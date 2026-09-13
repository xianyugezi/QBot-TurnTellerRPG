# -*- coding: utf-8 -*-
"""九期213：cloudsea_tactics 四件套单元测试（态势/钉位/扇区/响应槽）。"""
import pytest

from qbot_rpg.core import cloudsea_tactics as ct


class FakeHooks:
    """207 注册面替身（记录注册，不触引擎）。"""

    def __init__(self):
        self.hooks = []

    def register_trigger_proc_hook(self, h):
        self.hooks.append(h)


# ---- 态势 PostureMomentum ----

def test_posture_threshold_and_gate():
    p = ct.PostureMomentum(threshold=3)
    assert not p.is_full()
    p.register()
    p.register()
    assert p.make_counterattack_proc("反扑招") is None
    p.register()
    proc = p.make_counterattack_proc("反扑招")
    assert proc and proc["type"] == "counterattack" and proc["move"] == "反扑招"
    assert not p.is_full()  # 触发即清零（一轮一门）


def test_posture_negative_register_ignored():
    p = ct.PostureMomentum(threshold=2)
    p.register(-5)
    assert p.value == 0


# ---- 钉位 PinnedStreak ----

def test_pinned_streak_counts_and_resets():
    s = ct.PinnedStreak(threshold=2)
    s.on_round(True)
    assert not s.ready()
    s.on_round(True)
    assert s.ready() and s.consume() == 2
    assert s.streak == 0
    s.on_round(False)
    assert s.streak == 0


def test_pinned_from_snapshot_missing_keys_zero_behavior():
    assert ct.PinnedStreak.pinned_from_snapshot({}, "monster") is False
    assert ct.PinnedStreak.pinned_from_snapshot({"monster": {"marks": {"pinned": True}}}, "monster") is True


# ---- 扇区 position_bonus ----

def test_position_bonus_graylist_off():
    assert ct.position_bonus("front", "back", graylisted=False) == 0.0


def test_position_bonus_back_both_directions():
    assert ct.position_bonus("front", "back", graylisted=True) == pytest.approx(0.30)
    assert ct.position_bonus("back", "front", graylisted=True) == pytest.approx(0.30)


def test_position_bonus_side_combos_zero():
    assert ct.position_bonus("front", "left", graylisted=True) == 0.0
    assert ct.position_bonus("right", "back", graylisted=True) == 0.0


def test_position_bonus_rolling_exception_shortcircuit():
    # F08 滚转态：背击免疫短路
    assert ct.position_bonus("front", "back", ("rolling",), graylisted=True) == 0.0
    # F11 潜行态：全 fail
    assert ct.position_bonus("front", "back", ("burrowing",), graylisted=True) == 0.0


def test_position_bonus_no_face_exception():
    # F09 无面向族：加成失效（attacker 侧标记）
    assert ct.position_bonus("no_face", "back", graylisted=True) == 0.0


# ---- 响应槽 ArmedQueue ----

def test_armed_queue_fifo_and_capacity():
    q = ct.ArmedQueue(capacity=2, decay_rounds=2)
    q.arm("招A"); q.arm("招B")
    q.arm("招C")  # 容量满挤最旧
    assert len(q) == 2
    assert q.pop_trigger()["move"] == "招B"
    assert q.pop_trigger()["move"] == "招C"
    assert q.pop_trigger() is None


def test_armed_queue_dedup_and_decay():
    q = ct.ArmedQueue(capacity=3, decay_rounds=2)
    q.arm("招A"); q.arm("招A")
    assert len(q) == 1
    q.tick_round(); q.tick_round()
    assert len(q) == 0  # 两回合未触发衰减清空


# ---- 装配口 register_cloudsea_tactics ----

def test_register_via_hooks_module_and_round_head():
    fh = FakeHooks()
    handle = ct.register_cloudsea_tactics(fh, posture_move="反扑招", pinned_threshold=2)
    assert len(fh.hooks) == 1
    hook = fh.hooks[0]
    # 态势满 → round_head 返回反扑 proc
    handle["posture"].register(); handle["posture"].register(); handle["posture"].register()
    proc = hook("round_head", {"snapshot": {}})
    assert proc and proc["type"] == "counterattack"
    # 未注册面 → 引擎派发零行为由 207 测试保障；此处断言非 round_head 不处理
    assert hook("turn_end", {"snapshot": {}}) is None
