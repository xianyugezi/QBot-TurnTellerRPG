"""M13 技能库·批14·路14C：转职×技能装配联动（qbot_rpg/core/job_slots.py）。

文件名：qbot_rpg/core/job_slots.py
创建时间：2026-09-02
作者：Hermes 子agent-14C（M13 装配接线组批14路14C：并发同仓，仅新建本文件 +
  tests/unit/test_job_skill_slots_link.py；不碰兄弟路文件——14A 独占 /转职
  指令（core/job_change.py 等）、14B 独占战斗链路，本路消费已落盘的
  skill_slots 装配接口与 ctx 注入，零 NoneBot、零 content import）

功能描述：转职（玩家 job_id 永久变更，区别于 transform 战斗内形态切换——
  细化_6b 术语表「职业特色机制，非框架级常态换职业」）后的技能位重排联动：
  1) REARRANGE_JOB_KEY     转职快照段存档键（persistent_state["job_slots"]，
     与 skill_slots 快照段平行，1g1c/1g3 存档承接）
  2) snapshot_job_context(player, job_id, skills)  转职前快照——把玩家当前
     装配快照、当前 job_id、整库技能表打包成可 JSON 序列化的转职上下文段
     （含"重排前 active_order 排序捕获"，供重排时尽量保持玩家手动顺序）
  3) rearrange_job_slots(player_ctx, skills, job_id)  转职后技能位重排纯函数
     ——以新职业为装配视角（assemble_slots 按新 job_id 过滤 job_restrict），
     产出重排后新装配快照；不落存档（落档走 save_rearranged_slots）
  4) save_rearranged_slots(player, snapshot, job_id)  存档迁移：新装配快照
     覆盖 persistent_state[SLOT_STATE_KEY]（skill_slots 快照段）+ 记录
     REARRANGE_JOB_KEY 段（新 job_id / 时间 / 装配视角快照），旧存档无损
     迁移（缺 persistent_state / skill_slots 段 → 惰性创建，不抛异常）
  5) load_job_slots_state(player)  读转职快照段（缺省空 dict，防御读取）

规则要点（契约逐条）：
  - 新职业技能组装配：assemble_slots 按新 job_id 过滤 job_restrict（§4.3-3
    装配过滤：非当前职业排除、通用技能全职业可见；§4.3-4 职业变换时按新
    职业重算装配有效集）
  - 被动/触发槽重装配：转职 = 全量重算装配（与 transform 形态切换 SH-2
    双形态独立装配不同语义——job_change 是玩家职业永久变更，passive/
    trigger 槽内容按新职业可见集整体重装配，A 职业专属被动转职后不再装配）
  - active 手动顺序尽量保留：重排时先按旧 active_order 中仍对新职业可见
    的技能保持原相对顺序，再按缺省规则追加新职业新增技能（确定性兜底，
    与 assemble_slots 的 active_order 覆盖逻辑同构）
  - basic 恰 1 位：新职业 basic 可见集为空 → skill_id=None 占位（对齐
    skill_slots P-3，V-7 红拦属校验器职责，引擎不重复拦截）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  P-1  转职快照段：契约 §4.3-4 仅声明"职业变换时按新职业重算装配有效集
      （3b/3e2 存档承接）"，未定义段名与形态——本文件定型为
      persistent_state["job_slots"] = {job_id, at, active_order_snapshot,
      snapshot}（at 为 ISO-8601 字符串，由调用方注入；纯函数本体不读时钟，
      确定性测试注入固定值）。
  P-2  排序保留策略：重排后 active_order = 旧顺序 ∩ 新可见集（保序）+
      新可见集 − 旧集合（按缺省规则，与 assemble_slots 存档未覆盖追加
      同构）；旧顺序完全不可用（如全为 A 专属）→ 新职业缺省排序兜底。
  P-3  视角快照语义：REARRANGE_JOB_KEY.snapshot 存"以新职业装配视角"的快照
      （重排产物），load 侧可直接读取展示；旧快照被覆盖前已由调用方在
      persistent_state["skill_slots"] 原位更新（存档迁移以新装配为准）。
  P-4  迁移兼容：save_rearranged_slots 缺 skill_slots 旧段 → 惰性创建并挂
      回（对齐 skill_slots.save_slots_to_state 的 _ps_init 模式）；player
      缺 persistent_state → 惰性创建挂回；快照畸形（非 Mapping）→ 归一空
      快照骨架（不抛异常，防御读取）。
  P-5  skills 表缺省：rearrange_job_slots 的 skills 入参缺省 None → 读
      player_ctx["skills"]（M13 批13 ctx 注入的 {id: raw dict} 表）；两者
      都缺 → 空装配（basic 占位 None，确定性兜底）。

铁律：零 NoneBot import（G0 门禁）；core 层只依赖 data（技能数据经 ctx 注入，
零 import content）；纯函数确定性（同刻同参必同值）；完整类型标注（typing
3.9 兼容）；零定时器/零睡眠（本文件不含任何 sleep/定时器字面量）；不引入
随机；不 git commit；只写本文件 + 自己的测试。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple, cast

from qbot_rpg.core.skill_slots import (
    assemble_slots,
    load_slots_from_state,
    save_slots_to_state,
)

# =====================================================================================
# 常量
# =====================================================================================

# 转职快照段存档键（P-1：1g1c/1g3 存档承接，与 skill_slots 段平行）
REARRANGE_JOB_KEY: str = "job_slots"


# =====================================================================================
# 转职上下文快照（转职前打包）
# =====================================================================================


def snapshot_job_context(
    player: Mapping[str, Any],
    job_id: Optional[str],
    skills: Optional[Sequence[Any]] = None,
    at: Optional[str] = None,
) -> Dict[str, Any]:
    """转职前快照：把玩家当前装配快照 + 当前 job_id + 技能表打包成上下文段。

    入参：
      player: 玩家 dict（含 "persistent_state"；缺省 → 空装配快照兜底）。
      job_id: 当前职业 id（转职前；None → 不记录）。
      skills: 整库技能条目序列（SkillDef / raw dict；None → 空序列）。
      at:     时间戳字符串（ISO-8601；None → 不记录）。P-1：时间由调用方
              注入，纯函数本体不读时钟（确定性测试注入固定值）。
    出参：转职上下文段 dict（可 JSON 序列化）：
      - "job_id":             转职前职业 id（None → 缺省不写键）。
      - "at":                 时间戳（None → 缺省不写键）。
      - "active_order_snapshot": 当前装配快照的 active_order（重排时保序
        依据；无存档 → []）。
      - "snapshot":           当前装配快照（load_slots_from_state 读档；
        缺省 → 空快照骨架）。
      - "skills":             技能表原始条目列表（raw dict 原样，可 JSON）。
    核心逻辑：只读打包，不写 player、不落存档（存档迁移走
    save_rearranged_slots）。
    """
    out: Dict[str, Any] = {}
    if isinstance(job_id, str) and job_id:
        out["job_id"] = job_id
    if isinstance(at, str) and at:
        out["at"] = at
    snapshot = load_slots_from_state(player)
    order = snapshot.get("active_order")
    out["active_order_snapshot"] = list(order) if isinstance(order, (list, tuple)) else []
    out["snapshot"] = snapshot
    out["skills"] = _entries_to_raw(skills)
    return out


# =====================================================================================
# 转职后技能位重排（纯函数；不落存档）
# =====================================================================================


def rearrange_job_slots(
    player_ctx: Mapping[str, Any],
    job_id: str,
    skills: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """转职后技能位重排（§4.3-4：按新职业重算装配有效集）。

    入参：
      player_ctx: 玩家上下文 Mapping（读取 "skills" 表与旧 "active_order"；
                  不写 ctx、不碰 persistent_state——落档走
                  save_rearranged_slots）。
      job_id:     新职业 id（转职后；非空 str）。
      skills:     整库技能条目序列（SkillDef / raw dict / SlotKind 协议
                  对象；None → 读 player_ctx["skills"]，P-5）。
    出参：重排后新装配快照 dict（assemble_slots 产物形态，可 JSON 序列化）：
      - 新职业技能组装配：basic 固定第 1 位（新职业可见 basic 恰 1；空 →
        skill_id=None 占位）；active 按新职业可见集 + 旧顺序保序（P-2）；
        passive/trigger 槽按新职业可见集整体重装配（§4.3-4）。
      - job_restrict 过滤：新职业不可见的技能（A 专属等）不进任何槽。
    核心逻辑：以新职业视角调 assemble_slots 全量重算；active 顺序优先
    复用旧 active_order 中仍可见者（保序），再按缺省规则追加新技能。
    """
    table = skills
    if table is None:
        raw = player_ctx.get("skills")
        if isinstance(raw, Mapping):
            table = list(raw.values())
        elif isinstance(raw, (list, tuple)):
            table = list(raw)
        else:
            table = []
    items = list(table) if table is not None else []
    # 旧顺序捕获（保序依据；P-2）
    saved = player_ctx.get("active_order")
    old_order = tuple(x for x in saved if isinstance(x, str)) if isinstance(
        saved, (list, tuple)
    ) else ()
    ctx: Dict[str, Any] = {"job_id": job_id}
    if old_order:
        ctx["active_order"] = list(old_order)
    return assemble_slots(items, ctx)


# =====================================================================================
# 存档迁移（save/load 转职快照段）
# =====================================================================================


def save_rearranged_slots(
    player: MutableMapping[str, Any],
    snapshot: Mapping[str, Any],
    job_id: Optional[str] = None,
    at: Optional[str] = None,
) -> MutableMapping[str, Any]:
    """存档迁移：新装配快照覆盖 skill_slots 段 + 记录转职快照段（P-3）。

    入参：
      player:   玩家 dict（含 "persistent_state"；缺省 → 惰性创建并挂回，
                对齐 skill_slots.save_slots_to_state 的 _ps_init 模式）。
      snapshot: rearrange_job_slots 产出的新装配快照（原样落档）。
      job_id:   新职业 id（None → 转职段不写 job_id 键）。
      at:       时间戳字符串（None → 转职段不写 at 键）。
    出参：player["persistent_state"][REARRANGE_JOB_KEY] 当前值（挂回后的
    转职段节点，调用方可继续写）。副作用：
      - persistent_state[SLOT_STATE_KEY] ← snapshot（新装配为准，存档迁移）；
      - persistent_state[REARRANGE_JOB_KEY] ← {job_id, at, snapshot}。
    幂等：重复保存覆盖旧段。
    """
    save_slots_to_state(player, snapshot)
    ps = player.get("persistent_state")
    if not isinstance(ps, MutableMapping):
        ps = {}
        player["persistent_state"] = ps
    job_node: Dict[str, Any] = {}
    if isinstance(job_id, str) and job_id:
        job_node["job_id"] = job_id
    if isinstance(at, str) and at:
        job_node["at"] = at
    job_node["snapshot"] = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    ps[REARRANGE_JOB_KEY] = job_node
    return cast(MutableMapping[str, Any], ps[REARRANGE_JOB_KEY])


def load_job_slots_state(player: Mapping[str, Any]) -> Dict[str, Any]:
    """读转职快照段（1g1c/1g3 承接；防御读取，不抛异常）。

    入参：player: 玩家 dict（含 "persistent_state"；缺省 → 空 dict）。
    出参：persistent_state["job_slots"] 段（Mapping → 副本；缺省/畸形 → {}，
    确定性兜底）。
    """
    ps = player.get("persistent_state")
    if not isinstance(ps, Mapping):
        return {}
    raw = ps.get(REARRANGE_JOB_KEY)
    return dict(raw) if isinstance(raw, Mapping) else {}


# =====================================================================================
# 内部工具
# =====================================================================================


def _entries_to_raw(skills: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
    """技能条目序列 → raw dict 列表（快照可 JSON 序列化）。

    SkillDef / 协议对象 → raw 兜底（.raw dict 优先，否则字段收集）；raw
    dict 条目原样；非 dict 且无 raw → 跳过（确定性，不抛异常）。
    """
    out: List[Dict[str, Any]] = []
    for s in skills or ():
        if isinstance(s, Mapping):
            out.append(dict(s))
            continue
        raw = getattr(s, "raw", None)
        if isinstance(raw, Mapping):
            out.append(dict(raw))
            continue
        # 协议对象无 raw → 收集已知字段（快照只读展示用，字段缺失兜底）
        sid = getattr(s, "id", None)
        stype = getattr(s, "type", None)
        if isinstance(sid, str) and sid:
            entry: Dict[str, Any] = {"id": sid}
            if isinstance(stype, str):
                entry["type"] = stype
            out.append(entry)
    return out


# 转职上下文段的展示辅助：从存档转职段读出重排后的 active_order（供
# 战斗/展示层直接消费，与 skill_slots 快照口径一致）
def _rearranged_active_order(snapshot: Mapping[str, Any]) -> Tuple[str, ...]:
    """新装配快照的 active 顺序（缺省空元组；防御读取）。"""
    order = snapshot.get("active_order")
    if isinstance(order, (list, tuple)):
        return tuple(x for x in order if isinstance(x, str))
    return ()


__all__ = [
    "REARRANGE_JOB_KEY",
    "snapshot_job_context",
    "rearrange_job_slots",
    "save_rearranged_slots",
    "load_job_slots_state",
]
