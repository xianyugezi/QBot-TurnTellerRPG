"""战斗引擎（M1-批2 重写 · 完整回合状态机 + 伤害闭环 + 快照续战）。

本模块是 QQ 回合制 RPG 的**战斗主循环唯一权威实现**（细化_1g1c B0：
battle_state 为本场战斗唯一权威状态）。零 NoneBot import（细化_3a R1）。

依据（全部引用细化节号，不编造行号）：
  - 细化_1g1a_战斗状态集：8 态定义（战前准备/行动选择/结算中/死亡判定/胜利/
    失败/逃跑/快照中断 §1-§9）＋ 主循环骨架（①dot→②即死→③先手→④击杀→
    ⑤后手→⑥tick→⑦互杀→⑧结束→⑨快照，§0）
  - 细化_1g1b_战斗迁移表：主迁移 8 条（T1-T8）+ 辅助 A1-A6 + 状态机不变量
    （§二/§三/§四：死亡判定两触发点、打死不鞭尸只在 BOSS/最后目标、快照只落
    回合边界、结算收尾单点、拦截链⑦扣血→⑧死亡判定）
  - 细化_1g1c_战斗状态数据：battle_state 字段级 schema（回合/相位/双方单位/
    action_record/result/combo_state/ai_state/stats_collector/timestamps）、
    TC-01..TC-30 验收用例（A 组正常回合 / B 组击杀 / C 组玩家死亡 / D 组逃跑 /
    E 组快照还原 / F 组连段清零）
  - 细化_1g2_回合时序与拦截链：回合时序 ①-⑨ 写死不可配（§1.2）、回合结束
    tick 顺序（§1.3）、拦截链 8 阶段挂载点（§2）
  - 细化_1g3_快照续战与测试：快照落点约束 S0-S3、字段级 schema §1.2、
    中断恢复流程 §2、验收用例 A-E 组
  - 细化_1g4_战斗世界边界：战斗引擎与世界/区域边界（奖励/掉落/快照清理登记
    归世界层收尾，本引擎只产出结果标记；§承接）
  - 细化_1b_效果系统契约（DamagePipeline/DamageCtx/EffectRuntime/tick_turn_end/
    tick_after_action）、细化_1a_伤害公式数值（十乘区纯函数）、细化_1c(连段)、
    细化_1f(怪物 AI)—— AI 仅留默认普攻反击钩子（后手，细化_1g2 §1.1）。
  - M2-C1（怪物 AI × 战斗引擎集成）：docs/m2_shared_contract.md §六（battle 挂接点：
    enemy_act None 分支用 MonsterAI.decide 产出行动 → 走既有 _do_action/_resolve_damage_action
    执行通道；决策后 ai_state 回灌快照；打断=套完结）＋ §五（ai_state 快照 14 键形态）＋
    细化_1f ⑥ TC-08/15/16/17/18。MonsterAI 只读注入（enemy_ai），本模块不改写 monster_ai.py。

【工程补白】（设计文档未显式定义、实现需收敛处，显式标注）：
  1. 工作快照形态：effects.damage_pipeline / tick_turn_end 要求 combatant 位于
     顶层键 player/enemy（ctx.snapshot[side] 直达，细化_1b §1.4 共享契约）——
     引擎工作快照以顶层 player/enemy 承载 combatant，1g1c 其余元字段
     （turn/result/action_record/...）以兄弟键承载，不嵌套 sides（与 effects
     输入契约对齐，登记 contract_deviation）。
  2. F-21/F-22/F-23（contract_deviations P1-2/P1-3/P1-6）：本模块是三个递延
     项的消费落点——F-21 战斗路径真实调用 pipeline.prepare_defense() 归一化
     防御行；F-22 消费反射 side_effect → DamagePipeline.deliver_reflect 回注
     攻击者（解析钉钉：effects.deliver_reflect 以 event.source 为受击方，与
     _stage_reflect 产出事件语义相反——本层 reshape 事件后再交付，见
     _resolve_damage_action docstring）；F-23 效果值聚合经 runtime.cap_boost/
     cap_combined 封顶（S6/S7）。
  3. 防御指令（×0.5，1g1a §2/细化_1a §1.8）以守卫位 guard_active 承载，
     回合结束 tick 后清零；被控/硬直（skip_turn）连段保留（1g1c TC-29）。
  4. 逃跑成功率/回合数/代价 = 定稿未定义（1g1a §7 待补），默认 100% 成功，
     config.flee_chance 可配；BOSS 禁逃可经 config.battle_flee_blocked_on_boss。
  5. 行动顺序：1g2 §1.1 先手=玩家/后手=怪物写死；config.actor_order="speed"
     时按 spd 降序 + 玩家平局优先（速度排序扩展，多单位实装预留）。

快照续战（1g3）：to_snapshot()/from_snapshot()/interrupt_snapshot() 全量 JSON
可序列化；中断只落回合边界（回合开始前 / 回合结束 tick 后），回合内落快照抛
BattleStateError（TC-05/E-05）；随机种子随 formula_state.random_seed 保存，
恢复后随机序列一致（4a TC-17）。
"""

from __future__ import annotations

import copy
import json
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

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

# 回合相位（细化_1g1c round_phase / 1g2 §1.2 时序 ①-⑨）
PHASE_TURN_START = "turn_start"
PHASE_PLAYER_ACTION = "player_action"
PHASE_ENEMY_ACTION = "enemy_action"
PHASE_TURN_END_TICK = "turn_end_tick"

# 战斗生命周期 status / result.flag（细化_1g1c §1.3）
STATUS_ACTIVE = "active"
STATUS_WIN = "win"
STATUS_LOSE = "lose"
STATUS_ESCAPE = "escape"
STATUS_DRAW = "draw"

# 合法迁移集（细化_1g1b 主迁移 T1-T8 + 辅助 A1-A6；非法迁移抛 BattleStateError）
#   T1 PREP→ACT（战前→行动，经 ①dot→②即死）      T7 SNP→PREP（快照还原）
#   T2 ACT→RES（行动提交）                       T3 RES→DTH（每段扣血后）
#   T4 DTH→LOSE（玩家死）  T5 DTH→WIN（怪物死）    T6 ACT→FLY（逃跑，边界）
#   T8/tick RES→ACT（下一行动者）  SNP/边界 ACT→SNP（快照中断）
_LEGAL_EDGES: frozenset = frozenset(
    {
        (STATE_PREP, STATE_ACT),     # 1g1b T1
        (STATE_PREP, STATE_SNP),     # 1g1b T7 中断落点（回合开始前）
        (STATE_ACT, STATE_RES),      # 1g1b T2
        (STATE_ACT, STATE_FLY),      # 1g1b T6 边界逃跑
        (STATE_ACT, STATE_SNP),      # 1g1b T7 边界中断
        (STATE_ACT, STATE_DTH),      # （P0-01 修复）回合开始 dot 即死通道：start_turn ① 段
                                     # 在 ACT 态挂 DTH（1g1b 不变量2 回合开始②；1g1c TC-02/13）
        (STATE_RES, STATE_DTH),      # 1g1b T3 每段扣血后
        (STATE_RES, STATE_ACT),      # 1g1b T8（下一行动者/后手）
        (STATE_DTH, STATE_RES),      # 1g1b T3 未死回结算 / 套内续段 A4
        (STATE_DTH, STATE_WIN),      # 1g1b T5 / A5 BOSS 即时结束
        (STATE_DTH, STATE_LOSE),     # 1g1b T4 / A1 即死直出
        (STATE_SNP, STATE_PREP),     # 1g1b T7 还原回 ①
    }
)

