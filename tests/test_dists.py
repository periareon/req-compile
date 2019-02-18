import pkg_resources
from pkg_resources import Requirement

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


def test_add_remove_dist():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), 'root')
    dists.remove_dist('aaa')
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb')


def test_dist_with_extras():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0', reqs=[], extras=('x1',)), 'source_a')
    dists.add_dist(DistInfo('aaa', '1.2.0', reqs=[], extras=('x2',)), 'source_b')

    assert str(dists.dists['aaa'].metadata) == 'aaa[x1,x2]==1.2.0'


def test_add_remove_source():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), 'source_a')
    dists.add_dist(DistInfo('xxx', '1.3.0',
                            pkg_resources.parse_requirements(
                                ['bbb>0.1.0']
                            )), 'source_b')
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb>0.1.0,<1.0')
    dists.remove_source('source_a')
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb>0.1.0')


def test_add_remove_two_source_same_dist():
    dists = DistributionCollection()
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), 'source_a')
    dists.add_dist(DistInfo('aaa', '1.2.0',
                            pkg_resources.parse_requirements(
                                ['bbb<1.0']
                            )), 'source_b')
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb<1.0')
    dists.remove_source('source_a')
    assert dists.build_constraints('bbb') == pkg_resources.Requirement.parse('bbb<1.0')


def test_distinfo_requires():
    distinfo = DistInfo('aaa', '1.2.0',
                        pkg_resources.parse_requirements(
                            ['bbb<1.0;extra=="bob"',
                             'ccc'],
                        ))

    assert list(distinfo.requires()) == [pkg_resources.Requirement.parse('ccc')]


def test_distinfo_requires_with_extra():
    distinfo = DistInfo('aaa', '1.2.0',
                        pkg_resources.parse_requirements(
                            ['bbb<1.0;extra=="bob"',
                             'ccc'],
                        ))

    assert set(distinfo.requires(extras=('bob',))) == {Requirement.parse('bbb<1.0; extra == "bob"'),
                                                       Requirement.parse('ccc')}


def test_distinfo_requires_cache_ok():
    distinfo1 = DistInfo('aaa', '1.1.0',
                         pkg_resources.parse_requirements(
                             ['ccc'],
                         ))
    distinfo2 = DistInfo('aaa', '1.2.0',
                         pkg_resources.parse_requirements(
                             ['bbb<1.0;extra=="bob"',
                              'ccc'],
                         ))

    assert list(distinfo1.requires()) == [pkg_resources.Requirement.parse('ccc')]
    assert list(distinfo1.requires(extras=('bob',))) == [pkg_resources.Requirement.parse('ccc')]

    assert set(distinfo2.requires(extras=('bob',))) == {Requirement.parse('bbb<1.0; extra == "bob"'),
                                                        Requirement.parse('ccc')}
    assert set(distinfo2.requires(extras=('unknown',))) == {Requirement.parse('ccc')}
