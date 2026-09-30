from typing import Protocol
from pydantic import BaseModel

class ScenarioMetadata(BaseModel):
    scenario_id: str
    title: str

class ScenarioRepository(Protocol):
    def metadata(self, scenario_id: str) -> ScenarioMetadata: ...
    def keeper_truth(self, scenario_id: str) -> dict: ...

class PlaceholderScenarioRepository:
    def metadata(self, scenario_id):
        if scenario_id != 'placeholder':
            raise KeyError(scenario_id)
        return ScenarioMetadata(scenario_id=scenario_id, title='Placeholder — no scenario loaded')

    def keeper_truth(self, scenario_id):
        self.metadata(scenario_id)
        return {}  # Never returned by player-facing endpoints.
