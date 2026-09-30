import random
import re

_RNG = random.SystemRandom()

def roll_dice(expression: str, *, rng=None):
    match = re.fullmatch(r'([1-9][0-9]*)d([1-9][0-9]*)', expression)
    if not match:
        raise ValueError('Use NdM dice notation, such as 1d100')
    count, sides = map(int, match.groups())
    if count > 100 or sides > 1000:
        raise ValueError('Maximum 100 dice with 1000 sides')
    rolls = [(rng or _RNG).randint(1, sides) for _ in range(count)]
    return {'expression': expression, 'rolls': rolls, 'total': sum(rolls)}

def skill_check(skill_name: str, skill_value: int, difficulty: str = 'regular', *, rng=None):
    if not 0 <= skill_value <= 100 or difficulty not in ('regular', 'hard', 'extreme'):
        raise ValueError('Skill must be 0–100; difficulty regular, hard or extreme')
    roll = roll_dice('1d100', rng=rng)['total']
    threshold = skill_value // {'regular': 1, 'hard': 2, 'extreme': 5}[difficulty]
    # Skeleton success/failure resolution only; critical/fumble/bonus dice deferred.
    return {'skill': skill_name, 'skill_value': skill_value, 'roll': roll, 'difficulty': difficulty,
            'outcome': 'success' if roll <= threshold else 'failure'}

def san_check(current_san: int, success_loss: str, failure_loss: str, *, rng=None):
    if not 0 <= current_san <= 99:
        raise ValueError('SAN must be 0–99')
    # Validate both expressions before consuming randomness.
    for loss in (success_loss, failure_loss):
        if not re.fullmatch(r'[0-9]+', loss):
            match = re.fullmatch(r'([1-9][0-9]*)d([1-9][0-9]*)', loss)
            if not match or int(match[1]) > 100 or int(match[2]) > 1000:
                raise ValueError('Loss must be a nonnegative integer or NdM')
    roll = roll_dice('1d100', rng=rng)['total']
    outcome = 'success' if roll <= current_san else 'failure'
    expression = success_loss if outcome == 'success' else failure_loss
    loss = int(expression) if expression.isdigit() else roll_dice(expression, rng=rng)['total']
    return {'roll': roll, 'previous_san': current_san, 'outcome': outcome,
            'san_loss': min(current_san, loss), 'new_san': max(0, current_san - loss)}
