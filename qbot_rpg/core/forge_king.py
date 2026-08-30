"""M9 锻造·批3·路3C：铸造王（qbot_rpg/core/forge_king.py）——图鉴全亮判定/授予/守卫/称号加成。

文件名：qbot_rpg/core/forge_king.py
创建时间：2026-08-30
作者：Hermes 子agent-3C（M9 锻造实现组批3·路3C：并发同仓，仅新建本文件 +
  tests/unit/test_forge_king.py；不改动批0~批2 既有文件、不改 fixtures）

功能描述：铸造王（KF-01~03，2c2d §3.3）全流程的引擎侧服务，供装配层 /锻造 图鉴点亮
  即时结算 / 专属配方守卫 / 称号加成消费：
  1) codex_all_lit(ctx)：装备图鉴全亮判定（KF-01 查询口径：派生树全部节点 ∈ 玩家已锻造
     集合；经 codex weapon 分册统计；返回 {all_lit, lit_count, total, codex}）
  2) king_eligible(player, ctx)：铸造王资格（KF-01：图鉴全亮 → eligible；与等级解耦——
     等级到王但图鉴未亮不授予）
  3) grant_forge_king(player, ctx)：委托 ProficiencyEngine.grant_king_title(player,
     "forge", codex_all_lit=...) 即时结算铸造王称号（TTL-03 id=职业 ID）
  4) king_only_nodes(forge)：派生树内 king_only=true 节点 id 列表（KF-02 ① 专属配方；
     校验器已查 level≥7，N-16）
  5) king_bonus(settings)：称号加成（KF-02 ② 全属性+X% 可配，settings.forge 可配键，
     缺省 5% 示例；进 4b 加成层 pct）
  6) forge_king_eligible_check(player, ctx, node)：锻造 king_only 节点前置守卫（KF-02 ①：
     未获铸造王 → /锻造 拒绝「未获铸造王」）
  纯函数零 IO 零 NoneBot；返回 dict 结果与 bool 判定，不抛异常；构造器配置注入 +
  缺省默认值兜底（对齐 forge_progress / synthesis 模式）。

依据：
  - docs/细化/细化_2c2d_锻造套装与客制.md §3.3（KF-01~03：图鉴全亮→铸造王 + 专属配方
    king_only 节点 + 称号加成 + 群内展示；N-16 king_only 节点扩展）+ §3.3 KF 表
  - 【锻造定稿】§10.2（L219-223：图鉴全亮 L221 / 专属配方+称号加成+群内展示 L222 /
    与其他王并行 L223）
  - docs/细化/细化_2c5a_职业等级与SP.md §四 TTL-01~08（TTL-01 王称号图鉴全亮按职业独立
    授予、与等级区间解耦；TTL-03 id=职业 ID 自动生成；TTL-06 [称号] 前缀渲染；TTL-08
    title_state 存档）
  - docs/细化/细化_2c2b_锻造流程契约.md §4.4（铸造王称号：查询口径=派生树全部节点 ∈
    玩家已锻造集合）
  - docs/m9_接口摸底.md §三（codex weapon 分册 = equipment kind 已登记，mark_seen/
    codex_progress 可直接用；铸造王判定数据源就位）+ §四（grant_king_title 铸造王称号
    已有引擎支持）
  - 复用批1/批0：qbot_rpg/core/forge_tree.py（ForgeTreeEngine + FORGE_JOB_ID）、
    qbot_rpg/core/proficiency.py（ProficiencyEngine.grant_king_title / owned_titles）、
    qbot_rpg/core/codex.py（codex_progress 分册统计）、qbot_rpg/content/forge_models.py
    （ForgeNode）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x；不得新增定稿外机制行为）：
  F-1  图鉴全亮判定数据源：主判定 = 派生树全部节点 ∈ 玩家已锻造集合（2c2b §4.4 查询口径，
      玩家 forged 集合为真源）；codex weapon 分册（codex_progress(ctx,"weapon")）作为
      旁路统计随返回附带（m9_接口摸底 §三「走 codex weapon 分册或已锻造快照集合统计」
      两口径之一，本实现以 forged 快照集合为判定真源、codex 分册为可核对信息）。无
      registry（裸 ctx）→ codex 分册 total=0（codex 引擎 fail-safe），不影响 forged 主判定。
  F-2  已锻造集合落点：player["forged"]（list/set/tuple of 节点 id/名；None/缺失/非集合
      → 空集合确定性兜底），对齐 forge_tree._forged_set 口径；ctx["player"] 缺省回退 ctx
      自身（ctx 直带 forged 键也可）。
  F-3  派生树节点 id 提取：ctx["forge_tree"]=ForgeTreeEngine → nodes()；回退 ctx["forge"]
      为 ForgeTreeEngine 或 forge raw dict（含 trees）→ 逐节点 id（文件序，全局唯一 V2）。
  F-4  grant_forge_king 委托 ProficiencyEngine.grant_king_title(player, FORGE_JOB_ID,
      codex_all_lit=...)：title id = "forge"（TTL-03 职业 ID 自动生成）；已拥有 → 幂等
      granted=False；图鉴未全亮 → {ok:False, reason:"codex_incomplete"}（TTL-01/TC-20）。
  F-5  king_only_nodes 返回节点 id 字符串列表（文件序；forge 为 ForgeTreeEngine 或 forge
      raw dict 双形态）。
  F-6  king_bonus 可配键 settings.forge.king_bonus_pct（百分比数值，缺省 5.0=5% 示例）；
      返回 {key, percent, pct, enabled}——pct=percent/100（4b 加成层 pct 消费形态，
      KF-02 ②「全属性+X%」）；settings 可为全量 settings dict（含 forge 段）或 forge
      段本身。
  F-7  forge_king_eligible_check 的 node 三形态（ForgeNode / raw dict / 节点 id str）：
      id str 需 ctx 含 forge 树可解析；非 king_only 节点 → 守卫不适用 {ok:True}（KF-02 ①
      只拦专属配方）；king_only 且 player 无「铸造王」称号 → {ok:False,
      reason:"king_title_required"}（指令层文案「未获铸造王」）。
  F-8  铸造王称号 id = FORGE_JOB_ID（"forge"，与 proficiency 铸造职业实例 id 同键，
      TTL-03 id=职业 ID）。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；不写定时器/睡眠调用（M43 零定时器
      探针）；平台无关；不引入随机；每功能可追溯（文件头标注依据）。
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.content.forge_models import ForgeNode
from qbot_rpg.core.codex import codex_progress
from qbot_rpg.core.forge_tree import FORGE_JOB_ID, ForgeTreeEngine
from qbot_rpg.core.proficiency import ProficiencyEngine

__all__ = [
    "FORGE_KING_BONUS_DEFAULT",
    "FORGE_KING_BONUS_KEY",
    "KING_TITLE_ID",
    "codex_all_lit",
    "forge_king_eligible_check",
    "grant_forge_king",
    "king_bonus",
    "king_eligible",
    "king_only_nodes",
]

# 铸造王称号 id = 铸造职业 id（TTL-03：王称号条目 id = 职业 ID；F-8）
KING_TITLE_ID: str = FORGE_JOB_ID

# 称号加成可配键（KF-02 ②：settings.forge.king_bonus_pct，百分比数值；F-6）
FORGE_KING_BONUS_KEY: str = "king_bonus_pct"
# 称号加成缺省值（KF-02 ② 示例：全属性+5%）
FORGE_KING_BONUS_DEFAULT: float = 5.0


# ---------------------------------------------------------------------------
# ctx / player 基础工具（纯函数，缺省兜底；F-2/F-3）
# ---------------------------------------------------------------------------
def _player_of(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """ctx 中玩家表示（F-2）：ctx["player"] 优先，缺失回退 ctx 自身。"""
    p = ctx.get("player")
    return p if isinstance(p, Mapping) else ctx


def _forged_set(player: Mapping[str, Any]) -> set:
    """玩家已锻造集合（F-2：player["forged"]，list/set/tuple/Mapping 兼容）。"""
    v = player.get("forged")
    if isinstance(v, (set, frozenset, list, tuple)):
        return {str(x) for x in v}
    if isinstance(v, Mapping):
        return {str(k) for k in v if v[k]}
    return set()


def _iter_raw_nodes(forge_raw: Mapping[str, Any]) -> Iterator[Tuple[str, Mapping[str, Any]]]:
    """forge raw dict → (节点 id, 节点 dict) 迭代（文件序；F-3）。"""
    trees = forge_raw.get("trees")
    if not isinstance(trees, (list, tuple)):
        return
    for t in trees:
        if not isinstance(t, Mapping):
            continue
        nodes = t.get("nodes")
        if not isinstance(nodes, (list, tuple)):
            continue
        for e in nodes:
            if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
                yield e["id"], e


def _tree_node_ids(ctx: Mapping[str, Any]) -> List[str]:
    """派生树全部节点 id（文件序；F-3：ForgeTreeEngine / forge raw dict 双形态）。"""
    ft = ctx.get("forge_tree")
    if isinstance(ft, ForgeTreeEngine):
        return [n.id for n in ft.nodes() if n.id]
    forge = ctx.get("forge")
    if isinstance(forge, ForgeTreeEngine):
        return [n.id for n in forge.nodes() if n.id]
    if isinstance(forge, Mapping):
        return [nid for nid, _ in _iter_raw_nodes(forge)]
    trees = ctx.get("trees")
    if isinstance(trees, (list, tuple)):
        return [nid for nid, _ in _iter_raw_nodes({"trees": trees})]
    return []


# ---------------------------------------------------------------------------
# 1) codex_all_lit：装备图鉴全亮判定（KF-01 / 2c2b §4.4 查询口径）
# ---------------------------------------------------------------------------
def _all_lit_of(player: Mapping[str, Any], ctx: MutableMapping[str, Any]) -> Dict[str, Any]:
    """装备图鉴全亮判定核心（player 显式传入；供 codex_all_lit/king_eligible/
    grant_forge_king 三处复用，口径单一 F-1/F-2）。

    入参 player：玩家 dict（forged 集合真源）；ctx：派生树 + codex 统计。
    出参 dict：{all_lit, lit_count, total, codex}——
      - total：派生树全部节点数（分母）
      - lit_count：其中 ∈ 玩家已锻造集合的节点数
      - all_lit：total>0 且 lit_count==total（图鉴全亮）
      - codex：codex_progress(ctx,"weapon") 分册旁路统计（{total, seen, killed, pct}；
        无 registry → 各 0，不影响 forged 主判定）
    纯函数确定性；零 IO 零 NoneBot。
    """
    node_ids = _tree_node_ids(ctx)
    forged = _forged_set(player)
    total = len(node_ids)
    lit_count = sum(1 for nid in node_ids if nid in forged)
    all_lit = total > 0 and lit_count == total
    # codex weapon 分册旁路统计（F-1）：无 registry → codex 引擎 fail-safe total=0
    if hasattr(ctx.get("registry"), "all_ids"):
        codex = codex_progress(ctx, "weapon")
    else:
        codex = {"total": 0, "seen": 0, "killed": 0, "pct": 0.0}
    return {
        "all_lit": all_lit,
        "lit_count": lit_count,
        "total": total,
        "codex": codex,
    }


def codex_all_lit(ctx: MutableMapping[str, Any]) -> Dict[str, Any]:
    """装备图鉴全亮判定（KF-01 查询口径 2c2b §4.4 + codex weapon 分册统计，F-1）。

    入参 ctx：含玩家（ctx["player"] 或 ctx 直带 forged）+ 派生树（ctx["forge_tree"]=
      ForgeTreeEngine 或 ctx["forge"]=ForgeTreeEngine / forge raw dict）+ 可选
      ctx["registry"]（供 codex weapon 分册统计）。
    出参 dict：{all_lit, lit_count, total, codex}——见 _all_lit_of。
    纯函数确定性；零 IO 零 NoneBot。
    """
    return _all_lit_of(_player_of(ctx), ctx)


# ---------------------------------------------------------------------------
# 2) king_eligible：铸造王资格（KF-01：图鉴全亮 → eligible；与等级解耦）
# ---------------------------------------------------------------------------
def king_eligible(player: Mapping[str, Any], ctx: MutableMapping[str, Any]) -> Dict[str, Any]:
    """铸造王资格判定（KF-01 / TTL-01：图鉴全亮 → eligible；与等级解耦）。

    入参 player：玩家 dict（含 forged 集合；proficiency.forge.level 仅供展示，不参与
      判定——等级到王但图鉴未亮不授予，TTL-01）；ctx：派生树 + codex 统计。
    出参 dict：{eligible, all_lit, lit_count, total, has_title, reason}——
      - eligible：图鉴全亮（KF-01）
      - has_title：title_state.owned 是否已含 铸造王
      - reason：未全亮 → "codex_incomplete"；已全亮 → None
    纯函数确定性；零 IO 零 NoneBot。
    """
    lit = _all_lit_of(player, ctx)
    all_lit = bool(lit["all_lit"])
    return {
        "eligible": all_lit,
        "all_lit": all_lit,
        "lit_count": int(lit["lit_count"]),
        "total": int(lit["total"]),
        "has_title": _has_king_title(player),
        "reason": None if all_lit else "codex_incomplete",
    }


# ---------------------------------------------------------------------------
# 3) grant_forge_king：委托 ProficiencyEngine 即时结算铸造王称号（KF-01 / TTL-01~03）
# ---------------------------------------------------------------------------
def grant_forge_king(player: Mapping[str, Any], ctx: MutableMapping[str, Any]) -> Dict[str, Any]:
    """铸造王称号即时结算（KF-01 / TTL-01~03，F-4）。

    入参 player：玩家 dict（就地改写 title_state.owned）；ctx：派生树 + codex 统计。
    流程：codex_all_lit(ctx) → 委托 ProficiencyEngine().grant_king_title(player,
      "forge", codex_all_lit=all_lit) 即时落账（TTL-03 自动生成 title id="forge"）。
    出参 dict：{ok, granted, title_id, reason, all_lit, lit_count, total}——
      - 图鉴全亮 → granted=True 授「铸造王」；已拥有 → 幂等 granted=False
      - 图鉴未全亮 → {ok:False, reason:"codex_incomplete"}（TTL-01/TC-20 反例同构）
    纯函数确定性（对 ctx 零改写；player.title_state 由 proficiency 引擎落账）；
    零 IO 零 NoneBot。
    """
    lit = _all_lit_of(player, ctx)
    all_lit = bool(lit["all_lit"])
    eng = ProficiencyEngine()
    res = eng.grant_king_title(player, KING_TITLE_ID, codex_all_lit=all_lit)
    return {
        "ok": bool(res.get("ok")),
        "granted": bool(res.get("granted")),
        "title_id": res.get("title_id"),
        "reason": res.get("reason"),
        "all_lit": all_lit,
        "lit_count": int(lit["lit_count"]),
        "total": int(lit["total"]),
    }


# ---------------------------------------------------------------------------
# 4) king_only_nodes：派生树内 king_only=true 节点 id 列表（KF-02 ① / N-16）
# ---------------------------------------------------------------------------
def king_only_nodes(forge: object) -> List[str]:
    """派生树内 king_only=true 节点 id 列表（KF-02 ① 专属配方；N-16）。

    入参 forge：ForgeTreeEngine 或 forge raw dict（含 trees）；节点 king_only=true
      为铸造王专属配方（校验器 V7 已查 level≥7，W3 黄）。
    出参：节点 id 列表（文件序，确定性）；无 king_only 节点 → []（fixtures 无该节点
      合法——守卫只在配置了 king_only 时生效，F-7）。
    纯函数确定性；零 IO 零 NoneBot。
    """
    if isinstance(forge, ForgeTreeEngine):
        return [n.id for n in forge.nodes()
                if n.id and n.king_only is True]
    if isinstance(forge, Mapping):
        return [nid for nid, e in _iter_raw_nodes(forge)
                if e.get("king_only") is True]
    return []


# ---------------------------------------------------------------------------
# 5) king_bonus：称号加成（KF-02 ② 全属性+X% 可配；进 4b 加成层 pct）
# ---------------------------------------------------------------------------
def _to_percent(value: object, default: float) -> float:
    """百分比数值归一（int/float/数字串；bool/非法 → 缺省；负 → 钳制 0）。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    if isinstance(value, str):
        try:
            return max(0.0, float(value.strip()))
        except ValueError:
            return default
    return default


