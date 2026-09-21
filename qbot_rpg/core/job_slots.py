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
  6) resolve_inherit_chain(job_id, jobs_table)  批35 · §6.12-12 职业树继承解析
     ——沿 jobs.inherit.from 向上收集祖辈（传递闭包，环安全），纯函数确定性；
  7) inherited_skill_ids(job_id, jobs_table, skills)  按 inherit 链解析「继承
     而来的技能 id」集（祖辈职业专属可见技能 + 目标职业 skills 白名单 +
     批79 `mode=replace` 的替换映射），供 rearrange_job_slots 注入既有装配入口
     （只放宽技能位可见性）

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
  - 职业树继承（批35 §6.12-12）：目标职业声明 `inherit.from`（母职）时，转职
    装配额外纳入母职的职业专属技能（`job_restrict` 命中母职者）——只放宽技能位
    可见性，**不碰属性成长**（2026-09-09 拍板：职业成长跟随职业，见 levelup）；
    不带 `inherit` 的职业 → 装配结果与现状逐字段一致（对拍）

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
  P-6  职业树继承（批35 §6.12-12）：定稿只说"继承母职全部技能 + 配置驱动、
      不写死"，未定义字段形态与粒度——本文件定型为 jobs.inherit{from,skills}
      （进阶职一侧，与批23 advance 同侧）：from = 母职（ref job），skills =
      可选白名单（空/缺省 = 继承祖辈全部**职业专属**技能，通用技能不算继承）。
      链解析 = 传递闭包（职业树 A→B→C 时 C 继承 B、A），环安全、悬空停链。
      继承**只放宽技能位可见性**，不碰属性成长（2026-09-09 拍板：职业成长跟随
      职业）。P-7（批79 · X18 用户裁决）：`inherit.mode` 支持 "append"（缺省=现状，
      母职+本职业累加）与 "replace"（按 `inherit.replace` 把继承来的指定技能换成
      本职业技能；空/缺省 replace = 等价 append）；不实现技能等级继承（技能无等级
      维度，另立设计）。口径回填见 docs/进阶职业继承_设计口径.md §5。

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

# 职业条目上的继承声明键（批35 · §6.12-12：jobs.inherit{from, skills}）
INHERIT_KEY: str = "inherit"

# 批79 · X18：inherit.mode（继承模式）与 inherit.replace（替换映射）。
#   mode = "append"（缺省/未知）= 现状：母职继承技能 + 本职业自身技能**累加**；
#   mode = "replace"             = 按 `replace` 把「继承来的指定技能」换成「本职业技能」。
# 缺省/未知 mode 一律按 append（未知值由校验器黄提示，引擎侧取安全默认 → 零行为变化）。
INHERIT_MODE_KEY: str = "mode"
INHERIT_REPLACE_KEY: str = "replace"
INHERIT_MODE_APPEND: str = "append"
INHERIT_MODE_REPLACE: str = "replace"
INHERIT_MODES: Tuple[str, ...] = (INHERIT_MODE_APPEND, INHERIT_MODE_REPLACE)


# =====================================================================================
# 职业树继承解析（纯函数 · 批35 §6.12-12）
# =====================================================================================


def resolve_inherit_chain(
    job_id: Optional[str],
    jobs_table: Optional[Mapping[str, Any]],
) -> Tuple[str, ...]:
    """沿 `jobs.inherit.from` 向上收集祖辈职业 id（纯函数，确定性）。

    入参：
      job_id:     目标职业 id（None/空 → 空链）。
      jobs_table: 职业表 Mapping（{job_id: 条目 dict}；非 Mapping → 空链）。
    出参：祖辈 id 元组——直接母职在前，祖辈依次在后；不含 job_id 自身。
    规则（工程补白 P-6，配置驱动、不写死）：
      · 每级读 `inherit.from`（非空 str 且 ∈ jobs_table 才纳入）；
      · **传递闭包**（职业树：A→B→C 时 C 继承 B 且继承 A）；
      · 环安全（seen 集合；自指/环 → 停链，不抛异常）；
      · 引用不存在 → 停链（悬空引用由校验器 R-4 红拦，引擎侧不臆造）。
    """
    if not isinstance(job_id, str) or not job_id:
        return ()
    if not isinstance(jobs_table, Mapping):
        return ()
    chain: List[str] = []
    seen = {job_id}
    cur = job_id
    while True:
        job = jobs_table.get(cur)
        if not isinstance(job, Mapping):
            break
        inherit = job.get(INHERIT_KEY)
        if not isinstance(inherit, Mapping):
            break
        parent = inherit.get("from")
        if not isinstance(parent, str) or not parent or parent in seen:
            break
        if not isinstance(jobs_table.get(parent), Mapping):
            break
        chain.append(parent)
        seen.add(parent)
        cur = parent
    return tuple(chain)


