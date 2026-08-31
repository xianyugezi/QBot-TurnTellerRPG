"""M10 批次0·路0A：fishing_settings 模块单测（settings.fishing 读段容错归一）。

文件名：tests/unit/test_fishing_settings.py
创建时间：2026-08-31
作者：Hermes 子agent-0A（M10 钓鱼数据层 路0A）
功能描述：qbot_rpg.core.fishing_settings 纯函数直测（零 NoneBot、确定性、零定时器）：
  - fishing_cfg 三态容错：settings 全量 dict（含 fishing 段）/ settings.fishing 段本身
    / ctx 形态（含 settings 键）/ None / 非 Mapping → 缺段全默认兜底
  - 默认值逐键断言（对齐定稿 §三 行 72-82 九键）
  - 部分键覆盖合并：显式键生效、缺省保留默认
  - 非法类型逐键兜底：mode 非 str / 嵌套对象非法 / daily_limit 非 int / energy 非 bool
    / king_event 逐键容错
  - mode 枚举不拦（V4 归路0C 校验器，本路只做类型容错）
  - 深拷贝隔离：调用方改动不污染 DEFAULT_FISHING_SETTINGS
  - FISHING_SETTINGS_FIELD_DEFS / fishing_settings_meta 结构断言

依据：
  - docs/m10_shared_contract.md §一（settings.fishing 段字段表，默认值与定稿逐键一致）
    / §四（路0A 文件清单：core/fishing_settings.py + test_fishing_settings.py +
    settings.json）/ §五 铁律（M43 docstring 禁词：零定时器/零睡眠）
  - 钓鱼玩法设计定稿 v1.0.1 §三 配置结构（行 72-82 九键默认值）
  - 细化_2c1a §1.0（F-12 preferred_bait 引用 bait_ids）
  - 模式参考：tests/unit/test_forge_settings.py（M9 路0B 同构）
"""

from __future__ import annotations

from typing import Any, Dict, cast

from qbot_rpg.core.fishing_settings import (
    DEFAULT_FISHING_SETTINGS,
    FISHING_SETTINGS_FIELD_DEFS,
    FISHING_SETTINGS_KEYS,
    MODE_VALUES,
    fishing_cfg,
    fishing_settings_meta,
)


def _as_dict(obj: object) -> Dict[str, Any]:
    """fishing_cfg 返回类型为 Mapping[str, object]，测试内按 Dict[str, Any] 读取以做嵌套断言。"""
    return cast(Dict[str, Any], obj)


# ---------------------------------------------------------------------------
# 公共：默认值 / 键集 / 深拷贝隔离
# ---------------------------------------------------------------------------
def test_defaults_values() -> None:
    """默认值逐键断言（定稿 §三 行 72-82 九键，契约 §一 逐键一致）。"""
    got = fishing_cfg({})
    assert isinstance(got, dict)
    assert got["mode"] == "full"
    assert got["bait_ids"] == ["饵_蚯蚓", "饵_面团", "饵_小鱼", "饵_黄金虫", "饵_龙涎"]
    assert got["bait_bonus"] == {"rare": 8, "gold": 2}
    assert got["rod_full_bonus"] == {"rare": 4, "gold": 2}
    assert got["crown_thresholds"] == {"reverse": 5, "silver": 85, "gold": 95}
    assert got["wait_sec"] == {"min": 300, "max": 900}
    assert got["daily_limit"] == 20
    assert got["energy"] == {"enabled": False}
    assert got["king_event"] == {"enabled": True, "window_daily": 2, "chance": 0.3}


def test_keys_set_matches_contract() -> None:
    """键集 = FISHING_SETTINGS_KEYS 9 键（契约 §一 字段表）。"""
    got = fishing_cfg({})
    assert set(got) == set(FISHING_SETTINGS_KEYS)
    assert len(FISHING_SETTINGS_KEYS) == 9


