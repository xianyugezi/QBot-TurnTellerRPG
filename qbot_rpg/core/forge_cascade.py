"""M9 锻造数据层 · 独立模块（路 1B）：forge 树级联删除与红名机制。

文件名：qbot_rpg/core/forge_cascade.py
创建时间：2026-08-30
作者：Hermes 子agent-1B（M9 锻造实现组批1·路1B：并发同仓，仅新建本文件 +
tests/unit/test_forge_cascade.py）

功能描述（对应规划_路2c2_锻造.md T4 · 级联删除，纯数据层运行期/编辑器操作）：
  - delete_items_effect(forge, deleted_item_ids, mode) ：删除 items 装备条目后的
    forge 树同步清理，二选一模式（2c2a §12.1.2 ①② / 定稿 L294-299）：
      * mode="redflag"：被引节点及其整棵子树保留但标红（节点加 redflagged:true
        标记），/锻造 拒绝、/图纸 显示「已失效：物品已删除」——红名节点由批0
        validate_forge 的 V15 自动识别（item 引用缺失即红名），父链完整、branch
        清空后复查通过（V15 允许红名）。
      * mode="remove"：被引节点及其全部子节点移除，父节点 branch 引用同步清理
        （防悬空引用）；roots 同步清理。
  - delete_forge_nodes(forge, deleted_node_ids, reconnect)：删除 forge 节点——
    已锻造实例保留旧属性（快照不受影响，本层不回溯，纯数据层无玩家存档侧写）；
    未锻造子链二选一（定稿 L301-304）：
      * reconnect="promote"：子节点上提重连（子 parent 指向原父节点的父节点，
        链不断；被删根节点的直接子上提为根）；branch/roots 清理。
      * reconnect="remove"：整支移除（被删节点+全部后代）并清理引用。
  - cascade_recheck(forge, modules)：级联后运行共享校验器 validate_forge 复查
    （V15 无残留悬空引用、红名节点父链完整）——直接调用批0 validate_forge，
    返回 errors/warnings，并把「红名节点自身的 V7 item_missing」归类为
    redflag_expected（红名状态的合法特征，不计失败）。
  - is_redflagged(node)：红名查询（供 /锻造 拒绝、/图纸 失效标注）。兼容
    redflagged:true 与 invalid:true 两种标记。

依据：
  - docs/细化/细化_2c2a_锻造派生树schema.md §12.1.2 级联删除（L291-307 区域，
    细化文档 §一 1.2 级联删除 + §五 V15 + §六 F 验收 TC-25~27）
  - docs/m9_shared_contract.md §二 N-01~17 节点字段 + §六 V15 级联删除复查
  - /root/docs_archive/RPG框架项目/锻造系统设计定稿.md §12.1.2（L292-308 级联删除）
  - docs/规划/规划_路2c2_锻造.md T4（forge 树级联删除与红名机制）
  - docs/m9_接口摸底.md（坑位：来源纯度 / 红名语义）
  - qbot_rpg/content/forge_models.py（批0 已实装：validate_forge + Def 类——级联后
    复查复用它；V15 红名自动识别口径、_items_map 引用靶形态）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  1. 红名标记键：契约表述「节点加 invalid:true 或 redflagged 标记」。本实现规范键
     用 "redflagged": true（语义专名），is_redflagged 同时兼容 "invalid": true。
     红名节点**保留原 item 引用**（指向已删除条目）——这是 V15 自动识别红名的
     依据（item 引用缺失即红名），且 /图纸 可据此展示「已失效：物品已删除」。
  2. 子树范围：redflag 模式下「节点及其子树保留但标红」——对被引节点做整棵子树
     标红（全部后代节点 redflagged:true），保证子树内任一节点 /锻造 均被拒绝。
     非叶子被引节点红名时其子树节点 parent 仍指向红名父节点，V15 会以
     red_name_referenced 报出残留（契约 V15 语义：红名节点被引用为 parent=悬空，
     作者需继续处理）；叶子红名（如炎王剑 final=true）V15 零残留。TC-25 验收以
     叶子路径为准，中间节点红名的 V15 报错属正确行为（负例覆盖于单测）。
  3. 入参不变性：所有级联函数返回**新的 forge dict**（deepcopy 后改写），不改
     入参——级联是编辑器/运行时操作，须可回滚（任务铁律）。
  4. deleted_item_ids 匹配口径：节点 item 引用取 item 或 output_item 别名
     （N-03 二选一，同批0 ForgeNode.item 口径）；任一引用 ∈ deleted_item_ids
     即视为被引节点。
  5. cascade_recheck 的红名预期过滤：validate_forge 对红名节点报 V7 item_missing
     （加载期硬校验视角），但 V15 明确允许红名节点存在——复查语义为「无残留
     悬空引用、红名节点父链完整」。故 cascade_recheck 把 rule=item_missing 且
     item ∈ 红名节点引用集的错误归类为 redflag_expected（不计失败），真正残留
     （red_name_referenced / red_name_branch_not_cleared / 其它 V 错）留在 errors。
     级联保证判定面 = dangling_errors（V3 parent_missing / V4 环 / V5 branch_missing
     / V15 红名残留 / 非红名 V7 item_missing），ok = 无悬空引用（定稿 L299「不残留
     悬空引用」）；V6 leaf_not_final 等作者标注/结构类错误仍在 errors 全量返回
     （编辑器提示作者补 final 或续链），不计级联失败。
  6. 已锻造实例保留旧属性：本层纯数据层，不触碰玩家存档快照（属性快照入档归
     批1路1A 的实例化管线）；删除 forge 节点不回溯任何已入档实例——定稿
     L302「删除节点不回溯、实例继续可用（旧属性保留）」由「本层不写存档」天然
     满足，删除节点仅影响未锻造子链的树结构。

铁律：零 NoneBot import；纯函数（级联返回新 forge dict，不改入参）；确定性；
不写定时器/睡眠调用；平台无关；完整类型标注（typing 3.9 兼容）。
仅依赖标准库 + qbot_rpg.content.forge_models（validate_forge / ForgeNode）。
"""