def inherited_skill_ids(
    job_id: Optional[str],
    jobs_table: Optional[Mapping[str, Any]],
    skills: Optional[Sequence[Any]] = None,
) -> Tuple[str, ...]:
    """该职业按 `jobs.inherit` 配置应**额外可见**（继承而来）的技能 id 集。

    入参：
      job_id / jobs_table: 同 resolve_inherit_chain。
      skills: 整库技能条目序列（Mapping raw dict 或含 .id/.job_restrict 的
              协议对象；None/空 → 空集）。
    出参：技能 id 元组（按传入库序去重，确定性）。
    规则（工程补白 P-6）：
      · 取链上每级祖辈的**职业专属技能**（`job_restrict` 非空且命中该祖辈）；
        通用技能（`job_restrict` 空）本就全职业可见，**不算继承**；
      · 目标职业 `inherit.skills` 白名单非空 → 只保留列出的 id（交集）；
      · 白名单空/缺省 → 继承祖辈全部职业专属技能；
      · **批79 · X18 mode=replace**：对上一步得到的继承集套 `inherit.replace`
        （`{母职技能id: 本职业技能id}`）——键命中继承集者从结果中移除，对应值
        作为替代技能并入（去重；未声明的技能照旧继承）。键未落在继承集 → 该项
        不生效（替换**只影响继承来的技能**）。`mode` 缺省/append/未知 → 结果与
        批35 逐字段一致（零行为变化）。
      · 不读属性成长（2026-09-09 拍板：职业成长跟随职业，不保留旧成长）。
    """
    chain = resolve_inherit_chain(job_id, jobs_table)
    if not chain:
        return ()
    assert isinstance(jobs_table, Mapping)
    chain_set = set(chain)
    whitelist = _inherit_whitelist(job_id, jobs_table)
    out: List[str] = []
    seen: set = set()
    for entry in skills or ():
        sid = _entry_skill_id(entry)
        if not sid or sid in seen:
            continue
        restrict = _entry_job_restrict(entry)
        if not restrict:
            continue  # 通用技能：本就可见，不算继承（不重复计入）
        if not (chain_set & set(restrict)):
            continue  # 该技能不属于链上任何祖辈
        if whitelist is not None and sid not in whitelist:
            continue  # 白名单非空：只继承列出的技能
        out.append(sid)
        seen.add(sid)
    return _apply_inherit_replace(job_id, jobs_table, tuple(out))


def _apply_inherit_replace(
    job_id: Optional[str],
    jobs_table: Mapping[str, Any],
    inherited: Tuple[str, ...],
) -> Tuple[str, ...]:
    """把 `inherit.replace` 套用到继承技能 id 元组（批79 · X18；纯函数，确定性）。

    规则：
      · `mode != "replace"` 或 `replace` 空/非 Mapping → 原样返回（逐字段零变化）；
      · 键命中 `inherited` → 该继承技能从结果移除；
      · 值（本职业替代技能 id）并入结果末尾（按 replace 声明顺序，去重）；
      · 键不在 `inherited` → 忽略（替换只影响继承来的技能，不动其余继承技能、
        也不动全局技能注册表）。
    """
    if _inherit_mode(job_id, jobs_table) != INHERIT_MODE_REPLACE:
        return inherited
    replace_map = _inherit_replace_map(job_id, jobs_table)
    if not replace_map:
        return inherited  # 空/缺省 replace = 等价 append
    inherited_set = set(inherited)
    base = [sid for sid in inherited if sid not in replace_map]
    out = list(base)
    seen = set(base)
    for parent_sid, own_sid in replace_map.items():
        if parent_sid not in inherited_set:
            continue  # 未实际继承 → 不生效
        if own_sid in seen:
            continue
        out.append(own_sid)
        seen.add(own_sid)
    return tuple(out)


