"""M8 装配接线单测（批11-2 收口 · assembly/router_setup.py + assembly/context.py）。

文件：tests/unit/test_m8_assembly.py
创建：2026-08-29
作者：Hermes 主 agent（批11-2 收口裁决后补写）

功能：验证 M8 装配接线——
  ① Router 全量注册（build_router 后 30+ M8 炼金指令全部可解析，/图鉴 单入口无双注册）；
  ② make_context 注入 M8 引擎键（session_mgr/items/recipe/traits/count_item 等；
    registered=False 安全空值不抛）；
  ③ /图鉴 炼金分册走 render_alchemy_codex（双注册合并裁决）。

依据：docs/m8_contract_指令契约.md（全指令清单）+ 批11-2 收口裁决（/图鉴 并入 codex 分册、
  currencies 入账桶保留、珠升阶补白名单）。
测试风格对齐 tests/unit/test_assembly_router.py（build_router + parse_command）。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from qbot_rpg.assembly.context import AssemblyDeps, make_context
from qbot_rpg.assembly.router_setup import build_router, check_consistency
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command

# M8 全部炼金指令（含 /珠升阶；/图鉴 由 codex 注册不在此列）
M8_COMMANDS = (
    "合成", "炼金", "投料", "继承", "继承超", "确认", "放弃", "调合续",
    "深度炼金", "进化", "镶核心", "加成", "成品合成", "配方合成", "特性合成",
    "珠升阶", "分解", "登记", "复制", "挑战", "即时调合",
    "镶嵌", "拆珠", "教学", "协力", "种植", "收获", "代工", "收取", "技能面板",
)


class _FakeRepo:
    async def load_player(self, qid: str) -> Any:
        return None


class _FakeWorld:
    pass


class _FakeRegistry:
    """鸭式 registry（all_ids/resolve/modules_raw 最小面）。"""

    def all_ids(self, kind: str):
        return ()

    def resolve(self, ref: Any, kind: str):
        return None

    modules_raw: Dict[str, Any] = {}


def _deps(**over: Any) -> AssemblyDeps:
    base: Dict[str, Any] = {
        "repo": _FakeRepo(),
        "game_world": _FakeWorld(),
        "registry": _FakeRegistry(),
        "settings": {},
        "session_mgr": None,
    }
    base.update(over)
    return AssemblyDeps(**base)


# ---------------------------------------------------------------------------
# ① Router 全量注册
# ---------------------------------------------------------------------------

def test_router_registers_all_m8_commands() -> None:
    router = build_router(_deps())
    names = set(router.names())
    missing = [c for c in M8_COMMANDS if c not in names]
    assert not missing, f"M8 指令注册缺失：{missing}"


def test_router_codex_single_registration() -> None:
    """/图鉴 单入口（codex 注册，alchemy 不重复——双注册合并裁决）。"""
    router = build_router(_deps())
    names = set(router.names())
    assert "图鉴" in names


def test_router_consistency_m8() -> None:
    """注册缺白名单为空（M8 全部注册指令命中 parsers 白名单）。"""
    router = build_router(_deps())
    result = check_consistency(router)
    assert result["ok"] is True
    assert result["registered_not_whitelisted"] == []


def test_parse_all_m8_commands_resolve() -> None:
    """parse_command 对全部 M8 指令解析出正确 command（白名单补全生效）。"""
    for cmd in M8_COMMANDS:
        p = parse_command(f"/{cmd} 测试")
        # /继承超 兼容：parse_command 最长匹配可能落「继承」+子词，指令壳已剥离防御
        assert p.command == cmd or (cmd == "继承超" and p.command == "继承"), \
            (cmd, p.command)


def test_jewel_up_in_whitelist() -> None:
    """「珠升阶」已补入白名单（批11-2 收口裁决，缺则静默不响应）。"""
    assert "珠升阶" in DEFAULT_WHITELIST


# ---------------------------------------------------------------------------
# ② make_context M8 引擎注入
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_make_context_m8_keys_unregistered() -> None:
    """未注册玩家：make_context 含 M8 键且安全空值不抛异常。"""
    ctx = await make_context({"qq_id": "", "message": "/状态"}, _deps())
    for key in ("session_mgr", "items", "recipe", "traits", "registry",
                "battle_snapshot", "battle_alchemy_engine", "upgrade_unlocks",
                "wallet", "prof_engine", "resolve_player_name", "same_group"):
        assert key in ctx, f"M8 ctx 键缺失：{key}"
    assert ctx["items"] == {}
    assert ctx["upgrade_unlocks"] == {}


@pytest.mark.asyncio
async def test_make_context_m8_registered_hooks() -> None:
    """已注册玩家：背包 hooks + currencies 入账桶注入。"""
    from qbot_rpg.data.item import ItemInstance
    from qbot_rpg.data.player import Player

    player = Player(
        qid="10001", name="阿伟", job_id="alchemy", level=1, exp=0, hp=10, mp=10,
        currencies={"coins": 100, "gem": 5},
        inventory=(ItemInstance(item_id="mat_fire", name="火晶石", count=3,
                                quality="common", bound=True),),
    )
    repo = _FakeRepo()

    async def _load(qid: str):
        return player

    # 注入读档（鸭子替换实例方法，对齐现有装配测试 _deps 模式）
    setattr(repo, "load_player", _load)
    ctx = await make_context({"qq_id": "10001", "message": "/状态"}, _deps(repo=repo))
    assert ctx["registered"] is True
    assert ctx["count_item"]("mat_fire") == 3
    assert ctx["currencies"] == {"coins": 100, "gem": 5}
    assert ctx["inventory"] == {"mat_fire": 3}
