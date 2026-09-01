"""M13 技能库·批3·路3A：技能位装配（qbot_rpg/core/skill_slots.py）。

文件名：qbot_rpg/core/skill_slots.py
创建时间：2026-09-02
作者：Hermes 子agent-3A（M13 技能库实现组批3路3A：并发同仓，仅新建本文件 +
  tests/unit/test_skill_slots.py；不改动兄弟路文件——路3B 独占 test_demo
  skills.json 扩展、路3C 独占战斗接线，本文件只读消费 ctx 注入）

功能描述：技能位装配（6a §1.5 技能位与装配 / §4.3 绑定规则）——纯函数/引擎层：
  1) SLOT_STATE_KEY        存档键常量（player.persistent_state["skill_slots"]，
     1g1c/1g3 承接：装配结果落玩家存档，每次进战斗按装配快照生成可用技能列表）
  2) SlotKind 协议         技能条目访问器协议（core 层不 import content 的
     G0 约束：技能数据经 ctx 注入，访问器由消费方按协议实现——SkillDef 天然
     满足；raw dict 条目不满足时本层自动用 _RawSkillAdapter 兜底）
  3) skill_type/skill_id   raw 条目轻量访问器（type 缺省 active=TC-02 裁决；
     basic 必须显式，与 skill_models.DEFAULT_TYPE 同口径）
  4) assemble_slots(skills, player_ctx)  装配主入口（TC-04）：
     - basic 固定第 1 位（恰 1 个；0 个兜底插占位 skill_id=None；多个按
       job_restrict 命中当前职业者优先，仍多 → 首个）
     - active 可排序（装配快照 active_order 显式给出玩家顺序；未装配过 →
       缺省排序 job_restrict 命中者优先、其余按库序，确定性兜底）
     - passive 槽 / trigger 槽：装配位不占行动位（槽位类型标记 + 技能 id）
     - job_restrict 装配过滤（§4.3-3：通用技能全职业可见，非当前职业排除）
     - 未知 type → 不进任何槽（防御性跳过，V-11 属校验器职责）
     - 返回装配快照 dict（含 slots 列表 + active_order + passive/trigger 槽）
  5) save_slots_to_state(player, snapshot)  装配结果落存档接口（1g1c/1g3）：
     挂 player.persistent_state[SLOT_STATE_KEY]，惰性创建 + 挂回（对齐
     qbot_rpg/assembly/context.py _ps_init 模式）；幂等（重复保存覆盖）
  6) load_slots_from_state(player)  从存档读装配快照（1g1c/1g3 承接）：
     缺省 → 空快照骨架（非 None，确定性兜底）；存档畸形（非 dict）→
     归一空快照（防御读取，不抛异常）
  7) apply_job_form(snapshot, skills)  形态技替换技能位接口（F17 / [L88] /
     TC-06）——仅留接口注释与占位实现（当前原样返回快照），实现归批7/批15
     （职业变换 transform 形态激活时 job_form 匹配技能替换对应技能位）

依据：
  - docs/细化/细化_6a_技能库契约.md（349 行 v1.0）：
    §1.4 四类时机（basic 固定第 1 位 / active 可排序 / passive·trigger 装配槽
    不占行动位）；§1.5 技能位与装配（装配结果落玩家存档 1g1c/1g3；形态技能
    [L88] TC-06）；§4.3 绑定规则（装配过滤：职业限制自动过滤 + 通用技能全
    职业可见）；TC-02（type 缺省 active，basic 必须显式）；TC-04（四类时机
    门禁与技能位：basic 固定第 1 位且仅 1 位 / active 可排序 / passive·trigger
    进装配槽不占行动位）；TC-06（形态技替换技能位——本文件仅留接口）；
    §7 存档影响（装配结果落玩家存档）。
  - docs/m13_6a摸底.md：G5（技能位装配无存档——basic 固定第 1 位仅展示排序，
    无装配快照字段、无 job_form 替换 → 本文件收口装配快照 + 存档接口）；
    §5.2（装配无持久化 / 无槽位概念 → 本文件补槽位概念）。
  - 批1/批2 已落盘：qbot_rpg/content/skill_models.py（SkillDef 24 字段访问器，
    DEFAULT_TYPE="active" 等常量）、qbot_rpg/content/skill_validator.py
    （validate_skills V-1~V-7）、content/test_demo/skills.json（4 条示例：
    basic_attack / power_strike / stone_guard / flame_burst）。
  - 模式参考：qbot_rpg/core/forge_job.py（模块级纯函数集合 + 缺省兜底 +
    构造器注入）、qbot_rpg/core/fishing.py（ctx 注入 + _ps_init 惰性挂回）、
    qbot_rpg/assembly/context.py _ps_init（persistent_state 键惰性挂回）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  P-1  core 层不 import content（G0 单向依赖：content→data，core 不得依赖
       content）：本文件不 import skill_models；技能条目访问经 SlotKind 协议
       注入（SkillDef / 任意同协议对象），raw dict 由 _RawSkillAdapter 兜底，
       type 缺省 active 口径与 skill_models.DEFAULT_TYPE 常量同值但本地镜像。
  P-2  存档键形态：persistent_state["skill_slots"] = dict 快照（slots 列表 +
       active_order + passive/trigger 槽），与 1g1c/1g3 存档承接；快照本身
       可 JSON 序列化（纯 str/None/list/dict），对齐 data/battle.py 双轨
       快照 dict 口径（P1-3 自述）。
  P-3  basic 恰 1 兜底：契约 V-7（普攻每职业恰 1）是校验器红拦职责，引擎层
       不重复拦截——0 个 basic → 装配快照 basic 槽 skill_id=None 占位（战斗
       层可据此提示缺普攻，不抛异常）；多个 basic → 按 job_restrict 命中当前
       职业者优先，仍多取库序首个（确定性）。
  P-4  active 排序兜底：存档无 active_order（首次装配/旧存档）→ 确定性缺省
       排序：job_restrict 命中当前职业者优先（职业限定技能先排），其余按
       库序（skills 表原始顺序）；玩家在编辑器/指令侧拖拽后写 active_order
       即覆盖缺省。
  P-5  装配过滤（§4.3-3）：job_restrict 非空且不含当前职业 → 不装配（排除）；
       job_restrict 空 = 通用技能全职业可见；player_ctx 缺 job_id → 按通用
       口径放行（不确定职业时不误伤通用技能，确定性兜底）。
  P-6  passive/trigger 槽列表形态：[{"slot": "passive", "skill_id": "..."}, ...]
       按库序收集（槽位内容不排序，职业过滤同 P-5）；空槽不产出占位条目。
  P-7  job_form 占位：apply_job_form 当前原样返回快照（接口注释完整），
       实现归批7/批15（职业变换 transform 激活时替换对应技能位，TC-06）。

铁律：零 NoneBot import（G0 门禁）；core 层只依赖 data（技能数据经 ctx 注入，
零 import content）；纯函数确定性（同刻同参必同值）；完整类型标注（typing
3.9 兼容）；零定时器/零睡眠（本文件不含任何 sleep/定时器字面量）；不引入
随机；不 git commit；只写本文件 + 自己的测试。
"""
from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    cast,
)