def _inherit_mode(job_id: Optional[str], jobs_table: Mapping[str, Any]) -> str:
    """目标职业 `inherit.mode`（非 "replace" → "append" 缺省；未知值引擎侧取安全默认）。"""
    job = jobs_table.get(job_id) if isinstance(job_id, str) else None
    if not isinstance(job, Mapping):
        return INHERIT_MODE_APPEND
    inherit = job.get(INHERIT_KEY)
    if not isinstance(inherit, Mapping):
        return INHERIT_MODE_APPEND
    return INHERIT_MODE_REPLACE if inherit.get(INHERIT_MODE_KEY) == INHERIT_MODE_REPLACE \
        else INHERIT_MODE_APPEND


def _inherit_replace_map(
    job_id: Optional[str], jobs_table: Mapping[str, Any]
) -> Dict[str, str]:
    """目标职业 `inherit.replace` 映射（{母职技能id: 本职业技能id}；非 Mapping → {}）。

    只收「两侧均为非空字符串」的键值对（畸形项忽略，校验器 K-1/K-2 负责红拦）。
    """
    job = jobs_table.get(job_id) if isinstance(job_id, str) else None
    if not isinstance(job, Mapping):
        return {}
    inherit = job.get(INHERIT_KEY)
    if not isinstance(inherit, Mapping):
        return {}
    raw = inherit.get(INHERIT_REPLACE_KEY)
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, str] = {}
    for src, dst in raw.items():
        if isinstance(src, str) and src and isinstance(dst, str) and dst:
            out[src] = dst
    return out


def _inherit_whitelist(
    job_id: Optional[str], jobs_table: Mapping[str, Any]
) -> Optional[frozenset]:
    """目标职业 `inherit.skills` 白名单（非空 list[str] → frozenset；否则 None）。"""
    job = jobs_table.get(job_id) if isinstance(job_id, str) else None
    if not isinstance(job, Mapping):
        return None
    inherit = job.get(INHERIT_KEY)
    if not isinstance(inherit, Mapping):
        return None
    raw = inherit.get("skills")
    if not isinstance(raw, list):
        return None
    ids = tuple(x for x in raw if isinstance(x, str) and x)
    return frozenset(ids) if ids else None


def _entry_skill_id(entry: Any) -> Optional[str]:
    """技能条目 id（raw Mapping / 协议对象双形态；缺省 None）。"""
    v = entry.get("id") if isinstance(entry, Mapping) else getattr(entry, "id", None)
    return v if isinstance(v, str) and v else None


def _entry_job_restrict(entry: Any) -> Tuple[str, ...]:
    """技能条目 job_restrict（raw Mapping / 协议对象；非序列 → 空 = 通用）。"""
    v = (entry.get("job_restrict") if isinstance(entry, Mapping)
         else getattr(entry, "job_restrict", None))
    if isinstance(v, (list, tuple)):
        return tuple(x for x in v if isinstance(x, str))
    return ()


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
    # 批35 · §6.12-12 职业树继承：从 player_ctx["jobs"] 读职业表，按目标职业的
    # inherit 链解析「继承而来的技能 id」→ 注入装配入口（不新开装配，P-6）。
    jobs_table = player_ctx.get("jobs")
    if isinstance(jobs_table, Mapping):
        inherited = inherited_skill_ids(job_id, jobs_table, items)
        if inherited:
            ctx["inherited_skill_ids"] = list(inherited)
    return assemble_slots(items, ctx)


# =====================================================================================
# 职业树展示数据（纯函数 · 批35 §6.12-12 编辑器卡片/指令复用）
# =====================================================================================


