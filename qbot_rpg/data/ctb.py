"""CTB 静态数据层（行动恢复值表 + 行动种类标识）—— 纯数据，零依赖。

归属：Agent 5 · 数据与渲染迁移（DataRender），CTB 重写 Wave B。
架构修复：2026-09-10 主 Agent —— 原实现 `from qbot_rpg.core.ctb_rules import ...`
违反 TC-03 依赖矩阵（`data` 层允许依赖集为 `set()`，见 细化_3a §1.4）。
现按分层契约收敛：**本文件只承载字面量数据，不 import 任何 qbot_rpg 层**；
一切「读配置 / 解析 / 构造 CtbRuleConfig」的逻辑迁至 `qbot_rpg/core/ctb_config.py`。

依据：
  - docs/ctb/02_wave_a_decisions.md 裁决 1：recovery 是「该 action 的**总**行动恢复值」，
    与基准值是**覆盖**关系而非附加。
  - 细化_3a §1.4 依赖矩阵（data 层零依赖）+ §3.2 五类契约类型。

分工（分层口径）：
  - `data/ctb.py`（本文件）：**数据**——行动种类标识、按种类的默认恢复值、键名常量。
  - `core/ctb_config.py`：**逻辑**——内容包 action.json 解析、覆盖表构建、配置装配。

硬约束（对齐仓库规范）：
  - 零 NoneBot import；**仅标准库**（不 import qbot_rpg 任何层）。
  - 无 IO / 无随机 / 无定时器；同刻同参必同值。

数值权威落点说明：本文件的默认恢复值（100.0）与 `core/ctb_rules.DEFAULT_RECOVERY`
取同一数值。二者是**分层职责分离**（data 给字面量、core 给运行期规则），
`core/ctb_config.py` 在装配时会做一致性校验，防两处漂移。
"""

from __future__ import annotations

from typing import Dict, Mapping

__all__ = [
    # —— 行动种类标识 ——
    "ACTION_KIND_BASIC",
    "ACTION_KIND_SKILL",
    "ACTION_KIND_ITEM",
    "ACTION_KIND_GUARD",
    "ACTION_KIND_FLEE",
    # —— 恢复值数据 ——
    "DEFAULT_ACTION_RECOVERY",
    "ACTION_RECOVERY_TABLE",
    "HEAVY_RECOVERY_HINT",
    # —— 时间标准（隐性换算口径；增补 v1 §〇/§一）——
    "DEFAULT_TIME_UNIT",
    "DEFAULT_ACTION_TIME",
    # —— 键名常量 ——
    "RECOVERY_KEY",
    "RECOVERY_KEY_CN",
    # —— 类型 ——
    "ActionRecoveryTable",
    # —— settings 配置段默认值（纯数据）——
    "DEFAULT_CTB_SETTINGS",
]


# ---------------------------------------------------------------------------
# 一、行动种类标识（对齐内容包 action.json 的 kind 字段；小写）
# ---------------------------------------------------------------------------
ACTION_KIND_BASIC: str = "basic"
ACTION_KIND_SKILL: str = "skill"
ACTION_KIND_ITEM: str = "item"
ACTION_KIND_GUARD: str = "guard"
ACTION_KIND_FLEE: str = "flee"


# ---------------------------------------------------------------------------
# 二、行动恢复值（字面量数据；口径见 02_wave_a_decisions.md 裁决 1）
# ---------------------------------------------------------------------------
#: 内容包 action.json 未给 recovery 键、种类也未命中时的兜底值。
#: = 普通行动的基准恢复值（与 core/ctb_rules.DEFAULT_RECOVERY 同值，由 ctb_config 校验）。
DEFAULT_ACTION_RECOVERY: float = 100.0

#: 按行动种类的行动恢复值表（该 action 的**总**恢复值；未列出的种类 → DEFAULT_ACTION_RECOVERY）。
#:
#: 口径：recovery 是「总行动恢复值」，与基准值是**覆盖**关系而非附加；
#: next_ready 增量 = recovery * speed_reference / max(speed, min_speed) + delay。
#: 内容包可在 action.json 的每个 action 上写 recovery 键覆盖本表
#: （解析逻辑见 core/ctb_config.py 的 resolve_action_recovery）。
ACTION_RECOVERY_TABLE: Mapping[str, float] = {
    ACTION_KIND_BASIC: DEFAULT_ACTION_RECOVERY,   # 普攻：基准 100
    ACTION_KIND_SKILL: DEFAULT_ACTION_RECOVERY,   # 技能：缺省 100（重技能由 action 覆盖）
    ACTION_KIND_ITEM: DEFAULT_ACTION_RECOVERY,    # 道具：缺省 100
    ACTION_KIND_GUARD: DEFAULT_ACTION_RECOVERY,   # 防御：缺省 100
    ACTION_KIND_FLEE: DEFAULT_ACTION_RECOVERY,    # 逃跑：缺省 100
}

#: 内容包 action.json 中判为「重行动」的参考阈值（供文档/审计）。
#: 仅作**提示性**参考，不参与任何计算（是否重由内容包显式给值决定）。
#: 来源：docs/ctb/02_wave_a_decisions.md 裁决 1 推演的阈值下界 166.67 之上取整。
HEAVY_RECOVERY_HINT: float = 200.0


#: 时间单位（行动条）：1 个标准时长（设计文「1 回合」）的行动条数——**隐性换算口径
#: （玩家不可见）**。「N 回合」= N × 本值。默认 1000.0（= 基准速度一次普攻时长；
#: 增补 v1 §〇 2026-09-11 拍板；可调，与 core/ctb_rules.TIME_UNIT 同值、由 ctb_config 校验）。
DEFAULT_TIME_UNIT: float = 1000.0

#: 技能「行动时间」（反应窗口时长，行动条）缺省值；默认 400.0（增补 v1 §一）。
DEFAULT_ACTION_TIME: float = 400.0


# ---------------------------------------------------------------------------
# 三、键名常量（内容包 recovery 键的中英候选，解析逻辑在 core/ctb_config.py）
# ---------------------------------------------------------------------------
RECOVERY_KEY: str = "recovery"
RECOVERY_KEY_CN: str = "行动恢复"

#: recovery 覆盖表类型：{action 标识: 总恢复值}
ActionRecoveryTable = Dict[str, float]


# ---------------------------------------------------------------------------
# 四、settings["ctb"] 默认值（纯数据；读取逻辑在 core/ctb_config.py）
# ---------------------------------------------------------------------------
#: CTB 开关 + 数值配置项默认值（内容包 settings.json 的 "ctb" 段可覆盖任意键）。
#:
#: 字段与 core/ctb_rules.CtbRuleConfig 同名，可直接喂给 resolve_rule_config / CTBScheduler。
DEFAULT_CTB_SETTINGS: Mapping[str, object] = {
    "enabled": True,
    "speed_reference": 100.0,
    "min_speed": 1.0,
    "action_delay": 0.0,
    "default_recovery": DEFAULT_ACTION_RECOVERY,
    "recovery_table": {},
    "time_unit": DEFAULT_TIME_UNIT,
    "default_action_time": DEFAULT_ACTION_TIME,
}