# =====================================================================================
# 常量
# =====================================================================================

# 存档键（§7 装配结果落玩家存档；1g1c/1g3 承接）
SLOT_STATE_KEY: str = "skill_slots"

# 槽位类型（§1.4/§1.5：basic 固定第 1 位 / active 可排序 / passive·trigger 装配槽）
SLOT_BASIC: str = "basic"
SLOT_ACTIVE: str = "active"
SLOT_PASSIVE: str = "passive"
SLOT_TRIGGER: str = "trigger"

# 四类时机（F08；type 缺省 active=TC-02 裁决，basic 必须显式——镜像
# content.skill_models.DEFAULT_TYPE，G0 本地镜像不 import，P-1）
DEFAULT_TYPE: str = "active"

# 装配快照缺省（确定性兜底：空槽位结构，P-3/P-6）
_EMPTY_SNAPSHOT: Dict[str, Any] = {
    "slots": [],
    "active_order": [],
    "passive": [],
    "trigger": [],
    "version": 1,
}

# 槽位类型顺序（basic 固定第 1 位 → active 可排序 → passive/trigger 槽，§1.5）
_SLOT_KIND_ORDER: Tuple[str, ...] = (SLOT_BASIC, SLOT_ACTIVE, SLOT_PASSIVE, SLOT_TRIGGER)


# =====================================================================================
# SlotKind 协议（G0 注入访问器；SkillDef 天然满足）
# =====================================================================================