def king_bonus(settings: object) -> Dict[str, Any]:
    """铸造王称号加成（KF-02 ②：全属性+X% 可配，进 4b 加成层 pct）。

    入参 settings：全量 settings dict（含 forge 段）或 forge 段本身（F-6）；
      可配键 settings.forge.king_bonus_pct（百分比数值，缺省 5.0=5% 示例）。
    出参 dict：{key, percent, pct, enabled}——
      - key：可配键名（FORGE_KING_BONUS_KEY）
      - percent：配置百分比（≥0；缺失/非法 → 缺省 5.0）
      - pct：percent/100（4b 加成层 pct 消费形态）
      - enabled：percent>0（是否生效）
    纯函数确定性；零 IO 零 NoneBot。
    """
    seg: object = settings
    if isinstance(settings, Mapping):
        f = settings.get("forge")
        if isinstance(f, Mapping):
            seg = f
    raw = seg.get(FORGE_KING_BONUS_KEY) if isinstance(seg, Mapping) else None
    percent = _to_percent(raw, FORGE_KING_BONUS_DEFAULT)
    return {
        "key": FORGE_KING_BONUS_KEY,
        "percent": percent,
        "pct": percent / 100.0,
        "enabled": percent > 0.0,
    }


# ---------------------------------------------------------------------------
# 6) forge_king_eligible_check：锻造 king_only 节点前置守卫（KF-02 ①）
# ---------------------------------------------------------------------------
def _has_king_title(player: Mapping[str, Any]) -> bool:
    """player 是否已拥有「铸造王」称号（TTL-08 title_state.owned 含 KING_TITLE_ID）。"""
    ts = player.get("title_state")
    if not isinstance(ts, Mapping):
        return False
    owned = ts.get("owned")
    if not isinstance(owned, (list, tuple, set)):
        return False
    return KING_TITLE_ID in {str(x) for x in owned}


