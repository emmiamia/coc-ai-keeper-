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


# This repository is an internal service, deliberately separate from HTTP routes.
import json
from pathlib import Path
from pydantic import TypeAdapter
from app.models.game import GameState
from app.scenario.models import (
    Scenario, Location, NPC, Clue, Event, Encounter, KeeperContext,
    PlayerLocation, PlayerClue, PlayerKnowledge, Conditions, StateChanges,
    CoreEntities, Outcome,
)

class JsonScenarioRepository:
    ENTITY_MODELS = {'locations': Location, 'npcs': NPC, 'clues': Clue,
                     'events': Event, 'encounters': Encounter}

    def __init__(self, root):
        self.root = Path(root).resolve()

    def _directory(self, scenario_id):
        # IDs are directory names, never arbitrary filesystem paths.
        if not scenario_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in scenario_id):
            raise KeyError(scenario_id)
        directory = (self.root / scenario_id).resolve()
        if directory.parent != self.root or not directory.is_dir():
            raise KeyError(scenario_id)
        return directory

    def _read(self, scenario_id, filename):
        directory = self._directory(scenario_id)
        path = (directory / filename).resolve()
        if path.parent != directory:
            raise ValueError('Scenario files must remain inside their directory')
        return json.loads(path.read_text())

    def load_scenario(self, scenario_id) -> Scenario:
        scenario = Scenario.model_validate(self._read(scenario_id, 'scenario.json'))
        if scenario.id != scenario_id:
            raise ValueError('Scenario ID does not match directory')
        return scenario

    def known_location_ids(self, scenario_id, state):
        scenario = self.load_scenario(scenario_id)
        candidates = list(dict.fromkeys([*scenario.initial_known_locations,
            *state.known_locations,*state.visited_locations,
            *([scenario.starting_state.current_location] if scenario.starting_state.current_location else [])]))
        # Canonical clue unlocks are permissions to pursue a route, not automatic
        # knowledge. Only resolved state flags/recorded location knowledge grant entry.
        return [i for i in candidates if self.get_location(scenario_id,i).access_conditions.matches(state)]

    def metadata(self, scenario_id):
        scenario = self.load_scenario(scenario_id)
        return ScenarioMetadata(scenario_id=scenario.id, title=scenario.title)

    def _entities(self, scenario_id, category):
        entities = TypeAdapter(list[self.ENTITY_MODELS[category]]).validate_python(self._read(scenario_id, category + '.json'))
        if len({entity.id for entity in entities}) != len(entities):
            raise ValueError(f'Duplicate IDs in {category}')
        if category == 'npcs':
            ids = [item.id for npc in entities for item in npc.knowledge_items]
            if len(set(ids)) != len(ids):
                raise ValueError('Knowledge item IDs must be unique across NPCs')
        return entities

    def _get(self, scenario_id, category, entity_id):
        for entity in self._entities(scenario_id, category):
            if entity.id == entity_id:
                return entity
        raise KeyError(entity_id)

    def get_location(self, scenario_id, location_id) -> Location:
        return self._get(scenario_id, 'locations', location_id)

    def get_npc(self, scenario_id, npc_id) -> NPC:
        return self._get(scenario_id, 'npcs', npc_id)

    def get_clue(self, scenario_id, clue_id) -> Clue:
        return self._get(scenario_id, 'clues', clue_id)

    def get_event(self, scenario_id, event_id) -> Event:
        return self._get(scenario_id, 'events', event_id)

    def get_encounter(self, scenario_id, encounter_id) -> Encounter:
        return self._get(scenario_id, 'encounters', encounter_id)

    def knows_clue(self, scenario_id, clue_id, state):
        self.get_clue(scenario_id, clue_id)
        return clue_id in state.discovered_clues

    def require_discovered_clues(self, scenario_id, clue_ids, state):
        for clue_id in clue_ids:
            if not self.knows_clue(scenario_id, clue_id, state):
                raise PermissionError(f'Clue not discovered: {clue_id}')

    def player_location(self, scenario_id, location_id) -> PlayerLocation:
        location = self.get_location(scenario_id, location_id)
        return PlayerLocation(id=location.id, name=location.player_name,
                              description=location.player_description,
                              action_categories=location.action_categories)

    def player_clue(self, scenario_id, clue_id, state) -> PlayerClue:
        self.require_discovered_clues(scenario_id, [clue_id], state)
        clue = self.get_clue(scenario_id, clue_id)
        return PlayerClue(id=clue.id, reveal=clue.player_reveal)

    def revealable_knowledge(self, scenario_id, npc_id, state, action=None):
        # Eligibility is permission for future orchestration, not a disclosure.
        npc = self.get_npc(scenario_id, npc_id)
        return [item for item in npc.knowledge_items
                if item.access != 'keeper_only'
                and (item.access == 'public' or action == 'talk')
                and item.reveal_conditions.matches(state, action)]

    def player_npc_knowledge(self, scenario_id, npc_id, state):
        npc = self.get_npc(scenario_id, npc_id)
        return [PlayerKnowledge(id=item.id, information=item.information)
                for item in npc.knowledge_items if item.access != 'keeper_only'
                and (item.id in state.revealed_information or
                     (item.access == 'public' and item.reveal_conditions.matches(state)))]

    def event_eligible(self, scenario_id, event_id, state, action=None):
        event = self.get_event(scenario_id, event_id)
        return event.id not in state.triggered_events and event.trigger.matches(state, action)

    def get_context(self, scenario_id, state: GameState, location_id=None, npc_ids=None, action=None) -> KeeperContext:
        location_id = location_id if location_id is not None else state.current_location
        location = self.get_location(scenario_id, location_id) if location_id else None
        npcs = [self.get_npc(scenario_id, i) for i in
                (npc_ids if npc_ids is not None else location.npc_ids if location else [])]
        clues = [self.get_clue(scenario_id, i) for i in location.clue_ids] if location else []
        # Previously discovered clues remain usable after leaving their location.
        discovered = [self.get_clue(scenario_id, i) for i in state.discovered_clues]
        events = [self.get_event(scenario_id, i) for i in location.event_ids] if location else []
        encounters = [self.get_encounter(scenario_id, i) for i in location.encounter_ids] if location else []
        return KeeperContext(scenario_id=scenario_id, location=location, npcs=npcs,
            available_clues=[c for c in clues if c.availability.matches(state, action)],
            discovered_clues=discovered,
            eligible_events=[e for e in events if e.id not in state.triggered_events and e.trigger.matches(state, action)],
            eligible_encounters=[e for e in encounters if e.trigger.matches(state, action)])

    def validate_scenario(self, scenario_id):
        """Explicit authoring/preflight check; full validation is not a turn operation."""
        scenario = self.load_scenario(scenario_id)
        entities = {category: self._entities(scenario_id, category)
                    for category in self.ENTITY_MODELS}
        ids = {category: {entity.id for entity in values}
               for category, values in entities.items()}
        knowledge_ids = {item.id for npc in entities['npcs'] for item in npc.knowledge_items}

        def require(category, references):
            unknown = set(references) - ids[category]
            if unknown:
                raise ValueError(f'Unknown {category} references: {sorted(unknown)}')

        def knowledge(references):
            if set(references) - knowledge_ids:
                raise ValueError('Unknown NPC knowledge reference')

        def walk(model):
            if isinstance(model, CoreEntities):
                for category in ids:
                    require(category, getattr(model, category))
            if isinstance(model, Location):
                for category, field in [('npcs','npc_ids'),('clues','clue_ids'),('events','event_ids'),('encounters','encounter_ids')]:
                    require(category, getattr(model, field))
                for clue_id in model.clue_ids:
                    clue = next(c for c in entities['clues'] if c.id == clue_id)
                    if clue.location_id != model.id:
                        raise ValueError('Location clue membership disagrees with clue location')
            if isinstance(model, Clue):
                require('locations', [model.location_id])
            if isinstance(model, Conditions):
                require('clues', model.discovered_clues)
                knowledge(model.revealed_information)
                if model.location_id is not None:
                    require('locations', [model.location_id])
            if isinstance(model, StateChanges):
                require('clues', model.discover_clues)
                knowledge(model.reveal_information)
                if model.current_location is not None:
                    require('locations', [model.current_location])
            if isinstance(model, Outcome):
                require('events', model.next_events)
                require('encounters', model.next_encounters)
            if isinstance(model, Scenario):
                require('locations', model.initial_known_locations)
            if isinstance(model, GameState):
                require('locations', model.known_locations)
                require('clues', model.discovered_clues)
                require('locations', model.visited_locations)
                require('events', model.triggered_events)
                knowledge(model.revealed_information)
                if model.current_location is not None:
                    require('locations', [model.current_location])
            if isinstance(model, BaseModel):
                for field in type(model).model_fields:
                    walk(getattr(model, field))
            elif isinstance(model, dict):
                for value in model.values():
                    walk(value)
            elif isinstance(model, list):
                for value in model:
                    walk(value)
        walk(scenario)
        for values in entities.values():
            walk(values)
        return scenario


class ScenarioKnowledgeRepository(Protocol):
    """Typed internal boundary for future orchestration implementations."""
    def load_scenario(self, scenario_id: str) -> Scenario: ...
    def get_location(self, scenario_id: str, location_id: str) -> Location: ...
    def get_npc(self, scenario_id: str, npc_id: str) -> NPC: ...
    def get_clue(self, scenario_id: str, clue_id: str) -> Clue: ...
    def get_event(self, scenario_id: str, event_id: str) -> Event: ...
    def get_encounter(self, scenario_id: str, encounter_id: str) -> Encounter: ...
    def get_context(self, scenario_id: str, state: GameState, location_id: str | None = None,
                    npc_ids: list[str] | None = None, action: str | None = None) -> KeeperContext: ...
