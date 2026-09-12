"""战斗引擎（CTB 重写 · 行动条驱动 + 伤害闭环 + 快照 V2 续战）。

本模块是 QBot RPG 的**战斗主循环唯一权威实现**（battle_state 为本场战斗唯一
权威状态）。零 NoneBot import。**CTB（Charge Time Battle / 行动条制）**：不存在
「回合」这一时间单位——每个单位独立累计行动条，谁先满谁先动；一次行动的时间
代价由该 action 的 recovery 决定（公式见 core/ctb_rules.next_ready）。

依据（本模块 = Agent 3 重写，Wave A 产出为唯一事实源）：
  - docs/ctb/01_asset_inventory.md §1 三分类总表（107 方法：平移 79 / 重写 25 /
    删除 3）＋ §0.2 CTB 事件位点词典（10 事件）＋ §3 强制登记项 M1–M11 ＋
    §4 回合数语义标红 R1–R20 ＋ §2 外部影响面
  - docs/ctb/02_wave_a_decisions.md 三条权威裁决：
      裁决 1 · recovery = **总行动恢复值**（与 default_recovery 覆盖而非附加）
      裁决 2 · R-6 被拒行动 = **零时间成本、直接重试**（不派发链路事件、
               不消费票据时间、next_ready 保持原值、拒绝原因上报不静默吞）
      裁决 3 · tie-break 同刻连动 = 刻意设计（非缺陷）
  - qbot_rpg/core/ctb_rules.py（纯规则层：CtbEvent 10 事件 / next_ready 公式 /
    recovery_for / CtbRuleConfig / ActionBatchReport）——本模块只消费，不修改
  - qbot_rpg/core/ctb_scheduler.py（有状态调度器：逻辑时间唯一推进源；本模块
    持有实例并把「行动条推进」委托给它）——本模块只消费，不修改
  - docstring 中的事件位点（10 种，与 CtbEvent 常量一一对应）：
      BATTLE_START      进战建行动条（start）
      ACTOR_READY       某单位行动条到阈值（调度器判，引擎侧消费）
      ACTOR_TURN_START  该单位行动开始（回合开始 DOT/控制递减/即死 → 按持有者）
      BEFORE_ACTION     行动前（方位复位/季节校验/控制裁决）
      ACTION_RESOLVE    行动结算（伤害闭环/效果通道）
      AFTER_ACTION      行动后（状态衰减/AI 冷却/技能冷却/形态 tick）
      ACTOR_TURN_END    本次行动收尾（air_policy 落地/霸体清位）
      BATTLE_TIME_ADVANCE  全局逻辑时间推进（换季边界位点）
      ACTOR_DEATH       单位死亡（死亡判定两触发点之一）
      BATTLE_END        战斗终局（统一收尾/连段清零）

事件位点映射规则（Wave A §0.2，重写时的连线依据）：
  - 回合开始 DOT  → 目标自身 ACTOR_TURN_START
  - 回合结束 DOT  → 行动者 ACTOR_TURN_END / AFTER_ACTION
  - N 回合状态衰减 → N 次该状态持有者行动
  - AI 行动冷却    → N 次该 AI 自身行动
  - 全局战斗时间效果 → BATTLE_TIME_ADVANCE
  - 单次 after_action → 当前 action 的 AFTER_ACTION

【工程补白】（CTB 重写后的收敛口径，显式标注供审查）：
  1. 工作快照形态：effects.damage_pipeline / tick_turn_end 要求 combatant 位于
     顶层键 player/enemy（ctx.snapshot[side] 直达）——引擎工作快照以顶层
     player/enemy 承载 combatant，battle_time/action_seq/result/action_record
     等元字段以兄弟键承载，不嵌套 sides（与 effects 输入契约对齐）。
  2. **行动条与本模块的分工**：本模块持有 `_ctb`（CTBScheduler），调度器是
     逻辑时间的唯一推进源；本模块负责「行动内容」（打谁/打多少/死没死），
     调度器负责「谁什么时候动」。**本模块不得自建任何计时器**——时间只能由
     调度器的逻辑时间轴推进（m3 铁律 1）。
  3. **recovery 注入点**：每次行动结算后经 `_action_recovery(attacker, action)`
     解析该 action 的 recovery（action 显式 recovery 键 → 内容包定义 → 默认），
     再交给调度器算下次 ready。这是 CTB「行动代价」的唯一注入点。
  4. **R-6 被拒行动**（裁决 2）：四类门禁（energy_cost / consume_marks /
     combo_table / season）任一出被拒 outcome → **不调用 `_after_actor_action`**
     （不推进行动条、不派发 ACTOR_TURN_START 链路、next_ready 保持原值）；玩家
     侧由 `player_act` 直接返回，调度器暂停态不解除，可立即换指令重试。
     **被拒=该行动从未发生，时间轴不付出代价**。
  5. **行动条替代回合计数**：`_snap["battle_time"]`（逻辑时间，浮点）与
     `_snap["action_seq"]`（已结算行动计数，整数）双计数承载全部旧「回合数」
     语义（R1–R20 映射目标）；`action_record[*].action_seq` / `.battle_time`
     替代旧 `turn` 字段。快照兼容键 `turn` 保留为镜像（= action_seq），供
     世界层快照完整性校验（R-A）与旧读方过渡，**不参与任何数值计算**。
  6. 防御指令（×0.5）的持续窗口 = 「到该 actor 下次行动为止」（D2 霸体窗口
     同口径）——由 `_guard_actor` 置位、`_start_actor_turn` 清位，替代旧的
     「行动结束清零」。
  7. 快照 V2：`schema_version=2`、`rule_version="battle_ctb_v1"`，边界枚举为
     CTB 边界（`actor_ready`/`after_action`），旧 v1 快照被 `from_snapshot`
     显式拒绝（不静默降级——v1 的回合语义与 CTB 时间轴不可换算）。
"""

from __future__ import annotations

import copy
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from qbot_rpg.core.damage import (
    DamageFormulaParams,
    apply_derived_cap,
    block_rate,
    channel_elem,
    channel_phys,
    crit_roll,
    crit_prob,
    defense_factor,
    effective_con,
    elem_factor,
    hit_rate,
    pierce_pct,
    total_damage,
)
from qbot_rpg.core.effects import (
    ActionResult,
    BATTLE_SIDES,
    DamageCtx,
    DamagePipeline,
    EffectRuntime,
    PipelineResult,
    execute_action,
    tick_after_action,
    tick_turn_end,
)
from qbot_rpg.core.marks import MarksManager
from qbot_rpg.core.combo import (
    ComboActionResult,
    ComboEngine,
    InterruptResult,
)
# M2-C1：怪物连招打断=套完结（monster_chains.on_chain_broken，contract §六 / 细化_1f ⑤5.4）
from qbot_rpg.core.monster_chains import on_chain_broken
# CTB 重写（Wave A 冻结产物）：纯规则层 + 有状态调度器。本模块**只消费不修改**——
# 规则/时序的任何变更都归 ctb_rules.py / ctb_scheduler.py（Wave A 冻结口径）。
from qbot_rpg.core.ctb_rules import (
    CtbEvent,
    CtbRuleConfig,
    DEFAULT_RECOVERY,
    EVENT_ORDER,
    recovery_for,
    resolve_rule_config,
)
from qbot_rpg.core.ctb_scheduler import CTBScheduler

#: 模块日志器（NPC 行动执行等兜底路径留痕；不可达路径不静默吞错）
_logger = logging.getLogger("qbot_rpg.core.battle")

__all__ = [
    "BattleEngine",
    "BattleActor",
    "BattleStateError",
    "ActionOutcome",
    "TurnReport",
    "BattleOutcome",
    "STATE_PREP",
    "STATE_ACT",
    "STATE_RES",
    "STATE_DTH",
    "STATE_WIN",
    "STATE_LOSE",
    "STATE_FLY",
    "STATE_SNP",
    # CTB 重写（Agent 3）：行动报告 / 快照 V2 边界 / 规则版本
    "ActionReport",
    "SNAPSHOT_SCHEMA_VERSION",
    "CTB_RULE_VERSION",
    "CTB_BOUNDARY_ACTOR_READY",
    "CTB_BOUNDARY_AFTER_ACTION",
]

# ---------------------------------------------------------------------------
# 状态机常量（细化_1g1a §9 汇总表 8 态 / 1g1b §一）
# ---------------------------------------------------------------------------

STATE_PREP = "prep"   # S0 战前准备
STATE_ACT = "act"     # S1 行动选择
STATE_RES = "res"     # S2 结算中
STATE_DTH = "dth"     # S3 死亡判定
STATE_WIN = "win"     # S4 胜利
STATE_LOSE = "lose"   # S5 失败
STATE_FLY = "fly"     # S6 逃跑
STATE_SNP = "snp"     # S7 快照中断

# 行动相位（CTB 重写：旧「回合相位」→「当前行动者所处的事件位点」）
# 词表与 CtbEvent 常量同源（禁止散落字面量）；仅作为 battle_state 的可读标注，
# 不参与任何时序判定——时序判定一律走调度器（_ctb）。
PHASE_TURN_START = "turn_start"       # 该 actor 行动开始（ACTOR_TURN_START）
PHASE_PLAYER_ACTION = "player_action"  # 玩家侧行动结算中
PHASE_ENEMY_ACTION = "enemy_action"    # 敌方侧行动结算中
PHASE_TURN_END_TICK = "turn_end_tick"  # 该 actor 行动收尾（ACTOR_TURN_END）
# CTB 的「等待输入」位点：行动条已就绪、等待玩家指令（等价 ACTOR_READY，
# 2026-09-10 CTB 重写新增；替代回合制的「轮到我方行动」语义）。
PHASE_ACTOR_READY = "actor_ready"
# CTB 新增：战斗时间推进（BATTLE_TIME_ADVANCE / 换季边界位点）
PHASE_TIME_ADVANCE = "time_advance"

# 战斗生命周期 status / result.flag（细化_1g1c §1.3）
STATUS_ACTIVE = "active"
STATUS_WIN = "win"
STATUS_LOSE = "lose"
STATUS_ESCAPE = "escape"
STATUS_DRAW = "draw"

# CTB 快照 V2 契约常量（Agent 3 · 阶段 3）
#   - schema_version 从 1 升到 2：v1 是「回合边界」快照，其 turn 语义与 CTB 逻辑
#     时间轴不可换算 → from_snapshot 显式拒绝 v1（不静默降级）。
#   - boundary 枚举从 {turn_start, turn_end} 换为 CTB 边界 {actor_ready,
#     after_action}（Agent 3 依 §6 S8 定义）——`turn_start`/`turn_end` 不再是
#     合法值，契约测试 test_ctb_snapshot_boundary_is_ctb_boundary 据此断言。
SNAPSHOT_SCHEMA_VERSION = 2
CTB_RULE_VERSION = "battle_ctb_v1"
CTB_BOUNDARY_ACTOR_READY = "actor_ready"
CTB_BOUNDARY_AFTER_ACTION = "after_action"
CTB_BOUNDARIES: Tuple[str, ...] = (CTB_BOUNDARY_ACTOR_READY, CTB_BOUNDARY_AFTER_ACTION)
# v1 遗留边界名（仅用于拒绝路径报错文案，不得写入新快照）
_LEGACY_BOUNDARIES: Tuple[str, ...] = ("turn_start", "turn_end")

# 单次 `_resolve_ready_actor` 的最大推进次数（防「NPC 无限连动 + 玩家永不 ready」
# 的理论死循环；CTB 下正常战斗远小于该值，触顶说明规则参数异常，届时任务标红）。
_CTB_MAX_ADVANCE_PER_CALL = 512

# 合法迁移集（CTB 重写：状态机本体保留 8 态；合法边按 CTB 行动链重排）
#   T1 PREP→ACT（进战建条完成 / 快照还原回行动选择）
#   T2 ACT→RES（该 actor 提交行动 → 结算中）
#   T3 RES→DTH（每段扣血后死亡判定）  RES→ACT（本次行动收尾，交还行动条）
#   T4 DTH→LOSE（玩家死）  T5 DTH→WIN（怪物死）
#   T6 ACT→FLY（逃跑；CTB 下任意该 actor ready 时点，无回合边界约束）
#   T7 PREP→SNP / ACT→SNP（快照中断落点）
#   P0-01 通道：ACT→DTH（该 actor 行动开始 DOT/即死 直出终局）
_LEGAL_EDGES: frozenset = frozenset(
    {
        (STATE_PREP, STATE_ACT),     # T1
        (STATE_PREP, STATE_SNP),     # T7 中断落点
        (STATE_ACT, STATE_RES),      # T2
        (STATE_ACT, STATE_FLY),      # T6 逃跑
        (STATE_ACT, STATE_SNP),      # T7 边界中断
        (STATE_ACT, STATE_DTH),      # P0-01 行动开始 dot/即死通道
        (STATE_RES, STATE_DTH),      # T3 每段扣血后
        (STATE_RES, STATE_ACT),      # T3 本次行动收尾（交还行动条）
        (STATE_DTH, STATE_RES),      # T3 未死回结算 / 套内续段 A4
        (STATE_DTH, STATE_WIN),      # T5 / A5 BOSS 即时结束
        (STATE_DTH, STATE_LOSE),     # T4 / A1 即死直出
        (STATE_SNP, STATE_PREP),     # T7 还原
    }
)

# 引擎级默认配置（death_check 四项 + CTB 规则参数）
_BATTLE_DEFAULT_CONFIG: Dict[str, Any] = {
    # death_check 四项可配（1g1b §四 不变量1）
    "mutual_kill_basis": "order",        # 互杀判定基准 order/hp_ratio（L237）
    "mutual_kill_result": "draw",        # 互杀终态 draw/player_loss（L236）
    "no_target_action": "fallback",      # 无目标兜底 fallback/skip（L238）
    "boss_end_immediate": True,          # BOSS/最后目标死→立刻结束（L239）
    # 逃跑（1g1a §7 定稿待补，工程补白：默认 100% 成功）
    "flee_chance": 1.0,
    "battle_flee_blocked_on_boss": False,
    # CTB 行动条规则参数（透传给 CTBScheduler 的 CtbRuleConfig）
    #   recovery / speed_reference / min_speed / action_delay —— 见 ctb_rules.py
    "ctb": {},
    # 旧键保留（actor_order 在 CTB 下无意义——行动顺序由行动条动态决定；
    # 保留仅为旧配置不报错，读取侧不消费）
    "actor_order": "fixed",
    "rule_version": CTB_RULE_VERSION,
    # 部位破位倒地状态 id（方位 v0.6 §五：knockdown 走既有 status 体系）
    "knockdown_status_id": "knockdown",
    # 被击落倒地状态 id（跃空风险闭环，批③：action.air_drop=knockdown 命中空中玩家，
    # 走既有 status 体系；可配）
    "air_drop_status_id": "knockdown",
    # 被击落倒地窗口（实例 turns 覆写值；系统每个行动收尾双端各扣 1，缺省 3 =
    # 覆盖「玩家下一拍 + 怪下一次出手」的追击窗；可配）
    "air_drop_turns": 3,
    # 背击加成（B5 背击闭环，2026-09-11 批④；怪猎闇討ち映射）：玩家攻击结算时
    # 位于怪**背面**（combat_position.player.side == "back"）→ 物理通道伤害 ×
    # (1 + backstab_bonus)。缺省 +10%（0=关、可配）；元素不吃（闇討ち「属性伤害
    # 不计」口径——乘区挂在物理侧 skill_mult 上）。内容侧可经 settings["battle"]
    # 段覆盖（battle_config.resolve_battle_settings）。
    "backstab_bonus": 0.10,
    # 条件型会心「逆境」阈值（怪猎采纳 E20，2026-09-12 批⑤）：攻击方 HP ≤ 本比例
    # 时触发 combatant.crit_bonus_cond 的 low_hp 加成项（缺省 0.3=30%）；可经
    # settings["battle"] 段覆盖（battle_config.resolve_battle_settings）。
    "crit_cond_low_hp": 0.3,
}

# combatant 缺失字段兜底（细化_1g1c §1.2 双方单位 + 1a 公式所需属性）
_DEFAULT_STATS: Dict[str, Any] = {
    "max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100,
    "atk": 50, "dfn": 50, "mag": 30, "spd": 50,
    "foc": 50, "con": 50, "str": 50, "int": 50, "agi": 50, "spr": 50, "lck": 50,
    "elem_atk": 0, "elem_res": 0, "name": "",
}

# 五块效果快照键（细化_1b §1.4 / 定稿 §8.3）
_FIVE_BLOCKS: Tuple[str, ...] = (
    "status_state",
    "marks_state",
    "resist_table",
    "effect_triggers",
    "effect_cooldowns",
)

#: 空中姿态状态 ID 全集（跃空窗口载体；窗口初始化/到期判定/落地清理共用——增补 v1 §四）。
#: 2026-09-11 关联状态同步审计：补齐 rb/vc/po 系跃空姿态（此前三技缺挂载 → 跃起即被
#: R16 兜底静默落地）。内容侧新增任何「跃空保持」状态须同步登记本表。
_AIR_STATUS_IDS: Tuple[str, ...] = (
    "sw_vault_air", "vs_air_window", "va_air_window",
    "rb_vault_air", "vc_vault_air", "po_vault_air",
)


class BattleStateError(Exception):
    """非法状态迁移 / 非法操作（细化_1g1b §二 状态机不变量，不变量2/4）。"""


# ---------------------------------------------------------------------------
# 结果 dataclass（frozen，展示层/测试消费）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BattleActor:
    """战斗侧标识（player/enemy 双侧，细化_1g1a 战斗状态集）。"""

    side: str
    name: str


@dataclass(frozen=True)
class ActionOutcome:
    """单次行动结算结果（细化_1g1c action_record 语义 + 判定管线逐环 rating）。"""

    ok: bool
    seq: int
    actor: str
    action_type: str
    target: str
    hit: bool
    crit: str
    blocked: bool
    raw_damage: int
    final_damage: int
    target_hp: int
    side_effects: Tuple[Mapping[str, Any], ...]
    message: str = ""
    battle_ended: bool = False
    status: Optional[str] = None
    # M13 批15 路15C：组合技能战斗接线——combo_table 触发/结算审计（F-C1/F-C2）。
    # 语义：None=常规技能/普攻（未走组合判定）；dict=技能施放时组合判定结果
    # （{matched, name, kind, power, hits, mp_cost, energy_cost, events}）——
    # 命中组合行 → row 字段随行（行为随组合变化）；未命中 → matched=[] 且
    # reason∈{no_combo_match, energy_total_insufficient}（回退常规路径，能量
    # gain/cost 照常）。战报/展示层可据此渲染「烈焰爆破！」组合名。
    combo_result: Optional[Dict[str, Any]] = None
    # 背击附注（B5 背击闭环，2026-09-11 批④）：本次行动为「位于怪背面」结算
    # （吃了 backstab_bonus）→ 命中行尾拼「（背击）」；False = 常规（零副作用）。
    backstab: bool = False
    # 批⑥ 会心倍率动态化（方案B）：本次会心实际生效倍率（含超会心加成/负会心配置）；
    # 渲染直读「（会心·高阶 ×2.25）」；None=非会心或旧构造点 → 渲染回退静态档位表。
    crit_mult: Optional[float] = None


@dataclass(frozen=True)
class TurnReport:
    """一次行动/推进报告（CTB 重写：旧「一轮」报告容器保留，字段语义改变）。

    公开接口 `player_act()` / `action_report()` 的返回类型（签名零改动）。
    字段：
      `turn`      = action_seq 镜像（**审计/兼容用，不参与计算**）
      `action_seq`= 本次推进后的已结算行动计数（CTB 权威进度计量）
      `battle_time` = 本次推进后的逻辑战斗时间（CTB 权威时间计量）
      `ended`/`status` = 终局判定；`log` = 流水行；`outcomes` = ActionOutcome 序列

    **`phases` 已移除**（CTB R18/M7）：回合相位是回合制遗物，CTB 下进度语义由
    `action_seq` + `battle_time` 双计数承载。旧读方若访问 `report.phases`，
    经下方只读属性回落到当前事件位点（不破坏，但不再是 dataclass 字段）。
    """

    turn: int
    player: int
    enemy: int
    ended: bool
    status: Optional[str]            # None=进行中
    log: Tuple[Mapping[str, Any], ...] = ()
    outcomes: Tuple[ActionOutcome, ...] = ()
    # 方位 v0.6 HUD：双方当前方位格（side/height 原值；缺省 None——旧调用方零变化）
    player_pos: Optional[Tuple[str, str]] = None
    enemy_pos: Optional[Tuple[str, str]] = None
    # CTB 双计数（2026-09-10 补齐）：契约要求行动报告携带 action_seq（进度权威），
    # 供展示层/续战校验使用。默认值保证旧构造点零破坏。
    action_seq: int = 0
    battle_time: float = 0.0
    # 事件位点（非 dataclass 字段，保持字段集纯净；供旧读方过渡读取）
    _phase_label: Tuple[str, ...] = ()

    @property
    def phases(self) -> Tuple[str, ...]:
        """CTB 兼容属性：当前事件位点（替代旧回合相位）。

        非 dataclass 字段（契约要求字段集不含 `phases`），仅供尚未迁移的旧读方
        过渡访问；新读方请用 `action_seq` / `battle_time`。
        """
        return tuple(self._phase_label)

    def fields(self) -> Tuple[str, ...]:
        """字段名元组（契约测试断言口径：'action_seq' in fields，'phases' not in）。"""
        return tuple(k for k in self.__dataclass_fields__ if not k.startswith("_"))


@dataclass(frozen=True)
class ActionReport:
    """CTB 行动报告（Agent 3 新增；`battle_state()` 与快照侧的只读投影）。

    契约要求（tests/ctb/test_ctb_contract_interfaces.py
    `test_ctb_player_act_report_has_action_seq_not_phases`）：**含 `action_seq`、
    不含 `phases`**——`phases` 是回合相位遗物，CTB 下以 `action_seq` + `battle_time`
    双计数承载进度语义。`fields()` 供契约测试做字段名集合断言。
    """

    action_seq: int
    battle_time: float
    actor: Optional[str]
    events: Tuple[str, ...] = ()
    nested: Optional[Mapping[str, Any]] = None

    def fields(self) -> Tuple[str, ...]:
        """字段名元组（契约测试的断言口径：'action_seq' in fields and 'phases' not in fields）。"""
        return ("action_seq", "battle_time", "actor", "events")


@dataclass(frozen=True)
class BattleOutcome:
    """战斗终局（细化_1g1c §1.3 结果标记 + 收尾）。result 含可配终态。

    CTB：`turn` 为 action_seq 镜像（审计字段，不参与计算）。
    """

    status: str                        # win/lose/escape/draw
    reason: str                        # 触发来源（标记名）
    turn: int
    resolve_at: str                    # "after_action" / "immediate"
    combo_zeroed_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------


def _make_battle_resolver(
    registry: Any = None, defs: Optional[Mapping[str, Any]] = None
) -> Callable[[str, str], Any]:
    """归一化配置源为 callable(id, kind) -> Def|dict|None（对齐 effects._make_resolver）。

    2026-09-07 修复：defs 优先于 registry——launch 侧 defs 由 modules_raw 全量
    扁平构建（skills/actions/chains/effects/jobs 全含），registry.resolve 走 Def
    包装层对 veinborn 扁平条目（effect 引用式等）查不到 → 效果静默安全失败
    （edge_clear3 清蓄刃不生效实测暴露）。registry callable 形态保留原样。
    """
    if callable(registry):
        return registry
    if defs is not None:
        return lambda id_, _kind: defs.get(id_)
    if registry is not None:
        resolve = getattr(registry, "resolve", None)
        if callable(resolve):
            return lambda id_, kind: resolve(id_, kind)
    return lambda _id_, _kind: None


