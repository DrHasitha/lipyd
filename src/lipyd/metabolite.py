#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  This file is part of the `lipyd` python module
#
#  Copyright (c) 2015-2018 - EMBL
#
#  File author(s): Dénes Türei (turei.denes@gmail.com)
#
#  This code is not for public use.
#  Please do not redistribute.
#  For permission please contact me.
#
#  Website: http://www.ebi.ac.uk/~denes
#

from __future__ import generator_stop

from future.utils import iteritems
from past.builtins import xrange, range

import itertools
import collections
import operator
import functools

import numpy as np

import lipyd.formula as formula


class AbstractMetaboliteComponent(formula.Formula):
    
    def __init__(self,
                 core = 0.0,
                 charge = 0,
                 isotope = 0,
                 name = 'Unknown',
                 getname = lambda parent: parent.name,
                 **kwargs):
        """
        Represents a component of a molecule. It can be the basis of a core
        carrying more substituents. Or can be the basis of a substituent
        which might provide a custom set of options or a homolog series
        with different carbon counts and unsaturations on the aliphatic
        chain.
        
        :param core: You can provide the core (unchanged part) 3 ways:
            As a `float` which considered to be an exact mass.
            As a formula, e.g. `C2H5OH`.
            As a `dict` of atom counts, e.g. `{'C': 2, 'H': 6, 'O': 1}`.
        """
        
        formula.Mass.__init__(self,
            core if type(core) is not float else None,
            charge,
            isotope,
            **kwargs)
        
        if not self.has_mass():
            
            if type(core) is float:
                
                self.mass = core
                
            else:
                
                raise ValueError('Please provide either formula or '
                                'atom counts or mass.')
        
        self.name = name
        self.getname = getname


