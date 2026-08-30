"""M9 锻造数据层 · 路 1B：forge 级联删除与红名机制测试。

文件名：tests/unit/test_forge_cascade.py
创建时间：2026-08-30
作者：Hermes 子agent-1B（M9 锻造实现组批1·路1B：并发同仓，仅新建本文件 +
qbot_rpg/core/forge_cascade.py）

依据：docs/细化/细化_2c2a_锻造派生树schema.md §12.1.2（级联删除）+ §五 V15 +
§六 F 验收 TC-25~27；docs/m9_shared_contract.md §六 V15；规划_路2c2_锻造.md T4。
测试目标：qbot_rpg.core.forge_cascade.{delete_items_effect, delete_forge_nodes,
cascade_recheck, is_redflagged}。

测试口径（对齐 test_forge_models.py / test_alchemy_meta.py）：
  - 数据源：content/test_demo/forge.json + items.json 真实 fixture（共享契约 §九），
    由 json 加载深拷贝构造，不改静态 fixtures 文件。
  - 铁律：纯函数确定性——每个级联函数返回新 forge dict，入参不被改写（断言入参
    深等）；零 NoneBot；不写 time.sleep。
  - TC-25 删 items → redflag/remove 两路径：红名保留（is_redflagged 命中 + V15
    复查零残留 + V7 item_missing 归 redflag_expected）/ 整棵子树移除 + 父 branch
    清理（V15/V5 零悬空）。
  - TC-26 删 forge 节点 → 已锻实例保留旧属性（本层不回溯，纯数据层）+ promote
    上提重连（链不断）/ remove 整支移除并清理引用。
  - TC-27 级联后 cascade_recheck 复查：无残留悬空引用、红名节点父链完整。

【工程补白 · 注记】
  - test_demo forge.json 拓扑：铁剑〔根〕→ 铁剑Ⅰ → 铁剑Ⅱ → 炎剑 → 炎剑Ⅱ →
    炎剑Ⅲ → ■炎王剑（final，叶子）；node_flame_sword_2.branch=[冰剑, 雷剑]
    （雷剑/冰剑 parent=node_flame_sword_2）。
  - 中间节点红名（如删 炎剑 item → node_flame_sword 标红）时其子树节点 parent
    仍指向红名父 → V15 red_name_referenced 报残留（补白2：负例验证 V15 生效）；
    叶子红名（炎王剑）V15 零残留——TC-25 以叶子路径为正例。
"""

from __future__ import annotations

import copy
import json
import os
from typing import Dict, Iterable, List, Mapping, Set

from qbot_rpg.core.forge_cascade import (
    REDFLAG_MARK,
    cascade_recheck,
    delete_forge_nodes,
    delete_items_effect,
    is_redflagged,
)
from qbot_rpg.content.forge_models import ForgeNode, validate_forge

# ---------------------------------------------------------------------------
# 夹具：加载 test_demo 真实数据（深拷贝隔离，不写回文件）
# ---------------------------------------------------------------------------
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_json(rel: str) -> Dict[str, object]:
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return json.load(f)


def _forge() -> Dict[str, object]:
    return _load_json("content/test_demo/forge.json")


def _items() -> List[Dict[str, object]]:
    v = _load_json("content/test_demo/items.json")
    if isinstance(v, list):
        return [i for i in v if isinstance(i, dict)]
    if isinstance(v, dict):
        items_v = v.get("items")
        if isinstance(items_v, list):
            return [i for i in items_v if isinstance(i, dict)]
    return []


def _modules(forge: Mapping[str, object], removed_items: Iterable[str] = ()) -> Dict[str, object]:
    """模块上下文：items 可按需剔除已删条目（级联后复查须反映 items 删除状态）。"""
    items = [i for i in _items() if i.get("id") not in set(removed_items)]
    return {"forge": copy.deepcopy(forge), "items": items}


def _node(forge: object, nid: str) -> Dict[str, object]:
    if not isinstance(forge, Mapping):
        raise KeyError(nid)
    for tree in forge.get("trees", []):
        for n in tree.get("nodes", []):
            if isinstance(n, Mapping) and n.get("id") == nid:
                return dict(n)
    raise KeyError(nid)


