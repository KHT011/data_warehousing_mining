import importlib.util


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