class AbstractMetabolite(AbstractMetaboliteComponent):
    
    def __init__(self,
            core = 0.0,
            charge = 0,
            isotope = 0,
            name = 'Unknown',
            getname = lambda parent, subs:
                '%s(%s)' % (
                    parent.name,
                    '/'.join(
                        s.cc_unsat_str
                        for s in subs
                        if hasattr(s, 'cc_unsat_str') and s.cc_unsat_str
                    )
                ),
            subs = [],
            sum_only = False,
            **kwargs
        ):
        """
        Represents a metabolite with an unchanged core and a set of variable
        substituents.
        
        :param bool sum_only: Do not iterate all aliphatic chains
            independently but consider only sum of chain lengths and
            unsaturations.
        """
        
        AbstractMetaboliteComponent.__init__(
            self,
            core,
            charge = charge,
            isotope = isotope,
            name = name,
            getname = getname,
            **kwargs
        )
        
        self.subs = subs
        self.sum_only = sum_only
        self.sub0 = None
    
    def __iter__(self):
        
        for subs, inst in self.subsproduct():
            
            yield inst
    
    @staticmethod
    def get_substituent(sub):
        """
        Creates a `Forula` object if the substituent is not
        already an instance of `Formula` or `Substituent`.
        """
        
        return (
                formula.Formula(sub)
            if hasattr(sub, 'lower') or type(sub) is float
                else formula.Formula(**sub)
            if type(sub) is dict
                else sub
        )
    
    def itersubs(self):
        """
        Iterates all combinations of all substituents.
        Yields tuples of substituents.
        """
        
        self._restore_sub0()
        
        for subs in itertools.product(*self.subs):
            
            yield subs
    
    def subsproduct(self):
        """
        Iterates instances and substituents in parallel.
        Yields tuples of two elements.
        First element is a tuple of all molecule parts (substituents).
        Second element is the actual instance, i.e. the whole molecule.
        """
        
        iterator = self.itersum() if self.sum_only else self.itersubs()
        
        for subs in iterator:
            
            self.inst_name = self.getname(self, subs)
            
            self.inst = functools.reduce(
                operator.add,
                itertools.chain([self], (s for s in subs))
            )
            self.inst.name = self.inst_name
            
            yield subs, self.inst
    
    def iterlines(self):
        """
        Iterates standard lines.
        """
        
        for subs, inst in self.subsproduct():
            
            identity = [self.name, inst.getname()]
            
            for sub in self.subs:
                
                if self.has_variable_aliphatic_chain(sub):
                    
                    identity.extend([
                        sub.get_prefix(),
                        sub.c,
                        sub.u
                    ])
            
            # TODO: do not assume here max 3 substituents with
            # variable aliphatic chain
            # as this is lipid specific
            identity.extend([np.nan] * (11 - len(identity)))
            
            yield inst.mass, tuple(identity)
    
    def itersum(self):
        """
        Iterates by consifering only the sum of chain lengths and
        unsaturations.
        """
        
        self._restore_sub0()
        
        chains = [
            (i, s.chlens, s.unsats)
            for i, s in enumerate(self.subs)
            if self.has_variable_aliphatic_chain(s)
        ]
        
        if len(chains) <= 1:
            
            for subs in self.itersubs():
                
                yield subs
            
            return
        
        min_chlens = sum(min(c[1]) for c in chains[1:])
        min_unsats = sum(min(c[2]) for c in chains[1:])
        sum_chlens = list(set(
            sum(cc) - min_chlens for cc in
            itertools.product(*(c[1] for c in chains))
        ))
        sum_unsats = list(set(
            sum(uu) - min_unsats for uu in
            itertools.product(*(c[2] for c in chains))
        ))
        
        self.sub0 = chains[0]
        isub0 = self.sub0[0]
        sub0 = self.subs[isub0]
        
        sub0.chlens = sum_chlens
        sub0.unsats = sum_unsats
        
        for subs in itertools.product(*(
                s.__iter__()
                if i == isub0 else
                # other substituents iterated by their cores only
                s.__iter__(cores_only = True)
                for i, s in enumerate(self.subs)
            )):
            
            yield subs
        
        # at the end restore the real values
        self._restore_sub0()
    
    def _restore_sub0(self):
        
        if self.sub0:
            
            self.subs[self.sub0[0]].chlens = self.sub0[1]
            self.subs[self.sub0[0]].unsats = self.sub0[2]
    
    def has_variable_aliphatic_chain(self, sub):
        
        return (
            hasattr(sub, 'variable_aliphatic_chain') and
            sub.variable_aliphatic_chain
        )


