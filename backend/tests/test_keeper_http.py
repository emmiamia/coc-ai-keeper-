import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.agent.models import KeeperDecision
from app.agent.mcp_client import SkillResult, MechanicsError
from app.llm.provider import LLMResponse, ProviderError

ROOT=Path(__file__).resolve().parents[2]

class Provider:
    def __init__(self): self.requests=[]
    async def generate(self,request):
        self.requests.append(request)
        if request.response_schema is KeeperDecision:
            data={'intent':'search','action_category':'search_study','clue_id':'clue_douglas_journal','check_required':True,'mechanic':'skill_check'}
        else:
            data={'sentence_ids':list(range(len(json.loads(request.user_message)['approved_sentences'])))}
        return LLMResponse(text='untrusted hidden prose',provider='mock',model='mock',structured_data=data)

@pytest.fixture
def setup(tmp_path):
    if not (ROOT/'scenario_data/paper_chase/scenario.json').exists(): pytest.skip('Private local scenario absent')
    provider=Provider()
    mechanics=SimpleNamespace(skill_check=AsyncMock(return_value=SkillResult(skill='Spot Hidden',skill_value=50,roll=10,difficulty='regular',outcome='success')))
    path=tmp_path/'game.sqlite3'
    app=create_app(path,real_keeper=True,provider=provider,mechanics=mechanics)
    client=TestClient(app)
    created=client.post('/api/game/new',json={})
    assert created.status_code==201
    return SimpleNamespace(app=app,client=client,session=created.json(),path=path,provider=provider,mechanics=mechanics)

def action(s,turn_id='http-turn'):
    return s.client.post('/api/game/'+s.session['session_id']+'/action',json={'message':"I search Douglas's study.",'turn_id':turn_id})

def test_real_http_route_success_projection_and_reload(setup):
    s=setup
    assert s.session['scenario_id']=='paper_chase'
    assert s.session['state']['current_location']=='kimball_house'
    assert s.session['state']['discovered_clues']==[]
    assert len(s.session['messages'])==1
    result=action(s)
    assert result.status_code==200
    saved=result.json()
    s.mechanics.skill_check.assert_awaited_once_with('Spot Hidden',50,'regular')
    assert saved['state']['discovered_clues']==['clue_douglas_journal']
    assert saved['messages'][-2]['role']=='player'
    assert saved['messages'][-1]['role']=='keeper'
    assert 'untrusted hidden prose' not in result.text
    assert 'internal_context' not in result.text and 'requested_skill' not in result.text
    assert 'event_log' not in saved and 'story_flags' not in saved['state']
    assert 'pending_push' not in saved['state'] and 'npc_state' not in saved['state']
    restarted=TestClient(create_app(s.path,real_keeper=True,provider=s.provider,mechanics=s.mechanics))
    assert restarted.get('/api/game/'+saved['session_id']).json()==saved
    assert restarted.get('/api/game/'+saved['session_id']+'/state').json()==saved['state']


def test_internal_persisted_state_is_not_exposed(setup):
    s=setup
    def secret(state):
        state.story_flags['SECRET_FLAG']=True
        state.npc_state={'internal':'PRIVATE_NPC_TRUTH'}
        state.custom_world_state={'truth':'PRIVATE_WORLD_TRUTH'}
        state.revealed_information=['keeper_only_reference']
    s.app.state.states.update_state(s.session['session_id'],secret)
    response=s.client.get('/api/game/'+s.session['session_id'])
    assert response.status_code==200
    for private in ('SECRET_FLAG','PRIVATE_NPC_TRUTH','PRIVATE_WORLD_TRUTH','keeper_only_reference','keeper_truth','knowledge_items'):
        assert private not in response.text


def test_failure_check_has_no_clue_leak(setup):
    s=setup
    s.mechanics.skill_check.return_value=SkillResult(skill='Spot Hidden',skill_value=50,roll=99,difficulty='regular',outcome='failure')
    response=action(s)
    assert response.status_code==200
    assert response.json()['state']['discovered_clues']==[]
    assert response.json()['state']['push_available']
    assert 'clue_douglas_journal' not in response.text
    assert 'keeper_truth' not in response.text
    s.mechanics.skill_check.assert_awaited_once()

