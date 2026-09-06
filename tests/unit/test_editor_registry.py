"""editor_registry 页面注册表单测（tests/unit/test_editor_registry.py · M12 批1 路1A）。

覆盖：
  - 默认六页兜底（无 editor 模块时）
  - editor.json 加载 13 页全登记、字段齐
  - enabled:false 页 get_page 返回但 enabled_pages 不含
  - extends 解析（ai → module_file=enemies.json 同 monster）
  - validator 名登记存在性校验

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性；无 emoji；
      新测试文件 ruff E501 零豁免（行宽 ≤100）。
"""

from __future__ import annotations

from qbot_rpg.content.editor_registry import (
    default_editor_pages,
    load_editor_registry,
    validate_validators,
)
from qbot_rpg.content.registry import Registry

# =====================================================================================
# B 方案自动页表（m125_编辑器自动页表方案_B.md §3：无 editor.json 按模块自动生成）
# =====================================================================================
def test_auto_pages_blank_modules_empty() -> None:
    """modules_raw 空 → 空页表（语义定稿：无幽灵页，见方案 B §3.4）。"""
    editor = load_editor_registry(Registry(pack_id="demo_blank"))
    assert editor.pages == ()
    assert editor.schema_version is None


def test_auto_pages_demo_blank_five_modules() -> None:
    """demo_blank 五模块（settings/stats/formula/effects/items）→ 恰好 5 页。"""
    editor = load_editor_registry(Registry(
        pack_id="demo_blank",
        modules_raw={
            "settings": {}, "stats": {}, "formula": {}, "effects": [], "items": [],
        },
    ))
    assert [p.page_id for p in editor.pages] == [
        "items", "effects", "stats", "formula", "settings",
    ]
    # catalog 顺序 = 页序（战斗组在物品组后；世界组最后）——见 _MODULE_PAGE_CATALOG
    by_id = {p.page_id: p for p in editor.pages}
    assert by_id["items"].title == "物品"
    assert by_id["items"].meta_source == "meta/items"
    assert by_id["items"].validator == "items"
    assert by_id["settings"].page_kind == "object"
    assert by_id["stats"].page_kind == "map"
    assert by_id["effects"].page_kind is None  # list 形态缺省


def test_auto_pages_veinborn_all_modules() -> None:
    """veinborn 17 模块 → 17 页（含装备/物品/NPC/行动/效果；不含 ai/hidden 等特殊页；
    forge/fishing/enhance 等 object 形态模块不生成 auto 页——编辑器原始 JSON 兜底）。"""
    from qbot_rpg.content.loader import load_pack
    import asyncio
    from pathlib import Path
    pack = asyncio.run(load_pack(Path(__file__).resolve().parent.parent.parent
                                 / "content" / "veinborn"))
    editor = load_editor_registry(pack.registry)
    ids = [p.page_id for p in editor.pages]
    assert len(ids) == 19  # veinborn manifest +forge/proficiency（2026-09-06 武器锻造）
    for must in ("skill", "job", "monster", "map", "quest", "shop", "npc",
                 "items", "equipment", "action", "effects", "statuses",
                 "marks", "skill_chains", "stats", "formula", "settings"):
        assert must in ids, f"veinborn auto 页缺 {must}"
    # 特殊页不自动生成
    for non in ("ai", "hidden", "env_event", "log_card"):
        assert non not in ids, f"特殊页 {non} 不应自动生成"


def test_auto_pages_missing_module_skipped() -> None:
    """模块缺失 → 对应页跳过（demo_full 有 equipment 无 skills → 无技能页）。"""
    editor = load_editor_registry(Registry(
        pack_id="demo_full",
        modules_raw={
            "settings": {}, "stats": {}, "formula": {}, "effects": [],
            "statuses": [], "marks": [], "items": [], "equipment": [],
            "action": [], "enemies": [], "maps": [], "dungeon": [],
            "npc": [], "shop": [], "quest": [], "checkin": [],
        },
    ))
    ids = [p.page_id for p in editor.pages]
    assert "skill" not in ids
    assert "job" not in ids
    assert "equipment" in ids and "items" in ids
    assert "npc" in ids and "checkin" in ids


