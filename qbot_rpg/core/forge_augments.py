"""M9 锻造·批7·路7B：客制结构/校验/次数表/资格判定（qbot_rpg/core/forge_augments.py）。

文件名：qbot_rpg/core/forge_augments.py
创建时间：2026-08-30
作者：Hermes 子agent-7B（M9 锻造实现组批7·路7B：并发同仓，仅新建本文件 +
  tests/unit/test_forge_augments.py；不改动批0 forge_models.py / 批3 forge_sp.py，
  二者只读复用）

功能描述：forge_augments（forge.json 顶层 augments 段，2c2d §二）的纯函数层：
  1) parse_augments(modules)         解析 augments.augments[] → AugmentRow 元组
     （批0 Def 类复用；kind=numeric/slot 两型；含 cost/value/stat_key/slot_level/
     repeatable/max_repeat/disabled/trace 访问器；缺段 → 空元组）
  2) validate_augments(modules)      客制专项校验（委托批0 validate_forge 2c2d 段：
     V4 客制项枚举结构 / V5 消耗引用 / V6 次数表 / V7 final_tier 节点扩展 /
     V8 全段 disabled / W2 追溯行 / W3 settings 关），返回结构化 dict（不抛异常）
  3) limit_by_rarity(modules)        次数表（LIM-01~03）：rows 原样 + table
     {rarity: max_times}（0=不限）+ final_only {rarity: max_times}（终盘限定行）；
     供 M12 编辑器配置与资格判定 GU-A4/A5
  4) augment_eligible(player, weapon)  客制资格判定（GU-A1~A4 前置守卫：SP-F5 解锁 +
     宗师级（≥41）+ 最终强化武器 + 品质四档；只判资格不执行，返回 gates/reason）

依据：
  - docs/细化/细化_2c2d_锻造套装与客制.md §二（AUG-01~12/LIM-01~03 字段表 + §2.4.1
    GU-A1~A7 前置守卫 + §2.2.1 次数表 + §五 校验器 V4~V8/W2/W3 + §3.1 宗师 41-50）
  - 定稿（锻造系统设计定稿 v1.0.1）§14 客制强化（L174-183：终盘仅最终强化武器 L177 /
    4 项攻击·会心·防御·孔位 L178 / 消耗龙脉石类+宝石 L179 / 次数按品质四档 L180 /
    归口声明 L181 / 深度投入空间 L182）+ §12.3 数据样例 L324-349
  - docs/m9_shared_contract.md §五（Augment+limit_by_rarity 字段表 V4/V5）/ §六
    （2c2d 校验 V1-V8 硬 / W1-W4 黄）
  - 复用批0：qbot_rpg/content/forge_models.py（AugmentRow/LimitByRarity Def +
    validate_forge 2c2d 段——只读委托不重写）
  - 复用批3：qbot_rpg/core/forge_sp.py（SP-F5 unlock_augment 解锁判定 sp_locked——
    只读委托不重写）/ qbot_rpg/core/forge_job.py（forge_level 铸造职业等级）
  - content/test_demo/forge.json（客制段样例：aug_atk/aug_crit/aug_def/aug_slot +
    limit_by_rarity epic×3/legendary×2/终盘×1）

边界声明：本路仅「结构解析 / 配置校验 / 次数表 / 资格判定」，客制执行（扣消耗+
改实例+记 aug_list 的原子事务 AUG-F3）归 M12 编辑器或后续批次——本模块零副作用。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x；不冒充契约行号）：
  F-1  kind 枚举：权威 AUG-03 定 kind ∈ {numeric, slot} 两型（归口渠道：numeric=数值层
       / slot=统一开孔渠道）；任务派工单字面「三型 stat/slot/element」与权威不符，
       以权威为准——8 元素是节点 stats.element 属性键（2c2a N-08），非客制 kind。
  F-2  parse_augments 缺段/空段 → 空元组（共享契约 D-04 augments 可选；无 augments
       段是合法配置）；兼容双形态（Mapping {augments,limit_by_rarity} / list 视为
       augments 数组，对齐批0 _check_augments 口径）。
  F-3  validate_augments 委托批0 validate_forge（一次性全量跑），再按 augments 相关
       规则过滤聚合：field 前缀 forge.augments.* 或 节点级客制规则
       （augmentable_not_final_weapon / final_tier_invalid / final_tier_not_bool——
       final_tier 直接决定终盘行命中 GU-A4，纳入客制校验范围；king_only 属铸造王
       不纳入）。返回 dict {ok, present, errors, warnings, rule_counts}。
  F-4  limit_by_rarity：rows = LimitByRarity 视图元组（原样含 final_only）；table =
       非终盘行 {rarity: times}（LIM-02；缺行 → 0=不限）；final_only = 终盘限定行
       {rarity: times}（LIM-03，必须 legendary——V6 硬拦由批0 承载）。行序稳定
       （文件序），终盘行覆盖普通行同键时以 final_only 表独立承载不合并。
  F-5  augment_eligible 的 weapon 入参 = 目标武器实例 dict（含 final/augmentable/
       rarity/type 形态字段；GU-A3 消费方）；SP 解锁判定委托 forge_sp.sp_locked
       （未识别面板保守锁定）；宗师门槛 = 铸造等级 ≥ 41（2c2d §3.1 宗师 41-50，
       AUGMENT_MASTER_LEVEL_MIN 常量可配）；品质门槛 = rarity ∈ {epic, legendary}
       （GRD-R04）。只判资格不改写 player/weapon。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；平台无关；不引入随机；
      不写定时器/睡眠调用（M43 零定时器探针）；每功能可追溯（文件头标注依据）；
      渲染输出无 emoji。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, cast

from qbot_rpg.content.forge_models import (
    AUGMENT_KINDS,
    LIMIT_RARITY_QUALITIES,
    AugmentRow,
    LimitByRarity,
    validate_forge,
)
from qbot_rpg.core.forge_job import forge_level
from qbot_rpg.core.forge_sp import sp_locked

__all__ = [
    "AUGMENT_MASTER_LEVEL_MIN",
    "AUGMENT_SP_PANEL_ID",
    "AUGMENT_RARITY_QUALITIES",
    "augment_eligible",
    "limit_by_rarity",
    "parse_augments",
    "validate_augments",
]

# =====================================================================================
# 常量（对齐 2c2d §3.1 / GRD-R04 / SP-F5）
# =====================================================================================

# 宗师级门槛（2c2d §3.1 CAST 表：宗师 41-50；/客制 L237「宗师+最终强化武器」）
AUGMENT_MASTER_LEVEL_MIN: int = 41

# 客制 SP 解锁项 id（SP-F5 unlock_augment，2c2d §3.2）
AUGMENT_SP_PANEL_ID: str = "unlock_augment"

# 参与客制的品质白名单（4b GRD-R04：normal/fine 不参与客制）
AUGMENT_RARITY_QUALITIES: Tuple[str, ...] = ("epic", "legendary")

# 客制项 kind 白名单（AUG-03 权威两型；批0 AUGMENT_KINDS 镜像，防 import 链漂移）
_AUGMENT_KIND_WHITELIST: Set[str] = set(AUGMENT_KINDS)

# 节点级客制规则（validate_augments 过滤范围；F-3）
_AUGMENT_NODE_RULES: Set[str] = {
    "augmentable_not_final_weapon",  # 2c2a V16（仅最终强化武器可客制）
    "final_tier_invalid",            # 2c2d V7（final_tier 仅 final+legendary）
    "final_tier_not_bool",           # 2c2d V7（final_tier 须 bool）
}

# =====================================================================================
# 1) parse_augments：augments.augments[] → AugmentRow 元组（批0 Def 复用，F-2）
# =====================================================================================
def parse_augments(modules: Mapping[str, object]) -> Tuple[AugmentRow, ...]:
    """解析 forge.json augments 段客制项（AUG-01~12；批0 AugmentRow 复用）。

    入参：modules（loader 形态 dict，含 \"forge\" 键；forge 顶层是 obj 非 list）。
    出参：AugmentRow 元组（文件序）；缺 augments 段 / 空段 → 空元组（合法配置）。
    兼容双形态：augments 为 Mapping {augments:[], limit_by_rarity:[]} → 取 augments
    键；为 list → 视为 augments 数组（对齐批0 _check_augments 口径，F-2）。
    非 Mapping 行跳过（批0 V4 硬拦归属 validate_augments，本函数只解析不判错）。
    """
    forge = modules.get("forge")
    if not isinstance(forge, Mapping):
        return ()
    aug = forge.get("augments")
    if aug is None:
        return ()
    rows_raw: object
    if isinstance(aug, Mapping):
        rows_raw = aug.get("augments")
    elif isinstance(aug, list):
        rows_raw = aug
    else:
        return ()
    if not isinstance(rows_raw, list):
        return ()
    out: List[AugmentRow] = []
    for e in rows_raw:
        if isinstance(e, Mapping):
            out.append(cast(AugmentRow, AugmentRow.from_entry(e)))
    return tuple(out)


# =====================================================================================
# 2) validate_augments：客制专项校验（委托批0 validate_forge 2c2d 段，F-3）
# =====================================================================================
def validate_augments(modules: Mapping[str, object]) -> Dict[str, Any]:
    """客制专项校验（包装批0 validate_forge 2c2d 段：V4/V5/V6/V7/V8/W2/W3）。

    入参：modules（同 validate_forge 形态，可含 forge/items/enemies）。
    出参：dict（确定性，不抛异常）：
      {
        \"ok\": bool,           # 无客制相关硬错误（红拦）
        \"present\": bool,     # forge.augments 段存在（含空对象）
        \"errors\": [...],     # 客制相关红拦 [{field, kind, rule, msg}]
        \"warnings\": [...],   # 客制相关黄提示 [{field, kind, rule, msg}]
        \"rule_counts\": {kind: n},   # 按 2c2d-V4/V5/V6/V7/V8/W2/W3 计数
      }
    过滤范围：field 前缀 forge.augments.* 的 2c2d-V4/V5/V6/V8/W2/W3 消息 + 节点级
    客制规则（augmentable_not_final_weapon / final_tier_*，F-3）。
    forge 段缺失/非 Mapping → {ok:True, present:False, 空}（模块未接线默认放行，
    对齐既有校验器惯例）；augments 段缺失 → present=False 不判错。
    """
    forge = modules.get("forge")
    present = isinstance(forge, Mapping) and "augments" in forge
    # dict 形态收集器（批0 _emit 三形态兜底支持）
    report: Dict[str, List[Dict[str, Any]]] = {"errors": [], "warnings": []}
    validate_forge(modules, report)
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    rule_counts: Dict[str, int] = {}
    for bucket, target in (("errors", errors), ("warnings", warnings)):
        for entry in report.get(bucket, []):
            args = entry.get("args", ())
            field = args[1] if len(args) > 1 else ""
            kind = args[2] if len(args) > 2 else ""
            detail = entry.get("kwargs", {})
            rule = detail.get("rule", "")
            # 过滤：field 前缀 forge.augments.* 或 节点级客制规则
            if not (str(field).startswith("forge.augments") or rule in _AUGMENT_NODE_RULES):
                continue
            item: Dict[str, Any] = {
                "field": field,
                "kind": kind,
                "rule": rule,
                "msg": detail.get("msg", ""),
            }
            if rule:
                item["detail"] = {k: v for k, v in detail.items() if k != "msg"}
            target.append(item)
            rule_counts[kind] = rule_counts.get(kind, 0) + 1
    return {
        "ok": not errors,
        "present": present,
        "errors": errors,
        "warnings": warnings,
        "rule_counts": rule_counts,
    }


# =====================================================================================
# 3) limit_by_rarity：次数表（LIM-01~03；供 M12 编辑器配置与 GU-A4/A5 命中，F-4）
# =====================================================================================
def limit_by_rarity(modules: Mapping[str, object]) -> Dict[str, Any]:
    """客制次数表（LIM-01~03，2c2d §2.2.1；{rarity: max_times}，0=不限）。

    入参：modules（含 forge.augments.limit_by_rarity）。
    出参：dict：
      {
        \"rows\": [ {quality, times, final_only, index} ... ],  # 原样视图（文件序）
        \"table\": {quality: max_times, ...},     # 非终盘行；缺行 → 0（不限）
        \"final_only\": {quality: max_times, ...} # 终盘限定行（LIM-03，必 legendary）
      }
    缺段 / 非 list / 空 → table/final_only 空 dict、rows 空列表（次数不限语义由
    调用方按 0 处理）。quality/times 合法性（V6）由 validate_augments 承载，本函数
    只做容错归一（非法行跳过并保留 rows 原样供诊断）。
    """
    forge = modules.get("forge")
    if not isinstance(forge, Mapping):
        return {"rows": [], "table": {}, "final_only": {}}
    aug = forge.get("augments")
    limit_raw: object
    if isinstance(aug, Mapping):
        limit_raw = aug.get("limit_by_rarity")
    elif isinstance(aug, list):
        limit_raw = []
    else:
        limit_raw = None
    rows: List[Dict[str, Any]] = []
    table: Dict[str, int] = {}
    final_only: Dict[str, int] = {}
    if not isinstance(limit_raw, list):
        return {"rows": rows, "table": table, "final_only": final_only}
    for i, e in enumerate(limit_raw):
        if not isinstance(e, Mapping):
            continue
        lim = LimitByRarity.from_entry(e, index=i)
        q = lim.quality
        t = lim.times
        if not isinstance(q, str) or q not in LIMIT_RARITY_QUALITIES:
            continue
        if not isinstance(t, int) or isinstance(t, bool) or t < 1:
            continue  # V6 times ≥ 1；非法行跳过（0=不限 语义=缺行）
        rows.append({
            "quality": q,
            "times": t,
            "final_only": bool(lim.final_only),
            "index": i,
        })
        if lim.final_only is True:
            final_only[q] = t
        else:
            table[q] = t
    return {"rows": rows, "table": table, "final_only": final_only}


# =====================================================================================
# 4) augment_eligible：客制资格判定（GU-A1~A4 前置守卫，只判资格不执行，F-5）
# =====================================================================================
def augment_eligible(player: Any, weapon: Any) -> Dict[str, Any]:
    """客制资格判定（2c2d §2.4.1 GU-A1~A4 前置守卫；只判资格不执行）。

    入参：
      - player：玩家状态 dict（读 proficiency.forge.level + sp 解锁；纯读不改写）。
      - weapon：目标武器实例 dict（GU-A3 消费方：含 final/augmentable/rarity/type；
        非 Mapping → 形态门槛不满足）。
    出参：dict：
      {
        \"ok\": bool,          # 四守卫全过
        \"gates\": {
          \"sp_unlocked\": bool,   # GU-A1 SP-F5 unlock_augment 已解锁
          \"master_rank\": bool,   # GU-A2 铸造职业等级 ≥ AUGMENT_MASTER_LEVEL_MIN(41)
          \"final_weapon\": bool,  # GU-A3 final=true 且 augmentable=true 且 weapon
          \"quality_ok\": bool,    # GU-A4 rarity ∈ {epic, legendary}
        },
        \"reason\": str|None,  # 首个失败守卫：sp_not_unlocked / master_rank_insufficient
                              #   / not_final_weapon / quality_not_augmentable
        \"level\": int,        # 当前铸造职业等级
        \"need_level\": int,   # AUGMENT_MASTER_LEVEL_MIN
      }
    守卫按 GU-A1→A2→A3→A4 顺序短路（首个失败即 reason）；不执行任何消耗/改写。
    """
    # GU-A1：SP-F5 unlock_augment 解锁（委托 forge_sp.sp_locked，只读）
    sp_unlocked_gate = not sp_locked(player, AUGMENT_SP_PANEL_ID)
    # GU-A2：宗师级（2c2d §3.1 宗师 41-50；forge_job.forge_level 只读）
    level = forge_level(player)
    master_gate = level >= AUGMENT_MASTER_LEVEL_MIN
    # GU-A3：最终强化武器（final=true + augmentable=true + type=weapon）
    wtype = None
    wfinal = None
    waugmentable = None
    if isinstance(weapon, Mapping):
        wtype = weapon.get("type")
        wfinal = weapon.get("final")
        waugmentable = weapon.get("augmentable")
    final_weapon_gate = (
        isinstance(weapon, Mapping)
        and wfinal is True
        and waugmentable is True
        and wtype == "weapon"
    )
    # GU-A4：品质四档（epic/legendary 参与客制，GRD-R04）
    rarity = weapon.get("rarity") if isinstance(weapon, Mapping) else None
    quality_gate = rarity in AUGMENT_RARITY_QUALITIES

    gates: Dict[str, bool] = {
        "sp_unlocked": sp_unlocked_gate,
        "master_rank": master_gate,
        "final_weapon": final_weapon_gate,
        "quality_ok": quality_gate,
    }
    reason: Optional[str] = None
    if not sp_unlocked_gate:
        reason = "sp_not_unlocked"
    elif not master_gate:
        reason = "master_rank_insufficient"
    elif not final_weapon_gate:
        reason = "not_final_weapon"
    elif not quality_gate:
        reason = "quality_not_augmentable"
    return {
        "ok": reason is None,
        "gates": gates,
        "reason": reason,
        "level": level,
        "need_level": AUGMENT_MASTER_LEVEL_MIN,
    }
