"""M4 批次4·路E1：quest.json 任务数据模型（QuestDef 17 顶层字段 + board/timed/npc 子表
+ 三原语条件 + 防刷）+ validate_quests 专项校验测试。

依据：m4_shared_contract §3.3（任务 D1-D5）+ 细化_2b4_任务引擎契约.md（quest.json 字段级
schema §1.2 / board 5 key §1.3 / npc 3 key §1.4 / 三原语 §二 / reward §三 / 防刷 §四 /
双板 §五 / 验收 TC-01~TC-31）
+ 任务系统设计定稿.md（L138 main 命名 / L183 接取≤5 / L184 每日≤10 / L276 校验器）
+ 2026-08-27 M4 设计审查裁决（审查_M4设计_批次4_jspace.md）：P1-1/P1-2/P2-1/P2-2/P3-1。

测试目标：qbot_rpg.content.quest_models.validate_quests（独立模块专项校验，供主 agent 收口接 check_pack）。

测试口径（对齐 test_npc_models / test_shop_models）：
  - validate_quests(modules, report) 为纯函数；report 鸭子类型（本文件 _Report 收集器；
    另含真实 _Checker 收口兼容测试）。
  - 断言级别：errors=拦截（硬拦）/ warnings=黄提示（不拦截）。
  - 合法全量 schema（17 顶层字段 + 子表，TC-01）零红拦零黄。
"""
from __future__ import annotations

import copy

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.quest_models import (
    BOARD_ACCEPT_OVER_WARN,
    BOARD_LIMIT_OVER_WARN,
    BOARD_REFRESH_MODES,
    BOARD_SLOTS,
    COND_EVENT_PRESETS,
    COND_OPERATORS,
    QUEST_ACCEPT_LIMIT_DEFAULT,
    QUEST_CONDITIONS_ARRAY_ALL,
    QUEST_DAILY_LIMIT_DEFAULT,
    QUEST_MAIN_FIELD,
    QUEST_MODULE,
    QUEST_TYPE_DEFAULT,
    BoardDef,
    NpcGrantDef,
    QuestDef,
    TimedDef,
    parse_quests,
    validate_quests,
)
from qbot_rpg.content.validator import _Checker


# ---------------------------------------------------------------------------
# 夹具辅助：构造输入 → 跑校验器
# ---------------------------------------------------------------------------
class _Report:
    """validate_quests 收集器（鸭子类型：error/warning 与 validator._Checker._err/_warn 签名一致）。"""

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
    """标准模块上下文：引用靶齐全（items/maps/dungeon/npc/settings 货币键空间）。"""
    return {
        "items": [{"id": "铁矿"}, {"id": "强化石"}, {"id": "potion"}],
        "maps": [{"id": "rubble_field"}],
        "dungeon": [{"id": "molten_dungeon"}],
        "npc": [{"id": "blacksmith"}, {"id": "traveling_dealer"}],
        "settings": {"currencies": [{"id": "coins"}, {"id": "gem"}, {"id": "diamond"}]},
    }


def _legal_quests() -> list:
    """合法全量任务（TC-01：17 顶层字段 + board/timed/npc 子表全覆盖，零红拦零黄）。"""
    return [
        {
            "id": "q_ore_20",
            "name": "收集铁矿",
            "desc": "村长需要 20 个铁矿",
            "type": "collect",
            "conditions": [{"var": "gain_count", "op": "ge", "value": 20, "param": "铁矿"}],
            "consume": False,
            "reward": [{"exp": 50}, {"coins": 80}, {"item": "铁矿", "count": 3}],
            "board": {"slot": "daily", "refresh": "daily", "limit": 3},
            "timed": None,
            "unlock_chain": None,
            "zone": None,
            "filter": None,
            "bonus": None,
            "npc": None,
            "daily": False,
            "repeatable": False,
        },
        {
            "id": "q_main_weapon",
            "name": "特制武器",
            "desc": "锻造试炼",
            "type": "deliver",
            "main": True,
            "conditions": [{"var": "main_progress", "op": "ge", "value": 3}],
            "consume": True,
            "reward": "exp=60,coins=100",
            "board": {"slot": "weekly", "refresh": "weekly", "limit": 1,
                      "accept_limit": 5, "daily_limit": 10},
            "timed": {"deadline": "2026-09-01 05:00", "penalty": None},
            "unlock_chain": "q_ore_20",
            "zone": "rubble_field",
            "filter": {"quality": "精良"},
            "bonus": {"condition": {"var": "item_count", "op": "ge", "value": 5, "param": "强化石"},
                      "mult": 1.5},
            "npc": {"id": "blacksmith",
                    "conditions": [{"var": "level", "op": "ge", "value": 10}], "priority": 1},
            "daily": False,
            "repeatable": {"decay": 0.5, "cap": 1},
        },
    ]


