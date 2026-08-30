"""M9 锻造·批1·路1A：派生树引擎（qbot_rpg/core/forge_tree.py）——ForgeTreeEngine。

文件名：qbot_rpg/core/forge_tree.py
创建时间：2026-08-30
作者：Hermes 子agent-1A（M9 锻造实现组批1·路1A：并发同仓，仅新建本文件 +
  tests/unit/test_forge_tree.py；不改动批0 forge_models.py/forge_settings.py 等既有文件）

功能描述：ForgeTreeEngine 承载锻造派生树的全部结构查询与守卫判定——
  树加载（load_trees）/ 遍历（children_of / branch_of / path_to_root / subtree_of）/
  可锻性判定（parent_forged / already_forged / node_level_met，供 /锻造 守卫 GU-03/04/06）/
  实例合并（merge_forge_instance 委托批0 merge_node_item，AR-1~5）/ 节点查找（resolve_node，
  2c2b §5.2 精确→唯一前缀→歧义列表）/ 最终强化（final_of / line_endpoint）。
  纯函数零 IO 零 NoneBot；返回 dict 结果与 bool 判定，不抛异常；
  构造器配置注入 + 缺省默认值兜底（对齐 synthesis.py）。

依据：
  - docs/细化/细化_2c2a_锻造派生树schema.md：§二（派生树结构：父→子/多线分支/■最终强化）、
    §1.2（N-01~15 节点字段）、§1.3（AR-1~5 双源仲裁）、§1.4（S-01~05 settings）、
    §五（V1~V16 校验规则，拓扑语义来源）、§六（TC-01~27）。
  - 定稿 §12.1（节点）/ §12.1.1（双源仲裁）——细化 2c2a 的定稿行号依据。
  - docs/细化/细化_2c2b_锻造流程契约.md：§1.1（GU-03 节点存在/可锻、GU-04 前置已锻、
    GU-06 等级足够）、§五 5.2（匹配算法：精确→唯一前缀→歧义列表）、P-04（■ 输入可省略）。
  - docs/m9_shared_contract.md：§一~§三（ForgeTree/ForgeNode/MaterialReq/ForgeSettings 字段表）、
    §二（派生树拓扑）、AR-1~5（双源仲裁）、§十（M8 坑位：零定时器探针）。
  - docs/m9_接口摸底.md：§四（熟练度多职业承载：player["proficiency"]["forge"]）、
    §二（装备实例快照：merge 产物入档归本路）。
  - 模式参考：qbot_rpg/core/synthesis.py（构造器配置注入 + 缺省兜底 + ctx 契约）、
    qbot_rpg/core/alchemy_core.py（引擎模块形态：常量 + 类 + __all__）。
  - 复用批0：qbot_rpg/content/forge_models.py（ForgeTree/ForgeNode + merge_node_item——
    本文件只委托不重写其 AR-1~5 合并语义）；forge_settings.py（read_forge_settings 读段）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x；不得新增定稿外机制行为）：
  F-1  已锻造集合落点：player["forged"]（list/set/tuple of 节点 id 或节点名；None/缺失/非集合
       → 空集合，确定性兜底）。契约未指定已锻造集合的存档键，本引擎按 player["forged"] 读取；
       批4 /锻造 成功路径向 player["forged"] 追加产物节点 id。图鉴 codex 由装配层另行点亮，
       本引擎不读写（零 IO）。
  F-2  玩家铸造职业等级读取：player["proficiency"]["forge"]["level"]（铸造职业 id = "forge"，
       对齐 m9_接口摸底 §四；缺失/非非负整数 → 0，确定性兜底）。等级门槛 = 职业等级 ≥
       node.level（GU-06 / 2c2a N-05「可锻造节点等级上限=职业等级」）。
  F-3  line_endpoint 主线选择：沿 children（文件序）向下，优先走「不在本节点 branch 列表的 child」
       作为主线；branch 指向的 child 是「本线可转出的其他线」（2c2a N-07），不参与主线延伸。
       无 branch 标注 → 全部 children 视为主线。叶子非 final（数据缺陷，V6 应拦）→ 保守返回
       自身，不抛异常。
  F-4  resolve_node 名称归一：节点名可能带前导 ■（P-04，如「■炎王剑」）——精确/前缀匹配均先
       去除 ■ 后比较（含 key 亦去除）；罗马数字/括号按普通字符参与（P-03）。key 含空格 →
       not_found（名禁空格由指令壳 P-01 校验，引擎只做匹配不做校验，空格无候选命中）。
  F-5  merge_forge_instance 为薄封装：委托批0 merge_node_item（其已满足 AR-1 覆盖 / AR-2 追加 /
       AR-3 品质 / AR-4 配置模式），仅补 AR-5 快照缺省键（stats/slots/rarity/final/augmentable/
       monster_source 齐备，未声明键取契约缺省），供批4 实例化入档零缺失。不改写合并语义。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；不写定时器/睡眠调用（M43 零定时器探针）；
      平台无关；不引入随机；每功能可追溯（文件头标注依据）。
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Set, cast

from qbot_rpg.content.forge_models import (
    ForgeNode,
    ForgeSettings,
    ForgeTree,
    merge_node_item,
)
from qbot_rpg.content.forge_settings import FORGE_SETTINGS_KEYS, read_forge_settings

__all__ = [
    "FORGE_JOB_ID",
    "ForgeTreeEngine",
    "match_name",
]


# 铸造职业 id（m9_接口摸底 §四：proficiency.json 加 forge 实例；玩家 proficiency 键）
FORGE_JOB_ID: str = "forge"


def match_name(value: object) -> str:
    """节点名/输入 key 归一（【工程补白 F-4】）：去除前导 ■ 显示标记（P-04）并 strip 空白。

    罗马数字/括号按普通字符保留（P-03「普通字符参与匹配」）。纯函数确定性。
    """
    if not isinstance(value, str):
        return ""
    return value.replace("■", "").strip()


# =====================================================================================
# ForgeTreeEngine：锻造派生树引擎（构造器配置注入 + 缺省兜底）
# =====================================================================================
class ForgeTreeEngine:
    """锻造派生树引擎（细化_2c2a §二 拓扑 / §1.3 双源仲裁 + 2c2b §1.1 守卫 / §5.2 匹配）。

    构造器注入 forge raw dict / items 表 / settings，缺省默认值兜底（对齐 synthesis.py）；
    纯函数确定性，返回 dict 结果与 bool 判定，不抛异常；零 IO 零 NoneBot。
    """

    def __init__(
        self,
        forge: Optional[Mapping[str, object]] = None,
        items: Optional[object] = None,
        settings: Optional[Mapping[str, object]] = None,
    ) -> None:
        """构造派生树引擎（配置注入 + 缺省兜底）。

        入参：
          - forge：forge.json 顶层 raw dict（Mapping；含 trees / settings）。None/非 Mapping → {}。
          - items：items 表（id→条目 Mapping，或条目 list/tuple；供 item_of 解析 node.item）。
            None/空 → 空表（merge_forge_instance 的 items_def 由调用方显式传入，不依赖此表）。
          - settings：settings dict（含 forge 段）或 forge 段本身；None → 回退 forge["settings"]，
            再回退全部默认值。归一口径复用批0 read_forge_settings。
        """
        self._forge: Mapping[str, object] = forge if isinstance(forge, Mapping) else {}
        self._items: Dict[str, Mapping[str, object]] = self._norm_items(items)
        self._settings: Dict[str, object] = self._resolve_settings(settings)

        self._trees: List[ForgeTree] = []
        self._nodes: Dict[str, ForgeNode] = {}
        self._children: Dict[str, List[str]] = {}
        self._node_tree: Dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------
    # 构造辅助（纯函数，缺省兜底）
    # ------------------------------------------------------------------
    @staticmethod
    def _norm_items(items: object) -> Dict[str, Mapping[str, object]]:
        """items 表归一：Mapping（id→条目）或条目 list/tuple → {id: 条目}。"""
        out: Dict[str, Mapping[str, object]] = {}
        if isinstance(items, Mapping):
            for k, v in items.items():
                if isinstance(v, Mapping):
                    out[str(k)] = v
            return out
        if isinstance(items, (list, tuple)):
            for e in items:
                if isinstance(e, Mapping) and isinstance(e.get("id"), str):
                    out[e["id"]] = e
            return out
        return out

    def _resolve_settings(self, settings: Optional[Mapping[str, object]]) -> Dict[str, object]:
        """settings 归一（S-01~05 + 2c2d 补白键；缺省默认值兜底，复用 read_forge_settings）。

        优先级：① 显式 settings（含 forge 段）→ 取段；② 显式 settings 本身是 forge 段
        （含 FORGE_SETTINGS_KEYS 任一键）→ 包层取段；③ forge raw["settings"] 段；
        ④ 全默认值兜底（read_forge_settings(None)）。
        """
        if isinstance(settings, Mapping):
            seg = settings.get("forge")
            if isinstance(seg, Mapping):
                return read_forge_settings(settings)
            if any(k in settings for k in FORGE_SETTINGS_KEYS):
                return read_forge_settings({"forge": settings})
            return read_forge_settings(settings)
        seg = self._forge.get("settings")
        if isinstance(seg, Mapping):
            return read_forge_settings({"forge": seg})
        return read_forge_settings(None)

    def _load(self) -> None:
        """加载派生树：forge.trees → ForgeTree/ForgeNode + parent→child 反向索引 + 所属树映射。

        确定性：树序 = forge.trees 文件序；节点序 = 树内 nodes 文件序；children 保持父节点内
        子节点文件序。节点 id 跨树全局索引（契约 V2 节点 id 全文件唯一）。畸形条目跳过。
        """
        trees_raw = self._forge.get("trees")
        if not isinstance(trees_raw, (list, tuple)):
            return
        for t in trees_raw:
            if not isinstance(t, Mapping):
                continue
            tree = cast(ForgeTree, ForgeTree.from_entry(t))
            self._trees.append(tree)
            tree_id = tree.id
            for node in tree.node_defs():
                nid = node.id
                if not nid:
                    continue
                self._nodes[nid] = node
                self._node_tree[nid] = tree_id
                parent = node.parent
                if parent:
                    self._children.setdefault(parent, []).append(nid)

    # ------------------------------------------------------------------
    # 配置读取（构造器单源 + 缺省兜底）
    # ------------------------------------------------------------------
    def forge_raw(self) -> Mapping[str, object]:
        """forge.json 顶层 raw（只读镜像，构造器注入原样）。"""
        return self._forge

    def settings(self) -> Mapping[str, object]:
        """归一后的 forge settings 段（S-01~05 + 2c2d 补白键；read_forge_settings 合并默认）。"""
        return self._settings

    def forge_settings(self) -> ForgeSettings:
        """ForgeSettings dataclass 视图（批0；from_entry 兜底缺省值）。"""
        return ForgeSettings.from_entry(self._settings)

    # ------------------------------------------------------------------
    # 树加载与遍历（T2/T3；纯函数确定性）
    # ------------------------------------------------------------------
    def load_trees(self) -> List[ForgeTree]:
        """解析 forge.trees → ForgeTree 列表（文件序；空 → []）。"""
        return list(self._trees)

    def nodes(self) -> List[ForgeNode]:
        """全部节点（跨树，文件序）。"""
        return list(self._nodes.values())

    def node(self, node_id: str) -> Optional[ForgeNode]:
        """按节点 id 查 ForgeNode（无 → None）。"""
        return self._nodes.get(node_id)

    def tree_of(self, node_id: str) -> Optional[ForgeTree]:
        """节点所属树（ForgeTree；无 → None）。"""
        tid = self._node_tree.get(node_id)
        if tid is None:
            return None
        for t in self._trees:
            if t.id == tid:
                return t
        return None

    def children_of(self, node_id: str) -> List[str]:
        """父→子反向索引：parent == node_id 的全部子节点 id（文件序；无 → []）。"""
        return list(self._children.get(node_id, []))

    def branch_of(self, node_id: str) -> List[str]:
        """节点 branch 列表（N-07 本线可转出的其他线；文件序；无/未声明 → []）。"""
        node = self._nodes.get(node_id)
        return list(node.branch) if node is not None else []

    def path_to_root(self, node_id: str) -> List[str]:
        """沿 parent 链到根：返回根在前、含自身的节点 id 链（根→…→node；无 → []）。

        确定性：逐级 parent 上溯；成环/悬空保守截断（seen 防环）。供 /图纸 主链（2c2b §2.2）。
        """
        node = self._nodes.get(node_id)
        if node is None:
            return []
        chain: List[str] = []
        seen: Set[str] = set()
        cur: Optional[ForgeNode] = node
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            chain.append(cur.id)
            pid = cur.parent
            cur = self._nodes.get(pid) if pid else None
        chain.reverse()
        return chain

    def subtree_of(self, node_id: str) -> List[str]:
        """子树全节点（含自身 + 全部子孙，含分支 child）：DFS 文件序（确定性）。

        供 级联删除预览 / 图鉴树 等消费（2c2a §12.1.2 级联语义）；含分支（N-07）。
        """
        node = self._nodes.get(node_id)
        if node is None:
            return []
        out: List[str] = []
        seen: Set[str] = set()
        stack: List[str] = [node_id]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            out.append(cur)
            # 子节点逆序入栈 → 文件序出栈（确定性）
            for c in reversed(self.children_of(cur)):
                if c not in seen:
                    stack.append(c)
        return out

    # ------------------------------------------------------------------
    # 可锻性判定（供 /锻造 守卫 GU-03/04/06；2c2b §1.1）
    # ------------------------------------------------------------------
    @staticmethod
    def _forged_set(player: object) -> Set[str]:
        """已锻造集合读取（【工程补白 F-1】player["forged"]，list/set/tuple 兼容）。

        元素为节点 id 或节点名；None/缺失/非集合 → 空集合（确定性兜底）。
        """
        if not isinstance(player, Mapping):
            return set()
        v = player.get("forged")
        if isinstance(v, (set, frozenset, list, tuple)):
            return {str(x) for x in v}
        if isinstance(v, Mapping):
            return {str(k) for k in v if v[k]}
        return set()

    @staticmethod
    def _forge_level(player: object) -> int:
        """玩家铸造职业等级（【工程补白 F-2】player["proficiency"]["forge"]["level"]）。

        缺失/非非负整数 → 0（确定性兜底）；铸造职业 id = FORGE_JOB_ID。
        """
        if not isinstance(player, Mapping):
            return 0
        prof = player.get("proficiency")
        if not isinstance(prof, Mapping):
            return 0
        fnode = prof.get(FORGE_JOB_ID)
        if not isinstance(fnode, Mapping):
            return 0
        lv = fnode.get("level")
        if isinstance(lv, int) and not isinstance(lv, bool) and lv >= 0:
            return lv
        return 0

    def parent_forged(self, player: object, node_id: str) -> bool:
        """前置已锻判定（GU-04）：沿 parent 链上全部父节点 ∈ 玩家已锻造集合。

        根节点（无 parent）→ True（无前置）。node_id 不存在 → False（保守拒绝）。
        """
        node = self._nodes.get(node_id)
        if node is None:
            return False
        forged = self._forged_set(player)
        pid = node.parent
        while pid:
            if pid not in forged:
                return False
            pnode = self._nodes.get(pid)
            if pnode is None:
                return False  # 悬空 parent（数据缺陷，V3 应拦）→ 保守拒绝
            pid = pnode.parent
        return True

    def already_forged(self, player: object, node_id: str) -> bool:
        """已锻造判定：node_id ∈ 玩家已锻造集合（防重复锻造）。"""
        return node_id in self._forged_set(player)

    def node_level_met(self, player: object, node_id: str) -> bool:
        """节点等级门槛（GU-06 / 2c2a N-05）：铸造职业等级 ≥ node.level。

        node.level 非正整数（缺失/0/负，V12 应拦）→ 保守拒绝 False（对齐 synthesis 补白 12）。
        """
        node = self._nodes.get(node_id)
        if node is None:
            return False
        lv = node.level
        if not isinstance(lv, int) or isinstance(lv, bool) or lv <= 0:
            return False
        return self._forge_level(player) >= lv

    def forge_guard(self, player: object, key: object) -> dict:
        """组合守卫（GU-03→04→06 顺序 + 已锻拦截）：供 /锻造 指令壳一次判定。

        出参：{ok, reason, node?, node_id?, resolve?}；拒绝 reason ∈
          not_found / ambiguous / already_forged / parent_not_forged / level_insufficient。
        素材守卫（GU-05）与金币/材料扣减归批4 指令壳（本引擎纯判定）。
        """
        res = self.resolve_node(key)
        if not res["ok"]:
            return {"ok": False, "reason": str(res.get("match", "not_found")),
                    "node": None, "node_id": None, "resolve": res}
        nid = res["node_id"]
        node = res["node"]
        assert nid is not None and node is not None
        if self.already_forged(player, nid):
            return {"ok": False, "reason": "already_forged", "node": node, "node_id": nid}
        if not self.parent_forged(player, nid):
            return {"ok": False, "reason": "parent_not_forged", "node": node, "node_id": nid}
        if not self.node_level_met(player, nid):
            return {"ok": False, "reason": "level_insufficient", "node": node, "node_id": nid}
        return {"ok": True, "reason": None, "node": node, "node_id": nid}

    # ------------------------------------------------------------------
    # 装备实例合并生成（T12 前半；委托批0 merge_node_item，AR-1~5）
    # ------------------------------------------------------------------
    def merge_forge_instance(
        self,
        items_def: Mapping[str, object],
        node: object,
    ) -> Dict[str, object]:
        """装备实例合并生成（AR-1~5）：items 基础 + 节点改造 → 属性快照 dict。

        委托批0 merge_node_item（其已满足 AR-1 覆盖 / AR-2 追加 / AR-3 品质 / AR-4 配置模式），
        薄封装补齐 AR-5 快照缺省键——stats/slots/rarity/final/augmentable/monster_source
        全部齐备（未声明键取契约缺省：slots=[] / final=False / augmentable=False /
        monster_source=None / rarity=None），供批4 /锻造 成功路径实例化入档零缺失
        （【工程补白 F-5】）。深拷贝输出，不改写入参。
        """
        out = merge_node_item(items_def, node)
        out.setdefault("stats", {})
        out.setdefault("slots", [])
        out.setdefault("rarity", None)
        out.setdefault("final", False)
        out.setdefault("augmentable", False)
        out.setdefault("monster_source", None)
        return out

    def item_of(self, node: object) -> Optional[Mapping[str, object]]:
        """节点产物装备条目（N-03 node.item/output_item → items 表条目；无 → None）。

        node 可为 ForgeNode 或 raw dict；items 表为构造器注入（V7 引用解析的引擎侧便利）。
        """
        raw: Mapping[str, object] = node.raw if isinstance(node, ForgeNode) else (
            node if isinstance(node, Mapping) else {}
        )
        item_ref = raw.get("item") or raw.get("output_item")
        if not isinstance(item_ref, str) or not item_ref:
            return None
        return self._items.get(item_ref)

    # ------------------------------------------------------------------
    # 节点查找（2c2b §5.2 匹配算法：精确 → 唯一前缀 → 歧义列表）
    # ------------------------------------------------------------------
    def resolve_node(self, key: object) -> dict:
        """节点查找（2c2b §5.2）：节点 id / 中文名匹配，三态返回。

        匹配算法（确定性）：
          1) 精确：key == node.id 或 match_name(node.name) == match_name(key)（■ 去除后）。
             含 ■ 的 key（如「■炎王剑」）按 P-04 精确命中；「炎剑」精确命中 炎剑 不吞
             炎剑Ⅱ（P-03）。
          2) 唯一前缀：无精确命中时，恰一节点 match_name(name) 以 match_name(key) 开头 → 命中。
          3) 歧义：多候选 → {ok:False, match:"ambiguous", candidates:[node_id...]}；
             零候选 → {ok:False, match:"not_found"}。
          名禁空格由指令壳 P-01 校验，引擎不做校验；key 含空格直接 not_found（无候选命中）。

        出参：{ok, match, node_id?, node?, candidates?}。
        """
        if not isinstance(key, str):
            return {"ok": False, "match": "not_found", "node_id": None, "node": None,
                    "candidates": []}
        k = match_name(key)
        if not k or any(ch.isspace() for ch in k):
            return {"ok": False, "match": "not_found", "node_id": None, "node": None,
                    "candidates": []}

        # 1) 精确：id 精确（原文）或 name 精确（归一后）
        for nid, node in self._nodes.items():
            if nid == key or (node.name and match_name(node.name) == k):
                return {"ok": True, "match": "exact", "node_id": nid, "node": node,
                        "candidates": []}

        # 2) 唯一前缀 / 3) 歧义（name 归一后 startswith；文件序）
        hits: List[ForgeNode] = [
            n for n in self._nodes.values() if n.name and match_name(n.name).startswith(k)
        ]
        if len(hits) == 1:
            node = hits[0]
            return {"ok": True, "match": "prefix", "node_id": node.id, "node": node,
                    "candidates": []}
        if len(hits) > 1:
            return {"ok": False, "match": "ambiguous", "node_id": None, "node": None,
                    "candidates": [n.id for n in hits]}
        return {"ok": False, "match": "not_found", "node_id": None, "node": None,
                "candidates": []}

    # ------------------------------------------------------------------
    # 最终强化查询（2c2a §2.2 ■最终强化 / V6）
    # ------------------------------------------------------------------
    def final_of(self, tree: object) -> List[str]:
        """树中 final=true 节点 id 列表（该树线终点 ■；文件序）。

        tree 可为 ForgeTree / tree id（str） / tree raw dict（Mapping 含 id）；
        未识别 → []（确定性兜底）。
        """
        if isinstance(tree, ForgeTree):
            tid: Optional[str] = tree.id
        elif isinstance(tree, str):
            tid = tree
        elif isinstance(tree, Mapping):
            v = tree.get("id")
            tid = v if isinstance(v, str) else None
        else:
            tid = None
        return [nid for nid, node in self._nodes.items()
                if self._node_tree.get(nid) == tid and node.is_final is True]

    def line_endpoint(self, node_id: str) -> Optional[str]:
        """所在线终点（■最终强化节点 id；无 → None）。

        【工程补白 F-3】沿 children（文件序）向下走主线：优先走「不在本节点 branch 列表的 child」
        （branch = 本线可转出的其他线，2c2a N-07）；无 branch 标注 → 全部 children 视为主线；
        遇 final=true 返回；叶子非 final（数据缺陷）→ 保守返回自身。防环（seen）。
        """
        node = self._nodes.get(node_id)
        if node is None:
            return None
        cur = node
        seen: Set[str] = set()
        while cur.id not in seen:
            seen.add(cur.id)
            if cur.is_final is True:
                return cur.id
            children = self.children_of(cur.id)
            branch = set(cur.branch)
            main = [c for c in children if c not in branch] or list(children)
            if not main:
                return cur.id  # 叶子且非 final（数据缺陷）→ 保守返回自身
            nxt = self._nodes.get(main[0])
            if nxt is None:
                return cur.id
            cur = nxt
        return cur.id
