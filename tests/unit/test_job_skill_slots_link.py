"""M13 技能库·批14·路14C：转职×技能装配联动单元测试
（tests/unit/test_job_skill_slots_link.py）。

文件名：test_job_skill_slots_link.py
创建时间：2026-09-02
作者：Hermes 子agent-14C（M13 装配接线组批14路14C：并发同仓，仅新建本文件 +
  qbot_rpg/core/job_slots.py；不碰兄弟路文件——14A 独占 /转职 指令、14B 独占
  战斗链路。转职入口用纯函数/直接调 assemble_slots 消费已落盘接口，零
  NoneBot、零 content import）

依据：docs/细化/细化_6a_技能库契约.md：
  - §1.4 四类时机（basic 固定第 1 位 / active 可排序 / passive·trigger
    装配槽不占行动位）；
  - §1.5 技能位与装配（装配结果落玩家存档 1g1c/1g3）；
  - §4.3 绑定规则（装配过滤：job_restrict 自动过滤 + 通用技能全职业可见；
    #4 触发/被动装配：passive/trigger 装配槽内容同样受职业过滤，职业变换
    时按新职业重算装配有效集——本路转职联动落地）；
  - §7 存档影响（装配结果落玩家存档）。
依赖（已落盘）：qbot_rpg/core/skill_slots.py（assemble_slots /
  save_slots_to_state / load_slots_from_state / SLOT_STATE_KEY）。

测试目标：qbot_rpg.core.job_slots.{snapshot_job_context,
  rearrange_job_slots, save_rearranged_slots, load_job_slots_state,
  REARRANGE_JOB_KEY}。

覆盖矩阵：
  A 转职前装配（A 职业技能组）：A 职业视角装配快照（basic 固定第 1 位 /
    active 排序 / passive/trigger 槽）
  B 转职重排（→ B 职业技能组）：重排后 basic/active/passive/trigger 全按
    B 职业视角；A 专属技能转职后不可见（job_restrict 过滤）
  C 被动/触发槽重装配：A 专属 passive/trigger 转职后不装配；B 专属被动/
    触发进入新槽；通用被动/触发保留
  D active 顺序策略：旧顺序 ∩ 新可见集保序；旧顺序全不可用 → 缺省排序；
    新职业新增技能追加；玩家手动顺序优先于缺省排序
  E 存档迁移 round-trip：save 后 skill_slots 段更新 + job_slots 段记录；
    load_job_slots_state 等值；幂等覆盖；persistent_state 缺失惰性创建；
    畸形段防御归一；快照 JSON 可序列化
  F 上下文快照：snapshot_job_context 打包旧装配 + 旧 job_id + 技能表；
    只读不写 player；at 缺省不写键

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（docstring 不写
睡眠/定时器字样）；不引入随机；只写本文件。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from qbot_rpg.core.job_slots import (
    REARRANGE_JOB_KEY,
    load_job_slots_state,
    rearrange_job_slots,
    save_rearranged_slots,
    snapshot_job_context,
)
from qbot_rpg.core.skill_slots import (
    SLOT_BASIC,
    SLOT_PASSIVE,
    SLOT_STATE_KEY,
    SLOT_TRIGGER,
    assemble_slots,
)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _skill(
    sid: str,
    stype: str = "active",
    job_restrict: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """raw dict 技能条目（对齐批2 test_demo skills.json 四类示例形态）。"""
    entry: Dict[str, Any] = {"id": sid, "name": sid, "type": stype}
    if job_restrict is not None:
        entry["job_restrict"] = job_restrict
    return entry


def _lib_a() -> List[Dict[str, Any]]:
    """A 职业技能组整库（通用 + A 专属 + A 专属被动/触发）。"""
    return [
        _skill("basic_generic", "basic"),
        _skill("skill_common", "active"),
        _skill("skill_a_only", "active", job_restrict=["job_a"]),
        _skill("passive_a_only", "passive", job_restrict=["job_a"]),
        _skill("trigger_a_only", "trigger", job_restrict=["job_a"]),
        _skill("passive_common", "passive"),
    ]


def _lib_b() -> List[Dict[str, Any]]:
    """B 职业技能组整库（通用 + B 专属 + B 专属被动/触发）。"""
    return [
        _skill("basic_b_only", "basic", job_restrict=["job_b"]),
        _skill("skill_b_only", "active", job_restrict=["job_b"]),
        _skill("passive_b_only", "passive", job_restrict=["job_b"]),
        _skill("trigger_b_only", "trigger", job_restrict=["job_b"]),
    ]


def _lib_mixed() -> List[Dict[str, Any]]:
    """A+B 混合整库（转职后 A 专属应全部不可见）。"""
    return [
        _skill("basic_generic", "basic"),
        _skill("skill_common", "active"),
        _skill("skill_a_only", "active", job_restrict=["job_a"]),
        _skill("skill_b_only", "active", job_restrict=["job_b"]),
        _skill("passive_a_only", "passive", job_restrict=["job_a"]),
        _skill("passive_b_only", "passive", job_restrict=["job_b"]),
        _skill("trigger_a_only", "trigger", job_restrict=["job_a"]),
        _skill("trigger_b_only", "trigger", job_restrict=["job_b"]),
        _skill("passive_common", "passive"),
        _skill("trigger_common", "trigger"),
    ]


def _player(ps: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if ps is not None:
        out["persistent_state"] = ps
    return out


def _slot_ids(snapshot: Mapping[str, Any]) -> List[Any]:
    slots = snapshot.get("slots")
    return [s.get("skill_id") for s in slots] if isinstance(slots, list) else []


def _slot_kinds(snapshot: Mapping[str, Any]) -> List[Any]:
    slots = snapshot.get("slots")
    return [s.get("slot") for s in slots] if isinstance(slots, list) else []


# ===========================================================================
# A 转职前装配（A 职业技能组，职业视角 = assemble_slots）
# ===========================================================================
def test_pre_change_assemble_job_a_view() -> None:
    """转职前：A 职业视角装配 A 职业技能组（basic 固定第 1 位 + active 排序
    + passive/trigger 槽；§1.4/§1.5/TC-04）。"""
    snap = assemble_slots(_lib_a(), {"job_id": "job_a"})
    assert _slot_ids(snap)[0] == "basic_generic"
    # 缺省排序（P-4）：职业限定且命中当前职业者优先 → A 专属排前
    assert snap["active_order"] == ["skill_a_only", "skill_common"]
    assert snap["passive"] == [
        {"slot": SLOT_PASSIVE, "skill_id": "passive_a_only"},
        {"slot": SLOT_PASSIVE, "skill_id": "passive_common"},
    ]
    assert snap["trigger"] == [
        {"slot": SLOT_TRIGGER, "skill_id": "trigger_a_only"}
    ]


def test_pre_change_job_a_excludes_b_skills() -> None:
    """转职前：A 职业视角下 B 专属技能全部不可见（job_restrict 过滤，
    §4.3-3）。"""
    snap = assemble_slots(_lib_mixed(), {"job_id": "job_a"})
    assert "skill_b_only" not in snap["active_order"]
    assert all(s.get("skill_id") != "passive_b_only" for s in snap["passive"])
    assert all(s.get("skill_id") != "trigger_b_only" for s in snap["trigger"])


# ===========================================================================
# B 转职重排（A 职业技能组 → B 职业技能组）
# ===========================================================================
def test_rearrange_after_job_change_assembles_new_job_group() -> None:
    """转职后：以 B 职业视角重排（basic 固定第 1 位为 B 专属 basic +
    B 专属 active + 通用 active 保留；§4.3-4 按新职业重算装配有效集）。"""
    snap = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    assert snap["active_order"] == ["skill_b_only", "skill_common"]
    assert _slot_ids(snap)[0] == "basic_generic"
    assert _slot_kinds(snap)[0] == SLOT_BASIC
    # basic 恰 1 位（固定第 1 位；TC-04）
    assert _slot_kinds(snap).count(SLOT_BASIC) == 1


def test_rearrange_filters_out_old_job_skills() -> None:
    """转职后：A 专属技能（active/passive/trigger）全部不可见（job_restrict
    过滤生效，§4.3-3/#4）。"""
    snap = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    assert "skill_a_only" not in snap["active_order"]
    assert all(s.get("skill_id") != "passive_a_only" for s in snap["passive"])
    assert all(s.get("skill_id") != "trigger_a_only" for s in snap["trigger"])