def _check(quests: object, **extra_modules: object):
    """跑 validate_quests；默认带齐全引用靶模块。"""
    modules: dict = _base_modules()
    modules[QUEST_MODULE] = quests
    modules.update(extra_modules)
    rep = _Report()
    validate_quests(modules, rep)
    return rep


def _errs(rep, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e["detail"].get("rule") == rule]


def _warns(rep, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w["detail"].get("rule") == rule]


def _quest_by_id(quests: list, qid: str) -> dict:
    for q in quests:
        if q.get("id") == qid:
            return q
    raise AssertionError(f"quest 缺少 {qid}")


# ---------------------------------------------------------------------------
# 合法全量 schema 零红拦 + 访问器 + parse_quests
# ---------------------------------------------------------------------------
def test_legal_quest_full_green() -> None:
    """TC-01：合法全量 schema（17 顶层字段 + board/timed/npc 子表）→ 零红拦零黄。"""
    rep = _check(_legal_quests())
    assert not rep.errors, f"合法 quest 不应有红拦：{rep.errors}"
    assert not rep.warnings, f"合法 quest 应为零黄提示：{rep.warnings}"


def test_legal_quest_checker_integration() -> None:
    """收口兼容：validate_quests 直传真实 validator._Checker（_err/_warn 鸭子路径）零红拦零黄。"""
    modules = _base_modules()
    modules[QUEST_MODULE] = _legal_quests()
    checker = _Checker(modules, default_field_meta_table())
    validate_quests(modules, checker)
    assert not checker.errors, f"直传 _Checker 应零红拦：{checker.errors}"
    assert not checker.warnings, f"直传 _Checker 应零黄：{checker.warnings}"


def test_parse_quests() -> None:
    """parse_quests 提取 quest 模块 → QuestDef 元组（非 list/非对象条目跳过）。"""
    quests = _legal_quests()
    defs = parse_quests({QUEST_MODULE: quests})
    assert [d.id for d in defs] == ["q_ore_20", "q_main_weapon"]
    assert parse_quests({QUEST_MODULE: "nope"}) == ()
    assert parse_quests({}) == ()


def test_questdef_accessors_top_level() -> None:
    """QuestDef 17 顶层字段访问器（F03-F17；id/name 由 BaseDef）。"""
    entry = _quest_by_id(_legal_quests(), "q_main_weapon")
    d = QuestDef.from_entry(entry)
    assert d.id == "q_main_weapon"
    assert d.name == "特制武器"
    assert d.desc == "锻造试炼"
    assert d.type == "deliver"
    assert d.effective_type == "deliver"
    assert d.main is True
    assert d.is_main is True
    assert len(d.conditions) == 1
    assert d.conditions[0]["var"] == "main_progress"
    assert d.consume is True
    assert d.reward == "exp=60,coins=100"
    assert d.rewards is None
    assert isinstance(d.board, BoardDef)
    assert d.board.slot == "weekly"
    assert isinstance(d.timed, TimedDef)
    assert d.timed.deadline == "2026-09-01 05:00"
    assert d.unlock_chain == "q_ore_20"
    assert d.zone == "rubble_field"
    assert d.filter == {"quality": "精良"}
    assert d.bonus["mult"] == 1.5
    assert isinstance(d.npc, NpcGrantDef)
    assert d.npc.id == "blacksmith"
    assert d.npc.priority == 1
    assert d.daily is False
    assert d.repeatable == {"decay": 0.5, "cap": 1}
    # 派生
    assert d.is_repeatable() is True
    assert d.repeatable_decay() == 0.5
    assert d.repeatable_cap() == 1


