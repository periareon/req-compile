from pkg_resources import Requirement

from req_compile.utils import merge_requirements


def test_combine_reqs_conditions_and_markers():
    req1 = Requirement.parse('pylint<2;platform_system=="Windows"')
    req2 = Requirement.parse('pylint>1;python_version<"3.0"')

    assert merge_requirements(req1, req2) == Requirement.parse("pylint>1,<2")


def test_combine_no_specs():
    req1 = Requirement.parse("pylint")
    req2 = Requirement.parse('pylint;python_version<"3.0"')

    assert merge_requirements(req1, req2) == Requirement.parse("pylint")


def test_combine_dup_specs():
    req1 = Requirement.parse("pylint==1.0.1")
    req2 = Requirement.parse('pylint==1.0.1;python_version<"3.0"')

    assert merge_requirements(req1, req2) == Requirement.parse("pylint==1.0.1")


def test_combine_multiple_specs():
    req1 = Requirement.parse("pylint~=3.1")
    req2 = Requirement.parse("pylint>2,>3")

    assert merge_requirements(req1, req2) == Requirement.parse("pylint~=3.1,>2,>3")


def test_combine_extra_with_no_extra():
    req1 = Requirement.parse("fuzzywuzzy")
    req2 = Requirement.parse("fuzzywuzzy[speedup]")

    assert merge_requirements(req1, req2) == Requirement.parse("fuzzywuzzy[speedup]")


def test_combine_extra_with_extra():
    req1 = Requirement.parse("fuzzywuzzy[slowdown]")
    req2 = Requirement.parse("fuzzywuzzy[speedup]")

    assert merge_requirements(req1, req2) == Requirement.parse(
        "fuzzywuzzy[slowdown,speedup]"
    )


def test_combine_extras_sorted():
    req1 = Requirement.parse("x[b]")
    req2 = Requirement.parse("x[a]")

    assert merge_requirements(req1, req2) == Requirement.parse("x[a,b]")


def test_combine_extras_same():
    req1 = Requirement.parse("x[a]")
    req2 = Requirement.parse("x[a]")

    assert merge_requirements(req1, req2) == Requirement.parse("x[a]")


def test_combine_identical_reqs():
    req1 = Requirement.parse("pylint>=3.1")
    req2 = Requirement.parse("pylint>=3.1")

    assert merge_requirements(req1, req2) == Requirement.parse("pylint>=3.1")


def test_combine_diff_specs_identical_markers():
    req1 = Requirement.parse('pylint>=3.1; python_version>"3.0"')
    req2 = Requirement.parse('pylint>=3.2; python_version>"3.0"')

    assert merge_requirements(req1, req2) == Requirement.parse(
        'pylint>=3.1,>=3.2; python_version>"3.0"'
    )


def test_combine_and_compare_identical_reqs():
    req1 = Requirement.parse("pylint>=3.1")
    req2 = Requirement.parse("pylint>=3.1")

    assert merge_requirements(req1, req2) == req1


def test_combine_with_extras_markers():
    req1 = Requirement.parse('pylint; extra=="test"')
    req2 = Requirement.parse('pylint; python_version>"3.0" and extra=="test"')

    result = merge_requirements(req1, req2)
    assert result == Requirement.parse('pylint; extra=="test"')
