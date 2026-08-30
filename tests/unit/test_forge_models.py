"""M9 锻造数据层 · 路 0A：forge.json 数据模型 + 专项校验器测试。

文件名：test_forge_models.py
创建时间：2026-08-30
作者：Hermes 子agent-0A（M9 锻造实现组路0A：并发同仓，仅新建本文件 +
qbot_rpg/content/forge_models.py）

依据：docs/m9_shared_contract.md §〇~§八（字段表/校验规则/接口签名权威）+
docs/细化/细化_2c2a_锻造派生树schema.md §六（验收 TC-01~27，覆盖矩阵 A~F）+
docs/细化/细化_2c2d_锻造套装与客制.md §五/§六（sets/augments V1-V8/W1-W4）。
测试目标：qbot_rpg.content.forge_models.{validate_forge, merge_node_item,
forge_module_meta, ForgeTree/ForgeNode/MaterialReq/SetSkill/ForgeSet/AugmentRow/
LimitByRarity/ForgeSettings}。

测试口径（对齐 test_alchemy_models.py / test_shop_models.py）：
  - validate_forge 为 (modules, report) 纯函数；report 鸭子类型（_Report 收集器 +
    dict {"errors","warnings"} 形态 + 真实 validator._Checker 收口兼容测试）。
  - 断言级别：errors=红拦（加载失败）/ warnings=黄提示（不阻断）。
  - 2c2a §六 验收 TC-01~27 关键断言：V1~V15 正反例、V16/W1~W6 黄不拦、
    双源仲裁（覆盖 AR-1/追加 AR-2/品质 AR-3）、2c2d V1~V8/W1~W4。
  - 合法全量包（铁剑主干线+冰剑分支+炎王剑 final + 防具五树 + 套装 + 客制）
    零红零黄冒烟（TC-01/TC-02）。

铁律：零 NoneBot import；纯函数确定性；不写 time.sleep；不引入随机。
"""
from __future__ import annotations

from typing import Dict, Mapping, cast

from qbot_rpg.content.forge_models import (
    FORGE_ELEMENTS,
    FORGE_STAT_KEY_SPACE,
    FORGE_TREE_TYPES,
    LIMIT_RARITY_QUALITIES,
    MATERIAL_TIERS,
    RARITY_INT_MAP,
    RARITY_TIERS,
    SET_PIECE_COUNTS,
    SET_VARIANTS,
    SLOT_LEVELS,
    AugmentRow,
    ForgeNode,
    ForgeSet,
    ForgeSettings,
    ForgeTree,
    LimitByRarity,
    forge_module_meta,
    merge_node_item,
    validate_forge,
)
from qbot_rpg.content.validator import _Checker


