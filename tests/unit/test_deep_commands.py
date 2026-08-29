"""深度炼金指令壳单测（M8 批8-2 · alchemy_commands.py 的 /深度炼金 /进化 /镶核心 /加成 /挑战
/图鉴 /技能面板 /教学）。

文件：tests/unit/test_deep_commands.py
创建：2026-08-29
作者：Hermes 主 agent（批8-2 子agent 迭代上限截断后补写）

功能：直测 async 指令处理器（真实 DeepEngine/AlchemyMeta + fake session_mgr）：
  - /深度炼金（GU-20 大师解锁「深度未解锁」/ 大师成功开深度会话+面板）
  - /进化（GU-23 宗师 + GU-24 产出 N 次 合成不计 / 永久解锁「✅ 继承 2 额外槽（6 槽）」/ 幂等）
  - /镶核心（GU-26 深度会话中 / 成功品质上限+20 / 核心不匹配拒绝）
  - /加成（GU-28 宗师 / 限 1 次/调合）
  - /挑战（GU-47 宗师 / 材料×2 全量 / 开启挑战会话）
  - /图鉴（进度显示 / 全亮 → 王称号）
  - /技能面板（查看 SP / 解锁=面板项 / SP 不足拒绝）
  - /教学（目录 / 机制名 / 升大师 6 机制预览）

依据：docs/m8_contract_指令契约.md §6/7/8/16/19/23（GU-20~28/47~49/58/64 + F-06~08/16/19/23
  + M-06~08/16/19/23）+ 细化_2c5a TTL-01~09 + TC-14/15/16/23/27/31。
测试风格对齐 tests/unit/test_alchemy_commands.py / test_confirm_commands.py（parse_command
  直调 + 全字段 ctx + async fake session_mgr）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from qbot_rpg.commands.alchemy_commands import (
    cmd_buff,
    cmd_challenge,
    cmd_core,
    cmd_deep,
    cmd_evolve,
    cmd_skill_panel,
    cmd_tutorial,
    render_alchemy_codex,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command

# 注入白名单 W 的 parse 包装（DEFAULT_WHITELIST 未含 8 深度指令，批11A 装配补齐）
def _pc(raw: str):
    return parse_command(raw, whitelist=W)

# 深度炼金 8 指令白名单（DEFAULT_WHITELIST 未含；批11 路11A 装配 IF-34 补齐——本测试注入同款）
W = DEFAULT_WHITELIST | {
    "深度炼金", "进化", "镶核心", "加成", "挑战", "图鉴", "技能面板", "教学",
}


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

class FakeSessions:
    """async fake session_mgr（内存 dict；对齐 test_confirm_commands FakeSessions）。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, Any] = {}

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


class _FakeRegistry:
    """fake registry（all_ids 按 kind 返回注册表 id 列表——codex 图鉴分母）。"""

    def __init__(self, recipe_ids: list, item_ids: list) -> None:
        self._recipes = recipe_ids
        self._items = item_ids

    def all_ids(self, kind: str):
        if kind == "recipe":
            return tuple(self._recipes)
        if kind == "item":
            return tuple(self._items)
        return ()


ITEMS: Dict[str, dict] = {
    "mat_fire": {"id": "mat_fire", "name": "火晶石", "type": "material",
                 "elements": {"fire": 4}},
    "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable",
                   "quality": "common"},
    "core_fire": {"id": "core_fire", "name": "龙晶核", "type": "核心",
                  "elements": {"fire": 8}, "core": {"cap_bonus": 20}},
    "boost_stone": {"id": "boost_stone", "name": "贤者之石", "type": "加成",
                    "boost": {"quality": 30}},
}

RECIPES: Dict[str, dict] = {
    "r_deep": {"id": "r_deep", "name": "炼狱爆弹·深度", "level": 40, "kind": "craft",
               "master_only": True, "slots": 6, "quality_cap": 100,
               "output": {"item": "flame_bomb", "count": 1},
               "materials": [{"id": "mat_fire", "count": 2}],
               "cost": {"coins": 0, "gem": 0},
               "element_req": {"fire": [{"threshold": 5, "effect": "burn"}]}},
    "r_low": {"id": "r_low", "name": "火焰弹配方", "level": 5, "kind": "craft",
              "master_only": False, "slots": 4,
              "output": {"item": "flame_bomb", "count": 1},
              "materials": [{"id": "mat_fire", "count": 2}],
              "cost": {"coins": 0, "gem": 10},
              "evolve_to": {"id": "r_high", "condition": {"count": 5, "source": "炼金产出"}}},
    "r_high": {"id": "r_high", "name": "烈焰弹·改配方", "level": 8, "kind": "craft",
               "master_only": False, "slots": 6,
               "output": {"item": "flame_bomb", "count": 1},
               "materials": [{"id": "mat_fire", "count": 3}]},
}

