from fastapi.testclient import TestClient
from app.main import create_app

def test_turn_survives_restart(tmp_path):
    path = tmp_path / 'game.sqlite3'
    client = TestClient(create_app(path))
    assert client.get('/health').json() == {'status': 'ok'}
    created = client.post('/api/game/new', json={})
    assert created.status_code == 201
    session = created.json()
    url = '/api/game/' + session['session_id']
    result = client.post(url + '/action', json={'message': 'Look around'})
    assert result.status_code == 200
    saved = result.json()
    assert saved['messages'][0]['content'] == 'Look around'
    assert '[Placeholder Keeper]' in saved['messages'][1]['content']
    assert saved['state'] == session['state']
    restarted = TestClient(create_app(path))
    assert restarted.get(url).json() == saved
    assert restarted.get(url + '/state').json() == saved['state']
    assert len(saved['event_log']) == 1

def test_invalid_requests(tmp_path):
    client = TestClient(create_app(tmp_path / 'game.sqlite3'))
    assert client.get('/api/game/missing').status_code == 404
    assert client.post('/api/game/new', json={'scenario_id': 'private'}).status_code == 404
    session = client.post('/api/game/new', json={}).json()
    url = '/api/game/' + session['session_id'] + '/action'
    assert client.post(url, json={'message': '  '}).status_code == 422
    assert client.get('/api/game/' + session['session_id']).json()['messages'] == []