# ---------------------------------------------------------------------------
# 收集器 / 夹具辅助
# ---------------------------------------------------------------------------
class _Report:
    """validate_forge 收集器（鸭子类型：error/warning 与 _Checker._err/_warn 一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _legal_weapon_tree() -> list:
    """合法武器树：铁剑主干线（7 节点）+ 冰剑/雷剑 2 分支 + 炎王剑 final=true。

    对齐 2c2a §九 样例拓扑（铁剑〔1级〕→ … → ■炎王剑（火））+ TC-01。
    零红零黄（节点 stats 不与 items 同键；炎王剑 augmentable=final weapon）。
    """
    return [
        {
            "id": "tree_weapon", "name": "武器树", "type": "weapon",
            "roots": ["node_iron_sword"],
            "nodes": [
                {"id": "node_iron_sword", "name": "铁剑", "item": "iron_sword",
                 "type": "weapon", "level": 1, "parent": None,
                 "materials": [{"item": "iron_ore", "count": 3}], "final": False},
                {"id": "node_iron_sword_1", "name": "铁剑Ⅰ", "item": "iron_sword_1",
                 "type": "weapon", "level": 2, "parent": "node_iron_sword",
                 "materials": [{"item": "iron_ore", "count": 5}], "final": False},
                {"id": "node_iron_sword_2", "name": "铁剑Ⅱ", "item": "iron_sword_2",
                 "type": "weapon", "level": 3, "parent": "node_iron_sword_1",
                 "branch": ["node_ice_sword", "node_lightning_sword"],
                 "stats": {"atk": 24},
                 "materials": [{"item": "iron_ore", "count": 5}], "final": False},
                {"id": "node_flame_sword", "name": "炎剑", "item": "flame_sword",
                 "type": "weapon", "level": 4, "parent": "node_iron_sword_2",
                 "stats": {"element": "fire", "element_value": 8},
                 "materials": [{"item": "fire_dragon_scale", "count": 2}],
                 "final": False},
                {"id": "node_flame_sword_2", "name": "炎剑Ⅱ", "item": "flame_sword_2",
                 "type": "weapon", "level": 5, "parent": "node_flame_sword",
                 "materials": [{"item": "fire_dragon_scale", "count": 3}],
                 "final": False},
                {"id": "node_flame_sword_3", "name": "炎剑Ⅲ", "item": "flame_sword_3",
                 "type": "weapon", "level": 6, "parent": "node_flame_sword_2",
                 "materials": [{"item": "fire_dragon_scale", "count": 4}],
                 "final": False},
                {"id": "node_flame_king_sword", "name": "炎王剑", "item": "flame_king_sword",
                 "type": "weapon", "level": 7, "parent": "node_flame_sword_3",
                 "stats": {"element": "fire"}, "rarity": "legendary", "final": True,
                 "augmentable": True,
                 "materials": [{"item": "fire_dragon_scale", "count": 2},
                               {"item": "dragonite", "count": 1}]},
                {"id": "node_ice_sword", "name": "冰剑", "item": "ice_sword",
                 "type": "weapon", "level": 3, "parent": "node_iron_sword_2",
                 "materials": [{"item": "ice_crystal", "count": 2}], "final": True},
                {"id": "node_lightning_sword", "name": "雷剑", "item": "lightning_sword",
                 "type": "weapon", "level": 3, "parent": "node_iron_sword_2",
                 "materials": [{"item": "lightning_fang", "count": 2}],
                 "final": True},
            ],
        },
    ]


def _legal_armor_trees() -> list:
    """防具五部位树（每棵 1 根节点 final=true；供套装 pieces 引用，2c2d V2）。"""
    trees = []
    for idx, (tid, ttype) in enumerate([
        ("tree_armor_head", "armor_head"),
        ("tree_armor_body", "armor_body"),
        ("tree_armor_hand", "armor_hand"),
        ("tree_armor_leg", "armor_leg"),
        ("tree_armor_foot", "armor_foot"),
    ]):
        nid = f"node_dk_{ttype}"
        roots = [nid]
        nodes = [{
            "id": nid, "name": f"龙骑·{ttype}", "item": f"item_{ttype}",
            "type": ttype, "level": 1, "parent": None,
            "materials": [{"item": "iron_ore", "count": 2}], "final": True,
        }]
        # β 版专用无孔节点（同部位第二节点，供 W1 α/β 孔位对照测试引用；
        # 工程补白：夹具扩展，避免 α/β 双版引用同一节点导致孔位对照恒等）
        if ttype == "armor_head":
            nodes.append({
                "id": "node_dk_armor_head_beta", "name": "龙骑·头(β)", "item": "item_armor_head",
                "type": ttype, "level": 1, "parent": None,
                "materials": [{"item": "iron_ore", "count": 2}], "final": True,
            })
            roots = [nid, "node_dk_armor_head_beta"]
        trees.append({
            "id": tid, "name": f"防具树·{ttype}", "type": ttype,
            "roots": roots, "nodes": nodes,
        })
    return trees


def _legal_sets() -> list:
    """合法套装（α 版 5 防具件 + 2/3/5 技能档，零红零黄；2c2d V1/V2/V3 正例）。"""
    return [{
        "id": "set_dragon_knight", "name": "龙骑士套装", "variant": "alpha",
        "pieces": ["node_dk_armor_head", "node_dk_armor_body", "node_dk_armor_hand",
                   "node_dk_armor_leg", "node_dk_armor_foot"],
        "skills": [
            {"piece_count": 2, "skill": "dragon_guard", "level": 1},
            {"piece_count": 3, "skill": "dragon_guard", "level": 2},
            {"piece_count": 5, "skill": "dragon_guard", "level": 3},
        ],
        "desc": "龙之加护寄宿的勇者之铠", "enabled": True,
        "codex_group": "set_dragon_knight",
    }]


def _legal_augments() -> dict:
    """合法客制段（4 项 + 次数表；零红零黄；2c2d V4/V5/V6 正例）。"""
    return {
        "augments": [
            {"id": "aug_atk", "name": "攻击", "kind": "numeric", "effect": "atk+5",
             "stat_key": "atk", "value": {"flat": 5},
             "cost": [{"item": "dragonite", "count": 1}], "repeatable": True,
             "max_repeat": 3},
            {"id": "aug_crit", "name": "会心", "kind": "numeric", "effect": "crit+10%",
             "stat_key": "crit", "value": {"pct": 0.10},
             "cost": [{"item": "dragonite", "count": 1}], "repeatable": True,
             "max_repeat": 3},
            {"id": "aug_def", "name": "防御", "kind": "numeric", "effect": "def+10",
             "stat_key": "def", "value": {"flat": 10},
             "cost": [{"item": "dragonite", "count": 1}], "repeatable": True,
             "max_repeat": 3},
            {"id": "aug_slot", "name": "孔位", "kind": "slot", "effect": "开1孔",
             "slot_level": 1, "cost": [{"item": "dragonite", "count": 2}],
             "repeatable": False, "max_repeat": 1},
        ],
        "limit_by_rarity": [
            {"quality": "epic", "times": 3, "final_only": False},
            {"quality": "legendary", "times": 2, "final_only": False},
            {"quality": "legendary", "times": 1, "final_only": True},
        ],
    }


def _legal_items() -> list:
    """items 引用靶：装备条目（weapon/五防具 type）+ 材料类（material_tier 两档）。"""
    items = []
    for wid in ("iron_sword", "iron_sword_1", "iron_sword_2", "flame_sword",
                "flame_sword_2", "flame_sword_3", "flame_king_sword",
                "ice_sword", "lightning_sword"):
        items.append({"id": wid, "name": wid, "type": "weapon", "quality": "normal"})
    for ttype in ("armor_head", "armor_body", "armor_hand", "armor_leg", "armor_foot"):
        items.append({"id": f"item_{ttype}", "name": f"item_{ttype}", "type": ttype})
    items.append({"id": "iron_ore", "name": "铁矿石", "type": "material",
                  "material_tier": "normal", "source": "采集点"})
    items.append({"id": "ice_crystal", "name": "冰晶", "type": "material",
                  "material_tier": "normal", "source": "采集点"})
    items.append({"id": "lightning_fang", "name": "雷兽牙", "type": "material",
                  "material_tier": "rare", "source": "雷兽掉落"})
    items.append({"id": "fire_dragon_scale", "name": "火龙鳞", "type": "material",
                  "material_tier": "rare", "source": "火龙掉落"})
    items.append({"id": "dragonite", "name": "龙脉石", "type": "material",
                  "material_tier": "rare", "source": "BOSS 掉落"})
    return items


def _legal_enemies() -> list:
    """enemies 引用靶：火弱点怪（W2 判定：元素武器有发挥空间）。"""
    return [{
        "id": "fire_lizard", "name": "火蜥蜴", "tier": "normal", "area": "熔岩洞",
        "stats": {"hp": 60, "mp": 10, "str": 8, "int": 5, "con": 6, "spr": 5,
                  "foc": 4, "agi": 7, "luk": 4},
        "weakness": {"types": ["水"], "elements": {"fire": 1.5}},
        "pv": 8, "pv_recover": "battle_end", "resistance": {},
        "actions": [], "drops": {"battle": [], "special": [], "death": []}, "lore": [],
    }]


def _legal_modules(**overrides) -> dict:
    """标准模块上下文：完整合法包（武器树+防具树+套装+客制+items+enemies）。

    零红零黄冒烟（TC-01/TC-02 基准）。overrides 可覆盖 forge 整段或 trees 等。
    """
    forge = {
        "schema_version": "1.0",
        "trees": _legal_weapon_tree() + _legal_armor_trees(),
        "sets": _legal_sets(),
        "augments": _legal_augments(),
        "settings": {
            "forge_fee": "节点等级×10", "synth_ratio_3to1": True,
            "straight_forge": True, "decompose_rate": {"正式": 0.4},
            "exp_per_forge": "节点等级×2", "sets_enabled": True,
            "augments_enabled": True,
        },
    }
    forge.update(overrides.get("forge", {}))
    modules: Dict[str, object] = {"forge": forge}
    if "items" in overrides:
        modules["items"] = overrides["items"]
    else:
        modules["items"] = _legal_items()
    if "enemies" in overrides:
        modules["enemies"] = overrides["enemies"]
    else:
        modules["enemies"] = _legal_enemies()
    return modules


def _run(modules: Mapping[str, object]) -> _Report:
    """跑 validate_forge，返回收集器。"""
    report = _Report()
    validate_forge(modules, report)
    return report


def _rules(report: _Report, level: str) -> set:
    """收集指定级别（errors/warnings）的 rule 名集合。"""
    return {e["detail"].get("rule") for e in getattr(report, level)}


def _weapon_only_modules() -> dict:
    """仅武器树 + items + enemies 的最小包（含可选 sets/augments 段开关）。"""
    forge = {
        "schema_version": "1.0",
        "trees": _legal_weapon_tree(),
        "settings": {"sets_enabled": True, "augments_enabled": True},
    }
    return {"forge": forge, "items": _legal_items(), "enemies": _legal_enemies()}


# ---------------------------------------------------------------------------
# A 派生树结构（2c2a §六 TC-01 ~ TC-04b）
# ---------------------------------------------------------------------------
def test_tc01_legal_full_loads_zero_red_zero_yellow() -> None:
    """TC-01：合法全量包（武器树+防具树+套装+客制）零红零黄。"""
    report = _run(_legal_modules())
    assert report.errors == [], f"合法包应零红，got {report.errors}"
    assert report.warnings == [], f"合法包应零黄，got {report.warnings}"


def test_tc02_tree_type_duplicate_v1() -> None:
    """TC-02：重复 trees[].type（两台 tree_weapon）→ V1 硬错。"""
    trees = _legal_weapon_tree() + [dict(_legal_weapon_tree()[0], id="tree_weapon_2")]
    report = _run({"forge": {"trees": trees}, "items": _legal_items()})
    assert "tree_type_duplicate" in _rules(report, "errors"), "V1 树 type 重复应红拦"


def test_tc01b_trees_empty_v1() -> None:
    """V1：trees 空 → 硬错（防空池，共享契约 §十 坑位5）。"""
    report = _run({"forge": {"trees": []}})
    assert "trees_empty" in _rules(report, "errors"), "trees 空应 V1 红拦"


def test_v1_tree_id_duplicate() -> None:
    """V1：树 id 重复 → 硬错。"""
    trees = _legal_weapon_tree() + [
        dict(_legal_weapon_tree()[0], id="tree_weapon", type="armor_head")]
    report = _run({"forge": {"trees": trees}})
    assert "tree_id_duplicate" in _rules(report, "errors"), "树 id 重复应 V1 红拦"


# ---------------------------------------------------------------------------
# B 节点字段与双源仲裁（TC-05 ~ TC-09）
# ---------------------------------------------------------------------------
def test_tc05_node_id_duplicate_v2() -> None:
    """TC-20/TC-05：节点 id 全文件重复 → V2 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["id"] = "node_iron_sword_1"
    report = _run(m)
    assert "node_id_duplicate" in _rules(report, "errors"), "节点 id 重复应 V2 红拦"


