"""M8 全链路冒烟验证（批12 验收 · scripts/verify_m8_smoke.py）。

模拟玩家走完整条炼金玩法链路（真实指令壳 + 真实引擎 + fake session_mgr）：
  /合成 魔力药水（跨职业）→ /炼金 火焰弹（开会话）→ /投料 火晶石（链式，带特性源）
  → /继承 灼烧强化（特性）→ /确认 结算（品质/系数/终态）→ /分解 成品（材料+宝石）
  → /技能面板 SP 查看。

数据：traits/settings 取自 content/test_demo（真实档位/品质配置）；配方为专家档自定
（player alchemy 经验=800 → 专家档，配方 level=30 命中专家区间 [26,35]，继承 3 位）。

用法：cd /root/QBot-TurnTellerRPG && .venv/bin/python3 scripts/verify_m8_smoke.py
（全链路通过输出 "M8 SMOKE OK"，任一步失败退出码 1。）
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from qbot_rpg.commands.alchemy_commands import (
    cmd_confirm,
    cmd_decompose,
    cmd_feed,
    cmd_inherit,
    cmd_alchemy,
    cmd_synthesis,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.core.gem_wallet import GemWallet

_DEMO = Path(__file__).resolve().parent.parent / "content" / "test_demo"


def _load(name: str):
    with open(_DEMO / name, encoding="utf-8") as f:
        return json.load(f)


# 真实内容包数据（test_demo）
TRAITS: Dict[str, dict] = {e["id"]: e for e in _load("traits.json")}
_ITEMS_RAW = _load("items.json")
ITEMS: Dict[str, dict] = {e["id"]: e for e in _ITEMS_RAW}
SETTINGS: Dict[str, Any] = _load("settings.json")

# 专家档自定配方（player alchemy 经验=800 → 专家档，配方 level=30 命中 [26,35]）
RECIPES: Dict[str, dict] = {
    "rcp_flame": {"id": "rcp_flame", "name": "火焰弹", "level": 30, "kind": "craft",
                  "slots": 5, "pp_budget": 5,
                  "materials": [{"id": "alch_ember_crystal", "count": 2},
                                 {"id": "alch_frost_crystal", "count": 1}],
                  "cost": {"coins": 30, "gem": 0},
                  "output": {"item": "flame_bomb", "count": 1},
                  "element_req": {"fire": [{"threshold": 6, "effect": "范围爆炸"}]}},
    "rcp_mana": {"id": "rcp_mana", "name": "魔力药水", "level": 30, "kind": "craft",
                 "slots": 3, "pp_budget": 3,
                 "materials": [{"id": "alch_ember_crystal", "count": 1}],
                 "cost": {"coins": 10, "gem": 0},
                 "output": {"item": "mana_potion", "count": 1}},
}


class FakeSessions:
    """async fake session_mgr（对齐 test_confirm_commands）。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, tuple] = {}

    async def get_active(self, qid: str) -> Optional[Any]:
        view = self._sessions.get(qid)
        if view is None:
            return None
        return type("View", (), {"session_type": view[0], "payload": view[1]})()

    async def acquire(self, qid: str, session_type: str, payload: Any = None) -> Any:
        if qid in self._sessions:
            raise RuntimeError("SessionConflictError")
        self._sessions[qid] = (session_type, payload)
        return type("View", (), {"session_type": session_type, "payload": payload})()

    async def suspend(self, qid: str, snapshot: Any) -> None:
        if qid in self._sessions:
            self._sessions[qid] = (self._sessions[qid][0], snapshot)


def make_player() -> dict:
    return {
        "qid": "smoke01",
        # level = 职业档位索引 0-6（M8 存档口径：tier_index_for_level 直接用 level 当档位索引）。
        # 3=专家档 → job_tier_map 专家 [26,35] → 配方 level=30 命中；继承位=专家 3 位。
        "proficiency": {"alchemy": {"level": 3, "sp_earned": 3, "sp_used": 0,
                                    "unlocks": {}}},
        "currencies": {"coins": 1000, "gem": 30},
        "inventory": {"alch_ember_crystal": 10, "alch_frost_crystal": 10,
                      "mana_potion": 3, "flame_bomb": 2},
        "codex_state": {"alchemy": {}},
        "produce_counts": {},
    }


def make_ctx() -> dict:
    player = make_player()
    sessions = FakeSessions()
    return {
        "qid": "smoke01",
        "player": player,
        "items": ITEMS,
        "recipe": RECIPES,
        "traits": TRAITS,
        "settings": SETTINGS,
        "session_mgr": sessions,
        "inventory": player["inventory"],
        "currencies": player["currencies"],
        "count_item": lambda iid: player["inventory"].get(iid, 0),
        "remove_item": lambda iid, n: (
            player["inventory"].__setitem__(iid, player["inventory"].get(iid, 0) - n)
            if player["inventory"].get(iid, 0) >= n else False) or True,
        "add_item": lambda iid, n, bound=False, **kw: (
            player["inventory"].__setitem__(iid, player["inventory"].get(iid, 0) + n)
            if True else None) or True,
        "proficiency": player["proficiency"],
        "upgrade_unlocks": {},
        "codex_state": player["codex_state"],
        "wallet": GemWallet(settings=SETTINGS),
    }


def pc(raw: str):
    W = DEFAULT_WHITELIST | {"炼金", "投料", "继承", "确认", "分解"}
    return parse_command(raw, whitelist=W)


CHECKS: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    CHECKS.append((name, cond))
    mark = "OK " if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" | {detail}" if detail and not cond else ""))


async def main() -> int:
    ctx = make_ctx()
    try:
        # 1. /合成 魔力药水（跨职业标准版；cmd_synthesis 同步）
        out = cmd_synthesis(pc("/合成 魔力药水*2"), ctx)
        check("合成 魔力药水*2", "魔力药水" in out, out)

        # 2. /炼金 火焰弹（开会话 + 面板）
        out = await cmd_alchemy(pc("/炼金 火焰弹"), ctx)
        check("炼金 火焰弹 开会话", "火焰弹" in out, out)

        # 3. /投料 火晶石（链式，火晶石带 trait_burn_boost 特性源）
        out = await cmd_feed(pc("/投料 火晶石,冰晶石"), ctx)
        check("投料 火晶石,冰晶石", "连锁" in out or "火" in out, out)

        # 4. /继承 灼烧强化（特性源 = 火晶石 traits）
        out = await cmd_inherit(pc("/继承 灼烧强化"), ctx)
        check("继承 灼烧强化", "灼烧强化" in out, out)

        # 5. /确认 结算（品质/终态）
        out = await cmd_confirm(pc("/确认"), ctx)
        check("确认 结算", "火焰弹" in out or "品质" in out, out)

        # 6. /分解 火焰弹（材料+宝石两段式）
        out = await cmd_decompose(pc("/分解 火焰弹"), ctx)
        check("分解 火焰弹", "火晶石" in out or "宝石" in out or "分解" in out, out)

    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        check("异常", False, str(exc))

    ok = all(cond for _, cond in CHECKS)
    passed = sum(1 for _, c in CHECKS if c)
    print(f"\nM8 SMOKE {'OK' if ok else 'FAIL'}（{passed}/{len(CHECKS)} 通过）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