def _node_ids(forge: object) -> Set[str]:
    out: Set[str] = set()
    if not isinstance(forge, Mapping):
        return out
    for tree in forge.get("trees", []):
        if not isinstance(tree, Mapping):
            continue
        for n in tree.get("nodes", []):
            if isinstance(n, Mapping) and isinstance(n.get("id"), str):
                out.add(n["id"])
    return out


def _branch_refs(forge: object) -> List[str]:
    out: List[str] = []
    if not isinstance(forge, Mapping):
        return out
    for tree in forge.get("trees", []):
        if not isinstance(tree, Mapping):
            continue
        for n in tree.get("nodes", []):
            if not isinstance(n, Mapping):
                continue
            br = n.get("branch")
            if isinstance(br, list):
                out.extend(br)
    return out


def _rules(errors: object) -> Set[str]:
    if not isinstance(errors, list):
        return set()
    return {e["detail"].get("rule") for e in errors
            if isinstance(e, Mapping) and isinstance(e.get("detail"), Mapping)}


def _forge_of(res: Mapping[str, object]) -> Mapping[str, object]:
    """从级联结果 dict 取 forge（类型收窄：res['forge'] 运行时是 dict）。"""
    v = res.get("forge")
    return v if isinstance(v, Mapping) else {}


def _strs(v: object) -> Iterable[str]:
    """把级联结果里的 id 列表（object）窄化为 Iterable[str]（运行时为 list）。"""
    return v if isinstance(v, (list, tuple)) else []


# ---------------------------------------------------------------------------
# 公共：入参不变性（纯函数铁律）
# ---------------------------------------------------------------------------
def test_inputs_not_mutated_redflag() -> None:
    """级联函数返回新 dict，不改写入参（铁律：可回滚）。"""
    orig = _forge()
    snapshot = copy.deepcopy(orig)
    res = delete_items_effect(orig, ["flame_king_sword"], mode="redflag")
    assert orig == snapshot, "delete_items_effect 不得改写入参"
    assert res["forge"] is not orig, "应返回新 forge dict"


def test_inputs_not_mutated_delete_nodes() -> None:
    orig = _forge()
    snapshot = copy.deepcopy(orig)
    res = delete_forge_nodes(orig, ["node_iron_sword_2"], reconnect="promote")
    assert orig == snapshot, "delete_forge_nodes 不得改写入参"
    assert res["forge"] is not orig, "应返回新 forge dict"


# ---------------------------------------------------------------------------
# TC-25a：删 items 装备 → redflag 模式（节点及子树保留标红）
# ---------------------------------------------------------------------------
def test_tc25a_delete_item_redflag_leaf() -> None:
    """TC-25①：删炎王剑 item → node_flame_king_sword 标红保留；V15 复查零残留。"""
    orig = _forge()
    res = delete_items_effect(orig, ["flame_king_sword"], mode="redflag")
    nf = _forge_of(res)

    assert res["deleted"] == ["flame_king_sword"]
    assert "node_flame_king_sword" in _strs(res["redflagged"])
    # 节点保留（未移除）
    assert "node_flame_king_sword" in _node_ids(nf)
    node = _node(nf, "node_flame_king_sword")
    assert node.get(REDFLAG_MARK) is True, "被引节点应加 redflagged:true"
    assert is_redflagged(node), "is_redflagged 应命中红名节点"
    # 树结构不变（父链完整）
    assert node.get("parent") == "node_flame_sword_3"
    assert _node(nf, "node_flame_sword_3").get("parent") == "node_flame_sword_2"

    # V15 复查：红名叶子零残留；V7 item_missing 归类为红名预期
    rep = cascade_recheck(nf, _modules(orig, ["flame_king_sword"]))
    assert rep["ok"] is True, f"V15 复查应通过（红名叶子），got errors={rep['errors']}"
    assert "node_flame_king_sword" in _strs(rep["red_nodes"])
    assert "item_missing" in _rules(rep["redflag_expected"])
    assert "red_name_referenced" not in _rules(rep["errors"])
    assert "red_name_branch_not_cleared" not in _rules(rep["errors"])


