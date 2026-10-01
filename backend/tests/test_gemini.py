import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from pydantic import SecretStr
from google.genai import types
from app.llm.gemini import GeminiProvider, GeminiConfig, DEFAULT_MODEL, gemini_response_schema
from app.llm.provider import LLMProvider, LLMMessage, LLMRequest, ProviderError, ProviderConfigurationError, ProviderResponseError
from app.llm.smoke import ActionClassification

@pytest.fixture
def client():
    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(return_value=SimpleNamespace(text='Hello',parsed=None))),aclose=AsyncMock()))

@pytest.fixture
def provider(client):
    return GeminiProvider(GeminiConfig(api_key=SecretStr('test-credential-only')),client=client)

def generate(provider,**kwargs):
    return asyncio.run(provider.generate(LLMRequest(user_message='Harmless test',**kwargs)))

def test_interface_text_history_and_sdk_configuration(provider,client):
    assert isinstance(provider,LLMProvider)
    response=generate(provider,system_instruction='Test system',messages=[LLMMessage(role='user',content='Hi'),LLMMessage(role='keeper',content='Hello')])
    assert response.text == 'Hello'
    assert response.provider == 'gemini' and response.model == DEFAULT_MODEL
    assert response.structured_data is None
    args=client.aio.models.generate_content.call_args.kwargs
    assert [c.role for c in args['contents']] == ['user','model','user']
    assert args['config'].system_instruction == 'Test system'
    assert args['config'].tools is None
    assert 'test-credential-only' not in response.model_dump_json()

def test_environment_model_config(monkeypatch,client):
    monkeypatch.setenv('GEMINI_API_KEY','test-credential-only')
    monkeypatch.setenv('GEMINI_MODEL','configured-test-model')
    provider=GeminiProvider(client=client)
    assert generate(provider).model == 'configured-test-model'
    assert client.aio.models.generate_content.call_args.kwargs['model'] == 'configured-test-model'
    assert 'test-credential-only' not in repr(provider._config)

@pytest.mark.parametrize('key', [None,'','   '])
def test_missing_key_controlled(monkeypatch,key):
    if key is None: monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    else: monkeypatch.setenv('GEMINI_API_KEY',key)
    with pytest.raises(ProviderConfigurationError,match='GEMINI_API_KEY'): GeminiProvider()

def test_blank_model_controlled(monkeypatch,client):
    monkeypatch.setenv('GEMINI_API_KEY','test-credential-only'); monkeypatch.setenv('GEMINI_MODEL',' ')
    with pytest.raises(ProviderConfigurationError,match='GEMINI_MODEL'): GeminiProvider(client=client)

def test_sdk_factory_developer_api(monkeypatch,client):
    from app.llm import gemini
    factory=MagicMock(return_value=client)
    monkeypatch.setattr(gemini.genai,'Client',factory)
    config=GeminiConfig(api_key=SecretStr('test-credential-only'))
    provider=GeminiProvider(config)
    assert factory.call_args.kwargs['vertexai'] is False
    assert factory.call_args.kwargs['http_options'].timeout == 30000
    asyncio.run(provider.aclose())
    client.aio.aclose.assert_awaited_once()

@pytest.mark.parametrize('parsed', [None,{'intent':'search','requires_reasoning':True},ActionClassification(intent='search',requires_reasoning=True)])
def test_structured_schema_and_validation(provider,client,parsed):
    client.aio.models.generate_content.return_value=types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model', parts=[types.Part(text='{"intent":"search","requires_reasoning":true}')]))])
    client.aio.models.generate_content.return_value.parsed = parsed
    response=generate(provider,response_schema=ActionClassification)
    assert response.structured_data == {'intent':'search','requires_reasoning':True}
    config=client.aio.models.generate_content.call_args.kwargs['config']
    assert config.response_mime_type == 'application/json'
    assert config.response_schema == gemini_response_schema(ActionClassification)
    assert 'additionalProperties' not in config.response_schema

@pytest.mark.parametrize('text', ['not json','{}','{"intent":"search","requires_reasoning":"true"}','{"intent":"search","requires_reasoning":true,"unexpected":1}'])
def test_invalid_structured_fails_safely(provider,client,text):
    client.aio.models.generate_content.return_value=SimpleNamespace(text=text,parsed=None)
    with pytest.raises(ProviderResponseError,match='invalid structured data') as error: generate(provider,response_schema=ActionClassification)
    assert text not in str(error.value)

@pytest.mark.parametrize('text', [None,'','  '])
def test_empty_response(provider,client,text):
    client.aio.models.generate_content.return_value=SimpleNamespace(text=text,parsed=None)
    with pytest.raises(ProviderResponseError,match='no usable text'): generate(provider)

def test_invalid_sdk_parsed_response(provider,client):
    client.aio.models.generate_content.return_value=SimpleNamespace(text='{}',parsed={'intent':'other','requires_reasoning':True})
    with pytest.raises(ProviderResponseError): generate(provider,response_schema=ActionClassification)

