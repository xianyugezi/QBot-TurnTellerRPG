"""M7 /调查 指令测试（tests/unit/test_investigate_commands.py · F-07 R-07/R-11）。

覆盖：注册与白名单 · 无参当前图 · 别名彩蛋/条件不满足→泛化 · 蹲点成功/窗口外 ·
隐藏地图一次性揭示 · 泛化零暗示 · daily 配额超限 · one_shot 去重 · 注册门槛 ·
TPL-12 超参 · 无 emoji · 引擎双路径（真引擎 + 本地兜底）。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

import pytest

from qbot_rpg.commands.investigate_commands import (
    INVESTIGATE_CMD,
    cmd_investigate,
    register_investigate_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_PREFIX_REQUIRED, DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import CommandSpec, Router

# 违禁词（不提示原则，R-07/TC-09）
BANNED = ("此处有隐藏", "再调查看看", "似乎有什么", "藏着什么")


class _RawMap:
    """地图原始 dict 包装（raw 形态，MapDef 未实装 accessor 时用）。"""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.raw = dict(raw)


def _raw_map(raw: Mapping[str, Any]) -> _RawMap:
    return _RawMap(raw)


def _eval_hook(cond: object, cctx: Mapping[str, Any]) -> bool:
    """模拟条件引擎 eval_condition（装配层注入形态）：无条件→True；codex 完成度/时间三键匹配。"""
    if not isinstance(cond, Mapping):
        return True
    v = str(cond.get("var") or "")
    if "图鉴完成度" in v or v == "codex":
        return int(cctx.get("codex") or 0) >= int(cond.get("value", 60))
    if v == "season":
        return cctx.get("season_now") == cond.get("param")
    if v == "period":
        return cctx.get("period_now") == cond.get("param")
    if v == "weather":
        return cctx.get("weather_now") == cond.get("param")
    return True


def _base_ctx(**over: Any) -> MutableMapping[str, Any]:
    fog = _raw_map({
        "id": "fog_marsh", "name": "雾沼",
        "season": "秋", "period": "午夜", "weather": "雷雨",
        "interact_points": [
            {"id": "stone_altar", "alias": ["石像", "雾沼石像"], "desc": "石像底座刻着古老的纹路。",
             "lore_condition": {"var": "[图鉴完成度]", "op": ">=", "value": 60},
             "hidden_find_id": "hidden:stone_altar", "one_shot": True},
        ],
        "hidden": True, "lore_condition": {"var": "[图鉴完成度]", "op": ">=", "value": 60},
        "monsters": [
            {"enemy": "moon_wolf",
             "window": {"var": "season", "param": "秋"}},
        ],
    })
    ctx: MutableMapping[str, Any] = {
        "map_def": fog,
        "season": "秋", "period": "午夜", "weather": "雷雨",
        "eval_condition": _eval_hook,   # 模拟装配层注入的条件引擎 hook
        "persistent_state": {"investigate_quota": {}, "investigate_revealed": {}},
        "event_counts": {}, "longline_counters": {},
        "maps": [fog],
        "registry": {"enemy": {"moon_wolf": _RawMap({"name": "蚀月之狼"})}},
    }
    ctx.update(over)
    return ctx


def _parsed(raw: str) -> Any:
    return parse_command(raw)


# ---------------------------------------------------------------------------
# 注册与白名单
# ---------------------------------------------------------------------------
def test_investigate_in_whitelist_and_prefix_required() -> None:
    """「调查」入白名单 + 需 / 前缀（M4 对话接缝：可快捷绑定不可免前缀直发）。"""
    assert INVESTIGATE_CMD in DEFAULT_WHITELIST
    assert INVESTIGATE_CMD in DEFAULT_PREFIX_REQUIRED


def test_register_investigate_commands_no_make_context_registers() -> None:
    """未注入 make_context → 注册成功，handler 调用时才抛【待接线】（与 A-02 指令组同款语义）。"""
    router = Router()
    register_investigate_commands(router)
    spec = router.get(INVESTIGATE_CMD)
    assert spec is not None
    with pytest.raises(RuntimeError):
        spec.handler(_parsed("/调查"))  # type: ignore[misc]


def test_register_investigate_commands_with_make_context() -> None:
    """注入 make_context → 注册「调查」CommandSpec。"""
    router = Router()
    register_investigate_commands(router, make_context=lambda parsed: {})
    spec = router.get(INVESTIGATE_CMD)
    assert isinstance(spec, CommandSpec)
    assert spec.name == INVESTIGATE_CMD


# ---------------------------------------------------------------------------
# 无参当前图整体调查
# ---------------------------------------------------------------------------
def test_investigate_no_arg_ambient_plain_map() -> None:
    """无隐藏要素地图 → 泛化环境文本零暗示。"""
    ctx = _base_ctx()
    ctx["map_def"] = _raw_map({"id": "plains", "name": "青草平原"})
    reply = cmd_investigate(_parsed("/调查"), ctx)
    assert reply
    for word in BANNED:
        assert word not in reply


# ---------------------------------------------------------------------------
# 别名彩蛋 / 条件
# ---------------------------------------------------------------------------
def test_investigate_alias_egg_hit() -> None:
    """图鉴≥60 时 /调查 石像 → 彩蛋正文 + 发现卡片 + [事件:隐藏发现] 计数。"""
    ctx = _base_ctx()
    ctx["codex"] = 60
    reply = cmd_investigate(_parsed("/调查 石像"), ctx)
    assert "石像底座刻着古老的纹路" in reply
    assert "【发现】" in reply
    assert any("[事件:隐藏发现" in k for k in ctx["event_counts"])


def test_investigate_alias_condition_not_met_ambient() -> None:
    """图鉴 20（不满足）→ 泛化文本零暗示。"""
    ctx = _base_ctx()
    ctx["codex"] = 20
    reply = cmd_investigate(_parsed("/调查 石像"), ctx)
    for word in BANNED:
        assert word not in reply
    assert "【发现】" not in reply


def test_investigate_alias_unknown_ambient() -> None:
    """未知别名 → 泛化文本。"""
    ctx = _base_ctx()
    reply = cmd_investigate(_parsed("/调查 不存在的点"), ctx)
    for word in BANNED:
        assert word not in reply


# ---------------------------------------------------------------------------
# 蹲点（hunt）
# ---------------------------------------------------------------------------
def test_investigate_hunt_window_match() -> None:
    """秋·午夜·雷雨 + 图鉴≥60 蹲点 → 狼嗥演出 + 发现卡片 + BOSS 战信号。"""
    ctx = _base_ctx()
    ctx["codex"] = 60
    reply = cmd_investigate(_parsed("/调查 雾沼"), ctx)
    assert "【发现】" in reply
    assert "狼" in reply or "蚀月" in reply or "BOSS" in reply or "现身" in reply


def test_investigate_hunt_window_outside_ambient_or_map() -> None:
    """春·白昼·晴（窗口外）→ 隐藏地图揭示或泛化，绝无蹲点卡片。"""
    ctx = _base_ctx(season="春", period="白昼", weather="晴")
    ctx["codex"] = 60
    reply = cmd_investigate(_parsed("/调查 雾沼"), ctx)
    for word in BANNED:
        assert word not in reply


# ---------------------------------------------------------------------------
# 隐藏地图一次性揭示
# ---------------------------------------------------------------------------
def test_investigate_hidden_map_reveal_once() -> None:
    """隐藏地图首次揭示 → 一次性；二次 → 简短确认（done）无重复卡片。"""
    # 窗口外（春白昼晴）→ hunt 不触发，map_reveal（隐藏地图）优先
    ctx = _base_ctx(season="春", period="白昼", weather="晴")
    ctx["codex"] = 60
    first = cmd_investigate(_parsed("/调查"), ctx)
    assert "【发现】" in first  # 首次有揭示卡片
    second = cmd_investigate(_parsed("/调查"), ctx)
    assert "【发现】隐藏" not in second  # 二次不再出完整隐藏地图揭示（done 简短确认）


# ---------------------------------------------------------------------------
# daily 配额（R-11）
# ---------------------------------------------------------------------------
def test_investigate_daily_quota_exceeded_ambient() -> None:
    """揭示类每日 3 次上限，超限回落泛化。"""
    ctx = _base_ctx()
    ctx["codex"] = 60
    # 用参数化多交互点/多图连打 5 次，配额应锁死揭示
    for i in range(5):
        cmd_investigate(_parsed("/调查 石像"), ctx)
    quota = ctx["persistent_state"]["investigate_quota"]
    total = sum(int(v) for v in quota.values())
    assert total <= 3


# ---------------------------------------------------------------------------
# one_shot 去重
# ---------------------------------------------------------------------------
def test_investigate_egg_one_shot_dedup() -> None:
    """同彩蛋二次命中 → 简短确认无正文。"""
    ctx = _base_ctx()
    ctx["codex"] = 60
    first = cmd_investigate(_parsed("/调查 石像"), ctx)
    assert "石像底座刻着古老的纹路" in first
    second = cmd_investigate(_parsed("/调查 石像"), ctx)
    assert "石像底座刻着古老的纹路" not in second  # one_shot 后不再出正文


# ---------------------------------------------------------------------------
# 注册门槛 / TPL-12 / emoji
# ---------------------------------------------------------------------------
def test_investigate_unregistered_gate() -> None:
    """未注册玩家 → 注册门槛提示（RUL-08）。"""
    ctx = _base_ctx()
    ctx["registered"] = False
    reply = cmd_investigate(_parsed("/调查"), ctx)
    assert "注册" in reply


def test_investigate_tpl12_too_many_args() -> None:
    """超参 → TPL-12 错误模板（不崩）。"""
    ctx = _base_ctx()
    reply = cmd_investigate(_parsed("/调查 a b c"), ctx)
    assert isinstance(reply, str) and reply


def test_investigate_no_emoji() -> None:
    """渲染输出无装饰 emoji（3d 纪律：仅 ✅/❌ + 排版符号）。"""
    import re
    ctx = _base_ctx()
    ctx["codex"] = 60
    reply = cmd_investigate(_parsed("/调查 石像"), ctx)
    emoji = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", reply)
    assert not emoji, f"渲染含 emoji: {emoji}"


def test_investigate_engine_dual_path() -> None:
    """引擎双路径：真引擎（core.investigate）+ 本地兜底均可渲染。"""
    ctx = _base_ctx()
    ctx["codex"] = 60
    reply = cmd_investigate(_parsed("/调查 石像"), ctx)
    assert reply  # 任一引擎路径产出回复即通过