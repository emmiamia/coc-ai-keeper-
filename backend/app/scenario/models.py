"""Canonical models are Keeper-facing. Only explicit projections are player-facing."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.models.game import GameState, InvestigationPhase

class KnowledgeModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Conditions(KnowledgeModel):
    phases: list[InvestigationPhase] = Field(default_factory=list)
    periods: list[Literal['morning', 'afternoon', 'evening', 'night']] = Field(default_factory=list)
    day: int | None = Field(default=None, ge=1)
    required_flags: list[str] = Field(default_factory=list)
    forbidden_flags: list[str] = Field(default_factory=list)
    discovered_clues: list[str] = Field(default_factory=list)
    revealed_information: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    location_id: str | None = None

    def matches(self, state: GameState, action: str | None = None) -> bool:
        return (not self.phases or state.phase in self.phases) and (not self.periods or state.game_time.period in self.periods) and (self.day is None or state.game_time.day == self.day) and all(state.story_flags.get(f, False) for f in self.required_flags) and all(not state.story_flags.get(f, False) for f in self.forbidden_flags) and set(self.discovered_clues) <= set(state.discovered_clues) and set(self.revealed_information) <= set(state.revealed_information) and (not self.actions or action in self.actions) and (self.location_id is None or state.current_location == self.location_id)

class StateChanges(KnowledgeModel):
    discover_clues: list[str] = Field(default_factory=list)
    reveal_information: list[str] = Field(default_factory=list)
    flags: dict[str, bool] = Field(default_factory=dict)
    phase: InvestigationPhase | None = None
    current_location: str | None = None

class MechanicalCheck(KnowledgeModel):
    skill_name: str
    difficulty: Literal['regular', 'hard', 'extreme'] = 'regular'
    push_allowed: bool = False
    push_consequence_reference: str | None = None

class Outcome(KnowledgeModel):
    player_reference: str = ''
    keeper_context: str = ''
    state_changes: StateChanges = Field(default_factory=StateChanges)
    next_events: list[str] = Field(default_factory=list)
    next_encounters: list[str] = Field(default_factory=list)

class CoreEntities(KnowledgeModel):
    locations: list[str] = Field(default_factory=list)
    npcs: list[str] = Field(default_factory=list)
    clues: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    encounters: list[str] = Field(default_factory=list)

class Scenario(KnowledgeModel):
    id: str
    title: str
    setting: str
    player_premise: str
    keeper_truth: str
    starting_state: GameState = Field(default_factory=GameState)
    core_entities: CoreEntities = Field(default_factory=CoreEntities)
    progression_phases: list[InvestigationPhase] = Field(default_factory=lambda: ['open_investigation', 'focused_investigation', 'climax', 'epilogue'])
    initial_known_locations: list[str] = Field(default_factory=list)
    improvisation_policy: str

class Location(KnowledgeModel):
    id: str
    player_name: str
    player_description: str
    keeper_context: str = ''
    npc_ids: list[str] = Field(default_factory=list)
    clue_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    encounter_ids: list[str] = Field(default_factory=list)
    action_categories: list[str] = Field(default_factory=list)
    access_conditions: Conditions = Field(default_factory=Conditions)

class KnowledgeItem(KnowledgeModel):
    id: str
    information: str
    access: Literal['public', 'conversational', 'guarded', 'keeper_only']
    reveal_conditions: Conditions = Field(default_factory=Conditions)
    check_alternatives: list[MechanicalCheck] = Field(default_factory=list)
    check_grants: StateChanges = Field(default_factory=StateChanges)
    check_approaches: list[str] = Field(default_factory=list)
    state_changes: StateChanges = Field(default_factory=StateChanges)

class NPC(KnowledgeModel):
    id: str
    player_name: str
    role: str
    default_attitude: str
    keeper_context: str = ''
    knowledge_items: list[KnowledgeItem] = Field(default_factory=list)

class Clue(KnowledgeModel):
    id: str
    location_id: str
    category: str
    keeper_truth: str
    player_reveal: str
    # Authored player-safe question, never the undiscovered answer.
    discovery_question: str | None = None
    availability: Conditions = Field(default_factory=Conditions)
    discovery_actions: list[str] = Field(default_factory=list)
    discovery_context: str = ''
    required_checks: list[MechanicalCheck] = Field(default_factory=list)
    alternative_checks: list[MechanicalCheck] = Field(default_factory=list)
    success: Outcome = Field(default_factory=Outcome)
    failure: Outcome = Field(default_factory=Outcome)
    state_changes: StateChanges = Field(default_factory=StateChanges)
    unlocks: CoreEntities = Field(default_factory=CoreEntities)

class Event(KnowledgeModel):
    id: str
    trigger: Conditions = Field(default_factory=Conditions)
    mechanical_check: MechanicalCheck | None = None
    outcomes: dict[str, Outcome] = Field(default_factory=dict)

class Branch(KnowledgeModel):
    requirements: Conditions = Field(default_factory=Conditions)
    mechanical_checks: list[MechanicalCheck] = Field(default_factory=list)
    outcome: Outcome = Field(default_factory=Outcome)
    mechanic_support: Literal['supported', 'partial', 'unsupported'] = 'supported'

class Encounter(KnowledgeModel):
    id: str
    trigger: Conditions = Field(default_factory=Conditions)
    player_presentation: str
    keeper_context: str = ''
    branches: dict[str, Branch] = Field(default_factory=dict)

class KeeperContext(KnowledgeModel):
    """Internal canonical context; never serialize this through player endpoints."""
    scenario_id: str
    location: Location | None = None
    npcs: list[NPC] = Field(default_factory=list)
    available_clues: list[Clue] = Field(default_factory=list)
    discovered_clues: list[Clue] = Field(default_factory=list)
    eligible_events: list[Event] = Field(default_factory=list)
    eligible_encounters: list[Encounter] = Field(default_factory=list)

class PlayerLocation(KnowledgeModel):
    id: str
    name: str
    description: str
    action_categories: list[str]

class PlayerClue(KnowledgeModel):
    id: str
    reveal: str

class PlayerKnowledge(KnowledgeModel):
    id: str
    information: str
