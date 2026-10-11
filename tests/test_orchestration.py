import importlib.util
import subprocess
import pytest


def runner():
    assert importlib.util.find_spec('orchestration') is not None, 'Airflow task runner is missing'
    import orchestration
    return orchestration


def test_dag_default_etl_is_offline_and_smoke_is_isolated(monkeypatch):
    module=runner()
    monkeypatch.delenv('TMDB_TOKEN',raising=False)
    command=module.build_command('extract',{'smoke':True})
    assert command[1:4]==['/app/run_pipeline.py','stage','extract']
    assert '--smoke' in command and '--live' not in command


def test_live_requires_token_and_never_applies_to_synthetic(monkeypatch):
    module=runner()
    monkeypatch.delenv('TMDB_TOKEN',raising=False)
    with pytest.raises(ValueError,match='TMDB_TOKEN'):
        module.build_command('extract',{'live':True},'config/project.yaml')
    monkeypatch.setenv('TMDB_TOKEN','test-not-real')
    with pytest.raises(ValueError,match='synthetic'):
        module.build_command('extract',{'live':True,'smoke':True},'config/project.yaml')
    command=module.build_command('extract',{'live':True,'tmdb_limit':25},'config/project.yaml')
    assert '--live' in command
    assert 'test-not-real' not in command
    assert command[command.index('--tmdb-limit')+1]=='25'


def test_task_failure_propagates_to_airflow(tmp_path):
    module=runner()
    with pytest.raises(subprocess.CalledProcessError):
        module.run_step('validate',{},config_path=str(tmp_path/'missing.yaml'),project_root=str(tmp_path))


def test_unknown_steps_and_bad_limits_are_rejected():
    module=runner()
    with pytest.raises(ValueError,match='step'):
        module.build_command('shell',{},'config/project.yaml')
    with pytest.raises(ValueError,match='limit'):
        module.build_command('extract',{'tmdb_limit':-1},'config/project.yaml')
