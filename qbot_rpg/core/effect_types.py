"""效果系统共享类型与纯函数 —— 环打破模块（2026-09-10 架构修复）。

依据：细化_1b_效果系统契约 §2（接口签名）+ 定稿 §2.1（chance 三态）。

【为什么有这个模块】（2026-09-10 G0 TC-03 循环 import 修复）
  原依赖环：qbot_rpg/core/effects.py ↔ qbot_rpg/core/event_dispatcher.py
    - effects.py L1712（函数内 lazy）→ event_dispatcher.dispatch_event
    - event_dispatcher.py L138/180/188（函数内 lazy）→ effects.DamageCtx / _chance_roll / execute_action
  作者当时用「函数内 lazy import + noqa」规避 ImportError，但契约 R3「禁止循环 import」
  的判定口径是**文件级 import 图**（G0 TC-03 静态扫描），lazy 只在运行期遮住症状、
  未消除依赖环——一旦扫描器不再被其它违规掩盖，该环即暴露（本次修复即此情形）。

  解法：把「被对方引用的、且自身不依赖任何 effects 内部状态」的符号下沉到本模块
  （零同层依赖 → 必然是依赖图的汇点，不成环）：
    - DamageCtx     —— 纯 frozen dataclass，仅依赖标准库（typing/dataclasses）
    - chance_roll   —— 纯函数，仅依赖 math/random + DamageCtx

  下沉后：effects.py 与 event_dispatcher.py 均从本模块单向引入，环被消除，
  且 lazy import 全部可还原为顶层 import（依赖方向：effects → effect_types ← event_dispatcher）。

语义与实现零改动：DamageCtx 字段、chance_roll 判定规则与下沉前逐行一致
（仅 _chance_roll 更名公开为 chance_roll，effects 内保留 _chance_roll 别名兼容既有调用）。

零 NoneBot（细化_3a R1）。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = ["DamageCtx", "chance_roll"]


# ---------------------------------------------------------------------------
# 接口 dataclass（共享契约 / 批1 对接）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DamageCtx:
    """单次受击上下文（细化_1b §2 接口签名【细化】：raw_damage/attack_type/attacker/
    target/snapshot/variables）。

    - attack_type: basic/skill/status/crit/element（普攻/技能/异常/暴击/属性分型，
      细化_1b §2 阶段① scope 参数化依据）。
    - snapshot: 战斗快照 Map（数据形态同 data/battle.BattleSnapshot 字段，**须为可变
      工作拷贝**——pipeline 会写 hp/status_state/defenses 等，见模块 docstring 补白①），
      必含每侧 combatant（hp/max_hp/...）与五块快照键。
    - variables: {region,rng,luck,eval_formula,pipeline,is_reflect_damage,stat_map,...}
      运行期变量（M12.5 需求1：stat_map 由战斗层注入，L0 取数语义键可配）。
    """

    raw_damage: int
    attack_type: str = "basic"
    attacker: str = "player"
    target: str = "enemy"
    snapshot: Mapping[str, Any] = field(default_factory=dict)
    variables: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 概率判定纯函数（细化_1b §1.1 chance / 定稿 §2.1）
# ---------------------------------------------------------------------------


def chance_roll(
    chance: Any,
    ctx: DamageCtx,
    attacker_luck: int = 0,
    target_luck: int = 0,
) -> bool:
    """概率三态判定（细化_1b §1.1 chance / 定稿 §2.1）。

    -1 = 必定；0~100 固定；+0~100 幸运修正 =（√我方幸运−√对方幸运+概率）%，
    为负或超 100 均截断（变量定稿「只建议不限制」精神，【工程补白】截断）。
    可经 ctx.variables["rng"] 注入随机源（确定性测试）。

    2026-09-10：由 effects.py 下沉至本模块（环打破，实现逐行不变；
    effects 内保留 `_chance_roll` 别名以兼容既有调用与测试）。
    """
    if chance is None:
        return True
    mode = chance.get("mode", "-1") if isinstance(chance, dict) else "-1"
    value = float(chance.get("value", -1)) if isinstance(chance, dict) else -1.0
    rng_ = ctx.variables.get("rng")
    roll = rng_.random() if rng_ is not None else random.random()
    mode_s = str(mode).strip()
    if mode_s in ("-1", "always"):
        return True
    # P1-4 修复：识别字面 "lucky"（细化_1b A-3：mode=lucky, value=20 =>
    #（√我方幸运−√对方幸运+value）%）；"+" 前缀与 "lucky" 同走幸运修正分支
    if mode_s.isdigit() or mode_s.lstrip("+").isdigit() or mode_s == "lucky":
        if mode_s.isdigit() and not mode_s.startswith("+"):
            return (roll * 100.0) <= value  # 固定概率（不幸运修正）
        lucky = (math.sqrt(max(0, attacker_luck)) - math.sqrt(max(0, target_luck)) + value) / 100.0
        lucky = max(0.0, min(1.0, lucky))
        return roll < lucky
    return False
