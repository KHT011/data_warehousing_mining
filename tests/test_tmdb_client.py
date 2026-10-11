import pytest
import requests
from etl.extract import TMDBClient


class Response:
    def __init__(self, status, payload=None, headers=None):
        self.status_code=status; self.payload=payload; self.headers=headers or {}
    def json(self): return self.payload


class Session:
    def __init__(self, responses): self.responses=iter(responses); self.calls=0
    def get(self,*args,**kwargs):
        self.calls+=1
        result=next(self.responses)
        if isinstance(result,Exception): raise result
        return result


def test_retry_resume_language_and_refresh(tmp_path):
    session=Session([Response(429,headers={'Retry-After':'0'}),requests.Timeout(),Response(200,{'id':1,'title':'one','runtime':90})])
    c=TMDBClient(tmp_path,token='secret',session=session,sleep=lambda _:None)
    assert c.fetch(1,[2],'A')['payload']['runtime']==90
    assert c.fetch(1,[2],'B')['payload']['runtime']==90
    assert session.calls==3
    restarted=TMDBClient(tmp_path,token='secret',session=Session([]),sleep=lambda _:None)
    assert restarted.fetch(1,[2],'resume')['payload']['runtime']==90
    assert restarted.session.calls==0
    c.session=Session([Response(200,{'id':1,'title':'one','runtime':95})])
    assert c.fetch(1,[2],'C',refresh=True)['payload']['runtime']==95
    assert 'secret' not in (tmp_path/'tmdb_manifest.json').read_text()


def test_auth_missing_and_bounded_failure(tmp_path):
    with pytest.raises(ValueError,match='TMDB_TOKEN'):
        TMDBClient(tmp_path,token='')
    c=TMDBClient(tmp_path,token='token',session=Session([Response(401)]),sleep=lambda _:None)
    with pytest.raises(PermissionError): c.fetch(1,[],'A')
    c.session=Session([Response(404)])
    assert c.fetch(1,[],'A') is None
    c.session=Session([Response(503)]*5)
    with pytest.raises(RuntimeError,match='exhausted'): c.fetch(2,[],'A')
    assert c.session.calls==5


def test_payload_identity_and_language_cache(tmp_path):
    c=TMDBClient(tmp_path,token='token',session=Session([Response(200,{'id':1,'title':'one'})]),sleep=lambda _:None)
    c.fetch(1,[],'A')
    d=TMDBClient(tmp_path,token='token',language='fr-FR',session=Session([Response(200,{'id':2,'title':'wrong'})]),sleep=lambda _:None)
    with pytest.raises(ValueError,match='identity'): d.fetch(1,[],'B')
