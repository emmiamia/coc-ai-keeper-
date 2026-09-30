"""Structural assertions only; no source quotations or licensed prose fixtures."""
from pathlib import Path
import json
import pytest
from app.models.game import GameTime
from app.scenario.repository import JsonScenarioRepository
from app.state.repository import GameStateRepository

ROOT = Path(__file__).resolve().parents[2] / 'scenario_data'
SID = 'paper_chase'

@pytest.fixture
def repo():
    if not (ROOT/SID/'scenario.json').is_file():
        pytest.skip('Private local Paper Chase data is not installed; see scenario_data/README.md')
    return JsonScenarioRepository(ROOT)

@pytest.fixture
def state(repo):
    return repo.load_scenario(SID).starting_state

def test_load_and_validate_all_references(repo, state):
    scenario = repo.validate_scenario(SID)
    assert scenario.id == SID
    assert state.current_location == 'kimball_house'
    assert state.phase == 'open_investigation'
    assert state.game_time.day == 1
    assert state.game_time.period in ('morning','afternoon')
    assert len(scenario.core_entities.locations) == 8
    assert len(scenario.core_entities.npcs) == 4
    assert len(scenario.core_entities.clues) == 15
    assert len(scenario.core_entities.events) == 6

@pytest.mark.parametrize('location_id', ['kimball_house','nearby_residences','cemetery','library','police_station','newspaper_office','mausoleum','underground_tunnels'])
def test_location_exists(repo, location_id):
    assert repo.get_location(SID,location_id).id == location_id

def test_douglas_identity_is_private(repo, state):
    npc = repo.get_npc(SID,'douglas_kimball')
    assert npc.player_name == 'Mysterious figure'
    assert any(k.access == 'keeper_only' for k in npc.knowledge_items)
    assert repo.player_npc_knowledge(SID,npc.id,state) == []
    assert repo.revealable_knowledge(SID,npc.id,state,'talk') == []
    state.story_flags.update(douglas_identity_revealed=True,douglas_polite_conversation=True,douglas_not_attacked=True)
    assert {k.id for k in repo.revealable_knowledge(SID,npc.id,state,'talk')} == {'douglas_revealed_identity','douglas_explanation','douglas_request'}
    assert repo.player_npc_knowledge(SID,npc.id,state) == []
    state.revealed_information = [k.id for k in npc.knowledge_items]
    assert all(k.id != 'douglas_hidden_truth' for k in repo.player_npc_knowledge(SID,npc.id,state))

def test_thomas_does_not_know_hidden_fate(repo, state):
    thomas = repo.get_npc(SID,'thomas_kimball')
    assert {k.id for k in thomas.knowledge_items} == {'thomas_case','thomas_background','thomas_house','thomas_watch_suggestion'}
    assert not any(k.access == 'keeper_only' for k in thomas.knowledge_items)
    state.revealed_information = ['douglas_hidden_truth','douglas_explanation']
    assert {k.id for k in repo.player_npc_knowledge(SID,thomas.id,state)} == {'thomas_case','thomas_house'}
    public = json.dumps(repo.player_location(SID,'kimball_house').model_dump())
    assert 'keeper_context' not in public and 'clue_ids' not in public

def test_jefferson_public_conversation_guarded_are_separate(repo, state):
    npc = repo.get_npc(SID,'melodias_jefferson')
    by_id = {k.id:k for k in npc.knowledge_items}
    assert by_id['jefferson_reading_grave'].access == 'conversational'
    assert by_id['jefferson_night_report'].access == 'guarded'
    assert repo.player_npc_knowledge(SID,npc.id,state) == []
    assert repo.revealable_knowledge(SID,npc.id,state,'talk') == []
    state.story_flags['jefferson_conversation_success'] = True
    assert [k.id for k in repo.revealable_knowledge(SID,npc.id,state,'talk')] == ['jefferson_reading_grave']
    state.discovered_clues = ['clue_jefferson_hiding_information','clue_jefferson_alcohol']
    assert [k.id for k in repo.revealable_knowledge(SID,npc.id,state,'talk')] == ['jefferson_reading_grave']
    state.story_flags['jefferson_guarded_access'] = True
    assert {k.id for k in repo.revealable_knowledge(SID,npc.id,state,'talk')} == {'jefferson_reading_grave','jefferson_night_report'}
    assert repo.player_npc_knowledge(SID,npc.id,state) == []

@pytest.mark.parametrize('clue_id', ['clue_douglas_journal','clue_gravestone_tracks'])
def test_key_clues_exist_but_are_not_discovered(repo, state, clue_id):
    assert repo.get_clue(SID,clue_id).id == clue_id
    assert state.discovered_clues == []
    assert not repo.knows_clue(SID,clue_id,state)
    with pytest.raises(PermissionError): repo.player_clue(SID,clue_id,state)
    assert state.discovered_clues == []

def test_starting_context_does_not_discover_hidden_locations(repo, state):
    context = repo.get_context(SID,state)
    assert context.location.id == 'kimball_house'
    assert {n.id for n in context.npcs} == {'thomas_kimball'}
    assert context.discovered_clues == []
    assert state.visited_locations == state.discovered_clues == []
    assert not state.story_flags.get('mausoleum_discovered',False)
    assert not state.story_flags.get('underground_route_discovered',False)
    assert context.eligible_encounters == []