def test_defaults_deepcopy_isolation() -> None:
    """返回值深拷贝隔离：调用方改动不污染 DEFAULT_FISHING_SETTINGS 常量。"""
    got = _as_dict(fishing_cfg({}))
    got["bait_bonus"]["rare"] = 999
    got["bait_ids"].append("饵_改")
    got["king_event"]["chance"] = 0.9
    assert _as_dict(DEFAULT_FISHING_SETTINGS)["bait_bonus"]["rare"] == 8
    assert DEFAULT_FISHING_SETTINGS["bait_ids"] == [
        "饵_蚯蚓", "饵_面团", "饵_小鱼", "饵_黄金虫", "饵_龙涎",
    ]
    assert DEFAULT_FISHING_SETTINGS["king_event"]["chance"] == 0.3  # type: ignore[index]


# ---------------------------------------------------------------------------
# fishing_cfg：三态容错（缺段 / 段本身 / ctx 形态）
# ---------------------------------------------------------------------------
def test_defaults_when_no_fishing_section() -> None:
    """settings 无 fishing 段 / 段 None / 段空 / 非 Mapping / None → 全默认兜底。"""
    cases: list[object] = [
        {},
        {"currencies": []},
        {"fishing": None},
        {"fishing": {}},
        {"fishing": "not-a-map"},
        None,
        "not-a-map",
        42,
    ]
    for raw in cases:
        got = fishing_cfg(raw)
        assert isinstance(got, dict)
        assert set(got) == set(FISHING_SETTINGS_KEYS)
        for key in FISHING_SETTINGS_KEYS:
            assert got[key] == DEFAULT_FISHING_SETTINGS[key], (raw, key)
        # 嵌套默认对象不被调用方改动污染（深拷贝隔离）
        assert got["bait_bonus"] is not DEFAULT_FISHING_SETTINGS["bait_bonus"]


def test_section_dict_reads_fishing_key() -> None:
    """settings 全量 dict 含 fishing 段 → 取 data["fishing"] 段。"""
    raw = {
        "default_map": "start_village",
        "fishing": {"mode": "simple", "daily_limit": 5},
    }
    got = fishing_cfg(raw)
    assert got["mode"] == "simple"
    assert got["daily_limit"] == 5
    # 未覆盖键保留默认
    assert got["bait_ids"] == DEFAULT_FISHING_SETTINGS["bait_ids"]


def test_section_itself_passed_directly() -> None:
    """直接传 settings.fishing 段本身（无 fishing 键）→ 逐键读取。"""
    section = {"mode": "off", "bait_bonus": {"rare": 10}}
    got = fishing_cfg(section)
    assert got["mode"] == "off"
    assert got["bait_bonus"] == {"rare": 10, "gold": 2}
    assert got["daily_limit"] == 20


def test_ctx_shape_with_settings_key() -> None:
    """ctx 形态（含 settings 键且为 Mapping）→ 先解包 settings 再取段。"""
    ctx = {"qid": "1", "settings": {"fishing": {"mode": "simple"}}}
    got = fishing_cfg(ctx)
    assert got["mode"] == "simple"
    assert got["daily_limit"] == 20


def test_ctx_settings_not_mapping_falls_back() -> None:
    """ctx 形态但 settings 非 Mapping → 全默认兜底。"""
    got = fishing_cfg({"settings": "bad"})
    assert got == DEFAULT_FISHING_SETTINGS
    got2 = fishing_cfg({"settings": 5})
    assert got2 == DEFAULT_FISHING_SETTINGS


# ---------------------------------------------------------------------------
# fishing_cfg：部分键覆盖（缺省保留默认）
# ---------------------------------------------------------------------------
def test_partial_keys_override() -> None:
    """部分键覆盖：显式键生效，缺省保留默认。"""
    raw = {"fishing": {"mode": "simple"}}
    got = fishing_cfg(raw)
    assert got["mode"] == "simple"
    for key in ("bait_ids", "bait_bonus", "rod_full_bonus", "crown_thresholds",
                "wait_sec", "daily_limit", "energy", "king_event"):
        assert got[key] == DEFAULT_FISHING_SETTINGS[key], key