def test_v2_node_type_mismatch_tree() -> None:
    """V2：节点 type 与所属树不一致 → 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["type"] = "armor_head"
    report = _run(m)
    assert "node_type_tree_mismatch" in _rules(report, "errors"), "节点 type 与树不一致应 V2 红拦"


def test_tc05_node_item_parse_and_merge() -> None:
    """TC-05：node.item 引用 items 存在；/锻造 完成实例 = items 基础 + 节点改造合并。

    断言 ForgeNode.item 访问器（item/output_item 别名）+ merge_node_item 双源仲裁
    （AR-1 覆盖 / AR-2 追加 / AR-3 品质）。
    """
    items = {"id": "iron_sword", "name": "铁剑", "type": "weapon", "quality": "normal",
             "stats": {"atk": 5, "def": 2}}
    node = cast(ForgeNode, ForgeNode.from_entry({
        "id": "node_iron_sword_2", "name": "铁剑Ⅱ", "item": "iron_sword",
        "type": "weapon", "level": 3, "stats": {"atk": 24}, "rarity": "legendary",
    }))
    assert node.item == "iron_sword"
    merged = merge_node_item(items, node)
    # AR-1 覆盖：节点声明的 stats.atk 覆盖 items
    assert merged["stats"]["atk"] == 24  # type: ignore[index]
    # AR-2 追加：节点未声明的 stats.def 继承 items
    assert merged["stats"]["def"] == 2  # type: ignore[index]
    # AR-3 品质：节点 rarity 覆盖 items.quality
    assert merged["rarity"] == "legendary"
    # 冗余键
    assert merged["node_id"] == "node_iron_sword_2"
    assert merged["item_id"] == "iron_sword"


def test_merge_rarity_inherit_when_undeclared() -> None:
    """TC-09：节点未配置 rarity → 继承 items.quality（AR-3）。"""
    items = {"id": "iron_sword", "name": "铁剑", "type": "weapon", "quality": "fine"}
    node = cast(ForgeNode, ForgeNode.from_entry({
        "id": "node_x", "item": "iron_sword", "type": "weapon", "level": 1,
        "parent": None, "materials": [{"item": "iron_ore", "count": 1}], "final": False,
    }))
    merged = merge_node_item(items, node)
    assert merged["rarity"] == "fine", "节点未声明 rarity 应继承 items.quality"


def test_merge_rarity_override_conflict() -> None:
    """TC-09：节点 rarity 与 items.quality 冲突 → 以节点为准（AR-3）。"""
    items = {"id": "x", "name": "x", "type": "weapon", "quality": "normal"}
    node = cast(ForgeNode, ForgeNode.from_entry({
        "id": "node_x", "item": "x", "type": "weapon", "level": 1, "parent": None,
        "materials": [{"item": "iron_ore", "count": 1}], "final": False,
        "rarity": "legendary",
    }))
    assert merge_node_item(items, node)["rarity"] == "legendary"


def test_tc08_item_alias_duplicate_v7() -> None:
    """TC-08：同一节点同时写 item 与 output_item（别名双写）→ V7 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][1]["output_item"] = "iron_sword_1"
    report = _run(m)
    assert "item_alias_duplicate" in _rules(report, "errors"), "别名双写应 V7 红拦"