def test_rearrange_snapshot_matches_direct_assemble() -> None:
    """重排产物与直接以新职业调 assemble_slots 完全一致（纯函数确定性：
    同刻同参必同值）。"""
    via_rearrange = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    direct = assemble_slots(_lib_mixed(), {"job_id": "job_b"})
    assert via_rearrange == direct


def test_rearrange_basic_missing_placeholder() -> None:
    """新职业无可见 basic → basic 槽 skill_id=None 占位（引擎不重复拦截
    V-7；对齐 skill_slots P-3）。"""
    # 库中 basic 全为 A 专属 → B 职业视角 0 个可见 basic
    skills = [
        _skill("basic_a_only", "basic", job_restrict=["job_a"]),
        _skill("skill_b_only", "active", job_restrict=["job_b"]),
    ]
    snap = rearrange_job_slots({"skills": skills}, "job_b")
    assert _slot_ids(snap)[0] is None


# ===========================================================================
# C 被动/触发槽重装配（§4.3-4）
# ===========================================================================
def test_passive_trigger_reassembled_by_new_job() -> None:
    """转职后被动/触发槽按新职业重装配：A 专属被动/触发不装配，B 专属进入
    新槽，通用被动/触发保留（§4.3-4）。"""
    snap = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    assert snap["passive"] == [
        {"slot": SLOT_PASSIVE, "skill_id": "passive_b_only"},
        {"slot": SLOT_PASSIVE, "skill_id": "passive_common"},
    ]
    assert snap["trigger"] == [
        {"slot": SLOT_TRIGGER, "skill_id": "trigger_b_only"},
        {"slot": SLOT_TRIGGER, "skill_id": "trigger_common"},
    ]
    # 被动/触发不占行动位（不进 active_order）
    assert snap["active_order"] == ["skill_b_only", "skill_common"]


