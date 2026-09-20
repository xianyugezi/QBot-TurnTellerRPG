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

【批74 BUG-3 裁定：保留，不是死代码（防后人再删）】
  审计3 F6 记为「死表示」（运行时真身 = core/effects.py 的 dict 形态），但本类型
  同时是架构门禁 **TC-04** 的必需类型之一（`scripts/check_architecture.py:49-51`
  的 `REQUIRED_TYPES`；`check_tc04` 对「未定义」直接判 fail → `exit 1`）。
  删除它会连带：① 门禁 `REQUIRED_TYPES` 需评审调整；② `tests/unit/test_data.py:19`
  的 frozen 参数化；③ `qbot_rpg/data/__init__.py` 导出；④ 本文件 docstring 与
  手册 §六。属**架构契约变更**，不是死码清理，故阈值内**保留**。
  何时可删：先完成「契约 spec ↔ 运行期 dict」双轨收敛决策（接线为运行期真身，
  或评审撤销该契约类型）→ 再删本类型 + 从 `REQUIRED_TYPES` 移除同名条目
  （门禁不得留空条目空转）+ 同步测试/导出/本注释/手册 §六。
"""

from dataclasses import dataclass

from qbot_rpg.data.types import StatusID

__all__ = ["Duration", "StatusInstance"]


@dataclass(frozen=True)
class Duration:
    """状态时长：行动数 + 次数（双形，任一生效按效果系统语义）。"""

    turns: int        # 剩余行动数
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
