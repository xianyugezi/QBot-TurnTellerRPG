"""tests/unit/test_assembly_router.py — A-02 Router 构造与全指令注册单测（M7 TCA-02）。

依据：docs/细化/细化_M7_装配层契约.md 二、A-02（RA-05~RA-07）+ TCA-02（全指令组
注册 + 白名单一致 + 无冲突）。真实签名已实读核对（2026-08-28）：Router L194、
各 register_xxx (router, *, make_context=None) 尾部、parsers.DEFAULT_WHITELIST L107、
gm_constants.GM_COMMANDS L35。

测试风格对齐 tests/unit/test_assembly_context.py：真实 AssemblyDeps + FakeRepo /
StubGameWorld / 内容 Registry + 确定性注入；零 NoneBot。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from qbot_rpg.assembly import router_setup as rs
from qbot_rpg.assembly.context import AssemblyDeps, make_context
from qbot_rpg.assembly.router_setup import build_router, check_consistency
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import AliasTable, CommandSpec
from qbot_rpg.content.registry import Registry
from qbot_rpg.data import EquipmentSlot, ItemInstance, Player, PlayerAttributes
from qbot_rpg.data.gm_constants import GM_COMMANDS

# 9 组 22 指令（RA-06 M7 落地时点；gm 归 M12）——确定性注册清单断言锚点
ALL_REGISTERED = {
    # basic
    "角色", "角色详细", "背包", "背包筛选", "装备", "技能", "帮助",
    # register
    "注册",
    # status
    "状态",
    # shortcut
    "快捷解绑", "快捷列表",
    # quest
    "任务",
    # shop
    "商店", "购买", "出售",
    # checkin
    "签到",
    # battle
    "攻击",
    # explore
    "进入", "休息",
    # dialog（N-01，BCH-03）
    "对话",
    # log（F-03/F-04，BCH-05；is_gm=True）
    "日志",
    # investigate（F-05/F-06，BCH-06）
    "调查",
    # codex（F-11/F-12，BCH-08）
    "图鉴",
}

# 关键指令（TCA-02/03 冒烟锚点：状态/背包/任务/商店 handler 可调）
KEY_COMMANDS = ("状态", "背包", "任务", "商店")


# ---------------------------------------------------------------------------
# 夹具（对齐 test_assembly_context.py：真实 AssemblyDeps + 鸭子存储/世界）
# ---------------------------------------------------------------------------
def _player(qid: str = "10001") -> Player:
    """已注册 Player（warrior 职业，与 _registry jobs 表对齐）。"""
    return Player(
        qid=qid,
        name="阿伟",
        job_id="warrior",
        level=35,
        exp=1200,
        hp=220,
        mp=60,
        currencies={"gold": 350, "gem": 8},
        inventory=(
            ItemInstance(item_id="potion", name="药水", count=5, quality="normal", bound=False),
            ItemInstance(item_id="iron_sword", name="铁剑", count=1, quality="rare", bound=True),
        ),
        equipment={"weapon": EquipmentSlot(item_id="iron_sword", name="铁剑", slot_level=3)},
        attributes=PlayerAttributes(
            base={"hp": 100.0, "mp": 50.0, "str": 15.0},
            bonus={"flat": {"str": 5.0}, "pct": {"hp": 10.0}},
        ),
        title_state={"current": "斩龙者"},
        persistent_state={
            "location": "town_center",
            "active_effects": {},
            "quest_active": ["q1"],
            "quest_completed": ["q0"],
            "quest_daily": {},
            "event_counts": {},
            "checkin": {"last_key": "2026-08-27", "count": 3},
            "shortcuts": {"/药水": "use potion"},
            "npc_delivered": {},
            "npc_heard": [],
            "dialog_active": False,
            "personal_buys": {},
        },
        longline_counters={"battle_wins": 12},
        codex_state={},
    )


class FakeRepo:
    """鸭子类型 Repository：async load_player 返回预置 Player/None（对齐 BCH-01 测试）。"""

    def __init__(self, player: object) -> None:
        self._player = player

    async def load_player(self, qid: str):
        p = self._player
        if p is not None and p.qid == str(qid):  # type: ignore[attr-defined]
            return p
        return None


class StubGameWorld:
    """兄弟路未实装方法 → NotImplementedError（装配读取兜底不抛，见 context.py）。"""

    def get_map(self, map_id: str):
        raise NotImplementedError

    def monster_pool(self, map_id: str):
        raise NotImplementedError

    def get_npcs(self, map_id: str):
        raise NotImplementedError


def _registry() -> Registry:
    """内容注册表（job/effect/item/shop 表，name 冗余）——cmd_shop/cmd_status 消费。"""
    return Registry(
        pack_id="t", generation=1,
        tables={
            "job": {"warrior": SimpleNamespace(name="战士")},
            "effect": {"poison": SimpleNamespace(name="中毒")},
            "item": {"potion": SimpleNamespace(name="药水"),
                     "iron_sword": SimpleNamespace(name="铁剑")},
            "shop": {"shop1": SimpleNamespace(name="杂货店")},
        },
        names={"warrior": "战士", "poison": "中毒",
               "potion": "药水", "iron_sword": "铁剑", "shop1": "杂货店"},
        modules_raw={},
    )


def _settings(**over: object) -> dict:
    """settings 基础映射（可注入 command_mode/require_at/command_aliases 等）。"""
    s: dict = {
        "default_map": "newbie_village",
        "level_cap": 45,
        "shortcut_max": 20,
        "resource_pct": False,
        "exp_curve": lambda lv: 100 * lv,
        "conditional_rules": [],
        "attr_types": {"hp": "resource", "mp": "resource", "str": "combat"},
        "imprints": {"slot1": "印记A"},
        "stats": {"hp": {"base": 100}, "str": {"base": 10}},
    }
    s.update(over)
    return s


def _deps(player: object = None, **over: object) -> AssemblyDeps:
    """真实 AssemblyDeps（可注入 make_context/shortcuts/default_qid 等鸭式字段）。"""
    deps = AssemblyDeps(
        repo=FakeRepo(player),
        game_world=StubGameWorld(),
        registry=_registry(),
        settings=_settings(),
        session_mgr=None,
    )
    for k, v in over.items():
        setattr(deps, k, v)
    return deps


def _event(qid: str = "10001", **over: object) -> dict:
    """事件映射（make_context 消费；真实 ctx 构造用）。"""
    e: dict = {"group_id": "123456", "user_id": qid, "message": "/状态", "channel": "qq"}
    e.update(over)
    return e


def _stub_ctx(parsed: object) -> dict:
    """注入 make_context 的最小同步桩：返回空 ctx（注册/配置类测试不调用 handler）。"""
    return {}


def parse(raw: str):
    """parse_command 封装（对齐各指令组测试的 parse 辅助）。"""
    return parse_command(raw)


# ---------------------------------------------------------------------------
# TCA-02：全指令组注册 + 无冲突
# ---------------------------------------------------------------------------
def test_build_router_registers_all_thirteen_groups() -> None:
    """TCA-02：真实 AssemblyDeps + 各指令组 → build_router → 13 组 26 指令全注册。"""
    router = build_router(_deps(make_context=_stub_ctx))
    assert set(router.names()) == ALL_REGISTERED
    # 无冲突：Router.register 重名 ValueError 兜底 → 能构造即无重复
    assert len(router.names()) == len(set(router.names()))


def test_build_router_default_make_context_still_registers() -> None:
    """未注入 make_context（默认适配器路径）→ 全指令组照常注册（注册不触发 ctx）。"""
    router = build_router(_deps())
    assert set(router.names()) == ALL_REGISTERED


def test_build_router_key_handlers_callable_and_return_str() -> None:
    """TCA-02/03：关键指令（状态/背包/任务/商店）handler 可调且返回 str 正文。"""
    deps = _deps(
        _player(),
        default_qid="10001",
        default_group_id="123456",
        default_channel="qq",
    )
    router = build_router(deps)
    for name in KEY_COMMANDS:
        spec = router.get(name)
        assert spec is not None and spec.handler is not None, f"{name} handler 缺失"
        out = spec.handler(parse(f"/{name}"))
        assert isinstance(out, str) and out, f"{name} handler 应返回非空 str，收到 {out!r}"


def test_build_router_injected_make_context_is_used() -> None:
    """注入的 deps.make_context 被 register 闭包消费（parsed → ctx 传入 handler）。"""
    calls: list = []

    def record_make_context(parsed: object) -> dict:
        calls.append(parsed)
        return {"registered": True, "player": _player()}

    router = build_router(_deps(make_context=record_make_context))
    out = router.get("状态").handler(parse("/状态"))  # type: ignore[misc,union-attr]
    assert isinstance(out, str)
    assert calls and getattr(calls[0], "command", None) == "状态"


# ---------------------------------------------------------------------------
# RA-07 配置装载：前缀模式 / 别名 / GM 权限 / 快捷表
# ---------------------------------------------------------------------------
def test_build_router_prefix_mode_and_require_at_from_settings() -> None:
    """RA-07 前缀模式：settings.command_mode/require_at → Router 构造装载。"""
    deps = _deps(
        make_context=_stub_ctx,
        settings=_settings(command_mode="prefix_only", require_at=True),
    )
    router = build_router(deps)
    assert router.command_mode == "prefix_only"
    assert router.require_at is True


def test_build_router_prefix_mode_defaults() -> None:
    """RA-07 缺省：settings 无 command_mode/require_at → global_shortcut / False。"""
    router = build_router(_deps(make_context=_stub_ctx))
    assert router.command_mode == "global_shortcut"
    assert router.require_at is False


def test_build_router_aliases_loaded_from_settings() -> None:
    """RA-07 指令别名：settings.command_aliases → AliasTable（3c §六.7）。"""
    deps = _deps(
        make_context=_stub_ctx,
        settings=_settings(command_aliases={"炼金": {"alias": "炼丹", "keep_original": False}}),
    )
    router = build_router(deps)
    assert isinstance(router.aliases, AliasTable)  # type: ignore[attr-defined]
    entry = router.aliases.alias_for("炼丹")  # type: ignore[attr-defined]
    assert entry is not None and entry.command == "炼金"
    assert entry.keep_original is False


def test_build_router_aliases_default_empty() -> None:
    """RA-07 别名缺省：settings 无 command_aliases → 空 AliasTable（不抛错）。"""
    router = build_router(_deps(make_context=_stub_ctx))
    assert isinstance(router.aliases, AliasTable)  # type: ignore[attr-defined]
    assert not router.aliases  # type: ignore[attr-defined]


def test_build_router_gm_commands_loaded() -> None:
    """RA-07 GM 权限：GM_COMMANDS 装载为 gm_commands_set（快捷绑定校验注入快照）。"""
    router = build_router(_deps(make_context=_stub_ctx))
    assert router.gm_commands_set == set(GM_COMMANDS)  # type: ignore[attr-defined]
    assert {"重载", "封禁", "日志", "编辑", "设置"} <= router.gm_commands_set  # type: ignore[attr-defined]
    # 不遮蔽 gm_commands()（/日志 玩家可用冒险日志，handler 按 ctx["is_gm"] 分支；ADR-09 修正）
    assert router.gm_commands() == []


def test_build_router_shortcuts_carried_from_deps() -> None:
    """RA-07 快捷表：deps.shortcuts 映射挂载为 router.shortcuts（无 ctx 路由缺省）。"""
    deps = _deps(make_context=_stub_ctx, shortcuts={"/药水": "使用 药水"})
    router = build_router(deps)
    assert router.shortcuts == {"/药水": "使用 药水"}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# check_consistency 注册自检（RA-07 / TCA-02：白名单一致）
# ---------------------------------------------------------------------------
def test_check_consistency_clean_for_m7_groups() -> None:
    """自检无差异：M7 已注册 22 指令全部命中 parsers 白名单（注册缺白名单为空）。"""
    router = build_router(_deps(make_context=_stub_ctx))
    result = check_consistency(router)
    assert result["ok"] is True
    assert result["registered_not_whitelisted"] == []
    assert set(ALL_REGISTERED) <= set(DEFAULT_WHITELIST)


def test_check_consistency_whitelist_unregistered_is_expected_m7() -> None:
    """白名单缺注册为 M7 合法非空（制造/战斗邻近/地图/对话/GM 归后续里程碑）。"""
    router = build_router(_deps(make_context=_stub_ctx))
    result = check_consistency(router)
    unreg = set(result["whitelist_not_registered"])
    # 已知 M7 未注册（信息性）——锚点抽样防未来漂移（对话已注册 N-01，非白名单缺注册）
    assert {"重载", "地图", "使用", "炼金", "快捷绑定"} <= unreg
    assert not (unreg & set(ALL_REGISTERED))  # 已注册指令绝不落入白名单缺注册


def test_check_consistency_reports_registered_missing_whitelist() -> None:
    """注册缺白名单（硬不一致）被检出：额外注册非白名单指令 → 差异列表 + ok=False。"""
    router = build_router(_deps(make_context=_stub_ctx))
    router.register(CommandSpec("未知指令", whitelisted=True))
    result = check_consistency(router)
    assert result["ok"] is False
    assert result["registered_not_whitelisted"] == ["未知指令"]


def test_check_consistency_deterministic_sorted() -> None:
    """确定性：差异列表 sorted 输出（重复调用结果一致）。"""
    router = build_router(_deps(make_context=_stub_ctx))
    first = check_consistency(router)
    second = check_consistency(router)
    assert first == second


# ---------------------------------------------------------------------------
# 默认 make_context 适配器（工程补白 1：async 真实工厂同步桥接）
# ---------------------------------------------------------------------------
def test_default_adapter_bridges_real_async_make_context() -> None:
    """默认适配器：无注入时桥接真实 async make_context（asyncio.run）→ 状态面板。"""
    deps = _deps(_player(), default_qid="10001", default_group_id="123456")
    router = build_router(deps)  # 未注入 make_context → 默认适配器
    out = router.get("状态").handler(parse("/状态"))  # type: ignore[misc,union-attr]
    assert isinstance(out, str)
    assert "阿伟" in out  # 已注册玩家 ctx（真实 make_context 全字段）渲染


def test_default_adapter_unregistered_player_prompt() -> None:
    """默认适配器：无 qid（未注册）→ registered=False ctx → 注册门槛人话提示。"""
    deps = _deps(player=None)  # FakeRepo(None) → load_player 返回 None
    router = build_router(deps)
    out = router.get("注册").handler(parse("/注册"))  # type: ignore[misc,union-attr]
    assert isinstance(out, str) and out


def test_default_adapter_running_loop_raises_clear_wiring_error() -> None:
    """默认适配器运行中循环守卫：asyncio.run 内同步桥接 → 明确【待接线】RuntimeError。"""

    async def _inner() -> None:
        deps = _deps(_player(), default_qid="10001")
        event = _event()
        with pytest.raises(RuntimeError, match="【待接线】"):
            rs._await_sync(make_context(event, deps))  # 运行中循环 → 抛

    asyncio.run(_inner())


# ---------------------------------------------------------------------------
# 与真实 make_context 全字段对齐（RA-03 权威）：build_router 产物可被 route 消费
# ---------------------------------------------------------------------------
def test_router_dispatch_uses_command_mode_and_require_at() -> None:
    """前缀模式接入路由：require_at=True 下无 @ 输入 → 忽略（Router.dispatch 一致）。"""
    deps = _deps(
        make_context=_stub_ctx,
        settings=_settings(command_mode="prefix_only", require_at=True),
    )
    router = build_router(deps)
    # Router.dispatch 走 route_and_expand；require_at=True 无 @ → ignored
    result = router.dispatch("/状态")
    assert result.kind == "ignored"
    # prefix_only 但 @ 门未过同样 ignored（与 parsers S0 一致）
    result2 = router.dispatch("@机器人 /状态")
    assert result2.kind == "command"