def test_questdef_board_accessors() -> None:
    """BoardDef 5 key 访问器 + 生效侧（默认值兜底 D-07）。"""
    entry = _quest_by_id(_legal_quests(), "q_ore_20")
    d = QuestDef.from_entry(entry)
    b = d.board
    assert b.slot == "daily"
    assert b.refresh == "daily"
    assert b.limit == 3
    assert b.accept_limit is None  # 未配 → 生效侧取默认 5
    assert b.daily_limit is None  # 未配 → 生效侧取默认 10
    assert b.effective_accept_limit() == QUEST_ACCEPT_LIMIT_DEFAULT == 5
    assert b.effective_daily_limit() == QUEST_DAILY_LIMIT_DEFAULT == 10
    assert d.board_accept_limit() == 5
    assert d.board_daily_limit() == 10


def test_questdef_npc_conditions() -> None:
    """NpcGrantDef.conditions 访问器（统一条件引擎条目）。"""
    entry = _quest_by_id(_legal_quests(), "q_main_weapon")
    npc = QuestDef.from_entry(entry).npc
    assert len(npc.conditions) == 1
    assert npc.conditions[0]["var"] == "level"


def test_questdef_defaults() -> None:
    """缺省兜底（D-07 / TC-01）：最小配置 {id,name,conditions} 绝不报错，访问器缺省值合理。"""
    d = QuestDef.from_entry({"id": "q_min", "name": "最小任务", "conditions": []})
    assert d.type is None  # raw 未写 type（默认 collect 为 effective_type 兜底）
    assert d.effective_type == QUEST_TYPE_DEFAULT == "collect"
    assert d.main is False
    assert d.consume is False
    assert d.reward is None
    assert d.rewards is None
    assert d.conditions == ()
    assert isinstance(d.board, BoardDef)
    assert d.board.slot is None  # 未配 board → 生效槽位兜底 daily
    assert d.effective_board_slot() == "daily"
    assert d.timed.deadline is None
    assert d.unlock_chain is None
    assert d.zone is None
    assert d.filter is None
    assert d.bonus == {}
    assert d.npc.id is None
    assert d.daily is False
    assert d.repeatable is None
    assert d.is_repeatable() is False
    # 最小配置跑校验器：零红拦（默认兜底绝不报错）
    rep = _check([{"id": "q_min", "name": "最小任务", "conditions": []}])
    assert not rep.errors, f"最小配置不应红拦：{rep.errors}"
    assert not rep.warnings


# ---------------------------------------------------------------------------
# main 主线标记（P3-1：定稿 L138 命名 main，非细化收敛）
# ---------------------------------------------------------------------------
def test_main_field_naming() -> None:
    """main 沿用定稿 L138 命名（P3-1 修正：不是细化收敛而是定稿原文）。"""
    assert QUEST_MAIN_FIELD == "main"
    d = QuestDef.from_entry({"id": "q_m", "name": "主线", "main": True, "conditions": []})
    assert d.main is True
    assert d.is_main is True
    # 非 bool → 红拦
    rep = _check([{"id": "q_m", "name": "主线", "main": "yes", "conditions": []}])
    assert len(_errs(rep, "quest_main_invalid")) == 1


# ---------------------------------------------------------------------------
# daily 顶层字段 P2-2 收敛（board.slot 简写）
# ---------------------------------------------------------------------------
def test_daily_p22_shorthand_semantics() -> None:
    """P2-2 收敛：daily = board.slot 简写——daily:true ≡ 每日板；daily:false = 无简写。"""
    base = {"id": "q_d", "name": "每日", "conditions": []}
    d_false = QuestDef.from_entry({**base, "daily": False})
    assert d_false.daily is False
    assert d_false.effective_board_slot() == "daily"  # daily:false 与默认板=每日板不冲突
    assert d_false.is_daily_board is True

    d_true = QuestDef.from_entry({**base, "daily": True})
    assert d_true.daily is True
    assert d_true.effective_board_slot() == "daily"
    assert d_true.is_daily_board is True

    d_weekly = QuestDef.from_entry({**base, "board": {"slot": "weekly"}})
    assert d_weekly.daily is False
    assert d_weekly.effective_board_slot() == "weekly"  # 非每日板 = board.slot 显式
    assert d_weekly.is_daily_board is False

    d_weekly_daily_true = QuestDef.from_entry({**base, "daily": True, "board": {"slot": "weekly"}})
    assert d_weekly_daily_true.effective_board_slot() == "weekly"  # board.slot 显式优先