def job_inherit_summary(
    jobs_table: Any,
    skills: Any = None,
) -> Dict[str, Any]:
    """职业树展示数据（纯函数，可 JSON 序列化；编辑器【进阶职业卡片】后端口径）。

    入参：
      jobs_table: 职业表（Mapping{job_id: 条目} 或条目序列；条目为 Mapping）。
      skills:     整库技能条目序列（raw Mapping 或协议对象；缺省 → 名称兜底 id）。
    出参：
      {
        "jobs": [                     # 保持传入职业表顺序
          {"id", "name",
           "parent": <母职 id | None>,       # inherit.from：从哪个职业进阶
           "parent_name": <母职名 | None>,
           "ancestors": [<祖辈 id>...],      # 继承链（传递闭包）
           "advanced_jobs": [{"id","name"}], # 下级职业（谁挂在它下面，反向索引）
           "inherit_skills": [{"id","name"}...] | None,  # 声明白名单（None = 全部）
           "inherited_skills": [{"id","name"}...]},      # 实际继承到的技能
        ],
        "count": <职业数>,
      }
    规则：**配置驱动、不写死**——只读 `jobs.inherit`；无 `inherit` 的职业
    parent=None、inherited_skills=[]。「挂在谁下面就继承谁」= advanced_jobs 反向索引。
    """
    rows = _normalize_entries(jobs_table)
    by_id = {jid: entry for jid, entry in rows}
    skill_rows = _normalize_entries(skills) if skills is not None else []
    skill_list = [entry for _sid, entry in skill_rows]
    skill_name = {sid: str(e.get("name") or sid) for sid, e in skill_rows}
    # 反向索引：母职 → 下级职业（按职业表顺序，确定性）
    advanced: Dict[str, List[str]] = {}
    for jid, entry in rows:
        parent = _inherit_from(entry)
        if parent:
            advanced.setdefault(parent, []).append(jid)

    jobs_out: List[Dict[str, Any]] = []
    for jid, entry in rows:
        parent = _inherit_from(entry)
        chain = resolve_inherit_chain(jid, by_id)
        declared = _inherit_skill_ids_declared(entry)
        inherited = inherited_skill_ids(jid, by_id, skill_list)
        jobs_out.append({
            "id": jid,
            "name": str(entry.get("name") or jid),
            "parent": parent,
            "parent_name": (str(by_id[parent].get("name") or parent)
                            if parent in by_id else None),
            "ancestors": list(chain),
            "advanced_jobs": [
                {"id": c, "name": str(by_id[c].get("name") or c)}
                for c in advanced.get(jid, []) if c in by_id
            ],
            "inherit_skills": (
                None if declared is None
                else [{"id": s, "name": skill_name.get(s, s)} for s in declared]
            ),
            "inherited_skills": [
                {"id": s, "name": skill_name.get(s, s)} for s in inherited
            ],
        })
    return {"jobs": jobs_out, "count": len(jobs_out)}


def _normalize_entries(table: Any) -> List[Tuple[str, Mapping[str, Any]]]:
    """条目表归一为 [(id, Mapping)]（Mapping{id: entry} / 序列双形态；保序、去重）。"""
    out: List[Tuple[str, Mapping[str, Any]]] = []
    seen: set = set()
    if isinstance(table, Mapping):
        for k, v in table.items():
            jid = str(k)
            if jid and jid not in seen and isinstance(v, Mapping):
                out.append((jid, v))
                seen.add(jid)
    elif isinstance(table, (list, tuple)):
        for v in table:
            if not isinstance(v, Mapping):
                continue
            jid = v.get("id")
            if isinstance(jid, str) and jid and jid not in seen:
                out.append((jid, v))
                seen.add(jid)
    return out


def _inherit_from(entry: Mapping[str, Any]) -> Optional[str]:
    """职业条目的 inherit.from（非空 str → 该值；否则 None）。"""
    inherit = entry.get(INHERIT_KEY)
    if not isinstance(inherit, Mapping):
        return None
    parent = inherit.get("from")
    return parent if isinstance(parent, str) and parent else None


def _inherit_skill_ids_declared(entry: Mapping[str, Any]) -> Optional[List[str]]:
    """职业条目 inherit.skills 声明白名单（list[str] → 列表；否则 None = 全部）。"""
    inherit = entry.get(INHERIT_KEY)
    if not isinstance(inherit, Mapping):
        return None
    raw = inherit.get("skills")
    if not isinstance(raw, list):
        return None
    ids = [x for x in raw if isinstance(x, str) and x]
    return ids or None


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


__all__ = [
    "REARRANGE_JOB_KEY",
    "INHERIT_KEY",
    "INHERIT_MODE_KEY",
    "INHERIT_REPLACE_KEY",
    "INHERIT_MODE_APPEND",
    "INHERIT_MODE_REPLACE",
    "INHERIT_MODES",
    "snapshot_job_context",
    "resolve_inherit_chain",
    "inherited_skill_ids",
    "job_inherit_summary",
    "rearrange_job_slots",
    "save_rearranged_slots",
    "load_job_slots_state",
]
