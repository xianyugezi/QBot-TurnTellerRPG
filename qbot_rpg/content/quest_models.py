"""任务数据模型 —— M4 批次4·路E1：QuestDef 全字段（17 顶层 + board/timed/npc 子表）+ 三原语条件 + 防刷 + validate_quests。

依据：
  - m4_shared_contract §3.3（任务 D1-D5：三原语引擎 / 统一 reward / 每日防刷（daily_limit≤10 /
    accept_limit≤5 / quest_daily / 完成即移出）/ 主线置顶（main:true 常驻））
  - 细化_2b4_任务引擎契约.md（quest.json 字段级 schema：17 顶层字段 §1.2 / board 5 key §1.3 /
    npc 3 key §1.4 / timed 2 key（D-06）/ 三原语 §二 / reward 统一条目 §三 / 防刷三表 §四 /
    任务板双板 §五 / 验收 TC-01~TC-31 + 2026-08-27 M4 设计审查裁决 P1-1/P1-2：D-03 改标
    【工程补白】、发放器逐条目失败黄字跳过不中断整批）
  - 审查参考/任务系统设计定稿.md（L138 main 命名（P3-1：定稿原文非收敛）/ L181-187 板规则 /
    L183 接取上限 ≤5 / L184 每日完成上限 ≤10 / L205 完成即移出 / L276 校验器硬拦 4 类）
  - 2026-08-27 M4 设计审查裁决（设计审查_批次4，审查_M4设计_批次4_jspace.md）：
    P1-1（D-03 求值失败默认不满足 → 改标【工程补白】，依据改任务定稿 L277 黄提示体系 + L10 碎片化）
    P1-2（发放器逐条目失败黄字跳过；单事务=结算簿记原子性）
    P2-1（main「接收时不占 accept_limit 亦可配」未登记 → 删除该可配豁免，主线计入行数）
    P2-2（daily 顶层字段与默认板矛盾 → 收敛为 board.slot 简写，见【工程补白】2）
    P3-1（main 沿用定稿 L138 命名，不是细化收敛）

本文件 = 批次2·路C1 占位壳的批次4·路E1 实装（唯一文件）：
  - QuestDef 17 顶层字段访问器 + BoardDef/TimedDef/NpcGrantDef 三子表（2b4 §1.2~1.4）
  - 三原语条件校验（值型/累计型/事件型）：结构校验本地镜像 engine/condition_engine，
    求值权威 = A2 condition_engine（运行时 core/quest.py 调用）
  - validate_quests(modules, report) 专项校验（引用悬空 / 每日防刷默认 10 / 接取上限默认 5 /
    条件结构 / 双板 slot），纯函数供主 agent 收口接入 check_pack

【工程补白】（契约/定稿未显式定义处，显式标注供审查，不冒充定稿行号）：
  1. 条件结构校验 = 本地镜像 engine/condition_engine.validate_condition 规则（var 注册表 /
     9 运算符 / 组合嵌套 / 旧格式与事件未登记黄提示），content→data 单向铁律（细化_3a §2.2）
     不得反向依赖 engine——与 npc_models/shop_models 同口径；求值权威 = condition_engine（A2）。
  2. P2-2 收敛：daily 顶层字段保留为 **board.slot 简写**——`daily:true` ≡
     `board:{slot:"daily", refresh:"daily"}`；`daily:false`/缺省 = 不施加简写（**不表达「非每日板」**，
     与默认板=每日板不再矛盾）。非每日板一律显式配 `board.slot:"weekly"/"event"`。生效槽位 =
     board.slot 显式 > daily:true 简写 > 默认 "daily"；`is_daily_board` 派生属性承载 P2-2
     建议的「daily 缺省判据」。daily:true 与 board.slot 显式≠daily 同给 → 黄提示互斥
     （2b4 §1.2 row16「与 board 对象同给 → 互斥黄提示」）。
  3. reward 结构校验本地镜像 core/reward 条目 schema（{item|id,count} 物品 / coins·gem·exp·rep
     标量键值 / 组合数组）；内联键值串（D-05 序列化糖）展开归 core/reward 导入器，本层对非空串
     结构放行。`rewards` 为等价别名（D-01），同给异值 → 黄提示「奖励字段重复」。
  4. board.limit 默认 0=不限（幻觉审查_2b4 P2-2 补白：D-07 默认兜底清单未覆盖 limit 默认值）。
  5. zone 引用靶 = maps ∪ dungeon 两模块 id 并集（任务定稿 L104「ref dungeon.json / maps.json」）；
     npc.id 引用靶 = npc 模块（任务定稿 L143-145）。
  6. unlock_chain 引用悬空 → 黄提示「链式任务死链」（2b4 §1.5 黄提示族），非硬拦——
     硬拦清单（任务定稿 L276）仅含物品/怪物/变量/zone 引用不存在。
  7. 双板仲裁（裸 /任务 /接取 /交付 → 玩家任务板；/委托 → 委托板，任务定稿 L190-194）为
     指令层（core/quest.py + 指令接线）职责；本模型只承载 board.slot 多板（daily/weekly/event）
     与板级防刷字段。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；纯函数/懒计算；
确定性；工程补白显式标注；文件头标注依据；不 git commit。
仅依赖 qbot_rpg.content.models 的 BaseDef + qbot_rpg.content.field_meta 的 DEFAULT_CURRENCY_IDS。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, cast

from qbot_rpg.content.field_meta import DEFAULT_CURRENCY_IDS
from qbot_rpg.content.models import BaseDef

# =====================================================================================
# 任务发放常量（m4_shared_contract §3.3 D1-D5 + 2b4 §1.2 + 任务定稿 L138/L183/L184）
# =====================================================================================
QUEST_MODULE: str = "quest"  # quest.json 模块名（loader _KIND_FOR_MODULE 口径；批次 4 收口登记）
QUEST_DAILY_LIMIT_DEFAULT: int = 10  # 每日接取/完成上限默认（任务定稿 L184：≤10，0=不限）
QUEST_ACCEPT_LIMIT_DEFAULT: int = 5  # 同时接取上限默认（任务定稿 L183：≤5，0=不限）
QUEST_MAIN_FIELD: str = "main"  # 主线置顶字段（任务定稿 L138 命名 main: true；P3-1：定稿原文）
QUEST_TYPE_DEFAULT: str = "collect"  # type 展示标签默认（任务定稿 L97；非判定依据）
QUEST_CONDITIONS_ARRAY_ALL: str = "conditions 数组全与 + 支持 {all:[...]} 嵌套（2b4 D-02）"

# board 任务板（2b4 §1.3：5 key；任务定稿 L181-187）
BOARD_SLOTS: Tuple[str, ...] = ("daily", "weekly", "event")  # 多板槽位（L181）
BOARD_SLOT_DEFAULT: str = "daily"  # 默认板 = 每日板（D-07 / P2-2）
BOARD_REFRESH_MODES: Tuple[str, ...] = ("daily", "weekly", "once")  # 刷新模式（L182）
BOARD_REFRESH_DEFAULT: str = "daily"  # 每日懒计算刷新（05:00 可配，与签到/商店同刻对齐）
BOARD_LIMIT_DEFAULT: int = 0  # 板上限默认 0=不限（【工程补白】4：D-07 未覆盖，幻觉审查_2b4 P2-2）
BOARD_LIMIT_OVER_WARN: int = 10  # 每日完成上限超默认阈值（>10 → 黄提示）
BOARD_ACCEPT_OVER_WARN: int = 5  # 同时接取上限超默认阈值（>5 → 黄提示）

# reward 统一条目（2b4 §三：物品/货币键值/组合数组；D-05 内联串=糖；rewards 别名 D-01）
REWARD_SCALAR_KEYS: Tuple[str, ...] = ("coins", "gem", "exp", "rep")  # 货币/数值键值条目键
REWARD_ITEM_KEYS: Tuple[str, ...] = ("item", "id")  # 物品条目键（item 主键，id ≡ item，L126）
REWARD_COUNT_KEY: str = "count"  # 物品数量键
REWARD_BOUND_KEY: str = "bound"  # 物品绑定标记（reward.py 扩展字段，结构校验放行）

# timed 限时修饰符（2b4 §1.2#10 / D-06：{deadline, penalty}）
TIMED_KEYS: Tuple[str, ...] = ("deadline", "penalty")

# repeatable 重复衰减（2b4 §1.2#17：false=完成即移出；true=可重复；obj={decay,cap}；任务定稿 L185）
REPEATABLE_KEYS: Tuple[str, ...] = ("decay", "cap")

# 条件引擎镜像常量（【工程补白】1：本地镜像 engine/condition_engine，不 import engine）
COND_OPERATORS: Tuple[str, ...] = ("gt", "ge", "lt", "le", "eq", "ne", "between", "is", "not")
COND_OP_SYMBOLS: Dict[str, str] = {
    ">=": "ge", ">": "gt", "<=": "le", "<": "lt", "=": "eq", "!=": "ne",
}  # op 双写等价（任务定稿 L37）
# var 键空间（NPC 4.3 九类 + 签到/事件/扩展；扁平注册表——与 engine condition_engine 同源）
COND_VARS: Dict[str, str] = {
    "has_quest": "任务类", "quest_completed": "任务类", "quest_state": "任务类",
    "has_item": "物品类", "not_has_item": "物品类", "item_count": "物品类",
    "job": "职业类", "job_level": "职业类",
    "prof_level": "熟练类",
    "level": "状态类", "reputation": "状态类", "main_progress": "状态类", "codex": "状态类",
    "gain_count": "累计类", "kill_count": "累计类",
    "dungeon_clear": "副本类",
    "time": "时间类", "is_day": "时间类", "is_night": "时间类",
    "season": "时间类", "period": "时间类", "weather": "时间类",
    "affection": "关系类",
    "any": "组合", "all": "组合", "not": "组合",
}
COND_VAR_ALIASES: Dict[str, Optional[str]] = {
    "[当前等级]": None,
    "[图鉴完成度]": None,
    "[主线进度]": None,
    "[职业]": None,
    "[签到:连续天数]": None,
    "[签到:本月天数]": None,
    "[签到:今日已签]": None,
}
COND_VAR_ALIAS_PREFIXES: Tuple[str, ...] = (
    "[背包:", "[累计获得:", "[累计击杀:", "[副本通关:", "[熟练度:", "[声望:", "[季节:", "[时段:", "[天气:",
)
COND_EVENT_PRESETS: Tuple[str, ...] = (
    "[事件:副本通关]", "[事件:任务完成]", "[事件:签到]",
    "[事件:怪物击杀]", "[事件:等级提升]", "[事件:NPC对话]",
)
_COND_HARD_RULES: Tuple[str, ...] = (
    "var_not_registered", "op_invalid", "condition_not_object", "condition_empty",
)

# =====================================================================================
# 子表 Def 类型（风格对齐 shop_models/npc_models：BaseDef + 防御性读取访问器）
# =====================================================================================


@dataclass(frozen=True)
class BoardDef:
    """board 任务板子对象（2b4 §1.3：5 key：slot/refresh/limit/accept_limit/daily_limit）。

    默认板兜底（D-07 / P2-2）：漏配 board = {slot:"daily", refresh:"daily", limit:0,
    accept_limit:5, daily_limit:10}。访问器返回原始值（None=缺省），生效值经
    effective_* 派生（板级为全局默认，quest 级可不配并继承）。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "BoardDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def slot(self) -> Optional[str]:
        """板槽位：daily=每日刷新板、weekly=周板、event=活动板（2b4 §1.3#1）。"""
        v = self.raw.get("slot")
        return v if isinstance(v, str) else None

    @property
    def refresh(self) -> Optional[str]:
        """刷新模式：daily/weekly/once（2b4 §1.3#2；每日懒计算，05:00 可配）。"""
        v = self.raw.get("refresh")
        return v if isinstance(v, str) else None

    @property
    def limit(self) -> Optional[int]:
        """板上限：本周期该任务最多上架/完成次数（2b4 §1.3#3；0=不限，默认 0）。"""
        return self._int("limit")

    @property
    def accept_limit(self) -> Optional[int]:
        """同时接取上限（2b4 §1.3#4；板级全局默认 5，0=不限）。"""
        return self._int("accept_limit")

    @property
    def daily_limit(self) -> Optional[int]:
        """每日完成上限（2b4 §1.3#5；板级防刷总闸默认 10，0=不限）。"""
        return self._int("daily_limit")

    def _int(self, key: str) -> Optional[int]:
        v = self.raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    # ---- 生效侧（P2-2：daily 简写 + board.slot 显式 + 默认）----
    def effective_slot(self, daily_shorthand: bool = False) -> str:
        """生效板槽位：board.slot 显式 > daily:true 简写 > 默认 "daily"（P2-2 收敛）。"""
        if self.slot is not None:
            return self.slot
        if daily_shorthand:
            return "daily"
        return BOARD_SLOT_DEFAULT

    def effective_accept_limit(self) -> int:
        """生效接取上限：显式值，否则默认 5（任务定稿 L183 / 2b4 §1.3#4）。"""
        v = self.accept_limit
        return v if v is not None else QUEST_ACCEPT_LIMIT_DEFAULT

    def effective_daily_limit(self) -> int:
        """生效每日完成上限：显式值，否则默认 10（任务定稿 L184 / 2b4 §1.3#5）。"""
        v = self.daily_limit
        return v if v is not None else QUEST_DAILY_LIMIT_DEFAULT


