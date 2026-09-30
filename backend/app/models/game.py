from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

def now():
    return datetime.now(timezone.utc).isoformat()

class GameState(BaseModel):
    current_location: str | None = None
    hp: int = Field(default=10, ge=0)
    san: int = Field(default=50, ge=0, le=99)
    skills: dict[str, int] = Field(default_factory=dict)
    inventory: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    visited_locations: list[str] = Field(default_factory=list)
    discovered_clues: list[str] = Field(default_factory=list)
    revealed_information: list[str] = Field(default_factory=list)
    triggered_events: list[str] = Field(default_factory=list)
    story_flags: dict[str, bool] = Field(default_factory=dict)
    npc_state: dict = Field(default_factory=dict)
    custom_world_state: dict = Field(default_factory=dict)

class Message(BaseModel):
    role: Literal['player', 'keeper']
    content: str
    timestamp: str = Field(default_factory=now)

class Session(BaseModel):
    session_id: str
    scenario_id: str = 'placeholder'
    status: Literal['active', 'completed'] = 'active'
    state: GameState = Field(default_factory=GameState)
    event_log: list[dict] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    updated_at: str = Field(default_factory=now)