def test_daily_p22_conflict_warning() -> None:
    """P2-2 互斥黄提示：daily:true 与 board.slot 显式≠daily 同给（2b4 §1.2 row16）。"""
    rep = _check([{"id": "q_c", "name": "冲突", "conditions": [],
                   "daily": True, "board": {"slot": "weekly"}}])
    assert not rep.errors
    assert len(_warns(rep, "quest_daily_board_conflict")) == 1
    # daily:false + board.slot weekly → 不冲突（daily:false = 无简写）
    rep = _check([{"id": "q_c", "name": "冲突", "conditions": [],
                   "daily": False, "board": {"slot": "weekly"}}])
    assert not rep.errors
    assert not _warns(rep, "quest_daily_board_conflict")
    # daily:true + board.slot daily → 冗余但不冲突
    rep = _check([{"id": "q_c", "name": "冲突", "conditions": [],
                   "daily": True, "board": {"slot": "daily"}}])
    assert not _warns(rep, "quest_daily_board_conflict")


def test_daily_type_invalid() -> None:
    """daily 非 bool → 红拦。"""
    rep = _check([{"id": "q_d", "name": "每日", "conditions": [], "daily": "yes"}])
    assert len(_errs(rep, "quest_daily_invalid")) == 1


# ---------------------------------------------------------------------------
# 三原语条件（值型/累计型/事件型，2b4 §二；结构校验镜像 condition_engine）
# ---------------------------------------------------------------------------
def test_conditions_three_primitives() -> None:
    """三原语结构通过：值型（level/item_count）/ 累计型（gain_count/kill_count/dungeon_clear/
    main_progress/reputation/codex）/ 事件型（[事件:副本通关] 预置）→ 零记录。"""
    q = {
        "id": "q_prim", "name": "三原语", "conditions": [
            {"var": "level", "op": "ge", "value": 10},                                  # 值型
            {"var": "item_count", "op": "ge", "value": 20, "param": "铁矿"},            # 值型+param
            {"var": "gain_count", "op": "ge", "value": 30, "param": "铁矿"},            # 累计型
            {"var": "kill_count", "op": "ge", "value": 3, "param": "熔岩甲虫"},         # 累计型
            {"var": "dungeon_clear", "op": "ge", "value": 1, "param": "熔岩洞窟"},      # 累计型
            {"var": "main_progress", "op": "ge", "value": 3},                          # 累计型
            {"var": "reputation", "op": "ge", "value": 2, "param": "commercial"},       # 累计型
            {"var": "codex", "op": "ge", "value": 50},                                 # 累计型
            {"var": "[事件:副本通关]", "op": "ge", "value": 1, "param": "熔岩洞窟"},      # 事件型
        ],
    }
    rep = _check([q])
    assert not rep.errors, f"三原语条件不应红拦：{rep.errors}"
    assert not rep.warnings, f"三原语条件不应黄提示：{rep.warnings}"
    assert COND_OPERATORS[0:6] == ("gt", "ge", "lt", "le", "eq", "ne")
    assert "[事件:副本通关]" in COND_EVENT_PRESETS


def test_conditions_structure_errors() -> None:
    """条件结构硬拦（TC-06~12 反面）：var 未注册 / op 非法 / 条件非对象 / 空条件。"""
    q = {
        "id": "q_badcond", "name": "坏条件", "conditions": [
            {"var": "foobar", "op": "eq", "value": 1},
            {"var": "level", "op": "xx", "value": 1},
            "not_an_object",
            {},
        ],
    }
    rep = _check([q])
    assert len(_errs(rep, "var_not_registered")) == 1
    assert len(_errs(rep, "op_invalid")) == 1
    assert len(_errs(rep, "condition_not_object")) == 1
    assert len(_errs(rep, "condition_empty")) == 1


