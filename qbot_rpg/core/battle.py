"""战斗引擎（M1 实装 · 本里程碑：效果系统拦截链接线 + 其余占位）。

M1 实装依据：细化_1a_伤害公式数值 / 细化_1b_效果系统契约 / 细化_1c1a~1c2 连段 /
细化_1d 印记系统 / 细化_1e~1f（怪物 schema+AI）/ 细化_1g1a~1g4（战斗状态机/快照续战/战斗世界边界）；
1v1 回合状态机，一轮一条消息（【框架】L69/L1571）。

本文件 M1 先落**伤害拦截链接线**（拦截链接线历史教训：功能必须被调用）：
  - qbot_rpg/core/effects.DamagePipeline.damage_pipeline 是 8 阶段唯一入口
    （细化_1b §2 伪代码），本引擎 resolve_damage() 负责组装 DamageCtx 并调用之——
    代码路径：BattleEngine.resolve_damage -> DamagePipeline.damage_pipeline。
  - 组装规则：
      1) snapshot 必须是**可变工作拷贝**（data/battle.BattleSnapshot 为 frozen，
         而拦截链⑦⑧要写 HP/status_state → 拷贝后再入 ctx，见细化_1b §2/§8.3、
         本模块 M1 补白）；
      2) snapshot[side].defenses = DamagePipeline.prepare_defense(...) 归一化防御行
         （mitigation/shield/reflect/absorb/fatal_immune/guts，工程补白①）；
      3) EffectRuntime 包装五块快照（status_state/marks_state/resist_table/
         effect_triggers/effect_cooldowns，细化_1b §1.4）；
      4) 派生伤害（反弹/追击）经 variables["is_reflect_damage"] 关闭再弹
         （定稿 §3.5 派生伤害不触发对侧反弹/反击）。

状态机（start/player_act/snapshot/resume）M1 后续里程碑实装，本版本仅签名抛占位。
零 NoneBot import（3a R1）；战斗快照类型唯一落点 data/battle.py（3a D-03）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from qbot_rpg.core.effects import (
    DamageCtx,
    DamagePipeline,
    EffectRuntime,
    PipelineResult,
)

__all__ = ["BattleEngine", "BattleActor"]


@dataclass(frozen=True)
class BattleActor:
    """战斗侧标识（player/enemy 双侧，细化_1g1a 战斗状态集）。"""

    side: str
    name: str


class BattleEngine:
    """1v1 回合战斗状态机（锁定→攻击→反击→结算）。

    M1 部分：`resolve_damage` 已接线效果系统拦截链（细化_1b §2）；
    start/player_act/snapshot/resume 为状态机占位（细化_1g，后续里程碑实装）。
    """

    def __init__(
        self,
        pipeline: Optional[DamagePipeline] = None,
        runtime: Optional[EffectRuntime] = None,
    ) -> None:
        self._pipeline = pipeline or DamagePipeline()
        self._runtime = runtime if runtime is not None else EffectRuntime()

    # ---- M1 已接线：伤害拦截链（细化_1b §2 / 定稿 §3.4） ----

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
        """组装 DamageCtx 并执行 8 阶段拦截链（细化_1b §2 伪代码）。

        snapshot 语义：可变工作拷贝（模块 docstring 组装规则 1），含每侧 combatant
        （hp/max_hp/...）+ 五块快照键 + defenses 防御行。传 None 时构建最小可用骨架
        （敌人 hp=0、无防御行——演示/测试用，战斗层应传全量工作拷贝）。
        """
        snap = dict(snapshot) if snapshot is not None else self._minimal_snapshot(attacker, target, raw_damage)
        rt = runtime if runtime is not None else self._runtime
        # 组装规则 2：无防御行则补默认（工程补白①：由战斗层 prepare_defense 归一化）
        for side in (attacker, target):
            combatant = snap.get(side)
            if isinstance(combatant, dict) and "defenses" not in combatant:
                combatant["defenses"] = self._pipeline.prepare_defense(side)
        ctx = DamageCtx(
            raw_damage=max(0, int(raw_damage)),
            attack_type=attack_type,
            attacker=attacker,
            target=target,
            snapshot=snap,
            variables=dict(variables or {}),
        )
        return self._pipeline.damage_pipeline(ctx, rt)

    def _minimal_snapshot(self, attacker: str, target: str, raw_damage: int) -> dict:
        """最小战斗快照骨架（resolve_damage 无快照参数时的兜底，测试用）。"""
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

    # ---- 状态机占位（细化_1g，后续里程碑实装） ----

    def start(self, player: Any, enemy: Any, random_seed: Optional[int] = None) -> Any:
        raise NotImplementedError("M1 后续：回合战斗状态机（细化_1g）")

    def player_act(self, action: str, params: Any = None) -> Any:
        raise NotImplementedError("M1 后续：玩家行动结算（细化_1g/1a/1c）")

    def snapshot(self) -> Any:
        raise NotImplementedError("M1 后续：战斗快照序列化（细化_1g3）")

    def resume(self, snapshot: Any) -> "BattleEngine":
        raise NotImplementedError("M1 后续：快照续战（细化_1g3）")
