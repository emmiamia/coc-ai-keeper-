from typing import Protocol
from pydantic import BaseModel

class LLMMessage(BaseModel):
    role: str
    content: str

class LLMProvider(Protocol):
    async def generate(self, messages: list[LLMMessage]) -> str: ...