def test_conditions_soft_warnings() -> None:
    """条件软提示（TC-29/TC-31）：旧格式 {type,...} / 事件未登记 → 黄提示不拦。"""
    q = {
        "id": "q_soft", "name": "软条件", "conditions": [
            {"type": "job", "var": "job", "op": "eq", "value": "剑士"},
            {"var": "[事件:落石]", "op": "ge", "value": 1},
        ],
    }
    rep = _check([q])
    assert not rep.errors  # 软提示不拦
    assert len(_warns(rep, "legacy_format")) == 1
    assert len(_warns(rep, "event_not_registered")) == 1
    assert "[事件:落石]" not in COND_EVENT_PRESETS


def test_conditions_all_and_nested() -> None:
    """D-02 数组全与 + {all:[...]} 嵌套 → 结构通过。"""
    q = {
        "id": "q_all", "name": "全与", "conditions": [
            {"all": [
                {"var": "level", "op": "ge", "value": 10},
                {"var": "item_count", "op": "ge", "value": 50, "param": "铁矿"},
            ]},
        ],
    }
    rep = _check([q])
    assert not rep.errors
    assert not rep.warnings
    assert "conditions 数组全与" in QUEST_CONDITIONS_ARRAY_ALL


# ---------------------------------------------------------------------------
# reward 统一条目（2b4 §三：物品/货币键值/组合数组 + rewards 别名 D-01）
# ---------------------------------------------------------------------------
def test_reward_structure_ok() -> None:
    """TC-13~17：物品/货币键值/组合数组合法；内联串（D-05 糖）放行。"""
    q = {
        "id": "q_reward", "name": "奖励", "conditions": [],
        "reward": [{"exp": 50}, {"coins": 80}, {"gem": 3}, {"item": "铁矿", "count": 3}],
    }
    rep = _check([q])
    assert not rep.errors, f"合法 reward 不应红拦：{rep.errors}"
    assert not rep.warnings
    # 内联键值串 = 序列化糖（D-05），结构放行（展开归 core/reward 导入器）
    q2 = {"id": "q_inline", "name": "内联", "conditions": [], "reward": "exp=50,coins=80,item:铁矿*3"}
    rep = _check([q2])
    assert not rep.errors
    assert not rep.warnings
    # rewards 别名（D-01）等价
    q3 = {"id": "q_alias", "name": "别名", "conditions": [], "rewards": [{"exp": 10}]}
    rep = _check([q3])
    assert not rep.errors
    assert not rep.warnings


def test_reward_structure_errors() -> None:
    """reward 结构硬拦：条目非对象 / 同条目混合 / 未知键 / count 非法 / 标量负数。"""
    q = {
        "id": "q_badreward", "name": "坏奖励", "conditions": [], "reward": [
            "not_an_object",
            {"item": "铁矿", "exp": 5},            # 物品+标量混合
            {"item": "铁矿", "foo": 1},            # 未知键
            {"item": "铁矿", "count": 0},          # count 非法
            {"coins": -1},                        # 标量负数
        ],
    }
    rep = _check([q])
    assert len(_errs(rep, "quest_reward_entry_not_object")) == 1
    assert len(_errs(rep, "quest_reward_entry_mixed")) == 1
    assert len(_errs(rep, "quest_reward_entry_unknown_key")) == 1  # 混合条目提前返回，仅 foo 键触发
    assert len(_errs(rep, "quest_reward_count_invalid")) == 1
    assert len(_errs(rep, "quest_reward_value_invalid")) == 1


def test_reward_item_ref_missing() -> None:
    """TC-15 反面：reward 物品引用不存在 → 红拦（R-4，任务定稿 L276）。"""
    q = {"id": "q_ref", "name": "引用", "conditions": [],
         "reward": [{"item": "不存在之物", "count": 1}]}
    rep = _check([q])
    assert len(_errs(rep, "quest_reward_item_ref_missing")) == 1
    # items 模块未声明 → 跳过引用检查（默认放行）
    rep = _check([q], items=None)
    assert not _errs(rep, "quest_reward_item_ref_missing")


