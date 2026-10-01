"""Provider-neutral contracts; no SDK dependencies."""
from typing import Literal, Protocol, overload, runtime_checkable
from pydantic import BaseModel, ConfigDict, Field

class LLMMessage(BaseModel):
    role: Literal['user', 'assistant', 'player', 'keeper']
    content: str

class LLMRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    system_instruction: str = ''
    messages: list[LLMMessage] = Field(default_factory=list)
    user_message: str = Field(min_length=1)
    response_schema: type[BaseModel] | None = Field(default=None, exclude=True)

class LLMResponse(BaseModel):
    text: str
    provider: str
    model: str
    structured_data: dict | None = None

class ProviderError(RuntimeError):
    """Controlled provider error safe to display without SDK payloads."""

class ProviderConfigurationError(ProviderError):
    pass

class ProviderResponseError(ProviderError):
    pass

@runtime_checkable
class LLMProvider(Protocol):
    @overload
    async def generate(self, request: LLMRequest) -> LLMResponse: ...
    @overload
    async def generate(self, request: list[LLMMessage]) -> str: ...
    async def generate(self, request: LLMRequest | list[LLMMessage]) -> LLMResponse | str: ...
