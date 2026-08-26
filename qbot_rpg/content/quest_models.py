"""任务数据模型 —— M4 批次2·路C1 **占位壳**（批次4·路D1 填充实现）。

依据：m4_shared_contract §3.3（任务 D1-D5：三原语引擎 / 统一 reward / 每日防刷 / 主线置顶）
      + §4 批次派工单（批次 4 任务：quest_models.py / core/quest.py / quest 指令接线）。

本文件 = 批次2·路C1 仅建占位壳（class QuestDef + 常量），供校验器/loader 以稳定接口名注册；
批次 4·路D1 再填充完整实现（三原语条件/奖励/每日防刷/主线置顶，m4 §3.3 D1-D5）。

【工程补白】占位壳：本文件不含任何校验逻辑；loader DEF_CLASSES 侧暂不指向本类
（批次 4 收口时接入，同 map_models/npc_models 收口模式）。常量按 m4 §3.3 口径定型，
实现时不得偏离。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；
工程补白显式标注；文件头标注依据；不 git commit。
仅依赖 qbot_rpg.content.models 的 BaseDef。
"""

from __future__ import annotations

from dataclasses import dataclass

from qbot_rpg.content.models import BaseDef

# -------------------------------------------------------------------------------------
# 任务发放常量（m4_shared_contract §3.3 D1-D5 口径；批次 4·路D1 实现不得偏离）
# -------------------------------------------------------------------------------------
QUEST_MODULE: str = "quest"  # quest.json 模块名（loader _KIND_FOR_MODULE 口径；批次 4 登记）
QUEST_DAILY_LIMIT_DEFAULT: int = 10  # 每日接取上限（daily_limit≤10）
QUEST_ACCEPT_LIMIT_DEFAULT: int = 5  # 同时活跃任务上限（accept_limit≤5）
QUEST_MAIN_FIELD: str = "main"  # 主线置顶字段（定稿 L138 命名；main:true 常驻）
QUEST_CONDITIONS_ARRAY_ALL: str = "conditions 数组全与 + 支持 {all:[...]} 嵌套（2b4 D-02）"


@dataclass(frozen=True)
class QuestDef(BaseDef):
    """quest.json 条目（**占位壳**——批次 4·路D1 填充：三原语条件 / 统一 reward /
    每日防刷（daily_limit/accept_limit/quest_daily/完成即移出）/ 主线置顶 main:true）。

    当前仅为稳定接口名（供校验器/loader/收口注册）；字段访问器与校验逻辑由
    批次 4·路D1（quest_models.py 实装）补齐。
    """


__all__ = [
    "QuestDef",
    "QUEST_MODULE",
    "QUEST_DAILY_LIMIT_DEFAULT",
    "QUEST_ACCEPT_LIMIT_DEFAULT",
    "QUEST_MAIN_FIELD",
    "QUEST_CONDITIONS_ARRAY_ALL",
]