from __future__ import annotations

import copy
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Set, Tuple, cast

from qbot_rpg.content.forge_models import ForgeNode, validate_forge

__all__ = [
    "delete_items_effect",
    "delete_forge_nodes",
    "cascade_recheck",
    "is_redflagged",
    "REDFLAG_MARK",
    "REDFLAG_ALT_MARK",
    "ITEM_DELETE_MODES",
    "NODE_RECONNECT_MODES",
]

# 红名标记键（补白1）：规范键 redflagged + 兼容键 invalid
REDFLAG_MARK: str = "redflagged"
REDFLAG_ALT_MARK: str = "invalid"

ITEM_DELETE_MODES: Tuple[str, ...] = ("redflag", "remove")
NODE_RECONNECT_MODES: Tuple[str, ...] = ("promote", "remove")


# -------------------------------------------------------------------------------------
# 内部辅助（纯函数）
# -------------------------------------------------------------------------------------
def _node_ref(node: Mapping[str, object]) -> Optional[str]:
    """节点 item 引用（N-03：item / output_item 别名二选一，同批0 ForgeNode.item）。"""
    v = node.get("item") or node.get("output_item")
    return v if isinstance(v, str) and v else None


def _all_nodes(forge: Mapping[str, object]) -> List[Mapping[str, object]]:
    """flat 出全部树节点 raw dict（保持树序；非 Mapping 节点丢弃）。"""
    out: List[Mapping[str, object]] = []
    trees = forge.get("trees")
    if not isinstance(trees, list):
        return out
    for tree in trees:
        if not isinstance(tree, Mapping):
            continue
        nodes = tree.get("nodes")
        if isinstance(nodes, list):
            for n in nodes:
                if isinstance(n, Mapping):
                    out.append(n)
    return out