# 引擎级默认配置（对齐 1g1b §三 formula.json death_check 可配四项：L236-L239）
_BATTLE_DEFAULT_CONFIG: Dict[str, Any] = {
    # death_check 四项可配（1g1b §四 不变量1）
    "mutual_kill_basis": "order",        # 互杀判定基准 order/hp_ratio（L237）
    "mutual_kill_result": "draw",        # 互杀终态 draw/player_loss（L236）
    "no_target_action": "fallback",      # 后手无目标 fallback/skip（L238）
    "boss_end_immediate": True,          # BOSS/最后目标死→立刻结束（L239）
    # 逃跑（1g1a §7 定稿待补，工程补白④：默认 100% 成功）
    "flee_chance": 1.0,
    "battle_flee_blocked_on_boss": False,
    # 行动顺序（1g2 §1.1 先手写死 fixed；speed=按 spd 排序扩展，工程补白⑤）
    "actor_order": "fixed",
    "rule_version": "battle_v1.1.1",     # 1g1c rule_version（formula.json 对齐）
}

# combatant 缺失字段兜底（细化_1g1c §1.2 双方单位 + 1a 公式所需属性）
_DEFAULT_STATS: Dict[str, Any] = {
    "max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100,
    "atk": 50, "dfn": 50, "mag": 30, "spd": 50,
    "foc": 50, "con": 50, "str": 50, "int": 50, "agi": 50, "spr": 50, "lck": 50,
    "elem_atk": 0, "name": "",
}