def test_auto_pages_editor_declared_wins() -> None:
    """有 editor.json 声明 → 声明优先（auto 不覆盖声明页表）。"""
    raw = _sample_raw_editor()
    raw["pages"] = [p for p in raw["pages"] if p["page_id"] != "skill"]
    editor = load_editor_registry(Registry(
        pack_id="test", modules_raw={"editor": raw, "skills": [], "jobs": []},
    ))
    ids = [p.page_id for p in editor.pages]
    assert "skill" not in ids  # 声明页表不自动补技能页
    assert "npc" in ids


# =====================================================================================
# 默认页兜底（细化_5a2 M-06 5a2 L239 / PR-01 5a2 L50；M12.5/veinborn 扩展
# equipment/item 两页——veinborn 等无 editor.json 内容包也可编辑装备/物品）
# =====================================================================================
def test_default_six_pages_field_defaults() -> None:
    """兜底六页字段齐：title/icon/module_file/meta_source/validator。"""
    pages = default_editor_pages()
    by_id = {p.page_id: p for p in pages}
    assert by_id["monster"].module_file == "enemies.json"
    assert by_id["monster"].meta_source == "meta/monster"
    assert by_id["monster"].validator == "monster"
    assert by_id["monster"].tabs[-1] == "AI×6"  # 5a2 L65 样例 tab
    assert by_id["job"].module_file == "jobs.json"
    assert by_id["job"].validator == "job"
    assert by_id["quest"].module_file == "quest.json"  # 5a2 L67 样例口径
    for p in pages:
        assert p.enabled is True
        assert p.extends is None
        assert p.page_id and p.title and p.module_file and p.meta_source


# =====================================================================================
# editor.json 加载（细化_5a2 L59-77 配置样例）
# =====================================================================================
def _registry_with_editor(raw_editor: object) -> Registry:
    """构造带 editor 模块原始数据的 Registry（modules_raw 直填，零 IO）。"""
    return Registry(pack_id="test", modules_raw={"editor": raw_editor})


def _sample_raw_editor() -> dict:
    """13 页样例（对齐细化_5a2 L63-74 契约样例：六页 + 扩展七页）。"""
    return {
        "schema_version": 1,
        "pages": [
            {"page_id": "skill", "title": "技能", "icon": "⚔️",
             "module_file": "skills.json", "meta_source": "meta/skill",
             "enabled": True, "validator": "skill"},
            {"page_id": "job", "title": "职业", "icon": "🎖️",
             "module_file": "jobs.json", "meta_source": "meta/job",
             "enabled": True, "validator": "job"},
            {"page_id": "monster", "title": "怪物", "icon": "👹",
             "module_file": "enemies.json", "meta_source": "meta/monster",
             "enabled": True, "validator": "monster",
             "tabs": ["基本信息", "属性", "弱点", "PV", "抗性", "行动",
                      "特殊行动", "掉落", "图鉴", "AI×6"]},
            {"page_id": "map", "title": "地图", "icon": "🗺️",
             "module_file": "maps.json", "meta_source": "meta/map",
             "enabled": True, "validator": "map",
             "tabs": ["基础", "通道", "怪物", "NPC"]},
            {"page_id": "quest", "title": "任务", "icon": "📜",
             "module_file": "quest.json", "meta_source": "meta/quest",
             "enabled": True, "validator": "quest"},
            {"page_id": "shop", "title": "商店", "icon": "🏪",
             "module_file": "shop.json", "meta_source": "meta/shop",
             "enabled": True, "validator": "shop"},
            {"page_id": "npc", "title": "NPC", "icon": "🧙",
             "module_file": "npc.json", "meta_source": "meta/npc",
             "enabled": True, "validator": "npc",
             "tabs": ["基础", "地图挂点", "对话", "条件", "交互", "任务",
                      "商店", "情报", "教学", "发牌"]},
            {"page_id": "checkin", "title": "签到", "icon": "📅",
             "module_file": "checkin.json", "meta_source": "meta/checkin",
             "enabled": True, "validator": "checkin",
             "tabs": ["基础", "周期", "每日奖励", "连签奖励", "月度累计",
                      "补签", "预览"]},
            {"page_id": "ai", "title": "AI", "icon": "🤖",
             "module_file": "enemies.json", "meta_source": "meta/ai",
             "enabled": True, "validator": "ai", "extends": "monster",
             "tabs": ["行动表", "条件行动", "状态机", "阶段", "连招链", "换区"]},
            {"page_id": "hidden", "title": "隐藏要素", "icon": "🔮",
             "module_file": "maps.json", "meta_source": "meta/hidden",
             "enabled": True, "validator": "hidden",
             "tabs": ["隐藏BOSS", "隐藏任务", "彩蛋"]},
            {"page_id": "env_event", "title": "环境事件", "icon": "🌧️",
             "module_file": "settings.json", "meta_source": "meta/env_event",
             "enabled": True, "validator": "env_event"},
            {"page_id": "log_card", "title": "日志卡片", "icon": "📔",
             "module_file": "settings.json", "meta_source": "meta/log_card",
             "enabled": True, "validator": "log_card"},
        ],
    }


