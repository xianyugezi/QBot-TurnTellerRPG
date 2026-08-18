"""效果系统运行时：伤害拦截链 8 阶段 + 四模型判定 + L0 原子动作执行器（M1 战斗核心）。

依据（全部引用节号，不编造行号）：
  - 细化_1b_效果系统契约（§2 伤害拦截链 8 阶段接口签名/伪代码，§3 L0 原子动作词汇
    16 直行 + 3 修正器 + proc，§4 四模型 S1-S7 / D1-D7 / R1-R4 / I1-I9，§5 验收用例
    B/C/D/E 组，§1 三表字段级 schema，§1.4 快照扩展 status_state/marks_state/
    resist_table/effect_triggers/effect_cooldowns）
  - 《效果系统设计定稿》v1.1（§3.3-3.4 防御特效/拦截链，§4.1 持续双维，§6.1-6.4
    四模型，§7 L0 词汇，§7.1/7.2 模板归口，§8.3 快照）
  - 细化_1d_印记系统契约（mark_add/mark_remove/clear_marks 三动作语义 §3.2、
    marks_state 双向表结构 §2.1、生命周期 §2.2）

【工程补白】（设计文档未显式定义、实现层收敛，均显式标注）：
  1. 防御行（mitigation/shield/reflect/absorb/fatal_immune/guts）不写入五块快照
     键（定稿 §8.3 未列入），由战斗层在组装 ctx 时经 DamagePipeline.prepare_defense()
     归一化为 combatant.defenses 结构，pipeline 消费之（拦截链 §2 六挂载点 → 归一化
     落点）。这与 data/battle.BattleSnapshot.frozen 冲突（frozen 快照不可改 HP），
     故 battle.py 组装 ctx 时**必须传一份可变工作拷贝**。
  2. value 三型（数字 / "N%"/ 公式框）：数字与百分比运行时直接支持；含运算符/
     [变量] 的公式框依赖公式引擎（core/damage.DamageCalculator M1 未实装）——
     默认返回 0 + warnings.warn（对齐变量定稿 F-3「运行期异常返回 0 不崩溃」），
     可通过 ctx.variables["eval_formula"](expr) 注入求值器。
  3. dot/control 运行期登记存于 combatant 字典的 dot_pool / control_state 额外键
     （可 JSON，循 BattleSnapshot 快照哲学，不入五块键）。
  4. 抗性施加量 resist_gain 默认 +10（细化_1b §4.3 R3 未给数值，定稿 §6.3 只声明
     "越挂越难"）；内容包经 EffectRuntime(config) 的 resist_gain_step 可配。
  5. halve 衰减取整数向下取整（v//2）：20→10→5→2→1（对齐验收 C-6 序列）。

零 NoneBot（细化_3a R1）；接口层全部 frozen dataclass，禁裸 dict 参数（内部状态
如 status_state 实例可用 dict，符合快照 JSON 序列化契约）。
"""

from __future__ import annotations

import json
import math
import random
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DamageCtx",
    "PipelineResult",
    "ActionResult",
    "StatusApplyResult",
    "EffectRuntime",
    "DamagePipeline",
    "execute_action",
    "execute_proc_action",
    "apply_lifesteal",
    "apply_pierce",
    "apply_mitigation",
    "tick_turn_end",
    "tick_after_action",
    "DEFAULT_PIPELINE_ORDER",
    "BATTLE_SIDES",
]

# ---------------------------------------------------------------------------
# 常量与默认值（细化_1b §1.1 §2.4 §4.4 I7 / 定稿 §2.4）
# ---------------------------------------------------------------------------

BATTLE_SIDES: Tuple[str, str] = ("player", "enemy")

DEFAULT_PIPELINE_ORDER: Tuple[str, ...] = (
    "mitigation",   # ① 减伤/减免 —— 细化_1b §2 阶段①，定稿 §3.4①
    "shield",       # ② 护盾先扣 —— 阶段②
    "reflect",      # ③ 反弹 —— 阶段③
    "absorb",       # ④ 伤害吸收 —— 阶段④
    "fatal_immune",  # ⑤ 致命/非致命免疫 —— 阶段⑤
    "guts",         # ⑥ 战斗续行 —— 阶段⑥
    "apply_damage",  # ⑦ 扣血 —— 阶段⑦
    "death_check",  # ⑧ 死亡判定 —— 阶段⑧
)

_DEFAULT_CONFIG: Dict[str, Any] = {
    "chain_depth": 3,              # 特效链深度上限（细化_1b §1.1 字段 12 / 定稿 §2.4）
    "max_triggers_per_turn": 10,   # 每回合触发上限（细化_1b §1.1 字段 10）
    "max_triggers_per_battle": 99,  # 每场触发上限（细化_1b §1.1 字段 11）
    "fatal_guard_max": 3,          # 免死类每场上限 1-3（细化_1b §4.4 I7，默认 3；0=不限）
    "allow_dual_fatal_guard": False,  # 同类型互斥默认（I7 可配）
    "pvp_fatal_disabled": False,   # PVP 可禁用免死类（I7 / 定稿 §6.4）
    "resist_gain_enabled": False,  # 施加后抗性默认关（细化_1b §4.3 R3）
    "resist_gain_step": 10,        # R3 单次抗性增益量（工程补白④）
    "max_boost_pct": 100,          # S6 攻防提升满值上限 +100%（细化_1b §4.1 S6）
    "max_combined_pct": 100,       # S7 三维组合总加成上限（细化_1b §4.1 S7）
    "stack_default_max": 3,        # S3 max_stack 阙省（细化_1b §1.2 字段 6 默认 2-3）
    "level_default_max": 5,        # S4 max_level 默认 5（细化_1b §4.1 S4）
}


def _opposite(side: str) -> str:
    """战斗侧取反（attacker/enemy 双侧）。"""
    return "enemy" if side == "player" else "player"