@dataclass(frozen=True)
class TimedDef:
    """timed 限时修饰符（2b4 §1.2#10 / D-06：{deadline, penalty} 2 key）。

    deadline 现实时间懒计算（任务定稿 L102/L349②），接取时明确倒计时；penalty 默认无
    （可配扣物/仅提示）。结构语义判定归 core/quest.py 运行时。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "TimedDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def deadline(self) -> Optional[str]:
        """截止时刻（现实时间懒计算；内容包侧为可读时刻描述）。"""
        v = self.raw.get("deadline")
        return v if isinstance(v, str) else None

    @property
    def penalty(self) -> object:
        """超时惩罚（默认无；可配扣物/仅提示，2b4 D-06）。"""
        return self.raw.get("penalty")


@dataclass(frozen=True)
class NpcGrantDef:
    """npc 差异化发任务子对象（2b4 §1.4：3 key：id/conditions/priority）。

    与任务板区别：板=每日刷新通用任务；NPC=按条件差异化的支线（事件牌组，任务定稿 L153）。
    /与 NPC 对话 → 按满足条件匹配发布（L178）。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "NpcGrantDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def id(self) -> Optional[str]:
        """发起 NPC 引用（npc.json 的 NPC ID，任务定稿 L143-145）。"""
        v = self.raw.get("id")
        return v if isinstance(v, str) else None

    @property
    def conditions(self) -> Tuple[Mapping[str, object], ...]:
        """发任务条件（统一条件引擎 {var,op,value,param}，任务定稿 L149-151）。"""
        v = self.raw.get("conditions")
        return tuple(c for c in v if isinstance(c, Mapping)) if isinstance(v, list) else ()

    @property
    def priority(self) -> Optional[int]:
        """多候选匹配顺序：≥0 小者先，匹配第一个满足条件的任务（2b4 §1.4#3）。"""
        v = self.raw.get("priority")
        return v if isinstance(v, int) and not isinstance(v, bool) else None


