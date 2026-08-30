"""M9 锻造·批2·路2B：素材即进度查询服务单元测试（tests/unit/test_forge_progress.py）。

文件名：test_forge_progress.py
创建时间：2026-08-30
作者：Hermes 子agent-2B（M9 锻造实现组批2·路2B：并发同仓，仅新建本文件 +
qbot_rpg/core/forge_progress.py；不改动批0/批1 既有文件与 fixtures）

依据：docs/细化/细化_2c2c_锻造素材经济.md（§3 PROG-01~08 素材即进度）+
docs/细化/细化_2c2b_锻造流程契约.md（§1.3 缺件报错模板 + §2.2 持有进度行 + §2.3 ✓ 标注）。
测试目标：qbot_rpg.core.forge_progress 全功能（material_holdings / shortfall /
progress_line / forge_readiness）+ 真实 forge.json/items.json 兼容 + 三态判定。

覆盖矩阵：
  A 持有量逐项：material_holdings 真实 forge.json 炎剑Ⅱ 需求行逐项 {need, have, name,
    source}；背包物品栈按 id 计数（PROG-04）；source_override 覆写 > items.source；
    ForgeNode / raw dict 双形态；畸形行跳过
  B 差量计算：shortfall need−have，缺额 > 0 行列出（PROG-02），满额/负数行不显示；
    coins/gem 恒 0（F-2）
  C 进度行模板：progress_line 满额 `5/5 ✓` / 未满 `1/3` 不标 ✓（F-1）/ 已锻前置节点
    名后 ✓（F-3）；多段 ` | ` 分隔；全空前缀兜底
  D 满链判定三态：forge_readiness 全齐 ready / 缺素材 gaps（逐项带缺额+来源）/
    前置未锻 gaps（需先锻造 <前置名>）；tree=None 保守未锻（F-4）；engine 方法形态

铁律：零 NoneBot import；纯函数确定性；不写 time.sleep；不引入随机。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping, cast

from qbot_rpg.content.forge_models import ForgeNode
from qbot_rpg.core.forge_progress import (
    PROGRESS_PREFIX,
    ForgeProgressEngine,
    forge_readiness,
    material_holdings,
    progress_line,
    shortfall,
)
from qbot_rpg.core.forge_tree import FORGE_JOB_ID, ForgeTreeEngine

# 仓库根 = tests/unit/test_forge_progress.py 上溯两级
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORGE_JSON = _REPO_ROOT / "content" / "test_demo" / "forge.json"
_ITEMS_JSON = _REPO_ROOT / "content" / "test_demo" / "items.json"

# 武器树节点 id（对齐 test_forge_tree.py；炎剑Ⅱ 素材：火龙鳞×5 + 火晶石×2）
N_IRON = "node_iron_sword"           # 铁剑（根）
N_IRON_1 = "node_iron_sword_1"       # 铁剑Ⅰ
N_IRON_2 = "node_iron_sword_2"       # 铁剑Ⅱ
N_FLAME = "node_flame_sword"         # 炎剑
N_FLAME_2 = "node_flame_sword_2"     # 炎剑Ⅱ（火龙鳞×5 + 火晶石×2，branch 出口）

# 炎剑Ⅱ 素材需求（forge.json 文件序）
MAT_FLAME_2 = ("fire_dragon_scale", "alch_ember_crystal")
# 素材显示名 / 来源（items.json）
ITEM_NAME = {"fire_dragon_scale": "火龙鳞", "alch_ember_crystal": "火晶石",
             "ore": "矿石", "star_iron": "星铁矿石"}
ITEM_SOURCE = {"fire_dragon_scale": "火龙掉落/商店", "alch_ember_crystal": "采集/商店",
               "ore": "挖掘点/商店", "star_iron": "挖掘点/商店"}


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _tree() -> ForgeTreeEngine:
    """批1 ForgeTreeEngine（真实 forge.json + items.json）。"""
    forge = cast(Mapping, _load_json(_FORGE_JSON))
    items = _load_json(_ITEMS_JSON)
    return ForgeTreeEngine(forge=forge, items=items, settings={})


def _ctx(inventory: Mapping[str, int]) -> Dict[str, object]:
    """模拟背包 ctx（items 注册表 + inventory 计数映射；对齐 synthesis ctx 契约）。"""
    return {"items": _load_json(_ITEMS_JSON), "inventory": dict(inventory)}


def _player(*, forged: object = None, forge_level: int = 0) -> Dict[str, object]:
    """构造玩家 dict（proficiency.forge.level + forged 集合；可配）。"""
    return {"proficiency": {FORGE_JOB_ID: {"level": forge_level, "exp": 0}},
            "forged": forged}


def _node(engine: ForgeTreeEngine, node_id: str) -> ForgeNode:
    node = engine.node(node_id)
    assert node is not None
    return node


def _holdings(ctx: Dict[str, object], node: object) -> Dict[str, Dict[str, object]]:
    return material_holdings(ctx, node)


# ---------------------------------------------------------------------------
# A 持有量逐项（PROG-04）
# ---------------------------------------------------------------------------
def test_material_holdings_real_forge_node() -> None:
    """正例：炎剑Ⅱ 需求行逐项持有量（火龙鳞 1/5、火晶石 2/2；items 名/来源解析）。"""
    eng = _tree()
    node = _node(eng, N_FLAME_2)
    ctx = _ctx({"fire_dragon_scale": 1, "alch_ember_crystal": 2})
    h = _holdings(ctx, node)
    assert list(h.keys()) == list(MAT_FLAME_2)  # 文件序
    # 火龙鳞：need 5 / have 1（背包栈计数，PROG-04）
    assert h["fire_dragon_scale"] == {
        "need": 5, "have": 1, "name": "火龙鳞", "source": "火龙掉落/商店",
    }
    # 火晶石：need 2 / have 2（满额）
    assert h["alch_ember_crystal"] == {
        "need": 2, "have": 2, "name": "火晶石", "source": "采集/商店",
    }


def test_material_holdings_raw_dict_dual_form() -> None:
    """正例：raw dict 形态节点（非 ForgeNode）同样逐项解析（F-6 双形态）。"""
    raw = {"id": "node_demo", "materials": [
        {"item": "ore", "count": 3}, {"item": "star_iron", "count": 2},
    ]}
    ctx = _ctx({"ore": 3, "star_iron": 0})
    h = _holdings(ctx, raw)
    assert list(h.keys()) == ["ore", "star_iron"]
    assert h["ore"]["need"] == 3 and h["ore"]["have"] == 3
    assert h["star_iron"]["need"] == 2 and h["star_iron"]["have"] == 0


def test_material_holdings_count_item_hook_preferred() -> None:
    """正例：count_item hook 优先于 inventory（PROG-04 数据流；对齐 synthesis）。"""
    eng = _tree()
    node = _node(eng, N_IRON)  # 铁剑：矿石×3
    ctx: Dict[str, object] = {
        "items": _load_json(_ITEMS_JSON),
        "inventory": {"ore": 999},  # 应被 hook 覆盖
        "count_item": lambda iid: 7 if iid == "ore" else 0,
    }
    h = _holdings(ctx, node)
    assert h["ore"]["have"] == 7


def test_material_holdings_malformed_rows_skipped() -> None:
    """反例：畸形素材行（缺 item / count 非正 / 非 Mapping）跳过，不抛异常。"""
    raw = {"id": "node_demo", "materials": [
        {"count": 3},                      # 缺 item
        {"item": "ore", "count": 0},       # count 非正
        {"item": "star_iron", "count": 2},  # 合法
        "not-a-mapping",                    # 非 Mapping
    ]}
    ctx = _ctx({"ore": 1, "star_iron": 0})
    h = _holdings(ctx, raw)
    assert list(h.keys()) == ["star_iron"]
    assert h["star_iron"]["need"] == 2


def test_material_holdings_source_override_wins() -> None:
    """正例：source_override（M-04 行覆写）> items.source（F-5）。"""
    raw = {"id": "node_demo", "materials": [
        {"item": "ore", "count": 3, "source_override": "火山挖掘点"},
    ]}
    ctx = _ctx({"ore": 1})
    h = _holdings(ctx, raw)
    assert h["ore"]["source"] == "火山挖掘点"


# ---------------------------------------------------------------------------
# B 差量计算（PROG-02：need−have，负数行不显示）
# ---------------------------------------------------------------------------
def test_shortfall_positive_rows_only() -> None:
    """正例：缺额 > 0 行列出（名称/缺额/来源）；满额与负数行不显示（PROG-02）。"""
    ctx = _ctx({"fire_dragon_scale": 1, "alch_ember_crystal": 5})  # 火晶石 5>2 超持有
    h = _holdings(ctx, _node(_tree(), N_FLAME_2))
    s = shortfall(h)
    # 火晶石 have 5 ≥ need 2（差量 -3，负数行不显示）；仅火龙鳞 缺 4
    assert s["items"] == [("火龙鳞", 4, "火龙掉落/商店")]
    assert s["coins"] == 0 and s["gem"] == 0  # F-2 恒 0


def test_shortfall_no_gap() -> None:
    """反例：全满足 → items 空（无差量）。"""
    ctx = _ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2})
    h = _holdings(ctx, _node(_tree(), N_FLAME_2))
    s = shortfall(h)
    assert s["items"] == []
    assert s["coins"] == 0 and s["gem"] == 0


def test_shortfall_empty_holdings() -> None:
    """边界：空持有量（无素材/畸形节点）→ 空 items。"""
    s = shortfall({})
    assert s == {"items": [], "coins": 0, "gem": 0}


# ---------------------------------------------------------------------------
# C 进度行模板（PROG-05 + 2c2b §2.3 ✓ 标注）
# ---------------------------------------------------------------------------
def test_progress_line_full_and_partial() -> None:
    """正例：满额 `5/5 ✓`（F-1）、未满 `1/3` 不标 ✓、已锻前置节点名后 ✓（F-3）。"""
    ctx = _ctx({"fire_dragon_scale": 1, "alch_ember_crystal": 2})
    h = _holdings(ctx, _node(_tree(), N_FLAME_2))
    line = progress_line(h, forged_prefix_names=["铁剑", "铁剑Ⅰ", "铁剑Ⅱ", "炎剑"])
    assert line == "当前持有：火龙鳞 1/5 | 火晶石 2/2 ✅ | 铁剑 ✅ | 铁剑Ⅰ ✅ | 铁剑Ⅱ ✅ | 炎剑 ✅"


def test_progress_line_matches_prog05_template() -> None:
    """正例：PROG-05 定稿模板（持有 1/3、矿石 5/5、铁剑Ⅰ ✓）落位。"""
    raw = {"id": "node_demo", "materials": [
        {"item": "fire_dragon_scale", "count": 3},
        {"item": "ore", "count": 5},
    ]}
    ctx = _ctx({"fire_dragon_scale": 1, "ore": 5})
    h = _holdings(ctx, raw)
    line = progress_line(h, forged_prefix_names=["铁剑Ⅰ"])
    # 未满 1/3 不标 ✓；满额 5/5 标 ✓；已锻前置 铁剑Ⅰ ✓（F-1/F-3）
    assert line == "当前持有：火龙鳞 1/3 | 矿石 5/5 ✅ | 铁剑Ⅰ ✅"


def test_progress_line_empty() -> None:
    """边界：无素材 + 无前置 → 仅前缀（`当前持有：` 兜底）。"""
    assert progress_line({}) == PROGRESS_PREFIX


# ---------------------------------------------------------------------------
# D 满链判定三态（PROG-01 / 2c2b §2.3）
# ---------------------------------------------------------------------------
def test_forge_readiness_ready() -> None:
    """正例①：前置全锻 + 素材全满额 → ready=True + 可锻造 message。"""
    eng = _tree()
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    ctx = _ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2})
    player = _player(forged=full_chain)
    r = forge_readiness(ctx, player, _node(eng, N_FLAME_2), tree=eng)
    assert r["ready"] is True
    assert r["message"] == "可锻造"
    assert r["node_id"] == N_FLAME_2
    assert r["shortfall"]["items"] == []


def test_forge_readiness_missing_material() -> None:
    """正例②：前置全锻但缺素材 → ready=False，gaps 带缺额+来源（PROG-02 模板）。"""
    eng = _tree()
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    ctx = _ctx({"fire_dragon_scale": 1, "alch_ember_crystal": 2})  # 缺 火龙鳞×4
    player = _player(forged=full_chain)
    r = forge_readiness(ctx, player, _node(eng, N_FLAME_2), tree=eng)
    assert r["ready"] is False
    assert r["gaps"] == ["缺 火龙鳞×4（来源：火龙掉落/商店）"]
    assert r["shortfall"]["items"] == [("火龙鳞", 4, "火龙掉落/商店")]


def test_forge_readiness_parent_not_forged() -> None:
    """正例③：前置未锻（缺 铁剑Ⅰ）→ ready=False，gaps 需先锻造 <前置名>（TC-16）。"""
    eng = _tree()
    ctx = _ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2})  # 素材全满
    # 仅锻 铁剑（缺 铁剑Ⅰ）→ 前置链断裂
    player = _player(forged=[N_IRON])
    r = forge_readiness(ctx, player, _node(eng, N_FLAME_2), tree=eng)
    assert r["ready"] is False
    assert "需先锻造 铁剑Ⅰ" in r["gaps"]


def test_forge_readiness_parent_and_material_gaps() -> None:
    """反例：前置未锻 + 素材缺 → gaps 前置在前、素材在后（守卫顺序 GU-04→05）。"""
    eng = _tree()
    ctx = _ctx({"fire_dragon_scale": 1, "alch_ember_crystal": 2})  # 缺 火龙鳞×4
    player = _player(forged=[N_IRON])  # 缺 铁剑Ⅰ 前置
    r = forge_readiness(ctx, player, _node(eng, N_FLAME_2), tree=eng)
    assert r["ready"] is False
    assert r["gaps"][0] == "需先锻造 铁剑Ⅰ"
    assert r["gaps"][1] == "缺 火龙鳞×4（来源：火龙掉落/商店）"


def test_forge_readiness_tree_none_conservative() -> None:
    """边界：tree=None → 前置保守未锻（F-4 兜底），素材缺口照列。"""
    raw = {"id": "node_demo", "materials": [{"item": "ore", "count": 3}]}
    ctx = _ctx({"ore": 3})  # 素材满
    r = forge_readiness(ctx, _player(forged=[]), raw, tree=None)
    assert r["ready"] is False
    assert r["gaps"] == ["需先锻造 前置节点"]  # 无树可判 → 保守缺口


def test_forge_progress_engine_methods() -> None:
    """正例：ForgeProgressEngine 方法形态（构造器注入 tree，forge_readiness 复用其判定）。"""
    eng = _tree()
    svc = ForgeProgressEngine(tree=eng)
    ctx = _ctx({"fire_dragon_scale": 5, "alch_ember_crystal": 2})
    node = _node(eng, N_FLAME_2)
    h = svc.material_holdings(ctx, node)
    assert svc.shortfall(h)["items"] == []
    line = svc.progress_line(h, forged_prefix_names=["炎剑"])
    assert line == "当前持有：火龙鳞 5/5 ✅ | 火晶石 2/2 ✅ | 炎剑 ✅"
    # 前置全锻 + 素材满 → ready
    full_chain = [N_IRON, N_IRON_1, N_IRON_2, N_FLAME]
    r = svc.forge_readiness(ctx, _player(forged=full_chain), node)
    assert r["ready"] is True


def test_forge_progress_engine_default_empty_tree() -> None:
    """边界：ForgeProgressEngine() 缺省空树 → forge_readiness 前置保守未锻（F-4）。"""
    svc = ForgeProgressEngine()
    raw = {"id": "node_demo", "materials": [{"item": "ore", "count": 3}]}
    r = svc.forge_readiness(_ctx({"ore": 3}), _player(forged=[]), raw)
    assert r["ready"] is False
