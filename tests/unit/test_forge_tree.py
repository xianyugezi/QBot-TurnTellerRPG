"""M9 锻造·批1·路1A：派生树引擎单元测试（tests/unit/test_forge_tree.py）。

文件名：test_forge_tree.py
创建时间：2026-08-30
作者：Hermes 子agent-1A（M9 锻造实现组批1·路1A：并发同仓，仅新建本文件 +
qbot_rpg/core/forge_tree.py；不改动批0 既有文件）

依据：docs/m9_shared_contract.md §一~§三（字段表/派生树拓扑/AR-1~5）+
docs/细化/细化_2c2a_锻造派生树schema.md（§二 派生树结构 / §1.3 双源仲裁 / §六 TC-01~27）+
docs/细化/细化_2c2b_锻造流程契约.md（§1.1 守卫 GU-03/04/06 / §五 5.2 匹配算法）。
测试目标：qbot_rpg.core.forge_tree.ForgeTreeEngine 全方法 + 真实 forge.json 兼容。

覆盖矩阵：
  A 树加载与遍历：load_trees 9 节点解析 / children_of / branch_of / path_to_root /
    subtree_of（含分支）
  B 可锻性判定：parent_forged（前置已锻/缺前置）/ already_forged / node_level_met（等级门槛）
  C 节点查找：resolve_node 三态（精确 / 唯一前缀 / 歧义列表）
  D 实例合并：merge_forge_instance 覆盖（AR-1）/ 追加（AR-2）/ 品质（AR-3）/ 快照字段（AR-5）
  E 最终强化：final_of / line_endpoint

铁律：零 NoneBot import；纯函数确定性；不写 time.sleep；不引入随机。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, cast

from qbot_rpg.core.forge_tree import FORGE_JOB_ID, ForgeTreeEngine, match_name

# 仓库根 = tests/unit/test_forge_tree.py 上溯两级
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORGE_JSON = _REPO_ROOT / "content" / "test_demo" / "forge.json"
_ITEMS_JSON = _REPO_ROOT / "content" / "test_demo" / "items.json"

# 武器树 9 节点（forge.json 文件序；契约 §九 样例拓扑）
N_IRON = "node_iron_sword"          # 铁剑（根，level1）
N_IRON_1 = "node_iron_sword_1"      # 铁剑Ⅰ（level2）
N_IRON_2 = "node_iron_sword_2"      # 铁剑Ⅱ（level3，带 1 级孔）
N_FLAME = "node_flame_sword"        # 炎剑（level4，火）
N_FLAME_2 = "node_flame_sword_2"    # 炎剑Ⅱ（level5，branch→冰/雷）
N_FLAME_3 = "node_flame_sword_3"    # 炎剑Ⅲ（level6）
N_KING = "node_flame_king_sword"    # ■炎王剑（level7，final+augmentable）
N_ICE = "node_ice_sword"            # 冰剑（level5，final 分支）
N_LIGHT = "node_lightning_sword"    # 雷剑（level5，final 分支）

_TREE_ID = "tree_weapon"


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _engine() -> ForgeTreeEngine:
    """构造引擎（forge.json + items.json + settings.json 真实数据；独立 items 表可覆写）。"""
    forge = cast(Mapping, _load_json(_FORGE_JSON))
    items = _load_json(_ITEMS_JSON)
    return ForgeTreeEngine(forge=forge, items=items, settings={})


def _player(
    *,
    forged: object = None,
    forge_level: int = 0,
    with_prof: bool = True,
) -> Dict[str, object]:
    """构造玩家 dict（proficiency.forge.level + forged 集合；可配）。"""
    prof = {}
    if with_prof:
        prof = {FORGE_JOB_ID: {"level": forge_level, "exp": 0}}
    return {"proficiency": prof, "forged": forged}


# ---------------------------------------------------------------------------
# A 树加载与遍历
# ---------------------------------------------------------------------------
def test_load_trees_real_forge_json() -> None:
    """正例：forge.json 真实数据 1 棵树 9 节点全解析（TC-01 落库）。"""
    eng = _engine()
    trees = eng.load_trees()
    assert len(trees) == 1
    tree = trees[0]
    assert tree.id == _TREE_ID
    assert tree.tree_type == "weapon"
    assert len(eng.nodes()) == 9
    # roots
    assert tree.roots == (N_IRON,)
    # 关键节点字段可读
    king = eng.node(N_KING)
    assert king is not None
    assert king.name == "■炎王剑"
    assert king.level == 7
    assert king.is_final is True
    assert king.augmentable is True
    assert king.rarity == "legendary"


def test_children_of() -> None:
    """正例：父→子反向索引正确（含分支 child）。"""
    eng = _engine()
    assert eng.children_of(N_IRON) == [N_IRON_1]
    assert eng.children_of(N_IRON_1) == [N_IRON_2]
    assert eng.children_of(N_IRON_2) == [N_FLAME]
    assert eng.children_of(N_FLAME) == [N_FLAME_2]
    # 炎剑Ⅱ 子 = 炎剑Ⅲ（主线）+ 冰剑/雷剑（分支 child，parent 指向炎剑Ⅱ）
    assert eng.children_of(N_FLAME_2) == [N_FLAME_3, N_ICE, N_LIGHT]
    assert eng.children_of(N_KING) == []  # final 无子
    # 未知节点
    assert eng.children_of("node_nonexistent") == []


def test_branch_of() -> None:
    """正例：branch 列表（N-07 本线可转出其他线）。"""
    eng = _engine()
    assert eng.branch_of(N_FLAME_2) == [N_ICE, N_LIGHT]
    assert eng.branch_of(N_IRON) == []
    assert eng.branch_of("node_nonexistent") == []


def test_path_to_root() -> None:
    """正例：沿 parent 链到根（根在前含自身）；主干全长 7。"""
    eng = _engine()
    assert eng.path_to_root(N_IRON) == [N_IRON]
    assert eng.path_to_root(N_KING) == [
        N_IRON, N_IRON_1, N_IRON_2, N_FLAME, N_FLAME_2, N_FLAME_3, N_KING,
    ]
    # 分支节点：沿 parent 回溯到根（分支 child 的 parent 是炎剑Ⅱ）
    assert eng.path_to_root(N_ICE) == [N_IRON, N_IRON_1, N_IRON_2, N_FLAME, N_FLAME_2, N_ICE]
    # 未知节点
    assert eng.path_to_root("node_nonexistent") == []


def test_subtree_of() -> None:
    """正例：子树全节点（含自身 + 全部子孙，含分支 child）。"""
    eng = _engine()
    assert eng.subtree_of(N_IRON) == [
        N_IRON, N_IRON_1, N_IRON_2, N_FLAME, N_FLAME_2, N_FLAME_3, N_KING, N_ICE, N_LIGHT,
    ]
    # 炎剑Ⅱ 子树 = 主线（炎剑Ⅲ→炎王剑）+ 分支（冰剑/雷剑）
    assert eng.subtree_of(N_FLAME_2) == [N_FLAME_2, N_FLAME_3, N_KING, N_ICE, N_LIGHT]
    # 分支叶自身子树 = 自身
    assert eng.subtree_of(N_ICE) == [N_ICE]
    assert eng.subtree_of("node_nonexistent") == []


# ---------------------------------------------------------------------------
# B 可锻性判定（供 /锻造 守卫）
# ---------------------------------------------------------------------------
def test_parent_forged() -> None:
    """正例/反例：前置已锻判定（GU-04 沿 parent 链查已锻造集合）。"""
    eng = _engine()
    # 根节点无前置 → True
    assert eng.parent_forged(_player(forged=[N_IRON]), N_IRON) is True
    assert eng.parent_forged(_player(forged=[]), N_IRON) is True
    # 主干全锻 → True
    all_forged = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME, N_FLAME_2, N_FLAME_3, N_KING]
    assert eng.parent_forged(_player(forged=all_forged), N_KING) is True
    # 缺 铁剑Ⅰ（链条断裂）→ False
    assert eng.parent_forged(
        _player(forged=[N_IRON, N_IRON_2, N_FLAME, N_FLAME_2, N_FLAME_3, N_KING]), N_KING
    ) is False
    # 分支节点前置 = 铁剑…炎剑Ⅱ（branch 出口本身无要求）
    assert eng.parent_forged(
        _player(forged=[N_IRON, N_IRON_1, N_IRON_2, N_FLAME, N_FLAME_2]), N_ICE
    ) is True
    # forged 缺失/空 → 根 True / 非根 False
    assert eng.parent_forged(_player(forged=None), N_IRON) is True
    assert eng.parent_forged(_player(forged=None), N_IRON_1) is False
    # 未知节点 → False
    assert eng.parent_forged(_player(forged=[]), "node_nonexistent") is False


def test_already_forged() -> None:
    """正例/反例：已锻造判定。"""
    eng = _engine()
    p = _player(forged={N_IRON, N_KING})
    assert eng.already_forged(p, N_IRON) is True
    assert eng.already_forged(p, N_KING) is True
    assert eng.already_forged(p, N_FLAME) is False
    assert eng.already_forged(_player(forged=None), N_IRON) is False


def test_node_level_met() -> None:
    """正例/反例：节点等级门槛（GU-06 铸造职业等级 ≥ node.level）。"""
    eng = _engine()
    # 铁剑 level1：职业 0 级不可锻（0 < 1），1 级可锻
    assert eng.node_level_met(_player(forge_level=0), N_IRON) is False
    assert eng.node_level_met(_player(forge_level=1), N_IRON) is True
    # 炎剑 level4
    assert eng.node_level_met(_player(forge_level=3), N_FLAME) is False
    assert eng.node_level_met(_player(forge_level=4), N_FLAME) is True
    assert eng.node_level_met(_player(forge_level=7), N_FLAME) is True
    # ■炎王剑 level7
    assert eng.node_level_met(_player(forge_level=6), N_KING) is False
    assert eng.node_level_met(_player(forge_level=7), N_KING) is True
    # 无 proficiency 节点 → 0 级
    assert eng.node_level_met(_player(forge_level=0, with_prof=False), N_IRON) is False
    assert eng.node_level_met(_player(forge_level=0, with_prof=False), N_IRON_1) is False
    # 未知节点 → False
    assert eng.node_level_met(_player(forge_level=99), "node_nonexistent") is False


def test_forge_guard() -> None:
    """正例/反例：组合守卫 GU-03→04→06 + 已锻拦截。"""
    eng = _engine()
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME, N_FLAME_2, N_FLAME_3]
    # 全条件齐备 → ok
    r = eng.forge_guard(_player(forged=full_chain, forge_level=7), "炎王剑")
    assert r["ok"] is True and r["node_id"] == N_KING
    # 未找到
    r = eng.forge_guard(_player(forged=[]), "不存在之剑")
    assert r["ok"] is False and r["reason"] == "not_found"
    # 已锻拦截
    r = eng.forge_guard(_player(forged=[N_IRON], forge_level=1), N_IRON)
    assert r["ok"] is False and r["reason"] == "already_forged"
    # 前置未锻
    r = eng.forge_guard(_player(forged=[], forge_level=4), "炎剑")
    assert r["ok"] is False and r["reason"] == "parent_not_forged"
    # 等级不足（前置齐）
    r = eng.forge_guard(_player(forged=[N_IRON, N_IRON_1, N_IRON_2], forge_level=3), "炎剑")
    assert r["ok"] is False and r["reason"] == "level_insufficient"


# ---------------------------------------------------------------------------
# C 节点查找（2c2b §5.2：精确 → 唯一前缀 → 歧义）
# ---------------------------------------------------------------------------
def test_resolve_exact() -> None:
    """精确命中：中文名 / 节点 id / ■ 前缀（P-04）。"""
    eng = _engine()
    r = eng.resolve_node("炎剑Ⅱ")
    assert r["ok"] is True and r["match"] == "exact" and r["node_id"] == N_FLAME_2
    r = eng.resolve_node(N_ICE)  # id 精确
    assert r["ok"] is True and r["match"] == "exact" and r["node_id"] == N_ICE
    # 精确命中「炎剑」不吞「炎剑Ⅱ」（P-03 不自动扩展）
    r = eng.resolve_node("炎剑")
    assert r["ok"] is True and r["match"] == "exact" and r["node_id"] == N_FLAME
    # ■ 前缀可省略 / 可带（P-04）
    r = eng.resolve_node("炎王剑")
    assert r["ok"] is True and r["node_id"] == N_KING
    r = eng.resolve_node("■炎王剑")
    assert r["ok"] is True and r["match"] == "exact" and r["node_id"] == N_KING
    # 雷剑 精确（分支叶）
    r = eng.resolve_node("雷剑")
    assert r["ok"] is True and r["node_id"] == N_LIGHT


def test_resolve_unique_prefix() -> None:
    """唯一前缀命中：恰一节点以 key 开头。"""
    eng = _engine()
    # 「炎王」唯一前缀 → ■炎王剑
    r = eng.resolve_node("炎王")
    assert r["ok"] is True and r["match"] == "prefix" and r["node_id"] == N_KING
    # 「冰」唯一前缀 → 冰剑
    r = eng.resolve_node("冰")
    assert r["ok"] is True and r["match"] == "prefix" and r["node_id"] == N_ICE
    # 「铁剑Ⅰ」→ 精确命中 铁剑Ⅰ（前缀同时匹配 铁剑Ⅰ/铁剑Ⅱ？不——精确优先）
    r = eng.resolve_node("铁剑Ⅰ")
    assert r["ok"] is True and r["match"] == "exact" and r["node_id"] == N_IRON_1


def test_resolve_ambiguous() -> None:
    """歧义：多候选 → 候选列表，不默选。"""
    eng = _engine()
    # 「炎」前缀 → 炎剑 / 炎剑Ⅱ / 炎剑Ⅲ / ■炎王剑
    r = eng.resolve_node("炎")
    assert r["ok"] is False and r["match"] == "ambiguous"
    assert set(r["candidates"]) == {N_FLAME, N_FLAME_2, N_FLAME_3, N_KING}
    assert len(r["candidates"]) == 4
    # 「铁」前缀 → 铁剑 / 铁剑Ⅰ / 铁剑Ⅱ
    r = eng.resolve_node("铁")
    assert r["ok"] is False and r["match"] == "ambiguous"
    assert set(r["candidates"]) == {N_IRON, N_IRON_1, N_IRON_2}
    # 空格（P-01 名禁空格由指令壳校验；引擎不匹配）→ not_found
    r = eng.resolve_node("炎剑 Ⅱ")
    assert r["ok"] is False and r["match"] == "not_found"


def test_resolve_not_found() -> None:
    """未知节点 → not_found。"""
    eng = _engine()
    r = eng.resolve_node("不存在之剑")
    assert r["ok"] is False and r["match"] == "not_found"
    r = eng.resolve_node("")
    assert r["ok"] is False and r["match"] == "not_found"
    r = eng.resolve_node(123)
    assert r["ok"] is False and r["match"] == "not_found"


# ---------------------------------------------------------------------------
# D 装备实例合并生成（AR-1~5；委托批0 merge_node_item）
# ---------------------------------------------------------------------------
def test_merge_override_append() -> None:
    """铁剑Ⅰ(items_def) → 炎剑(node)：AR-1 覆盖 atk + AR-2 追加 element。"""
    eng = _engine()
    items = cast(List[Mapping], _load_json(_ITEMS_JSON))
    iron_1 = next(i for i in items if i["id"] == "iron_sword_1")  # atk 18 无元素
    node = eng.node(N_FLAME)  # 炎剑：stats {atk:32, element:fire, element_value:5}
    assert node is not None
    out = eng.merge_forge_instance(iron_1, node)
    stats = cast(Dict[str, object], out["stats"])
    # AR-1 覆盖：节点 stats.atk=32 覆盖 items atk 基础（stats 键级合并）
    assert stats["atk"] == 32
    # AR-2 追加：节点未声明键继承 items（price/slot/excludes 等保留）
    assert out["price"] == iron_1["price"]
    assert out["slot"] == "weapon"
    # AR-2 追加元素：节点 stats 新增 element/element_value
    assert stats["element"] == "fire"
    assert stats["element_value"] == 5
    # AR-3 品质：节点 rarity fine
    assert out["rarity"] == "fine"
    # 快照追溯字段
    assert out["node_id"] == N_FLAME
    assert out["item_id"] == "flame_sword"


def test_merge_quality_inherit() -> None:
    """AR-3 品质仲裁：节点 rarity 覆盖 / 未配置继承 items.quality。"""
    eng = _engine()
    items = cast(List[Mapping], _load_json(_ITEMS_JSON))
    # 铁剑Ⅱ items 无 quality；节点 rarity=fine → 节点为准
    iron_2 = next(i for i in items if i["id"] == "iron_sword_2")
    node = eng.node(N_IRON_2)
    assert node is not None
    out = eng.merge_forge_instance(iron_2, node)
    assert out["rarity"] == "fine"
    # items 带 quality + 节点未声明 rarity → 继承 items.quality
    custom_item = dict(iron_2, quality="epic")
    node_no_rarity_raw = {"id": "node_test", "name": "测试", "item": "iron_sword_2",
                          "type": "weapon", "level": 1, "parent": None, "materials": []}
    out2 = eng.merge_forge_instance(custom_item, node_no_rarity_raw)
    assert out2["rarity"] == "epic"


def test_merge_snapshot_fields() -> None:
    """AR-5 快照字段齐备：stats/slots/rarity/final/augmentable/monster_source 零缺失。"""
    eng = _engine()
    items = cast(List[Mapping], _load_json(_ITEMS_JSON))
    # 普通节点（无 slots/final/augmentable/monster_source）→ 快照缺省补齐
    iron = next(i for i in items if i["id"] == "iron_sword")
    node = eng.node(N_IRON)
    assert node is not None
    out = eng.merge_forge_instance(iron, node)
    assert out["stats"] == {"atk": 12}
    assert out["slots"] == []
    assert out["final"] is False
    assert out["augmentable"] is False
    assert out["monster_source"] is None
    assert out["rarity"] == "normal"
    # ■炎王剑：final+augmentable 保留、孔位保留、legendary
    king = next(i for i in items if i["id"] == "flame_king_sword")
    king_node = eng.node(N_KING)
    assert king_node is not None
    out2 = eng.merge_forge_instance(king, king_node)
    assert out2["final"] is True
    assert out2["augmentable"] is True
    assert out2["slots"] == [{"level": 3}]
    assert out2["rarity"] == "legendary"
    assert cast(Dict[str, object], out2["stats"])["element"] == "fire"


def test_item_of() -> None:
    """正例：node.item → items 表条目解析（V7 引擎侧便利）。"""
    eng = _engine()
    node = eng.node(N_KING)
    assert node is not None
    entry = eng.item_of(node)
    assert entry is not None and entry.get("id") == "flame_king_sword"


# ---------------------------------------------------------------------------
# E 最终强化（2c2a §2.2 ■最终强化 / V6）
# ---------------------------------------------------------------------------
def test_final_of() -> None:
    """正例：树 final=true 节点（线终点 ■）。"""
    eng = _engine()
    finals = eng.final_of(_TREE_ID)
    assert set(finals) == {N_KING, N_ICE, N_LIGHT}
    assert len(finals) == 3
    # 传 ForgeTree / raw dict 亦可用
    tree = eng.load_trees()[0]
    assert eng.final_of(tree) == finals
    assert eng.final_of({"id": _TREE_ID}) == finals
    assert eng.final_of("node_nonexistent") == []


def test_line_endpoint() -> None:
    """正例：所在线终点 ■（主线延伸优先，branch 不参与主线）。"""
    eng = _engine()
    # 主干任意节点 → ■炎王剑
    assert eng.line_endpoint(N_IRON) == N_KING
    assert eng.line_endpoint(N_IRON_2) == N_KING
    assert eng.line_endpoint(N_FLAME) == N_KING
    assert eng.line_endpoint(N_FLAME_2) == N_KING
    assert eng.line_endpoint(N_FLAME_3) == N_KING
    # final 自身
    assert eng.line_endpoint(N_KING) == N_KING
    assert eng.line_endpoint(N_ICE) == N_ICE
    assert eng.line_endpoint(N_LIGHT) == N_LIGHT
    # 未知节点
    assert eng.line_endpoint("node_nonexistent") is None


def test_match_name() -> None:
    """归一：■ 去除 + strip（P-04）。"""
    assert match_name("■炎王剑") == "炎王剑"
    assert match_name(" 炎剑 ") == "炎剑"
    assert match_name("炎剑Ⅱ") == "炎剑Ⅱ"
    assert match_name(None) == ""
    assert match_name(123) == ""


# ---------------------------------------------------------------------------
# 边界：空 forge / 缺省兜底
# ---------------------------------------------------------------------------
def test_empty_forge_defaults() -> None:
    """空 forge / 非 Mapping → 全缺省兜底，不抛异常。"""
    eng = ForgeTreeEngine(None)
    assert eng.load_trees() == []
    assert eng.nodes() == []
    assert eng.children_of("x") == []
    assert eng.path_to_root("x") == []
    assert eng.final_of("x") == []
    assert eng.line_endpoint("x") is None
    r = eng.resolve_node("x")
    assert r["ok"] is False and r["match"] == "not_found"
    # settings 缺省
    assert eng.settings().get("straight_forge") is True
    assert eng.settings().get("synth_ratio_3to1") is True
    fs = eng.forge_settings()
    assert fs.straight_forge is True


def test_settings_injection() -> None:
    """settings 注入：完整 settings（含 forge 段）与 forge 段本身均归一。"""
    forge = cast(Mapping, _load_json(_FORGE_JSON))
    # 完整 settings（含 forge 段）→ 取段
    full = {"forge": {"straight_forge": False, "synth_ratio_3to1": False}}
    eng = ForgeTreeEngine(forge=forge, settings=full)
    assert eng.settings().get("straight_forge") is False
    assert eng.settings().get("synth_ratio_3to1") is False
    # forge 段本身 → 包层归一
    seg = {"straight_forge": False}
    eng2 = ForgeTreeEngine(forge=forge, settings=seg)
    assert eng2.settings().get("straight_forge") is False
    assert eng2.settings().get("sets_enabled") is True  # 未声明 → 默认
    # 未传 settings → 回退 forge.json settings 段
    eng3 = ForgeTreeEngine(forge=forge, settings=None)
    assert eng3.settings().get("straight_forge") is True
    assert eng3.settings().get("forge_fee") == "节点等级×10"
