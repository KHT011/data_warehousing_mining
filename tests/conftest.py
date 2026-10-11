import pytest
from utils.config import load_config
from etl.synthetic import generate


@pytest.fixture
def cfg(tmp_path):
    c=load_config(smoke=True)
    for key in c['paths']:
        c['paths'][key]=str(tmp_path/key)
    c['paths']['warehouse']+='.duckdb'
    generate(c)
    return c
