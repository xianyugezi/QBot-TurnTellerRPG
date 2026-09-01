"""6a 行动库数据模型单测（tests/unit/test_skill_action_models.py · M13 批1 路1B）。

覆盖细化_6a 契约：
  - §2.2 ActionCore 共用块 7 字段（F01-F07 同构）
  - §2.3 怪物侧扩展 G01-G05 + 目标 G06 + 触发上限 G07 + AI 登记接口 G08-G16
  - ③ 校验器 V-4（元素注册表）/ V-9（probability 0/1 + 纯脚本怪）/ V-10（ID 唯一）/
    V-11（未登记字段拒绝）/ V-13（基础门禁）
  - ⑥ TC-01（示例数据加载）/ TC-07（V-10）/ TC-10（V-4）/ TC-12（V-9）/ TC-13（V-11）

测试目标：qbot_rpg.content.skill_action_models.{ActionDef, validate_actions,
skill_action_meta, action_core_meta, ACTION_CORE_FIELDS, ACTION_CORE_DEFAULTS,
ACTION_FIELD_REGISTRY, ACTION_KIND_VALUES, ATTACK_TYPE_VALUES, ELEMENT_VALUES,
TARGET_VALUES, INTENT_VALUES, DEFAULT_TRIGGER_LIMIT}。

测试口径（对齐 test_fishing_models.py / test_achievements_models.py）：
  - validate_actions 为 (modules, report) 纯函数；report 鸭子类型（_Report 收集器 +
    dict {"errors","warnings"} 形态 + 真实 validator._Checker 收口兼容测试）。
  - 断言级别：errors=红拦（加载失败）/ warnings=黄提示（不阻断）。
  - legal 包零红：读 tests/fixtures/packs/legal/action.json 断言 validate_actions
    红拦零命中（契约 TC-01 行动库侧）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping, Set, cast

from qbot_rpg.content.skill_action_models import (
    ACTION_CORE_DEFAULTS,
    ACTION_CORE_FIELDS,
    ACTION_FIELD_REGISTRY,
    ACTION_KIND_VALUES,
    ATTACK_TYPE_VALUES,
    DEFAULT_TRIGGER_LIMIT,
    INTENT_VALUES,
    TARGET_VALUES,
    ActionDef,
    action_core_meta,
    skill_action_meta,
    validate_actions,
)

LEGAL_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs" / "legal"


# ---------------------------------------------------------------------------
# 收集器 / 夹具辅助
# ---------------------------------------------------------------------------
class _Report:
    """validate_actions 收集器（鸭子类型：error/warning 与 _Checker._err/_warn 一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _ok_action(**over: object) -> dict:
    """一条合法行动（契约 §2 全字段形态 + 最小缺省兜底）。"""
    a = {
        "id": "claw_swipe",
        "name": "爪击",
        "kind": "damage",
        "power": 100,
        "attack_type": "slash",
        "element": "earth",
        "effects": [],
    }
    a.update(over)
    return a


def _ok_full_action(**over: object) -> dict:
    """全字段行动（G01-G07 + AI 登记接口 G08-G16 全配）。"""
    a = {
        "id": "tail_sweep",
        "name": "尾扫",
        "kind": "damage",
        "power": 80,
        "attack_type": "blunt",
        "element": "wind",
        "effects": [{"effect": "power_slash", "overrides": {"power": 50}}],
        # G01-G05 + G06 + G07
        "weight": 30,
        "probability": 1,
        "intent": "damage",
        "chain": ["claw_swipe"],
        "cooldown": 1,
        "target": "enemy_all",
        "trigger_limit": {"per_round": 3, "per_battle": 10},
        # AI 登记接口 G08-G16
        "condition": {"pv": "broken"},
        "hungry": 2,
        "armor": True,
        "interrupt": False,
        "tags": ["物理", "范围"],
        "charge": {"turns": 1},
        "preview": {"level": 2},
        "preview_chain": {"next": "claw_swipe"},
        "reveal_condition": "pv_broken",
        # 细化定型 F21
        "desc": "横扫尾部的范围攻击",
    }
    a.update(over)
    return a


