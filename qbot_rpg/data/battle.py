"""战斗快照领域类型 CombatantSnapshot / BattleSnapshot。

依据：细化_3a_架构分层契约 §3.2（BattleSnapshot 字段要点：会话类型、双方
CombatantSnapshot、回合数、combo_state、ai_state、status_state、marks_state、
resist_table、effect_triggers/cooldowns、formula_state{random_seed}；CombatantSnapshot
为 frozen 正例，细化_规则 L81-87 原样）；细化_1g1c_战斗状态数据（会话快照全量
状态登记）；细化_4a_存储层契约 §0.1 术语表（会话快照 ID+名称冗余存储，按旧配置
结算，D-05 —— storage 经此快照持久化，结算语义归会话管理器）。

⚠️ 当前实现口径（P1-3 复查登记）：实际战斗快照以 **1g3 dict 格式**落地
（core/battle.py `to_snapshot()` 返回 Dict：schema_version/snapshot_at/context/
units/ai_state/combo_state/turn/stats_collector/...），字段结构与本 dataclass
（player/enemy(CombatantSnapshot)/resist_table/effect_triggers...）**不同**。
本 dataclass 为契约 spec 类型（3a §3.2 唯一快照类型声明），M1 会话接线时须把
to_snapshot 收敛为本类型构造（player/enemy 映射 CombatantSnapshot、formula_state
注入 random_seed）或登记双轨保留——收敛前 U3「frozen 防误改」对真实 dict 快照
未生效。

formula_state 含 random_seed 键：中断恢复后同一回合随机序列一致（4a TC-17）。
frozen=True：快照不可变，防战斗中被误改（U3；细化_1g3 快照续战）。
"""

from dataclasses import dataclass, field
from typing import Dict

__all__ = ["CombatantSnapshot", "BattleSnapshot"]


@dataclass(frozen=True)
class CombatantSnapshot:
    """战斗参与者快照（玩家/敌方通用；name 为冗余存储，ID+名称冗余思路 SCHEMA-5）。"""

    max_hp: int
    hp: int
    atk: int
    dfn: int
    mag: int
    spd: int
    name: str                                 # 冗余名称（MIG-3：引用按 ID、显示按名字）


@dataclass(frozen=True)
class BattleSnapshot:
    """进行中战斗会话的全量快照（1v1 回合制，一轮一条消息）。

    各 *_state 为纯 JSON 可序列化 map：
      - combo_state   连段状态（细化_1c1a 连段状态集）
      - ai_state      怪物 AI 状态机（细化_1f）
      - status_state  状态实例（细化_1g1c）
      - marks_state   印记状态（细化_1d）
      - resist_table  抗性表
      - effect_triggers / effect_cooldowns  效果系统触发/冷却登记（细化_1b）
      - formula_state 公式求值状态，**必含 random_seed 键**（4a TC-17 随机序列往返）
    """

    session_type: str                         # 'battle'（sessions.session_type CHECK 约束）
    player: CombatantSnapshot
    enemy: CombatantSnapshot
    turn: int
    combo_state: Dict[str, object] = field(default_factory=dict)
    ai_state: Dict[str, object] = field(default_factory=dict)
    status_state: Dict[str, object] = field(default_factory=dict)
    marks_state: Dict[str, object] = field(default_factory=dict)
    resist_table: Dict[str, object] = field(default_factory=dict)
    effect_triggers: Dict[str, object] = field(default_factory=dict)
    effect_cooldowns: Dict[str, int] = field(default_factory=dict)
    formula_state: Dict[str, object] = field(default_factory=dict)  # 必含 random_seed 键
