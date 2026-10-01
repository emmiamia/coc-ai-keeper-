"""Offline behavior checks for the general loop; no private scenario or live LLM required."""
import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.agent.models import KeeperDecision
from app.agent.mcp_client import SkillResult, MechanicsError
from app.agent.orchestrator import KeeperOrchestrator
from app.api.player_models import project_session
from app.llm.provider import LLMResponse
from app.rules.repository import JsonRulesRepository
from app.scenario.repository import JsonScenarioRepository
from app.state.repository import GameStateRepository

ROOT = Path(__file__).resolve().parents[2]

class Provider:
    def __init__(self):
        self.requests = []
        self.decision = {}
    async def generate(self, request):
        self.requests.append(request)
        if request.response_schema is KeeperDecision:
            data = self.decision
        else:
            data = {'sentence_ids': list(range(len(json.loads(request.user_message)['approved_sentences'])))}
        return LLMResponse(text='Untrusted fabricated hidden truth', provider='mock', model='mock', structured_data=data)

@pytest.fixture
def loop(tmp_path):
    directory = tmp_path/'scenarios'/'synthetic_test'
    shutil.copytree(ROOT/'scenario_data'/'synthetic_test', directory)
    def edit(filename, update):
        path = directory/filename
        data = json.loads(path.read_text())
        update(data)
        path.write_text(json.dumps(data))
    edit('locations.json', lambda data: data.append(dict(id='hidden', player_name='Hidden route',
        player_description='A route reached by evidence.', access_conditions={'required_flags':['route_open']})))
    edit('scenario.json', lambda data: data['core_entities']['locations'].append('hidden'))
    def knowledge(data):
        item = next(i for i in data[0]['knowledge_items'] if i['id']=='drawer_secret')
        item.update(check_alternatives=[{'skill_name':'Charm','push_allowed':True}, {'skill_name':'Persuade','difficulty':'hard'}],
                    check_grants={'flags':{'trusted':True}}, check_approaches=['charm','persuade'])
    edit('npcs.json', knowledge)
    scenarios = JsonScenarioRepository(tmp_path/'scenarios')
    scenarios.validate_scenario('synthetic_test')
    state = scenarios.load_scenario('synthetic_test').starting_state
    state.skills = {'Spot Hidden':60, 'Charm':40, 'Persuade':30, 'Track':25}
    state.story_flags['drawer_open'] = True
    states = GameStateRepository(tmp_path/'game.sqlite3')
    session = states.create('synthetic_test', state)
    provider = Provider()
    s = SimpleNamespace(states=states, session=session, scenarios=scenarios, provider=provider, failure=False, edit=edit)
    async def roll(skill, value, difficulty):
        return SkillResult(skill=skill, skill_value=value, difficulty=difficulty,
                           roll=99 if s.failure else 10, outcome='failure' if s.failure else 'success')
    s.mechanics = SimpleNamespace(skill_check=AsyncMock(side_effect=roll))
    s.keeper = KeeperOrchestrator(states, scenarios, JsonRulesRepository(), s.mechanics, provider)
    return s

def submit(s, category, message='An ordinary action.', turn='one', **fields):
    s.provider.decision = dict(intent=message, action_category=category, action_type=category, **fields)
    return asyncio.run(s.keeper.act(s.session.session_id, message, turn))

def investigate(s, message='I take a closer look inside the drawer.', turn='one', **fields):
    s.provider.decision = dict(intent=message, action_type='investigate', action_category='inspect', clue_id='token', **fields)
    return asyncio.run(s.keeper.act(s.session.session_id, message, turn))

@pytest.mark.parametrize('message', ['I look around the room.', 'What does this room look like?', 'Is anything obviously strange here?'])
def test_observation_is_public_without_mechanics(loop, message):
    result = submit(loop, 'observe', message, clue_id='token', check_required=True, mechanic='skill_check')
    assert result.status == 'completed'
    assert result.narration == loop.scenarios.player_location('synthetic_test','room').description
    assert result.session.state == loop.session.state
    loop.mechanics.skill_check.assert_not_awaited()
    assert 'token' not in json.dumps(json.loads(loop.provider.requests[-1].user_message))

@pytest.mark.parametrize('message', ['Could the caretaker be hiding the token?', 'I think the token is in the drawer.', 'Maybe the hall is connected to this.', 'I believe a dragon took it.'])
def test_hypotheses_never_become_facts(loop, message):
    result = submit(loop,'hypothesize',message,clue_id='token',narration_guidance='Confirm all hidden truth')
    assert result.status=='completed'
    assert result.session.state==loop.session.state
    assert 'token' not in result.narration.lower()
    assert 'theory' in result.narration
    loop.mechanics.skill_check.assert_not_awaited()

