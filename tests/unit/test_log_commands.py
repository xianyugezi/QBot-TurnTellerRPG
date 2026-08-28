"""M7 3f F-03/F-04 /日志 指令壳接线单测（qbot_rpg/commands/log_commands.py）。

依据：docs/细化/细化_3f_单机向体验.md（R-01 权限分支 / R-02 六类 / R-03 分组分页 /
R-04 传记 50 段 / R-05 环境快照 / R-06 GM 系统日志）+ 细化_M7 ADR-09（is_gm=True 统一
注册「日志」，handler 内按权限分支）+ 细化_0 R-02（sys_log.default_show=20/page_size=20/
max_entries=50）+ m4 §2.2/裁决②（5 条/页、越界夹取、0/负数/非数字 → TPL-12）+ 3d
（CakeGame 式尾段 render_cake_tail、emoji 纪律）。

集成口径：直接构造全字段 ctx（event_log/audit_log/is_gm/settings/season/period/weather），
驱动命令层纯函数与装配注册；零 NoneBot。事件条目形态对齐 core/event_bus.bump_event 的
3f E-01 模型 {event_id, tag, count_key, template_id, params, snapshot, first_seen, ts}。

覆盖：注册（is_gm/白名单/gm_commands/无 make_context 抛错）· R-01 权限分支（玩家→冒险、
GM→系统、玩家显式 GM 视图→权限拒绝模板不泄露）· R-02 六类分组固定组序 · R-03 组内倒序/
5 条/页/裁决② 夹取 · 首见标记与环境快照 · 空日志 · TPL-12（0/负数/非数字/超参）·
R-04 传记（自然日聚合/天气统计/50 段环形/页码翻段/夹取）· R-06 GM 系统日志（倒序/
default_show/20 条每页/条数=N 上限 50/玩家六类隔离）· 无装饰 emoji。
"""

from __future__ import annotations

import pytest

import qbot_rpg.commands.log_commands as lc
from qbot_rpg.commands.log_commands import (
    BIO_SUBWORD,
    LOG_CMD,
    PERMISSION_DENIED,
    cmd_log,
    register_log_commands,
)
from qbot_rpg.commands.parsers import ParsedCommand
from qbot_rpg.commands.router import CommandSpec, Router

# 3d §4.2 装饰性 emoji 禁用清单（程序化扫描锚点）
BANNED_EMOJI = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸⛩️")


# ---------------------------------------------------------------------------
# 夹具：事件条目 / ctx 工厂
# ---------------------------------------------------------------------------

def _ev(tag: str, day: str, weather: str = "晴", first_seen: bool = False,
        time: str = "10:30:00", **params) -> dict:
    """六类事件条目（对齐 event_bus.bump_event 的 3f E-01 模型）。"""
    name = str(params.get("name") or "")
    return {
        "event_id": f"ev_{tag}_{day}_{name}",
        "tag": tag,
        "count_key": f"[事件:{tag}:{name}]",
        "template_id": f"tpl_{tag}",
        "params": dict(params),
        "snapshot": {"season": "秋", "period": "白昼", "weather": weather},
        "first_seen": bool(first_seen),
        "ts": f"{day}T{time}",
    }


def _audit(ts: str, command: str, params: str = "", result: str = "success",
           qq: str = "10001") -> dict:
    """GM 审计记录（对齐 gm_commands.build_audit_record 字段）。"""
    return {
        "ts": ts, "qq": qq, "group_id": "0", "command": command,
        "params": params, "target_qq": None, "result": result,
        "detail": "", "ref": None,
    }


def _ctx(**over) -> dict:
    """全字段日志指令 ctx（每测试新造避免跨用例串扰）。"""
    base = {
        "registered": True,
        "is_gm": False,
        "settings": {},
        "event_log": [],
        "audit_log": [],
        "season": "秋",
        "period": "白昼",
        "weather": "晴",
    }
    base.update(over)
    return base


def _ctx_ps(persistent_event_log: list, **over) -> dict:
    """persistent_state[\"event_log\"] 承载路径的 ctx（对齐 make_context/event_bus 落点）。"""
    ctx = _ctx(**over)
    ctx["persistent_state"] = {"event_log": list(persistent_event_log)}
    return ctx


