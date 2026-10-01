"""Untrusted LLM decisions and controlled orchestrator responses."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.models.game import Session

class KeeperDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    intent: str
    action_category: str
    action_type: Literal['observe','hypothesize','talk','move','investigate','mechanical_action','unsupported','clarification_needed'] | None = None
    destination_id: str | None = None
    knowledge_item_ids: list[str] = Field(default_factory=list)
    question_answerable: bool = True
    social_approach: Literal['ordinary','charm','persuade','intimidate','fast_talk','bribe'] = 'ordinary'
    check_required: bool = False
    mechanic: Literal['none','skill_check','roll_dice','san_check','combat'] = 'none'
    requested_skill: str | None = None
    clue_id: str | None = None
    npc_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    encounter_ids: list[str] = Field(default_factory=list)
    depends_on_clue_ids: list[str] = Field(default_factory=list)
    proposes_transition: bool = False
    narration_guidance: str = ''
    status: Literal['ready','clarification','unsupported'] = 'ready'

class NarrationChoice(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    sentence_ids: list[int]

class TurnResult(BaseModel):
    status: Literal['completed','clarification','unsupported','error']
    session: Session
    narration: str
    turn_id: str
