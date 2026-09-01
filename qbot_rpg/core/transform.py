"""M13 批6 路6A · 6b 变换引擎 F1 触发核心（qbot_rpg/core/transform.py）。

文件名：qbot_rpg/core/transform.py
创建时间：2026-09-02
作者：Hermes 子agent-6A（M13 6b 变换引擎实现组批6路6A：并发同仓，仅新建本文件 +
  tests/unit/test_transform_f1.py；不碰兄弟文件——6B 独占 core/transform_revert.py
  （F2 还原）、6C 独占 core/transform_snapshot.py（F3 快照），本文件独立实现
  F1 触发主体 + 5 态状态机框架，主 agent 收口合并）

功能描述：职业变换引擎核心（细化_6b §二 流程 F1 / §三 5 态状态机）——
  1) 5 态状态机常量与迁移表（S1 NORMAL / S2 TRANSFORMING 瞬态 / S3 FORM_ACTIVE /
     S4 REVERTING 瞬态 / S5 COOLDOWN；§3.1 状态集 + §3.2 状态图）：
     - STATE_* 常量 + STATE_TRANSITIONS 迁移表（源态 → 事件 → 目标态）
     - state_of_transform_state() 从 transform_state 段推导可观测用户态
       （S1/S3/S5 常态；S2/S4 瞬态不落快照不占回合，D-03）
     - can_transform() 触发闸 C1~C4（常态判定 + 冷却 + 形态激活互斥）
  2) F1 变换触发主流程 trigger_transform（细化_6b §2.1 流程 F1 ①~⑥）：
     ① 触发技效果先结算（resolve_hook 注入，TRF-1）→
     ② 变换（不额外耗回合，TRF-2）四动作同拍：
       ④a 施加形态状态（apply_status_hook 注入，D-02 双轨效果侧）
       ④b 切换 job_form 指针（transform_state.form）
       ④c 技能位重排（rearrange_hook 注入，SH-1~5，派生/被动/触发槽独立）
       ④d 按 state_policy 处理（combo/marks/buff 三键 clear|keep，§1.4）→
     ⑤ 形态专属派生链重评估（reassess_chains_hook 注入，job_scope 命中）→
     ⑥ remaining=turns（含变身当回合）+ cooldown_remaining=cooldown（从触发
       起算）进入 S3 形态持续计数（D-03 回合结束 tick 递减，递减归 F2）
  3) 技能位重排实现（SH-1~5）：rearrange_slots() 纯函数——按 skill_set 组内
     技能（basic/active/passive/trigger 四类）重排快照，derive_only 不占位
     （SH-3），被动/触发槽独立装配（SH-2），缺省组空 → 原样保留（防御兜底）
  4) state_policy 处理实现：apply_state_policy() 纯函数——combo=clear 清连段
     （写入 snap.combo_state[side] 五字段空态 + combo_events 审计，对齐
     ComboEngine.write_state/clear 口径）；marks=clear 清该侧印记实例；
     buff=clear 清该侧 status_state 中 category=增益/强化（buff）类条目
     （category 值域见细化_1b；无 registry 注入时按 category in
     BUFF_CATEGORIES 判定，防御性跳过非 dict 条目）；keep 一律不动
  5) 双轨挂载（D-02）：trigger_transform 返回 transform_state 段（引擎轨
     job_form 指针 + remaining + cooldown_remaining + active_skill_set）与
     side_effects 事件列表（效果轨施加形态状态钩子产物）；form_status_id
     落 transform_state.form_status_id 与 status_state 双写（联动
     dispel_reverts 归 F2，本文件只登记引用）
  6) TransformEngine 引擎类（构造器注入 resolve_hook / apply_status_hook /
     rearrange_hook / reassess_chains_hook / audit，缺省 = 模块级纯函数默认
     行为；对齐 fishing.py 注入三件套 + forge_job.py 引擎持有者先例）

依据：
  - docs/细化/细化_6b_职业库与变换引擎.md（409 行 v1.0）：
    §2.1 流程 F1（①~⑥ 时序 + TRF-1~6 规则：效果先结算 / 零额外回合 /
    不重结算 / 触发技标签显式 combo_preserve / 怒气沉没 / 形态代价可配）；
    §3.1 状态集（S1~S5 五态：NORMAL/TRANSFORMING/FORM_ACTIVE/REVERTING/
    COOLDOWN，逐态进入/退出语义）；§3.2 状态图；§3.3 触发条件 C1~C4 /
    持续时间 / 洗牌 SH-1~5（主动位互换 / 被动触发槽独立 / derive_only 不占位 /
    装备限制 / 常态回归）；§1.4 state_policy 三键（combo/marks/buff
    clear|keep，默认 clear/keep/keep）；§0.3 ADR D-01~D-05（D-02 双轨 /
    D-03 计时挂回合 tick）；
    §1.3 transform 段 11 字段（transform_skill/transform_to/duration/turns/
    cooldown/state_policy/skill_set/derive_chains 等）；§1.5 技能挂点
    （job_form/revert_form/derive_only）；§六 TC-01~04（触发 4 例）。
  - docs/m13_6b摸底.md（缺口：5 态状态机与 F1/F2/F3 引擎全缺；已就绪：
    effects 通道 / stat_modifier 通道 battle.py:561-577 / combo_preserve tag /
    快照回合边界机制）。
  - 批4 已落盘：qbot_rpg/content/job_models.py（JobDef/TransformDef/
    StatePolicyDef + transform_fields/state_policy_fields 字段表）——本文件
    零 import content（G0），仅按契约字段口径读取 ctx 注入的 transform 段。
  - 参考引擎模式：qbot_rpg/core/fishing.py（FishingEngine 注入三件套 +
    ctx 键惰性挂回 + 缺省兜底）、qbot_rpg/core/skill_slots.py（SlotKind
    协议 + _RawSkillAdapter 兜底）、qbot_rpg/core/combo.py（combo_state
    按侧嵌套五字段 + ComboEngine.write_state/clear 口径）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  F1-1  引擎轨与效果轨的写入通道：本引擎不直接改 battle_state（战斗层自持
        snapshot 权威），F1 产物 = 新 transform_state 段 dict + side_effects
        事件列表（含 form_status_id 登记），由接线方（主 agent 收口 battle.py）
        落盘；效果轨的形态状态本体（施加/移除/驱散联动）经 apply_status_hook
        注入——本文件不 import effects（G0），钩子缺省 = 仅登记事件不写状态
        （确定性兜底，测试注入桩验证四动作时序）。
  F1-2  触发技效果先结算的注入形态：resolve_hook(ctx, skill_id, action) →
        dict（含 ok/effects 等）；缺省 = 记录 pending 事件返回 {ok:True}
        （不重结算、不重复触发）。本文件保证「先 resolve 后变换」的时序契约
        （TRF-1），效果本体归战斗层技能结算通道（摸底报告：F1 缺口仅四动作
        需新引擎，效果结算走现有通道）。
  F1-3  state_policy 落点：policy 写战斗快照对应段（combo_state / marks_state /
        status_state）——combo 清空按 ComboEngine.write_state 五字段空态 +
        combo_events 审计（对齐 combo.clear 先例）；marks 清空 = 该侧实例
        列表置空；buff 清空 = 该侧 status_state 移除 category ∈
        BUFF_CATEGORIES（强化/增益）的条目（细 1b 分类口径本地镜像，防御性
        跳过非 dict 条目；registry 注入时可经 _is_buff_entry 访问器扩展）。
  F1-4  技能位重排口径（SH-1~5 引擎化）：以「形态技能组 = skill_set 组内
        技能条目」为源（ctx 注入组内技能序列），产出重排快照——basic 固定
        第 1 位（SH-1 主动位互换）、active 顺序 = 组内库序、passive/trigger
        槽独立装配（SH-2）；derive_only 条目不占任何位（SH-3，按
        _RawSkillAdapter 访问器 derive_only 判定，缺省 False）；equip_restrict
        不满足的禁用（SH-4）归装配层 4b 联动（本层不含装备语义）；组空/未
        注入 → 原快照副本（防御兜底，不臆造重排）；还原回归常态组（SH-5）
        归 F2（transform_revert.py）。
  F1-5  derive_chains 重评估注入：reassess_chains_hook(ctx, form,
        derive_chains) → list[str]（命中的链 ID）；缺省 = 原样返回入参链列表
        （引擎不持有链表——skill_chains 数据经 ctx 注入，job_scope 求值归
        接线方/6a 链引擎；本层只保证「变换后重新评估」时序钩子位）。
  F1-6  remaining/cooldown 口径（§2.1⑥ / §3.3 / D-03）：remaining 初始 =
        transform.turns（含变身当回合，TC-01④）；duration=battle 时
        remaining=-1 哨兵（整场不还原，F2 不递减）；cooldown_remaining 初始 =
        transform.cooldown（从触发起算，§2.2② REV-6）；回合结束 tick 递减归
        F2 tick 引擎（本文件不含 tick 推进，避免与兄弟路重叠）。
  F1-7  触发闸 C1~C4 的引擎侧判定：C1 常态（S1/S5）可由 transform_state.form
        为空判定 + 显式互斥拒绝（形态激活期 transform_skill 不可用，TC-03）；
        C2 资源足够（MP/怒气 energy_cost）归战斗层资源校验（6c 未定稿，
        ctx 注入 resource_check_hook 缺省放行）；C3 冷却转好 =
        cooldown_remaining<=0；C4 被控（skip_turn）不触发 = ctx 注入
        skip 判定（缺省 False 放行，战斗层接线时注入）。
  F1-8  combo_preserve 标签（TRF-4）：触发技默认普通技能=断连段（自然代价）；
        技能带 combo_preserve 标签 → 变换时连段保留（state_policy.combo=keep
        的等价通道）。本文件 state_policy 按配置键执行；标签通道归战斗层
        技能结算（摸底报告已就绪），引擎不重复实现。

铁律：零 NoneBot import（G0 门禁）；core 层只依赖 data（本文件零 import
content/data，技能/职业数据经 ctx 注入）；纯函数确定性（同刻同参必同值）；
完整类型标注（typing 3.9 兼容）；零定时器/零睡眠（本文件不含任何 sleep/
定时器字面量——引擎零定时器零睡眠，无时间依赖）；不引入随机；不 git
commit；只写本文件 + 自己的测试。
"""
from __future__ import annotations

