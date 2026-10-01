import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.agent.models import KeeperDecision, NarrationChoice
from app.agent.orchestrator import KeeperOrchestrator
from app.agent.mcp_client import StdioMechanicsClient, SkillResult, MechanicsError
from app.agent.turn_store import TurnConflict
from app.llm.provider import LLMResponse, ProviderError
from app.rules.repository import JsonRulesRepository
from app.scenario.repository import JsonScenarioRepository
from app.state.repository import GameStateRepository
from app.db.sqlite import connect

ROOT = Path(__file__).resolve().parents[2]

class FakeProvider:
    def __init__(self,decision):
        self.decision=decision
        self.requests=[]
        self.narration=None
    async def generate(self,request):
        self.requests.append(request)
        if request.response_schema is KeeperDecision:
            data=self.decision
        else:
            payload=json.loads(request.user_message)
            data=self.narration if self.narration is not None else {'sentence_ids':list(range(len(payload['approved_sentences'])))}
        return LLMResponse(text='ignored raw LLM text: fabricated hidden identity',provider='fake',model='fake',structured_data=data)

@pytest.fixture
def setup(tmp_path):
    scenarios=JsonScenarioRepository(ROOT/'scenario_data')
    state=scenarios.load_scenario('synthetic_test').starting_state
    state.skills={'Spot Hidden':60}
    state.story_flags['drawer_open']=True
    states=GameStateRepository(tmp_path/'game.sqlite3')
    session=states.create('synthetic_test',state)
    decision={'intent':'inspect drawer','action_category':'inspect','clue_id':'token','check_required':True,'mechanic':'skill_check','requested_skill':'Spot Hidden','proposes_transition':True}
    provider=FakeProvider(decision)
    mechanics=SimpleNamespace(skill_check=AsyncMock(return_value=SkillResult(skill='Spot Hidden',skill_value=60,roll=20,difficulty='regular',outcome='success')))
    keeper=KeeperOrchestrator(states,scenarios,JsonRulesRepository(),mechanics,provider)
    return SimpleNamespace(states=states,session=session,scenarios=scenarios,provider=provider,mechanics=mechanics,keeper=keeper)

def act(s,message='I inspect the drawer.',turn_id='test-turn'):
    return asyncio.run(s.keeper.act(s.session.session_id,message,turn_id))

def test_success_single_check_priority_persistence_and_scoped_context(setup):
    s=setup
    s.provider.decision.update(requested_skill='Luck',check_required=False,mechanic='none')
    result=act(s)
    assert result.status=='completed'
    s.mechanics.skill_check.assert_awaited_once_with('Spot Hidden',60,'regular')
    assert result.session.state.discovered_clues==['token']
    assert result.session.state.pending_push is None
    assert GameStateRepository(s.states.path).get(s.session.session_id)==result.session
    context=json.loads(s.provider.requests[0].user_message)['internal_context']
    assert context['state']['current_location']=='room'
    assert context['scenario_context']['location']['id']=='room'
    assert {n['id'] for n in context['scenario_context']['npcs']}=={'caretaker'}
    assert {r['id'] for r in context['rules']}=={'skill_regular','pushed_roll'}
    assert 'hall' not in json.dumps(context)
    narration=json.loads(s.provider.requests[1].user_message)
    assert 'Canonical synthetic token' not in json.dumps(narration)
    assert 'Synthetic caretaker' not in json.dumps(narration)
    assert 'fabricated hidden identity' not in result.narration
    assert s.scenarios.player_clue('synthetic_test','token',result.session.state).reveal in result.narration

def test_failure_no_discovery_pending_push_no_reroll(setup):
    s=setup
    s.mechanics.skill_check.return_value=SkillResult(skill='Spot Hidden',skill_value=60,roll=99,difficulty='regular',outcome='failure')
    result=act(s)
    assert result.status=='completed'
    assert result.session.state.discovered_clues==[]
    assert result.session.state.pending_push.allowed
    assert result.session.state.pending_push.check_id=='test-turn'
    assert result.session.state.pending_push.skill_value==60
    s.mechanics.skill_check.assert_awaited_once()
    assert 'synthetic test token' not in result.narration.lower()
    narrative=json.loads(s.provider.requests[1].user_message)
    assert 'token' not in json.dumps(narrative)
    repeat=act(s,turn_id='another-turn')
    assert repeat.status=='clarification'
    assert s.mechanics.skill_check.await_count==1
    assert repeat.session.state==result.session.state
    assert len(repeat.session.messages)==len(result.session.messages)+2