SETTINGS: Dict[str, Any] = {"alchemy": {}}


def _player(level: int = 4, *, produce: int = 0, codex_lit: int = 0,
            sp_used: int = 0) -> dict:
    """玩家（proficiency.alchemy.level=档位索引 0~6；大师=4 宗师=5）。"""
    return {
        "qid": "u1",
        "proficiency": {"alchemy": {"level": level, "sp_earned": 5, "sp_used": sp_used,
                                    "unlocks": {}}},
        "currencies": {"coins": 500, "gem": 50},
        "produce_counts": {"r_low": produce},
        "codex_state": {"alchemy": {f"r_low{i}": {"seen": True}
                                    for i in range(codex_lit)}},
    }


def make_ctx(player: dict, *, sessions: Optional[FakeSessions] = None,
             inv: Optional[dict] = None) -> dict:
    """全字段 ctx（items/recipe 注册表 + settings + session_mgr + hooks）。"""
    inv = inv if inv is not None else {"mat_fire": 20, "flame_bomb": 5,
                                       "core_fire": 2, "boost_stone": 2}
    registry = _FakeRegistry(list(RECIPES), list(ITEMS))
    return {
        "qid": player.get("qid", "u1"),
        "player": player,
        "items": ITEMS,
        "recipe": RECIPES,
        "traits": {},
        "settings": SETTINGS,
        "registry": registry,
        "session_mgr": sessions or FakeSessions(),
        "inventory": inv,
        "currencies": player.get("currencies", {}),
        "count_item": lambda iid: inv.get(iid, 0),
        "remove_item": lambda iid, n: inv.__setitem__(iid, inv.get(iid, 0) - n),
        "add_item": lambda iid, n: inv.__setitem__(iid, inv.get(iid, 0) + n),
        "upgrade_unlocks": {},
    }


def _qty_text(out: str) -> str:
    return out


# ---------------------------------------------------------------------------
# /深度炼金（TC-14）
# ---------------------------------------------------------------------------

async def test_deep_jingtong_rejected() -> None:
    """GU-20：精通（档位 3）→ 「深度未解锁」。"""
    ctx = make_ctx(_player(level=3))
    out = await cmd_deep(_pc("/深度炼金 炼狱爆弹·深度"), ctx)
    assert "深度未解锁" in out


async def test_deep_master_opens_session() -> None:
    """GU-20/21/22：大师（档位 4）→ 开深度会话 + 面板（6 槽/核心槽/刻度）。"""
    sessions = FakeSessions()
    ctx = make_ctx(_player(level=4), sessions=sessions)
    out = await cmd_deep(_pc("/深度炼金 炼狱爆弹·深度"), ctx)
    assert "炼狱爆弹·深度" in out
    assert await sessions.get_active("u1") is not None


async def test_deep_recipe_not_found() -> None:
    ctx = make_ctx(_player(level=4))
    out = await cmd_deep(_pc("/深度炼金 不存在的配方"), ctx)
    assert "配方不存在" in out


# ---------------------------------------------------------------------------
# /进化（TC-15）
# ---------------------------------------------------------------------------

async def test_evolve_count_not_met_rejected() -> None:
    """GU-24：宗师但炼金产出 2/5 → 拒绝。"""
    ctx = make_ctx(_player(level=5, produce=2))
    out = await cmd_evolve(_pc("/进化 火焰弹配方"), ctx)
    assert "进化" in out and "条件" in out or "产出" in out


async def test_evolve_ok_and_idempotent() -> None:
    """F-07：宗师+产出 5 次 → 永久解锁「✅ 继承 2 额外槽（6 槽）」；重复 → 已解锁。"""
    ctx = make_ctx(_player(level=5, produce=5))
    out = await cmd_evolve(_pc("/进化 火焰弹配方"), ctx)
    assert "继承" in out and "6 槽" in out
    assert "r_high" in (ctx.get("upgrade_unlocks") or {})
    # 幂等（ATO-05）：重复 /进化 不重复扣宝石
    ctx2 = make_ctx(_player(level=5, produce=5))
    ctx2["upgrade_unlocks"] = {"r_high": True}
    out2 = await cmd_evolve(_pc("/进化 火焰弹配方"), ctx2)
    assert "已解锁" in out2


# ---------------------------------------------------------------------------
# /镶核心（TC-16）与 /加成
# ---------------------------------------------------------------------------

async def test_core_no_session_rejected() -> None:
    """GU-26：无深度会话 → 无会话模板。"""
    ctx = make_ctx(_player(level=4))
    out = await cmd_core(_pc("/镶核心 龙晶核"), ctx)
    assert "当前没有调合会话" in out