class AbstractSubstituent(AbstractMetaboliteComponent):
    
    def __init__(
            self,
            cores = [0.0],
            c = (0, 1),
            u = (0, 1),
            counts = {},
            charges = [0],
            isotopes = [0],
            names = ['Unknown'],
            getname = lambda parent: '%u:%u' % (parent.c, parent.u),
            c_u_diff = lambda c, u: c > u + 1,
            prefix = '',
            even = False,
            **kwargs
        ):
        """
        Represents a set of distinct substituent parts in a molecule or
        a homolog series spanning accross a range of aliphatic chain
        length and unsaturated bonds.
        
        :param list cores: List of core variations. Same kind of definitions
            are possible like at `formula.Formula`: formula as `str`, `dict` of
            atoms or exact mass as `float`.
        :param tuple c: Tuple of 2 integers: range of chain lengths.
        :param tuple u: Tuple of 2 integers: range of unsaturations.
        :param list counts: Dictionary with extra atom counts.
            If you have one or more extra oxygen, nitrogen, phosphorous or
            any other atoms in the compound you can include here.
            Alternatively you can also include them in the core.
            Also accounts for the valences of the aliphatic chain
            not occupied by hydrogens. E.g. for a fatty acyl you need to
            remove 3 hydrogens as 3 valences are occupied by the oxygens.
            If you have a secondary amine you need to remove one more
            hydrogen. Otherwise, as this data structure has no information
            about constitution, we could not guess the number of hydrogens.
            Similarly, for oxo groups removal of 2 hydrogens necessary.
        :param list charges: List of integers: charges for each core
            variation.
        :param list isotopes: List of integers: extra neutrons for each core
            variation.
        :param getname: Method (callable) to create a name from the chain
            length and the unsaturation.
        :param c_u_diff: Method (callable) to decide if the chain length and
            unsaturation are compatible. E.g. if chain length is only C2, an
            unsaturation of 4 double bonds is not possible. By default, chain
            length must be greater by 2 than unsaturation, it means at acyl
            chains we avoid to assume double bond right next to the carboxyl
            group which is clearly impossible.
        :param bool even: If true only even chain lengths are considered.
        """
        
        self.prefix   = prefix
        self.c_u_diff = c_u_diff
        self.even     = even
        self.getname  = getname
        self.cores    = cores if type(cores) is list else [cores]
        self.charges  = charges if type(charges) is list else [charges]
        self.isotopes = isotopes if type(isotopes) is list else [isotopes]
        self.names    = names if type(names) is list else [names]
        self.counts   = collections.defaultdict(lambda: 0)
        self.counts.update(counts)
        
        AbstractMetaboliteComponent.__init__(
            self,
            self.cores[0],
            charge = self.charges[0],
            isotope = self.isotopes[0],
            name = self.names[0],
            getname = getname,
            **kwargs
        )
        
        # range of possible lengths and unsats
        self.set_chlens(c)
        self.set_unsats(u)
        
        # current value of length and unsat
        self.c = self.chlens[0]
        self.u = self.unsats[0]
        
        self.total = len(self.chlens) * len(self.unsats)
        self.variable_aliphatic_chain = (
            not (
                len(self.chlens) == 1 and
                self.chlens[0] == 0
            )
        )
    
    def __iter__(self, cores_only = False):
        
        for i in range(len(self.cores)):
            
            self.update_core(i)
            
            for c in self.chlens:
                
                self.c = c
                
                for u in self.unsats:
                    
                    self.u = u
                    
                    if not self.c_u_diff(self.c, self.u):
                        
                        continue
                    
                    # implicit hydrogens
                    h = c * 2 + 1 - 2 * u
                    p = self.get_prefix()
                    new_counts = self.counts.copy()
                    new_counts['C'] += c
                    new_counts['H'] += h
                    
                    new = self + formula.Formula(**new_counts)
                    name = self.getname(self)
                    
                    new.name = name
                    new.c = c
                    new.u = u
                    new.get_prefix = lambda: p
                    new.variable_aliphatic_chain = self.variable_aliphatic_chain
                    
                    new.cc_unsat_str = new.name if self.total > 1 else None
                    
                    yield new
                    
                    if cores_only:
                        
                        break
                
                if cores_only:
                    
                    break
    
    def set_chlens(self, c):
        
        self.chlens = (
            c if type(c) is list
            else [
                i for i in
                range(c[0], c[1] + 1)
                if not self.even or i % 2 == 0
            ]
        )
    
    def set_unsats(self, u):
        
        self.unsats = (
            u if type(u) is list
            else list(range(u[0], u[1] + 1))
        )
    
    def update_core(self, i = 0):
        
        try:
            new = self.cores[i]
        
        except:
            raise IndexError('Number of cores is less than %u' % i + 1)
        
        if type(new) is float:
            
            self.mass = new
            self.formula = ''
            
        elif type(new) is dict:
            
            self.formula_from_dict(new)
            
        elif hasattr(new, 'lower'):
            
            self.formula = new
            
        else:
            
            raise ValueError('Wrong mass or formula: `%s`' % str(new))
        
        self.charge = self.charges[i]
        self.isotope = self.isotopes[i]
        self.name = self.names[i]
        
        self.reset_atoms()
        self.calc_mass()
    
    def get_prefix(self):
        
        return self.prefix
