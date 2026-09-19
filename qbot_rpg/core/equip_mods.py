"""批26 · α组（装备侧）：装备附加引擎（qbot_rpg/core/equip_mods.py）。

依据：`CakeGame字段差距_补漏.md` §一 组 α（装备附加Re《核心配置》《品质部位筛选》）
逐条语义能力落地（**不照搬其 DB/INI/插件实现**）。本文件是四类装备附加字段的
**引擎侧唯一落点**（沿既有装配口径，不另造技能表）：

  · α1 `grant_skills`  list<obj>{skill, level} —— 穿戴时获得、卸下时收回。
    「其它来源」技能（消耗品 `learn_skill` 写 `persistent_state.skill_slots`、
    锻造套装写 `set_skills`、职业装配过滤）**各占独立来源容器**；本模块只维护
    装备来源容器 `persistent_state.equip_skills`，卸下只清本容器 → **其它来源
    不被收走**（来源计数语义，见 recompute_equip_skills docstring）。
  · α3 `skill_amp`     list<obj>{skill, type, value} —— 按技能累计；`damage` 类
    按 `1 + 总计/100` 作伤害乘数，`cooldown` 类按同一比率作用于冷却时长。
    上下限**不硬编码在本文件**：默认值在 content/forge_settings（settings.forge
    段既有可配处），校验器按配置红拦。
  · α5 `attack_override` obj{enabled, skill, chance} —— 普攻入口按 chance 概率
    替换为指定技能（RNG 由调用方经 ctx["rng"] 注入，引擎既有单源）。
  · α6 `job_override`  obj{job, level_reset, name_override} —— 穿戴期职业覆盖
    （含等级重置/显示名替换），卸下还原；与 jobs.transform.transform_to 的
    战斗内形态切换不是一回事。

【与 α1/α3/α5 的叠加顺序】（α6 docstring 同口径复述）：
  穿戴/卸下 → sync_equip_mods 一次重算：
    ① α1 装备来源技能容器（recompute_equip_skills）
    ② α6 职业覆盖（recompute_job_override，改 player.job_id/level 与显示名）
  战斗/指令期叠加顺序（互不覆盖、各自独立读点）：
    α5 普攻替换（battle_commands._attack_action，最外层：先决定本回合打哪个技能）
      → α3 增幅（battle._resolve_combo_action，作用于最终选定的 skill_id）
      → α1 技能可用集（skill_slots_battle 并集，只决定「能不能放」）
  α6 只改职业务/等级/显示名，不改技能集本身（技能集过滤仍走 skill_slots 快照）。

【工程补白 · 显式标注】（契约/文档未显式定义处的实现口径，不冒充文档行号）：
  P-1  装备来源技能容器落 `player.persistent_state`（Player 字段，随存档往返），
       经装配层镜像到 `ctx["equip_skills"]`；skill_slots_battle 在装配快照之上
       并集该容器（与 set_skills 完全同一路径）。
  P-2  同技能被多件装备同时授予：等级取各来源**最大值**（不叠乘）；来源计数
       = 授予槽位列表（`equip_skill_sources`）。卸下其一 → 重算后该技能仍在
       （来源列表缩短），全卸 → 容器移除该技能。
  P-3  穿戴行解析与 EquipmentEngine.aggregate_bonus 同源：按
       `player["equipment"]` 各槽 item_id → `ctx["items"]` 定义；槽序取
       sorted(equipment)（确定性）。无 items 注册表/缺定义 → 该槽跳过。
  P-4  skill_amp `type` 只做 `damage`/`cooldown` 两项——「熟练」类：我们有
       **职业熟练度**（core/proficiency，按职业的 exp/level），**无 per-技能熟练**，
       故不实现（存量差异如实登记，见字段元数据 help）。超限值由校验器红拦
       （门禁只严不宽；钳制会静默改写作者意图），本文件不做二次钳制。
  P-5  α5 替换技能须同时是**本玩家装备来源已授予**的技能（grant_skills 成立）
       才生效；不成立 → 不替换（不硬拦，校验层黄提示）。chance 非 1..100 →
       不替换（校验器红拦）。候选按槽序首个命中者取（确定性）。
  P-6  α6 多件装备同时给 job_override：按槽序取首个（确定性），不叠乘。
       base（原始 job_id/level）在首次覆盖时快照，覆盖切换/解除都以它为还原源；
       同槽换装 A→B 不丢 base。

铁律：零 NoneBot import；core 层零 import content（物品定义经 ctx 注入）；
纯函数确定性（除显式注入的 RNG 外不引入随机）；完整类型标注（typing 3.9 兼容）；
零定时器/零睡眠；不写真实内容包。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.core.equipment import offhand_penalized_slots_of_ctx

__all__ = [
    "EQUIP_SKILLS_STATE_KEY",
    "EQUIP_SKILL_SOURCES_KEY",
    "EQUIP_JOB_OVERRIDE_KEY",
    "JOB_NAME_OVERRIDE_KEY",
    "AMP_DAMAGE",
    "AMP_COOLDOWN",
    "AMP_TYPES",
    "raw_def",
    "items_table",
    "worn_slots",
    "grant_skills_of",
    "skill_amp_entries_of",
    "job_override_of",
    "attack_override_of",
    "recompute_equip_skills",
    "equip_skills_of",
    "skill_amp_table",
    "amp_value",
    "resolve_attack_override",
    "recompute_job_override",
    "sync_equip_mods",
]

# ---------------------------------------------------------------------------
# 存档 / 上下文键（P-1）
# ---------------------------------------------------------------------------
EQUIP_SKILLS_STATE_KEY: str = "equip_skills"
EQUIP_SKILL_SOURCES_KEY: str = "equip_skill_sources"
EQUIP_JOB_OVERRIDE_KEY: str = "equip_job_override"
JOB_NAME_OVERRIDE_KEY: str = "job_name_override"

# α3 增幅类型（P-4：只做伤害/冷却两项；「熟练」无对应概念，不实现）
AMP_DAMAGE: str = "damage"
AMP_COOLDOWN: str = "cooldown"
AMP_TYPES: Tuple[str, ...] = (AMP_DAMAGE, AMP_COOLDOWN)

# α5 触发概率取值域（百分比，1..100；0/缺省 = 不替换）
_CHANCE_MIN: int = 1
_CHANCE_MAX: int = 100


# ---------------------------------------------------------------------------
# 通用读取（dict / Def 双形态；core 零 import content）
# ---------------------------------------------------------------------------
def raw_def(entry: Any) -> Mapping[str, Any]:
    """物品定义归一（Mapping 直返；Def 对象取 .raw；其余 → 空 Mapping）。"""
    if isinstance(entry, Mapping):
        return entry
    raw = getattr(entry, "raw", None)
    return raw if isinstance(raw, Mapping) else {}


def items_table(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """ctx["items"] 注册表（非 Mapping → 空，缺表按无定义处理）。"""
    t = ctx.get("items")
    return t if isinstance(t, Mapping) else {}


def _item_def_of(items: Mapping[str, Any], item_id: str) -> Mapping[str, Any]:
    """物品 id → 定义（查无/非 Mapping → 空）。"""
    if not item_id:
        return {}
    return raw_def(items.get(item_id))


def _player(item: Any) -> Mapping[str, Any]:
    """玩家状态只读视图（Mapping 直返；其余 → 空）。"""
    return item if isinstance(item, Mapping) else {}


def _int_or_none(value: Any) -> Optional[int]:
    """非 bool 整数读取（其余 → None）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def worn_slots(player: Any) -> List[Tuple[str, str]]:
    """已穿戴槽位 → [(slot_id, item_id)]（槽序 sorted，确定性；P-3）。

    只读 `player["equipment"]`；槽实例 dict / 对象双形态取 item_id。
    """
    p = _player(player)
    equipment = p.get("equipment")
    if not isinstance(equipment, Mapping):
        return []
    out: List[Tuple[str, str]] = []
    for slot_id in sorted(str(k) for k in equipment.keys()):
        slot_obj = equipment.get(slot_id)
        if isinstance(slot_obj, Mapping):
            iid = slot_obj.get("item_id")
        else:
            iid = getattr(slot_obj, "item_id", None)
        sid = str(iid or "")
        if sid:
            out.append((slot_id, sid))
    return out


