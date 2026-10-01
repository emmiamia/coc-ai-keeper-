# CoC AI Keeper — Milestone 4D investigation loop

Milestone 2 adds a typed, local JSON Scenario Knowledge Layer with a synthetic test fixture. The served React/FastAPI app now uses the real Keeper investigation loop for the prepared local Paper Chase prototype. It coordinates scoped knowledge, Gemini decisions, local MCP checks, and SQLite; full scenario gameplay is not implemented. Normal tests use mocks and require no API key.

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

Open http://localhost:5174. Vite proxies API calls to port 8000. Start New Game, submit a message, refresh, then select Continue Game. The browser remembers the last session ID; paste any saved ID to resume another session. All game content lives in SQLite, not browser storage. Backend restarts preserve sessions in `data/game.sqlite3`; override with `COC_DB_PATH` if needed.

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


## Milestone 3: Minimal Rules Knowledge Layer

Scenario Knowledge is canonical scenario truth. Rules Knowledge supplies generic
resolution guidance. Game State is current playthrough truth. MCP executes dice
and mechanical checks. A future Keeper Agent will orchestrate them and narrate;
it is not implemented.

`backend/app/rules/models.py` defines typed rules and guidance;
`rules_data/core_rules.json` contains seven concise implementation summaries:
Regular/Hard/Extreme percentile checks, explicit pushed skill checks, Luck, SAN,
and bounded dice expressions. This is a limited mechanics subset needed by the
supported scenario, not a rulebook reproduction. No rulebook PDF is ingested.

`JsonRulesRepository()` loads the local catalog (or accepts an explicit file path).
`get_rule(rule_id)` returns one rule and raises `KeyError` for an unknown ID.
`get_rules_for_mechanic(mechanic)` returns only matching rules, in file order,
and returns an empty list for unknown mechanics. `get_check_guidance()` returns
request/avoid guidance and the fixed resolution priority:
scenario instruction, then generic rules, then safe Keeper judgment.
Returned models are copies; retrieval does not roll dice, update state, authorize
checks, classify actions, call MCP, or select scenario outcomes.

Skill guidance matches the existing MCP thresholds: full value, floor(value/2),
and floor(value/5). Luck reuses `skill_check` with name Luck, current Luck value,
and regular difficulty; orchestration must supply that value (no new Luck state
field or Luck-spending system was added). SAN maps to `san_check`, using current
SAN and explicit scenario-provided success/failure loss expressions. Missing SAN
loss values remain unresolved; generic rules do not invent them. Dice maps to
`roll_dice` using its existing bounded NdM grammar.

Pushing applies only to eligible failed skill checks and requires an explicit
player choice and justified/changed approach. It is a new declared check, never
an automatic reroll. Eligibility and more serious consequences remain with the
scenario/future orchestration. Luck and SAN checks are not pushable. Full combat,
critical/fumble resolution, bonus/penalty dice, opposed checks, Luck spending,
and the full insanity system remain unsupported.

Future flow: obtain the scenario's permitted check alternatives, retrieve the
matching generic rule, let future orchestration declare one valid check, then
call MCP once. A push requires a separate explicit decision; this repository
performs none of those orchestration steps.

Run the new rules tests:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/test_rules.py
```

The complete-suite command remains:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider
```

Milestone 3 verification: 89 tests passed (66 existing plus 23 rules cases), the
frontend production build passed, and a live MCP stdio client discovered and called
all three unchanged tools. Existing restart persistence tests passed.
`git diff --check` passed. The existing Starlette/httpx TestClient deprecation
warning remains.


## Milestone 4A: Gemini development provider

Gemini is the development runtime provider through Google's supported
`google-genai` SDK. The default model is `gemini-3.7-flash`; `GEMINI_MODEL` overrides
it. `GEMINI_API_KEY` is required only for live provider calls. Credentials belong
in the backend process environment; they are never sent to React or committed.
Environment files are Git-ignored and are not automatically loaded by the app.

