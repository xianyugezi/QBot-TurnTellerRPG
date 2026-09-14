# -*- coding: utf-8 -*-
"""九期215：战报八段终案测试（intent 四字段 / tpl 五新 key / D-01 emoji / sender 频控）。"""
import pytest

from qbot_rpg.core import cloudsea_emoji as ce
from qbot_rpg.core.monster_intent import build_intent
from qbot_rpg.core.templates import DEFAULT_TEMPLATES, PLACEHOLDER_WHITELIST
from qbot_rpg_bridge.cloudsea_sender import CloudseaSender, MENTION_CLASSES


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


# ---- intent 四扩展字段（G1B 接口）----

def test_intent_without_ext_unchanged_shape():
    it = build_intent("m_a", {"intent": "伤害"}, {})
    assert set(it) == {"level", "category", "action_id", "name_revealed", "chain_preview", "progress"}


def test_intent_ext_from_action_def():
    adef = {"stage_shift": {"at": 0.5, "to": "enraged"}, "windup": 2, "damage_tier": "🎯重"}
    it = build_intent("m_b", adef, {})
    assert it["stage_shift"] == {"at": 0.5, "to": "enraged"}
    assert it["windup"] == 2
    assert it["damage_tier"] == "🎯重"
    assert "target_ref" not in it  # 未声明不入 dict


def test_intent_ext_explicit_params_override():
    it = build_intent("m_c", {"windup": 1}, {}, windup=3, target_ref="player.main")
    assert it["windup"] == 3 and it["target_ref"] == "player.main"


# ---- 战报五新 key（template_table.json 全量表；白名单由表占位符自动派生）----

def test_tpl_five_new_keys_and_whitelist_sync():
    for key in ("battle_stage_shift_line", "battle_windup_unknown", "battle_windup_ready",
                "battle_merge_summary", "battle_mention_line"):
        assert key in DEFAULT_TEMPLATES, key
        assert key in PLACEHOLDER_WHITELIST, key
    text = DEFAULT_TEMPLATES["battle_merge_summary"].format(n=3, window_sec=30)
    assert "3" in text and "30" in text


# ---- D-01 emoji 白名单 ----

def test_emoji_whitelist_unregistered_always_ok():
    ok, unknown = ce.validate_emoji_use("⚗️ 深度炼成 ▫")
    assert ok and unknown == ()


def test_emoji_whitelist_registered_validation():
    ce.register_emoji_whitelist(["⚗️", "🌀", "◈"])
    try:
        ok, unknown = ce.validate_emoji_use("⚗️ 蓄势 🌀")
        assert ok and unknown == ()
        ok, unknown = ce.validate_emoji_use("⚗️ ⚔️ ✅")
        assert not ok and "⚔️" in unknown and "✅" not in unknown  # ✅ 功能标记恒放行
    finally:
        ce.register_emoji_whitelist([])


# ---- 壳层 sender 频控 ----

def _mk_sender(window=30.0, **kw):
    sent, clock = [], FakeClock()
    s = CloudseaSender(send=sent.append, merge_window_sec=window, clock=clock, **kw)
    return s, sent, clock


def test_sender_merge_window_lazy_expiry():
    s, sent, clock = _mk_sender(window=30)
    s.feed("战报一"); s.feed("战报二")
    assert sent == [] and s.pending() == 2  # 窗内攒住
    clock.advance(31)
    n = s.flush()
    assert n == 2
    assert len(sent) == 2  # 条目合并体 + 摘要行
    assert "已合并 2 条战报" in sent[-1] and "30" in sent[-1]


def test_sender_mention_class_flushes_and_direct_sends():
    s, sent, clock = _mk_sender(window=30)
    s.feed("战报一")
    clock.advance(31)
    s.feed("Boss 首破！", cls="boss_first", mention="@全体成员")
    assert "战报一" in sent[0]                     # 合并窗先出
    assert "已合并" in sent[1]
    assert sent[2].startswith("@全体成员") and "Boss 首破" in sent[2]


def test_sender_mention_classes_four():
    assert MENTION_CLASSES == ("boss_first", "urgent", "personal", "system")


def test_sender_emoji_stripped_on_violation():
    ce.register_emoji_whitelist(["⚗️"])
    try:
        s, sent, _ = _mk_sender(
            window=0.0, emoji_validator=ce.validate_emoji_use)
        s.feed("⚗️ 越白名单 ⚔️ 文本")  # window=0 → 立即到期合并发送
        out = "\n".join(sent)
        assert "⚗️" in out and "⚔️" not in out
    finally:
        ce.register_emoji_whitelist([])