def test_full_override_all_keys() -> None:
    """全键显式覆盖一次断言。"""
    raw = {"fishing": {
        "mode": "simple",
        "bait_ids": ["饵_龙涎"],
        "bait_bonus": {"rare": 20, "gold": 5},
        "rod_full_bonus": {"rare": 8, "gold": 4},
        "crown_thresholds": {"reverse": 1, "silver": 90, "gold": 99},
        "wait_sec": {"min": 0, "max": 600},
        "daily_limit": 3,
        "energy": {"enabled": True},
        "king_event": {"enabled": False, "window_daily": 1, "chance": 0.1},
    }}
    got = _as_dict(fishing_cfg(raw))
    assert got["mode"] == "simple"
    assert got["bait_ids"] == ["饵_龙涎"]
    assert got["bait_bonus"] == {"rare": 20, "gold": 5}
    assert got["rod_full_bonus"] == {"rare": 8, "gold": 4}
    assert got["crown_thresholds"] == {"reverse": 1, "silver": 90, "gold": 99}
    assert got["wait_sec"] == {"min": 0, "max": 600}
    assert got["daily_limit"] == 3
    assert got["energy"] == {"enabled": True}
    assert got["king_event"] == {"enabled": False, "window_daily": 1, "chance": 0.1}


# ---------------------------------------------------------------------------
# fishing_cfg：非法类型逐键兜底
# ---------------------------------------------------------------------------
def test_mode_non_str_falls_back() -> None:
    """mode 非 str / 空串 / None / bool → 回退默认 full。"""
    for bad in (None, 1, True, "", "   ", ["full"], {"mode": "full"}):
        got = fishing_cfg({"fishing": {"mode": bad}})
        assert got["mode"] == "full", bad


def test_mode_enum_not_validated_here() -> None:
    """mode 任意非空 str 通过（含非枚举值）——V4 枚举硬错由校验器（路0C）拦，读段不拦。"""
    for value in MODE_VALUES + ("weird", "FULL"):
        got = fishing_cfg({"fishing": {"mode": value}})
        assert got["mode"] == value


def test_bait_ids_filters_non_str() -> None:
    """bait_ids 含非 str 元素 → 过滤 str 元素生效（宽松容错）。"""
    got = fishing_cfg({"fishing": {"bait_ids": ["饵_蚯蚓", 1, None, "饵_龙涎"]}})
    assert got["bait_ids"] == ["饵_蚯蚓", "饵_龙涎"]


def test_bait_ids_empty_or_wrong_type_falls_back() -> None:
    """bait_ids 空列表 / 全非法 / 非 list → 回退默认 5 档。"""
    for bad in ([], ["   "], [1, 2], "饵_蚯蚓", {"a": 1}, 5, None):
        got = fishing_cfg({"fishing": {"bait_ids": bad}})
        assert got["bait_ids"] == DEFAULT_FISHING_SETTINGS["bait_ids"], bad


def test_nested_obj_partial_merge() -> None:
    """嵌套对象部分覆盖：显式合法键覆盖，缺省保留默认。"""
    got = fishing_cfg({"fishing": {"crown_thresholds": {"reverse": 10}}})
    assert got["crown_thresholds"] == {"reverse": 10, "silver": 85, "gold": 95}
    got2 = fishing_cfg({"fishing": {"wait_sec": {"min": 0}}})
    assert got2["wait_sec"] == {"min": 0, "max": 900}


def test_nested_obj_wrong_type_falls_back() -> None:
    """嵌套对象非 Mapping / 非法值类型 → 逐键回退默认。"""
    # 整段非对象 → 全默认
    for bad in (None, "x", 5, ["a"], True):
        got = fishing_cfg({"fishing": {"bait_bonus": bad}})
        assert got["bait_bonus"] == {"rare": 8, "gold": 2}, bad
    # 段内非法键值（非 int / bool / 负 / str）→ 保留默认，不污染其他键
    raw = {"fishing": {"bait_bonus": {"rare": "高", "gold": True}}}
    got = fishing_cfg(raw)
    assert got["bait_bonus"] == {"rare": 8, "gold": 2}
    raw2 = {"fishing": {"crown_thresholds": {"reverse": -1, "silver": "85", "gold": 3.5}}}
    got2 = fishing_cfg(raw2)
    assert got2["crown_thresholds"] == {"reverse": 5, "silver": 85, "gold": 95}
    raw3 = {"fishing": {"wait_sec": {"min": "abc", "max": None}}}
    got3 = fishing_cfg(raw3)
    assert got3["wait_sec"] == {"min": 300, "max": 900}


