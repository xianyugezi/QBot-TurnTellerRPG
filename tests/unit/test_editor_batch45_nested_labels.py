"""编辑器重写批4.5 · 嵌套子字段中文名（递归；含 element.children）+ 余量模块字段名。

覆盖任务书要求：
  · FieldMeta.children（及 element.children）里的键也要有中文 label，让列表表头/对象组头
    显示「中文名 + 原始键」而不是裸键（主 agent 实测：enemies.phases[]、drops.*、ai.*、
    parts.*、skills.level.*、jobs.transform.*、maps.*、quest.conditions.*、effects/statuses/
    marks children、forge/enhance/slots 等仍为裸键）；
  · 覆盖范围递归到真实内容包（veinborn/test_demo）出现过的嵌套键（数据反查，不凭想象造键）；
  · 装饰只补展示层 label / 纯展示 soft 子字段：type/required/enum/children 结构不变，
    泛型校验语义零变化；
  · 尚未覆盖模块（npc/shop/checkin/stats/formula/traits/recipe/proficiency/slots/dungeon/
    achievements/settings/manifest 等）字段全中文；
  · 无权威依据 / 动态键空间的键保留原始键，不猜（记入批报「待确认清单」）。
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest

from qbot_rpg.content import field_meta as fm_mod
from qbot_rpg.content import field_meta_pack as fmp
from qbot_rpg.content.models import FieldMeta
from qbot_rpg.web import api

REPO = Path(api.repo_root())
CONTENT = REPO / "content"

# 批4.5 覆盖的模块（顶层字段全中文）
COVERED_MODULES = (
    # 批B：展示文案已按包下放。下列为 veinborn/test_demo 两包声明并集覆盖的模块
    # （manifest/conditional 不在任何内容包 manifest 里声明，不再是「内容模块」，
    #  故不再要求包声明覆盖）。
    "effects", "statuses", "marks", "skill_chains", "action", "skills", "jobs",
    "formula", "items", "equipment", "traits", "recipe", "proficiency", "slots", "forge",
    "fishing", "enhance", "enemies", "maps", "dungeon", "stats", "npc", "shop", "quest",
    "checkin", "achievements", "settings", "ai", "hidden", "env_event",
    "log_card", "editor",
)


def _table():
    """批B：展示文案已下放到包；把两个真实包的声明并成「schema 覆盖面」表。"""
    table = api.field_meta_table()
    for pack in ("veinborn", "test_demo"):
        decl = fmp.load_field_meta(CONTENT / pack)
        if decl is not None:
            table = fmp.merge_field_meta_table(table, decl)
    return table


def _container_children(fm: FieldMeta) -> Dict[str, FieldMeta]:
    """一个字段的「下一层子字段」：obj → children；list → element.children。"""
    if fm.children:
        return dict(fm.children)
    if fm.element is not None and fm.element.children:
        return dict(fm.element.children)
    return {}


def _resolve(meta: Any, path: Tuple[str, ...]) -> Optional[FieldMeta]:
    fm = meta.fields.get(path[0])
    for key in path[1:]:
        if fm is None:
            return None
        fm = _container_children(fm).get(key)
    return fm


# ---------------------------------------------------------------------------
# 一、顶层字段：覆盖模块一律中文名（不裸键）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mod", COVERED_MODULES)
def test_covered_modules_top_fields_have_chinese_labels(mod: str) -> None:
    meta = _table().module(mod)
    assert meta is not None, mod
    if not meta.fields:
        pytest.skip(f"{mod} 无顶层字段表（map 模块键空间）")
    missing = [k for k, f in meta.fields.items() if not f.label]
    assert not missing, (mod, missing)


def test_stats_value_meta_children_have_labels() -> None:
    meta = _table().module("stats")
    assert meta is not None and meta.value_meta is not None
    kids = dict(meta.value_meta.children)
    assert kids and all(f.label for f in kids.values()), sorted(kids)


# ---------------------------------------------------------------------------
# 二、嵌套子字段：递归到真实内容包出现过的键（数据反查 + 元数据中文名）
# ---------------------------------------------------------------------------
def _load_entry(pack: str, module: str, entry_id: str) -> Any:
    """读条目：list 模块按 id（无 id 的用 #i 下标，如 slots）；object 模块返回整段。"""
    data = json.loads((CONTENT / pack / f"{module}.json").read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return data
    if entry_id.startswith("#"):
        return data[int(entry_id[1:])]
    for row in data:
        if isinstance(row, dict) and row.get("id") == entry_id:
            return row
    raise AssertionError(f"{pack}/{module} 无条目 {entry_id}")


# (pack, module, entry_id, 数据键路径)；元数据路径 = 去掉数字下标（列表下钻 element.children）
REAL_NESTED_SAMPLES: Tuple[Tuple[str, str, str, Tuple[Any, ...]], ...] = (
    # enemies：阶段表 / AI 行为态 / 掉落 / 印记触发 / 属性 / 弱点 / 图鉴 / 奖励 / 换区
    ("veinborn", "enemies", "gravelcrown", ("phases", 0, "threshold")),
    ("veinborn", "enemies", "gravelcrown", ("phases", 0, "enter_action")),
    ("veinborn", "enemies", "gravelcrown", ("phases", 0, "broadcast")),
    ("veinborn", "enemies", "gravelcrown", ("ai", "transitions", 0, "from")),
    ("veinborn", "enemies", "gravelcrown", ("ai", "transitions", 0, "condition")),
    ("veinborn", "enemies", "gravelcrown", ("drops", "death", 0, "count")),
    ("veinborn", "enemies", "gravelcrown", ("special_actions", 0, "trigger", "mark")),
    ("veinborn", "enemies", "gravelcrown", ("special_actions", 0, "trigger", "min")),
    ("veinborn", "enemies", "gravelcrown", ("stats", "hp")),
    ("veinborn", "enemies", "gravelcrown", ("weakness", "elements")),
    ("veinborn", "enemies", "gravelcrown", ("lore", 0, "unlock")),
    ("veinborn", "enemies", "gravelcrown", ("rewards", "exp")),
    ("test_demo", "enemies", "ash_wraith", ("zone_change", "hp_threshold")),
    # skills：等级 / 触发上限 / 效果列表元素
    ("test_demo", "skills", "blade_dance", ("level", "max")),
    ("test_demo", "skills", "basic_attack", ("trigger_limit", "per_round")),
    ("test_demo", "skills", "power_strike", ("effects", 0, "effect")),
    ("test_demo", "skills", "power_strike", ("effects", 0, "overrides")),
    # jobs：形态切换 / 状态策略 / 成长
    ("test_demo", "jobs", "berserker", ("transform", "transform_skill")),
    ("test_demo", "jobs", "berserker", ("transform", "state_policy", "marks")),
    ("test_demo", "jobs", "berserker", ("growth", "str")),
    # maps：刷怪行 / 通道出口 / 地图机制 / 采集点
    ("test_demo", "maps", "gloom_forest", ("monsters", 0, "enemy")),
    ("test_demo", "maps", "gloom_forest", ("monsters", 0, "respawn_minutes")),
    ("test_demo", "maps", "start_village", ("exits", "up", "to")),
    ("test_demo", "maps", "start_village", ("exits", "up", "mode")),
    ("test_demo", "maps", "misty_pass", ("mechanics", 0, "on_step", "type")),
    ("test_demo", "maps", "gloom_forest", ("gather_points", 0, "rate")),
    # quest：解锁条件 / 奖励
    ("test_demo", "quest", "q_start", ("conditions", 0, "var")),
    ("test_demo", "quest", "q_start", ("conditions", 0, "op")),
    ("test_demo", "quest", "q_start", ("reward", 0, "coins")),
    # effects / statuses：效果行动表元素 / 状态持续
    ("veinborn", "effects", "surge_tick", ("actions", 0, "mark")),
    ("veinborn", "statuses", "inexhaustible_form", ("duration", "turns")),
    # skill_chains：派生链步骤
    ("test_demo", "skill_chains", "chain_rage", ("steps", 0, "from")),
    ("test_demo", "skill_chains", "chain_rage", ("steps", 0, "condition", "count")),
    ("test_demo", "skill_chains", "chain_rage", ("steps", 0, "variant_override", "power")),
    # npc / shop / checkin
    ("test_demo", "npc", "elder_huai", ("interactions", 0, "action")),
    ("test_demo", "shop", "village_shop", ("items", 0, "stock")),
    ("test_demo", "checkin", "checkin_demo", ("rewards", "daily", 0, "day")),
    ("test_demo", "checkin", "checkin_demo", ("rewards", "daily", 0, "items")),
    # recipe / proficiency / slots
    ("test_demo", "recipe", "rcp_fire_crystal", ("materials", 0, "id")),
    ("test_demo", "recipe", "rcp_fire_crystal", ("cost", "coins")),
    ("test_demo", "proficiency", "alchemy", ("sp_panel", 0, "cost")),
    ("test_demo", "proficiency", "alchemy", ("energy", "regen_sec")),
    ("test_demo", "slots", "#0", ("slots", 0, "slot_level")),
    # settings / manifest / dungeon / achievements / forge / fishing / enhance
    ("veinborn", "settings", "", ("death_penalty", "weak_duration_sec")),
    ("veinborn", "settings", "", ("battle", "stamina_max")),
    ("veinborn", "settings", "", ("quest_board", "tiers", 0, "id")),
    ("veinborn", "settings", "", ("assistant", "helpers", 0, "name")),
    ("test_demo", "dungeon", "mist_dungeon_explore", ("drops", "normal", 0, "item")),
    ("test_demo", "achievements", "ach_codex_25", ("conditions", 0, "var")),
    ("test_demo", "forge", "", ("trees", 0, "nodes", 0, "materials", 0, "count")),
    ("test_demo", "fishing", "", ("species", 0, "codex_text", "desc")),
    ("veinborn", "enhance", "", ("cost", "stone_tiers", 0, "tier")),
)


def _data_at(entry: Any, path: Tuple[Any, ...]) -> Any:
    cur = entry
    for step in path:
        if isinstance(step, int):
            assert isinstance(cur, list) and len(cur) > step, path
            cur = cur[step]
        else:
            assert isinstance(cur, dict) and step in cur, (path, step)
            cur = cur[step]
    return cur


def _meta_path(path: Tuple[Any, ...]) -> Tuple[str, ...]:
    return tuple(str(s) for s in path if not isinstance(s, int))


@pytest.mark.parametrize("pack,mod,entry,path", REAL_NESTED_SAMPLES)
def test_real_nested_key_has_chinese_label(pack: str, mod: str, entry: str,
                                           path: Tuple[Any, ...]) -> None:
    """真实内容包里出现过的嵌套键 → 元数据有中文名（数据反查，不凭想象造键）。"""
    data = _load_entry(pack, mod, entry)
    _data_at(data, path)  # 该键确实存在于真实数据里
    meta = _table().module(mod)
    assert meta is not None, mod
    fm = _resolve(meta, _meta_path(path))
    assert fm is not None, (mod, path, "元数据未覆盖该嵌套键")
    assert fm.label, (mod, path, "嵌套键缺中文 label")


def test_added_real_nested_keys_are_soft_display_only() -> None:
    """真实数据反查补出的纯展示子字段必须 soft_label=True —— 泛型校验短路，语义零变化。"""
    meta = _table().module("enemies")
    assert meta is not None
    count = _resolve(meta, ("drops", "death", "count"))
    assert count is not None and count.soft_label
    trigger = _resolve(meta, ("special_actions", "trigger"))
    assert trigger is not None
    for key in ("mark", "min", "absent"):
        assert trigger.children[key].soft_label, key


# ---------------------------------------------------------------------------
# 三、装饰契约：只补 label / soft 展示子字段，结构与校验属性不变
# ---------------------------------------------------------------------------
def _snapshot(fm: FieldMeta) -> Tuple[Any, ...]:
    """除 label/group 外的校验属性快照 + 递归 children / element 结构。"""
    fields = tuple(
        (f.name, getattr(fm, f.name))
        for f in dataclasses.fields(FieldMeta)
        if f.name not in ("label", "group", "children", "element")
    )
    kids = tuple((k, _snapshot(v)) for k, v in fm.children.items())
    elem = _snapshot(fm.element) if fm.element is not None else None
    return (fields, kids, elem)


def test_recursive_decoration_is_label_only_for_existing_children() -> None:
    inner = FieldMeta(type="int", required=True, enum=("a", "b"), label="内层自带")
    original = FieldMeta(type="obj", children={"x": inner})
    out = fm_mod._decorate_field_meta(
        {"k": original}, {}, {}, {"k": {"x": "表内层"}})
    got = out["k"].children["x"]
    # 子字段自带 label 优先，表不得覆盖（与模块级 _decorate_field_meta 口径一致）
    assert got.label == "内层自带"
    assert _snapshot(got) == _snapshot(inner)
    assert set(out["k"].children) == {"x"}
    # 无自带 label 的子字段 → 表补上
    bare = FieldMeta(type="obj", children={"y": FieldMeta(type="str")})
    out2 = fm_mod._decorate_field_meta(
        {"k": bare}, {}, {}, {"k": {"y": "表补名"}})
    assert out2["k"].children["y"].label == "表补名"


def test_recursive_decoration_keeps_structure_without_child_table() -> None:
    original = FieldMeta(type="obj", children={"x": FieldMeta(type="int")})
    out = fm_mod._decorate_field_meta({"k": original}, {}, {"k": "中文"})
    assert _snapshot(out["k"]) == _snapshot(original)
    assert out["k"].children is original.children


def test_added_children_are_soft_display_only() -> None:
    """表里出现、children 未登记的键 → 只能补 soft_label 纯展示子字段（不引入红拦）。"""
    original = FieldMeta(type="obj", children={})
    out = fm_mod._decorate_field_meta(
        {"k": original}, {}, {}, {"k": {"ghost": "幽灵键"}})
    ghost = out["k"].children["ghost"]
    assert ghost.label == "幽灵键"
    assert ghost.soft_label is True
    assert ghost.required is False and ghost.default is None


def test_decoration_does_not_mutate_source_fieldmeta() -> None:
    original = FieldMeta(type="obj", children={"x": FieldMeta(type="int")})
    fm_mod._decorate_field_meta({"k": original}, {}, {}, {"k": {"x": "内层"}})
    assert original.children["x"].label == ""


def test_container_label_and_children_label_coexist() -> None:
    """容器自身中文名（`_label`）与其子字段中文名可同时给（drops.battle 等）。"""
    meta = _table().module("enemies")
    assert meta is not None
    battle = meta.fields["drops"].children["battle"]
    assert battle.label == "战斗掉落"
    assert battle.element.children["count"].label == "数量"


# ---------------------------------------------------------------------------
# 四、真实条目：列表表头/对象组头拿到的是中文名，不是裸键
# ---------------------------------------------------------------------------
def test_enemy_phases_list_headers_are_chinese() -> None:
    """主 agent 实测点名：enemies 的阶段表列表表头原为裸键 threshold/enter_action/broadcast。"""
    d = api.entry_detail("veinborn", "enemies", "gravelcrown", root=CONTENT)
    phases = next(f for f in d["fields"] if f["key"] == "phases")
    cols = {c["key"]: c["label"] for c in phases["columns"]}
    assert cols["threshold"] == "触发阈值"
    assert cols["enter_action"] == "进入行动"
    assert cols["broadcast"] == "播报"


def test_enemy_drops_and_ai_object_children_are_chinese() -> None:
    d = api.entry_detail("veinborn", "enemies", "gravelcrown", root=CONTENT)
    by_key = {f["key"]: f for f in d["fields"]}
    ai = by_key["ai"]
    ai_children = {c["key"]: c["label"] for c in ai.get("children", [])}
    assert ai_children.get("transitions") == "状态转移"
    drops = by_key["drops"]
    drop_children = {c["key"]: c["label"] for c in drops.get("children", [])}
    assert drop_children.get("battle") == "战斗掉落"


def test_maps_monsters_list_headers_are_chinese() -> None:
    d = api.entry_detail("test_demo", "maps", "gloom_forest", root=CONTENT)
    monsters = next(f for f in d["fields"] if f["key"] == "monsters")
    cols = {c["key"]: c["label"] for c in monsters["columns"]}
    assert cols["enemy"] == "怪物引用"
    assert cols["respawn_minutes"] == "刷新间隔(分钟)"


# ---------------------------------------------------------------------------
# 五、编辑器框架不写死业务字段名
# ---------------------------------------------------------------------------
def test_editor_framework_has_no_hardcoded_batch45_terms() -> None:
    banned = ["触发阈值", "进入行动", "播报", "状态转移", "战斗掉落", "怪物引用"]
    for path in (REPO / "qbot_rpg" / "web" / "api.py",
                 REPO / "qbot_rpg" / "web" / "editor_ops.py",
                 REPO / "qbot_rpg" / "web" / "static" / "index.html",
                 REPO / "scripts" / "editor_host.py"):
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, f"{path} 写死了业务字段名：{word}"