Install dependencies using `.venv/bin/python -m pip install -r backend/requirements.txt`.
The provider-neutral `LLMRequest` carries system instruction, message history,
user message, and optional Pydantic response schema. `LLMResponse` carries text,
provider/model identity, and optional validated structured data. The existing
message-list-to-text signature remains available for compatibility.
`GeminiProvider` alone translates these contracts to the async Gemini Developer
API with a 30-second HTTP timeout. Structured requests use SDK JSON/schema output
configuration and Pydantic validation. Empty/invalid responses and SDK failures
become controlled errors without raw credential-bearing SDK payloads. Call
`await provider.aclose()` when an owned client is no longer needed.

The placeholder FastAPI app does not instantiate Gemini. No Keeper orchestration,
scenario retrieval, Paper Chase transmission, state mutation, MCP function calling,
or gameplay has been connected to this provider.

Normal pytest uses mocked SDK clients and requires neither credentials nor network.
For an optional live check, set `GEMINI_API_KEY` privately in the shell, optionally
set `GEMINI_MODEL`, and run from the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m app.llm.smoke
```

This manually invoked command sends two harmless test prompts, checks plain text
and a tiny typed classification, closes the client, and prints status only. It
never runs under pytest and never reads scenario data or prints the API key.
Live verification is pending when credentials are unavailable.

SDK references: [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
and [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output).

Milestone 4A verification: all 112 tests passed (89 existing plus 23 provider cases),
the frontend production build passed, and `pip check` found no dependency conflicts.
MCP files and scenario/state implementations are unchanged. Private Paper Chase
data and environment files remain ignored; no credentials are staged/tracked.
Live verification was not run because `GEMINI_API_KEY` was unavailable. The existing
Starlette/httpx TestClient deprecation warning remains.


### Manual Gemini model diagnostic

With `GEMINI_API_KEY` already configured privately, run from the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m app.llm.model_diagnostic
```

The SDK lists models through the key, reports advertised actions, and tests up to
five API-discovered Flash/Flash-Lite candidates sequentially with one harmless
text prompt each. Each tested model reports PASS or sanitized failure/type/status.
The SDK is configured for one attempt per request and a 30-second HTTP timeout.
No scenario content, tools, grounding, caching, batch, Vertex AI or billing setup
is used. The current default model is unchanged; a successful text probe does not
prove structured-output support. Generated text and credentials are never printed.

