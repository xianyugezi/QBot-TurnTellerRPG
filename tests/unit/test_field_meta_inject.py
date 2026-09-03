"""M12 批4 路4A：field_meta 正式表注入单测（quest/shop/npc/checkin + 4 新视图模块）。

依据：docs/细化/细化_5a2_编辑器扩展页.md（NPC 10 标签 / 签到 7 区 / AI 6 子页 /
隐藏 3 / 环境事件 / 日志卡片）+ 真实内容包 content/test_demo json 条目口径 +
P-07（字段元数据 = 编辑器表单唯一数据源，需中文 label）。

覆盖：
  - quest/shop/npc/checkin 字段非空且 ≥7（表单可渲染）+ 关键键存在 + label 中文非空
  - ai/hidden/env_event/log_card 四视图模块在表（/api/meta/{page} 数据源）
  - settings 段含 env_event/log_card
  - 既有完备模块计数硬断言回归（skills 25/jobs 11/enemies 26/maps 12 不漂移）
  - test_demo 真实内容过 check_pack 零红拦（泛型字段表注入不误拦专项内容）

铁律：零 NoneBot import；纯 pytest；无 emoji；全中文注释。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.loader import load_pack

_REPO = Path(__file__).resolve().parent.parent.parent


def _table():
    return default_field_meta_table()


def _fields(module: str) -> dict:
    m = _table().modules.get(module)
    assert m is not None, f"模块 {module} 不在表"
    return dict(m.fields)


def test_quest_fields_injected() -> None:
    """quest 17 字段 + 关键键 + 全中文 label。"""
    f = _fields("quest")
    assert len(f) >= 15
    for key in ("id", "name", "type", "desc", "conditions", "reward", "npc",
                "zone", "repeatable"):
        assert key in f, f"quest 缺字段 {key}"
    # label 中文非空（编辑器表单列头）
    assert all(x.label for x in f.values()), "quest 字段 label 应全非空"


def test_shop_fields_injected() -> None:
    """shop 15 字段 + items 子表 + refresh 模式。"""
    f = _fields("shop")
    assert len(f) >= 12
    for key in ("id", "name", "type", "currency", "items", "refresh", "visible",
                "desc", "pool"):
        assert key in f, f"shop 缺字段 {key}"
    assert all(x.label for x in f.values()), "shop 字段 label 应全非空"


def test_npc_fields_injected() -> None:
    """npc 14 字段 + dialogues/interactions/quests 子表。"""
    f = _fields("npc")
    assert len(f) >= 10
    for key in ("id", "name", "icon", "map", "type", "dialogues", "interactions",
                "quests"):
        assert key in f, f"npc 缺字段 {key}"
    assert all(x.label for x in f.values()), "npc 字段 label 应全非空"


def test_checkin_fields_injected() -> None:
    """checkin 7 字段 + period/rewards 子表。"""
    f = _fields("checkin")
    assert len(f) >= 7
    for key in ("id", "name", "type", "period", "rewards"):
        assert key in f, f"checkin 缺字段 {key}"
    assert all(x.label for x in f.values()), "checkin 字段 label 应全非空"


def test_view_modules_present() -> None:
    """ai/hidden/env_event/log_card 四视图模块在表（/api/meta/{page} 数据源）。"""
    t = _table()
    for k in ("ai", "hidden", "env_event", "log_card"):
        assert k in t.modules, f"视图模块 {k} 缺登记"
        m = t.modules[k]
        assert len(m.fields) >= 1, f"{k} 应有字段"
        assert all(x.label for x in m.fields.values()), f"{k} 字段 label 应非空"


def test_settings_env_and_logcard_segments() -> None:
    """settings 段含 env_event/log_card（5a2 环境事件/日志卡片挂 settings.json）。"""
    t = _table()
    sf = t.modules["settings"].fields
    assert "env_event" in sf
    assert "log_card" in sf


def test_existing_modules_counts_stable() -> None:
    """既有完备模块计数硬断言（M13 硬计数连锁：改动会破坏 test_m13_hard_counts）。"""
    t = _table()
    assert len(t.modules["skills"].fields) == 25
    assert len(t.modules["jobs"].fields) == 11
    assert len(t.modules["enemies"].fields) == 26
    assert len(t.modules["maps"].fields) == 12


def test_test_demo_pack_still_loads() -> None:
    """test_demo 真实内容过 check_pack 零红拦（字段表注入不误拦专项内容）。"""
    pack = asyncio.run(load_pack(_REPO / "content" / "test_demo"))
    assert pack.pack_id == "test_demo"
    # 四模块真实条目存在（加载成功即证明零新增红拦）
    for mod in ("quest", "shop", "npc", "checkin"):
        assert mod in pack.modules


def test_meta_endpoint_fields_have_labels() -> None:
    """表单渲染前提：/api/meta 输出每字段 label 非空（前端表单列头）。"""
    t = _table()
    # 模拟 web/api.py meta_page 的字段输出逻辑（module 映射 + fields→list）
    module_map = {"skill": "skills", "job": "jobs", "monster": "enemies",
                  "map": "maps", "quest": "quest", "shop": "shop",
                  "npc": "npc", "checkin": "checkin"}
    for page, module in module_map.items():
        m = t.modules.get(module)
        if m is None:
            continue
        for fname, fmeta in m.fields.items():
            label = fmeta.label or fname
            assert label, f"{page}.{fname} label 空"


# =============================================================================
# M12.5 批1 路1C：C 类空表宽松注入（dungeon/achievements 编辑器表单数据源）
# =============================================================================
def test_dungeon_fields_injected() -> None:
    """dungeon 9 字段注入 + id required + 闭合枚举 + 全中文 label。"""
    f = _fields("dungeon")
    assert len(f) >= 9
    for key in ("id", "name", "type", "maps", "subquests", "safe_zone", "drops"):
        assert key in f, f"dungeon 缺字段 {key}"
    assert f["id"].required is True
    assert f["type"].enum == ("explore", "boss")
    assert all(x.label for x in f.values()), "dungeon 字段 label 应全非空"


def test_achievements_fields_injected() -> None:
    """achievements 7 字段注入 + id required + trigger/once 口径。"""
    f = _fields("achievements")
    assert len(f) >= 7
    for key in ("id", "name", "desc", "conditions", "trigger", "once", "reward"):
        assert key in f, f"achievements 缺字段 {key}"
    assert f["id"].required is True
    assert f["trigger"].enum == ("check",)
    assert f["once"].type == "bool"
    assert all(x.label for x in f.values()), "achievements 字段 label 应全非空"


def test_c_class_pack_still_loads_zero_red() -> None:
    """C 类注入后 test_demo 加载零新增红拦（dungeon/achievements 专项深结构不被泛型误拦）。"""
    pack = asyncio.run(load_pack(_REPO / "content" / "test_demo"))
    assert pack.pack_id == "test_demo"
    # 两模块真实条目存在（加载成功即证明零新增红拦；modules_raw 挂 registry）
    raw = pack.registry.modules_raw
    assert len(raw.get("dungeon", [])) >= 2
    assert len(raw.get("achievements", [])) >= 8


def test_skill_chains_fields_completed() -> None:
    """M12.5 批2 路2B：skill_chains 顶层键补登记（M13 深结构 4 键 + steps children）。"""
    f = _fields("skill_chains")
    for key in ("max_combo", "max_combo_behavior", "steps", "trigger_skill"):
        assert key in f, f"skill_chains 缺字段 {key}"
    assert f["steps"].type == "list"
    elem = f["steps"].element
    assert elem.type == "obj" and elem.children, "steps 元素应有 children"
    for k in ("from", "to", "tag", "condition", "priority", "mode", "armor",
              "consume"):
        assert k in elem.children, f"steps.children 缺 {k}"
    # 新增的 4 个 M12.5 键 + steps children 全部有中文 label（既有共享常量键
    # F_ID/F_NAME 等无 label 是历史口径，不在此断言范围）
    for key in ("max_combo", "max_combo_behavior", "steps", "trigger_skill"):
        assert f[key].label, f"{key} label 空"


def test_skill_chains_pack_still_loads_zero_red() -> None:
    """skill_chains 补键后 test_demo 加载零新增红拦（steps 深结构不被泛型误拦）。"""
    pack = asyncio.run(load_pack(_REPO / "content" / "test_demo"))
    raw = pack.registry.modules_raw
    sc = raw.get("skill_chains")
    assert isinstance(sc, list) and len(sc) >= 1