def _deep_mapping_of(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """把 Mapping 拷贝成可变 dict（含嵌套 list/dict 的浅拷贝足够：实例为 dict 字面量）。"""
    if value is None:
        return {}
    return dict(value)


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
    - variables: {region,rng,luck,eval_formula,pipeline,is_reflect_damage,...} 运行期变量。
    """

    raw_damage: int
    attack_type: str = "basic"
    attacker: str = "player"
    target: str = "enemy"
    snapshot: Mapping[str, Any] = field(default_factory=dict)
    variables: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineResult:
    """拦截链结算结果（细化_1b §2 伪代码输出）。side_effects 为副作用事件列表
    （reflect/absorb_record/guts/fatal_immune/death 等，供需展示层合并一轮消息）。"""

    final_damage: int
    side_effects: list
    target_hp: int


@dataclass(frozen=True)
class ActionResult:
    """L0 动作执行结果（细化_1b §3 L0 词汇）。side_effects 事件列表供展示层。"""

    ok: bool
    side_effects: list
    message: str = ""


@dataclass(frozen=True)
class StatusApplyResult:
    """apply_status 单次施加判定结果（细化_1b §4 四模型）。

    reason 取值：applied / replaced / covered_low / stacked / dual_added / renewed /
    immune_status / immune_mount / immune_all / miss / unknown_status / at_max_stack /
    at_max_level / blocked。
    """

    applied: bool
    status_id: str
    instance: Mapping[str, Any]
    reason: str
    side_effects: list


# ---------------------------------------------------------------------------
# 解析器适配（工程补白：registry.resolve(id, kind) 或 def 实例映射或 callable）
# ---------------------------------------------------------------------------


def _make_resolver(
    registry: Any = None, defs: Optional[Mapping[str, Any]] = None
) -> Callable[[str, str], Any]:
    """归一化「配置来源」为 callable(id, kind) -> Def|None。

    细化_1b §1：配置家族唯一数据源 = effects/statuses/marks 三表；registry 为
    pack.registry（Registry.resolve(id, kind)）；defs 为 {id: Def} 映射（批1 直连测试）。
    """
    if registry is not None:
        if callable(registry):
            return registry
        resolve = getattr(registry, "resolve", None)
        if callable(resolve):
            return lambda id_, kind: resolve(id_, kind)
    if defs is not None:
        return lambda id_, _kind: defs.get(id_)
    return lambda _id_, _kind: None


# ---------------------------------------------------------------------------
# EffectRuntime —— 五块快照状态 + 四模型
# ---------------------------------------------------------------------------


class EffectRuntime:
    """效果系统运行时：包装快照五块（细化_1b §1.4 / 定稿 §8.3）：

    status_state / marks_state / resist_table / effect_triggers / effect_cooldowns
    ——纯 JSON 可序列化（to_dict/from_dict/to_json/from_json），中断恢复（验收 G-1）
    与热重载快照（ID+名称冗余，验收 A-6）落点。

    承担四模型判定：叠加 S1-S7（apply_status）、衰减 D1-D7（decay_carrier/tick_turns/
    tick_trigger/clear_safe_zone）、耐性 R1-R4（apply_status 内 hit 判定 + resist 表）、
    免疫 I1-I9（immune_dims / apply_status 拦截）。
    """

    def __init__(
        self,
        status_state: Optional[Mapping[str, Any]] = None,
        marks_state: Optional[Mapping[str, Any]] = None,
        resist_table: Optional[Mapping[str, Any]] = None,
        effect_triggers: Optional[Mapping[str, Any]] = None,
        effect_cooldowns: Optional[Mapping[str, Any]] = None,
        resolver: Any = None,
        defs: Optional[Mapping[str, Any]] = None,
        config: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.status_state: Dict[str, Any] = _deep_mapping_of(status_state)
        self.marks_state: Dict[str, Any] = _deep_mapping_of(marks_state)
        self.resist_table: Dict[str, Any] = _deep_mapping_of(resist_table)
        self.effect_triggers: Dict[str, Any] = _deep_mapping_of(effect_triggers)
        self.effect_cooldowns: Dict[str, Any] = _deep_mapping_of(effect_cooldowns)
        self._resolver: Callable[[str, str], Any] = _make_resolver(resolver, defs)
        self.config: Dict[str, Any] = dict(_DEFAULT_CONFIG)
        if config:
            self.config.update(config)
        for side in BATTLE_SIDES:
            self.ensure_actor(side)

    # ---------------- 五块快照访问 ----------------

    def ensure_actor(self, side: str) -> None:
        """确保 per-actor 结构存在（marks_state/resist_table 为 per-actor 双向表）。"""
        for table in (self.marks_state, self.resist_table):
            if side not in table or not isinstance(table[side], list):
                if table is self.marks_state and side in table:
                    continue
            if side not in table:
                table[side] = [] if table is self.marks_state else {}
        if side not in self.status_state or not isinstance(self.status_state[side], list):
            self.status_state[side] = []
        trig = self.effect_triggers.setdefault(side, {})
        trig.setdefault("per_turn", {})
        trig.setdefault("per_battle", {})
        self.effect_cooldowns.setdefault(side, {})

    # ---------------- 状态实例 ----------------

    def status_instances(self, side: str) -> List[Dict[str, Any]]:
        self.ensure_actor(side)
        return self.status_state[side]  # type: ignore[return-value]

    def find_status(self, side: str, status_id: str) -> Optional[Dict[str, Any]]:
        for inst in self.status_instances(side):
            if inst.get("status_id") == status_id:
                return inst
        return None

    def _remove_status(self, side: str, inst: Mapping[str, Any]) -> None:
        lst = self.status_instances(side)
        for i in range(len(lst) - 1, -1, -1):
            if lst[i] is inst or (
                lst[i].get("status_id") == inst.get("status_id")
                and lst[i].get("_uid", "") == inst.get("_uid", "")
            ):
                lst.pop(i)
                return

    _UID_COUNTER = 0

    @classmethod
    def _next_uid(cls) -> int:
        cls._UID_COUNTER += 1
        return cls._UID_COUNTER

    # ---------------- 印记（marks_state，细化_1d §2.1/§3.2） ----------------

    def marks(self, side: str) -> List[Dict[str, Any]]:
        self.ensure_actor(side)
        return self.marks_state[side]  # type: ignore[return-value]

    def add_marks(
        self, mark_id: str, side: str, count: int = 1, applier: Optional[str] = None
    ) -> Tuple[bool, int]:
        """mark_add 三动作之一（细化_1d §3.2 A-1 / 印记定稿 §4.1）：

        - 施加必中（独立于伤害判定）；
        - 重复 = +count 至上限（max_stack，0=不限，到顶不再涨）。
        """
        mark_def = self._resolver(mark_id, "mark")
        max_stack = 0
        if mark_def is not None:
            ms = mark_def.raw.get("max_stack") if hasattr(mark_def, "raw") else mark_def.get("max_stack")
            try:
                max_stack = int(ms or 0)
            except (TypeError, ValueError):
                max_stack = 0
        applier = applier or "player"
        for inst in self.marks(side):
            if inst.get("mark_id") == mark_id:
                old = int(inst.get("count", 0))
                if max_stack and old + count > max_stack:
                    inst["count"] = max_stack
                else:
                    inst["count"] = old + count
                return True, max_stack
        inst = {
            "mark_id": mark_id,
            "name": (mark_def.name if mark_def is not None and hasattr(mark_def, "name") else mark_id),
            "count": count if not max_stack else min(count, max_stack),
            "applier": applier,
            "polarity": str(
                mark_def.raw.get("polarity", "positive")
                if mark_def is not None and hasattr(mark_def, "raw")
                else "positive"
            ),
        }
        if mark_def is not None and hasattr(mark_def, "raw"):
            dur = mark_def.raw.get("duration", "battle")
            if isinstance(dur, str) and dur.startswith("turns:"):
                try:
                    inst["remaining_turns"] = int(dur.split(":")[1])
                except (ValueError, IndexError):
                    pass
        self.marks(side).append(inst)
        return True, max_stack

    def remove_marks(
        self,
        side: str,
        polarity: str,
        count: int = 1,
        mark: Optional[str] = None,
    ) -> int:
        """mark_remove 三动作之一（细化_1d §3.2 A-2 / 印记定稿 §4.2）：

        寻址 = marks_on + polarity 过滤（+可选 mark 精确指定）；按层数消；
        FIFO（先施加的先被清）；count 超过现有层数=饱和减法至 0（D-03）。
        """
        remaining = max(0, count)
        removed = 0
        lst = self.marks(side)
        survivors: List[Dict[str, Any]] = []
        for inst in lst:
            if (
                remaining > 0
                and inst.get("polarity") == polarity
                and (mark is None or inst.get("mark_id") == mark)
            ):
                cur = int(inst.get("count", 0))
                sub = min(cur, remaining)
                cur -= sub
                removed += sub
                remaining -= sub
                if cur > 0:
                    inst["count"] = cur
                    survivors.append(inst)
            else:
                survivors.append(inst)
        self.marks_state[side] = survivors
        return removed

    def clear_marks(
        self, side: str, polarity: str, mark: Optional[str] = None
    ) -> int:
        """clear_marks 三动作之一（细化_1d §3.2 A-3 / 印记定稿 §4.2）：整组清空（无 count）。"""
        survivors = [
            inst
            for inst in self.marks(side)
            if not (
                inst.get("polarity") == polarity
                and (mark is None or inst.get("mark_id") == mark)
            )
        ]
        n = len(self.marks(side)) - len(survivors)
        self.marks_state[side] = survivors
        return n

    # ---------------- effect_triggers（细化_1b §2.4 / §8.3） ----------------

    def increment_trigger(self, side: str, effect_id: str, bucket: str = "per_battle") -> int:
        self.ensure_actor(side)
        cur = int(self.effect_triggers[side].get(bucket, {}).get(effect_id, 0))
        self.effect_triggers[side][bucket][effect_id] = cur + 1
        return cur + 1

    def trigger_counts(self, side: str, effect_id: str) -> Tuple[int, int]:
        self.ensure_actor(side)
        per_turn = int(self.effect_triggers[side]["per_turn"].get(effect_id, 0))
        per_battle = int(self.effect_triggers[side]["per_battle"].get(effect_id, 0))
        return per_turn, per_battle

    def reset_turn_triggers(self, side: str) -> None:
        """回合结束重置每回合触发计数（定稿 §2.4 / 细化_1b §0 结算时点）。"""
        self.ensure_actor(side)
        self.effect_triggers[side]["per_turn"] = {}

    # ---------------- effect_cooldowns（细化_1b §3.1 / §8.3） ----------------

    def cooldown(self, side: str, effect_id: str) -> int:
        self.ensure_actor(side)
        return int(self.effect_cooldowns[side].get(effect_id, 0))

    def set_cooldown(self, side: str, effect_id: str, value: int) -> None:
        self.ensure_actor(side)
        if value <= 0:
            self.effect_cooldowns[side].pop(effect_id, None)
        else:
            self.effect_cooldowns[side][effect_id] = value

    def tick_cooldowns(self, side: str) -> None:
        self.ensure_actor(side)
        for eid in list(self.effect_cooldowns[side]):
            v = int(self.effect_cooldowns[side][eid]) - 1
            self.set_cooldown(side, eid, v)

    # ---------------- resist_table（细化_1b §4.3 R4 / 定稿 §8.3） ----------------

    def resist(self, side: str, status_id: str) -> int:
        self.ensure_actor(side)
        return int(self.resist_table[side].get(status_id, 0))

    def add_resist(self, side: str, status_id: str, value: int) -> None:
        self.ensure_actor(side)
        self.resist_table[side][status_id] = self.resist(side, status_id) + value

    # ---------------- 免疫维度（细化_1b §4.4 I1-I4/I8，定稿 §6.4） ----------------

    def immune_dims(
        self, side: str, defense: Optional[Mapping[str, Any]] = None
    ) -> Dict[str, Any]:
        """汇总 per-actor 免疫维度：I1 status / I2 damage / I3 interrupt / I4 all。

        数据源：目标身上 immune_vs 状态（statuses.json 字段，细化_1b §1.2 字段 14）
        + 防御行 immune（prepare_defense 归一化，含 all 是否挡 debuff 可配）。"""
        dims = {
            "status": False,
            "damage": False,
            "interrupt": False,
            "all": False,
            "block_debuff": True,
        }
        for inst in self.status_instances(side):
            sdef = self._resolver(inst.get("status_id", ""), "status")
            if sdef is None:
                continue
            raw = sdef.raw if hasattr(sdef, "raw") else sdef
            iv = raw.get("immune_vs")
            if iv in dims:
                dims[iv] = True
        if defense is not None:
            imm = defense.get("immune") or {}
            for k in dims:
                if k in imm:
                    dims[k] = bool(imm[k])
        return dims

    def immune_to_interrupt(self, side: str, defense: Optional[Mapping[str, Any]] = None) -> bool:
        """I3 打断免疫 = 霸体（armor=true ⇔ immune_vs 含 interrupt），定稿 §6.4。"""
        dims = self.immune_dims(side, defense)
        return bool(dims.get("all") or dims.get("interrupt"))

    # ---------------- 叠加规则参数 ----------------

    @staticmethod
    def _boost_of(sdef: Any) -> float:
        """状态强度（S1 高覆盖低 / S5 强覆盖弱的比较量）：取首个 L0 动作数值或 1。"""
        raw = sdef.raw if hasattr(sdef, "raw") else sdef
        v = 1.0
        actions = raw.get("actions") if isinstance(raw, dict) else None
        if isinstance(actions, list) and actions:
            a0 = actions[0]
            if isinstance(a0, dict):
                val = a0.get("value")
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    v = float(val)
                elif isinstance(val, str) and "%" in val:
                    try:
                        v = float(val.rstrip("%")) / 100.0
                    except ValueError:
                        pass
        return v

    # ---------------- apply_status：S1-S7 + R1-R4 + I1-I9（细化_1b §4） ----------------

    def apply_status(
        self,
        status_id: str,
        target: str,
        source: str = "",
        attacker: Optional[str] = None,
        ctx: Optional[DamageCtx] = None,
        force: bool = False,
    ) -> StatusApplyResult:
        """施加状态。四模型判定全部在此收敛（细化_1b §4）：

        - R1-R4 耐性判定（hit_rate × 目标耐性；resist_gain 施加后抗性默认关；抗性表）;
        - I1-I9 免疫拦截（status/all 维挡负面状态、Mount 弱体盾、消耗性免疫 I6）;
        - S1-S7 叠加（single 高覆盖低 / dual 并存相加 2 槽 / stack 累积至 max_stack /
          level_based 至 max_level / 同来源同侧强覆盖 / 攻防上限 S6 / 三维组合 S7）;
        - D1-D7 衰减与持续双维落库（decay 类型、turns×charges，-1 维永不被清）。
        """
        side_effects: List[Dict[str, Any]] = []
        sdef = self._resolver(status_id, "status")
        if sdef is None:
            return StatusApplyResult(
                False, status_id, {}, "unknown_status", side_effects
            )
        raw = sdef.raw if hasattr(sdef, "raw") else sdef
        name = getattr(sdef, "name", None) or status_id

        category = str(raw.get("category", "other"))
        negative = category in {"weak", "seal", "harm"}  # 弱体/封锁/伤害（定稿 §4.3）
        frame = str(raw.get("stack_frame", "single"))
        max_stack = int(raw.get("max_stack") or self.config["stack_default_max"])
        level_based = bool(raw.get("level_based", False))
        max_level = int(raw.get("max_level") or self.config["level_default_max"])
        hit_rate = int((raw.get("hit_rate", 100) or 100))
        decay = str(raw.get("decay", "none"))
        decay_subject = str(raw.get("decay_subject", "carrier"))
        dur = raw.get("duration") or {}
        turns = int(dur.get("turns", 1) if isinstance(dur, dict) else 1)
        charges = int(dur.get("charges", 0) if isinstance(dur, dict) else 0)
        if turns == 0 and charges == 0:
            turns, charges = 1, 0  # 防御：不存在双零持续

        power = self._boost_of(sdef)
        first_action_value = 0
        actions = raw.get("actions") if isinstance(raw, dict) else None
        if isinstance(actions, list) and actions and isinstance(actions[0], dict):
            av = actions[0].get("value")
            if isinstance(av, (int, float)) and not isinstance(av, bool):
                first_action_value = int(av)
            elif isinstance(av, str) and "%" in av:
                try:
                    first_action_value = int(float(av.rstrip("%")))
                except ValueError:
                    first_action_value = 0

        # ---- I-矩阵拦截（I1/I2/I4/I5/I6），force 跳过（仅引擎命令场景） ----
        # 目标现有免疫维度：状态底 immune_vs（细化_1b §4.4）+ 防御行 immune。
        # I1 status 维挡负面状态不挡伤害；I4 all 维默认挡 debuff（block_debuff 可配）。
        # 不拦印记（印记非状态异常，细化_1d §5.2）。
        if not force and negative:
            defense = None
            if ctx is not None and isinstance(ctx.snapshot.get(target), dict):
                defense = ctx.snapshot[target].get("defenses")  # type: ignore[index]
            dims = self.immune_dims(target, defense)
            blocks_debuff_all = bool(dims["all"]) and bool(dims.get("block_debuff", True))
            if (dims["all"] and blocks_debuff_all) or dims["status"]:
                self._consume_consumable_immune(target)
                return StatusApplyResult(
                    False, status_id, {}, "immune_status", side_effects
                )
            # I5 免疫盾 Mount：单次弱体盾抵消下一次弱体（细化_1b §4.4 I5 / 定稿 §6.4）
            if defense is not None and isinstance(defense, dict):
                mount = defense.get("mount")
                if isinstance(mount, dict):
                    rem = int(mount.get("remaining", 0))
                    if rem > 0:
                        mount["remaining"] = rem - 1
                        return StatusApplyResult(
                            False, status_id, {}, "immune_mount", side_effects
                        )

        # ---- R1-R4 命中判定（细化_1b §4.3，default 100=必中） ----
        if not force:
            resist = self.resist(target, status_id)
            effective = hit_rate * max(0, 100 - resist) / 100.0
            rng = ctx.variables.get("rng") if ctx is not None else None
            rnd = rng.random() if rng is not None else random.random()
            if rnd > effective / 100.0:
                return StatusApplyResult(False, status_id, {}, "miss", side_effects)

        # 定位既有实例
        existing = self.find_status(target, status_id)

        if level_based:
            # S4 等级制叠加（冰结/感电类，max_level 默认 5，细化_1b §4.1 S4）
            if existing is None:
                existing = self._new_instance(status_id, name, first_action_value, turns, charges, decay, decay_subject, source, category=category)
                existing["level"] = 1
                existing["stacks"] = 1
                self.status_instances(target).append(existing)
                side_effects.append({"type": "status_applied", "target": target, "status_id": status_id, "level": 1})
            else:
                if int(existing.get("level", 0)) >= max_level:
                    return StatusApplyResult(False, status_id, existing, "at_max_level", side_effects)
                existing["level"] = int(existing.get("level", 0)) + 1
                self._reset_duration(existing, turns, charges)
                side_effects.append({"type": "status_level_up", "target": target, "status_id": status_id, "level": existing["level"]})
            self._after_apply(existing, raw, negative, target, status_id)
            res = StatusApplyResult(True, status_id, existing, "applied", side_effects)
            if negative and self.config["resist_gain_enabled"] and raw.get("resist_gain"):
                self.add_resist(target, status_id, int(raw.get("resist_gain_step") or self.config["resist_gain_step"]))  # R3
            return res

        # S5 同来源同侧：只保留一个（强覆盖弱，等强覆盖重置持续，细化_1b §4.1 S5）
        if existing is not None:
            prev_source = str(existing.get("source", ""))
            if source and prev_source == source:
                if power >= self._boost_of(sdef):
                    # 强覆盖（等强覆盖重置持续时间）
                    self._reset_duration(existing, turns, charges)
                    existing["value"] = first_action_value
                    side_effects.append({"type": "status_renewed", "target": target, "status_id": status_id})
                else:
                    return StatusApplyResult(False, status_id, existing, "covered_low", side_effects)
                self._after_apply(existing, raw, negative, target, status_id)
                return StatusApplyResult(True, status_id, existing, "renewed", side_effects)

        if existing is not None and frame == "single":
            # S1 high covers low（细化_1b §4.1 S1，默认框架）
            if power >= self._boost_of(sdef):
                # 高覆盖低 → 新覆盖旧（重置）
                existing["value"] = first_action_value
                existing["level"] = 1
                existing["stacks"] = int(existing.get("stacks", 1))
                self._reset_duration(existing, turns, charges)
                side_effects.append({"type": "status_replaced", "target": target, "status_id": status_id})
            else:
                return StatusApplyResult(False, status_id, existing, "covered_low", side_effects)
            self._after_apply(existing, raw, negative, target, status_id)
            return StatusApplyResult(True, status_id, existing, "applied", side_effects)

        if existing is not None and frame == "dual":
            # S2 不同框架并存相加；dual 2 槽约束（细化_1b §4.1 S2 / 定稿 §十一）
            same_id_instances = [i for i in self.status_instances(target) if i.get("status_id") == status_id]
            if len(same_id_instances) >= 2:
                # 2 槽已满 → 新盖最弱
                weakest = min(same_id_instances, key=lambda i: i.get("value", 0))
                self._remove_status(target, weakest)
                inst = self._new_instance(status_id, name, first_action_value, turns, charges, decay, decay_subject, source, category=category)
                inst["level"] = 1
                inst["stacks"] = 1
                self.status_instances(target).append(inst)
                side_effects.append({"type": "status_dual_added", "target": target, "status_id": status_id})
                self._after_apply(inst, raw, negative, target, status_id)
                return StatusApplyResult(True, status_id, inst, "dual_added", side_effects)
            inst = self._new_instance(status_id, name, first_action_value, turns, charges, decay, decay_subject, source, category=category)
            inst["level"] = 1
            inst["stacks"] = 1
            self.status_instances(target).append(inst)
            side_effects.append({"type": "status_dual_added", "target": target, "status_id": status_id})
            self._after_apply(inst, raw, negative, target, status_id)
            # R3
            if negative and self.config["resist_gain_enabled"] and raw.get("resist_gain"):
                self.add_resist(target, status_id, int(raw.get("resist_gain_step") or self.config["resist_gain_step"]))
            return StatusApplyResult(True, status_id, inst, "dual_added", side_effects)

        if existing is not None and frame == "stack":
            # S3 累积叠层至 max_stack（细化_1b §4.1 S3，默认 2-3）
            if int(existing.get("stacks", 1)) >= max_stack:
                self._reset_duration(existing, turns, charges)
                return StatusApplyResult(False, status_id, existing, "at_max_stack", side_effects)
            existing["stacks"] = int(existing.get("stacks", 1)) + 1
            self._reset_duration(existing, turns, charges)
            side_effects.append({"type": "status_stacked", "target": target, "status_id": status_id, "stacks": existing["stacks"]})
            self._after_apply(existing, raw, negative, target, status_id)
            return StatusApplyResult(True, status_id, existing, "stacked", side_effects)

        # 无既有实例 → 新建
        inst = self._new_instance(status_id, name, first_action_value, turns, charges, decay, decay_subject, source, category=category)
        inst["level"] = 1
        inst["stacks"] = 1
        self.status_instances(target).append(inst)
        side_effects.append({"type": "status_applied", "target": target, "status_id": status_id})
        self._after_apply(inst, raw, negative, target, status_id)
        if negative and self.config["resist_gain_enabled"] and raw.get("resist_gain"):
            self.add_resist(target, status_id, int(raw.get("resist_gain_step") or self.config["resist_gain_step"]))
        return StatusApplyResult(True, status_id, inst, "applied", side_effects)

    def _new_instance(
        self,
        status_id: str,
        name: str,
        value: int,
        turns: int,
        charges: int,
        decay: str,
        decay_subject: str,
        source: str,
        category: str = "other",
    ) -> Dict[str, Any]:
        """新建状态实例（细化_1b §1.4 status_state：层数/等级/剩余回合/剩余次数/衰减值）。"""
        return {
            "status_id": status_id,
            "name": name,
            "category": category,     # 定稿 §4.2 增益/§4.3 减益分类（dispel 寻址依据）
            "level": 1,
            "stacks": 1,
            "value": value,          # 衰减主体数值（D2 halve / D3 decrement 作用对象）
            "turns": turns,
            "charges": charges,
            "decay": decay,
            "decay_subject": decay_subject,
            "source": source,
            "immune_uses": 0,
            "trigger_halve": False,  # D4 trigger 衰减：True=减半 / False=-1
            "_uid": self._next_uid(),
        }

    @staticmethod
    def _reset_duration(inst: Mapping[str, Any], turns: int, charges: int) -> None:
        if isinstance(inst, dict):
            inst["turns"] = turns
            inst["charges"] = charges

    def _after_apply(
        self,
        inst: Mapping[str, Any],
        raw: Mapping[str, Any],
        negative: bool,
        target: str,
        status_id: str,
    ) -> None:
        """施加后处理：I6 消耗性免疫计数与 D4 trigger 衰减形态落库。"""
        if isinstance(inst, dict):
            inst.setdefault("category", str(raw.get("category", "other")))
            inst.setdefault("trigger_halve", bool(raw.get("trigger_halve", False)))
            immunity = raw.get("immune_vs") or ""
            if immunity in ("status", "damage", "interrupt", "all"):
                uses = int(raw.get("immune_uses") or 0)
                if uses:
                    inst["immune_uses"] = uses

    def _consume_consumable_immune(self, side: str) -> None:
        """I6 消耗性免疫：免疫拦截发生时消耗目标身上免疫状态 1 次；归零移除
        （D-5：免疫 2 次后消失，细化_1b §4.4 I6 / 定稿 §6.4）。"""
        for inst in self.status_instances(side):
            uses = int(inst.get("immune_uses", 0)) if isinstance(inst, dict) else 0
            if uses > 0:
                inst["immune_uses"] = uses - 1
                if uses - 1 <= 0:
                    self._remove_status(side, inst)
                return

    # ---------------- 衰减与持续双维（细化_1b §4.2 D1-D7，定稿 §6.2/§4.1） ----------------

    def decay_carrier(self, side: str) -> List[Dict[str, Any]]:
        """D5 衰减主体：携带者每次行动结算后衰减一次（非双方都衰减，H8）。

        D2 halve 数值减半（向下取整）/ D3 decrement 数值 -1；归零后实例移除（C-6）。
        """
        removed_log: List[Dict[str, Any]] = []
        lst = self.status_instances(side)
        for inst in list(lst):
            decay = inst.get("decay", "none") if isinstance(inst, dict) else "none"
            subject = inst.get("decay_subject", "carrier") if isinstance(inst, dict) else "carrier"
            if subject != "carrier":
                continue
            value = int(inst.get("value", 0)) if isinstance(inst, dict) else 0
            if decay == "halve":
                inst["value"] = value // 2
                removed_log.append({"type": "decay", "side": side, "status_id": inst.get("status_id"), "value": inst["value"]})
            elif decay == "decrement":
                inst["value"] = value - 1
                removed_log.append({"type": "decay", "side": side, "status_id": inst.get("status_id"), "value": inst["value"]})
            if int(inst.get("value", 0)) <= 0 and decay in ("halve", "decrement"):
                self._remove_status(side, inst)
                removed_log.append({"type": "status_expired", "side": side, "status_id": inst.get("status_id")})
        return removed_log

    def tick_trigger(self, side: str, status_id: str) -> Optional[Dict[str, Any]]:
        """D4 trigger 衰减 + D6 次数触发时扣减（细化_1b §4.1 P0-3 / §4.2 D4/D6）。

        返回被移除的实例（None=仍存活）。次数维：charges>0 每次触发 -1，归零即消失
        （回合0+次数10 = 触发 10 次后消失，C-9）；charges==0 视作「该维无限」
        （回合10+次数0 = 10 回合内无限触发）；turns==-1 维永不被清（D6 行）。
        """
        inst = self.find_status(side, status_id)
        if inst is None:
            return None
        if inst.get("decay", "") == "trigger":
            v = int(inst.get("value", 0))
            inst["value"] = v // 2 if inst.get("trigger_halve", False) else v - 1
        charges = int(inst.get("charges", 0))
        if charges > 0:
            inst["charges"] = charges - 1
            if int(inst["charges"]) <= 0:
                self._remove_status(side, inst)
                return inst
        return None

    def tick_turns(self, side: str) -> None:
        """D6 持续回合回合结束 tick 扣减（细化_1b §4.1 P0-3：回合=回合结束扣）。

        turns>0 → -1 后归零移除；turns==-1 → 永不被清（D6 行：-1 维不被清除）；
        turns==0 → 回合维无限（配合 回合0+次数N 语义，C-9）。
        """
        lst = self.status_instances(side)
        for inst in list(lst):
            t = int(inst.get("turns", 0))
            if t > 0:
                inst["turns"] = t - 1
                if inst["turns"] == 0:
                    self._remove_status(side, inst)

    def clear_safe_zone(self, side: str) -> None:
        """安全区清除增减益：任一维 -1 永不被清（细化_1b §4.1 §4.2 D6 / 定稿 §4.1）。"""
        survivors = [
            inst
            for inst in self.status_instances(side)
            if int(inst.get("turns", 0)) == -1 or int(inst.get("charges", 0)) == -1
        ]
        self.status_state[side] = survivors

    # ---------------- S6/S7 数值上限（细化_1b §4.1 S6/S7，定稿 §6.1） ----------------

    def cap_boost(self, pct: float) -> float:
        """S6 攻防提升满值上限 +100%（可配，config.max_boost_pct）。"""
        cap = self.config.get("max_boost_pct", 100)
        if cap <= 0:  # 0=不限
            return pct
        return max(-cap, min(cap, pct))

    def cap_combined(self, total: float) -> float:
        """S7 三维组合（dual×累积×等级）总加成上限（config.max_combined_pct）。"""
        cap = self.config.get("max_combined_pct", 100)
        if cap <= 0:  # 0=不限
            return total
        return min(cap, total)

    # ---------------- I7 免死约束校验（细化_1b §4.4 I7 / 定稿 §6.4 H1） ----------------

    def validate_fatal_guard(
        self, effect_ids: Sequence[str], pvp: bool = False
    ) -> List[str]:
        """免死类（致命免疫/战斗续行/不死续行）配置校验（I7）：

        - 每场上限默认 1-3（config.fatal_guard_max，0=不限）超限警告；
        - 同类型互斥默认（allow_dual_fatal_guard 可配）——同时配致命免疫+战斗续行提示；
        - PVP 可禁用免死类。
        """
        warnings_list: List[str] = []
        if pvp and self.config.get("pvp_fatal_disabled", False):
            warnings_list.append("PVP 已禁用免死类效果")
            return warnings_list
        fatal_kinds = 0
        for eid in effect_ids:
            edef = self._resolver(eid, "effect")
            if edef is None:
                continue
            raw = edef.raw if hasattr(edef, "raw") else edef
            if raw.get("type") in ("fatal_immune", "guts", "immortal"):
                fatal_kinds += 1
        cap = self.config.get("fatal_guard_max", 3)
        if cap and fatal_kinds > cap:
            warnings_list.append(f"免死类配置超上限（实际 {fatal_kinds} > 默认 {cap}），建议 1-3 次")
        if (
            not self.config.get("allow_dual_fatal_guard", False)
            and fatal_kinds >= 2
        ):
            warnings_list.append("已装备致命免疫，战斗续行将不生效（同类型互斥默认，allow_dual_fatal_guard 可配）")
        return warnings_list

    # ---------------- 序列化（细化_1b §1.4 快照扩展 / 定稿 §8.3） ----------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status_state": self.status_state,
            "marks_state": self.marks_state,
            "resist_table": self.resist_table,
            "effect_triggers": self.effect_triggers,
            "effect_cooldowns": self.effect_cooldowns,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], resolver: Any = None, config: Optional[Mapping[str, Any]] = None) -> "EffectRuntime":
        return cls(
            status_state=data.get("status_state"),
            marks_state=data.get("marks_state"),
            resist_table=data.get("resist_table"),
            effect_triggers=data.get("effect_triggers"),
            effect_cooldowns=data.get("effect_cooldowns"),
            resolver=resolver,
            config=config,
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str, resolver: Any = None, config: Optional[Mapping[str, Any]] = None) -> "EffectRuntime":
        return cls.from_dict(json.loads(text), resolver=resolver, config=config)


# ---------------------------------------------------------------------------
# DamagePipeline —— 伤害拦截链 8 阶段（细化_1b §2 / 定稿 §3.4）
# ---------------------------------------------------------------------------


class DamagePipeline:
    """伤害拦截链（默认管线，可配顺序、异常顺序仅警告，细化_1b §2 总则）。

    阶段（定稿 §3.4）：①减伤/减免 → ②护盾先扣 → ③反弹 → ④伤害吸收 → ⑤致命/非致命免疫
    → ⑥战斗续行 → ⑦扣血 → ⑧死亡判定。阶段间以伤害值递减传递（细化_1b §2 伪代码）。

    与战斗层接线（拦截链接线历史教训——每一函数必须有调用方）：
      battle.py 组装 ctx（快照可变工作拷贝 + combatan.defenses 归一化）+ EffectRuntime，
      调用 damage_pipeline(ctx, runtime)；反射等派生伤害回注时经 ctx.variables
      ["is_reflect_damage"]=True 关闭再弹（定稿 §3.5 派生伤害不触发对侧反弹）。
    """

    def __init__(
        self,
        registry: Any = None,
        defs: Optional[Mapping[str, Any]] = None,
        order: Optional[Sequence[str]] = None,
        config: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._resolve: Callable[[str, str], Any] = _make_resolver(registry, defs)
        self.config: Dict[str, Any] = dict(_DEFAULT_CONFIG)
        if config:
            self.config.update(config)
        order_tuple = tuple(order) if order is not None else DEFAULT_PIPELINE_ORDER
        missing = set(DEFAULT_PIPELINE_ORDER) - set(order_tuple)
        extra = set(order_tuple) - set(DEFAULT_PIPELINE_ORDER)
        missing_recal = [s for s in DEFAULT_PIPELINE_ORDER if s not in order_tuple]
        if order_tuple and missing_recal:
            warnings.warn(
                f"管线配置缺少阶段 {missing_recal}，将追加到末尾（细化_1b §2 可配数组）"
            )
            order_tuple = tuple(order_tuple) + tuple(
                s for s in DEFAULT_PIPELINE_ORDER if s not in order_tuple
            )
        if extra:
            warnings.warn(f"管线配置含未知阶段 {extra}，忽略（细化_1b §2）")
            order_tuple = tuple(s for s in order_tuple if s in DEFAULT_PIPELINE_ORDER)
        # B-9 异常顺序警告：死亡判定在扣血前（细化_1b §5 B-9 / 定稿 §3.4）
        if "death_check" in order_tuple and "apply_damage" in order_tuple:
            if order_tuple.index("death_check") < order_tuple.index("apply_damage"):
                warnings.warn("异常顺序：死亡判定在扣血前（细化_1b §2 总则，仅警告）")
        self._order: Tuple[str, ...] = order_tuple
        self._stages: Dict[str, Callable[[DamageCtx, EffectRuntime, list, int], int]] = {
            "mitigation": self._stage_mitigation,
            "shield": self._stage_shield,
            "reflect": self._stage_reflect,
            "absorb": self._stage_absorb,
            "fatal_immune": self._stage_fatal_immune,
            "guts": self._stage_guts,
            "apply_damage": self._stage_apply_damage,
            "death_check": self._stage_death_check,
        }

    # ---------------- 防御归一化（工程补白①：六挂载点 → combatant.defenses） ----------------

    def prepare_defense(
        self,
        actor: str,
        effect_ids: Sequence[str] = (),
        status_instances: Sequence[Mapping[str, Any]] = (),
    ) -> Dict[str, Any]:
        """把效果/状态配置归一化为防御行（mitigation/shield/reflect/absorb/
        fatal_immune/non_fatal_immune/guts/immune/mount）。

        配置来源 = 内容注册表（registry.resolve）或内容包 Def 实例（defs 构造参数）；
        效果按 type 归口（定稿 §3.3 防御特效五类），状态动作按 L0 模板归口
        （定稿 §7.2 生存模板四类：tpl_shield_* / tpl_mitigation_* / ...）。
        """
        defs: Dict[str, Any] = {
            "mitigation": [],
            "shield": {"value": 0, "remaining": 0, "turns": 0, "max": 0},
            "reflect": {"value": 0, "pct": True, "active": False},
            "absorb": {"value": 0, "pct": True, "record": 0, "active": False},
            "fatal_immune": {"count": 0, "max": 0},
            "non_fatal_immune": {"active": False, "count": 0},
            "guts": {"count": 0, "max": 0},
            "immune": {"status": False, "damage": False, "interrupt": False, "all": False, "block_debuff": True},
            "mount": {"remaining": 0},
        }

        def _fold_effect(raw: Mapping[str, Any]) -> None:
            typ = raw.get("type")
            if typ == "reflect":
                defs["reflect"]["active"] = True
                defs["reflect"]["value"] = int(raw.get("value", 20))
                defs["reflect"]["pct"] = bool(raw.get("pct", True))
            elif typ == "absorb":
                defs["absorb"]["active"] = True
                defs["absorb"]["value"] = int(raw.get("value", 50))
                defs["absorb"]["pct"] = bool(raw.get("pct", True))
            elif typ in ("fatal_immune", "non_fatal_immune"):
                key = "fatal_immune" if typ == "fatal_immune" else "non_fatal_immune"
                n = int(raw.get("count") or raw.get("uses") or 1)
                defs[key]["count"] = n
                defs[key]["max"] = n
            elif typ == "guts":
                defs["guts"]["count"] = int(raw.get("count") or 1)
                defs["guts"]["max"] = defs["guts"]["count"]
            elif typ == "shield":
                v = int(raw.get("value") or 0)
                defs["shield"] = {"value": v, "remaining": v, "turns": int(raw.get("turns") or 0), "max": v}
            elif typ == "mitigation":
                _fold_mitigation(raw)
            elif typ == "mount":
                defs["mount"]["remaining"] = int(raw.get("count") or raw.get("uses") or 1)

        def _fold_mitigation(raw: Mapping[str, Any]) -> None:
            defs["mitigation"].append(
                {"value": int(raw.get("value", 0)), "scope": str(raw.get("scope") or "all")}
            )

        def _fold_status_actions(status_id: str) -> None:
            sdef = self._resolve(status_id, "status")
            if sdef is None:
                return
            raw = sdef.raw if hasattr(sdef, "raw") else sdef
            iv = raw.get("immune_vs")
            if iv in defs["immune"]:
                defs["immune"][iv] = True
                if iv == "all":
                    defs["immune"]["block_debuff"] = bool(raw.get("block_debuff", True))
            actions = raw.get("actions")
            if isinstance(actions, list):
                for a in actions:
                    if not isinstance(a, dict):
                        continue
                    if a.get("type") == "mitigation":
                        _fold_mitigation(a)
                    elif a.get("type") == "shield":
                        v = int(a.get("value") or 0)
                        defs["shield"] = {"value": v, "remaining": v, "turns": int(a.get("turns") or 0), "max": v}
                    elif a.get("type") == "reflect":
                        defs["reflect"]["active"] = True
                        defs["reflect"]["value"] = int(a.get("value", 20))
                    elif a.get("type") == "absorb":
                        defs["absorb"]["active"] = True
                        defs["absorb"]["value"] = int(a.get("value", 50))

        for eid in effect_ids:
            edef = self._resolve(eid, "effect")
            if edef is None:
                continue
            raw = edef.raw if hasattr(edef, "raw") else edef
            _fold_effect(raw)
            actions = raw.get("actions")
            if isinstance(actions, list):
                for a in actions:
                    if isinstance(a, dict) and isinstance(a.get("value"), (int, float)) and not isinstance(a.get("value"), bool):
                        # 效果 type=reflect/absorb 时 value 已在 _fold_effect 处理
                        pass
        for inst in status_instances:
            _fold_status_actions(str(inst.get("status_id", "")))
        return defs

    # ---------------- ctx 辅助 ----------------

    @staticmethod
    def _combat(ctx: DamageCtx, side: str) -> Dict[str, Any]:
        c = ctx.snapshot.get(side)
        return c if isinstance(c, dict) else {}

    @staticmethod
    def _hp(ctx: DamageCtx, side: str) -> int:
        return int(DamagePipeline._combat(ctx, side).get("hp", 0))

    @staticmethod
    def _max_hp(ctx: DamageCtx, side: str) -> int:
        return int(DamagePipeline._combat(ctx, side).get("max_hp", 0))

    def _set_hp(self, ctx: DamageCtx, side: str, hp: int) -> None:
        self._combat(ctx, side)["hp"] = max(0, hp)

    def _defense(self, ctx: DamageCtx, side: str) -> Dict[str, Any]:
        c = self._combat(ctx, side)
        d = c.get("defenses")
        if not isinstance(d, dict):
            d = {}
            c["defenses"] = d
        return d

    # ---------------- 入口（细化_1b §2 伪代码） ----------------

    def damage_pipeline(self, ctx: DamageCtx, runtime: EffectRuntime) -> PipelineResult:
        """严格执行 8 阶段；阶段间以伤害值递减传递。副作用事件列表供展示层合并。"""
        d = max(0, int(ctx.raw_damage))
        side_effects: List[Dict[str, Any]] = []
        for stage_id in self._order:
            d = self._stages[stage_id](ctx, runtime, side_effects, d)
        hp = self._hp(ctx, ctx.target)
        return PipelineResult(final_damage=d, side_effects=side_effects, target_hp=hp)

    # ---------------- 阶段实现 ----------------

    def _stage_mitigation(self, ctx: DamageCtx, runtime: EffectRuntime, se: list, d: int) -> int:
        """① 减伤/减免（细化_1b §2 阶段①，定稿 §3.4① / §7.2② 生存模板二）。"""
        defs = self._defense(ctx, ctx.target)
        total = 0.0
        for m in defs.get("mitigation", []):
            scope = str(m.get("scope") or "all")
            if scope == "all" or scope == ctx.attack_type:
                total += float(m.get("value", 0)) / 100.0
        total = min(total, 1.0)
        out = max(0, round(d * (1 - total)))
        if total > 0:
            se.append({"type": "mitigation", "target": ctx.target, "reduced": d - out, "pct": total * 100})
        return out

    def _stage_shield(self, ctx: DamageCtx, runtime: EffectRuntime, se: list, d: int) -> int:
        """② 护盾先扣（细化_1b §2 阶段②，定稿 §3.4② / §7.2①）。"""
        defs = self._defense(ctx, ctx.target)
        shield = defs.get("shield")
        if not isinstance(shield, dict):
            return d
        remaining = int(shield.get("remaining", 0))
        if remaining <= 0 or d <= 0:
            return d
        absorbed = min(remaining, d)
        shield["remaining"] = remaining - absorbed
        shield["_absorbed_this_hit"] = absorbed  # stage④ 吸收记录「护盾挡的伤害也计入」（定稿 §3.3）
        d -= absorbed
        if absorbed > 0:
            se.append({"type": "shield_absorbed", "target": ctx.target, "absorbed": absorbed, "remaining": shield["remaining"]})
        return d

    def _stage_reflect(self, ctx: DamageCtx, runtime: EffectRuntime, se: list, d: int) -> int:
        """③ 反弹（细化_1b §2 阶段③ / 定稿 §3.4③：反弹伤害不触发反弹，§3.5）。"""
        if ctx.variables.get("is_reflect_damage", False):
            return d  # 派生伤害不触发对侧反弹（定稿 §3.5）
        defs = self._defense(ctx, ctx.target)
        refl = defs.get("reflect")
        if not (isinstance(refl, dict) and refl.get("active") and d > 0):
            return d
        pct = float(refl.get("value", 0)) / 100.0 if refl.get("pct", True) else float(refl.get("value", 0))
        reflect_damage = round(d * pct)
        if reflect_damage > 0:
            se.append(
                {
                    "type": "reflect",
                    "source": ctx.target,
                    "target": ctx.attacker,
                    "damage": reflect_damage,
                }
            )
        return d

    def _stage_absorb(self, ctx: DamageCtx, runtime: EffectRuntime, se: list, d: int) -> int:
        """④ 伤害吸收（细化_1b §2 阶段④ / 定稿 §3.4④ §3.3：护盾挡的伤害也计入）。"""
        defs = self._defense(ctx, ctx.target)
        absb = defs.get("absorb")
        if not (isinstance(absb, dict) and absb.get("active")):
            return d
        shield = defs.get("shield")
        shield_absorbed = shield.get("_absorbed_this_hit", 0) if isinstance(shield, dict) else 0
        record = d + shield_absorbed
        absb["record"] = int(absb.get("record", 0)) + record
        se.append({"type": "absorb_recorded", "target": ctx.target, "record": record})
        if isinstance(shield, dict):
            shield.pop("_absorbed_this_hit", None)
        return d

    def _stage_fatal_immune(self, ctx: DamageCtx, runtime: EffectRuntime, se: list, d: int) -> int:
        """⑤ 致命/非致命免疫（细化_1b §2 阶段⑤ / 定稿 §3.4⑤，消耗 triggers 计数）。

        免疫维度 damage = 伤害免疫全额免伤（细化_1b §4.4 I2）；致命/非致命免疫效果同。
        """
        if d <= 0:
            return d
        hp = self._hp(ctx, ctx.target)
        lethal = d >= max(0, hp)
        defs = self._defense(ctx, ctx.target)
        # I2 伤害免疫（immune_vs=damage / all），定稿 §6.4
        dims = runtime.immune_dims(ctx.target, defs)
        if dims.get("damage") or dims.get("all"):
            runtime.increment_trigger(ctx.target, "damage_immune", "per_battle")
            se.append({"type": "damage_immune", "target": ctx.target, "damage": d})
            return 0
        fi = defs.get("fatal_immune")
        nfi = defs.get("non_fatal_immune")
        if lethal and isinstance(fi, dict) and int(fi.get("count", 0)) > 0:
            fi["count"] = int(fi["count"]) - 1
            runtime.increment_trigger(ctx.target, "fatal_immune", "per_battle")
            se.append({"type": "fatal_immune", "target": ctx.target, "immune": True, "remaining": fi["count"]})
            return 0
        if isinstance(nfi, dict) and nfi.get("active") and int(nfi.get("count", 0)) > 0:
            nfi["count"] = int(nfi["count"]) - 1
            runtime.increment_trigger(ctx.target, "non_fatal_immune", "per_battle")
            se.append({"type": "non_fatal_immune", "target": ctx.target, "immune": True})
            return 0
        return d

    def _stage_guts(self, ctx: DamageCtx, runtime: EffectRuntime, se: list, d: int) -> int:
        """⑥ 战斗续行（细化_1b §2 阶段⑥ / 定稿 §3.4⑥：致死伤害时 HP 锁定 1，触发瞬间回复）。"""
        if d <= 0:
            return d
        hp = self._hp(ctx, ctx.target)
        defs = self._defense(ctx, ctx.target)
        gu = defs.get("guts")
        if not (isinstance(gu, dict) and int(gu.get("count", 0)) > 0):
            return d
        if d >= max(0, hp):
            gu["count"] = int(gu["count"]) - 1
            # 把伤害压到「扣血后恰好 1」：最终 d = max(0, hp - 1)，⑦扣血后 HP=1
            d = max(0, hp - 1)
            se.append({"type": "guts", "target": ctx.target, "quard_hp": 1, "remaining": gu["count"]})
            return d
        return d

    def _stage_apply_damage(self, ctx: DamageCtx, runtime: EffectRuntime, se: list, d: int) -> int:
        """⑦ 扣血（细化_1b §2 阶段⑦，无配置挂载：target.HP -= final_damage）。"""
        hp = self._hp(ctx, ctx.target)
        self._set_hp(ctx, ctx.target, hp - d)
        se.append({"type": "hp_change", "target": ctx.target, "delta": -d})
        return d

    def _stage_death_check(self, ctx: DamageCtx, runtime: EffectRuntime, se: list, d: int) -> int:
        """⑧ 死亡判定（细化_1b §2 阶段⑧ / 定稿 §3.4⑧：触发 on_death 事件/战斗结束流程）。"""
        hp = self._hp(ctx, ctx.target)
        if hp <= 0:
            se.append({"type": "death", "target": ctx.target, "trigger": "on_death"})
        return d

    # ---------------- 反弹等派生伤害入口（定稿 §3.5 特效级联） ----------------

    @classmethod
    def deliver_reflect(cls, pipeline: "DamagePipeline", ctx: DamageCtx, runtime: EffectRuntime, reflect_event: Mapping[str, Any]) -> PipelineResult:
        """把反弹/追击等派生伤害按管线结算，并注入 is_reflect_damage 关闭再弹（§3.5）。"""
        sub_vars = dict(ctx.variables)
        sub_vars["is_reflect_damage"] = True
        sub = DamageCtx(
            raw_damage=int(reflect_event.get("damage", 0)),
            attack_type="basic",
            attacker=str(reflect_event.get("target", ctx.attacker)),
            target=str(reflect_event.get("source", ctx.target)),
            snapshot=ctx.snapshot,
            variables=sub_vars,
        )
        return pipeline.damage_pipeline(sub, runtime)


# ---------------------------------------------------------------------------
# 回合钩子（细化_1b §0 结算时点总表）
# ---------------------------------------------------------------------------


def tick_turn_end(snapshot: Mapping[str, Any], runtime: EffectRuntime) -> List[Dict[str, Any]]:
    """回合结束 tick（细化_1b §0 结算时点：回合结束 tick 持续回合扣减 + 四路回复结算）：

    ① 伤害吸收回合末回复（④ 记录实伤，定稿 §7.2 时点矩阵「受伤害后回合末」）
    ② dot 持续伤害（定稿 §4.3 伤害类 / 细化_1b §3.1 dot 动作 tick）
    ③ 再生 regen 回复（tpl_regen 回合末）
    ④ 持续双维·回合扣减（D6）+ 限时印记 remaining_turns 扣减（细化_1d §三）
    ⑤ 每回合触发计数重置（定稿 §2.4）
    """
    log: List[Dict[str, Any]] = []
    for side in BATTLE_SIDES:
        c = snapshot.get(side)
        if not isinstance(c, dict):
            continue
        # ① 伤害吸收回合末回复
        defs = c.get("defenses")
        if isinstance(defs, dict):
            absb = defs.get("absorb")
            if isinstance(absb, dict) and absb.get("record"):
                pct = float(absb.get("value", 0)) / 100.0 if absb.get("pct", True) else float(absb.get("value", 0))
                heal = int(int(absb["record"]) * pct)
                hp = int(c.get("hp", 0))
                max_hp = int(c.get("max_hp", 0))
                c["hp"] = min(max_hp, hp + heal)
                absb["record"] = 0
                if heal > 0:
                    log.append({"type": "absorb_heal", "side": side, "heal": heal})
        # ② dot 持续伤害
        dots = c.get("dot_pool")
        if isinstance(dots, dict):
            for dot_id, dot in list(dots.items()):
                if isinstance(dot, dict) and dot.get("tick") == "turn_end":
                    value = int(dot.get("value", 0))
                    hp = int(c.get("hp", 0))
                    c["hp"] = max(0, hp - value)
                    log.append({"type": "dot_damage", "side": side, "status": dot.get("status_id", dot_id), "value": value})
                    rt = int(dot.get("turns", 0))
                    if rt > 0:
                        dot["turns"] = rt - 1
                    if dot.get("turns", 0) == 0:
                        dots.pop(dot_id, None)
        # ③ 再生 regen（tpl_regen 回合末）
        regen = defs.get("regen") if isinstance(defs, dict) else None
        if isinstance(regen, dict):
            v = int(regen.get("value", 0))
            hp = int(c.get("hp", 0))
            max_hp = int(c.get("max_hp", 0))
            c["hp"] = min(max_hp, hp + v)
            log.append({"type": "regen", "side": side, "heal": v})
        # ④ 持续双维·回合扣减 + 限时印记扣减
        runtime.tick_turns(side)
        for inst in runtime.marks(side):
            rt = inst.get("remaining_turns")
            if isinstance(rt, int) and rt > 0:
                inst["remaining_turns"] = rt - 1
        runtime.marks_state[side] = [
            m for m in runtime.marks(side)
            if not (isinstance(m.get("remaining_turns"), int) and int(m.get("remaining_turns") or 0) <= 0)
        ]
        # ⑤ 每回合触发计数重置
        runtime.reset_turn_triggers(side)
        runtime.tick_cooldowns(side)
    return log


def tick_after_action(snapshot: Mapping[str, Any], runtime: EffectRuntime, actor: str) -> List[Dict[str, Any]]:
    """携带者行动结算后衰减（细化_1b §0/§4.2 D5，H8：携带者每次行动结算后衰减一次，非双方）。"""
    return runtime.decay_carrier(actor)


# ---------------------------------------------------------------------------
# L0 原子动作执行器（细化_1b §3 词汇表 16 直行 + 3 修正器 + proc 容器）
# ---------------------------------------------------------------------------

_DEFAULT_PIPELINE: Optional[DamagePipeline] = None


def _get_pipeline(ctx: DamageCtx) -> DamagePipeline:
    global _DEFAULT_PIPELINE
    p = ctx.variables.get("pipeline")
    if isinstance(p, DamagePipeline):
        return p
    if _DEFAULT_PIPELINE is None:
        _DEFAULT_PIPELINE = DamagePipeline()
    return _DEFAULT_PIPELINE


def _resolve_side(actor: str, which: str) -> str:
    """L0 动作 target/self/enemy 的相对侧解析（细化_1b §3.1：target 与技能伤害 target 独立）。"""
    if which in ("self", "player"):
        return actor
    if which in ("enemy", "target"):
        return _opposite(actor)
    return which  # 显式 player/enemy


def _resolve_value(
    value: Any,
    base: int,
    ctx: DamageCtx,
    kind: str = "flat",
) -> int:
    """value 三型求值（细化_1b §1.1 actions[].item：数字框/百分比框/公式框）。

    数字/百分比运行时直接支持；公式框默认返回 0 + 警告（公式引擎 M1 未接线，
    对齐变量定稿 F-3），可注入 ctx.variables["eval_formula"]。
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("%"):
            try:
                return int(round((float(s.rstrip("%")) / 100.0) * int(base)))
            except (ValueError, TypeError):
                return 0
        eval_fn = ctx.variables.get("eval_formula")
        if callable(eval_fn) and (s.startswith(("[", "Math", "mind")) or any(op in s for op in ("+", "-", "*", "/", "(", ")"))):
            try:
                return int(float(str(eval_fn(s))))
            except Exception:  # noqa: BLE001 —— 求值异常不崩溃，F-3
                warnings.warn(f"L0 公式求值失败，返回 0：{value}")
                return 0
    warnings.warn(f"L0 value 无法解析为数字，返回 0：{value!r}")
    return 0


def _chance_roll(
    chance: Any,
    ctx: DamageCtx,
    attacker_luck: int = 0,
    target_luck: int = 0,
) -> bool:
    """概率三态判定（细化_1b §1.1 chance / 定稿 §2.1）。

    -1 = 必定；0~100 固定；+0~100 幸运修正 =（√我方幸运−√对方幸运+概率）%，
    为负或超 100 均截断（变量定稿「只建议不限制」精神，【工程补白】截断）。
    可经 ctx.variables["rng"] 注入随机源（确定性测试）。
    """
    if chance is None:
        return True
    mode = chance.get("mode", "-1") if isinstance(chance, dict) else "-1"
    value = float(chance.get("value", -1)) if isinstance(chance, dict) else -1.0
    rng_ = ctx.variables.get("rng")
    roll = rng_.random() if rng_ is not None else random.random()
    if str(mode) == "-1":
        return True
    if str(mode).isdigit() or str(mode).lstrip("+").isdigit():
        if not str(mode).startswith("+"):
            return (roll * 100.0) <= value  # 固定概率（不幸运修正）
        lucky = (math.sqrt(max(0, attacker_luck)) - math.sqrt(max(0, target_luck)) + value) / 100.0
        lucky = max(0.0, min(1.0, lucky))
        return roll < lucky
    return False


def execute_action(
    action: Mapping[str, Any],
    ctx: DamageCtx,
    runtime: EffectRuntime,
    depth: int = 0,
) -> ActionResult:
    """L0 原子动作执行器（细化_1b §3）：

    - 16 直行动作：damage / heal / stat_modifier / dot / control / status_apply /
      dispel / shield / mark_add / mark_remove / clear_marks / summon / convert /
      interrupt / aoe / proc；
    - 3 结算修正器：lifesteal / pierce / mitigation（挂伤害管线自动生效，本入口亦可直达）；
    - proc 容器：chance/cooldown/actions + 每回合 10 / 每场 99 / 链深 3 上限
      （细化_1b §1.1 字段 10-12 / 定稿 §2.4）。
    """
    atype = str(action.get("type", ""))
    side_effects: List[Dict[str, Any]] = []
    attacker = ctx.attacker
    which_target = str(action.get("target", "enemy"))
    target = _resolve_side(attacker, which_target)

    # ---- 防御修正器（3 个，细化_1b §3.2） ----
    if atype == "lifesteal":
        v = _resolve_value(action.get("value", "0%"), ctx.snapshot.get(attacker, {}).get("max_hp", 0), ctx)
        base_damage = int(action.get("damage_dealt", 0) or ctx.variables.get("damage_dealt", 0))
        heal = int(round(base_damage * v / 100.0)) if action.get("pct", True) else v
        c = ctx.snapshot.get(attacker)
        if isinstance(c, dict):
            c["hp"] = min(int(c.get("max_hp", 0)), int(c.get("hp", 0)) + heal)
        side_effects.append({"type": "lifesteal", "target": attacker, "heal": heal})
        return ActionResult(True, side_effects)
    if atype == "pierce":
        pct = float(action.get("value", 0))
        defense = int(ctx.snapshot.get(target, {}).get("dfn", 0))
        effective = int(round(defense * (1 - pct / 100.0)))
        side_effects.append({"type": "pierce", "target": target, "pct": pct, "effective_defense": effective})
        return ActionResult(True, side_effects)
    if atype == "mitigation":
        v = int(action.get("value", 0))
        scope = str(action.get("scope") or "all")
        defs = ctx.snapshot.get(target, {}).get("defenses")
        if isinstance(defs, dict):
            defs.setdefault("mitigation", []).append({"value": v, "scope": scope})
        side_effects.append({"type": "mitigation_added", "target": target, "value": v, "scope": scope})
        return ActionResult(True, side_effects)

    # ---- 直行动作 ----
    if atype == "damage":
        base = int(ctx.snapshot.get(attacker, {}).get("atk", 0))
        raw = _resolve_value(action.get("value"), base, ctx, "damage")
        sub_ctx = DamageCtx(
            raw_damage=raw,
            attack_type="skill" if action.get("attack_type") is None else str(action.get("attack_type")),
            attacker=attacker,
            target=target,
            snapshot=ctx.snapshot,
            variables=ctx.variables,
        )
        res = _get_pipeline(ctx).damage_pipeline(sub_ctx, runtime)
        side_effects.append({"type": "damage_dealt", "target": target, "damage": res.final_damage, "target_hp": res.target_hp})
        return ActionResult(True, side_effects, f"造成 {res.final_damage} 伤害")

    if atype == "heal":
        stat = str(action.get("stat") or "hp")
        when = str(action.get("when") or "instant")
        base = int(ctx.snapshot.get(attacker, {}).get("max_hp", 0))
        v = _resolve_value(action.get("value"), base, ctx, "heal")
        if when in ("instant", "on_skill"):
            c = ctx.snapshot.get(target)
            if isinstance(c, dict):
                key = "hp" if stat == "hp" else "mp"
                cur = int(c.get(key, 0))
                cap = int(c.get("max_hp" if stat == "hp" else "max_mp", cur))
                c[key] = min(cap, cur + v)
            side_effects.append({"type": "heal", "target": target, "stat": stat, "value": v})
        else:
            # 回合末/on_turn_start/on_turn_end 登记
            c = ctx.snapshot.get(target)
            if isinstance(c, dict):
                pool = c.setdefault("heal_pool", [])
                pool.append({"stat": stat, "when": when, "value": v})
            side_effects.append({"type": "heal_scheduled", "target": target, "stat": stat, "when": when, "value": v})
        return ActionResult(True, side_effects)

    if atype == "stat_modifier":
        stat = str(action.get("stat") or "atk")
        v = int(action.get("value", 0))
        c = ctx.snapshot.get(target)
        if isinstance(c, dict):
            cur = int(c.get(stat, 0))
            pct = int(action.get("pct", False))
            if pct:
                new = cur + int(round(cur * v / 100.0))
            else:
                new = cur + v
            c[stat] = max(0, new)
        side_effects.append({"type": "stat_modified", "target": target, "stat": stat, "value": v})
        return ActionResult(True, side_effects)

    if atype == "dot":
        status_id = str(action.get("status") or action.get("status_id") or action.get("dot_id") or "dot")
        value = _resolve_value(action.get("value"), int(ctx.snapshot.get(target, {}).get("max_hp", 0)), ctx)
        tick = str(action.get("tick") or "turn_end")
        turns = int(action.get("turns") or 3)
        c = ctx.snapshot.get(target)
        if isinstance(c, dict):
            pool = c.setdefault("dot_pool", {})
            pool[status_id] = {"status_id": status_id, "value": max(0, value), "tick": tick, "turns": turns, "source": attacker}
        side_effects.append({"type": "dot_applied", "target": target, "status_id": status_id, "value": max(0, value), "tick": tick})
        return ActionResult(True, side_effects)

    if atype == "control":
        ctype = str(action.get("control_type") or action.get("type") or "sleep")
        skip = float(action.get("skip_turn", 1.0) or 1.0)
        turns = int(action.get("turns") or 1)
        # R 模型：hit_rate 100 必中（细化_1b §4.3 R1）
        c = ctx.snapshot.get(target)
        if isinstance(c, dict):
            c["control_state"] = {"type": ctype, "skip_turn": skip, "turns": turns, "source": attacker}
        side_effects.append({"type": "controlled", "target": target, "control": ctype, "turns": turns})
        return ActionResult(True, side_effects)

    if atype == "status_apply":
        status_id = str(action.get("status_id") or action.get("status") or "")
        res = runtime.apply_status(status_id, target, source=str(action.get("source") or attacker), attacker=attacker, ctx=ctx)
        side_effects.append({"type": "status_apply", "target": target, "status_id": status_id, "applied": res.applied, "reason": res.reason})
        return ActionResult(res.applied, side_effects, res.reason)

    if atype == "dispel":
        # 驱散=清增益（强化/反制/治疗）；净化=清减益（弱体/封锁/伤害）（定稿 §4.4 / 细化_1b E-4）。
        # FIFO 顺序消除（先施加的先被清）；印记非增益/减益，天然不命中（细化_1d §5.2）。
        flt = action.get("filter")
        flt = [flt] if isinstance(flt, str) else list(flt or [])
        count = int(action.get("count") or 1)
        removed = 0
        survivors = []
        for inst in runtime.status_instances(target):
            if removed < count and inst.get("category", "") in flt:
                removed += 1
                continue
            survivors.append(inst)
        runtime.status_state[target] = survivors
        side_effects.append({"type": "dispel", "target": target, "filter": flt, "removed": removed})
        return ActionResult(True, side_effects, f"驱散 {removed} 个状态")

    if atype == "shield":
        v = int(action.get("value") or 0)
        turns = int(action.get("turns") or 0)
        defs = ctx.snapshot.get(target, {}).get("defenses")
        if not isinstance(defs, dict):
            defs = {"shield": {}}
            c = ctx.snapshot.get(target)
            if isinstance(c, dict):
                c["defenses"] = defs
        shield = defs.setdefault("shield", {})
        shield["value"] = v
        shield["remaining"] = v
        shield["turns"] = turns
        shield["max"] = v
        side_effects.append({"type": "shield", "target": target, "value": v, "turns": turns})
        return ActionResult(True, side_effects)

    if atype == "mark_add":
        mark_id = str(action.get("mark") or action.get("mark_id") or "")
        count = int(action.get("count") or 1)
        added, cap = runtime.add_marks(mark_id, target, count, applier=attacker)
        side_effects.append({"type": "mark_add", "target": target, "mark_id": mark_id, "count": count, "capped": bool(cap)})
        return ActionResult(True, side_effects)

    if atype == "mark_remove":
        marks_on = _resolve_side(attacker, str(action.get("marks_on") or "self"))
        polarity = str(action.get("polarity") or "positive")
        count = int(action.get("count") or 1)
        mark = action.get("mark")
        removed = runtime.remove_marks(marks_on, polarity, count, mark)
        side_effects.append({"type": "mark_remove", "marks_on": marks_on, "polarity": polarity, "removed": removed})
        return ActionResult(True, side_effects)

    if atype == "clear_marks":
        marks_on = _resolve_side(attacker, str(action.get("marks_on") or "self"))
        polarity = str(action.get("polarity") or "positive")
        mark = action.get("mark")
        removed = runtime.clear_marks(marks_on, polarity, mark)
        side_effects.append({"type": "clear_marks", "marks_on": marks_on, "polarity": polarity, "removed": removed})
        return ActionResult(True, side_effects)

    if atype == "summon":
        # 召唤/临时单位（细化_1b §3.1，M1 仅副作用事件；单位实体由战斗层 M1 挂实体注册）
        side_effects.append({"type": "summon", "target": target, "unit": action.get("unit")})
        return ActionResult(True, side_effects, "召唤（占位，战斗实体待接线）")

    if atype == "convert":
        side_effects.append({"type": "convert", "source": action.get("from"), "to": action.get("to")})
        return ActionResult(True, side_effects, "素材转换（占位）")

    if atype == "interrupt":
        # 打断 = 清连段类动作（细化_1b §3.1 interrupt 唯一归口 / 定稿 §7）；
        # I3：打断免疫 = 霸体（armor），定稿 §6.4
        defs = ctx.snapshot.get(target, {}).get("defenses")
        if runtime.immune_to_interrupt(target, defs):
            side_effects.append({"type": "interrupt_blocked", "target": target, "reason": "armor(打断免疫)"})
            return ActionResult(False, side_effects, "目标霸体，打断无效")
        combo = ctx.snapshot.get("combo_state")
        if isinstance(combo, dict):
            combo.setdefault(target, {})["interrupted"] = True
        side_effects.append({"type": "interrupt", "target": target})
        return ActionResult(True, side_effects)

    if atype == "aoe":
        # 范围效果（1v1 = 对目标 + 提示，定稿 §7 保留）
        base = int(ctx.snapshot.get(attacker, {}).get("atk", 0))
        raw = _resolve_value(action.get("value"), base, ctx, "aoe")
        sub_ctx = DamageCtx(
            raw_damage=raw, attack_type="skill", attacker=attacker,
            target=target, snapshot=ctx.snapshot, variables=ctx.variables,
        )
        res = _get_pipeline(ctx).damage_pipeline(sub_ctx, runtime)
        side_effects.append({"type": "aoe", "target": target, "damage": res.final_damage, "prompt": "范围攻击（1v1 命中目标）"})
        return ActionResult(True, side_effects)

    if atype == "proc":
        return execute_proc_action(action, ctx, runtime, depth)

    return ActionResult(False, side_effects, f"未知 L0 动作类型：{atype}")


def execute_proc_action(
    proc_action: Mapping[str, Any],
    ctx: DamageCtx,
    runtime: EffectRuntime,
    depth: int = 0,
) -> ActionResult:
    """proc 触发容器（细化_1b §2.5 / §1.1 字段 10-12，定稿 §2.5）：

    - 每回合上限（默认 10）+ 每场上限（默认 99）双重封顶（E-8 / G-2）；
    - 链深度上限（默认 3，防递归无限）；
    - chance 概率三态 + cooldown 冷却；
    - 触发时按序执行子动作（E-1 追击→偷取可链）。
    """
    side_effects: List[Dict[str, Any]] = []
    actor = ctx.attacker
    proc_id = str(proc_action.get("id") or proc_action.get("proc_id") or proc_action.get("type") or "proc")
    chain_depth = int(proc_action.get("chain_depth") or runtime.config.get("chain_depth", 3))
    if depth >= chain_depth:
        side_effects.append({"type": "proc_blocked", "reason": "chain_depth", "depth": depth})
        return ActionResult(False, side_effects, "特效链深度超限")
    if runtime.cooldown(actor, proc_id) > 0:
        side_effects.append({"type": "proc_blocked", "reason": "cooldown"})
        return ActionResult(False, side_effects, "特效冷却中")
    per_turn, per_battle = runtime.trigger_counts(actor, proc_id)
    if per_turn >= int(runtime.config.get("max_triggers_per_turn", 10)):
        side_effects.append({"type": "proc_blocked", "reason": "per_turn_limit"})
        return ActionResult(False, side_effects, "每回合触发上限")
    if per_battle >= int(runtime.config.get("max_triggers_per_battle", 99)):
        side_effects.append({"type": "proc_blocked", "reason": "per_battle_limit"})
        return ActionResult(False, side_effects, "每场触发上限")
    if not _chance_roll(proc_action.get("chance"), ctx):
        return ActionResult(False, side_effects, "概率未触发")
    # 触发成功：计数 + 冷却 + 子动作
    runtime.increment_trigger(actor, proc_id, "per_turn")
    runtime.increment_trigger(actor, proc_id, "per_battle")
    if int(proc_action.get("cooldown") or 0) > 0:
        runtime.set_cooldown(actor, proc_id, int(proc_action["cooldown"]))
    trigger = str(proc_action.get("trigger") or "")
    side_effects.append({"type": "proc_triggered", "actor": actor, "proc_id": proc_id, "trigger": trigger})
    for sub in proc_action.get("actions") or []:
        if not isinstance(sub, dict):
            continue
        res = execute_action(sub, ctx, runtime, depth=depth + 1)
        side_effects.extend(res.side_effects)
    return ActionResult(True, side_effects)


def apply_lifesteal(
    damage: int, pct: float, actor: str, ctx: DamageCtx, runtime: EffectRuntime
) -> int:
    """L0 结算修正器·生命偷取（细化_1b §3.2 / 定稿 §3.2）：造成伤害时按伤害 % 回复生命。"""
    heal = int(round(damage * pct / 100.0))
    c = ctx.snapshot.get(actor)
    if isinstance(c, dict) and heal > 0:
        c["hp"] = min(int(c.get("max_hp", 0)), int(c.get("hp", 0)) + heal)
    return heal


def apply_pierce(defense: int, pct: float) -> int:
    """L0 结算修正器·穿透（细化_1b §3.2 / 定稿 §7.1③）：有效防御 = 防御×(1−穿透%)。"""
    return int(round(defense * (1 - max(0.0, pct) / 100.0)))


def apply_mitigation(
    value: int, scope: str, target: str, ctx: DamageCtx, runtime: EffectRuntime
) -> None:
    """L0 结算修正器·减伤（细化_1b §3.2 / 定稿 §7.2②）：向目标防御行追加减伤条目。"""
    defs = ctx.snapshot.get(target, {}).get("defenses")
    if isinstance(defs, dict):
        defs.setdefault("mitigation", []).append({"value": value, "scope": scope})