def _pc(*args: str, raw: str = "") -> ParsedCommand:
    """构造 /日志 的 ParsedCommand（args 为 /日志 后的参数 token）。"""
    raw = raw or ("/日志 " + " ".join(args)).strip()
    return ParsedCommand(raw, command=LOG_CMD, args=list(args))


# ---------------------------------------------------------------------------
# 注册（ADR-09：is_gm=True 统一注册，保留 GM 强制 / 前缀）
# ---------------------------------------------------------------------------

def test_register_registers_log_command() -> None:
    """ADR-09：register_log_commands 注册「日志」CommandSpec（is_gm=True + 白名单参与匹配）。"""
    router = Router()
    register_log_commands(router)
    spec = router.get(LOG_CMD)
    assert isinstance(spec, CommandSpec)
    assert spec.name == "日志"
    assert spec.whitelisted is True
    assert spec.is_gm is True          # ADR-09：GM 强制 / 前缀 + 快捷禁绑 + E02 二次检查
    assert spec.handler is not None
    assert LOG_CMD in router.whitelist_names()
    assert LOG_CMD in router.gm_commands()


def test_register_without_make_context_raises() -> None:
    """make_context=None 且无注入 ctx 时 handler 调用抛 RuntimeError（【待接线】）。"""
    router = Router()
    register_log_commands(router)
    spec = router.get(LOG_CMD)
    assert spec is not None and spec.handler is not None
    with pytest.raises(RuntimeError):
        spec.handler(_pc())


def test_register_with_make_context_returns_str() -> None:
    """make_context 注入后 handler 返回 str 回复（装配注入路径）。"""
    router = Router()
    register_log_commands(router, make_context=lambda parsed: _ctx(
        event_log=[_ev("milestone", "2026-08-28", pct=50)],
    ))
    spec = router.get(LOG_CMD)
    assert spec is not None and spec.handler is not None
    out = spec.handler(_pc())
    assert isinstance(out, str)
    assert "【冒险日志】" in out


# ---------------------------------------------------------------------------
# R-01 权限分支（TC-01：玩家→冒险日志；GM→系统日志；无 GM 权限执行 GM 视图被拒）
# ---------------------------------------------------------------------------

def test_player_log_shows_adventure() -> None:
    """TC-01：玩家执行 /日志 → 冒险日志视图。"""
    ctx = _ctx(event_log=[_ev("milestone", "2026-08-28", pct=50)])
    out = cmd_log(_pc(), ctx)
    assert "【冒险日志】" in out
    assert "图鉴完成度达到 50%" in out
    assert "【系统日志】" not in out


def test_gm_log_shows_system_log() -> None:
    """TC-01：GM 执行 /日志 → 系统日志视图（不含玩家六类记录内容，R-06 隔离）。"""
    ctx = _ctx(
        is_gm=True,
        event_log=[_ev("hidden_find", "2026-08-28", weather="雨夜", name="蚀月之狼",
                       first_seen=True)],
        audit_log=[_audit("2026-08-28T12:00:00", "重载", "content_pack"),
                   _audit("2026-08-28T11:00:00", "日志")],
    )
    out = cmd_log(_pc(), ctx)
    assert "【系统日志】" in out
    assert "/重载 content_pack success by 10001" in out
    assert "【冒险日志】" not in out
    assert "蚀月之狼" not in out          # R-06：系统日志不含玩家六类记录内容


def test_player_explicit_gm_view_denied() -> None:
    """TC-01：玩家显式请求 GM 视图（/日志 系统）→ 3c 权限拒绝模板，不泄露系统日志内容。"""
    ctx = _ctx(audit_log=[_audit("2026-08-28T12:00:00", "封禁", "20002")])
    out = cmd_log(_pc("系统"), ctx)
    assert out == PERMISSION_DENIED
    assert "封禁" not in out             # 不泄露系统日志内容