def test_load_editor_registry_thirteen_pages() -> None:
    """editor.json 样例 → 12 行 page 条目全登记（六页 + 六组扩展页）。

    说明：细化_5a2 文档计数「新增 13 页」= NPC 1 + 签到 1 + AI 6 子页 +
    隐藏要素 3 子页 + 环境事件 1 + 日志卡片 1（5a2 L291），其中 AI×6 与
    隐藏×3 以 tabs 承载在单 page 行（5a2 L71-72）；editor.json 实际登记
    12 行（六页 + npc/checkin/ai/hidden/env_event/log_card 六行，
    5a2 M-01 L234 归口追加 6 行）。与 5a 六页合并后编辑器页面合计 19
    （6 + 13，按子页计数，5a2 L291）。
    """
    editor = load_editor_registry(_registry_with_editor(_sample_raw_editor()))
    assert len(editor.pages) == 12
    assert editor.schema_version == 1
    assert [p.page_id for p in editor.pages] == [
        "skill", "job", "monster", "map", "quest", "shop",
        "npc", "checkin", "ai", "hidden", "env_event", "log_card",
    ]
    # 13 子页口径：ai.tabs 6 + hidden.tabs 3（其余页 tabs 也齐）
    assert len(editor.get_page("ai").tabs) == 6  # type: ignore[union-attr]
    assert len(editor.get_page("hidden").tabs) == 3  # type: ignore[union-attr]