def _modules(actions: list, **extra: object) -> dict:
    """校验器 modules（action 键 + 引用靶模块）。"""
    m: Dict[str, object] = {"action": actions}
    m.update(extra)
    return m


def _run(modules: Mapping[str, object]) -> _Report:
    """跑 validate_actions，返回收集器。"""
    report = _Report()
    validate_actions(modules, report)
    return report


def _rules(report: _Report, level: str) -> Set[str]:
    """收集指定级别（errors/warnings）的 rule 名集合。"""
    return {e["detail"].get("rule") for e in getattr(report, level)}


# ---------------------------------------------------------------------------
# TC-01 示例数据加载 + 缺省兜底（三铁律②：漏配 = 合理默认不是报错）
# ---------------------------------------------------------------------------
def test_tc01_legal_full_zero_red() -> None:
    """全字段行动条目 → 红拦零命中（TC-01 行动库侧）。"""
    report = _run(_modules([_ok_full_action()]))
    assert report.errors == [], f"全字段合法行动应零红，got {report.errors}"


def test_tc02_minimal_defaults() -> None:
    """最小行动 {id,name} → 加载成功（kind/power/attack_type/element/effects 缺省兜底）。"""
    report = _run(_modules([_ok_action()]))
    assert report.errors == [], f"最小行动应零红，got {report.errors}"
    d = cast(ActionDef, ActionDef.from_entry({"id": "min", "name": "最小"}))
    assert d.power is None and d.element is None
    assert d.effects == ()
    # 缺省兜底表（契约 §1.2-A 默认值）
    assert ACTION_CORE_DEFAULTS["power"] == 100
    assert ACTION_CORE_DEFAULTS["kind"] == "damage"
    assert ACTION_CORE_DEFAULTS["attack_type"] == "slash"
    assert ACTION_CORE_DEFAULTS["effects"] == ()


# ---------------------------------------------------------------------------
# ActionCore 7 字段同构 + ActionDef 访问器
# ---------------------------------------------------------------------------
def test_action_core_fields_tuple() -> None:
    """ActionCore 共用块 7 字段（契约 §2.2：F01-F07 逐字段同构）。"""
    assert ACTION_CORE_FIELDS == (
        "id", "name", "kind", "power", "attack_type", "element", "effects",
    )


def test_action_def_accessors() -> None:
    """ActionDef 访问器冒烟（ActionCore 7 + G01-G07 + AI 登记接口 + desc）。"""
    d = cast(ActionDef, ActionDef.from_entry(_ok_full_action()))
    assert d.id == "tail_sweep" and d.name == "尾扫"
    # ActionCore 7
    assert d.power == 80.0
    assert d.attack_type == "blunt"
    assert d.element == "wind"
    assert d.effects == ({"effect": "power_slash", "overrides": {"power": 50}},)
    # G01-G07
    assert d.weight == 30.0
    assert d.probability == 1.0
    assert d.intent == "damage"
    assert d.chain == ("claw_swipe",)
    assert d.cooldown == 1.0
    assert d.target == "enemy_all"
    assert d.trigger_limit == {"per_round": 3, "per_battle": 10}
    # AI 登记接口 G08-G16
    assert d.condition == {"pv": "broken"}
    assert d.hungry == 2.0
    assert d.armor is True
    assert d.interrupt is False
    assert d.tags == ("物理", "范围")
    assert d.charge == {"turns": 1}
    assert d.preview == {"level": 2}
    assert d.preview_chain == {"next": "claw_swipe"}
    assert d.reveal_condition == "pv_broken"
    assert d.desc == "横扫尾部的范围攻击"
    # AI 登记接口全集
    ai = d.ai_fields()
    assert set(ai) == {
        "condition", "hungry", "armor", "interrupt", "tags",
        "charge", "preview", "preview_chain", "reveal_condition",
    }