def test_gm_explicit_sys_view_allowed() -> None:
    """GM 显式 /日志 系统 → 系统日志视图（与默认 /日志 同视图）。"""
    ctx = _ctx(is_gm=True, audit_log=[_audit("2026-08-28T12:00:00", "编辑")])
    out = cmd_log(_pc("系统"), ctx)
    assert "【系统日志】" in out
    assert "/编辑 success by 10001" in out


# ---------------------------------------------------------------------------
# R-02/R-03：六类分组 + 组内倒序 + 5 条/页 + 裁决② 夹取
# ---------------------------------------------------------------------------

def test_six_groups_fixed_order() -> None:
    """R-03：六类分组、组序固定（首杀→首钓冠级→剧情节点→隐藏发现→里程碑→图鉴新增）。"""
    entries = [
        _ev("codex_new", "2026-08-20", name="雾沼水蛭"),
        _ev("first_kill", "2026-08-19", name="蚀月之狼"),
        _ev("milestone", "2026-08-21", pct=50),
        _ev("first_crown", "2026-08-18", name="鲤鱼"),
        _ev("hidden_find", "2026-08-22", name="雾沼石像"),
        _ev("story_node", "2026-08-23", name="第三章"),
    ]
    ctx = _ctx(event_log=entries)
    out = cmd_log(_pc(), ctx)
    # 组序固定：首杀 → 首钓冠级 → 剧情节点 → 隐藏发现 → 里程碑（第 1 页 5 条）
    order = ["■ 首杀", "■ 首钓冠级", "■ 剧情节点", "■ 隐藏发现", "■ 里程碑"]
    idx = [out.index(h) for h in order]
    assert idx == sorted(idx)
    out2 = cmd_log(_pc("2"), ctx)        # 第 2 页 → 图鉴新增
    assert "■ 图鉴新增" in out2
    assert "图鉴新增：雾沼水蛭" in out2


def test_group_internal_desc_order() -> None:
    """R-03：组内倒序（最新在前）——后落盘的条目先展示。"""
    ctx = _ctx(event_log=[
        _ev("first_kill", "2026-08-18", time="09:00:00", name="史莱姆"),
        _ev("first_kill", "2026-08-19", time="10:00:00", name="蚀月之狼"),
        _ev("first_kill", "2026-08-20", time="11:00:00", name="巨蜥"),
    ])
    out = cmd_log(_pc(), ctx)
    i_giant = out.index("巨蜥")
    i_wolf = out.index("蚀月之狼")
    i_slime = out.index("史莱姆")
    assert i_giant < i_wolf < i_slime     # 最新在前（倒序）


def test_adventure_five_per_page_and_header() -> None:
    """R-03：每页 5 条 + 表头 `【冒险日志】第 X 页 / 共 Y 页`。"""
    entries = [_ev("first_kill", f"2026-08-{d:02d}", name=f"怪{d}") for d in range(1, 14)]
    ctx = _ctx(event_log=entries)
    out = cmd_log(_pc(), ctx)
    assert "【冒险日志】第 1 页 / 共 3 页" in out
    log_lines = [ln for ln in out.splitlines() if ln.startswith("[日志]")]
    assert len(log_lines) == 5


def test_adventure_clamp_last_page() -> None:
    """TC-03 + 裁决②：13 条 → 3 页；/日志 3 为最末页（无夹取），/日志 9 夹取最末页+提示。"""
    entries = [_ev("first_kill", f"2026-08-{d:02d}", name=f"怪{d}") for d in range(1, 14)]
    ctx = _ctx(event_log=entries)
    out = cmd_log(_pc("3"), ctx)
    assert "【冒险日志】第 3 页 / 共 3 页" in out
    assert "怪13" not in out                     # 最末页 = 最新段（怪11..怪13 在第 1 页）?
    assert "（已到最后一页）" not in out           # 合法最末页不夹取
    out9 = cmd_log(_pc("9"), ctx)
    assert "【冒险日志】第 3 页 / 共 3 页" in out9
    assert "（已到最后一页）" in out9             # 越界 → 夹取 + 提示（裁决②）
    assert "当前页：3/3" in out9


