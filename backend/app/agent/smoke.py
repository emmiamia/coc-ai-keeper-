"""Manual live one-turn smoke; explicitly sends scoped local scenario context."""
import asyncio
import os
import tempfile
from pathlib import Path
from app.agent.orchestrator import KeeperOrchestrator
from app.agent.mcp_client import StdioMechanicsClient
from app.llm.gemini import GeminiProvider
from app.llm.smoke import diagnostic_for, sanitize_diagnostic
from app.rules.repository import JsonRulesRepository
from app.scenario.repository import JsonScenarioRepository
from app.state.repository import GameStateRepository

async def run():
    root = Path(__file__).resolve().parents[3]
    scenarios = JsonScenarioRepository(root/'scenario_data')
    scenario = scenarios.validate_scenario('paper_chase')
    provider = GeminiProvider()
    try:
        with tempfile.TemporaryDirectory(prefix='.agent-smoke-',dir=root) as tmp:
            states = GameStateRepository(Path(tmp)/'game.sqlite3')
            starting = scenario.starting_state.model_copy(deep=True)
            # Smoke-only investigator configuration, not a new scenario fact.
            starting.skills['Spot Hidden'] = 50
            session = states.create(scenario.id,starting)
            keeper = KeeperOrchestrator(states,scenarios,JsonRulesRepository(),StdioMechanicsClient(root),provider)
            result = await keeper.act(session.session_id,"I search Douglas's study.",turn_id='manual-smoke-turn')
            assert result.status == 'completed', 'Agent turn did not complete; state remains safe'
            assert GameStateRepository(states.path).get(session.session_id) == result.session
            repeat = await keeper.act(session.session_id,"I search Douglas's study.",turn_id='manual-smoke-turn')
            assert repeat.session == result.session
            print(sanitize_diagnostic(f'PASS: safe persisted Agent turn; model={os.getenv("GEMINI_MODEL","gemini-3.7-flash")}; outcome={result.session.event_log[-1]["mechanics"]["outcome"]}'))
    finally:
        await provider.aclose()

def main():
    try: asyncio.run(run())
    except Exception as error:
        print('FAIL: '+diagnostic_for(error))
        raise SystemExit(1) from None

if __name__ == '__main__': main()