def test_action_def_charge_prefix() -> None:
    """charge_* 前缀字段防御性读取（契约 §2.3：键名前缀登记）。"""
    d = cast(ActionDef, ActionDef.from_entry(_ok_action(charge_turns=1, charge_armor=True)))
    assert d.charge_fields() == {"charge_turns": 1, "charge_armor": True}


def test_action_def_missing_defaults() -> None:
    """漏配字段 → 防御性访问器缺省兜底（None/() 不炸，三铁律②）。"""
    d = cast(ActionDef, ActionDef.from_entry({"id": "min", "name": "最小"}))
    assert d.weight is None
    assert d.probability is None
    assert d.intent is None
    assert d.chain == ()
    assert d.cooldown is None
    assert d.target is None
    assert d.trigger_limit is None
    assert d.condition is None
    assert d.hungry is None
    assert d.armor is None
    assert d.tags == ()
    assert d.charge is None
    assert d.charge_fields() == {}
    assert d.preview is None
    assert d.ai_fields() == {}


# ---------------------------------------------------------------------------
# 元数据单点（V-11 判定依据 / 编辑器注册表）
# ---------------------------------------------------------------------------
def test_meta_registry_contains_all_contract_fields() -> None:
    """行动库字段注册表含契约全部字段（F01-F07 + G01-G07 + AI 登记接口 G08-G16 + desc）。"""
    registry = set(ACTION_FIELD_REGISTRY)
    for f in ACTION_CORE_FIELDS:
        assert f in registry, f"ActionCore 字段 {f} 未登记"
    for g in ("weight", "probability", "intent", "chain", "cooldown", "target", "trigger_limit"):
        assert g in registry, f"G 系列字段 {g} 未登记"
    for ai in ("condition", "hungry", "armor", "interrupt", "tags",
               "charge", "preview", "preview_chain", "reveal_condition"):
        assert ai in registry, f"AI 登记接口 {ai} 未登记"
    assert "desc" in registry


def test_action_core_meta_single_point() -> None:
    """ActionCore 元数据单点（契约 §2.1/§⑦：skills 与 action 共用同一份定义）。"""
    meta = action_core_meta()
    assert set(meta) == set(ACTION_CORE_FIELDS)
    assert meta["id"].required is True
    assert meta["power"].default == 100
    assert meta["kind"].default == "damage"
    assert meta["effects"].type == "list"
    assert meta["effects"].element is not None and meta["effects"].element.ref_target == "effect"


def test_skill_action_meta_module() -> None:
    """行动库模块元数据工厂（供 field_meta 收口接线；kind=action / action_lib 命名空间）。"""
    meta = skill_action_meta()
    assert meta.entry_type == "list"
    assert meta.kind == "action"
    assert meta.namespace == "action_lib"
    assert meta.fields["target"].default == "enemy_single"
    assert meta.fields["weight"].default == 0
    assert meta.fields["probability"].default == 0
    assert "trigger_limit" in meta.fields


# ---------------------------------------------------------------------------
# V-11 未登记字段拒绝（TC-13）
# ---------------------------------------------------------------------------
def test_tc13_unregistered_field_hard_block() -> None:
    """行动带未登记字段 foo → 红拦「未登记字段」（V-11 防 schema 漂移）。"""
    report = _run(_modules([_ok_action(foo=1)]))
    assert "unregistered_field" in _rules(report, "errors"), \
        f"未登记字段应红拦，got {report.errors}"


def test_tc13_charge_prefix_registered() -> None:
    """charge_* 前缀字段放行（契约 §2.3：前缀登记），不触发 V-11。"""
    report = _run(_modules([_ok_action(charge_turns=1, charge_armor=True)]))
    assert report.errors == [], f"charge_* 前缀字段应放行，got {report.errors}"