def test_tc25a_delete_item_redflag_mid_negative() -> None:
    """TC-25① 负例：删中间节点 item（炎剑）→ 子树标红但子树 parent 仍指向红名父
    → V15 red_name_referenced 残留（验证 V15 生效，作者需继续处理）。"""
    orig = _forge()
    res = delete_items_effect(orig, ["flame_sword"], mode="redflag")
    nf = _forge_of(res)
    # 整棵子树标红（含后代）
    for nid in ("node_flame_sword", "node_flame_sword_2",
                "node_flame_sword_3", "node_flame_king_sword"):
        assert is_redflagged(_node(nf, nid)), f"{nid} 应标红"
    assert is_redflagged(_node(nf, "node_flame_sword"))
    # 子树节点保留
    for nid in ("node_flame_sword", "node_flame_sword_2", "node_flame_king_sword"):
        assert nid in _node_ids(nf)

    rep = cascade_recheck(nf, _modules(orig, ["flame_sword"]))
    assert "red_name_referenced" in _rules(rep["errors"]), \
        "红名中间节点被子树引用应 V15 报残留（补白2 负例）"
    assert rep["ok"] is False


# ---------------------------------------------------------------------------
# TC-25b：删 items 装备 → remove 模式（节点+子树移除 + 父 branch 清理）
# ---------------------------------------------------------------------------
def test_tc25b_delete_item_remove() -> None:
    """TC-25②：删炎王剑 item → 节点+子树移除；复查零悬空引用。"""
    orig = _forge()
    res = delete_items_effect(orig, ["flame_king_sword"], mode="remove")
    nf = _forge_of(res)

    assert "node_flame_king_sword" in _strs(res["removed"])
    assert "node_flame_king_sword" not in _node_ids(nf)
    assert res["redflagged"] == []

    rep = cascade_recheck(nf, _modules(orig, ["flame_king_sword"]))
    assert rep["ok"] is True, f"remove 后复查应通过，got errors={rep['errors']}"
    assert rep["dangling_errors"] == [], f"remove 后应无悬空引用，got {rep['dangling_errors']}"
    assert rep["red_nodes"] == [], "remove 后应无红名节点"
    # 无悬空：branch 全部可达、无 V15 残留
    rules = _rules(rep["errors"])
    assert "red_name_referenced" not in rules
    assert "branch_missing" not in rules


def test_tc25b_delete_item_remove_branch_cleaned() -> None:
    """TC-25②：删中间节点 item（炎剑Ⅱ）→ 子树移除 + 父（炎剑）branch 同步清冰剑/雷剑。"""
    orig = _forge()
    # 炎剑Ⅱ item=flame_sword_2；其 branch 指向 冰剑/雷剑（子树成员）
    res = delete_items_effect(orig, ["flame_sword_2"], mode="remove")
    nf = _forge_of(res)

    removed = set(_strs(res["removed"]))
    for nid in ("node_flame_sword_2", "node_flame_sword_3",
                "node_flame_king_sword", "node_ice_sword", "node_lightning_sword"):
        assert nid in removed, f"{nid} 应被整支移除"
        assert nid not in _node_ids(nf)
    # 父节点炎剑仍保留，其 branch 已清理（不再指向已删 冰剑/雷剑）
    parent = _node(nf, "node_flame_sword")
    assert parent.get("branch") == [], "父节点 branch 应同步清理"
    # 全树 branch 无悬空引用
    branch_refs = _branch_refs(nf)
    assert all(b in _node_ids(nf) for b in branch_refs), "branch 引用不应悬空"

    rep = cascade_recheck(nf, _modules(orig, ["flame_sword_2"]))
    assert rep["ok"] is True, f"复查应通过，got errors={rep['errors']}"