def test_passive_trigger_keep_generic_across_change() -> None:
    """通用（job_restrict 空）被动/触发转职前后均保留（全职业可见，
    §4.3-3）。"""
    skills = [
        _skill("basic_generic", "basic"),
        _skill("passive_common", "passive"),
        _skill("trigger_common", "trigger"),
    ]
    before = assemble_slots(skills, {"job_id": "job_a"})
    after = rearrange_job_slots({"skills": skills}, "job_b")
    assert before["passive"] == after["passive"] == [
        {"slot": SLOT_PASSIVE, "skill_id": "passive_common"}
    ]
    assert before["trigger"] == after["trigger"] == [
        {"slot": SLOT_TRIGGER, "skill_id": "trigger_common"}
    ]


# ===========================================================================
# D active 顺序策略
# ===========================================================================
def test_rearrange_keeps_old_order_intersection() -> None:
    """重排保留旧 active_order ∩ 新可见集的原相对顺序（P-2：手动顺序尽量
    保留），新职业新增技能按缺省规则追加。"""
    # 旧装配：玩家手动排序 [skill_common, skill_a_only]
    player_ctx: Dict[str, Any] = {
        "skills": _lib_mixed(),
        "active_order": ["skill_common", "skill_a_only"],
    }
    snap = rearrange_job_slots(player_ctx, "job_b")
    # skill_common 保留在首位（旧顺序中仍可见）；skill_b_only 追加在后
    assert snap["active_order"] == ["skill_common", "skill_b_only"]


def test_rearrange_old_order_unusable_falls_back() -> None:
    """旧 active_order 全为 A 专属（新职业全不可见）→ 新职业缺省排序兜底
    （P-2 确定性）。"""
    skills = [
        _skill("basic_generic", "basic"),
        _skill("skill_a_only", "active", job_restrict=["job_a"]),
        _skill("skill_b_only", "active", job_restrict=["job_b"]),
    ]
    player_ctx: Dict[str, Any] = {
        "skills": skills,
        "active_order": ["skill_a_only"],
    }
    snap = rearrange_job_slots(player_ctx, "job_b")
    assert snap["active_order"] == ["skill_b_only"]


def test_rearrange_no_saved_order_default_sort() -> None:
    """无旧排序（首次转职）→ 新职业缺省排序（职业命中者优先 + 库序，
    P-4 同构）。"""
    snap = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    assert snap["active_order"] == ["skill_b_only", "skill_common"]


# ===========================================================================
# E 存档迁移 round-trip（§7 / §4.3-4 存档承接）
# ===========================================================================
def test_save_rearranged_updates_slot_state_and_job_segment() -> None:
    """存档迁移：save 后 persistent_state[SLOT_STATE_KEY] 更新为新装配 +
    记录 REARRANGE_JOB_KEY 段（job_id/at/snapshot，P-3）。"""
    player = _player()
    snap = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    node = save_rearranged_slots(player, snap, job_id="job_b", at="2026-09-02T10:00:00+08:00")
    assert player["persistent_state"][SLOT_STATE_KEY] == snap
    job_seg = player["persistent_state"][REARRANGE_JOB_KEY]
    assert job_seg["job_id"] == "job_b"
    assert job_seg["at"] == "2026-09-02T10:00:00+08:00"
    assert job_seg["snapshot"] == snap
    assert node is job_seg


