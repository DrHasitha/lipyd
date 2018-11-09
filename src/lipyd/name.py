#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  This file is part of the `lipyd` python module
#
#  Copyright (c) 2015-2018 - EMBL
#
#  File author(s): Dénes Türei (turei.denes@gmail.com)
#
#  Distributed under the GNU GPLv3 License.
#  See accompanying file LICENSE.txt or copy at
#      http://www.gnu.org/licenses/gpl-3.0.html
#
#  Website: http://www.ebi.ac.uk/~denes
#

from __future__ import print_function
from past.builtins import xrange, range, reduce

from future.utils import iteritems

import sys
import imp
import re
import itertools

import lipyd.settings as settings
import lipyd.lipproc as lipproc


class LipidNameProcessor(object):
    
    def __init__(
            self,
            database = 'swisslipids',
            with_alcohols = True,
            with_coa = True,
            iso = False
        ):
        """
        Processes lipid names used in databases. Converts names to the
        standard used in this module and extracts carbon count and
        unsaturation information and other features.
        """
        
        self.database = database.lower()
        self.with_alcohols = with_alcohols
        self.with_coa = with_coa
        self.iso = iso
        self.lipnamesf = settings.get('lipnamesf')
        self.adducts_constraints = settings.get('adducts_constraints')
        
        self.gen_fa_greek()
        self.read_lipid_names()
    
    def reload(self, children = False):
        
        modname = self.__class__.__module__
        mod = __import__(modname, fromlist=[modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)
    
    def read_lipid_names(self, add_fa = True):
        """
        Reads annotations for lipid classes:
        - full names
        - short notations
        - database keywords
        (to process long names from SwissLipids and LipidMaps)
        - most abundant adducts
        
        The input file is given by the ``lipnamesf`` attribute.
        """
        result = {}
        
        with open(self.lipnamesf, 'r') as fp:
            
            hdr = True
            
            for l in fp:
                
                if l[0] == '#':
                    continue
                
                if hdr:
                    hdr = False
                    continue
                
                l = l.strip().split('\t')
                
                lip = (
                    tuple(l[1].split(';')) if l[1] else (),
                    l[0],
                    tuple(l[2].split(';')) if l[2] else ()
                )
                
                result[lip] = {
                    'full_name': l[4],
                    'swl': self.process_db_keywords(l[5]),
                    'lmp': self.process_db_keywords(l[6]),
                    'pos_adduct': (
                            l[7]
                        if l[7] != 'ND' and self.adducts_constraints else
                            None
                        ),
                    'neg_adduct': (
                            l[8]
                        if l[8] != 'ND' and self.adducts_constraints else
                            None
                        ),
                    'chains': tuple(l[3].split(';')) if l[3] else ()
                }
        
        self.lipnames = result
    
    @staticmethod
    def process_db_keywords(kwdstr):
        
        return \
            list(
                map(
                    lambda kwdset:
                        {
                            'neg':
                                list(
                                    map(
                                        lambda kwd:
                                            kwd[1:],
                                        list(
                                            filter(
                                                lambda kwd:
                                                    len(kwd) and \
                                                    kwd[0] == '!',
                                                kwdset.split(';')
                                            )
                                        )
                                    )
                                ),
                            'pos':
                                list(
                                    filter(
                                        lambda kwd:
                                            len(kwd) and kwd[0] != '!',
                                        kwdset.split(';')
                                    )
                                )
                        },
                    kwdstr.split('|')
                )
            )
    
    @staticmethod
    def has_sph_prefix(match):
        
        return match[0] in {'t', 'd', 'k', 'DH'}
    
    @staticmethod
    def is_ether(match):
        
        return match[0] in {'O', 'P'}
    
    @classmethod
    def attr_proc(cls, match, u = None):
        
        sph = match[0] if cls.has_sph_prefix(match) else ''
        
        if u == 0 and sph == 'd':
            
            sph = 'DH'
        
        return lipproc.ChainAttr(
            sph = sph,
            ether = cls.is_ether(match),
            oh = (match[-1],) if match[-1] else ()
        )
    
    @staticmethod
    def get_type(
            i,
            sphingo = False,
            ether = False,
            types = None,
            chainsexp = None
        ):
        
        # TODO: this does not feel perfect
        # some better heuristic should replace
        return (
            types[i]
                if types else
            'Sph'
                if sphingo and i == 0 else
            'FAL'
                if ether else
            chainsexp[i]
                if chainsexp and len(chainsexp) > i else
            'FA'
        )
    
    def attrs_types(self, cc1, chainsexp):
        
        sph    = cc1[0] if self.has_sph_prefix(cc1) else ''
        ether  = self.is_ether(cc1)
        fa1    = min(
            (i for i, c in enumerate(chainsexp) if c in {'FA', 'FAL'}),
            default = None
        )
        hasfal = 'FAL' in chainsexp
        oh     = (cc1[-1],) if cc1[-1] else ()
        
        chainsexp = tuple(
            'FAL'
                if not hasfal and ether and i == fa1 else
            c
                for i, c in enumerate(chainsexp)
        )
        
        attrs  = tuple(
            lipproc.ChainAttr(
                sph = sph if c == 'Sph' else '',
                ether = ether and c == 'FAL',
                # here have no idea which chain carries OHs
                # hence we add them to the last chain
                oh = oh if i == len(chainsexp) - 1 else ()
            )
            for i, c in enumerate(chainsexp)
        )
        
        return attrs, chainsexp
    
    def carbon_counts(
            self,
            name,
            ccexp = 2,
            chainsexp = None,
            sphingo = False,
            iso = False,
            types = None
        ):
        """
        Processes carbon and unsaturation counts from name.
        
        Args
        ----
        :param str name:
            Lipid name.
        :param int ccexp:
            Expected number of fatty acyl or other residues constaining
            aliphatic chain. E.g. for DAG this should be 2 and for TAG 3
            as the latter has 3 fatty acyls.
        :param tuple chainsexp:
            The type of the expected chains, e.g. `('Sph', 'FA')` for one
            sphingosine and a fatty acyl. This matters only if the chain
            types can not be inferred from the processed names.
        :param bool sphingo:
            Is this a sphingolipid, is the first chain a sphingosine base?
        :param bool iso:
            Process conformation isomer details for example 18:2(9E,11Z).
        :param tuple types:
            Explicit types for each chains.
        """
        
        # number of groups in one regex match unit
        _g = 5 if iso else 4
        _i = 3
        rechain = lipproc.rechainiso if iso else lipproc.rechain
        
        # regex finds the total carbon count
        cc1 = lipproc.rechainsum.search(name)
        cc1 = cc1.groups() if cc1 else cc1
        # regex finds 1-4 fatty acids
        cc2 = rechain.search(name)
        cc2 = cc2.groups() if cc2 else cc2
        
        chains = []
        
        if (
            ccexp and
            cc2 #and
            #cc2[(ccexp - 1) * _g + 1] and
            #cc2[(ccexp - 1) * _g + 2]
        ):
            
            for i in xrange(len(cc2) // _g):
                
                if cc2[i * _g + 1] and cc2[i * _g + 2]:
                    
                    c = int(cc2[i * _g + 1])
                    u = int(cc2[i * _g + 2])
                    attr = self.attr_proc(cc2[i * _g:i * _g + _g], u)
                    sphingo = sphingo or bool(attr.sph)
                    
                    chains.append(lipproc.Chain(
                        c = c,
                        u = u,
                        attr = attr,
                        typ = self.get_type(
                            i, sphingo, attr.ether, types, chainsexp
                        ),
                        iso = (
                            tuple(cc2[i * _g + _i].split(','))
                                if iso and cc2[i * _g + _i] else
                            ()
                        )
                    ))
            
            zerochains = sum(not c.c for c in chains)
            # ccexp = ccexp - zerochains
            chains = tuple(c for c in chains if c.c)
            chains = [] if len(chains) != ccexp else tuple(chains)
        
        # the total carbon count
        if chains:
            
            chainsum = lipproc.sum_chains(chains)
            
        elif cc1:
            
            c = int(cc1[1])
            u = int(cc1[2])
            
            if not chainsexp:
                
                attrs = (self.attr_proc(cc1, u),)
                types = ()
                
            else:
                attrs, types = self.attrs_types(cc1, chainsexp)
            
            chainsum = lipproc.ChainSummary(
                c = c,
                u = u,
                attr = attrs,
                typ  = types,
            )
            
        else:
            
            chainsum = None
        
        return chainsum, chains
    
    def isomeric_carbon_counts(
            self,
            name,
            ccexp = 2,
            sphingo = False,
            types = None
        ):
        """
        Calls `carbon_counts` with `iso=True`.
        """
        
        return self.carbon_counts(
            name,
            ccexp = ccexp,
            phingo = sphingo,
            iso = True,
            types = types
        )
    
    def headgroup_from_lipid_name(self, names, database = None):
        """
        For one database record attempts to identify the lipid class
        by looking up keywords.
        Calls greek name identification, greek fatty acid names are
        identified as 'FA'.
        
        Returns tuple of `lipproc.Headgroup` object and expected chain types.
        """
        
        database = database or self.database
        
        names = '|'.join(names)
        
        db = 'lmp' if database.lower() == 'lipidmaps' else 'swl'
        for lipclass, spec in iteritems(self.lipnames):
            for kwset in spec[db]:
                matched = [kw in names for kw in kwset['pos']]
                if sum(matched) == len(kwset['pos']) and \
                    sum(matched) > 0:
                    matched = [kw in names for kw in kwset['neg']]
                    if sum(matched) == 0:
                        return (
                            lipproc.Headgroup(
                                main = lipclass[1], # main class, e.g. Cer
                                sub  = lipclass[0]  # subclass, e.g. Hex
                            ),
                            spec['chains']
                        )
        
        fa_name = self.process_fa_name(names)
        
        if fa_name:
            
            return (lipproc.Headgroup(main = fa_name), (fa_name,))
        
        return None, None
    
    def process_fa_name(self, name):
        """
        Identifies fatty acids based on their greek name.
        """
        
        return (
            'FA'
                if name in self.fa_greek
                or 'FA' in name
                or 'atty acid' in name
            else 'FAL'
                if self.with_alcohols and (
                    name in self.fal_greek or
                    'atty alcohol' in name
                )
            else 'FACoA'
                # TODO: capture carbon counts of acyl-CoAs
                if self.with_coa and (
                    name in self.facoa_greek or
                    'oyl-CoA' in name
                )
            else None
        )
    
    def fa_greek_cc(self, name):
        
        chainsum, chains = None, None
        
        try:
            
            name1 = name.split('-')[1] if '-' in name else name
            
            for typ in {'FA', 'FAL', 'FACoA'}:
                
                if name1 in getattr(self, '%s_greek' % typ.lower()):
                    
                    cc1 = getattr(self, '%s_greek' % typ.lower())[name1]
                    iso = (
                        tuple(name.split(')')[0][1:].split(','))
                            if self.iso and '(' in name else
                        ()
                    )
                    chains   = [lipproc.Chain(
                        c = cc1[0],
                        u = cc1[1],
                        typ = typ,
                        iso = iso
                    )]
                    chainsum = lipproc.sum_chains(chains)
        
        except:
            pass
        
        return chainsum, chains
    
    def test_branched(self, name):
        """
        Tells if a lipid might contain branched aliphatic chains.
        """
        
        return bool(self.reme.search(name))
    
    def process(self, names, database = None):
        """
        The main method of this class. Processes a lipid name string
        and returns a standard name, prefix, carbon counts and
        unsaturations.
        
        Args
        ----
        :param list names:
            One or more names to process. Single result will be returned
            and names will be attempted to be processed one after the other
            until processing is successful.
        """
        
        if hasattr(names, 'lower'):
            # ok, if one passes a string let us still process it
            names = (names,)
        
        database = database or self.database
        
        hg, chainsum, chains, chainsiso, chainsexp = (
            None, None, None, None, None
        )
        
        hg, chainsexp = self.headgroup_from_lipid_name(
            names, database = database
        )
        
        # try greek fatty acyl carbon counts:
        if not hg and self.iso and database == 'swisslipids':
            
            try:
                
                for name0 in names:
                    
                    fa_greek = name0.split('-')
                    
                    if len(fa_greek) > 1:
                        
                        hg = self.process_fa_name(fa_greek[1])
                        
                        if hg:
                            
                            hg = lipproc.Headgroup(main = fa_name)
                            chainsexp = (fa_name,)
                            break
                
            except:
                
                pass
        
        for n in names:
            
            lyso =  hg and 'Lyso' in hg.sub
            
            # how many aliphatic chains this molecule has
            ccexp = (
                    2
                if not hg else
                    1
                if hg.main in {'FA', 'MAG'} or lyso else
                    3
                if hg.main == 'TAG' else
                    2
            )
            
            _chainsum, _chains = self.carbon_counts(
                n, ccexp = ccexp, chainsexp = chainsexp, iso = self.iso
            )
            
            chains = chains or _chains
            chainsum = chainsum or _chainsum
            
            if self.iso and _chains and any(c.iso for c in _chains):
                
                chains = _chains
            
            if (
                chainsum and chains and (
                    not self.iso or
                    any(c.iso for c in chains)
                )
            ):
                
                break
        
        if hg and hg.main in {'FA', 'FAL', 'FACoA'} and not chainsum:
            
            for name0 in names:
                
                chainsum, chains = self.fa_greek_cc(name0)
                
                if chainsum:
                    
                    break
        
        return hg, chainsum, chains
    
    def gen_fa_greek(self):
        """
        Generates a list of greek fatty acid names with their
        carbon counts and unsaturations.
        """
        
        fa_greek_parts = {
            'cc': {
                'hex': 6,
                'hept': 7,
                'oct': 8,
                'non': 9,
                'dec': 10,
                'undec': 11,
                'dodec': 12,
                'tridec': 13,
                'tetradec': 14,
                'pentadec': 15,
                'hexadec': 16,
                'heptadec': 17,
                'octadec': 18,
                'nonadec': 19,
                'eicos': 20,
                'icos': 20,
                'heneicos': 21,
                'docos': 22,
                'tricos': 23,
                'tetracos': 24,
                'pentacos': 25,
                'hexacos': 26,
                'heptacos': 27,
                'octacos': 28,
                'nonacos': 29,
                'triacont': 30
            },
            'uns': {
                '': 1,
                'adi': 2,
                'atri': 3,
                'atetra': 4,
                'apenta': 5,
                'ahexa': 6,
                'ahepta': 7,
                'aocta': 8
            },
            'end': {
                'enoate': 1,
                'anoate': 0,
                'enoic acid': 1,
                'anoic acid': 0
            }
        }
        
        fal_greek_end = {}
        fal_greek_end['anol'] = 0
        fal_greek_end['enol'] = 1
        
        facoa_greek_end = {}
        facoa_greek_end['anoyl-CoA'] = 0
        facoa_greek_end['enoyl-CoA'] = 1
        
        self.fa_greek  = {}
        self.fal_greek = {}
        self.facoa_greek = {}
        
        for cc, uns, end in itertools.product(
            fa_greek_parts['cc'].items(),
            fa_greek_parts['uns'].items(),
            fa_greek_parts['end'].items()):
            
            if len(uns[0]) and end[1] == 0:
                continue
            
            self.fa_greek['%s%s%s' % (cc[0], uns[0], end[0])] = (cc[1], uns[1] * end[1])
        
        for cc, uns, end in itertools.product(
            fa_greek_parts['cc'].items(),
            fa_greek_parts['uns'].items(),
            fal_greek_end.items()):
            
            if len(uns[0]) and end[1] == 0:
                continue
            
            self.fal_greek['%s%s%s' % (cc[0], uns[0], end[0])] = (cc[1], uns[1] * end[1])
        
        for cc, uns, end in itertools.product(
            fa_greek_parts['cc'].items(),
            fa_greek_parts['uns'].items(),
            facoa_greek_end.items()):
            
            if len(uns[0]) and end[1] == 0:
                continue
            
            self.facoa_greek['%s%s%s' % (cc[0], uns[0], end[0])] = (cc[1], uns[1] * end[1])