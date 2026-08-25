"""细化_1e §⑥ 验收测试用例 TC-01~TC-14 → pytest（M2 怪物体系 · A3 路：enemies 八段 schema）。

依据：细化_1e_怪物八段schema.md §⑥（TC-01~14 权威输入/预期）+ §①（字段级 schema F01-F18）+
§②（难度模板默认值）+ §④（木桩特例）+ §⑤（校验器规则 R1-R15）+ m2_shared_contract 第一~四节。
TC-14（残血换区 PV 恢复一半 / battle_start 开场技）是运行期行为，依赖战斗引擎与地图挂接（M3），
schema 层不验证 → pytest.mark.skip（附依赖说明）。

测试口径：每条测试按「构造输入 → 跑校验器 → 断言级别/结果」模式。校验器入口：
  - qbot_rpg.content.validator.check_pack（纯函数，直接喂 modules 字典）
  - qbot_rpg.content.loader.build_pack（整包管线，含 registry 挂载；用于合法包全量 TC-01）
断言级别：errors=拦截（拒绝入库）/ warnings=黄提示（不拦截）/ notes=提示（信息）。

契约偏差（登记，供主 agent 收口）：
  1. TC-04 文档示例元素 `thunder` 已在 8 元素注册表（_DEFAULT_ELEMENTS，与 core/damage.py 同源），
     不再触发引用拦截；测试改用 `ice`（未注册）触发同一 R3_element_ref 规则。
  2. TC-07 文档示例行动名 claw/rock_roll/hard_body/swipe/x 映射到 action.json 真实 ID
     （claw_swipe/rock_roll/hard_body/tail_sweep）；归一化概率数学（50/80、30/80）属 M3 AI 引擎，
     schema 层断言「池成员资格 + 权重和」数据级口径。
  3. 合法包 action.json 的入池行动 probability 用等价正值 0.5（细化_1e S1「写其他正值等价 1」）：
     0/1 触发 Y-2 概率极值黄提示（F_PROBABILITY 旗标误伤 0/1 开关），破坏 legal 包零黄提示基线；
     锚点行动缺省（默认 0），池语义规范表达在 enemies.actions[].probability。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from qbot_rpg.content.loader import PackLoadError, build_pack
from qbot_rpg.content.validator import (
    DIFFICULTY_TEMPLATES,
    PV_RANGES,
    TRIGGER_ALIASES,
    apply_enemy_difficulty_template,
    check_pack,
    is_dummy_enemy,
)

PACKS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs"
LEGAL_DIR = PACKS_DIR / "legal"
BADREF_DIR = PACKS_DIR / "badref"


# ---------------------------------------------------------------------------
# 夹具辅助：构造输入 → 跑校验器
# ---------------------------------------------------------------------------
def _load_pack_json(pack_dir: Path, name: str) -> object:
    return json.loads((pack_dir / f"{name}.json").read_text(encoding="utf-8"))


def _legal_enemies() -> list:
    data = _load_pack_json(LEGAL_DIR, "enemies")
    assert isinstance(data, list)
    return data


def _base_enemy(**overrides: object) -> dict:
    """合法普通怪（TC-01 形状）的深拷贝，用于单条校验用例的构造输入。"""
    for e in _legal_enemies():
        if e.get("id") == "rock_weasel":
            enemy = copy.deepcopy(e)
            enemy.update(overrides)
            return enemy
    raise AssertionError("legal/enemies.json 缺少 rock_weasel")


def _check(enemies: object, extra_modules: dict | None = None):
    """标准模块上下文（action/effects/statuses/items 取 legal fixtures 作引用基线）+ 传入 enemies 跑校验器。"""
    modules: dict = {
        "action": _load_pack_json(LEGAL_DIR, "action"),
        "effects": _load_pack_json(LEGAL_DIR, "effects"),
        "statuses": _load_pack_json(LEGAL_DIR, "statuses"),
        "items": _load_pack_json(LEGAL_DIR, "items"),
        "enemies": enemies,
    }
    if extra_modules:
        modules.update(extra_modules)
    return check_pack(modules)


def _errs(rep, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e.detail.get("rule") == rule]


def _warns(rep, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w.detail.get("rule") == rule]


def _notes(rep, rule: str | None = None) -> list:
    return [n for n in rep.notes if rule is None or n.detail.get("rule") == rule]


# ---------------------------------------------------------------------------
# TC-01 合法普通怪全量（细化_1e §⑥ TC-01）
# ---------------------------------------------------------------------------
def test_tc01_legal_enemy_full_green() -> None:
    """TC-01：合法包（含八段怪）整包校验全绿 + 普通怪八段齐全结构断言。

    输入：tests/fixtures/packs/legal（enemies.json 八段合法怪：普通/精英/BOSS/木桩各一 +
    action.json 怪物行动库）；预期：无拦截、无警告（合法包零黄基线，细化_3e#TC-30 同步覆盖）。
    """
    pack, changed = build_pack(LEGAL_DIR)
    assert changed
    assert pack.report.ok, f"合法包不应有红拦：{pack.report.errors}"
    assert not pack.report.warnings, f"合法包应为零黄提示：{pack.report.warnings}"

    enemies = _legal_enemies()
    ids = [e["id"] for e in enemies]
    assert len(ids) == len(set(ids)) == 4  # id 唯一（R8）

    rock = next(e for e in enemies if e["id"] == "rock_weasel")
    # TC-01 形状：tier normal / stats 9 键 / weakness / pv 20 / resistance / actions×2 /
    # special_actions×1 / drops 三类 / lore[10,50,100]
    assert rock["tier"] == "normal"
    assert set(rock["stats"]) == {"hp", "mp", "str", "int", "con", "spr", "foc", "agi", "luk"}
    assert rock["weakness"] and rock["weakness"] != {}
    assert rock["pv"] == 20
    assert "resistance" in rock
    assert len(rock["actions"]) == 2
    assert len(rock["special_actions"]) == 1
    assert set(rock["drops"]) == {"battle", "special", "death"}
    assert [l["unlock"] for l in rock["lore"]] == [10, 50, 100]  # 递增

    # 三档齐全 + 木桩
    tiers = {e["id"]: e.get("tier") for e in enemies}
    assert tiers["rock_weasel"] == "normal"
    assert tiers["stone_skink"] == "elite"
    assert tiers["ember_drake"] == "boss"
    assert tiers["training_dummy"] == "training"
    assert is_dummy_enemy(next(e for e in enemies if e["id"] == "training_dummy"))

    # registry 挂载：行动引用可解析
    assert pack.registry.resolve("claw_swipe", "action") is not None
    assert pack.registry.resolve("ember_drake", "enemy") is not None


# ---------------------------------------------------------------------------
# TC-02 stats 漏键模板补全（细化_1e §⑥ TC-02）
# ---------------------------------------------------------------------------
def test_tc02_stats_missing_template_fill() -> None:
    """TC-02：normal 怪缺 agi/luk → 提示「按低档模板补全」+ 补全模板基准值（10.0）。"""
    enemy = _base_enemy()
    del enemy["stats"]["agi"]
    del enemy["stats"]["luk"]
    rep = _check([enemy])
    assert not rep.errors

    fills = {n.detail["key"]: n.detail for n in _notes(rep, "R9_template_fill")}
    assert {"agi", "luk"} <= set(fills), f"应提示补全 agi/luk，实际 {list(fills)}"
    assert fills["agi"]["value"] == 10.0 and fills["luk"]["value"] == 10.0
    assert fills["agi"]["tier"] == "normal"

    # 模板函数同口径：补全键与基准值
    completed, _pv, filled = apply_enemy_difficulty_template(enemy["stats"], "normal")
    assert filled == ["agi", "luk"]
    assert completed["agi"] == 10.0 and completed["luk"] == 10.0


# ---------------------------------------------------------------------------
# TC-03 无弱点警告（细化_1e §⑥ TC-03）
# ---------------------------------------------------------------------------
def test_tc03_no_weakness_warning_not_blocking() -> None:
    """TC-03：weakness:{} → 警告「该怪无弱点」（Y-9/R3_no_weakness，不拦截）。"""
    for bad_weakness in ({}, None):
        enemy = _base_enemy(weakness=bad_weakness)
        rep = _check([enemy])
        assert not rep.errors
        assert _warns(rep, "R3_no_weakness"), (
            f"weakness={bad_weakness!r} 应有 Y-9 无弱点警告，"
            f"实际 {[(w.kind, dict(w.detail)) for w in rep.warnings]}"
        )


# ---------------------------------------------------------------------------
# TC-04 元素 ID 非法（细化_1e §⑥ TC-04）
# ---------------------------------------------------------------------------
def test_tc04_invalid_element_ref_blocked() -> None:
    """TC-04：weakness.elements 引用未注册元素 → 拦截（R3_element_ref）。

    契约偏差：文档示例 `thunder` 已在 8 元素注册表（core/damage.py DEFAULT_ELEMENTS 同源），
    改用未注册的 `ice` 触发同一引用拦截规则。
    """
    enemy = _base_enemy(weakness={"types": ["斩"], "elements": {"ice": 1.3}})
    rep = _check([enemy])
    errs = _errs(rep, "R3_element_ref")
    assert len(errs) == 1 and errs[0].detail.get("ref") == "ice", (
        f"应拦截未注册元素 ice，实际 {[(e.kind, dict(e.detail)) for e in rep.errors]}"
    )


# ---------------------------------------------------------------------------
# TC-05 PV 约束（细化_1e §⑥ TC-05）
# ---------------------------------------------------------------------------
def test_tc05_pv_negative_blocked_and_range_note() -> None:
    """TC-05：① pv:-1 → 拦截「PV 非负」（R4_pv_negative）；② normal 怪 pv:80 → 提示
    「PV 超出该档常见区间，确认？」（N-3/R4_pv_range，不拦截）。"""
    # ① pv 负值
    rep = _check([_base_enemy(pv=-1)])
    assert _errs(rep, "R4_pv_negative"), f"pv=-1 应拦截，实际 {rep.errors}"
    # ② normal 档 pv 80 超区间
    rep = _check([_base_enemy(pv=80)])
    assert not rep.errors
    notes = _notes(rep, "R4_pv_range")
    assert notes and notes[0].detail["tier"] == "normal", (
        f"normal pv=80 应有区间提示，实际 {[(n.kind, dict(n.detail)) for n in rep.notes]}"
    )
    # 补充：档内值不提示（精英 75 / BOSS 300 均在常见区间内）
    elite = _base_enemy(tier="elite", pv=75)
    assert not _notes(_check([elite]), "R4_pv_range")
    boss = _base_enemy(tier="boss", pv=300)
    assert not _notes(_check([boss]), "R4_pv_range")
    # 档区间常量（PV_RANGES 与细化_1e §② 一致）
    assert PV_RANGES == {"normal": (0.0, 20.0), "elite": (50.0, 100.0), "boss": (200.0, 500.0)}


# ---------------------------------------------------------------------------
# TC-06 行动引用缺失（细化_1e §⑥ TC-06）
# ---------------------------------------------------------------------------
def test_tc06_action_ref_missing_blocked() -> None:
    """TC-06：actions[].action 引用 action.json 不存在的 ID → 拦截（R1_action_ref）。"""
    enemy = _base_enemy(actions=[{"action": "clawX", "probability": 1, "weight": 50}])
    rep = _check([enemy])
    errs = _errs(rep, "R1_action_ref")
    assert len(errs) == 1 and errs[0].detail.get("ref") == "clawX", (
        f"应拦截悬空行动 clawX，实际 {[(e.kind, dict(e.detail)) for e in rep.errors]}"
    )


# ---------------------------------------------------------------------------
# TC-07 概率归一化语义（细化_1e §⑥ TC-07 / S1）
# ---------------------------------------------------------------------------
def test_tc07_probability_normalization_semantics() -> None:
    """TC-07：probability 纯入池开关（0=锚点 / 1=入池 / 其他正值等价 1；数值不参与概率计算）。

    输入 {claw_swipe,p=1,w=50} {rock_roll,p=1,w=30} {hard_body,p=0,w=100}
         + 附加 {tail_sweep,p=2,w=20}（非 0/1 正值）+ {hard_body,p=0.5,w=15}。
    预期：随机池 = 4 条（p>0 全部等价 1），hard_body(p=0) 不入池（只被链/条件/状态机触发）；
    p=2 / p=0.5 等价 1 不拦截（AI 定稿 L51）；归一化 = weight 归一化（数据级口径，引擎侧 M3）。
    """
    enemy = _base_enemy(actions=[
        {"action": "claw_swipe", "probability": 1, "weight": 50},
        {"action": "rock_roll", "probability": 1, "weight": 30},
        {"action": "hard_body", "probability": 0, "weight": 100},
        {"action": "tail_sweep", "probability": 2, "weight": 20},
        {"action": "hard_body", "probability": 0.5, "weight": 15},
    ])
    rep = _check([enemy])
    assert not rep.errors, f"p=2 / p=0.5 应等价 1 不拦截，实际 {rep.errors}"
    assert not _warns(rep, "R10_empty_pool"), "随机池非空，不应有空池黄提示"

    # 数据级口径（S1）：池成员资格 + weight 归一化
    def _pool(actions: list) -> list:
        return [a for a in actions
                if (a.get("probability") or 0) > 0]  # 缺省 0=锚点；其他正值等价 1

    pool = _pool(enemy["actions"])
    assert [a["action"] for a in pool] == ["claw_swipe", "rock_roll", "tail_sweep", "hard_body"]
    weights = [a["weight"] for a in pool]
    assert weights == [50, 30, 20, 15]
    total = sum(weights)
    assert [round(w / total, 2) for w in weights] == [round(50 / 115, 2),
                                                      round(30 / 115, 2),
                                                      round(20 / 115, 2),
                                                      round(15 / 115, 2)]

    # 基础三招子集（文档口径）：池 = 前两招，归一化 50/80、30/80；hard_body(p=0) 不入池
    base = _base_enemy(actions=[
        {"action": "claw_swipe", "probability": 1, "weight": 50},
        {"action": "rock_roll", "probability": 1, "weight": 30},
        {"action": "hard_body", "probability": 0, "weight": 100},
    ])
    base_pool = _pool(base["actions"])
    assert [a["action"] for a in base_pool] == ["claw_swipe", "rock_roll"]
    assert round(base_pool[0]["weight"] / 80, 2) == round(50 / 80, 2)
    assert round(base_pool[1]["weight"] / 80, 2) == round(30 / 80, 2)

    # 空随机池（全锚点）→ Y-11 黄提示不拦截
    empty = _base_enemy(actions=[{"action": "hard_body", "weight": 100}])
    rep = _check([empty])
    assert not rep.errors
    assert _warns(rep, "R10_empty_pool")


# ---------------------------------------------------------------------------
# TC-08 触发类型与别名（细化_1e §⑥ TC-08 / R2 / R11 / R12）
# ---------------------------------------------------------------------------
def _enemy_with_trigger(ttype: str, **trigger_extra: object) -> dict:
    return _base_enemy(special_actions=[
        {"id": "s_t", "action": "claw_swipe", "trigger": {"type": ttype, **trigger_extra}},
    ])


def test_tc08a_trigger_type_invalid_blocked() -> None:
    """TC-08 ①：trigger.type 非 13 类枚举（hp_above）→ 拦截（R2_trigger_type_invalid）。"""
    rep = _check([_enemy_with_trigger("hp_above", value=50)])
    assert _errs(rep, "R2_trigger_type_invalid"), f"hp_above 应拦截，实际 {rep.errors}"


def test_tc08b_after_action_missing_chance_blocked() -> None:
    """TC-08 ②：after_action 缺 chance → 拦截（R11_after_action_chance_required）。"""
    rep = _check([_enemy_with_trigger("after_action", action="claw_swipe")])
    assert _errs(rep, "R11_after_action_chance_required"), (
        f"after_action 缺 chance 应拦截，实际 {rep.errors}"
    )


def test_tc08c_legacy_alias_normalized() -> None:
    """TC-08 ③：type:"broken"（旧枚举别名）→ 通过（R-01）+ 提示归一为权威 pv_broken（R12）。"""
    rep = _check([_enemy_with_trigger("broken", value=30)])
    assert not rep.errors, f"旧别名 broken 应通过，实际 {rep.errors}"
    notes = _notes(rep, "R12_trigger_alias")
    assert notes and notes[0].detail["alias"] == "broken" and notes[0].detail["canonical"] == "pv_broken"
    assert TRIGGER_ALIASES["broken"] == "pv_broken"
    assert TRIGGER_ALIASES["revive"] == "get_up" and TRIGGER_ALIASES["enter_phase"] == "battle_start"


def test_tc08d_authoritative_enum_passes() -> None:
    """TC-08 ④：权威 13 类枚举（player_status / battle_start / x_ 前缀）→ 通过（不拦截）。"""
    for ttype, extra in (
        ("player_status", {}),
        ("battle_start", {"timing": "first_turn"}),
        ("x_custom_ritual", {}),
        ("turn_count", {"value": 3}),
        ("hp_below", {"value": 30}),
    ):
        rep = _check([_enemy_with_trigger(ttype, **extra)])
        assert not rep.errors, f"触发类型 {ttype} 应通过，实际 {rep.errors}"


def test_tc08e_trigger_param_completeness_bonus() -> None:
    """补充 R11：hp_below 缺 value → 拦截；after_action chance 越界 0-100 → 拦截。"""
    rep = _check([_enemy_with_trigger("hp_below")])
    assert _errs(rep, "R11_trigger_value_required"), f"hp_below 缺 value 应拦截，实际 {rep.errors}"
    rep = _check([_enemy_with_trigger("after_action", action="claw_swipe", chance=150)])
    assert _errs(rep, "R11_chance_range"), f"chance=150 应拦截，实际 {rep.errors}"


# ---------------------------------------------------------------------------
# TC-09 掉落扩展域（细化_1e §⑥ TC-09 / R5 / R13）
# ---------------------------------------------------------------------------
def _enemy_with_drop(**drop_fields: object) -> dict:
    return _base_enemy(drops={"battle": [{"item": "potion", **drop_fields}], "special": [], "death": []})


def test_tc09a_drop_chance_out_of_range_blocked() -> None:
    """TC-09 ①：chance:150 → 拦截（R5_chance_range 0-100）。"""
    rep = _check([_enemy_with_drop(chance=150, count=1)])
    assert _errs(rep, "R5_chance_range"), f"chance=150 应拦截，实际 {rep.errors}"


def test_tc09b_drop_count_min_max_blocked() -> None:
    """TC-09 ②：count:[3,1]（min>max）→ 拦截（R13_count_min_max）。"""
    rep = _check([_enemy_with_drop(chance=60, count=[3, 1])])
    assert _errs(rep, "R13_count_min_max"), f"count=[3,1] 应拦截，实际 {rep.errors}"


def test_tc09c_drop_condition_enum_blocked() -> None:
    """TC-09 ③：condition:"random"（非枚举）→ 拦截（R13_condition_enum）。"""
    rep = _check([_enemy_with_drop(chance=60, condition="random", count=1)])
    assert _errs(rep, "R13_condition_enum"), f"condition=random 应拦截，实际 {rep.errors}"


def test_tc09d_drop_extended_valid_and_empty_ref() -> None:
    """补充 R13：合法扩展域（condition pv_broken / after_action:<id> / count [min,max]）通过；
    after_action: 空引用 → 拦截（R13_condition_ref_empty）。"""
    for drop in (
        {"chance": 60, "condition": "pv_broken", "count": 1},
        {"chance": 100, "condition": "after_action:fireball", "count": [1, 3]},
        {"chance": 60, "count": [1, 2]},
    ):
        rep = _check([_enemy_with_drop(**drop)])
        assert not rep.errors, f"合法掉落 {drop} 应通过，实际 {rep.errors}"
    rep = _check([_enemy_with_drop(chance=60, condition="after_action:", count=1)])
    assert _errs(rep, "R13_condition_ref_empty"), f"after_action: 空引用应拦截，实际 {rep.errors}"


# ---------------------------------------------------------------------------
# TC-10 lore 递增（细化_1e §⑥ TC-10 / R6）
# ---------------------------------------------------------------------------
def test_tc10a_lore_unlock_non_increasing_blocked() -> None:
    """TC-10 ①：unlock [10,50,40] 非递增 → 拦截（R6_unlock_increasing）。"""
    enemy = _base_enemy(lore=[
        {"unlock": 10, "desc": "a"}, {"unlock": 50, "desc": "b"}, {"unlock": 40, "desc": "c"},
    ])
    rep = _check([enemy])
    errs = _errs(rep, "R6_unlock_increasing")
    assert len(errs) == 1 and errs[0].detail["value"] == 40, (
        f"lore 非递增应拦截，实际 {[(e.kind, dict(e.detail)) for e in rep.errors]}"
    )


def test_tc10b_lore_unlock_out_of_range_blocked() -> None:
    """TC-10 ②：unlock:0（或 >100）超出 1-100 → 拦截（R6_unlock_range）。"""
    for bad_unlock in (0, 101):
        enemy = _base_enemy(lore=[{"unlock": bad_unlock, "desc": "a"}])
        rep = _check([enemy])
        errs = _errs(rep, "R6_unlock_range")
        assert len(errs) == 1 and errs[0].detail["value"] == bad_unlock, (
            f"unlock={bad_unlock} 应拦截，实际 {rep.errors}"
        )


def test_tc10c_lore_valid_increasing_passes() -> None:
    """补充 R6：unlock [10,50,100] 递增 → 通过。"""
    rep = _check([_base_enemy()])
    assert not _errs(rep, "R6_unlock_increasing") and not _errs(rep, "R6_unlock_range")


# ---------------------------------------------------------------------------
# TC-11 木桩忽略项（细化_1e §⑥ TC-11 / R7）
# ---------------------------------------------------------------------------
def test_tc11a_training_tier_dummy_ignored_fields() -> None:
    """TC-11 ①：tier:"training" 且配 drops/lore/pv:30 → 三条黄提示「木桩忽略掉落/图鉴/PV」
    （Y-10/R7_dummy_ignored，不拦截；运行期 pv 强制 0 归 M3）。"""
    dummy = {
        "id": "t_dummy", "name": "木桩", "tier": "training",
        "stats": {"hp": 50000, "mp": 10, "str": 10, "int": 10, "con": 10,
                  "spr": 10, "foc": 10, "agi": 10, "luk": 10},
        "pv": 30,
        "drops": {"battle": [{"item": "potion", "chance": 60, "count": 1}], "special": [], "death": []},
        "lore": [{"unlock": 10, "desc": "不入图鉴"}],
    }
    assert is_dummy_enemy(dummy)
    rep = _check([dummy])
    assert not rep.errors, f"木桩忽略项不应红拦，实际 {rep.errors}"
    ignored = {w.detail.get("field_name") for w in _warns(rep, "R7_dummy_ignored")}
    assert ignored == {"pv", "drops", "lore"}, f"应三条木桩忽略黄提示，实际 {ignored}"


def test_tc11b_type_dummy_marker_variant() -> None:
    """TC-11 ②：type:"dummy" 标记（tier 保持 normal）同样按木桩处理（§④ 任一命中）。"""
    dummy = {
        "id": "d_dummy", "name": "木桩", "tier": "normal", "type": "dummy",
        "stats": {"hp": 50000, "mp": 10, "str": 10, "int": 10, "con": 10,
                  "spr": 10, "foc": 10, "agi": 10, "luk": 10},
        "pv": 30,
        "drops": {"battle": [{"item": "potion", "chance": 60, "count": 1}], "special": [], "death": []},
        "lore": [{"unlock": 10, "desc": "不入图鉴"}],
    }
    assert is_dummy_enemy(dummy)
    rep = _check([dummy])
    assert not rep.errors
    assert {w.detail.get("field_name") for w in _warns(rep, "R7_dummy_ignored")} == {"pv", "drops", "lore"}


# ---------------------------------------------------------------------------
# TC-12 木桩数值（细化_1e §⑥ TC-12 / R9 / R14）
# ---------------------------------------------------------------------------
def test_tc12a_dummy_negative_stats_and_def_base_blocked() -> None:
    """TC-12 ①：木桩 stats.hp:-5 且 def_base:-1 → 拦截（R9_stats_negative / R14_def_base_negative）。"""
    dummy = {
        "id": "t_dummy", "name": "木桩", "tier": "training",
        "stats": {"hp": -5, "mp": 10, "str": 10, "int": 10, "con": 10,
                  "spr": 10, "foc": 10, "agi": 10, "luk": 10},
        "def_base": -1,
    }
    rep = _check([dummy])
    assert _errs(rep, "R9_stats_negative"), f"hp 负值应拦截，实际 {rep.errors}"
    assert _errs(rep, "R14_def_base_negative"), f"def_base 负值应拦截，实际 {rep.errors}"


def test_tc12b_dummy_no_weakness_exempt() -> None:
    """TC-12 ②：木桩无 weakness → 通过（豁免「每怪 ≥1 弱点」约束 R3，不警告不拦截）。"""
    dummy = {
        "id": "t_dummy", "name": "木桩", "tier": "training",
        "stats": {"hp": 50000, "mp": 10, "str": 10, "int": 10, "con": 10,
                  "spr": 10, "foc": 10, "agi": 10, "luk": 10},
        # 无 weakness
    }
    rep = _check([dummy])
    assert not rep.errors, f"木桩无弱点应通过，实际 {rep.errors}"
    assert not _warns(rep, "R3_no_weakness"), f"木桩豁免 ≥1 弱点约束，不应警告，实际 {rep.warnings}"


# ---------------------------------------------------------------------------
# TC-13 三档模板默认值（细化_1e §⑥ TC-13 / §②）
# ---------------------------------------------------------------------------
def test_tc13a_elite_template_fill_values() -> None:
    """TC-13 ①：精英缺省 stats 仅配 hp → 补全 HP×2.5 / 攻击×1.2 / 防御×1.3 基准。"""
    stats = {"hp": 500}
    completed, pv, filled = apply_enemy_difficulty_template(stats, "elite")
    assert pv == 75.0
    assert filled == ["mp", "str", "int", "con", "spr", "foc", "agi", "luk"]
    assert completed["hp"] == 500.0        # 已配键直读
    assert completed["str"] == 12.0 and completed["int"] == 12.0      # 10×1.2 攻击
    assert completed["con"] == 13.0 and completed["spr"] == 13.0      # 10×1.3 防御
    assert completed["mp"] == 50.0
    assert completed["foc"] == 10.0 and completed["agi"] == 10.0 and completed["luk"] == 10.0

    # 校验器同口径：精英怪 stats 仅配 hp → N-1 模板补全提示
    enemy = _base_enemy(tier="elite", stats={"hp": 500})
    rep = _check([enemy])
    assert not rep.errors
    fills = {n.detail["key"] for n in _notes(rep, "R9_template_fill")}
    assert fills == {"mp", "str", "int", "con", "spr", "foc", "agi", "luk"}


def test_tc13b_boss_and_normal_pv_defaults() -> None:
    """TC-13 ②③：boss 缺省 pv → 默认 300；normal 缺省 pv → 默认 10（N-2/R4_pv_default）。"""
    boss = _base_enemy(tier="boss")
    del boss["pv"]
    rep = _check([boss])
    assert not rep.errors
    notes = _notes(rep, "R4_pv_default")
    assert notes and notes[0].detail["pv_default"] == 300 and notes[0].detail["tier"] == "boss"

    normal = _base_enemy()
    del normal["pv"]
    rep = _check([normal])
    assert not rep.errors
    notes = _notes(rep, "R4_pv_default")
    assert notes and notes[0].detail["pv_default"] == 10 and notes[0].detail["tier"] == "normal"


def test_tc13c_difficulty_template_constants() -> None:
    """三档模板常量与细化_1e §② 一致（PV 10/75/300；HP/攻/防乘区）。"""
    assert DIFFICULTY_TEMPLATES["normal"]["pv"] == 10
    assert DIFFICULTY_TEMPLATES["elite"]["pv"] == 75
    assert DIFFICULTY_TEMPLATES["boss"]["pv"] == 300
    assert DIFFICULTY_TEMPLATES["elite"]["hp_mult"] == 2.5
    assert DIFFICULTY_TEMPLATES["elite"]["atk_mult"] == 1.2
    assert DIFFICULTY_TEMPLATES["elite"]["def_mult"] == 1.3
    assert DIFFICULTY_TEMPLATES["boss"]["hp_mult"] == 10.0
    assert DIFFICULTY_TEMPLATES["boss"]["atk_mult"] == 1.3
    assert DIFFICULTY_TEMPLATES["boss"]["def_mult"] == 1.5
    assert DIFFICULTY_TEMPLATES["normal"]["hp_mult"] == 1.0


# ---------------------------------------------------------------------------
# TC-14 换区/开场技行为验收（运行期，依赖 M3）
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason="运行期行为：残血换区 PV 恢复一半（向下取整）+ 换区后第一回合 battle_start 开场技，"
           "依赖战斗引擎与地图挂接（M3 里程碑），schema 层不验证；M3 落地后补 e2e 用例。"
)
def test_tc14_zone_change_and_opener_runtime() -> None:
    """TC-14（M3）：残血换区（/进入 通道）后续战 → 血量保持残血、PV 恢复一半（向下取整）、
    换区后第一回合触发开场技（battle_start）；玩家离开副本 → 下次满状态重打。"""
    raise AssertionError("M3 运行期用例未落地（见 skip reason）")


# ---------------------------------------------------------------------------
# 配套回归：badref 八段坏例（交付③）与 action.json AI 字段（交付①）
# ---------------------------------------------------------------------------
def test_badref_8seg_red_blocks() -> None:
    """badref 包八段坏例：整包红拦，覆盖引用/枚举/参数三类拦截（R2/R6/R1/R15/R5/R3/R8/R13）。"""
    with pytest.raises(PackLoadError) as ei:
        build_pack(BADREF_DIR)
    rules = {e.detail.get("rule") for e in ei.value.errors}
    expected = {
        # bad_trigger：触发类型枚举 + lore 递增
        "R2_trigger_type_invalid", "R6_unlock_increasing",
        # bad_ref：行动/连招/掉落引用 + 元素引用
        "R1_action_ref", "R15_chain_ref_missing", "R5_item_ref", "R3_element_ref",
        # bad_enum：tier 枚举 + 掉落扩展域
        "R8_tier_enum", "R5_chance_range", "R13_count_min_max",
    }
    assert expected <= rules, f"badref 八段坏例缺拦截规则：{expected - rules}"
    # 既有坏引用断言不受影响（细化_3e#TC-05：items ghost_effect）
    assert any(e.kind == "R-4" and e.detail.get("ref") == "ghost_effect"
               for e in ei.value.errors)


def test_legal_action_library_ai_fields() -> None:
    """legal/action.json 行动库：AI 字段表面（weight/probability/intent/cooldown/hungry/tags/
    condition/armor/interrupt/charge_*/preview）经 ActionDef 可读（交付①）。"""
    pack, _ = build_pack(LEGAL_DIR)
    actions = pack.registry
    claw = actions.resolve("claw_swipe", "action")
    assert claw is not None
    assert claw.weight == 50.0
    assert claw.probability == 0.5          # 等价正值（S1：写其他正值等价 1 入池）
    assert claw.intent == "伤害"
    assert claw.cooldown == 0.0 and claw.hungry == 0.0
    assert claw.tags == ("物理", "近战")

    breath = actions.resolve("doomsday_breath", "action")
    assert breath.intent == "蓄力"
    charge = breath.charge_fields()
    assert charge.get("charge_turns") == 2 and charge.get("charge_armor") is True
    assert breath.interrupt is False
    assert breath.preview == {"level": 2, "category": "蓄力"}
    assert breath.armor is None or breath.armor is True  # 蓄力霸体字段可读
    # 行动引用均指向合法 effects（R-4 不红拦）
    assert not pack.report.errors