def test_daily_limit_nonneg_int_only() -> None:
    """daily_limit 仅非负 int 生效（排除 bool/float/负数/str）。"""
    for bad in (None, True, False, 3.5, -1, "20", "abc"):
        got = fishing_cfg({"fishing": {"daily_limit": bad}})
        assert got["daily_limit"] == 20, bad
    got = fishing_cfg({"fishing": {"daily_limit": 5}})
    assert got["daily_limit"] == 5


def test_energy_bool_only() -> None:
    """energy 段非 Mapping / enabled 非 bool → 回退默认 false。"""
    for bad in (None, "on", 1, 0, ["t"], {"enabled": "yes"}, {"enabled": 1}):
        got = fishing_cfg({"fishing": {"energy": bad}})
        assert got["energy"] == {"enabled": False}, bad
    got = fishing_cfg({"fishing": {"energy": {"enabled": True}}})
    assert got["energy"] == {"enabled": True}


def test_king_event_partial_merge_and_fallback() -> None:
    """king_event 逐键合并：enabled(bool)/window_daily(非负 int)/chance(数字)；非法回退。"""
    got = fishing_cfg({"fishing": {"king_event": {"window_daily": 1}}})
    assert got["king_event"] == {"enabled": True, "window_daily": 1, "chance": 0.3}
    # 非法类型逐键回退（保持其余默认）
    raw = {"fishing": {"king_event": {"enabled": "yes", "window_daily": -2, "chance": "高"}}}
    got2 = fishing_cfg(raw)
    assert got2["king_event"] == {"enabled": True, "window_daily": 2, "chance": 0.3}
    # 整段非对象 → 全默认
    got3 = fishing_cfg({"fishing": {"king_event": 5}})
    assert got3["king_event"] == {"enabled": True, "window_daily": 2, "chance": 0.3}
    # chance 接受 float / int
    got4 = _as_dict(fishing_cfg({"fishing": {"king_event": {"chance": 0.5}}}))
    assert got4["king_event"]["chance"] == 0.5


def test_unknown_keys_passthrough() -> None:
    """未知键默认放行不破坏加载（契约 §五 铁律 7 / §2.3 兜底）。"""
    raw = {"fishing": {"mode": "full", "future_key": {"a": 1}, "another_unknown": "x"}}
    got = fishing_cfg(raw)
    assert got["mode"] == "full"
    assert set(got) == set(FISHING_SETTINGS_KEYS)  # 未知键不进入归一结果


# ---------------------------------------------------------------------------
# FISHING_SETTINGS_FIELD_DEFS / fishing_settings_meta 结构断言
# ---------------------------------------------------------------------------
def test_field_defs_cover_all_keys() -> None:
    """FISHING_SETTINGS_FIELD_DEFS 覆盖 9 键且键集与 FISHING_SETTINGS_KEYS 一致。"""
    assert set(FISHING_SETTINGS_FIELD_DEFS) == set(FISHING_SETTINGS_KEYS)
    assert FISHING_SETTINGS_FIELD_DEFS["mode"].type == "enum"
    assert FISHING_SETTINGS_FIELD_DEFS["mode"].enum == MODE_VALUES
    assert FISHING_SETTINGS_FIELD_DEFS["mode"].default == "full"
    assert FISHING_SETTINGS_FIELD_DEFS["bait_ids"].type == "list"
    assert FISHING_SETTINGS_FIELD_DEFS["bait_ids"].element is not None
    assert FISHING_SETTINGS_FIELD_DEFS["bait_ids"].element.type == "str"
    for key in ("bait_bonus", "rod_full_bonus", "crown_thresholds",
                "wait_sec", "energy", "king_event"):
        assert FISHING_SETTINGS_FIELD_DEFS[key].type == "obj", key
    assert FISHING_SETTINGS_FIELD_DEFS["daily_limit"].type == "int"


def test_fishing_settings_meta_obj_with_children() -> None:
    """fishing_settings_meta → type=obj + children=FIELD_DEFS（对齐 forge 登记形态）。"""
    meta = fishing_settings_meta()
    assert meta.type == "obj"
    assert meta.children is not None
    assert set(meta.children) == set(FISHING_SETTINGS_KEYS)
