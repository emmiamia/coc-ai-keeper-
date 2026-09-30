import pytest
from mcp_server.tools.mechanics import roll_dice, skill_check, san_check

class Rolls:
    def __init__(self, *values):
        self.values = iter(values)
        self.calls = 0
    def randint(self, low, high):
        self.calls += 1
        value = next(self.values)
        assert low <= value <= high
        return value

def test_dice():
    assert roll_dice('2d6', rng=Rolls(2, 6)) == {'expression': '2d6', 'rolls': [2, 6], 'total': 8}

@pytest.mark.parametrize('difficulty,roll,outcome', [('regular',60,'success'), ('hard',31,'failure'), ('extreme',12,'success')])
def test_skill_single_roll(difficulty, roll, outcome):
    rng = Rolls(roll)
    assert skill_check('Spot Hidden', 60, difficulty, rng=rng)['outcome'] == outcome
    assert rng.calls == 1

def test_san_success_and_failure():
    rng = Rolls(40)
    assert san_check(50, '0', '1d6', rng=rng)['new_san'] == 50
    assert rng.calls == 1
    rng = Rolls(80, 6)
    result = san_check(3, '0', '1d6', rng=rng)
    assert result == {'roll':80, 'previous_san':3, 'outcome':'failure', 'san_loss':3, 'new_san':0}
    assert rng.calls == 2  # One SAN check, plus the required loss die.

@pytest.mark.parametrize('expression', ['0d6', '1d0', '101d6', '1d1001', '1d6+2', 'abc'])
def test_invalid_dice(expression):
    with pytest.raises(ValueError):
        roll_dice(expression)

def test_invalid_san_consumes_no_roll():
    rng = Rolls(50)
    with pytest.raises(ValueError):
        san_check(50, '0', '-1', rng=rng)
    assert rng.calls == 0

def test_mcp_schemas():
    import asyncio
    from mcp_server.server import mcp
    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {'roll_dice', 'skill_check', 'san_check'}
    dice = next(tool for tool in tools if tool.name == 'roll_dice')
    assert dice.inputSchema['properties']['expression']['type'] == 'string'