def test_errors_and_reflected_credentials_withheld(provider,client):
    client.aio.models.generate_content.side_effect=RuntimeError('SDK payload test-credential-only')
    with pytest.raises(ProviderError) as error: generate(provider)
    assert 'test-credential-only' not in str(error.value)
    assert error.value.__suppress_context__
    client.aio.models.generate_content.side_effect=None
    client.aio.models.generate_content.return_value=SimpleNamespace(text='test-credential-only',parsed=None)
    with pytest.raises(ProviderResponseError,match='withheld'): generate(provider)

def test_legacy_interface_still_returns_text(provider):
    response=asyncio.run(provider.generate([LLMMessage(role='player',content='Hello')]))
    assert response == 'Hello'

@pytest.mark.parametrize('messages', [[],[LLMMessage(role='keeper',content='Not a user message')]])
def test_invalid_legacy_request(provider,messages):
    with pytest.raises(ProviderResponseError): asyncio.run(provider.generate(messages))

def test_injected_client_lifecycle_not_owned(provider,client):
    asyncio.run(provider.aclose())
    client.aio.aclose.assert_not_awaited()


def test_old_boolean_literal_reproduces_sdk_conversion_error():
    from typing import Literal
    from pydantic import BaseModel
    from google import genai
    from google.genai import _transformers
    class IncompatibleSchema(BaseModel):
        requires_reasoning: Literal[True]
    with genai.Client(api_key='offline-test-placeholder',vertexai=False) as sdk:
        with pytest.raises(ValueError,match='Literal values must be strings'):
            _transformers.t_schema(sdk._api_client,IncompatibleSchema)


def test_smoke_schema_converts_through_actual_sdk_without_network():
    from google import genai
    from google.genai import _transformers
    with genai.Client(api_key='offline-test-placeholder',vertexai=False) as sdk:
        # Exercise the real conversion previously bypassed by the AsyncMock.
        converted = _transformers.t_schema(sdk._api_client,gemini_response_schema(ActionClassification))
    assert converted.properties['intent'].enum == ['search']
    assert converted.properties['requires_reasoning'].type == types.Type.BOOLEAN
    assert set(converted.required) == {'intent','requires_reasoning'}
    assert ActionClassification.model_json_schema()['additionalProperties'] is False


@pytest.mark.parametrize('value', [False,0,1,'true',None])
def test_smoke_schema_still_requires_actual_true(value):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ActionClassification.model_validate({'intent':'search','requires_reasoning':value})


def test_raw_sdk_schema_retains_rejected_additional_properties():
    from google import genai
    from google.genai import _transformers
    from pydantic import BaseModel, ConfigDict
    class ExtraForbidden(BaseModel):
        model_config = ConfigDict(extra='forbid')
        value: bool
    assert ExtraForbidden.model_json_schema()['additionalProperties'] is False
    with genai.Client(api_key='offline-test-placeholder',vertexai=False) as sdk:
        converted = _transformers.t_schema(sdk._api_client,ExtraForbidden)
    assert converted.additional_properties is False


def test_actual_provider_config_serializes_without_unsupported_fields(provider,client):
    from google import genai
    from google.genai import models
    client.aio.models.generate_content.return_value = SimpleNamespace(text='{"intent":"search","requires_reasoning":true}',parsed=None)
    generate(provider,response_schema=ActionClassification)
    config = client.aio.models.generate_content.call_args.kwargs['config']
    with genai.Client(api_key='offline-test-placeholder',vertexai=False) as sdk:
        payload = models._GenerateContentConfig_to_mldev(sdk._api_client,config)
    wire = payload['responseSchema'].model_dump(mode='json',exclude_none=True)
    def verify(node):
        if isinstance(node,dict):
            assert 'additionalProperties' not in node
            assert 'additional_properties' not in node
            for child in node.values(): verify(child)
        elif isinstance(node,list):
            for child in node: verify(child)
    verify(wire)
    assert wire['properties']['requires_reasoning']['type'] == 'BOOLEAN'
    assert wire['properties']['intent']['enum'] == ['search']
    assert wire['required'] == ['intent','requires_reasoning']


def test_nested_schema_compatibility_does_not_remove_property_names():
    from typing import Literal
    from pydantic import BaseModel, ConfigDict
    class Inner(BaseModel):
        model_config = ConfigDict(extra='forbid')
        additionalProperties: str
        enabled: Literal[True]
    class Outer(BaseModel):
        model_config = ConfigDict(extra='forbid')
        values: list[Inner]
        optional: Inner | None = None
    original = Outer.model_json_schema()
    compatible = gemini_response_schema(Outer)
    assert original['additionalProperties'] is False
    assert 'additionalProperties' not in compatible
    inner = compatible['$defs']['Inner']
    assert 'additionalProperties' not in inner
    assert 'additionalProperties' in inner['properties']
    assert inner['properties']['enabled']['type'] == 'boolean'
    assert 'const' not in inner['properties']['enabled']
    assert Outer.model_json_schema() == original


def test_provider_preserves_true_only_validation_after_schema_adaptation(provider,client):
    client.aio.models.generate_content.return_value = SimpleNamespace(text='{"intent":"search","requires_reasoning":false}',parsed=None)
    with pytest.raises(ProviderResponseError,match='invalid structured data'):
        generate(provider,response_schema=ActionClassification)