# ---------------------------------------------------------------------------
# TC-26a：删 forge 节点 → 已锻实例保留旧属性 + promote 上提重连（链不断）
# ---------------------------------------------------------------------------
def test_tc26a_delete_node_promote() -> None:
    """TC-26①：删铁剑Ⅱ → 子节点（炎剑）上提 parent 指向铁剑Ⅰ；链不断；复查通过。"""
    orig = _forge()
    res = delete_forge_nodes(orig, ["node_iron_sword_2"], reconnect="promote")
    nf = _forge_of(res)

    assert "node_iron_sword_2" in _strs(res["deleted"])
    assert "node_iron_sword_2" not in _node_ids(nf)
    assert "node_flame_sword" in _strs(res["reconnected"]), "炎剑应上提重连"
    # 上提：炎剑 parent 铁剑Ⅱ(已删) → 铁剑Ⅰ（原父的父）
    assert _node(nf, "node_flame_sword").get("parent") == "node_iron_sword_1"
    # 链不断：铁剑 → 铁剑Ⅰ → 炎剑 → 炎剑Ⅱ → … → 炎王剑
    chain = ["node_iron_sword", "node_iron_sword_1", "node_flame_sword",
             "node_flame_sword_2", "node_flame_sword_3", "node_flame_king_sword"]
    for i in range(1, len(chain)):
        assert _node(nf, chain[i]).get("parent") == chain[i - 1], \
            f"链 {chain[i-1]} → {chain[i]} 应完整（链不断）"
    # roots 不变（铁剑Ⅱ非根）
    assert _node(nf, "node_iron_sword").get("parent") is None

    # 已锻造实例保留旧属性（纯数据层不回溯：forge 数据不含玩家快照，node 保留
    # 原属性；快照不回溯由本层不写存档保证——见模块补白6）
    stats_v = _node(nf, "node_flame_sword").get("stats")
    atk_v = stats_v.get("atk") if isinstance(stats_v, Mapping) else None
    assert atk_v == 32

    rep = cascade_recheck(nf, _modules(orig))
    assert rep["ok"] is True, f"promote 后复查应通过，got errors={rep['errors']}"


def test_tc26a_delete_root_node_promote() -> None:
    """TC-26① 扩展：删根节点（铁剑）promote → 铁剑Ⅰ 上提为新根（roots 更新）。"""
    orig = _forge()
    res = delete_forge_nodes(orig, ["node_iron_sword"], reconnect="promote")
    nf = _forge_of(res)

    assert "node_iron_sword" in _strs(res["deleted"])
    assert "node_iron_sword" not in _node_ids(nf)
    # 铁剑Ⅰ 上提为根
    assert _node(nf, "node_iron_sword_1").get("parent") is None
    trees_v = nf.get("trees")
    roots = trees_v[0]["roots"] if isinstance(trees_v, list) and trees_v else []
    assert "node_iron_sword_1" in roots, "上提子节点应加入 roots"

    rep = cascade_recheck(nf, _modules(orig))
    assert rep["ok"] is True, f"根删除 promote 复查应通过，got errors={rep['errors']}"


# ---------------------------------------------------------------------------
# TC-26b：删 forge 节点 → remove 整支移除并清理引用
# ---------------------------------------------------------------------------
def test_tc26b_delete_node_remove() -> None:
    """TC-26②：删铁剑Ⅱ → 整支移除（含全部后代）+ 引用清理；复查通过。"""
    orig = _forge()
    res = delete_forge_nodes(orig, ["node_iron_sword_2"], reconnect="remove")
    nf = _forge_of(res)

    removed = set(_strs(res["removed"]))
    for nid in ("node_iron_sword_2", "node_flame_sword", "node_flame_sword_2",
                "node_flame_sword_3", "node_flame_king_sword",
                "node_ice_sword", "node_lightning_sword"):
        assert nid in removed, f"{nid} 应整支移除"
        assert nid not in _node_ids(nf)
    # 保留主干前半：铁剑 → 铁剑Ⅰ
    assert _node(nf, "node_iron_sword").get("parent") is None
    assert _node(nf, "node_iron_sword_1").get("parent") == "node_iron_sword"
    # 铁剑Ⅰ 无 branch 悬空（其 branch 原为空；若有指向已删节点的 branch 会被清理）
    # 全树 branch 无悬空
    branch_refs = _branch_refs(nf)
    assert all(b in _node_ids(nf) for b in branch_refs), "branch 引用不应悬空"

    rep = cascade_recheck(nf, _modules(orig))
    assert rep["ok"] is True, f"remove 后复查应通过，got errors={rep['errors']}"


