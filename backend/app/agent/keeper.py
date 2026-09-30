from typing import Protocol
from app.llm.provider import LLMProvider

class MechanicsClient(Protocol):
    async def call_tool(self, name: str, arguments: dict) -> dict: ...

class PlaceholderKeeper:
    def __init__(self, scenarios, states, provider: LLMProvider | None = None, mechanics: MechanicsClient | None = None):
        self.scenarios, self.states = scenarios, states
        self.provider, self.mechanics = provider, mechanics

    def act(self, session_id, message):
        session = self.states.get(session_id)
        self.scenarios.metadata(session.scenario_id)
        return self.states.append_turn(session_id, message,
            '[Placeholder Keeper] Your message has been saved. No scenario or AI narration is loaded yet.')
