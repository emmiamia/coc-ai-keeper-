"""The UI gets authored names only for clues already discovered."""
from app.api.player_models import project_session
from test_investigation_loop import loop, investigate

def test_projection_includes_only_discovered_authored_names(loop):
    before=project_session(loop.session,loop.scenarios)
    assert before.state.clue_names=={}
    result=investigate(loop)
    visible=project_session(result.session,loop.scenarios)
    assert visible.state.clue_names=={'token':'Synthetic Test Token'}
    assert visible.state.discovered_clues==['token']
    assert 'keeper_truth' not in visible.model_dump_json()
    assert 'Canonical synthetic token' not in visible.model_dump_json()

def test_projection_never_enumerates_undiscovered_labels(loop):
    loop.edit('clues.json',lambda data:data[0].update(player_name='UNREVEALED DISPLAY LABEL'))
    visible=project_session(loop.states.get(loop.session.session_id),loop.scenarios)
    assert 'UNREVEALED DISPLAY LABEL' not in visible.model_dump_json()
    assert visible.state.clue_names=={}

def test_missing_authored_name_has_neutral_safe_fallback(loop):
    loop.edit('clues.json',lambda data:data[0].pop('player_name'))
    result=investigate(loop)
    visible=project_session(result.session,loop.scenarios)
    assert visible.state.clue_names=={'token':'Discovered evidence'}