def _node_id_map(
    forge: Mapping[str, object],
) -> Tuple[Dict[str, MutableMapping[str, object]], Dict[str, List[str]]]:
    """构建 (node_id → node raw, node_id → 直接子节点 id 列表)。"""
    by_id: Dict[str, MutableMapping[str, object]] = {}
    children: Dict[str, List[str]] = {}
    for n in _all_nodes(forge):
        nid = n.get("id")
        if not isinstance(nid, str) or not nid:
            continue
        mm = n if isinstance(n, MutableMapping) else dict(n)
        by_id[nid] = mm
        p = n.get("parent")
        if isinstance(p, str) and p:
            children.setdefault(p, []).append(nid)
    return by_id, children


def _subtree_ids(
    by_id: Mapping[str, Mapping[str, object]],
    children: Mapping[str, List[str]],
    root_ids: Iterable[str],
) -> Set[str]:
    """沿 parent 反向（children 索引）收集 root_ids 的整棵后代集合（含自身）。"""
    out: Set[str] = set()
    stack: List[str] = list(root_ids)
    while stack:
        nid = stack.pop()
        if nid in out:
            continue
        out.add(nid)
        for c in children.get(nid, []):
            if c not in out:
                stack.append(c)
    return out


def _clean_refs(forge: MutableMapping[str, object], gone: Set[str]) -> None:
    """清理对 gone 集合的引用：branch 条目 / roots 条目（就地改写 trees 段）。"""
    trees = forge.get("trees")
    if not isinstance(trees, list):
        return
    for tree in trees:
        if not isinstance(tree, MutableMapping):
            continue
        # branch 清理：任何节点 branch 中含 gone 元素 → 移除
        nodes = tree.get("nodes")
        if isinstance(nodes, list):
            for n in nodes:
                if not isinstance(n, MutableMapping):
                    continue
                br = n.get("branch")
                if isinstance(br, list):
                    n["branch"] = [b for b in br if not (isinstance(b, str) and b in gone)]
        # roots 清理：roots 中含 gone 元素 → 移除
        roots = tree.get("roots")
        if isinstance(roots, list):
            tree["roots"] = [r for r in roots if not (isinstance(r, str) and r in gone)]


def _node_refs_by_ids(forge: Mapping[str, object]) -> Dict[str, Set[str]]:
    """node_id → 该节点 item 引用集合（别名双写防御：两键都算）。"""
    out: Dict[str, Set[str]] = {}
    for n in _all_nodes(forge):
        nid = n.get("id")
        if not isinstance(nid, str) or not nid:
            continue
        refs: Set[str] = set()
        for k in ("item", "output_item"):
            v = n.get(k)
            if isinstance(v, str) and v:
                refs.add(v)
        out[nid] = refs
    return out


# -------------------------------------------------------------------------------------
# 1) 删 items 装备条目 → forge 树同步（redflag / remove 二选一）
# -------------------------------------------------------------------------------------
def delete_items_effect(
    forge: Mapping[str, object],
    deleted_item_ids: Iterable[str],
    mode: str = "redflag",
) -> Dict[str, object]:
    """删除被 forge 节点引用的 items 装备条目后的 forge 树同步（2c2a §12.1.2 ①②）。

    入参：
      forge: forge.json 顶层 dict（Mapping，含 trees 等四段）；不会被改写。
      deleted_item_ids: 已从 items.json 删除的装备条目 id 迭代（可迭代）。
      mode: "redflag"（默认，① 节点及其子树保留标红）| "remove"（② 整棵子树移除）。
    返回：
      {"forge": 新 forge dict, "deleted": 实际处理的条目 id 列表,
       "redflagged": 红名/保留节点 id 列表（remove 模式为空）,
       "removed": 移除节点 id 列表（redflag 模式为空）,
       "mode": 实际模式}
    若 deleted_item_ids 中某条目无节点引用 → 该 id 计入 deleted 但不影响树
    （无引用即无级联动作，契约仅同步被引节点）。
    """
    if mode not in ITEM_DELETE_MODES:
        raise ValueError("mode 须 ∈ %s（契约 2c2a §12.1.2 二选一）" % (ITEM_DELETE_MODES,))

    deleted = sorted({d for d in deleted_item_ids if isinstance(d, str) and d})
    new_forge: MutableMapping[str, object] = cast(
        MutableMapping[str, object], copy.deepcopy(forge))

    # 收集被引节点：item 引用 ∈ deleted 的节点 id
    refs_by_id = _node_refs_by_ids(new_forge)
    affected: List[str] = []
    for nid, refs in refs_by_id.items():
        if refs & set(deleted):
            affected.append(nid)
    affected = sorted(set(affected))

    if not affected:
        return {
            "forge": new_forge,
            "deleted": deleted,
            "redflagged": [],
            "removed": [],
            "mode": mode,
        }

    by_id, children = _node_id_map(new_forge)
    subtree = _subtree_ids(by_id, children, affected)

    if mode == "redflag":
        # ① 被引节点及其整棵子树保留但标红（补白2）
        for n in _all_nodes(new_forge):
            rid = n.get("id")
            if isinstance(rid, str) and rid in subtree:
                mm = n if isinstance(n, MutableMapping) else dict(n)
                mm[REDFLAG_MARK] = True
        return {
            "forge": new_forge,
            "deleted": deleted,
            "redflagged": sorted(subtree),
            "removed": [],
            "mode": mode,
        }

    # ② 整棵子树移除 + 父节点 branch / roots 同步清理（防悬空）
    _clean_refs(new_forge, subtree)
    trees = new_forge.get("trees")
    if isinstance(trees, list):
        for tree in trees:
            if not isinstance(tree, MutableMapping):
                continue
            nodes = tree.get("nodes")
            if isinstance(nodes, list):
                tree["nodes"] = [
                    n for n in nodes if not (
                        isinstance(n, Mapping)
                        and isinstance(n.get("id"), str)
                        and n["id"] in subtree
                    )
                ]
    return {
        "forge": new_forge,
        "deleted": deleted,
        "redflagged": [],
        "removed": sorted(subtree),
        "mode": mode,
    }