# 五块效果快照键（细化_1b §1.4 / 定稿 §8.3）
_FIVE_BLOCKS: Tuple[str, ...] = (
    "status_state",
    "marks_state",
    "resist_table",
    "effect_triggers",
    "effect_cooldowns",
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


@dataclass(frozen=True)
class TurnReport:
    """一轮（先手→后手→tick→结算）报告（细化_1g2 §1.2 时序输出）。"""

    turn: int
    phases: Tuple[str, ...]
    player: int
    enemy: int
    ended: bool
    status: Optional[str]            # None=进行中
    log: Tuple[Mapping[str, Any], ...] = ()
    outcomes: Tuple[ActionOutcome, ...] = ()


@dataclass(frozen=True)
class BattleOutcome:
    """战斗终局（细化_1g1c §1.3 结果标记 + 收尾）。result 含可配终态。"""

    status: str                        # win/lose/escape/draw
    reason: str                        # 触发来源（标记名）
    turn: int
    resolve_at: str                    # "turn_end" / "immediate"
    combo_zeroed_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------


def _make_battle_resolver(
    registry: Any = None, defs: Optional[Mapping[str, Any]] = None
) -> Callable[[str, str], Any]:
    """归一化配置源为 callable(id, kind) -> Def|dict|None（对齐 effects._make_resolver）。"""
    if registry is not None:
        if callable(registry):
            return registry
        resolve = getattr(registry, "resolve", None)
        if callable(resolve):
            return lambda id_, kind: resolve(id_, kind)
    if defs is not None:
        return lambda id_, _kind: defs.get(id_)
    return lambda _id_, _kind: None


class BattleEngine:
    """1v1 回合战斗引擎（完整闭环）。

    主循环时序写死（1g1b 不变量1 / 1g2 §1.2）：①dot → ②即死 → ③先手 →
    ④击杀判定 → ⑤后手 → ⑥tick → ⑦互杀 → ⑧结束 → ⑨快照。
    BOSS/最后目标死亡 A5 立即结束；快照只落回合边界（不变量4）。
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
        self._params: DamageFormulaParams = params or DamageFormulaParams()
        # FIX-6 决策登记（细化_M6 测试体系强化 D6 §三 FIX-5/FIX-6 二选一 + §八）：
        # 段级参数当前仅默认值——battle 尚未从内容包 formula.json 装配段参数（JSON 段 →
        # DamageFormulaParams 的共享加载函数未落生产侧，测试侧读取器 = conftest
        # load_formula_params/formula_params fixture 已消费 fixtures 包）；内容包
        # formula.json 段参数暂无人消费，文档口径由 D6 §八 登记承接，生产装配随实现层
        # 规划 T01（formula.json 唯一配置源与校验器）落地。
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

    # ------------------------- 内部状态字段 -------------------------

    def _reset_state(self) -> None:
        self._state: str = STATE_PREP
        self._phase: str = PHASE_TURN_START
        self._snap: Dict[str, Any] = {}
        self._rng: random.Random = random.Random()
        self._rng_seed: Optional[int] = None
        self._seq: int = 0
        self._finished: bool = False
        self._guard_active: Dict[str, bool] = {"player": False, "enemy": False}
        self._turn_acted: Dict[str, bool] = {"player": False, "enemy": False}
        self._effect_ids: Dict[str, List[str]] = {"player": [], "enemy": []}
        # 霸体瞬态（1c2 §2.2：行动开始 → 本次结算完成；打断判定依据）
        self._armor_active: Dict[str, bool] = {"player": False, "enemy": False}
        self._death_order: List[str] = []   # 死亡登记顺序（互杀审计，1g1b A2）
        self._current_actor: Optional[str] = None      # 当前行动者（先手击杀判定，TC-11）
        self._qualified_kill_origin: bool = False      # 敌人死因=玩家行动直击（order 基准）

    # ------------------------- 状态机制 -------------------------

    @property
    def state(self) -> str:
        """当前状态（1g1b §一 状态变量 battle_state.phase）。"""
        return self._state

    @property
    def phase(self) -> str:
        """当前回合相位（1g1c round_phase）。"""
        return self._phase

    @property
    def finished(self) -> bool:
        """战斗是否已终局（win/lose/escape/draw 任意出口，1g1c §1.3）。"""
        return self._finished

    def _to_state(self, target: str, event: str) -> None:
        """状态迁移（1g1b §二 主迁移表）。非法迁移抛 BattleStateError。

        docstring 依据：1g1b §四 不变量 2「死亡判定唯一的两个触发点」与不变量 4
        「快照只落回合边界」；非法迁移（如直接 ACT→WIN、回合内落快照）在此拦截。
        """
        if self._state in (STATE_WIN, STATE_LOSE, STATE_FLY):
            if target in (STATE_WIN, STATE_LOSE, STATE_FLY) and self._state == target:
                return
            raise BattleStateError(f"战斗已终局（{self._state}），不允许迁移到 {target}（1g1b §一）")
        if (self._state, target) not in _LEGAL_EDGES:
            raise BattleStateError(
                f"非法状态迁移 {self._state}→{target}（事件 {event!r}，1g1b 迁移表未登记）"
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

        battle_map = {
            "round": int(self._snap.get("turn", 0)),
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
            "attacker": self._combat_map(attacker),
            "target": self._combat_map(target),
            "battle": {"round": int(self._snap.get("turn", 0))},
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
    ) -> int:
        """按「段」写入行动流水（1g1c §② B2：每段独立记录，收集时机=拦截链→扣血后）。"""
        self._seq += 1
        entry = {
            "seq": self._seq,
            "turn": int(self._snap.get("turn", 0)),
            "phase": phase,
            "actor": actor,
            "action": atype,
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
        生效→玩家胜）——仅当敌人死于玩家行动阶段时置位，回合开始 dot 双杀不入。
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
            {"trigger": trigger, "turn": int(self._snap.get("turn", 0)), "seq": self._seq}
        )

    def _death_check_side(self, side: str, trigger: str = "on_death") -> bool:
        """死亡判定（1g1b 不变量2：唯一两触发点 = 回合开始 ② / 每次扣血 ④）。

        返回 True=该侧新增死亡标记。调用方在拦截链⑦扣血后（含 dot 扣血、反弹回注）
        立即调用，且每个时段只挂一次 DTH（state 经 RES→DTH→RES 走一圈）。
        """
        if self._dead(side) and not self._combat(side).get("dead_mark"):
            self._to_state(STATE_DTH, fr"hit/{trigger}")
            self._mark_dead(side, trigger)
            self._to_state(STATE_RES, "continue")
            # 后手被先手击杀的怪物不执行反击 attr，A4/A5 由调用方按 BOSS 决定即时结束
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
                # 无先手击杀的双死（回合开始 dot 双杀等）→ 平局。原实现 L62 互杀一律平局已按拍板覆盖。
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
                return self._settle(STATUS_DRAW, "mutual_kill", reason_detail="同回合双死")

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

        - energy_cost：施放前检查（不足 → 被拒不耗回合，返回被拒 ActionOutcome）；
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
        # energy_cost 门禁（技能 def 段）
        cost = sd.get("energy_cost")
        if isinstance(cost, Mapping) and cost:
            ctx = self._resource_ctx(attacker, target, registry)
            for axis_id, cost_map in cost.items():
                if not isinstance(cost_map, Mapping):
                    continue
                ok = resource_axis.check_cost(ctx, str(axis_id), dict(cost_map), side=attacker)
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
                        f"能量不足（{axis_id}），技能被拒（不耗回合）")
                # 扣减
                resource_axis.pay_cost(ctx, str(axis_id), dict(cost_map), side=attacker)
        # energy_gain 结算（技能 def 段；成功施放后增加封顶）
        gain = sd.get("energy_gain")
        if isinstance(gain, Mapping) and gain:
            ctx = self._resource_ctx(attacker, target, registry)
            resource_axis.apply_gain(ctx, dict(gain), side=attacker)
        return None

    def _resource_ctx(self, attacker: str, target: str, registry: Any) -> Dict[str, Any]:
        """资源轴引擎 ctx 构造（注册表 + 双方 resource_state 注入）。"""
        from qbot_rpg.core.resource_axis import RESOURCE_STATE_KEY  # noqa: PLC0415

        state = self._snap.get(RESOURCE_STATE_KEY) or {}
        return {
            "stats": registry,
            RESOURCE_STATE_KEY: state,
        }

    def _tick_transform_state(self) -> None:
        """M13 6b（细化_6b §2.2/D-03）：transform 回合 tick（end_turn ⑥ 后）。

        - 形态剩余递减（remaining-1；自然结束 → 还原回常态 + 冷却起算）；
        - 冷却递减（S5 COOLDOWN 每回合 -1，归 0 回 NORMAL）。
        纯函数委托 transform_revert；无形态（form=null）→ 无操作。
        """
        from qbot_rpg.core.transform_revert import (  # noqa: PLC0415
            should_revert_natural,
            tick_cooldown,
            tick_remaining,
        )

        ts = self._snap.get("transform_state")
        if not isinstance(ts, dict):
            return
        if ts.get("form"):
            # 形态持续中：remaining 递减
            ts.update(tick_remaining(ts))
            if should_revert_natural(ts):
                # 自然结束还原：form 清空 + 冷却起算（transform 配置经 job 惰性解析，
                # 引擎层只做状态机迁移；具体 cooldown 值由装配层注入 job_def 时设置）
                ts["form"] = None
                ts["form_name"] = None
                ts["form_status_id"] = None
                ts["active_skill_set"] = None
        else:
            # 常态/冷却期：冷却递减
            ts.update(tick_cooldown(ts))

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
            turn=int(self._snap.get("turn", 0)),
            resolve_at=resolve_at,
            combo_zeroed_reason=zero_reason,
        )
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
        """最小战斗快照骨架（resolve_damage 无快照参数时的兜底，测试用；原样保留）。"""
        return {
            "session_type": "battle",
            "turn": 0,
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
        self._snap = {
            "session_type": "battle",
            "battle_id": str(uuid.uuid4()),
            "battle_type": battle_type,
            "status": STATUS_ACTIVE,
            "rule_version": str(self._config.get("rule_version", "battle_v1.1.1")),
            # P0-1 续战旧配置修复（M6 D3 RSM-02 / F-RSM-01）：世代绑定键——start 写当前
            # registry 世代；中断/回合边界快照经 to_snapshot 深拷贝自动沿用；旧快照缺该
            # 字段 → 续战入口兼容读取默认 0（走 RSM-04 降级）。
            # P2-RSM-05 修复：非数值 generation（畸形注入）回落 0，不崩（对齐 _num 防御口径）。
            "registry_generation": (
                int(getattr(self._registry, "generation", 0))
                if self._registry is not None
                and isinstance(getattr(self._registry, "generation", 0), (int, float))
                and not isinstance(getattr(self._registry, "generation", 0), bool)
                else 0
            ),
            "turn": 0,
            "round_phase": PHASE_TURN_START,
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
            # M8 批9 收口（BA-02/IF-B03）：战斗即时调合计数落战斗快照顶层键，
            # 中断恢复不清零、战斗结束由 start 重建清零——对齐 potion_use_counts 口径。
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
        }
        self._finished = False
        self._death_order = []
        self._guard_active = {"player": False, "enemy": False}
        self._armor_active = {"player": False, "enemy": False}
        self._turn_acted = {"player": False, "enemy": False}
        # 效果列表（F-21：effect_ids 装配源，玩家“装备”效果由外部注入）
        self._effect_ids.setdefault("player", [])
        self._effect_ids.setdefault("enemy", [])
        self._refresh_defenses()
        self.start_turn()
        return self

    def set_effect_ids(self, side: str, effect_ids: Sequence[str]) -> "BattleEngine":
        """装配某侧效果 ID 列表（F-21 prepare_defense 的 effect_ids 输入；1b 效果系统）。"""
        if side not in BATTLE_SIDES:
            raise ValueError(f"未知战斗侧：{side}")
        self._effect_ids[side] = list(effect_ids)
        self._refresh_defenses()
        return self

    def start_turn(self) -> TurnReport:
        """回合开始（1g2 §1.2 ①/②）：dot/持续伤害 + 控制结算 → 即死判定。

        ① 回合开始 dot 结算复用拦截链（1g2 §2.1 B；拦截链扣血后即查）；
        ② 即死判定（L46-48）——死则跳过其本回合行动 / A1 直出终局（1g1b A1）。
        """
        if self._finished:
            raise BattleStateError("战斗已终局，无法开始新回合（1g1c §1.3）")
        self._to_state(STATE_ACT, "start_turn")
        self._snap["turn"] = int(self._snap.get("turn", 0)) + 1
        self._phase = PHASE_TURN_START
        self._guard_active = {"player": False, "enemy": False}
        self._turn_acted = {"player": False, "enemy": False}

        # ① 回合开始 dot（tick=turn_start）经拦截链扣血
        rt = self._new_runtime()
        for side in BATTLE_SIDES:
            if not self._alive(side):
                continue
            c = self._combat(side)
            dots = c.get("dot_pool") or {}
            for dot_id in list(dots.keys()):
                dot = dots[dot_id]
                if isinstance(dot, dict) and dot.get("tick") == "turn_start":
                    src = str(dot.get("source") or self._opposite(side))
                    self.resolve_damage(src, side, int(dot.get("value", 0)),
                                        attack_type="status", snapshot=self._snap, runtime=rt)
                    self._absorb_runtime(rt)
                    self._death_check_side(side, "turn_start_dot")
                    rt_t = self._new_runtime()
                    if int(dot.get("turns", 0)) > 0:
                        dot["turns"] = int(dot["turns"]) - 1
                    if int(dot.get("turns", 0)) <= 0:
                        dots.pop(dot_id, None)
                    rt = rt_t
            # 控制结算：回合开始按控制剩余回合递减（1g2 §1.2 控制裁决；skip_turn）
            ctrl = c.get("control_state")
            if isinstance(ctrl, dict) and int(ctrl.get("turns", 0)) > 0:
                tn = int(ctrl.get("turns", 0)) - 1
                ctrl["turns"] = tn
                if tn <= 0:
                    c.pop("control_state", None)

        # ② 回合开始即死判定（A1 直出）
        if self._dead("player") or self._dead("enemy"):
            self._absorb_runtime(self._new_runtime())
            out = self._resolve_battle_end(force=True)
            if out is not None:
                self._phase = PHASE_TURN_START
                return self._turn_report()
        self._phase = PHASE_PLAYER_ACTION
        return TurnReport(
            turn=int(self._snap["turn"]), phases=(PHASE_TURN_START, PHASE_PLAYER_ACTION),
            player=int(self._combat("player").get("hp", 0)),
            enemy=int(self._combat("enemy").get("hp", 0)),
            ended=self._finished, status=self._snap.get("status"),
        )

    def action_order(self) -> Tuple[str, ...]:
        """行动顺序（1g2 §1.1 先手=玩家/后手=怪物，写死；活体过滤 + 死亡标记）。
        config.actor_order="speed" 时按 spd 降序、玩家平局优先（速度排序扩展）。
        """
        if not self._snap:
            return ()
        order = ["player", "enemy"]
        if str(self._config.get("actor_order", "fixed")) == "speed":
            def _key(side: str) -> Tuple[float, int]:
                c = self._combat(side)
                return (-float(c.get("spd", 0)), 0 if side == "player" else 1)
            order.sort(key=_key)
        return tuple(s for s in order if self._alive(s))

    def next_action_owner(self) -> Optional[str]:
        """下一个可行动者（⑤ 后手判定：被先手击杀的怪物不执行反击，1g2 §1.1 特例）。"""
        order = self.action_order()
        for side in order:
            if not self._turn_acted.get(side, False):
                return side
        return None

    def do_action(self, attacker: str, action_dict: Mapping[str, Any]) -> ActionOutcome:
        """行动入口（完整闭环）：命中→会心→格挡→双通道→总伤害→拦截链→扣血→
        死亡判定→状态 tick（1g2 §1.2/§三）。

        attacker ∈ {player, enemy}；action_dict 支持：
          - {"type":"normal"|"attack", "mult":1.0, "attack_type":"slash"|"blunt"|...,
             "elem_mult":0.0, "skill_id":...}
          - {"type":"skill", "skill_id":"...", "mult":2.0, ...}
          - {"type":"guard"|"defense"}                防御指令 ×0.5（1a §1.8）
          - {"type":"flee"|"run"}                     逃跑（回合边界，1g1b T6）
          - {"type":"item", "item_id":"...", "actions":[...]}  道具（L0 动作）
          - segments: [{...}] 连段/多段逐段结算（1g1c A-03/TC-07）
        返回 ActionOutcome（含 rating/damage/battle_ended）。
        """
        if self._finished:
            raise BattleStateError(f"战斗已终局（{self._snap.get('status')}），无法再行动（1g1c §1.3）")
        if attacker not in BATTLE_SIDES:
            raise ValueError(f"未知行动侧：{attacker}")
        if self._state not in (STATE_ACT, STATE_RES):
            raise BattleStateError(f"行动仅允许在行动选择/结算中发起（当前 {self._state}，1g1b T2）")
        if not self._alive(attacker):
            raise BattleStateError(f"{attacker} 已死亡/退场，不能行动（1g1b A1 跳过行动）")

        self._current_actor = attacker
        try:
            return self._do_action_inner(attacker, action_dict)
        finally:
            self._current_actor = None

    def _do_action_inner(self, attacker: str, action_dict: Mapping[str, Any]) -> ActionOutcome:
        atype = str(action_dict.get("type") or "normal")
        atype = {"attack": "normal", "defense": "guard", "run": "flee"}.get(atype, atype)
        self._phase = PHASE_PLAYER_ACTION if attacker == "player" else PHASE_ENEMY_ACTION
        self._turn_acted[attacker] = True

        if atype == "flee":
            return self._flee_actor(attacker)
        if atype == "guard":
            return self._guard_actor(attacker)

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
        raise ValueError(f"未知动作类型：{atype}（1g1b T2 动作词汇）")

    # ------------------------- 行动实现 -------------------------

    def _guard_actor(self, attacker: str) -> ActionOutcome:
        """防御指令（1a §1.8 ×0.5；1g1c TC-28 防御不打断连段保留）。"""
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
        self._after_actor_action(attacker)
        return ActionOutcome(True, seq, attacker, "guard", target, True, "low", False,
                             0, 0, int(self._combat(target).get("hp", 0)), (), "防御指令（本回合受击 ×0.5）")

    def _skip_turn(self, attacker: str) -> ActionOutcome:
        """被控制跳过行动（skip_turn 硬直，1g1c TC-29 连段保留）。"""
        target = self._opposite(attacker)
        seq = self._record_action(
            attacker, "skip", target,
            {"hit": False, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0},
            {"ch_phys": 0, "ch_elem": 0, "final": 0}, self._phase,
        )
        self._after_actor_action(attacker)
        return ActionOutcome(False, seq, attacker, "skip", target, False, "low", False,
                             0, 0, int(self._combat(target).get("hp", 0)),
                             ({"type": "skip_turn", "actor": attacker},), "被控制，跳过本回合行动")

    def _flee_actor(self, attacker: str) -> ActionOutcome:
        """逃跑（1g1b T6 / 1g1c TC-15..17：仅回合边界；成功后连段清零、退出战斗）。

        定稿未定义成功率/代价（1g1a §7 待补）——默认 100% 成功，config.flee_chance
        可配；BOSS 禁逃可经 config.battle_flee_blocked_on_boss；失败保留战斗与连段
        （1c1b L57 / 1g1c TC-16）。
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
        """道具（1g1c action_record action=item；TC-28 道具不打断连段、不耗回合）：
        经 L0 执行器跑道具 actions（heal/status_apply 等），跳过伤害链。"""
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
        self._after_actor_action(attacker)
        return ActionOutcome(True, seq, attacker, "item", target, True, "low", False,
                             0, 0, int(self._combat(target).get("hp", 0)), tuple(effects),
                             "道具使用成功")

    def _resolve_combo_action(self, attacker: str, action: Dict[str, Any]) -> ActionOutcome:
        """连段性行动（1c1a/b/c + 1c2）：combo 引擎判定 → 被拒短路 / 派生表单 → 伤害结算。

        M1-批3 主 agent 收口：combo.py 引擎已实现但本 battle 接线缺失（子代理撞迭代上限）。
        - ⑥ 被拒（MP/冷却/条件不足）：不改连段、不耗回合、可反复尝试（1c1c TC-DEF-04 /
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
        ca.setdefault("mult", float(ca.get("mult", 1.0)))
        # M13 批14 路14B：技能 def hits 多段展开（blade_dance hits=3 → 3 段伤害）。
        # 仅显式 hits>1 时展开（缺省 1 段不包 segments，保持既有单段路径零变化）。
        _hits = int(sd.get("hits", 1) or 1)
        if _hits > 1 and "segments" not in ca:
            ca["segments"] = [{"hit": True, "mult": 1.0} for _ in range(_hits)]

        def _marks_lookup(kind: str, which: str, rule: Mapping[str, Any], mark_id: Optional[str] = None) -> bool:
            # D1 定稿对照修复：combo 印记条件子句全量转接 MarksManager.evaluate（1d §3.1 唯一正确实现）
            side = attacker if which == "self" else target
            return self.marks_manager().evaluate(kind, side, dict(rule), mark_id)

        result = self.combo_engine().apply_action(attacker, ca, self._snap, self._armor_active,
                                                  marks_lookup=_marks_lookup)
        if result.rejected:
            # P1-5（dsh 批3）：被拒不耗回合——回滚 _do_action_inner 前置的 _turn_acted，
            # 否则 next_action_owner/to_snapshot 把被拒当已行动（"不耗回合"被打穿）。
            self._turn_acted[attacker] = False
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

        # ---- M13 6a 路3C：技能 MP 消耗扣费（1a §2.2 mp_cost 语义；被拒不扣）----
        # should_reject 已做 MP 门槛检查（enforce_mp 开）；成功施放后实际扣费。
        # mp_cost 优先 action 显式（skill_mp_cost/mp_cost），缺失回退技能 def。
        _mp_cost = int(ca.get(
            "skill_mp_cost", ca.get(
                "mp_cost", sd.get("mp_cost", 0))) or 0)
        if _mp_cost > 0:
            _c = self._combat(attacker)
            _mp = int(_c.get("mp", 0) or 0)
            if _mp >= _mp_cost:
                _c["mp"] = _mp - _mp_cost

        # ---- M13 6c 批12 收口：技能 energy_cost 门禁 + energy_gain 结算 ----
        # 技能 def 的 energy_cost（施放前检查：不足 → 被拒不耗回合，复用 rejected
        # 语义——返回被拒 outcome 不继续）+ energy_gain（成功结算后增加封顶）。
        _energy_gate = self._apply_skill_energy(attacker, ca, sd, target)
        if _energy_gate is not None:
            return _energy_gate

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
            # 下一回合随机流程；怪物连招走 ai_state，combo 引擎对怪物恒 no_active，
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
        # 霸体窗口=行动阶段结束（D2 修复：原在技能结算内清位→同回合敌后手打断不免疫，
        # 1c2 §2.2「使用期间」应为整个行动阶段；清位移至 _after_actor_action）
        out = self._resolve_damage_action(attacker, action)
        if hit_effects:
            out = ActionOutcome(
                out.ok, out.seq, out.actor, out.action_type, out.target, out.hit,
                out.crit, out.blocked, out.raw_damage, out.final_damage, out.target_hp,
                tuple(hit_effects) + out.side_effects, out.message,
                battle_ended=out.battle_ended, status=out.status,
            )
        return out

    def _resolve_damage_action(self, attacker: str, action: Dict[str, Any]) -> ActionOutcome:
        """伤害行动闭环（核心）：命中→会心→格挡→双通道→总伤害→拦截链→扣血→
        死亡判定（每段后）→ 反射回注（F-22）→ 状态衰减（D5）。

        段支持：action.get("segments") 为 [ {mult,...}, ... ] 时逐段结算（1g1c
        A-03/TC-07；套内击杀后续段照常 A4；BOSS/最后目标死亡 A5 立即结束）。
        \\
        """
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
            # ---- ① 命中（1a §1 签名：hit_rate(专注, 对方敏捷)）----
            focus = float(ac.get("foc", 50))
            espd = float(tc.get("spd", 50))
            hr = hit_rate(focus, espd, k=p.hit.k, cap_min=p.hit.cap_min, cap_max=p.hit.cap_max)
            if p.type_affinity.enabled and atk_type == "thrust":
                hr = min(p.hit.cap_max / 100.0, hr + p.type_affinity.thrust_hit)
            hit = self._roll() <= hr

            rating: Dict[str, Any] = {  # type: ignore[no-redef]
                "hit": hit, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0,
            }
            seg_damage: Dict[str, Any] = {"ch_phys": 0, "ch_elem": 0, "final": 0}  # type: ignore[no-redef]
            if not hit:
                # miss：伤害 0，仍写 action_record（提示未命中），不触发击杀判定（1g1c §② 命中行）
                self._record_action(attacker, str(action.get("type", "normal")), target,
                                    rating, seg_damage, self._phase)
                all_effects.append({"type": "miss", "target": target, "attacker": attacker})
                continue

            # ---- ② 会心（1a §1.4/§1.5：√幸运/2，三档）----
            lck = float(ac.get("lck", 50))
            super_crit_lv = int(ac.get("super_crit_lv", 0) or 0)
            crit_r = self._roll()
            # G1 定稿对照修复（damage 定稿对照 G1）：斩击会心 +5%（数值层 L92/L216
            # type_affinity.slash_crit）实战零生效——crit_prob 原全库零调用、crit_roll 无加成/
            # cap。现在先算有效 P（含 slash 加成 + cap 95，判定前应用，细化_1a §5-⑦）再判档。
            slash_bonus = p.type_affinity.slash_crit if atk_type == "slash" else 0.0
            p_eff = crit_prob(lck, p_coef=p.crit.p_coef, crit_bonus=0.0,
                              cap=p.crit.cap, slash_crit=slash_bonus)
            crit_id, crit_mult = crit_roll(
                crit_r, lck, p_coef=p.crit.p_coef, tiers=p.crit.tiers,
                tier_p=p.crit.tier_p, super_crit_level=super_crit_lv,
                p_override=p_eff,
            )
            rating["crit"] = crit_id

            # ---- ③ 格挡（1a §1.7：min(40%, 专注/(专注+150))；魔攻击无视）----
            magic = atk_type == "magic"
            br = block_rate(float(tc.get("foc", 50)), k=p.block.k, cap=p.block.cap)
            blocked = self._roll() <= br and not (magic and p.block.magic_ignores)
            rating["blocked"] = blocked

            # ---- ④ 双通道（1a §1.1-1.6：物理/元素独立 floor 后相加）----
            pierce = 0.0
            if p.type_affinity.enabled:
                pierce += pierce_pct(atk_type, blunt_pierce=p.type_affinity.blunt_pierce)
            pierce = min(0.6, pierce + float(seg.get("pierce", 0.0)))
            rating["pierce"] = pierce
            eff_con = effective_con(float(tc.get("con", 50)), pierce)
            df = defense_factor(eff_con, k=p.defense.k)
            # M2 技能倍率 = 基础 ×（1 + F-23 效果加成/100）→ F-23 消费点
            # M2-C1 修复（怪物 AI 蓄力/起身占行动槽 mult=0 语义）：原 `or 1.0` 把显式 0 吞成 1.0，
            # 蓄力播报/0 倍率 buff 行动误造成伤害——仅缺省（None/缺失）回落 1.0，0.0 原样保留
            _raw_mult = seg.get("mult")
            base_mult = float(_raw_mult) if _raw_mult is not None else 1.0
            skill_mult = self._apply_boost_to_mult(attacker, base_mult, "atk")
            # 派生累计 ≤1.5× 封顶（1a L129/L229；damage.apply_derived_cap，P1-7 消费）
            # M2-C1 修正：封顶只对「派生技」（action._derived，_resolve_combo_action 打标）
            # 生效——派生累计是派生链叠加的封顶，单技能基础倍率（技能库预算小技 150-200%）
            # 不应被封顶（tc16 怪物行动 fireball power 1.6 期望 multi==1.6）。
            if action.get("_derived"):
                skill_mult = apply_derived_cap(skill_mult, max_total_mult=p.derived.max_total_mult)
            rating["multi"] = skill_mult
            attack_value = float(ac.get("atk", 0))
            if magic:
                attack_value = float(ac.get("int", ac.get("mag", attack_value)))
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
            ch_elem = channel_elem(elem_atk, float(seg.get("elem_mult", 0.0)), weak_mult,
                                   crit_mult, elem_f, monster_def_rate=mdr)
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
            raw_total += raw

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
            self._record_action(attacker, str(action.get("type", "normal")), target,
                                rating, seg_damage, self._phase)

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
            # 反射致玩家死亡标记（终局在 end_turn ⑦⑧ 统一裁决/立即终局）
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
            target_hp=hp, side_effects=tuple(effects),
            message=f"{attacker} 对 {target} 造成 {damage.get('final', 0)} 伤害",
            battle_ended=battle_ended, status=status,
        )

    def _after_actor_action(self, actor: str) -> None:
        """行动者完成后：结算链推进（1g2 §1.2 ⑤ 后手判定；多段/连段期间保持 RES）。
        state 回行动选择（T8：下一行动者）以便下一个 actor 进入。"""
        if self._finished:
            return
        self._armor_active[actor] = False   # D2：霸体窗口=行动阶段结束（1c2 §2.2「使用期间」）
        nxt = self.next_action_owner()
        if nxt is not None and self._state in (STATE_RES,):
            self._to_state(STATE_ACT, "next_actor")

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
            return None
        if not isinstance(act, Mapping):
            return None
        ai = act.get("ai_state")
        if isinstance(ai, Mapping):
            self._snap["ai_state"] = ai  # 回灌快照（吸收返回）
        # M2 审查 P1-1：combo_broken 为「本回合连招被打断」一次性标记——
        # 打断同回合的怪物决策（本轮反击）应命中一次（立即反应），决策后清除，
        # 防跨回合/跨快照续玩无限期触发（monster_conditions._eval_combo_broken 消费）
        self._snap.pop("combo_broken", None)
        ad = dict(act)
        ad.pop("ai_state", None)  # 已回灌，不随行动 dict 下传
        # 蓄力起手/进度播报（charging）与起身演出（get_up）：占行动槽不造成伤害
        # （细化_1f：蓄力起手回合播报 1/N；起身演出占用行动槽；行动本体在 L0 释放/起身完成）
        if ad.get("charging") or ad.get("kind") == "get_up":
            ad["mult"] = 0.0
        adef = ad.get("action")
        if isinstance(adef, Mapping):
            atk = adef.get("attack_type")
            if atk:
                ad.setdefault("attack_type", self._normalize_attack_type(atk))
            ad.setdefault("armor", bool(adef.get("armor", False)))
            ad.setdefault("effects", list(adef.get("effects") or []))
        return ad

    def _interrupt_enemy_ai(self) -> bool:
        """M2-C1：玩家 interrupt 命中怪物 → 套完结（contract §六 / 细化_1f ⑤5.4 核心规则3）。

        怪物连招（chain_queue / exec_state=in_chain）与蓄力（exec_state=charging）被打断：
        - 在途链 → monster_chains.on_chain_broken（清队列、回 idle、当前链进冷却，
          下一回合走随机流程 L6，不继续原套）；
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
        # 打断标记（monster_conditions._eval_combo_broken 消费：本回合连招被打断 →
        # 下一回合 L3 可评估 combo_broken 触发行动，细化_1f ②L3）
        self._snap["combo_broken"] = True
        self._snap.setdefault("combo_events", []).append({
            "type": "monster_chain_broken", "side": "enemy",
            "chain_id": broken_chain, "charge_cleared": bool(charging),
        })
        return True

    def enemy_act(self, action_dict: Optional[Mapping[str, Any]] = None) -> Optional[ActionOutcome]:
        """⑤ 后手行动（1g2 §1.2 ⑤ / 1g1b A3）：怪物反击。

        被先手击杀的怪物不执行反击（1g2 §1.1 特例 写死）；目标无存活→
        no_target_action 兜底（fallback=空挥/skip，1g1b A3 / L56-57/L238）。
        action_dict 缺省：注入 MonsterAI 时由 decide 产出行动（M2-C1，contract §六），
        否则用 M1 默认普攻（细化_1f AI 钩子：默认 normal）。
        """
        if self._finished:
            return None
        if not self._alive("enemy") or self._dead("enemy"):
            return None  # 被先手击杀不反击（写死，1g2 §1.1 特例）
        if action_dict is None:
            action_dict = self._ai_action_dict()
        if action_dict is None:
            action_dict = {"type": "normal", "mult": 1.0}
        if self._dead("player"):
            # 玩家已死：后手无目标 → no_target_action 兜底
            mode = str(self._config.get("no_target_action", "fallback"))
            if mode == "skip":
                return None
            return self._skip_turn("enemy")  # fallback = 空挥/待机（1g1b A3）
        return self.do_action("enemy", action_dict)

    def end_turn(self) -> TurnReport:
        """⑥⑦⑧⑨ 回合收尾（1g2 §1.2 / 1g1b T8）：tick → 互杀 → 结束判定 → 下一回合。

        ⑥ 回合结束 tick（持续回合扣减/冷却递减/效果衰减/吸收回补/再生，1g2 §1.3）；
        ⑦ 互杀判定（order/hp_ratio，1g1b A2）；⑧ 战斗结束统一结算（不变量5）——
        未结束时 ⑨ 进入下一回合（回合边界，快照可在此落）。
        """
        if self._finished:
            return self._turn_report()
        if self._state not in (STATE_ACT, STATE_RES):
            raise BattleStateError(f"回合收尾需在行动完成后（当前 {self._state}，1g1b ⑧）")
        self._phase = PHASE_TURN_END_TICK
        rt = self._new_runtime()
        log = tick_turn_end(self._snap, rt)
        self._absorb_runtime(rt)

        # P0-02 修复：回合结束 tick 内 dot（tick=turn_end）扣血致死 → 死亡判定挂点
        # （1g1c §1.4「死而未结算不得穿透回合边界」/ TC-03）。原实现 tick 后只读
        # result.marks 不读 HP → HP=0 不死单位、怪物胜被无限推迟、玩家死则死锁。
        for side in BATTLE_SIDES:
            if int(self._combat(side).get("hp", 0)) <= 0:
                self._death_check_side(side, "turn_end_dot")

        # M2-C1（contract §五/§六）：怪物 AI 冷却回合收尾递减（MonsterAI.tick 递减
        # action/trigger/chain 三类冷却）。decide() 不递减（工程收敛 4，避免双重递减），
        # 本处为回合边界单点——end_turn 每轮恰一次。
        ai = self._snap.get("ai_state")
        if self._enemy_ai is not None and isinstance(ai, dict):
            self._enemy_ai.tick(ai)

        # M13 6b（细化_6b §2.2/D-03）：transform 回合 tick——形态剩余递减 →
        # 自然结束还原 → 冷却递减（S5 COOLDOWN 每回合 -1）。
        # 纯函数（transform_revert.tick_remaining/tick_cooldown/should_revert_natural）
        # 不引入定时器；形态配置经 job_def 惰性解析（无配置 → 常态无操作）。
        self._tick_transform_state()

        # M13 6c（细化_6c §1.3 F-R1 tick）：resource_state 回合结束结清——契约
        # 无每回合自动变化字段 → 现行为=保留（零增减幂等钩子，S4 被控保留天然
        # 成立）；tick_round_end 幂等钩子供契约扩展每回合变化时挂载。注册表未
        # 注入 / 无 resource_state 段 → 零操作降级（RS-5 精神，不抛异常）。
        try:
            from qbot_rpg.core.resource_lifecycle import (  # noqa: PLC0415
                ResourceLifecycle,
            )

            ResourceLifecycle(self._resource_registry).tick_round_end(self._snap)
        except Exception:  # noqa: BLE001 装配层未注入资源注册表 → 零操作降级
            pass

        # ⑦⑧ 互杀 + 战斗结束判定
        out = self._resolve_battle_end(force=False)
        if out is not None:
            self._phase = PHASE_TURN_END_TICK
            return self._turn_report(tuple(log))
        if self._dead("player") or self._dead("enemy"):
            out = self._resolve_battle_end(force=True)
            if out is not None:
                return self._turn_report(tuple(log))
        # ⑨ 下一回合（回合边界=回合结束 tick 后 → 可落快照）
        return self.start_turn()

    def _turn_report(self, log: Sequence[Mapping[str, Any]] = ()) -> TurnReport:
        return TurnReport(
            turn=int(self._snap.get("turn", 0)),
            phases=(self._phase,),
            player=int(self._combat("player").get("hp", 0)),
            enemy=int(self._combat("enemy").get("hp", 0)),
            ended=self._finished,
            status=self._snap.get("status") if self._finished else None,
            log=tuple(log),
        )

    def player_act(self, action: Any, params: Any = None) -> TurnReport:
        """玩家整轮指令（兼容旧签名 player_act(action, params=None)）：先手 → 后手 →
        tick → 结算。

        action 支持 str（'normal'/'guard'/'flee'/'skill:id'/dict）或 dict。
        返回 TurnReport（含 outcomes 流水）。一轮一条消息（框架 L69/L1571）。
        """
        action_dict = self._normalize_action(action, params)
        outcomes: List[ActionOutcome] = []
        res = self.do_action("player", action_dict)
        outcomes.append(res)
        ores = self.enemy_act()
        if ores is not None:
            outcomes.append(ores)
        rep = self.end_turn()
        return TurnReport(
            turn=rep.turn,
            phases=(PHASE_PLAYER_ACTION, PHASE_ENEMY_ACTION, PHASE_TURN_END_TICK),
            player=rep.player, enemy=rep.enemy, ended=rep.ended, status=rep.status,
            log=rep.log, outcomes=tuple(outcomes),
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
        """战斗快照序列化（1g3 §1.2 字段级：schema_version/snapshot_at/context/
        units/ai_state/combo_state/turn/stats_collector）。全量 JSON 可序列化。

        boundary：落点标注（turn_start/turn_end）。快照只落回合边界（1g3 S0/
        1g1b 不变量4）——回合内（结算中/死亡判定/玩家已行动未到 tick 边界）调用
        抛 BattleStateError（TC-05/E-05）。本引擎的自然边界＝回合开始 dot 结算后、
        玩家行动选取前（state=ACT 且玩家未行动），或战前 PREP / 终局。
        """
        if self._state in (STATE_RES, STATE_DTH):
            raise BattleStateError("回合内不落快照（1g3 S0 / 1g1b 不变量4：只落回合边界）")
        if self._state == STATE_ACT and self._turn_acted.get("player", False) and not self._finished:
            # 玩家已行动、未到回合结束 tick：属于回合内（TC-05 回合内不落快照）
            raise BattleStateError("回合内不落快照（玩家已行动未到 tick 边界，1g3 S0/TC-05）")
        snap = copy.deepcopy(self._snap)
        snap["schema_version"] = 1
        snap["snapshot_id"] = str(uuid.uuid4())
        snap["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        bnd = boundary or ("turn_start" if not self._finished else
                           ("turn_end" if self._phase == PHASE_TURN_END_TICK else "turn_start"))
        if boundary is not None and boundary not in ("turn_start", "turn_end"):
            raise ValueError(f"非法快照落点：{boundary!r}（1g3 §1.2 boundary 仅 turn_start/turn_end）")
        snap["snapshot_at"] = {"boundary": bnd, "turn": int(self._snap.get("turn", 0))}
        snap["snapshot_context"] = {
            "mode": str(self._snap.get("battle_type", "normal")),
            "map_id": str(self._snap.get("battle_type", "")),
            "zone": "normal",
        }
        snap["_engine_state"] = self._state
        snap["_guard_active"] = dict(self._guard_active)
        snap["_death_order"] = list(self._death_order)
        snap["formula_state"] = {"random_seed": self._rng_seed}
        return snap

    def snapshot(self) -> Dict[str, Any]:
        """旧名兼容：to_snapshot() 别名（M1 占位签名升级，细化_1g3）。"""
        return self.to_snapshot()

    def record_alchemy_used(self, n: int = 1) -> int:
        """M8 批9（BA-02/IF-B03）：战斗即时调合次数累计（落 _snap.battle_alchemy_used）。

        由战斗接线方在 /即时调合 结算后调用（中断恢复沿用快照值不清零；
        新战斗 start 重建 _snap 自然清零）。返回累计值。
        """
        cur = self._snap.get("battle_alchemy_used") or 0
        cur = int(cur) + int(n)
        self._snap["battle_alchemy_used"] = cur
        return cur

    def interrupt_snapshot(self) -> Dict[str, Any]:
        """中断信号落快照：等待回合边界（1g3 §2.2 落盘时序①/②），回合内抛错。"""
        if self._state in (STATE_RES, STATE_DTH):
            raise BattleStateError("中断信号排队到回合边界处理（1g3 §2.2①/TC-05，回合内不落快照）")
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
    ) -> "BattleEngine":
        """快照还原（1g3 §2.3 恢复时序①-⑤）：还原最近回合边界状态 → T7 回 PREP →
        start_turn 回 ① 继续。

        死亡判定已先于快照写入（1g3 S0/E-05）：恢复后状态=最近回合边界，无歧义。
        随机种子随 formula_state.random_seed 恢复 → 续玩随机序列一致（4a TC-17）。
        M2-C1（contract §六）：ai_state 随快照原样还原（MonsterAI 写入内容不丢）；
        enemy_ai/enemy_def 透传构造（MonsterAI 无状态=配置，需随还原引擎重建）。

        registry（M6 D3 RSM-03）：内容包配置源注入——续战世代重绑定（RSM-04）按快照
        registry_generation 从 watcher 取档重建 Registry 后传入，引擎按旧 registry
        解析 effects/statuses/marks（旧局旧配置，杜绝旧 combatant 数值 + 新解析混跑的
        半套配置）；__init__ 已有 registry 参数（L297/L331），本方法透传；缺省 None 走
        默认 defs/pipeline 解析（旧快照无世代 → RSM-04 降级）。_make_battle_resolver
        已支持 registry 优先解析（L269-281）。
        """
        eng = cls(pipeline=pipeline, registry=registry, defs=defs, config=config,
                  enemy_ai=enemy_ai, enemy_def=enemy_def, ai_action_lib=ai_action_lib,
                  ai_rng=ai_rng)
        eng._resource_registry = resource_registry  # M13 6c：资源轴注册表透传（RS-2/RS-5）
        eng._snap = copy.deepcopy(dict(data))
        eng._rng_seed = int((data.get("formula_state") or {}).get("random_seed", 0) or 0)
        eng._rng = random.Random(eng._rng_seed)
        eng._finished = data.get("status") not in (None, STATUS_ACTIVE)
        eng._guard_active = dict(data.get("_guard_active", {"player": False, "enemy": False}))
        eng._death_order = list(data.get("_death_order", []))
        eng._turn_acted = {"player": False, "enemy": False}
        eng._seq = len(eng._snap.get("action_record") or [])
        eng._effect_ids["player"] = []
        eng._effect_ids["enemy"] = []
        for side in BATTLE_SIDES:
            if side not in eng._snap:
                eng._snap[side] = dict(eng._snap.get("sides", {}).get(side, {}))
        bnd = str((data.get("snapshot_at") or {}).get("boundary", "turn_start"))
        if eng._finished:
            # 终局快照：保持终态（1g1c §1.3）
            final_status = str(data.get("status") or STATUS_LOSE)
            eng._state = {STATUS_WIN: STATE_WIN, STATUS_LOSE: STATE_LOSE,
                          STATUS_ESCAPE: STATE_FLY, STATUS_DRAW: STATE_LOSE}.get(
                final_status, STATE_LOSE)
            eng._phase = PHASE_TURN_END_TICK
        elif bnd == "turn_end":
            # 回合结束 tick 后边界：恢复回 PREP → 调用方 start_turn 回 ① 续玩（1g3 §2.3⑤）
            eng._state = STATE_PREP
            eng._phase = PHASE_TURN_START
        else:
            # turn_start 边界（回合开始 dot 已结算）：直接到玩家行动选择（1g2 §1.2 ③）
            eng._state = STATE_ACT
            eng._phase = PHASE_PLAYER_ACTION
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

    def resume(self, data: Mapping[str, Any]) -> "BattleEngine":
        """旧名兼容：快照续战（M1 占位签名升级，细化_1g3 §2.3）。
        M2-C1：沿用当前 enemy_ai（MonsterAI 无状态，随还原引擎重建同配置实例）。
        M6 D3 RSM-03：registry 透传（self._registry 注入续战引擎——世代重绑定后按旧
        registry 解析，旧局旧配置）。"""
        return self.__class__.from_snapshot(
            data, pipeline=self._pipeline, registry=self._registry, defs=self._defs,
            config=self._config, enemy_ai=self._enemy_ai,
            resource_registry=self._resource_registry,  # M13 6c：资源轴注册表透传（RS-2）
        )

    # ------------------------- 服务查询 -------------------------

    def battle_state(self) -> Dict[str, Any]:
        """battle_state 查询（1g1c §1.1 唯一权威状态；深拷贝防串改）。"""
        return copy.deepcopy(self._snap)

    def result(self) -> Dict[str, Any]:
        """结果标记（1g1c §1.3 / §1.2 五）。"""
        return copy.deepcopy(self._snap.get("result") or {})

    # ------------------------- 工具：JSON 往返测试辅助 -------------------------

    @staticmethod
    def _json_roundtrip(data: Mapping[str, Any]) -> Dict[str, Any]:
        return json.loads(json.dumps(dict(data), ensure_ascii=False))
