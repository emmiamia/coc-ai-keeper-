"""Explicit HTTP allowlist; internal GameState/Session are never returned for real games."""
from typing import Literal
from pydantic import BaseModel, Field
from app.models.game import Message, GameTime, InvestigationPhase

class PlayerState(BaseModel):
    current_location: str | None
    location_name: str | None
    hp: int
    san: int
    skills: dict[str,int]
    inventory: list[str]
    conditions: list[str]
    known_locations: list[str]
    discovered_clues: list[str]
    clue_names: dict[str,str] = Field(default_factory=dict)
    phase: InvestigationPhase
    game_time: GameTime
    push_available: bool

class PlayerSession(BaseModel):
    session_id: str
    scenario_id: str
    status: Literal['active','completed']
    state: PlayerState
    messages: list[Message]
    updated_at: str
    turn_outcome: Literal['completed', 'clarification'] | None = None


def project_session(session, scenarios):
    state = session.state
    location_name = None
    discovered = []
    clue_names = {}
    if session.scenario_id != 'placeholder':
        if state.current_location:
            location_name = scenarios.player_location(session.scenario_id,state.current_location).name
        for clue_id in state.discovered_clues:
            scenarios.player_clue(session.scenario_id,clue_id,state)
            discovered.append(clue_id)
            clue_names[clue_id] = scenarios.get_clue(session.scenario_id,clue_id).player_name
    return PlayerSession(session_id=session.session_id,scenario_id=session.scenario_id,
        status=session.status,messages=session.messages,updated_at=session.updated_at,
        turn_outcome=session.event_log[-1].get('outcome','completed') if session.event_log and session.event_log[-1].get('type') == 'keeper_turn_completed' else None,
        state=PlayerState(current_location=state.current_location,location_name=location_name,
            hp=state.hp,san=state.san,skills=state.skills,inventory=state.inventory,
            conditions=state.conditions,known_locations=scenarios.known_location_ids(session.scenario_id,state) if session.scenario_id != 'placeholder' else [],discovered_clues=discovered,clue_names=clue_names,phase=state.phase,
            game_time=state.game_time,push_available=bool(state.pending_push and state.pending_push.allowed)))
