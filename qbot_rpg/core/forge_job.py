"""M9 锻造·批3·路3A：铸造职业门槛+熟练计价+经验明细（qbot_rpg/core/forge_job.py）。

文件名：qbot_rpg/core/forge_job.py
创建时间：2026-08-30
作者：Hermes 子agent-3A（M9 锻造实现组批3·路3A：并发同仓，仅新建本文件 +
  tests/unit/test_forge_job.py + 扩展 content/test_demo/proficiency.json 加 forge 实例；
  不改动批0/批1/批2 既有文件——proficiency.py/forge_tree.py/forge_material.py 只读消费）

功能描述：铸造职业（proficiency.json id="forge"）的纯函数判定与入账封装——
  1) FORGE_JOB_ID          铸造职业 id 常量（复用 forge_tree 单一真源）
  2) forge_prof_node       玩家 proficiency.forge 节点（缺省创建，对齐 proficiency dict 形态）
  3) forge_level           铸造职业等级（缺省 0=见习）
  4) level_gate_met        可锻节点上限=职业等级判定（L213，返回 need/current/missing）
  5) forge_exp_for         熟练经验计价 = 节点等级 × exp_per_forge（settings.forge，缺省 ×2）
  6) gain_forge_exp        委托 ProficiencyEngine.gain_prof_exp 入账（craft 来源，EXP-01）
  7) exp_to_next           经验明细查询（当前 exp / 本级阈值差 / 还差 N，供「还差 N 熟练」文案）
  8) rank_name             铸造职业档位名（tier_name：见习/正式/…/王）
  纯函数零 IO 零 NoneBot；返回 dict 结果不抛异常；确定性兜底。

依据：
  - docs/细化/细化_2c2d_锻造套装与客制.md §3.1（CAST 表：铸造每级解锁明细 见习1-5→王51+；
    硬门槛统一收敛为「可锻节点等级上限=职业等级」L213）
  - 定稿（锻造系统设计定稿 v1.0.1）§10.1 L213（可锻节点上限=职业等级）/ L214（熟练节点×2）
  - docs/细化/细化_2c5a_职业等级与SP.md：LVL-01~07（7 级链/tier_names/job_rank_levels）、
    EXP-01~07（craft 来源入账/倍率/判定链）——经 proficiency.py（批0 已实装）承接
  - docs/m9_shared_contract.md §三（ForgeSettings exp_per_forge：「节点等级×2」缺省）/
    §二（ForgeNode level 字段：职业门槛）
  - docs/m9_接口摸底.md §四（player["proficiency"]["forge"] 多职业承载）
  - content/test_demo/proficiency.json（forge 实例：本路新增）

模式参考：qbot_rpg/core/forge_material.py（批2：模块级纯函数集合 + 默认 ProficiencyEngine() +
  settings 三态归一 + 委托引擎公开方法）；qbot_rpg/core/forge_tree.py（批1：构造器注入+缺省兜底）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x）：
  F-1  模块级引擎持有者：本模块维护模块级 ProficiencyEngine（默认无参构造），并提供
       configure_proficiency(entries, settings) 供装配层在加载 proficiency.json 后一次性注入
       forge 实例配置（job_rank_levels/tier_names/exp_sources 随内容包可配，2c2d §3.1
       「内容包可配」）。装配期一次性配置、运行期只读——配置固定后同刻同参必同值，保持
       纯函数确定性；缺省引擎（无注入）默认配置恰与 forge 实例默认形态一致
       （job_rank_levels [0,100,300,700,1500,3000,6000] / tier_names 见习→王 / craft 1.0），
       故无注入时行为与 forge 实例等价。
  F-2  exp_to_next 成长曲线：读取模块级 _RANKS（configure 时随 forge 实例 job_rank_levels
       更新，否则缺省 [0,100,300,700,1500,3000,6000] 对齐 proficiency.py 默认）；level 达
       末档（王）→ maxed=True、missing=0。
  F-3  forge_exp_for 计价：exp_per_forge 支持 int（节点等级×N）与 str「节点等级×N」
       （解析系数 N）；解析失败/缺省 → 系数 2（对齐定稿 L214 熟练节点×2）。
  F-4  level_gate_met 非法 node_level（非正整数，V12 应拦）→ 保守拒绝 {ok:False,
       reason:"invalid_node_level"}（对齐 forge_tree.node_level_met 保守拒绝口径）。
  F-5  gain_forge_exp 委托 ProficiencyEngine.gain_prof_exp(player, "forge", amount,
       source="craft")（EXP-01 craft 制作来源）；amount = forge_exp_for 计价结果；
       返回引擎原始结果 dict（ok/exp_gained/level/tier_from/tier_to/sp_gained/level_ups）。
  F-6  forge_prof_node 缺省节点形态对齐 proficiency dict（level/exp/sp_earned/sp_used/
       unlocks 五键）；player 非 Mapping → 返回 None（确定性兜底，不创建）。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；不写定时器/睡眠调用（M43 零定时器
      探针）；平台无关；不引入随机；每功能可追溯（文件头标注依据）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple

from qbot_rpg.content.forge_settings import FORGE_SETTINGS_KEYS, read_forge_settings
from qbot_rpg.core.forge_tree import FORGE_JOB_ID
from qbot_rpg.core.proficiency import ProficiencyEngine

__all__ = [
    "FORGE_JOB_ID",
    "configure_proficiency",
    "exp_to_next",
    "forge_exp_for",
    "forge_level",
    "forge_prof_node",
    "gain_forge_exp",
    "level_gate_met",
    "rank_name",
]

# =====================================================================================
# 模块级配置（【工程补白 F-1/F-2】装配期一次性注入，运行期只读）
# =====================================================================================

# 成长曲线缺省（对齐 proficiency.py _DEFAULT_RANK_LEVELS；forge 实例默认同值）
_DEFAULT_RANK_LEVELS: Tuple[int, ...] = (0, 100, 300, 700, 1500, 3000, 6000)

# 模块级引擎（默认无参构造；configure_proficiency 可替换）
_ENGINE: ProficiencyEngine = ProficiencyEngine()

# forge 职业成长曲线（exp_to_next 缺口计算用；configure 时随 forge 实例更新）
_RANKS: Tuple[int, ...] = _DEFAULT_RANK_LEVELS


def configure_proficiency(
    entries: Optional[Sequence[Mapping[str, Any]]] = None,
    settings: Optional[Mapping[str, Any]] = None,
) -> ProficiencyEngine:
    """装配层注入 proficiency.json 配置（【工程补白 F-1】forge 实例随内容包可配）。

    入参：
      - entries：proficiency.json 条目列表（含 forge 实例）；None/[] → 默认引擎兜底。
      - settings：settings dict（job_tier_map 主落点等，透传 ProficiencyEngine）。
    行为：重建模块级引擎（_ENGINE）与 forge 成长曲线（_RANKS）——从 entries 找 forge
      实例的 job_rank_levels（合法：非负整数、首项 0、单调递增 → 采纳；否则保留缺省）。
      装配期一次性调用，运行期只读；不调用时默认引擎行为 = forge 实例默认形态。
    出参：新引擎实例。
    """
    global _ENGINE, _RANKS
    _RANKS = _DEFAULT_RANK_LEVELS
    _ENGINE = ProficiencyEngine(entries, settings)
    if entries:
        for e in entries:
            if not isinstance(e, Mapping) or e.get("id") != FORGE_JOB_ID:
                continue
            raw = e.get("job_rank_levels")
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                ranks: list = []
                ok = True
                for x in raw:
                    if isinstance(x, bool) or not isinstance(x, int) or x < 0:
                        ok = False
                        break
                    ranks.append(int(x))
                if (
                    ok
                    and ranks
                    and ranks[0] == 0
                    and all(b > a for a, b in zip(ranks, ranks[1:]))
                ):
                    _RANKS = tuple(ranks)
            break
    return _ENGINE


def _engine() -> ProficiencyEngine:
    """模块级引擎（【工程补白 F-1】运行期只读）。"""
    return _ENGINE


def _tier_name(level: int) -> str:
    """档位名（level → tier_names[index]；缺省 7 级 见习→王，内容包可改）。"""
    return _ENGINE.tier_name(FORGE_JOB_ID, level)


# =====================================================================================
# 节点 / 等级（F-6 / forge_tree F-2 口径）
# =====================================================================================
def forge_prof_node(player: Any) -> Optional[MutableMapping[str, Any]]:
    """玩家铸造职业 proficiency 节点（【工程补白 F-6】缺省创建，对齐 proficiency dict 形态）。

    入参：player（玩家状态 dict；非 Mapping → None 确定性兜底，不创建）。
    逻辑：确保 player["proficiency"]["forge"] 为 MutableMapping——缺失时缺省创建
      {"level":0,"exp":0,"sp_earned":0,"sp_used":0,"unlocks":{}} 并挂回 player（就地改写，
      对齐 ProficiencyEngine._prof_node create=True 形态）。
    出参：proficiency.forge 节点（MutableMapping，就地引用）；player 非 Mapping → None。
    """
    if not isinstance(player, MutableMapping):
        return None
    prof = player.get("proficiency")
    if not isinstance(prof, MutableMapping):
        prof = {}
        player["proficiency"] = prof
    node = prof.get(FORGE_JOB_ID)
    if not isinstance(node, MutableMapping):
        node = {"level": 0, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}}
        prof[FORGE_JOB_ID] = node
    return node


def _read_prof_node(player: Any) -> Optional[Mapping[str, Any]]:
    """proficiency.forge 节点只读（无/非 Mapping → None，不改写；exp_to_next 用）。"""
    if not isinstance(player, Mapping):
        return None
    prof = player.get("proficiency")
    if not isinstance(prof, Mapping):
        return None
    node = prof.get(FORGE_JOB_ID)
    return node if isinstance(node, Mapping) else None


def forge_level(player: Any) -> int:
    """铸造职业等级（缺省 0=见习）。

    入参：player（玩家状态 dict）。出参：职业等级 int（≥0）。
    读 player["proficiency"]["forge"]["level"]；节点缺失/非 Mapping/等级非非负整数 → 0
    （确定性兜底，对齐 forge_tree._forge_level 口径）。纯读不改写。
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