def test_reward_alias_conflict() -> None:
    """TC-03：reward 与 rewards 同给异值 → 黄提示「奖励字段重复」；同给同值不提示。"""
    q = {"id": "q_c", "name": "重复", "conditions": [],
         "reward": [{"exp": 50}], "rewards": [{"exp": 60}]}
    rep = _check([q])
    assert not rep.errors
    assert len(_warns(rep, "quest_reward_alias_conflict")) == 1
    q2 = {"id": "q_c", "name": "重复", "conditions": [],
          "reward": [{"exp": 50}], "rewards": [{"exp": 50}]}
    rep = _check([q2])
    assert not _warns(rep, "quest_reward_alias_conflict")


# ---------------------------------------------------------------------------
# 防刷：每日完成上限默认 10 / 同时接取上限默认 5（任务定稿 L183/L184）
# ---------------------------------------------------------------------------
def test_daily_limit_default_and_over() -> None:
    """TC-18/19：daily_limit 默认 10（0=不限）；>10 → 黄提示（板上限冲突，不拦）。"""
    assert QUEST_DAILY_LIMIT_DEFAULT == 10
    assert BOARD_LIMIT_OVER_WARN == 10
    # 未配 board → 默认 10（TC-01 断言）
    q = {"id": "q_dl", "name": "防刷", "conditions": []}
    d = QuestDef.from_entry(q)
    assert d.board_daily_limit() == 10
    rep = _check([q])
    assert not _warns(rep, "quest_daily_limit_over_default")
    # daily_limit:0（0=不限，TC-19）→ 不提示
    q0 = {"id": "q_dl", "name": "防刷", "conditions": [], "board": {"daily_limit": 0}}
    rep = _check([q0])
    assert not _warns(rep, "quest_daily_limit_over_default")
    # daily_limit:11 > 10 → 黄提示（不拦加载）
    q11 = {"id": "q_dl", "name": "防刷", "conditions": [], "board": {"daily_limit": 11}}
    rep = _check([q11])
    assert not rep.errors
    assert len(_warns(rep, "quest_daily_limit_over_default")) == 1
    # 负数 → 红拦（R-2）
    rep = _check([{"id": "q_dl", "name": "防刷", "conditions": [],
                   "board": {"daily_limit": -1}}])
    assert len(_errs(rep, "quest_board_daily_limit_invalid")) == 1


def test_accept_limit_default_and_over() -> None:
    """TC-20：accept_limit 默认 5（0=不限）；>5 → 黄提示（不拦）。"""
    assert QUEST_ACCEPT_LIMIT_DEFAULT == 5
    assert BOARD_ACCEPT_OVER_WARN == 5
    q = {"id": "q_al", "name": "接取", "conditions": []}
    d = QuestDef.from_entry(q)
    assert d.board_accept_limit() == 5
    rep = _check([q])
    assert not _warns(rep, "quest_accept_limit_over_default")
    # accept_limit:0（0=不限）→ 不提示
    q0 = {"id": "q_al", "name": "接取", "conditions": [], "board": {"accept_limit": 0}}
    rep = _check([q0])
    assert not _warns(rep, "quest_accept_limit_over_default")
    # accept_limit:6 > 5 → 黄提示
    q6 = {"id": "q_al", "name": "接取", "conditions": [], "board": {"accept_limit": 6}}
    rep = _check([q6])
    assert not rep.errors
    assert len(_warns(rep, "quest_accept_limit_over_default")) == 1
    # 负数 → 红拦
    rep = _check([{"id": "q_al", "name": "接取", "conditions": [],
                   "board": {"accept_limit": -2}}])
    assert len(_errs(rep, "quest_board_accept_limit_invalid")) == 1


# ---------------------------------------------------------------------------
# 引用悬空（任务定稿 L276 硬拦 4 类 + 黄提示族）
# ---------------------------------------------------------------------------
def test_zone_ref_missing() -> None:
    """TC-05：zone 引用不存在 → 红拦（R-4，硬拦 4 类之一）。"""
    q = {"id": "q_zone", "name": "副本", "conditions": [], "zone": "nonexistent_dungeon"}
    rep = _check([q])
    assert len(_errs(rep, "quest_zone_ref_missing")) == 1
    # 合法 zone（maps 或 dungeon 的 id）→ 零红拦
    rep = _check([{"id": "q_zone", "name": "副本", "conditions": [], "zone": "molten_dungeon"}])
    assert not _errs(rep, "quest_zone_ref_missing")
    # maps/dungeon 模块未声明 → 跳过引用检查
    rep = _check([q], maps=None, dungeon=None)
    assert not _errs(rep, "quest_zone_ref_missing")


