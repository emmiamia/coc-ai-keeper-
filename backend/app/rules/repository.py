"""Deterministic local retrieval. Does not import or call MCP, state, or an LLM."""
from pathlib import Path
from typing import Literal, Protocol
from app.rules.models import Rule, CheckGuidance, RulesCatalog, SkillRule, LuckRule

Mechanic = Literal['skill_check', 'pushed_roll', 'luck_check', 'san_check', 'dice_expression']

class RulesRepository(Protocol):
    def get_rule(self, rule_id: str) -> Rule: ...
    def get_rules_for_mechanic(self, mechanic: Mechanic) -> list[Rule]: ...
    def get_check_guidance(self) -> CheckGuidance: ...

class JsonRulesRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else Path(__file__).resolve().parents[3] / 'rules_data/core_rules.json'
        self._catalog = RulesCatalog.model_validate_json(self.path.read_text())
        self._rules = {rule.id: rule for rule in self._catalog.rules}
        if len(self._rules) != len(self._catalog.rules):
            raise ValueError('Rule IDs must be unique')
        for rule in self._catalog.rules:
            if isinstance(rule, SkillRule):
                divisor = {'regular': 1, 'hard': 2, 'extreme': 5}[rule.difficulty]
                if rule.resolution.threshold_source != 'skill_value' or rule.resolution.threshold_divisor != divisor:
                    raise ValueError('Skill threshold must match its difficulty')
            if isinstance(rule, LuckRule):
                if rule.resolution.threshold_source != 'luck_value' or rule.resolution.threshold_divisor != 1:
                    raise ValueError('Luck uses its full value at regular difficulty')

    def get_rule(self, rule_id: str) -> Rule:
        # Return copies so a caller cannot rewrite later retrieval results.
        return self._rules[rule_id].model_copy(deep=True)

    def get_rules_for_mechanic(self, mechanic: Mechanic) -> list[Rule]:
        return [rule.model_copy(deep=True) for rule in self._catalog.rules if rule.mechanic == mechanic]

    def get_check_guidance(self) -> CheckGuidance:
        return self._catalog.check_guidance.model_copy(deep=True)