def _worn_defs(ctx: Mapping[str, Any], player: Any) -> List[Tuple[str, Mapping[str, Any]]]:
    """已穿戴件 → [(slot_id, item_def)]（缺定义跳过；P-3）。

    批38 · H7 副手：处于副手折算/失活槽的件**不参与** α 组四类（技能授予/增幅/普攻替换/
    职业覆盖）——在此**唯一已穿戴件枚举点**过滤一次，四处同时失活。开关关闭 → 空集，
    与既有实现逐字段一致（`core/equipment.offhand_penalized_slots_of_ctx` 同源判定）。
    """
    items = items_table(ctx)
    penalized = offhand_penalized_slots_of_ctx(ctx, player)
    out: List[Tuple[str, Mapping[str, Any]]] = []
    for slot_id, item_id in worn_slots(player):
        if slot_id in penalized:
            continue
        d = _item_def_of(items, item_id)
        if d:
            out.append((slot_id, d))
    return out


# ---------------------------------------------------------------------------
# α1 装备赋予技能
# ---------------------------------------------------------------------------
def grant_skills_of(item_def: Any) -> List[Tuple[str, int]]:
    """物品定义 `grant_skills` → [(skill_id, level)]（清洗：缺 skill/level<1 丢弃）。

    形态：list<obj>{skill: <skills 引用>, level: int ≥ 1}；缺省/非法 → []。
    引用存在性/等级下限由校验器红拦；此处防御性跳过（引擎不越权校验）。
    """
    d = raw_def(item_def)
    rows = d.get("grant_skills")
    if not isinstance(rows, (list, tuple)):
        return []
    out: List[Tuple[str, int]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sid = row.get("skill")
        lv = _int_or_none(row.get("level"))
        if isinstance(sid, str) and sid and lv is not None and lv >= 1:
            out.append((sid, lv))
    return out


def recompute_equip_skills(
    player: MutableMapping[str, Any],
    ctx: Mapping[str, Any],
) -> Dict[str, int]:
    """重算「装备来源技能」容器（α1；穿/卸/换装每次全量重算）。

    落点：`player["persistent_state"]["equip_skills"]` = {skill_id: level}；
          `player["persistent_state"]["equip_skill_sources"]` = {skill_id: [slot_id,...]}。
    来源计数语义（P-2）：本容器**只**承载装备来源——卸下装备只可能让本容器少一项，
    不会触碰 `skill_slots`（消耗品学习）/`set_skills`（锻造套装）等其它来源；某技能
    是否仍可用由装配层对「各来源容器取并集」决定（skill_slots_battle）。同技能多件
    授予 → 等级取最大、来源列槽位。

    入参：player 玩家状态（可变 dict）；ctx（读 ctx["items"]，物品定义注入）。
    出参：本次重算后的 {skill_id: level}（同一份写回存档节点）。
    """
    levels: Dict[str, int] = {}
    sources: Dict[str, List[str]] = {}
    for slot_id, d in _worn_defs(ctx, player):
        for sid, lv in grant_skills_of(d):
            if lv > levels.get(sid, 0):
                levels[sid] = lv
            sources.setdefault(sid, []).append(slot_id)
    ps = player.get("persistent_state")
    if levels:
        if not isinstance(ps, MutableMapping):
            ps = {}
            player["persistent_state"] = ps
        ps[EQUIP_SKILLS_STATE_KEY] = dict(levels)
        ps[EQUIP_SKILL_SOURCES_KEY] = {k: list(v) for k, v in sources.items()}
    elif isinstance(ps, MutableMapping):
        # 无装备来源技能 → 不写空容器（不带新字段的既有行为逐字段一致，回归对拍）
        ps.pop(EQUIP_SKILLS_STATE_KEY, None)
        ps.pop(EQUIP_SKILL_SOURCES_KEY, None)
    return dict(levels)


def equip_skills_of(player: Any) -> Dict[str, int]:
    """读装备来源技能容器（缺省/畸形 → {}；只读不写）。"""
    p = _player(player)
    ps = p.get("persistent_state")
    if not isinstance(ps, Mapping):
        return {}
    node = ps.get(EQUIP_SKILLS_STATE_KEY)
    if not isinstance(node, Mapping):
        return {}
    out: Dict[str, int] = {}
    for sid, lv in node.items():
        v = _int_or_none(lv)
        if isinstance(sid, str) and sid and v is not None and v >= 1:
            out[sid] = v
    return out


# ---------------------------------------------------------------------------
# α3 装备增幅技能
# ---------------------------------------------------------------------------
def skill_amp_entries_of(item_def: Any) -> List[Tuple[str, str, int]]:
    """物品定义 `skill_amp` → [(skill_id, amp_type, value)]（清洗非法项）。

    形态：list<obj>{skill, type, value}；type ∈ AMP_TYPES、value 为非 bool int、
    skill 非空 str 才收；缺省/非法 → 跳过（枚举/上下限红拦归校验器）。
    """
    d = raw_def(item_def)
    rows = d.get("skill_amp")
    if not isinstance(rows, (list, tuple)):
        return []
    out: List[Tuple[str, str, int]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sid = row.get("skill")
        kind = row.get("type")
        val = _int_or_none(row.get("value"))
        if (isinstance(sid, str) and sid and isinstance(kind, str)
                and kind in AMP_TYPES and val is not None):
            out.append((sid, kind, val))
    return out


def skill_amp_table(player: Any, ctx: Mapping[str, Any]) -> Dict[str, Dict[str, Dict[str, int]]]:
    """已穿戴装备增幅汇总 → {"player": {skill_id: {amp_type: 总计}}}（α3）。

    总计 = 各穿戴件同 (skill, type) 的 value 求和（不钳制——超限归校验器红拦）。
    无穿戴/无增幅 → {}（确定性空表；战斗侧据此零改动）。
    """
    acc: Dict[str, Dict[str, int]] = {}
    for _slot, d in _worn_defs(ctx, player):
        for sid, kind, val in skill_amp_entries_of(d):
            node = acc.setdefault(sid, {})
            node[kind] = node.get(kind, 0) + val
    if not acc:
        return {}
    return {"player": acc}


def amp_value(
    table: Any,
    side: str,
    skill_id: str,
    amp_type: str,
) -> int:
    """从 skill_amp_table 读某侧/技能/类型的增幅总计（缺省 → 0；只读纯函数）。"""
    if not isinstance(table, Mapping):
        return 0
    side_node = table.get(side)
    if not isinstance(side_node, Mapping):
        return 0
    skill_node = side_node.get(skill_id)
    if not isinstance(skill_node, Mapping):
        return 0
    v = _int_or_none(skill_node.get(amp_type))
    return v if v is not None else 0


# ---------------------------------------------------------------------------
# α5 替换普攻
# ---------------------------------------------------------------------------
def attack_override_of(item_def: Any) -> Optional[Dict[str, Any]]:
    """物品定义 `attack_override` → {enabled, skill, chance}（清洗后；不成立 → None）。

    形态：obj{enabled: bool, skill: <skills 引用>, chance: int 0~100}；缺省/非法 → None。
    """
    d = raw_def(item_def)
    node = d.get("attack_override")
    if not isinstance(node, Mapping):
        return None
    skill = node.get("skill")
    if not isinstance(skill, str) or not skill:
        return None
    chance = _int_or_none(node.get("chance"))
    return {
        "enabled": bool(node.get("enabled")),
        "skill": skill,
        "chance": chance if chance is not None else 0,
    }


def _resolve_rng(ctx: Mapping[str, Any]) -> Any:
    """RNG 解析（引擎既有单源；不新引入随机源，与 use_commands._resolve_rng 同口径）。"""
    r = ctx.get("rng")
    if r is not None and hasattr(r, "randint"):
        return r
    return random


def resolve_attack_override(
    ctx: Mapping[str, Any],
    player: Any = None,
    rng: Any = None,
) -> Optional[str]:
    """普攻替换判定（α5）→ 命中返回替换技能 id；不替换返回 None。

    兜底：`player` 缺省取 ctx["player"]；`rng` 缺省取 ctx["rng"]（再兜底 random）。
    命中条件（P-5）：
      1) 穿戴件 `attack_override.enabled` 为 True、skill 非空、chance ∈ 1..100；
      2) 该 skill 同时是本玩家**装备来源已授予**技能（grant_skills 成立）；
      3) randint(1,100) ≤ chance（引擎既有 RNG，确定性可注入）。
    候选按槽序取首个（确定性）。chance=0/缺省/不满足 → None：行为与现状逐字段一致。
    """
    p = player if isinstance(player, Mapping) else ctx.get("player")
    if not isinstance(p, Mapping):
        return None
    granted = equip_skills_of(p)
    chosen: Optional[Tuple[str, int]] = None
    for _slot, d in _worn_defs(ctx, p):
        ov = attack_override_of(d)
        if ov is None or not ov["enabled"]:
            continue
        if ov["skill"] not in granted:
            continue
        ch = ov["chance"]
        if not isinstance(ch, int) or ch < _CHANCE_MIN or ch > _CHANCE_MAX:
            continue
        chosen = (ov["skill"], ch)
        break
    if chosen is None:
        return None
    r = rng if (rng is not None and hasattr(rng, "randint")) else _resolve_rng(ctx)
    roll = int(r.randint(_CHANCE_MIN, _CHANCE_MAX))
    return chosen[0] if roll <= chosen[1] else None


# ---------------------------------------------------------------------------
# α6 替换职业
# ---------------------------------------------------------------------------
def job_override_of(item_def: Any) -> Optional[Dict[str, Any]]:
    """物品定义 `job_override` → {job, level_reset, name_override}（不成立 → None）。

    形态：obj{job: <jobs 引用>, level_reset: bool, name_override: str}；job 非空才有效。
    """
    d = raw_def(item_def)
    node = d.get("job_override")
    if not isinstance(node, Mapping):
        return None
    job = node.get("job")
    if not isinstance(job, str) or not job:
        return None
    name = node.get("name_override")
    return {
        "job": job,
        "level_reset": bool(node.get("level_reset")),
        "name_override": name if isinstance(name, str) else "",
    }


def recompute_job_override(
    player: MutableMapping[str, Any],
    ctx: Mapping[str, Any],
) -> Dict[str, Any]:
    """重算穿戴期职业覆盖（α6；穿/卸/换装每次全量重算）。

    语义（P-6）：穿戴件带 `job_override` → `player["job_id"]` 覆盖为替换职业；
    `level_reset` 为真 → `player["level"]` 置 1；`name_override` 非空 → 写
    `persistent_state.job_name_override`（装配层据此改显示名）。全部卸下 → 还原
    首次覆盖时快照的 base（job_id/level），并清显示名覆盖。base 只在首次覆盖时
    记录：A→B 换装不丢 base、等级重置不丢原等级。

    与 jobs.transform.transform_to 不同：那是战斗内形态切换（战斗快照内），
    本项改的是玩家常态职业/等级/显示名，随穿脱生效/还原。

    入参：player 玩家状态（可变 dict）；ctx（读 ctx["items"]；写 ctx 镜像）。
    出参：当前生效的覆盖 dict（无 → {}）。
    """
    chosen: Optional[Dict[str, Any]] = None
    for _slot, d in _worn_defs(ctx, player):
        ov = job_override_of(d)
        if ov is not None:
            chosen = ov
            break
    ps = player.get("persistent_state")
    if not isinstance(ps, MutableMapping):
        ps = None
    node = ps.get(EQUIP_JOB_OVERRIDE_KEY) if ps is not None else None
    base_job: Optional[str] = None
    base_level: Optional[int] = None
    if isinstance(node, Mapping):
        bj = node.get("base_job_id")
        bl = _int_or_none(node.get("base_level"))
        base_job = bj if isinstance(bj, str) and bj else None
        base_level = bl
    if chosen is None:
        # 无覆盖：有 base 则还原并清理（无 persistent_state 即无 base → 不动存档）
        if base_job is not None:
            player["job_id"] = base_job
        if base_level is not None:
            player["level"] = base_level
        if ps is not None:
            ps.pop(EQUIP_JOB_OVERRIDE_KEY, None)
            ps.pop(JOB_NAME_OVERRIDE_KEY, None)
        _mirror_job_ctx(ctx, player, None)
        return {}
    # 首次覆盖：快照 base
    if base_job is None:
        cur_job = player.get("job_id")
        base_job = str(cur_job) if isinstance(cur_job, str) and cur_job else ""
    if base_level is None:
        cur_lv = _int_or_none(player.get("level"))
        base_level = cur_lv if cur_lv is not None else 1
    player["job_id"] = chosen["job"]
    if chosen["level_reset"]:
        player["level"] = 1
    else:
        player["level"] = base_level
    name_override = str(chosen.get("name_override") or "")
    applied = {
        "job": chosen["job"],
        "level_reset": bool(chosen["level_reset"]),
        "name_override": name_override,
        "base_job_id": base_job,
        "base_level": base_level,
    }
    if ps is None:
        ps = {}
        player["persistent_state"] = ps
    ps[EQUIP_JOB_OVERRIDE_KEY] = dict(applied)
    if name_override:
        ps[JOB_NAME_OVERRIDE_KEY] = name_override
    else:
        ps.pop(JOB_NAME_OVERRIDE_KEY, None)
    _mirror_job_ctx(ctx, player, name_override or None)
    return applied


def _mirror_job_ctx(
    ctx: Mapping[str, Any],
    player: Mapping[str, Any],
    name_override: Optional[str],
) -> None:
    """把职业/等级/显示名镜像回当前指令 ctx（同拍读一致；非可变 ctx → 跳过）。

    还原（name_override=None）时不动 ctx["job_name"]——它在下一次装配按
    persistent_state + 还原后的 job_id 重算（本函数取不到 registry，不臆造名字）。
    """
    if not isinstance(ctx, MutableMapping):
        return
    job = player.get("job_id")
    if isinstance(job, str) and job:
        ctx["job_id"] = job
    lv = _int_or_none(player.get("level"))
    if lv is not None:
        ctx["level"] = lv
    if name_override:
        ctx["job_name"] = name_override


# ---------------------------------------------------------------------------
# 穿 / 卸 / 换装统一入口（装配层调用一次）
# ---------------------------------------------------------------------------
def sync_equip_mods(
    ctx: Mapping[str, Any],
    player: MutableMapping[str, Any],
) -> Dict[str, Any]:
    """装备附加统一重算入口（穿/卸/换装后调用一次；α1 + α6）。

    步骤（顺序即叠加顺序，见模块 docstring）：
      ① α1 recompute_equip_skills（装备来源技能容器）；
      ② α6 recompute_job_override（职业覆盖/还原）；
      ③ 镜像 `ctx["equip_skills"]`（供 skill_slots_battle 并集装配）。
    返回 {equip_skills, job_override}（调用方可忽略；幂等，重复调用同值）。
    """
    skills = recompute_equip_skills(player, ctx)
    job_override = recompute_job_override(player, ctx)
    if isinstance(ctx, MutableMapping):
        if skills:
            ctx[EQUIP_SKILLS_STATE_KEY] = dict(skills)
        else:
            ctx.pop(EQUIP_SKILLS_STATE_KEY, None)
    return {"equip_skills": skills, "job_override": job_override}
