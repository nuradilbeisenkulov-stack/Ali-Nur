"""Synthetic safety checks of the real model adapter with a mocked transport."""
import json
import httpx
from app.engine import TriageEngine


def test_model_gets_no_admin_or_outcomes(monkeypatch, data_dir):
    monkeypatch.setenv('SUPPORT_AI', 'auto')
    monkeypatch.setenv('SUPPORT_AI_BACKEND', 'ollama')
    monkeypatch.setenv('OLLAMA_URL', 'http://127.0.0.1:11434')
    captured = {}
    def post(self, url, **kwargs):
        captured.update(kwargs['json'])
        content = {'category': 'report.payment', 'draft_text': 'По вашему сообщению, покупка не появилась на балансе. Обращение передано администратору на рассмотрение. Уточните время оплаты.', 'needs_human': False}
        return httpx.Response(200, request=httpx.Request('POST', url), json={'message': {'content': json.dumps(content)}})
    monkeypatch.setattr(httpx.Client, 'post', post)
    result = TriageEngine(data_dir).triage({'kind':'report', 'lang':'ru', 'messages':[{'role':'player','text':'Я оплатил покупку, но баланс не изменился.'},{'role':'admin','text':'SECRET_RESULT'}], 'verdict':'SECRET_VERDICT'})
    serialized = json.dumps(captured)
    assert 'SECRET' not in serialized
    assert result['needs_human'] is True
    assert 'время оплаты' in result['draft_reply']['text']
    assert result['draft_reply']['cited'] == []


def test_model_cannot_invent_rule_or_promise(monkeypatch, data_dir):
    monkeypatch.setenv('SUPPORT_AI', 'auto')
    monkeypatch.setenv('SUPPORT_AI_BACKEND', 'ollama')
    monkeypatch.setenv('OLLAMA_URL', 'http://127.0.0.1:11434')
    def post(self, url, **kwargs):
        return httpx.Response(200, request=httpx.Request('POST', url), json={'message': {'content': json.dumps({'category':'report.payment','draft_text':'По правилу 999.123 мы вернём деньги и нарушитель будет наказан.', 'needs_human':False})}})
    monkeypatch.setattr(httpx.Client, 'post', post)
    result = TriageEngine(data_dir).triage({'kind':'report','lang':'ru','messages':[{'role':'player','text':'Прошу проверить мой платёж за покупку.'}]})
    assert '999' not in result['draft_reply']['text']
    assert result['needs_human']
    assert any('резервный' in reason for reason in result['reasons'])


def test_remote_model_endpoint_is_disallowed(monkeypatch, data_dir):
    import pytest
    monkeypatch.setenv('OLLAMA_URL', 'https://example.com')
    with pytest.raises(ValueError):
        TriageEngine(data_dir)
