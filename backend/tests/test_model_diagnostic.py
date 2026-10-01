from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from google.genai import errors,types
from app.llm import model_diagnostic as diagnostic
from app.llm.gemini import DEFAULT_MODEL

def model(name, actions=None):
    return types.Model(name='models/'+name,supported_actions=actions if actions is not None else ['generateContent'])

def client_with(models):
    return SimpleNamespace(models=SimpleNamespace(list=MagicMock(return_value=models),generate_content=MagicMock(return_value=SimpleNamespace(text='Hello'))))

def test_only_discovered_capable_verified_free_models_tested(capsys):
    client=client_with([model('gemini-2.5-flash-lite'),model('gemini-3.1-flash-lite'),model('gemini-2.5-flash', ['embedContent']),model('gemini-pro'),model('gemini-flash-paid-only'),model('gemini-flash-image')])
    assert diagnostic.inspect_and_test(client) == 0
    calls=client.models.generate_content.call_args_list
    assert [c.kwargs['model'] for c in calls] == ['gemini-2.5-flash-lite','gemini-3.1-flash-lite']
    assert all(c.kwargs['contents'] == diagnostic.PROMPT for c in calls)
    assert all(c.kwargs['config'].tools is None for c in calls)
    assert DEFAULT_MODEL == 'gemini-3.7-flash'
    out=capsys.readouterr().out
    assert 'SKIP gemini-flash-paid-only' in out
    assert 'PASS gemini-2.5-flash-lite' in out


def test_sequential_probe_continues_after_failure_and_redacts(monkeypatch,capsys):
    monkeypatch.setenv('GEMINI_API_KEY','private-test-secret')
    client=client_with([model('gemini-2.5-flash'),model('gemini-2.5-flash-lite')])
    client.models.generate_content.side_effect=[errors.ServerError(503,{'error':{'code':503,'status':'UNAVAILABLE','message':'High demand private-test-secret'}}),SimpleNamespace(text='Hello')]
    assert diagnostic.inspect_and_test(client) == 0
    out=capsys.readouterr().out
    assert 'FAIL gemini-2.5-flash: ServerError (HTTP 503, UNAVAILABLE)' in out
    assert 'PASS gemini-2.5-flash-lite' in out
    assert 'private-test-secret' not in out
    assert client.models.generate_content.call_count == 2


def test_list_only_and_limit(capsys):
    client=client_with([model('gemini-2.5-flash'),model('gemini-2.5-flash-lite')])
    assert diagnostic.inspect_and_test(client,list_only=True) == 0
    client.models.generate_content.assert_not_called()
    assert diagnostic.inspect_and_test(client,limit=1) == 0
    assert client.models.generate_content.call_count == 1


def test_no_candidates_sends_no_request():
    client=client_with([model('unknown-flash-paid')])
    assert diagnostic.inspect_and_test(client) == 1
    client.models.generate_content.assert_not_called()


def test_empty_text_failure(capsys):
    client=client_with([model('gemini-2.5-flash')])
    client.models.generate_content.return_value=SimpleNamespace(text=None)
    assert diagnostic.inspect_and_test(client) == 1
    assert 'FAIL gemini-2.5-flash' in capsys.readouterr().out


def test_main_is_developer_api_single_attempt_and_no_model_override(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','private-test-secret')
    monkeypatch.setattr('sys.argv',['model_diagnostic','--list-only'])
    client=client_with([])
    context=MagicMock(); context.__enter__.return_value=client
    factory=MagicMock(return_value=context)
    monkeypatch.setattr(diagnostic.genai,'Client',factory)
    with pytest.raises(SystemExit) as exit: diagnostic.main()
    assert exit.value.code == 0
    kwargs=factory.call_args.kwargs
    assert kwargs['vertexai'] is False
    assert kwargs['http_options'].retry_options.attempts == 1
    client.models.generate_content.assert_not_called()