def _node_king_only(ctx: Mapping[str, Any], node: object) -> Tuple[Optional[str], bool]:
    """节点 king_only 解析（F-7：ForgeNode / raw dict / 节点 id str 三形态）。

    返回 (node_id, is_king_only)；id str 需 ctx 含 forge 树可解析；未解析到节点 →
      (None, False)（守卫不适用，存在性由 forge_guard GU-03 另判）。
    """
    if isinstance(node, ForgeNode):
        return node.id, node.king_only is True
    if isinstance(node, Mapping):
        nid = node.get("id")
        return (nid if isinstance(nid, str) else None), node.get("king_only") is True
    if isinstance(node, str) and node:
        ft = ctx.get("forge_tree")
        if isinstance(ft, ForgeTreeEngine):
            nd = ft.node(node)
            if nd is not None:
                return node, nd.king_only is True
        forge = ctx.get("forge")
        if isinstance(forge, ForgeTreeEngine):
            nd = forge.node(node)
            if nd is not None:
                return node, nd.king_only is True
        if isinstance(forge, Mapping):
            for nid, e in _iter_raw_nodes(forge):
                if nid == node:
                    return node, e.get("king_only") is True
        return node, False
    return None, False


def forge_king_eligible_check(
    player: Mapping[str, Any], ctx: Mapping[str, Any], node: object
) -> Dict[str, Any]:
    """锻造 king_only 节点前置守卫（KF-02 ①：未获铸造王 → /锻造 拒绝「未获铸造王」）。

    入参：
      - player：玩家 dict（title_state.owned 判据）
      - ctx：派生树（ctx["forge_tree"]=ForgeTreeEngine 或 ctx["forge"]；供 id str 解析）
      - node：目标节点（ForgeNode / raw dict / 节点 id str；F-7 三形态）
    出参 dict：{ok, reason, node_id, king_only, has_title, message}——
      - 非 king_only 节点 → 守卫不适用 {ok:True, king_only:False}
      - king_only 且已获铸造王 → {ok:True, king_only:True, has_title:True}
      - king_only 且未获铸造王 → {ok:False, reason:"king_title_required",
        message:"未获铸造王", has_title:False}
    纯函数确定性；零 IO 零 NoneBot。
    """
    nid, king_only = _node_king_only(ctx, node)
    if not king_only:
        return {"ok": True, "reason": None, "node_id": nid, "king_only": False,
                "has_title": None, "message": None}
    has_title = _has_king_title(player)
    if not has_title:
        return {"ok": False, "reason": "king_title_required", "node_id": nid,
                "king_only": True, "has_title": False, "message": "未获铸造王"}
    return {"ok": True, "reason": None, "node_id": nid, "king_only": True,
            "has_title": True, "message": None}
