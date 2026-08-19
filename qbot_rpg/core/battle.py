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
    ) -> None:
        """构造引擎。

        pipeline/runtime：效果/配置源注入（默认自建）；params：伤害公式参数载
        体（damage.DamageFormulaParams，细化_1a §2.1）；registry/defs：内容包
        配置源（effects/statuses 解析，F-21/F-23 用）；config：引擎配置
        （death_check 四项等，1g1b §三）。

        兼容旧签名：BattleEngine() / BattleEngine(pipeline, runtime) 原样可用。
        """
        self._pipeline: DamagePipeline = (
            pipeline if pipeline is not None else DamagePipeline(registry=registry, defs=defs)
        )
        self._params: DamageFormulaParams = params or DamageFormulaParams()
        self._config: Dict[str, Any] = dict(_BATTLE_DEFAULT_CONFIG)
        if config:
            self._config.update(config)
        # 外部 runtime 仅作默认解析/配置参考；引擎体内五块始终以快照为准
        self._runtime_base: Optional[EffectRuntime] = runtime
        self._registry: Any = registry
        self._defs: Optional[Mapping[str, Any]] = defs
        self._resolver: Callable[[str, str], Any] = _make_battle_resolver(registry, defs)
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
                # order（L60-62/TC-11）：先手击杀生效→玩家胜；回合开始 dot 双杀
                # （无先后）→ draw（可配 player_loss，L236）
                if bool(result.get("player_killed_enemy", False)):
                    p_dead, e_dead = False, True
                else:
                    p_dead, e_dead = True, True  # 无先手击杀 → 双死
            else:  # hp_ratio（L63/L237）
                pr = self._combat("player").get("hp", 0) / max(1, self._combat("player").get("max_hp", 1))
                er = self._combat("enemy").get("hp", 0) / max(1, self._combat("enemy").get("max_hp", 1))
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
        }
        self._finished = False
        self._death_order = []
        self._guard_active = {"player": False, "enemy": False}
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
            return self._resolve_damage_action(attacker, dict(action_dict))
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
        chance = float(self._config.get("flee_chance", 1.0))
        ok = chance >= 1.0 or self._roll() < chance
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
        atk_type = str(action.get("attack_type") or "slash")

        # 连段/派生累计（1c1a/1a derived：≤1.5× 封顶，damage.apply_derived_cap）
        seg_total: int = 0
        raw_total: int = 0
        all_effects: List[Mapping[str, Any]] = []
        last_hp: int = int(tc.get("hp", 0))
        rating: Dict[str, Any] = {"hit": True, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0}
        seg_damage: Dict[str, Any] = {"ch_phys": 0, "ch_elem": 0, "final": 0}

        for idx, seg in enumerate(segments, start=1):
            seg = dict(seg)
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

            rating: Dict[str, Any] = {
                "hit": hit, "crit": "low", "blocked": False, "pierce": 0.0, "multi": 1.0,
            }
            seg_damage: Dict[str, Any] = {"ch_phys": 0, "ch_elem": 0, "final": 0}
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
            base_mult = float(seg.get("mult", 1.0) or 1.0)
            skill_mult = self._apply_boost_to_mult(attacker, base_mult, "atk")
            # 派生累计 ≤1.5× 封顶（1a L129/L229；damage.apply_derived_cap，P1-7 消费）
            skill_mult = apply_derived_cap(skill_mult, max_total_mult=p.derived.max_total_mult)
            rating["multi"] = skill_mult
            attack_value = float(ac.get("atk", 0))
            if magic:
                attack_value = float(ac.get("int", ac.get("mag", attack_value)))
            # G3 定稿对照修复（damage 定稿对照 G3）：base_attack_mult（M2 全局攻击倍率基线，
            # 数值层 L179/细化_1a §1.2）实战零消费——现乘入物理通道首因子。
            attack_value *= p.base_attack_mult
            weak_mult = float(seg.get("weakness_mult", 1.0))
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
        nxt = self.next_action_owner()
        if nxt is not None and self._state in (STATE_RES,):
            self._to_state(STATE_ACT, "next_actor")

    def enemy_act(self, action_dict: Optional[Mapping[str, Any]] = None) -> Optional[ActionOutcome]:
        """⑤ 后手行动（1g2 §1.2 ⑤ / 1g1b A3）：怪物反击。

        被先手击杀的怪物不执行反击（1g2 §1.1 特例 写死）；目标无存活→
        no_target_action 兜底（fallback=空挥/skip，1g1b A3 / L56-57/L238）。
        action_dict 缺省用默认普攻（细化_1f AI 钩子：默认 normal）。
        """
        if self._finished:
            return None
        if not self._alive("enemy") or self._dead("enemy"):
            return None  # 被先手击杀不反击（写死，1g2 §1.1 特例）
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
        defs: Optional[Mapping[str, Any]] = None,
        config: Optional[Mapping[str, Any]] = None,
    ) -> "BattleEngine":
        """快照还原（1g3 §2.3 恢复时序①-⑤）：还原最近回合边界状态 → T7 回 PREP →
        start_turn 回 ① 继续。

        死亡判定已先于快照写入（1g3 S0/E-05）：恢复后状态=最近回合边界，无歧义。
        随机种子随 formula_state.random_seed 恢复 → 续玩随机序列一致（4a TC-17）。
        """
        eng = cls(pipeline=pipeline, defs=defs, config=config)
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
        eng._refresh_defenses()
        return eng

    def resume(self, data: Mapping[str, Any]) -> "BattleEngine":
        """旧名兼容：快照续战（M1 占位签名升级，细化_1g3 §2.3）。"""
        return self.__class__.from_snapshot(data, pipeline=self._pipeline, defs=self._defs,
                                           config=self._config)

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