# ---------------------------------------------------------------------------
# TC-27：级联删除后重复跑校验器 → V15 复查零残留（含红名父链完整）
# ---------------------------------------------------------------------------
def test_tc27_recheck_after_cascade() -> None:
    """TC-27：红名 + 节点删除级联后 cascade_recheck 复查零残留、红名父链完整。"""
    orig = _forge()
    # 1) 删炎王剑 item → redflag（叶子红名）
    r1 = delete_items_effect(orig, ["flame_king_sword"], mode="redflag")
    nf1 = _forge_of(r1)
    rep1 = cascade_recheck(nf1, _modules(orig, ["flame_king_sword"]))
    assert rep1["ok"] is True, "红名叶子级联后复查应通过"
    assert "node_flame_king_sword" in _strs(rep1["red_nodes"])
    # 红名节点父链完整：node_flame_king_sword.parent 仍可达
    assert _node(nf1, "node_flame_king_sword").get("parent") in _node_ids(nf1)

    # 2) 再删 forge 节点（铁剑Ⅱ，promote）→ 复查仍通过、无残留
    r2 = delete_forge_nodes(nf1, ["node_iron_sword_2"], reconnect="promote")
    nf2 = _forge_of(r2)
    rep2 = cascade_recheck(nf2, _modules(orig, ["flame_king_sword"]))
    assert rep2["ok"] is True, f"再级联后复查应通过，got errors={rep2['errors']}"
    # 红名节点仍保留且父链完整（炎王剑 parent=炎剑Ⅲ 仍在）
    assert "node_flame_king_sword" in _node_ids(nf2)
    assert _node(nf2, "node_flame_king_sword").get("parent") == "node_flame_sword_3"
    assert is_redflagged(_node(nf2, "node_flame_king_sword"))

    # 3) 直接调批0 validate_forge 也应零红（V7 item_missing 除外——红名预期）
    class _R:
        def __init__(self) -> None:
            self.errors: List[Dict[str, object]] = []
            self.warnings: List[Dict[str, object]] = []
        def error(self, module, field, kind, **d):
            self.errors.append({"field": field, "kind": kind, "detail": d})
        def warning(self, module, field, kind, **d):
            self.warnings.append({"field": field, "kind": kind, "detail": d})

    report = _R()
    validate_forge(_modules(nf2), report)
    rules = _rules(report.errors)
    # 无 V15 残留；红名节点 V7 item_missing 允许（红名状态）
    assert "red_name_referenced" not in rules
    assert "red_name_branch_not_cleared" not in rules
    assert "branch_missing" not in rules


# ---------------------------------------------------------------------------
# 红名查询：is_redflagged（供 /锻造 拒绝、/图纸 失效标注）
# ---------------------------------------------------------------------------
def test_is_redflagged_marks() -> None:
    """is_redflagged 兼容 redflagged:true / invalid:true 两种标记 + ForgeNode 形态。"""
    assert is_redflagged({REDFLAG_MARK: True}) is True
    assert is_redflagged({"invalid": True}) is True
    assert is_redflagged({"redflagged": False}) is False
    assert is_redflagged({"invalid": False}) is False
    assert is_redflagged({}) is False
    assert is_redflagged(None) is False
    # ForgeNode 形态
    n = ForgeNode.from_entry({"id": "x", "redflagged": True})
    assert is_redflagged(n) is True
    n2 = ForgeNode.from_entry({"id": "x"})
    assert is_redflagged(n2) is False


