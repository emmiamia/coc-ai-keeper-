from mcp.server.fastmcp import FastMCP
from mcp_server.tools.mechanics import roll_dice, skill_check, san_check

mcp = FastMCP('CoC Mechanics')
@mcp.tool(name='roll_dice')
def dice(expression: str) -> dict:
    return roll_dice(expression)
# Explicit signatures supply typed MCP schemas and keep RNG injection private.
@mcp.tool(name='skill_check')
def check_skill(skill_name: str, skill_value: int, difficulty: str = 'regular') -> dict:
    return skill_check(skill_name, skill_value, difficulty)

@mcp.tool(name='san_check')
def check_san(current_san: int, success_loss: str, failure_loss: str) -> dict:
    return san_check(current_san, success_loss, failure_loss)

if __name__ == '__main__':
    mcp.run(transport='stdio')
