"""M13 批16 路16C：技能位战斗消费（qbot_rpg/core/skill_slots_battle.py）。

文件名：qbot_rpg/core/skill_slots_battle.py
创建时间：2026-09-02
作者：Hermes 子agent-16C（M13 技能库实现组批16路16C：并发同仓，仅新建本文件 +
  tests/unit/test_skill_slots_battle.py 与对 battle_commands._attack_action 的
  装配过滤小改；不动兄弟路文件——路16A 独占资源生命周期、路16B 独占 transform×资源）

功能描述：技能位战斗消费（6a §1.5/§4.3 承接）——装配快照（skill_slots_state）
→ 战斗可用技能列表的**引擎层唯一权威**：
  1) SKILL_SLOTS_STATE_KEY   装配快照存档键常量（= core.skill_slots.SLOT_STATE_KEY
     "skill_slots"，本地镜像防循环依赖；ctx["skill_slots_state"] 同键）
  2) SLOT_* 槽位类型常量       basic 固定第 1 位 / active 可排序 / passive·trigger
     装配槽（镜像 skill_slots 常量口径，G0 零 import content）
  3) slots_from_snapshot(snapshot)  装配快照 → 战斗可用技能列表（四类槽全量，
     basic 缺位 → skill_id None 占位；畸形快照 → 空骨架确定性兜底；纯函数）
  4) available_skills(ctx)         进战斗消费入口：ctx["skill_slots_state"] →
     战斗可用技能 id 列表（basic 固定第 1 位 + active 排序 + passive/trigger 槽）
  5) is_slot_equipped(ctx, skill_id)  技能是否在装配内（basic/active/passive/
     trigger 任一槽命中；未装配/未知技能 → False；畸形快照 → False）
  6) battle_equipped_skills(ctx)    战斗可用技能 id → 技能 def 映射
     （{skill_id: SkillDef|raw dict}；ctx["skills"] 同源解析，缺省 {}）
  7) passive/trigger 槽挂点登记：PASSIVE_PROC_HOOK / TRIGGER_PROC_HOOK
     （proc 容器执行位——被动常驻/触发条件命中由战斗/效果层经 hook 注入执行；
     本文件登记接口，不臆造条件判定）

依据：
  - docs/细化/细化_6a_技能库契约.md（349 行 v1.0）：
    §1.4 四类时机（basic 固定第 1 位 [L62/L86] / active 可排序 [L86] /
    passive·trigger 装配槽不占行动位 [L64-65]）；§1.5 技能位与装配
    （装配结果落玩家存档 [L87]，每次进战斗按装配快照生成可用技能列表）；
    §4.3 绑定规则（装配过滤：job_restrict 自动过滤 + 通用技能全职业可见）；
    TC-04（四类时机门禁与技能位）；TC-05（指令被拒无副作用）；§7 存档影响。
  - docs/m13_6a摸底.md：G5（技能位装配无存档 → 批13 收口装配快照落存档）。
  - 批13 已落盘：qbot_rpg/core/skill_slots.py（assemble_slots/save_slots_to_state/
    load_slots_from_state + SLOT_STATE_KEY）；qbot_rpg/assembly/context.py
    ctx["skill_slots"] 接口 + ctx["skill_slots_state"]（_ps_init 绑 ps）。
  - 批14 已落盘：qbot_rpg/core/battle.py（_resolve_combo_action 从
    combo_engine().resolve_skill 解析技能 def——技能通道已就绪，本文件消费
    装配快照产出**战斗可用技能列表**（槽位过滤/未装配拒绝判定基准））。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  P-1  战斗可用技能列表口径：装配快照 slots 列表（basic 固定第 1 位 →
       active 排序 → passive/trigger 槽）逐项收集；slots 缺省/畸形 → 回退
       active_order + passive + trigger 三键并集（老存档兼容，确定性兜底）；
       全缺 → 空骨架 []。basic 槽 skill_id=None（缺普攻占位 P-3）→ 收集为
       None 占位不丢弃（战斗层可提示缺普攻）。
  P-2  未装配拒绝判定 = is_slot_equipped（装配快照内技能才可施放；契约
       §1.5「每次进战斗按装配快照生成可用技能列表」）。非装配内技能 →
       战斗外被拒（不消耗行动）；被动/触发槽技能不在行动位 → 不可直接施放
       （is_slot_equipped 对 passive/trigger 槽返回 False，见 P-3）。
  P-3  passive/trigger 槽技能不可主动施放：行动位 = basic + active（§1.4
       表：passive/trigger 不占行动位 [L64-65]）。is_slot_equipped 仅对
       basic/active 槽判定（被动/触发槽经被动挂点生效，见 P-4）；判定严格
       区分槽类型（不把 passive/trigger 槽当行动位技能放行）。
  P-4  passive/trigger 被动生效挂点：本文件登记 hook 接口
       （PASSIVE_PROC_HOOK/TRIGGER_PROC_HOOK 键名常量），由战斗/效果层在
       既有触发引擎挂载点（行动开始/受击/行动后，1f/1e 承接）经
       ctx[hook] 注入执行 proc 容器；本文件不实现条件判定引擎（trigger
       条件 13 类枚举归 1e/1f 触发引擎），仅保证装配快照 → 可用列表链路
       完整（被动/触发槽技能在 available_skills 中可见、有挂点可执行）。
  P-5  ctx 键读口径：available_skills/is_slot_equipped 读 ctx["skill_slots_state"]
       （批13 落盘键，_ps_init 绑 ps 恒存在）；缺省/畸形 → 确定性兜底
       （空列表/False），不抛异常（对齐 load_slots_from_state 防御口径）。
  P-6  套装激活技能并入口径（2026-09-14 套装档位批）：ctx[SET_SKILLS_STATE_KEY]
       （"set_skills" = forge_set_skills.resolve_set_skills 产出的 {技能 id: 等级}）
       经 with_set_skills 追加为装配槽行（slot 见 P-7）→ available_skills /
       battle_equipped_skills 自然包含；同 skill_id 已在装配快照内则不重复追加
       （装配行优先）。这是套装技能「进入玩家可用技能集」的唯一路径，不另开旁路。
  P-7  套装技能槽类型：技能表 ctx["skills"][skill_id] 的 type（basic/active/passive/
       trigger）可用则以该 type 入槽（尊重 6a 技能时机）；技能表缺该技能/缺 type →
       默认 passive（套装技能常驻生效、不占行动位）。因此套装技能的**等级**随行
       携带（"level" 键），可用性判定与装配技能同源（is_slot_equipped 只放行
       basic/active 行动位）。

铁律：零 NoneBot import（G0 门禁）；core 层只依赖 data（技能数据经 ctx 注入，
零 import content）；纯函数确定性（同刻同参必同值）；完整类型标注（typing
3.9 兼容）；零定时器/零睡眠（本文件不含任何 sleep/定时器字面量）；不引入
随机；不 git commit；只写本文件 + 自己的测试 + battle_commands 装配过滤小改。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

# =====================================================================================
# 常量
# =====================================================================================

# 装配快照存档键（ctx["skill_slots_state"] 同键；镜像 skill_slots.SLOT_STATE_KEY，
# G0 本地镜像不 import，P-5）
SKILL_SLOTS_STATE_KEY: str = "skill_slots_state"

# 槽位类型（§1.4/§1.5：basic 固定第 1 位 / active 可排序 / passive·trigger 装配槽）
SLOT_BASIC: str = "basic"
SLOT_ACTIVE: str = "active"
SLOT_PASSIVE: str = "passive"
SLOT_TRIGGER: str = "trigger"

# 套装激活技能结算键（ACT-02~05：forge_set_skills.sync_set_skills 产出的
# {技能 id: 等级}；本文件经 with_set_skills 并入装配快照 → 可用技能集，P-6）
SET_SKILLS_STATE_KEY: str = "set_skills"

# 装备来源技能结算键（批26 α1：core/equip_mods.recompute_equip_skills 产出的
# {技能 id: 等级}，落 player.persistent_state["equip_skills"]，装配层镜像到
# ctx["equip_skills"]；本文件经 with_source_skills 并入装配快照 → 可用技能集）。
# 「各来源容器取并集」= 来源计数语义：卸下装备只清装备容器，消耗品学习
# （skill_slots 快照）/ 锻造套装（set_skills）等其它来源不受影响，P-8。
EQUIP_SKILLS_STATE_KEY: str = "equip_skills"

# 套装激活技能缺省槽类型（§1.4：套装技能常驻生效，默认 passive 不占行动位；
# 技能表给出 type 时以其为准，P-7）
_SET_SKILL_DEFAULT_SLOT: str = SLOT_PASSIVE

# 行动位槽类型（§1.4：basic+active 占行动位；passive/trigger 不占行动位 [L64-65]）
_ACTION_SLOTS: Tuple[str, ...] = (SLOT_BASIC, SLOT_ACTIVE)

# 槽位类型顺序（basic 固定第 1 位 → active → passive → trigger，§1.5）
_SLOT_KIND_ORDER: Tuple[str, ...] = (SLOT_BASIC, SLOT_ACTIVE, SLOT_PASSIVE, SLOT_TRIGGER)

# passive/trigger 被动生效挂点键名（P-4：战斗/效果层经 ctx 注入 proc 容器执行位；
# 本文件只登记接口常量，不实现条件判定）
PASSIVE_PROC_HOOK: str = "skill_slots_passive_proc"
TRIGGER_PROC_HOOK: str = "skill_slots_trigger_proc"

# 装配快照空骨架（确定性兜底，对齐 skill_slots._EMPTY_SNAPSHOT 口径）
_EMPTY_SNAPSHOT: Dict[str, Any] = {
    "slots": [],
    "active_order": [],
    "passive": [],
    "trigger": [],
    "version": 1,
}


# =====================================================================================
# 装配快照 → 战斗可用技能列表（纯函数，引擎层唯一权威）
# =====================================================================================


def _snapshot_of(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """ctx 装配快照读取（P-5：缺省/畸形 → 空骨架，不抛异常）。

    P-6：读取后并入 ctx[SET_SKILLS_STATE_KEY] 的套装激活技能（with_set_skills）；
    P-8（批26 α1）：再并入 ctx[EQUIP_SKILLS_STATE_KEY] 的装备来源技能
    （with_source_skills）——两者都是「独立来源容器」，装配快照之上取并集，
    卸下装备只清装备容器，其它来源技能不被收走。available_skills /
    battle_equipped_skills / is_slot_equipped / equipped_slot_kind 全部经同一
    路径消费（技能表 ctx["skills"] 提供 type 时用其时机，P-7）。
    """
    raw = ctx.get(SKILL_SLOTS_STATE_KEY)
    snapshot = raw if isinstance(raw, Mapping) else _EMPTY_SNAPSHOT
    snap = with_set_skills(snapshot, ctx.get(SET_SKILLS_STATE_KEY), ctx.get("skills"))
    return with_source_skills(snap, ctx.get(EQUIP_SKILLS_STATE_KEY), ctx.get("skills"))


def source_skill_rows(source_skills: object, skill_table: object = None) -> List[Dict[str, Any]]:
    """来源技能表 → 装配槽行（P-6/P-7/P-8；套装/装备来源共用）。

    入参 source_skills: {技能 id: 等级}（非 Mapping → []）；
              skill_table: ctx["skills"]（可选，提供技能的 6a type）；
    出参 list[dict]: {"slot": <basic|active|passive|trigger>, "skill_id": str,
    "level": int}；技能 id 非空、等级为 ≥1 的非 bool int 才收；按技能 id 升序确定。
    """
    if not isinstance(source_skills, Mapping):
        return []
    rows: List[Dict[str, Any]] = []
    for sid in sorted(k for k in source_skills if isinstance(k, str) and k):
        lv = source_skills[sid]
        if not isinstance(lv, int) or isinstance(lv, bool) or lv < 1:
            continue
        rows.append({
            "slot": _set_skill_slot(sid, skill_table),
            "skill_id": sid,
            "level": lv,
        })
    return rows


def set_skill_rows(set_skills: object, skill_table: object = None) -> List[Dict[str, Any]]:
    """套装激活技能表 → 装配槽行（P-6/P-7；等价 source_skill_rows 的别名）。"""
    return source_skill_rows(set_skills, skill_table)


def _set_skill_slot(skill_id: str, skill_table: object) -> str:
    """套装技能槽类型（P-7）：技能表 type ∈ 四类 → 用之；否则 passive 缺省。"""
    if isinstance(skill_table, Mapping):
        row = skill_table.get(skill_id)
        kind: object = None
        if isinstance(row, Mapping):
            kind = row.get("type")
        else:
            kind = getattr(row, "type", None)
        if isinstance(kind, str) and kind in _SLOT_KIND_ORDER:
            return kind
    return _SET_SKILL_DEFAULT_SLOT


def with_source_skills(
    snapshot: Mapping[str, Any],
    source_skills: object,
    skill_table: object = None,
) -> Dict[str, Any]:
    """装配快照 + 某来源技能 → 合并快照（P-6/P-8；不改入参，返回新 dict）。

    基础槽行取 slots_from_snapshot(snapshot)（含 slots 优先 / active_order+passive+
    trigger 老存档回退），来源技能行去重追加（同 skill_id 已在装配内 → 装配行优先，
    先并来源优先）。source_skills 缺省/畸形 → 原快照确定性归一。
    """
    base: Dict[str, Any] = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    rows = slots_from_snapshot(base)
    have = {r.get("skill_id") for r in rows if r.get("skill_id")}
    for row in source_skill_rows(source_skills, skill_table):
        if row["skill_id"] in have:
            continue
        rows.append(row)
        have.add(row["skill_id"])
    base["slots"] = rows
    return base


def with_set_skills(
    snapshot: Mapping[str, Any],
    set_skills: object,
    skill_table: object = None,
) -> Dict[str, Any]:
    """装配快照 + 套装激活技能 → 合并快照（P-6；with_source_skills 的具名别名）。

    保留原名（既有消费方/测试）；实现统一走 with_source_skills（单一并集口径）。
    """
    return with_source_skills(snapshot, set_skills, skill_table)


def set_skill_levels(ctx: Mapping[str, Any]) -> Dict[str, int]:
    """ctx[SET_SKILLS_STATE_KEY] → {技能 id: 等级}（清洗后的套装激活等级表）。

    展示/审计用（六级战斗结算读 level 消费此表）；缺省/畸形 → {}（确定性兜底）。
    """
    raw = ctx.get(SET_SKILLS_STATE_KEY)
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, int] = {}
    for sid, lv in raw.items():
        if isinstance(sid, str) and sid and isinstance(lv, int) \
                and not isinstance(lv, bool) and lv >= 1:
            out[sid] = lv
    return out


def slots_from_snapshot(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """装配快照 → 战斗可用技能列表（四类槽全量，§1.5「进战斗按装配快照生成」）。

    入参：装配快照（assemble_slots 产物形态：slots / active_order / passive /
    trigger / version；或 ctx["skill_slots_state"] 存档节点）。
    出参：技能槽列表 [{"slot": "basic", "skill_id": "..."}, ...]：
      - 优先 slots 键（basic 固定第 1 位 → active 排序 → passive/trigger 槽）；
      - slots 缺省/畸形 → 回退 active_order + passive + trigger 三键并集
        （老存档兼容，P-1）；
      - basic 槽 skill_id=None（缺普攻占位）→ 保留占位条目（P-1）；
      - 条目防御性清洗（slot 类型非法/非 Mapping → 跳过），纯函数不抛异常；
      - 行内含合法 "level"（非 bool int）→ 保留（套装技能行携带等级，P-7）。
    """
    if not isinstance(snapshot, Mapping):
        return []
    slots = snapshot.get("slots")
    if isinstance(slots, list):
        cleaned: List[Dict[str, Any]] = []
        for item in slots:
            if not isinstance(item, Mapping):
                continue
            kind = item.get("slot")
            sid = item.get("skill_id")
            if isinstance(kind, str) and kind in _SLOT_KIND_ORDER:
                row: Dict[str, Any] = {
                    "slot": kind, "skill_id": sid if isinstance(sid, str) else None,
                }
                lv = item.get("level")
                if isinstance(lv, int) and not isinstance(lv, bool):
                    row["level"] = lv
                cleaned.append(row)
        return cleaned
    # 回退：active_order + passive + trigger 三键并集（老存档兼容，P-1）
    fallback: List[Dict[str, Any]] = []
    active_order = snapshot.get("active_order")
    if isinstance(active_order, (list, tuple)):
        for sid in active_order:
            if isinstance(sid, str) and sid:
                fallback.append({"slot": SLOT_ACTIVE, "skill_id": sid})
    for key, kind in ((SLOT_PASSIVE, SLOT_PASSIVE), (SLOT_TRIGGER, SLOT_TRIGGER)):
        rows = snapshot.get(key)
        if isinstance(rows, (list, tuple)):
            for row in rows:
                if isinstance(row, Mapping) and isinstance(row.get("skill_id"), str):
                    fallback.append({"slot": kind, "skill_id": row["skill_id"]})
    return fallback


def available_skills(ctx: Mapping[str, Any]) -> List[str]:
    """进战斗消费入口：ctx["skill_slots_state"] → 战斗可用技能 id 列表。

    出参：技能 id 列表（basic 固定第 1 位 → active 排序 → passive/trigger 槽
    库序；basic 缺位 → 首个 None 占位；passive/trigger 槽技能**可见**——
    被动生效挂点消费，P-4）。缺省/畸形快照 → []（确定性兜底，P-5）。
    """
    return [
        str(row.get("skill_id")) if row.get("skill_id") is not None else ""
        for row in slots_from_snapshot(_snapshot_of(ctx))
    ]


def is_slot_equipped(ctx: Mapping[str, Any], skill_id: str) -> bool:
    """技能是否在装配内（未装配拒绝判定，P-2/P-3）。

    判定口径（§1.4 行动位 + §1.5 装配快照）：
      - basic/active 槽命中 → True（行动位技能可施放）；
      - passive/trigger 槽命中 → False（不占行动位，不可直接施放 [L64-65]，
        经被动挂点生效 P-4）；
      - 未装配 / 未知技能 / 畸形快照 → False。
    """
    if not isinstance(skill_id, str) or not skill_id:
        return False
    for row in slots_from_snapshot(_snapshot_of(ctx)):
        if row.get("skill_id") == skill_id and row.get("slot") in _ACTION_SLOTS:
            return True
    return False


def battle_equipped_skills(ctx: Mapping[str, Any]) -> Dict[str, Any]:
    """战斗可用技能 id → 技能 def 映射（{skill_id: SkillDef|raw dict}）。

    ctx["skills"] 同源解析（批13 注册态无关注入，_table_from_registry 保证
    Mapping.get 契约）；缺省 {}（系统未启用/无技能表兜底，不抛异常）。
    """
    out: Dict[str, Any] = {}
    table = ctx.get("skills")
    if not isinstance(table, Mapping):
        return out
    for row in slots_from_snapshot(_snapshot_of(ctx)):
        sid = row.get("skill_id")
        if isinstance(sid, str) and sid and sid in table:
            out[sid] = table[sid]
    return out


def equipped_slot_kind(ctx: Mapping[str, Any], skill_id: str) -> Optional[str]:
    """技能所在槽类型（basic/active/passive/trigger；未装配 → None）。

    展示/审计用：命令层可据此提示「被动技能不可主动施放」等；判定与
    is_slot_equipped 同源（slots_from_snapshot 防御清洗）。
    """
    if not isinstance(skill_id, str) or not skill_id:
        return None
    for row in slots_from_snapshot(_snapshot_of(ctx)):
        if row.get("skill_id") == skill_id:
            return str(row.get("slot") or "")
    return None


__all__ = [
    "SKILL_SLOTS_STATE_KEY",
    "SET_SKILLS_STATE_KEY",
    "EQUIP_SKILLS_STATE_KEY",
    "SLOT_BASIC",
    "SLOT_ACTIVE",
    "SLOT_PASSIVE",
    "SLOT_TRIGGER",
    "PASSIVE_PROC_HOOK",
    "TRIGGER_PROC_HOOK",
    "set_skill_rows",
    "source_skill_rows",
    "with_set_skills",
    "with_source_skills",
    "set_skill_levels",
    "slots_from_snapshot",
    "available_skills",
    "is_slot_equipped",
    "battle_equipped_skills",
    "equipped_slot_kind",
]
