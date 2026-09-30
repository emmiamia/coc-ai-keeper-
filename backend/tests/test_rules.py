import json
from pathlib import Path
import pytest
from app.rules.repository import JsonRulesRepository
from app.rules.models import SkillRule, PushRule, SanRule
from mcp_server.tools.mechanics import skill_check

DATA = Path(__file__).resolve().parents[2] / 'rules_data/core_rules.json'

@pytest.fixture
def repo():
    return JsonRulesRepository()

def test_repository_loads_and_unknown_id_fails(repo):
    assert repo.path == DATA
    with pytest.raises(KeyError): repo.get_rule('not_a_rule')
    assert repo.get_rules_for_mechanic('unknown') == []

@pytest.mark.parametrize('difficulty,divisor', [('regular',1),('hard',2),('extreme',5)])
def test_threshold_guidance_agrees_with_mcp_boundaries(repo,difficulty,divisor):
    rule = repo.get_rule('skill_'+difficulty)
    assert isinstance(rule,SkillRule)
    assert rule.difficulty == difficulty
    assert rule.mcp_tool == 'skill_check'
    assert rule.resolution.threshold_divisor == divisor
    assert rule.resolution.rounding == 'floor'
    value = 63
    threshold = value // rule.resolution.threshold_divisor
    class Draw:
        def __init__(self,roll): self.roll,self.calls = roll,0
        def randint(self,low,high):
            self.calls += 1
            assert low <= self.roll <= high
            return self.roll
    for roll,expected in [(threshold,'success'),(threshold+1,'failure')]:
        rng = Draw(roll)
        result = skill_check('Test',value,rule.difficulty,rng=rng)
        assert result['outcome'] == expected
        assert rng.calls == rule.resolution.declared_check_roll_count == 1

def test_push_requires_explicit_new_check(repo):
    rule = repo.get_rule('pushed_roll')
    assert isinstance(rule,PushRule)
    assert rule.requires_failed_eligible_skill_check
    assert rule.requires_explicit_player_authorization
    assert rule.requires_justified_or_changed_approach
    assert rule.new_declared_check and not rule.automatic_reroll
    assert rule.failed_push_may_have_more_serious_consequence
    assert rule.applies_to == 'eligible_skill_checks_only'
    assert rule.mcp_tool == 'skill_check'
    assert rule.eligibility_authority == 'scenario_and_future_orchestrator'

def test_luck_reuses_skill_primitive(repo):
    rule = repo.get_rule('luck_check')
    assert rule.mcp_tool == 'skill_check'
    assert rule.tool_skill_name == 'Luck'
    assert rule.tool_difficulty == 'regular'
    assert rule.resolution.threshold_source == 'luck_value'
    assert rule.resolution.threshold_divisor == 1
    assert not rule.push_allowed and not rule.luck_spending_supported

def test_san_has_no_scenario_loss_values(repo):
    rule = repo.get_rule('san_check')
    assert isinstance(rule,SanRule)
    assert rule.mcp_tool == 'san_check'
    assert rule.threshold_source == 'current_san'
    assert rule.loss_expression_source == 'scenario'
    assert rule.required_tool_arguments == ('current_san','success_loss','failure_loss')
    assert rule.unspecified_loss_policy == 'require_explicit_resolution_do_not_invent'
    assert 'success_loss' not in rule.model_dump() and 'failure_loss' not in rule.model_dump()
    assert rule.loss_calculation_owner == 'mcp'
    assert not rule.push_allowed

def test_dice_mapping_and_limits(repo):
    rule = repo.get_rule('dice_expression')
    assert rule.mcp_tool == 'roll_dice'
    assert rule.examples == ['1d4','1d6','1d10','1d100']
    assert (rule.min_dice,rule.max_dice,rule.min_sides,rule.max_sides) == (1,100,1,1000)
    assert not rule.arithmetic_modifiers_supported

@pytest.mark.parametrize('mechanic,count', [('skill_check',3),('pushed_roll',1),('luck_check',1),('san_check',1),('dice_expression',1)])
def test_retrieval_scoped_by_mechanic(repo,mechanic,count):
    selected = repo.get_rules_for_mechanic(mechanic)
    assert len(selected) == count
    assert all(rule.mechanic == mechanic for rule in selected)

def test_guidance_and_priority(repo):
    guidance = repo.get_check_guidance()
    assert guidance.resolution_priority == ('scenario_instruction','generic_rules','safe_keeper_judgment')
    assert guidance.scenario_instruction_overrides_generic_guidance
    assert len(guidance.request_when) == 2
    assert len(guidance.avoid_when) == 3
    assert not guidance.automatic_action_classification

def test_results_do_not_mutate_repository(repo):
    rule = repo.get_rule('dice_expression')
    rule.examples.clear()
    assert repo.get_rule('dice_expression').examples
    scoped = repo.get_rules_for_mechanic('dice_expression')
    scoped[0].examples.clear()
    assert repo.get_rule('dice_expression').examples
    repo.get_check_guidance().request_when.clear()
    assert repo.get_check_guidance().request_when

@pytest.mark.parametrize('corruption', ['duplicate_id','threshold','tool','auto_push','authorization','priority','scenario_loss'])
def test_invalid_rules_rejected(tmp_path,corruption):
    data = json.loads(DATA.read_text())
    if corruption == 'duplicate_id': data['rules'].append(data['rules'][0])
    if corruption == 'threshold': data['rules'][1]['resolution']['threshold_divisor'] = 1
    if corruption == 'tool': data['rules'][0]['mcp_tool'] = 'roll_dice'
    if corruption == 'auto_push': data['rules'][3]['automatic_reroll'] = True
    if corruption == 'authorization': data['rules'][3]['requires_explicit_player_authorization'] = False
    if corruption == 'priority': data['check_guidance']['resolution_priority'].reverse()
    if corruption == 'scenario_loss': data['rules'][5]['failure_loss'] = '1d4'
    path = tmp_path/'rules.json'; path.write_text(json.dumps(data))
    with pytest.raises(ValueError): JsonRulesRepository(path)

def test_rules_retrieval_never_resolves_mechanics(monkeypatch):
    import mcp_server.tools.mechanics as mechanics
    def forbidden(*args,**kwargs): pytest.fail('Rules retrieval executed mechanics')
    for name in ('roll_dice','skill_check','san_check'):
        monkeypatch.setattr(mechanics,name,forbidden)
    repo = JsonRulesRepository()
    for mechanic in ('skill_check','pushed_roll','luck_check','san_check','dice_expression'):
        assert repo.get_rules_for_mechanic(mechanic)
    assert repo.get_check_guidance()
