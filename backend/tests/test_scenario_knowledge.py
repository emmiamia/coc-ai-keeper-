import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.db.sqlite import connect
from app.models.game import GameState, GameTime, PendingPush
from app.scenario.repository import JsonScenarioRepository
from app.state.repository import GameStateRepository

ROOT = Path(__file__).resolve().parents[2] / 'scenario_data'

@pytest.fixture
def repo():
    return JsonScenarioRepository(ROOT)

@pytest.fixture
def state(repo):
    return repo.load_scenario('synthetic_test').starting_state

def test_load_and_independent_location(repo, monkeypatch):
    scenario = repo.load_scenario('synthetic_test')
    assert 'NOT PAPER CHASE' in scenario.title
    assert scenario.core_entities.clues == ['token']
    monkeypatch.setattr(repo, 'load_scenario', lambda _: pytest.fail('Independent retrieval loaded scenario'))
    assert repo.get_location('synthetic_test', 'room').clue_ids == ['token']
    with pytest.raises(KeyError): repo.get_clue('synthetic_test', 'missing')

@pytest.mark.parametrize('scenario_id', ['../synthetic_test', '/tmp', '', 'missing'])
def test_reject_invalid_scenario_ids(repo, scenario_id):
    with pytest.raises(KeyError): repo.load_scenario(scenario_id)

def test_npc_access_and_explicit_disclosure(repo, state):
    npc = repo.get_npc('synthetic_test', 'caretaker')
    assert {k.access for k in npc.knowledge_items} == {'public','conversational','guarded','keeper_only'}
    assert [k.id for k in repo.player_npc_knowledge('synthetic_test','caretaker',state)] == ['greeting']
    assert [k.id for k in repo.revealable_knowledge('synthetic_test','caretaker',state,'talk')] == ['greeting','small_talk']
    state.story_flags['trusted'] = True
    assert 'drawer_secret' in [k.id for k in repo.revealable_knowledge('synthetic_test','caretaker',state,'talk')]
    assert 'drawer_secret' not in [k.id for k in repo.player_npc_knowledge('synthetic_test','caretaker',state)]
    state.revealed_information.extend(['drawer_secret','internal'])
    assert [k.id for k in repo.player_npc_knowledge('synthetic_test','caretaker',state)] == ['greeting','drawer_secret']

def test_clue_existence_availability_and_discovery_are_separate(repo, state):
    assert repo.get_clue('synthetic_test','token').keeper_truth
    assert not repo.knows_clue('synthetic_test','token',state)
    assert repo.get_context('synthetic_test',state).available_clues == []
    state.story_flags['drawer_open'] = True
    context = repo.get_context('synthetic_test',state)
    assert [c.id for c in context.available_clues] == ['token']
    assert context.discovered_clues == []
    with pytest.raises(PermissionError): repo.player_clue('synthetic_test','token',state)
    with pytest.raises(PermissionError): repo.require_discovered_clues('synthetic_test',['token'],state)
    assert state.discovered_clues == []

def test_visibility_projections(repo, state):
    public = repo.player_location('synthetic_test','room').model_dump()
    assert set(public) == {'id','name','description','action_categories'}
    assert 'token' not in json.dumps(public)
    state.discovered_clues.append('token')
    assert set(repo.player_clue('synthetic_test','token',state).model_dump()) == {'id','reveal'}
    assert repo.get_clue('synthetic_test','token').keeper_truth != repo.player_clue('synthetic_test','token',state).reveal

def test_relevant_context(repo, state):
    state.story_flags['drawer_open'] = True
    context = repo.get_context('synthetic_test',state)
    assert context.location.id == 'room'
    assert [n.id for n in context.npcs] == ['caretaker']
    assert not hasattr(context,'keeper_truth')
    assert context.eligible_events == []
    state.current_location = 'hall'
    context = repo.get_context('synthetic_test',state)
    assert context.npcs == context.available_clues == context.eligible_events == context.eligible_encounters == []
    state.discovered_clues = ['token']
    assert [c.id for c in repo.get_context('synthetic_test',state).discovered_clues] == ['token']

@pytest.mark.parametrize('change', ['phase','period','day','required_flag','forbidden_flag','action','location','triggered'])
def test_event_gates(repo, state, change):
    state.phase = 'focused_investigation'
    state.game_time = GameTime(day=1, period='night')
    state.story_flags['drawer_open'] = True
    assert repo.event_eligible('synthetic_test','night_signal',state,'wait')
    assert [e.id for e in repo.get_context('synthetic_test',state,action='wait').eligible_events] == ['night_signal']
    action = 'wait'
    if change == 'phase': state.phase = 'open_investigation'
    if change == 'period': state.game_time.period = 'afternoon'
    if change == 'day':
        # Fixture has no day gate; an explicit day condition is independently supported.
        from app.scenario.models import Conditions
        assert not Conditions(day=2).matches(state)
        return
    if change == 'required_flag': state.story_flags['drawer_open'] = False
    if change == 'forbidden_flag': state.story_flags['signal_blocked'] = True
    if change == 'action': action = 'talk'
    if change == 'location': state.current_location = 'hall'
    if change == 'triggered': state.triggered_events.append('night_signal')
    assert not repo.event_eligible('synthetic_test','night_signal',state,action)
    assert repo.get_context('synthetic_test',state,action=action).eligible_events == []

