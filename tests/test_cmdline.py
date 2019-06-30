import pytest

from qer.cmdline import compile_main
import os

from qer.repos.findlinks import FindLinksRepository
from qer.repos.pypi import PyPIRepository
from qer.repos.solution import SolutionRepository
from qer.repos.source import SourceRepository


@pytest.fixture
def compile_mock(mocker):
    perform_compile_mock = mocker.patch('qer.cmdline.perform_compile')
    result = mocker.MagicMock()
    result.generate_lines.return_value = [('line', 'line')]
    perform_compile_mock.return_value = result, mocker.MagicMock()
    mocker.patch('qer.cmdline._create_input_reqs')
    mocker.patch('os.path.exists')
    mocker.patch('os.listdir')
    mocker.patch('qer.repos.solution.load_from_file')
    mocker.patch('qer.repos.repository.process_distribution')
    return perform_compile_mock


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
