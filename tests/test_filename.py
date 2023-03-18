import pkg_resources
import pytest


import req_compile.filename


@pytest.mark.parametrize(
    "filename,result_name,result_version",
    [
        ["post-2.3.1-2.tar.gz", "post", "2.3.1-2"],
        ["pytest-ui-0.3b0.linux-x86_64.tar.gz", "pytest-ui", "0.3beta0"],
        ["backports-thing-1.0.1.tar.gz", "backports-thing", "1.0.1"],
        ["backports-thing-1.0.1.tar.gz", "backports-thing", "1.0.1"],
        ["project-v1.0.tar.gz", "project", "1.0"],
        ["pyvmomi-5.5.0.2014.1.1.tar.gz", "pyvmomi", "5.5.0.2014.1.1"],
        ["pyvmomi-5.5.0-2014.1.1.tar.gz", "pyvmomi", None],
        ["python-project-3-0.0.1.tar.gz", "python-project-3", "0.0.1"],
        ["python-project-v2-0.1.1.tar.gz", "python-project-v2", "0.1.1"],
        ["divisor-1.0.0s-1.0.0.zip", "divisor-1.0.0s", "1.0.0"],
        [
            "django-1.6-fine-uploader-0.2.0.3.tar.gz",
            "django-1.6-fine-uploader",
            "0.2.0.3",
        ],
        ["selenium-2.0-dev-9429.tar.gz", "selenium", "2.0-dev-9429"],
        ["django-ajax-forms_0.3.1.tar.gz", "django-ajax-forms", "0.3.1"],
        ["lskdjfknw.sdi.siqwenr", "lskdjfknw.sdi.siqwenr", None],
    ],
)
def test_parse_source_filename(filename, result_name, result_version):
    result = req_compile.filename.parse_source_filename(filename)
    assert result == (
        result_name,
        pkg_resources.parse_version(result_version) if result_version else None,
    )