@pytest.mark.parametrize('failure',['gemini','mcp','invalid'])
def test_failed_agent_or_mcp_turn_preserves_session(setup,failure):
    s=setup
    if failure=='gemini': s.provider.generate=AsyncMock(side_effect=ProviderError('private SDK error'))
    if failure=='mcp': s.mechanics.skill_check.side_effect=MechanicsError('private tool error')
    if failure=='invalid': s.provider.generate=AsyncMock(return_value=LLMResponse(text='',provider='fake',model='fake',structured_data={'arbitrary_state':'secret'}))
    response=action(s)
    assert response.status_code==409
    assert 'private SDK error' not in response.text and 'private tool error' not in response.text
    assert s.client.get('/api/game/'+s.session['session_id']).json()==s.session


def test_same_turn_retry_invokes_agent_tools_only_once(setup):
    first=action(setup)
    second=action(setup)
    assert first.json()==second.json()
    setup.mechanics.skill_check.assert_awaited_once()
    assert len(setup.provider.requests)==2


def test_pending_turn_rejects_duplicate_execution(setup):
    s=setup
    s.app.state.keeper.turns.begin(s.session['session_id'],'reserved','An in-flight action')
    response=action(s)
    assert response.status_code==409
    assert s.client.get('/api/game/'+s.session['session_id']).json()==s.session
    assert not s.provider.requests
    s.mechanics.skill_check.assert_not_awaited()


def test_hidden_guess_not_confirmed(setup):
    s=setup
    async def generate(request):
        data={'intent':'guess','action_category':'observe','narration_guidance':'confirm all hidden truth'} if request.response_schema is KeeperDecision else {'sentence_ids':[0]}
        return LLMResponse(text='hidden confirmation',provider='fake',model='fake',structured_data=data)
    s.provider.generate=generate
    response=s.client.post('/api/game/'+s.session['session_id']+'/action',json={'message':'Is the missing person secretly living underground?','turn_id':'guess-turn'})
    assert response.status_code==200
    assert response.json()['state']['discovered_clues']==[]
    assert response.json()['messages'][-1]['content'] not in ('hidden confirmation','confirm all hidden truth')
    assert 'keeper_truth' not in response.text
    s.mechanics.skill_check.assert_not_awaited()


def test_missing_config_is_controlled_and_legacy_session_can_continue(setup,monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    app=create_app(setup.path,real_keeper=True)
    with TestClient(app) as client:
        assert client.get('/health').status_code==200
        assert client.get('/api/game/'+setup.session['session_id']).status_code==200
        response=client.post('/api/game/'+setup.session['session_id']+'/action',json={'message':'I look around.'})
        assert response.status_code==503
        legacy=app.state.states.create('placeholder')
        assert client.get('/api/game/'+legacy.session_id).status_code==200
        assert client.post('/api/game/'+legacy.session_id+'/action',json={'message':'I look around.'}).status_code==409


def test_missing_session_and_scenario_are_controlled(setup):
    assert setup.client.post('/api/game/missing/action',json={'message':'look'}).status_code==404
    assert setup.client.post('/api/game/new',json={'scenario_id':'synthetic_test'}).status_code==404


def test_action_a_completed_then_b_clarification_retry_is_b_not_a(setup):
    s=setup
    s.mechanics.skill_check.return_value=SkillResult(skill='Spot Hidden',skill_value=50,roll=99,difficulty='regular',outcome='failure')
    assert action(s,turn_id='action-A').status_code==200
    async def clarification(request):
        return LLMResponse(text='',provider='mock',model='mock',structured_data={'intent':'guess','action_category':'observe','status':'clarification'})
    s.provider.generate=clarification
    body={'message':'I think I know the thief. Am I right?','turn_id':'action-B'}
    first=s.client.post('/api/game/'+s.session['session_id']+'/action',json=body)
    assert first.status_code==200
    assert first.json()['turn_outcome']=='clarification'
    retry=s.client.post('/api/game/'+s.session['session_id']+'/action',json=body)
    assert retry.status_code==200
    assert retry.json()==first.json()
    assert first.json()['messages'][-2]['content']==body['message']
    s.mechanics.skill_check.assert_awaited_once()