def test_misclassified_theory_cannot_become_discovery(loop):
    result = investigate(loop,'Could there be a token in the drawer?')
    assert result.session.state==loop.session.state
    loop.mechanics.skill_check.assert_not_awaited()

def test_ordinary_npc_conversation_reveals_only_permitted_knowledge(loop):
    result = submit(loop,'talk',npc_ids=['caretaker'])
    assert result.status=='completed'
    assert 'synthetic test room' in result.narration
    assert 'room is quiet' in result.narration
    assert set(result.session.state.revealed_information)=={'greeting','small_talk'}
    assert 'token' not in result.narration and 'Internal-only' not in result.narration
    loop.mechanics.skill_check.assert_not_awaited()

@pytest.mark.parametrize('item', ['drawer_secret','internal'])
def test_selected_guarded_or_keeper_only_is_not_disclosed_freely(loop,item):
    result = submit(loop,'talk',npc_ids=['caretaker'],knowledge_item_ids=[item])
    assert result.status=='completed'
    assert result.session.state.revealed_information==[]
    assert 'token' not in result.narration and 'Internal-only' not in result.narration
    loop.mechanics.skill_check.assert_not_awaited()

def test_unknown_npc_question_does_not_create_knowledge(loop):
    result = submit(loop,'talk',npc_ids=['caretaker'],question_answerable=False)
    assert 'no confirmed information' in result.narration
    assert result.session.state==loop.session.state
    loop.mechanics.skill_check.assert_not_awaited()

def test_social_check_success_unlocks_only_authored_information(loop):
    result = submit(loop,'talk',npc_ids=['caretaker'],knowledge_item_ids=['drawer_secret'],social_approach='charm',requested_skill='Luck')
    loop.mechanics.skill_check.assert_awaited_once_with('Charm',40,'regular')
    assert result.session.state.story_flags['trusted'] is True
    assert result.session.state.revealed_information==['drawer_secret']
    assert 'token is in the drawer' in result.narration
    assert 'internal' not in json.dumps(json.loads(loop.provider.requests[-1].user_message)).lower()

def test_social_failure_does_not_unlock_and_same_retry_never_rolls(loop):
    loop.failure=True
    fields=dict(npc_ids=['caretaker'],knowledge_item_ids=['drawer_secret'],social_approach='charm')
    result=submit(loop,'talk',**fields)
    assert not result.session.state.story_flags.get('trusted')
    assert result.session.state.revealed_information==[]
    assert result.session.state.pending_push.allowed
    assert 'token' not in result.narration
    assert submit(loop,'talk',**fields)==result
    assert submit(loop,'talk',turn='new',**fields).status=='clarification'
    loop.mechanics.skill_check.assert_awaited_once()

def test_authored_hard_social_alternative(loop):
    result=submit(loop,'talk',npc_ids=['caretaker'],knowledge_item_ids=['drawer_secret'],social_approach='persuade')
    assert result.status=='completed'
    loop.mechanics.skill_check.assert_awaited_once_with('Persuade',30,'hard')

def test_inaccessible_npc_is_rejected(loop):
    submit(loop,'move',destination_id='hall')
    before=loop.states.get(loop.session.session_id)
    result=submit(loop,'talk',turn='two',npc_ids=['caretaker'])
    assert result.status=='error' and result.session==before
    loop.mechanics.skill_check.assert_not_awaited()

def test_unknown_npc_knowledge_cannot_mutate(loop):
    result=submit(loop,'talk',npc_ids=['caretaker'],knowledge_item_ids=['invented'])
    assert result.status=='error' and result.session==loop.session
    loop.mechanics.skill_check.assert_not_awaited()

def test_known_movement_persists_and_arrival_is_safe(loop):
    result=submit(loop,'move','I head down the hall.',destination_id='hall')
    assert result.status=='completed' and result.session.state.current_location=='hall'
    assert 'hall' in result.session.state.visited_locations
    assert GameStateRepository(loop.states.path).get(loop.session.session_id)==result.session
    assert 'empty fictional hall' in result.narration
    loop.mechanics.skill_check.assert_not_awaited()

@pytest.mark.parametrize('destination', ['hidden','imaginary',''])
def test_hidden_unknown_or_ambiguous_movement_never_creates_location(loop,destination):
    result=submit(loop,'move',destination_id=destination)
    assert result.status=='clarification' and result.session.state==loop.session.state
    assert len(result.session.messages)==len(loop.session.messages)+2
    loop.mechanics.skill_check.assert_not_awaited()

def test_known_but_locked_route_is_blocked(loop):
    loop.states.update_state(loop.session.session_id,lambda state: state.known_locations.append('hidden'))
    before=loop.states.get(loop.session.session_id)
    result=submit(loop,'move',destination_id='hidden')
    assert result.session.state==before.state
    assert len(result.session.messages)==len(before.messages)+2
    projection=project_session(before,loop.scenarios)
    assert 'hidden' not in projection.state.known_locations