def test_load_editor_registry_fields_complete() -> None:
    """12 页字段齐（PR-02 九字段语义：icon/module_file/meta_source/extends/validator）。"""
    editor = load_editor_registry(_registry_with_editor(_sample_raw_editor()))
    by_id = {p.page_id: p for p in editor.pages}
    assert len(by_id) == 12
    # 六页归口（5a P-06）：skill→skills.json / job→jobs.json / monster→enemies.json /
    # map→maps.json / quest→quest.json / shop→shop.json
    assert by_id["skill"].module_file == "skills.json"
    assert by_id["job"].module_file == "jobs.json"
    assert by_id["monster"].module_file == "enemies.json"
    assert by_id["map"].module_file == "maps.json"
    assert by_id["quest"].module_file == "quest.json"
    assert by_id["shop"].module_file == "shop.json"
    # 扩展页归口（5a2 L69-74）：npc.json/checkin.json/enemies.json[AI]/maps.json[隐藏]/
    # settings.json[环境事件]/settings.json[日志卡片]
    assert by_id["npc"].module_file == "npc.json"
    assert by_id["checkin"].module_file == "checkin.json"
    assert by_id["ai"].module_file == "enemies.json"
    assert by_id["hidden"].module_file == "maps.json"
    assert by_id["env_event"].module_file == "settings.json"
    assert by_id["log_card"].module_file == "settings.json"
    # meta_source 逐页（5a2 M-03 19 页口径）
    assert by_id["ai"].meta_source == "meta/ai"
    assert by_id["hidden"].meta_source == "meta/hidden"
    assert by_id["env_event"].meta_source == "meta/env_event"
    assert by_id["log_card"].meta_source == "meta/log_card"
    # tabs 齐（NPC 10 标签 / 签到 7 区 / AI 6 子页 / 隐藏 3 子页）
    assert len(by_id["npc"].tabs) == 10
    assert len(by_id["checkin"].tabs) == 7
    assert len(by_id["ai"].tabs) == 6
    assert len(by_id["hidden"].tabs) == 3
    assert by_id["monster"].tabs[-1] == "AI×6"
    # icon 用契约样例值（5a2 L63-74 emoji）
    assert by_id["skill"].icon == "⚔️"
    assert by_id["npc"].icon == "🧙"
    assert by_id["checkin"].icon == "📅"
    assert by_id["ai"].icon == "🤖"


# =====================================================================================
# enabled:false 启停语义（细化_5a2 PR-03 5a2 L52）
# =====================================================================================
def test_disabled_page_get_page_but_not_enabled_pages() -> None:
    """enabled:false → get_page 返回该页；enabled_pages 不含（PR-03）。"""
    raw = _sample_raw_editor()
    raw["pages"][7] = dict(raw["pages"][7])  # checkin 页 → 停用
    raw["pages"][7]["enabled"] = False
    editor = load_editor_registry(_registry_with_editor(raw))
    page = editor.get_page("checkin")
    assert page is not None and page.enabled is False
    assert "checkin" not in [p.page_id for p in editor.enabled_pages()]
    assert len(editor.enabled_pages()) == 11
    # 停用页不影响引擎侧模块加载语义（模块文件仍可被其他页共享引用）
    assert editor.page_for_module("checkin.json") is not None


def test_get_page_missing_returns_none() -> None:
    """未登记 page_id → get_page 返回 None。"""
    editor = load_editor_registry(_registry_with_editor(_sample_raw_editor()))
    assert editor.get_page("not_a_page") is None


# =====================================================================================
# extends 解析（细化_5a2 L71/L79：ai extends=monster 共享 enemies.json）
# =====================================================================================
def test_page_for_module_extends_host_wins() -> None:
    """page_for_module(enemies.json) → 宿主页 monster（ai 挂载页不覆盖）。"""
    editor = load_editor_registry(_registry_with_editor(_sample_raw_editor()))
    page = editor.page_for_module("enemies.json")
    assert page is not None
    assert page.page_id == "monster"
    assert page.extends is None


def test_page_for_module_shared_settings_module() -> None:
    """settings.json 被 env_event/log_card 两页共享 → 返回首个独立页（env_event）。"""
    editor = load_editor_registry(_registry_with_editor(_sample_raw_editor()))
    page = editor.page_for_module("settings.json")
    assert page is not None
    assert page.page_id in ("env_event", "log_card")


def test_page_for_module_single_module_fallback() -> None:
    """module_file 无宿主页时回落首个共享页（checkin.json 单页 → checkin）。"""
    raw = _sample_raw_editor()
    raw["pages"] = [p for p in raw["pages"] if p["page_id"] != "checkin"]
    editor = load_editor_registry(_registry_with_editor(raw))
    # checkin 已移除 → 无页
    assert editor.page_for_module("checkin.json") is None
    # shop 单页 → shop
    page = editor.page_for_module("shop.json")
    assert page is not None and page.page_id == "shop"