# =====================================================================================
# 等级门槛（定稿 §10.1 L213：可锻节点上限=职业等级）
# =====================================================================================
def level_gate_met(player: Any, node_level: Any) -> Dict[str, Any]:
    """可锻节点上限判定（定稿 §10.1 L213：可锻节点等级上限=职业等级）。

    规则：node_level ≤ 铸造职业等级 → 可锻 {ok:True}；否则 {ok:False, need, current, missing}。
    出参：{ok, need, current, missing}；node_level 非正整数（V12 应拦）→ 保守拒绝
      {ok:False, reason:"invalid_node_level", need, current, missing:0}（【工程补白 F-4】）。
    """
    current = forge_level(player)
    if isinstance(node_level, bool) or not isinstance(node_level, int) or node_level <= 0:
        return {
            "ok": False,
            "reason": "invalid_node_level",
            "need": node_level,
            "current": current,
            "missing": 0,
        }
    if current >= node_level:
        return {"ok": True, "need": node_level, "current": current, "missing": 0}
    return {
        "ok": False,
        "reason": "level_insufficient",
        "need": node_level,
        "current": current,
        "missing": node_level - current,
    }


# =====================================================================================
# 熟练计价（定稿 L214 / m9 契约 §三 exp_per_forge）
# =====================================================================================
def _parse_exp_coeff(raw: Any) -> Optional[int]:
    """exp_per_forge 系数解析（【工程补白 F-3】）。

    int ≥0 → 原值；str「节点等级×N」/「×N」/纯数字串 → N；其它/无法解析 → None
    （调用方兜底系数 2）。
    """
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if s.isdigit():
            return int(s)
        for token in s.split("×"):
            t = token.strip()
            if t.isdigit():
                return int(t)
    return None


