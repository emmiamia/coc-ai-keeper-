import asyncio
import base64
from urllib.parse import quote
from unittest.mock import AsyncMock
import httpx
import pytest
from google.genai import errors
from app.llm.provider import LLMRequest, ProviderError
from app.llm.smoke import diagnostic_for, sanitize_diagnostic

@pytest.mark.parametrize('code,status,message', [
    (404,'NOT_FOUND','models/test-model is not found for this API version'),
    (401,'UNAUTHENTICATED','API key not valid'),
    (403,'PERMISSION_DENIED','Permission denied'),
    (429,'RESOURCE_EXHAUSTED','Quota exceeded; retry later'),
])
def test_sdk_error_type_status_and_message(code,status,message):
    sdk_error = errors.ClientError(code,{'error':{'code':code,'status':status,'message':message}})
    try:
        try: raise sdk_error
        except Exception: raise ProviderError('Production-safe failure') from None
    except ProviderError as error:
        result = diagnostic_for(error)
        assert 'ClientError' in result
        assert str(code) in result and status in result and message in result
        assert str(error) == 'Production-safe failure'
        assert error.__suppress_context__

@pytest.mark.parametrize('error', [httpx.ConnectError('Connection refused'),httpx.ReadTimeout('Request timed out')])
def test_connectivity_diagnostic(error):
    result=diagnostic_for(error)
    assert type(error).__name__ in result and str(error) in result

def test_configured_credentials_and_encoded_forms_redacted(monkeypatch):
    secret='private-test-key/with+characters'
    other='another-private-token'
    monkeypatch.setenv('GEMINI_API_KEY',secret)
    monkeypatch.setenv('OTHER_ACCESS_TOKEN',other)
    result=sanitize_diagnostic('Authentication failed '+secret+' '+quote(secret,safe='')+' '+base64.b64encode(secret.encode()).decode()+' '+other)
    assert secret not in result and other not in result
    assert quote(secret,safe='') not in result
    assert base64.b64encode(secret.encode()).decode() not in result
    assert 'Authentication failed' in result

@pytest.mark.parametrize('payload', [
    'https://user:unknown-password@example.test/path?key=unknown-secret',
    'Authorization: Bearer unknown-secret',
    'x-goog-api-key: unknown-secret',
    '{"api_key": "unknown-secret"}',
    'password=unknown-secret',
    'Bearer unknown-secret',
])
def test_unknown_labelled_credentials_and_urls_redacted(payload):
    result=sanitize_diagnostic('Connection failed '+payload)
    assert 'unknown-secret' not in result and 'unknown-password' not in result
    assert 'Connection failed' in result

def test_manual_main_reports_sanitized_error(monkeypatch,capsys):
    from app.llm import smoke
    monkeypatch.setenv('GEMINI_API_KEY','private-test-credential')
    error=httpx.ConnectError('Connection refused https://host.test/?key=private-test-credential')
    async def fail():
        try: raise error
        except Exception: raise ProviderError('Production-safe failure') from None
    monkeypatch.setattr(smoke,'run',fail)
    with pytest.raises(SystemExit) as exit: smoke.main()
    assert exit.value.code == 1
    output=capsys.readouterr()
    assert 'FAIL: ConnectError:' in output.out
    assert 'Connection refused' in output.out
    assert 'private-test-credential' not in output.out+output.err


def test_nonprovider_failure_does_not_print_raw_traceback(monkeypatch,capsys):
    from app.llm import smoke
    monkeypatch.setenv('GEMINI_API_KEY','private-test-credential')
    async def fail(): raise RuntimeError('Close failed private-test-credential')
    monkeypatch.setattr(smoke,'run',fail)
    with pytest.raises(SystemExit): smoke.main()
    output=capsys.readouterr()
    assert 'RuntimeError: Close failed' in output.out
    assert 'private-test-credential' not in output.out+output.err
    assert not output.err