class SlotKind(Protocol):
    """技能条目访问器协议（core 层不 import content 的 G0 约束，P-1）。

    消费方（装配层/战斗接线）注入任意满足本协议的技能定义对象：
      - content.skill_models.SkillDef 天然满足（id/name 由 BaseDef 承载，
        type/job_restrict/job_form 为属性访问器）；
      - raw dict 条目不满足协议（dict 无 .type 属性）→ 本模块 _RawSkillAdapter
        自动兜底适配。
    """

    @property
    def id(self) -> str:  # noqa: A003
        """技能 id（全库唯一，F01）。"""
        ...

    @property
    def type(self) -> str:
        """四类时机 basic/active/passive/trigger（F08；缺省 active）。"""
        ...

    @property
    def job_restrict(self) -> Tuple[str, ...]:
        """职业限制（F16；空 = 通用技能全职业可见）。"""
        ...

    @property
    def job_form(self) -> Optional[str]:
        """形态技（F17；None = 非形态技；替换语义归 apply_job_form）。"""
        ...


# =====================================================================================
# raw 条目轻量访问器（防御性读取，P-1）
# =====================================================================================


def skill_type(entry: Mapping[str, Any]) -> str:
    """raw 技能条目的 type（F08；缺省 active=TC-02 裁决）。

    与 content.skill_models.SkillDef.type 同口径（G0 不 import content，P-1）：
    type 缺失 → active（TC-02：仅核心字段按 active 处理，basic 必须显式）；
    type 显式给出（含未知值）→ 原样透传（访问器不做枚举校验——枚举校验归
    V-13 校验器；未知 type 由 assemble_slots 防御性跳过）。
    """
    v = entry.get("type")
    return v if isinstance(v, str) else DEFAULT_TYPE


def skill_id(entry: Mapping[str, Any]) -> Optional[str]:
    """raw 技能条目的 id（F01；非字符串/空 → None，装配时跳过）。"""
    v = entry.get("id")
    return v if isinstance(v, str) and v else None


def skill_job_restrict(entry: Mapping[str, Any]) -> Tuple[str, ...]:
    """raw 技能条目的 job_restrict（F16；非 list → 空 = 通用技能）。"""
    v = entry.get("job_restrict")
    return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()


def skill_job_form(entry: Mapping[str, Any]) -> Optional[str]:
    """raw 技能条目的 job_form（F17；非字符串 → None = 非形态技）。"""
    v = entry.get("job_form")
    return v if isinstance(v, str) and v else None


class _RawSkillAdapter:
    """raw dict 条目适配 SlotKind 协议（P-1 兜底：ctx 注入 raw dict 也可装配）。

    只读包装：不拷贝、不改写原条目；访问器口径与 SkillDef 同源（type 缺省
    active / job_restrict 空元组 / job_form None）。
    """

    __slots__ = ("_entry",)

    def __init__(self, entry: Mapping[str, Any]) -> None:
        self._entry = entry

    @property
    def id(self) -> str:  # noqa: A003
        v = skill_id(self._entry)
        return v if v is not None else ""

    @property
    def type(self) -> str:
        return skill_type(self._entry)

    @property
    def job_restrict(self) -> Tuple[str, ...]:
        return skill_job_restrict(self._entry)

    @property
    def job_form(self) -> Optional[str]:
        return skill_job_form(self._entry)


def _as_skill(entry: Any) -> SlotKind:
    """把任意条目适配为 SlotKind（SkillDef/同协议对象直返；raw dict 包装）。"""
    if hasattr(entry, "type") and hasattr(entry, "job_restrict"):
        return cast(SlotKind, entry)
    if isinstance(entry, Mapping):
        return _RawSkillAdapter(entry)
    # 非 Mapping / 无协议 → 空占位（装配时 id=None 跳过，确定性兜底）
    return _RawSkillAdapter({})


# =====================================================================================
# 装配过滤（§4.3-3：job_restrict 自动过滤，通用技能全职业可见）
# =====================================================================================


def job_visible(skill: SlotKind, job_id: Optional[str]) -> bool:
    """技能对当前职业可见性（§4.3-3 装配过滤，P-5）。

    job_restrict 空 = 通用技能全职业可见；非空 → 须含当前职业；job_id 缺失
    （不确定职业）→ 通用口径放行（不误伤通用技能，确定性兜底）。
    """
    restrict = skill.job_restrict
    if not restrict:
        return True
    if job_id is None:
        return True
    return job_id in restrict


