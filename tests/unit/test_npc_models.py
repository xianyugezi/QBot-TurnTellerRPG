"""M4 批次2·路C1：npc.json NPC 数据模型（NPCDef 顶层 15 字段 + 6 子表）+ validate_npcs 专项校验测试。

依据：m4_shared_contract §3.1（NPC/对话 B1-B6）+ 细化_2b1_NPC数据与发牌员.md
（npc.json schema F01-F15 / 发牌员三策略 / 10 类动作 / 验收 TC-01~TC-20）
+ NPC系统设计定稿.md（类型 6 类 L344-349 / 条件引擎 §四 / 发牌员 §六 / 校验器 §4.5）。
测试目标：qbot_rpg.content.npc_models.validate_npcs（独立模块专项校验，供主 agent 收口接 check_pack）。

测试口径（对齐 test_maps_schema）：
  - validate_npcs(modules, report) 为纯函数；report 鸭子类型（本文件 _Report 收集器；
    另含真实 _Checker 收口兼容测试）。
  - 断言级别：errors=拦截（硬拦）/ warnings=黄提示（不拦截）。
  - 合法全量 schema（顶层 15 字段 + 子表，TC-01）零红拦零黄。
"""
from __future__ import annotations

import copy

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.npc_models import (
    ACTION_TYPES,
    DEALER_STRATEGY_DEFAULT,
    DEALER_STRATEGY_LEGACY,
    DEALER_STRATEGIES,
    DEFAULT_MAX_DIALOG_DEPTH,
    DIALOGUE_ACTION_SUBSET,
    NPC_TYPE_DEFAULT,
    NPC_TYPE_NAMES,
    NPC_TYPES,
    REPEAT_TYPES,
    DealerDef,
    DialogueDef,
    InteractionDef,
    NPCDef,
    QuestRefDef,
    parse_npcs,
    validate_npcs,
)
from qbot_rpg.content.validator import _Checker


