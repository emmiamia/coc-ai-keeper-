# Scenario data

`synthetic_test/` is TEST / SYNTHETIC SCENARIO — NOT PAPER CHASE.
Its six JSON files contain only fictional architecture test data.

Future authorized scenario directories use `scenario.json` plus arrays in
`locations.json`, `npcs.json`, `clues.json`, `events.json`, and `encounters.json`.
Use `JsonScenarioRepository.validate_scenario(id)` before use. Keep canonical
Keeper fields internal, and access player information through explicit projections.
The synthetic fixture contains no licensed scenario content. Any populated
licensed scenario must be supplied separately from an authorized source. No scraping, embeddings, LLM integration, or Keeper narration
is implemented. The HTTP app continues using its empty placeholder repository.


## Private local Paper Chase data (Milestone 2B)

`paper_chase/` contains six populated JSON files adapted only from the user-supplied
ground-truth specification using concise paraphrases. The entire directory is
Git-ignored; no original PDF is included. The existing models/repository and public
synthetic fixture remain versionable. Private data must be supplied separately to
another checkout. The Paper Chase test module skips its 23 cases when the local
`scenario.json` is absent; once installed, schema, references, and gates must pass.

Load/preflight through `JsonScenarioRepository('scenario_data')` and
`validate_scenario('paper_chase')`. The HTTP game flow still uses the placeholder
repository. Population does not enable scenario gameplay or an agent.

### Mapping to the existing schema

- Setting uses the existing string field; the initial time is day 1 afternoon.
  Lila's default attitude is marked unspecified rather than invented.
- `Conditions` combines requirements with AND. Alternatives such as APP/Credit
  Rating, initial Charm/Persuade, guarded leverage, and police access use documented
  normalized resolution flags. A future trusted orchestrator must evaluate the
  actual alternative and set the flag only after legitimate resolution. These
  flags are not themselves mechanical checks, and retrieval does not set them.
- `discovery_context` preserves alternative/optional checks that cannot be encoded
  as a conjunctive `required_checks` list. Tracks require examining the surroundings
  AND successful Spot Hidden OR Track. Mausoleum STR is conditional, with tool
  retries where appropriate. Newspaper archive access precedes Library Use.
- `mausoleum_discovered` is set only by the `event_follow_tracks` outcome after
  recorded track discovery and an explicit follow action. Merely listing the
  mausoleum in canonical `unlocks` does not change player knowledge or location.
  Undiscovered locations are internal entities, not initial player destinations.
  Callers must check resolved discovery state before offering hidden destinations;
  the existing `player_location` projector does not authorize navigation.
- NPC `douglas_kimball` has a neutral player name. Identity and explanation knowledge
  are guarded, with canonical truth Keeper-only. Only explicit revealed-information
  state permits the guarded text in player knowledge. Canonical NPC context is not
  a player projection; the schema has no dynamic NPC name projector.
- Outcomes requiring choices have separate entries or branches. Outcome dictionaries
  do not carry their own selection predicates: future orchestration must select
  the matching locked-window, stakeout/asleep, and encounter outcome from resolved
  state. A selected location does not authorize discovery or contact by itself.
- Relative time changes are Keeper instructions plus flags ending in `_required`.
  No JSON outcome can directly change `game_time`, increment day, clear pending
  pushes, or mark a session completed in the current schema. Future orchestration
  must use the existing transactional state interface. No clock engine was added.
- SAN recognition is a partial-support branch with a SAN check reference and the
  specified failed-check loss in Keeper context. The supplied specification does
  not provide success loss; it remains unspecified and is not invented. The typed
  check schema does not encode SAN loss formulas or execute this check.
- Jefferson's pushed alternatives and attitude consequence, unresolved endings,
  optional disclosure, eventual closure, and severe mausoleum smell are preserved
  as conditions/state flags or Keeper references. No numeric attitude penalty,
  extra NPC biography, full combat, or mechanical consequence was invented.
- Event/encounter retrieval is eligibility only. No event fires, outcome executes,
  clue reveals, push rolls, identity becomes known, or phase/time advances merely
  because data is loaded. The phase is non-linear state rather than a fixed route.

Run local scenario structural tests:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/test_paper_chase.py
```