from typing import (
    Any,
    Callable,
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
# 5 态状态机常量（细化_6b §3.1 状态集：S1~S5）
# =====================================================================================

# S1 常态（职业默认形态，使用常态技能组；怒气/冷却积累中；初始 / REVERTING 完成）
STATE_NORMAL: str = "NORMAL"
# S2 变换中（瞬态：不落快照、不占回合；四动作同拍执行，F1 ④）
STATE_TRANSFORMING: str = "TRANSFORMING"
# S3 形态激活（常态：形态技能组可用；持续回合 tick 递减；形态专属派生链生效）
STATE_FORM_ACTIVE: str = "FORM_ACTIVE"
# S4 还原结算（瞬态：不落快照、不占回合；state_policy + job_form 切回 +
# 技能位重排回常态 + 形态状态移除，F2）
STATE_REVERTING: str = "REVERTING"
# S5 冷却期（常态：形态冷却随回合 tick 递减；期间 transform_skill 施放被拒）
STATE_COOLDOWN: str = "COOLDOWN"

# 五态全集（§3.1 状态集登记，防漂移）
TRANSFORM_STATES: Tuple[str, ...] = (
    STATE_NORMAL,
    STATE_TRANSFORMING,
    STATE_FORM_ACTIVE,
    STATE_REVERTING,
    STATE_COOLDOWN,
)

# 瞬态集合（S2/S4：不落快照、不占回合，D-03）
TRANSIENT_STATES: Tuple[str, ...] = (STATE_TRANSFORMING, STATE_REVERTING)

# 常态（可观测用户态）集合（S1/S3/S5）
OBSERVABLE_STATES: Tuple[str, ...] = (STATE_NORMAL, STATE_FORM_ACTIVE, STATE_COOLDOWN)

# =====================================================================================
# 状态迁移表（细化_6b §3.1 进入/退出 + §3.2 状态图）
# =====================================================================================
# 事件键：trigger（F1 触发技结算成功） / complete（瞬态同拍完成） /
#         expire（turns 用尽/驱散命中，回合结束 tick 结算） /
#         revert_now（revert_form 技能即时还原） / cooldown_done（冷却 tick 归零）
STATE_TRANSITIONS: Dict[str, Dict[str, str]] = {
    STATE_NORMAL: {
        "trigger": STATE_TRANSFORMING,      # S1 → S2（触发技结算成功，F1）
    },
    STATE_TRANSFORMING: {
        "complete": STATE_FORM_ACTIVE,      # S2 → S3（同拍完成）
    },
    STATE_FORM_ACTIVE: {
        "expire": STATE_REVERTING,          # S3 → S4（turns 用尽/驱散命中，tick）
        "revert_now": STATE_REVERTING,      # S3 → S4（revert_form 即时，D-05）
    },
    STATE_REVERTING: {
        # S4 → S5（冷却 > 0）或 S4 → S1（冷却 = 0）——目标按冷却判定，迁移表
        # 登记双目标，由 resolve_transition() 按 cooldown_remaining 二选一
        "complete": STATE_COOLDOWN,
        "complete_no_cooldown": STATE_NORMAL,
    },
    STATE_COOLDOWN: {
        "cooldown_done": STATE_NORMAL,      # S5 → S1（冷却 tick 归零）
    },
}


def resolve_transition(
    current: str,
    event: str,
    cooldown_remaining: int = 0,
) -> Optional[str]:
    """按状态迁移表解析目标态（§3.2 状态图；未知源态/事件 → None，确定性兜底）。

    REVERTING 完成事件按冷却二分：cooldown_remaining > 0 → S5 COOLDOWN；
    否则 → S1 NORMAL（§3.1 S4 退出：「→ COOLDOWN（冷却 > 0）或 → NORMAL
    （冷却 = 0）」）。
    """
    table = STATE_TRANSITIONS.get(current)
    if table is None:
        return None
    target = table.get(event)
    if target is None:
        return None
    if current == STATE_REVERTING and event == "complete":
        return STATE_COOLDOWN if cooldown_remaining > 0 else STATE_NORMAL
    return target


# =====================================================================================
# transform_state 段键（对齐 6C transform_snapshot 7 字段契约口径，本地镜像常量）
# =====================================================================================

# battle_state 内新增段键（§4.1 JSONC 示例；6C 同键，本文件本地镜像防循环依赖）
TRANSFORM_STATE_KEY: str = "transform_state"

# 7 字段键（§4.1 T1~T7；6C TRANSFORM_STATE_FIELDS 同口径，本地镜像）
TRANSFORM_STATE_FIELDS: Tuple[str, ...] = (
    "job_id",               # T1 职业 ID 冗余（防热重载失效）
    "form",                 # T2 当前形态 ID；null=常态（S1/S5）
    "form_name",            # T3 形态显示名冗余
    "remaining",            # T4 形态剩余回合（含当回合；S3 >0）
    "cooldown_remaining",   # T5 形态冷却剩余（S5 >0）
    "form_status_id",       # T6 形态标记状态引用（双轨持久化）
    "active_skill_set",     # T7 当前技能位方案 ID（技能位重排恢复基准）
)


def empty_transform_state(job_id: str = "") -> Dict[str, Any]:
    """常态骨架（S1/S5 基准；T2 form=null=常态；7 字段全默认，对齐 6C 口径）。"""
    return {
        "job_id": job_id if isinstance(job_id, str) else "",
        "form": None,
        "form_name": "",
        "remaining": 0,
        "cooldown_remaining": 0,
        "form_status_id": None,
        "active_skill_set": "",
    }


# =====================================================================================
# 防御性读取辅助（类型校验 + 钳制，不抛异常——三铁律② 缺省兜底口径）
# =====================================================================================


def _norm_str(v: Any) -> str:
    """字符串归一：非 str → 空串（防御读取）。"""
    return v if isinstance(v, str) else ""


def _norm_opt_str(v: Any) -> Optional[str]:
    """可空字符串归一：None/空串/非 str → None（形态指针/状态引用空值语义）。"""
    if v is None:
        return None
    return v if isinstance(v, str) and v else None


def _norm_int(v: Any, default: int = 0) -> int:
    """整数归一（bool 除外）；非 int / 非法 → default。"""
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return default


def _norm_bool(v: Any, default: bool = False) -> bool:
    """布尔归一：非 bool → default（防御读取）。"""
    return v if isinstance(v, bool) else default


def _norm_str_list(v: Any) -> Tuple[str, ...]:
    """字符串列表归一：非 list → 空元组（防御读取）。"""
    if not isinstance(v, list):
        return ()
    return tuple(x for x in v if isinstance(x, str) and x)


def _norm_policy(v: Any) -> Dict[str, str]:
    """state_policy 段归一：非 Mapping → 空 dict（缺省三键由访问器兜底）。"""
    if not isinstance(v, Mapping):
        return {}
    out: Dict[str, str] = {}
    for key in ("combo", "marks", "buff"):
        val = v.get(key)
        if isinstance(val, str) and val in ("clear", "keep"):
            out[key] = val
    return out


def _transform_segment_of(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """transform 段定位：ctx[\"transform\"] → ctx[\"transform_def\"].raw →
    ctx[\"job\"].transform（G0 注入形态，防御读取缺省空）。"""
    v = ctx.get("transform")
    if isinstance(v, Mapping):
        return v
    td = ctx.get("transform_def")
    if isinstance(td, Mapping):
        return td
    job = ctx.get("job")
    if isinstance(job, Mapping):
        t = job.get("transform")
        if isinstance(t, Mapping):
            return t
    job_def = ctx.get("job_def")
    if job_def is not None:
        raw = getattr(job_def, "raw", None)
        if isinstance(raw, Mapping):
            t = raw.get("transform")
            if isinstance(t, Mapping):
                return t
    return {}


# =====================================================================================
# TransformStateKind 协议（G0 注入：引擎侧状态对象任意实现；Mapping 自动适配）
# =====================================================================================


class TransformStateKind(Protocol):
    """transform_state 访问器协议（core 层不 import content 的 G0 约束）。

    6C TransformStateKind 同构协议；raw dict 由 _RawStateAdapter 自动适配。
    属性缺省 = 常态默认（防御兜底）。
    """

    @property
    def job_id(self) -> str:
        """T1 职业 ID 冗余（缺省 ""）。"""
        ...

    @property
    def form(self) -> Optional[str]:
        """T2 当前形态 ID；None=常态（S1/S5）。"""
        ...

    @property
    def form_name(self) -> str:
        """T3 形态显示名冗余（缺省 ""）。"""
        ...

    @property
    def remaining(self) -> int:
        """T4 形态剩余回合（含当回合；缺省 0）。"""
        ...

    @property
    def cooldown_remaining(self) -> int:
        """T5 形态冷却剩余（缺省 0）。"""
        ...

    @property
    def form_status_id(self) -> Optional[str]:
        """T6 形态标记状态引用（缺省 None）。"""
        ...

    @property
    def active_skill_set(self) -> str:
        """T7 当前技能位方案 ID（缺省 ""）。"""
        ...


class _RawStateAdapter:
    """raw dict 适配 TransformStateKind（防御兜底：畸形值 → 常态默认）。"""

    __slots__ = ("_raw",)

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = raw

    @property
    def job_id(self) -> str:
        return _norm_str(self._raw.get("job_id"))

    @property
    def form(self) -> Optional[str]:
        return _norm_opt_str(self._raw.get("form"))

    @property
    def form_name(self) -> str:
        return _norm_str(self._raw.get("form_name"))

    @property
    def remaining(self) -> int:
        return _norm_int(self._raw.get("remaining"), 0)

    @property
    def cooldown_remaining(self) -> int:
        return _norm_int(self._raw.get("cooldown_remaining"), 0)

    @property
    def form_status_id(self) -> Optional[str]:
        return _norm_opt_str(self._raw.get("form_status_id"))

    @property
    def active_skill_set(self) -> str:
        return _norm_str(self._raw.get("active_skill_set"))


def _state_to_mapping(state: Any) -> Mapping[str, Any]:
    """任意状态对象 → 7 字段 Mapping（协议对象属性读取；raw dict 直返；其他 → 空）。

    属性值为 callable（如 property 方法）时取调用结果（防御性）。
    """
    if isinstance(state, Mapping):
        return state
    if hasattr(state, "job_id") and hasattr(state, "form"):
        raw: Dict[str, Any] = {}
        for key in TRANSFORM_STATE_FIELDS:
            v = getattr(state, key, None)
            raw[key] = v() if callable(v) else v
        return raw
    return {}


def normalize_transform_state(
    raw: Optional[Mapping[str, Any]],
    job_id: str = "",
) -> Dict[str, Any]:
    """transform_state 7 字段防御性归一（畸形键 → 合理默认，不抛异常）。

    对齐 6C normalize_transform_state 口径（快照读档防御）。不变量：
      - form=null（常态 S1/S5）时 remaining 强制 0（§4.1 T4「非 S3 时 0」）；
      - cooldown_remaining 独立保留（S5 冷却期 form=null 且 cooldown>0 合法，T5）；
      - job_id 优先取 raw 值，缺省回退参数 job_id（T1 冗余注入）。
    """
    out = empty_transform_state(job_id)
    if not isinstance(raw, Mapping):
        return out
    raw_job = _norm_str(raw.get("job_id"))
    if raw_job:
        out["job_id"] = raw_job
    out["form"] = _norm_opt_str(raw.get("form"))
    out["form_name"] = _norm_str(raw.get("form_name"))
    out["remaining"] = max(0, _norm_int(raw.get("remaining"), 0))
    out["cooldown_remaining"] = max(0, _norm_int(raw.get("cooldown_remaining"), 0))
    out["form_status_id"] = _norm_opt_str(raw.get("form_status_id"))
    out["active_skill_set"] = _norm_str(raw.get("active_skill_set"))
    if out["form"] is None:
        out["remaining"] = 0  # 常态无剩余回合（§4.1 T4）
    return out


def transform_state_of(ctx: Mapping[str, Any]) -> Dict[str, Any]:
    """从 ctx 读取当前 transform_state 段（缺省 → 常态骨架，确定性兜底）。

    ctx[\"transform_state\"] 优先（战斗快照权威段）；缺省回退
    ctx[\"player\"].persistent_state[\"transform_state\"]（存档兜底，对齐
    fishing._persistent_state_of 惰性挂回形态）；再缺省 → 常态骨架。
    """
    ts = ctx.get("transform_state")
    if isinstance(ts, Mapping):
        return normalize_transform_state(ts)
    player = ctx.get("player")
    if isinstance(player, Mapping):
        ps = player.get("persistent_state")
        if isinstance(ps, Mapping):
            saved = ps.get("transform_state")
            if isinstance(saved, Mapping):
                return normalize_transform_state(saved)
    return empty_transform_state()


# =====================================================================================
# 状态判定（S1/S3/S5 可观测用户态 + S2/S4 瞬态判定，§3.1）
# =====================================================================================


def state_of_transform_state(state: Any) -> str:
    """从 transform_state 段推导可观测状态机用户态（§3.1 S1/S3/S5）。

    判定序（确定性）：form 非空 → S3 FORM_ACTIVE；form 空且
    cooldown_remaining > 0 → S5 COOLDOWN；否则 → S1 NORMAL。
    S2/S4 为瞬态（不落快照、不占回合，D-03）——快照推导不到，返回由
    transient 事件语义表达（resolve_transition 迁移路径），本函数只产
    可观测常态（S1/S3/S5）。
    """
    ts = normalize_transform_state(_state_to_mapping(state))
    if ts["form"] is not None:
        return STATE_FORM_ACTIVE
    if ts["cooldown_remaining"] > 0:
        return STATE_COOLDOWN
    return STATE_NORMAL


def is_form_active(state: Any) -> bool:
    """S3 形态激活判定：form 非空（§3.1 S3 为常态用户态）。"""
    return state_of_transform_state(state) == STATE_FORM_ACTIVE


def is_cooldown_active(state: Any) -> bool:
    """S5 冷却期判定：cooldown_remaining > 0（§3.1 S5 常态；S1 无冷却）。"""
    return state_of_transform_state(state) == STATE_COOLDOWN


# =====================================================================================
# 触发闸 C1~C4（细化_6b §3.3 触发条件：全部满足才允许施放触发技）
# =====================================================================================


def _resolve_resource_check(
    ctx: Mapping[str, Any],
    transform: Mapping[str, Any],
) -> Tuple[bool, str]:
    """C2 资源校验：ctx[\"resource_check_hook\"] 注入（6c 资源轴未定稿前由
    战斗层接线 MP/怒气判定）；缺省放行（{True, \"\"}，F1-7）。"""
    hook = ctx.get("resource_check_hook")
    if callable(hook):
        try:
            result = hook(ctx, transform)
        except Exception:
            return False, "资源校验异常"
        if isinstance(result, Mapping):
            ok = bool(result.get("ok", False))
            reason = str(result.get("reason") or "资源不足")
            return ok, "" if ok else reason
        return bool(result), "资源不足"
    return True, ""


def _resolve_skip_check(ctx: Mapping[str, Any]) -> bool:
    """C4 被控（skip_turn）判定：ctx[\"skip_check\"] 注入；缺省 False 放行
    （F1-7：战斗层接线时注入行动权判定，引擎零 NoneBot 平台无关）。"""
    hook = ctx.get("skip_check")
    if callable(hook):
        try:
            return bool(hook(ctx))
        except Exception:
            return False
    return False


def can_transform(
    ctx: Mapping[str, Any], transform: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """触发闸 C1~C4（§3.3）：全部满足才允许施放触发技；任一不满足 → 拒绝。

    判定序（确定性，逐条短路返回）：
      C1 当前形态 = 常态（S1/S5）：transform_state.form 为空；形态激活期
         transform_skill 不可用（TC-03，显式互斥拒绝）；
      C2 资源足够：ctx[\"resource_check_hook\"] 注入（6c 未定稿缺省放行，
         F1-7；TC-02 怒气不足拒绝归战斗层接线）；
      C3 形态冷却已转好：cooldown_remaining <= 0（S5 冷却 >0 拒绝，TC-03）；
      C4 战斗进行中且非不可行动状态：ctx[\"skip_check\"] 注入（缺省 False
         放行；被控 skip_turn 不触发，TC-04，怒气保留归战斗层）。

    入参：transform = transform 段（缺省从 ctx 读取）；返回 {ok, reason,
    guard}（guard ∈ C1~C4，ok=True 时 guard=\"\"）。
    """
    seg = transform if isinstance(transform, Mapping) else _transform_segment_of(ctx)
    ts = transform_state_of(ctx)
    if ts["form"] is not None:
        return {"ok": False, "reason": "形态激活期不可变换（C1）", "guard": "C1"}
    ok, reason = _resolve_resource_check(ctx, seg)
    if not ok:
        return {"ok": False, "reason": reason or "资源不足（C2）", "guard": "C2"}
    if ts["cooldown_remaining"] > 0:
        return {
            "ok": False,
            "reason": f"形态冷却中（剩余 {ts['cooldown_remaining']} 回合，C3）",
            "guard": "C3",
        }
    if _resolve_skip_check(ctx):
        return {"ok": False, "reason": "被控制无法行动（C4）", "guard": "C4"}
    return {"ok": True, "reason": "", "guard": ""}


# =====================================================================================
# 技能位重排（细化_6b §3.3 洗牌 SH-1~5；引擎化纯函数）
# =====================================================================================

# 槽位类型（对齐 skill_slots 常量口径，本地镜像防循环依赖）
SLOT_BASIC: str = "basic"
SLOT_ACTIVE: str = "active"
SLOT_PASSIVE: str = "passive"
SLOT_TRIGGER: str = "trigger"

# 槽位类型顺序（basic 固定第 1 位 → active → passive → trigger，SH-1/SH-2）
_SLOT_KIND_ORDER: Tuple[str, ...] = (SLOT_BASIC, SLOT_ACTIVE, SLOT_PASSIVE, SLOT_TRIGGER)


class SkillEntryKind(Protocol):
    """技能条目访问器协议（G0 注入；SkillDef 天然满足；raw dict 自动适配）。

    derive_only 为 6a 技能挂点（§1.5 #38：派生形态技能不占技能位）。
    """

    @property
    def id(self) -> str:  # noqa: A003
        """技能 id（全库唯一）。"""
        ...

    @property
    def type(self) -> str:
        """四类时机 basic/active/passive/trigger（缺省 active）。"""
        ...

    @property
    def derive_only(self) -> bool:
        """派生形态技能（SH-3：不占技能位/不可直接施放/仅派生替换出现）。"""
        ...


class _RawSkillAdapter:
    """raw dict 条目适配 SkillEntryKind（type 缺省 active / derive_only 缺省 False）。"""

    __slots__ = ("_entry",)

    def __init__(self, entry: Mapping[str, Any]) -> None:
        self._entry = entry

    @property
    def id(self) -> str:  # noqa: A003
        v = self._entry.get("id")
        return v if isinstance(v, str) and v else ""

    @property
    def type(self) -> str:
        v = self._entry.get("type")
        return v if isinstance(v, str) else SLOT_ACTIVE

    @property
    def derive_only(self) -> bool:
        v = self._entry.get("derive_only")
        return v if isinstance(v, bool) else False


def _as_skill(entry: Any) -> SkillEntryKind:
    """任意条目适配 SkillEntryKind（协议对象直返；raw dict 包装；其他 → 空占位）。"""
    if hasattr(entry, "type") and hasattr(entry, "derive_only"):
        return cast(SkillEntryKind, entry)
    if isinstance(entry, Mapping):
        return _RawSkillAdapter(entry)
    return _RawSkillAdapter({})


def rearrange_slots(
    snapshot: Mapping[str, Any],
    form_skills: Sequence[Any],
) -> Dict[str, Any]:
    """技能位重排（§3.3 洗牌 SH-1~5 引擎化；F1 ④c 动作）。

    入参：
      snapshot:    当前装配快照（assemble_slots 产物形态：slots /
                   active_order / passive / trigger / version；缺省 → 空骨架）。
      form_skills: 形态技能组（skill_set 组内技能条目序列：SkillDef / raw
                   dict / 任意 SkillEntryKind 协议对象，G0 注入）。
    出参：重排后快照 dict（可 JSON 序列化）：
      - basic 固定第 1 位（SH-1 主动位互换：常态主动位 ↔ 形态主动位）；
      - active 顺序 = 组内库序（形态主动技能位，SH-1）；
      - passive/trigger 槽独立装配（SH-2：被动/触发槽双形态独立，job_form
        字段限定归装配层过滤，本层按组内条目装配）；
      - derive_only 条目不占任何位（SH-3，派生形态技能不占技能位）；
      - 未知 type 条目跳过（防御性）；无 id 条目跳过。
    兜底（F1-4）：form_skills 为空/未注入 → 原快照副本（不臆造重排）；
    快照缺 basic → basic 槽 skill_id=None 占位（对齐 skill_slots P-3）。
    """
    base = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    entries = [_as_skill(s) for s in (form_skills or [])]
    basic: List[SkillEntryKind] = []
    actives: List[SkillEntryKind] = []
    passives: List[SkillEntryKind] = []
    triggers: List[SkillEntryKind] = []
    for s in entries:
        if not s.id or s.derive_only:
            continue  # 无 id / derive_only 不占位（SH-3）
        t = s.type
        if t == SLOT_BASIC:
            basic.append(s)
        elif t == SLOT_ACTIVE:
            actives.append(s)
        elif t == SLOT_PASSIVE:
            passives.append(s)
        elif t == SLOT_TRIGGER:
            triggers.append(s)
    if not basic and not actives and not passives and not triggers:
        # 组空/未注入 → 原快照副本（F1-4 防御兜底，不臆造重排）
        out = dict(base)
        out.setdefault("slots", [])
        out.setdefault("active_order", [])
        out.setdefault("passive", [])
        out.setdefault("trigger", [])
        out.setdefault("version", 1)
        return out
    basic_id: Optional[str] = basic[0].id if basic else None
    active_order = [s.id for s in actives]
    passive_slots: List[Dict[str, Any]] = [
        {"slot": SLOT_PASSIVE, "skill_id": s.id} for s in passives
    ]
    trigger_slots: List[Dict[str, Any]] = [
        {"slot": SLOT_TRIGGER, "skill_id": s.id} for s in triggers
    ]
    slots: List[Dict[str, Any]] = [{"slot": SLOT_BASIC, "skill_id": basic_id}]
    slots.extend({"slot": SLOT_ACTIVE, "skill_id": sid} for sid in active_order)
    slots.extend(passive_slots)
    slots.extend(trigger_slots)
    return {
        "slots": slots,
        "active_order": active_order,
        "passive": passive_slots,
        "trigger": trigger_slots,
        "version": int(base.get("version", 1)) if isinstance(base.get("version", 1), int) else 1,
    }


# =====================================================================================
# state_policy 处理（细化_6b §1.4 #32~#34 + §2.1 ④d：combo/marks/buff 三键）
# =====================================================================================

# buff 清除的分类值域（细化_1b 分类口径本地镜像：强化/增益类；防御性跳过
# 非 dict 条目；registry 注入时可经 _is_buff_entry 访问器扩展）
BUFF_CATEGORIES: Tuple[str, ...] = ("强化", "增益")


def _is_buff_entry(entry: Any) -> bool:
    """buff 类状态条目判定：category ∈ BUFF_CATEGORIES（细 1b 分类口径本地
    镜像；registry 注入可替换本访问器）。"""
    if isinstance(entry, Mapping):
        return str(entry.get("category") or "other") in BUFF_CATEGORIES
    cat = getattr(entry, "category", None)
    if isinstance(cat, str):
        return cat in BUFF_CATEGORIES
    return False


def _clear_combo_state(
    snap: MutableMapping[str, Any],
    side: str,
    reason: str,
) -> List[Dict[str, Any]]:
    """combo=clear：清连段+清活跃链（§1.4 #32）——写入 combo_state[side]
    五字段空态 + combo_events 审计（对齐 ComboEngine.write_state/clear 口径，
    combo.py L931-940：empty_combo_state 五字段 + combo_clear 事件）。"""
    cs = snap.setdefault("combo_state", {})
    if not isinstance(cs, dict):
        cs = snap["combo_state"] = {}
    cs[side] = {
        "chain_id": None,
        "chain_name": None,
        "count": 0,
        "hold": False,
        "step_index": -1,
    }
    events = snap.setdefault("combo_events", [])
    if not isinstance(events, list):
        events = snap["combo_events"] = []
    events.append(
        {"type": "combo_clear", "side": side, "reason": reason, "count_before": 0}
    )
    return events


def _clear_marks(snap: MutableMapping[str, Any], side: str) -> None:
    """marks=clear：清印记（§1.4 #33）——该侧印记实例列表置空。"""
    ms = snap.setdefault("marks_state", {})
    if not isinstance(ms, dict):
        ms = snap["marks_state"] = {}
    ms[side] = []


def _clear_buffs(snap: MutableMapping[str, Any], side: str) -> List[Dict[str, Any]]:
    """buff=clear：全清 buff（§1.4 #34）——移除该侧 status_state 中
    category ∈ BUFF_CATEGORIES 的条目（防御性跳过非 dict 条目，F1-3）。"""
    ss = snap.setdefault("status_state", {})
    if not isinstance(ss, dict):
        ss = snap["status_state"] = {}
    entries = ss.get(side)
    if not isinstance(entries, list):
        ss[side] = []
        return []
    removed: List[Dict[str, Any]] = []
    survivors: List[Any] = []
    for e in entries:
        if isinstance(e, dict) and _is_buff_entry(e):
            removed.append(e)
        else:
            survivors.append(e)
    ss[side] = survivors
    return removed


def apply_state_policy(
    snap: MutableMapping[str, Any],
    policy: Mapping[str, Any],
    side: str = "player",
    reason: str = "transform",
) -> Dict[str, Any]:
    """state_policy 处理（§2.1 ④d / §1.4 #32~#34；F1/F2 对称共用）。

    入参：
      snap:   战斗快照（combo_state/marks_state/status_state 段；缺省惰性建段）。
      policy: state_policy 段（combo/marks/buff 三键 clear|keep；缺省按
              clear/keep/keep——§1.4 默认值，与 StatePolicyDef 兜底同源）。
      side:   处理侧（缺省 player；PVP 敌方侧接线传 enemy，SN-5）。
      reason: 审计 reason（默认 transform；F2 还原传 revert，REV-3 对称）。
    出参：处理报告 dict {combo, marks, buff, cleared_buffs}（供消息/审计）。

    三键语义（§1.4 字段表）：
      combo: clear=清连段+清活跃链 / keep=保留（默认 clear）；
      marks: keep=保留（狂战士默认示例）/ clear=清印记（默认 keep）；
      buff:  keep=战嚎减伤/药剂临时层跨形态保留 / clear=全清（默认 keep）。
    """
    p = _norm_policy(policy)
    combo = p.get("combo", "clear")
    marks = p.get("marks", "keep")
    buff = p.get("buff", "keep")
    cleared_buffs: List[Dict[str, Any]] = []
    if combo == "clear":
        _clear_combo_state(snap, side, reason)
    if marks == "clear":
        _clear_marks(snap, side)
    if buff == "clear":
        cleared_buffs = _clear_buffs(snap, side)
    return {
        "combo": combo,
        "marks": marks,
        "buff": buff,
        "cleared_buffs": cleared_buffs,
    }


# =====================================================================================
# F1 变换触发主流程（细化_6b §2.1 流程 F1 ①~⑥ / TRF-1~6）
# =====================================================================================


def _resolve_skill_effect(
    ctx: Mapping[str, Any],
    transform: Mapping[str, Any],
) -> Dict[str, Any]:
    """③ 触发技效果先结算（TRF-1）：ctx[\"resolve_hook\"] 注入（战斗层技能
    结算通道）；缺省 = 记录 pending 事件返回 {ok:True}（F1-2，确定性兜底）。

    返回 {ok, effects, resolved}；resolve 失败 → 变换不触发（流程 ① 前
    拒绝路径，资源校验之外的触发技自身失败）。
    """
    hook = ctx.get("resolve_hook")
    if callable(hook):
        try:
            result = hook(ctx, transform)
        except Exception:
            return {"ok": False, "effects": [], "resolved": False, "error": "触发技结算异常"}
        if isinstance(result, Mapping):
            _effs = result.get("effects", [])
            return {
                "ok": bool(result.get("ok", False)),
                "effects": _effs if isinstance(_effs, list) else [],
                "resolved": True,
            }
        return {"ok": bool(result), "effects": [], "resolved": True}
    return {"ok": True, "effects": [], "resolved": False}


def _apply_form_status(
    ctx: Mapping[str, Any],
    transform: Mapping[str, Any],
    form: str,
) -> Optional[str]:
    """④a 施加形态状态（D-02 双轨效果侧）：ctx[\"apply_status_hook\"] 注入
    （effects.apply_status 通道）；缺省 = 返回 form_status_id 候选（transform
    段 form_status_id 或 None，F1-1 确定性兜底不写状态）。

    返回施加成功的形态状态 ID（form_status_id，T6 双写登记）；None = 未施加。
    """
    hook = ctx.get("apply_status_hook")
    if callable(hook):
        try:
            result = hook(ctx, transform, form)
        except Exception:
            return None
        if isinstance(result, Mapping):
            v = result.get("status_id") or result.get("form_status_id")
            return v if isinstance(v, str) and v else None
        if isinstance(result, str) and result:
            return result
        return None
    v = transform.get("form_status_id")
    return v if isinstance(v, str) and v else None


def _rearrange(
    ctx: Mapping[str, Any],
    transform: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    """④c 技能位重排（SH-1~5）：ctx[\"rearrange_hook\"] 注入（接线方可委托
    skill_slots.apply_job_form 或本模块 rearrange_slots）；缺省 = 本模块
    rearrange_slots（组内技能经 ctx[\"form_skills\"] 注入，G0）。"""
    hook = ctx.get("rearrange_hook")
    if callable(hook):
        try:
            result = hook(ctx, transform, snapshot)
        except Exception:
            return dict(snapshot) if isinstance(snapshot, Mapping) else {}
        if isinstance(result, Mapping):
            return dict(result)
        return dict(snapshot) if isinstance(snapshot, Mapping) else {}
    form_skills = ctx.get("form_skills")
    seq: Sequence[Any] = form_skills if isinstance(form_skills, (list, tuple)) else []
    return rearrange_slots(snapshot, seq)


def _reassess_chains(
    ctx: Mapping[str, Any],
    transform: Mapping[str, Any],
    form: str,
) -> Tuple[str, ...]:
    """⑤ 形态专属派生链重评估（job_scope 命中，§2.1⑤ / §2.3）：ctx 注入
    reassess_chains_hook(ctx, transform, form) → 命中链 ID 列表；缺省 = 原样
    返回 transform.derive_chains（F1-5，引擎不持有链表——skill_chains 数据
    经 ctx 注入，job_scope 求值归接线方/6a 链引擎）。"""
    hook = ctx.get("reassess_chains_hook")
    if callable(hook):
        try:
            result = hook(ctx, transform, form)
        except Exception:
            return ()
        if isinstance(result, (list, tuple)):
            return tuple(x for x in result if isinstance(x, str) and x)
        return ()
    return _norm_str_list(transform.get("derive_chains"))


def trigger_transform(
    ctx: MutableMapping[str, Any],
    transform: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """F1 变换触发主流程（细化_6b §2.1 流程 F1 ①~⑥；TC-01~04）。

    时序（契约逐条）：
      ① 玩家选择触发技（一次行动技能，耗 MP+回合）——调用方已识别
         transform_skill（技能结算通道）；
      ② 资源校验（C2/C3/C4 闸门：can_transform；不足 → 被拒不耗回合、
         不触发变换——TC-02/03/04）【资源本体归战斗层 6c，闸门可注入】；
      ③ 结算技能效果（先结算：resolve_hook 注入，TRF-1）——效果本体走
         现有技能结算通道（摸底报告已就绪），本流程保证时序先后；
      ④ 触发变换（不额外耗回合，TRF-2）四动作同拍：
         ④a 施加形态状态（apply_status_hook，D-02 效果侧；form_status_id
             登记 T6 双写）；
         ④b 切换 job_form → transform_to（transform_state.form）；
         ④c 技能位重排为 skill_set 组（SH-1~5；rearrange 产物落
             active_skill_set + 快照）；
         ④d 按 state_policy 处理（apply_state_policy：combo/marks/buff
             三键，默认清连段+清活跃链/印记 keep/buff keep，§1.4）；
      ⑤ 形态专属派生链重评估（reassess_chains_hook，job_scope 命中）；
      ⑥ 进入形态持续计数（remaining = transform.turns 含变身当回合，
         TC-01④；cooldown_remaining = transform.cooldown 从触发起算
         REV-6；D-03 回合结束 tick 递减归 F2 tick 引擎）。

    入参：
      ctx:       战斗上下文（MutableMapping；读写 transform_state /
                 combo_state / marks_state / status_state / combo_events 段，
                 G0 注入钩子：resource_check_hook / skip_check /
                 resolve_hook / apply_status_hook / rearrange_hook /
                 reassess_chains_hook / form_skills / transform_def /
                 job / job_def）。
      transform: transform 段（缺省从 ctx 读取，_transform_segment_of）。
    出参：结构化 dict：
      - ok:          变换是否触发（False = 拒绝/失败，reason/guard 给出）；
      - reason/guard: 拒绝原因/闸门（C1~C4）或结算失败原因；
      - state:       触发后状态机态（S3 FORM_ACTIVE 或 S1 NORMAL 未触发）；
      - transform_state: 新 7 字段段（T1~T7：job_id/form/form_name/
                        remaining/cooldown_remaining/form_status_id/
                        active_skill_set）——引擎轨（D-02），接线方挂
                        battle_state[TRANSFORM_STATE_KEY]；
      - slots_snapshot: 技能位重排快照（SH-1~5 产物，接线方落装配存档）；
      - policy_report:  state_policy 处理报告（combo/marks/buff/cleared_buffs）；
      - chains:       重评估命中的形态专属派生链 ID 列表（job_scope）；
      - side_effects: 效果轨事件列表（含 form_status_id 登记与 resolve
                      效果，D-02 双轨产物）；
      - action_used:  True（本次行动权已由触发技消耗，变换不额外耗回合
                      TRF-2——本字段供战斗层核对行动权语义）。
    拒绝路径不写任何段（幂等：不触发变换、不重结算、不耗额外回合）。
    """
    seg = transform if isinstance(transform, Mapping) else _transform_segment_of(ctx)
    ts = transform_state_of(ctx)
    effects_log: List[Dict[str, Any]] = []
    if ts["form"] is not None:
        return {
            "ok": False, "reason": "形态激活期不可变换（C1）", "guard": "C1",
            "state": state_of_transform_state(ts),
            "transform_state": ts, "slots_snapshot": None,
            "policy_report": None, "chains": (), "side_effects": effects_log,
            "action_used": False,
        }
    gate = can_transform(ctx, seg)
    if not gate["ok"]:
        return {
            "ok": False, "reason": gate["reason"], "guard": gate["guard"],
            "state": state_of_transform_state(ts),
            "transform_state": ts, "slots_snapshot": None,
            "policy_report": None, "chains": (), "side_effects": effects_log,
            "action_used": False,
        }
    # ③ 触发技效果先结算（TRF-1；效果本体走战斗层通道，本流程只保证时序）
    resolved = _resolve_skill_effect(ctx, seg)
    effects_log.append({
        "type": "resolve", "skill": seg.get("transform_skill"), "ok": resolved["ok"]
    })
    if not resolved["ok"]:
        return {
            "ok": False, "reason": str(resolved.get("error") or "触发技结算失败"),
            "guard": "", "state": state_of_transform_state(ts),
            "transform_state": ts, "slots_snapshot": None,
            "policy_report": None, "chains": (), "side_effects": effects_log,
            "action_used": True,
        }
    # ④ 触发变换（不额外耗回合，TRF-2）四动作同拍
    form = _norm_opt_str(seg.get("transform_to")) or ""
    form_name = _norm_str(seg.get("form_name")) or form
    form_status_id = _apply_form_status(ctx, seg, form)
    if form_status_id is not None:
        effects_log.append(
            {"type": "form_status_applied", "form": form, "form_status_id": form_status_id}
        )
    duration = _norm_str(seg.get("duration")) or "turns"
    turns = _norm_int(seg.get("turns"), 0)
    cooldown = max(0, _norm_int(seg.get("cooldown"), 0))
    remaining: int = -1 if duration == "battle" else max(1, turns)
    # 归一化不变量（对齐 6C F3-3）：form 非空（S3）时 remaining 恒 ≥0——
    # battle 哨兵 -1 经 normalize 会被钳 0，故 battle 模式直接落 -1 不归一
    new_ts_raw: Dict[str, Any] = {
        "job_id": _norm_str(ts.get("job_id")) or _norm_str(seg.get("job_id")),
        "form": form,
        "form_name": form_name,
        "remaining": remaining,
        "cooldown_remaining": cooldown,
        "form_status_id": form_status_id,
        "active_skill_set": _norm_str(seg.get("skill_set")),
    }
    if duration == "battle":
        new_ts = new_ts_raw
    else:
        new_ts = normalize_transform_state(new_ts_raw)
    slots = _rearrange(ctx, seg, {})
    policy_report = apply_state_policy(
        ctx, _norm_policy(seg.get("state_policy")), side="player", reason="transform"
    )
    chains = _reassess_chains(ctx, seg, form)
    effects_log.append(
        {
            "type": "transform_committed",
            "form": form,
            "remaining": remaining,
            "cooldown_remaining": cooldown,
            "active_skill_set": new_ts["active_skill_set"],
            "chains": list(chains),
        }
    )
    # 引擎轨落 ctx（transform_state 段挂回，对齐 _ps_init 惰性挂回形态）
    ctx[TRANSFORM_STATE_KEY] = new_ts
    return {
        "ok": True, "reason": "", "guard": "",
        "state": STATE_FORM_ACTIVE,
        "transform_state": new_ts,
        "slots_snapshot": slots,
        "policy_report": policy_report,
        "chains": chains,
        "side_effects": effects_log,
        "action_used": True,
    }


# =====================================================================================
# TransformEngine（引擎注入模式：构造器注入钩子，缺省 = 模块级纯函数默认行为）
# =====================================================================================


class TransformEngine:
    """F1 变换触发引擎（构造器注入模式，对齐 fishing.py 注入三件套 +
    forge_job.py 引擎持有者先例）。

    注入项（均可缺省，缺省 = 模块级纯函数默认行为，确定性保持）：
      resource_check_hook:   Callable[[Mapping, Mapping], Any] —— C2 资源校验
                             （6c 未定稿前缺省放行，F1-7）。
      resolve_hook:          Callable[[Mapping, Mapping], Any] —— ③ 触发技
                             效果先结算（TRF-1，F1-2）。
      apply_status_hook:     Callable[[Mapping, Mapping, str], Any] —— ④a 施加
                             形态状态（D-02 效果侧，F1-1）。
      rearrange_hook:        Callable[[Mapping, Mapping, Mapping], Any] —— ④c
                             技能位重排（SH-1~5，F1-4）。
      reassess_chains_hook:  Callable[[Mapping, Mapping, str], Any] —— ⑤ 派生链
                             重评估（job_scope，F1-5）。
      skip_check:            Callable[[Mapping], Any] —— C4 被控判定（F1-7）。
      audit:                 Callable[[str], None] —— 审计日志观察口。
    方法委托模块级纯函数（trigger_transform 前将注入钩子挂 ctx），不引入
    可变全局状态。
    """

    def __init__(
        self,
        *,
        resource_check_hook: Optional[Callable[..., Any]] = None,
        resolve_hook: Optional[Callable[..., Any]] = None,
        apply_status_hook: Optional[Callable[..., Any]] = None,
        rearrange_hook: Optional[Callable[..., Any]] = None,
        reassess_chains_hook: Optional[Callable[..., Any]] = None,
        skip_check: Optional[Callable[..., Any]] = None,
        audit: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._resource_check_hook = resource_check_hook
        self._resolve_hook = resolve_hook
        self._apply_status_hook = apply_status_hook
        self._rearrange_hook = rearrange_hook
        self._reassess_chains_hook = reassess_chains_hook
        self._skip_check = skip_check
        self._audit = audit

    def _inject(self, ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        """把构造器注入钩子挂 ctx（仅缺省键不覆盖调用方显式注入，幂等）。"""
        if self._resource_check_hook is not None:
            ctx.setdefault("resource_check_hook", self._resource_check_hook)
        if self._resolve_hook is not None:
            ctx.setdefault("resolve_hook", self._resolve_hook)
        if self._apply_status_hook is not None:
            ctx.setdefault("apply_status_hook", self._apply_status_hook)
        if self._rearrange_hook is not None:
            ctx.setdefault("rearrange_hook", self._rearrange_hook)
        if self._reassess_chains_hook is not None:
            ctx.setdefault("reassess_chains_hook", self._reassess_chains_hook)
        if self._skip_check is not None:
            ctx.setdefault("skip_check", self._skip_check)
        return ctx

    def trigger(
        self, ctx: MutableMapping[str, Any], transform: Optional[Mapping[str, Any]] = None
    ) -> Dict[str, Any]:
        """F1 触发（引擎版）：注入钩子挂 ctx 后委托模块级 trigger_transform。"""
        result = trigger_transform(self._inject(ctx), transform)
        if self._audit is not None:
            self._audit(
                "transform_f1: ok=%s guard=%s form=%s"
                % (
                    result.get("ok"), result.get("guard"),
                    result.get("transform_state", {}).get("form"),
                )
            )
        return result


__all__ = [
    # 状态机常量
    "STATE_NORMAL",
    "STATE_TRANSFORMING",
    "STATE_FORM_ACTIVE",
    "STATE_REVERTING",
    "STATE_COOLDOWN",
    "TRANSFORM_STATES",
    "TRANSIENT_STATES",
    "OBSERVABLE_STATES",
    "STATE_TRANSITIONS",
    "resolve_transition",
    # transform_state 段
    "TRANSFORM_STATE_KEY",
    "TRANSFORM_STATE_FIELDS",
    "empty_transform_state",
    "normalize_transform_state",
    "transform_state_of",
    "TransformStateKind",
    # 状态判定
    "state_of_transform_state",
    "is_form_active",
    "is_cooldown_active",
    # 触发闸
    "can_transform",
    # 技能位重排
    "SLOT_BASIC",
    "SLOT_ACTIVE",
    "SLOT_PASSIVE",
    "SLOT_TRIGGER",
    "SkillEntryKind",
    "rearrange_slots",
    # state_policy
    "BUFF_CATEGORIES",
    "apply_state_policy",
    # F1 主流程
    "trigger_transform",
    # 引擎
    "TransformEngine",
]