# =====================================================================================
# 装配主入口（TC-04）
# =====================================================================================


def assemble_slots(
    skills: Sequence[Any],
    player_ctx: Mapping[str, Any],
) -> Dict[str, Any]:
    """技能位装配主入口（6a §1.5 / TC-04）——生成装配快照（不落存档）。

    入参：
      skills:     技能条目序列（SkillDef / raw dict / 任意 SlotKind 协议对象，
                  P-1 注入；条目无 id 或 type 非法 → 跳过）。
      player_ctx: 玩家上下文 Mapping（读取 "job_id"；缺省 None → 通用口径
                  P-5；本函数不写 ctx、不碰 persistent_state——落档走
                  save_slots_to_state）。
    出参：装配快照 dict（可 JSON 序列化，P-2）：
      - "slots":        槽位列表 [{"slot": "basic", "skill_id": "..."}, ...]
        basic 固定第 1 位（恰 1 个，0 个 → skill_id=None 占位 P-3，多个 →
        按 job_restrict 命中者优先取库序首个）；active 按 active_order（缺省
        P-4 排序）；passive/trigger 按库序收集（P-6）。
      - "active_order":  active 技能 id 列表（玩家顺序；未装配过 → 缺省排序）。
      - "passive":       passive 槽 [{"slot": "passive", "skill_id": "..."}, ...]。
      - "trigger":       trigger 槽 [{"slot": "trigger", "skill_id": "..."}, ...]。
      - "version":       快照版本（当前 1）。

    规则要点（契约逐条）：
      - basic 固定第 1 位且仅 1 位（TC-04；[L62/L86]）——slots[0] 恒为 basic 槽。
      - active 可排序（TC-04；[L86]）——active_order 显式承载玩家顺序。
      - passive/trigger 进装配槽不占行动位（TC-04；[L64-65]）。
      - job_restrict 装配过滤（§4.3-3；通用技能全职业可见）。
      - job_form 形态替换本函数不处理（F17/[L88] → apply_job_form，归批7/批15）。
    """
    job_id = _ctx_job_id(player_ctx)
    skills_seq = tuple(_as_skill(s) for s in skills)
    # 按类型分组（防御性跳过：无 id 的条目不进任何槽）
    basic: List[SlotKind] = []
    actives: List[SlotKind] = []
    passives: List[SlotKind] = []
    triggers: List[SlotKind] = []
    for s in skills_seq:
        if not s.id:
            continue
        t = s.type
        if t == SLOT_BASIC:
            basic.append(s)
        elif t == SLOT_ACTIVE:
            actives.append(s)
        elif t == SLOT_PASSIVE:
            passives.append(s)
        elif t == SLOT_TRIGGER:
            triggers.append(s)
        # 未知 type（防御性跳过；枚举校验归 V-13 校验器）
    # 职业过滤（§4.3-3）
    basic = [s for s in basic if job_visible(s, job_id)]
    actives = [s for s in actives if job_visible(s, job_id)]
    passives = [s for s in passives if job_visible(s, job_id)]
    triggers = [s for s in triggers if job_visible(s, job_id)]

    # ---- basic 固定第 1 位（恰 1 个；0 个占位 None P-3；多个取命中者优先 P-3）----
    basic_id: Optional[str]
    if not basic:
        basic_id = None  # 缺普攻占位（V-7 红拦属校验器职责，引擎不重复拦截）
    else:
        # 多个 basic 时：职业限定且命中当前职业者最优先 → 通用次之 → 库序兜底
        # （确定性；§4.3-3 通用技能全职业可见 + V-7 口径下同职业多 basic 属
        #  校验器红拦场景，引擎层只做确定性选择不拦截）
        def _basic_key(s: SlotKind) -> Tuple[int, int]:
            # 职业限定且命中当前职业最优先(0) → 通用(1) → 职业限定未命中(2)
            if s.job_restrict and job_visible(s, job_id):
                rank = 0
            elif not s.job_restrict:
                rank = 1
            else:
                rank = 2
            return (rank, _seq_index(skills_seq, s.id))

        chosen = min(basic, key=_basic_key)
        basic_id = chosen.id

    # ---- active 可排序（快照 active_order；缺省 P-4：职业命中者优先 + 库序）----
    saved_order = _ctx_active_order(player_ctx)
    if saved_order:
        by_id = {sk.id: sk for sk in actives}
        ordered: List[SlotKind] = []
        seen: set = set()
        for sid in saved_order:
            hit = by_id.get(sid)
            if hit is not None and sid not in seen:
                ordered.append(hit)
                seen.add(sid)
        # 存档未覆盖的新增技能 → 按缺省排序规则追加（确定性，不丢弃）
        for s in actives:
            if s.id not in seen:
                ordered.append(s)
        actives = ordered
    else:
        # 缺省排序：job_restrict 命中当前职业者优先，其余按库序

        def _default_key(s: SlotKind) -> Tuple[int, int]:
            hit = 0 if (s.job_restrict and job_visible(s, job_id)) else 1
            return (hit, _seq_index(skills_seq, s.id))

        actives.sort(key=_default_key)
    active_order = [s.id for s in actives]

    # ---- passive/trigger 槽（按库序收集，P-6）----
    passive_slots: List[Dict[str, Any]] = [
        {"slot": SLOT_PASSIVE, "skill_id": s.id} for s in passives
    ]
    trigger_slots: List[Dict[str, Any]] = [
        {"slot": SLOT_TRIGGER, "skill_id": s.id} for s in triggers
    ]

    # ---- slots 全量列表（basic 固定第 1 位 → active → passive → trigger）----
    slots: List[Dict[str, Any]] = [{"slot": SLOT_BASIC, "skill_id": basic_id}]
    slots.extend({"slot": SLOT_ACTIVE, "skill_id": sid} for sid in active_order)
    slots.extend(passive_slots)
    slots.extend(trigger_slots)

    return {
        "slots": slots,
        "active_order": active_order,
        "passive": passive_slots,
        "trigger": trigger_slots,
        "version": 1,
    }