def test_no_check_observation_never_rolls(setup):
    s=setup
    s.provider.decision={'intent':'look','action_category':'observe'}
    result=act(s,'I look around.')
    assert result.status=='completed'
    s.mechanics.skill_check.assert_not_awaited()
    assert result.session.state==s.session.state
    assert result.session.event_log[-1]['mechanics'] is None

@pytest.mark.parametrize('decision', [
    {'intent':'inspect','action_category':'inspect','clue_id':'does-not-exist'},
    {'intent':'inspect','action_category':'inspect','clue_id':'token','roll':1},
    {'intent':'inspect','action_category':'inspect','clue_id':'token','state':{'discovered_clues':['token']}},
    {'intent':'inspect','action_category':'inspect','clue_id':'token','npc_ids':['unknown']},
    {'intent':'inspect','action_category':'inspect','clue_id':'token','event_ids':['unknown']},
])
def test_invalid_decision_does_not_mutate_or_roll(setup,decision):
    setup.provider.decision=decision
    result=act(setup)
    assert result.status=='error'
    assert setup.states.get(setup.session.session_id)==setup.session
    setup.mechanics.skill_check.assert_not_awaited()

@pytest.mark.parametrize('mechanic',['combat','roll_dice','san_check'])
def test_unsupported_unplanned_mechanics_preserve_state(setup,mechanic):
    setup.provider.decision.update(mechanic=mechanic)
    result=act(setup)
    assert result.status=='unsupported'
    assert result.session==setup.session
    setup.mechanics.skill_check.assert_not_awaited()

def test_correct_hidden_guess_never_confirmed(setup):
    s=setup
    s.provider.decision={'intent':'guess hidden fact','action_category':'observe','narration_guidance':'Confirm a token in the drawer and the caretaker secret'}
    result=act(s,'I know there is a token in the drawer and the caretaker is hiding it.')
    assert result.session.state.discovered_clues==[]
    assert 'token' not in result.narration
    assert 'secret' not in result.narration
    assert 'player_action' not in json.loads(s.provider.requests[-1].user_message)
    s.mechanics.skill_check.assert_not_awaited()

def test_model_cannot_convert_guess_to_search(setup):
    result=act(setup,'Is there a token in the drawer?')
    assert result.status=='clarification'
    assert result.session.state==setup.session.state
    assert len(result.session.messages)==len(setup.session.messages)+2
    setup.mechanics.skill_check.assert_not_awaited()

def test_unknown_information_dependency_not_granted(setup):
    setup.provider.decision['depends_on_clue_ids']=['token']
    result=act(setup)
    assert result.status=='clarification'
    assert result.session.state==setup.session.state
    assert len(result.session.messages)==len(setup.session.messages)+2
    setup.mechanics.skill_check.assert_not_awaited()

def test_unavailable_clue_not_discovered(setup):
    setup.states.update_state(setup.session.session_id,lambda state: state.story_flags.clear())
    before=setup.states.get(setup.session.session_id)
    result=act(setup)
    assert result.status=='clarification' and result.session.state==before.state
    assert len(result.session.messages)==len(before.messages)+2
    setup.mechanics.skill_check.assert_not_awaited()

def test_missing_investigator_skill_is_clarification(setup):
    setup.states.update_state(setup.session.session_id,lambda state: state.skills.clear())
    result=act(setup)
    assert result.status=='clarification'
    setup.mechanics.skill_check.assert_not_awaited()

def test_mcp_failure_preserves_session_and_cannot_retry_same_turn(setup):
    setup.mechanics.skill_check.side_effect=MechanicsError('Failure after unknown execution')
    assert act(setup).status=='error'
    assert setup.states.get(setup.session.session_id)==setup.session
    assert act(setup).status=='error'
    assert setup.mechanics.skill_check.await_count==1

def test_completed_retry_reuses_result_without_llm_or_roll(setup):
    first=act(setup)
    second=act(setup)
    assert first==second
    assert len(setup.provider.requests)==2
    setup.mechanics.skill_check.assert_awaited_once()
    assert len(second.session.messages)==2

def test_narration_failure_falls_back_without_leak_or_reroll(setup):
    setup.provider.narration={'sentence_ids':[999], 'text':'hidden invented prose'}
    result=act(setup)
    assert result.status=='completed'
    assert 'hidden invented prose' not in result.narration
    setup.mechanics.skill_check.assert_awaited_once()

