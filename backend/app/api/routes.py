from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from app.models.game import Session, GameState
from app.api.player_models import PlayerSession, PlayerState, project_session

class NewGame(BaseModel):
    scenario_id: str | None = None

class Action(BaseModel):
    turn_id: str | None = Field(default=None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')
    message: str = Field(min_length=1, max_length=10000)
    @field_validator('message')
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError('Message cannot be blank')
        return value.strip()

def routes(states, scenarios, keeper, *, real_keeper=False):
    router = APIRouter()
    @router.get('/health')
    def health():
        return {'status': 'ok'}
    session_model = PlayerSession if real_keeper else Session
    state_model = PlayerState if real_keeper else GameState
    def safe(session):
        return project_session(session,scenarios) if real_keeper else session
    @router.post('/api/game/new', response_model=session_model, status_code=201)
    def new(body: NewGame):
        scenario_id = body.scenario_id or ('paper_chase' if real_keeper else 'placeholder')
        if real_keeper:
            if scenario_id != 'paper_chase': raise HTTPException(404,'Scenario not supported')
            try:
                scenario = scenarios.validate_scenario(scenario_id)
            except (KeyError,FileNotFoundError):
                raise HTTPException(503,'The private scenario data is not installed locally') from None
            except Exception:
                raise HTTPException(503,'Scenario data could not be validated') from None
            initial = scenario.starting_state.model_copy(deep=True)
            # Fixed prototype investigator, matching the verified manual demo.
            for skill,value in {'Spot Hidden':50,'Charm':40,'Persuade':40,'Psychology':30,'Track':20,'Library Use':40,'APP':50,'Credit Rating':30,'Intimidate':30}.items():
                initial.skills.setdefault(skill,value)
            initial.known_locations = list(scenario.initial_known_locations)
            return safe(states.create(scenario_id,initial,opening_message=scenario.player_premise))
        try:
            scenarios.metadata(scenario_id)
        except KeyError:
            raise HTTPException(404, 'Scenario not found')
        return states.create(scenario_id)
    @router.get('/api/game/{session_id}', response_model=session_model)
    def get(session_id: str):
        try:
            return safe(states.get(session_id))
        except KeyError:
            raise HTTPException(404, 'Session not found')
    @router.get('/api/game/{session_id}/state', response_model=state_model)
    def state(session_id: str):
        return get(session_id).state
    @router.post('/api/game/{session_id}/action', response_model=session_model)
    async def action(session_id: str, body: Action):
        try:
            if not real_keeper:
                return keeper.act(session_id, body.message)
            session = states.get(session_id)
            if session.scenario_id != 'paper_chase':
                raise HTTPException(409,'This is a legacy session. Start a new Paper Chase game.')
            if keeper.provider is None:
                raise HTTPException(503,'Gemini is not configured in the backend environment')
            result = await keeper.act(session_id,body.message,turn_id=body.turn_id)
            if result.status not in ('completed','clarification'):
                status_code = 400 if result.status == 'unsupported' else 409
                raise HTTPException(status_code,detail={'message':result.narration,'status':result.status,'turn_id':result.turn_id})
            return safe(result.session)
        except KeyError:
            raise HTTPException(404, 'Session not found')
    return router