# =====================================================================================
# QuestDef：quest.json 条目（2b4 §1.2：17 顶层字段 + 子表；id/name/raw/kind 由 BaseDef 承载）
# =====================================================================================


@dataclass(frozen=True)
class QuestDef(BaseDef):
    """quest.json 条目（2b4 §1.2：17 顶层字段 + board/timed/npc 子表）。

    17 顶层字段：id/name（BaseDef）/ desc / type / main / conditions / consume / reward /
    board / timed / unlock_chain / zone / filter / bonus / npc / daily / repeatable。

    关键口径：
      - main 沿用定稿 L138 命名（P3-1：定稿原文，非细化收敛）；main:true 常驻、不刷新不移除、
        /任务 置顶（L135/L138/L187）。
      - conditions 三原语（值型/累计型/事件型）判定 100% 由统一条件引擎驱动（L19），
        数组全与（D-02）；求值权威 = condition_engine（A2），本类只承载结构与访问器。
      - daily = board.slot 简写（P2-2 收敛，见模块头【工程补白】2）：daily:true ≡
        board:{slot:"daily", refresh:"daily"}；daily:false = 无简写（不表达「非每日板」）。
      - reward 统一条目（物品/货币键值/组合数组，任务定稿 L108-126）；rewards 等价别名（D-01）。

    访问器均为防御性读取（类型不符 → None/空），缺省兜底语义由校验器/引擎侧负责；
    布尔标记（main/consume/daily）缺省 false（对齐 shop_models.visible 口径）。
    """

    # ---- 数值/字符串/映射/列表辅助（与 NPCDef/ShopDef 同风格）----
    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _bool(self, key: str) -> bool:
        v = self.raw.get(key)
        return v if isinstance(v, bool) else False

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    def _entries(self, key: str) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get(key)
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    # ---- 17 顶层字段访问器（F03-F17；F01/F02 由 BaseDef）----
    @property
    def desc(self) -> Optional[str]:
        """描述（任务定稿 L96；默认空）。"""
        return self._str("desc")

    @property
    def type(self) -> Optional[str]:
        """展示标签/编辑器模板（collect/deliver/slay/explore/intel…，L97；**非判定依据**，
        判定全由 conditions 驱动，引擎对 type 零分支——L18/L21）。原始值；默认 collect 由
        校验侧兜底（effective_type）。"""
        return self._str("type")

    @property
    def effective_type(self) -> str:
        """生效 type：显式值，否则默认 "collect"（任务定稿 L97 / D-07）。"""
        t = self.type
        return t if t is not None else QUEST_TYPE_DEFAULT

    @property
    def main(self) -> bool:
        """主线标记（任务定稿 L138 命名 main: true；常驻不刷新不移除，/任务 置顶，L135/L187）。"""
        return self._bool(QUEST_MAIN_FIELD)

    @property
    def is_main(self) -> bool:
        """主线别名（供引擎可读语义）。"""
        return self.main

    @property
    def conditions(self) -> Tuple[Mapping[str, object], ...]:
        """判定条件数组（三原语 {var,op,value,param}；数组全与 D-02；空数组=接取即完成）。"""
        return self._entries("conditions")

    @property
    def consume(self) -> bool:
        """交付语义布尔：true=交付时扣物出包（deliver）/false=只计数不扣物（collect，L99/L81）。"""
        return self._bool("consume")

    @property
    def reward(self) -> object:
        """统一 reward 条目（str 内联串 | list 结构化 | dict 单条；L100/L108-126）。"""
        return self.raw.get("reward")

    @property
    def rewards(self) -> object:
        """reward 等价别名（D-01：复数 alias，同给异值 → 黄提示「奖励字段重复」）。"""
        return self.raw.get("rewards")

    @property
    def board(self) -> BoardDef:
        """任务板配置（2b4 §1.3：5 key；缺省每日默认板）。"""
        return BoardDef.from_entry(self.raw.get("board"))

    @property
    def timed(self) -> TimedDef:
        """限时修饰符（{deadline,penalty}；缺省 null）。"""
        return TimedDef.from_entry(self.raw.get("timed"))

    @property
    def unlock_chain(self) -> Optional[str]:
        """前置任务 ID（链式任务，L103/L85；引用悬空 → 黄提示死链）。"""
        return self._str("unlock_chain")

    @property
    def zone(self) -> Optional[str]:
        """地图/副本关联（ref dungeon.json/maps.json，L104；副本子任务 zone 限定不占板槽位）。"""
        return self._str("zone")

    @property
    def filter(self) -> object:
        """交付过滤（品质/特性/数量要求，L105/L299；炼金三档评价过滤子句）。"""
        return self.raw.get("filter")

    @property
    def bonus(self) -> Mapping[str, object]:
        """条件倍率（{condition:{var,op,value,param},mult:N}，L106/L300；如无伤交付×1.5）。"""
        return self._mapping("bonus")

    @property
    def npc(self) -> NpcGrantDef:
        """NPC 差异化发任务子对象（2b4 §1.4：3 key；缺省 null）。"""
        return NpcGrantDef.from_entry(self.raw.get("npc"))

    @property
    def daily(self) -> bool:
        """每日板标记（**board.slot 简写**，P2-2 收敛）：true ≡ board:{slot:"daily",
        refresh:"daily"}；false/缺省 = 无简写（不表达「非每日板」，与默认板=每日板不冲突）。
        非每日板请显式配 board.slot:"weekly"/"event"。"""
        return self._bool("daily")

    @property
    def repeatable(self) -> object:
        """重复/衰减开关（L185/L187）：false=完成即移出不可再接（默认）；true=可重复；
        obj={decay:N,cap:M}=重复衰减（第 2 次起奖励×decay，至 cap 下限，F-4）。"""
        return self.raw.get("repeatable")

    # ---- 派生/生效侧 ----
    @property
    def is_daily_board(self) -> bool:
        """是否每日板（P2-2「daily 缺省判据」承载）：生效板槽位 == "daily"。"""
        return self.effective_board_slot() == "daily"

    def effective_board_slot(self) -> str:
        """生效板槽位：board.slot 显式 > daily:true 简写 > 默认 "daily"（P2-2 收敛）。"""
        return self.board.effective_slot(self.daily)

    def board_accept_limit(self) -> int:
        """生效同时接取上限（默认 5，0=不限；任务定稿 L183）。"""
        return self.board.effective_accept_limit()

    def board_daily_limit(self) -> int:
        """生效每日完成上限（默认 10，0=不限；任务定稿 L184）。"""
        return self.board.effective_daily_limit()

    def is_repeatable(self) -> bool:
        """是否可重复：repeatable=true 或 {decay,cap} 对象（false/None=完成即移出）。"""
        r = self.repeatable
        if isinstance(r, bool):
            return r
        return isinstance(r, Mapping)

    def repeatable_decay(self) -> Optional[float]:
        """repeatable 对象 {decay,cap} 的 decay（数值；非对象 → None）。"""
        r = self.repeatable
        if not isinstance(r, Mapping):
            return None
        v = r.get("decay")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def repeatable_cap(self) -> Optional[float]:
        """repeatable 对象 {decay,cap} 的 cap（数值；非对象 → None）。"""
        r = self.repeatable
        if not isinstance(r, Mapping):
            return None
        v = r.get("cap")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def reward_entries(self) -> Tuple[Mapping[str, object], ...]:
        """统一 reward 条目序列（本地镜像，不含内联串展开）：reward 优先，缺省取 rewards 别名；
        str=内联串原样单条（展开归 core/reward 导入器）；dict=单条；list=逐条过滤对象条目。"""
        raw = self.raw.get("reward")
        if raw is None:
            raw = self.raw.get("rewards")
        if isinstance(raw, Mapping):
            return (raw,)
        if isinstance(raw, list):
            return tuple(e for e in raw if isinstance(e, Mapping))
        if isinstance(raw, str):
            return ({"inline": raw},) if raw else ()
        return ()

    def has_reward_alias_conflict(self) -> bool:
        """reward 与 rewards 同给且异值（D-01：黄提示「奖励字段重复」，同给同值不提示）。"""
        return ("reward" in self.raw and "rewards" in self.raw
                and self.raw.get("reward") != self.raw.get("rewards"))


