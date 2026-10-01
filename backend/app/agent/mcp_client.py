"""Typed backend boundary around the existing local stdio MCP server."""
import json
import anyio
import sys
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MechanicsError(RuntimeError):
    pass

class SkillResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    skill: str
    skill_value: int = Field(ge=0, le=100)
    roll: int = Field(ge=1, le=100)
    difficulty: Literal['regular','hard','extreme']
    outcome: Literal['success','failure']

class DiceResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expression: str
    rolls: list[int]
    total: int

class SanResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    roll: int = Field(ge=1, le=100)
    previous_san: int = Field(ge=0,le=99)
    outcome: Literal['success','failure']
    san_loss: int = Field(ge=0)
    new_san: int = Field(ge=0,le=99)

class StdioMechanicsClient:
    def __init__(self, root=None, python=None):
        self.root = Path(root) if root else Path(__file__).resolve().parents[3]
        self.python = python or sys.executable

    async def call_tool(self, name, arguments):
        if name not in ('roll_dice','skill_check','san_check'):
            raise MechanicsError('Unsupported MCP tool')
        params = StdioServerParameters(command=self.python,args=['-m','mcp_server.server'],cwd=str(self.root))
        try:
            with anyio.fail_after(30):
                async with stdio_client(params) as (read,write):
                    async with ClientSession(read,write) as client:
                        await client.initialize()
                        result = await client.call_tool(name,arguments)
                        if result.isError:
                            raise MechanicsError('MCP tool failed')
                        if result.structuredContent is not None:
                            data = result.structuredContent
                        else:
                            texts = [c.text for c in result.content if c.type == 'text']
                            if len(texts) != 1:
                                raise MechanicsError('Unexpected MCP response')
                            data = json.loads(texts[0])
                        return data
        except Exception:
            raise MechanicsError('MCP resolution failed; outcome must not be rerolled automatically') from None

    async def skill_check(self, skill_name, skill_value, difficulty='regular') -> SkillResult:
        try:
            result = SkillResult.model_validate(await self.call_tool('skill_check',dict(skill_name=skill_name,skill_value=skill_value,difficulty=difficulty)))
            if (result.skill,result.skill_value,result.difficulty) != (skill_name,skill_value,difficulty):
                raise ValueError('MCP result does not match declared check')
            return result
        except Exception:
            raise MechanicsError('Invalid skill-check result') from None

    async def roll_dice(self, expression) -> DiceResult:
        try:
            result = DiceResult.model_validate(await self.call_tool('roll_dice',dict(expression=expression)))
            if result.expression != expression or result.total != sum(result.rolls):
                raise ValueError('MCP dice result mismatch')
            return result
        except Exception:
            raise MechanicsError('Invalid dice result') from None

    async def san_check(self, current_san, success_loss, failure_loss) -> SanResult:
        try:
            result = SanResult.model_validate(await self.call_tool('san_check',dict(current_san=current_san,success_loss=success_loss,failure_loss=failure_loss)))
            if result.previous_san != current_san or result.new_san != current_san-result.san_loss:
                raise ValueError('MCP SAN result mismatch')
            return result
        except Exception:
            raise MechanicsError('Invalid SAN result') from None