def test_save_load_job_slots_roundtrip() -> None:
    """save → load_job_slots_state 等值 round-trip（1g1c/1g3 存档承接）。"""
    player = _player()
    snap = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    save_rearranged_slots(player, snap, job_id="job_b")
    loaded = load_job_slots_state(player)
    assert loaded["job_id"] == "job_b"
    assert loaded["snapshot"] == snap


def test_save_rearranged_idempotent_overwrite() -> None:
    """重复保存覆盖旧段（幂等）。"""
    player = _player({"skill_slots": {"old": True}, REARRANGE_JOB_KEY: {"old": True}})
    snap = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    save_rearranged_slots(player, snap, job_id="job_b")
    assert player["persistent_state"][SLOT_STATE_KEY] == snap
    assert player["persistent_state"][REARRANGE_JOB_KEY]["snapshot"] == snap


def test_save_creates_persistent_state_lazily() -> None:
    """persistent_state 缺失 → 惰性创建并挂回（对齐 _ps_init 模式，P-4）。"""
    player: Dict[str, Any] = {}
    snap = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    save_rearranged_slots(player, snap, job_id="job_b")
    assert "persistent_state" in player
    assert player["persistent_state"][SLOT_STATE_KEY] == snap


def test_load_job_slots_missing_and_malformed() -> None:
    """转职段缺省/畸形 → {}（防御读取，不抛异常）。"""
    assert load_job_slots_state(_player()) == {}
    bad = {"persistent_state": {REARRANGE_JOB_KEY: "oops"}}
    assert load_job_slots_state(bad) == {}
    bad2 = {"persistent_state": {REARRANGE_JOB_KEY: ["not", "mapping"]}}
    assert load_job_slots_state(bad2) == {}


def test_snapshot_json_serializable() -> None:
    """转职上下文段/重排快照可 JSON 序列化（存档 dict 口径，P-2）。"""
    import json

    snap = rearrange_job_slots({"skills": _lib_mixed()}, "job_b")
    text = json.dumps(snap, ensure_ascii=False)
    assert json.loads(text) == snap
    ctx_seg = snapshot_job_context(_player(), "job_a", _lib_mixed(), at="2026-09-02T10:00:00+08:00")
    text2 = json.dumps(ctx_seg, ensure_ascii=False)
    assert json.loads(text2) == ctx_seg


# ===========================================================================
# F 上下文快照（转职前打包）
# ===========================================================================
def test_snapshot_job_context_packs_current_state() -> None:
    """snapshot_job_context 打包旧装配 + 旧 job_id + 技能表（P-1/P-3 只读，
    不写 player、不落存档）。"""
    player = _player()
    snap = assemble_slots(_lib_a(), {"job_id": "job_a"})
    from qbot_rpg.core.skill_slots import save_slots_to_state

    save_slots_to_state(player, snap)
    seg = snapshot_job_context(player, "job_a", _lib_a(), at="2026-09-02T10:00:00+08:00")
    assert seg["job_id"] == "job_a"
    assert seg["at"] == "2026-09-02T10:00:00+08:00"
    assert seg["active_order_snapshot"] == snap["active_order"]
    assert seg["snapshot"] == snap
    assert [s["id"] for s in seg["skills"]] == [
        "basic_generic", "skill_common", "skill_a_only",
        "passive_a_only", "trigger_a_only", "passive_common",
    ]
    # 只读：打包不新增/改写存档键（skill_slots 段原样保留）
    assert player["persistent_state"][SLOT_STATE_KEY] == snap
    assert REARRANGE_JOB_KEY not in player["persistent_state"]


def test_snapshot_job_context_defaults() -> None:
    """job_id/at 缺省 → 段内不写对应键；无存档 → 空装配快照兜底。"""
    seg = snapshot_job_context(_player(), None, None)
    assert "job_id" not in seg
    assert "at" not in seg
    assert seg["active_order_snapshot"] == []
    assert seg["snapshot"]["slots"] == []
    assert seg["skills"] == []