# =====================================================================================
# 装配结果落存档接口（1g1c/1g3 承接，§7）
# =====================================================================================


def save_slots_to_state(
    player: MutableMapping[str, Any],
    snapshot: Mapping[str, Any],
) -> MutableMapping[str, Any]:
    """装配结果落玩家存档（§7 装配结果落玩家存档 / 1g1c/1g3 承接）。

    入参：
      player:   玩家 dict（含 "persistent_state" 键；缺省 → 惰性创建并挂回，
                对齐 qbot_rpg/assembly/context.py _ps_init 模式）。
      snapshot: assemble_slots 产出的装配快照（Mapping，原样落档；调用方
                保证可 JSON 序列化，P-2）。
    出参：player["persistent_state"][SLOT_STATE_KEY] 当前值（挂回后的存档
    节点，调用方可直接继续写）。幂等：重复保存覆盖旧快照。

    存档键：persistent_state["skill_slots"]（SLOT_STATE_KEY）；快照结构见
    assemble_slots 出参（slots / active_order / passive / trigger / version）。
    """
    ps = player.get("persistent_state")
    if not isinstance(ps, MutableMapping):
        ps = {}
        player["persistent_state"] = ps
    node = dict(snapshot) if isinstance(snapshot, Mapping) else dict(_EMPTY_SNAPSHOT)
    ps[SLOT_STATE_KEY] = node
    return cast(MutableMapping[str, Any], ps[SLOT_STATE_KEY])


def load_slots_from_state(player: Mapping[str, Any]) -> Dict[str, Any]:
    """从玩家存档读装配快照（1g1c/1g3 承接）。

    入参：player: 玩家 dict（含 "persistent_state"；缺省 → 空快照兜底）。
    出参：装配快照 dict；缺省/畸形（非 Mapping）→ 空快照骨架
    （slots [] / active_order [] / passive [] / trigger [] / version 1，
    确定性兜底，不抛异常）。本函数只读不写存档（写走 save_slots_to_state）。
    """
    ps = player.get("persistent_state")
    if not isinstance(ps, Mapping):
        return dict(_EMPTY_SNAPSHOT)
    raw = ps.get(SLOT_STATE_KEY)
    if not isinstance(raw, Mapping):
        return dict(_EMPTY_SNAPSHOT)
    return _normalize_snapshot(raw)


