"""Gemini Developer API adapter; never connects to scenario/state/MCP."""
import os
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError
from google import genai
from google.genai import types
from app.llm.provider import (LLMMessage, LLMRequest, LLMResponse,
    ProviderError, ProviderConfigurationError, ProviderResponseError)

DEFAULT_MODEL = 'gemini-3.7-flash'

def gemini_response_schema(model: type[BaseModel]) -> dict:
    """Adapt only Gemini-incompatible constraints; retain full local validation.

    Schema nodes and property-name maps are distinct: a property literally named
    additionalProperties must not be deleted. model_json_schema returns a fresh
    document, so this never mutates the provider-neutral model.
    """
    def adapt(node):
        if not isinstance(node, dict):
            return node
        node = dict(node)
        node.pop('additionalProperties', None)
        node.pop('additional_properties', None)
        # SDK response_schema accepts const only for strings. Other singleton
        # values remain enforced by the original Pydantic response model.
        if 'const' in node and not isinstance(node['const'], str):
            node.pop('const')
        for keyword in ('properties', '$defs', 'definitions', 'patternProperties', 'dependentSchemas'):
            if isinstance(node.get(keyword), dict):
                node[keyword] = {name: adapt(schema) for name, schema in node[keyword].items()}
        for keyword in ('items', 'not', 'if', 'then', 'else', 'contains'):
            if isinstance(node.get(keyword), dict):
                node[keyword] = adapt(node[keyword])
        for keyword in ('anyOf', 'oneOf', 'allOf', 'prefixItems'):
            if isinstance(node.get(keyword), list):
                node[keyword] = [adapt(schema) for schema in node[keyword]]
        return node
    return adapt(model.model_json_schema())


class GeminiConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    api_key: SecretStr
    model: str = DEFAULT_MODEL

    @classmethod
    def from_environment(cls):
        key = os.getenv('GEMINI_API_KEY', '').strip()
        model = os.getenv('GEMINI_MODEL', DEFAULT_MODEL).strip()
        if not key:
            raise ProviderConfigurationError('Set GEMINI_API_KEY in the backend environment.')
        if not model:
            raise ProviderConfigurationError('GEMINI_MODEL must not be blank.')
        return cls(api_key=SecretStr(key), model=model)

class GeminiProvider:
    def __init__(self, config: GeminiConfig | None = None, *, client=None):
        self._config = config if config is not None else GeminiConfig.from_environment()
        if not self._config.api_key.get_secret_value().strip() or not self._config.model.strip():
            raise ProviderConfigurationError('Gemini requires a nonempty API key and model.')
        self._owns_client = client is None
        try:
            self._client = client if client is not None else genai.Client(
                api_key=self._config.api_key.get_secret_value(), vertexai=False,
                http_options=types.HttpOptions(timeout=30000))
        except Exception:
            raise ProviderConfigurationError('Could not initialize the Gemini Developer API client.') from None

    async def aclose(self):
        if self._owns_client:
            await self._client.aio.aclose()

    async def generate(self, request: LLMRequest | list[LLMMessage]) -> LLMResponse | str:
        legacy = isinstance(request, list)
        if legacy:
            if not request or request[-1].role not in ('user', 'player'):
                raise ProviderResponseError('Legacy input must end with a user/player message.')
            request = LLMRequest(messages=request[:-1], user_message=request[-1].content)
        contents = [types.Content(role='model' if m.role in ('assistant', 'keeper') else 'user',
                    parts=[types.Part(text=m.content)]) for m in request.messages]
        contents.append(types.Content(role='user', parts=[types.Part(text=request.user_message)]))
        config = types.GenerateContentConfig(system_instruction=request.system_instruction or None)
        if request.response_schema is not None:
            config.response_mime_type = 'application/json'
            config.response_schema = gemini_response_schema(request.response_schema)
        try:
            raw = await self._client.aio.models.generate_content(
                model=self._config.model, contents=contents, config=config)
            text = raw.text
            if not isinstance(text, str) or not text.strip():
                raise ProviderResponseError('Gemini returned no usable text.')
            if self._config.api_key.get_secret_value() in text:
                raise ProviderResponseError('Gemini returned sensitive output; response withheld.')
            structured = None
            if request.response_schema is not None:
                parsed = getattr(raw, 'parsed', None)
                validated = (request.response_schema.model_validate(parsed.model_dump() if isinstance(parsed, BaseModel) else parsed)
                             if parsed is not None else request.response_schema.model_validate_json(text))
                structured = validated.model_dump(mode='json')
                if self._config.api_key.get_secret_value() in validated.model_dump_json():
                    raise ProviderResponseError('Gemini returned sensitive output; response withheld.')
            response = LLMResponse(text=text, provider='gemini', model=self._config.model, structured_data=structured)
        except ProviderResponseError:
            raise
        except ValidationError:
            raise ProviderResponseError('Gemini returned invalid structured data.') from None
        except Exception:
            raise ProviderError('Gemini request failed; check credentials, model access, and connectivity.') from None
        return response.text if legacy else response