# =====================================================================================
# validator 钩子名登记存在性校验（细化_5a2 PR-05 5a2 L54）
# =====================================================================================
def test_validator_names_registered() -> None:
    """样例 12 行页 validator 名全部登记（12 名互异；子页计数口径见 L121-127）。"""
    editor = load_editor_registry(_registry_with_editor(_sample_raw_editor()))
    names = editor.validator_names()
    assert len(names) == 12
    for expected in ("skill", "job", "monster", "npc", "checkin",
                     "ai", "hidden", "env_event", "log_card"):
        assert expected in names
    assert editor.has_validator("monster")


def test_validate_validators_all_known_zero_missing() -> None:
    """known 提供且全覆盖 → 零缺失（上层注入真实校验器名集合）。"""
    editor = load_editor_registry(_registry_with_editor(_sample_raw_editor()))
    # known = 全部登记名（模拟上层校验器已实现）
    known_all = [v for v in editor.validator_names()]
    assert validate_validators(editor, known=known_all) == ()
    # 缺省 known → 页表内部一致性（无重复名 → 零缺失）
    assert validate_validators(editor) == ()


def test_validate_validators_dangling_name_reported() -> None:
    """某页 validator 名不在 known（外部实现缺失）→ 该页被报出（黄提示级）。"""
    raw = _sample_raw_editor()
    raw["pages"] = list(raw["pages"])
    raw["pages"][0] = dict(raw["pages"][0])
    raw["pages"][0]["validator"] = "ghost_validator"  # 无外部实现
    editor = load_editor_registry(_registry_with_editor(raw))
    # known 缺 ghost_validator → skill 页被报
    known = [v for v in editor.validator_names() if v != "ghost_validator"]
    assert "skill" in validate_validators(editor, known=known)
    assert "monster" not in validate_validators(editor, known=known)


def test_validator_none_not_required() -> None:
    """validator 缺省/None → 不登记也不报缺失（缺省 None 不硬拦）。"""
    raw = _sample_raw_editor()
    raw["pages"] = [p for p in raw["pages"] if p["page_id"] != "ai"]
    raw["pages"].append({"page_id": "no_validator", "title": "无校验器",
                         "module_file": "x.json", "meta_source": "meta/x"})
    editor = load_editor_registry(_registry_with_editor(raw))
    assert editor.get_page("no_validator") is not None
    no_v_page = editor.get_page("no_validator")
    assert no_v_page is not None and no_v_page.validator is None
    assert "no_validator" not in editor.validator_names()
    assert validate_validators(editor) == ()


# =====================================================================================
# 宽容解析边界（解析产物可靠性）
# =====================================================================================
def test_load_skips_invalid_entries_and_bad_types() -> None:
    """坏条目（非 dict/缺 page_id/字段类型错）被跳过或回落默认，不抛错。"""
    raw = {
        "schema_version": "1",  # 非 int → schema None
        "pages": [
            "not-a-dict",
            {"title": "无 id"},          # 缺 page_id → 丢弃
            {"page_id": 123, "title": "数字 id"},  # 非字符串 id → 丢弃
            {"page_id": "ok", "title": "正常页", "module_file": "ok.json",
             "meta_source": "meta/ok", "enabled": "yes"},  # enabled 非 bool → True
        ],
    }
    editor = load_editor_registry(_registry_with_editor(raw))
    assert editor.schema_version is None
    assert [p.page_id for p in editor.pages] == ["ok"]
    page = editor.get_page("ok")
    assert page is not None
    assert page.enabled is True  # 非 bool 回落默认 true
    assert page.validator is None  # 缺省 None
    assert page.icon == "" and page.tabs == ()


def test_empty_pages_list_yields_empty_registry() -> None:
    """editor.json 声明 pages:[]（空包显式声明无页面）→ 空注册表非兜底。"""
    editor = load_editor_registry(_registry_with_editor({"schema_version": 1, "pages": []}))
    assert editor.pages == ()
    assert editor.schema_version == 1
