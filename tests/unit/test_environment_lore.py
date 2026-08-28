"""M7 环境 lore 定向测试（tests/unit/test_environment_lore.py · BCH-09 3f F-15/F-16 · R-22~R-24 · E-06）。

覆盖：
  - ambient_context 环境泛暗示（R-23 / F-15）：地图 lore.ambient[] 窗口匹配 / 零暗示
    泛化池 / 环境快照头 / rng 确定性。
  - lore_hint 定向线索（R-24 / F-16）：未 seen 零暗示 · 基础段阈值门 · 传闻段
    lore_unlocked 门 · condition 门（2a1d LC-01/LC-E）。
  - lore_view 展示数据源：no_def / not_seen / locked 不泄露 / unlocked 传闻正文。
  - unlock_lore_wired 解锁接线：codex 接口优先 · fallback 直写 · 未 seen 不写。
  - codex_commands「（传闻）」标记消费（最小侵入接线）。

零 NoneBot import；纯函数确定性（rng ctx 注入）；每函数 docstring；无 emoji。
"""

from __future__ import annotations

import sys
from typing import Any, Mapping, MutableMapping

from qbot_rpg.commands.codex_commands import cmd_codex
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.core.codex import mark_seen, unlock_lore
from qbot_rpg.core.environment_lore import (
    DEFAULT_AMBIENT_TEXT,
    RUMOR_PREFIX,
    ambient_context,
    lore_hint,
    lore_view,
    unlock_lore_wired,
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
class _Def:
    """EnemyDef 鸭子类型（id/name/raw/get）。"""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.id = str(raw.get("id") or "")
        self.name = str(raw.get("name") or self.id)
        self.raw = raw

    def get(self, key: str, default: object = None) -> object:
        return self.raw.get(key, default)


class _Reg:
    """内容注册表替身（resolve/all_ids/resolve_name）。"""

    def __init__(self, tables: Mapping[str, Mapping[str, _Def]]) -> None:
        self._t = tables

    def resolve(self, rid: str, kind: str) -> object:
        return self._t.get(kind, {}).get(rid)

    def all_ids(self, kind: str) -> tuple:
        return tuple(self._t.get(kind, {}))

    def resolve_name(self, rid: str):
        return rid.upper()


def _moon_def() -> _Def:
    """蚀月之狼定义（lore 含基础段 + 两条「传闻：」深层传闻）。"""
    return _Def({
        "id": "moon_wolf", "name": "蚀月之狼",
        "lore": [
            {"unlock": 10, "desc": "每逢雷雨之夜，传说之狼会现身于雾沼——"},
            {"unlock": 50, "desc": f"{RUMOR_PREFIX}它对雷声格外敏感，雷雨天活动频繁。"},
            {"unlock": 100, "desc": f"{RUMOR_PREFIX}其弱点在月光下才会显露。"},
        ],
    })


def _rain_lore_moon() -> _Def:
    """带 condition 门的 lore（2a1d LC-01：unlock 阈值 + condition 同时满足才显示）。"""
    return _Def({
        "id": "rain_moon", "name": "雨月",
        "lore": [
            {"unlock": 10, "desc": "它只在特定的夜晚出没。"},
            {"unlock": 30, "desc": "雷雨之夜可见其踪迹。",
             "condition": {"var": "weather", "op": "eq", "param": "雷雨"}},
        ],
    })


def _reg() -> _Reg:
    return _Reg({
        "enemy": {"moon_wolf": _moon_def(), "rain_moon": _rain_lore_moon()},
        "equipment": {"iron_sword": _Def({"id": "iron_sword", "name": "铁剑"})},
        "item": {"potion": _Def({"id": "potion", "name": "药水"})},
    })


def _ctx(**over: Any) -> MutableMapping[str, Any]:
    """基础 ctx（season/period/weather/registry/codex_state 等）。"""
    ctx: MutableMapping[str, Any] = {
        "registry": _reg(),
        "codex_state": {},
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {"event_log": []},
        "settings": {},
        "season": "秋",
        "period": "午夜",
        "weather": "雷雨",
    }
    ctx.update(over)
    return ctx


# ---------------------------------------------------------------------------
# ambient_context 环境泛暗示（R-23 / F-15 / TC-09 零暗示）
# ---------------------------------------------------------------------------
def test_ambient_context_no_map_zero_hint() -> None:
    """无 map_def → 零暗示泛化文本（绝无「此处有隐藏」措辞）+ 环境快照头。"""
    ctx = _ctx()
    text = ambient_context(ctx)
    assert text.startswith("（秋·午夜·雷雨）")
    assert "隐藏" not in text
    assert "此处" not in text
    assert "似乎有什么" not in text


def test_ambient_context_map_pool_matching_window() -> None:
    """地图 lore.ambient[] 命中窗口（秋·午夜·雷雨）→ 返回该泛暗示片段。"""
    fog = {
        "id": "fog_marsh", "name": "雾沼",
        "lore": {"ambient": [
            {"text": "你听到远处传来低沉的狼嗥，与平时的风雨声不同……",
             "window": {"season": "秋", "period": "午夜", "weather": "雷雨"}},
            {"text": "雾霭缓缓流动，林间传来零星的鸟鸣。",
             "window": {"weather": "晴"}},
        ]},
    }
    text = ambient_context(_ctx(), fog)
    assert "狼嗥" in text
    assert text.startswith("（秋·午夜·雷雨）")


def test_ambient_context_map_pool_no_match_falls_back() -> None:
    """窗口不匹配 → 回落零暗示泛化池（不泄露未命中片段）。"""
    fog = {
        "id": "fog_marsh", "name": "雾沼",
        "lore": {"ambient": [
            {"text": "只有在夏日正午才会显现的景象。",
             "window": {"season": "夏", "period": "正午"}},
        ]},
    }
    ctx = _ctx(season="春", period="白昼", weather="晴")
    text = ambient_context(ctx, fog)
    assert "显现" not in text
    assert "隐藏" not in text
    assert text.startswith("（春·白昼·晴）")


def test_ambient_context_rng_deterministic_choice() -> None:
    """rng 注入 → 同种子同调用序确定性选择（多命中池）。"""
    import random
    map_def = {
        "id": "x", "name": "X",
        "lore": {"ambient": [
            {"text": "片段甲。", "window": {"weather": "雷雨"}},
            {"text": "片段乙。", "window": {"weather": "雷雨"}},
        ]},
    }
    ctx = _ctx(rng=random.Random(42))
    a = ambient_context(ctx, map_def)
    ctx2 = _ctx(rng=random.Random(42))
    b = ambient_context(ctx2, map_def)
    assert a == b
    assert "片段" in a


def test_ambient_context_condition_expression_window() -> None:
    """window 支持条件表达式形态（var/all → eval_condition）。"""
    map_def = {
        "id": "x", "name": "X",
        "lore": {"ambient": [
            {"text": "深夜的林地传来异响。",
             "window": {"all": [
                 {"var": "season", "op": "eq", "param": "秋"},
                 {"var": "period", "op": "eq", "param": "午夜"},
             ]}},
        ]},
    }
    assert "异响" in ambient_context(_ctx(), map_def)
    ctx = _ctx(season="春", period="白昼", weather="晴")
    assert "异响" not in ambient_context(ctx, map_def)


def test_ambient_context_no_snapshot_no_header() -> None:
    """环境快照三键全缺 → 无占位头，仅正文。"""
    text = ambient_context({}, None)
    assert "（" not in text
    assert text  # 有正文


def test_ambient_context_template_placeholders() -> None:
    """泛暗示正文支持 {季节}/{时段}/{天气}/{地图} 模板占位符。"""
    map_def = {
        "id": "fog", "name": "雾沼",
        "lore": {"ambient": [
            {"text": "{季节}的{时段}，{天气}笼罩着{地图}。"},
        ]},
    }
    text = ambient_context(_ctx(), map_def)
    assert "秋的午夜，雷雨笼罩着雾沼。" in text


# ---------------------------------------------------------------------------
# lore_hint 定向线索（R-24 / F-16 / R-25 不提前泄露）
# ---------------------------------------------------------------------------
def test_lore_hint_not_seen_zero_hint() -> None:
    """未 seen → 环境泛暗示（零暗示），不泄露名称/传闻/弱点。"""
    ctx = _ctx()
    text = lore_hint(ctx, "monster", "moon_wolf")
    assert "传闻" not in text
    assert "雷声" not in text
    assert "月光" not in text
    assert "隐藏" not in text


def test_lore_hint_seen_not_unlocked_base_only() -> None:
    """已见未解锁 → 只回基础段（unlock 阈值命中），传闻段不泄露（R-25）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")  # monster 1/2 → pct 50
    text = lore_hint(ctx, "monster", "moon_wolf")
    assert "现身于雾沼" in text            # unlock 10 基础段（pct 50 ≥ 10）
    assert "雷声格外敏感" not in text      # unlock 50 传闻未解锁 → 不泄露
    assert "月光下才会显露" not in text    # unlock 100 传闻未解锁 → 不泄露


def test_lore_hint_seen_threshold_not_met_zero_hint() -> None:
    """已见但完成度低于全部 unlock 阈值 → 回落泛化（零暗示）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    ctx["codex"] = 5  # 覆盖 mark_seen 投影：完成度 5% < unlock 10
    text = lore_hint(ctx, "monster", "moon_wolf")
    assert "现身于雾沼" not in text  # unlock 10 > pct 5 → 不显示
    assert "隐藏" not in text


def test_lore_hint_seen_unlocked_rumor_only() -> None:
    """已见 + lore_unlocked → 只回「传闻：」段（定向线索，非直接坐标）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    unlock_lore(ctx, "monster", "moon_wolf")
    text = lore_hint(ctx, "monster", "moon_wolf")
    assert f"{RUMOR_PREFIX}它对雷声格外敏感" in text
    assert f"{RUMOR_PREFIX}其弱点在月光下" in text
    assert "现身于雾沼" not in text  # 基础段不混入传闻段


def test_lore_hint_unlocked_no_rumor_lines_uses_all_lore() -> None:
    """解锁但无「传闻：」前缀行（默认内容包）→ 全 lore 行作传闻正文。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    unlock_lore(ctx, "monster", "moon_wolf")
    # 覆写定义为无「传闻：」前缀（模拟默认内容包 lore 全为基础段）
    ctx["registry"] = _Reg({
        "enemy": {"moon_wolf": _Def({
            "id": "moon_wolf", "name": "蚀月之狼",
            "lore": [
                {"unlock": 10, "desc": "它弱水系，魔击破防更快。"},
                {"unlock": 50, "desc": "血量低于三成会滚石反击。"},
            ],
        })},
    })
    text = lore_hint(ctx, "monster", "moon_wolf")
    assert "弱水系" in text and "滚石反击" in text


def test_lore_hint_condition_gate() -> None:
    """lore 行 condition（2a1d LC-01）不满足 → 该行排除（LC-E 未解锁处理）。"""
    ctx = _ctx()  # weather=雷雨 → unlock 30 传闻 condition 满足
    mark_seen(ctx, "monster", "rain_moon", "雨月")
    ctx["codex"] = 50  # 全局完成度 50% ≥ unlock 30（覆盖 mark_seen 三册均值投影）
    text = lore_hint(ctx, "monster", "rain_moon")
    assert "雷雨之夜可见其踪迹" in text
    # 天气不满足 → 该行按未解锁处理（不显示）
    ctx2 = _ctx(weather="晴")
    mark_seen(ctx2, "monster", "rain_moon", "雨月")
    ctx2["codex"] = 50
    text2 = lore_hint(ctx2, "monster", "rain_moon")
    assert "雷雨之夜可见其踪迹" not in text2
    assert "特定的夜晚出没" in text2  # unlock 10 无条件行仍可见


# ---------------------------------------------------------------------------
# lore_view 展示数据源（不泄露原则）
# ---------------------------------------------------------------------------
def test_lore_view_no_def() -> None:
    """registry 无此条目 → ok=False / reason=no_def。"""
    res = lore_view(_ctx(), "monster", "ghost_wolf")
    assert res["ok"] is False and res["reason"] == "no_def"
    assert res["unlocked"] is False and res["text"] is None


def test_lore_view_not_seen_no_leak() -> None:
    """未见 → unlocked=False / text=None（不泄露）。"""
    res = lore_view(_ctx(), "monster", "moon_wolf")
    assert res["unlocked"] is False and res["text"] is None
    assert res["reason"] == "not_seen"


def test_lore_view_seen_not_unlocked_no_leak() -> None:
    """已见未解锁 → unlocked=False / text=None（传闻只在补全后出现，R-25）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    res = lore_view(ctx, "monster", "moon_wolf")
    assert res["unlocked"] is False and res["text"] is None
    assert res["reason"] == "locked"


def test_lore_view_unlocked_returns_rumor() -> None:
    """解锁 → unlocked=True + 传闻正文。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    unlock_lore(ctx, "monster", "moon_wolf")
    res = lore_view(ctx, "monster", "moon_wolf")
    assert res["unlocked"] is True
    assert res["reason"] == "unlocked"
    assert f"{RUMOR_PREFIX}它对雷声格外敏感" in res["text"]
    assert "现身于雾沼" not in res["text"]  # 传闻段仅传闻行


def test_lore_view_weapon_category_no_lore() -> None:
    """无 lore 数据的分册（weapon/item）→ 解锁后正文为空串，不崩。"""
    ctx = _ctx()
    mark_seen(ctx, "weapon", "iron_sword", "铁剑")
    unlock_lore(ctx, "weapon", "iron_sword")
    res = lore_view(ctx, "weapon", "iron_sword")
    assert res["unlocked"] is True
    assert res["text"] == ""


# ---------------------------------------------------------------------------
# unlock_lore_wired 解锁接线（F-16 / hidden_trigger 补白 5 收口）
# ---------------------------------------------------------------------------
def test_unlock_lore_wired_via_codex() -> None:
    """经 codex.unlock_lore 写 codex_state lore_unlocked（已见条目）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    res = unlock_lore_wired(ctx, "monster", "moon_wolf")
    assert res["ok"] is True and res["unlocked"] is True
    assert res["via"] == "codex"
    assert ctx["codex_state"]["monster"]["moon_wolf"]["lore_unlocked"] is True
    # 幂等：重复调用仍 ok
    res2 = unlock_lore_wired(ctx, "monster", "moon_wolf")
    assert res2["ok"] is True


def test_unlock_lore_wired_not_seen_no_write() -> None:
    """未 seen → ok=False（不写入、不泄露）。"""
    ctx = _ctx()
    res = unlock_lore_wired(ctx, "monster", "moon_wolf")
    assert res["ok"] is False
    assert res["unlocked"] is False
    assert "moon_wolf" not in ctx["codex_state"].get("monster", {})


def test_unlock_lore_wired_unknown_category() -> None:
    """未知分册 → ok=False（codex.unlock_lore 语义透传）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    res = unlock_lore_wired(ctx, "fossil", "moon_wolf")
    assert res["ok"] is False


def test_unlock_lore_wired_fallback_on_import_failure(monkeypatch) -> None:
    """codex 惰性 import 失败 → 直写 codex_state 兜底（via=fallback）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    real_import = __import__

    def _blocked(name, *a, **k):
        if name == "qbot_rpg.core.codex":
            raise ImportError("sibling unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _blocked)
    res = unlock_lore_wired(ctx, "monster", "moon_wolf")
    assert res["ok"] is True and res["unlocked"] is True
    assert res["via"] == "fallback"
    assert ctx["codex_state"]["monster"]["moon_wolf"]["lore_unlocked"] is True


def test_unlock_lore_wired_fallback_not_seen(monkeypatch) -> None:
    """兜底路径同样遵守未 seen 不写。"""
    ctx = _ctx()
    real_import = __import__

    def _blocked(name, *a, **k):
        if name == "qbot_rpg.core.codex":
            raise ImportError("sibling unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _blocked)
    res = unlock_lore_wired(ctx, "monster", "moon_wolf")
    assert res["ok"] is False and res["unlocked"] is False
    assert "moon_wolf" not in ctx["codex_state"].get("monster", {})


# ---------------------------------------------------------------------------
# codex_commands「（传闻）」标记消费（最小侵入接线）
# ---------------------------------------------------------------------------
def test_codex_category_page_rumor_mark_after_unlock() -> None:
    """解锁后 /图鉴 分册条目行尾追加「（传闻）」标记。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    reply = cmd_codex(parse_command("/图鉴 怪物"), ctx)
    assert "（传闻）" not in reply  # 未解锁零标记
    unlock_lore(ctx, "monster", "moon_wolf")
    reply2 = cmd_codex(parse_command("/图鉴 怪物"), ctx)
    assert "蚀月之狼（传闻）" in reply2
    # 未解锁条目不误标
    assert "雨月（传闻）" not in reply2
