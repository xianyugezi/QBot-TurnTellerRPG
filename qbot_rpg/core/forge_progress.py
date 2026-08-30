"""M9 锻造·批2·路2B：素材即进度查询服务（qbot_rpg/core/forge_progress.py）——ForgeProgressEngine。

文件名：qbot_rpg/core/forge_progress.py
创建时间：2026-08-30
作者：Hermes 子agent-2B（M9 锻造实现组批2·路2B：并发同仓，仅新建本文件 +
  tests/unit/test_forge_progress.py；不改动批0/批1 已有文件、fixtures）

功能描述：素材即进度（PROG-01~08）的查询服务，供两处复用——/锻造 错误提示（缺件差量+
  来源）与 /图纸 持有进度行（持有/需求 + ✓ 标注 + 满链可锻判定）：
  1) material_holdings(ctx, node)：节点素材需求行逐项持有量（PROG-04：背包物品栈按 id
     计数；持有取自 ctx 背包计数映射——count_item hook 或 inventory，对齐 synthesis.py）
  2) shortfall(node_holdings)：差量计算（PROG-02：need−have，负数行不显示）→
     {items: [(名称, 缺额, 来源)], coins, gem} 供 /锻造 错误提示
  3) progress_line(node_holdings, forged_prefix_names)：`当前持有：火龙鳞 1/3 | 矿石
     5/5 ✓ | 铁剑Ⅰ ✓`（PROG-05 模板；已锻前置节点名后 ✓；素材满额 5/5 ✓，未满 1/3
     仅进度不标 ✓）
  4) forge_readiness(ctx, player, node, tree)：满链推进度（PROG-01 / 2c2b §2.3：前置
     全部已锻 + 素材全部满额 → {ready: True, message}；否则 {ready: False, gaps}）——
     复用 forge_tree.parent_forged 判定前置
  纯函数确定性（同刻同参必同值），零 IO 零 NoneBot；构造器配置注入 + 缺省兜底。

依据：
  - docs/细化/细化_2c2c_锻造素材经济.md：§3（PROG-01 原子校验三态 / PROG-02 差量计算 /
    PROG-03 不扣半程 / PROG-04 数据流 / PROG-05 图纸全链输出 / PROG-07 来源提示随行）、
    §1（SOUR-00 来源提示元数据：source_override M-04 覆写 > items 来源标签）。
  - docs/细化/细化_2c2b_锻造流程契约.md：§1.1（GU-05 素材足够）、§1.3（缺件报错模板：
    `❌ 素材不足：需要 …；缺：…（来源：…）`）、§2.2（持有进度行模板 L101-107）、
    §2.3（✓ 标注规则：已锻前置节点后 ✓ / 素材满额 ✓ 态 / 满链推进度可锻造）。
  - docs/m9_shared_contract.md：§二（MaterialReq M-01~04：item/count/tier/source_override）、
    §八（items 材料类 source 来源标签）。
  - 复用批1：qbot_rpg/core/forge_tree.py（ForgeTreeEngine.parent_forged 前置已锻判定——
    本文件只调用不重写其语义）。
  - 模式参考：qbot_rpg/core/synthesis.py（ctx hook 模式：count_item 持有计数 / items
    注册表名解析；构造器配置注入 + 缺省兜底）、qbot_rpg/core/alchemy_core.py（引擎模块
    形态：常量 + 类 + __all__）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x；不得新增定稿外机制行为）：
  F-1  满额素材标 ✓：progress_line 中素材 `have ≥ need` 追加 ` ✓`（2c2b §2.3「素材满额即
       ✓ 态」）；TC-13 定稿模板原文 `矿石 5/5` 未带后缀，本实现按任务口径与 §2.3 语义落
       「5/5 ✓」——✓ 标注规则以 §2.3 为准（满额 = ✓ 态）。
  F-2  shortfall 的 coins/gem 恒 0：入参仅素材持有量（node_holdings），不含节点 cost
       （N-11 / 金币）；货币差量归批4 /锻造 指令壳按 node.cost 另算。结构保留 coins/gem
       键对齐 synthesis._material_shortfall 形态（{items, coins, gem}）。
  F-3  progress_line 的已锻前置节点名由调用方传入（forged_prefix_names 序列）：引擎零
       状态，前置已锻判定属 forge_tree.parent_forged（本函数不重复判定）；模板按名渲染
       `名 ✓`。缺省 () → 只渲染素材段（单节点 / 根节点 / 图纸不关心前置时复用）。
  F-4  forge_readiness 的 tree（ForgeTreeEngine）缺省 None → 前置保守未锻（gaps 含前置
       缺口）：无树无法判定 parent 链，保守报缺前置（确定性兜底）；调用方（/锻造 /图纸
       指令壳）应注入批1 ForgeTreeEngine 获得真实判定。
  F-5  素材来源解析（PROG-07/SOUR-00）：source_override（M-04 行覆写）优先，回退
       items 材料条目的 source 来源标签；items 无条目/无 source → 空串。
  F-6  node 归一：material_holdings / forge_readiness 接受 ForgeNode（批0）或 raw dict
       两种形态；materials 逐行读 item/count/source_override，行序保持文件序。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；不写定时器/睡眠调用（M43 零定时器
      探针）；平台无关；不引入随机；每功能可追溯（文件头标注依据）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from qbot_rpg.content.forge_models import ForgeNode
from qbot_rpg.core.forge_tree import ForgeTreeEngine

__all__ = [
    "PROGRESS_PREFIX",
    "ForgeProgressEngine",
    "material_holdings",
    "shortfall",
    "progress_line",
    "forge_readiness",
]

# /图纸 持有进度行前缀（PROG-05 / 2c2b §2.2 模板 L107）
PROGRESS_PREFIX: str = "当前持有："


# ---------------------------------------------------------------------------
# ctx 基础工具（纯函数，镜像 synthesis.py 同款实现——持有计数/物品名解析）
# ---------------------------------------------------------------------------
def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    """持有计数（PROG-04）：优先 ctx[\"count_item\"] hook；回退 ctx[\"inventory\"] in-memory。"""
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            v: Any = hook(item_id)
            return int(v)
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


def _items_lookup(ctx: Mapping[str, Any], item_id: str) -> Optional[Mapping[str, Any]]:
    """items 条目查找（F-5）：ctx[\"items\"] 支持 id→条目 Mapping 或条目 list/tuple。

    对齐 ForgeTreeEngine._norm_items 双形态（真实 items.json 为条目数组 list）；
    ctx[\"resolve_item\"] 解析器 hook 兜底。未命中 → None。
    """
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        if isinstance(hit, Mapping):
            return hit
    elif isinstance(items, (list, tuple)):
        for e in items:
            if isinstance(e, Mapping) and e.get("id") == item_id:
                return e
    resolver = ctx.get("resolve_item")
    if callable(resolver):
        try:
            hit = resolver(item_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            return hit
    return None


def _item_name(item_id: str, ctx: Mapping[str, Any]) -> str:
    """物品 id → 显示名（items 表 name；缺省回退原 id）。"""
    if not isinstance(item_id, str):
        return str(item_id)
    hit = _items_lookup(ctx, item_id)
    if hit is not None:
        name = hit.get("name")
        if isinstance(name, str) and name:
            return name
    return item_id


def _item_source(item_id: str, ctx: Mapping[str, Any]) -> str:
    """素材来源标签（PROG-07 / SOUR-00）：items 材料条目 source；缺 → 空串。"""
    hit = _items_lookup(ctx, item_id)
    if hit is not None:
        src = hit.get("source")
        if isinstance(src, str) and src:
            return src
    return ""


# ---------------------------------------------------------------------------
# node 归一（F-6：ForgeNode 或 raw dict → 素材需求行 Mapping 列表，文件序）
# ---------------------------------------------------------------------------
def _materials_of(node: object) -> List[Mapping[str, object]]:
    """节点素材需求行归一（F-6）：ForgeNode.raw / raw dict 的 materials list。

    行序 = 文件序（materials 数组序）；畸形条目（非 Mapping）跳过。
    """
    raw: Mapping[str, object] = node.raw if isinstance(node, ForgeNode) else (
        node if isinstance(node, Mapping) else {}
    )
    mats = raw.get("materials")
    if not isinstance(mats, list):
        return []
    return [m for m in mats if isinstance(m, Mapping)]


def _node_id(node: object) -> Optional[str]:
    """节点 id 提取（ForgeNode.id / raw dict[\"id\"]；无 → None）。"""
    if isinstance(node, ForgeNode):
        return node.id
    if isinstance(node, Mapping):
        v = node.get("id")
        return v if isinstance(v, str) and v else None
    return None


def _as_int(value: object) -> Optional[int]:
    """int 归一（bool 除外）；非 int/可转数字串 → None（对齐 synthesis._as_int）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# 1) material_holdings：节点素材需求行逐项持有量（PROG-04）
# ---------------------------------------------------------------------------
def material_holdings(ctx: Mapping[str, Any], node: object) -> Dict[str, Dict[str, Any]]:
    """节点素材需求行逐项持有量（PROG-04 / 2c2c §3.1；F-6 双形态 node）。

    入参：
      - ctx：玩家表示 + items 注册表/count_item hook（对齐 synthesis.py ctx 契约）；
        持有量 = 背包物品栈按 id 计数（count_item hook 或 inventory，PROG-04 数据流）。
      - node：ForgeNode 或 raw dict（含 materials 行；item/count/source_override）。

    出参：{item_id: {need, have, name, source}}，行序 = materials 文件序。
      - need：需求 count（非正整数行跳过，V11 应拦）
      - have：背包持有量（_count_item，缺 → 0）
      - name：素材显示名（items 表 name，缺 → 原 item_id）
      - source：来源提示（source_override 覆写 > items.source；F-5）
    纯函数确定性；零 IO 零 NoneBot。
    """
    out: Dict[str, Dict[str, Any]] = {}
    for m in _materials_of(node):
        item_id = m.get("item")
        if not isinstance(item_id, str) or not item_id:
            continue
        need = _as_int(m.get("count"))
        if need is None or need <= 0:
            continue
        override = m.get("source_override")
        source = override if isinstance(override, str) and override else _item_source(
            item_id, ctx
        )
        out[item_id] = {
            "need": need,
            "have": _count_item(ctx, item_id),
            "name": _item_name(item_id, ctx),
            "source": source,
        }
    return out


# ---------------------------------------------------------------------------
# 2) shortfall：差量计算（PROG-02：need−have，负数行不显示）
# ---------------------------------------------------------------------------
def shortfall(node_holdings: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """差量计算（PROG-02 / 2c2c §3.1）：逐项 need−have，仅缺额 > 0 的行列出。

    入参：node_holdings（material_holdings 输出：{item_id: {need, have, name, source}}）。
    出参：{items: [(名称, 缺额, 来源), ...], coins: 0, gem: 0} 供 /锻造 错误提示
      （2c2b §1.3 模板 `缺：火龙鳞×2（来源：火龙掉落/商店）`）。
      - 素材行按文件序；have ≥ need（差量 ≤ 0）的行不显示（负数行不显示）。
      - coins/gem 恒 0（F-2：入参仅素材持有量，货币差量归批4 按 node.cost 另算）。
    纯函数确定性。
    """
    items: List[tuple] = []
    for _item_id, h in node_holdings.items():
        need = int(h.get("need", 0))
        have = int(h.get("have", 0))
        deficit = need - have
        if deficit > 0:
            items.append((str(h.get("name", _item_id)), deficit, str(h.get("source", ""))))
    return {"items": items, "coins": 0, "gem": 0}


# ---------------------------------------------------------------------------
# 3) progress_line：持有进度行（PROG-05 / 2c2b §2.2 模板 + §2.3 ✓ 标注）
# ---------------------------------------------------------------------------
def progress_line(
    node_holdings: Mapping[str, Mapping[str, Any]],
    forged_prefix_names: Sequence[str] = (),
) -> str:
    """持有进度行（PROG-05 模板 `当前持有：火龙鳞 1/3 | 矿石 5/5 ✓ | 铁剑Ⅰ ✓`）。

    入参：
      - node_holdings：material_holdings 输出（素材行；need/have/name）。
      - forged_prefix_names：已锻前置节点名序列（F-3；调用方经 forge_tree.parent_forged
        判定后传入；每名渲染 `名 ✓`）。
    输出规则（2c2b §2.3）：
      - 素材行：`名 have/need`；满额（have ≥ need）→ 追加 ` ✓`（F-1）；未满仅进度不标。
      - 已锻前置节点名：`名 ✓`。
      - 素材段在前（文件序）、前置段在后，` | ` 连接，前缀 `当前持有：`。
      - 全空 → `当前持有：`（前缀兜底，无内容段）。
    纯函数确定性。
    """
    parts: List[str] = []
    for _item_id, h in node_holdings.items():
        name = str(h.get("name", _item_id))
        need = int(h.get("need", 0))
        have = int(h.get("have", 0))
        seg = f"{name} {have}/{need}"
        if have >= need:
            seg += " ✅"
        parts.append(seg)
    for pname in forged_prefix_names:
        if isinstance(pname, str) and pname:
            parts.append(f"{pname} ✅")
    return PROGRESS_PREFIX + " | ".join(parts)


# ---------------------------------------------------------------------------
# 4) forge_readiness：满链推进度（PROG-01 三态 / 2c2b §2.3 可锻造）
# ---------------------------------------------------------------------------
def _first_unforged_parent(
    tree: ForgeTreeEngine, player: object, node_id: str
) -> Optional[str]:
    """前置链上第一个未锻父节点 id（根在前→自身；全部已锻/根节点 → None）。

    复用 tree.path_to_root（含自身）+ tree.already_forged；自身不参与前置判定。
    供 gaps 的「需先锻造 <前置名>」缺口定位（2c2b TC-16 / GU-04）。
    """
    chain = tree.path_to_root(node_id)
    if not chain:
        return None
    for nid in chain:
        if nid == node_id:
            break
        if not tree.already_forged(player, nid):
            return nid
    return None


def forge_readiness(
    ctx: Mapping[str, Any],
    player: object,
    node: object,
    tree: Optional[ForgeTreeEngine] = None,
) -> Dict[str, Any]:
    """满链推进度（PROG-01 / 2c2b §2.3）：前置全部已锻 + 素材全部满额 → 可锻造。

    入参：
      - ctx：玩家背包表示（material_holdings 的计数来源）。
      - player：已锻造集合（tree.parent_forged 前置判定输入，F-1 口径同批1）。
      - node：ForgeNode 或 raw dict（素材行 + id）。
      - tree：ForgeTreeEngine（批1）；None → 前置保守未锻（F-4 确定性兜底）。
    出参：
      - {ready: True, message: "可锻造", node_id, shortfall}：前置全锻 + 素材全满额
        （2c2b §2.3「满链推进度」；message 供 /图纸 辅助行）。
      - {ready: False, gaps: [...], node_id, shortfall}：gaps 为缺口描述列表——
        `需先锻造 <前置节点名>`（首个未锻前置，2c2b TC-16）+ 逐素材
        `缺 <名>×<缺额>（来源：<来源>）`（PROG-02 模板，来源空则略）；素材缺口在后。
    纯函数确定性（同刻同参必同值）；不抛异常。
    """
    holdings = material_holdings(ctx, node)
    node_id = _node_id(node)
    short = shortfall(holdings)

    # 前置判定（复用批1 parent_forged；F-4 兜底：无树 → 保守未锻）
    parent_ok = True
    first_unforged: Optional[str] = None
    if tree is not None:
        if node_id:
            parent_ok = tree.parent_forged(player, node_id)
            if not parent_ok:
                first_unforged = _first_unforged_parent(tree, player, node_id)
    else:
        parent_ok = False  # 无树无法判 parent 链 → 保守缺口（F-4）

    gaps: List[str] = []
    if not parent_ok:
        if first_unforged:
            node = tree.node(first_unforged) if tree is not None else None
            name = node.name if node is not None else _item_name(first_unforged, ctx)
            gaps.append(f"需先锻造 {name}")
        else:
            gaps.append("需先锻造 前置节点")  # F-4 兜底（无树/无链可判）

    for _item_id, h in holdings.items():
        need = int(h.get("need", 0))
        have = int(h.get("have", 0))
        deficit = need - have
        if deficit > 0:
            src = str(h.get("source", ""))
            base = f"缺 {h.get('name', _item_id)}×{deficit}"
            gaps.append(base if not src else f"{base}（来源：{src}）")

    if gaps:
        return {"ready": False, "gaps": gaps, "node_id": node_id, "shortfall": short}
    return {
        "ready": True,
        "message": "可锻造",
        "node_id": node_id,
        "shortfall": short,
    }


# ---------------------------------------------------------------------------
# ForgeProgressEngine：素材即进度查询引擎（构造器注入 ForgeTreeEngine + 缺省兜底）
# ---------------------------------------------------------------------------
class ForgeProgressEngine:
    """素材即进度查询引擎（PROG-01~08）：持有量/差量/进度行/满链判定。

    构造器注入 ForgeTreeEngine（批1，parent_forged 前置判定）；缺省 None → 内部
    缺省构造空树引擎（forge 缺省 {}，前置保守未锻，对齐 F-4 兜底）。
    纯函数确定性，零 IO 零 NoneBot；方法委托模块级同名函数。
    """

    def __init__(self, tree: Optional[ForgeTreeEngine] = None) -> None:
        """构造素材即进度引擎（构造器配置注入 + 缺省兜底）。

        入参：
          - tree：ForgeTreeEngine（批1，forge 真实树）；None → 缺省空树引擎
            （forge_raw {}，所有节点查询返回空；前置判定保守未锻）。
        """
        if isinstance(tree, ForgeTreeEngine):
            self._tree: ForgeTreeEngine = tree
        else:
            self._tree = ForgeTreeEngine()  # 缺省空树（F-4 兜底口径）

    def engine(self) -> ForgeTreeEngine:
        """内部 ForgeTreeEngine（只读引用；供调用方复用 parent_forged 等）。"""
        return self._tree

    def material_holdings(
        self, ctx: Mapping[str, Any], node: object
    ) -> Dict[str, Dict[str, Any]]:
        """节点素材需求行逐项持有量（PROG-04；委托模块级 material_holdings）。"""
        return material_holdings(ctx, node)

    def shortfall(
        self, node_holdings: Mapping[str, Mapping[str, Any]]
    ) -> Dict[str, Any]:
        """差量计算（PROG-02；委托模块级 shortfall）。"""
        return shortfall(node_holdings)

    def progress_line(
        self,
        node_holdings: Mapping[str, Mapping[str, Any]],
        forged_prefix_names: Sequence[str] = (),
    ) -> str:
        """持有进度行（PROG-05 / §2.3 ✓ 标注；委托模块级 progress_line）。"""
        return progress_line(node_holdings, forged_prefix_names)

    def forge_readiness(
        self, ctx: Mapping[str, Any], player: object, node: object
    ) -> Dict[str, Any]:
        """满链推进度（PROG-01 / 2c2b §2.3；复用 self._tree.parent_forged）。"""
        return forge_readiness(ctx, player, node, tree=self._tree)