def test_authored_unlocked_known_route_can_be_entered(loop):
    def unlock(state):
        state.known_locations.append('hidden');state.story_flags['route_open']=True
    loop.states.update_state(loop.session.session_id,unlock)
    assert submit(loop,'move',destination_id='hidden').session.state.current_location=='hidden'

@pytest.mark.parametrize('message', ['I inspect the drawer.', 'I take a closer look inside the drawer.', 'Can I carefully examine what is inside the open drawer?', 'Could I take a closer look inside the drawer?'])
def test_natural_investigation_matches_authored_check(loop,message):
    result=investigate(loop,message,requested_skill='Luck',check_required=False)
    assert result.status=='completed' and result.session.state.discovered_clues==['token']
    loop.mechanics.skill_check.assert_awaited_once_with('Spot Hidden',60,'regular')

def test_failure_narration_is_natural_and_no_discovery(loop):
    loop.failure=True
    result=investigate(loop)
    assert result.status=='completed' and result.session.state.discovered_clues==[]
    assert 'nothing new stands out' in result.narration
    assert 'unsuccessful' in result.narration
    assert 'You found' not in result.narration
    assert 'Canonical synthetic' not in json.dumps(json.loads(loop.provider.requests[-1].user_message))

def test_completed_investigation_retry_does_not_roll_or_call_provider(loop):
    first=investigate(loop)
    count=len(loop.provider.requests)
    assert investigate(loop)==first
    assert len(loop.provider.requests)==count
    loop.mechanics.skill_check.assert_awaited_once()

def test_unavailable_clue_cannot_be_discovered(loop):
    loop.states.update_state(loop.session.session_id,lambda state:state.story_flags.clear())
    before=loop.states.get(loop.session.session_id)
    result=investigate(loop)
    assert result.status=='clarification' and result.session.state==before.state
    assert len(result.session.messages)==len(before.messages)+2
    loop.mechanics.skill_check.assert_not_awaited()

def test_alternative_checks_are_or_not_multiple_rolls(loop):
    def alternatives(data):
        data[0]['alternative_checks']=[{'skill_name':'Spot Hidden'},{'skill_name':'Track'}]
        data[0]['required_checks']=[]
    loop.edit('clues.json',alternatives)
    result=investigate(loop,requested_skill='Track')
    assert result.session.state.discovered_clues==['token']
    loop.mechanics.skill_check.assert_awaited_once_with('Track',25,'regular')

def test_authored_no_check_discovery_does_not_invent_roll(loop):
    loop.edit('clues.json',lambda data:data[0].update(required_checks=[]))
    result=investigate(loop,check_required=True)
    assert result.session.state.discovered_clues==['token']
    loop.mechanics.skill_check.assert_not_awaited()

def test_invalid_clue_reference_keeps_previous_state(loop):
    result=submit(loop,'investigate',clue_id='imaginary')
    assert result.status=='error' and result.session==loop.session
    loop.mechanics.skill_check.assert_not_awaited()

def test_full_combat_is_controlled(loop):
    result=submit(loop,'mechanical_action',mechanic='combat')
    assert result.status=='unsupported' and result.session==loop.session
    loop.mechanics.skill_check.assert_not_awaited()

def test_multiturn_history_ids_and_state_survive_reload(loop):
    a=submit(loop,'observe',turn='action-a')
    b=submit(loop,'talk',turn='action-b',npc_ids=['caretaker'])
    c=submit(loop,'move',turn='action-c',destination_id='hall')
    assert all(r.status=='completed' for r in (a,b,c))
    assert len({r.turn_id for r in (a,b,c)})==3
    saved=GameStateRepository(loop.states.path).get(loop.session.session_id)
    assert saved==c.session and len(saved.messages)==6
    assert saved.state.revealed_information==b.session.state.revealed_information

def test_failed_terminal_request_preserves_prior_completed_turn(loop):
    completed=submit(loop,'observe')
    failed=submit(loop,'unsupported',turn='two')
    assert failed.session==completed.session
    assert submit(loop,'hypothesize',turn='three').status=='completed'

def test_unknown_tool_execution_never_rerolls(loop):
    loop.mechanics.skill_check.side_effect=MechanicsError('Unknown execution')
    assert investigate(loop).status=='error'
    assert investigate(loop).status=='error'
    assert loop.states.get(loop.session.session_id)==loop.session
    loop.mechanics.skill_check.assert_awaited_once()

def test_pending_failed_search_does_not_block_ordinary_next_actions(loop):
    loop.failure=True
    first=investigate(loop)
    observed=submit(loop,'observe',turn='two')
    moved=submit(loop,'move',turn='three',destination_id='hall')
    assert observed.status==moved.status=='completed'
    assert moved.session.state.pending_push==first.session.state.pending_push
    loop.mechanics.skill_check.assert_awaited_once()