def parse_quests(modules: Mapping[str, object]) -> Tuple[QuestDef, ...]:
    """从 modules 提取 quest 模块 → QuestDef 元组（非 list / 非对象条目跳过；供运行期与测试复用）。"""
    quests = modules.get(QUEST_MODULE) if isinstance(modules, Mapping) else None
    if not isinstance(quests, list):
        return ()
    return tuple(cast(QuestDef, QuestDef.from_entry(e)) for e in quests if isinstance(e, Mapping))


# =====================================================================================
# validate_quests：quest 模块专项校验（2b4 §1.5 + 任务定稿 §八 + P1-1/P1-2/P2-1/P2-2 裁决）
# =====================================================================================
# 规则清单（红拦=errors / 黄提示=warnings）：
#   硬拦 R-1：id 必填非空 string 且池内唯一；name 必填；type/main/consume/daily 类型错；
#             board.slot ∉ daily|weekly|event；board.refresh ∉ daily|weekly|once
#   硬拦 R-2：limit/accept_limit/daily_limit 负数或非整数；npc.priority 负数；bonus.mult 非法
#   硬拦 R-4：reward 物品引用不存在（items 模块存在时）；reward 货币键未注册（settings 存在时）；
#             zone 引用不存在（maps/dungeon 模块存在时）；npc.id 引用不存在（npc 模块存在时）
#   硬拦 R-5：条目非对象；conditions 非数组；条件结构（var 未注册/op 非法/空条件）；reward 结构错
#             （条目非对象/同条目多键/未知键/count 非法）；board/timed/filter/bonus/npc 非对象
#   黄提示 Y：accept_limit>5（板上限冲突）；daily_limit>10（防刷上限超默认）；unlock_chain 死链；
#             daily:true 与 board.slot 显式≠daily 互斥；reward/rewards 同给异值；
#             repeatable 衰减异常；条件旧格式/事件未登记（CND 软提示）


def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    """收集器鸭子类型适配：优先 report.<method>，其次 validator._Checker 的 _<method>。"""
    _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
    fn = getattr(report, method, None)
    if not callable(fn):
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", QUEST_MODULE, field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", QUEST_MODULE, field, kind, **detail)


# -------------------------------------------------------------------------------------
# 条件引擎本地镜像（【工程补白】1：content→data 单向铁律，不 import engine）
# -------------------------------------------------------------------------------------
def _cond_var_ok(var: object) -> bool:
    """var 键注册判定（镜像 condition_engine.normalize_var 的接受集合，不含归一结果）。"""
    if not isinstance(var, str) or not var:
        return False
    v = var.strip()
    if not v:
        return False
    if v in COND_VARS or v in COND_VAR_ALIASES:
        return True
    for prefix in COND_VAR_ALIAS_PREFIXES:
        if v.startswith(prefix) and v.endswith("]") and len(v) > len(prefix):
            return True
    if v.startswith("[事件:") and v.endswith("]"):
        return True
    if v.startswith("[签到:") and v.endswith("]"):
        return True
    if v.startswith("x_"):
        return True
    return False


def _cond_op_ok(op: object) -> bool:
    if not isinstance(op, str) or not op:
        return False
    o = op.strip().lower()
    return o in COND_OPERATORS or o in COND_OP_SYMBOLS


def _cond_event_name(var: str) -> str:
    """事件名内嵌目标剥离：[事件:副本通关:熔岩洞窟] → [事件:副本通关]（NPC 4.3.2）。"""
    inner = var[len("[事件:"):]
    if inner.endswith("]"):
        inner = inner[:-1]
    if ":" in inner:
        name, _ = inner.rsplit(":", 1)
        if name:
            return "[事件:" + name + "]"
    return var


def _check_condition(report: object, cond: object, base_field: str, node_id: str) -> None:
    """条件表达式结构校验（镜像 engine/condition_engine.validate_condition 规则）。

    红拦（error）：var 未注册 / op 非法 / 条件非对象 / 空条件（_COND_HARD_RULES）。
    黄提示（不拦）：旧格式 {type,var,op,value} / 旧 event 原语 / 事件 var 未在预置注册表。
    递归 any/all/not 嵌套（NPC 4.4 / 2b4 D-02）。求值失败默认 False（D-03 安全失败，
    2026-08-27 裁决 P1-1 改标【工程补白】）由引擎侧保证——本层只做结构校验。
    """
    if cond is None:
        return
    if isinstance(cond, (list, tuple)):
        for c in cond:
            _check_condition(report, c, base_field, node_id)
        return
    if not isinstance(cond, Mapping):
        _err(report, base_field, "CND", rule="condition_not_object",
             node_id=node_id, got=type(cond).__name__,
             msg="条件表达式要填对象 {var,op,value,param} 或 any/all/not 组合")
        return
    if "var" in cond:
        var = cond.get("var")
        if not _cond_var_ok(var):
            _err(report, f"{base_field}.var", "CND", rule="var_not_registered",
                 node_id=node_id, var=var, allowed=sorted(COND_VARS),
                 msg="条件变量键 %r 未注册" % (var,))
        elif cond.get("op") is not None and not _cond_op_ok(cond.get("op")):
            _err(report, f"{base_field}.op", "CND", rule="op_invalid",
                 node_id=node_id, op=cond.get("op"),
                 allowed=list(COND_OPERATORS) + list(COND_OP_SYMBOLS),
                 msg="条件运算符 %r 不认识（9 种：%s，符号双写 >= > <= < = !=）"
                     % (cond.get("op"), "/".join(COND_OPERATORS)))
        elif cond.get("type"):
            _warn(report, f"{base_field}.type", "CND", rule="legacy_format", node_id=node_id,
                  msg="旧格式 {type,var,op,value}，建议迁移为 {var,op,value,param}（type 忽略）")
        if isinstance(var, str) and var.startswith("[事件:") and var.endswith("]"):
            ev = _cond_event_name(var)
            if ev not in COND_EVENT_PRESETS:
                _warn(report, f"{base_field}.var", "CND", rule="event_not_registered",
                      node_id=node_id, var=var, presets=list(COND_EVENT_PRESETS),
                      msg="事件 %r 未在事件注册表登记，确认拼写或先登记（NPC 4.3.2）" % (var,))
        return
    if "all" in cond:
        for c in cond["all"] if isinstance(cond["all"], (list, tuple)) else [cond["all"]]:
            _check_condition(report, c, base_field, node_id)
        return
    if "any" in cond:
        for c in cond["any"] if isinstance(cond["any"], (list, tuple)) else [cond["any"]]:
            _check_condition(report, c, base_field, node_id)
        return
    if "not" in cond:
        _check_condition(report, cond["not"], base_field, node_id)
        return
    if cond.get("type") == "event" and isinstance(cond.get("event"), str):
        _warn(report, base_field, "CND", rule="legacy_format", node_id=node_id,
              msg="旧 event 原语 {type:event,...}，建议迁移为 {var:'[事件:x]',op:'ge',value:count,param:target}")
        return
    _err(report, base_field, "CND", rule="condition_empty", node_id=node_id,
         msg="条件表达式缺 var 或 any/all/not 键")


