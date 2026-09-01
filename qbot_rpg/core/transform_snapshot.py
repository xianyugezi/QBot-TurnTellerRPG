"""M13 批6 路6C · 6b 变换引擎 F3 快照续战（qbot_rpg/core/transform_snapshot.py）。

文件名：qbot_rpg/core/transform_snapshot.py
创建时间：2026-09-02
作者：Hermes 子agent-6C（M13 6b 变换引擎实现组批6路6C：并发同仓，仅新建本文件 +
  tests/unit/test_transform_f3.py；不碰兄弟文件——6A 独占 core/transform.py（F1）、
  6B 独占 core/transform_revert.py（F2），本文件独立实现 F3，主 agent 收口合并）

功能描述：变换引擎 F3 快照写入与恢复（细化_6b §四 F3 流程 + §4.1~4.3，TC-13~16）：
  1) transform_state 7 字段定义（T1~T7：job_id/form/form_name/remaining/
     cooldown_remaining/form_status_id/active_skill_set，§4.1 字段表逐字段语义）：
     - TRANSFORM_STATE_KEY 快照段键（battle_state 内新增段，承接 1g1c/1g3 容器）
     - TRANSFORM_STATE_FIELDS 恰 7 键登记（与契约字段表逐键一致，防漂移）
     - empty_transform_state() 常态骨架（S1/S5 基准；form=null=常态，T2）
  2) snapshot_write(state)   F3 写入接口：7 字段归一化快照（可 JSON 序列化，
     深拷贝防外部改写；None → 常态骨架；协议对象/raw dict 双形态输入，G0 注入）
  3) snapshot_restore(snap)  F3 恢复接口：中断续战按快照还原形态上下文——
     ② form 恢复形态指针 / ③ active_skill_set 恢复技能位重排基准 /
     ④ remaining 恢复剩余回合计数（回合结束 tick 递减继续，递减推进归 F2 tick 引擎）/
     ⑤ T6 交叉校验（form_status_id 与 status_state 双写一致，不一致以较早者为准
     + audit 审计日志，§4.2⑤【细化补充】）/ SN-3 删除降级（状态本体缺失 →
     降级 form_status_id=None，形态保留、技能位按 active_skill_set 清偿，
     不报错不悬空，§4.3 SN-3）
  4) clear_transform_state() SN-4 战斗结束清零：死亡/胜利/失败/逃跑 →
     全段清零回常态（job_id 冗余保留；怒气 reset=battle 同批清零归 6c 资源轴）
  5) 挂点辅助（摸底报告挂载点建议）：
     - attach_initial_state()  start() 初始化建段（battle_state[TRANSFORM_STATE_KEY]
       = 常态骨架 + T1 职业 ID 注入）
     - attach_cleared_state()  _settle 战斗结束清零挂点（SN-4 + transform_cleared_at
       审计键，对齐 combo_zeroed_at 先例）
     - to_snapshot 深拷贝自动携带本段（无需额外代码）；from_snapshot 透传恢复同理
       （恢复上下文由接线方按 snapshot_restore 出参消费）
  6) TransformSnapshotEngine  引擎注入模式（构造器注入 job_id_provider /
     status_state_provider / audit 回调，缺省 = 模块级纯函数默认行为；
     对齐 forge_job.py 模块级引擎持有者先例）

依据：
  - docs/细化/细化_6b_职业库与变换引擎.md（409 行 v1.0）：
    §4.1 battle_state 中 transform 字段（7 字段 JSONC 示例 L274-285 + 字段表
    T1~T7 L287-295：job_id 冗余 OLD-2 / form null=常态 / form_name 展示冗余 /
    remaining 含当回合 S3>0 / cooldown_remaining S5>0 / form_status_id 双轨持久化 /
    active_skill_set 洗牌恢复基准）；
    §4.2 快照写入与恢复时序（流程 F3 ①~⑥：回合边界同批落快照 / 中断恢复
    还原形态 / active_skill_set 技能位恢复 / remaining 恢复 / T6 双写交叉校验
    【细化补充】/ 战斗结束全段清零回常态【狂战士 L135】）；
    §4.3 边界与一致性规则（SN-1 快照只落回合边界 / SN-2 旧局旧配置 ID+名称冗余 /
    SN-3 删除降级 / SN-4 形态随战斗清零 / SN-5 PVP 同规格归 4e）。
  - docs/m13_6b摸底.md（缺口：transform_state 7 字段未落快照——battle.py
    start L890-933 无该段、to_snapshot L1748-1780 未含、data/battle.py
    BattleSnapshot L46-75 无字段、_settle L742+ 无清零；挂载点建议：
    start() 初始化建段 / to_snapshot 深拷贝自动携带 / from_snapshot L1804-1864
    透传恢复 / _settle 增清零）。
  - 模式参考：qbot_rpg/core/skill_slots.py（SlotKind 协议 G0 注入 + _RawSkillAdapter
    兜底 + _normalize_snapshot 防御归一）、qbot_rpg/core/forge_job.py（模块级
    纯函数集合 + 构造器注入）、qbot_rpg/content/job_models.py（transform 段
    11 字段 + state_policy 3 字段模型，本文件零 import 只读契约口径）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  F3-1  T6 交叉校验的实现口径：status_state 侧条目查找按 {side: [entries]} 结构
        （battle_state status_state 形态），条目 id 键兼容 "id"/"status_id"；
        时长字段取 entry 的 remaining/turns/duration 首数值（防御性读取）；
        双写不一致 → 取较早者（min）并回调 audit（§4.2⑤「不一致以较早者为准
        +审计日志」为细化补充，无现成 status schema 可引用，按最小防御口径实现）。
  F3-2  SN-3 删除降级的判定边界：form_status_id 非空但 status_state 中找不到
        对应条目（配置删除/状态已被驱散）→ form_status_id 降级 None、form 与
        active_skill_set 保留（契约原文「形态保留、技能位按 active_skill_set
        清偿」），不抛异常不悬空；audit 可注入观察。
  F3-3  归一化不变量：form=null（常态 S1/S5）时 remaining 强制 0（§4.1 T4
        「非 S3 时 0」）；cooldown_remaining 独立保留（S5 冷却期 form=null 且
        cooldown>0 是合法状态，T5，不可随 form 清空）。
  F3-4  remaining 的回合递减（D-03 回合结束 tick 推进）归 F2 还原引擎
        （transform_revert.py，6B）；本文件只做快照写/读与恢复上下文，
        不实现 tick 递减（避免与兄弟路重叠）。
  F3-5  模块级函数均为纯函数（同刻同参必同值）；TransformSnapshotEngine
        注入回调仅作数据来源/观察口，不引入可变全局状态。

铁律：零 NoneBot import；core 层只依赖 data（本文件零 import content/data，
纯标准库）；平台无关；零定时器/零睡眠（本文件不含任何 sleep/定时器调用）；
不引入随机；不 git commit；只写本文件 + 自己的测试。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional, Tuple

# =====================================================================================
# 常量：transform_state 段键 + 7 字段登记（细化_6b §4.1 T1~T7）
# =====================================================================================

# battle_state 内新增段键（§4.1 JSONC 示例；承接 1g1c/1g3 快照容器）
TRANSFORM_STATE_KEY: str = "transform_state"

# 7 字段登记（§4.1 字段表 T1~T7 逐键；与契约键名一致，防字段漂移）
TRANSFORM_STATE_FIELDS: Tuple[str, ...] = (
    "job_id",               # T1 职业 ID 冗余（防热重载失效，3e2 OLD-2）
    "form",                 # T2 当前形态 ID；null=常态（S1/S5）
    "form_name",            # T3 形态显示名冗余（1g3 展示用，防配置删除后悬空）
    "remaining",            # T4 形态剩余回合（含当回合；S3 时 >0，非 S3 时 0）
    "cooldown_remaining",   # T5 形态冷却剩余（S5 时 >0；S1/S3 时 0）
    "form_status_id",       # T6 形态标记状态引用（联动 dispel_reverts，双轨持久化）
    "active_skill_set",     # T7 当前技能位方案 ID（技能位重排的恢复基准）
)

# 战斗结束清零审计键（对齐 core/battle.py combo_zeroed_at 审计先例，SN-4）
_TRANSFORM_CLEARED_KEY: str = "transform_cleared_at"


def empty_transform_state(job_id: str = "") -> Dict[str, Any]:
    """常态骨架（S1/S5 基准；SN-4 清零目标形态；T2 form=null=常态）。

    7 字段全默认：job_id 注入 / form None / form_name "" / remaining 0 /
    cooldown_remaining 0 / form_status_id None / active_skill_set ""。
    返回新 dict（可 JSON 序列化），调用方可直接挂 battle_state。
    """
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
    """可空字符串归一：None/空串/非 str → None（形态指针/状态引用的空值语义）。"""
    if v is None:
        return None
    return v if isinstance(v, str) and v else None


def _norm_int_nonneg(v: Any) -> int:
    """非负整数归一：非 int（含 bool）/ 负值 → 0 钳制（防御读取）。"""
    if isinstance(v, int) and not isinstance(v, bool):
        return max(v, 0)
    return 0


# =====================================================================================
# 7 字段归一化（写/读共用的防御性归一，F3-3 不变量）
# =====================================================================================


def normalize_transform_state(
    raw: Optional[Mapping[str, Any]],
    job_id: str = "",
) -> Dict[str, Any]:
    """transform_state 7 字段防御性归一（畸形键 → 合理默认，不抛异常）。

    对齐 skill_slots._normalize_snapshot 模式（快照读档防御）。不变量（F3-3）：
      - form=null（常态 S1/S5）时 remaining 强制 0（§4.1 T4「非 S3 时 0」）；
      - cooldown_remaining 独立保留（S5 冷却期 form=null 且 cooldown>0 合法，T5）；
      - job_id 优先取 raw 值，缺省回退参数 job_id（T1 冗余注入）。
    返回 7 字段全量 dict（含缺省键，快照段恒为全字段形态）。
    """
    out = empty_transform_state(job_id)
    if not isinstance(raw, Mapping):
        return out
    raw_job = _norm_str(raw.get("job_id"))
    if raw_job:
        out["job_id"] = raw_job
    out["form"] = _norm_opt_str(raw.get("form"))
    out["form_name"] = _norm_str(raw.get("form_name"))
    out["remaining"] = _norm_int_nonneg(raw.get("remaining"))
    out["cooldown_remaining"] = _norm_int_nonneg(raw.get("cooldown_remaining"))
    out["form_status_id"] = _norm_opt_str(raw.get("form_status_id"))
    out["active_skill_set"] = _norm_str(raw.get("active_skill_set"))
    if out["form"] is None:
        out["remaining"] = 0  # 常态无剩余回合（§4.1 T4）
    return out


# =====================================================================================
# TransformStateKind 协议（G0 注入：引擎侧状态对象任意实现；Mapping 自动适配）
# =====================================================================================


class TransformStateKind:
    """transform_state 访问器协议（core 层不 import content 的 G0 约束）。

    6A/6B 引擎侧状态对象（任意满足本协议的类）可直接传入 snapshot_write；
    raw dict 由 _RawStateAdapter 自动适配。属性缺省 = 常态默认（防御兜底）。
    """

    @property
    def job_id(self) -> str:
        """T1 职业 ID 冗余（缺省 ""）。"""
        return ""

    @property
    def form(self) -> Optional[str]:
        """T2 当前形态 ID；None=常态（S1/S5）。"""
        return None

    @property
    def form_name(self) -> str:
        """T3 形态显示名冗余（缺省 ""）。"""
        return ""

    @property
    def remaining(self) -> int:
        """T4 形态剩余回合（含当回合；缺省 0）。"""
        return 0

    @property
    def cooldown_remaining(self) -> int:
        """T5 形态冷却剩余（缺省 0）。"""
        return 0

    @property
    def form_status_id(self) -> Optional[str]:
        """T6 形态标记状态引用（缺省 None）。"""
        return None

    @property
    def active_skill_set(self) -> str:
        """T7 当前技能位方案 ID（缺省 ""）。"""
        return ""


class _RawStateAdapter(TransformStateKind):
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
        return _norm_int_nonneg(self._raw.get("remaining"))

    @property
    def cooldown_remaining(self) -> int:
        return _norm_int_nonneg(self._raw.get("cooldown_remaining"))

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
    if isinstance(state, TransformStateKind):
        raw: Dict[str, Any] = {}
        for key in TRANSFORM_STATE_FIELDS:
            v = getattr(state, key, None)
            raw[key] = v() if callable(v) else v
        return raw
    return {}


# =====================================================================================
# F3 写入接口（snapshot_write）
# =====================================================================================


def snapshot_write(state: Any = None) -> Dict[str, Any]:
    """F3 写入：transform_state 7 字段快照（可 JSON 序列化，深拷贝防外部改写）。

    入参：
      state: 引擎侧 transform_state——raw dict / TransformStateKind 协议对象
             （6A/6B 状态对象直接注入，G0）/ None（→ 常态骨架，start 建段用）。
    出参：7 字段归一 dict（含缺省键全字段形态），调用方挂
    battle_state[TRANSFORM_STATE_KEY]。

    F3 ① 落点：回合结束 tick 后（形态递减已发生，递减归 F2）transform_state
    与 resource_state/combo_state/status_state 同批落快照【狂战士 L427】【1g3 S0】；
    to_snapshot 深拷贝自动携带本段（battle.py L1774 copy.deepcopy(self._snap)），
    本接口产出即段内容。
    """
    if state is None:
        return empty_transform_state()
    return normalize_transform_state(_state_to_mapping(state))


# =====================================================================================
# F3 恢复接口（snapshot_restore：中断续战还原形态上下文 + T6 交叉校验 + SN-3 降级）
# =====================================================================================


def _find_status_entry(
    status_state: Optional[Mapping[str, Any]],
    form_status_id: str,
    side: str = "player",
) -> Optional[Mapping[str, Any]]:
    """status_state 中按形态状态 id 查找条目（F3-1 实现口径）。

    status_state 形态 = {side: [entries]}（battle_state 结构）；条目 id 键兼容
    "id"/"status_id"（防御性，防 status schema 键名差异）；缺省 side="player"
    （形态挂在玩家侧，SN-5 PVP 同规格归 4e 接线时传 enemy）。
    """
    if not isinstance(status_state, Mapping):
        return None
    entries = status_state.get(side)
    if not isinstance(entries, list):
        return None
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        eid = e.get("id")
        if not isinstance(eid, str):
            eid = e.get("status_id")
        if eid == form_status_id:
            return e
    return None


def _status_remaining(entry: Mapping[str, Any]) -> Optional[int]:
    """状态条目时长字段读取（remaining/turns/duration 首数值；防御性，F3-1）。

    用于 T6 双写一致性校验：引擎计数 T4 与状态时长双写，取较早者（min）。
    """
    for key in ("remaining", "turns", "duration"):
        v = entry.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            return v
    return None


def snapshot_restore(
    snap: Optional[Mapping[str, Any]],
    *,
    status_state: Optional[Mapping[str, Any]] = None,
    side: str = "player",
    audit: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """F3 恢复：中断续战按快照还原形态上下文（流程 F3 ②~⑤ / TC-14）。

    时序（细化_6b §4.2）：
      ② 读 transform_state：form 非空 → 恢复形态上下文（无需重新触发）；
      ③ active_skill_set 恢复技能位重排（形态技能组直接可用，T7）；
      ④ remaining 恢复剩余回合计数（回合结束 tick 递减继续，递减归 F2）；
      ⑤ T6 交叉校验：form_status_id 与 status_state 双写一致，不一致以较早者
         为准 + audit 审计日志（F3-1 实现口径）。
    降级（§4.3）：
      - SN-3 删除降级：form_status_id 在 status_state 缺失（配置删除/状态已清）
        → form_status_id 降级 None（形态保留、技能位按 active_skill_set 清偿，
        不报错不悬空），audit 可观察；
      - 旧档兼容：快照无 transform_state 段 → 常态骨架（非 None，确定性兜底）。

    入参：
      snap:         战斗快照（battle_state dict，含 transform_state 段；缺省 None
                    → 常态骨架）。
      status_state: status_state 段（battle_state.status_state；缺省 None → 跳过
                    T6 交叉校验，仅归一恢复）。
      side:         状态挂侧（缺省 "player"；PVP 敌方侧接线时传 "enemy"）。
      audit:        审计日志回调（F3 ⑤ 双写不一致 / SN-3 降级时调用，可空）。
    出参：恢复后的 transform_state dict（7 字段全量，可直接挂回 battle_state /
    供接线方消费技能位/剩余回合/形态指针）。

    T6 校验数据源约定：status_state 为可选注入（接线方提供战斗的
    status_state 段时执行交叉校验/降级；缺省 None → 原样恢复不做校验，
    恢复上下文完整交付，TC-13 round-trip 全字段一致）。
    """
    if not isinstance(snap, Mapping):
        return empty_transform_state()
    raw = snap.get(TRANSFORM_STATE_KEY)
    out = normalize_transform_state(raw if isinstance(raw, Mapping) else None)
    if out["form"] is not None and out["form_status_id"] is not None:
        # T6 交叉校验仅在校验数据源（status_state）可用时执行（F3-1）：
        # 调用方未提供 status_state → 不做校验、不降级，form_status_id 原样保留
        # （恢复上下文完整交付，校验归接线方决定是否注入数据源）。
        if status_state is None:
            return out
        entry = _find_status_entry(status_state, out["form_status_id"], side=side)
        if entry is None:
            # SN-3：状态本体缺失（配置删除/已被驱散）→ 降级，不报错不悬空
            if audit is not None:
                audit(
                    "transform_snapshot: form_status_id=%r 在 status_state 缺失，"
                    "降级为无形态状态（SN-3）" % (out["form_status_id"],)
                )
            out["form_status_id"] = None
        else:
            s_rem = _status_remaining(entry)
            if s_rem is not None and s_rem != out["remaining"]:
                # F3 ⑤：双写不一致 → 以较早者为准（min）+ 审计日志
                earlier = min(s_rem, out["remaining"])
                if audit is not None:
                    audit(
                        "transform_snapshot: T4/T6 双写不一致 remaining=%d vs "
                        "status=%d，取较早者 %d" % (out["remaining"], s_rem, earlier)
                    )
                out["remaining"] = earlier
    return out


# =====================================================================================
# SN-4 战斗结束清零（_settle 挂点）
# =====================================================================================


def clear_transform_state(job_id: str = "") -> Dict[str, Any]:
    """SN-4 形态随战斗清零：死亡/胜利/失败/逃跑 → 全段清零回常态。

    【狂战士 L79/L135】形态随战斗结束还原回常态；job_id 冗余保留（职业归属
    不清零，T1）；怒气 reset=battle 同批清零归 6c 资源轴（本文件不含）。
    出参：常态骨架 dict（form=None / remaining=0 / cooldown_remaining=0 /
    form_status_id=None / active_skill_set=""）。
    """
    return empty_transform_state(job_id)


# =====================================================================================
# 挂点辅助（摸底报告挂载点建议：start() 建段 / _settle 清零）
# =====================================================================================


def attach_initial_state(
    battle_state: MutableMapping[str, Any],
    job_id: str = "",
) -> Dict[str, Any]:
    """start() 初始化建段挂点：battle_state[TRANSFORM_STATE_KEY] = 常态骨架。

    摸底报告 L18：battle.py start L890-933 无 transform_state 段 → 本挂点补建
    （T1 职业 ID 注入，常态 S1）。此后 to_snapshot 深拷贝自动携带本段
    （battle.py to_snapshot L1774 deepcopy），from_snapshot 透传恢复
    （_snap = deepcopy(data) 自动携带）。
    """
    node = empty_transform_state(job_id)
    battle_state[TRANSFORM_STATE_KEY] = node
    return node


def attach_cleared_state(
    battle_state: MutableMapping[str, Any],
    job_id: str = "",
) -> Dict[str, Any]:
    """_settle 战斗结束清零挂点（SN-4）：transform_state 全段清零回常态。

    摸底报告 L18：_settle L742+ 无 SN-4 清零 → 本挂点补清（死亡/胜利/失败/
    逃跑四路统一；battle.py _settle 为统一收尾入口 L742-783）。对齐
    combo_zeroed_at 审计先例：battle_state 增 transform_cleared_at="battle_end"。
    返回清零后段。
    """
    node = clear_transform_state(job_id)
    battle_state[TRANSFORM_STATE_KEY] = node
    battle_state[_TRANSFORM_CLEARED_KEY] = "battle_end"
    return node


# =====================================================================================
# 状态判定辅助（恢复后上下文消费：S3 形态激活 / S5 冷却期）
# =====================================================================================


def is_form_active(state: Optional[Mapping[str, Any]]) -> bool:
    """S3 形态激活判定：form 非空（§3.1 S3 形态激活为常态用户态）。

    入参为 transform_state 段（None/畸形 → False，确定性兜底）。
    """
    return normalize_transform_state(state)["form"] is not None


def is_cooldown_active(state: Optional[Mapping[str, Any]]) -> bool:
    """S5 冷却期判定：cooldown_remaining > 0（§3.1 S5 冷却期常态）。

    常态 S1 无冷却（cooldown=0）；S3 形态激活期冷却 0（T5）。None/畸形 → False。
    """
    return normalize_transform_state(state)["cooldown_remaining"] > 0


# =====================================================================================
# TransformSnapshotEngine（引擎注入模式：构造器注入，缺省 = 纯函数默认行为）
# =====================================================================================


class TransformSnapshotEngine:
    """F3 快照引擎（构造器注入模式，对齐 forge_job.py 模块级引擎持有者先例）。

    注入项（均可缺省，缺省 = 模块级纯函数默认行为，确定性保持）：
      job_id_provider:       Callable[[], str] —— 职业 ID 来源（start/_settle
                             建段时注入，T1 冗余键值）。
      status_state_provider: Callable[[], Optional[Mapping[str, Any]]] ——
                             status_state 读取器（T6 交叉校验数据源，F3-1）。
      audit:                 Callable[[str], None] —— 审计日志回调（F3 ⑤
                             双写不一致 / SN-3 降级观察口）。
    方法委托模块级纯函数（write/restore/clear），注入仅作数据来源/观察口，
    不引入可变全局状态。
    """

    def __init__(
        self,
        *,
        job_id_provider: Optional[Callable[[], str]] = None,
        status_state_provider: Optional[Callable[[], Optional[Mapping[str, Any]]]] = None,
        audit: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._job_id_provider = job_id_provider
        self._status_state_provider = status_state_provider
        self._audit = audit

    def _job_id(self) -> str:
        if self._job_id_provider is not None:
            v = self._job_id_provider()
            return v if isinstance(v, str) else ""
        return ""

    def write(self, state: Any = None) -> Dict[str, Any]:
        """F3 写入（引擎版）：state 缺省 None 时产出带注入 job_id 的常态骨架。"""
        if state is None:
            return empty_transform_state(self._job_id())
        return snapshot_write(state)

    def restore(self, snap: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        """F3 恢复（引擎版）：status_state 经注入读取器取数后委托 snapshot_restore。"""
        ss: Optional[Mapping[str, Any]] = None
        if self._status_state_provider is not None:
            v = self._status_state_provider()
            ss = v if isinstance(v, Mapping) else None
        return snapshot_restore(snap, status_state=ss, audit=self._audit)

    def clear(self) -> Dict[str, Any]:
        """SN-4 清零（引擎版）：常态骨架 + 注入 job_id。"""
        return clear_transform_state(self._job_id())


__all__ = [
    "TRANSFORM_STATE_KEY",
    "TRANSFORM_STATE_FIELDS",
    "TransformStateKind",
    "TransformSnapshotEngine",
    "attach_cleared_state",
    "attach_initial_state",
    "clear_transform_state",
    "empty_transform_state",
    "is_cooldown_active",
    "is_form_active",
    "normalize_transform_state",
    "snapshot_restore",
    "snapshot_write",
]
