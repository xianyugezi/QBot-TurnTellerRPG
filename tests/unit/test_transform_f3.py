"""M13 批6 路6C · 6b 变换引擎 F3 快照续战测试（tests/unit/test_transform_f3.py）。

文件名：tests/unit/test_transform_f3.py
创建时间：2026-09-02
作者：Hermes 子agent-6C（M13 6b 变换引擎实现组批6路6C：并发同仓，仅新建本文件 +
  qbot_rpg/core/transform_snapshot.py；不碰兄弟文件——6A 独占 core/transform.py、
  6B 独占 core/transform_revert.py）

测试目标：qbot_rpg.core.transform_snapshot（F3 快照引擎）：
  - 7 字段定义与登记（T1~T7 恰 7 键，§4.1 字段表）；
  - snapshot_write 7 字段写（协议对象/raw dict/None 三形态 + 深拷贝隔离 +
    畸形值归一 + form=null 不变量）；
  - snapshot_restore 恢复（round-trip 完全一致 TC-13 / 中断恢复还原形态
    TC-14 / remaining 恢复 / active_skill_set 恢复 / T6 交叉校验取较早者 /
    SN-3 删除降级 / 旧档兼容）；
  - 战斗结束清零 SN-4（TC-15：清空回常态 + attach 挂点 + 幂等）；
  - 引擎注入模式（job_id_provider / status_state_provider / audit 接线）。

依据：docs/细化/细化_6b_职业库与变换引擎.md §4.1~4.3（T1~T7 字段表 /
流程 F3 ①~⑥ / SN-1~5）+ §六 TC-13~16（快照与续战 4 例）+ docs/m13_6b摸底.md
（缺口登记与挂载点建议）。TC-16 热重载旧局旧配置归 7A 装配/世代重绑定
（RSM-04），本层不覆盖。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机；不 git commit。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from qbot_rpg.core.transform_snapshot import (
    TRANSFORM_STATE_FIELDS,
    TRANSFORM_STATE_KEY,
    TransformSnapshotEngine,
    TransformStateKind,
    attach_cleared_state,
    attach_initial_state,
    clear_transform_state,
    empty_transform_state,
    is_cooldown_active,
    is_form_active,
    snapshot_restore,
    snapshot_write,
)

# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------


def _full_state() -> Dict[str, Any]:
    """形态激活中（S3）transform_state 全 7 字段（狂战士 berserker 示例，TC-13 口径）。"""
    return {
        "job_id": "berserker",
        "form": "berserker_form",
        "form_name": "狂战士形态",
        "remaining": 2,
        "cooldown_remaining": 0,
        "form_status_id": "rage_form",
        "active_skill_set": "transform_skills",
    }


def _cooldown_state() -> Dict[str, Any]:
    """冷却期（S5）：form=null + cooldown>0（§4.1 T5 合法形态，F3-3 不变量）。"""
    return {
        "job_id": "berserker",
        "form": None,
        "form_name": "",
        "remaining": 0,
        "cooldown_remaining": 3,
        "form_status_id": None,
        "active_skill_set": "",
    }


def _status_state(
    form_status_id: str = "rage_form", remaining: Optional[int] = 2
) -> Dict[str, Any]:
    """status_state 段（{side: [entries]}；条目 id 键兼容 id/status_id，F3-1）。"""
    entry: Dict[str, Any] = {"id": form_status_id, "category": "强化"}
    if remaining is not None:
        entry["remaining"] = remaining
    return {"player": [entry], "enemy": []}


class _StubState(TransformStateKind):
    """协议对象桩（6A/6B 引擎侧状态对象形态；G0 注入适配）。"""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = dict(raw)

    @property
    def job_id(self) -> str:
        return str(self._raw.get("job_id", ""))

    @property
    def form(self) -> Optional[str]:
        v = self._raw.get("form")
        return v if isinstance(v, str) and v else None

    @property
    def form_name(self) -> str:
        return str(self._raw.get("form_name", ""))

    @property
    def remaining(self) -> int:
        v = self._raw.get("remaining", 0)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0

    @property
    def cooldown_remaining(self) -> int:
        v = self._raw.get("cooldown_remaining", 0)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0

    @property
    def form_status_id(self) -> Optional[str]:
        v = self._raw.get("form_status_id")
        return v if isinstance(v, str) and v else None

    @property
    def active_skill_set(self) -> str:
        return str(self._raw.get("active_skill_set", ""))


# ---------------------------------------------------------------------------
# 1. 7 字段定义与登记（§4.1 字段表 T1~T7）
# ---------------------------------------------------------------------------


def test_transform_state_fields_exactly_7_keys() -> None:
    """TRANSFORM_STATE_FIELDS 恰 7 键，键名与契约字段表 T1~T7 逐键一致。"""
    assert TRANSFORM_STATE_FIELDS == (
        "job_id",               # T1
        "form",                 # T2
        "form_name",            # T3
        "remaining",            # T4
        "cooldown_remaining",   # T5
        "form_status_id",       # T6
        "active_skill_set",     # T7
    )
    assert len(TRANSFORM_STATE_FIELDS) == 7


def test_empty_transform_state_full_defaults() -> None:
    """常态骨架：7 字段全默认（form=null=常态 S1/S5，T2；其余 0/空/None）。"""
    s = empty_transform_state()
    assert s == {
        "job_id": "",
        "form": None,
        "form_name": "",
        "remaining": 0,
        "cooldown_remaining": 0,
        "form_status_id": None,
        "active_skill_set": "",
    }
    assert set(s.keys()) == set(TRANSFORM_STATE_FIELDS)


def test_empty_transform_state_job_id_injected() -> None:
    """常态骨架 job_id 注入（T1 职业 ID 冗余；start 建段口径）。"""
    s = empty_transform_state("berserker")
    assert s["job_id"] == "berserker"
    bad: Any = 123  # 非 str 注入（防御兜底路径，经 Any 避开静态类型误报）
    s_bad = empty_transform_state(bad)
    assert s_bad["job_id"] == ""


# ---------------------------------------------------------------------------
# 2. snapshot_write 7 字段写（F3 ①）
# ---------------------------------------------------------------------------


def test_snapshot_write_full_state_all_7_fields() -> None:
    """写入：形态激活中（S3）全 7 字段逐值保留（TC-13 写入侧）。"""
    out = snapshot_write(_full_state())
    assert out == _full_state()


def test_snapshot_write_protocol_object_adapter() -> None:
    """写入：TransformStateKind 协议对象直接注入（G0：6A/6B 状态对象可用）。"""
    stub = _StubState(_full_state())
    out = snapshot_write(stub)
    assert out == _full_state()


def test_snapshot_write_none_returns_normal_skeleton() -> None:
    """写入：None → 常态骨架（start 建段 / 无形态职业兜底，F3 ①）。"""
    out = snapshot_write(None)
    assert out == empty_transform_state()
    assert out["form"] is None and out["remaining"] == 0


def test_snapshot_write_deepcopy_isolation() -> None:
    """写入：深拷贝隔离——外部改原 dict 不影响已产出快照（防共享改写）。"""
    raw = _full_state()
    out = snapshot_write(raw)
    raw["form"] = "other_form"
    raw["remaining"] = 99
    assert out["form"] == "berserker_form"
    assert out["remaining"] == 2


def test_snapshot_write_normalizes_malformed_values() -> None:
    """写入：畸形值归一（非 str/负值/非 int → 合理默认，不抛异常，三铁律②）。"""
    out = snapshot_write(
        {
            "job_id": 3,
            "form": 7,
            "form_name": ["x"],
            "remaining": -5,
            "cooldown_remaining": "3",
            "form_status_id": 0,
            "active_skill_set": {"a": 1},
        }
    )
    assert out["job_id"] == ""
    assert out["form"] is None
    assert out["form_name"] == ""
    assert out["remaining"] == 0
    assert out["cooldown_remaining"] == 0
    assert out["form_status_id"] is None
    assert out["active_skill_set"] == ""


def test_snapshot_write_form_null_forces_remaining_zero() -> None:
    """写不变量（F3-3）：form=null（常态）时 remaining 强制 0（§4.1 T4）。"""
    out = snapshot_write(
        {
            "job_id": "berserker",
            "form": None,
            "form_name": "",
            "remaining": 5,  # 常态携带剩余回合 → 归一为 0
            "cooldown_remaining": 0,
            "form_status_id": None,
            "active_skill_set": "",
        }
    )
    assert out["remaining"] == 0


def test_snapshot_write_cooldown_kept_with_null_form() -> None:
    """写不变量（F3-3）：S5 冷却期 form=null 且 cooldown>0 合法保留（§4.1 T5）。"""
    out = snapshot_write(_cooldown_state())
    assert out["form"] is None
    assert out["remaining"] == 0
    assert out["cooldown_remaining"] == 3


# ---------------------------------------------------------------------------
# 3. snapshot_restore 恢复（F3 ②~⑤ / TC-14 + T6 交叉校验 + SN-3 降级）
# ---------------------------------------------------------------------------


def test_restore_roundtrip_exact_identity() -> None:
    """round-trip：写→读完全一致（TC-13：序列化→反序列化 7 字段逐值相同）。"""
    snap = {"transform_state": _full_state()}
    restored = snapshot_restore(snap)
    assert restored == _full_state()
    # 经 JSON 序列化往返后仍一致（快照须可 JSON 序列化，1g3/4a）
    import json

    again = snapshot_restore(json.loads(json.dumps(snap)))
    assert again == _full_state()


def test_restore_interrupt_resume_form_context() -> None:
    """中断恢复还原形态（TC-14）：form/remaining/active_skill_set 逐值恢复。"""
    restored = snapshot_restore({"transform_state": _full_state()})
    assert restored["form"] == "berserker_form"   # ② 形态指针
    assert restored["remaining"] == 2             # ④ 剩余回合（递减继续归 F2）
    assert restored["active_skill_set"] == "transform_skills"  # ③ 技能位恢复基准
    assert restored["form_status_id"] == "rage_form"
    assert restored["job_id"] == "berserker"      # T1 冗余


def test_restore_remaining_continues_after_resume() -> None:
    """续战后剩余回合递减继续（TC-14）：恢复 remaining=2，F2 tick 递减口径不变。"""
    restored = snapshot_restore({"transform_state": _full_state()})
    assert restored["remaining"] == 2
    # F2 tick 递减（归 transform_revert.py，本层只保证恢复上下文供递减消费）：
    # 恢复上下文可直接作为递减输入
    ticked = snapshot_write({**restored, "remaining": restored["remaining"] - 1})
    assert ticked["remaining"] == 1


def test_restore_status_cross_check_takes_earlier() -> None:
    """T6 交叉校验（F3 ⑤）：remaining 与 status_state 双写不一致 → 取较早者。"""
    snap = {"transform_state": _full_state()}  # remaining=2
    audits: List[str] = []
    restored = snapshot_restore(
        snap, status_state=_status_state("rage_form", remaining=1), audit=audits.append
    )
    assert restored["remaining"] == 1  # min(2, 1) = 1
    assert any("双写不一致" in a for a in audits)
    # 反向不一致：状态时长更长 → 取引擎计数（较早者）
    restored2 = snapshot_restore(
        snap, status_state=_status_state("rage_form", remaining=5), audit=audits.append
    )
    assert restored2["remaining"] == 2  # min(2, 5) = 2


def test_restore_status_cross_check_consistent_no_audit() -> None:
    """T6 双写一致：不触发审计日志，remaining 原样保留。"""
    audits: List[str] = []
    restored = snapshot_restore(
        _full_state_snap(), status_state=_status_state("rage_form", remaining=2),
        audit=audits.append,
    )
    assert restored["remaining"] == 2
    assert audits == []


def test_restore_sn3_missing_status_degrades() -> None:
    """SN-3 删除降级：form_status_id 在 status_state 缺失 → 降级 None 不报错。"""
    audits: List[str] = []
    restored = snapshot_restore(
        _full_state_snap(), status_state={"player": [], "enemy": []},
        audit=audits.append,
    )
    assert restored["form"] == "berserker_form"      # 形态保留
    assert restored["active_skill_set"] == "transform_skills"  # 技能位清偿
    assert restored["form_status_id"] is None        # 状态引用降级
    assert any("SN-3" in a for a in audits)


def test_restore_status_id_key_compat() -> None:
    """status_state 条目 id 键兼容 status_id（F3-1 防御口径）。"""
    ss: Dict[str, Any] = {"player": [{"status_id": "rage_form", "remaining": 2}], "enemy": []}
    restored = snapshot_restore(_full_state_snap(), status_state=ss)
    assert restored["form_status_id"] == "rage_form"
    assert restored["remaining"] == 2


def test_restore_legacy_snapshot_without_segment() -> None:
    """旧档兼容：快照无 transform_state 段 → 常态骨架（非 None，确定性兜底）。"""
    restored = snapshot_restore({"status": "active", "turn": 3})
    assert restored == empty_transform_state()
    assert restored["form"] is None and restored["remaining"] == 0
    assert restored["cooldown_remaining"] == 0


def test_restore_non_mapping_input() -> None:
    """恢复入参 None/非 Mapping → 常态骨架（防御读取，不抛异常）。"""
    assert snapshot_restore(None) == empty_transform_state()
    bad: Any = "bad"  # 非 Mapping 输入（防御读取路径，经 Any 避开静态类型误报）
    assert snapshot_restore(bad) == empty_transform_state()


# ---------------------------------------------------------------------------
# 4. 战斗结束清零 SN-4（TC-15）+ 挂点 + 判定辅助
# ---------------------------------------------------------------------------


def test_clear_transform_state_resets_to_normal() -> None:
    """SN-4 清零：全段清零回常态（form=null/remaining=0/cooldown=0，TC-15）。"""
    cleared = clear_transform_state("berserker")
    assert cleared == empty_transform_state("berserker")
    assert cleared["form"] is None
    assert cleared["remaining"] == 0
    assert cleared["cooldown_remaining"] == 0
    assert cleared["form_status_id"] is None
    assert cleared["active_skill_set"] == ""


def test_attach_initial_state_builds_segment() -> None:
    """start() 建段挂点：battle_state 增 transform_state 常态骨架（T1 注入）。"""
    battle: Dict[str, Any] = {"status": "active"}
    node = attach_initial_state(battle, job_id="berserker")
    assert battle[TRANSFORM_STATE_KEY] == node
    assert node == empty_transform_state("berserker")
    assert node["job_id"] == "berserker"


def test_attach_cleared_state_sn4_zeroes_with_audit() -> None:
    """_settle 清零挂点（SN-4）：段清零回常态 + transform_cleared_at 审计键。"""
    battle: Dict[str, Any] = {"transform_state": _full_state()}
    node = attach_cleared_state(battle, job_id="berserker")
    assert node == empty_transform_state("berserker")
    assert battle[TRANSFORM_STATE_KEY] == node
    assert battle.get("transform_cleared_at") == "battle_end"


def test_attach_cleared_state_idempotent() -> None:
    """清零幂等：对已清零段再清零 → 结果不变（重复调用安全）。"""
    battle: Dict[str, Any] = {"transform_state": _full_state()}
    attach_cleared_state(battle, job_id="berserker")
    first = dict(battle[TRANSFORM_STATE_KEY])
    attach_cleared_state(battle, job_id="berserker")
    assert battle[TRANSFORM_STATE_KEY] == first


def test_form_active_and_cooldown_helpers() -> None:
    """状态判定辅助：S3 形态激活 / S5 冷却期 / 常态三分。"""
    assert is_form_active(_full_state()) is True
    assert is_form_active(_cooldown_state()) is False
    assert is_form_active(empty_transform_state()) is False
    assert is_form_active(None) is False
    assert is_cooldown_active(_cooldown_state()) is True
    assert is_cooldown_active(_full_state()) is False
    assert is_cooldown_active(empty_transform_state()) is False


# ---------------------------------------------------------------------------
# 5. 引擎注入模式（TransformSnapshotEngine）
# ---------------------------------------------------------------------------


def test_engine_write_injects_job_id() -> None:
    """引擎写入：job_id_provider 注入 → 常态骨架携带 T1 职业 ID。"""
    eng = TransformSnapshotEngine(job_id_provider=lambda: "berserker")
    out = eng.write()
    assert out["job_id"] == "berserker"
    assert out["form"] is None
    # 显式 state 传入时委托 snapshot_write（不注入覆盖）
    out2 = eng.write(_full_state())
    assert out2 == _full_state()


def test_engine_restore_uses_status_provider_and_audit() -> None:
    """引擎恢复：status_state_provider 取数 + audit 观察口接线。"""
    audits: List[str] = []
    eng = TransformSnapshotEngine(
        status_state_provider=lambda: _status_state("rage_form", remaining=1),
        audit=audits.append,
    )
    restored = eng.restore(_full_state_snap())
    assert restored["remaining"] == 1
    assert any("双写不一致" in a for a in audits)


def test_engine_clear_and_helpers() -> None:
    """引擎清零 + 判定：委托纯函数默认行为。"""
    eng = TransformSnapshotEngine(job_id_provider=lambda: "berserker")
    assert eng.clear() == empty_transform_state("berserker")
    assert eng.restore(None) == empty_transform_state()


def _full_state_snap() -> Dict[str, Any]:
    """带 transform_state 段的战斗快照（恢复入参形态）。"""
    return {"transform_state": _full_state()}
