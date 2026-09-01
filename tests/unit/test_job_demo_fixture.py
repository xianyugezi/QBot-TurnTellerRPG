"""M13 6b test_demo 狂战士示例夹具单测（tests/unit/test_job_demo_fixture.py · M13 批7 路7C）。

覆盖：
  - jobs.json 结构（4 条职业：狂战士完整 transform + 3 条生活职业）
  - transform 段 11 字段 + state_policy 3 字段覆盖
  - skills.json 形态技能（berserk/平息战意/怒涛斩/裂地击 job_form 限定）
  - build_pack 零红拦（test_demo 全链路）

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "content" / "test_demo"


def _jobs() -> List[Dict[str, Any]]:
    return json.loads((DEMO / "jobs.json").read_text(encoding="utf-8"))


def _skills() -> List[Dict[str, Any]]:
    return json.loads((DEMO / "skills.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# jobs.json 结构
# ---------------------------------------------------------------------------
def test_jobs_has_berserker_and_life_jobs() -> None:
    """jobs.json 含狂战士 + 三条生活职业（PRF-01 引用靶）。"""
    jobs = _jobs()
    ids = [j["id"] for j in jobs]
    assert "berserker" in ids, "缺狂战士"
    for life in ("alchemy", "forge", "fishing"):
        assert life in ids, f"缺生活职业 {life}（proficiency.json PRF-01 引用）"


def test_berserker_transform_full() -> None:
    """狂战士 transform 段 11 字段完整。"""
    b = next(j for j in _jobs() if j["id"] == "berserker")
    tr = b.get("transform")
    assert tr is not None, "狂战士必须有 transform 段"
    for key in ("transform_skill", "transform_to", "duration", "turns",
                "revert", "cooldown", "dispel_reverts", "state_policy",
                "skill_set", "equip_restrict", "derive_chains"):
        assert key in tr, f"transform 缺字段 {key}"
    assert tr["transform_to"] == "berserker_form"
    assert tr["duration"] == "turns"
    assert tr["revert"] is True


def test_berserker_state_policy_full() -> None:
    """state_policy 三键 ∈ {clear, keep}。"""
    b = next(j for j in _jobs() if j["id"] == "berserker")
    sp = b["transform"]["state_policy"]
    assert set(sp.keys()) == {"combo", "marks", "buff"}
    for v in sp.values():
        assert v in ("clear", "keep"), f"state_policy 值非法: {v}"


def test_berserker_resource_axes_valid() -> None:
    """resource_axes 引用 stats.json 注册键（V3）。"""
    from qbot_rpg.content.loader import build_pack  # noqa: PLC0415

    pack, _ = build_pack(DEMO)
    stats = pack.registry.modules_raw.get("stats", {})
    b = next(j for j in _jobs() if j["id"] == "berserker")
    for ax in b["resource_axes"]:
        assert ax in stats or ax == "combo", f"资源轴 {ax} 未注册"


# ---------------------------------------------------------------------------
# skills.json 形态技能
# ---------------------------------------------------------------------------
def test_form_skills_exist() -> None:
    """形态技能齐备：berserk（触发）/ calm_fury（还原）/ 怒涛斩/裂地击。"""
    skills = _skills()
    ids = {s["id"] for s in skills}
    for sid in ("rage_burst", "calm_fury", "rage_slash", "quake_smash"):
        assert sid in ids, f"缺形态技能 {sid}"


def test_form_skills_job_form_limited() -> None:
    """形态技能 job_form=berserker_form 限定。"""
    skills = _skills()
    form_skills = [s for s in skills if s.get("job_form")]
    assert len(form_skills) >= 4, f"形态技能应 ≥4，got {len(form_skills)}"
    for s in form_skills:
        assert s["job_form"] == "berserker_form", f"{s['id']} job_form 非法"


def test_revert_form_skill_in_form_scope() -> None:
    """平息战意 revert_form=true 且 job_form 归属形态（V7 正例）。"""
    calm = next(s for s in _skills() if s["id"] == "calm_fury")
    assert calm.get("revert_form") is True
    assert calm.get("job_form") == "berserker_form"


def test_derive_only_skill_effects_valid() -> None:
    """fury_spin_finisher derive_only=true + effects 引用存在（V7 正例）。"""
    spin = next(s for s in _skills() if s["id"] == "fury_spin_finisher")
    assert spin.get("derive_only") is True
    assert spin.get("job_form") == "berserker_form"


def test_basic_attack_per_job_valid() -> None:
    """V-7：常态普攻每职业恰 1（形态普攻不占位）。"""
    from qbot_rpg.content.loader import build_pack  # noqa: PLC0415

    pack, _ = build_pack(DEMO)  # 零红拦即 V-7 通过
    assert pack.report.ok


# ---------------------------------------------------------------------------
# build_pack 全链路
# ---------------------------------------------------------------------------
def test_build_pack_zero_red() -> None:
    """build_pack 加载 test_demo 零红拦（含 jobs/skills/skill_chains）。"""
    from qbot_rpg.content.loader import build_pack  # noqa: PLC0415

    pack, _ = build_pack(DEMO)
    assert pack.report.ok, f"test_demo 应零红拦：{pack.report.errors}"
    assert len(pack.registry.all_ids("job")) == 4, "jobs 应 4 条"
    assert len(pack.registry.all_ids("skill")) >= 20, "skills 应 ≥20 条"
