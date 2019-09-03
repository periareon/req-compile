import pkg_resources

from req_compile.dists import DistributionCollection, DistInfo

dists = None


def setup():
    pass


def run_add_source():
    dists = DistributionCollection()
    info = DistInfo('a', pkg_resources.parse_version('1.0.0'), pkg_resources.parse_requirements(['b<1', 'c==2.0.0']))
    dists.add_dist(info, None, None)


def setup_build_constraints():
    global dists
    dists = DistributionCollection()
    info1 = DistInfo('a', pkg_resources.parse_version('1.0.0'), pkg_resources.parse_requirements(['b<1', 'c==2.0.0']))
    dists.add_dist(info1, None, None)

    info2 = DistInfo('x', pkg_resources.parse_version('1.0.0'), pkg_resources.parse_requirements(['b>0.5']))
    dists.add_dist(info2, None, None)

    info3 = DistInfo('y', pkg_resources.parse_version('1.0.0'), pkg_resources.parse_requirements(['b<2']))
    dists.add_dist(info3, None, None)


def run_build_constraints():
    global dists
    result = dists['b'].build_constraints()
    return result