# ---------------------------------------------------------------------------
# 夹具辅助：构造输入 → 跑校验器
# ---------------------------------------------------------------------------
class _Report:
    """validate_npcs 收集器（鸭子类型：error/warning 与 validator._Checker._err/_warn 签名一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []
        self.notes: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def note(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.notes.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _base_modules() -> dict:
    """标准模块上下文：引用靶齐全；maps **不含 npcs 数组**（双向校验不触发，
    避免单 NPC 用例误报 maps.npcs 悬空引用/未使用 NPC——需 npcs 接线时各用例显式构造）。"""
    return {
        "maps": [{"id": "rubble_field"}, {"id": "crag_den"}],
        "quest": [{"id": "q_ore_20"}, {"id": "q_sword"}],
        "shop": [{"id": "village_shop"}, {"id": "blacksmith_shop"}],
        "items": [{"id": "potion"}, {"id": "hi_potion"}],
        "effects": [{"id": "regen"}],
        "statuses": [{"id": "berserk"}],
        "marks": [{"id": "fire_mark"}],
        "tutorials": [{"id": "pv_break_tut"}],
        "enemies": [{"id": "rock_weasel", "lore": [{"unlock": 10, "desc": "弱水系"}]}],
    }


def _wired_modules() -> dict:
    """引用靶 + maps.npcs 接线（shopkeep_lin/traveling_dealer 均被引用 → 零未使用提示）。"""
    modules = _base_modules()
    modules["maps"] = [
        {"id": "rubble_field", "npcs": ["shopkeep_lin", "traveling_dealer"]},
        {"id": "crag_den", "npcs": ["traveling_dealer"]},
    ]
    return modules


def _legal_npc() -> list:
    """合法全量 NPC（TC-01：顶层 15 字段 + 子表全覆盖，零红拦零黄）。"""
    return [
        {
            "id": "shopkeep_lin", "name": "杂货商人·林", "icon": "🧺",
            "map": "rubble_field", "type": "merchant", "desc": "物美价廉，童叟无欺。",
            "visible": True,
            "dialogues": {
                "greeting": "物美价廉，童叟无欺！",
                "options": [
                    {"text": "买东西", "action": "shop", "shop_refs": ["village_shop"]},
                    {"text": "接点活儿", "action": "quest",
                     "quests": [{"quest_id": "q_ore_20",
                                 "condition": {"var": "level", "op": "ge", "value": 5}}]},
                    {"text": "打听消息", "action": "intel", "intel_refs": ["beetle_lore"]},
                    {"text": "聊两句", "action": "reply",
                     "text": ["今天天气不错", "欢迎再来"]},
                ],
            },
            "interactions": [
                {"action": "quest", "text": "接点活儿",
                 "quests": [{"quest_id": "q_ore_20",
                             "condition": {"var": "level", "op": "ge", "value": 5}}]},
                {"action": "shop", "text": "看看货物", "shop_refs": ["village_shop"],
                 "condition": {"var": "level", "op": "ge", "value": 5}},
                {"action": "heal", "text": "帮忙治疗", "cost": {"coins": 50},
                 "heal": {"hp": "100%", "mp": "100%"}},
                {"action": "give_item", "text": "领取补给",
                 "items": [{"id": "potion", "count": 3}], "repeat": "daily"},
                {"action": "buff", "text": "祝福一下", "effects": ["regen"], "turns": 3},
                {"action": "teleport", "text": "送我去 X", "map": "crag_den",
                 "cost": {"coins": 10}},
            ],
            "quests": [{"quest_id": "q_ore_20",
                        "condition": {"var": "level", "op": "ge", "value": 5}}],
            "shop_refs": ["village_shop"],
            "intel": [{"unlock": 10, "desc": "岩皮鼬弱水系"}],
            "intel_refs": ["beetle_lore"],
            "tutorials": [{"tutorial_id": "pv_break_tut",
                           "condition": {"var": "level", "op": "ge", "value": 3}}],
            "dealer": None,
        },
        {
            "id": "traveling_dealer", "name": "行商·骆驼", "icon": "🐫",
            "map": "rubble_field", "type": "dealer",
            "dialogues": {"greeting": "今天想听点什么？"},
            "dealer": {
                "strategy": "rotate",
                "pool": [
                    {"id": "tale_1", "condition": {"var": "level", "op": "ge", "value": 1},
                     "weight": 1,
                     "deliver": {"action": "reply", "text": ["远方有个传说…"]}, "once": True},
                    {"id": "tale_2",
                     "deliver": {"action": "give_item",
                                 "items": [{"id": "potion", "count": 1}], "repeat": "once"}},
                ],
            },
        },
    ]


def _check(npcs: object, **extra_modules: object):
    """跑 validate_npcs；默认带齐全引用靶模块。"""
    modules: dict = _base_modules()
    modules["npc"] = npcs
    modules.update(extra_modules)
    rep = _Report()
    validate_npcs(modules, rep)
    return rep


def _errs(rep, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e["detail"].get("rule") == rule]


def _warns(rep, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w["detail"].get("rule") == rule]


def _npc_by_id(npcs: list, nid: str) -> dict:
    for n in npcs:
        if n.get("id") == nid:
            return n
    raise AssertionError(f"npc 缺少 {nid}")


# ---------------------------------------------------------------------------
# 合法全量 schema 零红拦 + 访问器 + parse_npcs
# ---------------------------------------------------------------------------
def test_legal_npc_full_green() -> None:
    """TC-01：合法全量 schema（顶层 15 字段 + dialogues/interactions/quests/shop_refs/intel/
    intel_refs/tutorials/dealer 子表）→ 零红拦零黄。"""
    modules = _wired_modules()
    modules["npc"] = _legal_npc()
    rep = _Report()
    validate_npcs(modules, rep)
    assert not rep.errors, f"合法 npc 不应有红拦：{rep.errors}"
    assert not rep.warnings, f"合法 npc 应为零黄提示：{rep.warnings}"


def test_legal_npc_checker_integration() -> None:
    """收口兼容：validate_npcs 直传真实 validator._Checker（_err/_warn 鸭子路径）零红拦零黄。"""
    modules = _wired_modules()
    modules["npc"] = _legal_npc()
    checker = _Checker(modules, default_field_meta_table())
    validate_npcs(modules, checker)
    assert not checker.errors, f"直传 _Checker 应零红拦：{checker.errors}"
    assert not checker.warnings, f"直传 _Checker 应零黄：{checker.warnings}"


def test_parse_npcs() -> None:
    """parse_npcs 提取 npc 模块 → NPCDef 元组（非 list/非对象条目跳过）。"""
    npcs = _legal_npc()
    defs = parse_npcs({"npc": npcs})
    assert [d.id for d in defs] == ["shopkeep_lin", "traveling_dealer"]
    assert parse_npcs({"npc": "nope"}) == ()
    assert parse_npcs({}) == ()


def test_npcdef_accessors_top_level() -> None:
    """NPCDef 顶层 15 字段访问器（F01-F15）。"""
    entry = _npc_by_id(_legal_npc(), "shopkeep_lin")
    d = NPCDef.from_entry(entry)
    assert d.id == "shopkeep_lin"
    assert d.name == "杂货商人·林"
    assert d.icon == "🧺"  # type: ignore[attr-defined]
    assert d.map == "rubble_field"  # type: ignore[attr-defined]
    assert d.type == "merchant"  # type: ignore[attr-defined]
    assert d.desc == "物美价廉，童叟无欺。"  # type: ignore[attr-defined]
    assert d.visible is True  # type: ignore[attr-defined]
    assert isinstance(d.dialogues, DialogueDef)  # type: ignore[attr-defined]
    assert d.dialogues.greeting == "物美价廉，童叟无欺！"  # type: ignore[attr-defined]
    assert len(d.dialogues.options) == 4  # type: ignore[attr-defined]
    assert len(d.interactions) == 6  # type: ignore[attr-defined]
    assert isinstance(d.interactions[0], InteractionDef)  # type: ignore[attr-defined]
    assert d.interactions[0].action == "quest"  # type: ignore[attr-defined]
    assert d.interactions[0].text == "接点活儿"  # type: ignore[attr-defined]
    assert d.quests[0].quest_id == "q_ore_20"  # type: ignore[attr-defined]
    assert isinstance(d.quests[0], QuestRefDef)  # type: ignore[attr-defined]
    assert d.shop_refs == ("village_shop",)  # type: ignore[attr-defined]
    assert d.intel[0].get("unlock") == 10  # type: ignore[attr-defined]
    assert d.intel_refs == ("beetle_lore",)  # type: ignore[attr-defined]
    assert d.tutorials[0]["tutorial_id"] == "pv_break_tut"  # type: ignore[attr-defined]
    assert d.dealer is None  # type: ignore[attr-defined]


def test_npcdef_accessors_dealer() -> None:
    """NPCDef dealer 子表访问器（strategy + pool 候选牌，2b1 §二）。"""
    entry = _npc_by_id(_legal_npc(), "traveling_dealer")
    d = NPCDef.from_entry(entry)
    assert d.type == "dealer"  # type: ignore[attr-defined]
    assert isinstance(d.dealer, DealerDef)  # type: ignore[attr-defined]
    assert d.dealer.strategy == "rotate"  # type: ignore[attr-defined]
    cards = d.dealer.pool  # type: ignore[attr-defined]
    assert [c.id for c in cards] == ["tale_1", "tale_2"]
    assert cards[0].weight == 1
    assert cards[0].once is True
    assert cards[0].deliver.get("action") == "reply"
    assert cards[1].condition is None


def test_npcdef_defaults() -> None:
    """缺省兜底：type 缺省 merchant、visible 缺省 true、dialogues 缺省空 greeting。"""
    d = NPCDef.from_entry({"id": "x", "name": "路人甲", "icon": "🙂"})
    assert d.type is None # type: ignore[attr-defined]  # raw 未写 type（默认 merchant 为校验侧兜底，访问器不伪造）
    assert d.visible is True  # type: ignore[attr-defined]
    assert d.dialogues.greeting is None  # type: ignore[attr-defined]
    assert d.interactions == ()  # type: ignore[attr-defined]
    assert d.dealer is None  # type: ignore[attr-defined]
    assert d.shop_refs == ()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# id / name / icon / type（TC-02）
# ---------------------------------------------------------------------------
def test_id_required_and_duplicate() -> None:
    """TC-02 ①：id 缺失 → 红拦；两个 NPC 同 id → 红拦（唯一性）。"""
    npcs = _legal_npc()
    npcs[0]["id"] = ""
    rep = _check(npcs)
    assert _errs(rep, "npc_id_required")
    npcs = _legal_npc()
    npcs[1]["id"] = "shopkeep_lin"  # 与 npcs[0] 同 id
    rep = _check(npcs)
    assert len(_errs(rep, "npc_id_duplicate")) == 1


def test_name_space_forbidden() -> None:
    """TC-02 ②③：name 含空格 → 红拦；· 允许（合法 fixture 已覆盖 ③ 零红拦）。"""
    npcs = [_legal_npc()[0]]
    npcs[0]["name"] = "铁匠 老周"
    rep = _check(npcs)
    assert len(_errs(rep, "npc_name_space_forbidden")) == 1
    npcs[0]["name"] = "铁匠·老周"
    rep = _check(npcs)
    assert not _errs(rep, "npc_name_space_forbidden")
    npcs[0]["name"] = "铁匠Ⅱ"
    rep = _check(npcs)
    assert not rep.errors


def test_name_and_icon_required() -> None:
    """name/icon 必填（定稿 L386 F01-F03）。"""
    npcs = [_legal_npc()[0]]
    del npcs[0]["name"]
    del npcs[0]["icon"]
    rep = _check(npcs)
    assert _errs(rep, "npc_name_required")
    assert _errs(rep, "npc_icon_required")


def test_type_enum() -> None:
    """type 枚举 6 类（定稿 L344-349）：非法 → 红拦；缺省 merchant 不拦。"""
    npcs = [_legal_npc()[0]]
    npcs[0]["type"] = "healer"
    rep = _check(npcs)
    assert len(_errs(rep, "npc_type_invalid")) == 1
    npcs[0].pop("type")
    rep = _check(npcs)
    assert not _errs(rep, "npc_type_invalid")
    assert NPC_TYPE_DEFAULT == "merchant"
    assert set(NPC_TYPES) == {"merchant", "quest_giver", "intel_giver", "tutor",
                              "narrator", "dealer"}
    assert NPC_TYPE_NAMES["dealer"] == "发牌员"


# ---------------------------------------------------------------------------
# 引用校验（TC-20 ①：NPC 引用不存在 → 红拦）
# ---------------------------------------------------------------------------
def test_map_ref_dangling() -> None:
    """map 挂点引用不存在 → 红拦；maps 模块缺失 → 跳过引用检查（默认放行）。"""
    npcs = [_legal_npc()[0]]
    npcs[0]["map"] = "no_such_map"
    rep = _check(npcs)
    assert len(_errs(rep, "npc_map_ref_missing")) == 1
    rep = _check(npcs, maps=None)  # maps 未声明 → 跳过引用检查
    assert not _errs(rep, "npc_map_ref_missing")


def test_action_specific_refs_missing() -> None:
    """动作专属引用不存在 → 各自红拦（quests/shop_refs/items/effects/teleport map/tutorials）。"""
    npc = {
        "id": "bad_refs", "name": "坏引用", "icon": "❌",
        "interactions": [
            {"action": "quest", "text": "t", "quests": [{"quest_id": "q_missing"}]},
            {"action": "shop", "text": "t", "shop_refs": ["shop_missing"]},
            {"action": "give_item", "text": "t", "items": [{"id": "item_missing", "count": 1}]},
            {"action": "buff", "text": "t", "effects": ["fx_missing"]},
            {"action": "teleport", "text": "t", "map": "map_missing"},
            {"action": "tutorial", "text": "t", "tutorials": ["tut_missing"]},
        ],
    }
    rep = _check([npc])
    assert len(_errs(rep, "npc_quest_ref_missing")) == 1
    assert len(_errs(rep, "npc_shop_ref_missing")) == 1
    assert len(_errs(rep, "npc_give_item_ref_missing")) == 1
    assert len(_errs(rep, "npc_buff_effect_ref_missing")) == 1
    assert len(_errs(rep, "npc_teleport_map_missing")) == 1
    assert len(_errs(rep, "npc_tutorial_ref_missing")) == 1
    # 引用靶模块缺失 → 默认放行
    rep = _check([npc], quest=None, shop=None, items=None, effects=None, statuses=None,
                 marks=None, tutorials=None)
    assert not _errs(rep, "npc_quest_ref_missing")
    assert not _errs(rep, "npc_shop_ref_missing")


def test_maps_npc_ref_roundtrip() -> None:
    """双向校验：maps.npcs 引用不存在的 NPC → 红拦；NPC 未被任何地图引用 → 黄提示（TC-20 ③）。"""
    npcs = [_legal_npc()[0]]
    modules = _base_modules()
    modules["npc"] = npcs
    modules["maps"] = [{"id": "rubble_field", "npcs": ["ghost_npc", "shopkeep_lin"]}]
    rep = _Report()
    validate_npcs(modules, rep)
    assert len(_errs(rep, "map_npc_ref_missing")) == 1  # ghost_npc 悬空
    # shopkeep_lin 被引用 → 无未使用提示
    assert not _warns(rep, "npc_unused")
    # 未接线内容包（maps 无 npcs 数组）→ 不触发未使用噪音
    modules["maps"] = [{"id": "rubble_field"}]
    rep = _Report()
    validate_npcs(modules, rep)
    assert not _warns(rep, "npc_unused")
    assert not _errs(rep, "map_npc_ref_missing")


def test_unused_npc_warning() -> None:
    """TC-20 ③：两个 NPC 只被引用其一 → 另一个黄提示「未使用 NPC」。"""
    npcs = _legal_npc()
    modules = _base_modules()
    modules["npc"] = npcs
    modules["maps"] = [{"id": "rubble_field", "npcs": ["shopkeep_lin"]}]
    rep = _Report()
    validate_npcs(modules, rep)
    unused = [w for w in _warns(rep, "npc_unused")
              if w["detail"].get("node_id") == "traveling_dealer"]
    assert len(unused) == 1


# ---------------------------------------------------------------------------
# 交互动作（10 类 action 枚举 + 动作专属值域）
# ---------------------------------------------------------------------------
def test_interaction_action_enum() -> None:
    """interactions[].action ∈ 10 类；缺失/非法 → 红拦。"""
    npcs = [_legal_npc()[0]]
    npcs[0]["interactions"][0].pop("action")
    npcs[0]["interactions"][1]["action"] = "fly"
    rep = _check(npcs)
    assert _errs(rep, "npc_action_required")
    assert _errs(rep, "npc_action_invalid")
    assert set(ACTION_TYPES) == {"quest", "shop", "heal", "give_item", "buff", "repair",
                                 "teleport", "intel", "tutorial", "reply"}


def test_interaction_text_required() -> None:
    """interactions[].text 菜单文案必填（2b1 I02）。"""
    npcs = [_legal_npc()[0]]
    npcs[0]["interactions"][0].pop("text")
    rep = _check(npcs)
    assert len(_errs(rep, "npc_interaction_text_required")) == 1


def test_action_specific_values() -> None:
    """动作专属值域：heal 百分比串非法 / give_item count 与 repeat / buff turns / teleport cost 负数。"""
    npc = {
        "id": "bad_vals", "name": "坏数值", "icon": "❌",
        "interactions": [
            {"action": "heal", "text": "t", "heal": {"hp": "100x"}},
            {"action": "give_item", "text": "t", "items": [{"id": "potion", "count": 0}],
             "repeat": "weekly"},
            {"action": "buff", "text": "t", "effects": ["regen"], "turns": -1},
            {"action": "teleport", "text": "t", "map": "crag_den", "cost": {"coins": -5}},
        ],
    }
    rep = _check([npc])
    assert _errs(rep, "npc_heal_value_invalid")
    assert _errs(rep, "npc_give_item_count_invalid")
    assert _errs(rep, "npc_give_item_repeat_invalid")
    assert _errs(rep, "npc_buff_turns_invalid")
    assert _errs(rep, "npc_cost_coins_invalid")
    assert REPEAT_TYPES == ("once", "daily")


def test_repair_action_degraded_not_blocked() -> None:
    """repair（依赖未实现的装备耐久）降级：配置不拦截（2b1 S4），仅结构。"""
    npc = {
        "id": "smith", "name": "铁匠·老周", "icon": "🔨",
        "interactions": [{"action": "repair", "text": "修修装备", "cost": {"coins": 20}}],
    }
    rep = _check([npc])
    assert not rep.errors
    assert not rep.warnings


# ---------------------------------------------------------------------------
# 条件引擎（TC-08：结构红拦 + 旧格式/事件未登记黄提示）
# ---------------------------------------------------------------------------
def test_condition_structure_errors() -> None:
    """条件结构硬拦：var 未注册 / op 非法 / 空条件。"""
    npc = {
        "id": "cond", "name": "条件测试", "icon": "🔮",
        "interactions": [
            {"action": "shop", "text": "t", "shop_refs": ["village_shop"],
             "condition": {"var": "foobar", "op": "eq", "value": 1}},
            {"action": "shop", "text": "t", "shop_refs": ["village_shop"],
             "condition": {"var": "level", "op": "xx", "value": 1}},
            {"action": "shop", "text": "t", "shop_refs": ["village_shop"], "condition": {}},
        ],
    }
    rep = _check([npc])
    assert len(_errs(rep, "var_not_registered")) == 1
    assert len(_errs(rep, "op_invalid")) == 1
    assert len(_errs(rep, "condition_empty")) == 1


def test_condition_soft_warnings() -> None:
    """条件软提示：旧格式 {type,...} / 事件未登记 → 黄提示不拦（NPC 4.5 只建议不限制）。"""
    npc = {
        "id": "cond2", "name": "条件软", "icon": "🔮",
        "interactions": [
            {"action": "shop", "text": "t", "shop_refs": ["village_shop"],
             "condition": {"type": "job", "var": "job", "op": "eq", "value": "剑士"}},
            {"action": "shop", "text": "t", "shop_refs": ["village_shop"],
             "condition": {"var": "[事件:落石]", "op": "ge", "value": 1}},
        ],
    }
    rep = _check([npc])
    assert not rep.errors  # 软提示不拦
    assert len(_warns(rep, "legacy_format")) == 1
    assert len(_warns(rep, "event_not_registered")) == 1


def test_condition_combos_and_param() -> None:
    """组合 any/all/not 嵌套 + param 四要素合法 → 零记录。"""
    npc = {
        "id": "cond3", "name": "条件组合", "icon": "🔮",
        "interactions": [
            {"action": "shop", "text": "t", "shop_refs": ["village_shop"],
             "condition": {"all": [
                 {"var": "level", "op": "ge", "value": 10},
                 {"var": "item_count", "op": "ge", "value": 50, "param": "金币"},
             ]}},
            {"action": "shop", "text": "t", "shop_refs": ["village_shop"],
             "condition": {"any": [
                 {"var": "job", "op": "eq", "value": "剑士"},
                 {"not": {"var": "has_item", "op": "is", "value": "铁矿"}},
             ]}},
        ],
    }
    rep = _check([npc])
    assert not rep.errors
    assert not rep.warnings


# ---------------------------------------------------------------------------
# 对话树（深度软拦 + 5 类 action 建议 + 结构）
# ---------------------------------------------------------------------------
def _dialog_npc(options: list) -> list:
    return [{"id": "talker", "name": "话痨·甲", "icon": "💬", "dialogues": {"greeting": "嗨", "options": options}}]


def test_dialog_depth_soft_block() -> None:
    """TC-03：树深 3 层（默认 max_dialog_depth=2）→ 黄提示不拦；配置 3 或 0 不限 → 零提示。"""
    deep = _dialog_npc([
        {"text": "a", "action": "reply", "text": ["x"], "options": [
            {"text": "b", "action": "reply", "text": ["y"], "options": [
                {"text": "c", "action": "reply", "text": ["z"]}]}]}])
    rep = _check(deep)
    assert not rep.errors  # 软拦不拦截
    assert len(_warns(rep, "npc_dialog_too_deep")) == 1
    # settings.max_dialog_depth=3 → 不再超深
    rep = _check(deep, settings={"max_dialog_depth": 3})
    assert not _warns(rep, "npc_dialog_too_deep")
    # max_dialog_depth=0 → 不限
    rep = _check(deep, settings={"max_dialog_depth": 0})
    assert not _warns(rep, "npc_dialog_too_deep")
    # settings 缺省 → 默认 2
    assert DEFAULT_MAX_DIALOG_DEPTH == 2


def test_dialog_depth_two_levels_ok() -> None:
    """树深 2 层（greeting→选项→子选项）→ 零提示（≤ 默认 max_dialog_depth=2）。"""
    two = _dialog_npc([
        {"text": "a", "action": "reply", "text": ["x"], "options": [
            {"text": "b", "action": "reply", "text": ["y"]}]}])
    rep = _check(two)
    assert not rep.errors
    assert not _warns(rep, "npc_dialog_too_deep")


def test_dialog_action_subset_warning() -> None:
    """S3 裁决：dialogues.options[].action 非 5 类子集 → 黄提示（结构不拦截）。"""
    npc = _dialog_npc([
        {"text": "a", "action": "repair", "cost": {"coins": 10}},  # repair ∉ 5 类子集（无必填子字段）
        {"text": "b", "action": "shop", "shop_refs": ["village_shop"]},  # 子集内
    ])
    rep = _check(npc)
    assert not rep.errors
    assert len(_warns(rep, "npc_dialog_action_not_subset")) == 1
    assert set(DIALOGUE_ACTION_SUBSET) == {"shop", "quest", "tutorial", "intel", "reply"}


def test_dialog_option_text_required() -> None:
    """dialogues.options[].text 必填（2b1 D03）；reply 无任何 text → npc_reply_text_invalid。"""
    npc = _dialog_npc([{"action": "shop", "shop_refs": ["village_shop"]}])  # 缺选项文案
    rep = _check(npc)
    assert len(_errs(rep, "npc_dialog_option_text_required")) == 1
    npc = _dialog_npc([{"action": "reply"}])  # reply 缺回复内容/标签
    rep = _check(npc)
    assert len(_errs(rep, "npc_reply_text_invalid")) == 1


# ---------------------------------------------------------------------------
# 发牌员（三策略 / 兼容迁移 / 牌池 / type=dealer 必配）
# ---------------------------------------------------------------------------
def test_dealer_strategy_enum() -> None:
    """dealer.strategy ∈ rotate/random/condition；非法 → 红拦。"""
    npc = {"id": "d", "name": "发牌·乙", "icon": "🎴", "type": "dealer",
           "dealer": {"strategy": "banana", "pool": []}}
    rep = _check([npc])
    assert _errs(rep, "npc_dealer_strategy_invalid")
    assert DEALER_STRATEGIES == ("rotate", "random", "condition")
    assert DEALER_STRATEGY_DEFAULT == "condition"


def test_dealer_strategy_legacy_warning() -> None:
    """用户裁决④：旧 first_match/weighted/random → 读取兼容 + 黄提示迁移。"""
    npc = {"id": "d", "name": "发牌·乙", "icon": "🎴", "type": "dealer",
           "dealer": {"strategy": "first_match", "pool": []}}
    rep = _check([npc])
    assert not rep.errors
    assert len(_warns(rep, "npc_dealer_strategy_legacy")) == 1
    assert DEALER_STRATEGY_LEGACY["first_match"] == "condition"
    assert DEALER_STRATEGY_LEGACY["weighted"] == "random"
    assert DEALER_STRATEGY_LEGACY["random"] == "random"


def test_dealer_type_requires_dealer() -> None:
    """2b1 F15：type=dealer 时 dealer 必配；type≠dealer 可无 dealer。"""
    npc = {"id": "d", "name": "发牌·乙", "icon": "🎴", "type": "dealer"}
    rep = _check([npc])
    assert len(_errs(rep, "npc_dealer_required")) == 1
    npc.pop("type")  # 缺省 merchant → 无 dealer 合法
    rep = _check([npc])
    assert not _errs(rep, "npc_dealer_required")


def test_dealer_pool_structure() -> None:
    """牌池条目结构（P01-P05）：id 必填/池内唯一 / deliver 必填 + action / weight 负数 / once 非 bool。"""
    npc = {"id": "d", "name": "发牌·乙", "icon": "🎴", "type": "dealer",
           "dealer": {"strategy": "random", "pool": [
               {"id": "c1", "weight": -1, "once": "yes"},  # 无 deliver + weight 负 + once 非 bool
               {"id": "c1", "deliver": {"action": "nope"}},  # 重复 id + action 非法
               {"deliver": {"action": "reply", "text": ["x"]}},  # 无 id
           ]}}
    rep = _check([npc])
    assert len(_errs(rep, "npc_dealer_card_id_required")) == 1
    assert len(_errs(rep, "npc_dealer_card_id_duplicate")) == 1
    assert len(_errs(rep, "npc_dealer_card_weight_invalid")) == 1
    assert len(_errs(rep, "npc_dealer_card_once_invalid")) == 1
    assert len(_errs(rep, "npc_dealer_card_deliver_required")) == 1
    assert len(_errs(rep, "npc_action_invalid")) == 1


def test_dealer_empty_pool_soft_warn() -> None:
    """type=dealer 牌池空 → 黄提示（孤寂卡节奏，TC-12 侧）不拦。"""
    npc = {"id": "d", "name": "发牌·乙", "icon": "🎴", "type": "dealer",
           "dealer": {"strategy": "condition"}}
    rep = _check([npc])
    assert not rep.errors
    assert len(_warns(rep, "npc_dealer_pool_empty")) == 1


# ---------------------------------------------------------------------------
# 其余子表结构
# ---------------------------------------------------------------------------
def test_quests_top_level_condition() -> None:
    """顶层 quests[] 结构 + 条件校验（与 interactions quests 同契约）。"""
    npc = {"id": "q", "name": "任务·丙", "icon": "📜",
           "quests": [
               {"condition": {"var": "level", "op": "ge", "value": 5}},  # 缺 quest_id
               {"quest_id": "q_missing"},  # 引用悬空
               {"quest_id": "q_sword", "condition": {"var": "nope", "op": "eq", "value": 1}},
           ]}
    rep = _check([npc])
    assert len(_errs(rep, "npc_quest_ref_quest_id_required")) == 1
    assert len(_errs(rep, "npc_quest_ref_missing")) == 1
    assert len(_errs(rep, "var_not_registered")) == 1


def test_intel_refs_structural() -> None:
    """intel_refs 仅结构校验（【工程补白】3：enemies lore 无 id）；非字符串 → 红拦。"""
    npc = {"id": "i", "name": "情报·丁", "icon": "📖",
           "intel": "not-a-list", "intel_refs": [123]}
    rep = _check([npc])
    assert _errs(rep, "npc_intel_invalid")
    assert _errs(rep, "npc_intel_ref_invalid")


def test_tutorials_dual_form() -> None:
    """tutorials[] 双形态（str 引用 / {tutorial_id, condition}）；tutorial_id 悬空 → 红拦。"""
    npc = {"id": "t", "name": "教学·戊", "icon": "🎓",
           "tutorials": ["pv_break_tut", {"tutorial_id": "tut_missing"}]}
    rep = _check([npc])
    missing = _errs(rep, "npc_tutorial_ref_missing")
    assert len(missing) == 1  # 第一条 str 引用存在；第二条 {tutorial_id} 悬空
    assert missing[0]["detail"]["ref"] == "tut_missing"


def test_dialogues_not_object() -> None:
    """dialogues 非对象 / visible 非 bool / desc 非 str → 红拦。"""
    npc = {"id": "x", "name": "路人·己", "icon": "🙂", "dialogues": "hi",
           "visible": "yes", "desc": 5}
    rep = _check([npc])
    assert _errs(rep, "npc_dialogues_not_object")
    assert _errs(rep, "npc_visible_invalid")
    assert _errs(rep, "npc_desc_invalid")