def test_first_seen_and_weather_snapshot() -> None:
    """R-02/R-05：首见标记 + 环境快照（天气）展示，对齐 3f L137 样例。"""
    ctx = _ctx(event_log=[
        _ev("hidden_find", "2026-08-28", weather="雨夜", name="蚀月之狼", first_seen=True),
        _ev("codex_new", "2026-08-28", weather="晴", name="雾沼水蛭"),
    ])
    out = cmd_log(_pc(), ctx)
    assert "首次发现隐藏要素『蚀月之狼』【首见】" in out
    assert "[日志] 10:30 雨夜 ·" in out
    assert "图鉴新增：雾沼水蛭" in out
    assert "10:30 晴" in out


def test_adventure_empty() -> None:
    """空冒险日志 → 空文案。"""
    out = cmd_log(_pc(), _ctx())
    assert out == "（暂无冒险日志）"


def test_adventure_from_persistent_state() -> None:
    """数据源兜底：persistent_state[\"event_log\"] 承载（ADR-05 落点）也能读到。"""
    ctx = _ctx_ps([_ev("milestone", "2026-08-28", pct=50)])
    out = cmd_log(_pc(), ctx)
    assert "【冒险日志】" in out
    assert "图鉴完成度达到 50%" in out


def test_adventure_local_fallback(monkeypatch) -> None:
    """兄弟路 read_log 不可用（未落盘/异常）→ 本地兼容读兜底，分组/分页/夹取口径一致。"""
    monkeypatch.setattr(lc, "_resolve_read_log", lambda: None)
    entries = [_ev("first_kill", f"2026-08-{d:02d}", name=f"怪{d}") for d in range(1, 14)]
    ctx = _ctx(event_log=entries)
    out = cmd_log(_pc("9"), ctx)
    assert "【冒险日志】第 3 页 / 共 3 页" in out
    assert "（已到最后一页）" in out
    out2 = cmd_log(_pc(), _ctx(event_log=[_ev("hidden_find", "2026-08-28",
                                              weather="雨夜", name="蚀月之狼",
                                              first_seen=True)]))
    assert "首次发现隐藏要素『蚀月之狼』【首见】" in out2


@pytest.mark.parametrize("raw,args", [
    ("/日志 0", ["0"]), ("/日志 -1", ["-1"]), ("/日志 abc", ["abc"]),
    ("/日志 1 2", ["1", "2"]), ("/日志 传记 0", [BIO_SUBWORD, "0"]),
])
def test_player_invalid_page_tpl12(raw, args) -> None:
    """裁决② + 3d §5.1：0/负数/非数字/超参/传记页码非法 → TPL-12。"""
    ctx = _ctx(event_log=[_ev("milestone", "2026-08-28", pct=50)])
    out = cmd_log(_pc(*args, raw=raw), ctx)
    assert out == f"❌ 指令不正确：{raw}。输入 /帮助 查看可用指令。"


def test_unknown_tag_not_in_adventure() -> None:
    """非六类 tag（环境事件等）不进冒险日志分组视图（六类分组边界）。"""
    ctx = _ctx(event_log=[
        {"event_id": "ev_env_1", "tag": "event", "count_key": "[事件:环境事件:雨夜]",
         "template_id": "tpl_env", "params": {}, "snapshot": {"weather": "雨夜"},
         "first_seen": False, "ts": "2026-08-28T10:30:00"},
        _ev("codex_new", "2026-08-28", name="雾沼水蛭"),
    ])
    out = cmd_log(_pc(), ctx)
    assert "图鉴新增：雾沼水蛭" in out
    assert "冒险记录" not in out                     # 非六类条目不渲染（六类分组边界）
    assert "【冒险日志】" in out
    assert "■ 图鉴新增" in out


# ---------------------------------------------------------------------------
# R-04：传记（六类 × 自然日聚合叙述段，50 段环形，页码翻段）
# ---------------------------------------------------------------------------