def test_tracks_gate_and_mausoleum_unlock_persistence(repo, state, tmp_path):
    state.current_location = 'cemetery'
    clue = repo.get_clue(SID,'clue_gravestone_tracks')
    assert not clue.availability.matches(state)
    state.discovered_clues.append('clue_jefferson_favorite_grave')
    assert clue.availability.matches(state)
    assert not repo.event_eligible(SID,'event_follow_tracks',state,'follow_tracks')
    states = GameStateRepository(tmp_path/'game.sqlite3')
    session = states.create(SID,state)
    saved = states.record_clue_discovery(session.session_id,clue.id,repo)
    assert repo.event_eligible(SID,'event_follow_tracks',saved.state,'follow_tracks')
    assert clue.unlocks.locations == ['mausoleum']
    transition = repo.get_event(SID,'event_follow_tracks').outcomes['discover_mausoleum'].state_changes
    def apply(state):
        state.story_flags.update(transition.flags)
        state.current_location = transition.current_location
    states.update_state(session.session_id,apply)
    restored = GameStateRepository(states.path).get(session.session_id)
    assert restored.state.story_flags['mausoleum_discovered']
    assert restored.state.current_location == 'mausoleum'
    assert clue.id in restored.state.discovered_clues
    assert repo.player_clue(SID,clue.id,restored.state).id == clue.id

@pytest.mark.parametrize('action,location', [('watch_house','kimball_house'),('watch_cemetery','cemetery')])
def test_stakeout_requires_explicit_choice_and_night(repo, state, action, location):
    state.current_location = location
    state.game_time = GameTime(period='night')
    assert not repo.event_eligible(SID,'event_nighttime_stakeout',state,action)
    state.story_flags['stakeout_explicitly_chosen'] = True
    state.game_time.period = 'afternoon'
    assert not repo.event_eligible(SID,'event_nighttime_stakeout',state,action)
    state.game_time.period = 'night'
    assert repo.event_eligible(SID,'event_nighttime_stakeout',state,action)
    assert 'event_nighttime_stakeout' in [e.id for e in repo.get_context(SID,state,action=action).eligible_events]
    assert not repo.event_eligible(SID,'event_nighttime_stakeout',state,'talk')
    state.story_flags['nighttime_intrusions_stop'] = True
    assert not repo.event_eligible(SID,'event_nighttime_stakeout',state,action)

def test_locked_window_preserves_visit_and_private_identity(repo):
    event = repo.get_event(SID,'event_nighttime_stakeout')
    assert event.mechanical_check.skill_name == 'Luck'
    for key in ('success_window_locked','success_window_unlocked'):
        changes = event.outcomes[key].state_changes
        assert changes.flags['figure_observed']
        assert changes.flags['figure_contact_available']
        assert not changes.flags.get('douglas_identity_revealed',False)
        assert event.outcomes[key].next_encounters == ['encounter_douglas']

def test_encounter_branch_gates_and_combat_marker(repo, state):
    encounter = repo.get_encounter(SID,'encounter_douglas')
    assert encounter.player_presentation == 'A mysterious figure is nearby.'
    assert {'talk','follow','flee','attack'} <= set(encounter.branches)
    assert encounter.branches['attack'].mechanic_support in ('partial','unsupported')
    assert not encounter.branches['talk'].requirements.matches(state)
    assert not encounter.branches['polite_conversation'].requirements.matches(state)
    assert not encounter.branches['follow_underground_ending'].requirements.matches(state)
    assert not encounter.branches['flee'].outcome.state_changes.reveal_information
    assert not encounter.branches['shout'].outcome.state_changes.flags.get('douglas_identity_revealed',False)
    assert encounter.branches['talk'].mechanical_checks[0].skill_name == 'SAN'
    assert encounter.branches['talk'].mechanic_support == 'partial'

def test_push_failure_is_explicit_and_time_is_deferred(repo, state):
    state.current_location = 'library'
    event = repo.get_event(SID,'event_library_push_failure')
    assert not repo.event_eligible(SID,event.id,state,'push_library_research')
    state.story_flags.update(library_push_explicitly_chosen=True,library_pushed_check_failed=True)
    assert repo.event_eligible(SID,event.id,state,'push_library_research')
    cost = event.outcomes['information_with_cost'].state_changes
    assert cost.discover_clues == ['clue_library_old_report']
    assert cost.flags['time_advance_to_next_morning_required']
    assert repo.get_clue(SID,'clue_library_old_report').required_checks[0].push_allowed

def test_tunnel_entry_needs_discovery(repo, state):
    state.current_location = 'underground_tunnels'
    assert not repo.event_eligible(SID,'event_tunnel_exploration',state,'enter_tunnels')
    state.story_flags['underground_route_discovered'] = True
    assert repo.event_eligible(SID,'event_tunnel_exploration',state,'enter_tunnels')
    event = repo.get_event(SID,'event_tunnel_exploration')
    assert event.mechanical_check.skill_name == 'Navigate'
    for outcome in event.outcomes.values():
        assert outcome.state_changes.flags['time_advance_toward_night_required']
    state.story_flags['underground_access_closed'] = True
    assert not repo.event_eligible(SID,event.id,state,'enter_tunnels')

def test_epilogue_disclosure_is_player_choice(repo, state):
    encounter = repo.get_encounter(SID,'encounter_douglas')
    assert not encounter.branches['tell_thomas'].requirements.matches(state)
    state.story_flags['douglas_identity_revealed'] = True
    assert not encounter.branches['tell_thomas'].requirements.matches(state)
    state.story_flags['tell_thomas_explicitly_chosen'] = True
    assert encounter.branches['tell_thomas'].requirements.matches(state)
    assert encounter.branches['keep_secret'].outcome.state_changes.phase == 'epilogue'
    assert encounter.branches['unresolved_ending'].outcome.state_changes.phase == 'epilogue'