def test_redflag_rejects_forge() -> None:
    """红名节点 /锻造 拒绝语义：is_redflagged 命中 → 可拒绝（供指令侧判定）。"""
    orig = _forge()
    res = delete_items_effect(orig, ["flame_king_sword"], mode="redflag")
    nf = _forge_of(res)
    node = _node(nf, "node_flame_king_sword")
    assert is_redflagged(node), "红名节点 is_redflagged 应命中（/锻造 拒绝依据）"


# ---------------------------------------------------------------------------
# 模式参数校验 / 边界
# ---------------------------------------------------------------------------
def test_invalid_mode_rejected() -> None:
    import pytest
    with pytest.raises(ValueError):
        delete_items_effect(_forge(), ["flame_king_sword"], mode="bogus")
    with pytest.raises(ValueError):
        delete_forge_nodes(_forge(), ["node_iron_sword_2"], reconnect="bogus")


def test_delete_unknown_item_noop() -> None:
    """删除无节点引用的 items 条目 → 树不变（无引用即无级联动作）。"""
    orig = _forge()
    res = delete_items_effect(orig, ["nonexistent_weapon"], mode="redflag")
    assert res["redflagged"] == []
    assert res["forge"] == orig, "无引用条目不应改树"


def test_delete_unknown_node_noop() -> None:
    """删除不存在的 forge 节点 → 树不变。"""
    orig = _forge()
    res = delete_forge_nodes(orig, ["ghost_node"], reconnect="promote")
    assert res["deleted"] == []
    assert res["forge"] == orig


def test_tc26a_delete_ancestor_and_descendant_promote() -> None:
    """P1-2 回归：同批删祖先+后代（铁剑Ⅱ+炎剑）promote → 后代子（炎剑Ⅱ）上溯重连
    到首个存活祖先（铁剑Ⅰ），链不断；复查零悬空。"""
    orig = _forge()
    # 删 node_iron_sword_2（祖先） + node_flame_sword（其子，同批）
    res = delete_forge_nodes(
        orig, ["node_iron_sword_2", "node_flame_sword"], reconnect="promote")
    nf = _forge_of(res)
    # 铁剑Ⅰ 存活（未删），炎剑Ⅱ 应重连到 铁剑Ⅰ（上溯跳过已删的 铁剑Ⅱ/炎剑）
    assert "node_iron_sword_1" in _node_ids(nf), "铁剑Ⅰ 应保留"
    assert "node_iron_sword_2" not in _node_ids(nf), "铁剑Ⅱ 应已删"
    assert "node_flame_sword" not in _node_ids(nf), "炎剑 应已删"
    assert _node(nf, "node_flame_sword_2").get("parent") == "node_iron_sword_1", \
        "炎剑Ⅱ 应上溯重连到首个存活祖先 铁剑Ⅰ（链不断）"
    # 复查零悬空
    rep = cascade_recheck(nf, _modules(orig))
    assert rep["ok"] is True, f"同批删祖先+后代复查应通过，got errors={rep['errors']}"


def test_tc25a_redflag_clears_branch_recheck() -> None:
    """P1-3 回归：带 branch 中间节点（炎剑Ⅱ）红名 → 清空自身 branch →
    V15 red_name_branch_not_cleared 不再残留（branch 维度清干净；parent 残留
    red_name_referenced 仍按中间节点负例语义红拦，不在此断言范围）。"""
    orig = _forge()
    res = delete_items_effect(orig, ["flame_sword_2"], mode="redflag")
    nf = _forge_of(res)
    # 炎剑Ⅱ 红名且 branch 已清空
    assert "node_flame_sword_2" in _strs(res["redflagged"])
    assert is_redflagged(_node(nf, "node_flame_sword_2"))
    assert _node(nf, "node_flame_sword_2").get("branch") == [], \
        "红名节点自身 branch 应清空（V15 red_name_branch_not_cleared 不拦）"
    # V15 复查：branch 残留 red_name_branch_not_cleared 应消失
    rep = cascade_recheck(nf, _modules(orig, ["flame_sword_2"]))
    assert "red_name_branch_not_cleared" not in _rules(rep["errors"]), \
        f"branch 应已清空，got errors={rep['errors']}"