def test_bio_default_newest_segment() -> None:
    """R-04：/日志 传记 无页码 → 最近 1 段（按日倒序取最新）。"""
    ctx = _ctx(event_log=[
        _ev("hidden_find", "2026-08-27", weather="雨夜", name="蚀月之狼", first_seen=True),
        _ev("hidden_find", "2026-08-27", weather="雨夜", name="雾沼石像"),
        _ev("codex_new", "2026-08-28", weather="晴", name="雾沼水蛭"),
    ])
    out = cmd_log(_pc(BIO_SUBWORD), ctx)
    assert "【传记】第 1 段 / 共 2 段" in out
    assert "2026-08-28 · 图鉴新增" in out
    assert "晴×1" in out
    assert "蚀月之狼" not in out          # 只展示最近 1 段


def test_bio_page_flips_segments() -> None:
    """R-04：/日志 传记 2 → 翻到更早一段（聚合叙述段 + 计数 + 天气快照统计）。"""
    ctx = _ctx(event_log=[
        _ev("hidden_find", "2026-08-27", weather="雨夜", name="蚀月之狼"),
        _ev("hidden_find", "2026-08-27", weather="雨夜", name="雾沼石像"),
        _ev("codex_new", "2026-08-28", weather="晴", name="雾沼水蛭"),
    ])
    out = cmd_log(_pc(BIO_SUBWORD, "2"), ctx)
    assert "【传记】第 2 段 / 共 2 段" in out
    assert "2026-08-27 · 隐藏发现" in out
    assert "隐藏发现 2 条 · 雨夜×2" in out


def test_bio_cap_50_ring() -> None:
    """TC-06：52 个自然日 → 传记 50 段环形（最旧 2 段被覆盖）。"""
    entries = []
    for d in range(1, 53):                # 52 个自然日
        entries.append(_ev("codex_new", f"2026-07-{d:02d}", name=f"物{d}"))
    ctx = _ctx(event_log=entries)
    out = cmd_log(_pc(BIO_SUBWORD, "60"), ctx)   # 超段 → 夹取最末段
    assert "【传记】第 50 段 / 共 50 段" in out
    assert "（已到最后一页）" in out
    assert "2026-07-03" in out            # 最旧保留段（52 日 → 覆盖 07-01/07-02 → 剩 50 段）
    assert "2026-07-01" not in out
    assert "2026-07-02" not in out


def test_bio_empty() -> None:
    """空传记 → 空文案。"""
    out = cmd_log(_pc(BIO_SUBWORD), _ctx())
    assert out == "（暂无传记）"


# ---------------------------------------------------------------------------
# R-06：GM 系统日志（倒序 / default_show=20 / 20 条每页 / 条数=N 上限 50）
# ---------------------------------------------------------------------------

def test_sys_log_newest_first() -> None:
    """R-06：系统日志最近事件倒序（最新在前）。"""
    ctx = _ctx(is_gm=True, audit_log=[
        _audit("2026-08-28T10:00:00", "重载", "pack_a"),
        _audit("2026-08-28T11:00:00", "日志"),
        _audit("2026-08-28T12:00:00", "编辑"),
    ])
    out = cmd_log(_pc(), ctx)
    assert "【系统日志】第 1 页 / 共 1 页" in out
    assert out.index("/编辑") < out.index("/日志") < out.index("/重载")


def test_sys_log_default_show_and_page_size() -> None:
    """R-06：默认展示 20 条（sys_log.default_show），分页 20 条/页（sys_log.page_size）。"""
    ctx = _ctx(is_gm=True, audit_log=[
        _audit(f"2026-08-28T{i:02d}:00:00", "日志", params=f"p{i}")
        for i in range(1, 26)             # 25 条审计
    ])
    out = cmd_log(_pc(), ctx)
    assert "【系统日志】第 1 页 / 共 1 页" in out     # 默认 20 条 → 1 页
    assert "[25:00:00]" in out and "[01:00:00]" not in out   # 最近 20 条（p6..p25）
    out2 = _pc("2")
    out2.kv = [{"key": "条数", "value": "50"}]       # 条数=N 走 kv（对齐 gm_commands 5b G8）
    out2 = cmd_log(out2, ctx)  # type: ignore[assignment]
    assert "【系统日志】第 2 页 / 共 2 页" in out2  # type: ignore[operator]  # 25 条 → 20/5 两页
    assert "[01:00:00]" in out2  # type: ignore[operator]  # 第 2 页含最旧 p1


