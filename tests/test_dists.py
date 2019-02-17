import pkg_resources

from qer.dists import DistributionCollection, DistInfo


def test_unconstrained():
    dists = DistributionCollection()
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb')


def test_one_source():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), 'root')
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb<1.0')


def test_two_sources():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), 'root')
    dists.add_dist(DistInfo('ccc', '1.0.0',
                            pkg_resources.parse_requirements(
                                ['bbb>0.5']
                            )), 'root')
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb>0.5,<1.0')


def test_two_sources_same():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), 'root')
    dists.add_dist(DistInfo('ccc', '1.0.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), 'root')
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb<1.0')


def test_add_remove_source():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), 'root')
    dists.remove_dist('aaa')
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb')