# -------------------------------------------------------------------------------------
# 2) 删 forge 节点 → 已锻实例保留旧属性 + 未锻子链重连/移除
# -------------------------------------------------------------------------------------
def delete_forge_nodes(
    forge: Mapping[str, object],
    deleted_node_ids: Iterable[str],
    reconnect: str = "remove",
) -> Dict[str, object]:
    """删除 forge 节点（定稿 L301-304：已锻实例不回溯，未锻子链二选一）。

    入参：
      forge: forge.json 顶层 dict；不会被改写。
      deleted_node_ids: 要删除的 forge 节点 id 迭代。
      reconnect: "promote"（默认，① 子节点上提重连，链不断）| "remove"（② 整支移除）。
    返回：
      {"forge": 新 forge dict,
       "affected_nodes": 受影响的节点 id 列表（被删节点 + 全部后代；promote 时
         含上提重连的节点）,
       "deleted": 实际删除的节点 id 列表,
       "removed": 整支移除的节点 id 列表（含后代；promote 模式=被删节点自身）,
       "reconnected": 上提重连的子节点 id 列表（remove 模式为空）,
       "mode": reconnect 模式,
       "note": 已锻造实例保留旧属性（快照不受影响，本层不回溯）声明}
    说明：已锻造实例属性已快照入玩家存档，删除 forge 节点不回溯——本层纯数据层
    不写玩家存档（补白6），删除仅影响未锻造子链的树结构。
    """
    if reconnect not in NODE_RECONNECT_MODES:
        raise ValueError(
            "reconnect 须 ∈ %s（定稿 §12.1.2 未锻子链二选一）" % (NODE_RECONNECT_MODES,))

    targets = sorted({d for d in deleted_node_ids if isinstance(d, str) and d})
    new_forge: MutableMapping[str, object] = cast(
        MutableMapping[str, object], copy.deepcopy(forge))

    by_id, children = _node_id_map(new_forge)
    present = [t for t in targets if t in by_id]

    affected_set = _subtree_ids(by_id, children, present)
    affected = sorted(affected_set)
    reconnected: List[str] = []

    if reconnect == "promote":
        # ① 子节点上提重连：直接子节点 parent 指向被删节点的父（原父的父），链不断。
        #    被删根节点（parent=None）的直接子上提为根（加入 tree.roots）。
        for nid in present:
            node = by_id[nid]
            gp = node.get("parent")  # 原父的父（被删节点的父）
            grand: Optional[str] = gp if isinstance(gp, str) and gp else None
            for c in children.get(nid, []):
                cnode = by_id[c]
                # 只处理仍在树中的直接子（子树中更深的后代 parent 不变，链不断）
                cnode["parent"] = grand if grand is not None else None
                if grand is None:
                    # 被删根节点：直接子上提为新根 → 加入对应 tree.roots
                    _add_root(new_forge, c)
                reconnected.append(c)
            # 被删节点的 branch 指向（转线目标）在重连场景下随子节点继承；若
            # branch 目标非直接子（更深后代）仍可达，无需清理；直接子已上提。
        # 清理对已删节点的全部引用（branch/roots），防 V5/V15 悬空
        _clean_refs(new_forge, set(present))
        # 移除被删节点自身（子树其余节点保留并重连）
        _remove_nodes(new_forge, set(present))
    else:
        # ② 整支移除：被删节点 + 全部后代移除，引用清理
        _clean_refs(new_forge, affected_set)
        _remove_nodes(new_forge, affected_set)

    return {
        "forge": new_forge,
        "affected_nodes": sorted(set(affected) | set(reconnected)),
        "deleted": present,
        "removed": sorted(affected_set),
        "reconnected": sorted(set(reconnected)),
        "mode": reconnect,
        "note": "已锻造实例保留旧属性（快照不受影响，本层不回溯）",
    }