def _resolve_exp_per_forge(settings: Any) -> Any:
    """exp_per_forge 归一（【工程补白 F-3】settings 三态容错 → read_forge_settings 权威）。

    三态：全量 settings dict（含 forge 段）/ forge 段本身（含 FORGE_SETTINGS_KEYS 任一键）/
    None → 缺省合并（read_forge_settings 兜底 "节点等级×2"）。
    """
    if isinstance(settings, Mapping):
        seg = settings.get("forge")
        if isinstance(seg, Mapping):
            return read_forge_settings(settings).get("exp_per_forge")
        if any(k in settings for k in FORGE_SETTINGS_KEYS):
            return read_forge_settings({"forge": settings}).get("exp_per_forge")
        return read_forge_settings(settings).get("exp_per_forge")
    return read_forge_settings(None).get("exp_per_forge")


def forge_exp_for(node_level: Any, settings: Any = None) -> int:
    """熟练经验计价（定稿 L214 / m9 契约 §三 exp_per_forge：节点等级×N）。

    计价 = 节点等级 × 系数；系数来自 settings.forge.exp_per_forge（int 或「节点等级×N」），
    缺省/解析失败 → 2（【工程补白 F-3】）。node_level 非正整数 → 0（确定性兜底）。
    出参：int 熟练经验（每件）。
    """
    if isinstance(node_level, bool) or not isinstance(node_level, int) or node_level <= 0:
        return 0
    coeff = _parse_exp_coeff(_resolve_exp_per_forge(settings))
    if coeff is None:
        coeff = 2  # 【工程补白 F-3】缺省 熟练节点×2
    return node_level * coeff


