"""状态实例领域类型 Duration / StatusInstance。

依据：细化_3a_架构分层契约 §3.2（StatusInstance 字段要点：status_id+name 冗余、
level、stacks、duration{turns,charges}、衰减、来源）；细化_1b_效果系统契约
（状态四模型字段：turns/charges 双形、衰减类型、来源）。

⚠️ 当前实现口径（P1-2 复查登记）：效果系统实际以 dict 形态落地
（core/effects.py status_state：decay 为**字符串衰减类型** halve/decrement/
trigger/none + decay_subject/value 键，duration 扁平为 turns/charges）。
本 dataclass 为契约 spec 类型（3a §3.2 唯一落点声明），字段形态与 effects.py
不一致——M1 效果系统接线时须收敛对齐（补 decay_subject/value、decay 改 str
类型）或提供互转函数，收敛前禁止把本类型直接灌入 effects 系统。

frozen=True：状态实例不可变（细化_3a §3.2，U3）。
"""

from dataclasses import dataclass

from qbot_rpg.data.types import StatusID

__all__ = ["Duration", "StatusInstance"]


@dataclass(frozen=True)
class Duration:
    """状态时长：回合数 + 次数（双形，任一生效按效果系统语义）。"""

    turns: int        # 剩余回合数
    charges: int      # 剩余触发次数


@dataclass(frozen=True)
class StatusInstance:
    """运行时状态实例（战斗 buff/负面状态持有对象）。

    status_id+name 冗余存储（SCHEMA-5 / MIG-3：引用按 ID 存储、显示按名字）。
    """

    status_id: StatusID
    name: str                                 # 冗余名称（MIG-3）
    level: int                                # 状态等级
    stacks: int                               # 叠加层数
    duration: Duration                        # {turns, charges} 双形
    decay: float                              # 衰减值（spec 字段；⚠️ 与 effects.py 实际 str 衰减类型不一致，见文件头收敛说明）
    source: str                               # 来源（效果/药剂 ID 等）