def _remove_nodes(forge: MutableMapping[str, object], gone: Set[str]) -> None:
    """从 trees[].nodes 移除 gone 集合中的节点（就地）。"""
    trees = forge.get("trees")
    if not isinstance(trees, list):
        return
    for tree in trees:
        if not isinstance(tree, MutableMapping):
            continue
        nodes = tree.get("nodes")
        if isinstance(nodes, list):
            tree["nodes"] = [
                n for n in nodes if not (
                    isinstance(n, Mapping)
                    and isinstance(n.get("id"), str)
                    and n["id"] in gone
                )
            ]


def _add_root(forge: MutableMapping[str, object], node_id: str) -> None:
    """将 node_id 加入其所属树的 roots（被删根节点 promote 上提场景）。"""
    trees = forge.get("trees")
    if not isinstance(trees, list):
        return
    for tree in trees:
        if not isinstance(tree, MutableMapping):
            continue
        nodes = tree.get("nodes")
        if not isinstance(nodes, list):
            continue
        # 找到该节点所属树（节点在 trees[].nodes 中）
        if any(
            isinstance(n, Mapping) and n.get("id") == node_id for n in nodes
        ):
            roots = tree.get("roots")
            if isinstance(roots, list) and node_id not in roots:
                roots.append(node_id)
            return


