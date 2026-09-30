"""Small declarative rules subset matching the existing MCP primitives."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

class RulesModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class RuleBase(RulesModel):
    id: str = Field(min_length=1)
    summary: str = Field(min_length=1)

class PercentileResolution(RulesModel):
    roll_expression: Literal['1d100'] = '1d100'
    threshold_source: Literal['skill_value', 'luck_value']
    threshold_divisor: Literal[1, 2, 5]
    rounding: Literal['floor'] = 'floor'
    success_comparison: Literal['roll <= threshold'] = 'roll <= threshold'
    declared_check_roll_count: Literal[1] = 1

class SkillRule(RuleBase):
    mechanic: Literal['skill_check']
    mcp_tool: Literal['skill_check']
    difficulty: Literal['regular', 'hard', 'extreme']
    resolution: PercentileResolution

class PushRule(RuleBase):
    mechanic: Literal['pushed_roll']
    mcp_tool: Literal['skill_check']
    requires_failed_eligible_skill_check: Literal[True]
    requires_explicit_player_authorization: Literal[True]
    requires_justified_or_changed_approach: Literal[True]
    automatic_reroll: Literal[False]
    new_declared_check: Literal[True]
    eligibility_authority: Literal['scenario_and_future_orchestrator']
    consequence_source: Literal['scenario_or_safe_keeper_judgment']
    failed_push_may_have_more_serious_consequence: Literal[True]
    max_pushes_per_original_check: Literal[1]
    applies_to: Literal['eligible_skill_checks_only']

class LuckRule(RuleBase):
    mechanic: Literal['luck_check']
    mcp_tool: Literal['skill_check']
    tool_skill_name: Literal['Luck']
    tool_difficulty: Literal['regular']
    resolution: PercentileResolution
    push_allowed: Literal[False]
    luck_spending_supported: Literal[False]

class SanRule(RuleBase):
    mechanic: Literal['san_check']
    mcp_tool: Literal['san_check']
    threshold_source: Literal['current_san']
    loss_expression_source: Literal['scenario']
    required_tool_arguments: tuple[Literal['current_san'], Literal['success_loss'], Literal['failure_loss']]
    unspecified_loss_policy: Literal['require_explicit_resolution_do_not_invent']
    loss_calculation_owner: Literal['mcp']
    push_allowed: Literal[False]

class DiceRule(RuleBase):
    mechanic: Literal['dice_expression']
    mcp_tool: Literal['roll_dice']
    notation: Literal['NdM']
    examples: list[str]
    min_dice: Literal[1]
    max_dice: Literal[100]
    min_sides: Literal[1]
    max_sides: Literal[1000]
    arithmetic_modifiers_supported: Literal[False]
    resolution_owner: Literal['mcp']

Rule = Annotated[SkillRule | PushRule | LuckRule | SanRule | DiceRule,
                 Field(discriminator='mechanic')]

class CheckGuidance(RulesModel):
    request_when: list[str]
    avoid_when: list[str]
    scenario_instruction_overrides_generic_guidance: Literal[True]
    resolution_priority: tuple[Literal['scenario_instruction'], Literal['generic_rules'], Literal['safe_keeper_judgment']]
    automatic_action_classification: Literal[False]

class RulesCatalog(RulesModel):
    version: Literal[1]
    scope: str
    rules: list[Rule]
    check_guidance: CheckGuidance
    unsupported_mechanics: list[str]
