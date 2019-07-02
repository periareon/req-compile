import pytest

from qer.cmdline import compile_main
import os

from qer.dists import DistInfo
from qer.repos.findlinks import FindLinksRepository
from qer.repos.pypi import PyPIRepository
from qer.repos.solution import SolutionRepository
from qer.repos.source import SourceRepository
from qer import utils


@pytest.fixture
def basic_compile_mock(mocker):
    perform_compile_mock = mocker.patch('qer.cmdline.perform_compile')
    result = mocker.MagicMock()
    result.generate_lines.return_value = [('line', 'line')]
    perform_compile_mock.return_value = result, mocker.MagicMock()
    return perform_compile_mock


@pytest.fixture
def compile_mock(basic_compile_mock, mocker):
    mocker.patch('qer.cmdline._create_input_reqs')
    mocker.patch('os.path.exists')
    mocker.patch('os.listdir')
    mocker.patch('qer.repos.solution.load_from_file')
    mocker.patch('qer.repos.repository.process_distribution')
    return basic_compile_mock


def test_multiple_sources(compile_mock):
    compile_main(['requirements.txt', '--source', '1', '--source', '2', '--source', '3', '--no-index'])
    perform_compile_args = compile_mock.mock_calls[0][1]
    assert (list(perform_compile_args[1]) ==
            [SourceRepository('1'), SourceRepository('2'), SourceRepository('3')])


def test_resolution_order(compile_mock):
    compile_main(['requirements.txt',
                  '--source', 'source 1',
                  '--solution', 'solution',
                  '--source', 'source 2',
                  '--index-url', 'index',
                  '--find-links', 'find-links'])

    perform_compile_args = compile_mock.mock_calls[0][1]
    assert (list(perform_compile_args[1]) ==
            [SolutionRepository('solution'),
             SourceRepository('source 1'),
             SourceRepository('source 2'),
             FindLinksRepository('find-links'),
             PyPIRepository('index', None)])


def test_source_dirs_dont_hit_pypi(mocker, basic_compile_mock):
    mocker.patch('os.path.exists')
    metadata_mock = mocker.patch('qer.metadata.extract_metadata')
    metadata_mock.return_value = DistInfo('myproj', '1.0', ['unknown_req'])

    compile_main(['source/myproj'])
    perform_compile_args = basic_compile_mock.mock_calls[0][1]
    assert (perform_compile_args[0] ==
            {'source/myproj': [utils.parse_requirement('myproj==1.0')]})
