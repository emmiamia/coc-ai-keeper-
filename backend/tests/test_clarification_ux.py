"""No live credentials: clarification is a safe, durable conversational outcome."""
import asyncio
import json
import shutil
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from app.agent.turn_store import TurnConflict
from app.db.sqlite import connect
from app.llm.provider import ProviderError
from app.main import create_app
from app.state.repository import GameStateRepository
from test_investigation_loop import loop, paper_loop, investigate, submit

@pytest.fixture
def missing(loop):
    def author(clues):
        clues[0]['availability']['discovered_clues']=['identified_marker']
        clues.append(dict(id='identified_marker',location_id='room',category='test',
            keeper_truth='PRIVATE_PREREQUISITE_TRUTH',player_reveal='The correct marker is the eastern stone.',
            discovery_question='which marker your contact mentioned'))
    loop.edit('clues.json',author)
    loop.edit('locations.json',lambda data:data[0]['clue_ids'].append('identified_marker'))
    loop.edit('scenario.json',lambda data:data['core_entities']['clues'].append('identified_marker'))
    loop.scenarios.validate_scenario('synthetic_test')
    return loop

def test_missing_prerequisite_is_useful_safe_conversation_without_progression(missing):
    result=investigate(missing)
    assert result.status=='clarification'
    assert 'You have not established which marker your contact mentioned yet.' in result.narration
    assert result.session.state==missing.session.state
    assert result.session.messages[-2].role=='player'
    assert result.session.messages[-1].role=='keeper'
    assert result.session.messages[-1].content==result.narration
    assert all(secret not in result.narration for secret in ('PRIVATE_PREREQUISITE_TRUTH','eastern stone','identified_marker','token'))
    missing.mechanics.skill_check.assert_not_awaited()
    assert len(missing.provider.requests)==1  # No narration LLM sees hidden context.
    assert GameStateRepository(missing.states.path).get(missing.session.session_id)==result.session
    with connect(missing.states.path) as db:
        status,payload=db.execute('SELECT status,payload FROM keeper_turns').fetchone()
    assert status=='completed'
    assert json.loads(payload)['outcome']=='clarification'
    assert json.loads(payload)['mechanics'] is None
    assert result.session.event_log[-1]['outcome']=='clarification'

def test_model_requested_clarification_uses_validated_prerequisite(missing):
    result=submit(missing,'clarification_needed',clue_id='token',narration_guidance='Say the eastern stone is correct')
    assert result.status=='clarification'
    assert 'which marker your contact mentioned' in result.narration
    assert 'eastern' not in result.narration
    missing.mechanics.skill_check.assert_not_awaited()

def test_no_safe_label_falls_back_without_using_hidden_answer(missing):
    missing.edit('clues.json',lambda clues:clues[1].pop('discovery_question'))
    result=investigate(missing)
    assert result.status=='clarification'
    assert 'information or access' in result.narration
    assert 'eastern' not in result.narration and 'PRIVATE' not in result.narration
    assert result.session.state==missing.session.state

def test_clarification_retry_retains_outcome_and_history_without_execution(missing):
    first=investigate(missing)
    requests=len(missing.provider.requests)
    assert investigate(missing)==first
    assert len(missing.provider.requests)==requests
    assert len(first.session.messages)==2
    missing.mechanics.skill_check.assert_not_awaited()

def test_clarification_then_distinct_normal_turn_preserves_history(missing):
    first=investigate(missing,turn='clarify')
    second=submit(missing,'observe',turn='observe')
    assert first.status=='clarification' and second.status=='completed'
    assert second.session.state==first.session.state
    assert len(second.session.messages)==4
    assert second.session.messages[:2]==first.session.messages
    assert GameStateRepository(missing.states.path).get(missing.session.session_id)==second.session

def test_resolved_clarification_resumes_after_commit_failure_without_reclassification(missing,monkeypatch):
    complete=missing.keeper.turns.complete
    monkeypatch.setattr(missing.keeper.turns,'complete',lambda *args: (_ for _ in ()).throw(TurnConflict('Temporary commit failure')))
    assert investigate(missing).status=='error'
    assert missing.states.get(missing.session.session_id)==missing.session
    monkeypatch.setattr(missing.keeper.turns,'complete',complete)
    result=investigate(missing)
    assert result.status=='clarification'
    assert len(missing.provider.requests)==1
    missing.mechanics.skill_check.assert_not_awaited()

