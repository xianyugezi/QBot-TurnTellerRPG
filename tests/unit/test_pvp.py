"""PVP 引擎单测（tests/unit/test_pvp.py · M11 批3 路3A）。

覆盖：锁定（防自己/开关/门槛/目标不存在/显示字段）、攻击（未锁定/目标不存在/
开关）、偷袭判定、防刷（每日上限）、配置三态容错。
"""
from __future__ import annotations

from typing import Any, MutableMapping

from qbot_rpg.core.pvp import (
    pvp_attack,
    pvp_cfg,
    pvp_lock,
    sneak_attack_allowed,
)


def _player(qid: str = "123456789", name: str = "小王", level: int = 12) -> dict:
    return {
        "qid": qid, "name": name, "job_id": "mage", "level": level,
        "hp": 80, "max_hp": 80, "mp": 50, "max_mp": 50,
        "attributes": {"base": {"atk": 12, "def": 8, "spd": 10, "lck": 10}},
        "equipment": {"weapon": {"name": "法杖"}},
    }


def _ctx(**extra) -> MutableMapping[str, Any]:
    ctx: MutableMapping[str, Any] = {
        "qid": "987654321",
        "level": 15,
        "players": {"123456789": _player(), "987654321": _player("987654321", "阿伟", 15)},
        "settings": {"pvp": {"enabled": True, "level_gate": 10}},
        "skills": {"s1": {"name": "斩击"}, "s2": {"name": "火球"}},
        "pvp_daily": {"rewards": 0},
    }
    ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# 配置三态容错
# ---------------------------------------------------------------------------
def test_pvp_cfg_defaults():
    """无 pvp 段 → 全默认（enabled=False）。"""
    cfg = pvp_cfg({})
    assert cfg["enabled"] is False
    assert cfg["mode"] == "turn_based"
    assert cfg["level_gate"] == 10


def test_pvp_cfg_from_settings():
    """ctx 含 settings 键 → 解包读段。"""
    cfg = pvp_cfg({"settings": {"pvp": {"enabled": True, "level_gate": 5}}})
    assert cfg["enabled"] is True
    assert cfg["level_gate"] == 5


def test_pvp_cfg_bad_type_fallback():
    """段非法类型 → 全默认不报错。"""
    assert pvp_cfg({"settings": {"pvp": "bogus"}})["enabled"] is False
    assert pvp_cfg(None)["enabled"] is False


# ---------------------------------------------------------------------------
# /锁定玩家
# ---------------------------------------------------------------------------
def test_lock_ok_returns_target():
    """锁定成功 → 目标状态卡（等级/职业/血量/装备摘要）。"""
    r = pvp_lock(_ctx(), "123456789")
    assert r["ok"] is True
    t = r["target"]
    assert t["name"] == "小王"
    assert t["level"] == 12
    assert t["job"] == "mage"
    assert t["hp"] == 80
    assert "法杖" in t["equipment_summary"]


def test_lock_self_rejected():
    """锁定自己 → 拒绝。"""
    r = pvp_lock(_ctx(), "987654321")
    assert r["ok"] is False
    assert "自己" in r["message"]


def test_lock_disabled():
    """PVP 开关关 → 拒绝。"""
    ctx = _ctx()
    ctx["settings"] = {"pvp": {"enabled": False}}
    r = pvp_lock(ctx, "123456789")
    assert r["ok"] is False
    assert "未开启" in r["message"]


def test_lock_level_gate():
    """等级门槛：自己等级不足 → 拒绝。"""
    ctx = _ctx(level=5)
    r = pvp_lock(ctx, "123456789")
    assert r["ok"] is False
    assert "等级" in r["message"]


def test_lock_target_not_found():
    """目标不存在 → 拒绝。"""
    r = pvp_lock(_ctx(), "111111111")
    assert r["ok"] is False


def test_lock_empty_target():
    """空目标 → 拒绝。"""
    r = pvp_lock(_ctx(), "")
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 偷袭判定
# ---------------------------------------------------------------------------
def test_sneak_allowed_when_target_in_battle():
    """目标战斗会话中 → 可偷袭。"""
    ctx = _ctx(active_sessions={"123456789": {"type": "battle"}})
    assert sneak_attack_allowed(ctx, "123456789") is True


def test_sneak_not_allowed_idle():
    """目标空闲 → 不可偷袭（正常开战）。"""
    ctx = _ctx(active_sessions={})
    assert sneak_attack_allowed(ctx, "123456789") is False


def test_sneak_not_allowed_other_session():
    """目标在非战斗会话（调合）→ 不可偷袭。"""
    ctx = _ctx(active_sessions={"123456789": {"type": "alchemy"}})
    assert sneak_attack_allowed(ctx, "123456789") is False


# ---------------------------------------------------------------------------
# /攻击玩家
# ---------------------------------------------------------------------------
def test_attack_no_target():
    """未锁定 → 拒绝。"""
    r = pvp_attack(_ctx(), "1")
    assert r["ok"] is False
    assert "锁定" in r["message"]


def test_attack_target_not_found():
    """锁定目标不存在 → 拒绝。"""
    ctx = _ctx()
    ctx["pvp_target"] = "111111111"
    r = pvp_attack(ctx, "1")
    assert r["ok"] is False


def test_attack_disabled():
    """PVP 开关关 → 拒绝。"""
    ctx = _ctx()
    ctx["pvp_target"] = "123456789"
    ctx["settings"] = {"pvp": {"enabled": False}}
    r = pvp_attack(ctx, "1")
    assert r["ok"] is False


def test_attack_settle_shape():
    """攻击结算 → 结构化 result（不依赖真实 BattleEngine，模拟失败也返回结构化）。"""
    ctx = _ctx()
    ctx["pvp_target"] = "123456789"
    r = pvp_attack(ctx, "1")
    # 引擎/开战可能失败，但返回必须是结构化 dict（不抛错）
    assert isinstance(r, dict)
    assert "ok" in r


# ---------------------------------------------------------------------------
# 防刷（FR-R1 每日上限）
# ---------------------------------------------------------------------------
def test_daily_reward_limit():
    """每日奖励上限 → 奖励封顶但胜负正常结算（M11 A3 P1-2：不伪造防守方胜）。"""
    ctx = _ctx()
    ctx["pvp_target"] = "123456789"
    ctx["pvp_daily"] = {"rewards": 5}
    # 上限 5 → reward_blocked 标记（battle=None 无结算 → ended=False winner=None）
    from qbot_rpg.core.pvp import pvp_settle

    r = pvp_settle(ctx, None, None, _player())
    assert r["ok"] is True
    assert r["result"]["reward_blocked"] is True
    # 胜负不被伪造（battle 无状态 → winner 保持 None 而非 defender）
    assert r["result"]["winner"] is None