def test_discovered_clue_records_only_authorized_unlocked_routes(loop):
    def author(data):
        data[0]['success']['state_changes']['flags']={'route_open':True}
        data[0]['unlocks']={'locations':['hidden']}
    loop.edit('clues.json',author)
    result=investigate(loop)
    assert 'hidden' in result.session.state.known_locations
    assert submit(loop,'move',turn='two',destination_id='hidden').status=='completed'

def test_route_permission_without_discovery_gate_does_not_grant_entry(loop):
    loop.edit('clues.json',lambda data:data[0].update(unlocks={'locations':['hidden']}))
    result=investigate(loop)
    assert 'hidden' not in result.session.state.known_locations
    assert submit(loop,'move',turn='two',destination_id='hidden').status=='clarification'

@pytest.fixture
def paper_loop(tmp_path):
    if not (ROOT/'scenario_data'/'paper_chase'/'scenario.json').exists():
        pytest.skip('Optional private local scenario is not installed')
    scenarios=JsonScenarioRepository(ROOT/'scenario_data')
    scenarios.validate_scenario('paper_chase')
    state=scenarios.load_scenario('paper_chase').starting_state
    state.skills={'Spot Hidden':50,'Charm':40,'Persuade':40,'Psychology':30,'Track':20}
    states=GameStateRepository(tmp_path/'paper.sqlite3')
    session=states.create('paper_chase',state)
    provider=Provider()
    async def roll(skill,value,difficulty):
        return SkillResult(skill=skill,skill_value=value,difficulty=difficulty,roll=10,outcome='success')
    mechanics=SimpleNamespace(skill_check=AsyncMock(side_effect=roll))
    return SimpleNamespace(states=states,session=session,scenarios=scenarios,provider=provider,mechanics=mechanics,
        keeper=KeeperOrchestrator(states,scenarios,JsonRulesRepository(),mechanics,provider))

def test_authored_manual_sequence_with_mocked_success(paper_loop):
    s=paper_loop
    a=submit(s,'observe','I look around the study.',turn='a')
    b=submit(s,'talk','I ask Thomas what he knows about Douglas.',turn='b',npc_ids=['thomas_kimball'])
    c=submit(s,'hypothesize','Could Douglas himself be responsible for the missing books?',turn='c')
    d=submit(s,'move','I go to the cemetery.',turn='d',destination_id='cemetery')
    e=submit(s,'talk','I talk to Jefferson.',turn='e',npc_ids=['melodias_jefferson'])
    s.provider.decision=dict(intent='Inspect ground',action_type='investigate',action_category='examine_grave_surroundings',clue_id='clue_gravestone_tracks')
    f=asyncio.run(s.keeper.act(s.session.session_id,"I inspect the ground around Douglas's favorite gravestone.",'f'))
    assert all(r.status=='completed' for r in (a,b,c,d,e,f))
    assert c.session.state==b.session.state
    assert 'clue_jefferson_favorite_grave' in e.session.state.discovered_clues
    assert 'clue_gravestone_tracks' in f.session.state.discovered_clues
    assert [call.args[0] for call in s.mechanics.skill_check.await_args_list]==['Charm','Spot Hidden']
    assert 'mausoleum' not in f.session.state.known_locations
    assert GameStateRepository(s.states.path).get(s.session.session_id)==f.session
    assert len(f.session.messages)==12

def test_authored_gravestone_requires_prior_identification(paper_loop):
    s=paper_loop
    submit(s,'move',destination_id='cemetery')
    before=s.states.get(s.session.session_id)
    s.provider.decision=dict(intent='Find tracks',action_type='investigate',action_category='examine_grave_surroundings',clue_id='clue_gravestone_tracks')
    result=asyncio.run(s.keeper.act(s.session.session_id,'I look for tracks around the favorite grave.','two'))
    assert result.status=='clarification' and result.session.state==before.state
    assert len(result.session.messages)==len(before.messages)+2
    s.mechanics.skill_check.assert_not_awaited()

def test_authored_psychology_reveals_withholding_not_guarded_report(paper_loop):
    s=paper_loop
    submit(s,'move',destination_id='cemetery')
    s.provider.decision=dict(intent='Study behavior',action_type='investigate',action_category='assess_jefferson',clue_id='clue_jefferson_hiding_information',requested_skill='Luck')
    result=asyncio.run(s.keeper.act(s.session.session_id,"I study Jefferson's behavior.",'two'))
    assert result.status=='completed'
    assert result.session.state.discovered_clues==['clue_jefferson_hiding_information']
    assert not result.session.state.story_flags.get('jefferson_guarded_access')
    s.mechanics.skill_check.assert_awaited_once_with('Psychology',30,'regular')