def test_merge_node_item_slot_override() -> None:
    """AR-1：节点 slots 覆盖 items（带孔装备唯一来源，TC-06）。"""
    items = {"id": "x", "name": "x", "type": "weapon"}
    node = cast(ForgeNode, ForgeNode.from_entry({
        "id": "node_x", "item": "x", "type": "weapon", "level": 1, "parent": None,
        "materials": [{"item": "iron_ore", "count": 1}], "final": True,
        "slots": [{"level": 1}],
    }))
    merged = merge_node_item(items, node)
    assert merged["slots"] == [{"level": 1}], "节点 slots 应覆盖 items（AR-1）"


# ---------------------------------------------------------------------------
# C 素材两档（TC-10/TC-11）
# ---------------------------------------------------------------------------
def test_tc10_material_tier_derivation() -> None:
    """TC-10：items 材料元数据 material_tier 两档落位（V10 材料类判定）。"""
    report = _run(_legal_modules())
    assert "material_not_material_class" not in _rules(report, "errors")
    # 素材行缺省 tier 派生正确：iron_ore normal / fire_dragon_scale rare（items 元数据）
    mats = {m["id"]: m for m in _legal_modules()["items"] if "material_tier" in m}
    assert mats["iron_ore"]["material_tier"] == "normal"
    assert mats["fire_dragon_scale"]["material_tier"] == "rare"


def test_tc11_material_row_tier_override_legal() -> None:
    """TC-11：素材行显式 tier 覆写合法（M-03 行覆写 > items 元数据）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["materials"] = [
        {"item": "iron_ore", "count": 1, "tier": "rare"}]  # items normal → 行覆写 rare
    report = _run(m)
    assert report.errors == [], "行覆写 tier 合法，应零红"


# ---------------------------------------------------------------------------
# D 校验器（TC-19 ~ TC-24b）—— V1~V15 硬 / V16+W1~W6 黄
# ---------------------------------------------------------------------------
def test_tc19_parent_missing_v3() -> None:
    """TC-19：parent 指向不存在 id → V3 硬错（报缺失 id）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][1]["parent"] = "node_ghost"
    report = _run(m)
    assert "parent_missing" in _rules(report, "errors"), "parent 悬空应 V3 红拦"


def test_v3_parent_cross_tree() -> None:
    """V3：parent 指向他树节点 → 硬错（父节点须同树）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][1]["parent"] = "node_dk_armor_head"
    report = _run(m)
    assert "parent_cross_tree" in _rules(report, "errors"), "parent 跨树应 V3 红拦"


def test_v3_root_missing() -> None:
    """V3：roots 每 id 存在；roots 引用未定义 → 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["roots"] = ["node_ghost_root"]
    report = _run(m)
    assert "root_missing" in _rules(report, "errors"), "root 悬空应 V3 红拦"


def test_tc19b_parent_cycle_v4() -> None:
    """TC-19：父链成环（A→B→A）→ V4 硬错（报环路路径）。"""
    m = _legal_modules()
    nodes = m["forge"]["trees"][0]["nodes"]
    nodes[0]["parent"] = "node_flame_sword"  # iron_sword → flame_sword
    # （成环：iron_sword_2→flame_sword→...）
    report = _run(m)
    rules = _rules(report, "errors")
    assert "parent_cycle" in rules or "parent_self_cycle" in rules, \
        "父链成环应 V4 红拦"


def test_v4_root_not_declared() -> None:
    """V4：parent=null 的节点未在 roots 声明 → 硬错（每节点可达某一根）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["roots"] = ["node_iron_sword"]
    # 把 node_ice_sword 的 parent 清空 → 成为未声明的根
    for n in m["forge"]["trees"][0]["nodes"]:
        if n["id"] == "node_ice_sword":
            n["parent"] = None
    report = _run(m)
    assert "root_not_declared" in _rules(report, "errors"), "未声明根应 V4 红拦"


def test_tc20_branch_dangling_v5() -> None:
    """TC-20：branch 指向悬空 id → V5 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][2]["branch"] = ["node_ghost_branch"]
    report = _run(m)
    assert "branch_missing" in _rules(report, "errors"), "branch 悬空应 V5 红拦"


def test_v5_branch_duplicate_warning() -> None:
    """V5：重复分支 id → 黄提示（去重告警，不阻断）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][2]["branch"] = ["node_ice_sword", "node_ice_sword"]
    report = _run(m)
    assert "branch_duplicate" in _rules(report, "warnings"), "branch 重复应黄提示"


def test_tc04_leaf_not_final_v6() -> None:
    """TC-04/TC-23：线终点（叶子）final=false → V6 硬错。"""
    m = _legal_modules()
    for n in m["forge"]["trees"][0]["nodes"]:
        if n["id"] == "node_ice_sword":  # 叶子 → 强制 final=false
            n["final"] = False
    report = _run(m)
    assert "leaf_not_final" in _rules(report, "errors"), "叶子非 final 应 V6 红拦"


def test_tc04b_final_has_child_v6() -> None:
    """TC-04：final=true 节点有子节点 → V6 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][2]["final"] = True  # 铁剑Ⅱ 有子（炎剑/冰剑/雷剑）
    report = _run(m)
    assert "final_has_child" in _rules(report, "errors"), "final=true 有子应 V6 红拦"


def test_tc21_item_missing_v7() -> None:
    """TC-21：node.item 引用缺失 → V7 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["item"] = "ghost_sword"
    report = _run(m)
    assert "item_missing" in _rules(report, "errors"), "node.item 缺失应 V7 红拦"


def test_tc21b_item_type_mismatch_v8() -> None:
    """TC-21：items 条目类型 ≠ node.type → V8 硬错。"""
    m = _legal_modules()
    for it in m["items"]:
        if it["id"] == "iron_sword":
            it["type"] = "armor_head"
    report = _run(m)
    assert "item_type_mismatch" in _rules(report, "errors"), "items 类型不匹配应 V8 红拦"


def test_tc24_stat_key_drift_v9() -> None:
    """V9：改造键不在 items 元数据键空间内（防新键漂移）→ 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][2]["stats"] = {"atk_drift": 1}
    report = _run(m)
    assert "stat_key_drift" in _rules(report, "errors"), "改造键漂移应 V9 红拦"


