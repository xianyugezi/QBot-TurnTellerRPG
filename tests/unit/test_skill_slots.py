"""M13 技能库·批3·路3A：技能位装配单元测试（tests/unit/test_skill_slots.py）。

文件名：test_skill_slots.py
创建时间：2026-09-02
作者：Hermes 子agent-3A（M13 技能库实现组批3路3A：并发同仓，仅新建本文件 +
  qbot_rpg/core/skill_slots.py；不改动兄弟路文件——路3B 独占 test_demo
  skills.json 扩展、路3C 独占战斗接线）

依据：docs/细化/细化_6a_技能库契约.md：
  - §1.4 四类时机（basic 固定第 1 位 / active 可排序 / passive·trigger 装配槽
    不占行动位）；
  - §1.5 技能位与装配（basic 固定第 1 位 + active 拖拽排序 + passive/trigger
    装配槽 + 装配结果落玩家存档 1g1c/1g3 + 形态技能 [L88]）；
  - §4.3 绑定规则（装配过滤：job_restrict 自动过滤 + 通用技能全职业可见）；
  - TC-02（type 缺省 active，basic 必须显式）；TC-04（四类时机门禁与技能位）；
  - §7 存档影响（装配结果落玩家存档）。
测试目标：qbot_rpg.core.skill_slots.{assemble_slots, save_slots_to_state,
  load_slots_from_state, apply_job_form, job_visible, skill_type, skill_id,
  skill_job_restrict, skill_job_form, 常量}。

覆盖矩阵：
  A 装配规则（TC-04）：basic 固定第 1 位 / basic 恰 1 占位兜底（0 个）/ basic
    多选命中当前职业优先 / active 可排序（active_order）/ active 缺省排序 /
    passive 槽 / trigger 槽 / 槽序（basic→active→passive→trigger）/ 不占行动位
    （active_order 只含 active）
  B 装配过滤（§4.3-3）：job_restrict 非当前职业排除 / 通用技能全职业可见 /
    缺 job_id 通用口径放行
  C 缺省兜底：type 缺省 active（TC-02）/ 无 id 跳过 / 未知 type 跳过 /
    空技能序列 → 空快照骨架
  D 存档 round-trip（1g1c/1g3）：save → load 等值 / 无存档缺省空快照 /
    persistent_state 缺失惰性创建挂回 / 存档畸形（非 dict / 键畸形）归一 /
    幂等覆盖
  E job_form 接口（F17/[L88]/TC-06）：apply_job_form 占位原样返回（实现归
    批7/批15）
  F raw 条目适配（P-1）：raw dict 条目可装配（G0 注入形态）

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（docstring 不写
睡眠/定时器字样）；不引入随机；只写本文件。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple, cast

from qbot_rpg.core.skill_slots import (
    SLOT_ACTIVE,
    SLOT_BASIC,
    SLOT_PASSIVE,
    SLOT_STATE_KEY,
    SLOT_TRIGGER,
    SlotKind,
    apply_job_form,
    assemble_slots,
    job_visible,
    load_slots_from_state,
    save_slots_to_state,
    skill_id,
    skill_job_form,
    skill_job_restrict,
    skill_type,
)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _skill(
    sid: str,
    stype: str = "active",
    job_restrict: Optional[List[str]] = None,
    job_form: Optional[str] = None,
) -> Dict[str, Any]:
    """raw dict 技能条目（批2 skills.json 四类示例形态：basic_attack /
    power_strike / stone_guard / flame_burst）。"""
    entry: Dict[str, Any] = {"id": sid, "name": sid, "type": stype}
    if job_restrict is not None:
        entry["job_restrict"] = job_restrict
    if job_form is not None:
        entry["job_form"] = job_form
    return entry


class _FakeSkill:
    """SlotKind 协议对象（模拟 SkillDef 形态：属性访问器）。"""

    def __init__(
        self,
        sid: str,
        stype: str = "active",
        job_restrict: Optional[Tuple[str, ...]] = None,
        job_form: Optional[str] = None,
    ) -> None:
        self._id = sid
        self._type = stype
        self._restrict = job_restrict or ()
        self._form = job_form

    @property
    def id(self) -> str:  # noqa: A003
        return self._id

    @property
    def type(self) -> str:
        return self._type

    @property
    def job_restrict(self) -> Tuple[str, ...]:
        return self._restrict

    @property
    def job_form(self) -> Optional[str]:
        return self._form


def _four_kinds() -> List[Dict[str, Any]]:
    """四类时机各 1 条（TC-04 前置：basic_attack + power_strike + stone_guard
    + flame_burst，对齐 content/test_demo/skills.json 示例 id）。"""
    return [
        _skill("basic_attack", "basic"),
        _skill("power_strike", "active"),
        _skill("stone_guard", "passive"),
        _skill("flame_burst", "trigger"),
    ]


def _snapshot_of(snapshot: Mapping[str, Any], key: str) -> List[Any]:
    v = snapshot.get(key)
    return list(v) if isinstance(v, list) else []


def _slot_ids(snapshot: Mapping[str, Any]) -> List[Optional[str]]:
    return [cast(Any, s).get("skill_id") for s in _snapshot_of(snapshot, "slots")]


def _player(ps: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if ps is not None:
        out["persistent_state"] = ps
    return out


# ===========================================================================
# A 装配规则（TC-04）
# ===========================================================================
def test_basic_fixed_first_slot() -> None:
    """basic 固定第 1 位（slots[0] = basic 槽，且仅 1 个 basic 槽；TC-04）。"""
    snap = assemble_slots(_four_kinds(), {})
    slots = _snapshot_of(snap, "slots")
    assert slots[0] == {"slot": SLOT_BASIC, "skill_id": "basic_attack"}
    assert [s.get("slot") for s in slots].count(SLOT_BASIC) == 1


def test_basic_zero_fallback_placeholder() -> None:
    """0 个 basic → basic 槽 skill_id=None 占位（引擎不重复拦截 V-7；P-3）。"""
    skills = [_skill("power_strike", "active"), _skill("stone_guard", "passive")]
    snap = assemble_slots(skills, {})
    slots = _snapshot_of(snap, "slots")
    assert slots[0] == {"slot": SLOT_BASIC, "skill_id": None}


def test_basic_multiple_prefers_job_restricted_hit() -> None:
    """多个 basic → job_restrict 命中当前职业者优先（仍多取库序首个，P-3）。"""
    skills = [
        _skill("basic_generic", "basic"),
        _skill("basic_mage", "basic", job_restrict=["mage"]),
    ]
    snap = assemble_slots(skills, {"job_id": "mage"})
    assert _slot_ids(snap)[0] == "basic_mage"
    # 非 mage 职业 → 通用 basic 胜出
    snap2 = assemble_slots(skills, {"job_id": "warrior"})
    assert _slot_ids(snap2)[0] == "basic_generic"


def test_active_order_respected() -> None:
    """active 可排序：active_order 显式给出玩家顺序（slots 随序，TC-04）。"""
    skills = [
        _skill("basic_attack", "basic"),
        _skill("skill_b", "active"),
        _skill("skill_a", "active"),
    ]
    snap = assemble_slots(skills, {"active_order": ["skill_b", "skill_a"]})
    assert snap["active_order"] == ["skill_b", "skill_a"]
    assert _slot_ids(snap) == ["basic_attack", "skill_b", "skill_a"]


def test_active_order_missing_default_sort() -> None:
    """无 active_order → 确定性缺省排序（职业命中者优先 + 库序，P-4）。"""
    skills = [
        _skill("basic_attack", "basic"),
        _skill("skill_restricted", "active", job_restrict=["mage"]),
        _skill("skill_generic", "active"),
    ]
    snap = assemble_slots(skills, {"job_id": "mage"})
    assert snap["active_order"] == ["skill_restricted", "skill_generic"]
    # 非 mage 职业 → 职业限定技能被过滤，只剩通用
    snap2 = assemble_slots(skills, {"job_id": "warrior"})
    assert snap2["active_order"] == ["skill_generic"]


def test_active_order_stale_ids_dropped() -> None:
    """active_order 含已不存在的 id → 丢弃（不装配幽灵技能）；新增技能按缺省
    排序追加（确定性，不丢弃）。"""
    skills = [
        _skill("basic_attack", "basic"),
        _skill("skill_a", "active"),
        _skill("skill_new", "active"),
    ]
    snap = assemble_slots(skills, {"active_order": ["skill_a", "ghost_removed"]})
    assert snap["active_order"] == ["skill_a", "skill_new"]
    assert "ghost_removed" not in snap["active_order"]


def test_passive_slot_collected() -> None:
    """passive 槽：装配槽收集（不占行动位，TC-04）。"""
    skills = [
        _skill("basic_attack", "basic"),
        _skill("stone_guard", "passive"),
        _skill("power_strike", "active"),
    ]
    snap = assemble_slots(skills, {})
    assert snap["passive"] == [{"slot": SLOT_PASSIVE, "skill_id": "stone_guard"}]
    # passive 不进 active_order（不占行动位）
    assert snap["active_order"] == ["power_strike"]


def test_trigger_slot_collected() -> None:
    """trigger 槽：装配槽收集（不占行动位，TC-04）。"""
    skills = [
        _skill("basic_attack", "basic"),
        _skill("flame_burst", "trigger"),
        _skill("power_strike", "active"),
    ]
    snap = assemble_slots(skills, {})
    assert snap["trigger"] == [{"slot": SLOT_TRIGGER, "skill_id": "flame_burst"}]
    assert snap["active_order"] == ["power_strike"]


def test_slots_full_order_basic_active_passive_trigger() -> None:
    """slots 全量顺序：basic 固定第 1 位 → active → passive → trigger（§1.5）。"""
    skills = [
        _skill("basic_attack", "basic"),
        _skill("flame_burst", "trigger"),
        _skill("power_strike", "active"),
        _skill("stone_guard", "passive"),
    ]
    snap = assemble_slots(skills, {})
    assert _slot_ids(snap) == [
        "basic_attack", "power_strike", "stone_guard", "flame_burst",
    ]
    assert [cast(Any, s).get("slot") for s in _snapshot_of(snap, "slots")] == [
        SLOT_BASIC, SLOT_ACTIVE, SLOT_PASSIVE, SLOT_TRIGGER,
    ]


# ===========================================================================
# B 装配过滤（§4.3-3）
# ===========================================================================
def test_job_restrict_filters_out_other_job() -> None:
    """job_restrict 非当前职业 → 不装配（§4.3-3 职业限制自动过滤）。"""
    skills = [
        _skill("basic_attack", "basic"),
        _skill("mage_only", "active", job_restrict=["mage"]),
    ]
    snap = assemble_slots(skills, {"job_id": "warrior"})
    assert "mage_only" not in snap["active_order"]


def test_job_restrict_empty_generic_all_jobs() -> None:
    """job_restrict 空 = 通用技能全职业可见（§4.3-3）。"""
    skills = [
        _skill("basic_attack", "basic"),
        _skill("generic_skill", "active"),
    ]
    for job in ("mage", "warrior", "thief"):
        snap = assemble_slots(skills, {"job_id": job})
        assert "generic_skill" in snap["active_order"]


def test_job_visible_helper() -> None:
    """job_visible：限制命中 / 通用放行 / 缺 job_id 通用口径放行（P-5）。"""
    restricted = _FakeSkill("s1", job_restrict=("mage",))
    generic = _FakeSkill("s2")
    assert job_visible(restricted, "mage") is True
    assert job_visible(restricted, "warrior") is False
    assert job_visible(generic, "warrior") is True
    assert job_visible(restricted, None) is True  # 缺 job_id 不误伤通用口径


# ===========================================================================
# C 缺省兜底（TC-02）
# ===========================================================================
def test_type_default_active() -> None:
    """type 缺省 active（TC-02 裁决：仅核心字段按 active 处理，basic 必须显式）。"""
    assert skill_type({"id": "x", "name": "x"}) == "active"
    snap = assemble_slots([{"id": "mystery", "name": "神秘技能"}], {})
    assert snap["active_order"] == ["mystery"]
    assert _slot_ids(snap)[0] == {"slot": "basic", "skill_id": None}["skill_id"]


def test_skill_type_helpers() -> None:
    """skill_type / skill_id / skill_job_restrict / skill_job_form 防御读取。"""
    assert skill_type(_skill("a", "basic")) == "basic"
    assert skill_type({"id": "b", "type": "weird"}) == "weird"  # 显式值透传（枚举校验归 V-13）
    assert skill_type({"id": "c", "type": 7}) == "active"  # 非字符串 → 缺省 active
    assert skill_id({"id": "ok"}) == "ok"
    assert skill_id({"id": 123}) is None
    assert skill_job_restrict({"job_restrict": ["mage", 7]}) == ("mage",)
    assert skill_job_restrict({"job_restrict": "mage"}) == ()
    assert skill_job_form({"job_form": "flame_form"}) == "flame_form"
    assert skill_job_form({"job_form": 7}) is None


def test_entry_without_id_skipped() -> None:
    """无 id 条目 → 跳过（不进任何槽，确定性兜底）。"""
    skills = [
        {"name": "no_id_skill", "type": "active"},
        _skill("basic_attack", "basic"),
    ]
    snap = assemble_slots(skills, {})
    assert snap["active_order"] == []


def test_unknown_type_skipped() -> None:
    """未知 type → 防御性跳过（枚举校验归 V-13 校验器，引擎不拦截）。"""
    skills = [
        _skill("basic_attack", "basic"),
        _skill("mystery", "ultra"),
    ]
    snap = assemble_slots(skills, {})
    assert snap["active_order"] == []
    assert _slot_ids(snap) == ["basic_attack"]


def test_empty_skills_empty_snapshot() -> None:
    """空技能序列 → 空快照骨架（basic 占位 None + 空槽，确定性兜底）。"""
    snap = assemble_slots([], {})
    assert _slot_ids(snap) == [None]
    assert snap["active_order"] == []
    assert snap["passive"] == []
    assert snap["trigger"] == []
    assert snap["version"] == 1


# ===========================================================================
# D 存档 round-trip（1g1c/1g3 承接，§7）
# ===========================================================================
def test_save_load_roundtrip() -> None:
    """save → load 等值 round-trip（装配结果落玩家存档，§7）。"""
    player = _player()
    snap = assemble_slots(_four_kinds(), {})
    save_slots_to_state(player, snap)
    loaded = load_slots_from_state(player)
    assert loaded == snap
    assert player["persistent_state"][SLOT_STATE_KEY] == snap


def test_load_missing_state_empty_snapshot() -> None:
    """无存档 → 空快照骨架（非 None，确定性兜底）。"""
    player: Dict[str, Any] = {}
    snap = load_slots_from_state(player)
    assert snap["slots"] == []
    assert snap["active_order"] == []
    assert snap["passive"] == []
    assert snap["trigger"] == []
    assert snap["version"] == 1


def test_save_creates_persistent_state_lazily() -> None:
    """persistent_state 缺失 → 惰性创建并挂回（对齐 _ps_init 模式）。"""
    player: Dict[str, Any] = {}
    snap = assemble_slots(_four_kinds(), {})
    node = save_slots_to_state(player, snap)
    assert "persistent_state" in player
    assert player["persistent_state"][SLOT_STATE_KEY] is node


def test_load_malformed_state_normalized() -> None:
    """存档畸形（非 dict / 键畸形）→ 防御性归一空骨架（不抛异常）。"""
    player_bad = {"persistent_state": {SLOT_STATE_KEY: "oops"}}
    assert load_slots_from_state(player_bad)["slots"] == []
    player_bad2 = {"persistent_state": {SLOT_STATE_KEY: {"slots": "oops"}}}
    assert load_slots_from_state(player_bad2)["slots"] == []
    # 键畸形但结构可救 → 部分归一
    player_mixed = {
        "persistent_state": {
            SLOT_STATE_KEY: {
                "slots": [{"slot": "active", "skill_id": "a"}, {"slot": "nope", "skill_id": "b"}],
                "active_order": ["a", 7],
                "version": "x",
            }
        }
    }
    loaded = load_slots_from_state(player_mixed)
    assert loaded["slots"] == [{"slot": "active", "skill_id": "a"}]
    assert loaded["active_order"] == ["a"]
    assert loaded["version"] == 1


def test_save_overwrites_idempotent() -> None:
    """重复保存覆盖旧快照（幂等）。"""
    player = _player({"skill_slots": {"old": True}})
    snap = assemble_slots(_four_kinds(), {})
    save_slots_to_state(player, snap)
    assert player["persistent_state"][SLOT_STATE_KEY] == snap


def test_snapshot_json_serializable() -> None:
    """装配快照可 JSON 序列化（存档/快照 dict 口径，P-2）。"""
    import json

    snap = assemble_slots(_four_kinds(), {"active_order": ["power_strike"]})
    text = json.dumps(snap, ensure_ascii=False)
    assert json.loads(text) == snap


# ===========================================================================
# E job_form 接口（F17 / [L88] / TC-06 —— 占位，实现归批7/批15）
# ===========================================================================
def test_apply_job_form_placeholder_returns_snapshot() -> None:
    """apply_job_form 占位实现：原样返回快照副本（不改变装配结果，P-7）。"""
    snap = assemble_slots(_four_kinds(), {})
    out = apply_job_form(snap, _four_kinds(), form="flame_form")
    assert out == snap
    assert out is not snap  # 副本（调用方修改不污染原快照）


# ===========================================================================
# F raw 条目适配（P-1：G0 注入形态）
# ===========================================================================
def test_protocol_object_and_raw_mixed() -> None:
    """SlotKind 协议对象与 raw dict 混装可装配（G0 注入形态，P-1）。"""
    fakes: List[SlotKind] = [
        _FakeSkill("basic_attack", "basic"),
        _FakeSkill("stone_guard", "passive"),
    ]
    skills: List[Any] = [fakes[0], _skill("power_strike", "active"), fakes[1]]
    snap = assemble_slots(skills, {})
    assert _slot_ids(snap) == ["basic_attack", "power_strike", "stone_guard"]


def test_real_skilldef_from_entry() -> None:
    """真实 SkillDef 可装配（与 content.skill_models 集成验证；G0 允许
    core → content.models，断言 SlotKind 协议由 SkillDef 满足）。"""
    from qbot_rpg.content.models import BaseDef
    from qbot_rpg.content.skill_models import SkillDef

    entry = {
        "id": "basic_attack", "name": "普攻", "type": "basic", "kind": "damage",
        "power": 100, "attack_type": "none", "element": None, "effects": [],
        "mp_cost": 0, "cooldown": 0, "tag": "none", "armor": False,
        "interrupt": False, "chain_refs": [], "consume_marks": {},
        "job_restrict": [], "job_form": None, "level": None, "hits": 1,
        "trigger_limit": {"per_round": 10, "per_battle": 99},
        "desc": "基础普攻（演示）", "hit_mod": 1.0, "crit_mod": 1.0,
        "block_mode": "auto",
    }
    sd = cast(SkillDef, SkillDef.from_entry(entry))
    assert isinstance(sd, BaseDef)
    snap = assemble_slots([sd], {})
    assert _slot_ids(snap)[0] == "basic_attack"
    # 装配层只消费协议（id/type/job_restrict/job_form），SkillDef 全满足
    assert sd.type == "basic"
    assert sd.job_restrict == ()
