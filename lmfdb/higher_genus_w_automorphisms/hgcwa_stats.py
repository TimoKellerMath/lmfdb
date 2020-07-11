# based on /lmfdb/elliptic_curves/ec_stats.py
# Authors: David Neill Asanza, Albert Ford, Ngi Nho, Jen Paulhus


import re
from flask import url_for
from lmfdb.app import app
from lmfdb import db
from sage.all import UniqueRepresentation, cached_method
from lmfdb.logger import make_logger

from lmfdb.utils import comma, display_knowl

logger = make_logger("hgcwa")


the_HGCWAstats = None

def get_stats():
    global the_HGCWAstats
    if the_HGCWAstats is None:
        the_HGCWAstats = HGCWAstats()
    return the_HGCWAstats

def max_group_order(group_list):
    orders = []
    for group in group_list:
        order = int(re.search(r'\[(\d+)', group).group(1))
        orders.append(order)
    return max(orders)

def hgcwa_summary():
    counts = get_stats().counts()
    refined_passports_knowl = display_knowl(
        'curve.highergenus.aut.refinedpassport', 
        title='refined passports')
    generating_vectors_knowl = display_knowl(
        'curve.highergenus.aut.generatingvector',
        title='generating vectors')
    stats_url = url_for('.statistics')
    return (
        r'Currently the database contains all groups $G$ acting as '
        r'automorphisms of curves $X/\C$ of genus %s to %s such that $X/G$ '
        r'has genus 0, as well as genus 2 through 4 with quotient genus '
        r'greater than 0. There are %s distinct %s in the database. The '
        r'number of distinct %s is %s. Here are some '
        r'<a href="%s">further statistics</a>.' % 
        (counts['genus_min'], counts['genus_max'], counts['distinct_refined_passports_c'],
         refined_passports_knowl, generating_vectors_knowl, 
         counts['distinct_generating_vectors_c'], stats_url)
    )

def hgcwa_stats_summary():
    counts = get_stats().counts()
    refined_passports_knowl = display_knowl(
        'curve.highergenus.aut.refinedpassport', 
        title='refined passports')
    generating_vectors_knowl = display_knowl(
        'curve.highergenus.aut.generatingvector',
        title='generating vectors')
    return (
        r'Currently the database contains all groups $G$ acting as '
        r'automorphisms of curves $X$ from genus %s up to genus %s so that '
        r'the quotient space $X/G$ is the Riemann sphere ($X/G$ has genus 0). '
        r'There are %s distinct %s in the database. The number of distinct '
        r'%s is %s. ' %
        (counts['genus_min'], counts['genus_max'], counts['distinct_refined_passports_c'], 
            refined_passports_knowl, generating_vectors_knowl,
            counts['distinct_generating_vectors_c'])
    )

@app.context_processor
def ctx_hgcwa_summaries():
    return {'hgcwa_summary': hgcwa_summary, 'hgcwa_stats_summary': hgcwa_stats_summary}


class HGCWAstats(UniqueRepresentation):
    """
    Class for creating and displaying statistics for higher genus curves with automorphisms
    """
    #TODO provide getter for subset of stats (e.g. for top matter)

    def __init__(self):
        logger.debug("Constructing an instance of HGCWAstats")
        self._counts = {}
        self._stats = {}

    def counts(self):
        self.init_hgcwa_count()
        return self._counts

    def stats(self):
        self.init_hgcwa_count()
        self.init_hgcwa_stats()
        return self._stats

    def init_hgcwa_count(self):
        if self._counts:
            return
        logger.debug("Computing HGCWA counts...")
        hgcwa = db.hgcwa_passports
        counts = {}

        genus_min = 2 
        genus_max = hgcwa.max('genus')
        dim_min = 0
        dim_max = hgcwa.max('dim')
        distinct_generating_vectors = hgcwa.count()
        distinct_refined_passports = len(hgcwa.distinct('passport_label'))

        counts['genus_min'] = genus_min
        counts['genus_max'] = genus_max
        counts['dim_min'] = dim_min
        counts['dim_max'] = dim_max
        counts['distinct_generating_vectors'] = distinct_generating_vectors
        counts['distinct_generating_vectors_c'] = comma(distinct_generating_vectors)
        counts['distinct_refined_passports'] = distinct_refined_passports
        counts['distinct_refined_passports_c'] = comma(distinct_refined_passports)

        self._counts  = counts
        logger.debug("... finished computing HGCWA counts.")

    def init_hgcwa_stats(self):
        if self._stats:
            return
        logger.debug("Computing HGCWA stats...")
        hgcwa = db.hgcwa_passports
        counts = self._counts
        stats = {}
        
        ##################################
        # Collect genus joint statistics #
        ##################################

        genus_detail = []
        for genus in range(counts['genus_min'], counts['genus_max'] + 1):
            families = len(hgcwa.distinct('label', {'genus':genus}))
            refined_passports = len(hgcwa.distinct('passport_label', {'genus':genus}))
            gen_vectors = hgcwa.count({'genus':genus})
            group_list = hgcwa.distinct('group', {'genus':genus})
            group_count = len(group_list)
            max_grp_order = max_group_order(group_list)
            genus_detail.append({'genus_num': genus, 'families': families,
                'refined_passports': refined_passports, 'gen_vectors': gen_vectors, 
                'groups': [group_count, max_grp_order]})
        stats['genus_detail'] = genus_detail

        ######################################
        # Collect dimension joint statistics #
        ######################################

        dim_detail = []
        for dim in range(counts['dim_min'], counts['dim_max'] + 1):
            gen_vectors = hgcwa.count({'dim':dim})
            dim_detail.append({'dim_num': dim, 'gen_vectors': gen_vectors })
        stats['dim_detail'] = dim_detail

        self._stats = stats
        logger.debug("... finished computing HGCWA stats.")        