# ---------------------------------------------------------------------------
# V-10 ID 唯一（TC-07）
# ---------------------------------------------------------------------------
def test_tc07_duplicate_id_hard_block() -> None:
    """库内两条同 id 行动 → 红拦（V-10 库内唯一）。"""
    report = _run(_modules([_ok_action(), _ok_action()]))
    assert "action_id_duplicate" in _rules(report, "errors"), \
        f"重复 id 应红拦，got {report.errors}"


# ---------------------------------------------------------------------------
# V-4 元素注册表（TC-10）
# ---------------------------------------------------------------------------
def test_tc10_element_registry() -> None:
    """element=thunder（注册表内）通过；element=ice（未注册）红拦（V-4）。"""
    ok = _run(_modules([_ok_action(element="thunder")]))
    assert ok.errors == [], f"注册表内元素应通过，got {ok.errors}"
    bad = _run(_modules([_ok_action(element="ice")]))
    assert "element_not_registered" in _rules(bad, "errors"), \
        f"未注册元素应红拦，got {bad.errors}"


def test_tc10_element_null_allowed() -> None:
    """element=null（缺省）通过（F06 默认 null）。"""
    report = _run(_modules([_ok_action(element=None)]))
    assert report.errors == [], f"element null 应通过，got {report.errors}"


# ---------------------------------------------------------------------------
# V-9 概率语义 + 纯脚本怪（TC-12）
# ---------------------------------------------------------------------------
def test_tc12_probability_must_be_01() -> None:
    """probability 负值 → 红拦（V-9 + P-8 读兼容：非 0/1 正值等价 1 放行）。"""
    # P-8 读兼容：既有内容包 probability=0.5 旧语义（正值等价 1）放行
    report = _run(_modules([_ok_action(probability=2)]))
    assert report.errors == [], f"probability=2 正值应放行（P-8 读兼容），got {report.errors}"
    # 负值红拦
    report = _run(_modules([_ok_action(probability=-1)]))
    assert "probability_not_01" in _rules(report, "errors"), \
        f"probability=-1 应红拦，got {report.errors}"


def test_tc12_pure_script_warning() -> None:
    """weight 全 0 且无 chain/condition → 黄提示「纯脚本怪？」（V-9 不拦截）。"""
    report = _run(_modules([_ok_action(weight=0)]))
    assert report.errors == [], f"纯脚本怪黄提示不应红拦，got {report.errors}"
    assert "pure_script_monster" in _rules(report, "warnings"), \
        f"应发纯脚本怪黄提示，got {report.warnings}"


def test_tc12_weight_chain_suppress_warning() -> None:
    """weight>0 或 chain/condition 任一存在 → 不触发纯脚本怪提示。"""
    for over in ({"weight": 10}, {"chain": ["claw_swipe"]}, {"condition": "pv_broken"}):
        report = _run(_modules([_ok_action(**over)]))
        assert "pure_script_monster" not in _rules(report, "warnings"), \
            f"over={over} 不应发纯脚本怪提示，got {report.warnings}"


# ---------------------------------------------------------------------------
# V-13 基础门禁（id/name/kind/attack_type/power/target）
# ---------------------------------------------------------------------------
def test_v13_id_name_required() -> None:
    """id/name 非空（V-13 基础门禁）。"""
    rep1 = _run(_modules([_ok_action(id="")]))
    assert "action_id_invalid" in _rules(rep1, "errors")
    rep2 = _run(_modules([_ok_action(name="")]))
    assert "action_name_invalid" in _rules(rep2, "errors")


def test_v13_kind_enum() -> None:
    """kind 五枚举（V-13）；既有内容包 basic/active 旧值读兼容放行。"""
    for k in ACTION_KIND_VALUES:
        report = _run(_modules([_ok_action(kind=k)]))
        assert report.errors == [], f"kind={k} 应通过，got {report.errors}"
    legacy = _run(_modules([_ok_action(kind="basic")]))
    assert legacy.errors == [], f"旧值 basic 应读兼容放行，got {legacy.errors}"
    bad = _run(_modules([_ok_action(kind="bogus")]))
    assert "kind_enum_invalid" in _rules(bad, "errors"), \
        f"kind=bogus 应红拦，got {bad.errors}"


