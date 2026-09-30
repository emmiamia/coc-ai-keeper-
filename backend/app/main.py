import os
from pathlib import Path
from fastapi import FastAPI
from app.api.routes import routes
from app.agent.keeper import PlaceholderKeeper
from app.scenario.repository import PlaceholderScenarioRepository
from app.state.repository import GameStateRepository

def create_app(db_path=None):
    states = GameStateRepository(db_path or os.getenv('COC_DB_PATH') or str(Path(__file__).resolve().parents[2] / 'data/game.sqlite3'))
    scenarios = PlaceholderScenarioRepository()
    app = FastAPI(title='CoC AI Keeper Skeleton')
    app.include_router(routes(states, scenarios, PlaceholderKeeper(scenarios, states)))
    return app

app = create_app()
