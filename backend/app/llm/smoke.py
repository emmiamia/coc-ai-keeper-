"""Manual live Gemini smoke: python -m app.llm.smoke (never runs under pytest)."""
import asyncio
import base64
import json
import os
import re
from urllib.parse import quote, quote_plus
from typing import Literal
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from app.llm.gemini import GeminiProvider
from app.llm.provider import LLMRequest, ProviderError

class ActionClassification(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    intent: Literal['search']
    # The provider adapts the wire schema; this model remains authoritative.
    requires_reasoning: Literal[True]

    @field_validator('requires_reasoning', mode='before')
    @classmethod
    def require_reasoning(cls, value: bool) -> bool:
        if type(value) is not bool or value is not True:
            raise ValueError('requires_reasoning must be true for this smoke response')
        return value

async def run():
    provider = GeminiProvider()
    try:
        plain = await provider.generate(LLMRequest(system_instruction='You are a test assistant.', user_message='Say hello in one short sentence.'))
        assert plain.text.strip()
        result = await provider.generate(LLMRequest(
            system_instruction='You are a test assistant. Return the requested structured response.',
            user_message='Classify this action: I search the room. Use intent search and requires_reasoning true.',
            response_schema=ActionClassification))
        ActionClassification.model_validate(result.structured_data)
        # Only status and model are printed, never prompt/raw output/credentials.
        print(sanitize_diagnostic(f'PASS: plain text and validated structured output ({result.model})'))
    finally:
        await provider.aclose()

def sanitize_diagnostic(message: str) -> str:
    """Only for manually invoked diagnostics; never dump requests or headers."""
    # Redact configured secrets even when an SDK URL-encodes or escapes them.
    secrets = [value for name, value in os.environ.items() if value and
               re.search(r'(?:key|token|secret|password|credentials?)$', name, re.I)]
    for secret in sorted(secrets, key=len, reverse=True):
        variants = {secret, quote(secret, safe=''), quote_plus(secret),
                    json.dumps(secret)[1:-1], base64.b64encode(secret.encode()).decode()}
        for variant in sorted(variants, key=len, reverse=True):
            message = message.replace(variant, '[REDACTED]')
    # Unknown credentials may appear in URLs, headers or labelled payload fields.
    message = re.sub(r'https?://[^\s\'"<>]+', '[URL REDACTED]', message, flags=re.I)
    message = re.sub(r'\b(?:Bearer|Basic)\s+[^\s,;\'"}]+', '[AUTH REDACTED]', message, flags=re.I)
    message = re.sub(r'(?im)[\x27\x22]?(?:authorization|x-goog-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|credential|secret|token|key)[\x27\x22]?\s*[:=][^\n]*', '[CREDENTIAL DETAILS REDACTED]', message)
    message = re.sub(r'AIza[A-Za-z0-9_-]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}', '[KEY REDACTED]', message)
    message = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', message)
    return ' '.join(message.split())[:1000]


def diagnostic_for(error: Exception) -> str:
    # `raise ... from None` hides the SDK error in production tracebacks but
    # retains __context__. Inspect it only here, without changing the provider.
    underlying = error
    seen = set()
    while isinstance(underlying, ProviderError) and id(underlying) not in seen:
        seen.add(id(underlying))
        nested = underlying.__cause__ or underlying.__context__
        if nested is None:
            break
        underlying = nested
    if isinstance(underlying, ValidationError):
        message = 'Structured response validation failed; response contents withheld.'
    else:
        message = str(getattr(underlying, 'message', None) or underlying)
    code = getattr(underlying, 'code', None)
    status = getattr(underlying, 'status', None)
    details = []
    if isinstance(code, int) and 100 <= code <= 599:
        details.append(f'HTTP {code}')
    if isinstance(status, str) and re.fullmatch(r'[A-Z_]{3,60}', status):
        details.append(status)
    label = type(underlying).__name__
    return sanitize_diagnostic(f'{label}' + (f" ({', '.join(details)})" if details else '') + f': {message}')


def main():
    try:
        asyncio.run(run())
    except Exception as error:
        print(f'FAIL: {diagnostic_for(error)}')
        raise SystemExit(1) from None

if __name__ == '__main__':
    main()