def test_encounter_branch_requirements_and_unsupported_combat(repo, state):
    encounter = repo.get_encounter('synthetic_test','visitor')
    assert set(encounter.branches) == {'talk','flee','follow','attack'}
    assert encounter.branches['attack'].mechanic_support == 'unsupported'
    assert not encounter.branches['follow'].requirements.matches(state)
    state.discovered_clues.append('token')
    assert encounter.branches['follow'].requirements.matches(state)
    assert repo.get_context('synthetic_test',state).eligible_encounters == []
    state.story_flags['signal_heard'] = True
    assert [e.id for e in repo.get_context('synthetic_test',state).eligible_encounters] == ['visitor']

def test_discovery_phase_time_push_persist(repo, tmp_path):
    path = tmp_path/'game.sqlite3'
    states = GameStateRepository(path)
    session = states.create('synthetic_test', repo.load_scenario('synthetic_test').starting_state)
    assert session.state.discovered_clues == []
    saved = states.record_clue_discovery(session.session_id,'token',repo)
    assert saved.state.discovered_clues == ['token']
    assert states.record_clue_discovery(session.session_id,'token',repo).state.discovered_clues == ['token']
    def transition(state):
        state.phase = 'focused_investigation'
        state.game_time = GameTime(day=2,period='night')
        state.pending_push = PendingPush(check_id='test-failed-check',skill_name='Spot Hidden',skill_value=50,context='Synthetic failed drawer check',allowed=True,consequence_reference='Synthetic consequence')
    saved = states.update_state(session.session_id,transition)
    reloaded = GameStateRepository(path).get(session.session_id)
    assert reloaded == saved
    assert reloaded.state.phase == 'focused_investigation'
    assert reloaded.state.game_time == GameTime(day=2,period='night')
    assert reloaded.state.pending_push.allowed
    assert repo.player_clue('synthetic_test','token',reloaded.state).id == 'token'
    with connect(path) as db:
        document = json.loads(db.execute('SELECT document FROM sessions').fetchone()[0])
    assert document['state'] == reloaded.state.model_dump()
    assert repo.load_scenario('synthetic_test').starting_state.discovered_clues == []

def test_legacy_json_gets_defaults(tmp_path):
    states = GameStateRepository(tmp_path/'legacy.sqlite3')
    session = states.create('placeholder')
    old = session.model_dump()
    for key in ('phase','game_time','pending_push'): old['state'].pop(key)
    with connect(states.path) as db:
        db.execute('UPDATE sessions SET document=? WHERE session_id=?',(json.dumps(old),session.session_id))
    restored = states.get(session.session_id)
    assert restored.state.phase == 'open_investigation'
    assert restored.state.game_time == GameTime()
    assert restored.state.pending_push is None

def test_invalid_transition_rolls_back(tmp_path):
    states = GameStateRepository(tmp_path/'game.sqlite3')
    session = states.create('placeholder')
    with pytest.raises(ValidationError):
        states.update_state(session.session_id,lambda s: setattr(s,'phase','invalid'))
    assert states.get(session.session_id) == session


def test_fixture_reference_validation(repo):
    assert repo.validate_scenario('synthetic_test').id == 'synthetic_test'

@pytest.mark.parametrize('corruption', ['reference','duplicate','unknown_field','scenario_id'])
def test_invalid_authored_data_rejected(tmp_path, corruption):
    import shutil
    shutil.copytree(ROOT/'synthetic_test',tmp_path/'synthetic_test')
    filename = 'scenario.json' if corruption == 'scenario_id' else 'locations.json'
    path = tmp_path/'synthetic_test'/filename
    data = json.loads(path.read_text())
    if corruption == 'reference': data[0]['clue_ids'] = ['missing']
    if corruption == 'duplicate': data.append(data[0])
    if corruption == 'unknown_field': data[0]['unclassified_secret'] = 'should be rejected'
    if corruption == 'scenario_id': data['id'] = 'wrong'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError): JsonScenarioRepository(tmp_path).validate_scenario('synthetic_test')

def test_npc_revelation_persists(repo, tmp_path):
    states = GameStateRepository(tmp_path/'npc.sqlite3')
    session = states.create('synthetic_test')
    states.update_state(session.session_id,lambda state: state.revealed_information.append('drawer_secret'))
    restored = GameStateRepository(states.path).get(session.session_id)
    assert 'drawer_secret' in [k.id for k in repo.player_npc_knowledge('synthetic_test','caretaker',restored.state)]

def test_discovery_unknown_clue_rejected(repo, tmp_path):
    states = GameStateRepository(tmp_path/'game.sqlite3')
    session = states.create('synthetic_test')
    with pytest.raises(KeyError): states.record_clue_discovery(session.session_id,'missing',repo)
    assert states.get(session.session_id) == session