# -------------------------------------------------------------------------------------
# 3) 级联后复查（V15：无残留悬空引用、红名节点父链完整）
# -------------------------------------------------------------------------------------
def cascade_recheck(
    forge: Mapping[str, object],
    modules: Mapping[str, object],
) -> Dict[str, object]:
    """级联操作后运行批0 validate_forge 复查，返回 errors/warnings。

    直接调用 qbot_rpg.content.forge_models.validate_forge（共享校验器，V1~V15 +
    V16/W1~W6 + 2c2d 全量）；modules 用于提供 items/enemies 等引用靶（对齐
    validate_forge 的 (modules, report) 鸭子形态），其中 forge 段被替换为级联后
    的 forge。

    返回：
      {"errors": [...], "warnings": [...], "red_nodes": [...],
       "redflag_expected": [...], "dangling_errors": [...], "ok": bool}
      - errors：validate_forge 全量错误（红名节点自身的 item_missing 已归类到
        redflag_expected）。含级联残留 + 作者层结构/标注类（如 V6 leaf_not_final——
        子树移除后暴露的非 final 叶子属作者标注决策，编辑器提示，不计级联失败）。
      - dangling_errors：级联残留悬空引用子集（V3 parent_missing / V4 环 /
        V5 branch_missing / V15 red_name_referenced·red_name_branch_not_cleared /
        非红名节点 V7 item_missing）——级联保证的判定面（定稿 L299「不残留悬空
        引用」）。
      - warnings：黄提示（不阻断）。
      - red_nodes：级联后仍存在的红名节点 id 列表。
      - redflag_expected：红名节点自身的 V7 item_missing（红名状态合法特征，
        补白5；不计入失败）。
      - ok：dangling_errors 为空（级联复查通过：无残留悬空引用、红名节点父链完整）。
    错误条目形态（对齐批0 收集器口径）：{"module","field","kind","detail"}。
    """
    modules2: Dict[str, object] = dict(modules)
    modules2["forge"] = forge
    report = _CascadeReport()
    validate_forge(modules2, report)

    # 红名节点引用集：rule=item_missing 且 item ∈ 红名节点引用 → 预期红名
    red_ids: List[str] = []
    red_refs: Set[str] = set()
    for n in _all_nodes(forge):
        nid = n.get("id")
        if isinstance(nid, str) and nid and is_redflagged(n):
            red_ids.append(nid)
            r = _node_ref(n)
            if r:
                red_refs.add(r)
    red_nodes = sorted(set(red_ids))

    errors: List[Dict[str, object]] = []
    redflag_expected: List[Dict[str, object]] = []
    for e in report.errors:
        detail = cast(Dict[str, object], e.get("detail") or {})
        is_red_item_missing = (
            e.get("kind") == "V7"
            and detail.get("rule") == "item_missing"
            and isinstance(detail.get("item"), str)
            and detail["item"] in red_refs
        )
        if is_red_item_missing:
            redflag_expected.append(e)
        else:
            errors.append(e)

    # 级联残留悬空引用子集（V15/V5/V3/V4 + 非红名 V7 item_missing）
    dangling_errors = [e for e in errors if _is_dangling_error(e)]

    return {
        "errors": errors,
        "warnings": list(report.warnings),
        "red_nodes": red_nodes,
        "redflag_expected": redflag_expected,
        "dangling_errors": dangling_errors,
        "ok": not dangling_errors,
    }


# 级联残留悬空引用规则集（定稿 L299「不残留悬空引用」判定面；V6 作者标注类不在内）
_DANGLING_RULES: Set[str] = {
    "parent_missing", "parent_cross_tree", "root_missing",      # V3 引用缺失
    "parent_cycle", "parent_self_cycle", "root_not_declared",   # V4 环/可达
    "branch_missing",                                            # V5 分支悬空
    "red_name_referenced", "red_name_branch_not_cleared",       # V15 红名残留
    "item_missing",                                              # 非红名 V7 item 悬空
}


def _is_dangling_error(e: Mapping[str, object]) -> bool:
    """错误是否为级联残留悬空引用（V15/V5/V3/V4 + 非红名 V7 item_missing）。"""
    detail = cast(Dict[str, object], e.get("detail") or {})
    rule = detail.get("rule")
    if rule in _DANGLING_RULES:
        return True
    # V7 item_missing 已由上层过滤红名预期；到达这里的 item_missing 即非红名悬空
    if e.get("kind") == "V7" and rule == "item_missing":
        return True
    return False


class _CascadeReport:
    """validate_forge 收集器（error/warning 鸭子形态；结果结构化保留）。"""

    def __init__(self) -> None:
        self.errors: List[Dict[str, object]] = []
        self.warnings: List[Dict[str, object]] = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append(
            {"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append(
            {"module": module, "field": field, "kind": kind, "detail": detail})


# -------------------------------------------------------------------------------------
# 4) 红名查询（供 /锻造 拒绝、/图纸 失效标注）
# -------------------------------------------------------------------------------------
def is_redflagged(node: object) -> bool:
    """节点是否红名（redflagged:true 或 invalid:true 标记；兼容 raw dict 与 ForgeNode）。

    供 /锻造 拒绝红名节点、/图纸 显示「已失效：物品已删除」。
    """
    if isinstance(node, ForgeNode):
        raw = node.raw
    elif isinstance(node, Mapping):
        raw = node
    else:
        return False
    return bool(raw.get(REDFLAG_MARK) is True or raw.get(REDFLAG_ALT_MARK) is True)