Use `--list-only` to inspect without generation, or `--limit 1` to probe at most
one candidate. The model-list API does not expose billing/free-tier eligibility.
The diagnostic therefore intersects API discovery with a conservative exact-ID
policy of models documented with free standard text input/output on Google's
[pricing page](https://ai.google.dev/gemini-api/docs/pricing), checked 2026-09-30.
Unknown and paid-only models are skipped; no guessed or undiscovered ID is called.
This policy is not a guarantee of project-specific quota or billing status. It
assumes the user's project remains on the stated free tier and never enables
billing. Other checkouts/date changes may require reviewing the eligibility policy.


## Milestone 4B: first Keeper vertical slice

`KeeperOrchestrator(states, scenarios, rules, mechanics, provider).act(session_id,
message, turn_id=None)` is the programmatic entry point. It loads persistent state,
assembles current-location/NPC/clue context plus relevant rules and generic guidance,
requests a typed `KeeperDecision`, validates every entity reference and discovery
dependency, resolves one scenario-defined skill check, and persists the resulting
session. No frontend or HTTP route was changed; those remain the Milestone 1
placeholder. This does not make the entire Paper Chase scenario playable.

Implemented actions are a clue with exactly one explicitly authored skill check
(e.g. searching the study for the journal) and ordinary observation without rolls.
The scenario's skill/difficulty take priority over model suggestions, and the
investigator must already have that skill value in state. A conservative explicit
verb guard rejects guesses/questions being silently converted to searches. It is
not a general natural-language understanding or meta-knowledge detector. Unknown
IDs, unavailable clues, unsupported plans, combat, and missing skills return
controlled responses without changing the session. The model has no state-write
API or field for dice results. Full event/NPC interaction, OR/optional checks,
movement, outcome chains and full combat are outside this slice.

`StdioMechanicsClient` launches the existing local MCP server and provides typed
`skill_check`, `roll_dice`, and `san_check` methods, normalizes/validates results,
and bounds calls to 30 seconds. It performs no random logic. All three methods
work; only scenario-authored skill checks are selected by this first orchestration
slice. Dice/SAN execution plans remain future work, including unresolved scenario
SAN loss values. An invalid MCP result or transport error is not automatically
retried. Pending pushes record the original check, context and consequence
reference but do not execute another roll; explicit push resolution remains future.

The additive SQLite `keeper_turns` table journals each action and its baseline,
status and trusted resolution before narration. Game-state fields/tables are
unchanged. A resolved action can resume after interruption without rolling again;
a completed `turn_id` returns the original result without new provider/tool calls.
Reuse the same `turn_id` when retrying the same action. IDs cannot be reused for a
different message/session. A pending interrupted tool call or failed call needs
review because its outcome may be unknown. Another in-flight action is blocked.
Atomic completion writes state, both messages and the tool-result event together,
only if the session still matches its original baseline. A concurrent change is
never overwritten; a conflicting recorded result needs explicit reconciliation.
Turn records are retained; this prototype has no pruning/recovery UI.

Narration receives only approved public-location text and authorized outcome
passages, never raw player guesses, hidden context, untrusted narration guidance,
flags or conversation history. To enforce visibility in this milestone, Gemini
returns typed sentence selections rather than unrestricted prose. Only approved
passages are rendered; new text is ignored and invalid narration falls back to
those passages without rerolling. Success includes the selected clue's player
reveal; failure includes no clue content. This deliberately constrains style;
free-form narration would require further safeguards. No arbitrary model-generated
facts or state changes are accepted.

### Manual live Agent smoke

With the private local scenario data installed and `GEMINI_API_KEY` configured
privately in your shell, run from the repository root:

```sh
GEMINI_MODEL=gemini-3.5-flash-lite PYTHONPATH=backend .venv/bin/python -m app.agent.smoke
```

This explicitly sends scoped local Paper Chase context to Gemini for a single
study-search turn, uses real stdio MCP, and verifies SQLite reload/idempotent retry.
The smoke seeds a **test investigator** with Spot Hidden 50 (not a scenario fact),
uses a temporary database inside the repository, prints only status/outcome/model,
and removes that database afterward. A random failure is valid and produces a
pending push rather than a forced successful clue reveal. This never runs under
pytest and does not require a browser. No automatic billing/model switch occurs.

Verification: 170 tests passed (144 existing plus 26 orchestrator cases), the
frontend production build passed, and all three real MCP tools worked through
the adapter. `git diff --check` passed. Live Gemini Agent verification is pending
because this execution environment lacks `GEMINI_API_KEY`. The existing upstream
Starlette/httpx TestClient deprecation warning remains.


## Milestone 4C: React connected to the real Keeper

The served `app.main:app` now follows:
React → FastAPI → Keeper Agent → scoped Scenario/Rules → Gemini/MCP → SQLite.
The existing UI layout is unchanged. New Game starts Paper Chase using its authored
starting state and player premise as the opening Keeper message. The prototype
investigator uses HP 10, SAN 50 and Spot Hidden 50; there is no character creation.
Only this prepared scenario is accepted; private data must be installed locally.

Action requests retain the `message` field and optionally add `turn_id`; the UI
always supplies a stable random ID. Completed responses retain session ID, messages,
status, timestamps and visible state. Real HTTP responses use an explicit allowlist:
location/name, HP, SAN, skills, inventory, conditions, discovered clue IDs, phase,
coarse time, and a push-availability boolean. Internal flags, NPC/custom state,
pending-push references/consequences, tool event logs, Keeper context and decisions
are excluded. Continue and reload use the same projection. Old placeholder sessions
can be read but require New Game to use the real Agent.

React automatically reloads its saved session, shows processing/error states and
locks requests synchronously to prevent accidental double submission. An uncertain
network response retains the pending turn ID in local browser storage; retrying the
same message reuses it, so a completed mechanical result is never silently rerolled.
A different explicit action receives a new ID. Ambiguous/pending turns can require
review. Clarification/unsupported actions return controlled HTTP 400 responses;
failed/pending/conflicting Agent turns return 409; missing backend provider config
returns 503. These errors leave the last saved session shown. Provider and MCP errors
never expose raw SDK data. Narration failure uses the previously documented safe
approved-text fallback without discarding or rerolling a resolved check.

The server instantiates the provider at startup using backend `GEMINI_API_KEY` and
`GEMINI_MODEL`, and closes its client at shutdown. Missing credentials permit session
viewing/creation but prevent Agent execution with a controlled error. Environment
files are ignored but are not automatically loaded. The offline factory
`create_app(db_path)` retains Milestone 1 behavior for its existing tests; production
uses `create_app(real_keeper=True)`. New HTTP tests inject mocked provider/mechanics.

### Local launch and manual browser verification

In a backend terminal where `GEMINI_API_KEY` is already configured privately:

```sh
cd /Users/emmayue/Desktop/coc-ai-keeper
GEMINI_MODEL=gemini-3.5-flash-lite .venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

In a separate frontend terminal:

```sh
cd /Users/emmayue/Desktop/coc-ai-keeper/frontend
npm run dev
```

Open http://localhost:5174. Select New Game, send `I search Douglas's study.`, and
observe the Keeper response. Both success and failure are valid; failure must not
reveal the undiscovered journal. Refresh to verify restored conversation/location
and visible state. Continue Game also accepts a saved session ID. Guessing hidden
facts must not confirm or unlock them. No API key belongs in React or `VITE_*` config.

Current limits remain one prepared scenario, limited supported actions, approved
text narration, no push execution/full combat, and no arbitrary upload or RAG.
Frontend code does not execute any mechanics. Live browser testing is left to the
user's credential-configured environment.

Verification: all 181 pytest cases passed (170 existing plus 11 HTTP cases), all
four frontend interaction tests passed (`cd frontend && npm test`), production build
passed, and `git diff --check` passed. MCP/Scenario/Rules implementations are
unchanged; private data and environment files remain ignored. One existing
Starlette/httpx deprecation warning remains.


## Milestone 4D: bounded general investigation loop

Structured decisions now classify observe, hypothesize, talk, move, investigate,
mechanical_action, unsupported, or clarification_needed. The model resolves natural
phrasing to authored entities and action categories; exact verb prefixes are no
longer required for typed investigation decisions. Legacy decisions retain their
existing guard. Speculative questions cannot become clue discoveries.

Observation uses only the current public location description, without a roll or
undiscovered clues. Hypotheses receive a neutral response without confirming hidden
truth, changing flags, or discovering evidence. Narration still selects approved
sentences, with natural connective phrases and concise unsuccessful-check metadata;
free model prose and hidden reasoning never enter the final narration request.

Talking requires one current-location NPC. Selected knowledge must belong to that
NPC. Ordinary facts can be disclosed when authored conditions match; guarded facts
remain gated and Keeper-only facts are never disclosed. Questions outside NPC
knowledge receive a safe lack-of-information response. New typed NPC check
alternatives, grants, and approaches encode the authored social gates. A successful
check grants only authored flags and information; failure preserves the gate.
Preflight validation happens before rolling. Jefferson's first conversation uses
Charm OR Persuade; his guarded report supports Intimidate OR hard Persuade when
explicitly approached that way. Odell uses APP OR Credit Rating. Alcohol bribes,
changed-approach push execution, chained events, and full combat remain unsupported.

Known destinations are supplied separately from the scoped reasoning context as
public IDs/names. Movement accepts only repository-backed, known, accessible
locations, records current/visited/known locations, and persists safe arrival
narration. Scenario metadata declares initial known destinations; location access
conditions guard private routes. Authored clue unlocks record location knowledge
only after their access gate matches. Tracks alone do not discover the mausoleum.
No model-proposed location, state mutation, skill, difficulty, or outcome is trusted.

Investigation supports one mandatory authored check, one selected authored OR
alternative, or explicitly authored no-check discovery. The gravestone requires
prior favorite-grave identification and Spot Hidden OR Track. Psychology exposes
Jefferson's withholding without unlocking his guarded report. Multiple mandatory
checks and unplanned mechanics require a dedicated future plan. An unresolved push
blocks another attempt at the same clue/knowledge item, including another turn ID;
it does not block unrelated observation or movement. Turn receipts still prevent
retry execution, and mechanics are saved before narration.

The fixed prototype investigator now supplies these development values for new
games: Spot Hidden 50, Charm 40, Persuade 40, Psychology 30, Track 20, Library Use 40,
APP 50, Credit Rating 30, Intimidate 30. These are prototype defaults, not scenario
facts or character creation. Existing saved profiles are not overwritten; missing
required skills produce clarification. Start a new game for the browser exercise.
HTTP projection adds accessible known-location IDs; internal NPC unlock records,
flags, hidden destinations, and consequences remain private. No new UI is added.

### Manual browser exercise

Restart the backend with the existing privately configured key and model override:

```sh
cd /Users/emmayue/Desktop/coc-ai-keeper
GEMINI_MODEL=gemini-3.5-flash-lite .venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Keep/start the existing frontend with `npm run dev` from the repository's
`frontend` directory. Open http://localhost:5174, choose New Game, and submit these
as six separate actions:

1. `I look around the study.`
2. `I ask Thomas what he knows about Douglas.`
3. `Could Douglas himself be responsible for the missing books?`
4. `I go to the cemetery.`
5. `I talk to Jefferson.`
6. `I inspect the ground around Douglas's favorite gravestone.`

A–D should be ordinary safe responses without dice. E uses one authored social
check; a genuine failure is valid. F can run an authored investigation check only
if E established the favorite grave, otherwise it asks for clarification. Refresh
after D/F to verify location, history, and discoveries persist. A failed check must
not reveal its clue. Explicitly retrying the same request must not roll again.
There is no automatic paid billing or model change. Live Gemini/browser results
must be checked locally; offline tests do not claim live model validation.

Verification commands (normal suites require no live credentials):

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=.pytest_cache/4d
cd frontend
npm test
npm run build
```

The 43 new offline behavior cases use synthetic fixtures, plus three optional local
private-scenario cases (skipped if private data is absent). They cover observation,
theories, NPC partitions/social checks, access gates, paraphrases, OR checks,
no-check discovery, retry protection, natural failure narration, route unlocks,
and multi-turn SQLite reload. Existing suites are retained unchanged.

Milestone 4D verification: 225 backend/MCP tests passed (182 retained plus 43 new),
9 frontend tests passed, Vite production build passed, and `git diff --check`
passed. The existing Starlette/httpx TestClient deprecation warning remains.
MCP mechanics are unchanged; private scenario files and credentials remain
ignored/untracked. Live browser verification is pending in the local keyed shell.


## Milestone 4D.1: conversational clarification

Gameplay clarification now resolves a turn receipt without resolving mechanics.
The player message and safe Keeper clarification are atomically appended to SQLite
history while the entire GameState is preserved. The journal remains completed
for retry purposes, with `outcome: clarification` recorded separately from receipt
status. Repeated IDs return the same clarification/session without another model
call or roll; interrupted resolved receipts resume through the same baseline guard.
No existing journal rows or failed receipts are rewritten.

The action API returns HTTP 200 and the normal projected session for both completed
and clarification outcomes. `turn_outcome` distinguishes these outcomes from the
session's active/completed lifecycle and remains available after reload. Unsupported
gameplay remains HTTP 400 with `status: unsupported`; actual Agent/system failures
remain controlled errors. React displays saved clarification in conversation and
uses `Saved · Keeper clarification`, while unsupported requests receive gameplay
feedback. Only technical failures display `Request failed — last saved session shown`.
Compatibility feedback also handles old HTTP 400 clarification responses without
calling them a system failure; those old responses do not imply saved history.

Missing discovery explanations use actual authored prerequisite IDs, the saved
visibility state, and optional player-safe `Clue.discovery_question` labels. Labels
are questions to establish, never their hidden answers, and must be reviewed by
the scenario author as safe for players. No Keeper truth, undiscovered player_reveal,
internal flags, model prose, or narration guidance is used as the explanation.
Scoped blocked-investigation references help the classifier retain the target even
when its prerequisite is unmet. The private favorite-grave prerequisite supplies
only the safe question `which gravestone Douglas favored`; its truth and discovery
conditions are unchanged. Missing labels or unresolved targets receive a generic
safe clarification rather than an invented explanation. Clarification needs no
second narration LLM call.

No gameplay support, MCP tool, scenario truth, or discovery requirement is changed.
Restart/reload the backend and refresh the frontend before retesting the existing
cemetery session. Submit the gravestone action while its prerequisite is missing;
expect a normal Keeper reply and two persisted history messages, with no roll,
discovery, or progression. Refresh to confirm the saved reply. A previously failed
turn ID still needs review; send a newly authored submission rather than trying to
reuse an old failed receipt.

Milestone 4D.1 verification: 238 backend/MCP cases passed (225 retained plus 13
new), 15 frontend tests passed (9 retained plus 6 new), the production build passed,
and `git diff --check` passed. Only the existing Starlette/httpx deprecation warning
remains. No live Gemini request or Git commit was made; MCP tools are unchanged.

## Milestone UI-1: investigation dossier presentation

The supplied mockup guides the dark case cover, warm parchment transcript, serif
hierarchy, muted burgundy composer, and layered investigator folder. All texture
and ornaments use local CSS or small original inline SVG marks; no image assets,
external fonts, artwork downloads, or new gameplay dependencies are required.
Desktop allocates approximately 70% to the transcript and 30% to the dossier. The
transcript scrolls independently for long sessions; the composer is anchored near
the bottom. Narrow screens stack the dossier below the transcript and wrap header
controls. Keeper/player roles use archival labels, distinct marks, and faint rules,
not chat bubbles or separate cards. An empty case has an intentional opening state.

New Game, Continue Game, multiline submissions, reload, the synchronous request
lock, stable retry IDs, and clarification/error semantics remain unchanged. Continue
Game reveals the existing session-reference input in a native disclosure. Session
UUIDs and friendly timestamps are available in a quiet dossier disclosure. Opening
briefing text is the only case-note source; it is never generated from Keeper truth.
Saved clarification remains part of the normal transcript. Unsupported gameplay
receives non-error feedback, while real failures retain the existing failure message.

The minimal additive projection is `PlayerState.clue_names`, keyed only by already
discovered IDs. Names come from the optional authored `Clue.player_name`; private
Paper Chase data and the public synthetic fixture receive display labels. Discovery
IDs are retained for compatibility, but the UI never parses them into names or
renders them as clue labels. Missing labels use `Discovered evidence`. No hidden
clue names, reveal text, conditions, or internal state are added to the projection.

The dossier shows real current HP and SAN values. Maxima and numeric roll results
are not exposed, so no denominators, percentage gauges, invented roll values, or
prose-parsed mechanic badges are shown. Colored rules are decorative, not gauges.
The existing pending-push boolean can render a small `Pending push` note; it is not
a new push control. Richer check rows would need an explicit player-safe projection
of authorized skill/difficulty/value/roll/outcome metadata, which is outside UI-1.

Keyboard focus is visible; controls have labels and disabled states; Enter in the
textarea remains a newline. Decorative SVGs are hidden from assistive technology.
Text stays high-contrast and at comfortable reading sizes, status includes words
rather than color alone, and there are no decorative animations. Native disclosure
controls keep secondary information reachable without dominating the case file.

Verification: 241 backend/MCP tests passed (238 retained plus 3 clue-projection
cases), all 26 frontend tests passed (15 retained plus 11 presentation cases), Vite
production build passed, and `git diff --check` passed. New rendering tests cover
controls, multiline input, loading, safe labels, case notes, clarification/error
presentation, persisted transcripts, honest vitals, and pending-push metadata.
The existing Starlette/httpx deprecation warning remains. Browser pixel inspection
was unavailable; the local preview is http://localhost:5174. For manual QA, refresh
after backend reload, inspect a continued case and an empty case, expand Continue
Game/session reference, try keyboard navigation, and check desktop/narrow layouts.
No gameplay logic, prompts, mechanics, persistence, or discovery gates are changed.
No Git commit is created for UI-1.
