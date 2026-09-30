# CoC AI Keeper — Milestone 2

The playable HTTP flow remains the Milestone 1 placeholder skeleton. Milestone 2 adds a typed, local JSON Scenario Knowledge Layer with a synthetic test fixture. No prepared licensed scenario, AI narration, Keeper Agent, LLM integration, RAG, or live mechanics orchestration is implemented. No API key is required.

## Structure

- `frontend/`: React/Vite conversation, action input, investigator sidebar, New/Continue controls.
- `backend/app/api/`: validated FastAPI routes.
- `backend/app/agent/`: placeholder turn coordinator, mechanics client protocol, future truth/improvisation constraints.
- `backend/app/llm/`: swappable asynchronous provider protocol.
- `backend/app/scenario/`: typed canonical models, deterministic JSON retrieval, explicit visibility projections, and the existing placeholder repository.
- `backend/app/models/`: typed session, message and structured game state.
- `backend/app/state/` and `db/`: transactional SQLite session repository.
- `mcp_server/`: stdio MCP server and deterministic mechanics functions.
- `backend/tests/`, `mcp_server/tests/`: persistence, API validation, mechanics and MCP schema tests.
- `scenario_data/`: authoring instructions and an explicitly synthetic test fixture; no licensed scenario content.

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

## Milestone 1 checkpoint verification

15 pytest tests passed; frontend production build passed with Vite 7.3.6. npm audit reported zero vulnerabilities. One upstream Starlette/httpx TestClient deprecation warning remains, without test failures. The browser flow has not been manually exercised; API restart persistence is verified by tests.


## Milestone 2: Scenario Knowledge architecture

Scenario Knowledge is canonical story/world truth. Game State records what happened in
this playthrough. MCP supplies deterministic mechanics. A future Keeper Agent will
orchestrate these boundaries and narration; that agent is not implemented here.

`JsonScenarioRepository(root)` reads six typed files per scenario directory:
`scenario.json`, `locations.json`, `npcs.json`, `clues.json`, `events.json`, and
`encounters.json`. Entity files are arrays. `validate_scenario(id)` performs explicit
schema, duplicate-ID, and cross-reference validation for authoring/preflight.
`load_scenario(id)` reads metadata, starting state, policy, and entity references;
it does not load all entities. `get_location`, `get_npc`, `get_clue`, `get_event`,
and `get_encounter` retrieve independent typed entities. Category files are read
on demand; there are no embeddings, vector database, or cache invalidation rules.

`get_context(scenario_id, state, location_id=None, npc_ids=None, action=None)` returns
Keeper-only context scoped to the selected/current location, NPCs, available clues,
previously discovered clues, and eligible events/encounters. Previously discovered
clues remain accessible after leaving a location. It excludes unrelated entities
and global scenario truth. Location event/encounter references select candidates;
`event_eligible` can check an explicitly selected event independently. Conditions
use structured action categories, flags, phase, coarse time, location, and known
information. No natural-language inference or automatic progression is performed.

Canonical models explicitly separate `keeper_truth`/`keeper_context` from player
fields. Keeper context must never be returned through player HTTP routes.
`player_location` excludes clue IDs and secrets. `player_clue` requires recorded
discovery. `knows_clue` and `require_discovered_clues` let future orchestration
reject dependencies on undiscovered information without changing player knowledge.
An available clue is not a discovered clue. `revealable_knowledge` checks public,
conversational, and guarded NPC knowledge against conditions and a talk action;
it never returns Keeper-only items and does not itself disclose or persist anything.
`player_npc_knowledge` returns public information and explicitly recorded revelations,
never Keeper-only items. Knowledge item IDs are unique across a scenario.

State now includes `phase` (open/focused investigation, climax, epilogue),
`game_time` (positive day and morning/afternoon/evening/night), and optional
`pending_push` (original check ID, skill/value/difficulty, context, permission,
and consequence reference). Pending push is only storage: it causes no roll.
One declared MCP check still produces one random roll. Encounter branches mark
mechanics as supported, partial, or unsupported; the fixture marks attack unsupported.

SQLite still stores the same session JSON document in the same table. Existing
session documents receive missing state fields through model defaults when read;
no SQL migration is needed. Future writes persist the extended document.
`GameStateRepository.create(id, starting_state)` copies authored starting state.
`update_state(id, transition)` validates trusted internal changes transactionally;
failed transitions roll back. `record_clue_discovery(id, clue_id, scenarios)` validates
the clue and records discovery idempotently, **only after trusted orchestration has
resolved the discovery**. It does not enforce checks, execute outcomes/unlocks, or
infer anything from player text. No unrestricted HTTP state-update endpoint exists.
The default API continues to accept only the placeholder scenario.

The fixture at `scenario_data/synthetic_test/` is labeled
**TEST / SYNTHETIC SCENARIO — NOT PAPER CHASE**. It contains two fictional locations,
a drawer token, a caretaker with four knowledge access types, a gated nighttime
event, and a branching visitor encounter. It is committed test data; future
licensed scenario content must be supplied separately from an authorized source.

Run the complete suite from the repository root:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider
```

Run just the new knowledge/state tests:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/test_scenario_knowledge.py
```

For programmatic use (with `PYTHONPATH=backend`), initialize
`JsonScenarioRepository('scenario_data')`, validate/load `synthetic_test`, create a
session using its starting state, then call `record_clue_discovery` and reload it
through a fresh `GameStateRepository`. Tests demonstrate this flow, guarded NPC
knowledge, afternoon-versus-night event eligibility, legacy defaults, rollback,
and persistence of phase, game time, and pending push.


Milestone 2 verification: all 43 tests passed (28 new parameterized knowledge/state
cases plus the original 15), and the frontend production build passed. Live
Vite-proxy requests verified create/action/retrieve, direct SQLite equality, and
reload after an actual FastAPI process restart. A live MCP stdio client discovered
and called all three intended tools. One upstream Starlette/httpx TestClient
deprecation warning remains. Browser button interactions were not manually exercised.


## Milestone 2B: private local scenario population

The local `scenario_data/paper_chase/` directory now contains six typed JSON files
adapted from the supplied specification. It is deliberately Git-ignored and is
not enabled in the placeholder HTTP app. No source PDF, agent, LLM, Rules KB,
embeddings, combat implementation, or MCP changes were added.

See `scenario_data/README.md` for data/schema adaptations, resolution-flag meanings,
limitations, private-data provisioning, and the local structural-test command.
The complete suite passes 66 tests with the private data present (43 existing plus
23 Paper Chase cases); one existing Starlette/httpx deprecation warning remains.
A checkout without private data skips those 23 cases while keeping the existing
schema, synthetic-fixture, API/persistence, and MCP tests available.
