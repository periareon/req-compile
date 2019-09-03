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


def test_dist_with_two_extras():
    dists = DistributionCollection()
    metadata = DistInfo('a', '1.0.0', reqs=pkg_resources.parse_requirements(
                                ['b ; extra=="x1"',
                                 'c ; extra=="x2"'],
                            ))

    recurse = dists.add_dist(metadata, None, Requirement.parse('a[x1]<3.0'))
    assert recurse == {dists['a'], dists['a[x1]']}

    dists.add_dist(metadata, None, Requirement.parse('a[x2]>=1.0'))

    assert dists['a'].build_constraints() == Requirement.parse('a>=1.0,<3.0')
    # We don't expect any constraints on the extras themselves
    assert dists['a[x1]'].build_constraints() == Requirement.parse('a[x1]')
    assert dists['a[x2]'].build_constraints() == Requirement.parse('a[x2]')

    assert {dep.key for dep in dists['a'].dependencies} == set()
    assert {dep.key for dep in dists['a[x1]'].dependencies} == {'a', 'b'}
    assert {dep.key for dep in dists['a[x2]'].dependencies} == {'a', 'c'}

def test_dist_with_extra_metadata_later():
    dists = DistributionCollection()
    metadata = DistInfo('a', '1.0.0', reqs=pkg_resources.parse_requirements(
                                ['b ; extra=="x1"',
                                 'c ; extra=="x2"'],
                            ))

    dists.add_dist('a', None, Requirement.parse('a[x1]'))

    assert dists['a'].build_constraints() == Requirement.parse('a')
    assert dists['a[x1]'].build_constraints() == Requirement.parse('a[x1]')

    dists.add_dist(metadata, None, None)

    assert {dep.key for dep in dists['a'].dependencies} == set()
    assert {dep.key for dep in dists['a[x1]'].dependencies} == {'a', 'b'}


def test_metadata_is_mirror_with_extra():
    dists = DistributionCollection()
    metadata = DistInfo('a', '1.0.0', [])

    dists.add_dist('a', None, Requirement.parse('a[x]'))

    assert dists['a'].build_constraints() == Requirement.parse('a')
    assert dists['a[x]'].build_constraints() == Requirement.parse('a[x]')

    dists.add_dist(metadata, None, None)

    assert dists['a'].metadata.version == '1.0.0'
    assert dists['a[x]'].metadata.version == '1.0.0'


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


def test_add_remove_two_source_same_dist_different_extras():
    dists = DistributionCollection()

    nx1 = DistInfo('a', '1.0',
                   pkg_resources.parse_requirements(
                       ['aaa[x1]']))
    nx2 = DistInfo('b', '1.0',
                   pkg_resources.parse_requirements(
                       ['aaa[x2]']))

    aaa = DistInfo('aaa', '1.2.0',
                   pkg_resources.parse_requirements(
                       ['bbb<1.0 ; extra=="x1"',
                        'ccc>3.0 ; extra=="x2"']))

    nx1_node = list(dists.add_dist(nx1, None, None))[0]
    nx2_node = list(dists.add_dist(nx2, None, None))[0]
    dists.add_dist('aaa', nx1_node, Requirement.parse('aaa[x1]'))
    dists.add_dist('aaa', nx2_node, Requirement.parse('aaa[x2]'))

    assert 'bbb' not in dists
    assert 'ccc' not in dists

    assert dists['aaa'].metadata is None

    dists.add_dist(aaa, nx1_node, Requirement.parse('aaa[x1]'))

    assert str(dists['aaa'].metadata) == 'aaa==1.2.0'
    assert str(dists['aaa[x1]'].metadata) == 'aaa==1.2.0'
    assert str(dists['aaa[x2]'].metadata) == 'aaa==1.2.0'
    assert 'bbb' in dists
    assert 'ccc' in dists

    dists.remove_dists(nx1_node)

    assert str(dists['aaa'].metadata) == 'aaa==1.2.0'
    assert str(dists['aaa[x2]'].metadata) == 'aaa==1.2.0'
    assert 'ccc' in dists
    assert 'aaa[x1]' not in dists
    assert 'bbb' not in dists

    dists.remove_dists(nx2_node)

    assert 'aaa' not in dists
    assert 'aaa[x1]' not in dists
    assert 'aaa[x2]' not in dists
    assert 'bbb' not in dists
    assert 'ccc' not in dists


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
