from packaging.requirements import Requirement

from req_compile.utils import merge_requirements


def test_combine_reqs_conditions_and_markers():
    req1 = Requirement('pylint<2;platform_system=="Windows"')
    req2 = Requirement('pylint>1;python_version<"3.0"')

    assert merge_requirements(req1, req2) == Requirement("pylint>1,<2")


def test_combine_no_specs():
    req1 = Requirement("pylint")
    req2 = Requirement('pylint;python_version<"3.0"')

    assert merge_requirements(req1, req2) == Requirement("pylint")


def test_combine_dup_specs():
    req1 = Requirement("pylint==1.0.1")
    req2 = Requirement('pylint==1.0.1;python_version<"3.0"')

    assert merge_requirements(req1, req2) == Requirement("pylint==1.0.1")


def test_combine_multiple_specs():
    req1 = Requirement("pylint~=3.1")
    req2 = Requirement("pylint>2,>3")

    assert merge_requirements(req1, req2) == Requirement("pylint~=3.1,>2,>3")


def test_combine_extra_with_no_extra():
    req1 = Requirement("fuzzywuzzy")
    req2 = Requirement("fuzzywuzzy[speedup]")

    assert merge_requirements(req1, req2) == Requirement("fuzzywuzzy[speedup]")


def test_combine_extra_with_extra():
    req1 = Requirement("fuzzywuzzy[slowdown]")
    req2 = Requirement("fuzzywuzzy[speedup]")

    assert merge_requirements(req1, req2) == Requirement(
        "fuzzywuzzy[slowdown,speedup]"
    )


def test_combine_extras_sorted():
    req1 = Requirement("x[b]")
    req2 = Requirement("x[a]")

    assert merge_requirements(req1, req2) == Requirement("x[a,b]")


def test_combine_extras_same():
    req1 = Requirement("x[a]")
    req2 = Requirement("x[a]")

    assert merge_requirements(req1, req2) == Requirement("x[a]")


def test_combine_identical_reqs():
    req1 = Requirement("pylint>=3.1")
    req2 = Requirement("pylint>=3.1")

    assert merge_requirements(req1, req2) == Requirement("pylint>=3.1")


def test_combine_diff_specs_identical_markers():
    req1 = Requirement('pylint>=3.1; python_version>"3.0"')
    req2 = Requirement('pylint>=3.2; python_version>"3.0"')

    assert merge_requirements(req1, req2) == Requirement(
        'pylint>=3.1,>=3.2; python_version>"3.0"'
    )


def test_combine_and_compare_identical_reqs():
    req1 = Requirement("pylint>=3.1")
    req2 = Requirement("pylint>=3.1")

    assert merge_requirements(req1, req2) == req1


def test_combine_with_extras_markers():
    req1 = Requirement('pylint; extra=="test"')
    req2 = Requirement('pylint; python_version>"3.0" and extra=="test"')

    result = merge_requirements(req1, req2)
    assert result == Requirement('pylint; extra=="test"')
