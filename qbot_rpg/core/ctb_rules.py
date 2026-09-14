"""CTB 规则层（纯规则/常量，无状态）—— CTB 重写 · Agent 2（调度器架构）。

依据：
  - docs/ctb/01_asset_inventory.md §0.2「CTB 事件位点词典」（10 种事件：BATTLE_START /
    ACTOR_READY / BEFORE_ACTION / ACTION_RESOLVE / AFTER_ACTION / ACTOR_TURN_START /
    ACTOR_TURN_END / BATTLE_TIME_ADVANCE / ACTOR_DEATH / BATTLE_END）；
    §0.1 三分类口径（【删除】类保留同名壳，本层只管时序规则，不碰引擎实现）。
  - 需求文档（CTB 重写）给定核心公式（本文档唯一权威落值）：
        next_ready = current_time + recovery(action) * speed_reference
                                   / max(effective_speed, min_speed) + action_delay

本文件 = **纯规则/常量层**（同 qbot_rpg/core 系「零 IO、无随机、同参必同值」口径）：
  - next_ready(...)            CTB 行动条推进公式（唯一实现，调度器只调用它）
  - recovery_for(action)       每 action 的行动恢复值查询（可配）
  - speed_reference / min_speed / action_delay  公式三参数默认值
  - CtbEvent / EVENT_ORDER     10 种事件枚举 + 冻结的确定性事件次序
  - CTB_TIEBREAK_RULE          tie-break 规则说明（冻结文本，供审计/文档引用）
  - TieBreakKey                tie-break 排序键（显式、确定性、可复现）
  - ActionBatchReport          多 NPC 行动合并上报载体（调度器产出、引擎消费）
  - CtbRuleConfig              规则参数聚合（可注入，默认对齐本文件常量）

硬约束（对齐仓库规范）：
  - 零 NoneBot import；仅标准库；不 import qbot_rpg.core.battle（调度层不得反向依赖引擎）。
  - 无 IO / 无随机 / 无 timer；同刻同参必同值。

【工程补白】（需求文档未逐字拍死、实现需收敛处，显式标注供审查）：
  1. 公式三参默认值：speed_reference=100.0（速度参照，SPD 100 时 recovery 即时），
     min_speed=1.0（速度下限保护，防除零/负速度），action_delay=0.0（基础延迟）。
     均可在 CtbRuleConfig / settings 中覆盖（对齐 worldtime 的「配置经构造注入」口径）。
  2. recovery 表 default_recovery：普通行动基准 100.0；重/轻行动由内容包在 action def 内
     给 recovery 键覆盖（未给 → 取 default_recovery）。键名兼容中英（recovery / 行动恢复）。
     **口径（2026-09-10 主 agent 裁决）：recovery 是「该 action 的总行动恢复值」**，
     不是「基础之上的附加」。即 next_ready 的增量 = recovery * speed_reference / speed，
     与 default_recovery 之间是**覆盖**关系而非叠乘。
     推论：需求文档 §25 黑盒场景 2 写「重技能 recovery=150 → P→E→E→P」，
     数学上要求 P 侧 recovery > 166.67（见 RECOVERY_DOC_EXAMPLE_MIN），
     故文档中的 150 为示例笔误；验收以「recovery=200 → P→E→E→P」为准（见 tests/ctb）。
  3. 被拒行动的时间代价（R-6 语义空洞，2026-09-10 用户裁决）：
     **零时间成本，直接重试**。四类门禁（energy_cost / consume_marks / combo_table /
     season）任一拒绝该行动时：
       - 不派发 ACTOR_TURN_START 及其后续链路事件（不构成一次行动）；
       - **不消费该单位的票据时间**——`next_ready` 保持原值，行动条不推进；
       - 玩家侧立即解除暂停，重新请求输入（可换一个可行指令）；
       - 拒绝原因经事件/返回值上报，不静默吞掉。
     即：被拒 = 该行动从未发生，时间轴不付出代价（对齐「试探性输入不应被惩罚」的体验口径）。
  4. tie-break 规则（冻结）：同 next_ready 时依次比较
        (a) effective_speed 降序（快者先动）
        (b) 阵营优先级升序（player=0 优先于 enemy=1；未知阵营=大值兜底）
        (c) actor_id 字典序升序（稳定 id，字符串化后比较）
     三级全等时（同 id 重复入队视为非法，调度器按 FIFO seq 兜底，保证确定性）。
     注（2026-09-10 复核）：该规则使同刻并列时高速方先动，属**刻意设计**；
     由此产生的「同刻连动」（如 SPD100 vs SPD75、recovery 均为 100 时 t=400 双方
     同时 ready → P 先动）是 CTB 递推的数学必然，非缺陷。
  5. event 次序 EVENT_ORDER 为**逻辑序**而非全局序：BATTLE_TIME_ADVANCE 在时间推进时
     单独派发；ACTOR_READY 之后紧跟 ACTOR_TURN_START → BEFORE_ACTION → ACTION_RESOLVE
     → AFTER_ACTION → ACTOR_TURN_END 为一次行动完整链路（调度器保证派发顺序）。
  6. ActionBatchReport 字段：为引擎上报多 NPC 连锁行动提供数据（batch 内每条 = 一次
     NPC 行动摘要），battle_time 区间 + actor 列表 + 事件序列；不承载伤害数值（引擎侧填）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "CtbEvent",
    "EVENT_ORDER",
    "CTB_TIEBREAK_RULE",
    "DEFAULT_RECOVERY",
    "SPEED_REFERENCE",
    "MIN_SPEED",
    "ACTION_DELAY",
    "TIME_UNIT",
    "DEFAULT_ACTION_TIME",
    "DEFAULT_AIR_TIME",
    "DEFAULT_AIR_EXTEND",
    "DEFAULT_TURN_COST",
    "DEFAULT_AIR_HIT_SHRINK",
    "DEFAULT_AIR_DROP_DELAY",
    "DEFAULT_COUNTER_REFUND",
    "SIDE_PRIORITY",
    "CtbRuleConfig",
    "TieBreakKey",
    "build_tiebreak_key",
    "next_ready",
    "recovery_for",
    "rounds_to_bars",
    "bars_to_rounds",
    "action_delay_for",
    "time_cost",
    "ActionBatchReport",
    "resolve_rule_config",
]

_logger = logging.getLogger("qbot_rpg.ctb_rules")


# ---------------------------------------------------------------------------
# 一、事件枚举（10 种，对齐 01_asset_inventory §0.2 事件位点词典）
# ---------------------------------------------------------------------------
class CtbEvent:
    """CTB 事件位点词典（10 种，冻结常量容器，禁止实例化）。

    对齐 docs/ctb/01_asset_inventory.md §0.2；调度器 emit / 引擎订阅均以本类常量为准，
    禁止散落字面量（防拼写漂移）。
    """

    BATTLE_START = "BATTLE_START"
    ACTOR_READY = "ACTOR_READY"
    BEFORE_ACTION = "BEFORE_ACTION"
    ACTION_RESOLVE = "ACTION_RESOLVE"
    AFTER_ACTION = "AFTER_ACTION"
    ACTOR_TURN_START = "ACTOR_TURN_START"
    ACTOR_TURN_END = "ACTOR_TURN_END"
    BATTLE_TIME_ADVANCE = "BATTLE_TIME_ADVANCE"
    ACTOR_DEATH = "ACTOR_DEATH"
    BATTLE_END = "BATTLE_END"

    def __new__(cls, *_: Any, **__: Any) -> "CtbEvent":  # pragma: no cover - 防实例化
        raise TypeError("CtbEvent 为常量容器，禁止实例化")


# 一次行动完整链路的**冻结次序**（调度器派发必须按此序；审计/测试可引用）
EVENT_ORDER: Tuple[str, ...] = (
    CtbEvent.BATTLE_START,
    CtbEvent.BATTLE_TIME_ADVANCE,
    CtbEvent.ACTOR_READY,
    CtbEvent.ACTOR_TURN_START,
    CtbEvent.BEFORE_ACTION,
    CtbEvent.ACTION_RESOLVE,
    CtbEvent.AFTER_ACTION,
    CtbEvent.ACTOR_TURN_END,
    CtbEvent.ACTOR_DEATH,
    CtbEvent.BATTLE_END,
)


# ---------------------------------------------------------------------------
# 二、公式参数默认值（需求文档给定公式的落值，可经 CtbRuleConfig 覆盖）
# ---------------------------------------------------------------------------
#: 普通行动的基准恢复值（recovery(action) 缺省）
DEFAULT_RECOVERY: float = 100.0
#: 速度参照（SPD == speed_reference 时，一次 recovery=DEFAULT_RECOVERY 的行动耗时 = recovery）
SPEED_REFERENCE: float = 100.0
#: 速度下限保护（防除零 / 防负速度 / 防极端高速无限连动）
MIN_SPEED: float = 1.0
#: 基础延迟（每次行动结算后叠加的固定时间片）
ACTION_DELAY: float = 0.0

#: 时间单位（行动条）：1 个标准时长（设计文「1 回合」）的行动条数——**隐性换算口径
#: （玩家不可见）**：设计文 / 内容中的「N 回合」时长 = N × 本值行动条。
#: 默认 1000.0（= 基准速度一次普攻的行动条时长；增补 v1 §〇 2026-09-11 拍板）。
#: 可经 CtbRuleConfig / settings["ctb"]["time_unit"] 覆盖（可调，勿硬编码）。
TIME_UNIT: float = 1000.0

#: 技能「行动时间」（反应类窗口时长，行动条）缺省值（增补 v1 §一）：
#: 技能 def 未显式给 action_time 时的兜底；默认 400.0（闪反标准示例）。
DEFAULT_ACTION_TIME: float = 400.0

#: 跃空维持（行动条）：进入空中后的默认维持时长——**隐性口径（玩家不可见）**；
#: 增补 v1 §四（2026-09-11 拍板）：跃空默认维持 2000 行动条；使用攻击/技能小幅延长
#: （见 DEFAULT_AIR_EXTEND），专用技可用技能自身 `air_extend` 大幅延长；到期自动落地。
#: 可经 CtbRuleConfig / settings["ctb"]["air_time"] 覆盖（可调，勿硬编码）。
DEFAULT_AIR_TIME: float = 2000.0

#: 空中攻击/技能每次「延长」的缺省值（行动条；增补 v1 §四：少量延长）。
#: 技能 def 可用自身 `air_extend`（正数）覆盖本缺省（大幅延长档参考 400~600）。
DEFAULT_AIR_EXTEND: float = 150.0

#: 怪物转向的行动条成本（增补 v1 §三）：「转向消耗行动条（时间成本）」的 1v1 落地
#: 切片——玩家绕背/侧移后，怪转回面向时其下次 ready 追加本值；目标未变不转向=零消耗。
#: 可经 CtbRuleConfig / settings["ctb"]["turn_cost"] 覆盖（可调）。
DEFAULT_TURN_COST: float = 400.0

#: 跃空窗口「对空命中缩短」缺省值（行动条）——跃空风险闭环（2026-09-11 批③实装）：
#: 怪物攻击命中空中玩家 → 该玩家各空中姿态窗口缩短本值（柔和档；**隐性口径，玩家不可见**）。
#: 可经 CtbRuleConfig / settings["ctb"]["air_hit_shrink"] 覆盖（可调，勿硬编码）。
DEFAULT_AIR_HIT_SHRINK: float = 400.0

#: 「被击落」行动条硬直缺省值（行动条）——对空必杀（action.air_drop="knockdown"）命中
#: 空中玩家 → 立即落地 + 倒地，且其下次 ready 追加本值（大硬直；**隐性口径，玩家不可见**）。
#: 可经 CtbRuleConfig / settings["ctb"]["air_drop_delay"] 覆盖（可调，勿硬编码）。
DEFAULT_AIR_DROP_DELAY: float = 400.0

#: 反击返还的行动条缺省值（怪猎采纳 C11）：防反/闪反成功时返还给玩家的时间
#: （`next_ready −= 本值`，不低于当前时刻）；范围参考 150~250。**隐性口径（玩家不可见）**。
#: 可经 CtbRuleConfig / settings["ctb"]["counter_refund"] 覆盖（可调，勿硬编码）。
DEFAULT_COUNTER_REFUND: float = 200.0

#: 黑盒验收场景 2 的 recovery 下界（供测试引用，避免魔数散落）。
#:
#: 推演（P SPD=100 / E SPD=75 / speed_reference=100 / 普攻 recovery=100）：
#:   E 的 ready 时刻 = 133.33, 266.67, 400.0 …
#:   P 用重技能后 ready = 100 + R * 100 / 100 = 100 + R
#:   欲使 E **连动两次**（P(慢)→E→E→P），需 E 第二次 ready 仍早于 P：
#:       100 + R > 266.67  →  R > 166.67
#: 故需求文档 §25 写「重技能 recovery=150」为示例笔误（算不出期望序列）；
#: 验收改用 RECOVERY_DOC_EXAMPLE_SLOW = 200（> 下界，稳定满足 P→E→E→P）。
RECOVERY_DOC_EXAMPLE_MIN: float = 166.66666666666666
#: 黑盒验收场景 2 实际采用的慢技能 recovery（总恢复值口径）
RECOVERY_DOC_EXAMPLE_SLOW: float = 200.0

#: 阵营优先级（tie-break 次级键）：数值小者先动；player 优先（01_asset_inventory §1.1 口径）
SIDE_PRIORITY: Mapping[str, int] = {
    "player": 0,
    "enemy": 1,
}
#: 未知阵营兜底优先级（排在所有已知阵营之后，仍保持确定性）
UNKNOWN_SIDE_PRIORITY: int = 1 << 30

#: tie-break 规则冻结文本（供审计/文档引用，禁止在别处重复描述造成漂移）
CTB_TIEBREAK_RULE: str = (
    "同 next_ready 时，依次比较：(a) effective_speed 降序；(b) 阵营优先级升序"
    "（player 优先于 enemy）；(c) actor_id 字典序升序。三级全等时按入队 seq FIFO 兜底。"
)


# ---------------------------------------------------------------------------
# 三、规则参数聚合（可注入；缺省对齐上文常量）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CtbRuleConfig:
    """CTB 规则参数（不可变；由调度器构造注入，缺省对齐模块常量）。

    字段：
      speed_reference: 速度参照（公式分子系数）
      min_speed:       速度下限保护
      action_delay:    基础延迟
      default_recovery: 普通行动缺省恢复值
      recovery_table:  按 action 标识的恢复值覆盖表（键可为 action id / kind）
      time_unit:       时间单位（行动条／标准时长；隐性换算口径，增补 v1 §〇）
      default_action_time: 技能「行动时间」（反应窗口）缺省值（增补 v1 §一）
      air_time:        跃空维持（行动条；隐性口径，增补 v1 §四）
      air_extend:      空中攻击/技能每次延长的缺省值（行动条；增补 v1 §四）
      turn_cost:       怪物转向的行动条成本（增补 v1 §三）
      air_hit_shrink:  对空命中缩短值（行动条；跃空风险闭环柔和档——怪物攻击
                       命中空中玩家时其窗口缩短，隐性口径）
      air_drop_delay:  被击落硬直——下次 ready 追加值（行动条；对空必杀
                       `air_drop=knockdown` 命中空中玩家，隐性口径）
      counter_refund:  反击返还的行动条（防反/闪反成功；隐性口径）
    """

    speed_reference: float = SPEED_REFERENCE
    min_speed: float = MIN_SPEED
    action_delay: float = ACTION_DELAY
    default_recovery: float = DEFAULT_RECOVERY
    recovery_table: Mapping[str, float] = field(default_factory=dict)
    time_unit: float = TIME_UNIT
    default_action_time: float = DEFAULT_ACTION_TIME
    air_time: float = DEFAULT_AIR_TIME
    air_extend: float = DEFAULT_AIR_EXTEND
    turn_cost: float = DEFAULT_TURN_COST
    air_hit_shrink: float = DEFAULT_AIR_HIT_SHRINK
    air_drop_delay: float = DEFAULT_AIR_DROP_DELAY
    counter_refund: float = DEFAULT_COUNTER_REFUND

    def with_overrides(self, overrides: Optional[Mapping[str, Any]]) -> "CtbRuleConfig":
        """返回覆盖部分字段后的新配置（缺省/非法值保持原值，不抛错）。

        :param overrides: 局部覆盖映射（None / 非 Mapping → 原样返回 self）
        :return: 新的 CtbRuleConfig（frozen，不修改自身）
        """
        if not overrides or not isinstance(overrides, Mapping):
            return self
        try:
            table = overrides.get("recovery_table", self.recovery_table)
            return CtbRuleConfig(
                speed_reference=_to_float(
                    overrides.get("speed_reference"), self.speed_reference
                ),
                min_speed=_to_float(overrides.get("min_speed"), self.min_speed),
                action_delay=_to_float(overrides.get("action_delay"), self.action_delay),
                default_recovery=_to_float(
                    overrides.get("default_recovery"), self.default_recovery
                ),
                recovery_table=table if isinstance(table, Mapping) else self.recovery_table,
                time_unit=_to_float(overrides.get("time_unit"), self.time_unit),
                default_action_time=_to_float(
                    overrides.get("default_action_time"), self.default_action_time
                ),
                air_time=_to_float(overrides.get("air_time"), self.air_time),
                air_extend=_to_float(overrides.get("air_extend"), self.air_extend),
                turn_cost=_to_float(overrides.get("turn_cost"), self.turn_cost),
                air_hit_shrink=_to_float(
                    overrides.get("air_hit_shrink"), self.air_hit_shrink
                ),
                air_drop_delay=_to_float(
                    overrides.get("air_drop_delay"), self.air_drop_delay
                ),
                counter_refund=_to_float(
                    overrides.get("counter_refund"), self.counter_refund
                ),
            )
        except Exception:  # pragma: no cover - 兜底不崩（规则层 fail-safe）
            _logger.exception("CtbRuleConfig.with_overrides 失败，回退原配置")
            return self


def resolve_rule_config(source: Any = None) -> CtbRuleConfig:
    """从多种来源解析出 CtbRuleConfig（settings / 已构造对象 / None 一律兜底）。

    支持来源：
      - CtbRuleConfig 实例 → 原样返回
      - Mapping（如 settings["ctb"] 段）→ 按字段覆盖缺省
      - None / 其它 → 返回默认配置

    :param source: 配置来源（任意类型，非法一律兜底默认）
    :return: 规范化后的 CtbRuleConfig（绝不抛错）
    """
    try:
        if isinstance(source, CtbRuleConfig):
            return source
        base = CtbRuleConfig()
        if isinstance(source, Mapping):
            # 兼容 settings 顶层包一层 {"ctb": {...}} 的形态
            inner = source.get("ctb")
            if isinstance(inner, Mapping):
                source = inner
            return base.with_overrides(source)
        return base
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("resolve_rule_config 失败，回退默认配置")
        return CtbRuleConfig()


# ---------------------------------------------------------------------------
# 四、公式实现（唯一实现点）
# ---------------------------------------------------------------------------
def _to_float(value: Any, default: float) -> float:
    """宽松数值化：非法 / None / bool → default（规则层不抛错）。"""
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_action_field(action: Any, keys: Sequence[str]) -> Any:
    """从 action（Mapping / 对象）按候选键名取值，均缺 → None。

    :param action: 行动定义（Mapping 或带属性的对象；None/非法 → None）
    :param keys: 候选键名（按优先级）
    :return: 首个命中的值或 None
    """
    if action is None:
        return None
    for key in keys:
        try:
            if isinstance(action, Mapping):
                if key in action:
                    return action[key]
            elif hasattr(action, key):
                return getattr(action, key)
        except Exception:  # pragma: no cover - 防御：对象属性访问异常
            continue
    return None


#: recovery 取值候选键（英 / 中）
_RECOVERY_KEYS: Tuple[str, ...] = ("recovery", "行动恢复")
#: action 标识候选键（用于 recovery_table 匹配）
_ACTION_ID_KEYS: Tuple[str, ...] = ("id", "action_id", "kind", "name")


def recovery_for(action: Any, config: Optional[CtbRuleConfig] = None) -> float:
    """查询某 action 的行动恢复值 recovery(action)（可配，缺省 DEFAULT_RECOVERY）。

    解析顺序：
      1) action 自带 recovery 键（recovery / 行动恢复）
      2) config.recovery_table 按 action 标识（id/action_id/kind/name）命中
      3) action 为裸数值 → 视为 recovery 本身
      4) 兜底 config.default_recovery

    :param action: 行动定义（Mapping / 对象 / 数值 / None）
    :param config: 规则配置（None → 默认配置）
    :return: recovery 值（非负浮点；非法输入 → default_recovery）
    """
    cfg = config or CtbRuleConfig()
    try:
        explicit = _extract_action_field(action, _RECOVERY_KEYS)
        if explicit is not None:
            val = _to_float(explicit, cfg.default_recovery)
            return _clamp_non_negative(val, cfg.default_recovery)

        if isinstance(action, (int, float)) and not isinstance(action, bool):
            return _clamp_non_negative(float(action), cfg.default_recovery)

        table = cfg.recovery_table or {}
        if table and action is not None:
            for id_key in _ACTION_ID_KEYS:
                ident = _extract_action_field(action, (id_key,))
                if ident is None:
                    continue
                ident_s = str(ident)
                if ident_s in table:
                    val = _to_float(table[ident_s], cfg.default_recovery)
                    return _clamp_non_negative(val, cfg.default_recovery)

        return cfg.default_recovery
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("recovery_for 失败，回退 default_recovery")
        return cfg.default_recovery


def rounds_to_bars(rounds: Any, config: Optional[CtbRuleConfig] = None) -> float:
    """设计文「N 个标准时长（回合）」→ 行动条（隐性换算口径；增补 v1 §〇）。

    换算：bars = N × time_unit（默认 1000 → ``rounds_to_bars(5) == 5000.0``）。
    非法 / None → 0.0；time_unit 非法（≤0）→ 回退模块默认 TIME_UNIT。

    :param rounds: 「N 回合」的 N（设计文口径；玩家不可见）
    :param config: 规则配置（None → 默认配置）
    :return: 对应行动条数（float，非负）
    """
    try:
        cfg = config or CtbRuleConfig()
        _unit = cfg.time_unit if (cfg.time_unit and cfg.time_unit > 0) else TIME_UNIT
        return max(0.0, _to_float(rounds, 0.0)) * float(_unit)
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("rounds_to_bars 失败，回退 0.0")
        return 0.0


def bars_to_rounds(bars: Any, config: Optional[CtbRuleConfig] = None) -> float:
    """行动条 → 设计文「N 个标准时长（回合）」（隐性换算口径；增补 v1 §〇）。

    换算：N = bars ÷ time_unit（默认 1000 → ``bars_to_rounds(5000) == 5.0``）。
    非法 / None → 0.0；time_unit 非法（≤0）→ 回退模块默认 TIME_UNIT。

    :param bars: 行动条数
    :param config: 规则配置（None → 默认配置）
    :return: 标准时长数（float）
    """
    try:
        cfg = config or CtbRuleConfig()
        _unit = cfg.time_unit if (cfg.time_unit and cfg.time_unit > 0) else TIME_UNIT
        return _to_float(bars, 0.0) / float(_unit)
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("bars_to_rounds 失败，回退 0.0")
        return 0.0


def _clamp_non_negative(value: float, default: float) -> float:
    """负值视为非法 → default（防 recovery 负值导致时间倒流）。"""
    if value < 0:
        return default
    return value


def action_delay_for(action: Any, config: Optional[CtbRuleConfig] = None) -> float:
    """查询某 action 的基础延迟 action_delay（action 自带键优先，缺省取 config）。

    :param action: 行动定义（Mapping / 对象 / None）
    :param config: 规则配置（None → 默认配置）
    :return: delay 值（非负浮点；非法 → config.action_delay）
    """
    cfg = config or CtbRuleConfig()
    try:
        explicit = _extract_action_field(action, ("action_delay", "延迟"))
        if explicit is None:
            return cfg.action_delay
        return _clamp_non_negative(_to_float(explicit, cfg.action_delay), 0.0)
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("action_delay_for 失败，回退 config.action_delay")
        return cfg.action_delay


def time_cost(
    action: Any,
    effective_speed: Any,
    config: Optional[CtbRuleConfig] = None,
) -> float:
    """单次行动的时间代价 = recovery(action) * speed_reference / max(speed, min_speed) + delay。

    :param action: 行动定义（recovery 来源）
    :param effective_speed: 单位有效速度（含增益/减益后的值；非法 → 走下限保护）
    :param config: 规则配置（None → 默认配置）
    :return: 非负时间代价（浮点）
    """
    cfg = config or CtbRuleConfig()
    try:
        rec = recovery_for(action, cfg)
        delay = action_delay_for(action, cfg)
        spd = _to_float(effective_speed, cfg.min_speed)
        guard = max(spd, cfg.min_speed)  # min_speed 下限保护（防除零/防负速度）
        if guard <= 0:  # 理论上被 min_speed 挡住；此处为极端配置兜底
            guard = abs(cfg.min_speed) or MIN_SPEED
        cost = rec * cfg.speed_reference / guard + delay
        return cost if cost >= 0 else 0.0
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("time_cost 计算失败，回退 0 时间片")
        return 0.0


def next_ready(
    current_time: Any,
    action: Any,
    effective_speed: Any,
    config: Optional[CtbRuleConfig] = None,
) -> float:
    """CTB 核心公式：next_ready = current_time + recovery * speed_reference
    / max(effective_speed, min_speed) + action_delay。

    需求文档给定公式的**唯一实现点**；调度器只调用本函数，不自行拼公式。

    :param current_time: 当前逻辑时间（秒；非法 → 0.0）
    :param action: 行动定义（recovery / action_delay 来源）
    :param effective_speed: 单位有效速度（下限保护 min_speed）
    :param config: 规则配置（None → 默认配置）
    :return: 新的 ready 时刻（= current_time + 时间代价）
    """
    cfg = config or CtbRuleConfig()
    try:
        now = _to_float(current_time, 0.0)
        cost = time_cost(action, effective_speed, cfg)
        result = now + cost
        _logger.debug(
            "next_ready: now=%.4f cost=%.4f -> %.4f (speed=%s min_speed=%s)",
            now, cost, result, effective_speed, cfg.min_speed,
        )
        return result
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("next_ready 计算失败，回退 current_time")
        return _to_float(current_time, 0.0)


# ---------------------------------------------------------------------------
# 五、tie-break 排序键
# ---------------------------------------------------------------------------
# TieBreakKey 元组字段序（冻结）：(next_ready, -effective_speed, side_priority, actor_id)
#   - next_ready 升序（最小者先动）
#   - effective_speed 取负 → 降序（快者先动）
#   - side_priority 升序（player 优先）
#   - actor_id 字典序升序（稳定 id 兜底）
TieBreakKey = Tuple[float, float, int, str]


def build_tiebreak_key(
    next_ready_time: Any,
    effective_speed: Any,
    side: Any,
    actor_id: Any,
) -> TieBreakKey:
    """构造 tie-break 排序键（元组可直接排序；规则冻结见 CTB_TIEBREAK_RULE）。

    :param next_ready_time: 该单位的下次 ready 时刻
    :param effective_speed: 有效速度（降序 → 取负）
    :param side: 阵营（player/enemy；未知 → UNKNOWN_SIDE_PRIORITY）
    :param actor_id: 稳定单位标识（字符串化后字典序）
    :return: (next_ready, -speed, side_priority, str(actor_id))
    """
    side_key = SIDE_PRIORITY.get(str(side), UNKNOWN_SIDE_PRIORITY)
    try:
        return (
            _to_float(next_ready_time, 0.0),
            -_to_float(effective_speed, 0.0),
            int(side_key),
            str(actor_id),
        )
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("build_tiebreak_key 失败，回退全兜底键")
        return (0.0, 0.0, UNKNOWN_SIDE_PRIORITY, str(actor_id))


# ---------------------------------------------------------------------------
# 六、多 NPC 行动合并上报载体
# ---------------------------------------------------------------------------
@dataclass
class ActionBatchReport:
    """多 NPC 连锁行动的**合并上报**载体（调度器产出、引擎消费）。

    可暂停输入式 CTB 语义：NPC 连锁行动时引擎自动推进不等待输入；多个 NPC 行动在
    玩家 Ready 之前**合并为一次上报**（本对象），到玩家 Ready 时暂停并把控制权交还。

    字段：
      entries:        每次 NPC 行动的摘要条目（dict：actor_id/side/event/time/action 等；
                      伤害数值等由引擎在消费时填入，调度器只填时序骨架）
      start_time:     本批次起始逻辑时间
      end_time:       本批次结束逻辑时间
      paused_actor_id: 触发暂停的玩家 actor id（None → 未因玩家而暂停）
      paused_ready_at: 触发暂停的时刻（None → 未暂停）
    """

    entries: List[Dict[str, Any]] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    paused_actor_id: Optional[str] = None
    paused_ready_at: Optional[float] = None

    def add(self, entry: Mapping[str, Any]) -> None:
        """追加一条 NPC 行动摘要（非 Mapping → 忽略，不抛错）。"""
        if isinstance(entry, Mapping):
            self.entries.append(dict(entry))

    @property
    def count(self) -> int:
        """批次内 NPC 行动条数。"""
        return len(self.entries)

    @property
    def actor_ids(self) -> List[str]:
        """批次涉及的 actor id 列表（去重保序）。"""
        seen: List[str] = []
        for e in self.entries:
            aid = str(e.get("actor_id", ""))
            if aid and aid not in seen:
                seen.append(aid)
        return seen

    @property
    def event_sequence(self) -> List[str]:
        """批次内事件名序列（按时序；供审计/复现断言）。"""
        return [str(e.get("event", "")) for e in self.entries]

    def mark_pause(self, actor_id: Any, ready_at: Any) -> None:
        """登记触发暂停的玩家 actor 与时刻。"""
        self.paused_actor_id = str(actor_id)
        try:
            self.paused_ready_at = _to_float(ready_at, 0.0)
        except Exception:  # pragma: no cover
            self.paused_ready_at = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化（JSON 友好；引擎/渲染层消费）。"""
        return {
            "entries": [dict(e) for e in self.entries],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "paused_actor_id": self.paused_actor_id,
            "paused_ready_at": self.paused_ready_at,
            "count": self.count,
            "actor_ids": self.actor_ids,
        }
