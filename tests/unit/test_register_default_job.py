"""M13 批13 路13C · 注册默认职业接线单测（register_commands default_job B7 链）。

依据：
  - docs/细化/细化_4f_基础指令组契约.md（RUL-03/04 + B7 裁决：settings.default_job_id →
    jobs.json 首个 recommended_newbie=true 职业 → jobs 首职业；RUL-03 职业列表推荐角标）
  - docs/细化/细化_M6_三引擎与基础指令.md §四 REG-04（缺省职业与初始状态）
  - docs/m13_6b摸底.md（recommended_newbie 消费侧已实现 register_commands L204-222
    default_job / L224-237 _available_jobs / L337-340 成功消息推荐角标）
  - content/test_demo/jobs.json（批4 已落盘 4 职业：berserker recommended_newbie=false +
    alchemy/forge/fishing recommended_newbie=true）
  - 兄弟路并行（13A ctx 注入 jobs、13B 技能位装配）：本路零 NoneBot、纯函数直测
    register_commands；ctx["jobs"] 由本测试本地注入（不依赖 13A 是否落盘，importorskip 兜底）。

测试风格对齐 tests/unit/test_register_commands.py：make_ctx 模式、纯 pytest、零 NoneBot、
断言具体输出字符串。渲染仅 ✅/❌ 功能性标记（M5 裁决「不用 emoji」：🟢 推荐角标降级
纯文本「（推荐新手）」/ 列表「（推荐）」）。文件头零定时器零睡眠。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.register_commands import (
    _available_jobs,
    cmd_register,
    default_job,
    render_register_success,
    resolve_job,
)

pytest.importorskip("qbot_rpg.commands.register_commands")

# 批4 已落盘 jobs.json 语义（content/test_demo/jobs.json）：4 职业，berserker 非推荐，
# alchemy/forge/fishing recommended_newbie=true。测试侧按同一语义造映射。
_JOBS = {
    "berserker": {"name": "狂战士", "recommended_newbie": False},
    "alchemy": {"name": "炼金术士", "recommended_newbie": True},
    "forge": {"name": "铁匠", "recommended_newbie": True},
    "fishing": {"name": "渔夫", "recommended_newbie": True},
}

_STATS = {
    "hp": {"name": "生命", "type": "resource", "base": 100},
    "mp": {"name": "魔力", "type": "resource", "base": 30},
    "str": {"name": "力量", "type": "combat", "base": 12},
    "con": {"name": "体质", "type": "combat", "base": 10},
}


def make_ctx(**over):
    """未注册玩家基础 ctx（每场景新造；jobs 本地注入对齐 13A 语义）。"""
    base = {
        "registered": False,
        "player": None,
        "jobs": {k: dict(v) for k, v in _JOBS.items()},
        "stats": {k: dict(v) for k, v in _STATS.items()},
        "settings": {"default_job_id": "alchemy", "default_map": "新手村", "world_name": "艾泽拉"},
        "name_exists": lambda name: False,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# B7 链 ①：settings.default_job_id 存在 → 用它
# ---------------------------------------------------------------------------


def test_default_job_uses_configured_id():
    """B7 ①：settings.default_job_id=alchemy → default_job 返回 alchemy（含 id 冗余）。"""
    d = default_job(make_ctx())
    assert d is not None
    assert d["id"] == "alchemy"
    assert d["name"] == "炼金术士"
    assert d["recommended_newbie"] is True


def test_default_job_id_matches_test_demo_jobs():
    """13C 核对：default_job_id 首选（settings 侧配置优先于推荐标记，同 test_demo 语义）。"""
    ctx = make_ctx(settings={"default_job_id": "berserker", "default_map": "新手村"})
    d = default_job(ctx)
    assert d is not None
    assert d["id"] == "berserker"  # 显式配置优先（哪怕非推荐职业）
    assert d["recommended_newbie"] is False


def test_default_job_id_falsy_falls_to_recommended():
    """B7 防御：default_job_id 空串/None → 跳过配置直走推荐链。"""
    for bad in ("", None):
        ctx = make_ctx(settings={"default_job_id": bad, "default_map": "新手村"})
        d = default_job(ctx)
        assert d["id"] == "alchemy"  # 首个 recommended_newbie


def test_default_job_invalid_id_falls_through_chain():
    """B7 防御：default_job_id 不在 jobs 表 → 不建无效职业，继续推荐/首职业（REG-04 补白 2）。"""
    ctx = make_ctx(settings={"default_job_id": "nope", "default_map": "新手村"})
    d = default_job(ctx)
    assert d["id"] == "alchemy"  # 首个 recommended_newbie
    assert d["name"] == "炼金术士"


# ---------------------------------------------------------------------------
# B7 链 ②：无 default_job_id → 首个 recommended_newbie
# ---------------------------------------------------------------------------


def test_default_job_takes_first_recommended():
    """B7 ②：无配置 → 首个 recommended_newbie=true 职业（alchemy，非表首 berserker）。"""
    ctx = make_ctx(settings={"default_map": "新手村", "world_name": "艾泽拉"})
    d = default_job(ctx)
    assert d["id"] == "alchemy"
    assert d["recommended_newbie"] is True


def test_default_job_recommended_skips_non_recommended_head():
    """B7 ② 边界：表首为非推荐（berserker）时不得误取，必须跳过到首个推荐。"""
    jobs = {
        "berserker": {"name": "狂战士", "recommended_newbie": False},
        "forge": {"name": "铁匠", "recommended_newbie": True},
    }
    ctx = make_ctx(jobs={k: dict(v) for k, v in jobs.items()}, settings={"default_map": "新手村"})
    assert default_job(ctx)["id"] == "forge"


# ---------------------------------------------------------------------------
# B7 链 ③：无推荐标记 → jobs 首职业
# ---------------------------------------------------------------------------


def test_default_job_takes_first_when_no_recommended():
    """B7 ③：全表无 recommended_newbie=true → jobs 首职业（berserker）。"""
    jobs = {
        "berserker": {"name": "狂战士", "recommended_newbie": False},
        "mage": {"name": "法师", "recommended_newbie": False},
    }
    ctx = make_ctx(jobs={k: dict(v) for k, v in jobs.items()}, settings={"default_map": "新手村"})
    assert default_job(ctx)["id"] == "berserker"


def test_default_job_empty_jobs_returns_none():
    """B7 兜底：jobs 表缺失/空 → None（调用方回落 novice 新手兜底）。"""
    assert default_job(make_ctx(jobs=None)) is None
    assert default_job(make_ctx(jobs={})) is None


def test_default_job_entry_as_plain_string():
    """B7 兼容：jobs 表值为纯字符串（非映射）→ 按 str 职业名兜底（不崩）。"""
    ctx = make_ctx(jobs={"novice": "新手"}, settings={"default_map": "新手村"})
    d = default_job(ctx)
    assert d is not None
    assert d["id"] == "novice"
    assert d["name"] == "新手"
    assert d["recommended_newbie"] is False


# ---------------------------------------------------------------------------
# /注册 无职业参数 → 默认职业（B7 链落玩家）
# ---------------------------------------------------------------------------


def test_register_without_job_uses_default_job():
    """/注册 小明（无职业参数）→ 落 default_job_id=alchemy 炼金术士（推荐角标明示）。"""
    ctx = make_ctx()
    out = cmd_register(parse_command("/注册 小明"), ctx)
    assert "✅ 注册成功！" in out
    assert "职业：炼金术士（推荐新手） ｜ 位置：新手村" in out
    assert ctx["registered"] is True
    assert ctx["player"]["job_id"] == "alchemy"


def test_register_default_falls_to_first_recommended():
    """/注册 无参 + 无 default_job_id → 首个 recommended_newbie 落玩家。"""
    ctx = make_ctx(settings={"default_map": "新手村", "world_name": "艾泽拉"})
    out = cmd_register(parse_command("/注册 小明"), ctx)
    assert "职业：炼金术士（推荐新手）" in out
    assert ctx["player"]["job_id"] == "alchemy"


def test_register_default_falls_to_first_job():
    """/注册 无参 + 全表无推荐 → jobs 首职业落玩家（不显示推荐角标）。"""
    jobs = {
        "berserker": {"name": "狂战士", "recommended_newbie": False},
        "mage": {"name": "法师", "recommended_newbie": False},
    }
    ctx = make_ctx(
        jobs={k: dict(v) for k, v in jobs.items()},
        settings={"default_map": "新手村", "world_name": "艾泽拉"},
    )
    out = cmd_register(parse_command("/注册 小明"), ctx)
    assert "职业：狂战士 ｜ 位置：新手村" in out
    assert "（推荐新手）" not in out
    assert ctx["player"]["job_id"] == "berserker"


def test_register_default_when_jobs_absent_falls_to_novice():
    """/注册 无参 + ctx 无 jobs 表 → 兜底「新手」职业（RUL-04 降级，不硬崩）。"""
    ctx = make_ctx(jobs=None)
    out = cmd_register(parse_command("/注册 小明"), ctx)
    assert "职业：新手 ｜ 位置：新手村" in out
    assert ctx["player"]["job_id"] == "novice"


def test_register_explicit_job_beats_default():
    """/注册 带显式职业参数 → 显式职业优先于 B7 缺省链（RUL-03）。"""
    ctx = make_ctx()
    out = cmd_register(parse_command("/注册 小明 狂战士"), ctx)
    assert "职业：狂战士 ｜ 位置：新手村" in out
    assert ctx["player"]["job_id"] == "berserker"


# ---------------------------------------------------------------------------
# 推荐角标显示（RUL-03 职业列表 / TPL-4F-01 成功消息）
# ---------------------------------------------------------------------------


def test_available_jobs_recommended_badge():
    """RUL-03：可用职业列表 recommended_newbie=true 附「（推荐）」，非推荐不带。"""
    avail = _available_jobs(make_ctx())
    assert avail == ["狂战士", "炼金术士（推荐）", "铁匠（推荐）", "渔夫（推荐）"]


def test_register_success_recommended_badge_only_when_recommended():
    """TPL-4F-01：推荐角标仅 recommended_newbie 职业显示（推荐有、非推荐无）。"""
    ctx = make_ctx()
    rec = default_job(ctx)  # alchemy（推荐）
    assert "（推荐新手）" in render_register_success(
        ctx, "小明", rec, ctx.get("player") or {"attributes": None}, "新手村"
    )
    non = resolve_job(ctx, "狂战士")  # berserker（非推荐）
    assert "（推荐新手）" not in render_register_success(
        ctx, "小明", non, {"attributes": None}, "新手村"
    )


def test_job_not_found_list_shows_recommended_badge():
    """RUL-03：职业不存在黄提示列表同样带推荐角标（数据型功能标记，纯文本）。"""
    ctx = make_ctx()
    out = cmd_register(parse_command("/注册 阿伟 刺客"), ctx)
    assert out == "❌ 没有『刺客』这个职业，可用：狂战士 炼金术士（推荐） 铁匠（推荐） 渔夫（推荐）"
    assert ctx["registered"] is False and ctx["player"] is None


def test_recommended_badge_no_decorative_emoji():
    """M5 裁决：推荐角标为纯文本「（推荐）/（推荐新手）」，渲染输出零装饰 emoji。"""
    ctx = make_ctx()
    out = cmd_register(parse_command("/注册 小明"), ctx)
    assert "🟢" not in out
    assert "（推荐新手）" in out
    banned = set("🔥💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")
    for ch in out:
        assert ch not in banned, f"命中禁用装饰 emoji：{ch}"