def test_unlock_chain_dead() -> None:
    """unlock_chain 引用悬空 → 黄提示死链（不拦；2b4 §1.5 黄提示族）。"""
    q = {"id": "q_chain", "name": "链式", "conditions": [], "unlock_chain": "q_missing"}
    rep = _check([q])
    assert not rep.errors
    assert len(_warns(rep, "quest_unlock_chain_dead")) == 1
    # 合法前置（本池内存在）→ 零黄
    rep = _check([{"id": "q_ore_20", "name": "前置", "conditions": []},
                  {"id": "q_chain", "name": "链式", "conditions": [],
                   "unlock_chain": "q_ore_20"}])
    assert not _warns(rep, "quest_unlock_chain_dead")


def test_npc_grant_ref_missing() -> None:
    """npc.id 引用不存在 → 红拦（R-4）；结构非法 → 红拦。"""
    q = {"id": "q_npc", "name": "支线", "conditions": [], "npc": {"id": "ghost_npc"}}
    rep = _check([q])
    assert len(_errs(rep, "quest_npc_ref_missing")) == 1
    # 合法 npc → 零红拦
    rep = _check([{"id": "q_npc", "name": "支线", "conditions": [],
                   "npc": {"id": "blacksmith", "priority": 2}}])
    assert not rep.errors
    assert not rep.warnings
    # npc 模块未声明 → 跳过
    rep = _check([q], npc=None)
    assert not _errs(rep, "quest_npc_ref_missing")


def test_npc_grant_structure() -> None:
    """npc 子对象结构：非对象红拦 / conditions 非数组红拦 / priority 负数红拦。"""
    q = {"id": "q_npc", "name": "支线", "conditions": [],
         "npc": {"id": "blacksmith", "conditions": "nope", "priority": -1}}
    rep = _check([q])
    assert len(_errs(rep, "quest_npc_conditions_not_list")) == 1
    assert len(_errs(rep, "quest_npc_priority_invalid")) == 1
    rep = _check([{"id": "q_npc", "name": "支线", "conditions": [], "npc": "not_object"}])
    assert len(_errs(rep, "quest_npc_not_object")) == 1


# ---------------------------------------------------------------------------
# 双板：board.slot 多板（daily/weekly/event）+ 板结构（任务定稿 L181-187）
# ---------------------------------------------------------------------------
def test_board_slots_multi_board() -> None:
    """双板：slot 枚举 daily|weekly|event 合法；非法 → 红拦；缺省 daily 不拦。"""
    for slot in ("daily", "weekly", "event"):
        rep = _check([{"id": "q_s", "name": "板", "conditions": [], "board": {"slot": slot}}])
        assert not rep.errors, f"board.slot={slot} 不应红拦：{rep.errors}"
    assert set(BOARD_SLOTS) == {"daily", "weekly", "event"}
    rep = _check([{"id": "q_s", "name": "板", "conditions": [], "board": {"slot": "hourly"}}])
    assert len(_errs(rep, "quest_board_slot_invalid")) == 1
    # 缺省 board → 每日默认板，绝不报错
    rep = _check([{"id": "q_s", "name": "板", "conditions": []}])
    assert not rep.errors


def test_board_refresh_and_structure() -> None:
    """board.refresh 枚举 daily|weekly|once；board 非对象 / limit 负数 → 红拦。"""
    for mode in ("daily", "weekly", "once"):
        rep = _check([{"id": "q_r", "name": "刷", "conditions": [], "board": {"refresh": mode}}])
        assert not rep.errors, f"board.refresh={mode} 不应红拦"
    assert set(BOARD_REFRESH_MODES) == {"daily", "weekly", "once"}
    rep = _check([{"id": "q_r", "name": "刷", "conditions": [], "board": {"refresh": "monthly"}}])
    assert len(_errs(rep, "quest_board_refresh_invalid")) == 1
    rep = _check([{"id": "q_r", "name": "刷", "conditions": [], "board": "not_object"}])
    assert len(_errs(rep, "quest_board_not_object")) == 1
    rep = _check([{"id": "q_r", "name": "刷", "conditions": [], "board": {"limit": -3}}])
    assert len(_errs(rep, "quest_board_limit_invalid")) == 1


