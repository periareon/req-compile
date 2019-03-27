import pkg_resources
from pkg_resources import Requirement

from qer.dists import DistributionCollection, DistInfo


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

    dists.add_dist(metadata, None, Requirement.parse('a[x1]<3.0'))
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
    metadata = DistInfo('a', '1.0.0', reqs=[])

    dists.add_dist('a', None, Requirement.parse('a[x]'))

    assert dists['a'].build_constraints() == Requirement.parse('a')
    assert dists['a[x]'].build_constraints() == Requirement.parse('a[x]')

    dists.add_dist(metadata, None, None)

    assert dists['a'].metadata.version == '1.0.0'
    assert dists['a[x]'].metadata.version == '1.0.0'

#
# def test_dist_with_unselected_extra():
#     dists = DistributionCollection()
#     dists.add_dist(DistInfo('aaa', '1.2.0', reqs=pkg_resources.parse_requirements(
#                                 ['bbb<1.0 ; extra=="x1"']
#                             ), extras=()), 'source_a')
#
#     assert str(dists.nodes['aaa'].metadata) == 'aaa==1.2.0'
#
#
# def test_add_remove_two_source_same_dist_different_extras():
#     dists = DistributionCollection()
#     dists.add_dist(DistInfo('aaa', '1.2.0',
#                             pkg_resources.parse_requirements(
#                                 ['bbb<1.0 ; extra=="x1"']
#                             ), extras=('x1',)), 'source_a')
#     dists.add_dist(DistInfo('aaa', '1.2.0',
#                             pkg_resources.parse_requirements(
#                                 ['bbb<1.0 ; extra=="x1"']
#                             )), 'source_b')
#     assert str(dists.nodes['aaa'].metadata) == 'aaa[x1]==1.2.0'
#     dists.remove_source('source_a')
#     assert str(dists.nodes['aaa'].metadata) == 'aaa==1.2.0'
#
#
# def test_add_remove_two_source_same_dist_different_extras2():
#     dists = DistributionCollection()
#     dists.add_dist(DistInfo('aaa', '1.2.0',
#                             pkg_resources.parse_requirements(
#                                 ['bbb<1.0 ; extra=="x1"']
#                             ), extras=('x1',)), 'source_a')
#     dists.add_dist(DistInfo('aaa', '1.2.0',
#                             pkg_resources.parse_requirements(
#                                 ['bbb<1.0 ; extra=="x1"']
#                             )), 'source_b')
#     assert str(dists.nodes['aaa'].metadata) == 'aaa[x1]==1.2.0'
#     dists.remove_source('source_b')
#     assert str(dists.nodes['aaa'].metadata) == 'aaa[x1]==1.2.0'
#
#
# def test_add_remove_source():
#     dists = DistributionCollection()
#     dists.add_dist(DistInfo('aaa', '1.2.0',
#                             pkg_resources.parse_requirements(
#                                 ['bbb<1.0']
#                             )), 'source_a')
#     dists.add_dist(DistInfo('xxx', '1.3.0',
#                             pkg_resources.parse_requirements(
#                                 ['bbb>0.1.0']
#                             )), 'source_b')
#     assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb>0.1.0,<1.0')
#     dists.remove_source('source_a')
#     assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb>0.1.0')
#
#
# def test_add_remove_two_source_same_dist():
#     dists = DistributionCollection()
#     dists.add_dist(DistInfo('aaa', '1.2.0',
#                             pkg_resources.parse_requirements(
#                                 ['bbb<1.0']
#                             )), 'source_a')
#     dists.add_dist(DistInfo('aaa', '1.2.0',
#                             pkg_resources.parse_requirements(
#                                 ['bbb<1.0']
#                             )), 'source_b')
#     assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb<1.0')
#     dists.remove_source('source_a')
#     assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb<1.0')
#
#
# def test_distinfo_requires():
#     distinfo = DistInfo('aaa', '1.2.0',
#                         pkg_resources.parse_requirements(
#                             ['bbb<1.0;extra=="bob"',
#                              'ccc'],
#                         ))
#
#     assert list(distinfo.requires()) == [pkg_resources.Requirement.parse('ccc')]
#
#
# def test_distinfo_requires_with_extra():
#     distinfo = DistInfo('aaa', '1.2.0',
#                         pkg_resources.parse_requirements(
#                             ['bbb<1.0;extra=="bob"',
#                              'ccc'],
#                         ))
#
#     assert set(distinfo.requires(extras=('bob',))) == {Requirement.parse('bbb<1.0; extra == "bob"'),
#                                                        Requirement.parse('ccc')}
#
#
# def test_distinfo_requires_cache_ok():
#     distinfo1 = DistInfo('aaa', '1.1.0',
#                          pkg_resources.parse_requirements(
#                              ['ccc'],
#                          ))
#     distinfo2 = DistInfo('aaa', '1.2.0',
#                          pkg_resources.parse_requirements(
#                              ['bbb<1.0;extra=="bob"',
#                               'ccc'],
#                          ))
#
#     assert list(distinfo1.requires()) == [pkg_resources.Requirement.parse('ccc')]
#     assert list(distinfo1.requires(extras=('bob',))) == [pkg_resources.Requirement.parse('ccc')]
#
#     assert set(distinfo2.requires(extras=('bob',))) == {Requirement.parse('bbb<1.0; extra == "bob"'),
#                                                         Requirement.parse('ccc')}
#     assert set(distinfo2.requires(extras=('unknown',))) == {Requirement.parse('ccc')}