# =====================================================================================
# 入账（EXP-01 craft 来源；委托 ProficiencyEngine）
# =====================================================================================
def gain_forge_exp(player: Any, node_level: Any, settings: Any = None) -> Dict[str, Any]:
    """铸造熟练经验入账（EXP-01 craft 来源，委托 ProficiencyEngine.gain_prof_exp）。

    入参：
      - player：玩家状态 dict（就地改写 proficiency.forge 的 level/exp/sp_earned）。
      - node_level：本次锻造节点等级（计价基准）。
      - settings：exp_per_forge 计价源（全量 settings dict / forge 段 / None，见 F-3）。
    逻辑：amount = forge_exp_for(node_level, settings)（缺省 节点等级×2）→
      _engine().gain_prof_exp(player, FORGE_JOB_ID, amount, source="craft")
      （EXP-01 craft 制作来源；EXP-06 入账→连跳升级→发 SP 判定链由引擎承载）。
    出参：引擎原始结果 {ok, exp_gained, level, tier_from, tier_to, sp_gained, level_ups}；
      amount ≤0（非法节点等级）→ 委托引擎 exp_amount_invalid 拒绝（【工程补白 F-5】）。
    """
    amount = forge_exp_for(node_level, settings)
    return _engine().gain_prof_exp(player, FORGE_JOB_ID, amount, source="craft")


# =====================================================================================
# 经验明细（支撑「还差 N 熟练」文案）
# =====================================================================================
def exp_to_next(player: Any) -> Dict[str, Any]:
    """经验明细查询（【工程补白 F-2】；供「还差 N 熟练」文案）。

    入参：player（纯读，不改写）。
    出参：{ok, level, exp, cost, missing, rank, next_rank?, maxed}：
      - exp      当前级内余量（proficiency.forge.exp，缺省 0）
      - cost     本级阈值差（job_rank_levels[level+1]-job_rank_levels[level]；已满级 0）
      - missing  还差 N = max(0, cost - exp)；已满级 0
      - rank     当前档位名（rank_name）；next_rank 未满级时下一档名
      - maxed    level 达成长曲线末档（王）→ True
    """
    level = forge_level(player)
    node = _read_prof_node(player)
    exp = 0
    if node is not None:
        e = node.get("exp")
        exp = e if isinstance(e, int) and not isinstance(e, bool) and e >= 0 else 0
    ranks = _RANKS
    max_level = len(ranks) - 1
    base = {
        "ok": True,
        "level": level,
        "exp": exp,
        "rank": _tier_name(level),
    }
    if level >= max_level:
        return {**base, "cost": 0, "missing": 0, "maxed": True, "next_rank": None}
    cost = ranks[level + 1] - ranks[level]
    missing = max(0, cost - exp)
    return {
        **base,
        "cost": cost,
        "missing": missing,
        "maxed": False,
        "next_rank": _tier_name(level + 1),
    }


# =====================================================================================
# 档位名（LVL-01 tier_names）
# =====================================================================================
def rank_name(player: Any) -> str:
    """铸造职业档位名（tier_name：见习/正式/精通/专家/大师/宗师/王，内容包可改）。

    入参：player。出参：档位名 str（level 0=见习；forge_level 缺省 0 → 见习）。
    """
    return _engine().tier_name(FORGE_JOB_ID, forge_level(player))