# ---------------------------------------------------------------------------
# id / name / type / 其它结构
# ---------------------------------------------------------------------------
def test_id_required_and_duplicate() -> None:
    """id 缺失 → 红拦；两个任务同 id → 红拦（唯一性）。"""
    quests = _legal_quests()
    quests[0]["id"] = ""
    rep = _check(quests)
    assert _errs(rep, "quest_id_required")
    quests = _legal_quests()
    quests[1]["id"] = "q_ore_20"  # 与 quests[0] 同 id
    rep = _check(quests)
    assert len(_errs(rep, "quest_id_duplicate")) == 1


def test_name_required() -> None:
    """name 必填 → 红拦。"""
    quests = [_legal_quests()[0]]
    del quests[0]["name"]
    rep = _check(quests)
    assert len(_errs(rep, "quest_name_required")) == 1


def test_type_is_pure_label() -> None:
    """TC-04：自定义 type 标签（不在预设 collect/deliver/slay/explore/intel）不报错——纯展示标签。"""
    for tag in ("gather_rare", "hunt_boss", "intel"):
        rep = _check([{"id": "q_t", "name": "标签", "conditions": [], "type": tag}])
        assert not rep.errors, f"type={tag} 不应红拦（纯展示标签）"
    # 非字符串 type → 红拦
    rep = _check([{"id": "q_t", "name": "标签", "conditions": [], "type": 123}])
    assert len(_errs(rep, "quest_type_invalid")) == 1


def test_repeatable_structure() -> None:
    """repeatable：bool / {decay,cap} 合法；非法形态红拦；衰减异常黄提示（F-4）。"""
    for r in (True, False, {"decay": 0.5, "cap": 1}, None):
        rep = _check([{"id": "q_r", "name": "重复", "conditions": [], "repeatable": r}])
        assert not rep.errors, f"repeatable={r!r} 不应红拦"
        assert not rep.warnings
    # 非法形态
    rep = _check([{"id": "q_r", "name": "重复", "conditions": [], "repeatable": "yes"}])
    assert len(_errs(rep, "quest_repeatable_invalid")) == 1
    # decay 越界（0<decay<1 之外）→ 黄提示
    rep = _check([{"id": "q_r", "name": "重复", "conditions": [],
                   "repeatable": {"decay": 2, "cap": 1}}])
    assert not rep.errors
    assert len(_warns(rep, "quest_repeatable_anomaly")) == 1
    # cap 非法 → 红拦
    rep = _check([{"id": "q_r", "name": "重复", "conditions": [],
                   "repeatable": {"decay": 0.5, "cap": 0}}])
    assert len(_errs(rep, "quest_repeatable_cap_invalid")) == 1


def test_timed_structure() -> None:
    """timed：{deadline, penalty} 结构；非对象 → 红拦（D-06）。"""
    rep = _check([{"id": "q_t", "name": "限时", "conditions": [],
                   "timed": {"deadline": "2026-09-01 05:00"}}])
    assert not rep.errors
    rep = _check([{"id": "q_t", "name": "限时", "conditions": [], "timed": "nope"}])
    assert len(_errs(rep, "quest_timed_not_object")) == 1


def test_conditions_not_list_and_bonus() -> None:
    """conditions 非数组红拦；bonus 结构（非对象/condition 结构/mult 非法）。"""
    rep = _check([{"id": "q_c", "name": "条件", "conditions": {"var": "level"}}])
    assert len(_errs(rep, "quest_conditions_not_list")) == 1
    q = {"id": "q_b", "name": "倍率", "conditions": [],
         "bonus": {"condition": {"var": "foobar", "op": "eq", "value": 1}, "mult": -1}}
    rep = _check([q])
    assert len(_errs(rep, "var_not_registered")) == 1
    assert len(_errs(rep, "quest_bonus_mult_invalid")) == 1
    rep = _check([{"id": "q_b", "name": "倍率", "conditions": [], "bonus": "nope"}])
    assert len(_errs(rep, "quest_bonus_not_object")) == 1
