"""tests/unit/test_assembly_context.py — A-01 make_context 工厂单测（M7 RA-03 全字段 + 缺省兜底）。

依据：docs/细化/细化_M7_装配层契约.md 一、A-01（RA-01~RA-04）+ TCA-01（构造已注册
玩家 + 完整 deps 调 make_context → 全字段齐备，缺省兜底生效）。

覆盖：全字段存在性 / registered 两态 / 缺省兜底（不抛异常）/ 双形态背包 / 职业/称号/
最终属性 / exp_next / 入包 hook / 效果渲染 / 世界/会话/环境确定性注入 / GM 集合 /
兄弟路 game_world 未实装方法不阻塞。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from qbot_rpg.assembly.context import AssemblyDeps, make_context
from qbot_rpg.content.registry import Registry
from qbot_rpg.data import EquipmentSlot, ItemInstance, Player, PlayerAttributes

# RA-03 全景字段（权威表 1.3 节；TCA-01 逐字段断言）
RA03_FIELDS = (
    "registered", "player",
    "name", "job_id", "level", "exp", "hp", "mp",
    "job_name", "location", "title", "stats", "attributes",
    "attr_final", "exp_next", "level_cap",
    "conditional_rules", "attr_types", "imprints",
    "inventory", "inventory_items", "equipment", "worn_refs",
    "active_effects", "effects",
    "quest_engine", "quest_active", "quest_completed", "quest_daily",
    "longline_counters", "event_counts",
    "shop_engine", "current_shop_ref", "currencies",
    "world_stock", "world_sold_out",
    "checkin_engine", "checkin_state",
    "shortcuts", "shortcut_max", "gm_commands",
    "npc_delivered", "heard", "npcs", "npc_interactions",
    "dialog_active", "dialog_session",
    "season", "period", "weather",
    "battle_engine", "battle_session", "target", "turn",
    "battle_reward_fn", "battle_rewards", "battle_hint", "battle_status_changes",
    "game_world", "map_def", "monster_pool",
    "rng", "now", "today",
    "group_name", "per_channel", "channel", "to", "qq_id", "is_gm",
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _player(qid: str = "10001", **over: object) -> Player:
    """构造已注册 Player（覆盖 conftest make_player，自含避免依赖 tests 包）。"""
    attrs = PlayerAttributes(
        base={"hp": 100.0, "mp": 50.0, "str": 15.0},
        bonus={"flat": {"str": 5.0}, "pct": {"hp": 10.0}},
    )
    inv = (
        ItemInstance(item_id="potion", name="药水", count=2, quality="normal", bound=False),
        ItemInstance(item_id="iron_sword", name="铁剑", count=1, quality="rare",
                     bound=True, slot="weapon"),
    )
    base: dict = dict(
        qid=qid, name="阿伟", job_id="warrior", level=35, exp=1200, hp=220, mp=60,
        currencies={"gold": 350, "gem": 8},
        inventory=inv,
        equipment={"weapon": EquipmentSlot(item_id="iron_sword", name="铁剑", slot_level=3)},
        attributes=attrs,
        title_state={"current": "斩龙者"},
        persistent_state={
            "location": "town_center",
            "active_effects": {"poison": {"effect": "poison", "turns": 2, "refreshed": 0}},
            "quest_active": ["q1"],
            "quest_completed": ["q0"],
            "quest_daily": {"key": "2026-08-28", "completed": 1},
            "event_counts": {"battle:slime": 5},
            "checkin": {"last_key": "2026-08-27", "count": 3},
            "shortcuts": {"/药水": "use potion"},
            "npc_delivered": {"intel:ref1": True},
            "npc_heard": ["intro1"],
            "dialog_active": False,
            "personal_buys": {"shop1": {"potion": {"count": 2, "key": "2026-08-28"}}},
        },
        longline_counters={"battle_wins": 12},
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
    """兄弟路未实装方法全部 NotImplementedError（验证 make_context 兜底不抛）。"""

    def get_map(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError

    def monster_pool(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError

    def get_npcs(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError


class WorldWithNpcs:
    """已交付 get_npcs 的 GameWorld（BCH-01 路 B 交付后形态）。"""

    def get_npcs(self, map_id: str) -> list:  # noqa: ANN001
        return [{"id": "npc1", "name": "村长"}]

    def get_map(self, map_id: str):  # noqa: ANN001
        return None

    def monster_pool(self, map_id: str) -> list:  # noqa: ANN001
        return ["slime"]


class SessionMgrNone:
    def get_active(self, qid: str):  # noqa: ANN001
        return None


class SessionMgrNotImpl:
    def get_active(self, qid: str):  # noqa: ANN001
        raise NotImplementedError


def _registry() -> Registry:
    """内容注册表（job/effect/item/shop 表，name 冗余）。"""
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


def _deps(player: object, **over: object) -> AssemblyDeps:
    deps = AssemblyDeps(
        repo=FakeRepo(player),
        game_world=StubGameWorld(),
        registry=_registry(),
        settings=_settings(),
        session_mgr=SessionMgrNone(),
    )
    for k, v in over.items():
        setattr(deps, k, v)
    return deps


def _event(**over: object) -> dict:
    e: dict = {"group_id": "123456", "user_id": "10001", "message": "/状态", "channel": "qq"}
    e.update(over)
    return e


# ---------------------------------------------------------------------------
# TCA-01 全字段 + 注册态
# ---------------------------------------------------------------------------
async def test_registered_full_fields_all_present() -> None:
    """TCA-01：已注册玩家 + 完整 deps → RA-03 全字段齐备（逐字段断言存在）。"""
    ctx = await make_context(_event(), _deps(_player()))
    for k in RA03_FIELDS:
        assert k in ctx, f"RA-03 字段缺失: {k}"
    assert ctx["registered"] is True
    assert ctx["player"] is not None


async def test_registered_scalar_values() -> None:
    """已注册：name/job_id/level/exp/hp/mp/职业名/称号/位置/货币 取值正确。"""
    ctx = await make_context(_event(), _deps(_player()))
    assert ctx["name"] == "阿伟"
    assert ctx["job_id"] == "warrior"
    assert ctx["level"] == 35
    assert ctx["exp"] == 1200
    assert ctx["hp"] == 220
    assert ctx["mp"] == 60
    assert ctx["job_name"] == "战士"
    assert ctx["title"] == "斩龙者"
    assert ctx["location"] == "town_center"      # persistent_state 优先
    assert ctx["currencies"] == {"gold": 350, "gem": 8}
    assert ctx["worn_refs"] == {"weapon": "iron_sword"}


async def test_unregistered_player_fields_none() -> None:
    """未注册（repo 无档）：registered=False，player 相关标量 None + 集合安全空值。"""
    ctx = await make_context(_event(), _deps(None))
    assert ctx["registered"] is False
    assert ctx["player"] is None
    for k in ("name", "job_id", "level", "exp", "hp", "mp",
              "job_name", "location", "title", "attributes"):
        assert ctx[k] is None, f"未注册 {k} 应为 None"
    assert ctx["inventory"] == {}
    assert ctx["inventory_items"] == []
    assert ctx["effects"] == []
    assert ctx["attr_final"] == {}


async def test_other_qid_not_registered() -> None:
    """repo 有档但 qid 不匹配 → 视为未注册（读档按 qid）。"""
    ctx = await make_context(_event(user_id="99999"), _deps(_player(qid="10001")))
    assert ctx["registered"] is False
    assert ctx["player"] is None


# ---------------------------------------------------------------------------
# 缺省兜底（不抛异常）
# ---------------------------------------------------------------------------
async def test_optional_deps_defaults_no_crash() -> None:
    """仅 repo/game_world/registry/settings（其余缺省）→ 不抛异常，确定性兜底。"""
    deps = AssemblyDeps(repo=FakeRepo(_player()), game_world=StubGameWorld(),
                        registry=_registry(), settings=_settings())
    ctx = await make_context(_event(), deps)
    assert isinstance(ctx["rng"], random.Random)
    assert ctx["now"] is not None  # 默认 dayroll → UTC+8 datetime
    assert isinstance(ctx["today"], str) and ctx["today"]
    assert ctx["season"] == "--" and ctx["period"] == "--" and ctx["weather"] == "--"
    assert ctx["battle_session"] is None and ctx["target"] is None and ctx["turn"] is None


async def test_explicit_none_env_deps() -> None:
    """rng_factory/dayroll/time_query/weather_query 显式 None → 不抛，缺省 "--"/None。"""
    deps = _deps(_player(), rng_factory=None, dayroll=None, time_query=None, weather_query=None)
    ctx = await make_context(_event(), deps)
    assert isinstance(ctx["rng"], random.Random)
    assert ctx["now"] is None
    assert ctx["today"] == ""
    assert ctx["season"] == "--" and ctx["weather"] == "--"


async def test_game_world_stubs_no_raise() -> None:
    """兄弟路 game_world 未实装（get_map/monster_pool/get_npcs 抛 NotImplementedError）→ 不阻塞。"""
    ctx = await make_context(_event(), _deps(_player()))
    assert ctx["map_def"] is None
    assert ctx["monster_pool"] == []
    assert ctx["npcs"] == []


async def test_session_mgr_notimpl_no_raise() -> None:
    """session_mgr.get_active 抛 NotImplementedError → battle_session 缺省 None。"""
    deps = _deps(_player())
    deps.session_mgr = SessionMgrNotImpl()
    ctx = await make_context(_event(), deps)
    assert ctx["battle_session"] is None
    assert ctx["target"] is None and ctx["turn"] is None


# ---------------------------------------------------------------------------
# 双形态背包 + 入包 hook
# ---------------------------------------------------------------------------
async def test_inventory_dual_form() -> None:
    """inventory={item_id: count} 计数映射；inventory_items=list[ItemInstance] 展示列表。"""
    ctx = await make_context(_event(), _deps(_player()))
    assert ctx["inventory"] == {"potion": 2, "iron_sword": 1}
    assert len(ctx["inventory_items"]) == 2
    assert all(isinstance(i, ItemInstance) for i in ctx["inventory_items"])


async def test_inventory_hooks() -> None:
    """add_item/remove_item/count_item 操作 ctx 内计数映射（reward.py/shop.py 契约）。"""
    ctx = await make_context(_event(), _deps(_player()))
    assert ctx["count_item"]("potion") == 2
    assert ctx["add_item"]("potion", 3) is True
    assert ctx["count_item"]("potion") == 5
    assert ctx["remove_item"]("potion", 2) is True
    assert ctx["count_item"]("potion") == 3
    assert ctx["remove_item"]("potion", 99) is False   # 不够数不扣
    assert ctx["add_item"]("potion", 0) is False        # 非法数量不入包
    assert ctx["add_item"]("elixir", 1) is True         # 新 id 入包
    assert ctx["count_item"]("elixir") == 1


# ---------------------------------------------------------------------------
# 计算字段
# ---------------------------------------------------------------------------
async def test_attr_final_computed() -> None:
    """attr_final = calc_all_final_attributes 出口（hp 吃 pct、str 吃 flat）。"""
    # resource_pct=True：资源属性（hp）才吃百分比加成（框架默认 False 时 hp 不吃 pct）
    ctx = await make_context(_event(), _deps(_player(), settings=_settings(resource_pct=True)))
    af = ctx["attr_final"]
    assert af["hp"] == 110     # 100 × (1 + 10%)
    assert af["str"] == 20     # 15 + 5
    assert af["mp"] == 50      # 无加成


async def test_attr_final_resource_pct_default_off() -> None:
    """默认 resource_pct=False：资源属性（hp/mp）不乘 pct 百分比（框架语义）。"""
    ctx = await make_context(_event(), _deps(_player()))
    af = ctx["attr_final"]
    assert af["hp"] == 100     # 100（pct 10% 被跳过）
    assert af["str"] == 20     # 15 + 5（combat 属性 pct/flat 照常）


async def test_exp_next_and_level_cap() -> None:
    """exp_next 按 settings.exp_curve；满级（level ≥ cap）→ 0。"""
    ctx = await make_context(_event(), _deps(_player()))
    assert ctx["exp_next"] == 3500   # 100 × 35
    assert ctx["level_cap"] == 45
    ctx2 = await make_context(_event(), _deps(_player(level=45)))
    assert ctx2["exp_next"] == 0


async def test_bad_conditional_rules_no_crash() -> None:
    """非法条件规则 → 归一跳过/兜底，attr_final 仍为 dict 不抛异常。"""
    deps = _deps(_player(), settings=_settings(
        conditional_rules=[{"source": "str", "target": "con", "per_point": "not-a-number"}],
    ))
    ctx = await make_context(_event(), deps)
    assert isinstance(ctx["attr_final"], dict)
    assert ctx["conditional_rules"] == [
        {"source": "str", "target": "con", "per_point": "not-a-number"},
    ]


# ---------------------------------------------------------------------------
# 状态/世界/会话/环境
# ---------------------------------------------------------------------------
async def test_state_fields_from_persistent() -> None:
    """quest/checkin/event_counts/longline/shortcuts/npc/听过的键从 persistent_state 装载。"""
    ctx = await make_context(_event(), _deps(_player()))
    assert ctx["quest_active"] == {"q1": {"name": "q1"}}  # list 旧格式归一 dict
    assert ctx["quest_completed"] == ["q0"]
    assert ctx["quest_daily"]["completed"] == 1
    assert ctx["event_counts"] == {"battle:slime": 5}
    assert ctx["longline_counters"] == {"battle_wins": 12}
    assert ctx["checkin_state"]["count"] == 3
    assert ctx["shortcuts"] == {"/药水": "use potion"}
    assert ctx["shortcut_max"] == 20
    assert ctx["npc_delivered"] == {"intel:ref1": True}
    assert ctx["heard"] == {"intro1"}
    assert ctx["dialog_active"] is False
    assert ctx["personal_buys"]["shop1"]["potion"]["count"] == 2


async def test_effects_rendered() -> None:
    """active_effects → effects 渲染列表（name 反查注册表 / remaining=turns / source）。"""
    ctx = await make_context(_event(), _deps(_player()))
    assert ctx["active_effects"] == {"poison": {"effect": "poison", "turns": 2, "refreshed": 0}}
    assert ctx["effects"] == [
        {"name": "中毒", "remaining": 2, "duration": None, "source": "poison"},
    ]


async def test_dialog_session_restore() -> None:
    """persistent_state["dialog_session"] Mapping → DialogSession；非法形态 → None。"""
    p = _player()
    p.persistent_state["dialog_session"] = {"state": "menu", "npc_id": "npc1"}
    ctx = await make_context(_event(), _deps(p))
    assert ctx["dialog_session"] is not None
    p2 = _player()
    p2.persistent_state["dialog_session"] = "bogus"
    ctx2 = await make_context(_event(), _deps(p2))
    assert ctx2["dialog_session"] is None


async def test_world_with_npcs() -> None:
    """已交付 get_npcs 的 GameWorld：npcs/monster_pool 如实注入。"""
    deps = _deps(_player())
    deps.game_world = WorldWithNpcs()
    ctx = await make_context(_event(), deps)
    assert ctx["npcs"] == [{"id": "npc1", "name": "村长"}]
    assert ctx["monster_pool"] == ["slime"]
    assert ctx["map_def"] is None


async def test_deterministic_rng_now_env_injected() -> None:
    """rng/now/today/season/period/weather 由注入源提供（确定性）。"""
    deps = _deps(_player())
    rng = random.Random(42)
    deps.rng_factory = lambda qid: rng
    deps.dayroll = lambda: (datetime(2026, 8, 28, 12, 0, tzinfo=timezone(timedelta(hours=8))),
                            "2026-08-28")
    deps.time_query = lambda: {"season": "夏", "period": "昼"}
    deps.weather_query = lambda: "晴"
    ctx = await make_context(_event(), deps)
    assert ctx["rng"] is rng
    # ctx["now"] 归一为绝对秒级时间戳（对齐 checkin/dayroll 引擎契约 int），today 保持日期键
    assert ctx["now"] == int(datetime(2026, 8, 28, 12, 0,
                                      tzinfo=timezone(timedelta(hours=8))).timestamp())
    assert ctx["today"] == "2026-08-28"
    assert ctx["season"] == "夏" and ctx["period"] == "昼"
    assert ctx["weather"] == "晴"


# ---------------------------------------------------------------------------
# 事件透传 / 注册表
# ---------------------------------------------------------------------------
async def test_event_fields_passthrough() -> None:
    """event 群名/渠道/目标/QQ id/is_gm 透传 ctx。"""
    e = _event(qq_id="10002", group_name="测试群", per_channel="group", to="123", is_gm=True)
    ctx = await make_context(e, _deps(_player(qid="10002")))
    assert ctx["qq_id"] == "10002"
    assert ctx["group_id"] == "123456"
    assert ctx["group_name"] == "测试群"
    assert ctx["per_channel"] == "group"
    assert ctx["to"] == "123"
    assert ctx["is_gm"] is True
    assert ctx["channel"] == "qq"
    assert ctx["message"] == "/状态"


async def test_registry_tables_injected() -> None:
    """items/shops 注册表 + resolve_* + stats 模板注入。"""
    ctx = await make_context(_event(), _deps(_player()))
    assert ctx["items"]["potion"] is not None
    assert ctx["items"]["iron_sword"] is not None
    assert ctx["shops"]["shop1"] is not None
    assert callable(ctx["resolve_item"]) and callable(ctx["resolve_shop"])
    assert ctx["stats"]["hp"]["base"] == 100
    assert callable(ctx["npc_interactions"])
    assert isinstance(ctx["gm_commands"], set) and len(ctx["gm_commands"]) >= 1