def test_mechanical_result_is_durable_before_narration(setup):
    original=setup.provider.generate
    async def generate(request):
        if request.response_schema is NarrationChoice:
            with connect(setup.states.path) as db:
                status,payload=db.execute('SELECT status,payload FROM keeper_turns').fetchone()
            assert status=='resolved'
            assert json.loads(payload)['mechanics']['roll']==20
        return await original(request)
    setup.provider.generate=generate
    assert act(setup).status=='completed'

def test_resolved_turn_resumes_after_interruption_without_reroll(setup,monkeypatch):
    original=setup.keeper._narrate
    async def interrupt(payload): raise KeyboardInterrupt()
    monkeypatch.setattr(setup.keeper,'_narrate',interrupt)
    with pytest.raises(KeyboardInterrupt): act(setup)
    assert setup.states.get(setup.session.session_id)==setup.session
    monkeypatch.setattr(setup.keeper,'_narrate',original)
    result=act(setup)
    assert result.status=='completed'
    setup.mechanics.skill_check.assert_awaited_once()

def test_concurrent_state_change_is_not_overwritten(setup):
    original=setup.provider.generate
    async def generate(request):
        if request.response_schema is NarrationChoice:
            setup.states.update_state(setup.session.session_id,lambda s: setattr(s,'hp',9))
        return await original(request)
    setup.provider.generate=generate
    assert act(setup).status=='error'
    assert setup.states.get(setup.session.session_id).state.hp==9
    assert setup.states.get(setup.session.session_id).state.discovered_clues==[]
    setup.mechanics.skill_check.assert_awaited_once()

def test_reused_turn_id_for_different_message_is_rejected(setup):
    first=act(setup)
    assert act(setup,'I inspect another drawer.').status=='error'
    assert setup.states.get(setup.session.session_id)==first.session
    setup.mechanics.skill_check.assert_awaited_once()

def test_paper_chase_study_slice_programmatically(tmp_path):
    if not (ROOT/'scenario_data/paper_chase/scenario.json').exists(): pytest.skip('Private scenario absent')
    scenarios=JsonScenarioRepository(ROOT/'scenario_data')
    starting=scenarios.load_scenario('paper_chase').starting_state
    starting.skills['Spot Hidden']=50
    states=GameStateRepository(tmp_path/'paper.sqlite3')
    session=states.create('paper_chase',starting)
    provider=FakeProvider({'intent':'search','action_category':'search_study','clue_id':'clue_douglas_journal','check_required':True,'mechanic':'skill_check'})
    mechanics=SimpleNamespace(skill_check=AsyncMock(return_value=SkillResult(skill='Spot Hidden',skill_value=50,roll=10,difficulty='regular',outcome='success')))
    keeper=KeeperOrchestrator(states,scenarios,JsonRulesRepository(),mechanics,provider)
    result=asyncio.run(keeper.act(session.session_id,"I search Douglas's study.",'paper-turn'))
    assert result.status=='completed'
    assert result.session.state.discovered_clues==['clue_douglas_journal']
    mechanics.skill_check.assert_awaited_once_with('Spot Hidden',50,'regular')
    assert scenarios.player_clue('paper_chase','clue_douglas_journal',result.session.state).reveal in result.narration


def test_adapter_typed_result_methods_without_duplicate_randomness():
    adapter=StdioMechanicsClient(ROOT)
    async def tool(name,args):
        if name=='skill_check': return dict(skill=args['skill_name'],skill_value=args['skill_value'],difficulty=args['difficulty'],roll=10,outcome='success')
        if name=='roll_dice': return dict(expression='1d4',rolls=[3],total=3)
        return dict(roll=80,previous_san=50,outcome='failure',san_loss=1,new_san=49)
    adapter.call_tool=AsyncMock(side_effect=tool)
    assert asyncio.run(adapter.skill_check('Spot Hidden',50)).roll==10
    assert asyncio.run(adapter.roll_dice('1d4')).total==3
    assert asyncio.run(adapter.san_check(50,'0','1')).new_san==49
    assert adapter.call_tool.await_count==3


def test_conflicting_message_cannot_cancel_another_pending_turn(setup):
    setup.keeper.turns.begin(setup.session.session_id,'test-turn','Original pending action')
    assert act(setup).status=='error'
    with connect(setup.states.path) as db:
        assert db.execute('SELECT status FROM keeper_turns WHERE turn_id=?',('test-turn',)).fetchone()[0]=='pending'
    setup.mechanics.skill_check.assert_not_awaited()