def test_tc24_stat_override_w1() -> None:
    """TC-24：节点 stats.atk 与 items 同键 → V1~V15 通过 + W1 黄提示（覆盖生效不阻断）。"""
    m = _weapon_only_modules()
    # items 装备条目带 atk 键（模拟瘦 items 冲突）
    for it in m["items"]:
        if it["id"] == "iron_sword_2":
            it["stats"] = {"atk": 10}
    report = _run(m)
    assert "stat_override_items" in _rules(report, "warnings"), "同键冲突应 W1 黄"
    assert report.errors == [], "W1 不阻断：应零红"


def test_tc22_material_not_material_class_v10() -> None:
    """TC-22：素材引用非材料类物品 → V10 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["materials"] = [
        {"item": "iron_sword", "count": 1}]  # 装备条目（非材料类）
    report = _run(m)
    assert "material_not_material_class" in _rules(report, "errors"), \
        "素材非材料类应 V10 红拦"


def test_v10_material_item_missing() -> None:
    """TC-22：materials[].item 缺失 → V10 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["materials"] = [{"item": "ghost_mat", "count": 1}]
    report = _run(m)
    assert "material_item_missing" in _rules(report, "errors"), "素材引用缺失应 V10 红拦"


def test_v11_material_count_tier() -> None:
    """V11：count<1 或 tier 非法 → 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["materials"] = [
        {"item": "iron_ore", "count": 0, "tier": "epic"}]
    report = _run(m)
    rules = _rules(report, "errors")
    assert "material_count_invalid" in rules, "count<1 应 V11 红拦"
    assert "material_tier_invalid" in rules, "tier 非法应 V11 红拦"


def test_v11_materials_required() -> None:
    """V11：materials 每节点 ≥1 行（缺行 → 硬错）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0].pop("materials")
    report = _run(m)
    assert "materials_required" in _rules(report, "errors"), "materials 缺行应 V11 红拦"


def test_v12_node_level_invalid() -> None:
    """V12：level<1 或非整数 → 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["level"] = 0
    report = _run(m)
    assert "node_level_invalid" in _rules(report, "errors"), "level 非法应 V12 红拦"


def test_v13_rarity_invalid() -> None:
    """V13：rarity 非四档（且非历史整数）→ 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["rarity"] = "mythic"
    report = _run(m)
    assert "rarity_invalid" in _rules(report, "errors"), "rarity 非法应 V13 红拦"


def test_v13_rarity_int_compat_legal() -> None:
    """V13：历史整数 1-4 兼容映射合法（不报红）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["rarity"] = 3  # epic
    report = _run(m)
    assert "rarity_invalid" not in _rules(report, "errors"), "整数品质应兼容"
    assert RARITY_INT_MAP[3] == "epic"


def test_v14_slot_level_invalid() -> None:
    """V14：slots[].level ∉ {1,2,3} → 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][6]["slots"] = [{"level": 4}]  # 炎王剑
    report = _run(m)
    assert "slot_level_invalid" in _rules(report, "errors"), "孔位 level 非法应 V14 红拦"


def test_v15_red_name_referenced() -> None:
    """V15：级联删除复查——红名节点（item 缺失）仍被 parent 引用 → 硬错。"""
    m = _legal_modules()
    for n in m["forge"]["trees"][0]["nodes"]:
        if n["id"] == "node_iron_sword":  # 红名化：item 引用缺失
            n["item"] = "ghost_item"
    report = _run(m)
    rules = _rules(report, "errors")
    assert "red_name_referenced" in rules, "红名节点被引用应 V15 红拦"


def test_v16_augmentable_not_final_weapon_warning() -> None:
    """V16 黄：augmentable=true 且 final=false 或非武器 → 黄提示（不阻断）。"""
    m = _legal_modules()
    for n in m["forge"]["trees"][0]["nodes"]:
        if n["id"] == "node_iron_sword":
            n["augmentable"] = True  # final=false 非最终武器
    report = _run(m)
    assert "augmentable_not_final_weapon" in _rules(report, "warnings"), \
        "augmentable 非最终武器应 V16 黄"
    assert report.errors == [], "V16 黄不阻断"


def test_w2_element_no_weak_enemy() -> None:
    """W2 黄：元素武器节点带元素但怪物表无弱该属性怪 → 黄提示（TC-24b）。"""
    m = _weapon_only_modules()
    # 删掉火弱点怪（enemies 只留无弱点的怪）
    m["enemies"] = [dict(_legal_enemies()[0], weakness={"types": [], "elements": {}})]
    report = _run(m)
    assert "element_no_weak_enemy" in _rules(report, "warnings"), \
        "元素无弱点怪应 W2 黄"
    assert report.errors == [], "W2 黄不阻断"


def test_w3_sets_disabled_but_data() -> None:
    """W3 黄：settings 关闭 P1（sets_enabled=false）但 sets 数据存在 → 黄提示。"""
    m = _legal_modules()
    m["forge"]["settings"]["sets_enabled"] = False
    report = _run(m)
    assert "sets_disabled_but_data" in _rules(report, "warnings"), \
        "settings 关 P1 但数据存在应 W3 黄"


def test_w3_augments_disabled_but_data() -> None:
    """W3 黄：settings 关闭 P2（augments_enabled=false）但 augments 数据存在 → 黄提示。"""
    m = _legal_modules()
    m["forge"]["settings"]["augments_enabled"] = False
    report = _run(m)
    assert "augments_disabled_but_data" in _rules(report, "warnings"), \
        "settings 关 P2 但数据存在应 W3 黄"


def test_w4_synth_off_deadlock_risk() -> None:
    """W4 黄：synth_ratio_3to1=false 且存在稀有素材需求 → 黄提示（素材死锁风险）。"""
    m = _legal_modules()
    m["forge"]["settings"]["synth_ratio_3to1"] = False
    report = _run(m)
    assert "synth_off_deadlock_risk" in _rules(report, "warnings"), \
        "合成关闭+稀有素材应 W4 黄"
    assert report.errors == [], "W4 黄不阻断"


