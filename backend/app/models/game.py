from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

def now():
    return datetime.now(timezone.utc).isoformat()

InvestigationPhase = Literal['open_investigation', 'focused_investigation', 'climax', 'epilogue']

class GameTime(BaseModel):
    day: int = Field(default=1, ge=1)
    period: Literal['morning', 'afternoon', 'evening', 'night'] = 'morning'

class PendingPush(BaseModel):
    check_id: str
    skill_name: str
    skill_value: int = Field(ge=0, le=100)
    difficulty: Literal['regular', 'hard', 'extreme'] = 'regular'
    context: str
    allowed: bool = False
    consequence_reference: str

class GameState(BaseModel):
    phase: InvestigationPhase = 'open_investigation'
    game_time: GameTime = Field(default_factory=GameTime)
    pending_push: PendingPush | None = None
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
