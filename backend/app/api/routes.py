from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from app.models.game import Session, GameState

class NewGame(BaseModel):
    scenario_id: str = 'placeholder'

class Action(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    @field_validator('message')
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError('Message cannot be blank')
        return value.strip()

def routes(states, scenarios, keeper):
    router = APIRouter()
    @router.get('/health')
    def health():
        return {'status': 'ok'}
    @router.post('/api/game/new', response_model=Session, status_code=201)
    def new(body: NewGame):
        try:
            scenarios.metadata(body.scenario_id)
        except KeyError:
            raise HTTPException(404, 'Scenario not found')
        return states.create(body.scenario_id)
    @router.get('/api/game/{session_id}', response_model=Session)
    def get(session_id: str):
        try:
            return states.get(session_id)
        except KeyError:
            raise HTTPException(404, 'Session not found')
    @router.get('/api/game/{session_id}/state', response_model=GameState)
    def state(session_id: str):
        return get(session_id).state
    @router.post('/api/game/{session_id}/action', response_model=Session)
    def action(session_id: str, body: Action):
        try:
            return keeper.act(session_id, body.message)
        except KeyError:
            raise HTTPException(404, 'Session not found')
    return router