class BattleEngine:
    """CTB 战斗引擎（行动条驱动 · 完整伤害闭环）。

    主循环不再有「先手→后手→tick」的固定行动序；一次行动的生命周期为
    `ACTOR_READY → ACTOR_TURN_START → BEFORE_ACTION → ACTION_RESOLVE →
    AFTER_ACTION → ACTOR_TURN_END`，全部由 `CTBScheduler` 的行动条推进决定。
    BOSS/最后目标死亡立即结束；快照只落 CTB 边界（actor_ready / after_action）。
    """

    def __init__(
        self,
        pipeline: Optional[DamagePipeline] = None,
        runtime: Optional[EffectRuntime] = None,
        params: Optional[DamageFormulaParams] = None,
        registry: Any = None,
        defs: Optional[Mapping[str, Any]] = None,
        config: Optional[Mapping[str, Any]] = None,
        combo_engine: Optional[ComboEngine] = None,
        enemy_ai: Any = None,
        enemy_def: Optional[Mapping[str, Any]] = None,
        ai_action_lib: Any = None,
        ai_rng: Any = None,
    ) -> None:
        """构造引擎。

        pipeline/runtime：效果/配置源注入（默认自建）；params：伤害公式参数载
        体（damage.DamageFormulaParams，细化_1a §2.1）；registry/defs：内容包
        配置源（effects/statuses 解析，F-21/F-23 用）；config：引擎配置
        （death_check 四项等，1g1b §三）；combo_engine：连段引擎（细化_1c；
        默认自建，与 registry/defs 同源解析技能/链配置）。

        M2-C1（contract §六）：enemy_ai=怪物 AI 决策引擎实例（MonsterAI，只读注入；
        None=保留 M1 默认普攻反击）。显式 enemy_ai 优先；enemy_def 给出时自动构造
        （action_lib 缺省用 defs 映射；ai_rng 缺省自建——确定性测试请显式注入
        enemy_ai 或 ai_rng，铁律 6）。enemy_def/ai_action_lib/ai_rng 亦经
        from_snapshot 透传（快照续玩不丢 AI 引擎）。

        兼容旧签名：BattleEngine() / BattleEngine(pipeline, runtime) 原样可用。
        """
        self._pipeline: DamagePipeline = (
            pipeline if pipeline is not None else DamagePipeline(registry=registry, defs=defs)
        )
        # M12.5 需求1 批C：formula.json 生产侧装配链——显式 params 优先；否则
        # 从 registry.modules_raw["formula"] 装配段参数（含 stat_map），无 registry /
        # 无 formula 模块 → DamageFormulaParams() 默认（缺省零破坏）。共享加载函数
        # 生产侧落点 = core/formula_loader（原 conftest 读取器同源提权）。
        _loaded_params = self._formula_params_from_registry(registry) if params is None else params
        self._params: DamageFormulaParams = _loaded_params or DamageFormulaParams()
        # FIX-6 决策登记（细化_M6 测试体系强化 D6 §三 FIX-5/FIX-6 二选一 + §八）：
        # M12.5 需求1 批C 已落地：battle 从内容包 formula.json 装配段参数（JSON 段 →
        # DamageFormulaParams 共享加载函数生产侧 = core/formula_loader，conftest
        # 读取器同源提权；registry.modules_raw["formula"] 装配，含 stat_map 段）。
        # 内容包 formula.json 段参数现由引擎实消费；无 formula 模块/无 registry →
        # 全默认（零破坏）。文档口径由 D6 §八 + m125 记录承接。
        self._config: Dict[str, Any] = dict(_BATTLE_DEFAULT_CONFIG)
        if config:
            self._config.update(config)
        # 外部 runtime 仅作默认解析/配置参考；引擎体内五块始终以快照为准
        self._runtime_base: Optional[EffectRuntime] = runtime
        self._registry: Any = registry
        self._defs: Optional[Mapping[str, Any]] = defs
        self._resolver: Callable[[str, str], Any] = _make_battle_resolver(registry, defs)
        self._combo: ComboEngine = combo_engine or ComboEngine(
            defs=defs, registry=registry,
            config={"enforce_mp": bool(self._config.get("combo_enforce_mp", False))},
        )
        # M2-C1：怪物 AI 注入（enemy_ai 显式优先；enemy_def 自动构造）
        # M12.5 木桩：enemy_def 原样保留（_is_dummy_enemy_def 判定源；from_snapshot
        # 续战走快照 is_dummy_battle 标记，不依赖本属性）
        self._enemy_def: Optional[Mapping[str, Any]] = enemy_def
        self._enemy_ai: Any = None
        # M13 6c（细化_6c §1.4 RS-3/RS-5）：资源轴注册表注入位——装配层传入
        # stats.json 资源轴注册段（stats["resource_axes"] 形态）供战斗结束 reset
        # 策略 / 快照恢复按注册表逐轴口径执行；None → 零操作降级（RS-5 精神）。
        self._resource_registry: Any = None
        if enemy_ai is not None:
            self._enemy_ai = enemy_ai
        elif enemy_def is not None:
            from qbot_rpg.core.monster_ai import MonsterAI

            lib = ai_action_lib if ai_action_lib is not None else (
                defs if isinstance(defs, Mapping) else None
            )
            self._enemy_ai = MonsterAI(
                enemy_def, lib, ai_rng if ai_rng is not None else random.Random()
            )
        self._reset_state()

    def _formula_params_from_registry(self, registry: Any = None) -> Optional[DamageFormulaParams]:
        """registry.modules_raw["formula"] → DamageFormulaParams（M12.5 需求1 批C）。

        无 registry / 无 formula 模块 / 装配异常 → None（调用方回落默认，零破坏）。
        共享加载函数生产侧落点 = core/formula_loader（原 conftest 读取器同源）。

        注意：只在 __init__ 早期被调用（self._registry 尚未赋值），故只读入参
        registry，不读 self._registry（from_snapshot 重建时显式传 registry）。
        """
        raw = getattr(registry, "modules_raw", None)
        if not isinstance(raw, Mapping):
            return None
        formula = raw.get("formula")
        if not isinstance(formula, Mapping):
            return None
        try:
            from qbot_rpg.core.formula_loader import load_formula_params

            return load_formula_params(formula)
        except Exception:  # noqa: BLE001 —— 装配异常回落默认，不阻断开战
            return None

    # ------------------------- 内部状态字段 -------------------------

    def _reset_state(self) -> None:
        self._state: str = STATE_PREP
        self._phase: str = PHASE_ACTOR_READY
        self._snap: Dict[str, Any] = {}
        self._rng: random.Random = random.Random()
        self._rng_seed: Optional[int] = None
        self._seq: int = 0
        self._finished: bool = False
        self._guard_active: Dict[str, bool] = {"player": False, "enemy": False}
        # 防反/闪反姿态窗口：时间口径（增补 v1 §一，2026-09-11）——窗口数据存于
        # snap.counter_stance（cast_time + action_time），到期自然结束（见
        # `_expire_counter_stance` / `_player_stance`）；原 R10 计数口径已退役。
        self._effect_ids: Dict[str, List[str]] = {"player": [], "enemy": []}
        # CTB 行动条：持有调度器实例（逻辑时间唯一推进源）。
        # **未登记单位** → start() 时 push_actor 双侧；battle_state 查询不依赖它。
        self._ctb: Optional[CTBScheduler] = None
        # 当前 ready 的 player 是否已消费（_player_consumed_ready）。
        # CTB 语义：调度器在玩家 ready 时暂停；引擎在玩家提交行动后调
        # complete_player_action 解除暂停。本标记用于 player_act 的幂等读写。
        self._player_ready_pending: bool = False
        # M13 批15 路15A：transform 还原冷却延迟缓存（D-05：dispel 还原延迟到
        # 持有者下一次行动收尾——CTB 下 = 该 actor 的下一次 AFTER_ACTION）
        self._transform_dispel_pending: Dict[str, bool] = {"player": False, "enemy": False}
        self._transform_revert_pending: Dict[str, bool] = {"player": False, "enemy": False}
        # 霸体瞬态（1c2 §2.2：行动开始 → 本次结算完成；打断判定依据）
        self._armor_active: Dict[str, bool] = {"player": False, "enemy": False}
        self._death_order: List[str] = []   # 死亡登记顺序（互杀审计，1g1b A2）
        self._current_actor: Optional[str] = None      # 当前行动者（先手击杀判定，TC-11）
        self._qualified_kill_origin: bool = False      # 敌人死因=玩家行动直击（order 基准）
        # CTB：最近提交的 action dict（recovery 解析源；do_action 写入）
        self._last_action_dict: Optional[Mapping[str, Any]] = None
        # M13 批15 路15A：transform 装配注入位（set_transform_def）与事件审计
        self._transform_def: Dict[str, Any] = {}
        self._transform_events: List[Mapping[str, Any]] = []
        self._job_id: str = ""
        # 调度器事件缓冲游标（消费调度器 drain_events 后按序落 log）
        self._ctb_event_log: List[Mapping[str, Any]] = []
        # NPC 自动行动 outcome 暂存（Render 通道）：调度器在 `player_act` 内自动
        # 结算 NPC ready 拍时，把其 ActionOutcome 暂存于此，供 `player_act` 汇总进
        # TurnReport.outcomes（渲染层据此产出「怪物行动行」）。
        self._npc_outcomes: List[ActionOutcome] = []
        # 跃空窗口（增补 v1 §四）：引擎级待发事件（自动落地等）——并入下一次行动
        # outcome 的 side_effects（渲染层出「落回地面」行）；取走即清（防重复播报）。
        self._pending_air_events: List[Mapping[str, Any]] = []
        # 空中延长幂等标记（同一行动多次收尾调用只延长一次）
        self._air_ext_marker: Optional[str] = None

    # ------------------------- 状态机制 -------------------------

    @property
    def state(self) -> str:
        """当前状态（8 态状态机；CTB 下仍承载「战前/行动选择/结算中/终局」语义）。"""
        return self._state

    @property
    def phase(self) -> str:
        """当前事件位点标注（CTB：当前行动者所处的事件位点，非回合相位）。

        保留属性名以零破坏旧读方；**不参与时序判定**——时序由 `_ctb` 调度器决定。
        """
        return self._phase

    @property
    def finished(self) -> bool:
        """战斗是否已终局（win/lose/escape/draw 任意出口，1g1c §1.3）。"""
        return self._finished

    @property
    def battle_time(self) -> float:
        """当前逻辑战斗时间（CTB 行动条时间轴；无真实时钟）。

        Agent 3 新增只读查询（不改变六大稳定接口）：调度器逻辑时间 = BATTLE_TIME_ADVANCE
        累积；战斗未开始（无调度器）→ 0.0。
        """
        return float(self._ctb.battle_time) if self._ctb is not None else 0.0

    @property
    def action_seq(self) -> int:
        """已结算行动计数（CTB 下替代旧「回合数」的进度计数源）。"""
        if self._ctb is not None:
            return int(self._ctb.action_seq)
        return int(self._snap.get("action_seq", 0) or 0)

    @property
    def ctb_scheduler(self) -> Optional[CTBScheduler]:
        """行动条调度器只读视图（测试/审计可用；外部不得直接推进它）。"""
        return self._ctb

    def _to_state(self, target: str, event: str) -> None:
        """状态迁移（CTB 重写：8 态本体保留，合法边按行动链重排 `_LEGAL_EDGES`）。

        非法迁移（如直接 ACT→WIN、结算中重入）在此拦截；终局态不可再迁出。
        """
        if self._state in (STATE_WIN, STATE_LOSE, STATE_FLY):
            if target in (STATE_WIN, STATE_LOSE, STATE_FLY) and self._state == target:
                return
            raise BattleStateError(f"战斗已终局（{self._state}），不允许迁移到 {target}")
        if (self._state, target) not in _LEGAL_EDGES:
            raise BattleStateError(
                f"非法状态迁移 {self._state}→{target}（事件 {event!r}，CTB 迁移表未登记）"
            )
        self._state = target

    # ------------------------- 快照/运行时装配 -------------------------

    def _new_runtime(self) -> EffectRuntime:
        """从当前快照五块构建 EffectRuntime（五块以快照为权威；1g1b §一状态变量）。"""
        return EffectRuntime(
            status_state=self._snap.get("status_state"),
            marks_state=self._snap.get("marks_state"),
            resist_table=self._snap.get("resist_table"),
            effect_triggers=self._snap.get("effect_triggers"),
            effect_cooldowns=self._snap.get("effect_cooldowns"),
            resolver=self._resolver,
            config=None,
        )

    def _absorb_runtime(self, rt: EffectRuntime) -> None:
        """把 runtime 五块写回快照（runtime 内顶层重绑需回灌，1g1b §一/1g3 S3）。"""
        for key in _FIVE_BLOCKS:
            self._snap[key] = getattr(rt, key)

    def _player_stance(self) -> Optional[Tuple[str, str]]:
        """防反/闪反姿态检测（标签制；**行动时间窗口**口径——增补 v1 §一，2026-09-11）。

        窗口 = [写入时刻, 写入时刻 + 行动时间)（行动条；半开区间）：

          - 写入时刻 `cast_time` = 姿态技能结算时的 `battle_time`（写侧见
            `_resolve_combo_action`，与 R11 结构成对）；
          - 时长 `action_time` = 技能 def 的 `action_time`（缺省 →
            规则 `default_action_time`，默认 400）；
          - 消费时以**当前 `battle_time`**（= 敌方该次行动的结算时刻）落入区间
            判定——窗口内出现符合标签条件的敌方行动 → 可触发。

        到期自然结束（无补偿）；**持有者提前再次行动不提前关闭窗口**（纯时间口径；
        原 R10「至持有者再次行动止」计数口径 `_stance_owner_seq` 已退役）。
        """
        try:
            _st = self._snap.get("counter_stance")
            if isinstance(_st, Mapping):
                _t = str(_st.get("type") or "")
                _c = str(_st.get("skill") or "")
                if _t in ("parry", "dodge") and _c:
                    _cast = _st.get("cast_time")
                    _dur = _st.get("action_time")
                    if _cast is None or _dur is None:
                        return None
                    _now = float(self.battle_time)
                    _t0 = float(_cast)
                    if _t0 <= _now < _t0 + float(_dur):
                        return (_t, _c)
            return None
        except Exception:
            return None

    def _expire_counter_stance(self) -> None:
        """姿态窗口到期清理：`now >= cast_time + action_time` → 移除（无补偿）。

        纯时间口径（增补 v1 §一）：到期即结束、与持有者是否再次行动无关；
        消费侧 `_player_stance` 做同口径判空（双保险——快照不留残存过期窗口）。
        """
        try:
            _st = self._snap.get("counter_stance")
            if not isinstance(_st, Mapping):
                return
            _cast = _st.get("cast_time")
            _dur = _st.get("action_time")
            if _cast is None or _dur is None:
                return
            if float(self.battle_time) >= float(_cast) + float(_dur):
                self._snap.pop("counter_stance", None)
        except Exception:  # pragma: no cover - 清理失败不阻断行动收尾
            return

    def _action_tags(self, action: Mapping[str, Any]) -> Tuple[bool, bool]:
        """怪行动可反标签（tags 含 可防反/可闪反——内容配置；ca 未合并时从 defs 解析）。"""
        _t = tuple(str(x) for x in (action.get("tags") or ()))
        if not _t:
            _sid = str(action.get("skill_id") or "")
            if _sid:
                _sd = self.combo_engine().resolve_skill(_sid) or {}
                _t = tuple(str(x) for x in (_sd.get("tags") or ()))
        return ("可防反" in _t, "可闪反" in _t)

    def _run_counter(self, skill_id: str) -> int:
        """执行反击技（防反/闪反成功派生——玩家对怪造成一次反击伤害，不占行动/无消耗）。
        返回反击伤害（0=未执行）。"""
        _sd = self.combo_engine().resolve_skill(skill_id)
        if not isinstance(_sd, Mapping):
            return 0
        try:
            _ca = dict(_sd)
            _ca["type"] = "skill"
            _ca["skill_id"] = skill_id
            _ca.pop("cooldown_remaining", None)
            out = self._resolve_damage_action("player", _ca)
            _dmg = int(getattr(out, "final_damage", 0) or 0) if out is not None else 0
            return _dmg
        except Exception:
            return 0

    def _refresh_defenses(self) -> None:
        """F-21（contract_deviations P1-2）：战斗路径真实调用 prepare_defense(side,
        effect_ids, status_instances) 把效果/状态配置归一化为 defense 行。

        依据：1g1b §2.2 拦截链接线、1g2 §2.1（输入=总伤害⑥）；effects 工程补白①
        说明防御行由战斗层 prepare_defense 归一化后落入 combatant.defenses。
        每次结算前刷新——新施加的护盾/减伤/反弹/吸收状态次击即可生效。
        """
        rt = self._new_runtime()
        for side in BATTLE_SIDES:
            c = self._snap.get(side)
            if not isinstance(c, dict):
                continue
            c["defenses"] = self._pipeline.prepare_defense(
                side,
                self._effect_ids.get(side, ()),
                rt.status_instances(side),
            )

    def marks_manager(self) -> MarksManager:
        """印记状态管理器访问器（细化_1d §2.1/§3）：绑定当前快照 marks_state
        （唯一权威双向表），施加/消除/条件求值/公式 [印记:X] 共用同一状态。

        对快照的写入即时生效（同一 dict 对象）；缺键时惰性补建 {player:[],enemy:[]}。
        """
        ms = self._snap.get("marks_state")
        if not isinstance(ms, dict):
            ms = {"player": [], "enemy": []}
            self._snap["marks_state"] = ms
        return MarksManager(ms, resolver=self._resolver)

    def combo_engine(self) -> ComboEngine:
        """连段引擎访问器（细化_1c）：绑定当前快照（以快照 combo_state 为权威）。
        用于技能/链配置解析、条件评估、派生/打断判定。"""
        return self._combo

    @property
    def armor_active(self) -> Dict[str, bool]:
        """霸体瞬态（读/写：测试与结算窗口控制，1c2 §2.2）。"""
        return self._armor_active

    def _combat(self, side: str) -> Dict[str, Any]:
        c = self._snap.get(side)
        return c if isinstance(c, dict) else {}

    def _opposite(self, side: str) -> str:
        return "enemy" if side == "player" else "player"

    def _alive(self, side: str) -> bool:
        c = self._combat(side)
        return bool(c) and not bool(c.get("dead_mark", False)) and int(c.get("hp", 0)) > 0

    def _dead(self, side: str) -> bool:
        return not self._alive(side)

    def _roll(self) -> float:
        """本场战斗随机数（固定种子可复现，1a 验收约定/4a TC-17）。"""
        return self._rng.random()

    # ------------------------- 变量/公式装配（F-组） -------------------------

    def _combat_map(self, side: str) -> Dict[str, Any]:
        """给公式求值器的 combatant 映射（额外补战斗期派生键，变量体系 §二②）。"""
        c = dict(self._combat(side))
        c.setdefault("shield", int((c.get("defenses") or {}).get("shield", {}).get("remaining", 0)))
        c.setdefault("mitigation", len((c.get("defenses") or {}).get("mitigation", [])))
        c.setdefault("pv", 0)
        c.setdefault("level", 0)
        c.setdefault("hit_streak", 0)
        c.setdefault("miss_streak", 0)
        # 印记→公式视图（细化_1d §3.1/§3.3 + 变量体系 §二⑤）：[印记:名]（_PARAM_RULES
        # 我方印记:/对方印记: → slot["marks"][名]）与 [印记总数]（marks_total）经
        # MarksManager 取同一 marks_state 双向表，不另存状态（1d §0.2 单一数据源）。
        c.update(self.marks_manager().formula_view(side))
        return c

    def _make_eval_formula(self, attacker: str = "player", target: str = "enemy") -> Callable[[str], float]:
        """公式引擎接线：注入 formula_engine.evaluate，携带战斗 rng_state 确定性，
        并组装 EvaluatorCtx（attacker/target/battle 变量映射，变量体系 §一/§二）。

        P1-02 修复（dsh 批2 P1-02）：原实现闭包固定 player/enemy，敌方技能/道具内
        含 [我方攻击]/[对方攻击] 的公式按错误侧解析。现在按当前行动者参数组装侧映射。

        依据：细化_1b F 组（F-1~F-5）+ contract_deviations P0-2；effects
        _resolve_value 优先取 ctx.variables['eval_formula']（P0-2 修复路径）。
        lazy import 防循环依赖（formula_engine → 不 import battle）。
        """
        from qbot_rpg.core.formula_engine import EvaluatorCtx, evaluate

        # R-C 映射（Wave A §4 R8）：内容包公式变量 `[战斗:round]` 原读回合数。
        # CTB 无「回合」→ 映射为 **action 计数**（`action_seq`）：与旧回合数同为
        # 「战斗推进了多少步」的单调整数，粒度从「整轮」细化为「单次行动」；
        # 公式作者按 `round` 写的阈值（如「第 3 回合强化」）在 CTB 下等价于
        # 「第 3 次行动强化」，语义方向一致、粒度更细。**不用 battle_time**：
        # 时间是浮点且受速度影响，会让同一公式在不同阵容下产出不同离散档位。
        _round_like = self.action_seq
        battle_map = {
            "round": _round_like,
            # 时间轴另键透出，供内容包需要连续时间语义时使用（新增，不影响旧公式）
            "battle_time": self.battle_time,
            "map_id": str(self._snap.get("battle_type", "")),
            "boss_phase": int((self._snap.get("ai_state") or {}).get("boss_phase", 1)),
            "kills": 0,
        }

        def _eval(expr: str) -> float:
            ectx = EvaluatorCtx(
                attacker=self._combat_map(attacker),
                target=self._combat_map(target),
                battle=battle_map,
                rng_state=self._rng_seed,
            )
            return evaluate(expr, ectx)

        return _eval

    def _base_variables(self, attacker: str, target: str) -> Dict[str, Any]:
        """DamageCtx.variables 装配（1b §2 接口 + 公式注入 + rng 确定性）。"""
        return {
            "rng": self._rng,
            "rng_state": self._rng_seed,
            "eval_formula": self._make_eval_formula(attacker, target),  # P1-02：随当前行动者切换侧映射
            "pipeline": self._pipeline,
            "is_reflect_damage": False,
            # M12.5 需求1 批B：stat_map 注入 effects 层（L0 动作 damage/aoe/pierce
            # 取数语义键；缺省 = 现值键名零破坏，内容包覆盖即换键）
            "stat_map": self._params.stat_map,
            "attacker": self._combat_map(attacker),
            "target": self._combat_map(target),
            # R-C 映射（Wave A §4 R9）：同 `_make_eval_formula`——`[战斗:round]`
            # 在 CTB 下 = action 计数（见该方法 docstring 的映射理由）。
            "battle": {"round": self.action_seq, "battle_time": self.battle_time},
            "damage_dealt": 0,
        }

    # ------------------------- F-23：S6/S7 上限接线 -------------------------

    def _status_raw(self, inst: Mapping[str, Any]) -> Dict[str, Any]:
        """状态实例 → 配置 raw（经内容源解析；未注册返回空 dict）。"""
        d = self._resolver(str(inst.get("status_id", "")), "status")
        if d is None:
            return {}
        return d.raw if hasattr(d, "raw") else d

    def _aggregate_boost(self, side: str, stat: str) -> float:
        """F-23（contract_deviations P1-6）：聚合 stat_modifier 效果值并封顶。

        - S6 cap_boost：单属性攻防提升 ±100% 满值上限（1b §4.1 S6）；
        - S7 cap_combined：三维组合总加成上限（1b §4.1 S7）。
        效果值聚合 = 遍历目标状态实例的 stat_modifier 动作按属性求和（百分比加
        法叠乘前先封顶，1g1c §② 派生累计乘区「加法叠乘 + ≤1.5× 封顶」的 S6/S7
        上限版），随后消费函数（_apply_boost_to_mult）再乘入技能倍率。
        """
        rt = self._new_runtime()
        agg_pct = 0.0
        for inst in rt.status_instances(side):
            raw = self._status_raw(inst)
            actions = raw.get("actions") or []
            for a in actions:
                if not isinstance(a, dict):
                    continue
                if a.get("type") == "stat_modifier" and a.get("stat") == stat:
                    v = a.get("value")
                    if isinstance(v, str) and v.strip().endswith("%"):
                        try:
                            agg_pct += float(v.strip().rstrip("%"))
                        except ValueError:
                            pass
                    elif isinstance(v, (int, float)) and not isinstance(v, bool):
                        agg_pct += float(v)  # 未带 % 视作百分点（F-23 收敛）
        # S6 单属性封顶 → S7 三维组合再封顶
        boosted = rt.cap_boost(agg_pct)
        return rt.cap_combined(boosted)

    def _apply_boost_to_mult(self, side: str, base_mult: float, stat: str = "atk") -> float:
        """把 F-23 聚合封顶后的加成并入技能倍率（M2 乘区，1a §1.2）。"""
        boost = self._aggregate_boost(side, stat)
        return base_mult * (1.0 + boost / 100.0)

    # ------------------------- 行动记录/统计 -------------------------

    def _record_action(
        self,
        actor: str,
        atype: str,
        target: str,
        rating: Dict[str, Any],
        damage: Dict[str, Any],
        phase: str,
        name: Optional[str] = None,
    ) -> int:
        """按「段」写入行动流水（每段独立记录，收集时机=拦截链→扣血后）。

        CTB（R6 映射）：旧 `turn` 字段 → `action_seq` + `battle_time` 双字段。
        `turn` 键**保留为 action_seq 镜像**（供世界层快照完整性校验 R-A 与旧读方
        过渡），但不参与计算；新读方（Agent 4 的 `_build_segments`）应按
        `action_seq` 过滤。
        """
        self._seq += 1
        _aseq = self.action_seq
        entry = {
            "seq": self._seq,
            "action_seq": _aseq,
            "battle_time": self.battle_time,
            "turn": _aseq,               # 兼容镜像（= action_seq，见 docstring）
            "phase": phase,
            "actor": actor,
            "action": atype,
            "name": (name or atype),
            "target": target,
            "rating": rating,
            "damage": damage,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._snap.setdefault("action_record", []).append(entry)
        if damage.get("final", 0) >= 0:
            self._snap.setdefault("stats_collector", {}).setdefault("per_action", []).append({
                "source": atype,
                "seg": len(self._snap["action_record"]),
                "ch_phys": damage.get("ch_phys", 0),
                "ch_elem": damage.get("ch_elem", 0),
                "crit": rating.get("crit", "low"),
                "blocked": bool(rating.get("blocked", False)),
                "pierce": rating.get("pierce", 0.0),
                "weak_type": rating.get("weak_type", 1.0),   # G3（定稿 §8.1 L326）：类型弱点倍率
                "weak_elem": rating.get("weak_elem", 1.0),   # G3（定稿 §8.1 L327）：元素弱点倍率
                "final": damage.get("final", 0),
            })
        return self._seq

    # ------------------------- 死亡判定（1g1b §三 T3/T4/T5 + A1/A4/A5） -------------------------

    def _mark_dead(self, side: str, trigger: str) -> None:
        """死亡登记：死亡判定后置位（1g1c dead_mark；玩家死→mark_lose L47，
        怪物死→mark_win L48）。同侧去重；顺序入 _death_order 供互杀审计。

        player_killed_enemy 标记先手击杀（1g1c TC-11：互杀 order 基准＝先手击杀
        生效→玩家胜）——仅当敌人死于玩家行动阶段时置位，行动开始 dot 双杀不入。
        """
        c = self._combat(side)
        if not c or c.get("dead_mark"):
            return
        c["_hp_before_death"] = float(c.get("hp", 0))   # G4：致死前 HP 记录（hp_ratio 互杀基准 L63）
        c["dead_mark"] = True
        c["hp"] = 0
        self._death_order.append(side)
        result = self._snap.setdefault("result", {})
        if side == "player":
            result["mark_lose"] = True
        else:
            result["mark_win"] = True
            if side == "enemy" and self._current_actor == "player" and self._qualified_kill_origin:
                result["player_killed_enemy"] = True  # 先手击杀（TC-11 order 基准）
        result.setdefault("marks", {}).setdefault(side, []).append(
            {"trigger": trigger, "action_seq": self.action_seq,
             "battle_time": self.battle_time,
             "turn": self.action_seq,   # 兼容镜像（R7：审计字段，不参与计算）
             "seq": self._seq}
        )

    def _death_check_side(self, side: str, trigger: str = "on_death") -> bool:
        """死亡判定（唯一两触发点 = 该 actor 行动开始 / 每次扣血后）。

        返回 True=该侧新增死亡标记。调用方在拦截链⑦扣血后（含 dot 扣血、反弹回注）
        立即调用，且每个时段只挂一次 DTH（state 经 RES→DTH→RES 走一圈）。

        CTB（ACTOR_DEATH 事件位点）：死亡同时同步给调度器（移出队列 + bump
        generation），使死者的在途票据作废、不再产出 ACTOR_READY。
        """
        if self._dead(side) and not self._combat(side).get("dead_mark"):
            self._to_state(STATE_DTH, f"hit/{trigger}")
            self._mark_dead(side, trigger)
            # 功能三批2：death 事件（effects trigger=death；死亡标记后触发）
            self._dispatch_event("death", side)
            self._to_state(STATE_RES, "continue")
            # CTB：同步调度器（ACTOR_DEATH）——死者退队，旧票作废
            if self._ctb is not None:
                _view = self._ctb.get_actor(side)
                if _view is not None and _view.alive:
                    self._ctb.mark_dead(side)
            # A4/A5 由调用方按 BOSS 决定即时结束
            return True
        return False

    def _boss_immediate_win(self) -> bool:
        """A5 BOSS/最后目标死亡→战斗立刻结束（不鞭尸；1g1b 辅助迁移 A5 / L53/L65/L239）。"""
        ec = self._combat("enemy")
        trig = bool(ec.get("is_boss", False)) or bool(ec.get("is_last_target", False))
        if not trig:
            return False
        if self._config.get("boss_end_immediate", True) and ec.get("dead_mark"):
            return True
        return False

    def _resolve_battle_end(self, force: bool = False) -> Optional[BattleOutcome]:
        """⑧ 战斗结束判定（1g1b 主迁移 T4/T5/T6 + A2 互杀 + A1 即死直出）。

        结算收尾单点（不变量5）：胜负/奖励/掉落/快照清理统一在此一次（L64）；
        BOSS/最后目标死亡走 A5 立即结束例外（L65/L239）。结果标记也由 1g1c
        §1.3 状态机驱动（mark_win/mark_lose/mark_escape/mutual_kill → status）。
        """
        if self._finished:
            return None
        result = self._snap.setdefault("result", {})
        p_dead = bool(result.get("mark_lose", False))
        e_dead = bool(result.get("mark_win", False))

        # ⑦ 互杀判定（双方死亡标记同轮并存，1g1b A2 / L59-63）
        mutual = p_dead and e_dead
        if mutual:
            result["mutual_kill"] = True
            basis = str(self._config.get("mutual_kill_basis", "order"))
            if basis == "order":
                # 互杀判定（定稿 L60-62 + 1g1c TC-11）——【D5 拍板，用户 2026-08-19】：
                # 「先手击杀生效 → 先手胜」（玩家对怪物：玩家先手击杀怪物即使同归于尽也判玩家胜）；
                # 无先手击杀的双死（行动开始 dot 双杀等）→ 平局。原实现 L62 互杀一律平局已按拍板覆盖。
                if bool(result.get("player_killed_enemy", False)):
                    # player_killed_enemy 由 _mark_dead 在「敌人死于玩家行动阶段」时置位
                    p_dead, e_dead = False, True   # 先手击杀生效 → 玩家胜（玩家视为存活结算）
                else:
                    p_dead, e_dead = True, True    # 无先手击杀（dot 双杀等）→ 平局
            else:  # hp_ratio（定稿 L63：比较「致死前一刻」双方剩余 HP 百分比，高者胜）
                p_before = float(self._combat("player").get("_hp_before_death", 0))
                e_before = float(self._combat("enemy").get("_hp_before_death", 0))
                p_max = max(1, float(self._combat("player").get("max_hp", 1)))
                e_max = max(1, float(self._combat("enemy").get("max_hp", 1)))
                pr = p_before / p_max
                er = e_before / e_max
                if abs(pr - er) < 1e-9:
                    p_dead, e_dead = True, True
                elif pr < er:
                    p_dead, e_dead = True, False
                else:
                    p_dead, e_dead = False, True
            if p_dead and e_dead:
                if self._config.get("mutual_kill_result") == "player_loss":
                    return self._settle(STATUS_LOSE, "mutual_kill", reason_detail="可配互杀玩家败")
                return self._settle(STATUS_DRAW, "mutual_kill", reason_detail="同时双死")

        if e_dead and not p_dead:
            if self._boss_immediate_win():
                return self._settle(STATUS_WIN, "boss_end_immediate", resolve_at="immediate")
            if force:
                return self._settle(STATUS_WIN, "enemy_dead")
            return None  # 普通怪：标记已打，当轮末尾统一结算（不变量5）
        if p_dead and not e_dead:
            # 玩家死：当轮末尾结算（L47/L64）——玩家死亡无法再行动，立即终局
            return self._settle(STATUS_LOSE, "player_dead", resolve_at="immediate")
        return None

    def _apply_skill_energy(
        self, attacker: str, ca: Mapping[str, Any], sd: Mapping[str, Any], target: str
    ) -> Optional[ActionOutcome]:
        """M13 6c 批12：技能 energy_cost 门禁 + energy_gain 结算（resource_axis 委托）。

        - energy_cost：施放前检查（不足 → 被拒不消耗行动，返回被拒 ActionOutcome）；
        - energy_gain：成功路径（调用方继续）后增加封顶——本方法在检查通过时
          立即结算 gain（同一技能 energy_cost+gain 并存时：先扣后增，契约 K4）。
        未注入 resource_registry（引擎无注册表）→ 零操作（容错，装配层接线后生效）。
        """
        try:
            from qbot_rpg.core import resource_axis  # noqa: PLC0415
        except Exception:  # pragma: no cover - 防御兜底
            return None
        registry = getattr(self, "_resource_registry", None)
        if registry is None:
            return None
        # energy_cost 门禁（技能 def 段；支持 {axis: {key: amt}} 与 {axis: amt}
        # 数值型简写两种形态——check_cost/pay_cost 内部归一（_cost_map_of））
        cost = sd.get("energy_cost")
        if isinstance(cost, Mapping) and cost:
            ctx = self._resource_ctx(attacker, target, registry)
            for axis_id, cost_map in cost.items():
                if not isinstance(axis_id, str) or not axis_id:
                    continue
                # 简写形态 {axis: int} → 归一 {axis: {axis: int}}（数值型 K1）
                _norm_cost: Dict[str, Any] = dict(cost_map) if isinstance(cost_map, Mapping) \
                    else {axis_id: int(cost_map or 0)}
                ok = resource_axis.check_cost(ctx, axis_id, _norm_cost, side=attacker)
                if not ok.get("ok", True):
                    seq = self._record_action(
                        attacker, str(ca.get("type", "skill")), target,
                        {"hit": False, "crit": "low", "blocked": False, "pierce": 0.0,
                         "multi": 1.0, "combo_rejected": True, "combo_reason": "energy_insufficient"},
                        {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase)
                    return ActionOutcome(
                        False, seq, attacker, str(ca.get("type", "skill")), target,
                        False, "low", False, 0, 0,
                        int(self._combat(target).get("hp", 0)), (),
                        f"能量不足（{axis_id}），技能被拒（不消耗行动）")
                # 扣减
                resource_axis.pay_cost(ctx, axis_id, _norm_cost, side=attacker)
        # energy_gain 结算（技能 def 段；成功施放后增加封顶）
        gain = sd.get("energy_gain")
        if isinstance(gain, Mapping) and gain:
            ctx = self._resource_ctx(attacker, target, registry)
            resource_axis.apply_gain(ctx, dict(gain), side=attacker)
        return None

    def _apply_consume_marks_gate(
        self, attacker: str, ca: Mapping[str, Any], sd: Mapping[str, Any], target: str
    ) -> Optional[ActionOutcome]:
        """技能 consume_marks 门禁 + 扣除（G2 2026-09-02 接线，细化_1d §4.2）。

        - consume_marks：{mark_id: count} 施放前检查（不足 → 被拒不消耗行动，S-01
          完全免费：不耗 MP/行动/连段保留；AT-17）；成功路径施放后扣除（AT-16）。
        - 侧判定（契约 P-1）：印记定义 appliable_to 含 self → attacker 侧；
          仅 enemy → target 侧（test_demo fire_mark / veinborn break_* 先例）。
        - 无 consume_marks 字段 → 零操作（既有技能零变化）。
        """
        consume = sd.get("consume_marks")
        if not isinstance(consume, Mapping) or not consume:
            return None
        try:
            mm = self.marks_manager()
            from qbot_rpg.core.marks import RemoveMark  # noqa: PLC0415
            from qbot_rpg.content.models import MarkDef  # noqa: PLC0415

            def _side_of(mark_id: str) -> str:
                d = self._resolver(mark_id, "mark")
                raw = d if isinstance(d, Mapping) else getattr(d, "raw", None)
                if isinstance(raw, Mapping):
                    apt = raw.get("appliable_to")
                    if isinstance(apt, list) and "self" in apt:
                        return attacker
                return target

            def _polarity_of(mark_id: str) -> str:
                d = self._resolver(mark_id, "mark")
                raw = d if isinstance(d, Mapping) else getattr(d, "raw", None)
                if isinstance(raw, Mapping):
                    return str(raw.get("polarity") or "positive")
                return "positive"

            for mark_id, need in consume.items():
                if not isinstance(mark_id, str) or not mark_id:
                    continue
                need_n = int(need or 0)
                if need_n <= 0:
                    continue
                side = _side_of(mark_id)
                pol = _polarity_of(mark_id)
                _md = self._resolver(mark_id, "mark")
                _mraw = _md if isinstance(_md, Mapping) else (getattr(_md, "raw", None) if _md else None)
                _mark_cn = str((_mraw or {}).get("name") or mark_id) if isinstance(_mraw, Mapping) else mark_id
                have = mm.count_by_name(side, mark_id) if hasattr(mm, "count_by_name") else 0
                if have < need_n:
                    seq = self._record_action(
                        attacker, str(ca.get("type", "skill")), target,
                        {"hit": False, "crit": "low", "blocked": False, "pierce": 0.0,
                         "multi": 1.0, "combo_rejected": True, "combo_reason": "marks_insufficient"},
                        {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase)
                    return ActionOutcome(
                        False, seq, attacker, str(ca.get("type", "skill")), target,
                        False, "low", False, 0, 0,
                        int(self._combat(target).get("hp", 0)), (),
                        f"印记不足（{_mark_cn}），技能被拒（不消耗行动）")
            # 检查全部通过 → 施放后实际扣除（此处即扣：调用点在 effects 结算前，
            # 契约 ADR D-01「先于结算」；扣后由 marks_manager 回灌快照）
            for mark_id, need in consume.items():
                if not isinstance(mark_id, str) or not mark_id:
                    continue
                need_n = int(need or 0)
                if need_n <= 0:
                    continue
                side = _side_of(mark_id)
                pol = _polarity_of(mark_id)
                mm.apply_remove(RemoveMark(side=side, polarity=pol, count=need_n, mark=mark_id))
        except Exception:  # pragma: no cover - 防御兜底不阻断战斗
            return None
        return None

    def _resource_ctx(self, attacker: str, target: str, registry: Any) -> Dict[str, Any]:
        """资源轴引擎 ctx 构造（注册表 + 双方 resource_state 注入）。"""
        from qbot_rpg.core.resource_axis import RESOURCE_STATE_KEY  # noqa: PLC0415

        state = self._snap.get(RESOURCE_STATE_KEY) or {}
        return {
            "stats": registry,
            RESOURCE_STATE_KEY: state,
        }

    # ------------------------- M13 批15 路15A：transform 战斗接线 -------------------------

    def _job_transform_segment(self) -> Dict[str, Any]:
        """惰性解析当前职业 transform 段（G0：不 import content/job_models）。

        读取优先级（防御性，缺省空段）：
          1) self._transform_def（装配层显式注入的 transform 段——测试/命令层
             可经 set_transform_def 注入，优先于一切配置源）；
          2) self._defs[\\"jobs\\"][job_id][\\"transform\\"]（jobs.json 配置，
             job_id 取 self._job_id 或 player 侧 job 字段）；
          3) player 侧 combatant job_transform 字段（命令层挂载形态）。
        返回空段 → 无 transform 配置（零操作降级）。
        """
        if isinstance(self._transform_def, Mapping) and self._transform_def:
            return dict(self._transform_def)
        defs = self._defs if isinstance(self._defs, Mapping) else {}
        jobs = defs.get("jobs")
        if isinstance(jobs, Mapping):
            job_id = str(self._job_id or "") or str(self._combat("player").get("job") or "")
            if job_id:
                jd = jobs.get(job_id)
                if isinstance(jd, Mapping):
                    t = jd.get("transform")
                    if isinstance(t, Mapping):
                        return dict(t)
        pc = self._combat("player")
        t = pc.get("job_transform")
        if isinstance(t, Mapping):
            return dict(t)
        return {}

    def _transform_ctx(self, attacker: str, ca: Mapping[str, Any], sd: Any) -> Dict[str, Any]:
        """构造 trigger_transform 战斗 ctx（快照段 + G0 钩子注入）。

        注入项：
          - transform_state：战斗快照 transform_state 段（引擎轨权威）；
          - combo_state/marks_state/status_state/combo_events：state_policy
            读写段（apply_state_policy 直接改快照）；
          - resolve_hook：触发技效果已在战斗通道结算（TRF-1），此处恒
            {ok:True} 不重结算（F1-2 时序契约）；
          - apply_status_hook：形态状态施加（form_status_id 双写 T6）；
          - rearrange_hook：技能位重排——形态技能组经 ctx[\\"form_skills\\"]
            注入（技能条目 raw dict），缺省引擎侧 rearrange_slots 装配
            （SH-1~5；装配层 skill_slots.apply_job_form 委托由 15B 路覆盖）；
          - resource_check_hook：C2 资源门禁——MP 足够 + energy_cost 已由
            战斗层上方门禁扣费，此处放行（防双重扣费，TRF-2 不额外消耗行动）；
          - skip_check：C4 被控判定（skip_turn 不触发）。
        """
        from qbot_rpg.core.transform import (  # noqa: PLC0415
            TRANSFORM_STATE_KEY,
            trigger_transform,
        )
        from qbot_rpg.core.transform_revert import REVERT_FORM  # noqa: PLC0415

        tctx: Dict[str, Any] = {
            TRANSFORM_STATE_KEY: self._snap.get(TRANSFORM_STATE_KEY),
            "combo_state": self._snap.setdefault("combo_state", {}),
            "marks_state": self._snap.setdefault("marks_state", {"player": [], "enemy": []}),
            "status_state": self._snap.setdefault("status_state", {"player": [], "enemy": []}),
            "combo_events": self._snap.setdefault("combo_events", []),
            "resolve_hook": (lambda c, t: {"ok": True, "effects": []}),
            "apply_status_hook": self._transform_apply_status,
            "resource_check_hook": (lambda c, t: {"ok": True, "reason": ""}),
            "skip_check": self._transform_skip_check,
        }
        fs = self._snap.get("transform_form_skills")
        if isinstance(fs, list):
            tctx["form_skills"] = fs
        return tctx

    def _transform_apply_status(self, ctx: Mapping[str, Any], transform: Mapping[str, Any], form: str) -> Optional[str]:
        """④a 形态状态施加（D-02 双轨效果侧）：经效果系统 apply_status 真实
        施加（status_state 写快照），返回 form_status_id（T6 双写登记）。

        形态状态定义（status_id）优先 transform.form_status_id，缺省
        form_status_id=None（不施加——双轨联动 dispel_reverts 由命令层/
        装配层在配置时保证）。无 registry/defs 解析 → 不施加（降级 None）。
        """
        from qbot_rpg.core.effects import DamageCtx  # noqa: PLC0415

        status_id = transform.get("form_status_id")
        if not isinstance(status_id, str) or not status_id:
            return None
        rt = self._new_runtime()
        ctx_snap = self._snap
        dctx = DamageCtx(
            raw_damage=0, attack_type="transform", attacker="player", target="player",
            snapshot=ctx_snap, variables=self._base_variables("player", "player"),
        )
        res = rt.apply_status(status_id, "player", source="player", attacker="player", ctx=dctx)
        self._absorb_runtime(rt)
        return status_id if bool(getattr(res, "applied", False)) else None

    def _transform_skip_check(self, ctx: Mapping[str, Any]) -> bool:
        """C4 被控判定（CTB 重写）：玩家 control_state 剩余**次数**>0 → True（不触发）。

        旧口径「skip_turn>0」中的时长单位是「回合」；CTB 下控制由持有者行动次数
        驱动（`_start_actor_turn` 中 `control_state.turns` 按持有者行动递减），
        故本判定的门禁语义 = 「该玩家当前仍处于被控窗口内」——**判定代码不变**
        （仍读 skip_turn>0），仅其时间单位由 R3/R4 的递减节奏重新定义。
        """
        ctrl = self._combat("player").get("control_state")
        return bool(isinstance(ctrl, dict) and float(ctrl.get("skip_turn", 0) or 0) > 0)

    def set_transform_def(self, transform: Optional[Mapping[str, Any]]) -> "BattleEngine":
        """装配注入：transform 段（transform_skill/transform_to/duration/turns/
        cooldown/state_policy/skill_set/form_status_id…）。None → 清空配置。
        """
        self._transform_def = dict(transform) if isinstance(transform, Mapping) else {}
        return self

    def set_job_id(self, job_id: str) -> "BattleEngine":
        """装配注入：当前职业 ID（_job_transform_segment 经 defs[jobs] 解析
        transform 段的 job_id 基准；缺省回退 player 侧 job 字段）。"""
        self._job_id = str(job_id or "")
        return self

    def _transform_policy_report(self) -> List[Mapping[str, Any]]:
        """transform 事件审计（触发/还原事件列表，供战报消息消费）。"""
        return list(getattr(self, "_transform_events", []) or ())

    def _apply_transform_revert(
        self,
        reason: str,
        *,
        cooldown: int = 5,
        side: str = "player",
    ) -> bool:
        """F2 还原结算（自然结束/主动 revert_form/被驱散 dispel 三路归一）。

        战斗层封装 transform_revert.revert_transform 的 state_policy 注入
        通道（combo/marks/buff 真实清快照）。transform 配置缺省 → 冷却按
        transform.cooldown（缺省 5）起算；无形态（form=null）→ 零操作。
        返回是否实际还原。
        """
        from qbot_rpg.core.transform_revert import (  # noqa: PLC0415
            REVERT_DISPEL,
            revert_transform,
        )

        ts = self._snap.get("transform_state")
        if not isinstance(ts, dict) or ts.get("form") is None:
            return False
        tseg = self._job_transform_segment()
        if not tseg:
            tseg = {"cooldown": cooldown}
        result = revert_transform(
            {"player": {"persistent_state": {"transform_state": ts}},
             "battle_state": self._snap},
            tseg,
            reason=reason,
            side=side,
            combo_clear=self._transform_combo_clear,
            marks_clear=self._transform_marks_clear,
            buff_remove=self._transform_buff_remove,
        )
        if result.get("ok") and result.get("reverted"):
            self._snap["transform_state"] = result["state"]
            # D-05：dispel 还原后清除持久标记（dispel_triggered 消费位，防重复还原）
            if reason == REVERT_DISPEL:
                ps = self._snap.get("player")
                if isinstance(ps, dict):
                    ps_ps = ps.get("persistent_state")
                    if isinstance(ps_ps, dict):
                        ps_ps.pop("transform_pending_dispel", None)
            events = list(getattr(self, "_transform_events", []) or ())
            events.append({
                "type": "transform_reverted",
                "reason": str(result.get("reason") or reason),
                "cooldown_remaining": int(result["state"].get("cooldown_remaining", 0)),
            })
            self._transform_events = events
            return True
        return False

    def _transform_combo_clear(self, side: str, snap: Mapping[str, Any], reason: str) -> None:
        """combo=clear 注入通道：清连段五字段空态 + combo_events 审计。"""
        from qbot_rpg.core.transform import apply_state_policy  # noqa: PLC0415

        if not isinstance(snap, dict):
            snap = self._snap
        apply_state_policy(snap, {"combo": "clear", "marks": "keep", "buff": "keep"}, side=side, reason=reason)

    def _transform_marks_clear(self, side: str, snap: Mapping[str, Any]) -> None:
        """marks=clear 注入通道：清印记实例列表。"""
        ms = snap.get("marks_state")
        if isinstance(ms, dict):
            ms[side] = []

    def _transform_buff_remove(self, side: str, snap: Mapping[str, Any], status_id: str) -> None:
        """buff=clear 注入通道：移除形态状态本体（status_state 条目）。"""
        ss = snap.get("status_state")
        if not isinstance(ss, dict):
            return
        entries = ss.get(side)
        if not isinstance(entries, list):
            return
        ss[side] = [e for e in entries if not (isinstance(e, dict) and (e.get("id") or e.get("status_id")) == status_id)]

    def _transform_dispel_tick(self, side: str = "player") -> None:
        """D-05 dispel 延迟结算（M8，CTB 重写）：驱散命中登记 → **持有者下一次
        行动收尾**还原（旧口径「下一回合结束 tick」→ CTB「下一次 ACTOR_TURN_END」）。

        读 transform_revert.dispel_triggered（persistent_state 标记）或战斗内瞬态
        缓存（_transform_dispel_pending，本次行动窗口内被驱散）。
        """
        from qbot_rpg.core.transform_revert import (  # noqa: PLC0415
            REVERT_DISPEL,
            dispel_triggered,
        )

        if self._transform_dispel_pending.get(side):
            self._transform_dispel_pending[side] = False
            self._apply_transform_revert(REVERT_DISPEL)
            return
        ps = self._snap.get("player")
        if isinstance(ps, dict) and dispel_triggered({"player": ps}, side=side):
            self._apply_transform_revert(REVERT_DISPEL)
            # 消费持久标记（防下次行动重复还原；_apply_transform_revert 内
            # 已在 REVERT_DISPEL 分支清除，此处兜底幂等）
            ps_ps = ps.get("persistent_state")
            if isinstance(ps_ps, dict):
                ps_ps.pop("transform_pending_dispel", None)

    def _resolve_combo_table_gate(
        self, attacker: str, ca: Mapping[str, Any], sd: Mapping[str, Any], target: str
    ) -> Optional[ActionOutcome]:
        """M13 批15 路15C：技能 combo_table 组合门禁 + F-C2 结算。

        - 无 combo_table 段 → None（B-3 常规技能回退）；
        - gate_combination 命中组合行 → settle_combo 双耗结算（MP+能量按行
          池分布扣减）+ 行为随组合变化，返回组合结算 ActionOutcome；
        - 未命中 → 被拒不消耗行动（reason=no_combo_match）。
        审计落 ca 侧 combo_result（战报/测试可观察）。
        """
        from qbot_rpg.core.combo_table import resolve_trigger  # noqa: PLC0415
        from qbot_rpg.core.combo_settle import settle_combo  # noqa: PLC0415

        rows_exist = bool(sd.get("combo_table"))
        if not rows_exist:
            return None
        registry = getattr(self, "_resource_registry", None)
        if not isinstance(registry, Mapping) or not registry:
            # 无资源注册表（引擎未装配资源轴）→ 组合门禁跳过（B-3 常规技能回退）
            return None
        axis_id = "element_energy"
        if registry is not None and isinstance(registry, Mapping):
            # 找第一个子池型轴作为组合能量轴（缺省 element_energy）
            for aid, entry in registry.items():
                if isinstance(entry, Mapping) and entry.get("type") == "element_energy":
                    axis_id = str(aid)
                    break
        ctx = self._resource_ctx(attacker, target, registry or {})
        # F-C1 一站式（resolve_trigger）：① 常规 → ② 总量门 → ③ 组合匹配
        gate = resolve_trigger(ctx, sd, axis_id, side=attacker)
        if not gate.get("ok"):
            reason = gate.get("reason", "no_combo_match")
            # 总量门不足优先提示（元素爆发 any:2 不足 → 「能量不足」）
            msg = f"能量不足（{reason}），组合技能被拒（不消耗行动）" \
                if reason in ("total_insufficient", "energy_total_insufficient") \
                else f"组合未达成（{reason}），技能被拒（不消耗行动）"
            seq = self._record_action(
                attacker, str(ca.get("type", "skill")), target,
                {"hit": False, "crit": "low", "blocked": False, "pierce": 0.0,
                 "multi": 1.0, "combo_rejected": True, "combo_reason": reason},
                {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase)
            return ActionOutcome(
                False, seq, attacker, str(ca.get("type", "skill")), target,
                False, "low", False, 0, 0,
                int(self._combat(target).get("hp", 0)), (), msg)
        row = gate.get("row")
        if row is None:
            return None
        # F-C2 双耗结算（MP + 能量按行池分布；先 check 后 pay）
        mp_cost = int(sd.get("mp_cost", 0) or 0)
        r = settle_combo(
            ctx, row, axis_id=axis_id, side=attacker, mp_cost=mp_cost,
            mp_check=lambda c, cost: bool(
                int(self._combat(attacker).get("mp", 0)) >= cost),
            mp_pay=lambda c, cost: self._combat(attacker).__setitem__(
                "mp", int(self._combat(attacker).get("mp", 0)) - cost),
            energy_check=lambda c, aid, cost: bool(
                self._energy_check_ok(c, aid, cost)),
            energy_pay=lambda c, aid, cost: self._energy_pay(c, aid, cost),
        )
        if not r.get("ok"):
            reason = r.get("reason", "combo_cost_insufficient")
            seq = self._record_action(
                attacker, str(ca.get("type", "skill")), target,
                {"hit": False, "crit": "low", "blocked": False, "pierce": 0.0,
                 "multi": 1.0, "combo_rejected": True, "combo_reason": reason},
                {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase)
            return ActionOutcome(
                False, seq, attacker, str(ca.get("type", "skill")), target,
                False, "low", False, 0, 0,
                int(self._combat(target).get("hp", 0)), (),
                f"能量不足（{reason}），组合技能被拒（不消耗行动）")
        # 成功：行为随组合变化（kind/power/element/hits/effects 覆写 ca）
        behavior = r.get("behavior") or {}
        if isinstance(ca, dict):
            ca["_combo_settled"] = True  # 防下方常规 MP/energy 重复扣费
            ca["combo_result"] = {"row": str(getattr(row, "name", "")),
                                  "energy": r.get("energy_cost")}
            if behavior.get("kind"):
                ca["kind"] = behavior["kind"]
            if behavior.get("power"):
                ca["power"] = behavior["power"]
            if behavior.get("element"):
                ca["element"] = behavior["element"]
            if behavior.get("hits"):
                ca["hits"] = behavior["hits"]
        return None  # 放行常规伤害结算（组合行为已覆写）

    def _energy_check_ok(self, ctx: Mapping[str, Any], axis_id: str, cost: Mapping[str, int]) -> bool:
        """能量池检查（缺注册表 → True 放行）。"""
        from qbot_rpg.core.resource_axis import check_cost  # noqa: PLC0415

        try:
            return bool(check_cost(ctx, axis_id, dict(cost), side="player").get("ok", True))
        except Exception:  # noqa: BLE001 - 防御兜底
            return True

    def _energy_pay(self, ctx: Mapping[str, Any], axis_id: str, cost: Mapping[str, int]) -> None:
        """能量池扣减（缺注册表 → 零操作）。"""
        from qbot_rpg.core.resource_axis import pay_cost  # noqa: PLC0415

        try:
            pay_cost(dict(ctx), axis_id, dict(cost), side="player")
        except Exception:  # noqa: BLE001 - 防御兜底
            pass

    def _tick_skill_cooldowns(self, actor: Optional[str] = None) -> None:
        """技能冷却递减（M9，CTB 重写）。

        旧口径（每回合 -1，`end_turn` 全员递减）→ CTB 口径：**该施放者每次行动后
        -1**（只递减 `actor` 侧，未指定时递减全部——保留旧调用兼容）。语义等价：
        「施放后 N 回合不可用」→「施放后该施放者 N 次行动不可用」。
        """
        _cdm = self._snap.get("skill_cooldowns")
        if not isinstance(_cdm, dict):
            return
        _sides = [actor] if actor else list(_cdm.keys())
        for side in _sides:
            _cds = _cdm.get(side)
            if not isinstance(_cds, dict):
                continue
            for _sid, _left in list(_cds.items()):
                _n = int(_left or 0) - 1
                if _n <= 0:
                    _cds.pop(_sid, None)
                else:
                    _cds[_sid] = _n

    def _tick_transform_state(self, actor: Optional[str] = None) -> None:
        """transform 形态 tick（M10，CTB 重写）。

        - 形态剩余递减（remaining-1；自然结束 → 还原回常态 + 冷却起算）；
        - 冷却递减（每"拍" -1，归 0 回 NORMAL）。

        CTB 口径：形态按**持有者行动次数**计时（旧「N 回合」→「N 次行动」）。
        `actor` 限定只有**形态持有者**（玩家侧）自己的行动才推进形态/冷却——旧回合制
        下「回合边界」对全员各结算一次；CTB 无回合边界，若不对 actor 设限，敌方每次
        行动也会扣减玩家的形态剩余/冷却，等于把「N 次玩家行动」错算成「N 次任意行动」
        （数值偏差：形态提前结束、冷却提前归零）。无形态（form=null）→ 冷却分支。
        纯函数委托 transform_revert。
        """
        from qbot_rpg.core.transform_revert import (  # noqa: PLC0415
            REVERT_DISPEL,
            REVERT_FORM,
            REVERT_NATURAL,
            should_revert_natural,
            tick_cooldown,
            tick_remaining,
        )

        # 形态/冷却属玩家（transform 段挂在玩家侧）；仅玩家自身行动后推进。
        if actor is not None and actor != "player":
            return

        ts = self._snap.get("transform_state")
        if not isinstance(ts, dict):
            return
        if ts.get("form"):
            # 形态持续中：remaining 递减
            ts.update(tick_remaining(ts))
            # M13 批15 路15A：dispel 延迟还原（D-05）——持有者下一次行动收尾结算
            # （CTB：等价旧「下一回合结束 tick」；state_policy + 冷却起算，P-3 不豁免）
            self._transform_dispel_tick(actor or "player")
            ts = self._snap.get("transform_state")
            if not isinstance(ts, dict):
                return
            # dispel 还原后同拍冷却递减（P-3 不豁免 + D-03：与自然结束同规则）
            if ts.get("form") is None and ts.get("cooldown_remaining", 0) > 0:
                ts.update(tick_cooldown(ts))
            if not ts.get("form"):
                return
            if should_revert_natural(ts):
                # 自然结束还原：form 清空 + 冷却起算（transform 配置经 job 惰性解析，
                # 引擎层只做状态机迁移；具体 cooldown 值由装配层注入 job_def 时设置）
                self._apply_transform_revert(REVERT_NATURAL)
                ts = self._snap.get("transform_state")
                if not isinstance(ts, dict):
                    return
                # 还原后同拍冷却递减（D-03：冷却随行动 tick 递减）
                if ts.get("cooldown_remaining", 0) > 0:
                    ts.update(tick_cooldown(ts))
        else:
            # 常态/冷却期：冷却递减
            ts.update(tick_cooldown(ts))

    # ------------------------- 换季×战斗联动（M13 6c：EFF-2/F-R2/E1/E5） -------------------------

    def _init_season_state(self) -> None:
        """进战懒加载（EFF-2）：战斗开始初始化换季状态段。

        初始生效季节 = 进战当前世界季节（ctx[\"season_now\"] 注入通道，装配层
        接 worldtime.season_now；无季节环境 → 回落通用 SEASON_ANY，全技能可用
        零空窗 P-2/P-10）。season_event_state 幂等段随 start 骨架就位（缺省
        last_season_idx=-1 → 首次换季必触发 E5 恰一次）。战斗外（无快照）→
        零操作降级（F-R2 ⑥ / P-7）。
        """
        from qbot_rpg.core.battle_season import (  # noqa: PLC0415
            init_battle_season,
        )

        snap = self._snap
        if not isinstance(snap, dict) or not snap:
            return
        season = str(snap.get("season_now") or "") or None
        init_battle_season(snap, season=season)
        # season_event_state 幂等段进战登记：last_season_idx ← 进战季节索引
        # （E5 恰一次语义——只有「后续换季 ≠ 进战季节」才触发事件）。
        try:
            from qbot_rpg.core import season_events  # noqa: PLC0415

            seg = snap.get(season_events.SEASON_EVENT_STATE_KEY)
            if not isinstance(seg, dict):
                seg = {}
                snap[season_events.SEASON_EVENT_STATE_KEY] = seg
            seasons = ("spring", "summer", "autumn", "winter")
            if season in seasons:
                seg[season_events.LAST_SEASON_IDX_KEY] = seasons.index(season)
            else:
                seg[season_events.LAST_SEASON_IDX_KEY] = -1
        except Exception:  # noqa: BLE001 - 防御兜底
            pass

    def _season_ctx(self) -> Dict[str, Any]:
        """换季懒重读数据源 ctx（season_now + season_idx 注入通道，P-1）。"""
        snap = self._snap
        if not isinstance(snap, dict):
            return {}
        return {"season_now": snap.get("season_now"), "season_idx": snap.get("season_idx")}

    def _check_season_action(self, attacker: str, action: Dict[str, Any]) -> Optional[ActionOutcome]:
        """技能行动换季校验（EFF-5 唯一入口，skill_season.validate_skill_action）。

        仅拦截 {type: skill} 行动（普攻 normal/防御 guard 全年可用，EFF-3 兜底）；
        非当季技能 → **被拒（R-6 裁决 2：零时间成本、直接重试）**——不推进行动条、
        不派发 ACTOR_TURN_START 链路事件，拒绝原因经 outcome 上报（不静默吞）。
        旧表述「不耗回合」在 CTB 下即此语义（被拒 = 该行动从未发生）。
        懒重读：当前季节经 ctx season_now 每次行动前现读（SC-2 引擎零新状态机）。
        未注入 season_now（无季节环境）→ 判定恒 ok，零空窗。
        """
        if str(action.get("type") or "") != "skill":
            return None
        skill_id = str(action.get("skill_id") or action.get("id") or "")
        if not skill_id:
            return None
        try:
            from qbot_rpg.core import skill_season  # noqa: PLC0415
        except Exception:  # pragma: no cover - 防御兜底
            return None
        sd = self.combo_engine().resolve_skill(skill_id) or {}
        season = skill_season.current_season(self._season_ctx())
        result = skill_season.validate_skill_action(sd, season)
        if result.get("ok"):
            return None
        # 非当季：被拒（R-6：零时间成本、直接重试；不推进行动条）——_record_action
        # 仅写审计流水，不动 queue、不动 next_ready（调用方 player_act 直接返回）。
        target = self._opposite(attacker)
        seq = self._record_action(
            attacker, "skill", target,
            {"hit": False, "crit": "low", "blocked": False, "pierce": 0.0,
             "multi": 1.0, "combo_rejected": True, "combo_reason": "season_mismatch"},
            {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase)
        return ActionOutcome(
            False, seq, attacker, "skill", target, False, "low", False,
            0, 0, int(self._combat(target).get("hp", 0)), (),
            "此术式与当前时节不合，技能被拒（零时间成本，可立即换指令）")

    def _tick_season_boundary(self) -> Dict[str, Any]:
        """换季结算边界（M11，CTB 重写）：挂 `BATTLE_TIME_ADVANCE`（全局时间推进位点）。

        旧口径「end_turn ⑥ tick 后（⑥⑦ 之间）」是「回合边界」；CTB 无回合边界 →
        换季是**全局战斗时间效果**（季节属世界、不属任何 actor），故挂全局时间推进
        位点（由 `_on_battle_time_advance` 调用）。不变量保持：切换必须发生在
        「当前行动校验完成之后」（时间位点在 ACTOR_READY 之前派发）；幂等由
        battle_season.tick_season_boundary 内部保证（SC-3 恰一次）。
        `battle_season.py` 函数体纯（仅读写 battle_season/season_event_state 段）。
        """
        from qbot_rpg.core.battle_season import tick_season_boundary  # noqa: PLC0415

        snap = self._snap
        if not isinstance(snap, dict) or not snap:
            return {"switched": False}
        season = str(snap.get("season_now") or "") or None
        return tick_season_boundary(snap, season)

    def _fire_season_event(self, switched: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """on_season_change 换季事件触发（E1/E5：恰一次 + L2 proc 容器）。

        仅在换季结算切换成功（switched=True）且当前季节索引 ≠ 上次已触发索引
        时触发（season_events.trigger_season_event 幂等基准）；proc 列表经
        ctx[\"season_procs\"] 注入（内容包装配，缺省空 → 只登记不执行）。
        L2 proc 走 execute_proc_action 容器（max_triggers 双重封顶，E3）。
        """
        if not switched.get("switched"):
            return []
        try:
            from qbot_rpg.core import season_events  # noqa: PLC0415
        except Exception:  # pragma: no cover - 防御兜底
            return []
        snap = self._snap
        season = str(snap.get("season_now") or "") or None
        procs = snap.get("season_procs") if isinstance(snap, dict) else None
        if not isinstance(procs, list):
            procs = []
        rt = self._new_runtime()
        runner = None
        if isinstance(procs, list) and procs:
            from qbot_rpg.core.effects import execute_proc_action  # noqa: PLC0415

            def _runner(proc: Mapping[str, Any], runtime: Any) -> Any:
                ctx = DamageCtx(
                    raw_damage=0, attack_type="season", attacker="player",
                    target="enemy", snapshot=snap,
                    variables=self._base_variables("player", "enemy"),
                )
                return execute_proc_action(proc, ctx, runtime)

            runner = _runner
        result = season_events.trigger_season_event(
            snap, season, procs=procs, runtime=rt, proc_runner=runner,
        )
        self._absorb_runtime(rt)
        # 功能三批2：season_change 收编——season_procs（既有装配通道）与 effects
        # trigger=season_change（新通用事件通道）双轨触发；无配置 → [] 零行为变化
        self._dispatch_event("season_change", "player")
        self._dispatch_event("season_change", "enemy")
        return list(result.get("proc_results") or [])

    def _dispatch_event(self, event: str, side: str, **kw: Any) -> List[Dict[str, Any]]:
        """功能三：统一效果事件分派（通用效果事件分派器 · 批2 接线）。

        在战斗时点 fire 匹配事件的效果/proc/状态 on_xxx 动作（effects 定义 trigger
        字段 / statuses on_gain/on_lose；未配置 → [] 零行为变化）。registry 注入
        self._registry（未注入/异常 → 安全失败返回 []，不阻断战斗主流程）。
        """
        try:
            from qbot_rpg.core.event_dispatcher import dispatch_event  # noqa: PLC0415

            return dispatch_event(
                event, side, self._snap, self._registry,
                runtime=self._new_runtime(), **kw,
            )
        except Exception:  # noqa: BLE001 —— 事件分派异常不阻断战斗（安全失败）
            return []

    def _settle(
        self,
        status: str,
        reason: str,
        resolve_at: str = "turn_end",
        reason_detail: str = "",
    ) -> BattleOutcome:
        """⑧ 统一收尾（1g1c §1.3 结果标记 + B5/TC-25：任何出口连段一律清零）。

        奖励/掉落/消息登记由世界层（1g4）消费 result 后统一执行；本引擎只标记
        终态并清理战斗内资源（连段清零 + 快照清理标记）。
        """
        result = self._snap.setdefault("result", {})
        result["flag"] = status
        result["resolve_at"] = resolve_at
        self._snap["status"] = status
        # B5：combo_state 随战斗结束清零（1c1b T7 / 1g1c B5），combo_zeroed_at 审计
        if self._snap.get("combo_state"):
            zero_reason = {
                STATUS_WIN: "battle_end", STATUS_LOSE: "death",
                STATUS_ESCAPE: "escape", STATUS_DRAW: "battle_end",
            }.get(status, "battle_end")
            self._snap["combo_state"] = {}
            self._snap["combo_zeroed_at"] = zero_reason
        else:
            zero_reason = None
        # 功能三批2：battle_end 事件（effects trigger=battle_end；在 marks 清零前
        # 触发——效果仍可读印记/状态；无配置 → [] 零行为变化）
        self._dispatch_event("battle_end", "player")
        self._dispatch_event("battle_end", "enemy")
        # P1-2（dsh 批3）：marks_state 与连段双轴生命周期一致——战斗结束/逃跑成功清零
        self._snap["marks_state"] = {"player": [], "enemy": []}
        # M13 6b（细化_6b §4.1 SN-4）：transform_state 战斗结束清零回常态（form=null）
        self._snap["transform_state"] = {
            "job_id": "", "form": None, "form_name": None,
            "remaining": 0, "cooldown_remaining": 0,
            "form_status_id": None, "active_skill_set": None,
        }
        # M13 6c（细化_6c §1.3 F-R1 终段 / S5 + §1.4 RS-3）：resource_state 战斗结束
        # reset 策略处理——battle 型清零 / keep 型跨战斗保留（RS-3 存档双落由装配层
        # 消费）/ battle_start 型战斗内保留。引擎按注册表逐轴口径；无 resource_state
        # 段或未注册轴 → 零操作降级（RS-5 精神，不抛异常）。
        try:
            from qbot_rpg.core.resource_lifecycle import (  # noqa: PLC0415
                RESET_BATTLE,
                ResourceLifecycle,
            )

            ResourceLifecycle(self._resource_registry).battle_end_reset(
                self._snap, reset_policy=RESET_BATTLE,
            )
        except Exception:  # noqa: BLE001 装配层未注入资源注册表 → 零操作降级（RS-5）
            pass
        self._finished = True
        self._state = {STATUS_WIN: STATE_WIN, STATUS_LOSE: STATE_LOSE,
                       STATUS_ESCAPE: STATE_FLY, STATUS_DRAW: STATE_LOSE}[status]
        # 快照清理登记（1g1c TC-18/TC-24：战斗结束不残留脏快照）
        self._snap["snapshot_cleaned"] = True
        outcome = BattleOutcome(
            status=status,
            reason=reason + (f"[{reason_detail}]" if reason_detail else ""),
            turn=self.action_seq,          # CTB（R12）：action_seq 镜像（审计，不参与计算）
            resolve_at=resolve_at,
            combo_zeroed_reason=zero_reason,
        )
        # BATTLE_END 事件位点：通知调度器终局（不再派发行动链事件）
        if self._ctb is not None and not self._ctb.finished:
            self._ctb.finish()
        self._outcome = outcome
        return outcome

    # ------------------------- 公开 API · resolve_damage（保留旧签名） -------------------------

    def resolve_damage(
        self,
        attacker: str,
        target: str,
        raw_damage: int,
        attack_type: str = "basic",
        snapshot: Optional[dict] = None,
        runtime: Optional[EffectRuntime] = None,
        variables: Optional[dict] = None,
    ) -> PipelineResult:
        """组装 DamageCtx 并执行 8 阶段拦截链（细化_1b §2 伪代码；保留 M1 接线）。

        兼容旧签名：snapshot 传 None 时构建最小可用骨架（_minimal_snapshot，测试/
        演示用）；战斗层应传**可变工作拷贝**（拦截链⑦⑧写 HP/defenses）。
        variables 会补默认变量（rng/rng_state/eval_formula/pipeline 等，F-组）。
        """
        snap = dict(snapshot) if snapshot is not None else self._minimal_snapshot(attacker, target, raw_damage)
        rt = runtime if runtime is not None else self._new_runtime()
        for side in (attacker, target):
            combatant = snap.get(side)
            if isinstance(combatant, dict) and "defenses" not in combatant:
                combatant["defenses"] = self._pipeline.prepare_defense(side)
        vars_ = self._base_variables(attacker, target)
        vars_.update(dict(variables or {}))
        vars_["pipeline"] = self._pipeline
        ctx = DamageCtx(
            raw_damage=max(0, int(raw_damage)),
            attack_type=attack_type,
            attacker=attacker,
            target=target,
            snapshot=snap,
            variables=vars_,
        )
        res = self._pipeline.damage_pipeline(ctx, rt)
        if runtime is None:
            # 引擎自建 runtime：把五块回灌（供调用方读取状态变化）
            for key in _FIVE_BLOCKS:
                snap[key] = getattr(rt, key)
        return res

    def _minimal_snapshot(self, attacker: str, target: str, raw_damage: int) -> dict:
        """最小战斗快照骨架（resolve_damage 无快照参数时的兜底，测试用；原样保留）。

        CTB：`turn` 键保留为 action_seq 镜像（= 0）以满足世界层完整性校验（R-A），
        另补 `action_seq` / `battle_time` 双计数键。
        """
        return {
            "session_type": "battle",
            "turn": 0,               # 兼容镜像（= action_seq，R-A）
            "action_seq": 0,
            "battle_time": 0.0,
            attacker: {
                "max_hp": 1000, "hp": 1000, "atk": 100, "dfn": 50,
                "mag": 50, "spd": 50, "name": attacker,
            },
            target: {
                "max_hp": 1000, "hp": max(0, 200 - (raw_damage // 2)), "atk": 100, "dfn": 50,
                "mag": 50, "spd": 50, "name": target,
            },
            "status_state": {attacker: [], target: []},
            "marks_state": {attacker: [], target: []},
            "resist_table": {attacker: {}, target: {}},
            "effect_triggers": {attacker: {"per_turn": {}, "per_battle": {}}, target: {"per_turn": {}, "per_battle": {}}},
            "effect_cooldowns": {attacker: {}, target: {}},
            "formula_state": {},
        }

    # ------------------------- 公开 API · 战斗生命周期（1g2 时序） -------------------------

    def start(
        self,
        player: Mapping[str, Any],
        enemy: Mapping[str, Any],
        random_seed: Optional[int] = None,
        battle_type: str = "dummy",
        config: Optional[Mapping[str, Any]] = None,
    ) -> "BattleEngine":
        """S0 战前准备 → 主循环（1g1a §1 / 1g1b T1）。

        建立 battle_state（1g1c §1.2：battle_id/status/rule_version/双方单位/
        action_record/result/combo_state/ai_state/stats_collector/timestamps），
        确立随机种子与收集器（L311-333），随即进入首个回合（start_turn）。

        player/enemy：combatant 映射（max_hp/hp/atk/dfn/mag/spd/foc/con/str/int/
        agi/spr/lck/elem_atk/is_boss 等；缺省字段用 _DEFAULT_STATS）。battle_type：
        ambush/dungeon/dummy（1g1c §1.2）。config：本次战斗覆盖引擎配置。
        """
        if self._state != STATE_PREP:
            raise BattleStateError(f"start 仅允许战前准备态进入（当前 {self._state}，1g1b T1）")
        if config:
            self._config.update(config)
        # M13 批15 路15A：job_id 冗余缓存（装配层可经 set_job_id 注入；缺省 ""
        # → _job_transform_segment 回退 player 侧 job 字段）
        self._job_id = str(getattr(self, "_job_id", "") or "")
        self._rng_seed = random_seed if random_seed is not None else random.SystemRandom().randint(0, 2**31 - 1)
        # 尊重调用方注入的自定义确定性 RNG（测试 QueueRNG 等；内置 Random → 按 seed 重建），
        # 生产构造 _reset_state 已建默认 Random() → isinstance(Random) 走 seed 重建（4a TC-17 同种子可复现）。
        if getattr(self, "_rng", None) is None or isinstance(self._rng, random.Random):
            self._rng = random.Random(self._rng_seed)

        def _combatant(data: Mapping[str, Any]) -> Dict[str, Any]:
            merged: Dict[str, Any] = dict(_DEFAULT_STATS)
            merged.update(data)
            merged["max_hp"] = int(merged.get("max_hp", 500))
            merged["hp"] = min(int(merged.get("hp", merged["max_hp"])), merged["max_hp"])
            merged["name"] = str(merged.get("name") or "unit")
            merged.setdefault("dead_mark", False)
            merged.setdefault("skip_turn", False)
            merged.setdefault("defenses", {})
            return merged

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # 携带素材冻结源（battle_materials：装配层传背包素材集；None/非法 → {}）
        _frozen_materials = self._config.get("battle_materials")
        self._snap = {
            "session_type": "battle",
            "battle_id": str(uuid.uuid4()),
            "battle_type": battle_type,
            # M12.5 木桩标记：快照常驻（续战 from_snapshot 恢复即可判，不依赖
            # 调用方 enemy_def 透传）；判定源 = 敌人条目 tier/type（怪物模块 §十五）
            "is_dummy_battle": bool(
                (self._enemy_def if isinstance(self._enemy_def, Mapping) else {})
                .get("tier") == "training"
                or (self._enemy_def if isinstance(self._enemy_def, Mapping) else {})
                .get("type") == "dummy"
            ),
            "status": STATUS_ACTIVE,
            "rule_version": str(self._config.get("rule_version", CTB_RULE_VERSION)),
            # P0-1 续战旧配置修复（M6 D3 RSM-02 / F-RSM-01）：世代绑定键——start 写当前
            # registry 世代；中断/边界快照经 to_snapshot 深拷贝自动沿用；旧快照缺该
            # 字段 → 续战入口兼容读取默认 0（走 RSM-04 降级）。
            # P2-RSM-05 修复：非数值 generation（畸形注入）回落 0，不崩（对齐 _num 防御口径）。
            "registry_generation": (
                int(getattr(self._registry, "generation", 0))
                if self._registry is not None
                and isinstance(getattr(self._registry, "generation", 0), (int, float))
                and not isinstance(getattr(self._registry, "generation", 0), bool)
                else 0
            ),
            # CTB 双计数（Agent 3）：action_seq=已结算行动计数（整数，替代旧回合数）；
            # battle_time=逻辑时间（浮点，由调度器推进）。`turn` 保留为 action_seq 的
            # 兼容镜像（R-A：世界层快照完整性校验需要该键存在），**不参与任何计算**。
            "action_seq": 0,
            "battle_time": 0.0,
            "turn": 0,
            "round_phase": PHASE_ACTOR_READY,
            "player": _combatant(dict(player)),
            "enemy": _combatant(dict(enemy)),
            "action_record": [],
            "result": {"flag": None, "mark_win": False, "mark_lose": False,
                       "mark_escape": False, "mutual_kill": False},
            "combo_state": {},
            "combo_zeroed_at": None,
            "ai_state": {},
            # M2 审查 P2-3：lost_pending 预留（1g4 F-08 丢失挂起子态；M4 丢失判定写入，
            # to_snapshot 深拷贝自动携带——快照结构稳定，M4 读路径键存在）
            "lost_pending": None,
            # M8 批9 收口（BA-02/IF-B03）：战斗即时调合计数。Step 5 迁移（方位 v0.6
            # §三.7）后段内 battle_resources.battle_alchemy_used 为权威读点；顶层键保留
            # 同步镜像（旧快照/旧读方兼容）。中断恢复不清零、战斗结束由 start 重建清零。
            "battle_alchemy_used": 0,
            "stats_collector": {"per_action": []},
            "formula_state": {"random_seed": self._rng_seed},
            "timestamps": {"created_at": now, "updated_at": now, "snapshot_at": None},
            # 效果系统五块（1b §8.3 快照扩展）
            "status_state": {"player": [], "enemy": []},
            "marks_state": {"player": [], "enemy": []},
            "resist_table": {"player": {}, "enemy": {}},
            "effect_triggers": {"player": {"per_turn": {}, "per_battle": {}},
                                "enemy": {"per_turn": {}, "per_battle": {}}},
            "effect_cooldowns": {"player": {}, "enemy": {}},
            # M13 6b（细化_6b §4.1）：transform_state 7 字段（T1~T7）——形态快照段，
            # 常态骨架（form=null）；由变换引擎 F1 写入、F3 快照携带、F2 还原/清零。
            "transform_state": {"job_id": "", "form": None, "form_name": None,
                                "remaining": 0, "cooldown_remaining": 0,
                                "form_status_id": None, "active_skill_set": None},
            # M13 6c（细化_6c §1.4 RS-1~6）：resource_state 快照段（per-side dict，
            # 数值型单键 / 子池型池级展开 D-04）——start 常态骨架；运行时增减经
            # ResourceLifecycle 引擎（resource_lifecycle.py）写入，快照随深拷贝携带。
            "resource_state": {"player": {}, "enemy": {}},
            # M13 6c（细化_6c §2.3 机制 M6）：battle_season 换季状态段（P-2：
            # {season, pending}）——进战懒加载初始生效季节=进战当前世界季节
            # （EFF-2），由 _init_season_state 在 start 收尾统一写入；无季节环境
            # （未注入 ctx season_now）→ 回落通用 SEASON_ANY（全技能可用零空窗）。
            "battle_season": {"season": "general", "pending": False},
            # M13 6c（细化_6c §2.5 M7）：season_event_state 换季事件幂等段
            # （E2/E5：last_season_idx 恰一次幂等基准；战斗外/缺段 → 缺省 -1）。
            "season_event_state": {"last_season_idx": -1},
            # 方位战斗系统 v0.6（草案 §三.1/§三.3/§三.7 + 附录 A Step 0 快照地基）：
            # combat_position / parts_state / battle_resources 三段空壳。快照=战斗唯一
            # 权威状态——空壳先随 start/中断/续战全链往返；机制按 §四 T8 时序由后续
            # 步骤注入。读取侧一律缺段降级（旧快照无段不崩，对齐 resource_state RS-5）。
            "combat_position": {
                # §三.1：每 combatant 一份。1v1 双方相对寻址：player 恒朝敌，
                # side=玩家相对怪物的方位格、height=空/地；默认正面贴地。
                "player": {"relative_to": "enemy", "side": "front", "height": "ground"},
                "enemy": {"relative_to": "player", "side": "front", "height": "ground"},
            },
            # §三.3：部位破坏实例态（part_id → {"break_value": 0, "broken": false}）。
            # 配置源=EnemyDef.parts[]（内容包），本段=战斗内权威实例。1v1 单敌直接按
            # part_id 索引；组队/多敌里程碑（§二.6）需扩 side 包裹，预留不预做。
            "parts_state": {},
            # §三.7：战斗携带素材冻结容器——start 从引擎配置 battle_materials 深拷贝
            # 冻结（内容包装配层传背包素材集；N5 白名单随试点包定）；即时调合查询/扣减
            # 以本段为权威（附录 A Step 5：count_item/remove_item hook 绑容器 + 扣减
            # 同步落实时背包防消耗丢失）。battle_alchemy_used：段内权威读点（顶层=同步
            # 镜像兼容旧快照/旧读方）。快照透传：续战 from_snapshot 全量还原不重冻。
            "battle_resources": {
                "materials": dict(
                    copy.deepcopy(_frozen_materials)
                    if isinstance(_frozen_materials, Mapping)
                    else {}
                ),
                "battle_alchemy_used": 0,
            },
        }
        self._finished = False
        self._death_order = []
        self._guard_active = {"player": False, "enemy": False}
        self._armor_active = {"player": False, "enemy": False}
        self._player_ready_pending = False
        self._ctb_event_log = []
        # 效果列表（F-21：effect_ids 装配源，玩家“装备”效果由外部注入）
        self._effect_ids.setdefault("player", [])
        self._effect_ids.setdefault("enemy", [])
        self._refresh_defenses()
        # M13 6c（细化_6c §2.3 EFF-2 进战懒加载）：战斗开始初始化换季状态段——
        # 初始生效季节 = 进战当前世界季节（注入通道 ctx season_now；无季节环境
        # → 回落通用 SEASON_ANY，全技能可用零空窗 P-2/P-10）。引擎零 import
        # worldtime/engine（G0），懒重读数据源经装配层注入 ctx。
        self._init_season_state()
        # M13 6c（细化_6c §1.3 F-R1 首行）：battle_start_init——战斗开始按注册表
        # 置 base（数值型置 base / 子池型各池置 base，覆盖残留值）。注册表未注入
        # → 零操作降级（RS-5 精神：resource_state 保持空骨架，读取回落 base）。
        try:
            from qbot_rpg.core.resource_lifecycle import ResourceLifecycle  # noqa: PLC0415

            _rl = ResourceLifecycle(self._resource_registry)
            _rl.battle_start_init(self._snap, "player")
            _rl.battle_start_init(self._snap, "enemy")
        except Exception:  # noqa: BLE001 - 装配层未注入注册表 → 零操作降级
            pass
        # 功能三批2：battle_start 事件（双方 effects trigger=battle_start 触发；
        # 无配置 → [] 零行为变化）
        self._dispatch_event("battle_start", "player")
        self._dispatch_event("battle_start", "enemy")
        # 方位 v0.6（附录 A Step 2）：敌方 parts 配置 → parts_state 实例化（幂等；
        # 无 parts 配置 → 空段零变化；中断恢复随快照段透传不重建）
        self._init_parts_state()
        # ---- CTB：建行动条（BATTLE_START 事件位点）----
        # 调度器是逻辑时间的唯一推进源；本引擎把「谁什么时候动」全权委托给它。
        # 木桩敌人（tier=training/type=dummy）不入队——等价旧口径「木桩永不出手」
        # （Wave A M3 语义等价性论证：木桩不参与 ready 队列）。
        self._ctb = self._make_scheduler()
        self._to_state(STATE_ACT, "battle_start")
        # 首个 ready 推进：调度器消费第一个 ready（action_seq → 1）——
        # 若首个 ready 是玩家则暂停、等待 `player_act` 提交行动；若是 NPC 则会
        # 自动连锁到下一个玩家 ready 或终局（`_resolve_ready_actor` 内循环）。
        self._resolve_ready_actor()
        self._sync_counts()
        return self

    def _make_scheduler(self) -> CTBScheduler:
        """按当前战斗配置建行动条调度器并登记双方（CTB 重写核心装配）。

        - 规则参数取自 `config["ctb"]`（recovery/speed_reference/min_speed/
          action_delay），经 `resolve_rule_config` 归一（缺省对齐 ctb_rules 常量）。
        - 有效速度 = combatant 的 `spd`（下限保护由公式层负责）。
        - 木桩敌人不入队（`_is_dummy_enemy_def()`）——调度器侧无该单位即永不 ready，
          与旧「木桩永不出手」语义等价。
        - `initiative_fn=None`：首轮无偏置（双方 ready 时刻由公式自然产出，
          保证同种子同序列的确定性）。
        - `npc_resolver=self._resolve_npc_action`（2026-09-10 补）：**NPC 行动执行回调**。
          调度器只负责「何时轮到 NPC」，**行动内容与数值结算仍归引擎**——在
          ACTION_RESOLVE 位点回调本引擎，执行 MonsterAI 决策 + 命中/伤害/效果全链路。
          这是旧 `enemy_act()` 承担的执行职责在 CTB 下的迁移落点（分层契约：
          调度器零战斗数值，引擎零时序决策）。
        """
        cfg = self._config.get("ctb")
        ctb = CTBScheduler(
            config=cfg,
            initiative_fn=None,
            seed=self._rng_seed,
            npc_resolver=self._resolve_npc_action,
        )
        ctb.push_actor(
            "player", side="player",
            effective_speed=float(self._combat("player").get("spd", 0) or 0),
            is_player=True,
        )
        if not self._is_dummy_enemy_def():
            ctb.push_actor(
                "enemy", side="enemy",
                effective_speed=float(self._combat("enemy").get("spd", 0) or 0),
                is_player=False,
            )
        ctb.start()
        return ctb

    def _resolve_npc_action(self, actor_id: str, action_seq: int) -> Optional[float]:
        """NPC 行动执行回调（ACTION_RESOLVE 位点，2026-09-10 补生产缺口）。

        由 `CTBScheduler._auto_resolve_npc` 在 NPC 行动结算点调用；本方法负责
        **把 MonsterAI 的决策真正执行成一次行动**，并把该行动的 recovery 回传，
        供调度器计算该 NPC 的下一次 ready。

        职责链（对齐 01_asset_inventory §0.2 事件位点词典 + m2_shared_contract §六）：
          1. 终局/死亡前置：战斗已结束或该 actor 已退场 → 不行动（返回 None）。
          2. 控制状态：`control_state.skip_turn` > 0 由 `do_action` 内部裁决为跳过
             （时间照走的硬直），无需在此特判。
          3. 行动内容：`_ai_action_dict()`（MonsterAI.decide；PVP 防守方恒防御；
             无 AI 注入 → None → 回落 M1 默认普攻）。
          4. 执行：走与玩家完全相同的 `do_action` 提交通道（同构双库：技能=怪物行动
             =一次出手，复用同一伤害/效果/连段/死亡判定链）。
          5. recovery 回传：取该 actor 本次 action 的总恢复值。

        异常一律兜底（记日志 + 返回默认 recovery），**绝不向上抛**——NPC 执行异常
        不得中断时间轴推进（否则调度器抛错会导致战斗卡死）。

        :param actor_id: 行动者标识（CTB 下为 "enemy" 等 NPC 侧）
        :param action_seq: 本次行动序号（审计用）
        :return: 该行动的 recovery（调度器重签票据用）；无法解析 → None（走规则默认）
        """
        try:
            if self._finished or not self._alive(actor_id):
                return None
            if self._state not in (STATE_ACT, STATE_RES):
                return None
            action_dict = self._ai_action_dict()
            if action_dict is None:
                # 无 AI 注入 / decide 异常 → M1 默认普攻（contract §六 回落口径）
                action_dict = {"type": "normal", "mult": 1.0}
            outcome = self.do_action(actor_id, action_dict)
            # Render 通道（04_wave_b_integration §五.1 遗留风险 1 收口）：把 NPC 自动
            # 裁决的 ActionOutcome 暂存，供 `player_act` 汇总进 TurnReport.outcomes。
            # 缺此前，NPC 伤害虽已结算/落 record，但不出现在报告 outcomes 里 →
            # 渲染层拿不到 NPC 行动行（战斗表现为「玩家单方面输出」）。
            if outcome is not None:
                self._npc_outcomes.append(outcome)
            return self._action_recovery(actor_id, action_dict)
        except Exception:  # noqa: BLE001 - 兜底不崩：NPC 执行异常不得阻断时间轴
            _logger.exception("NPC 行动执行失败：actor=%s action_seq=%s", actor_id, action_seq)
            return None

    def _ctb_actor_speed(self, side: str) -> float:
        """该侧当前有效速度（CTB 行动条入队/更新用）。"""
        return float(self._combat(side).get("spd", 0) or 0)

    def _sync_scheduler_deaths(self) -> None:
        """死亡同步：把引擎侧死亡标记推给调度器（移出队列 + bump generation）。

        每段扣血后调用（`_death_check_side` 收尾）——死者的在途票据作废，
        不再产出 ACTOR_READY。
        """
        if self._ctb is None:
            return
        ctb = self._ctb
        for side in BATTLE_SIDES:
            _view = ctb.get_actor(side)
            if self._dead(side) and _view is not None and _view.alive:
                ctb.mark_dead(side)

    def _rule_config(self) -> CtbRuleConfig:
        """当前 CTB 规则配置（可调参数读取的唯一入口）。

        调度器已装配 → 调度器当前生效值（含运行期 change_rules 变更）；未装配 →
        由 `config["ctb"]` 段归一（缺省对齐 ctb_rules 常量）。
        """
        if self._ctb is not None:
            return self._ctb._rule
        return resolve_rule_config(self._config.get("ctb"))

    def _action_recovery(self, actor: str, action: Optional[Mapping[str, Any]]) -> float:
        """解析该 action 的 recovery（CTB 行动代价的唯一注入点）。

        优先级（对齐 ctb_rules.recovery_for 的键词表）：
          1. action 显式 `recovery` / `行动恢复` 键；
          2. 技能 def 的 `recovery` 键（经 combo 引擎解析）；
          3. `CtbRuleConfig.default_recovery`（= DEFAULT_RECOVERY 100.0）。
        **语义（裁决 1）**：recovery 是该 action 的**总行动恢复值**，与 default
        之间是覆盖关系，不是附加。
        """
        rule: CtbRuleConfig = self._rule_config()
        action = dict(action or {})
        _sid = str(action.get("skill_id") or "")
        if _sid and action.get("type") == "skill":
            try:
                _sd = self.combo_engine().resolve_skill(_sid) or {}
                for _k in ("recovery", "行动恢复"):
                    if _sd.get(_k) is not None:
                        action.setdefault(_k, _sd.get(_k))
            except Exception:  # noqa: BLE001 - 解析失败回落默认，不阻断行动
                pass
        return float(recovery_for(action, rule))

    def set_effect_ids(self, side: str, effect_ids: Sequence[str]) -> "BattleEngine":
        """装配某侧效果 ID 列表（F-21 prepare_defense 的 effect_ids 输入；1b 效果系统）。"""
        if side not in BATTLE_SIDES:
            raise ValueError(f"未知战斗侧：{side}")
        self._effect_ids[side] = list(effect_ids)
        self._refresh_defenses()
        return self

    def start_turn(self) -> TurnReport:
        """推进行动条至下一个 ready 并交还控制权（CTB 重写：旧「回合开始」→ 行动条推进）。

        **语义变更（Wave A M1）**：旧语义 = 「每个回合开始时**全员**结算 DOT/控制」；
        CTB 语义 = 「每个单位**自己**行动开始时**仅该单位**结算 DOT/控制」。
        本方法不再递增行动数，也不再全员同步 tick——它只是「把时间轴推到下一个
        谁该动」的公开入口（保留方法名与签名，供旧调用方与测试过渡）。

        真正的按持有者 DOT/控制/即死结算在 `_start_actor_turn(actor)` 内（由
        `_resolve_ready_actor` 在每次 ACTOR_READY 时调用）。

        返回 ActionReport 语义的 TurnReport（兼容容器）。若战斗已终局或队列空 →
        返回当前状态的报告，不抛错（旧调用方 < 1 处，防误用崩溃）。
        """
        if self._finished:
            return self._turn_report()
        if self._ctb is None:
            raise BattleStateError("行动条未建立（请先 start()，CTB 无 PREP 外的手动推进）")
        self._resolve_ready_actor()
        return self._turn_report()

    def _resolve_ready_actor(self) -> Optional[Dict[str, Any]]:
        """把行动条推进到**下一个 ready**，并在玩家 ready 时暂停（CTB 主循环接口）。

        调度器行为：`advance_to_next_ready()` 每次消费一个 ready；NPC 会自动把完整
        行动链走完（`_auto_resolve_npc`），玩家 ready 则暂停。本方法循环推进，直到
        「玩家暂停（已消费其 ready，等待指令）/ 战斗结束 / 队列空」。

        幂等前置：若当前**已处于玩家暂停态**（等待输入），直接返回——不重复消费。

        每轮：同步双计数、消费事件（含 BATTLE_TIME_ADVANCE 换季）、同步死亡、
        在 ACTOR_TURN_START 位点为该 actor 结算自身 DOT/控制。

        返回：最后一次推进的关键事件 payload（空队列 / 已结束 / 已暂停 → None）。
        """
        if self._ctb is None or self._finished:
            return None
        # 已暂停等待玩家输入：ready 已被消费（action_seq 已含该拍），不重复推进
        if self._ctb.paused:
            self._player_ready_pending = True
            self._phase = PHASE_ACTOR_READY
            return None
        evt: Optional[Dict[str, Any]] = None
        for _ in range(_CTB_MAX_ADVANCE_PER_CALL):
            if self._finished or self._ctb.finished:
                break
            # ---- 暂停/交还判定（2026-09-10 修正）----
            # `paused` 语义 = 「玩家 ready 已被消费，控制权在玩家手上」。
            # CTB 不变式：**时间轴必须单调推进**——任何 ready 时刻早于玩家的 NPC
            # 都必须在玩家拿到控制权之前行动完。故暂停不能只看 `paused` 标记，
            # 必须比较「队首 ready 时刻」与「玩家下一次 ready 时刻」：
            #   - 队首是玩家，或队列里已无更早 ready 的 NPC → 可交还（break）
            #   - 队首是 ready 早于/等于玩家的 NPC → 必须先消费它（继续循环）
            _head = self._ctb.peek_next()
            if _head is None:
                break
            if self._ctb.paused:
                if bool(getattr(_head, "is_player", False)):
                    break
                # 队首是 NPC：仅当其 ready 不晚于玩家的下一次 ready 时才必须先走；
                # 否则玩家这一拍已就绪，应立即交还控制权（不得让玩家等 NPC）。
                _p_ready = self._next_player_ready()
                if _p_ready is not None and float(
                    getattr(_head, "next_ready", 0.0) or 0.0
                ) > float(_p_ready):
                    break
            elif self._ctb.should_pause_for_input():
                break
            # ACTOR_TURN_START 位点（M1）：在**消费该单位的 ready 之前**，先为其
            # 结算自身 DOT/控制/即死。对所有单位统一处理（玩家与 NPC 同通道）。
            _nxt = self._ctb.peek_next()
            if _nxt is not None:
                _aid = str(_nxt.actor_id)
                if not self._start_actor_turn(_aid):
                    # 该 actor 因 DOT/即死退场 → 重新取队首（其票据已被死亡同步作废）
                    self._sync_scheduler_deaths()
                    continue
                if self._finished:
                    break
            evt = self._ctb.advance_to_next_ready()
            self._sync_counts()
            self._consume_ctb_events()
            self._sync_scheduler_deaths()
            # 玩家 ready → 调度器暂停：仍需回到循环顶部复核「是否还有更早的 NPC」
            # （玩家 ready 消费后，时间轴可能已跳到玩家拍，NPC 若更早则其票据
            # 时间必然 < 玩家拍，会在下一轮被优先消费）
            if self._ctb.paused and not self._has_earlier_npc_ready():
                break
        # 调度器 finish（某方全灭）→ 引擎侧统一收尾
        if self._ctb.finished and not self._finished:
            self._resolve_battle_end(force=True)
        self._sync_counts()
        self._player_ready_pending = bool(self._ctb.paused)
        if self._player_ready_pending:
            # CTB：行动条就绪、等待玩家输入（替代回合制的「轮到我方行动」位点）
            self._phase = PHASE_ACTOR_READY
            self._state = STATE_ACT if self._state not in (
                STATE_WIN, STATE_LOSE, STATE_FLY) else self._state
        return evt

    def _next_player_ready(self) -> Optional[float]:
        """玩家单位的下一次 ready 时刻（调度器视角；未登记 → None）。

        CTB 交还判定用：只有当「队首 NPC 的 ready 时刻 ≤ 玩家 ready」时，才必须
        先让该 NPC 行动完；否则玩家这一刻已就绪，应立即交还控制权。
        """
        try:
            if self._ctb is None:
                return None
            for _vid in ("player",):
                _v = self._ctb.get_actor(_vid)
                if _v is not None and _v.alive:
                    return float(_v.next_ready)
            return None
        except Exception:  # pragma: no cover - 兜底不崩
            return None

    def _has_earlier_npc_ready(self) -> bool:
        """队列中是否存在「ready 时刻不晚于玩家」的存活 NPC（交还前置条件）。

        用于玩家 ready 消费后的复核：若仍有 NPC 的 ready 落在玩家这一刻之前/同刻，
        则时间轴尚未走到玩家拍，不得交还控制权（否则该 NPC 的这次行动被静默跳过）。
        """
        try:
            if self._ctb is None:
                return False
            _p = self._next_player_ready()
            if _p is None:
                return False
            _head = self._ctb.peek_next()
            if _head is None or bool(getattr(_head, "is_player", False)):
                return False
            return float(getattr(_head, "next_ready", 0.0) or 0.0) <= float(_p)
        except Exception:  # pragma: no cover - 兜底不崩
            return False

    def _sync_counts(self) -> None:
        """把调度器的 action_seq / battle_time 同步进快照（含 `turn` 兼容镜像）。

        CTB 双计数是快照的权威计量；`turn` 仅作镜像（R-A：世界层完整性校验需要）。
        """
        if self._ctb is None:
            return
        _aseq = int(self._ctb.action_seq)
        _btime = float(self._ctb.battle_time)
        self._snap["action_seq"] = _aseq
        self._snap["battle_time"] = round(_btime, 6)
        self._snap["turn"] = _aseq                       # 兼容镜像（不参与计算）
        self._snap["timestamps"] = dict(self._snap.get("timestamps") or {})
        self._snap["timestamps"]["updated_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _consume_ctb_events(self) -> None:
        """消费调度器事件缓冲 → 落 `_ctb_event_log`（本次推进的事件位点流水）。

        事件位点的**业务行为**由引擎在各挂载点显式执行（见各 `_on_*` 与
        `_start_actor_turn`）；本方法只做审计留痕 + BATTLE_TIME_ADVANCE 的换季。
        """
        if self._ctb is None:
            return
        for ev in self._ctb.drain_events():
            self._ctb_event_log.append(ev)
            if str(ev.get("event")) == CtbEvent.BATTLE_TIME_ADVANCE:
                self._on_battle_time_advance(ev)

    def _on_battle_time_advance(self, ev: Mapping[str, Any]) -> None:
        """BATTLE_TIME_ADVANCE 位点（M11）：全局战斗时间推进 → 换季边界结算。

        换季是**全局战斗时间效果**（季节属世界、不属任何 actor），故挂在时间推进
        位点而非某单位行动后。保持旧不变量：切换发生在「当前行动校验完成之后」
        （时间位点在 ACTOR_READY 之前派发），且 tick_season_boundary 内部幂等。
        """
        self._tick_season_boundary()
        self._phase = PHASE_TIME_ADVANCE

    def _start_actor_turn(self, actor: str) -> bool:
        """ACTOR_TURN_START 位点（M1）：该 actor 行动开始 —— 自身 DOT/控制/即死。

        等价旧 `start_turn` 的「①+②」但**只作用于该 actor**（映射规则：回合开始
        DOT → 目标自身 ACTOR_TURN_START）：
          - tick=turn_start 的 DOT：结算 → 递减 → 归零移除（R1/R2）；
          - control_state.turns 递减、归零清理（R3/R4）；
          - 即死判定（谁先到点谁先判，A1 直出终局）。
        返回 False = 该 actor 已死或战斗终局（调用方不应继续其行动）。
        """
        if self._finished or not self._alive(actor):
            return False
        self._phase = PHASE_TURN_START
        # 防御窗口收口：该 actor 再次行动 → 上一次的 guard 窗口到期（D2 同口径）
        self._guard_active[actor] = False
        # 功能三批2：turn_start 事件（按持有者，替代旧全员 turn_start）
        self._dispatch_event("turn_start", actor)

        c = self._combat(actor)
        rt = self._new_runtime()
        dots = c.get("dot_pool") or {}
        for dot_id in list(dots.keys()):
            dot = dots[dot_id]
            if isinstance(dot, dict) and dot.get("tick") == "turn_start":
                src = str(dot.get("source") or self._opposite(actor))
                self.resolve_damage(src, actor, int(dot.get("value", 0)),
                                    attack_type="status", snapshot=self._snap, runtime=rt)
                self._absorb_runtime(rt)
                self._death_check_side(actor, "turn_start_dot")
                rt = self._new_runtime()
                if int(dot.get("turns", 0)) > 0:
                    dot["turns"] = int(dot["turns"]) - 1
                if int(dot.get("turns", 0)) <= 0:
                    dots.pop(dot_id, None)
        # 控制结算：该 actor 行动开始按控制剩余次数递减（skip_turn 硬直）
        ctrl = c.get("control_state")
        if isinstance(ctrl, dict) and int(ctrl.get("turns", 0)) > 0:
            tn = int(ctrl.get("turns", 0)) - 1
            ctrl["turns"] = tn
            if tn <= 0:
                c.pop("control_state", None)

        # ② 即死判定（A1 直出）
        if self._dead("player") or self._dead("enemy"):
            self._absorb_runtime(self._new_runtime())
            self._sync_scheduler_deaths()
            self._resolve_battle_end(force=True)
            return False
        return True

    def _is_dummy_enemy_def(self) -> bool:
        """M12.5 木桩判定：enemy_def tier=training 或 type=dummy（怪物模块 §十五 15.1）。

        依据内容包敌人条目本身而非 battle_type（battle_type 默认 "dummy" 历史
        遗留——PvE 普通战斗也落该默认值，不可作判定依据）。优先读快照标记
        is_dummy_battle（start 时写入；from_snapshot 续战无需 enemy_def 透传）。
        """
        if self._snap.get("is_dummy_battle"):
            return True
        ed = getattr(self, "_enemy_def", None)
        if isinstance(ed, Mapping):
            return ed.get("tier") == "training" or ed.get("type") == "dummy"
        return False

    def action_order(self) -> Tuple[str, ...]:
        """【删除】纯回合制产物：一次性排出整回合固定出手序——CTB 无对应物。

        CTB 的行动顺序由每个单位独立累计的行动条动态决定（谁先满谁先动），
        不可能用静态 tuple 表达（Wave A M2 语义等价性论证）。按硬约束保留同名
        签名壳并抛 NotImplementedError，以暴露任何未迁移的误用调用点。

        替代：`next_action_owner()`（返回行动条上下一名 ready 单位）。
        """
        raise NotImplementedError(
            "action_order 已随 CTB 重写删除：行动顺序由行动条动态决定，"
            "请改用 next_action_owner() / engine.action_seq（Wave A M2）"
        )

    def next_action_owner(self) -> Optional[str]:
        """下一个可行动者（CTB 重写，M3）：行动条上下一名 ready 单位。

        等价旧语义「本回合内下一个还没行动的单位」→ CTB「行动条率先到达阈值的
        单位」。木桩敌人不入队（start 时即不 push_actor）→ 天然不出现在队列中，
        与旧口径「木桩永不出手」等价。队列空 / 已终局 → None。
        """
        if self._ctb is None or self._finished:
            return None
        view = self._ctb.peek_next()
        if view is None:
            return None
        return str(view.actor_id)

    def do_action(self, attacker: str, action_dict: Mapping[str, Any]) -> ActionOutcome:
        """行动入口（完整闭环）：命中→会心→格挡→双通道→总伤害→拦截链→扣血→
        死亡判定→状态 tick。

        attacker ∈ {player, enemy}；action_dict 支持：
          - {"type":"normal"|"attack", "mult":1.0, "attack_type":"slash"|"blunt"|...,
             "elem_mult":0.0, "skill_id":...}
          - {"type":"skill", "skill_id":"...", "mult":2.0, ...}
          - {"type":"guard"|"defense"}                防御指令 ×0.5（1a §1.8）
          - {"type":"flee"|"run"}                     逃跑（CTB：该 actor ready 时点即可）
          - {"type":"item", "item_id":"...", "actions":[...]}  道具（L0 动作）
          - segments: [{...}] 连段/多段逐段结算
        返回 ActionOutcome（含 rating/damage/battle_ended）。

        **CTB 语义**：本方法是「提交一次行动」的入口，不含任何时间推进——
        时间推进（下次 ready 重签）由 `_after_actor_action` 在行动收尾时驱动；
        **被拒行动（R-6）** 不会走到 `_after_actor_action`，故零时间成本。
        """
        if self._finished:
            raise BattleStateError(f"战斗已终局（{self._snap.get('status')}），无法再行动")
        if attacker not in BATTLE_SIDES:
            raise ValueError(f"未知行动侧：{attacker}")
        if self._state not in (STATE_ACT, STATE_RES):
            raise BattleStateError(f"行动仅允许在行动选择/结算中发起（当前 {self._state}）")
        if not self._alive(attacker):
            raise BattleStateError(f"{attacker} 已死亡/退场，不能行动")

        self._current_actor = attacker
        # CTB recovery 解析源：记下本次提交的原始 action dict（含 skill_id），
        # 供 `_after_actor_action` 计算该 action 的 recovery（唯一注入点）。
        self._last_action_dict = dict(action_dict)
        try:
            return self._do_action_inner(attacker, action_dict)
        finally:
            self._current_actor = None

    def _do_action_inner(self, attacker: str, action_dict: Mapping[str, Any]) -> ActionOutcome:
        # 功能三批2：action_start 事件（effects trigger=action_start；含普攻/技能/
        # 道具/防御/逃跑全动作类型——在动作分派前触发；无配置 → [] 零行为变化）
        self._dispatch_event("action_start", attacker)
        atype = str(action_dict.get("type") or "normal")
        atype = {"attack": "normal", "defense": "guard", "run": "flee"}.get(atype, atype)
        self._phase = PHASE_PLAYER_ACTION if attacker == "player" else PHASE_ENEMY_ACTION

        if atype == "flee":
            return self._flee_actor(attacker)
        if atype == "guard":
            return self._guard_actor(attacker)

        # M13 6c（细化_6c §2.2 EFF-5）：技能行动换季校验——非当季技能被拒
        # （R-6：零时间成本，复用 rejected 管道语义；普攻/防御全年可用 EFF-3 兜底）。
        _season_gate = self._check_season_action(attacker, dict(action_dict))
        if _season_gate is not None:
            return _season_gate

        # 控制状态裁决（1g2 §1.2：混乱=行动变随机普攻；skip_turn=跳过行动）
        ctrl = self._combat(attacker).get("control_state")
        if isinstance(ctrl, dict) and int(ctrl.get("turns", 0)) > 0:
            if float(ctrl.get("skip_turn", 0)) > 0:
                return self._skip_turn(attacker)
            action_dict = {"type": "normal", "controlled": ctrl.get("type", "混乱")}
            atype = "normal"

        if atype in ("normal", "skill"):
            return self._resolve_combo_action(attacker, dict(action_dict))
        if atype == "item":
            return self._resolve_item_action(attacker, dict(action_dict))
        raise ValueError(f"未知动作类型：{atype}（CTB 动作词汇）")

    # ------------------------- 行动实现 -------------------------

    def _guard_actor(self, attacker: str) -> ActionOutcome:
        """防御指令（1a §1.8 ×0.5）。

        CTB 重写（Wave A S3/工程补白 6）：防御窗口不再「回合结束清零」，而是
        **到该 actor 下次行动为止**（由下一次 `_start_actor_turn` 清位）——语义
        等价「守住自己这一拍，直到下一次轮到自己」。
        """
        self._to_state(STATE_RES, "guard")
        self._guard_active[attacker] = True
        target = self._opposite(attacker)
        seq = self._record_action(
            attacker, "guard", target,
            {"hit": True, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0},
            {"ch_phys": 0, "ch_elem": 0, "final": 0},
            self._phase,
        )
        tick_after_action(self._snap, self._new_runtime(), attacker)
        self._absorb_runtime(self._new_runtime())
        # 功能三批2：action_end（防御行动收尾）
        self._dispatch_event("action_end", attacker)
        self._after_actor_action(attacker)
        return ActionOutcome(True, seq, attacker, "guard", target, True, "low", False,
                             0, 0, int(self._combat(target).get("hp", 0)),
                             self._seal_side_effects(()),
                             "防御指令（受击 ×0.5，直到下次行动）")

    def _skip_turn(self, attacker: str) -> ActionOutcome:
        """被控制跳过行动（skip_turn 硬直，连段保留）。

        CTB 重写（M6）：该 actor 的本次 ready **被消费但不产出 action**，随后的
        行动条推进照常（`_after_actor_action` 重签其票据）——**时间必须继续走**，
        否则硬直会造成死锁。关键不变量：①连段保留（combo_state 不动）；②时间推进。
        """
        target = self._opposite(attacker)
        seq = self._record_action(
            attacker, "skip", target,
            {"hit": False, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0},
            {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase,
        )
        self._after_actor_action(attacker)
        return ActionOutcome(False, seq, attacker, "skip", target, False, "low", False,
                             0, 0, int(self._combat(target).get("hp", 0)),
                             self._seal_side_effects(({"type": "skip_turn", "actor": attacker},)),
                             "被控制，跳过本次行动")

    def _flee_actor(self, attacker: str) -> ActionOutcome:
        """逃跑（1g1b T6）：成功后连段清零、退出战斗。

        CTB 重写（Wave A §1.7 `_flee_actor`）：旧约束「仅回合边界」（T6）在 CTB
        下无意义 → 改为「该 actor 任意 ready 时点均可尝试逃跑」。

        成功率 = 敏捷比 agi/(agi+敌agi)（玩家属性定稿 L185；双方 agi 均 0 时按
        1.0 兜底），config.flee_chance 作附加修正系数；BOSS 禁逃可经
        config.battle_flee_blocked_on_boss；失败保留战斗与连段。
        """
        enemy = self._combat("enemy")
        blocked_on_boss = bool(self._config.get("battle_flee_blocked_on_boss", False)) and \
            bool(enemy.get("is_boss", False))
        target = self._opposite(attacker)
        if blocked_on_boss:
            seq = self._record_action(
                attacker, "flee", target,
                {"hit": False, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0},
                {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase,
            )
            return ActionOutcome(False, seq, attacker, "flee", target, False, "low", False,
                                 0, 0, int(self._combat(target).get("hp", 0)),
                                 ({"type": "flee_blocked", "reason": "boss"},), "BOSS 战禁止逃跑")
        # G2 定稿对照修复（玩家属性定稿 L185「敏捷 = 逃跑成功率 agi/(agi+敌agi)」）：
        # 原实现 config.flee_chance 默认 1.0 恒成功，未接敏捷公式。现在成功率 = 敏捷比
        # （双方 agi 均 0 时按 1.0 兜底），config.flee_chance 作附加修正系数（作者可调）。
        agi_self = float(self._combat(attacker).get("agi", 0))
        agi_opp = float(self._combat(target).get("agi", 0))
        base = 1.0 if (agi_self + agi_opp) <= 0 else agi_self / (agi_self + agi_opp)
        chance = max(0.0, min(1.0, base * float(self._config.get("flee_chance", 1.0))))
        ok = chance >= 1.0 or self._roll() <= chance
        # 定稿 action_record 语义：逃跑动作仍按段记录（1g1c TC-17）
        seq = self._record_action(
            attacker, "flee", target,
            {"hit": ok, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0},
            {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase,
        )
        if not ok:
            return ActionOutcome(False, seq, attacker, "flee", target, False, "low", False,
                                 0, 0, int(self._combat(target).get("hp", 0)),
                                 ({"type": "flee_failed"},), "逃跑失败，战斗继续（连段保留）")
        self._snap.get("result", {})["mark_escape"] = True
        outcome = self._settle(STATUS_ESCAPE, "flee")
        return ActionOutcome(True, seq, attacker, "flee", target, True, "low", False,
                             0, 0, int(self._combat(target).get("hp", 0)),
                             ({"type": "flee"},), "逃跑成功，退出战斗",
                             battle_ended=True, status=outcome.status)

    def _resolve_item_action(self, attacker: str, action: Dict[str, Any]) -> ActionOutcome:
        """道具（action_record action=item；道具不打断连段）：
        经 L0 执行器跑道具 actions（heal/status_apply 等），跳过伤害链。

        CTB（R-6）：道具行动**消耗一次行动**（走 `_after_actor_action` 推进时间）；
        旧注释「不耗回合」在 CTB 下等价于「占用本次 ready」——与技能被拒（零时间
        成本）不同：道具是成功行动，故按其 recovery 正常推进行动条。
        """
        self._to_state(STATE_RES, "item")
        target = self._opposite(attacker)
        ctx = DamageCtx(
            raw_damage=0, attack_type="item", attacker=attacker, target=target,
            snapshot=self._snap, variables=self._base_variables(attacker, target),
        )
        rt = self._new_runtime()
        effects: List[Mapping[str, Any]] = []
        for a in action.get("actions") or []:
            res = execute_action(a, ctx, rt)
            effects.extend(res.side_effects)
        self._absorb_runtime(rt)
        seq = self._record_action(
            attacker, "item", target,
            {"hit": True, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0},
            {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase,
        )
        tick_after_action(self._snap, rt, attacker)
        # 功能三批2：action_end（道具行动收尾）
        self._dispatch_event("action_end", attacker)
        # 方位 v0.6（§四 T8：action_end → air_policy → next actor）：道具行动（含
        # 即时调合接线层 auto_use 注入的 action_category=alchemy + air_policy=land）
        # 按行动定义 air_policy 结算——land → 空中落地；缺省保持（接线层显式传参）
        _land = self._settle_air_policy(attacker, action.get("air_policy"))
        if _land is not None:
            effects.append(_land)
        self._after_actor_action(attacker)
        return ActionOutcome(True, seq, attacker, "item", target, True, "low", False,
                             0, 0, int(self._combat(target).get("hp", 0)), tuple(effects),
                             "道具使用成功")

    def _resolve_combo_action(self, attacker: str, action: Dict[str, Any]) -> ActionOutcome:
        """连段性行动（1c1a/b/c + 1c2）：combo 引擎判定 → 被拒短路 / 派生表单 → 伤害结算。

        M1-批3 主 agent 收口：combo.py 引擎已实现但本 battle 接线缺失（子代理撞迭代上限）。
        - ⑥ 被拒（MP/冷却/条件不足）：不改连段、不消耗行动、可反复尝试（1c1c TC-DEF-04 /
          1c2 §2.4 / 1c3 TC-30）——状态保持 ACT（未推 RES），调用方可直接再次 do_action。
        - 派生/自动替换：ComboActionResult.form_id 覆写 action.skill_id 后走既有伤害通道。
        """
        target = self._opposite(attacker)
        ca = dict(action)
        if not ca.get("skill_id"):
            ca["skill_id"] = ca.get("id", "")
        sd = self.combo_engine().resolve_skill(str(ca.get("skill_id") or "")) or {}
        ca.setdefault("tag", str(sd.get("tag", "")))           # D4：skill def 合并 tag
        ca.setdefault("armor", bool(sd.get("armor", False)))   # D4：skill def armor
        if "effects" not in ca:
            ca["effects"] = list(sd.get("effects") or [])      # D4：skill def effects（标准技能路径也能执行印记/打断等）
        # 方位 v0.6（附录 A Step 2/Step 3）：skill def F08/F09/F10 合并——position_rule
        # （部位命中资格，Step 2 part resolve 消费）、break_power（破坏力固有值）、
        # air_policy（行动后高度策略，Step 3 行动收尾消费）随技能 def 注入
        ca.setdefault("position_rule", sd.get("position_rule"))
        ca.setdefault("break_power", float(sd.get("break_power", 0) or 0))
        ca.setdefault("air_policy", sd.get("air_policy"))
        # 跃空风险闭环（批③）：air_drop=对空击落档（knockdown=击中空中玩家即击落）
        ca.setdefault("air_drop", sd.get("air_drop"))

        _action_had_mult = "mult" in ca  # action 原样是否显式 mult（折算判据）
        ca.setdefault("mult", float(ca.get("mult", 1.0)))
        # M13 批21 dsh A1 P0-2：技能 power(F04) 折算战斗倍率——sd.power/100
        # （普攻 100 → 1.0×；强力斩击 150 → 1.5×）。仅当 mult 未被 action
        # 显式给定且当前 = 缺省 1.0 时折算（组合行/链步骤显式 mult 优先）。
        # P2-10 衍生修复（qa_report_20260907）：power 显式为 0 的功能技（utility/
        # status/transform：脊格/专精/填弹/放账等）mult 须 =0（零伤害只走 effects）——
        # 原 `> 0` 条件使 power=0 不折算 → mult 保持 1.0 → 功能技当普攻打人。
        # 语义：power 键存在（显式 0 也是声明「无伤害」）→ mult=power/100（0.0）；
        # power 键缺失（普通攻击/buff 行无伤害语义）→ 保持缺省 1.0 不变。
        # P2-10 衍生修复（qa_report_20260907）：power 显式为 0 的功能技（utility/
        # status/transform：脊格/专精/填弹/放账等）mult 须 =0（零伤害只走 effects）——
        # 原 `> 0` 条件使 power=0 不折算 → mult 保持 1.0 → 功能技当普攻打人。
        # 语义：power 键存在（显式 0 也是声明「无伤害」）→ mult=power/100（0.0）；
        # power 键缺失（普通攻击/buff 行无伤害语义）→ 保持缺省 1.0 不变。
        _sd_power = float(sd.get("power", 0) or 0)
        if "power" in sd and not _action_had_mult and ca.get("mult", 1.0) == 1.0:
            ca["mult"] = _sd_power / 100.0
        # M13 批17 路17C：技能冷却接线（14B 缺口②）——技能 def cooldown 字段。
        # 冷却表 _snap["skill_cooldowns"] = {side: {skill_id: remaining}}；
        # 施放成功设 cooldown、end_turn 递减、此处注入 action.cooldown_remaining
        # 供 combo.should_reject 拒绝（冷却中被拒不消耗行动）。
        _cd_map = self._snap.get("skill_cooldowns")
        _cd_side = _cd_map.get(attacker) if isinstance(_cd_map, dict) else None
        _cd_left = _cd_side.get(str(ca.get("skill_id") or ""), 0) \
            if isinstance(_cd_side, dict) else 0
        if _cd_left > 0:
            ca["cooldown_remaining"] = int(_cd_left)
        else:
            ca.pop("cooldown_remaining", None)
        # M13 批14 路14B：技能 def hits 多段展开（blade_dance hits=3 → 3 段伤害）。
        # 仅显式 hits>1 时展开（缺省 1 段不包 segments，保持既有单段路径零变化）。
        _hits = int(sd.get("hits", 1) or 1)
        if _hits > 1 and "segments" not in ca:
            ca["segments"] = [{"hit": True, "mult": 1.0} for _ in range(_hits)]

        def _marks_lookup(kind: str, which: str, rule: Mapping[str, Any], mark_id: Optional[str] = None) -> bool:
            # D1 定稿对照修复：combo 印记条件子句全量转接 MarksManager.evaluate（1d §3.1 唯一正确实现）
            side = attacker if which == "self" else target
            res = self.marks_manager().evaluate(kind, side, dict(rule), mark_id)
            return res

        # 方位战斗系统 v0.6（附录 A Step 1 / §四 height check）：怪物行动 position_rule
        # 命中资格检查——未命中不拒施放（门禁/消耗已过、行动槽已占），整条行动打空：
        # 无伤害/无破坏力/无效果（effects 消费点在其后），文案「未命中」由渲染层模板出。
        # 玩家技能 position_rule 的消费点是部位命中资格（Step 2 part resolve），本步不检查。
        if attacker == "enemy":
            _pr = ca.get("position_rule")
            if isinstance(_pr, Mapping) and _pr:
                from qbot_rpg.core.position import position_of, rule_permits  # noqa: PLC0415

                _ps, _ph = position_of(self._snap, "player")
                if not rule_permits(_pr, _ps, _ph):
                    # 2026-09-09：未命中=闪避成功（防御方空中姿态 on_dodge_effects）
                    self._trigger_on_dodge(target, attacker)
                    # 闪反成功派生（2026-09-09 用户拍板：可闪反行动+玩家闪反姿态
                    # → 免伤（天然）+ 自动反击）
                    _st = self._player_stance()
                    _p_ca = ca.get("skill_id")
                    _pdef = self.combo_engine().resolve_skill(_p_ca) if _p_ca else None
                    _dodgeable = "可闪反" in tuple(str(x) for x in ((_pdef or {}).get("tags") or ()))
                    _dodge_ct = None
                    if _st and _st[0] == "dodge" and _dodgeable:
                        # 反击返还（怪猎采纳 C11，批⑤）：闪反成功 → 玩家返还（同防反
                        # 口径——须在 _run_counter 之前，先返还再让内部收尾推进时间轴）
                        self._hasten_player_after_counter()
                        _cd = self._run_counter(_st[1])
                        _dodge_ct = {"type": "dodge_counter", "target": "enemy",
                                     "attacker": "player", "skill_id": _st[1],
                                     "damage": _cd}
                    return self._position_miss_outcome(attacker, ca, target, _ps, _ph,
                                                       extra_effect=_dodge_ct)

        result = self.combo_engine().apply_action(attacker, ca, self._snap, self._armor_active,
                                                  marks_lookup=_marks_lookup)
        # 2026-09-07：派生审计透出——apply_action 的 form_id（派生/自动替换实际
        # 技能）写 ca.combo_result → outcome.combo_result（消息层派生技名用）。
        if result.form_id and result.form_id != ca.get("skill_id") and not ca.get("combo_result"):
            ca["combo_result"] = {"form_id": str(result.form_id), "derived": bool(result.derivation)}
        if result.rejected:
            # R-6（裁决 2）：被拒 = 零时间成本、直接重试。**不调用 _after_actor_action**
            # （不推进行动条、不重签票据、不派发链路事件）；仅写审计流水。
            # 旧的 `_turn_acted[attacker]=False` 回滚在 CTB 下不再需要——时间推进由
            # _after_actor_action 单点驱动，被拒路径本就不经过它。
            seq = self._record_action(
                attacker, str(action.get("type", "skill")), target,
                {"hit": False, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0,
                 "combo_rejected": True, "combo_reason": result.reject_reason},
                {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase)
            msg = result.messages[0] if result.messages else f"指令被拒（{result.reject_reason}）"
            return ActionOutcome(False, seq, attacker, str(action.get("type", "skill")), target,
                                 False, "low", False, 0, 0, int(self._combat(target).get("hp", 0)),
                                 (), msg)
        if result.form_id and result.form_id != ca.get("skill_id"):
            action = dict(action)
            action["skill_id"] = result.form_id
            action["_derived"] = bool(result.derivation)
            if result.step is not None:
                step_tag = getattr(result.step, "tag", None)
                if step_tag:
                    action.setdefault("tag", step_tag)
            # M13 批17 路17C：同步 ca（segments/energy 等扩展随派生 skill_id 走）
            ca["skill_id"] = result.form_id
            ca["_derived"] = bool(result.derivation)
            # 【G1 派生结算修复（veinborn 破脉核派生缺口）】form_id 替换发生后，
            # 伤害倍率/effects/tag/armor/hits 重新按派生技 def 解析——原实现仅覆写
            # skill_id，mult 与 effects 仍停留在源技能（rb_core_strike power60→
            # 0.6×、mark_add 源印记重复执行），派生技 vb_core_breaker power200→
            # 2.0×、core_broken 印记完全不生效。显式给定值保持优先（与上方 power
            # 折算/effects 合并同一口径）：仅当 action 原样未显式给出时才跟随派生技。
            _fsd = self.combo_engine().resolve_skill(str(result.form_id or "")) or {}
            _f_power = float(_fsd.get("power", 0) or 0)
            if _f_power > 0 and not _action_had_mult:
                ca["mult"] = _f_power / 100.0
            if "effects" not in action:
                ca["effects"] = list(_fsd.get("effects") or [])
            if not action.get("tag"):
                ca["tag"] = str(_fsd.get("tag", "") or "")
            if not action.get("armor"):
                ca["armor"] = bool(_fsd.get("armor", False))
            _f_hits = int(_fsd.get("hits", 1) or 1)
            if _f_hits > 1 and "segments" not in ca:
                ca["segments"] = [{"hit": True, "mult": 1.0} for _ in range(_f_hits)]
            # 方位 v0.6（附录 A Step 3）：air_policy 随派生技 def 解析（同 effects/tag/
            # armor 口径——派生=实际施放技能；仅当行动原样未显式给出时跟随派生技）
            if not action.get("air_policy"):
                ca["air_policy"] = _fsd.get("air_policy")
            # 跃空风险闭环（批③）：air_drop 同口径随派生技 def 解析
            if not action.get("air_drop"):
                ca["air_drop"] = _fsd.get("air_drop")

        # 防反/闪反姿态标记（用户拍板标签制）：玩家施放技能若带 counter_type/
        # counter_skill（守势=parry/回环+腾空=dodge）→ 记入 snap.counter_stance。
        # 窗口=行动时间口径（增补 v1 §一，2026-09-11；替换原 R10 计数口径）：
        # 记「写入时刻 + 时长」——消费侧 `_player_stance` 按 battle_time 判窗口，
        # 到期自然结束；时长取技能 def `action_time`（缺省 → 规则 default_action_time）。
        if attacker == "player":
            _sid_now = str(ca.get("skill_id") or "")
            _sd_now = self.combo_engine().resolve_skill(_sid_now) or {}
            _ct_now = str(_sd_now.get("counter_type") or "")
            _cs_now = str(_sd_now.get("counter_skill") or "")
            if _ct_now in ("parry", "dodge") and _cs_now:
                _at_raw = _sd_now.get("action_time")
                if (
                    isinstance(_at_raw, (int, float))
                    and not isinstance(_at_raw, bool)
                    and float(_at_raw) > 0
                ):
                    _at = float(_at_raw)
                else:
                    _at = float(self._rule_config().default_action_time)
                self._snap["counter_stance"] = {
                    "type": _ct_now, "skill": _cs_now,
                    "cast_time": float(self.battle_time), "action_time": _at}

        # ---- M13 批15 路15C：组合技能战斗接线（细化_6c §三 F-C1/F-C2）----
        # 技能 def combo_table 段 → 施放时 F-C1 触发判定（gate_combination：
        # 常规门禁由上方管道承载 → 总量门 → 多重集匹配）。命中组合行 → 锁定
        # 行为随组合变化（kind/power/element/hits/effects）+ F-C2 双耗结算
        # （MP+能量按行池分布扣减，CM-2 先匹配后消耗）；未命中 → 回退常规
        # 技能路径（energy_cost/gain 已在上方照常，被拒不消耗行动语义不适用——
        # 无组合表 = 常规技能 B-3）。审计落 combo_result（战报/测试可观察）。
        # 注意：组合 gate 在 MP/energy 扣费之前（F-C2 双耗由 settle_combo 完成，
        # 命中标记 _combo_settled 跳过下方常规扣费防重复；被拒不扣）。
        _combo = self._resolve_combo_table_gate(attacker, ca, sd, target)
        if _combo is not None:
            return _combo

        # ---- M13 6c 批12 收口：技能 energy_cost 门禁 + energy_gain 结算 ----
        # 技能 def 的 energy_cost（施放前检查：不足 → 被拒不消耗行动，复用 rejected
        # 语义——返回被拒 outcome 不继续）+ energy_gain（成功结算后增加封顶）。
        # 组合已结算（_combo_settled）→ 跳过（settle_combo 已双耗，防重复）。
        # 顺序：energy 门禁在 MP 扣费之前（被拒不扣任何消耗，批17 收口）。
        if not ca.get("_combo_settled"):
            _energy_gate = self._apply_skill_energy(attacker, ca, sd, target)
            if _energy_gate is not None:
                # R-6（裁决 2）：被拒 = 零时间成本、直接重试——不推进行动条
                # （不调用 _after_actor_action），拒绝原因随 outcome 上报。
                return _energy_gate

        # ---- G2（2026-09-02）：consume_marks 门禁 + 扣除（细化_1d §4.2 / S-01）----
        # 施放前检查（不足 → 被拒不消耗行动，零副作用）；检查通过后即扣。
        # 顺序：energy 之后、MP 扣费之前（与 energy_cost 同语义，被拒不扣任何消耗）。
        # 派生路径：ca.skill_id 已同步为派生技（G1），此处按最终 skill_id 解析 def，
        # 取派生技的 consume_marks（若 action 显式带 consume_marks 则优先）。
        if not ca.get("_combo_settled"):
            # 按最终 skill_id 解析 def（派生路径 ca.skill_id 已是派生技 → 取派生技
            # consume_marks；非派生 = 源技能，解析结果同 sd 零变化）
            _final_sid = str(ca.get("skill_id") or "")
            _consume_sd = sd
            if _final_sid:
                _cd_def = self.combo_engine().resolve_skill(_final_sid) or {}
                if isinstance(_cd_def, Mapping) and _cd_def:
                    _consume_sd = _cd_def
            _consume_gate = self._apply_consume_marks_gate(attacker, ca, _consume_sd, target)
            if _consume_gate is not None:
                # R-6：同 energy gate——被拒零时间成本、直接重试
                return _consume_gate

        # ---- M13 6a 路3C：技能 MP 消耗扣费（1a §2.2 mp_cost 语义；被拒不扣）----
        # should_reject 已做 MP 门槛检查（enforce_mp 开）；成功施放后实际扣费。
        # mp_cost 优先 action 显式（skill_mp_cost/mp_cost），缺失回退技能 def。
        _mp_cost = int(ca.get(
            "skill_mp_cost", ca.get(
                "mp_cost", sd.get("mp_cost", 0))) or 0)
        if _mp_cost > 0 and not ca.get("_combo_settled"):
            _c = self._combat(attacker)
            _mp = int(_c.get("mp", 0) or 0)
            if _mp >= _mp_cost:
                _c["mp"] = _mp - _mp_cost

        # ---- M13 批17 路17C：技能冷却起算（技能 def cooldown > 0）----
        # 成功施放（未拒绝）→ 冷却表写入；end_turn tick 递减（_tick_skill_cooldowns）。
        # 语义：cooldown=N → 施放后 N 次行动不可用（含下次行动）——存储 N+1，
        # end_turn 逐行动递减（施放当次行动不减，下次行动施放检查仍 = N 拦）。
        _cd = int(sd.get("cooldown", 0) or 0)
        if _cd > 0:
            _cdm = self._snap.setdefault("skill_cooldowns", {})
            if not isinstance(_cdm, dict):
                _cdm = {}
                self._snap["skill_cooldowns"] = _cdm
            _cds = _cdm.setdefault(attacker, {})
            if not isinstance(_cds, dict):
                _cds = {}
                _cdm[attacker] = _cds
            _sid = str(ca.get("skill_id") or "")
            if _sid:
                _cds[_sid] = max(int(_cds.get(_sid, 0) or 0), _cd + 1)

        # ---- M13 批15 路15A：transform 触发技（transform_skill）战斗接线 ----
        # 细化_6b §2.1 F1：触发技（如狂暴/rage_burst）成功结算后触发变换——
        # 形态切换 + 技能位重排 + state_policy（清连段等），不额外消耗行动。
        # 触发条件 C1~C4 经 transform.can_transform 判定（C1 形态激活期互斥 /
        # C2 资源 / C3 冷却 / C4 被控）；触发技效果本体走上方既有效果通道
        # （TRF-1 效果先结算），此处仅做变换挂接。job/transform 配置经
        # self._job_transform_segment() 惰性解析（无配置 → 零操作降级）。
        # 拒绝路径：不改 transform_state、不消耗额外行动（同 combo rejected 语义）。
        if not ca.get("_derived"):
            ts = self._snap.get("transform_state")
            if isinstance(ts, dict) and ts.get("form") is None:
                tseg = self._job_transform_segment()
                if tseg and str(tseg.get("transform_skill") or "") == str(ca.get("skill_id") or ""):
                    from qbot_rpg.core.transform import (  # noqa: PLC0415
                        TRANSFORM_STATE_KEY,
                        trigger_transform,
                    )

                    tctx = self._transform_ctx(attacker, ca, sd)
                    tr = trigger_transform(tctx, tseg)
                    if tr.get("ok"):
                        self._snap["transform_state"] = tr["transform_state"]
                        # 状态/印记/连段侧真实生效（state_policy 清连段写快照）
                        self._absorb_runtime(self._new_runtime())
                        self._transform_events = list(tr.get("side_effects") or ())
                        ca.setdefault("transform_triggered", True)
                        ca.setdefault("transform_form", str(tr["transform_state"].get("form") or ""))
                    else:
                        # 变换被拒（C1 形态激活互斥 / C3 冷却中 / C2 资源不足 /
                        # C4 被控）：拒绝不消耗行动、不改形态——触发技效果已在上方
                        # 通道结算，此处登记拒绝事件（战报/测试可观察）
                        self._transform_events = [
                            {"type": "transform_rejected", "reason": str(tr.get("reason") or ""),
                             "guard": str(tr.get("guard") or "")}
                        ]
                    # 拒绝（C1~C4/资源不足）→ 变换不触发：不消耗行动、不改形态，
                    # 触发技本身仍按普通技能结算（技能效果已在上方通道结算）
        # ---- M13 批15 路15A：revert_form 技能主动还原（D-05 即时，不判 remaining）----
        # 技能带 revert_form=true 且当前形态激活 → 施放即还原（还原钩子经
        # _apply_transform_revert(REVERT_FORM) 执行 state_policy + 冷却起算）
        if bool(sd.get("revert_form", False)):
            from qbot_rpg.core.transform_revert import REVERT_FORM  # noqa: PLC0415

            self._apply_transform_revert(REVERT_FORM)

        # ---- P1-3/P1-4（dsh 批3）：技能 effects 消费 + 打断/霸体闭环 ----
        # 1c2 §1.3 字段 24「effects 归口效果系统；interrupt 唯一实现走 effects.json」：
        # 印记施加/消除、打断等 L0 动作经 execute_action 真实进战斗（原仅道具路径可达）。
        tag = str(ca.get("tag") or "")
        eff_list = ca.get("effects") or []
        armor_flag = bool(ca.get("armor", False))
        if tag == "interrupt" or any(
            (e or {}).get("type") == "interrupt" for e in eff_list if isinstance(e, dict)
        ):
            # P1-4：打断技攻击窗口三条件（1c2 §2.2）——目标连段清零
            self.combo_engine().apply_interrupt(attacker, target, self._snap, self._armor_active)
            # M2-C1（contract §六）：玩家 interrupt 命中怪物 → 套完结（在途链/蓄力清空，
            # 下次行动随机流程；怪物连招走 ai_state，combo 引擎对怪物恒 no_active，
            # 故独立评估 _interrupt_enemy_ai，免疫/霸体检查在内部）
            if target == "enemy":
                self._interrupt_enemy_ai()
        if result.armor or armor_flag:
            self._armor_active[attacker] = True        # 霸体：本行动阶段期间免疫打断（1c2 §2.2）
        rt = self._new_runtime()
        hit_effects: List[Mapping[str, Any]] = []
        if eff_list:
            ctx = DamageCtx(
                raw_damage=0, attack_type="skill", attacker=attacker, target=target,
                snapshot=self._snap, variables=self._base_variables(attacker, target),
            )
            for eff_raw in eff_list:
                if isinstance(eff_raw, dict):
            
                    hit_effects.extend(execute_action(eff_raw, ctx, rt).side_effects)
            self._absorb_runtime(rt)
        # 霸体窗口=行动阶段结束（D2 修复：原在技能结算内清位→同一次行动敌后手打断不免疫，
        # 1c2 §2.2「使用期间」应为整个行动阶段；清位移至 _after_actor_action）
        # M13 批17 路17C：伤害结算传 ca（含 skill def 合并 + segments 多段展开 +
        # 派生 skill_id 同步）——原 action 缺这些扩展（hits=3 只出 1 段问题根因）。
        out = self._resolve_damage_action(attacker, ca)
        # 2026-09-07 探针 #5：transform 触发技/revert 技施放成功（power 0
        # utility）但吃命中 roll miss → 渲染成「未命中」误导。功能成功事件
        # 注入 message（渲染层 message 优先直出）。
        if not out.message:
            _tf = self._transform_events or []
            _tf_types = {str(ev.get("type") or "") for ev in _tf}
            if "transform_committed" in _tf_types or "transform_reverted" in _tf_types:
                _msg = "形态切换完成"
                if ca.get("transform_triggered"):
                    _msg = f"形态切换：进入{ca.get('transform_form') or ''}形态"
                # dataclasses.replace：字段整包复制——新增字段自动随行，勿再手抄字段
                # （批④ 背击实证：手抄回包漏抄新字段致旗标丢失）
                out = replace(out, hit=True, raw_damage=0, final_damage=0, message=_msg)
        # M13 批17 路17C：组合审计透出（ca 侧 combo_result → outcome.combo_result）
        _cr = ca.get("combo_result")
        if isinstance(_cr, dict):
            out = replace(out, combo_result=_cr)
        if hit_effects:
            out = replace(
                out, side_effects=tuple(hit_effects) + tuple(out.side_effects or ()))
        return out

    def _face_enemy(self, pre_side: Optional[str] = None) -> Optional[Mapping[str, Any]]:
        """怪转回面向（**转向事件化 + 行动条成本**；背击窗口时序修订，2026-09-11 批④）。

        v1 §三 1v1 落地切片（原「玩家行动**前**」时序在批④ 修订为「行动**结算后**」——
        否则背击永远无成立时机，见 v1 变更记录 v1.3）：

        - 判定基准 = **行动前捕获的侧位** `pre_side`（缺省读当前侧位——兼容直调）；
          目标未变（行动前已在正面）/ 快照缺段 / 终局 → **不转向、零消耗**，返回 None；
        - 玩家 side ∈ {back/left/right} → 本次行动已在侧位/背后**结算完毕**（背面攻击
          已吃背击加成）→ 怪转身：玩家 side 归位 front + **转向成本**（`ctb.turn_cost`，
          行动条；隐性口径玩家不可见）追加到怪的下一次 ready（`CTBScheduler.delay_actor`）
          ——转向是可读的节奏事件（渲染层出 `battle_enemy_turned` 行）。
        - 重定位类行动（行动前=front，行动把 side 移到 back/left/right）**不触发**转向
          （捕获方位在移动前 = front）；被拒行动（R-6 零成本）调用方不调本函数。
        - 高度不动（腾空空中行动不受影响）；完整仇恨值（来源/衰减/远程系数）依赖
          多目标选择，属组队里程碑前置，见增补 v1 §三.5。

        :param pre_side: 行动前捕获的玩家侧位（None → 读当前快照侧位）
        :return: 转向事件 dict（无转向 → None）
        """
        try:
            if self._finished:
                return None
            _cp = self._snap.get("combat_position")
            if not isinstance(_cp, dict):
                return None
            _pe = _cp.get("player")
            if not isinstance(_pe, dict):
                return None
            _pre = pre_side if isinstance(pre_side, str) and pre_side else str(
                _pe.get("side") or "front")
            if _pre == "front":
                return None
            _pe["side"] = "front"
            _cost = 0.0
            try:
                _cost = float(self._rule_config().turn_cost)
            except Exception:  # noqa: BLE001 - 配置解析失败按零成本（不阻断行动）
                _cost = 0.0
            if _cost > 0 and self._ctb is not None:
                self._ctb.delay_actor("enemy", _cost)
            return {"type": "enemy_turned", "actor": "enemy"}
        except Exception:  # noqa: BLE001 - 归位/计费失败不阻断行动
            return None

    # -------------------- 反击返还 + 会心来源（怪猎采纳 C11/E19/E20，批⑤） --------------------

    def _hasten_player_after_counter(self) -> None:
        """防反/闪反成功 → 玩家行动条返还（怪猎采纳 C11；`ctb.counter_refund`）。

        语义：`CTBScheduler.hasten_actor("player", refund)`——玩家下一次 ready 减
        返还值（下限钳到当前时刻=最多「立即行动」，不倒流）；失败路径不调用
        （落空不双罚：只付行动条、不返还资源）。**隐性口径（玩家不可见）**——
        加速本身即反馈；调度器未装配 / 配置非法 → 静默跳过（不阻断战斗结算）。
        """
        try:
            if self._ctb is None:
                return
            _refund = float(getattr(self._rule_config(), "counter_refund", 0.0) or 0.0)
            if _refund > 0:
                self._ctb.hasten_actor("player", _refund)
        except Exception:  # noqa: BLE001 - 返还失败不阻断行动
            return

    def _crit_bonus_of(self, attacker: str, target: str) -> float:
        """攻击方会心加成聚合（小数口径；怪猎采纳 E19/E20，批⑤）。

        - 基础：combatant `crit_bonus`（**百分数**；可为负 → 负会心/赌狗流派；
          缺省 0）；
        - 条件：combatant `crit_bonus_cond` 映射 {back/low_hp/first: 百分数}——
            back：攻击方位于目标**背面**（方位联动；口径同 B5 背击）；
            low_hp：攻击方 HP ≤ `crit_cond_low_hp` 阈值（缺省 0.3）；
            first：本场首次**命中**（命中评估即消耗，写入快照 first_strike_used）；
          未知条件键忽略（只建议不限制）。
        本函数仅在「命中成立」的会心求值点被调用 → 调用即视为本次命中消费首击。
        异常兜底 0.0（绝不阻断伤害结算）。
        """
        try:
            ac = self._combat(attacker)
            total = 0.0
            _base = ac.get("crit_bonus", 0)
            if isinstance(_base, (int, float)) and not isinstance(_base, bool):
                total += float(_base) / 100.0
            cond = ac.get("crit_bonus_cond")
            if isinstance(cond, Mapping):
                _used = bool(self._snap.get("first_strike_used", {}).get(attacker))
                for key, val in cond.items():
                    if not isinstance(val, (int, float)) or isinstance(val, bool):
                        continue
                    if key == "back":
                        from qbot_rpg.core.position import position_of  # noqa: PLC0415

                        if (attacker == "player" and target == "enemy"
                                and position_of(self._snap, "player")[0] == "back"):
                            total += float(val) / 100.0
                    elif key == "low_hp":
                        _mx = float(ac.get("max_hp", 0) or 0)
                        _hp = float(ac.get("hp", 0) or 0)
                        try:
                            _thr = float(self._config.get("crit_cond_low_hp", 0.3) or 0.0)
                        except (TypeError, ValueError):
                            _thr = 0.0
                        if _mx > 0 and _thr > 0 and (_hp / _mx) <= _thr:
                            total += float(val) / 100.0
                    elif key == "first":
                        if not _used:
                            total += float(val) / 100.0
            # 首击消费置位（本函数=命中评估点；置位后本场后续命中不再吃首击）
            self._snap.setdefault("first_strike_used", {})[attacker] = True
            return total
        except Exception:  # noqa: BLE001 - 兜底 0（不阻断伤害结算）
            return 0.0

    # ------------------------- 跃空窗口（增补 v1 §四，2026-09-11） -------------------------

    def _air_stance_instances(self, side: str = "player") -> List[Mapping[str, Any]]:
        """该侧空中姿态状态实例列表（sw_vault_air / vs_air_window / va_air_window）。

        兼容实例的 dict / 对象两种形态（对齐旧 `_settle_air_landing` 扫描口径）。
        """
        st = self._snap.get("status_state")
        insts = st.get(side) if isinstance(st, Mapping) else None
        if not isinstance(insts, list):
            return []
        out: List[Mapping[str, Any]] = []
        for inst in insts:
            if isinstance(inst, Mapping):
                sid = str(inst.get("status_id") or inst.get("id") or "")
            else:
                sid = str(getattr(inst, "status_id", None)
                          or getattr(inst, "id", "") or "")
            if sid in _AIR_STATUS_IDS:
                out.append(inst)
        return out

    def _clear_air_stances(self, side: str = "player") -> None:
        """清理该侧空中姿态实例（落地统一清理点：到期 / air_policy=land / 击落）。

        原地重写（保持列表对象同一性——陈旧运行时引用不回灌脏数据）。
        """
        st = self._snap.get("status_state")
        if not isinstance(st, dict):
            return
        insts = st.get(side)
        if not isinstance(insts, list):
            return
        st[side][:] = [
            inst for inst in insts
            if not (isinstance(inst, Mapping)
                    and str(inst.get("status_id") or inst.get("id") or "") in _AIR_STATUS_IDS)
        ]

    def _take_pending_air_events(self) -> List[Mapping[str, Any]]:
        """取走引擎级待发事件（跃空自动落地等；取走即清，防重复播报）。"""
        _evs = list(getattr(self, "_pending_air_events", None) or [])
        self._pending_air_events = []
        return _evs

    def _seal_side_effects(
        self, seq: Sequence[Mapping[str, Any]]
    ) -> Tuple[Mapping[str, Any], ...]:
        """收口 side_effects：既有序列 + 引擎级待发事件（跃空自动落地等）。"""
        return tuple(seq or ()) + tuple(self._take_pending_air_events())

    def _update_air_window(self, actor: str) -> None:
        """跃空窗口维护：初始化 + 使用攻击/技能的延长（增补 v1 §四）。

        - 窗口载体 = 空中姿态状态实例的 `air_expire_at`（行动条时刻；**隐性口径**，
          玩家不可见）；窗口时长取 `ctb.air_time`（缺省 2000，可调）。
        - 玩家在空中且持有姿态：实例缺窗口起点 → 初始化为「本拍时刻 + air_time」
          （本拍时刻 = 该行动起始的 battle_time，收尾时尚未推进）。
        - 玩家**在自己行动中**使用攻击/技能 → 各姿态窗口 +延长值（技能 `air_extend`
          正数优先，否则规则缺省 `ctb.air_extend`）；每次行动只延长一次
          （`_air_ext_marker` 幂等，防多级收尾重入重复计费）。
        """
        try:
            from qbot_rpg.core.position import position_of  # noqa: PLC0415

            _ps, _ph = position_of(self._snap, "player")
            if _ph != "air":
                return
            insts = self._air_stance_instances("player")
            if not insts:
                return   # 无姿态：交由 _settle_air_landing 兜底落地
            _now = float(self.battle_time)
            _rule = self._rule_config()
            for inst in insts:
                if not isinstance(inst, dict):
                    continue
                _v = inst.get("air_expire_at")
                _ok = False
                if _v is not None and not isinstance(_v, bool):
                    try:
                        _ok = float(_v) > 0
                    except (TypeError, ValueError):
                        _ok = False
                if not _ok:
                    inst["air_expire_at"] = _now + float(_rule.air_time)
            if actor != "player" or getattr(self, "_current_actor", None) != "player":
                return
            _act = self._last_action_of(actor) or {}
            if str(_act.get("type") or "").lower() not in ("normal", "attack", "skill"):
                return
            _key = "{}:{:.6f}".format(int(self.action_seq), _now)
            if getattr(self, "_air_ext_marker", None) == _key:
                return
            self._air_ext_marker = _key
            _ext = self._air_extend_of(_act, _rule)
            if _ext > 0:
                for inst in insts:
                    if not isinstance(inst, dict):
                        continue
                    try:
                        _base = float(inst.get("air_expire_at") or _now)
                    except (TypeError, ValueError):
                        _base = _now
                    inst["air_expire_at"] = _base + float(_ext)
        except Exception:  # noqa: BLE001 - 窗口维护失败不阻断行动收尾
            return

    def _air_extend_of(self, action: Mapping[str, Any], rule: Any) -> float:
        """本次空中行动的延长值：技能 `air_extend`（正数）优先，否则规则缺省。"""
        _def_ext = float(getattr(rule, "air_extend", 0.0) or 0.0)
        _sid = str(action.get("skill_id") or "")
        if _sid:
            try:
                _sd = self.combo_engine().resolve_skill(_sid) or {}
                _v = _sd.get("air_extend")
                if isinstance(_v, (int, float)) and not isinstance(_v, bool) and _v > 0:
                    return float(_v)
            except Exception:  # noqa: BLE001 - 解析失败回退缺省
                pass
        return _def_ext

    def _settle_air_landing(self) -> None:
        """空中姿态到期自动落地（**行动条口径**——增补 v1 §四，2026-09-11）。

        判定（玩家侧；本方法由 `_after_actor_action` 调用）：

        - 不在空中 → 无操作；
        - 空中但无任何空中姿态状态 → 落地（R16 兜底语义保留）；
        - 空中且有姿态：窗口 = `air_expire_at`（初始化/延长见 `_update_air_window`）；
          全部到期（now >= expire）→ 清理姿态 + 自动落地；任一未到期 → 保持。

        落地产出 `air_land` 事件（经 `_pending_air_events` 并入下一次行动 outcome，
        渲染层出「落回地面」行）；battle_notes 审计记录保留。
        """
        try:
            from qbot_rpg.core.position import position_of  # noqa: PLC0415

            _ps, _ph = position_of(self._snap, "player")
            if _ph != "air":
                return
            insts = self._air_stance_instances("player")
            if insts:
                _now = float(self.battle_time)
                for inst in insts:
                    _v = inst.get("air_expire_at")
                    try:
                        _exp = float(_v) if _v is not None else None
                    except (TypeError, ValueError):
                        _exp = None
                    if _exp is not None and _exp > _now:
                        return   # 窗口未到期：保持空中
            # 落地：清理姿态 → height=ground → 事件（自动落地可被玩家读到）
            self._clear_air_stances("player")
            _rt = self._new_runtime()
            _ctx = DamageCtx(raw_damage=0, attack_type="basic", attacker="player",
                             target="enemy", snapshot=self._snap)
            execute_action({"type": "reposition", "target": "self", "height": "ground"},
                           _ctx, _rt)
            self._absorb_runtime(_rt)
            self._snap.setdefault("battle_notes", []).append(
                {"type": "air_land", "side": "player", "auto": True})
            self._pending_air_events.append(
                {"type": "air_land", "actor": "player", "auto": True})
        except Exception:  # noqa: BLE001 - 落地失败不阻断行动收尾
            return

    def _apply_air_hit_consequences(
        self, attacker: str, action: Mapping[str, Any],
        effects: List[Mapping[str, Any]],
    ) -> Optional[Mapping[str, Any]]:
        """怪物攻击命中空中玩家后的跃空后果（跃空风险闭环，2026-09-11 批③实装）。

        调用点：`_resolve_damage_action` 收尾、`_after_actor_action` 之前——到达本点
        = 方位检查已过（该行动可触达空中）、防反早段分流已完毕（防反成功=完全免伤，
        不吃本后果）。两档（均**隐性口径，玩家不可见**）：

        - **击落档**（`action.air_drop == "knockdown"`，对空必杀）：立即落地（清理空中
          姿态 + height=ground）+ 倒地状态（`air_drop_status_id`，缺省 knockdown；受击
          增伤=可被追击）+ 行动条硬直（`ctb.air_drop_delay` 经 `delay_actor` 追加到
          玩家下次 ready，纯时间平移）+ `air_drop` 事件（渲染「将你从空中击落」行）；
        - **柔和档**（缺省）：各空中姿态窗口缩短 `ctb.air_hit_shrink`（行动条）——窗口
          降至当前时刻以下则本行动收尾由 `_settle_air_landing` 按既有「到期」语义落地
          （无硬直）。

        护栏：非 enemy→player / 行动无伤害语义（mult≤0，如召唤/辅助） / 玩家不在空中 /
        无空中姿态实例 → 无操作返回 None。
        """
        try:
            if attacker != "enemy":
                return None
            try:
                _mult = float(action.get("mult", 1.0) or 0.0)
            except (TypeError, ValueError):
                _mult = 0.0
            if _mult <= 0:
                return None
            # 对空口径 = **招式显式声明**（position_rule.height 含 "air"）：只有内容层
            # 标了「对空」的招式才有跃空后果。无 rule 的兜底普攻（系统「无 rule=全量」
            # 旧口径，可打到空中）不触发——它非「对空招式」，不吃缩短/击落（批③裁决）。
            _pr = action.get("position_rule")
            _height = _pr.get("height") if isinstance(_pr, Mapping) else None
            if not (isinstance(_height, (list, tuple))
                    and "air" in [str(x) for x in _height]):
                return None
            from qbot_rpg.core.position import position_of  # noqa: PLC0415

            _ps, _ph = position_of(self._snap, "player")
            if _ph != "air":
                return None
            insts = self._air_stance_instances("player")
            if not insts:
                return None
            _rule = self._rule_config()
            if str(action.get("air_drop") or "").strip().lower() == "knockdown":
                # 击落：清理姿态 → 落地 → 倒地（可被追击）→ 行动条硬直 → 事件
                self._clear_air_stances("player")
                _rt = self._new_runtime()
                _ctx = DamageCtx(raw_damage=0, attack_type="basic", attacker="player",
                                 target="enemy", snapshot=self._snap)
                execute_action({"type": "reposition", "target": "self",
                                "height": "ground"}, _ctx, _rt)
                _sid = str(self._config.get("air_drop_status_id") or "knockdown")
                execute_action({"type": "status_apply", "status_id": _sid,
                                "source": "air_drop", "target": "self"}, _ctx, _rt)
                self._absorb_runtime(_rt)
                # 倒地窗口覆写（对齐破位口径「持有者行动次数」）：系统在**每个行动
                # 收尾**对双端各扣 1（`tick_turn_end` → `tick_turns`），状态 def 的
                # turns=1 会在本次行动收尾即被扣除——置位 `air_drop_turns`（缺省 3；
                # 含本次收尾扣减 → 实际撑过「玩家下一拍 + 怪下一次出手」的追击窗，
                # 可被追击 ×1.5 实际生效）。
                _turns = int(self._config.get("air_drop_turns", 3) or 0)
                if _turns > 0:
                    _st = self._snap.get("status_state")
                    _insts = _st.get("player") if isinstance(_st, Mapping) else None
                    if isinstance(_insts, list):
                        for _inst in reversed(_insts):
                            if (isinstance(_inst, Mapping)
                                    and _inst.get("status_id") == _sid):
                                if isinstance(_inst, dict):
                                    _inst["turns"] = _turns
                                break
                _delay = float(getattr(_rule, "air_drop_delay", 0.0) or 0.0)
                if _delay > 0 and self._ctb is not None:
                    self._ctb.delay_actor("player", _delay)
                self._snap.setdefault("battle_notes", []).append(
                    {"type": "air_drop", "side": "player", "attacker": "enemy"})
                _ev: Mapping[str, Any] = {"type": "air_drop", "actor": "player",
                                          "attacker": "enemy"}
                if isinstance(effects, list):
                    effects.append(_ev)
                return _ev
            # 柔和档：窗口缩短；缩至当前时刻以下 → 立即按「到期」语义落地（无硬直）。
            # 须在本方法内直接结算：行动收尾的窗口维护（`_update_air_window`）会把
            # 「非正值」当作未初始化**重设**（reinit 守卫）——不先落地反而会重置窗口。
            _shrink = float(getattr(_rule, "air_hit_shrink", 0.0) or 0.0)
            if _shrink > 0:
                for inst in insts:
                    if not isinstance(inst, dict):
                        continue
                    _v = inst.get("air_expire_at")
                    try:
                        _exp = float(_v) if _v is not None else None
                    except (TypeError, ValueError):
                        _exp = None
                    if _exp is not None:
                        inst["air_expire_at"] = _exp - _shrink
                self._settle_air_landing()
            return None
        except Exception:  # noqa: BLE001 - 跃空后果失败不阻断行动收尾
            return None

    def _trigger_on_dodge(self, defender: str, attacker: str) -> None:
        """闪避回馈（2026-09-09 御剑·腾空原版）：防御方空中被攻击未命中
        （roll miss / 未命中 position miss）→ 遍历其 status def 的
        on_dodge_effects 执行（statuses.json 内容配置；无 → 零操作）。

        条件：defender 当前 height == air 且 status_state 含带
        on_dodge_effects 的 status。执行失败不阻断战斗。
        """
        try:
            from qbot_rpg.core.position import position_of  # noqa: PLC0415

            _s, _h = position_of(self._snap, defender)
            if _h != "air":
                return
            st = self._snap.get("status_state")
            insts = st.get(defender) if isinstance(st, Mapping) else None
            if not insts:
                return
            todo: List[Mapping[str, Any]] = []
            for inst in insts:
                if not isinstance(inst, Mapping):
                    continue
                sid = str(inst.get("status_id") or "")
                if not sid:
                    continue
                sdef = self._resolver(sid, "status")
                raw = getattr(sdef, "raw", sdef)
                if isinstance(raw, Mapping):
                    ode = raw.get("on_dodge_effects")
                    if isinstance(ode, list):
                        todo.extend(e for e in ode if isinstance(e, dict))
            if not todo:
                return
            rt = self._new_runtime()
            ctx = DamageCtx(
                raw_damage=0, attack_type="skill", attacker=defender, target=attacker,
                snapshot=self._snap, variables=self._base_variables(defender, attacker),
            )
            from qbot_rpg.core.effects import execute_action  # noqa: PLC0415

            for eff in todo:
                execute_action(eff, ctx, rt)
            self._absorb_runtime(rt)
        except Exception:  # noqa: BLE001 - 闪避回馈失败不阻断战斗
            pass

    def _position_miss_outcome(
        self, attacker: str, action: Mapping[str, Any], target: str, side: str, height: str,
        extra_effect: Optional[Mapping[str, Any]] = None,
    ) -> ActionOutcome:
        """方位 miss 收口（方位 v0.6 §四：未命中——技能照常消耗、无伤害/破坏力/效果）。

        行动槽已占（本行动消耗一次 ready），与命中结算同构走完状态迁移与
        行动收尾（RES 迁移 / action_record / tick / action_end / after_actor），只不产
        生任何伤害与效果；渲染层经 side_effects 的 position_miss 标记出模板文案
        （battle_enemy_position_miss，模板配置化），engine message 仅兜底直读方。
        """
        # 2026-09-09：状态容错——行动已提交（RES）时 position_miss 幂等收尾
        # （正常路径：技能施放提交 RES → 怪行动 position_miss 前置判定；不重复迁移）
        if self._state != STATE_RES:
            self._to_state(STATE_RES, "submit:position_miss")
        rating: Dict[str, Any] = {
            "hit": False, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0,
            "position_miss": True, "side": side, "height": height,
        }
        seg_damage: Dict[str, Any] = {"ch_phys": 0, "ch_elem": 0, "final": 0}
        self._record_action(
            attacker, str(action.get("type", "normal")), target, rating, seg_damage, self._phase,
        )
        tick_after_action(self._snap, self._new_runtime(), attacker)
        self._absorb_runtime(self._new_runtime())
        self._dispatch_event("action_end", attacker)
        # 方位 v0.6（§四 T8）：miss 也是完整行动——action_end 后按行动 air_policy 结算
        _land = self._settle_air_policy(attacker, action.get("air_policy"))
        self._after_actor_action(attacker)
        _fx: List[Mapping[str, Any]] = [
            {"type": "position_miss", "actor": attacker, "target": target,
             "side": side, "height": height},
        ]
        if extra_effect is not None:
            _fx.append(extra_effect)
        if _land is not None:
            _fx.append(_land)
        _fx.extend(self._take_pending_air_events())
        return ActionOutcome(
            True, self._seq, attacker, str(action.get("type", "normal")), target,
            False, "low", False, 0, 0, int(self._combat(target).get("hp", 0) or 0),
            tuple(_fx),
            f"未命中：目标不在攻击方位内（{side}/{height}）",
        )

    # ------------------------- 空中规则（方位 v0.6 §三.6/§四 T8，附录 A Step 3） -------------------------

    def _settle_air_policy(
        self, actor: str, policy: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """air_policy 行动收尾结算（方位 v0.6 §三.6/§四 T8：action_end → air_policy → next actor）。

        - land：行动者当前 height=air → 落地（height=ground），返回落地事件
          {"type": "air_land", "actor"}（渲染层出「落回地面」行，模板配置化）；
          已在地面 → 无变化、无事件。
        - preserve / preserve_height / 缺省（None）：保持当前高度，无事件。
        - 旧快照无 combat_position 段 / 缺 actor 段 → 降级不动（读取侧缺段不崩，
          对齐 resource_state RS-5 精神）。

        与 combo 完全正交：本结算只改高度快照字段，不触碰 combo_state（§三.6）。
        """
        if policy != "land":
            return None
        cp = self._snap.get("combat_position")
        if not isinstance(cp, MutableMapping):
            return None
        me = cp.get(actor)
        if not isinstance(me, MutableMapping):
            return None
        if me.get("height") != "air":
            return None
        me["height"] = "ground"
        # 落地统一清理：空中姿态状态（跃空窗口载体）随落地自然消散（增补 v1 §四）
        self._clear_air_stances(actor)
        return {"type": "air_land", "actor": actor}

    # ------------------------- 部位破坏（方位 v0.6 §三.3/§三.4，附录 A Step 2） -------------------------

    def _enemy_parts_defs(self) -> List[Mapping[str, Any]]:
        """敌方部位配置列表（快照 enemy combatant `parts` 透传：enemies.json parts[] 原样）。

        无 parts 键/非列表 → []（既有怪零变化）；配置=只读镜像（战斗内权威实例态在
        parts_state，§三.3）。
        """
        e = self._combat("enemy")
        parts = e.get("parts") if isinstance(e, Mapping) else None
        if not isinstance(parts, list):
            return []
        return [p for p in parts if isinstance(p, Mapping)]

    def _init_parts_state(self) -> None:
        """start 时按敌方 parts 配置实例化 parts_state（id → {break_value, broken}）。

        幂等：已有 dict 实例不覆盖（续战快照段直接透传，不重建）；无 parts → 保持空段。
        """
        st = self._snap.setdefault("parts_state", {})
        if not isinstance(st, dict):
            st = {}
            self._snap["parts_state"] = st
        for pd_ in self._enemy_parts_defs():
            pid = str(pd_.get("id") or "")
            if not pid:
                continue
            cur = st.get(pid)
            if not isinstance(cur, dict):
                st[pid] = {"break_value": 0.0, "broken": False}

    def _part_state_of(self, part_id: Optional[str]) -> Optional[Mapping[str, Any]]:
        """部位实例态读取（缺 parts_state 段/缺键 → None；旧快照降级不崩）。"""
        if not part_id:
            return None
        st = self._snap.get("parts_state")
        if not isinstance(st, Mapping):
            return None
        cur = st.get(part_id)
        return cur if isinstance(cur, Mapping) else None

    def _resolve_part_target(
        self, action: Mapping[str, Any]
    ) -> Tuple[Optional[str], Mapping[str, Any]]:
        """部位 resolve（§四 part resolve，方位 v0.6 §三.3/附录 A Step 2）。

        候选条件（玩家当前格同时满足）：
          1) part.positions 覆盖玩家当前 (side, height)（部位可达方位格，怪物局部坐标）
          2) action.position_rule 放行该格（F08 玩家侧消费点；无 rule = 全量）
        多候选 → target_priority 高者优先，同值随机（消耗一次 roll）；无候选 →
        (None, {}) 纯本体（打整体 HP，无部位乘区/无破坏力累计）。
        """
        from qbot_rpg.core.position import position_of, rule_permits  # noqa: PLC0415

        cell_side, cell_height = position_of(self._snap, "player")
        rule = action.get("position_rule")
        cands: List[Mapping[str, Any]] = []
        for pd_ in self._enemy_parts_defs():
            pos = pd_.get("positions")
            if not isinstance(pos, Mapping):
                continue
            if rule_permits(pos, cell_side, cell_height) and rule_permits(
                    rule, cell_side, cell_height):
                cands.append(pd_)
        if not cands:
            return None, {}
        cands.sort(key=lambda d: float(d.get("target_priority", 0) or 0), reverse=True)
        top_val = float(cands[0].get("target_priority", 0) or 0)
        top = [d for d in cands
               if float(d.get("target_priority", 0) or 0) >= top_val]
        pick = top[0]
        if len(top) > 1:
            idx = int(self._roll() * len(top))
            pick = top[min(idx, len(top) - 1)]
        return str(pick.get("id") or ""), pick

    def _status_damage_mult(self, target: str) -> float:
        """目标侧受击增伤乘区（§五：status def `damage_mult`；缺省/未知状态 → 1.0）。

        knockdown 状态 def 挂 damage_mult 即倒地叠加增伤源（内容包 statuses.json）。
        """
        mult = 1.0
        st = self._snap.get("status_state")
        if isinstance(st, Mapping):
            insts = st.get(target)
            if isinstance(insts, list):
                for inst in insts:
                    if not isinstance(inst, Mapping):
                        continue
                    sid = str(inst.get("status_id") or "")
                    if not sid:
                        continue
                    sdef = self._resolver(sid, "status")
                    raw = getattr(sdef, "raw", sdef)
                    if isinstance(raw, Mapping):
                        dm = raw.get("damage_mult")
                        if isinstance(dm, (int, float)) and not isinstance(dm, bool):
                            mult *= float(dm)
        return mult

    def _fire_part_break(
        self, attacker: str, target: str, part_def: Mapping[str, Any],
        events: List[Mapping[str, Any]],
    ) -> None:
        """破位事件收口（§三.3 on_break + §四 破位时序）：全部走既有 effects 通道。

        - knockdown（默认 1；部位覆写 0 = 该部位破位不倒地，§三.3 on_break.knockdown）
          → status_apply 挂 knockdown_status_id 状态（config 可改 id）；窗口 = 持有者
          **N 次行动**（CTB 重写 R5：旧口径把 `on_break.knockdown` 当「回合数」写入
          实例 `turns`，CTB 下 `turns` 的消费方改为「持有者行动次数」——即该状态每次
          持有者行动递减一次；数值 N 语义由「N 回合」改「N 次行动」）
        - marks → mark_add 原子动作（破位附加印记，如素材掉落标记）
        - effects → 原样执行（附加效果：断尾削扫尾范围=行动禁用/替换等）
        相对侧语义：attacker=player 施加方，target 键用相对 "enemy"（effects 层口径）。
        """
        ob = part_def.get("on_break")
        if not isinstance(ob, Mapping):
            ob = {}
        kd = int(ob.get("knockdown", 1) or 0)
        kd_id = str(self._config.get("knockdown_status_id") or "knockdown")
        entries: List[Mapping[str, Any]] = []
        if kd > 0:
            entries.append({"type": "status_apply", "status_id": kd_id,
                            "source": "part_break", "target": "enemy"})
        for mk in ob.get("marks") or []:
            if isinstance(mk, str) and mk:
                entries.append({"type": "mark_add", "mark": mk, "count": 1,
                                "target": "enemy"})
        for fx in ob.get("effects") or []:
            if isinstance(fx, Mapping):
                entries.append(fx)
        if not entries:
            return
        rt = self._new_runtime()
        ctx = DamageCtx(raw_damage=0, attack_type="basic", attacker=attacker,
                        target=target, snapshot=self._snap,
                        variables=self._base_variables(attacker, target))
        for act in entries:
            res = execute_action(act, ctx, rt)
            events.extend(res.side_effects)
        self._absorb_runtime(rt)
        # 倒地窗口覆写：on_break.knockdown = **持有者行动次数**（实例 turns 置位；
        # 状态 def 静态 duration 不承载 N3 数值，窗口数值归部位配置）。
        # CTB 重写（R5）：`turns` 的递减由该状态持有者的每次行动触发
        # （tick_after_action 路径），故 N 的语义从「N 回合」= 「N 次持有者行动」。
        if kd > 0:
            st = self._snap.get("status_state")
            insts = st.get(target) if isinstance(st, Mapping) else None
            if isinstance(insts, list):
                for inst in reversed(insts):
                    if isinstance(inst, Mapping) and inst.get("status_id") == kd_id:
                        if isinstance(inst, dict):
                            inst["turns"] = kd
                        break

    def _resolve_damage_action(self, attacker: str, action: Dict[str, Any]) -> ActionOutcome:
        """伤害行动闭环（核心）：命中→会心→格挡→双通道→总伤害→拦截链→扣血→
        死亡判定（每段后）→ 反射回注（F-22）→ 状态衰减（D5）。

        段支持：action.get("segments") 为 [ {mult,...}, ... ] 时逐段结算（1g1c
        A-03/TC-07；套内击杀后续段照常 A4；BOSS/最后目标死亡 A5 立即结束）。
        \\
        """
        # 2026-09-09：submit 幂等容错（防反/闪反反击在行动已提交 RES 后结算——
        # 反击不重复提交状态；正常路径 act→res 不变）
        if self._state != STATE_RES:
            self._to_state(STATE_RES, f"submit:{action.get('type', 'normal')}")
        target = self._opposite(attacker)
        segments = action.get("segments") or [action]
        ac, tc = self._combat(attacker), self._combat(target)
        p = self._params
        atk_type = self._normalize_attack_type(str(action.get("attack_type") or "slash"))

        # 连段/派生累计（1c1a/1a derived：≤1.5× 封顶，damage.apply_derived_cap）
        seg_total: int = 0
        raw_total: int = 0
        all_effects: List[Mapping[str, Any]] = []
        last_hp: int = int(tc.get("hp", 0))
        rating: Dict[str, Any] = {"hit": True, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0}
        seg_damage: Dict[str, Any] = {"ch_phys": 0, "ch_elem": 0, "final": 0}

        # ---- 方位 v0.6（附录 A Step 2）部位 resolve（§四 part resolve）：行动级选定 ----
        # 玩家攻击 & 敌方带 parts：玩家当前格 ∈ 部位 positions ∩ action.position_rule
        # → 候选部位（target_priority 高优先/同值随机）；无部位/无候选 → 纯本体
        # （本行动打本体：无部位乘区、无破坏力累计——任意攻击仍打整体 HP，§二.3）。
        part_id: Optional[str] = None
        part_def: Mapping[str, Any] = {}
        if attacker == "player" and target == "enemy" and self._enemy_parts_defs():
            part_id, part_def = self._resolve_part_target(action)
            if part_id:
                all_effects.append({"type": "part_target", "part": part_id,
                                    "actor": attacker, "target": target})

        # ---- 防反判定（2026-09-09 用户拍板标签制）：怪攻击命中路径——行动带可防反
        # 标签 + 玩家当次行动防反姿态（守势类）→ 整次攻击完全免伤 + 自动反击；
        # 无标签 → 失败：受伤（姿态减伤照常）+ 无反击（用户示例语义）。----
        self._snap.pop("_parried_this_act", None)
        if attacker == "enemy" and target == "player":
            _st = self._player_stance()
            _at = self._action_tags(action)
            if _st and _st[0] == "parry" and _at[0]:
                self._snap["_parried_this_act"] = True
                rating0 = {"hit": True, "crit": "low", "blocked": False,
                           "pierce": 0.0, "multi": 0.0}
                seg0 = {"ch_phys": 0, "ch_elem": 0, "final": 0}
                _rname = None
                _rca = action.get("skill_id")
                if _rca:
                    _rsd = self.combo_engine().resolve_skill(str(_rca)) or {}
                    _rname = str(_rsd.get("name") or "") or None
                self._record_action(attacker, str(action.get("type", "normal")), target,
                                    rating0, seg0, self._phase, name=_rname)
                all_effects.append({"type": "parry", "target": target,
                                    "attacker": attacker, "skill_id": _st[1]})
                # 反击返还（怪猎采纳 C11，批⑤）：防反成功 → 玩家下一 ready 返还
                # `ctb.counter_refund`（缺省 200 行动条；隐性口径玩家不可见）。
                # **须在 `_run_counter` 之前**——反击技内部走完整收尾链（含本拍
                # 时间轴推进），先返还才能让推进落在提早后的 ready 上；失败路径
                # 不调用（落空不双罚——只付行动条）。
                self._hasten_player_after_counter()
                _cd = self._run_counter(_st[1])
                all_effects.append({"type": "parry_counter", "target": "enemy",
                                    "attacker": "player", "skill_id": _st[1],
                                    "damage": _cd})
                # 防反=完整行动收尾（状态机不绕过：tick/action_end/air_policy/after_actor
                # ——否则状态链断（后续 position_miss 等 res→res 崩溃））
                tick_after_action(self._snap, self._new_runtime(), attacker)
                self._absorb_runtime(self._new_runtime())
                self._dispatch_event("action_end", attacker)
                _land = self._settle_air_policy(attacker, action.get("air_policy"))
                if _land is not None:
                    all_effects.append(_land)
                self._after_actor_action(attacker)
                _thp_now = int((self._snap.get(target) or {}).get("hp", 0))
                return self._action_outcome(attacker, action, target, rating0, seg0,
                                            all_effects, _thp_now,
                                            battle_ended=False)
            # 闪反失败：可闪反行动命中位移中的玩家（已在攻击范围）→ 受伤照常 +
            # 击退回正面（失败位移语义）
            if _st and _st[0] == "dodge" and _at[1]:
                all_effects.append({"type": "dodge_fail", "target": target,
                                    "attacker": attacker})
                try:
                    _cp = self._snap.setdefault("combat_position", {}).setdefault(
                        "player", {"relative_to": "enemy"})
                    if isinstance(_cp, dict):
                        _cp["side"] = "front"
                        _cp["height"] = "ground"
                except Exception:
                    pass
                # 闪反失败击落：空中姿态（窗口载体）随落地清理（增补 v1 §四）
                self._clear_air_stances("player")

        for idx, seg in enumerate(segments, start=1):
            seg = dict(seg)
            # M2-C1 修复（0 倍率占行动槽/功能技不造成伤害）：max(1,) 通道保底会把
            # mult=0 抬成每通道 1 点——蓄力起手/起身演出误伤 2、吼叫类 0 倍率 buff 误伤。
            # 0 倍率段：记录 0 伤害 action_record，跳过命中/会心/格挡/通道结算
            # （技能 effects 已在上游 _resolve_combo_action L1236-1244 执行，不受影响）。
            _raw_mult0 = seg.get("mult")
            if _raw_mult0 is not None and float(_raw_mult0) <= 0:
                self._record_action(
                    attacker, str(action.get("type", "normal")), target,
                    {"hit": True, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 0.0},
                    {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase,
                )
                continue
            # P1-01 修复（dsh 批2 P1-01）：每段结算前刷新防御行——战斗中新施加的
            # 反射/吸收/减伤状态（status_actions 折叠）次击即可进 defenses 生效
            # （F-21 prepare_defense 归一化，docstring 自述「每次结算前刷新」）。
            self._refresh_defenses()
            rt = self._new_runtime()
            # ---- ① 命中（方位制——2026-09-09 用户拍板：移除命中/闪避 roll 计算）----
            # 攻击资格由方位判定（position_rule：行动覆盖方位 vs 目标当前方位）前置把关
            # （_resolve_combo_action L2160 区：范围内必中；范围外=position_miss 未命中，
            # 不会进入伤害管线）；此处不再 roll——命中恒真。玩家防御=主动闪反（位移离开
            # 攻击方位）/防反（守势减伤）。miss 分支保留作安全网（不进即不触发）。
            hit = True

            rating: Dict[str, Any] = {  # type: ignore[no-redef]
                "hit": hit, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0,
            }
            seg_damage: Dict[str, Any] = {"ch_phys": 0, "ch_elem": 0, "final": 0}  # type: ignore[no-redef]
            if not hit:
                # miss：伤害 0，仍写 action_record（提示未命中），不触发击杀判定（1g1c §② 命中行）
                self._record_action(attacker, str(action.get("type", "normal")), target,
                                    rating, seg_damage, self._phase)
                all_effects.append({"type": "miss", "target": target, "attacker": attacker})
                # 2026-09-09：闪避回馈（防御方空中姿态 on_dodge_effects——御剑腾空）
                self._trigger_on_dodge(target, attacker)
                continue

            # ---- ② 会心（1a §1.4/§1.5：√幸运/2，三档）----
            # M12.5 需求1 批B：stat_map 语义键取数（缺省 lck=现值，零破坏）
            lck = float(ac.get(p.stat_map.crit_luck, 50))
            super_crit_lv = int(ac.get("super_crit_lv", 0) or 0)
            crit_r = self._roll()
            # G1 定稿对照修复（damage 定稿对照 G1）：斩击会心 +5%（数值层 L92/L216
            # type_affinity.slash_crit）实战零生效——crit_prob 原全库零调用、crit_roll 无加成/
            # cap（CritParams.cap，默认 100；判定前应用，细化_1a §5-⑦/增补 v1 §五）再判档。
            slash_bonus = p.type_affinity.slash_crit if atk_type == "slash" else 0.0
            # 会心来源（怪猎采纳 E19/E20，批⑤）：combatant 显式 crit_bonus（百分数；
            # 负值 → 负会心/赌狗流派）+ 条件型会心（crit_bonus_cond：方位/逆境/首击）。
            # 口径=小数（crit_prob 直接相加）；slash 加成独立保留（原 G1 口径不变）。
            crit_bonus_all = self._crit_bonus_of(attacker, target) + slash_bonus
            p_eff = crit_prob(lck, p_coef=p.crit.p_coef, crit_bonus=crit_bonus_all,
                              cap=p.crit.cap)
            crit_id, crit_mult = crit_roll(
                crit_r, lck, p_coef=p.crit.p_coef, tiers=p.crit.tiers,
                tier_p=p.crit.tier_p, super_crit_level=super_crit_lv,
                p_override=p_eff, negative_crit=p.crit.negative_crit,
            )
            rating["crit"] = crit_id
            # 批⑥ 方案B：实际生效倍率透传（含超会心加成）→ ActionOutcome → 渲染动态化
            rating["crit_mult"] = crit_mult

            # ---- ③ 格挡（1a §1.7：min(40%, 专注/(专注+150))；魔攻击无视）----
            magic = atk_type == "magic"
            # M12.5 需求1 批B：stat_map 语义键取数（缺省 foc=现值，零破坏）
            br = block_rate(float(tc.get(p.stat_map.block_focus, 50)), k=p.block.k, cap=p.block.cap)
            blocked = self._roll() <= br and not (magic and p.block.magic_ignores)
            rating["blocked"] = blocked

            # ---- ④ 双通道（1a §1.1-1.6：物理/元素独立 floor 后相加）----
            pierce = 0.0
            if p.type_affinity.enabled:
                pierce += pierce_pct(atk_type, blunt_pierce=p.type_affinity.blunt_pierce)
            pierce = min(0.6, pierce + float(seg.get("pierce", 0.0)))
            rating["pierce"] = pierce
            # M12.5 需求1 批B：stat_map 语义键取数（缺省 con=现值，零破坏）
            eff_con = effective_con(float(tc.get(p.stat_map.def_con, 50)), pierce)
            df = defense_factor(eff_con, k=p.defense.k)
            # M2 技能倍率 = 基础 ×（1 + F-23 效果加成/100）→ F-23 消费点
            # M2-C1 修复（怪物 AI 蓄力/起身占行动槽 mult=0 语义）：原 `or 1.0` 把显式 0 吞成 1.0，
            # 蓄力播报/0 倍率 buff 行动误造成伤害——仅缺省（None/缺失）回落 1.0，0.0 原样保留
            _raw_mult = seg.get("mult")
            base_mult = float(_raw_mult) if _raw_mult is not None else 1.0
            skill_mult = self._apply_boost_to_mult(attacker, base_mult, "atk")
            # 派生累计 ≤1.5× 封顶（1a L129/L229；damage.apply_derived_cap，P1-7 消费）
            # P1-1（qa_report_20260907）修正：cap 语义 = 派生链「伤害加成增量」防
            # 膨胀（派生定稿 §6.3/风险表）——只约束 **boost 加成因子**（1+boost/100
            # ≤1.5），不砍技能自身完整 base_mult（派生大招 power 200-420 → 2.0-4.2×
            # 是数值定稿 §4.2 预算档位，非派生链累计）。修复前整个 skill_mult 被
            # min 到 1.5，裂脊斩 300%/零距 320% 等派生终技全被误砍。
            # M2-C1（tc16）保留：非派生技能（含怪物行动）不套此封顶。
            if action.get("_derived"):
                # base_mult 完整保留；仅加成因子 cap（boost +100% → 因子 2.0 压 1.5）
                boost_factor = 1.0 + self._aggregate_boost(attacker, "atk") / 100.0
                boost_factor = apply_derived_cap(
                    boost_factor, max_total_mult=p.derived.max_total_mult)
                skill_mult = base_mult * boost_factor
            # ---- 背击（B5 背击闭环，2026-09-11 批④）：玩家攻击结算时位于怪背面 ----
            # → 物理通道伤害 ×(1 + backstab_bonus)。乘区挂在 skill_mult 上＝只影响
            # 物理通道（ch_elem 走 elem_mult 不吃——怪猎闇討ち「属性伤害不计」口径）。
            # 可配（缺省 +10%；0=关）；命中行「（背击）」附注经 rating 透传 ActionOutcome。
            if attacker == "player":
                try:
                    _bs_bonus = float(self._config.get("backstab_bonus", 0.10) or 0.0)
                except (TypeError, ValueError):
                    _bs_bonus = 0.0
                if _bs_bonus > 0:
                    from qbot_rpg.core.position import position_of  # noqa: PLC0415

                    if position_of(self._snap, "player")[0] == "back":
                        skill_mult *= (1.0 + _bs_bonus)
                        rating["backstab"] = True
            rating["multi"] = skill_mult
            # M12.5 需求1 批B：stat_map 语义键取数（缺省 atk / int→mag 回退链=现值，
            # 零破坏）
            attack_value = float(ac.get(p.stat_map.atk_atk, 0))
            if magic:
                attack_value = float(ac.get(p.stat_map.mag_int,
                                            ac.get("mag", attack_value)))
            # G3 定稿对照修复（damage 定稿对照 G3）：base_attack_mult（M2 全局攻击倍率基线，
            # 数值层 L179/细化_1a §1.2）实战零消费——现乘入物理通道首因子。
            attack_value *= p.base_attack_mult
            weak_mult = float(seg.get("weakness_mult", 1.0))
            # G3（定稿 §8.1 L326-327）：弱点倍率入 rating 供 stats_collector 记录
            #（类型/元素弱点当前共用统一 weak_mult；怪物配置 weakness 细分在数据包阶段引入）
            rating["weak_type"] = weak_mult
            rating["weak_elem"] = weak_mult
            # R-09 拍板（用户 2026-08-18）：O1 怪物防御率为**每怪物可配字段**
            # （enemies.json per-monster monster_def_rate，缺省 1.0 普通同玩家）——
            # 取自目标 combatant 配置，回退全局 DamageFormulaParams.monster_def_rate。
            mdr = float(tc.get("monster_def_rate", p.monster_def_rate) or p.monster_def_rate)
            ch_phys = channel_phys(attack_value, skill_mult, weak_mult, crit_mult, df,
                                   monster_def_rate=mdr)
            elem_atk = float(ac.get("elem_atk", 0) or 0)
            elem_f = elem_factor(float(tc.get("elem_res", 0)), k=p.defense.k)
            # 属性会心（怪猎采纳 E21，批⑤）：元素通道默认不吃会心（×1.0，防双通道
            # 会心膨胀）；天赋 Lv1-3（combatant `elem_crit_lv`）→ ×(1 + 步进×Lv)
            # （缺省步进 0.05 → +5%/10%/15%；Lv>3 按 3 封顶）。步进可经
            # formula.json crit.elem_crit_step 调（CritParams.elem_crit_step）。
            try:
                _elem_lv = int(ac.get("elem_crit_lv", 0) or 0)
            except (TypeError, ValueError):
                _elem_lv = 0
            elem_crit_mult = 1.0 + p.crit.elem_crit_step * min(max(_elem_lv, 0), 3)
            ch_elem = channel_elem(elem_atk, float(seg.get("elem_mult", 0.0)), weak_mult,
                                   elem_crit_mult, elem_f, monster_def_rate=mdr)
            seg_damage["ch_phys"], seg_damage["ch_elem"] = ch_phys, ch_elem

            # ---- ⑤ 总伤害（1a §1.7-1.9：格挡×0.5 / 防御指令×0.5 / 乱数[0.9,1.1]）----
            rng_multi = p.rng[0] + self._roll() * (p.rng[1] - p.rng[0])
            guard = bool(self._guard_active.get(target, False))
            raw, blocked_eff = total_damage(
                ch_phys, ch_elem,
                rng=rng_multi, blocked=blocked, magic=magic, guard=guard,
                magic_ignores_block=p.block.magic_ignores,
                halve_after_block=p.block.halve_after_block,
            )
            rating["blocked"] = blocked_eff
            # ---- 方位 v0.6（附录 A Step 2）：部位乘区（position_bonus × knockdown_bonus）----
            # 只对命中已破部位（broken）的段生效（§二.3：已破部位方位=常驻增伤；倒地
            # 窗口内打已破部位=叠加增伤——knockdown 乘区挂 status def damage_mult，§五）。
            # 硬时序：破坏力结算用未乘增伤的 base_raw（§三.4 basis=命中/会心/格挡/防御/
            # 乱数后、DamagePipeline 前，不含破位乘区）——防「破位→增伤→破坏力膨胀」
            # 自反馈（v0.6 修正 #4/#5）。本次破位不吃本次增伤（先乘后判，置位自下段起效）。
            _part_state = self._part_state_of(part_id) if part_id else None
            broken_hit = bool(_part_state and _part_state.get("broken"))
            base_raw = raw
            if broken_hit:
                # 常驻增伤 × 倒地叠加（status def damage_mult）；整型入账对齐既有伤害口径
                _dmg_float = float(raw) * float(p.battle_position.broken_part_mult)
                _dmg_float = _dmg_float * self._status_damage_mult(target)
                raw = int(_dmg_float)
            raw_total += raw

            # ---- 破坏力（每段一次，写死多段 N 次；命中部位且未破才累计）----
            if part_id and part_def and not (broken_hit):
                _bpp = p.battle_position
                _basis = max(0.0, float(base_raw) - float(_bpp.break_base_damage))
                _delta = (float(action.get("break_power", 0) or 0)
                          + float(_bpp.break_sqrt_coef) * (_basis ** 0.5))
                _st_map = self._snap.setdefault("parts_state", {})
                if not isinstance(_st_map, dict):
                    _st_map = {}
                    self._snap["parts_state"] = _st_map
                _pst = _st_map.get(part_id)
                if not isinstance(_pst, dict):
                    _pst = {"break_value": 0.0, "broken": False}
                    _st_map[part_id] = _pst
                _pst["break_value"] = float(_pst.get("break_value", 0.0) or 0.0) + _delta
                rating["part"] = part_id
                rating["break_delta"] = round(_delta, 2)
                all_effects.append({"type": "part_damage", "part": part_id,
                                    "break_delta": round(_delta, 2),
                                    "actor": attacker, "target": target})
                _thr = float(part_def.get("break_threshold", 0) or 0)
                if not _pst.get("broken") and _pst["break_value"] >= _thr:
                    _pst["broken"] = True
                    rating["part_broken"] = True
                    _ob_raw = part_def.get("on_break")
                    _ob_kd = int((_ob_raw.get("knockdown", 1) or 0)) \
                        if isinstance(_ob_raw, Mapping) else 1
                    all_effects.append({
                        "type": "part_break", "part": part_id,
                        "part_name": str(part_def.get("name") or part_id),
                        "knockdown": _ob_kd,
                        "actor": attacker, "target": target,
                        "break_value": round(_pst["break_value"], 2)})
                    # on_break 收口（knockdown 状态/marks/effects 全走 effects 通道）；
                    # 本段伤害已按破位前状态结算——本次破位不吃本次增伤（下段/下次起效）
                    self._fire_part_break(attacker, target, part_def, all_effects)

            # ---- ⑥⑦⑧ 拦截链（1b §2：减伤→护盾→反弹→吸收→免疫→续行→扣血→死亡判定）----
            vars_ = self._base_variables(attacker, target)
            vars_["damage_dealt"] = seg_total
            res = self.resolve_damage(attacker, target, raw, str(seg.get("attack_type") or atk_type),
                                      snapshot=self._snap, runtime=rt, variables=vars_)
            self._absorb_runtime(rt)
            seg_total += res.final_damage
            seg_damage["final"] += res.final_damage
            all_effects.extend(res.side_effects)
            last_hp = res.target_hp
            _seg_rname: Optional[str] = None
            if str(action.get("type", "normal")) == "skill":
                _sid = str(action.get("skill_id") or "")
                if _sid:
                    _sd = self.combo_engine().resolve_skill(_sid) or {}
                    _seg_rname = str(_sd.get("name") or "") or None
            self._record_action(attacker, str(action.get("type", "normal")), target,
                                rating, seg_damage, self._phase, name=_seg_rname)

            # ⑧ 死亡判定（每次扣血后立即，1g2 §1.2 ④；1g1b 不变量2）
            # 先手击杀来源标记（TC-11 order 基准：玩家行动直击杀敌）
            self._qualified_kill_origin = attacker == "player"
            died = self._death_check_side(target, "hit")
            if died:
                if self._boss_immediate_win():
                    # A5：BOSS/最后目标死亡→立即结束，不清算后续段数（1g1b A5）
                    outcome = self._resolve_battle_end(force=True)
                    if outcome is not None:
                        return self._action_outcome(
                            attacker, action, target, rating, seg_damage, all_effects,
                            last_hp, battle_ended=True, status=outcome.status,
                        )
                # A4：套内击杀后续段照常（鞭尸，1g1b A4 / L51-52）

            # ---- F-22 反射回注（contract_deviations P1-3）----
            refl_events = [e for e in res.side_effects if e.get("type") == "reflect"]
            for ev in refl_events:
                rr = self._deliver_reflect(attacker, target, ev, rt)
                all_effects.append({"type": "reflect_delivered", "damage": rr.final_damage,
                                    "target": str(ev.get("target", attacker)), "hp": rr.target_hp})
                died2 = self._death_check_side(str(ev.get("target", attacker)), "reflect")
                if died2 and self._boss_immediate_win():
                    out = self._resolve_battle_end(force=True)
                    if out is not None:
                        return self._action_outcome(attacker, action, target, rating,
                                                    seg_damage, all_effects, last_hp,
                                                    battle_ended=True, status=out.status)
            # 反射致玩家死亡标记（终局在 _after_actor_action 统一裁决/立即终局）
            if self._dead("player"):
                out = self._resolve_battle_end(force=False)
                if out is not None:
                    return self._action_outcome(attacker, action, target, rating,
                                                seg_damage, all_effects, last_hp,
                                                battle_ended=True, status=out.status)
            rt = self._new_runtime()

        # 行动后衰减（D5 携带者每次行动结算后衰减一次，1g2 §1.3#1 / 1b §4.2 H8）
        tick_after_action(self._snap, self._new_runtime(), attacker)
        self._absorb_runtime(self._new_runtime())
        # 功能三批2：action_end（普攻/技能行动收尾）
        self._dispatch_event("action_end", attacker)
        # 方位 v0.6（§四 T8：action_end → air_policy → next actor）：按行动定义
        # air_policy（skill def F10 合并/接线层显式）结算——land → 空中落地；事件
        # 随 side_effects 出渲染行（击杀终局路径在上方已 return，不落地）
        _land = self._settle_air_policy(attacker, action.get("air_policy"))
        if _land is not None:
            all_effects.append(_land)
        # 跃空风险闭环（批③）：怪物攻击命中空中玩家 → 柔和档窗口缩短 / 对空必杀击落。
        # 到达本点 = 方位检查已过、防反/闪反失败路径已分流（防反成功早退不吃本后果）。
        self._apply_air_hit_consequences(attacker, action, all_effects)
        self._after_actor_action(attacker)
        return self._action_outcome(attacker, action, target, rating, seg_damage,
                                    all_effects, last_hp)

    def _deliver_reflect(self, attacker: str, target: str, ev: Mapping[str, Any], rt: EffectRuntime) -> PipelineResult:
        """F-22 反弹落地：消费 reflect 副作用 → DamagePipeline.deliver_reflect 回注。

        解析钉钉（工程补白②）：effects._stage_reflect 产出事件 source=防御方/
        target=攻击方（语义：反弹伤害落到 event.target）；而 effects.deliver_reflect
        以 event.source 为受击方（sub.target=event.source）。两者方向相反——本层
        reshape（source↔target）后交付，使反弹伤害实际结算到**原攻击者**（=event.
        target），并保留 is_reflect_damage=True 关闭再弹（定稿 §3.5 / 1b §2 阶段③）。
        """
        reshape: Dict[str, Any] = {
            "damage": int(ev.get("damage", 0)),
            "source": str(ev.get("target", attacker)),   # 受击方 = 原攻击者
            "target": str(ev.get("source", target)),
        }
        base_ctx = DamageCtx(raw_damage=int(ev.get("damage", 0)), attack_type="basic",
                             attacker=attacker, target=target,
                             snapshot=self._snap, variables=self._base_variables(attacker, target))
        rr = DamagePipeline.deliver_reflect(self._pipeline, base_ctx, rt, reshape)
        self._absorb_runtime(rt)
        return rr

    def _action_outcome(
        self,
        attacker: str,
        action: Mapping[str, Any],
        target: str,
        rating: Mapping[str, Any],
        damage: Mapping[str, Any],
        effects: Sequence[Mapping[str, Any]],
        hp: int,
        battle_ended: bool = False,
        status: Optional[str] = None,
    ) -> ActionOutcome:
        return ActionOutcome(
            ok=True, seq=self._seq, actor=attacker,
            action_type=str(action.get("type", "normal")), target=target,
            hit=bool(rating.get("hit", False)), crit=str(rating.get("crit", "low")),
            blocked=bool(rating.get("blocked", False)),
            raw_damage=int(damage.get("final", 0)), final_damage=int(damage.get("final", 0)),
            target_hp=hp, side_effects=self._seal_side_effects(effects),
            message=f"{attacker} 对 {target} 造成 {damage.get('final', 0)} 伤害",
            battle_ended=battle_ended, status=status,
            backstab=bool(rating.get("backstab", False)),
            crit_mult=rating.get("crit_mult"),
        )

    def _with_extra_effects(
        self, out: ActionOutcome, extra: Sequence[Mapping[str, Any]]
    ) -> ActionOutcome:
        """在既有 outcome 的 side_effects 尾部追加引擎级事件（frozen；replace 整包复制）。"""
        if out is None or not extra:
            return out
        return replace(out, side_effects=tuple(out.side_effects or ()) + tuple(extra))

    def _after_actor_action(self, actor: str) -> None:
        """ACTOR_TURN_END 位点（CTB 重写，M4/M9/M10）：行动者完成后收尾 + 推进时间。

        这是「一次行动结束」的唯一收口，承担旧 `end_turn` ⑥ tick 拆下来的各项：
          - 霸体窗口关闭（D2：行动阶段结束）；
          - 技能冷却递减（该施放者本侧 -1，M9）；
          - transform 形态 tick（持有者，M10）+ dispel 延迟还原（M8）；
          - 跃空窗口维护（初始化/延长——增补 v1 §四）+ 到期自动落地（R16）；
          - **行动收尾 DOT / 吸收回复 / 持续双维扣减**（`tick_turn_end`，2026-09-10 整合）；
          - **行动条重签**：把该 actor 的下一次 ready 交给调度器（recovery 注入）。

        2026-09-10 整合（缺口修复）：旧 `end_turn` ⑥ 的 `effects.tick_turn_end`
        此前**无任何调用点**——`tick="turn_end"` 的 DOT（含 `part_break_per_tick`
        破位）、伤害吸收行动收尾回复、regen、持续双维扣减、限时印记 remaining_turns
        扣减全部**静默失效**。CTB 下「回合末」的等价位点 = 该行动者的 ACTOR_TURN_END
        （映射规则：回合结束 DOT → 行动者 `actor_action_end`，见 01_asset_inventory
        §0.2 事件位点词典）。

        **注意本函数只对「持有行动收尾状态的那一侧」结算**：`tick_turn_end(snapshot,
        runtime)` 签名不带 actor（它内部按 BATTLE_SIDES 遍历双方），故这里不能
        按 `actor` 过滤——DOT 挂在谁身上就扣谁的血（08:25 旧回合制里双方同时结算，
        CTB 下改为**任一行动者收尾时统一结算双方**，保证 DOT 结算频率与旧语义等价：
        每个行动边界结算一次）。
        """
        if self._finished:
            return
        self._armor_active[actor] = False   # D2：霸体窗口=行动阶段结束
        # 防反/闪反姿态窗口到期清理（时间口径，增补 v1 §一，2026-09-11）：到期即
        # 自然结束（now >= cast_time + action_time → 移除）；与持有者是否再次行动
        # 无关（原 R10「随持有者行动过期」计数口径已退役）。
        self._expire_counter_stance()
        # M9/M10/M8/R16：该行动者侧的各项 tick 归位到 AFTER_ACTION
        self._tick_skill_cooldowns(actor)
        self._tick_transform_state(actor)
        # 跃空窗口（增补 v1 §四）：初始化/延长（玩家行动使用攻击/技能）→ 到期判定
        self._update_air_window(actor)
        self._settle_air_landing()
        # 行动收尾状态结算（旧 end_turn ⑥：turn_end DOT / 吸收回复 / 持续双维扣减）
        # 结算后须复核死亡（DOT 可能致死）——致死则立即终局，不再推进时间轴。
        try:
            _te_log = tick_turn_end(self._snap, self._new_runtime())
            if _te_log:
                self._snap.setdefault("turn_end_log", []).extend(_te_log)
                self._death_check_side("player", "turn_end_dot")
                self._death_check_side("enemy", "turn_end_dot")
                self._sync_scheduler_deaths()
        except Exception:  # noqa: BLE001 - 兜底不崩：行动收尾结算异常不阻断时间轴
            _logger.exception("tick_turn_end 结算失败：actor=%s", actor)
        if self._finished:
            return
        # 行动条推进：该 actor 本次行动代价 = 该 action 的 recovery（唯一注入点）
        if self._ctb is not None:
            _rec = self._action_recovery(actor, self._last_action_of(actor))
            if actor == "player":
                self._ctb.complete_player_action(recovery=_rec)
            else:
                # NPC 的行动链由 advance_to_next_ready 内部 _auto_resolve_npc 已重签；
                # 此处兜底：若该 NPC 票据为空（如引擎直接 do_action("enemy", ...) 而
                # 非经调度器 auto-resolve），补一次重签，保证行动条不停滞。
                _view = self._ctb.get_actor(actor)
                if _view is not None and _view.ticket is None and _view.alive:
                    self._ctb._enqueue(_view, base_time=self._ctb.battle_time, recovery=_rec)
        self._sync_counts()
        # 行动后把时间轴推到下一个 ready（NPC 连锁自动推进 / 玩家 ready 暂停）。
        # 收口态恒为 `act`（CTB 唯一「交还行动条」落点）：res→act 为正常结算收尾；
        # skip/guard 等**未进入 res** 的路径本就处于 act → 幂等自迁（`act→act`）
        # 不得报非法（旧回合制靠 end_turn→start_turn 显式跨回合，CTB 无回合边界）。
        if self._state in (STATE_RES, STATE_ACT) and self._state != STATE_ACT:
            self._to_state(STATE_ACT, "action_end")
        self._resolve_ready_actor()

    def _last_action_of(self, actor: str) -> Optional[Mapping[str, Any]]:
        """取该 actor 最近一次提交的 action dict（recovery 解析用）。

        为什么从 `_last_action_dict` 取（而非 `action_record`）：record 只存
        `action`（atype 字符串），丢失 `skill_id`，无法解析技能 def 的 recovery。
        本字段由 `do_action` 在提交时写入，是 recovery 解析的准确来源。
        """
        if getattr(self, "_last_action_dict", None) is not None:
            return self._last_action_dict
        rec = self._snap.get("action_record") or []
        for entry in reversed(rec):
            if isinstance(entry, Mapping) and entry.get("actor") == actor:
                return {"type": str(entry.get("action") or "")}
        return None

    def _normalize_attack_type(self, atk: str) -> str:
        """内容层 attack_type 中文枚举 → 伤害通道 token（m2_shared_contract §四：斩/打/突/魔；
        伤害通道口径 slash/blunt/thrust/magic，battle L987/L1236）。未识别原样透传。"""
        return {"斩": "slash", "打": "blunt", "突": "thrust", "魔": "magic"}.get(str(atk), str(atk))

    def _ai_action_dict(self) -> Optional[Dict[str, Any]]:
        """M2-C1：MonsterAI 决策产出 action_dict（enemy_act None 分支，contract §六）。

        依据：m2_shared_contract §六（enemy_act None 时用 MonsterAI.decide 产出行动，
        走既有 _do_action 执行通道）＋ §五（action_dict 形态：{type, skill_id, mult, kind,
        action_id, action, source, ai_state, [charging|progress|chain_id]}）。
        - decide 同步更新 battle_state['ai_state']（原地）；返回 ai_state 回灌快照（吸收返回，
          contract §六）；MonsterAI 无状态，ai_state 以快照为权威。
        - 执行侧字段合并：action 定义（decide 已把 power→mult）的 attack_type/armor/effects
          归一化到 action_dict 顶层（T24 同构双库：技能=怪物行动=一次出手，复用玩家伤害通道）。
        - 无 AI 注入 / decide 异常返回 None → 调用方落 M1 默认普攻。
        - M11 批4 A3 P1-3：PVP 战斗（battle_type=="pvp"）防守方无 AI → 一直防御
          （定稿 L352「防守方不操作则一直防御」；玩家互斗非镜像场景防守方离线/
          不操作=恒 guard，不自动普攻反击）。
        """
        if self._snap.get("battle_type") == "pvp":
            return {"type": "guard", "mult": 1.0}
        if self._enemy_ai is None:
            return None
        try:
            act = self._enemy_ai.decide(self._snap)
        except Exception as exc:  # M2 审查 P2-1：decide 异常回落 M1 默认普攻（docstring 承诺落地）
            self._snap.setdefault("ai_errors", []).append(str(exc)[:200])
            import logging  # noqa: PLC0415
            logging.getLogger("qbot_rpg.ai").warning("MonsterAI decide 异常: %s", exc)
            return None
        if not isinstance(act, Mapping):
            return None
        ai = act.get("ai_state")
        if isinstance(ai, Mapping):
            self._snap["ai_state"] = ai  # 回灌快照（吸收返回）
        # M2 审查 P1-1：combo_broken 为「本次行动连招被打断」一次性标记——
        # 打断同一次行动的怪物决策（本轮反击）应命中一次（立即反应），决策后清除，
        # 防跨行动/跨快照续玩无限期触发（monster_conditions._eval_combo_broken 消费）
        self._snap.pop("combo_broken", None)
        ad = dict(act)
        ad.pop("ai_state", None)  # 已回灌，不随行动 dict 下传
        # 蓄力起手/进度播报（charging）与起身演出（get_up）：占行动槽不造成伤害
        # （细化_1f：蓄力起手行动播报 1/N；起身演出占用行动槽；行动本体在 L0 释放/起身完成）
        if ad.get("charging") or ad.get("kind") == "get_up":
            ad["mult"] = 0.0
        adef = ad.get("action")
        if isinstance(adef, Mapping):
            atk = adef.get("attack_type")
            if atk:
                ad.setdefault("attack_type", self._normalize_attack_type(atk))
            ad.setdefault("armor", bool(adef.get("armor", False)))
            ad.setdefault("effects", list(adef.get("effects") or []))
            # 方位 v0.6（附录 A Step 1/Step 3）：position_rule / air_policy 随行动定义
            # 透传顶层（ActionCore 共用键：miss 检查读 position_rule；行动收尾读
            # air_policy 结算——怪侧配置 land 且自身空中时同样落地）
            ad.setdefault("position_rule", adef.get("position_rule"))
            ad.setdefault("air_policy", adef.get("air_policy"))
        return ad

    def _interrupt_enemy_ai(self) -> bool:
        """M2-C1：玩家 interrupt 命中怪物 → 套完结（contract §六 / 细化_1f ⑤5.4 核心规则3）。

        怪物连招（chain_queue / exec_state=in_chain）与蓄力（exec_state=charging）被打断：
        - 在途链 → monster_chains.on_chain_broken（清队列、回 idle、当前链进冷却，
          下次行动走随机流程 L6，不继续原套）；
        - 蓄力 → 清除 charge（蓄力可被打断；armor=true 霸体免疫，细化_1f ①1.1 核心规则7）；
        - 免疫检查：蓄力 charge.armor、战斗瞬态 armor_active（1c2 §2.2 霸体窗口）、
          效果系统 I3 打断免疫（effects.immune_to_interrupt，1b §4.4）。
        返回是否实际打断（供消息/测试）。链节点 armor（finisher 霸体）细化留 M3（TODO）。
        """
        ai = self._snap.get("ai_state")
        if not isinstance(ai, dict):
            return False
        exec_state = ai.get("exec_state")
        # M2 审查 P2-2：在途链判定以 chain_queue 为真（真实在途链必有非空队列）——
        # 单行动（长度 1 套）执行后 exec_state 停留 in_chain 是执行中态，非在途链，
        # 避免对已完成单行动的打断误判（on_chain_broken 无链可断 + combo_broken 误置）
        in_chain = bool(ai.get("chain_queue"))
        charging = exec_state == "charging"
        if not (in_chain or charging):
            return False
        if bool(self._armor_active.get("enemy", False)):
            return False
        ch = ai.get("charge") or {}
        if charging and bool(ch.get("armor")):
            return False
        rt = self._new_runtime()
        if rt.immune_to_interrupt("enemy", self._combat("enemy").get("defenses")):
            return False
        broken_chain = ai.get("chain_id")
        if in_chain:
            on_chain_broken(ai)
        if charging:
            ai["charge"] = None
            ai["exec_state"] = "idle"
        # 打断标记（monster_conditions._eval_combo_broken 消费：本次行动连招被打断 →
        # 下次行动 L3 可评估 combo_broken 触发行动，细化_1f ②L3）
        self._snap["combo_broken"] = True
        self._snap.setdefault("combo_events", []).append({
            "type": "monster_chain_broken", "side": "enemy",
            "chain_id": broken_chain, "charge_cleared": bool(charging),
        })
        return True

    def enemy_act(self, action_dict: Optional[Mapping[str, Any]] = None) -> Optional[ActionOutcome]:
        """【删除】纯回合制产物：「玩家先手 → 怪物固定后手反击」的先/后手对。

        CTB 无先手/后手对——怪物与玩家由行动条公平竞争 ready，走**同一条**
        `ACTOR_READY → BEFORE_ACTION → ACTION_RESOLVE` 通道（Wave A M5 语义等价性
        论证）。按硬约束保留同名签名壳并抛 NotImplementedError，以暴露未迁移的
        误用调用点（已知 A1 级：`core/pvp.py:350`）。

        替代：怪物行动由 `CTBScheduler` 在 NPC ready 时自动推进（`_auto_resolve_npc`），
        行动内容经 `_ai_action_dict()`（MonsterAI 决策，已平移）产出。
        """
        raise NotImplementedError(
            "enemy_act 已随 CTB 重写删除：CTB 无先手/后手对，怪物与玩家同走 ACTOR_READY "
            "通道（Wave A M5）。怪物行动由调度器在 NPC ready 时自动推进；"
            "PVP 防守方请改走 CTB 行动推进接口。"
        )

    def end_turn(self) -> TurnReport:
        """【删除】纯回合制产物：「整轮收尾」（⑥tick → ⑦互杀 → ⑧结束 → ⑨下一回合）。

        CTB 无「一轮」边界 → 集中结算点不存在（Wave A M4）。其内部各 tick 已逐项
        拆挂到各自事件位点，**能力未丢失**：
          - 行动收尾 tick（持续扣减/效果衰减/吸收回补/再生）→ `AFTER_ACTION`（行动者）；
          - 玩家/敌方 DOT（tick=turn_end）→ 行动者 `ACTOR_TURN_END`；
          - 空中姿态落地 → `AFTER_ACTION`（`_settle_air_landing`）；
          - 怪物 AI 冷却 → 该 AI 自身行动后（`AFTER_ACTION`）；
          - transform / 技能冷却 → 持有者行动后（`_after_actor_action`，M9/M10）；
          - 换季边界 → `BATTLE_TIME_ADVANCE`（M11）；
          - 互杀/终局 → `BATTLE_END`（`_resolve_battle_end`）。

        按硬约束保留同名签名壳并抛 NotImplementedError，以暴露未迁移的误用调用点。
        """
        raise NotImplementedError(
            "end_turn 已随 CTB 重写删除：CTB 无「整轮收尾」集中结算点（Wave A M4）。"
            "各项 tick 已拆挂到 AFTER_ACTION / ACTOR_TURN_END / BATTLE_TIME_ADVANCE / "
            "BATTLE_END 位点；时间推进请用 _after_actor_action / start_turn（推进行动条）。"
        )

    def _snapshot_pos(self, side: str) -> Optional[Tuple[str, str]]:
        """快照当前方位（side/height 原值）；缺段/非法 → None（HUD 省略）。"""
        try:
            cp = self._snap.get("combat_position")
            ent = cp.get(side) if isinstance(cp, Mapping) else None
            if not isinstance(ent, Mapping):
                return None
            s = str(ent.get("side") or "")
            h = str(ent.get("height") or "")
            if s not in ("front", "back", "left", "right") or h not in ("ground", "air"):
                return None
            return (s, h)
        except Exception:  # noqa: BLE001 - HUD 方位缺失不阻断
            return None

    def _turn_report(self, log: Sequence[Mapping[str, Any]] = ()) -> TurnReport:
        return TurnReport(
            turn=self.action_seq,        # CTB（R18）：action_seq 镜像（不参与计算）
            player=int(self._combat("player").get("hp", 0)),
            enemy=int(self._combat("enemy").get("hp", 0)),
            ended=self._finished,
            status=self._snap.get("status") if self._finished else None,
            log=tuple(log),
            player_pos=self._snapshot_pos("player"),
            enemy_pos=self._snapshot_pos("enemy"),
            action_seq=self.action_seq,   # CTB 权威进度计量
            battle_time=self.battle_time,  # CTB 权威时间计量
            _phase_label=(self._phase,),   # 事件位点（旧读方经 .phases 属性读取）
        )

    def action_report(self) -> ActionReport:
        """CTB 行动报告（只读投影；契约字段 `action_seq`，无 `phases`）。

        tests/ctb/test_ctb_contract_interfaces.py 要求报告形态含 action_seq、不含
        回合相位——本方法即该契约的实现：把 CTB 双计数 + 当前事件位点投影为
        `ActionReport`。`player_act` 的返回容器仍是 TurnReport（签名零改动），
        本方法是新增只读查询，供新读方（展示层）使用。
        """
        return ActionReport(
            action_seq=self.action_seq,
            battle_time=self.battle_time,
            actor=self._current_actor,
            events=tuple(str(e.get("event") or "") for e in self._ctb_event_log[-8:]),
            nested={
                "player": int(self._combat("player").get("hp", 0)),
                "enemy": int(self._combat("enemy").get("hp", 0)),
            },
        )

    def player_act(self, action: Any, params: Any = None) -> TurnReport:
        """玩家提交一次行动并推进到下一个 ready（CTB 公开主入口，签名零改动）。

        CTB 语义（Wave A §1.11）：旧「整轮：先手 → 后手 → tick → 结算」→
        「提交一次玩家行动 → 结算 → **行动条推进到下一个 ready actor**」。
        一次 `player_act` = 一次玩家行动；推进后 NPC 连锁由调度器自动走完，
        直到下一个玩家 ready（暂停）或终局。

        **R-6（裁决 2）**：行动被拒 → 零时间成本——不推进行动条、不解除暂停、
        不派发后续事件；返回被拒报告，调用方可立即换可行指令重试。

        action 支持 str（'normal'/'guard'/'flee'/'skill:id'）或 dict；
        返回 TurnReport（含 outcomes 流水，字段语义见 TurnReport docstring）。
        """
        # 玩家 ready 前置推进行动条：把控制权推到玩家拍（含 NPC 连锁自动推进）。
        # 幂等：若当前已处于玩家暂停态，_resolve_ready_actor 不重复消费。
        # NPC 行动 outcome 属「上一次推进」产物 → 本次报告前清空，只收本拍内容。
        self._npc_outcomes = []
        if self._ctb is not None and not self._ctb.paused and not self._finished:
            self._resolve_ready_actor()
        pre_npc = list(self._npc_outcomes)   # 押到玩家拍之前的 NPC 连锁行动
        self._npc_outcomes = []
        if self._finished:
            return self._turn_report()

        action_dict = self._normalize_action(action, params)
        # 背击窗口（B5 背击闭环，2026-09-11 批④）：**捕获行动前侧位**——本次行动于
        # 该侧位结算（side=back → 背击加成）；结算**后**怪才转回面向（转向事件 +
        # 行动条成本，见 _face_enemy）。重定位类行动（行动前=front、行动把 side
        # 移到 back/left/right）不触发转向；被拒行动零成本不触发（R-6）。
        _pre_side: Optional[str] = None
        try:
            from qbot_rpg.core.position import position_of  # noqa: PLC0415

            _pre_side = position_of(self._snap, "player")[0]
        except Exception:  # noqa: BLE001 - 方位读取失败按缺省正面（不阻断行动）
            _pre_side = "front"
        outcomes: List[ActionOutcome] = []
        res = self.do_action("player", action_dict)
        if getattr(res, "ok", True):
            _turn_ev = self._face_enemy(_pre_side)
            if _turn_ev is not None:
                res = self._with_extra_effects(res, (_turn_ev,))
        outcomes.append(res)
        # 玩家行动收尾推进行动条时，期间自动结算的 NPC 行动 outcome 并入本报告
        # （Render 通道：渲染层按 outcomes 顺序产出「怪物行动行」）。
        outcomes.extend(self._npc_outcomes)
        self._npc_outcomes = []
        # R-6（裁决 2）：被拒 = 零时间成本、直接重试——不推进行动条、不解除暂停，
        # 保持当前 ready 等玩家下一个可行指令；拒绝原因经 log/outcome 上报。
        if not getattr(res, "ok", True):
            return TurnReport(
                turn=self.action_seq,
                _phase_label=(self._phase,),
                player=int(self._combat("player").get("hp", 0)),
                enemy=int(self._combat("enemy").get("hp", 0)),
                ended=self._finished,
                status=self._snap.get("status") if self._finished else None,
                log=tuple(getattr(res, "side_effects", ()) or ()),
                outcomes=tuple(pre_npc) + tuple(outcomes),
                player_pos=self._snapshot_pos("player"),
                enemy_pos=self._snapshot_pos("enemy"),
                action_seq=self.action_seq,
                battle_time=self.battle_time,
            )
        # 成功行动：`_after_actor_action` 已推进行动条（complete_player_action 解除
        # 暂停 + 重签票据 + 推 NPC 连锁）——此处仅汇总本次推进的日志/结果。
        # 2026-09-10 修复：先同步 CTB 双计数进快照，再构造报告——否则 report 与
        # battle_state() 的 action_seq/battle_time 落后于调度器（契约要求一致）。
        self._sync_counts()
        log = list(getattr(res, "side_effects", ()) or ())
        return TurnReport(
            turn=self.action_seq,
            _phase_label=(self._phase,),
            player=int(self._combat("player").get("hp", 0)),
            enemy=int(self._combat("enemy").get("hp", 0)),
            ended=self._finished, status=self._snap.get("status"),
            log=tuple(log), outcomes=tuple(pre_npc) + tuple(outcomes),
            player_pos=self._snapshot_pos("player"),
            enemy_pos=self._snapshot_pos("enemy"),
            action_seq=self.action_seq,
            battle_time=self.battle_time,
        )

    def _normalize_action(self, action: Any, params: Any = None) -> Mapping[str, Any]:
        """玩家指令归一化：str（'normal'/'guard'/'flee'/'skill:id'）或 dict。"""
        if isinstance(action, Mapping):
            return dict(action)
        if not isinstance(action, str):
            raise ValueError(f"无法识别的行动指令：{action!r}")
        act = action.strip()
        if act == "normal":
            return {"type": "normal"}
        if act in ("guard", "defense"):
            return {"type": "guard"}
        if act in ("flee", "run"):
            return {"type": "flee"}
        if act.startswith("skill:"):
            sid = act.split(":", 1)[1]
            return {"type": "skill", "skill_id": sid, **({} if params is None else {"mult": float(params)})}
        raise ValueError(f"无法识别的行动指令：{action!r}")

    # ------------------------- 快照续战（1g3） -------------------------

    def to_snapshot(self, boundary: Optional[str] = None) -> Dict[str, Any]:
        """战斗快照序列化（**CTB V2**）。

        契约（tests/ctb/test_ctb_contract_interfaces.py · TestToSnapshotContract）：
          - `schema_version >= 2`（CTB 新格式；V1 为回合制产物，删档后不再产出）
          - `rule_version = "battle_ctb_v1"`
          - 含 RNG 状态：顶层 `random_seed` + `rng_state`（缺失则续战随机序列不可复现）
          - 落点为 CTB 边界，**不再是 turn_start / turn_end**
          - 全量 JSON 可序列化

        :param boundary: 落点标注（CTB 边界名，如 "actor_ready" / "after_action"）；
            None → 按当前态推导（未结束 → "actor_ready"；已结束 → "battle_end"）。
        :raises BattleStateError: 结算中/死亡判定中（状态不确定）不落快照。
        :raises ValueError: 非法落点名。
        """
        if self._state in (STATE_RES, STATE_DTH):
            raise BattleStateError("结算/死亡判定中不落快照（状态不确定）")
        if boundary is not None and boundary not in CTB_BOUNDARIES:
            raise ValueError(
                f"非法快照落点：{boundary!r}（CTB 边界仅 {sorted(CTB_BOUNDARIES)}）"
            )
        snap = copy.deepcopy(self._snap)
        # ---- CTB V2 头（旧 turn 语义由 battle_time/action_seq 双计数承载）----
        snap["schema_version"] = 2
        snap["rule_version"] = str(self._config.get("rule_version", CTB_RULE_VERSION))
        snap["snapshot_id"] = str(uuid.uuid4())
        snap["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        bnd = boundary or ("battle_end" if self._finished else "actor_ready")
        snap["snapshot_at"] = {
            "boundary": bnd,
            "battle_time": self.battle_time,
            "action_seq": self.action_seq,
            # 兼容镜像：世界层快照完整性校验要求 turn 键（R-A）。= action_seq 镜像，
            # **不参与任何数值计算**（CTB 无回合数，R1–R20 已全部改由双计数承载）。
            "turn": self.action_seq,
        }
        snap["snapshot_context"] = {
            "mode": str(self._snap.get("battle_type", "normal")),
            "map_id": str(self._snap.get("battle_type", "")),
            "zone": "normal",
        }
        snap["_engine_state"] = self._state
        snap["_guard_active"] = dict(self._guard_active)
        snap["_death_order"] = list(self._death_order)
        # ---- CTB 行动条快照（续战时间轴连续的关键）----
        # 存每个单位的下次 ready 时刻（含当前单位）+ 调度器代数/时刻；续战据此
        # 精确重建行动条，避免「重算 ready」导致的时间漂移（vs 仅存 battle_time）。
        if self._ctb is not None:
            snap["ctb_state"] = {
                "time": self._ctb.battle_time,
                "action_seq": self._ctb.action_seq,
                "paused_actor_id": self._ctb.paused_actor_id,
                "actors": [
                    {
                        "actor_id": v.actor_id,
                        "side": v.side,
                        "effective_speed": v.effective_speed,
                        "is_player": v.is_player,
                        "alive": v.alive,
                        "next_ready": v.next_ready,
                    }
                    for v in self._ctb.actors()
                ],
            }
        else:
            snap["ctb_state"] = None
        # ---- RNG 状态（顶层，契约要求；formula_state 内保留同值以兼容旧读方）----
        snap["random_seed"] = self._rng_seed
        try:
            snap["rng_state"] = list(self._rng.getstate())
        except Exception:  # pragma: no cover - 防御（rng 异常不阻断快照）
            snap["rng_state"] = None
        snap["formula_state"] = {
            "random_seed": self._rng_seed,
            "rng_state": snap["rng_state"],
        }
        return snap

    def snapshot(self) -> Dict[str, Any]:
        """旧名兼容：to_snapshot() 别名（M1 占位签名升级，细化_1g3）。"""
        return self.to_snapshot()

    def record_alchemy_used(self, n: int = 1) -> int:
        """M8 批9（BA-02/IF-B03）：战斗即时调合次数累计。

        Step 5 迁移（方位 v0.6 §三.7）：权威落 battle_resources.battle_alchemy_used
        （段内优先读，顶层兜底兼容旧快照）；顶层键同步镜像写（旧读方/旧快照形态
        一致）。由战斗接线方在 /即时调合 结算后调用（中断恢复沿用快照值不清零；
        新战斗 start 重建 _snap 自然清零）。返回累计值。
        """
        br = self._snap.setdefault("battle_resources", {})
        cur = int(br.get("battle_alchemy_used",
                         self._snap.get("battle_alchemy_used", 0)) or 0)
        cur = cur + int(n)
        br["battle_alchemy_used"] = cur
        self._snap["battle_alchemy_used"] = cur
        return cur

    def interrupt_snapshot(self) -> Dict[str, Any]:
        """中断信号落快照：等待 CTB 边界（该 actor 行动收尾后），结算中抛错。

        CTB 重写（§1.11 `interrupt_snapshot` / S8）：旧「等待回合边界（回合开始前/
        回合结束 tick 后）」→ 新「等待 CTB 边界（actor_ready / after_action）」。
        不变量保留：结算中/死亡判定中（状态不确定）不落快照。
        """
        if self._state in (STATE_RES, STATE_DTH):
            raise BattleStateError(
                "中断信号排队到行动边界处理（当前结算/死亡判定中，CTB 不落不确定态快照）")
        return self.to_snapshot()

    @classmethod
    def from_snapshot(
        cls,
        data: Mapping[str, Any],
        pipeline: Optional[DamagePipeline] = None,
        registry: Any = None,          # RSM-03：世代重绑定注入（P0-1 续战旧配置修复，M6 D3）
        defs: Optional[Mapping[str, Any]] = None,
        config: Optional[Mapping[str, Any]] = None,
        enemy_ai: Any = None,
        enemy_def: Optional[Mapping[str, Any]] = None,
        ai_action_lib: Any = None,
        ai_rng: Any = None,
        resource_registry: Any = None,  # M13 6c：资源轴注册表注入（RS-2 恢复按注册表逐轴口径）
        combo_engine: Any = None,  # 2026-09-07：连段引擎显式注入（raw defs resolver——绕 registry Def 坑）
    ) -> "BattleEngine":
        """快照还原（CTB V2 续战）：还原最近边界状态 → 重建行动条 → 回到行动选择。

        死亡判定已先于快照写入：恢复后状态=最近边界，无歧义。
        随机种子随 `random_seed` + `rng_state`（顶层，V2 权威位）恢复 → 续玩随机
        序列一致（同种子同序列契约）。
        M2-C1（contract §六）：ai_state 随快照原样还原（MonsterAI 写入内容不丢）；
        enemy_ai/enemy_def 透传构造（MonsterAI 无状态=配置，需随还原引擎重建）。

        registry（M6 D3 RSM-03）：内容包配置源注入——续战世代重绑定（RSM-04）按快照
        registry_generation 从 watcher 取档重建 Registry 后传入，引擎按旧 registry
        解析 effects/statuses/marks（旧局旧配置，杜绝旧 combatant 数值 + 新解析混跑的
        半套配置）；__init__ 已有 registry 参数，本方法透传；缺省 None 走默认
        defs/pipeline 解析（旧快照无世代 → RSM-04 降级）。
        """
        # ---- CTB V2 门槛（删档决策）：只吃 V2，V1 显式拒绝，不得静默降级 ----
        # V1 快照承载回合语义（turn 驱动），与 CTB 时间轴（battle_time/action_seq）
        # 不可换算；带病续战会产出错误时序，故显式报错。
        _sv = data.get("schema_version")
        try:
            _sv_int = int(_sv) if _sv is not None else 0
        except Exception:
            _sv_int = 0
        if _sv_int < 2:
            raise ValueError(
                f"不支持的快照版本 schema_version={_sv!r}（CTB 只吃 V2 及以上；"
                "V1 为旧版格式，本项目已决策删档，不可续战）"
            )
        eng = cls(pipeline=pipeline, registry=registry, defs=defs, config=config,
                  enemy_ai=enemy_ai, enemy_def=enemy_def, ai_action_lib=ai_action_lib,
                  ai_rng=ai_rng, combo_engine=combo_engine)
        eng._resource_registry = resource_registry  # M13 6c：资源轴注册表透传（RS-2/RS-5）
        eng._snap = copy.deepcopy(dict(data))
        _fs = data.get("formula_state") or {}
        eng._rng_seed = int(
            data.get("random_seed", _fs.get("random_seed", 0)) or 0
        )
        # G3 续战修复：优先恢复 rng 内部状态（防随机序列重放）。
        # CTB V2：rng_state 走顶层（V2 权威位）；_rng_state 为 V1 旧键，保留兜底读。
        _rst = data.get("rng_state", data.get("_rng_state"))
        if isinstance(_rst, (list, tuple)) and _rst:
            try:
                # M12.5/veinborn rng 死区修复：to_snapshot 存 list(self._rng.getstate())
                # 只转外层——getstate 返回 (ver, tuple(ints), gauss)，list() 后内部 tuple
                # 变 list；JSON 往返后 setstate(tuple(list)) 内部仍是 list → TypeError →
                # 回落 seed 重播 → 每轮同 seed 序列重放（连续 miss 死区）。此处递归归一
                # 内部 tuple：setstate 契约 (version:int, state:tuple[int,...], gauss)。
                def _norm_rng_state(s: Any) -> Any:
                    if isinstance(s, list):
                        return tuple(_norm_rng_state(x) for x in s)
                    return s

                eng._rng = random.Random()
                eng._rng.setstate(_norm_rng_state(_rst))
            except Exception:  # pragma: no cover - 畸形 state 回落 seed
                eng._rng = random.Random(eng._rng_seed)
        else:
            eng._rng = random.Random(eng._rng_seed)
        eng._finished = data.get("status") not in (None, STATUS_ACTIVE)
        eng._guard_active = dict(data.get("_guard_active", {"player": False, "enemy": False}))
        eng._death_order = list(data.get("_death_order", []))
        eng._seq = len(eng._snap.get("action_record") or [])
        eng._effect_ids["player"] = []
        eng._effect_ids["enemy"] = []
        for side in BATTLE_SIDES:
            if side not in eng._snap:
                eng._snap[side] = dict(eng._snap.get("sides", {}).get(side, {}))
        # ---- CTB：重建行动条（恢复行动顺序的唯一权威）----
        # 快照不存调度器内部队列（删档口径：调度器状态可由 combatant + 计数重建）——
        # 以「当前逻辑时间 + 末次 ready 时刻」为基数重建，使续战时间轴连续。
        eng._snap.setdefault("action_seq", 0)
        eng._snap.setdefault("battle_time", 0.0)
        if eng._finished:
            # 终局快照：保持终态，不建行动条（无可推进）
            final_status = str(data.get("status") or STATUS_LOSE)
            eng._state = {STATUS_WIN: STATE_WIN, STATUS_LOSE: STATE_LOSE,
                          STATUS_ESCAPE: STATE_FLY, STATUS_DRAW: STATE_LOSE}.get(
                final_status, STATE_LOSE)
            eng._phase = PHASE_TURN_END_TICK
        else:
            # 非终局：回到行动选择，重建行动条（时间轴从快照 battle_time 起算）
            eng._state = STATE_ACT
            eng._phase = PHASE_PLAYER_ACTION
            eng._rebuild_scheduler(base_time=float(eng._snap.get("battle_time", 0.0) or 0.0))
        # M13 6c（细化_6c §1.4 RS-2/RS-5）：resource_state 中断恢复还原——按快照
        # 还原各资源当前值（续战从该值起算）；旧档缺 resource_state 段 → 按字段
        # 缺失降级（不报错不悬空，RS-5）；battle_start 型轴恢复后重置为 base
        # （F-R1 首行 + RS-2 合并口径）。注册表未注入 → 零操作降级（RS-5 精神）。
        try:
            from qbot_rpg.core.resource_lifecycle import (  # noqa: PLC0415
                ResourceLifecycle,
            )

            ResourceLifecycle(eng._resource_registry).restore_resource_state(
                eng._snap, data,
            )
            # RS-5「不悬空」：已删注册轴从 resource_state 段移除（字段缺失降级、
            # 显示隐藏）；仅当注入注册表时清理——未注入 → 原样保留（降级不破坏）。
            # RS-4 旧局旧配置：世代重绑定注入旧 registry 时旧轴仍在注册表内，
            # 不误删；仅当前 registry 已删的轴被清理。
            if isinstance(eng._resource_registry, Mapping):
                rs = eng._snap.get("resource_state")
                if isinstance(rs, dict):
                    for side in ("player", "enemy"):
                        side_state = rs.get(side)
                        if isinstance(side_state, dict):
                            for k in [
                                k for k in side_state
                                if k not in eng._resource_registry
                            ]:
                                del side_state[k]
        except Exception:  # noqa: BLE001 旧档畸形段 / 未注入注册表 → 降级不阻断续战
            pass
        eng._refresh_defenses()
        return eng

    def _rebuild_scheduler(self, base_time: float = 0.0) -> None:
        """重建行动条（快照续战 / 规则变更后调用）。

        依据当前 combatant 与快照 `ctb_state` 重建调度器：
          - 有 `ctb_state`（V2 完整快照）→ 逐单位还原 next_ready（精确续战）；
          - 无（旧档 / 规则变更）→ 以 `base_time` 为基数按公式重算 ready（降级）。
        死亡侧不入队（引擎侧死亡标记权威）。
        """
        self._ctb = self._make_scheduler()
        _ctb_state = self._snap.get("ctb_state")
        _aseq = int(self._snap.get("action_seq", 0) or 0)
        if isinstance(_ctb_state, Mapping):
            # 精确还原：时间锚 + action_seq + 各单位 next_ready
            self._ctb._action_seq = int(_ctb_state.get("action_seq", _aseq) or 0)
            _t = float(_ctb_state.get("time", base_time) or 0.0)
            self._ctb._time = _t
            _ready = {
                str(a.get("actor_id")): float(a.get("next_ready", _t) or _t)
                for a in (_ctb_state.get("actors") or [])
                if isinstance(a, Mapping)
            }
            _paused_aid = _ctb_state.get("paused_actor_id")
            _paused_aid = str(_paused_aid) if _paused_aid is not None else None
            for _view in self._ctb.actors():
                _view.ticket = None
                if not _view.alive:
                    continue
                if _view.actor_id == _paused_aid:
                    # 暂停中的玩家：其 ready 已在快照时消费，尚未重签 →
                    # 从当前时间按默认 recovery 重签（下一次 ready 在未来）。
                    self._ctb._enqueue(_view, base_time=_t)
                else:
                    # 未消费的单位：next_ready 直接还原（不经 recovery 递推）。
                    self._set_ready(_view, _ready.get(_view.actor_id, _t))
            # 暂停态还原：快照时玩家 ready 已消费 → 恢复为暂停等待输入
            if _paused_aid is not None:
                self._ctb._paused = True
                self._ctb._paused_actor_id = _paused_aid
        else:
            # 降级：无 ctb_state → 按公式从 base_time 重算
            self._ctb._action_seq = _aseq
            _t = float(base_time or 0.0)
            self._ctb._time = _t
            for _view in self._ctb.actors():
                _view.ticket = None
                if _view.alive:
                    self._ctb._enqueue(_view, base_time=_t)
        # 死亡侧退队（快照 status 未终局但某侧 dead_mark 的边界情况）
        for _side in BATTLE_SIDES:
            if self._dead(_side):
                self._ctb.mark_dead(_side)
        self._player_ready_pending = bool(self._ctb.paused)

    def _set_ready(self, view: Any, next_ready: float) -> None:
        """直接把某单位的下次 ready 设为给定值并签发票据（快照精确还原用）。

        与 `_enqueue` 区别：**不应用 recovery 递推**——next_ready 是快照里的原值。
        """
        try:
            ctb = self._ctb
            if ctb is None:
                return
            view.next_ready = float(next_ready)
            ctb._seq += 1
            from qbot_rpg.core.ctb_scheduler import CtbTicket  # noqa: PLC0415

            view.ticket = CtbTicket(
                actor_id=view.actor_id,
                generation=ctb._generation,
                ready_at=view.next_ready,
                seq=ctb._seq,
                side=view.side,
                effective_speed=view.effective_speed,
            )
        except Exception:  # noqa: BLE001 - 还原失败（视图异常）不阻断续战
            pass

    def resume(self, data: Mapping[str, Any]) -> "BattleEngine":
        """旧名兼容：快照续战（签名保留）。
        M2-C1：沿用当前 enemy_ai（MonsterAI 无状态，随还原引擎重建同配置实例）。
        M6 D3 RSM-03：registry 透传（self._registry 注入续战引擎——世代重绑定后按旧
        registry 解析，旧局旧配置）。CTB V2：还原后行动条由 from_snapshot 重建。"""
        return self.__class__.from_snapshot(
            data, pipeline=self._pipeline, registry=self._registry, defs=self._defs,
            config=self._config, enemy_ai=self._enemy_ai,
            resource_registry=self._resource_registry,  # M13 6c：资源轴注册表透传（RS-2）
        )

    # ------------------------- 服务查询 -------------------------

    def battle_state(self) -> Dict[str, Any]:
        """battle_state 查询（1g1c §1.1 唯一权威状态；深拷贝防串改）。

        CTB V2：额外挂 `random_seed` + `rng_state`（当前 RNG 快照），供续战可复现
        性校验（tests/ctb 契约：恢复后 rng_state 须与原局一致）。
        """
        st = copy.deepcopy(self._snap)
        st["random_seed"] = self._rng_seed
        try:
            st["rng_state"] = list(self._rng.getstate())
        except Exception:  # pragma: no cover - 防御
            st["rng_state"] = None
        return st

    def result(self) -> Dict[str, Any]:
        """结果标记（1g1c §1.3 / §1.2 五）。"""
        return copy.deepcopy(self._snap.get("result") or {})

    # ------------------------- 工具：JSON 往返测试辅助 -------------------------

    @staticmethod
    def _json_roundtrip(data: Mapping[str, Any]) -> Dict[str, Any]:
        return json.loads(json.dumps(dict(data), ensure_ascii=False))
