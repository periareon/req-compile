import contextlib
import logging
import os

import pytest

import req_compile.extractor


@contextlib.contextmanager
def temp_cwd(new_cwd):
    old_cwd = os.getcwd()
    try:
        os.chdir(new_cwd)
        yield new_cwd
    finally:
        os.chdir(old_cwd)


@pytest.mark.parametrize('archive_fixture', ['mock_targz', 'mock_zip', 'mock_zip'])
def test_extractor(archive_fixture, tmpdir, mock_targz, mock_zip):
    directory = 'comtypes-1.1.7'
    if archive_fixture == 'mock_targz':
        archive = mock_targz(directory)
    elif archive_fixture == 'mock_zip':
        archive = mock_zip(directory)
    else:
        archive = os.path.abspath(os.path.join('source-packages', directory))

    with temp_cwd(str(tmpdir.mkdir('fake_root'))) as fake_root:
        logging.getLogger('req_compile.tests').info('Running in context: %s', fake_root)
        if archive_fixture == 'mock_targz':
            extractor = req_compile.extractor.TarExtractor('gz', archive, fake_root)
            prefix = directory + '/'
        elif archive_fixture == 'mock_zip':
            extractor = req_compile.extractor.ZipExtractor(archive, fake_root)
            prefix = directory + '/'
        else:
            extractor = req_compile.extractor.NonExtractor(archive, fake_root)
            prefix = ''

        with contextlib.closing(extractor):
            all_names = set(extractor.names())
            assert all_names == {
                prefix + 'README',
                prefix + 'setup.py',
                prefix + 'comtypes/__init__.py',
                prefix + 'test/setup.py'
            }

            assert extractor.contents(prefix + 'README') == 'README CONTENTS'
            assert extractor.exists(prefix + 'test')
            assert extractor.exists(prefix + 'test/setup.py')
            assert not extractor.exists(prefix + 'test/setup2.py')
