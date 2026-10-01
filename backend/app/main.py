import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from app.api.routes import routes
from app.agent.keeper import PlaceholderKeeper
from app.scenario.repository import PlaceholderScenarioRepository, JsonScenarioRepository
from app.state.repository import GameStateRepository

ROOT = Path(__file__).resolve().parents[2]

def create_app(db_path=None, *, real_keeper=False, provider=None, mechanics=None, scenario_root=None):
    """Explicit offline legacy fixture remains available; served app uses real Keeper."""
    states = GameStateRepository(db_path or os.getenv('COC_DB_PATH') or str(ROOT/'data/game.sqlite3'))
    owned_provider = None
    if real_keeper:
        from app.agent.orchestrator import KeeperOrchestrator
        from app.agent.mcp_client import StdioMechanicsClient
        from app.rules.repository import JsonRulesRepository
        scenarios = JsonScenarioRepository(scenario_root or ROOT/'scenario_data')
        keeper = KeeperOrchestrator(states,scenarios,JsonRulesRepository(),mechanics or StdioMechanicsClient(),provider)
    else:
        scenarios = PlaceholderScenarioRepository()
        keeper = PlaceholderKeeper(scenarios,states)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal owned_provider
        if real_keeper and provider is None and os.getenv('GEMINI_API_KEY'):
            from app.llm.gemini import GeminiProvider
            try:
                owned_provider = GeminiProvider()
                keeper.provider = owned_provider
            except Exception:
                # No SDK errors/credentials enter logs or responses.
                keeper.provider = None
        try:
            yield
        finally:
            if owned_provider:
                try: await owned_provider.aclose()
                except Exception: pass

    app = FastAPI(title='CoC AI Keeper',lifespan=lifespan)
    app.state.states,app.state.keeper = states,keeper
    app.include_router(routes(states,scenarios,keeper,real_keeper=real_keeper))
    return app

app = create_app(real_keeper=True)
