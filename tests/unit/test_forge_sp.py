"""M9 锻造·批3·路3B：铸造 SP 面板解锁单元测试（tests/unit/test_forge_sp.py）。

文件名：test_forge_sp.py
创建时间：2026-08-30
作者：Hermes 子agent-3B（M9 锻造实现组批3·路3B：并发同仓，仅新建本文件 +
  qbot_rpg/core/forge_sp.py + 扩展 content/test_demo/proficiency.json forge 实例 sp_panel；
  不改动 qbot_rpg/core/proficiency.py（只读消费））

依据：docs/细化/细化_2c2d_锻造套装与客制.md §3.2（SP-F1~F5 五类解锁项）+
  docs/细化/细化_2c5a_职业等级与SP.md SP-01~08（每级 1 SP/面板自选/双计/1 SP/次）。
测试目标：qbot_rpg.core.forge_sp.{FORGE_SP_PANEL, sp_available, sp_unlock, sp_locked,
  sp_panel_view}。

覆盖矩阵：
  A sp_available 随等级增长：新玩家 0；入账熟练跨 2 阈值升 2 级 → 2（SP-01 每级 1）
  B sp_unlock 五类逐一解锁（SP-F1~F5 全 ok，sp_used 逐项 +1）
  C 幂等：repeatable=false 已解锁再解锁 → not_repeatable、sp_available 不变（不重复扣点）
  D SP 不足拒：sp_earned=0 → sp_insufficient（TC-16 语义）
  E 未识别面板拒：未知 id / 空串 / 非 str → panel_not_found
  F sp_locked 未解锁判定：初始全 True；解锁对应项 False；未知面板 True；player None → True
  G sp_panel_view 结构：5 项（SP-F1→F5 序）、字段 id/name/scope/desc/unlocked 齐备、
    解锁状态逐项正确、纯读不改写
  H content/test_demo/proficiency.json forge 实例 sp_panel 与 FORGE_SP_PANEL 同构
    （id/name 一致 + cost=1/repeatable=false/max_repeat=1）

铁律：零 NoneBot import；纯函数确定性；零定时器探针合规；不引入随机。

"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from qbot_rpg.core.forge_sp import (
    FORGE_SP_PANEL,
    sp_available,
    sp_locked,
    sp_panel_view,
    sp_unlock,
)
from qbot_rpg.core.forge_tree import FORGE_JOB_ID
from qbot_rpg.core.proficiency import ProficiencyEngine

# 仓库根 = tests/unit/test_forge_sp.py 上溯两级
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROF_JSON = _REPO_ROOT / "content" / "test_demo" / "proficiency.json"

# SP-F1~F5 面板项 id（文件序，与 2c2d §3.2 一一对应）
_F1 = "unlock_branch_tree"
_F2 = "unlock_combine_3to1"
_F3 = "unlock_slot_tool"
_F4 = "unlock_sets"
_F5 = "unlock_augment"
_ALL_PANEL_IDS: List[str] = [_F1, _F2, _F3, _F4, _F5]


def _player(sp_earned: int = 0, unlocks: Dict[str, int] | None = None) -> Dict[str, Any]:
    """铸造职业玩家表示（SP 存量与已解锁可配；sp_used 由解锁路径维护）。"""
    used = 0
    if unlocks:
        used = sum(1 for _ in unlocks)  # 五项均 cost=1，已解锁项数即已用 SP
    return {
        "proficiency": {
            FORGE_JOB_ID: {
                "level": 0,
                "exp": 0,
                "sp_earned": sp_earned,
                "sp_used": used,
                "unlocks": dict(unlocks or {}),
            }
        }
    }


def _level_up(player: Dict[str, Any], exp: int) -> Dict[str, Any]:
    """入账铸造熟练经验（默认成长曲线，升 N 级发 N SP）。"""
    return ProficiencyEngine().gain_prof_exp(player, FORGE_JOB_ID, exp, "craft")


def _load_forge_prof_entry() -> Dict[str, Any]:
    """读真实 proficiency.json 的 forge 实例（路3B 落盘对齐断言用）。"""
    raw = json.loads(_PROF_JSON.read_text(encoding="utf-8"))
    entries = raw if isinstance(raw, list) else []
    for e in entries:
        if isinstance(e, dict) and e.get("id") == FORGE_JOB_ID:
            return e
    raise AssertionError("proficiency.json 缺 forge 实例（路3B 未落盘）")


# ---------------------------------------------------------------------------
# A sp_available 随等级增长（SP-01 每级 1 点 / SP-06 双计）
# ---------------------------------------------------------------------------
def test_sp_available_starts_zero() -> None:
    """新玩家（无 proficiency.forge）→ 0（确定性兜底）。"""
    assert sp_available({}) == 0
    assert sp_available(None) == 0
    assert sp_available({"proficiency": {}}) == 0


def test_sp_available_grows_with_level() -> None:
    """入账 350 熟练（默认曲线 0→100→300 跨两阈值）→ 升 2 级 → SP=2。"""
    player = _player()
    r = _level_up(player, 350)
    assert r["ok"] is True and r["level_ups"] == 2 and r["sp_gained"] == 2
    assert player["proficiency"]["forge"]["level"] == 2
    assert sp_available(player) == 2


def test_sp_available_reflects_used() -> None:
    """sp_earned=5 / 已解锁 2 项（sp_used=2）→ 可用 3（SP-06 双计）。"""
    p = _player(sp_earned=5, unlocks={_F1: 1, _F2: 1})
    assert sp_available(p) == 3


# ---------------------------------------------------------------------------
# B sp_unlock 五类逐一解锁（SP-F1~F5；2c2d §3.2）
# ---------------------------------------------------------------------------
def test_sp_unlock_all_five_in_order() -> None:
    """SP 充足时逐一解锁 SP-F1~F5，每项 ok、sp_used 逐项 +1（cost=1）。"""
    p = _player(sp_earned=5)
    for i, pid in enumerate(_ALL_PANEL_IDS, start=1):
        r = sp_unlock(p, pid)
        assert r["ok"] is True, (pid, r)
        assert r["panel_id"] == pid
        assert r["unlock_count"] == 1
        assert r["sp_used_delta"] == 1
        assert p["proficiency"]["forge"]["unlocks"][pid] == 1
        assert p["proficiency"]["forge"]["sp_used"] == i
    assert sp_available(p) == 0


def test_sp_unlock_panel_names_match_2c2d() -> None:
    """解锁返回 panel_name 与 2c2d §3.2 名称一致。"""
    p = _player(sp_earned=1)
    r = sp_unlock(p, _F1)
    assert r["ok"] and r["panel_name"] == "分支树视野"


# ---------------------------------------------------------------------------
# C 幂等：repeatable=false 已解锁再解锁 → 拒绝且不重复扣点
# ---------------------------------------------------------------------------
def test_sp_unlock_idempotent_not_repeatable() -> None:
    """已解锁（repeatable=false）再次解锁 → not_repeatable；sp_available 不变。"""
    p = _player(sp_earned=2, unlocks={_F1: 1})
    before = sp_available(p)
    r = sp_unlock(p, _F1)
    assert r["ok"] is False and r["reason"] == "not_repeatable"
    assert p["proficiency"]["forge"]["unlocks"][_F1] == 1  # 未重复累加
    assert sp_available(p) == before  # 未重复扣点


# ---------------------------------------------------------------------------
# D SP 不足拒（TC-16 语义）
# ---------------------------------------------------------------------------
def test_sp_unlock_insufficient() -> None:
    """sp_earned=0 → sp_insufficient，零副作用。"""
    p = _player(sp_earned=0)
    r = sp_unlock(p, _F1)
    assert r["ok"] is False and r["reason"] == "sp_insufficient"
    assert p["proficiency"]["forge"].get("unlocks", {}) == {}
    assert p["proficiency"]["forge"]["sp_used"] == 0


def test_sp_unlock_insufficient_after_spending() -> None:
    """花光 SP 后（可用 0）再解锁 → sp_insufficient。"""
    p = _player(sp_earned=2, unlocks={_F1: 1, _F2: 1})
    assert sp_available(p) == 0
    r = sp_unlock(p, _F3)
    assert r["ok"] is False and r["reason"] == "sp_insufficient"


# ---------------------------------------------------------------------------
# E 未识别面板拒
# ---------------------------------------------------------------------------
def test_sp_unlock_unknown_panel() -> None:
    """未知面板项 id / 空串 / 非 str → panel_not_found。"""
    p = _player(sp_earned=5)
    assert sp_unlock(p, "no_such_panel")["reason"] == "panel_not_found"
    assert sp_unlock(p, "")["reason"] == "panel_not_found"
    assert sp_unlock(p, 123)["reason"] == "panel_not_found"
    assert sp_unlock(p, None)["reason"] == "panel_not_found"
    assert sp_available(p) == 5  # 零副作用


# ---------------------------------------------------------------------------
# F sp_locked 未解锁判定（消费方：3:1 入口隐藏 / /套装、/客制 拒绝 / /图纸 分支折叠）
# ---------------------------------------------------------------------------
def test_sp_locked_all_locked_initially() -> None:
    """初始（无解锁）→ SP-F1~F5 全部锁定。"""
    p = _player(sp_earned=0)
    for pid in _ALL_PANEL_IDS:
        assert sp_locked(p, pid) is True


def test_sp_locked_flips_after_unlock() -> None:
    """解锁 F2 后：F2 未锁定、其余仍锁定（TC-20 语义）。"""
    p = _player(sp_earned=1)
    assert sp_locked(p, _F2) is True
    assert sp_unlock(p, _F2)["ok"] is True
    assert sp_locked(p, _F2) is False
    for pid in (_F1, _F3, _F4, _F5):
        assert sp_locked(p, pid) is True


def test_sp_locked_unknown_panel_conservative() -> None:
    """未知面板项 / 空串 / 非 str / player None → 保守锁定 True（F-2/F-3）。"""
    p = _player(sp_earned=5, unlocks={_F1: 1, _F2: 1, _F3: 1, _F4: 1, _F5: 1})
    assert sp_locked(p, "no_such_panel") is True
    assert sp_locked(p, "") is True
    assert sp_locked(p, 123) is True
    assert sp_locked(None, _F1) is True
    assert sp_locked({}, _F1) is True


# ---------------------------------------------------------------------------
# G sp_panel_view 结构（供 /技能面板 渲染）
# ---------------------------------------------------------------------------
def test_sp_panel_view_structure() -> None:
    """5 项（SP-F1→F5 序）、字段齐备、初始全未解锁。"""
    p = _player(sp_earned=0)
    view = sp_panel_view(p)
    assert [v["id"] for v in view] == _ALL_PANEL_IDS
    assert len(view) == len(FORGE_SP_PANEL) == 5
    for v in view:
        assert set(v.keys()) == {"id", "name", "scope", "desc", "unlocked"}
        assert isinstance(v["name"], str) and v["name"]
        assert isinstance(v["scope"], str) and v["scope"]
        assert isinstance(v["desc"], str) and v["desc"]
        assert v["unlocked"] is False


def test_sp_panel_view_reflects_unlock_state() -> None:
    """解锁 F1/F4 后视图对应项 unlocked=True，其余 False。"""
    p = _player(sp_earned=2)
    assert sp_unlock(p, _F1)["ok"] is True
    assert sp_unlock(p, _F4)["ok"] is True
    view = {v["id"]: v["unlocked"] for v in sp_panel_view(p)}
    assert view[_F1] is True and view[_F4] is True
    for pid in (_F2, _F3, _F5):
        assert view[pid] is False


def test_sp_panel_view_pure_read_no_mutation() -> None:
    """sp_panel_view 纯读：player 快照前后不变。"""
    import copy

    p = _player(sp_earned=3)
    snapshot = copy.deepcopy(p)
    sp_panel_view(p)
    assert p == snapshot


# ---------------------------------------------------------------------------
# H proficiency.json forge 实例 sp_panel 与 FORGE_SP_PANEL 同构（路3B 落盘对齐）
# ---------------------------------------------------------------------------
def test_proficiency_json_forge_entry_aligned() -> None:
    """真实 proficiency.json forge 实例：sp_panel 五项 id/name 与 FORGE_SP_PANEL 一致，
    且 cost=1/repeatable=false/max_repeat=1（2c2d §3.2 定价）。"""
    entry = _load_forge_prof_entry()
    panel = entry.get("sp_panel")
    assert isinstance(panel, list) and len(panel) == 5
    by_id = {item["id"]: item for item in panel}
    assert list(by_id.keys()) == _ALL_PANEL_IDS
    for item in FORGE_SP_PANEL:
        cfg = by_id[item["id"]]
        assert cfg["name"] == item["name"]
        assert cfg["cost"] == 1
        assert cfg["repeatable"] is False
        assert cfg["max_repeat"] == 1


def test_proficiency_json_forge_entry_unlocks_via_engine() -> None:
    """真实 proficiency.json entries 注入引擎：解锁路径与 FORGE_SP_PANEL 一致（跨层对齐）。"""
    entry = _load_forge_prof_entry()
    engine = ProficiencyEngine(entries=[entry])
    p = {"proficiency": {"forge": {"level": 0, "exp": 0, "sp_earned": 3,
                                    "sp_used": 0, "unlocks": {}}}}
    for pid in (_F1, _F2, _F3):
        r = engine.unlock_item(p, FORGE_JOB_ID, pid)
        assert r["ok"] is True, (pid, r)
    assert engine.unlock_count(p, FORGE_JOB_ID, _F4) == 0
