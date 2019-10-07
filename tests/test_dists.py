import pkg_resources
from pkg_resources import Requirement

from req_compile.dists import DistributionCollection, DistInfo


def test_unconstrained():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb']
                            )), None, Requirement.parse('aaa'))
    assert dists['bbb'].build_constraints() == pkg_resources.Requirement.parse('bbb')


def test_one_source():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), None, Requirement.parse('aaa'))
    assert dists['aaa'].build_constraints() == Requirement.parse('aaa')
    assert dists['bbb'].build_constraints() == Requirement.parse('bbb<1.0')


def test_two_sources():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), None, Requirement.parse('aaa'))
    dists.add_dist(DistInfo('ccc', '1.0.0',
                            pkg_resources.parse_requirements(
                                ['bbb>0.5']
                            )), None, Requirement.parse('ccc'))
    assert dists['bbb'].build_constraints() == pkg_resources.Requirement.parse('bbb>0.5,<1.0')


def test_two_sources_same():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), None, Requirement.parse('aaa'))
    dists.add_dist(DistInfo('ccc', '1.0.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), None, Requirement.parse('ccc'))
    assert dists['bbb'].build_constraints() == pkg_resources.Requirement.parse('bbb<1.0')


def test_add_remove_dist():
    dists = DistributionCollection()
    nodes = dists.add_dist(DistInfo('aaa', '1.2.0',
                                    pkg_resources.parse_requirements(
                                        ['bbb<1.0']
                                    )), None, Requirement.parse('aaa'))
    assert len(nodes) == 1
    dists.remove_dists(nodes)
    assert 'bbb' not in dists


def test_dist_with_unselected_extra():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0', reqs=pkg_resources.parse_requirements(
        ['bbb<1.0 ; extra=="x1"']
    )), None, None)

    assert str(dists.nodes['aaa'].metadata) == 'aaa==1.2.0'


def test_unnormalized_dist_with_extra():
    dists = DistributionCollection()
    metadata = DistInfo('A', '1.0.0', [])

    dists.add_dist(metadata, None, Requirement.parse('A[x]'))

    assert dists['A'].metadata.version == '1.0.0'
    assert dists['A[x]'].metadata.version == '1.0.0'


def test_metadata_violated():
    dists = DistributionCollection()
    metadata_a = DistInfo('a', '1.0.0', [])

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_a, None, Requirement.parse('a>1.0'))

    assert dists.nodes['a'].metadata is None


def test_metadata_violated_removes_transitive():
    dists = DistributionCollection()
    metadata_a = DistInfo('a', '1.0.0', reqs=pkg_resources.parse_requirements(['b']))

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_a, None, Requirement.parse('a>1.0'))

    assert dists['a'].metadata is None
    assert 'b' not in dists


def test_metadata_transitive_violated():
    dists = DistributionCollection()
    metadata_a = DistInfo('a', '1.0.0', [])
    metadata_b = DistInfo('b', '1.0.0', reqs=pkg_resources.parse_requirements(['a>1.0']))

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_b, None, None)

    assert dists.nodes['a'].metadata is None


# def test_repo_with_extra():
#     dists = DistributionCollection()
#     metadata_a = DistInfo('a', '1.0.0', [])
#     metadata_a_extra = DistInfo('a[extra]', '1.0.0', [])
#
#     dists.add_dist(metadata_a, None, None, repo=)
#     dists.add_dist(metadata_b, None, None)