# -------------------------------------------------------------------------------------
# 引用集合收集（模块缺失/非 list → None：调用方跳过引用检查，细化_3e §2.3 默认放行）
# -------------------------------------------------------------------------------------
def _id_set(modules: Mapping[str, object], key: str) -> Optional[Set[str]]:
    data = modules.get(key)
    if not isinstance(data, list):
        return None
    ids: Set[str] = set()
    for e in data:
        if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
            ids.add(e["id"])
    return ids if ids else None


def _settings_currency_ids(modules: Mapping[str, object]) -> Tuple[str, ...]:
    """settings 货币键空间（settings.currencies[].id）；settings 缺省/非法 → 默认模板（3h §5.1）。

    镜像 validator._settings_currency_ids（content→content 同层引用，currency 注册表唯一口径）。
    """
    settings = modules.get("settings")
    if not isinstance(settings, Mapping):
        return DEFAULT_CURRENCY_IDS
    raw = settings.get("currencies")
    ids: List[str] = []
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
                ids.append(e["id"])
    return tuple(ids) or DEFAULT_CURRENCY_IDS


def _zone_union(modules: Mapping[str, object]) -> Optional[Set[str]]:
    """zone 引用靶（【工程补白】5）：maps ∪ dungeon 两模块 id 并集（任务定稿 L104）。"""
    union: Set[str] = set()
    any_mod = False
    for key in ("maps", "dungeon"):
        ids = _id_set(modules, key)
        if ids is not None:
            any_mod = True
            union |= ids
    return union if any_mod else None


# -------------------------------------------------------------------------------------
# 引用靶构建
# -------------------------------------------------------------------------------------
class _Refs:
    """quest 模块跨模块引用校验靶（None = 目标模块未声明/无合法 id → 跳过对应引用检查）。"""

    __slots__ = ("quest_ids", "item_ids", "zone_ids", "npc_ids", "currency_ids")

    def __init__(self) -> None:
        self.quest_ids: Optional[Set[str]] = None
        self.item_ids: Optional[Set[str]] = None
        self.zone_ids: Optional[Set[str]] = None
        self.npc_ids: Optional[Set[str]] = None
        self.currency_ids: Tuple[str, ...] = ()


# -------------------------------------------------------------------------------------
# reward 结构校验（【工程补白】3：本地镜像 core/reward 条目 schema；D-05 内联串=糖）
# -------------------------------------------------------------------------------------
def _check_reward(report: object, reward: object, base: str, node_id: str,
                  refs: _Refs) -> None:
    """reward 统一条目校验（物品/货币键值/组合数组；内联串非空放行——展开归导入器）。

    硬拦：条目非对象 / 同条目同时含物品与标量键 / 未知键 / count 非正整数 / 标量值非法 /
          物品引用不存在（items 模块存在时）/ 货币键未注册（settings 存在时）。
    """
    if reward is None:
        return  # 缺省空奖励（D-07：reward=空，绝不报错）
    if isinstance(reward, str):
        return  # 内联键值串（含空串）结构展开归 core/reward 导入器（D-05 序列化糖），本层放行
    entries = reward if isinstance(reward, list) else [reward]
    for i, entry in enumerate(entries):
        ebase = f"{base}.{i}" if isinstance(reward, list) else base
        if not isinstance(entry, Mapping):
            _err(report, ebase, "R-5", rule="quest_reward_entry_not_object",
                 node_id=node_id, got=type(entry).__name__,
                 msg="reward 条目需对象 {item,count} / {coins|gem|exp|rep:N}")
            continue
        _check_reward_entry(report, entry, ebase, node_id, refs)