def test_w5_node_scale_weapon() -> None:
    """W5 黄：武器节点总量超 500 → 黄提示（配置负担预警，不阻断）。"""
    # 构造 501 个武器节点（共享 parent 链太繁，直接手搓一个超大树）
    nodes = []
    for i in range(501):
        nodes.append({"id": f"node_bulk_{i}", "name": f"B{i}", "item": "iron_sword",
                      "type": "weapon", "level": 1,
                      "parent": (f"node_bulk_{i-1}" if i else None),
                      "materials": [{"item": "iron_ore", "count": 1}],
                      "final": False})
    nodes[-1]["final"] = True  # 末端叶子 final
    report = _run({"forge": {"trees": [{
        "id": "tree_bulk", "name": "超大武器树", "type": "weapon",
        "roots": ["node_bulk_0"], "nodes": nodes}]},
        "items": _legal_items()})
    assert "weapon_scale" in _rules(report, "warnings"), "武器超规模应 W5 黄"
    assert report.errors == [], "W5 黄不阻断"


def test_w6_root_level_not_1() -> None:
    """W6 黄：根节点 level≠1 → 建议根=1 黄提示（不阻断）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["level"] = 3
    report = _run(m)
    assert "root_level_not_1" in _rules(report, "warnings"), "根 level≠1 应 W6 黄"
    assert report.errors == [], "W6 黄不阻断"


# ---------------------------------------------------------------------------
# 2c2d 套装（V1/V2/V3 + W1/W4 黄）
# ---------------------------------------------------------------------------
def test_2c2d_v1_set_family_variant_unique() -> None:
    """2c2d V1：套装族 id 重复 / (id, variant) 组合重复 → 硬错。"""
    # 族 id 重复
    m = _legal_modules()
    m["forge"]["sets"].append(dict(_legal_sets()[0], variant="beta"))
    report = _run(m)
    # 同族 beta 是新 variant，组合不重复；但 id 族级唯一判定：beta 记录 id 相同 → 重复？
    # 契约 V1「sets[].id 族级唯一；同族 variant ∈ {alpha,beta} 且 (id,variant) 唯一」——
    # α/β 两条记录共用族 id 是合法形态（VAR-01），故族 id 允许重复、组合唯一。
    assert report.errors == [], "α/β 双记录共用族 id 应合法（VAR-01）"
    # 组合重复（同族同 variant）
    m2 = _legal_modules()
    m2["forge"]["sets"].append(dict(_legal_sets()[0]))  # 同 alpha 完全重复
    report2 = _run(m2)
    assert "set_variant_duplicate" in _rules(report2, "errors"), \
        "(id,variant) 组合重复应 V1 红拦"


def test_2c2d_v1_set_variant_invalid() -> None:
    """2c2d V1：variant ∉ {alpha,beta} → 硬错。"""
    m = _legal_modules()
    m["forge"]["sets"][0]["variant"] = "gamma"
    report = _run(m)
    assert "set_variant_invalid" in _rules(report, "errors"), "variant 非法应 V1 红拦"


def test_2c2d_v2_set_pieces() -> None:
    """2c2d V2：pieces 悬空 / 非防具部位 / 部位重复 / >5 → 硬错。"""
    # 悬空引用
    m = _legal_modules()
    m["forge"]["sets"][0]["pieces"] = ["node_ghost"]
    report = _run(m)
    assert "set_piece_missing" in _rules(report, "errors"), "套装件悬空应 V2 红拦"
    # 非防具部位
    m2 = _legal_modules()
    m2["forge"]["sets"][0]["pieces"] = ["node_iron_sword", "node_dk_armor_body"]
    report2 = _run(m2)
    assert "set_piece_not_armor" in _rules(report2, "errors"), "套装件非防具应 V2 红拦"
    # 部位重复
    m3 = _legal_modules()
    m3["forge"]["sets"][0]["pieces"] = ["node_dk_armor_head", "node_dk_armor_head"]
    report3 = _run(m3)
    assert "set_piece_duplicate" in _rules(report3, "errors"), "套装件重复应 V2 红拦"
    # >5 项
    m4 = _legal_modules()
    m4["forge"]["sets"][0]["pieces"] = [
        "node_dk_armor_head", "node_dk_armor_body", "node_dk_armor_hand",
        "node_dk_armor_leg", "node_dk_armor_foot", "node_iron_sword"]
    report4 = _run(m4)
    assert "set_pieces_too_many" in _rules(report4, "errors"), "套装件>5 应 V2 红拦"


def test_2c2d_v3_set_skill_piece_count() -> None:
    """2c2d V3：piece_count ∉ {2,3,5} → 硬错（TC-23：档位 2,4,5 缺 3）。"""
    m = _legal_modules()
    m["forge"]["sets"][0]["skills"] = [
        {"piece_count": 2, "skill": "dragon_guard", "level": 1},
        {"piece_count": 4, "skill": "dragon_guard", "level": 2},  # 4 非法
        {"piece_count": 5, "skill": "dragon_guard", "level": 3},
    ]
    report = _run(m)
    assert "set_skill_piece_count_invalid" in _rules(report, "errors"), \
        "piece_count 非法应 V3 红拦"


def test_2c2d_v3_set_skill_gap() -> None:
    """2c2d V3：同一 skill 档位跳档（2,5 缺 3）→ 硬错。"""
    m = _legal_modules()
    m["forge"]["sets"][0]["skills"] = [
        {"piece_count": 2, "skill": "dragon_guard", "level": 1},
        {"piece_count": 5, "skill": "dragon_guard", "level": 3},  # 缺 3
    ]
    report = _run(m)
    assert "set_skill_gap" in _rules(report, "errors"), "档位跳档应 V3 红拦"


def test_2c2d_v3_set_skill_level_invalid() -> None:
    """2c2d V3：level ∉ {1,2,3} → 硬错。"""
    m = _legal_modules()
    m["forge"]["sets"][0]["skills"][0]["level"] = 5
    report = _run(m)
    assert "set_skill_level_invalid" in _rules(report, "errors"), "技能 level 非法应 V3 红拦"


def test_2c2d_w1_alpha_beta_slot_mismatch() -> None:
    """2c2d W1 黄：同族 α/β 孔位对照（α > β）→ 黄提示（不阻断）。"""
    m = _legal_modules()
    beta = dict(_legal_sets()[0], variant="beta")
    # β 版头部换用 β 专用无孔节点（其余 4 件同 α）；α 版头部加 1 孔
    # → α 孔位(1) > β 孔位(0) → W1
    beta["pieces"] = ["node_dk_armor_head_beta", "node_dk_armor_body",
                      "node_dk_armor_hand", "node_dk_armor_leg", "node_dk_armor_foot"]
    m["forge"]["sets"].append(beta)
    for t in m["forge"]["trees"]:
        for n in t.get("nodes", []):
            if n["id"] == "node_dk_armor_head":
                n["slots"] = [{"level": 1}]
    report = _run(m)
    assert "alpha_beta_slot_mismatch" in _rules(report, "warnings"), \
        "α 孔位>β 应 W1 黄"
    assert report.errors == [], "W1 黄不阻断"


def test_2c2d_w4_set_skill_level_over_cap() -> None:
    """2c2d W4 黄：套装技能 level 超默认封顶 3 → 黄提示（数值膨胀风险）。"""
    m = _legal_modules()
    m["forge"]["sets"][0]["skills"][0]["level"] = 4
    report = _run(m)
    assert "set_skill_level_over_cap" in _rules(report, "warnings"), \
        "技能 level 超封顶应 W4 黄"
    # V3 硬：level=4 超出 {1,2,3} 默认封顶 → 同时红拦（TC-23：level=4 未改上限 → V3 硬拦）
    assert "set_skill_level_invalid" in _rules(report, "errors"), \
        "level=4 超默认封顶应 V3 硬拦"


# ---------------------------------------------------------------------------
# 2c2d 客制（V4/V5/V6/V8 + W2 黄）
# ---------------------------------------------------------------------------
def test_2c2d_v4_augment_structure() -> None:
    """2c2d V4：kind 非法 / numeric 缺 stat_key / slot 缺 slot_level / cost 空 → 硬错。"""
    # kind 非法
    m = _legal_modules()
    m["forge"]["augments"]["augments"][0]["kind"] = "heal"
    report = _run(m)
    assert "augment_kind_invalid" in _rules(report, "errors"), "kind 非法应 V4 红拦"
    # numeric 缺 stat_key
    m2 = _legal_modules()
    m2["forge"]["augments"]["augments"][0].pop("stat_key")
    report2 = _run(m2)
    assert "augment_numeric_stat_key_required" in _rules(report2, "errors"), \
        "numeric 缺 stat_key 应 V4 红拦"
    # slot 缺 slot_level
    m3 = _legal_modules()
    m3["forge"]["augments"]["augments"][3].pop("slot_level")
    report3 = _run(m3)
    assert "augment_slot_level_invalid" in _rules(report3, "errors"), \
        "slot 缺 slot_level 应 V4 红拦"
    # cost 空
    m4 = _legal_modules()
    m4["forge"]["augments"]["augments"][0]["cost"] = []
    report4 = _run(m4)
    assert "augment_cost_required" in _rules(report4, "errors"), "cost 空应 V4 红拦"


def test_2c2d_v5_augment_cost_ref() -> None:
    """2c2d V5：客制消耗引用（items 缺失 / 龙脉石非 rare）→ 硬错。"""
    # 消耗 item 缺失
    m = _legal_modules()
    m["forge"]["augments"]["augments"][0]["cost"] = [{"item": "ghost", "count": 1}]
    report = _run(m)
    assert "augment_cost_item_missing" in _rules(report, "errors"), \
        "客制消耗缺失应 V5 红拦"
    # 龙脉石类非 rare（items 材料 tier normal）
    m2 = _legal_modules()
    m2["forge"]["augments"]["augments"][0]["cost"] = [{"item": "iron_ore", "count": 1}]
    report2 = _run(m2)
    assert "augment_cost_not_rare" in _rules(report2, "errors"), \
        "龙脉石类非 rare 应 V5 红拦"


def test_2c2d_v6_limit_by_rarity() -> None:
    """2c2d V6：quality 非法 / 同 quality>2 行 / final_only 非 legendary / times<1 → 硬错。"""
    # quality 非法（整数/R 口径禁入）
    m = _legal_modules()
    m["forge"]["augments"]["limit_by_rarity"][0]["quality"] = 3
    report = _run(m)
    assert "limit_quality_invalid" in _rules(report, "errors"), "quality 非法应 V6 红拦"
    # 同 quality >2 行
    m2 = _legal_modules()
    m2["forge"]["augments"]["limit_by_rarity"].append(
        {"quality": "legendary", "times": 1, "final_only": False})
    report2 = _run(m2)
    assert "limit_quality_too_many" in _rules(report2, "errors"), \
        "同 quality>2 行应 V6 红拦"
    # final_only 非 legendary
    m3 = _legal_modules()
    m3["forge"]["augments"]["limit_by_rarity"][0]["final_only"] = True  # epic
    report3 = _run(m3)
    assert "limit_final_only_requires_legendary" in _rules(report3, "errors"), \
        "final_only 非 legendary 应 V6 红拦"
    # times<1
    m4 = _legal_modules()
    m4["forge"]["augments"]["limit_by_rarity"][0]["times"] = 0
    report4 = _run(m4)
    assert "limit_times_invalid" in _rules(report4, "errors"), "times<1 应 V6 红拦"


def test_2c2d_v7_node_extension_warning() -> None:
    """2c2d V7 黄：king_only level<7 / final_tier 非终盘 → 黄提示（不阻断）。"""
    m = _legal_modules()
    for n in m["forge"]["trees"][0]["nodes"]:
        if n["id"] == "node_iron_sword_1":
            n["king_only"] = True  # level=2 <7 → 黄
        if n["id"] == "node_iron_sword":  # 非 final 非 legendary 标 final_tier
            n["final_tier"] = True
    report = _run(m)
    rules = _rules(report, "warnings")
    assert "king_only_level" in rules, "king_only level<7 应 2c2d V7 黄"
    assert "final_tier_invalid" in rules, "final_tier 非终盘应 2c2d V7 黄"
    assert report.errors == [], "2c2d V7 黄不阻断"


def test_2c2d_v7_king_only_not_bool() -> None:
    """2c2d V7 硬：king_only/final_tier 非布尔 → 硬错。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["king_only"] = "yes"
    report = _run(m)
    assert "king_only_not_bool" in _rules(report, "errors"), "king_only 非布尔应硬错"