def test_v13_attack_type_enum() -> None:
    """attack_type 五枚举（V-13）；中文旧值读兼容放行。"""
    for at in ATTACK_TYPE_VALUES:
        report = _run(_modules([_ok_action(attack_type=at)]))
        assert report.errors == [], f"attack_type={at} 应通过，got {report.errors}"
    legacy = _run(_modules([_ok_action(attack_type="斩")]))
    assert legacy.errors == [], f"中文旧值 斩 应读兼容放行，got {legacy.errors}"
    bad = _run(_modules([_ok_action(attack_type="bogus")]))
    assert "attack_type_enum_invalid" in _rules(bad, "errors"), \
        f"attack_type=bogus 应红拦，got {bad.errors}"


def test_v13_power_negative() -> None:
    """power 负数 → 红拦（V-13 数值域）；power 缺省放行。"""
    bad = _run(_modules([_ok_action(power=-10)]))
    assert "power_negative" in _rules(bad, "errors"), \
        f"power 负数应红拦，got {bad.errors}"
    ok = _run(_modules([_ok_action()]))
    assert ok.errors == []


def test_g06_target_enum() -> None:
    """target 六枚举（G06 细化定型）；非法值红拦。"""
    for t in TARGET_VALUES:
        report = _run(_modules([_ok_action(target=t)]))
        assert report.errors == [], f"target={t} 应通过，got {report.errors}"
    bad = _run(_modules([_ok_action(target="all_enemies")]))
    assert "target_enum_invalid" in _rules(bad, "errors"), \
        f"target=all_enemies 应红拦，got {bad.errors}"


def test_g02_g03_enums_constants() -> None:
    """G02/G03 枚举常量（契约 §2.3：probability ∈ {0,1} / intent 九枚举）。"""
    assert INTENT_VALUES == (
        "damage", "defense", "charge", "heal", "control", "buff", "debuff", "mark", "utility",
    )
    assert DEFAULT_TRIGGER_LIMIT == {"per_round": 10, "per_battle": 99}
    # G02 合法值 0/1 均通过
    for p in (0, 1):
        report = _run(_modules([_ok_action(probability=p)]))
        assert report.errors == [], f"probability={p} 应通过，got {report.errors}"


# ---------------------------------------------------------------------------
# 收集器三形态 / legal 包零红 / 登记一致性
# ---------------------------------------------------------------------------
def test_report_dict_form() -> None:
    """收集器 dict 形态：{\"errors\":[],\"warnings\":[]}（_emit 兜底）。"""
    modules = _modules([_ok_action(foo=1)])
    report: Dict[str, list] = {"errors": [], "warnings": []}
    validate_actions(modules, report)
    assert report["errors"], "dict 形态应收集 errors"
    assert report["errors"][0]["rule"] == "unregistered_field"


def test_report_checker_form() -> None:
    """真实 validator._Checker 收口兼容（_err/_warn 回落）。"""
    from qbot_rpg.content.field_meta import default_field_meta_table
    from qbot_rpg.content.validator import _Checker

    checker = _Checker(_modules([_ok_action(foo=1)]), default_field_meta_table())
    validate_actions(_modules([_ok_action(foo=1)]), checker)
    assert any("unregistered_field" in str(e.detail) for e in checker.errors), \
        "_Checker 应收集 V-11 红拦"


def test_legal_pack_zero_red() -> None:
    """legal 包 action.json 红拦零命中（契约 TC-01：示例数据加载）。"""
    actions = json.loads((LEGAL_DIR / "action.json").read_text(encoding="utf-8"))
    report = _run(_modules(actions))
    assert report.errors == [], f"legal action.json 应红拦零命中，got {report.errors}"


def test_actions_module_missing_skipped() -> None:
    """action 模块缺失 → 跳过不报错（对齐既有校验器「模块未接线默认放行」惯例）。"""
    report = _run({})
    assert report.errors == [] and report.warnings == []
