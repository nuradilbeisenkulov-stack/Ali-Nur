import json
import httpx
from app.engine import TriageEngine


def test_gemini_only_trusted_synthetic_and_no_leakage(monkeypatch, data_dir):
    monkeypatch.setenv('SUPPORT_AI', 'auto')
    monkeypatch.setenv('SUPPORT_AI_BACKEND', 'gemini')
    monkeypatch.setenv('SUPPORT_EXTERNAL_SCOPE', 'synthetic')
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-test-key')
    captured=[]
    def post(self,url,**kwargs):
        captured.append((url,kwargs))
        data={'category':'report.payment','draft_text':'Вы сообщили о проблеме с оплатой. Обращение передано администратору на рассмотрение. Уточните время платежа.','needs_human':True}
        return httpx.Response(200,request=httpx.Request('POST',url),json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(data)}]}}]})
    monkeypatch.setattr(httpx.Client,'post',post)
    engine=TriageEngine(data_dir)
    ticket={'kind':'report','lang':'ru','reporter_hash':'PRIVATE_HASH','verdict':'PRIVATE_VERDICT','messages':[{'role':'player','text':'Я оплатил монеты, но платёж не поступил.'},{'role':'admin','text':'PRIVATE_ADMIN'}]}
    engine.triage(ticket)
    assert not captured
    result=engine.triage(ticket,synthetic=True)
    assert len(captured)==1
    assert 'PRIVATE_' not in json.dumps(captured)
    assert captured[0][1]['headers']['x-goog-api-key']=='synthetic-test-key'
    assert 'synthetic-test-key' not in json.dumps(result)
    assert any('Контекстный черновик' in r for r in result['reasons'])


def test_gemini_missing_key_never_sends(monkeypatch,data_dir):
    monkeypatch.setenv('SUPPORT_AI','auto')
    monkeypatch.setenv('SUPPORT_AI_BACKEND','gemini')
    monkeypatch.setenv('GEMINI_API_KEY','')
    monkeypatch.setenv('SUPPORT_EXTERNAL_SCOPE','synthetic')
    def prohibited(*args,**kwargs): raise AssertionError('No request allowed')
    monkeypatch.setattr(httpx.Client,'post',prohibited)
    result=TriageEngine(data_dir).triage({'kind':'report','lang':'ru','messages':[{'role':'player','text':'Я оплатил набор монет.'}]},synthetic=True)
    assert any('GEMINI_API_KEY' in r for r in result['reasons'])
