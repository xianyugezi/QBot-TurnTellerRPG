"""事件键解析中心测试（tests/unit/test_event_keys.py · M12.5 批5 路5A）。

覆盖 resolve_event_key：无配置回退默认键 / 配置改名出新键 / 配置完整键
直接透传 / events 段缺失回退 / ctx 与 settings 双入参形态 / 防呆与兜底。
"""

from __future__ import annotations

from qbot_rpg.core.event_bus import (
    EVENT_KEY,
    EVENT_KEY_DEFAULTS,
    resolve_event_key,
)


def _mk_ctx(events: dict | None = None) -> dict:
    """构造最小 ctx：settings 子表承载 events 段（装配口径 ctx["settings"]）。"""
    settings: dict = {}
    if events is not None:
        settings["events"] = events
    return {"settings": settings}


# ---------------------------------------------------------------------------
# 无配置 / events 段缺失 → 默认键回退（向后兼容零破坏）
# ---------------------------------------------------------------------------
def test_no_config_returns_default_key() -> None:
    """零配置 ctx（空 settings）→ 默认键 `[事件:签到]`（等价现字面量）。"""
    assert resolve_event_key(_mk_ctx(), "签到") == "[事件:签到]"
    assert resolve_event_key(_mk_ctx(), "副本通关") == "[事件:副本通关]"
    assert resolve_event_key(_mk_ctx(), "等级提升") == "[事件:等级提升]"


def test_missing_events_section_falls_back() -> None:
    """settings 无 events 段 → 回退 EVENT_KEY_DEFAULTS（零破坏）。"""
    assert resolve_event_key(_mk_ctx(), "怪物击杀") == "[事件:怪物击杀]"
    # settings 为空 dict 与完全无 settings 的 ctx 等价
    assert resolve_event_key({"settings": {}}, "任务完成") == "[事件:任务完成]"
    assert resolve_event_key({}, "成就达成") == "[事件:成就达成]"


def test_settings_direct_form_matches_ctx_form() -> None:
    """settings 直传与 ctx 包裹两形态结果一致（resolve 中心双入参契约）。"""
    settings = {"events": {"签到": "每日打卡"}}
    assert resolve_event_key(settings, "签到") == "[事件:每日打卡]"
    assert resolve_event_key(_mk_ctx({"签到": "每日打卡"}), "签到") == "[事件:每日打卡]"


# ---------------------------------------------------------------------------
# 配置改名（name 段可配）→ 新键
# ---------------------------------------------------------------------------
def test_configured_rename_produces_new_key() -> None:
    """events 段命中 → 配置 name 段包 `[事件:...]` 外壳。"""
    events = {"签到": "每日打卡", "副本通关": "地牢征服"}
    assert resolve_event_key(_mk_ctx(events), "签到") == "[事件:每日打卡]"
    assert resolve_event_key(_mk_ctx(events), "副本通关") == "[事件:地牢征服]"


def test_configured_others_still_default() -> None:
    """部分配置：命中项用配置，未命中项回退默认（同名配置不泄漏）。"""
    events = {"签到": "每日打卡"}
    assert resolve_event_key(_mk_ctx(events), "签到") == "[事件:每日打卡]"
    assert resolve_event_key(_mk_ctx(events), "等级提升") == "[事件:等级提升]"


def test_configured_value_whitespace_stripped() -> None:
    """配置值带空白 → strip 后使用。"""
    assert resolve_event_key(_mk_ctx({"签到": " 每日打卡 "}), "签到") == "[事件:每日打卡]"


def test_configured_empty_value_falls_back() -> None:
    """配置值空串/None → 视同未命中，回退默认键（零破坏）。"""
    assert resolve_event_key(_mk_ctx({"签到": ""}), "签到") == "[事件:签到]"
    assert resolve_event_key(_mk_ctx({"签到": None}), "签到") == "[事件:签到]"


# ---------------------------------------------------------------------------
# 配置完整键（含前缀）→ 直接透传
# ---------------------------------------------------------------------------
def test_configured_full_key_passthrough() -> None:
    """配置值为完整键（已以 [ 开头）→ 原样透传（可配自定义前缀外壳）。"""
    events = {"签到": "[milestone:每日打卡]"}
    assert resolve_event_key(_mk_ctx(events), "签到") == "[milestone:每日打卡]"
    events2 = {"签到": "[事件:每日打卡]"}
    assert resolve_event_key(_mk_ctx(events2), "签到") == "[事件:每日打卡]"


# ---------------------------------------------------------------------------
# 默认表与防呆兜底
# ---------------------------------------------------------------------------
def test_defaults_table_covers_audit_keys() -> None:
    """EVENT_KEY_DEFAULTS 覆盖审计 13 类事件（默认 name 段 = 现键名）。"""
    keys = [
        "签到", "副本通关", "等级提升", "怪物击杀", "任务完成", "图鉴新增",
        "成就达成", "首杀", "首钓冠级", "隐藏发现", "里程碑", "环境事件",
        "NPC对话",
    ]
    assert set(keys) <= set(EVENT_KEY_DEFAULTS)
    for name in keys:
        assert EVENT_KEY_DEFAULTS[name] == name
        assert resolve_event_key(_mk_ctx(), name) == f"{EVENT_KEY}{name}]"


def test_unknown_name_falls_back_to_itself() -> None:
    """默认表外事件名 → 以其自身为 name 段回退（向前兼容扩展）。"""
    assert resolve_event_key(_mk_ctx(), "神鱼支线完成") == "[事件:神鱼支线完成]"


def test_already_full_key_passthrough_defensive() -> None:
    """入参已带外壳（迁移期双解析防呆）→ 原样直通不二次包壳。"""
    assert resolve_event_key(_mk_ctx(), "[事件:签到]") == "[事件:签到]"
    # 配置命中但事件名已为完整键：事件名直通优先
    events = {"[事件:签到]": "每日打卡"}
    assert resolve_event_key(_mk_ctx(events), "[事件:签到]") == "[事件:签到]"


def test_empty_or_non_mapping_input_tolerated() -> None:
    """空事件名 / None / 非 Mapping 入参 → 不抛（对齐本模块兜底精神）。"""
    assert resolve_event_key(_mk_ctx(), "") == ""
    assert resolve_event_key(_mk_ctx(), None) == ""  # type: ignore[arg-type]
    assert resolve_event_key(None, "签到") == "[事件:签到]"
    assert resolve_event_key("not-a-mapping", "签到") == "[事件:签到]"
