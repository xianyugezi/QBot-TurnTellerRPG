"""/温室 指令壳单测（2c5c FARM-07/08：状态查看 + 大师解锁复制）。

文件：tests/unit/test_greenhouse_commands.py
创建：2026-09-06
作者：Hermes 主代理（指令缺口补全批2路2）

覆盖：
  - 空温室状态查看（地块 0/N + 提示）
  - 有作物：倒计时/可收获标记
  - /温室 复制 <素材>：非大师 → 等级不足拒绝
  - 缺参/错误子词
风格对齐 test_alchemy_harvest（make_ctx + 指令壳直调 async）。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from qbot_rpg.commands.alchemy_commands import (
    GREENHOUSE_CMD,
    cmd_greenhouse,
    register_alchemy_commands,
)
from qbot_rpg.commands.parsers import parse_command, ParsedCommand
from qbot_rpg.commands.router import Router

_ITEMS = {
    "mossvein_seed": {"id": "mossvein_seed", "name": "苔脉籽",
                      "seed": {"output": "mossvein_herb", "quality_floor": 40}},
    "mossvein_herb": {"id": "mossvein_herb", "name": "苔脉草"},
    "glowcap_seed": {"id": "glowcap_seed", "name": "莹菇孢子",
                     "seed": {"output": "glowcap", "quality_floor": 50, "traits": ["莹光"]}},
    "glowcap": {"id": "glowcap", "name": "莹光菇"},
}


def make_ctx(**over: Any) -> dict:
    now = int(time.time())
    base: Dict[str, Any] = {
        "registered": True,
        "player": {
            "name": "测试勇士", "level": 10, "qid": "u1",
            "currencies": {"coins": 5000, "gem": 20},
            "inventory": [], "farm_plots": {},
            "attributes": {"base": {}},
        },
        "items": _ITEMS,
        "settings": {"alchemy": {"farming": {
            "enabled": True, "harvest_sec": 14400, "plots_max": 3,
            "greenhouse": {"unlock_tier": "大师", "copy_slot": 1,
                           "copy_cost": {"gem": 10, "coins": 1000}},
        }}},
        "now": now,
        "templates": None,
        "currencies": {"coins": 5000, "gem": 20},
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    return parse_command(raw)


def test_greenhouse_empty_status() -> None:
    """空温室：地块 0/3 + 提示。"""
    ctx = make_ctx()
    out = asyncio.run(cmd_greenhouse(parse("/温室"), ctx))
    assert "地块 0/3" in out
    assert "无作物" in out
    assert "大师" in out


def test_greenhouse_with_plots() -> None:
    """有作物：倒计时 + 可收获。"""
    now = int(time.time())
    ctx = make_ctx(player={
        "name": "测试勇士", "level": 10, "qid": "u1",
        "currencies": {"coins": 5000, "gem": 20},
        "inventory": [], "attributes": {"base": {}},
        "farm_plots": {
            "1": {"slot": 1, "seed_id": "mossvein_seed", "seed_name": "苔脉籽",
                  "planted_at": now - 3600, "harvest_at": now + 3600},
            "2": {"slot": 2, "seed_id": "glowcap_seed", "seed_name": "莹菇孢子",
                  "planted_at": now - 20000, "harvest_at": now - 5000},
        },
    })
    out = asyncio.run(cmd_greenhouse(parse("/温室"), ctx))
    assert "地块 2/3" in out
    assert "苔脉籽" in out
    assert "可收获" in out


def test_greenhouse_copy_locked() -> None:
    """复制：非大师 → 等级不足。"""
    ctx = make_ctx()
    out = asyncio.run(cmd_greenhouse(parse("/温室 复制 苔脉籽"), ctx))
    assert "大师" in out and "等级不足" in out


def test_greenhouse_copy_missing_arg() -> None:
    """复制缺素材 → 参数错误。"""
    ctx = make_ctx()
    out = asyncio.run(cmd_greenhouse(parse("/温室 复制"), ctx))
    assert "素材" in out


def test_register_greenhouse() -> None:
    """注册白名单。"""
    router = Router()
    register_alchemy_commands(router)
    spec = router.get(GREENHOUSE_CMD)
    assert spec is not None
    assert spec.whitelisted
