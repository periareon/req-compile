import os

from req_compile.containers import RequirementsFile


def test_gather_indices():
    """Verify all the parameters in the requirements files are found."""
    reqfile = RequirementsFile.from_file(
        os.path.join(os.path.dirname(__file__), "gather_indices", "requirements.in")
    )
    assert reqfile.parameters == [
        "--index-url",
        "https://tools/simple",
        "-e",
        "../../tool_project",
        "--extra-index-url",
        "https://tools/prebuilt/simple",
    ]
