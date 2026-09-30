# CoC AI Keeper — first milestone

Local project skeleton only. There is no prepared scenario, AI narration, Keeper prompt, RAG or live mechanics orchestration. Placeholder responses are clearly labeled. No API key is required.

## Structure

- `frontend/`: React/Vite conversation, action input, investigator sidebar, New/Continue controls.
- `backend/app/api/`: validated FastAPI routes.
- `backend/app/agent/`: placeholder turn coordinator, mechanics client protocol, future truth/improvisation constraints.
- `backend/app/llm/`: swappable asynchronous provider protocol.
- `backend/app/scenario/`: canonical repository interface and empty placeholder implementation.
- `backend/app/models/`: typed session, message and structured game state.
- `backend/app/state/` and `db/`: transactional SQLite session repository.
- `mcp_server/`: stdio MCP server and deterministic mechanics functions.
- `backend/tests/`, `mcp_server/tests/`: persistence, API validation, mechanics and MCP schema tests.
- `scenario_data/`: instructions for future private licensed JSON, no scenario content.

## Run locally

Use Python 3.10+ and Node 20.19+ (or 22.12+). On this machine, `/opt/homebrew/bin/python3.13` meets the Python requirement; the system `python3` does not. From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
# Optional: requirements.lock.txt records the exact Python 3.13 verification environment.
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal, from this directory:

```sh
cd frontend
npm install
npm run dev
```

Open http://localhost:5174. Vite proxies API calls to port 8000. Start New Game, submit a message, refresh, then select Continue Game. The browser remembers the last session ID; paste any saved ID to resume another session. All game content lives in SQLite, not browser storage. Backend restarts preserve sessions in `backend/data/game.sqlite3`; override with `COC_DB_PATH` if needed.

Run the MCP server separately, from this directory with the virtual environment active:

```sh
python -m mcp_server.server
```

It uses stdio and waits for an MCP client; it is not an HTTP service. A future client can launch this command and invoke `roll_dice`, `skill_check`, `san_check`. The backend currently defines the client interface but does not launch or invoke the server.

## API

- `GET /health`
- `POST /api/game/new` with `{}` or `{"scenario_id":"placeholder"}`
- `GET /api/game/{session_id}`
- `POST /api/game/{session_id}/action` with `{"message":"Look around"}`
- `GET /api/game/{session_id}/state`

Interactive API docs: http://127.0.0.1:8000/docs.

## Checks

```sh
source .venv/bin/activate
pytest -q
cd frontend
npm run build
```

Tests cover creation, message persistence after reconstructing the app, unchanged authoritative state, missing sessions/scenarios, blank messages, fixed random draws, difficulty thresholds, SAN loss/clamping, invalid dice, and registered MCP schemas.

## Assumptions and scope

Placeholder investigator values are HP 10 and SAN 50, with no location, skills or clues. SQLite stores a validated session JSON document keyed by session ID, including state, conversation, event log and timestamps. Turn writes use one transaction to prevent lost concurrent updates. Conversation never mutates authoritative mechanics.

Mechanics support bounded `NdM` notation, regular/hard/extreme checks at full/half/fifth thresholds, and SAN loss as a nonnegative integer or dice expression. SAN loss is capped at remaining SAN. Criticals, fumbles, bonus/penalty dice, opposed checks and combat are deferred. A SAN check uses one percentile roll and, only when needed, a separate loss roll. Randomness is injectable in tests; outcomes are fixed once those draws occur. Runtime tool-result persistence and retry deduplication belong to future orchestration.

This project lives in the existing CoC AI Keeper repository at `/Users/emmayue/Desktop/coc-ai-keeper`. It was moved out of the unrelated NourishSteps workspace; no existing NourishSteps app files were modified. Private scenario truth is never returned through these endpoints; before real scenarios are enabled, player-facing projections and unlock filtering must be implemented. Full session responses are safe only for this empty placeholder milestone.

## Verification results

15 pytest tests passed; frontend production build passed with Vite 7.3.6. npm audit reported zero vulnerabilities. One upstream Starlette/httpx TestClient deprecation warning remains, without test failures. The browser flow has not been manually exercised; API restart persistence is verified by tests.