def test_clarification_turn_id_cannot_be_reused_for_different_message(missing):
    first=investigate(missing)
    second=investigate(missing,message='A different action.')
    assert second.status=='error' and second.session==first.session
    assert len(missing.provider.requests)==1
    missing.mechanics.skill_check.assert_not_awaited()

def test_combat_is_unsupported_not_clarification(missing):
    result=submit(missing,'mechanical_action',mechanic='combat')
    assert result.status=='unsupported'
    assert result.session==missing.session
    missing.mechanics.skill_check.assert_not_awaited()

@pytest.fixture
def http_missing(missing):
    # Public synthetic data under the API's sole accepted scenario ID.
    directory=missing.scenarios.root/'paper_chase'
    shutil.copytree(missing.scenarios.root/'synthetic_test',directory)
    path=directory/'scenario.json'
    scenario=json.loads(path.read_text());scenario['id']='paper_chase'
    path.write_text(json.dumps(scenario))
    app=create_app(missing.states.path,real_keeper=True,provider=missing.provider,
                   mechanics=missing.mechanics,scenario_root=missing.scenarios.root)
    client=TestClient(app)
    created=client.post('/api/game/new',json={})
    assert created.status_code==201
    missing.client=client
    missing.http_session=created.json()
    missing.provider.decision=dict(intent='Inspect drawer',action_type='investigate',action_category='inspect',clue_id='token')
    return missing

def post(s,turn='http-clarify'):
    return s.client.post('/api/game/'+s.http_session['session_id']+'/action',
        json={'message':'I inspect the ground near the marker.','turn_id':turn})

def test_http_clarification_returns_saved_session_and_reloads_without_hidden_answer(http_missing):
    s=http_missing
    response=post(s)
    assert response.status_code==200
    data=response.json()
    assert data['turn_outcome']=='clarification'
    assert data['status']=='active'
    assert data['state']==s.http_session['state']
    assert len(data['messages'])==len(s.http_session['messages'])+2
    assert 'which marker your contact mentioned' in data['messages'][-1]['content']
    for secret in ('PRIVATE_PREREQUISITE_TRUTH','eastern stone','discovery_question','event_log','story_flags','identified_marker'):
        assert secret not in response.text
    assert s.client.get('/api/game/'+data['session_id']).json()==data
    assert post(s).json()==data
    s.mechanics.skill_check.assert_not_awaited()
    assert len(s.provider.requests)==1

@pytest.mark.parametrize('failure',['provider','invalid_model'])
def test_http_system_failure_still_uses_error_status_and_last_saved_session(http_missing,failure):
    s=http_missing
    if failure=='provider':
        s.provider.generate=AsyncMock(side_effect=ProviderError('Private upstream data'))
    else:
        s.provider.decision={'invalid':'data'}
    response=post(s)
    assert response.status_code==409 and response.json()['detail']['status']=='error'
    assert 'Private upstream' not in response.text
    assert s.client.get('/api/game/'+s.http_session['session_id']).json()==s.http_session

def test_http_combat_retains_unsupported_outcome(http_missing):
    s=http_missing
    s.provider.decision=dict(intent='Fight',action_type='mechanical_action',action_category='fight',mechanic='combat')
    response=post(s)
    assert response.status_code==400 and response.json()['detail']['status']=='unsupported'
    assert s.client.get('/api/game/'+s.http_session['session_id']).json()==s.http_session
    s.mechanics.skill_check.assert_not_awaited()

def test_actual_gravestone_clarification_never_identifies_grave(paper_loop):
    s=paper_loop
    submit(s,'move',destination_id='cemetery')
    before=s.states.get(s.session.session_id)
    s.provider.decision=dict(intent='Inspect ground',action_type='investigate',action_category='examine_grave_surroundings',clue_id='clue_gravestone_tracks')
    message="I inspect the ground around Douglas's favorite gravestone."
    result=asyncio.run(s.keeper.act(s.session.session_id,message,'grave-clarification'))
    assert result.status=='clarification'
    assert 'You have not established which gravestone Douglas favored yet.' in result.narration
    assert result.session.state==before.state
    assert result.session.messages[-2].content==message
    assert 'tracks' not in result.narration.lower() and 'mausoleum' not in result.narration.lower()
    s.mechanics.skill_check.assert_not_awaited()