def _normalize_snapshot(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """存档快照防御性归一（畸形键 → 空骨架；不抛异常）。"""
    out: Dict[str, Any] = dict(_EMPTY_SNAPSHOT)
    slots = raw.get("slots")
    if isinstance(slots, list):
        cleaned: List[Dict[str, Any]] = []
        for item in slots:
            if isinstance(item, Mapping):
                slot_kind = item.get("slot")
                sid = item.get("skill_id")
                if isinstance(slot_kind, str) and slot_kind in _SLOT_KIND_ORDER:
                    cleaned.append(
                        {"slot": slot_kind, "skill_id": sid if isinstance(sid, str) else None}
                    )
        out["slots"] = cleaned
    active_order = raw.get("active_order")
    if isinstance(active_order, list):
        out["active_order"] = [x for x in active_order if isinstance(x, str)]
    passive = raw.get("passive")
    if isinstance(passive, list):
        out["passive"] = _clean_slot_list(passive, SLOT_PASSIVE)
    trigger = raw.get("trigger")
    if isinstance(trigger, list):
        out["trigger"] = _clean_slot_list(trigger, SLOT_TRIGGER)
    version = raw.get("version")
    if isinstance(version, int) and not isinstance(version, bool) and version >= 1:
        out["version"] = version
    return out


def _clean_slot_list(items: Any, kind: str) -> List[Dict[str, Any]]:
    """槽列表防御性归一（条目非 Mapping / 键非法 → 跳过）。"""
    out: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, Mapping):
            continue
        sid = item.get("skill_id")
        if isinstance(sid, str) and sid:
            out.append({"slot": kind, "skill_id": sid})
    return out


# =====================================================================================
# job_form 形态替换接口（F17 / [L88] / TC-06 —— 仅接口注释 + 占位，实现归批7/批15）
# =====================================================================================


def apply_job_form(
    snapshot: Mapping[str, Any],
    skills: Sequence[Any],
    form: Optional[str] = None,
) -> Dict[str, Any]:
    """形态技替换技能位（F17 / 契约 [L88] / TC-06）。

    语义（契约 §4.3-3 / 细化 §1.5）：职业变换 transform 形态激活时，job_form
    匹配该形态的技能替换对应技能位；变换回原职业恢复原技能列表。

    接口约定（当前为占位实现）：
      - 入参：装配快照 + 技能条目序列 + 当前激活形态名（form）；
      - 出参：替换后的新装配快照（不落存档，调用方决定是否 save）。
    实现归批7/批15（职业变换 transform 落盘后接线）；本路只保证接口形态与
    快照结构兼容——当前原样返回快照副本（确定性占位，不改变装配结果）。

    【工程补白 P-7】：占位返回快照副本；form 非 None 时也原样返回（不臆造
    替换语义）。批7/批15 实现时：遍历 skills，job_form == form 的技能按
    type 替换对应槽位（basic 固定第 1 位 / active 排序位 / passive/trigger 槽）。
    """
    return dict(snapshot) if isinstance(snapshot, Mapping) else dict(_EMPTY_SNAPSHOT)


# =====================================================================================
# 内部工具
# =====================================================================================


def _ctx_job_id(player_ctx: Mapping[str, Any]) -> Optional[str]:
    """player_ctx 中当前职业 id（缺省 None = 通用口径 P-5）。"""
    v = player_ctx.get("job_id")
    return v if isinstance(v, str) and v else None


def _ctx_active_order(player_ctx: Mapping[str, Any]) -> Tuple[str, ...]:
    """player_ctx 中玩家已保存的 active 排序（active_order；缺省空 = 缺省排序 P-4）。"""
    v = player_ctx.get("active_order")
    if isinstance(v, (list, tuple)):
        return tuple(x for x in v if isinstance(x, str))
    return ()


def _seq_index(skills_seq: Sequence[SlotKind], sid: str) -> int:
    """技能在库序中的下标（未找到 → 大数靠后，确定性兜底）。"""
    for i, s in enumerate(skills_seq):
        if s.id == sid:
            return i
    return len(skills_seq)


__all__ = [
    "SLOT_STATE_KEY",
    "SLOT_BASIC",
    "SLOT_ACTIVE",
    "SLOT_PASSIVE",
    "SLOT_TRIGGER",
    "DEFAULT_TYPE",
    "SlotKind",
    "skill_type",
    "skill_id",
    "skill_job_restrict",
    "skill_job_form",
    "job_visible",
    "assemble_slots",
    "save_slots_to_state",
    "load_slots_from_state",
    "apply_job_form",
]