def test_2c2d_v8_all_augments_disabled() -> None:
    """2c2d V8 黄：客制全段 disabled 且 settings 开 → 配置意图存疑黄提示。"""
    m = _legal_modules()
    for a in m["forge"]["augments"]["augments"]:
        a["disabled"] = True
    report = _run(m)
    assert "augments_all_disabled" in _rules(report, "warnings"), \
        "全段 disabled 应 2c2d V8 黄"
    assert report.errors == [], "2c2d V8 黄不阻断"


def test_2c2d_w2_augment_trace_legacy() -> None:
    """2c2d W2 黄：追溯行 trace=true（aug_heal 类）→ 黄提示（回复已砍不生效）。"""
    m = _legal_modules()
    m["forge"]["augments"]["augments"].append({
        "id": "aug_heal", "name": "回复", "kind": "numeric",
        "effect": "吸血5%（已砍）", "stat_key": "lifesteal",
        "disabled": True, "trace": True})
    report = _run(m)
    assert "augment_trace_legacy" in _rules(report, "warnings"), \
        "追溯行应 2c2d W2 黄"


# ---------------------------------------------------------------------------
# 收集器三形态 / 模块元数据
# ---------------------------------------------------------------------------
def test_report_dict_form() -> None:
    """收集器 dict 形态：{"errors":[],"warnings":[]}（_emit 兜底）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["level"] = 0  # 造 V12 红
    report: Dict[str, list] = {"errors": [], "warnings": []}
    validate_forge(m, report)
    assert report["errors"], "dict 形态应收集 errors"
    assert report["errors"][0]["args"][0] == "forge"  # module
    assert report["errors"][0]["args"][2] == "V12"


def test_report_checker_form() -> None:
    """真实 validator._Checker 收口兼容（_err/_warn 回落）。"""
    m = _legal_modules()
    m["forge"]["trees"][0]["nodes"][0]["level"] = 0
    # 用默认 field_meta 表构建 _Checker（forge 未登记 → 泛型放行，但 _err 回落可测）
    from qbot_rpg.content.field_meta import default_field_meta_table
    checker = _Checker(m, default_field_meta_table())
    validate_forge(m, checker)
    assert any(e.kind == "V12" for e in checker.errors), "_Checker 应收集 V12"


def test_forge_module_meta_entry_type_object() -> None:
    """forge_module_meta()：entry_type=object（forge.json 顶层 obj 非 list）+ fields={}。"""
    meta = forge_module_meta()
    assert meta.entry_type == "object", "forge 顶层是 obj 非 list → entry_type=object"
    assert meta.kind == "forge"
    # fields={} 空表：根节点 parent=null 等可空字段防泛型 R-1 误拦，
    # 深结构校验由 validate_forge 专项全权（对齐 dungeon/npc/shop 口径）
    assert meta.fields == {}, "fields={} 空表（专项校验器全权）"


def test_def_accessors() -> None:
    """Def 类访问器冒烟（ForgeTree/ForgeNode/MaterialReq/SetSkill/ForgeSet/
    AugmentRow/LimitByRarity/ForgeSettings 字段可解析）。"""
    tree = cast(ForgeTree, ForgeTree.from_entry({
        "id": "tree_weapon", "name": "武器树", "type": "weapon",
        "roots": ["node_iron_sword"], "nodes": _legal_weapon_tree()[0]["nodes"],
    }))
    assert tree.tree_type == "weapon"
    assert tree.roots == ("node_iron_sword",)
    nodes = tree.node_defs()
    assert nodes[0].id == "node_iron_sword"
    assert nodes[0].item == "iron_sword"
    assert nodes[6].is_final is True
    mats = nodes[6].material_defs()
    assert mats[0].item == "fire_dragon_scale"
    assert mats[0].count == 2

    s = cast(ForgeSet, ForgeSet.from_entry(_legal_sets()[0]))
    assert s.variant == "alpha"
    assert s.pieces[0] == "node_dk_armor_head"
    sk = s.skill_defs()
    assert sk[0].piece_count == 2 and sk[0].skill == "dragon_guard" and sk[0].level == 1

    a = cast(AugmentRow, AugmentRow.from_entry(_legal_augments()["augments"][0]))
    assert a.aug_kind == "numeric" and a.stat_key == "atk"
    assert a.cost[0]["item"] == "dragonite"
    lim = LimitByRarity.from_entry(_legal_augments()["limit_by_rarity"][0])
    assert lim.quality == "epic" and lim.times == 3 and lim.final_only is False

    fs = ForgeSettings.from_entry({"forge_fee": "节点等级×10", "synth_ratio_3to1": False})
    assert fs.synth_ratio_3to1 is False
    assert fs.sets_enabled is True  # 缺省 true


def test_constants_coverage() -> None:
    """常量边界（共享契约 §一~§五 枚举快照）。"""
    assert FORGE_TREE_TYPES == (
        "weapon", "armor_head", "armor_body", "armor_hand", "armor_leg", "armor_foot")
    assert RARITY_TIERS == ("normal", "fine", "epic", "legendary")
    assert MATERIAL_TIERS == ("normal", "rare")
    assert SLOT_LEVELS == (1, 2, 3)
    assert SET_VARIANTS == ("alpha", "beta")
    assert SET_PIECE_COUNTS == (2, 3, 5)
    assert LIMIT_RARITY_QUALITIES == ("normal", "fine", "epic", "legendary")
    assert len(FORGE_ELEMENTS) == 8
    assert "atk" in FORGE_STAT_KEY_SPACE and "element" in FORGE_STAT_KEY_SPACE


# ---------------------------------------------------------------------------
# 模块缺失放行（对齐既有校验器惯例：forge 未接线 → 跳过不硬拦）
# ---------------------------------------------------------------------------
def test_forge_missing_module_skipped() -> None:
    """forge 模块缺失/非 Mapping → 跳过不硬拦（默认放行）。"""
    report = _run({})
    assert report.errors == [] and report.warnings == []
    report2 = _run({"forge": "not-a-mapping"})
    assert report2.errors == [] and report2.warnings == []
