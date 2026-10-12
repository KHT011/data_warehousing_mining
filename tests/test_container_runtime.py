import importlib.util
import zipfile


def test_startup_extracts_missing_csvs_without_overwriting_existing_data(tmp_path):
    from utils.container_runtime import prepare_raw_data, MOVIELENS_FILES
    archive = tmp_path / 'ml-20m.zip'
    raw = tmp_path / 'data' / 'raw'
    raw.mkdir(parents=True)
    (raw / 'ratings.csv').write_text('existing ratings')
    with zipfile.ZipFile(archive, 'w') as zipped:
        for name in MOVIELENS_FILES:
            zipped.writestr('ml-20m/' + name, 'fixture ' + name)
        zipped.writestr('../../escape.txt', 'must not extract')
    prepare_raw_data(archive, raw)
    assert (raw / 'ratings.csv').read_text() == 'existing ratings'
    for name in MOVIELENS_FILES:
        if name != 'ratings.csv':
            assert (raw / name).read_text() == 'fixture ' + name
    assert not (tmp_path / 'escape.txt').exists()
    archive.unlink()
    prepare_raw_data(archive, raw)  # Subsequent starts need no archive.


def test_startup_without_zip_allows_synthetic_smoke(tmp_path):
    from utils.container_runtime import prepare_raw_data
    prepare_raw_data(tmp_path / 'absent.zip', tmp_path / 'raw')
    assert not (tmp_path / 'raw' / 'ratings.csv').exists()


def test_incomplete_archive_fails_before_extracting(tmp_path):
    import pytest
    from utils.container_runtime import prepare_raw_data
    archive = tmp_path / 'ml-20m.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('ml-20m/ratings.csv', 'fixture')
    with pytest.raises(ValueError, match='missing'):
        prepare_raw_data(archive, tmp_path / 'raw')
    assert not (tmp_path / 'raw' / 'ratings.csv').exists()


def test_standalone_restart_clears_only_runtime_pid_files(tmp_path):
    assert importlib.util.find_spec('utils.container_runtime') is not None, 'Restart cleanup is missing'
    from utils.container_runtime import cleanup_airflow_runtime
    files={'airflow-webserver.pid':b'25','airflow-webserver-monitor.pid':b'19',
           'airflow.db':b'persisted database','standalone_admin_password.txt':b'private fixture',
           'unrelated.pid':b'42'}
    for name,data in files.items():(tmp_path/name).write_bytes(data)
    cleanup_airflow_runtime(tmp_path)
    assert not (tmp_path/'airflow-webserver.pid').exists()
    assert not (tmp_path/'airflow-webserver-monitor.pid').exists()
    for name in ['airflow.db','standalone_admin_password.txt','unrelated.pid']:
        assert (tmp_path/name).read_bytes()==files[name]
    cleanup_airflow_runtime(tmp_path)  # A second startup is harmless.
