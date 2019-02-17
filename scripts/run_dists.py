import pkg_resources

from qer.dists import DistributionCollection, DistInfo, MetadataSources

dists = None


def setup():
    pass


def run_add_source():
    dists = DistributionCollection()
    info = DistInfo('a', pkg_resources.parse_version('1.0.0'), pkg_resources.parse_requirements(['b<1', 'c==2.0.0']))
    dists.add_dist(info, 'source')


def setup_build_constraints():
    global dists
    dists = DistributionCollection()
    info1 = DistInfo('a', pkg_resources.parse_version('1.0.0'), pkg_resources.parse_requirements(['b<1', 'c==2.0.0']))
    dists.add_dist(info1, 'source1')

    info2 = DistInfo('x', pkg_resources.parse_version('1.0.0'), pkg_resources.parse_requirements(['b>0.5']))
    dists.add_dist(info2, 'source2')

    info3 = DistInfo('y', pkg_resources.parse_version('1.0.0'), pkg_resources.parse_requirements(['b<2']))
    dists.add_dist(info3, 'source3')


def run_build_constraints():
    global dists
    dists.build_constraints('b')
