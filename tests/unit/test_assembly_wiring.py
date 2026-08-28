"""tests/unit/test_assembly_wiring.py — M7 N-02 世界层 NPC 挂载收口 + 装配层事件 hook 接线。

依据：
  - docs/细化/细化_M7_NPC对话接线.md（N-02 RN-05~RN-08 + N-03 RN-10 三表管线）
  - docs/细化/细化_M7_装配层契约.md（A-01 RA-03 ctx 字段全景 / RA-04 事务写路径）
  - docs/细化/细化_M7_交互补全总纲.md（BCH-04 批序 / ADR-05 事件双表 + event_log 环形）
  - docs/细化/细化_3f_单机向体验.md（F-09 / D-05 隐藏任务条件全与 + 零暗示不提示原则）

本文件为 BCH-04 N-02 挂载收口单测：以 A-01 make_context 为唯一装配入口（真实签名
async make_context(event, deps)），驱动**真实引擎**（npc.dispatch_action / available_quests
/ quest.quest_accept / quest_available / shop.resolve_shop_arg / dialog_commands 壳），
验证装配链路可消费。零 NoneBot import；纯函数确定性（rng/now 注入）。

覆盖：
  - make_context npcs 注入（有 NPC 地图 / 无 NPC → [] / 兄弟路未实装方法 → []）
  - make_context bump_event hook 注入（event_counts + longline_counters + event_log
    三表生效，且 [事件:*] 条件可回读）
  - NPC 对话 → 商店移交 → current_shop_ref 改写 → /商店 回店链路
  - NPC intel 交付 → ctx["codex_state"] 图鉴点亮
  - NPC quest 卡 → npc.available_quests 过滤（SM06 去重 + 条件）→ quest 引擎接取
  - 隐藏任务条件全与（3f D-05：满足才发；不满足 → 普通对话零暗示）
"""

from __future__ import annotations

from types import SimpleNamespace

from qbot_rpg.assembly.context import AssemblyDeps, _event_key_parts, make_context
from qbot_rpg.commands.dialog_commands import (
    DIALOG_CMD,
    _apply_shop_refs,
    _bump_events,
    cmd_dialog,
    cmd_dialog_session,
)
from qbot_rpg.commands.parsers import ParsedCommand
from qbot_rpg.content.registry import Registry
from qbot_rpg.core import npc as npc_mod
from qbot_rpg.core import quest as quest_mod
from qbot_rpg.core.npc import is_delivered
from qbot_rpg.core.shop import resolve_shop_arg
from qbot_rpg.data import Player, PlayerAttributes
from qbot_rpg.engine.condition_engine import eval_condition


# ---------------------------------------------------------------------------
# 夹具：NPC / world / registry / player / deps
# ---------------------------------------------------------------------------

# 与 test_dialog_commands 同口径的真实 NPC dict（dialog 引擎 parse 形态）
BLACKSMITH: dict = {
    "id": "blacksmith_zhou",
    "name": "铁匠·老周",
    "icon": "铁",
    "type": "blacksmith",
    "visible": True,
    "dialogues": {"greeting": "要修点什么？"},
    "interactions": [
        {"text": "接任务", "action": "quest", "quests": [{"quest_id": "q_fetch"}]},
        {"text": "打开商店", "action": "shop", "shop_refs": ["blacksmith_shop"]},
        {"text": "打听消息", "action": "intel", "intel_refs": [{"id": "lore1"}]},
    ],
}


def _player(qid: str = "10001", **over: object) -> Player:
    """构造已注册 Player（location=town_center，codex/事件表可覆盖）。"""
    attrs = PlayerAttributes(
        base={"hp": 100.0, "mp": 50.0, "str": 15.0},
        bonus={"flat": {"str": 5.0}, "pct": {"hp": 10.0}},
    )
    base: dict = dict(
        qid=qid, name="阿伟", job_id="warrior", level=35, exp=1200, hp=220, mp=60,
        currencies={"gold": 350, "gem": 8},
        inventory=(),
        equipment={},
        attributes=attrs,
        title_state={"current": "斩龙者"},
        persistent_state={
            "location": "town_center",
            "quest_active": [],
            "quest_completed": [],
            "quest_daily": {},
            "event_counts": {},
        },
        longline_counters={},
        codex_state={},
    )
    base.update(over)
    return Player(**base)