def _check_reward_entry(report: object, entry: Mapping[str, object], base: str,
                        node_id: str, refs: _Refs) -> None:
    """单条 reward 条目校验。"""
    keys = set(entry.keys())
    item_keys = [k for k in REWARD_ITEM_KEYS if k in entry]
    scalar_keys = [k for k in REWARD_SCALAR_KEYS if k in entry]
    # 同条目同时含物品与标量键 → 结构错误
    if item_keys and scalar_keys:
        _err(report, base, "R-5", rule="quest_reward_entry_mixed",
             node_id=node_id, item_keys=item_keys, scalar_keys=scalar_keys,
             msg="reward 条目不能同时是物品与货币键值（%s + %s）"
                 % ("/".join(item_keys), "/".join(scalar_keys)))
        return
    if not item_keys and not scalar_keys:
        _err(report, base, "R-5", rule="quest_reward_entry_structure",
             node_id=node_id, keys=sorted(keys),
             msg="reward 条目需含物品键（item/id）或标量键（coins/gem/exp/rep）")
        return
    if item_keys:
        # 物品条目 {item|id, count, bound}（id ≡ item 键，L126）
        item_key = item_keys[0]
        item_id = entry[item_key]
        unknown = keys - {item_key, REWARD_COUNT_KEY, REWARD_BOUND_KEY}
        if unknown:
            _err(report, base, "R-5", rule="quest_reward_entry_unknown_key",
                 node_id=node_id, keys=sorted(unknown),
                 msg="物品条目多余键 %s（合法：%s/count/bound）" % (sorted(unknown), item_key))
        if not isinstance(item_id, str) or not item_id:
            _err(report, f"{base}.{item_key}", "R-5", rule="quest_reward_item_id_invalid",
                 node_id=node_id, item_id=item_id, msg="物品条目 %s 需非空字符串" % (item_key,))
        elif refs.item_ids is not None and item_id not in refs.item_ids:
            _err(report, f"{base}.{item_key}", "R-4", rule="quest_reward_item_ref_missing",
                 node_id=node_id, item=item_id, registered=sorted(refs.item_ids),
                 msg="奖励物品 %r 在 items.json 中不存在，先去物品页添加（定稿 L276/L278）"
                     % (item_id,))
        if REWARD_COUNT_KEY in entry:
            count = entry[REWARD_COUNT_KEY]
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                _err(report, f"{base}.count", "R-2", rule="quest_reward_count_invalid",
                     node_id=node_id, count=count,
                     msg="物品 count 需 ≥1 整数（缺省 1）")
        if REWARD_BOUND_KEY in entry and not isinstance(entry[REWARD_BOUND_KEY], bool):
            _err(report, f"{base}.bound", "R-1", rule="quest_reward_bound_invalid",
                 node_id=node_id, value=entry[REWARD_BOUND_KEY],
                 msg="物品 bound 需 bool（缺省 true=绑定）")
        return
    # 标量条目 {coins|gem|exp|rep: N}
    key = scalar_keys[0]
    unknown = keys - {key}
    if unknown:
        _err(report, base, "R-5", rule="quest_reward_entry_unknown_key",
             node_id=node_id, keys=sorted(unknown),
             msg="标量条目多余键 %s（合法：%s 单键）" % (sorted(unknown), key))
    value = entry[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _err(report, f"{base}.{key}", "R-2", rule="quest_reward_value_invalid",
             node_id=node_id, key=key, value=value,
             msg="标量奖励 %s 需 ≥0 整数" % (key,))
        return
    # 货币键注册（coins/gem 走 settings 货币键空间，L123）；exp/rep 数值直入账不查注册
    if key in ("coins", "gem") and refs.currency_ids and key not in refs.currency_ids:
        _err(report, f"{base}.{key}", "R-4", rule="quest_reward_currency_unregistered",
             node_id=node_id, currency=key, registered=list(refs.currency_ids),
             msg="奖励货币键 %r 未注册（settings.currencies 键空间）" % (key,))


# -------------------------------------------------------------------------------------
# board 任务板子对象校验（2b4 §1.3 + 任务定稿 L181-187 + P2-2）
# -------------------------------------------------------------------------------------
def _check_board(report: object, board: object, base: str, node_id: str,
                 daily_flag: object) -> None:
    """board 结构校验：5 key（slot/refresh/limit/accept_limit/daily_limit）。

    红拦：board 非对象 / slot ∉ daily|weekly|event / refresh ∉ daily|weekly|once /
          limit/accept_limit/daily_limit 负数或非整数。
    黄提示：accept_limit>5（板上限冲突）/ daily_limit>10（防刷上限超默认）/ daily:true 与
          board.slot 显式≠daily 互斥（P2-2，2b4 §1.2 row16）。
    """
    if board is None:
        _check_daily_conflict(report, daily_flag, None, node_id)
        return  # 漏配 board = 每日默认板（D-07），绝不报错
    if not isinstance(board, Mapping):
        _err(report, base, "R-5", rule="quest_board_not_object",
             node_id=node_id, got=type(board).__name__,
             msg="board 要填对象 {slot, refresh, limit, accept_limit, daily_limit}")
        _check_daily_conflict(report, daily_flag, None, node_id)
        return
    slot = board.get("slot")
    if slot is not None and (not isinstance(slot, str) or slot not in BOARD_SLOTS):
        _err(report, f"{base}.slot", "R-1", rule="quest_board_slot_invalid",
             node_id=node_id, slot=slot, allowed=list(BOARD_SLOTS),
             msg="board.slot %r 不认识（多板三值：%s，缺省 daily）"
                 % (slot, "/".join(BOARD_SLOTS)))
    refresh = board.get("refresh")
    if refresh is not None and (not isinstance(refresh, str) or refresh not in BOARD_REFRESH_MODES):
        _err(report, f"{base}.refresh", "R-1", rule="quest_board_refresh_invalid",
             node_id=node_id, refresh=refresh, allowed=list(BOARD_REFRESH_MODES),
             msg="board.refresh %r 不认识（三模式：%s，缺省 daily=每日懒计算 05:00）"
                 % (refresh, "/".join(BOARD_REFRESH_MODES)))
    for key, rule in (("limit", "quest_board_limit_invalid"),
                      ("accept_limit", "quest_board_accept_limit_invalid"),
                      ("daily_limit", "quest_board_daily_limit_invalid")):
        if key in board:
            v = board[key]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                _err(report, f"{base}.{key}", "R-2", rule=rule, node_id=node_id, value=v,
                     msg="board.%s 需 ≥0 整数（0=不限）" % (key,))
    # 黄提示：板上限冲突（2b4 §1.5）——接取上限>5 / 每日完成上限>10（任务定稿 L183/L184）
    al = board.get("accept_limit")
    if isinstance(al, int) and not isinstance(al, bool) and al > BOARD_ACCEPT_OVER_WARN:
        _warn(report, f"{base}.accept_limit", "Y-4", rule="quest_accept_limit_over_default",
              node_id=node_id, accept_limit=al, default=QUEST_ACCEPT_LIMIT_DEFAULT,
              msg="同时接取上限 %s > 默认 %s（可配 0=不限，但超默认提示板上限冲突确认？定稿 L183）"
                  % (al, QUEST_ACCEPT_LIMIT_DEFAULT))
    dl = board.get("daily_limit")
    if isinstance(dl, int) and not isinstance(dl, bool) and dl > BOARD_LIMIT_OVER_WARN:
        _warn(report, f"{base}.daily_limit", "Y-4", rule="quest_daily_limit_over_default",
              node_id=node_id, daily_limit=dl, default=QUEST_DAILY_LIMIT_DEFAULT,
              msg="每日完成上限 %s > 默认 %s（防刷闸放太宽确认？定稿 L184）"
                  % (dl, QUEST_DAILY_LIMIT_DEFAULT))
    _check_daily_conflict(report, daily_flag, board, node_id)


def _check_daily_conflict(report: object, daily_flag: object, board: object, node_id: str) -> None:
    """P2-2 互斥黄提示：daily:true 与 board.slot 显式 ≠ daily 同给（2b4 §1.2 row16）。

    daily:false/缺省 = 无简写（不表达「非每日板」），与任何 board 均不冲突（P2-2 收敛）。
    """
    if daily_flag is not True:
        return
    slot = board.get("slot") if isinstance(board, Mapping) else None
    if slot is not None and slot != "daily":
        _warn(report, "quest.daily", "Y-4", rule="quest_daily_board_conflict",
              node_id=node_id, daily=True, board_slot=slot,
              msg="daily:true（每日板简写）与 board.slot=%r 互斥——非每日板请用 board.slot "
                  "显式配置并去掉 daily（P2-2 收敛，2b4 §1.2 row16）" % (slot,))


# -------------------------------------------------------------------------------------
# timed / npc 子对象校验
# -------------------------------------------------------------------------------------
def _check_timed(report: object, timed: object, base: str, node_id: str) -> None:
    """timed 结构校验（2b4 D-06：{deadline, penalty}；deadline 语义判定归 core/quest.py）。"""
    if timed is None:
        return
    if not isinstance(timed, Mapping):
        _err(report, base, "R-5", rule="quest_timed_not_object",
             node_id=node_id, got=type(timed).__name__,
             msg="timed 要填对象 {deadline, penalty}")
        return
    deadline = timed.get("deadline")
    if deadline is not None and (not isinstance(deadline, str) or not deadline):
        _err(report, f"{base}.deadline", "R-5", rule="quest_timed_deadline_invalid",
             node_id=node_id, deadline=deadline,
             msg="timed.deadline 需非空字符串（现实时间懒计算，接取时明确倒计时）")


def _check_npc_grant(report: object, npc: object, base: str, node_id: str,
                     refs: _Refs) -> None:
    """npc 差异化发任务子对象校验（2b4 §1.4：id/conditions/priority）。"""
    if npc is None:
        return
    if not isinstance(npc, Mapping):
        _err(report, base, "R-5", rule="quest_npc_not_object",
             node_id=node_id, got=type(npc).__name__,
             msg="npc 要填对象 {id, conditions, priority}")
        return
    nid = npc.get("id")
    if not isinstance(nid, str) or not nid:
        _err(report, f"{base}.id", "R-1", rule="quest_npc_id_invalid",
             node_id=node_id, npc_id=nid,
             msg="npc.id 必填（npc.json 的 NPC ID，任务定稿 L143-145）")
    elif refs.npc_ids is not None and nid not in refs.npc_ids:
        _err(report, f"{base}.id", "R-4", rule="quest_npc_ref_missing",
             node_id=node_id, ref=nid, registered=sorted(refs.npc_ids),
             msg="发起 NPC %r 在 npc.json 中不存在（任务定稿 L143-145）" % (nid,))
    conds = npc.get("conditions")
    if conds is not None and not isinstance(conds, list):
        _err(report, f"{base}.conditions", "R-5", rule="quest_npc_conditions_not_list",
             node_id=node_id, got=type(conds).__name__,
             msg="npc.conditions 需数组（统一条件引擎 {var,op,value,param}）")
    elif isinstance(conds, list):
        for ci, c in enumerate(conds):
            _check_condition(report, c, f"{base}.conditions.{ci}", node_id)
    priority = npc.get("priority")
    if priority is not None and (not isinstance(priority, int) or isinstance(priority, bool)
                                 or priority < 0):
        _err(report, f"{base}.priority", "R-2", rule="quest_npc_priority_invalid",
             node_id=node_id, priority=priority,
             msg="npc.priority 需 ≥0 整数（小者先，匹配第一个满足条件的任务发布）")


# -------------------------------------------------------------------------------------
# 单任务校验
# -------------------------------------------------------------------------------------
def _check_repeatable(report: object, repeatable: object, base: str, node_id: str) -> None:
    """repeatable 校验（2b4 §1.2#17：bool / {decay,cap}；F-4 重复衰减）。

    硬拦：非 bool 且非对象 / decay 非数值 / cap 负数或非数值。
    黄提示：衰减异常（decay 非 0<decay<1 或 cap<1——2b4 §1.5 黄提示族）。
    """
    if repeatable is None or isinstance(repeatable, bool):
        return
    if not isinstance(repeatable, Mapping):
        _err(report, base, "R-5", rule="quest_repeatable_invalid",
             node_id=node_id, got=type(repeatable).__name__,
             msg="repeatable 需 bool 或对象 {decay:N, cap:M}（重复衰减，任务定稿 L185）")
        return
    decay = repeatable.get("decay")
    if decay is not None and (isinstance(decay, bool)
                              or not isinstance(decay, (int, float))):
        _err(report, f"{base}.decay", "R-2", rule="quest_repeatable_decay_invalid",
             node_id=node_id, decay=decay, msg="repeatable.decay 需数值（奖励递减倍率）")
    elif isinstance(decay, (int, float)) and not 0 < decay < 1:
        _warn(report, f"{base}.decay", "Y-4", rule="quest_repeatable_anomaly",
              node_id=node_id, decay=decay,
              msg="repeatable.decay=%s 不在 (0,1) 区间——重复奖励不递减？确认（2b4 §1.5）" % (decay,))
    cap = repeatable.get("cap")
    if cap is not None and (isinstance(cap, bool)
                            or not isinstance(cap, (int, float)) or cap < 1):
        _err(report, f"{base}.cap", "R-2", rule="quest_repeatable_cap_invalid",
             node_id=node_id, cap=cap,
             msg="repeatable.cap 需 ≥1 数值（衰减下限）")
    elif isinstance(cap, (int, float)) and cap < 1:
        _warn(report, f"{base}.cap", "Y-4", rule="quest_repeatable_anomaly",
              node_id=node_id, cap=cap, msg="repeatable.cap=%s 低于 1，衰减无下限？确认" % (cap,))


def _check_quest(report: object, quest: Mapping[str, object], idx: int, node_id: str,
                 refs: _Refs, seen_ids: Set[str]) -> None:
    """单任务校验：17 顶层字段 + board/timed/npc 子表 + conditions 三原语。"""
    qid = quest.get("id")
    if not isinstance(qid, str) or not qid:
        _err(report, f"quest.{idx}.id", "R-5", rule="quest_id_required", node_id=node_id,
             msg="任务 id 必填（全局唯一，被 unlock_chain / 副本 subquests 引用）")
    elif qid in seen_ids:
        _err(report, f"quest.{idx}.id", "R-5", rule="quest_id_duplicate", node_id=node_id,
             id=qid, msg="任务 id %r 重复（全局唯一）" % (qid,))
    else:
        seen_ids.add(qid)

    name = quest.get("name")
    if not isinstance(name, str) or not name:
        _err(report, f"quest.{idx}.name", "R-5", rule="quest_name_required", node_id=node_id,
             name=name, msg="任务 name 必填（玩家可见任务名）")

    # type：纯展示标签（L18/L97），任意字符串放行（TC-04：自定义标签不报错）；非字符串 → 红拦
    if "type" in quest and quest["type"] is not None and not isinstance(quest["type"], str):
        _err(report, f"quest.{idx}.type", "R-1", rule="quest_type_invalid", node_id=node_id,
             value=quest["type"], msg="type 需字符串展示标签（collect/deliver/...，非判定依据）")

    # main 主线标记（任务定稿 L138 命名；bool）
    if "main" in quest and not isinstance(quest["main"], bool):
        _err(report, f"quest.{idx}.main", "R-1", rule="quest_main_invalid", node_id=node_id,
             value=quest["main"], msg="main 需 bool（main:true 常驻不刷新不移除，定稿 L138）")

    # conditions 判定条件数组（三原语 {var,op,value,param}；D-02 全与）
    conditions = quest.get("conditions")
    if conditions is None:
        pass  # 缺省 []（D-07：数组为空=接取即完成，幻觉审查 2b4 P1-3 已入 ADR 语义）
    elif not isinstance(conditions, list):
        _err(report, f"quest.{idx}.conditions", "R-5", rule="quest_conditions_not_list",
             node_id=node_id, got=type(conditions).__name__,
             msg="conditions 需数组（三原语 {var,op,value,param}，全与判定 D-02）")
    else:
        for ci, cond in enumerate(conditions):
            _check_condition(report, cond, f"quest.{idx}.conditions.{ci}", node_id)

    # consume 交付语义布尔
    if "consume" in quest and not isinstance(quest["consume"], bool):
        _err(report, f"quest.{idx}.consume", "R-1", rule="quest_consume_invalid", node_id=node_id,
             value=quest["consume"],
             msg="consume 需 bool（true=交付扣物 / false=计数不扣，定稿 L99/L81）")

    # reward 统一条目 + rewards 别名（D-01）
    if "reward" in quest:
        _check_reward(report, quest["reward"], f"quest.{idx}.reward", node_id, refs)
    elif "rewards" in quest:
        _check_reward(report, quest["rewards"], f"quest.{idx}.rewards", node_id, refs)
    if "reward" in quest and "rewards" in quest and quest["reward"] != quest["rewards"]:
        _warn(report, f"quest.{idx}.reward", "Y-4", rule="quest_reward_alias_conflict",
              node_id=node_id, reward=quest["reward"], rewards=quest["rewards"],
              msg="reward 与 rewards 同给且异值（D-01 等价别名）——保留其一，奖励字段重复确认？")

    # board 任务板（5 key；漏配=每日默认板）
    _check_board(report, quest.get("board"), f"quest.{idx}.board", node_id,
                 quest.get("daily"))

    # timed 限时修饰符
    _check_timed(report, quest.get("timed"), f"quest.{idx}.timed", node_id)

    # unlock_chain 链式任务（引用悬空 → 黄提示死链，2b4 §1.5 黄提示族）
    uc = quest.get("unlock_chain")
    if uc is not None:
        if not isinstance(uc, str) or not uc:
            _err(report, f"quest.{idx}.unlock_chain", "R-1", rule="quest_unlock_chain_invalid",
                 node_id=node_id, unlock_chain=uc,
                 msg="unlock_chain 需字符串（前置任务 ID，任务定稿 L103）")
        elif refs.quest_ids is not None and uc not in refs.quest_ids:
            _warn(report, f"quest.{idx}.unlock_chain", "Y-4", rule="quest_unlock_chain_dead",
                  node_id=node_id, ref=uc, registered=sorted(refs.quest_ids),
                  msg="链式任务前置 %r 不存在（死链确认？任务定稿 L85/L277）" % (uc,))

    # zone 地图/副本关联（引用悬空 → 硬拦 R-4，任务定稿 L276）
    zone = quest.get("zone")
    if zone is not None:
        if not isinstance(zone, str) or not zone:
            _err(report, f"quest.{idx}.zone", "R-1", rule="quest_zone_invalid", node_id=node_id,
                 zone=zone, msg="zone 需字符串（dungeon.json/maps.json 的 ID，定稿 L104）")
        elif refs.zone_ids is not None and zone not in refs.zone_ids:
            _err(report, f"quest.{idx}.zone", "R-4", rule="quest_zone_ref_missing",
                 node_id=node_id, zone=zone, registered=sorted(refs.zone_ids),
                 msg="zone %r 引用不存在（dungeon.json/maps.json，副本子任务限定，定稿 L104/L276）"
                     % (zone,))

    # filter 交付过滤（品质/特性/数量要求）
    if "filter" in quest and quest["filter"] is not None and not isinstance(quest["filter"], Mapping):
        _err(report, f"quest.{idx}.filter", "R-5", rule="quest_filter_not_object",
             node_id=node_id, got=type(quest["filter"]).__name__,
             msg="filter 要填对象（品质/特性/数量过滤，定稿 L105/L299）")

    # bonus 条件倍率 {condition, mult}
    bonus = quest.get("bonus")
    if bonus is not None:
        if not isinstance(bonus, Mapping):
            _err(report, f"quest.{idx}.bonus", "R-5", rule="quest_bonus_not_object",
                 node_id=node_id, got=type(bonus).__name__,
                 msg="bonus 要填对象 {condition:{var,op,value,param}, mult:N}（定稿 L106/L300）")
        else:
            if "condition" in bonus:
                _check_condition(report, bonus["condition"], f"quest.{idx}.bonus.condition", node_id)
            mult = bonus.get("mult")
            if mult is not None and (isinstance(mult, bool)
                                     or not isinstance(mult, (int, float)) or mult < 0):
                _err(report, f"quest.{idx}.bonus.mult", "R-2", rule="quest_bonus_mult_invalid",
                     node_id=node_id, mult=mult,
                     msg="bonus.mult 需 ≥0 数值（奖励倍率，如 1.5=无伤交付×1.5）")

    # npc 差异化发任务子对象
    _check_npc_grant(report, quest.get("npc"), f"quest.{idx}.npc", node_id, refs)

    # daily 每日板标记（board.slot 简写；P2-2：互斥黄提示在 _check_board 内处理）
    if "daily" in quest and not isinstance(quest["daily"], bool):
        _err(report, f"quest.{idx}.daily", "R-1", rule="quest_daily_invalid", node_id=node_id,
             value=quest["daily"],
             msg="daily 需 bool（board.slot 简写，P2-2：daily:true ≡ board:{slot:daily,refresh:daily}）")

    # repeatable 重复/衰减开关
    _check_repeatable(report, quest.get("repeatable"), f"quest.{idx}.repeatable", node_id)


def validate_quests(modules: Mapping[str, object], report: object) -> None:
    """quest 模块专项校验（M4 批次4·路E1：QuestDef 17 顶层字段 + 子表 + 三原语 + 防刷）。纯函数，无副作用。

    入口：主 agent 收口时在 check_pack 的 _Checker.run() 尾部调用
        validate_quests(modules, checker)  （checker._err/_warn 签名与 _emit 一致）
    或自建收集器（暴露 error(module, field, kind, **detail) / warning(...)）。
    返回 None；红拦/黄提示全部经 report 追加（一次给全量）。

    modules: 模块名（无 .json 后缀）→ parsed JSON（含 "quest" 与可选 "items"/"settings"/
             "npc"/"maps"/"dungeon"）。quest 未声明 → 默认放行（细化_3e §2.3）；
             引用目标模块未声明 → 跳过对应引用检查。

    覆盖验收（2b4 §1.5 + 任务定稿 §八 + 2026-08-27 裁决）：
      - TC-01 最小配置默认值兜底（D-07）：type/consume/main/daily/repeatable 缺省、
        board 缺省=每日默认板、daily_limit=10、accept_limit=5，绝不报错
      - TC-04 自定义 type 标签不报错（纯展示标签，判定只由 conditions 驱动）
      - TC-05 zone 引用不存在 → 红拦（R-4）
      - TC-06~TC-12 三原语条件结构（值型/累计型/事件型 var+op 结构校验，D-02 全与）
      - TC-13~TC-17 reward 统一条目（物品/货币键值/组合数组结构 + 引用）
      - TC-18~TC-19 每日防刷：daily_limit 默认 10、>10 黄提示（板上限冲突）
      - TC-20 接取上限：accept_limit 默认 5、>5 黄提示
      - 引用悬空：reward 物品 / zone / npc.id 硬拦；unlock_chain 死链黄提示
      - 双板：board.slot 多板枚举（daily/weekly/event）；daily 简写 P2-2 收敛
      - 旧格式条件 / 事件未登记 → 黄提示不拦（TC-29/TC-31）
    """
    if not isinstance(modules, Mapping):
        return
    quests = modules.get(QUEST_MODULE)
    if quests is None:
        return  # 未声明 quest 模块：默认放行
    if not isinstance(quests, list):
        _err(report, QUEST_MODULE, "R-5", rule="module_structure", expect="list")
        return

    refs = _Refs()
    refs.quest_ids = _id_set(modules, QUEST_MODULE)
    refs.item_ids = _id_set(modules, "items")
    refs.zone_ids = _zone_union(modules)
    refs.npc_ids = _id_set(modules, "npc")
    refs.currency_ids = _settings_currency_ids(modules)

    seen_ids: Set[str] = set()
    for idx, entry in enumerate(quests):
        if not isinstance(entry, Mapping):
            _err(report, f"quest.{idx}", "R-5", rule="quest_not_object",
                 node_id=f"#{idx}", got=type(entry).__name__,
                 msg="任务条目需对象")
            continue
        node_id = entry.get("id")
        if not isinstance(node_id, str) or not node_id:
            node_id = f"<quest.{idx}>"
        _check_quest(report, entry, idx, node_id, refs, seen_ids)


__all__ = [
    # 常量
    "QUEST_MODULE",
    "QUEST_DAILY_LIMIT_DEFAULT",
    "QUEST_ACCEPT_LIMIT_DEFAULT",
    "QUEST_MAIN_FIELD",
    "QUEST_TYPE_DEFAULT",
    "QUEST_CONDITIONS_ARRAY_ALL",
    "BOARD_SLOTS",
    "BOARD_SLOT_DEFAULT",
    "BOARD_REFRESH_MODES",
    "BOARD_REFRESH_DEFAULT",
    "BOARD_LIMIT_DEFAULT",
    "BOARD_LIMIT_OVER_WARN",
    "BOARD_ACCEPT_OVER_WARN",
    "REWARD_SCALAR_KEYS",
    "REWARD_ITEM_KEYS",
    "REWARD_COUNT_KEY",
    "REWARD_BOUND_KEY",
    "TIMED_KEYS",
    "REPEATABLE_KEYS",
    # 条件镜像常量
    "COND_OPERATORS",
    "COND_OP_SYMBOLS",
    "COND_VARS",
    "COND_VAR_ALIASES",
    "COND_VAR_ALIAS_PREFIXES",
    "COND_EVENT_PRESETS",
    # Def 类型
    "BoardDef",
    "TimedDef",
    "NpcGrantDef",
    "QuestDef",
    # 函数
    "parse_quests",
    "validate_quests",
]