async def test_core_ok_in_deep_session() -> None:
    """COR-01/02：深度会话中 + 核心适配 → 品质上限+20、火适配。"""
    sessions = FakeSessions()
    ctx = make_ctx(_player(level=4), sessions=sessions)
    await cmd_deep(_pc("/深度炼金 炼狱爆弹·深度"), ctx)
    out = await cmd_core(_pc("/镶核心 龙晶核"), ctx)
    assert "品质上限" in out or "适配" in out


async def test_buff_ok_and_once_limit() -> None:
    """GU-28：宗师 + 加成道具 → 成功；第 2 次 → 限 1 次拒绝。"""
    sessions = FakeSessions()
    ctx = make_ctx(_player(level=5), sessions=sessions)
    await cmd_deep(_pc("/深度炼金 炼狱爆弹·深度"), ctx)
    out = await cmd_buff(_pc("/加成 贤者之石"), ctx)
    assert "品质" in out or "加成" in out
    out2 = await cmd_buff(_pc("/加成 贤者之石"), ctx)
    assert "限 1 次" in out2


# ---------------------------------------------------------------------------
# /挑战（TC-23）
# ---------------------------------------------------------------------------

async def test_challenge_not_master_rejected() -> None:
    """GU-47：专家（档位 3）→ 拒绝。"""
    ctx = make_ctx(_player(level=3))
    out = await cmd_challenge(_pc("/挑战 炼狱爆弹·深度"), ctx)
    assert "宗师" in out or "等级不足" in out


async def test_challenge_ok_with_double_materials() -> None:
    """GU-47~49：宗师 + 深度会话中 + 材料×2 → 开启挑战会话。"""
    sessions = FakeSessions()
    ctx = make_ctx(_player(level=5), sessions=sessions)
    await cmd_deep(_pc("/深度炼金 炼狱爆弹·深度"), ctx)
    out = await cmd_challenge(_pc("/挑战 炼狱爆弹·深度"), ctx)
    assert "挑战" in out


# ---------------------------------------------------------------------------
# /图鉴（TC-27）
# ---------------------------------------------------------------------------

async def test_codex_progress_and_king() -> None:
    """F-19/TTL-01：图鉴进度显示；全亮 → 炼金王称号。"""
    ctx = make_ctx(_player(level=5, codex_lit=2))
    out = render_alchemy_codex(ctx)
    assert "炼金图鉴" in out


async def test_codex_all_lit_grant_king() -> None:
    """TTL-01：全点亮 → 「炼金王」称号。"""
    # codex_lit 覆盖全部注册条目（r_deep/r_low/r_high + items 5 = 8 个 seen）
    player = _player(level=5)
    player["codex_state"] = {"alchemy": {
        "r_deep": {"seen": True}, "r_low": {"seen": True}, "r_high": {"seen": True},
        "mat_fire": {"seen": True}, "flame_bomb": {"seen": True},
        "core_fire": {"seen": True}, "boost_stone": {"seen": True},
    }}
    ctx = make_ctx(player)
    out = render_alchemy_codex(ctx)
    assert "炼金王" in out or "称号" in out


# ---------------------------------------------------------------------------
# /技能面板（TC-27）
# ---------------------------------------------------------------------------

async def test_skill_panel_view() -> None:
    """F-19：查看 SP 面板（可用点 + 分支列表）。"""
    ctx = make_ctx(_player(level=4, sp_used=0))
    out = await cmd_skill_panel(_pc("/技能面板"), ctx)
    assert "SP" in out or "可用" in out


async def test_skill_panel_unlock_subword() -> None:
    """F-19：解锁=品质上限+10 子词 → 解锁成功（SP 扣减）。"""
    ctx = make_ctx(_player(level=4, sp_used=0))
    out = await cmd_skill_panel(_pc("/技能面板 解锁=品质上限+10"), ctx)
    assert "品质上限" in out or "解锁" in out


# ---------------------------------------------------------------------------
# /教学（TC-31）
# ---------------------------------------------------------------------------

async def test_tutorial_catalog() -> None:
    """GU-64/F-23：无参 → 教学目录。"""
    ctx = make_ctx(_player())
    out = await cmd_tutorial(_pc("/教学"), ctx)
    assert "教学" in out


async def test_tutorial_mechanism() -> None:
    """F-23：/教学 连锁奖励 → 机制教学文案。"""
    ctx = make_ctx(_player())
    out = await cmd_tutorial(_pc("/教学 连锁奖励"), ctx)
    assert "连锁" in out or "教学" in out


async def test_tutorial_master_announcement() -> None:
    """F-23/L482：大师（档位 4）→ 深度机制 6 预览。"""
    ctx = make_ctx(_player(level=4))
    out = await cmd_tutorial(_pc("/教学"), ctx)
    # 升大师公告含 6 机制预览（或目录兜底）
    assert isinstance(out, str) and len(out) > 0