class FakeRepo:
    """鸭子类型 Repository：async load_player 返回预置 Player/None。"""

    def __init__(self, player: object) -> None:
        self._player = player

    async def load_player(self, qid: str):  # noqa: ANN001
        p = self._player
        if p is not None and p.qid == str(qid):  # type: ignore[attr-defined]
            return p
        return None


class StubGameWorld:
    """兄弟路未实装方法全部 NotImplementedError（验证 make_context 兜底不抛 → []）。"""

    def get_map(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError

    def monster_pool(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError

    def get_npcs(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError


class WorldWithNpcs:
    """已交付 get_npcs 的 GameWorld（BCH-01 路 B 形态）：返回铁匠 NPC 列表。"""

    def get_npcs(self, map_id: str) -> list:  # noqa: ANN001
        return [BLACKSMITH]

    def get_map(self, map_id: str):  # noqa: ANN001
        return None

    def monster_pool(self, map_id: str) -> list:  # noqa: ANN001
        return []


class WorldEmptyNpcs:
    """无 NPC 地图（get_npcs → []，RN-05 空列表口径）。"""

    def get_npcs(self, map_id: str) -> list:  # noqa: ANN001
        return []

    def get_map(self, map_id: str):  # noqa: ANN001
        return None

    def monster_pool(self, map_id: str) -> list:  # noqa: ANN001
        return []


class SessionMgrNone:
    def get_active(self, qid: str):  # noqa: ANN001
        return None


def _registry() -> Registry:
    """内容注册表（job/effect/item/shop；shop 以 dict 形态供 resolve_shop 解析回店）。"""
    return Registry(
        pack_id="t", generation=1,
        tables={
            "job": {"warrior": SimpleNamespace(name="战士")},
            "effect": {"poison": SimpleNamespace(name="中毒")},
            "item": {"potion": SimpleNamespace(name="药水")},
            "shop": {
                "blacksmith_shop": {"id": "blacksmith_shop", "name": "铁匠铺",
                                    "type": "normal", "icon": "铁"},
            },
        },
        names={"warrior": "战士", "poison": "中毒",
               "potion": "药水", "blacksmith_shop": "铁匠铺"},
        modules_raw={},
    )


def _settings(**over: object) -> dict:
    s: dict = {
        "default_map": "newbie_village",
        "level_cap": 45,
        "shortcut_max": 20,
        "resource_pct": False,
        "exp_curve": lambda lv: 100 * lv,
        "conditional_rules": [],
        "attr_types": {"hp": "resource", "mp": "resource", "str": "combat"},
        "imprints": {},
        "stats": {"hp": {"base": 100}, "str": {"base": 10}},
    }
    s.update(over)
    return s


def _deps(player: object, **over: object) -> AssemblyDeps:
    deps = AssemblyDeps(
        repo=FakeRepo(player),
        game_world=WorldEmptyNpcs(),
        registry=_registry(),
        settings=_settings(),
        session_mgr=SessionMgrNone(),
    )
    for k, v in over.items():
        setattr(deps, k, v)
    return deps


def _event(**over: object) -> dict:
    e: dict = {"group_id": "123456", "user_id": "10001", "message": "/对话", "channel": "qq"}
    e.update(over)
    return e


def _pc(*args: str) -> ParsedCommand:
    """构造 /对话 的 ParsedCommand（args 为 /对话 后的参数 token）。"""
    raw = ("/对话 " + " ".join(args)).strip()
    return ParsedCommand(raw, command=DIALOG_CMD, args=list(args))


# ---------------------------------------------------------------------------
# RN-05 npcs 注入（有 NPC / 无 NPC / 兄弟路未实装 → []）
# ---------------------------------------------------------------------------
async def test_make_context_injects_npcs_present() -> None:
    """RN-05：有 NPC 地图 → ctx['npcs'] 从 game_world.get_npcs(location) 读（完整 dict）。"""
    ctx = await make_context(_event(), _deps(_player(), game_world=WorldWithNpcs()))
    assert ctx["npcs"] == [BLACKSMITH]
    assert ctx["npcs"][0]["id"] == "blacksmith_zhou"
    assert ctx["npcs"][0]["visible"] is True


async def test_make_context_npcs_empty_when_no_npcs() -> None:
    """RN-05：无 NPC 地图（get_npcs → []）→ ctx['npcs'] == []（指令壳出空地图提示）。"""
    ctx = await make_context(_event(), _deps(_player(), game_world=WorldEmptyNpcs()))
    assert ctx["npcs"] == []


async def test_make_context_npcs_empty_when_world_missing_method() -> None:
    """RN-05 兜底：兄弟路 get_npcs 未实装（NotImplementedError）→ ctx['npcs'] == [] 不抛。"""
    ctx = await make_context(_event(), _deps(_player(), game_world=StubGameWorld()))
    assert ctx["npcs"] == []


async def test_make_context_npcs_empty_unregistered() -> None:
    """RN-05：未注册玩家 → ctx['npcs'] 安全空值 []（location 缺失兜底）。"""
    ctx = await make_context(_event(), _deps(None, game_world=WorldWithNpcs()))
    assert ctx["npcs"] == []


# ---------------------------------------------------------------------------
# RN-10 bump_event hook 注入（三表 + 条件可回读）
# ---------------------------------------------------------------------------
def test_fallback_bump_event_three_tables_readable_form() -> None:
    """RN-10：本地兜底 _fallback_bump_event 三表 + 条件可回读（确定性，独立于兄弟路实现）。

    event_counts 写条件引擎可读形态（[事件:NPC对话]:npc1 复合键 / 无参事件标量）——
    condition_engine._read_counter 扁平口径，[事件:*] 条件可回读（dsh P1-3）。
    """
    from qbot_rpg.assembly.context import _fallback_bump_event

    ctx = {"event_counts": {}, "longline_counters": {}, "event_log": [], "settings": {}}  # type: ignore[var-annotated]
    _fallback_bump_event(ctx, "[事件:NPC对话:blacksmith_zhou]")
    _fallback_bump_event(ctx, "[事件:副本通关]")
    # ① longline_counters：原始事件键（冒险日志累计口径）
    assert ctx["longline_counters"]["[事件:NPC对话:blacksmith_zhou]"] == 1  # type: ignore[index]
    assert ctx["longline_counters"]["[事件:副本通关]"] == 1  # type: ignore[index]
    # ② event_counts：条件引擎可读形态
    assert ctx["event_counts"]["[事件:NPC对话]:blacksmith_zhou"] == 1  # type: ignore[index]
    assert ctx["event_counts"]["[事件:副本通关]"] == 1  # type: ignore[index]
    # ③ event_log：环形实例日志（最小 {"key","ts"} 形态）
    assert len(ctx["event_log"]) == 2
    assert ctx["event_log"][0]["key"] == "[事件:NPC对话:blacksmith_zhou]"  # type: ignore[index]
    # ④ [事件:*] 条件回读
    assert eval_condition({"var": "[事件:NPC对话:blacksmith_zhou]", "op": "ge", "value": 1}, ctx)
    assert eval_condition({"var": "[事件:副本通关]", "op": "ge", "value": 1}, ctx)


async def test_make_context_injects_bump_event_hook_updates_three_tables() -> None:
    """RN-10：ctx['bump_event'] 可调；调用后 event_counts + longline_counters + event_log 三表生效。

    兄弟路 event_bus.py 已落盘（真实 hook，三表 + 3f E-01 富模型）；未落盘时惰性兜底
    _fallback_bump_event（同样三表）——本断言对双实现稳健（只断言增长与键归属）。
    """
    ctx = await make_context(_event(), _deps(_player(), game_world=WorldEmptyNpcs()))
    hook = ctx["bump_event"]
    assert callable(hook)
    # 三表容器齐备
    assert isinstance(ctx["event_counts"], dict)
    assert isinstance(ctx["longline_counters"], dict)
    assert isinstance(ctx["event_log"], list)
    before = (len(ctx["event_counts"]), len(ctx["longline_counters"]), len(ctx["event_log"]))
    key = "[事件:装配测试:unique_npc]"
    hook(ctx, key)
    after = (len(ctx["event_counts"]), len(ctx["longline_counters"]), len(ctx["event_log"]))
    assert after[0] > before[0]  # event_counts 增长
    assert after[1] > before[1]  # longline_counters 增长
    assert after[2] > before[2]  # event_log 增长
    # longline 原始键（双实现同口径）；event_counts 原始键或条件可读复合键任一归属
    assert ctx["longline_counters"].get(key, 0) >= 1
    assert (ctx["event_counts"].get(key, 0) >= 1
            or ctx["event_counts"].get("[事件:装配测试]:unique_npc", 0) >= 1)


async def test_make_context_bump_event_unregistered_safe() -> None:
    """RN-10：未注册玩家 → bump_event 仍注入可调（三表缺省空值不抛）。"""
    ctx = await make_context(_event(), _deps(None, game_world=WorldEmptyNpcs()))
    assert callable(ctx["bump_event"])
    assert ctx["event_log"] == []
    ctx["bump_event"](ctx, "[事件:签到]")
    assert ctx["event_counts"]["[事件:签到]"] == 1


async def test_bump_event_hook_consumed_by_dialog_commands() -> None:
    """RN-10 · N-03：dialog_commands._bump_events 优先消费 ctx['bump_event']（装配 hook）。"""
    ctx = await make_context(_event(), _deps(_player(), game_world=WorldEmptyNpcs()))
    before = (len(ctx["event_counts"]), len(ctx["longline_counters"]), len(ctx["event_log"]))
    _bump_events(ctx, ["[事件:NPC对话:blacksmith_zhou]", "[事件:副本通关]"])
    after = (len(ctx["event_counts"]), len(ctx["longline_counters"]), len(ctx["event_log"]))
    assert after[0] - before[0] >= 2  # event_counts 双键增长
    assert after[1] - before[1] >= 2  # longline_counters 双键增长
    assert after[2] - before[2] >= 2  # event_log 双实例增长


def test_event_key_parts_split() -> None:
    """事件键切分（对齐 condition_engine._parse_event_var）：内嵌目标 / 无参 / 非事件。"""
    assert _event_key_parts("[事件:NPC对话:blacksmith_zhou]") == \
        ("[事件:NPC对话]", "blacksmith_zhou")
    assert _event_key_parts("[事件:副本通关]") == ("[事件:副本通关]", None)
    assert _event_key_parts("foo") == ("foo", None)


# ---------------------------------------------------------------------------
# RN-06 当前商店连接：对话 → 商店移交 → current_shop_ref → /商店 回店
# ---------------------------------------------------------------------------
async def test_shop_handoff_dispatch_writes_current_shop_ref() -> None:
    """RN-06：装配 ctx → npc.dispatch_action(shop 条目) 改写 current_shop_ref → /商店 回店。"""
    ctx = await make_context(_event(), _deps(_player(), game_world=WorldWithNpcs()))
    assert ctx["current_shop_ref"] == []  # 初始无当前商店
    entry = {"action": "shop", "shop_refs": ["blacksmith_shop"]}
    res = npc_mod.dispatch_action(entry, ctx, ctx.get("rng"), "blacksmith_zhou")
    assert res["ok"] is True
    assert ctx["current_shop_ref"] == "blacksmith_shop"
    # /商店 无参 → 当前商店（地图级）直接回店（shop_refs[0]）
    assert resolve_shop_arg(None, ctx) == "blacksmith_shop"


async def test_shop_handoff_full_dialog_flow() -> None:
    """RN-06 · TCN-05：/对话 铁匠·老周 → 选 2（打开商店）→ current_shop_ref 改写 → 回店。"""
    ctx = await make_context(_event(), _deps(_player(), game_world=WorldWithNpcs()))
    out1 = cmd_dialog(_pc("铁匠·老周"), ctx)
    assert "铁匠·老周：" in out1
    assert ctx["current_shop_ref"] == []
    out2 = cmd_dialog_session(("digit", 2), ctx)
    assert "已打开商店" in out2
    assert ctx["current_shop_ref"] == "blacksmith_shop"
    # 后续 /商店（resolve_shop_arg 无参）直接回店
    assert resolve_shop_arg(None, ctx) == "blacksmith_shop"


async def test_shop_handoff_apply_shop_refs_idempotent() -> None:
    """RN-06：dialog result.shop_refs → _apply_shop_refs 写首个；非空 → 幂等跳过。"""
    ctx = await make_context(_event(), _deps(_player(), game_world=WorldEmptyNpcs()))
    assert ctx["current_shop_ref"] == []
    _apply_shop_refs(ctx, ["blacksmith_shop", "general_shop"])
    assert ctx["current_shop_ref"] == "blacksmith_shop"
    _apply_shop_refs(ctx, ["other_shop"])  # 已写 → 不覆盖
    assert ctx["current_shop_ref"] == "blacksmith_shop"


# ---------------------------------------------------------------------------
# RN-07 quest / codex 联动
# ---------------------------------------------------------------------------
async def test_intel_delivery_lights_codex_state() -> None:
    """RN-07：NPC intel 交付 → ctx['codex_state'] 图鉴点亮 + npc_delivered 已听（双轨）。"""
    ctx = await make_context(_event(), _deps(_player(), game_world=WorldWithNpcs()))
    assert ctx["codex_state"] == {}  # player.codex_state 注入装配 ctx
    entry = {"action": "intel", "intel_refs": [{"id": "lore1"}]}
    res = npc_mod.dispatch_action(entry, ctx, ctx.get("rng"), "blacksmith_zhou")
    assert res["ok"] is True and res["delivered"] is True
    assert ctx["codex_state"]["lore1"] is True
    assert is_delivered(ctx, "blacksmith_zhou", "intel:lore1")
    # 一次一物：已听后重复交付 → already 置灰（不死胡同）
    res2 = npc_mod.dispatch_action(entry, ctx, ctx.get("rng"), "blacksmith_zhou")
    assert res2["already"] is True


async def test_intel_delivery_via_dialog_flow_lights_codex() -> None:
    """RN-07 · TCN-07：/对话 铁匠·老周 → 选 3（打听消息）→ codex_state 点亮 + 已听双轨。"""
    ctx = await make_context(_event(), _deps(_player(), game_world=WorldWithNpcs()))
    cmd_dialog(_pc("铁匠·老周"), ctx)
    out = cmd_dialog_session(("digit", 3), ctx)
    assert "打听消息" in out
    assert ctx["codex_state"].get("lore1") is True
    assert is_delivered(ctx, "blacksmith_zhou", "intel:lore1")


def test_quest_card_filtered_by_available_quests() -> None:
    """RN-07 · SM06：npc.available_quests 过滤（活跃/已完成/条件不满足剔除，顺序即优先级）。"""
    ctx = {
        "quest_active": {"q_active": {"name": "进行中"}},
        "quest_completed": ["q_completed"],
        "quest_daily": {},
        "event_counts": {},
    }
    deliver = {"quests": [
        {"quest_id": "q_active"},
        {"quest_id": "q_completed"},
        {"quest_id": "q_locked", "condition": {"var": "[事件:解锁]", "op": "ge", "value": 1}},
        {"quest_id": "q_ok"},
    ]}
    avail = npc_mod.available_quests(deliver, ctx)
    assert [q["quest_id"] for q in avail] == ["q_ok"]


def _int_now_deps(player: object, **over: object) -> AssemblyDeps:
    """quest 引擎用 deps：dayroll 注入 int 秒 now（quest._now 期望 UTC+8 秒级时间戳）。"""
    return _deps(player, dayroll=lambda: (1756000000, "2026-08-28"), **over)


async def test_quest_card_accept_via_quest_engine() -> None:
    """RN-07：NPC quest 卡 → available_quests 命中 → quest 引擎接取 → quest_active 入表。"""
    ctx = await make_context(_event(), _int_now_deps(_player(), game_world=WorldEmptyNpcs()))
    ctx["quests"] = {
        "q_hidden": {"id": "q_hidden", "name": "村长的委托",
                     "board": {"slot": "daily", "accept_limit": 5, "daily_limit": 10},
                     "conditions": [{"var": "level", "op": "ge", "value": 1}]},
    }
    deliver = {"quests": [{"quest_id": "q_hidden"}]}
    assert [q["quest_id"] for q in npc_mod.available_quests(deliver, ctx)] == ["q_hidden"]
    res = quest_mod.quest_accept("q_hidden", ctx)
    assert res["ok"] is True
    assert "q_hidden" in ctx["quest_active"]
    # 已接取 → 不再重复发（SM06 去重）
    assert npc_mod.available_quests(deliver, ctx) == []


# ---------------------------------------------------------------------------
# RN-08 隐藏任务条件全与（3f F-09 / D-05）：满足才发；不满足 → 零暗示
# ---------------------------------------------------------------------------
def test_hidden_quest_all_and_conditions_at_quest_engine() -> None:
    """RN-08 · D-05：quest.npc.conditions 组合全与（quest_available 对裸条件数组求值）。

    quest_available 文档口径：「NPC 差异化发任务候选走 quest.npc.conditions（发任务条件，
    §1.4），本入口对裸条件数组直接求值」——传 quest.npc.conditions 数组断言全与；
    任一不满足即不发。npc.py 发任务路径消费 quest.npc.conditions 的接线登记工程补白
    （BCH-07 3f 批次实现，见 npc.py 模块头补白 11）。
    """
    npc_conditions = [
        {"var": "codex", "op": "ge", "value": 50},
        {"var": "[事件:雨夜]", "op": "ge", "value": 1},
    ]
    met = {"codex": 60, "event_counts": {"[事件:雨夜]": 2}}
    assert quest_mod.quest_available(npc_conditions, met) is True
    # 图鉴不满足 → 不发
    assert quest_mod.quest_available(
        npc_conditions, {"codex": 30, "event_counts": {"[事件:雨夜]": 2}}) is False
    # 事件不满足 → 不发
    assert quest_mod.quest_available(npc_conditions, {"codex": 60, "event_counts": {}}) is False


async def test_hidden_quest_unmet_zero_hint() -> None:
    """RN-08 · 零暗示：quest 卡 condition 不满足 → no_available_quest（无任务 id，普通对话）。"""
    ctx = await make_context(_event(), _int_now_deps(_player(), game_world=WorldEmptyNpcs()))
    ctx["quests"] = {
        "q_hidden": {"id": "q_hidden", "name": "雨夜之谜",
                     "board": {"slot": "daily", "accept_limit": 5, "daily_limit": 10},
                     "conditions": []},
    }
    entry = {"action": "quest", "quests": [
        {"quest_id": "q_hidden", "condition": {"var": "[事件:雨夜]", "op": "ge", "value": 1}},
    ]}
    # 事件未触发 → 不满足 → 不发任务（零暗示：data 无 quest_id）
    res = npc_mod.dispatch_action(entry, ctx, ctx.get("rng"), "npc1")
    assert res["ok"] is False
    assert res["reason"] == "no_available_quest"
    assert res.get("data") is None


async def test_hidden_quest_condition_met_offers_quest() -> None:
    """RN-08：quest 卡 condition 满足 → 发任务（data.quest_id 命中），可经 quest 引擎接取。"""
    ctx = await make_context(_event(), _int_now_deps(_player(), game_world=WorldEmptyNpcs()))
    ctx["quests"] = {
        "q_hidden": {"id": "q_hidden", "name": "雨夜之谜",
                     "board": {"slot": "daily", "accept_limit": 5, "daily_limit": 10},
                     "conditions": []},
    }
    ctx["event_counts"]["[事件:雨夜]"] = 1  # 满足发任务条件
    entry = {"action": "quest", "quests": [
        {"quest_id": "q_hidden", "condition": {"var": "[事件:雨夜]", "op": "ge", "value": 1}},
    ]}
    res = npc_mod.dispatch_action(entry, ctx, ctx.get("rng"), "npc1")
    assert res["ok"] is True
    assert res["data"]["quest_id"] == "q_hidden"
    assert quest_mod.quest_accept("q_hidden", ctx)["ok"] is True
    assert "q_hidden" in ctx["quest_active"]