def test_sys_log_settings_override() -> None:
    """settings.sys_log 可配（default_show/max_entries 覆盖缺省）。"""
    ctx = _ctx(is_gm=True,
               settings={"sys_log": {"default_show": 5, "max_entries": 10}},
               audit_log=[_audit(f"2026-08-28T{i:02d}:00:00", "日志", params=f"p{i}")
                          for i in range(1, 13)])
    out = cmd_log(_pc(), ctx)
    assert "【系统日志】第 1 页 / 共 1 页" in out     # 窗口 10 条 → 展示 5 条
    assert "p12" in out and "p6" not in out


def test_sys_log_empty() -> None:
    """空系统日志 → 空文案。"""
    out = cmd_log(_pc(), _ctx(is_gm=True))
    assert out == "（暂无系统日志）"


@pytest.mark.parametrize("raw,args", [
    ("/日志 0", ["0"]), ("/日志 -1", ["-1"]), ("/日志 abc", ["abc"]),
    ("/日志 1 2", ["1", "2"]), ("/日志 条数=abc", []),
])
def test_gm_invalid_tpl12(raw, args) -> None:
    """GM 视图页码/条数非法 → TPL-12。"""
    ctx = _ctx(is_gm=True, audit_log=[_audit("2026-08-28T10:00:00", "日志")])
    kv = []
    if "条数" in raw:
        kv = [{"key": "条数", "value": raw.split("=")[-1]}]
    parsed = _pc(*args, raw=raw)
    parsed.kv = kv
    out = cmd_log(parsed, ctx)
    assert out == f"❌ 指令不正确：{raw}。输入 /帮助 查看可用指令。"


# ---------------------------------------------------------------------------
# 3d 纪律：无装饰 emoji（仅 ✅/❌ 功能性标记 + 排版符号）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ctx_factory", [
    lambda: _ctx(event_log=[_ev("hidden_find", "2026-08-28", weather="雨夜",
                                name="蚀月之狼", first_seen=True),
                            _ev("milestone", "2026-08-28", pct=50)]),
    lambda: _ctx(event_log=[_ev("hidden_find", "2026-08-27", weather="雨夜", name="蚀月之狼"),
                            _ev("codex_new", "2026-08-28", weather="晴", name="雾沼水蛭")]),
    lambda: _ctx(is_gm=True, audit_log=[_audit("2026-08-28T10:00:00", "重载", "pack_a")]),
])
def test_no_decorative_emoji(ctx_factory) -> None:
    """3d D-01：冒险/传记/系统日志输出零装饰 emoji（仅 ✅/❌ 功能性标记 + 排版符号）。"""
    ctx = ctx_factory()
    outs = [cmd_log(_pc(), ctx), cmd_log(_pc(BIO_SUBWORD), ctx)]
    for out in outs:
        for ch in out:
            assert ch not in BANNED_EMOJI, f"输出含禁用 emoji: {ch!r} in {out!r}"


# ---------------------------------------------------------------------------
# 确定性 / 纯函数
# ---------------------------------------------------------------------------

def test_deterministic_same_input_same_output() -> None:
    """纯函数确定性：同 ctx 同参多次调用输出一致。"""
    ctx = _ctx(event_log=[
        _ev("first_kill", "2026-08-18", time="09:00:00", name="史莱姆"),
        _ev("hidden_find", "2026-08-28", weather="雨夜", name="蚀月之狼", first_seen=True),
        _ev("milestone", "2026-08-28", pct=50),
    ])
    assert cmd_log(_pc(), ctx) == cmd_log(_pc(), ctx)
    assert cmd_log(_pc(BIO_SUBWORD), ctx) == cmd_log(_pc(BIO_SUBWORD), ctx)
    ctx_gm = _ctx(is_gm=True, audit_log=[_audit("2026-08-28T10:00:00", "重载", "pack_a")])
    assert cmd_log(_pc(), ctx_gm) == cmd_log(_pc(), ctx_gm)