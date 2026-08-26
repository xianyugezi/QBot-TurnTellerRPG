"""签到数据模型 —— M4 批次5·路F1：CheckinDef 全字段（多表 loop/monthly/activity + 奖励三通道 + 补签）+ [签到:*] 三键 + validate_checkins。

依据：
  - m4_shared_contract §3.4（签到 E1-E4：多表（loop/monthly/activity）并存一次结算；连签独立计数（streak）
    + 补签（默认关/两通道/月上限）；**补签只计不补发（用户裁决⑦）**；里程碑不重复；
    **[签到:<表名>.<字段>] 三键（用户裁决⑧）**：连续天数=指定表 streak / 本月天数=指定表当月 signed_days /
    今日已签=指定表今日已签；缺省表名=主表 loop）
  - 细化_2b5_签到引擎契约.md（checkin.json 字段级 schema：顶层 7 字段 §1.2 / period 4 key §1.4 /
    rewards 三通道 §1.5 / makeup 3 key §1.6 / bonus §1.7 / 校验器边界 §1.8 / 连签与独立计数 §三 /
    补签 §四 / 验收 TC-01~TC-33 + 2026-08-27 M4 设计审查裁决 P2-4/P2-5）
  - 审查参考/签到系统设计定稿.md（字段元数据表 L127-137 / 奖励四通道 L51-58 / 多表并存 L75-79 /
    结算管线 L62-73 / 校验器 §八 L139-151 / 日界统一 §5.2）
  - 2026-08-27 M4 设计审查裁决（设计审查_批次4，审查_M4设计_批次4_jspace.md）：
    P2-4（裁决⑧）[签到:*] 三键 = 表名限定：`[签到:<表名>.<字段>]`，缺省表名 = 主表（loop）
    P2-5（裁决⑦）补签只恢复 signed_days 与 streak 连续性、**不补发所补日期的 daily 奖励**；里程碑不重复

本文件 = M4 批次5·路F1 的独立模块（主 agent 收口时并入 content/models.py + validator.py 的 check_pack，
同 quest_models/shop_models 收口模式）：
  - 零冲突：不修改 models.py / validator.py / loader.py / __init__.py 既有内容。
  - CheckinDef 访问器 + PeriodDef / RewardsDef / RewardEntryDef / MakeupDef 四子表。
  - [签到:*] 三键解析（parse_checkin_key，裁决⑧）+ 跨模块（quest/npc/shop 条件）引用校验。
  - validate_checkins(modules, report, now=None) 为纯函数（无副作用），report 鸭子类型
    （error(module, field, kind, **detail) / warning(...)，同 _Checker._err/_warn 签名）。

【工程补白】（契约/定稿未显式定义处，显式标注供审查，不冒充定稿行号）：
  1. 任务派单口语化字段名（id/table/days[]/streak_bonus[]/makeup/settings）映射到权威 schema：
     table → type（定稿 L129，loop|monthly|activity 三值）；days[]（每日奖励）→ rewards.daily[]；
     streak_bonus[]（连签里程碑 days 阈值→额外奖励）→ rewards.streak[]；monthly_total 为第三个奖励
     通道（定稿 L57/L135）。本实现以定稿/细化权威字段树为准（顶层 7 字段：id/name/type/desc/period/
     rewards/makeup/bonus，细化_2b5 §1.2），不另立字段名。
  2. 重置时刻统一 05:00 **不落数据**：checkin.json 不存重置时刻字段；统一配置键 = settings.refresh_time
     （默认 "05:00"，商店/任务/签到三表同刻对齐，细化_2b5 §5.3 / 定稿 L106）。运行期解析权威 = A3
     core/dayroll（content→data 单向铁律不得反向依赖 core），本模块仅导出引用键与默认值常量文档。
  3. 里程碑阈值递增（连签 rewards.streak.days / 月度累计 rewards.monthly_total.days 严格递增）为结构
     硬拦——定稿 L56/L57 里程碑表语义（连签 N 天/签满 N 天阈值），递增防阈值倒挂/重复；定稿未显式要求
     递增校验，本实现按结构一致性收敛。
  4. 活动表时间窗黄提示（定稿 L147 未开始/已过期）为 best-effort：validate_checkins 接受可选 now
     （UTC+8 秒级时间戳）并本地镜像 A3 is_window_open 判定（纯函数）；now 缺省 None → 跳过（保确定性）。
     语义级启停（未开始/已过期 → 自动停用不报错）权威在 core/checkin.py 运行时（2b5 §2.2）。
  5. streak.days > cycle_days 黄提示（定稿 L148 / TC-06）的周期口径：loop/activity 用显式 cycle_days
     （缺省 7）；monthly 用显式 cycle_days，未配按 31（自然月天数上限，保守口径不误伤 ≤31 的合法阈值；
     运行期月度周期按实际当月天数，见 2b5 D-01）。
  6. 「签到表无人引用」（定稿 L150）黄提示为保守口径：仅多表包（≥2 表）且包内存在 [签到:*] 条件键
     （接线机制已启用）时，对未被任何 [签到:*] 条件引用的非 loop 表提示；loop 为主表默认入口豁免
     （裁决⑧ 缺省表名=loop）；活动表 bonus 挂载在运营页（content 层不可见），故本提示为 best-effort。
  7. 补签费超常见区间黄提示（定稿 L149）阈值 MAKEUP_COST_WARN_MAX=10000（单货币键单次费用），
     定稿未给具体区间，本实现收敛为工程常数。
  8. 每日奖励 day 重复（同表 rewards.daily[] 内）→ 黄提示：定稿 L55 按天轮转 key=day，重复日后条目
     遮蔽前条目（补白收敛防错账）。
  9. 补签两通道（定稿 L58）：① 补签卡（物品，经 reward 发放，无独立配置字段）② 货币付费 makeup.cost
     （settings 货币键值）。enabled=true 且 cost 为空 → 黄提示「补签不花钱？确认」（定稿 L149）。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；纯函数/懒计算；
确定性；工程补白显式标注；文件头标注依据；不 git commit。
仅依赖 qbot_rpg.content.models 的 BaseDef + qbot_rpg.content.field_meta 的 DEFAULT_CURRENCY_IDS。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Mapping, Optional, Set, Tuple, cast

from qbot_rpg.content.field_meta import DEFAULT_CURRENCY_IDS
from qbot_rpg.content.models import BaseDef

# =====================================================================================
# 权威枚举与常量（m4_shared_contract §3.4 + 细化_2b5 §1.2~1.8 + 定稿 L127-151 + 裁决⑦⑧）
# =====================================================================================
CHECKIN_MODULE: str = "checkin"  # checkin.json 模块名（loader _KIND_FOR_MODULE 口径；批次 7 收口登记）

# 三表类型（定稿 L129 / 细化_2b5 §1.3#3；缺省 loop）
CHECKIN_TYPES: Tuple[str, ...] = ("loop", "monthly", "activity")
CHECKIN_TYPE_DEFAULT: str = "loop"
CHECKIN_TYPE_NAMES: Dict[str, str] = {  # 定稿 L129 中文对照（供提示/编辑器）
    "loop": "常驻循环",
    "monthly": "月度",
    "activity": "活动",
}

# period 周期子对象（细化_2b5 §1.4：4 key）
CHECKIN_PERIOD_KEYS: Tuple[str, ...] = ("start", "end", "cycle_days", "reset_on_break")
CHECKIN_CYCLE_DAYS_DEFAULT: int = 7  # 定稿 L131：cycle_days 默认 7（loop/activity；monthly 自动当月天数）
CHECKIN_RESET_ON_BREAK_DEFAULT: bool = True  # 定稿 L132：断签重来默认 true
CHECKIN_MAX_MONTH_DAYS: int = 31  # 自然月天数上限（【工程补白】5：monthly 校验口径）
CHECKIN_NAME_MAX_LEN: int = 20  # 定稿 L128：name ≤20 字

# 重置时刻统一 05:00（【工程补白】2：不落数据；运行期权威 = A3 core/dayroll）
CHECKIN_RESET_TIME_KEY: str = "refresh_time"  # 统一配置键（商店/任务/签到三表同刻对齐，定稿 L106）
CHECKIN_RESET_TIME_DEFAULT: str = "05:00"  # 默认重置时刻（A3 dayroll DEFAULT_REFRESH_TIME 镜像）

# rewards 三通道（细化_2b5 §1.5：daily/streak/monthly_total；缺省 []）
CHECKIN_DAILY_WRAPPER: str = "day"  # 每日奖励包装键（定稿 L133）
CHECKIN_MILESTONE_WRAPPER: str = "days"  # 连签/月度累计里程碑包装键（定稿 L134/L135）
CHECKIN_ITEM_CONTAINER_KEY: str = "items"  # 物品容器键（定稿 L60：items[]{id,count}）

# 统一 reward 条目 5 键（定稿 L60 / 细化_2b5 §1.5；任务/签到共用发放器）
REWARD_ITEM_KEYS: Tuple[str, ...] = ("item", "id")  # 物品键（id ≡ item，定稿 L60 用 id）
REWARD_COUNT_KEY: str = "count"
REWARD_BOUND_KEY: str = "bound"  # 绑定标记（reward.py 扩展字段，结构校验放行）
REWARD_SCALAR_KEYS: Tuple[str, ...] = ("coins", "gem", "exp", "rep")  # 货币/数值键值条目键
# 单条签到奖励条目合法键 = 包装键 + 物品容器 + 标量键（定稿 L42 样例：同日 items+coins+exp 并存）
CHECKIN_ENTRY_ALLOWED_KEYS: Tuple[str, ...] = (
    CHECKIN_DAILY_WRAPPER, CHECKIN_MILESTONE_WRAPPER,
    CHECKIN_ITEM_CONTAINER_KEY, "coins", "gem", "exp", "rep",
)

# makeup 补签子对象（细化_2b5 §1.6：3 key；默认关）
CHECKIN_MAKEUP_MAX_PER_MONTH_DEFAULT: int = 0  # 定稿 L58/L16：0=不限（只建议不限制）
CHECKIN_MAKEUP_COST_WARN_MAX: int = 10000  # 【工程补白】7：补签费超常见区间阈值（定稿 L149）

# [签到:*] 三键（裁决⑧：表名限定；缺省表名 = 主表 loop）
CHECKIN_KEY_PREFIX: str = "[签到:"
CHECKIN_DEFAULT_TABLE: str = "loop"  # 缺省表名 = 主表（loop），裁决⑧
CHECKIN_KEY_STREAK: str = "连续天数"  # = 指定表 streak（2b5 裁决⑧）
CHECKIN_KEY_MONTHLY: str = "本月天数"  # = 指定表当月 signed_days（2b5 裁决⑧）
CHECKIN_KEY_TODAY: str = "今日已签"  # = 指定表今日已签（2b5 裁决⑧）
CHECKIN_KEY_FIELDS: Tuple[str, ...] = (CHECKIN_KEY_STREAK, CHECKIN_KEY_MONTHLY, CHECKIN_KEY_TODAY)

# 跨模块条件引用扫描靶（quest/npc/shop 条件引擎 var 键）
CHECKIN_REF_MODULES: Tuple[str, ...] = ("quest", "npc", "shop")


# =====================================================================================
# 子表 Def 类型（风格对齐 shop_models/npc_models：BaseDef + 防御性读取访问器）
# =====================================================================================


@dataclass(frozen=True)
class PeriodDef:
    """period 周期子对象（细化_2b5 §1.4：4 key：start/end/cycle_days/reset_on_break）。

    loop/monthly 常驻：start/end 缺省 null；activity 必填 start/end（时间窗懒计算启停，2b5 §2.2）。
    cycle_days 缺省 7（loop/activity）；monthly 自动 = 当月自然天数（28-31，运行期按实际当月天数，
    D-01）。reset_on_break 缺省 true（断签归 1；false=断签不重来，定稿 L132）。

    访问器返回原始值（None=缺省），生效值经 effective_* 派生（本层不伪造默认值）。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "PeriodDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def start(self) -> Optional[str]:
        """起算点时间串（\"YYYY-MM-DD[ HH:MM]\"）；loop/monthly 常驻=null；activity 必填。"""
        v = self.raw.get("start")
        return v if isinstance(v, str) else None

    @property
    def end(self) -> Optional[str]:
        """截止点时间串；activity 必填，过期懒计算停用（定稿 L130/L78）。"""
        v = self.raw.get("end")
        return v if isinstance(v, str) else None

    @property
    def cycle_days(self) -> Optional[int]:
        """周期天数：loop/activity N=cycle_days；monthly 自动=当月天数（缺省 None=自动）。"""
        v = self.raw.get("cycle_days")
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def reset_on_break(self) -> Optional[bool]:
        """断签重来开关：true=断签归 1；false=断签不重来（定稿 L132）。"""
        v = self.raw.get("reset_on_break")
        return v if isinstance(v, bool) else None

    def effective_cycle_days(self, table_type: str) -> int:
        """生效周期天数（校验口径）：显式 cycle_days > 类型默认（loop/activity=7；monthly=31 上限）。

        【工程补白】5：monthly 运行期按实际当月自然天数（D-01）；本口径仅供校验比对
        （streak.days > cycle / daily.day > cycle 黄提示），取自然月上限 31 保守不误伤。
        """
        cd = self.cycle_days
        if cd is not None:
            return cd
        if table_type == "monthly":
            return CHECKIN_MAX_MONTH_DAYS
        return CHECKIN_CYCLE_DAYS_DEFAULT

    def effective_reset_on_break(self) -> bool:
        """生效断签重来：显式值，否则默认 true（定稿 L132 / D-07）。"""
        v = self.reset_on_break
        return v if v is not None else CHECKIN_RESET_ON_BREAK_DEFAULT


@dataclass(frozen=True)
class RewardEntryDef:
    """签到奖励条目（每日/连签/月度累计统一 schema，细化_2b5 §1.5）。

    每日奖励条目 {day, items[], coins, gem, exp, rep}；连签/月度累计条目 {days, items[], ...}。
    day/days 为通道包装键（daily 用 day，streak/monthly_total 用 days）；items[]{id,count} 为物品数组；
    coins/gem/exp/rep 为标量键值——**可并存**（定稿 L42 样例同日多通道）。
    统一 reward 条目 = 任务/签到共用发放器（定稿 L60）。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "RewardEntryDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def day(self) -> Optional[int]:
        """每日奖励 day 编号（周期内第几天，1..N；D-01 口径见细化 §1.4）。"""
        v = self.raw.get(CHECKIN_DAILY_WRAPPER)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def days(self) -> Optional[int]:
        """里程碑阈值 days（连签 N 天/签满 N 天，定稿 L56/L57）。"""
        v = self.raw.get(CHECKIN_MILESTONE_WRAPPER)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def items(self) -> Tuple[Mapping[str, object], ...]:
        """物品条目数组 items[]{id,count}（定稿 L60；id ≡ item 键引用 items.json）。"""
        v = self.raw.get(CHECKIN_ITEM_CONTAINER_KEY)
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    def item_ids(self) -> Tuple[str, ...]:
        """物品条目引用的物品 ID 序列（去重前原序；供引用校验/引擎结算）。"""
        ids: List[str] = []
        for it in self.items:
            for k in REWARD_ITEM_KEYS:
                v = it.get(k)
                if isinstance(v, str) and v:
                    ids.append(v)
                    break
        return tuple(ids)

    def _scalar(self, key: str) -> Optional[int]:
        v = self.raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def coins(self) -> Optional[int]:
        return self._scalar("coins")

    @property
    def gem(self) -> Optional[int]:
        return self._scalar("gem")

    @property
    def exp(self) -> Optional[int]:
        return self._scalar("exp")

    @property
    def rep(self) -> Optional[int]:
        return self._scalar("rep")

    def has_reward(self) -> bool:
        """是否含任何奖励载荷（物品或标量键值）；空条目 = 该天/该档无奖励（合法但无意义）。"""
        if self.items:
            return True
        return any(self.raw.get(k) is not None for k in REWARD_SCALAR_KEYS)


@dataclass(frozen=True)
class RewardsDef:
    """rewards 奖励三通道（细化_2b5 §1.5：daily/streak/monthly_total；缺省 []）。"""

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "RewardsDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    def _entries(self, key: str) -> Tuple[RewardEntryDef, ...]:
        v = self.raw.get(key)
        return tuple(RewardEntryDef.from_entry(e) for e in v if isinstance(e, Mapping)) \
            if isinstance(v, list) else ()

    @property
    def daily(self) -> Tuple[RewardEntryDef, ...]:
        """每日奖励（{day, ...}；按天轮转，定稿 L55）。"""
        return self._entries("daily")

    @property
    def streak(self) -> Tuple[RewardEntryDef, ...]:
        """连签里程碑（{days, ...}；连续签到 N 天额外给，定稿 L56）。"""
        return self._entries("streak")

    @property
    def monthly_total(self) -> Tuple[RewardEntryDef, ...]:
        """月度累计里程碑（{days, ...}；当月签满 N 天给，不要求连续，定稿 L57）。"""
        return self._entries("monthly_total")

    def channel(self, name: str) -> Tuple[RewardEntryDef, ...]:
        """按通道名取条目（daily/streak/monthly_total；未知通道 → 空）。"""
        if name == "daily":
            return self.daily
        if name == "streak":
            return self.streak
        if name == "monthly_total":
            return self.monthly_total
        return ()


@dataclass(frozen=True)
class MakeupDef:
    """makeup 补签子对象（细化_2b5 §1.6：3 key：enabled/cost/max_per_month；默认关）。

    默认：enabled=false / cost={} / max_per_month=0（0=不限）。
    两通道（任一满足即可用，定稿 L58）：① 补签卡（物品，经 reward 发放，无独立配置字段）
    ② 货币付费 cost（settings 货币键值，定稿 L136）。
    裁决⑦：补签只恢复 signed_days 与 streak 连续性、**不补发所补日期 daily 奖励**；里程碑不重复。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "MakeupDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def enabled(self) -> bool:
        """补签总开关（默认关，可选模块，定稿 L58/L46）。"""
        v = self.raw.get("enabled")
        return v if isinstance(v, bool) else False

    @property
    def cost(self) -> Mapping[str, object]:
        """货币付费通道（`{coins:100}`…，settings 货币键值，定稿 L136）。"""
        v = self.raw.get("cost")
        return v if isinstance(v, Mapping) else {}

    @property
    def max_per_month(self) -> Optional[int]:
        """每月最大补签次数上限（0=不限，定稿 L58/L16）。"""
        v = self.raw.get("max_per_month")
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def effective_max_per_month(self) -> int:
        """生效月上限：显式值，否则默认 0=不限（定稿 L58/L16 / D-07）。"""
        v = self.max_per_month
        return v if v is not None else CHECKIN_MAKEUP_MAX_PER_MONTH_DEFAULT

    def has_cost_channel(self) -> bool:
        """是否配置货币付费通道（cost 非空）。补签卡通道经 reward 发放无配置字段。"""
        return bool(self.cost)


# =====================================================================================
# CheckinDef：checkin.json 条目（细化_2b5 §1.2：顶层 7 字段 + period 4 + rewards 3 + makeup 3 + bonus）
# =====================================================================================


@dataclass(frozen=True)
class CheckinDef(BaseDef):
    """checkin.json 条目（细化_2b5 §1.2：顶层 7 字段 + period 4 + rewards 3 + makeup 3 + bonus）。

    顶层 7 字段：id/name（BaseDef）/ type / desc / period / rewards / makeup / bonus。
    type 三类：loop 常驻循环 / monthly 月度 / activity 活动（缺省 loop，定稿 L129）。

    [签到:*] 三键（裁决⑧）：连续天数 = 指定表 streak / 本月天数 = 指定表当月 signed_days /
    今日已签 = 指定表今日已签；缺省表名 = 主表 loop。

    访问器均为防御性读取（类型不符 → None/空），缺省兜底语义由校验器/引擎侧负责
    （本层不伪造默认值；布尔标记缺省 false 对齐 shop_models.visible 口径）。
    """

    # ---- 数值/字符串/映射/列表辅助（与 QuestDef/ShopDef 同风格）----
    @classmethod
    def from_entry(cls, entry: Mapping[str, object], name_field: str = "name",
                   id_override: Optional[str] = None) -> "CheckinDef":
        """覆写 BaseDef.from_entry 的返回类型为 CheckinDef（类型标注精确化，行为不变）。"""
        return cast("CheckinDef", super().from_entry(entry, name_field=name_field,
                                                     id_override=id_override))

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    # ---- 顶层字段访问器（F03-F07；F01/F02 由 BaseDef）----
    @property
    def type(self) -> Optional[str]:
        """三表类型：loop 循环 / monthly 月度 / activity 活动（定稿 L129；缺省 loop 见 effective_type）。"""
        return self._str("type")

    @property
    def effective_type(self) -> str:
        """生效类型：显式值，否则默认 \"loop\"（定稿 L129 / D-07）。"""
        t = self.type
        return t if t in CHECKIN_TYPES else CHECKIN_TYPE_DEFAULT

    @property
    def is_activity(self) -> bool:
        """是否活动表（activity 必填 start/end，定稿 L130）。"""
        return self.effective_type == "activity"

    @property
    def desc(self) -> Optional[str]:
        """表描述（定稿 L39；缺省 \"\"）。"""
        return self._str("desc")

    @property
    def period(self) -> PeriodDef:
        """周期子对象（4 key；缺省常驻默认，2b5 §1.4）。"""
        return PeriodDef.from_entry(self.raw.get("period"))

    @property
    def rewards(self) -> RewardsDef:
        """奖励三通道（daily/streak/monthly_total；缺省空，2b5 §1.5）。"""
        return RewardsDef.from_entry(self.raw.get("rewards"))

    @property
    def makeup(self) -> MakeupDef:
        """补签配置（默认关，2b5 §1.6）。"""
        return MakeupDef.from_entry(self.raw.get("makeup"))

    @property
    def bonus(self) -> Mapping[str, object]:
        """活动加成对象（运营页挂载倍率，2b5 §1.7；缺省无）。"""
        return self._mapping("bonus")

    # ---- 派生/生效侧 ----
    def effective_cycle_days(self) -> int:
        """生效周期天数（校验口径）：显式 cycle_days > 类型默认（loop/activity=7；monthly=31 上限）。"""
        return self.period.effective_cycle_days(self.effective_type)

    def effective_reset_on_break(self) -> bool:
        """生效断签重来（默认 true，定稿 L132）。"""
        return self.period.effective_reset_on_break()

    def streak_thresholds(self) -> Tuple[int, ...]:
        """连签里程碑阈值序列（递增；运行期判断阈值达成/里程碑不重复）。"""
        return tuple(d.days for d in self.rewards.streak if d.days is not None)

    def monthly_total_thresholds(self) -> Tuple[int, ...]:
        """月度累计阈值序列（递增；不要求连续，碎片化铁律，定稿 L57）。"""
        return tuple(d.days for d in self.rewards.monthly_total if d.days is not None)


# =====================================================================================
# [签到:*] 三键解析（裁决⑧：表名限定；缺省表名=主表 loop）
# =====================================================================================


def parse_checkin_key(var: object) -> Optional[Tuple[str, str]]:
    """解析 [签到:<表名>.<字段>] 三键（裁决⑧）→ (表名, 字段)。

    - 格式：`[签到:<表名>.<字段>]`，如 `[签到:loop.连续天数]` / `[签到:monthly.本月天数]` /
      `[签到:activity.今日已签]`；**缺省表名 = 主表 loop**（`[签到:连续天数]` → (\"loop\", \"连续天数\")）。
    - 字段三值（裁决⑧）：连续天数=指定表 streak / 本月天数=指定表当月 signed_days /
      今日已签=指定表今日已签。
    - 非法格式 / 未知字段 → None（消费方按求值失败处理，2b5 裁决⑧ 求值失败默认 False）。
    """
    if not isinstance(var, str) or not var:
        return None
    v = var.strip()
    if not (v.startswith(CHECKIN_KEY_PREFIX) and v.endswith("]")):
        return None
    inner = v[len(CHECKIN_KEY_PREFIX):-1].strip()
    if not inner:
        return None
    if "." in inner:
        table, sep, field = inner.partition(".")
        if not sep:
            return None
        table = table.strip()
    else:
        table, field = None, inner
    field = field.strip()
    if not field or field not in CHECKIN_KEY_FIELDS:
        return None
    return (table if table else CHECKIN_DEFAULT_TABLE), field


def parse_checkins(modules: Mapping[str, object]) -> Tuple[CheckinDef, ...]:
    """从 modules 提取 checkin 模块 → CheckinDef 元组（非 list / 非对象条目跳过；供运行期与测试复用）。"""
    checkins = modules.get(CHECKIN_MODULE) if isinstance(modules, Mapping) else None
    if not isinstance(checkins, list):
        return ()
    return tuple(cast(CheckinDef, CheckinDef.from_entry(e)) for e in checkins if isinstance(e, Mapping))


# =====================================================================================
# validate_checkins：checkin 模块专项校验（2b5 §1.8 + 定稿 §八 + 裁决⑦⑧；供主 agent 收口接 check_pack）
# =====================================================================================
# 规则清单（红拦=errors / 黄提示=warnings）：
#   硬拦 R-1：id 必填非空 string 且池内唯一；name 必填；type ∉ loop|monthly|activity（缺省 loop 不拦）；
#             desc/period/rewards/makeup/bonus 类型错；period.start/end 非 str；reset_on_break 非 bool
#   硬拦 R-2：cycle_days 非 ≥1 整数；补签费/奖励数负数（定稿 L143「奖励数量不能是负数哦」）；
#             items[].count 非 ≥1 整数；items[].bound 非 bool；scalar 非 ≥0 整数；makeup.max_per_month 负数；
#             bonus.mult 非法
#   硬拦 R-4：items 物品引用不存在（items 模块存在时）；coins/gem 货币键未注册（settings 存在时）；
#             makeup.cost 货币键未注册；activity 缺 start/end（定稿 L130 活动表必填）
#   硬拦 R-5：表条目/period/rewards/makeup/bonus 非对象；rewards 通道非数组；条目非对象；条目未知键；
#             条目缺 day/days 或 day/days 非 ≥1 整数；items 非数组；物品条目非对象/缺 id/未知键；
#             连签与月度累计阈值非严格递增（【工程补白】3）
#   黄提示 Y：activity 时间窗未开始/已过期（now 提供时，定稿 L147）；streak.days>cycle_days（L148）；
#             makeup 开启但无费用通道（L149）；补签费超常见区间（L149）；循环表缺 cycle_days 已按默认 7
#             补全（L151/TC-03）；name>20 字（L128）；常驻表配时间窗；每日 day 超周期（L55）；
#             每日 day 重复（【工程补白】8）；[签到:*] 条件键格式/表引用悬空/表无人引用（L150 + 裁决⑧）


def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    """收集器鸭子类型适配：优先 report.<method>，其次 validator._Checker 的 _<method>。"""
    _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
    fn = getattr(report, method, None)
    if not callable(fn):
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", CHECKIN_MODULE, field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", CHECKIN_MODULE, field, kind, **detail)


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


# -------------------------------------------------------------------------------------
# 引用靶构建
# -------------------------------------------------------------------------------------
class _Refs:
    """checkin 模块跨模块引用校验靶（None = 目标模块未声明/无合法 id → 跳过对应引用检查）。

    table_types: id → 生效 type 映射（裁决⑧ 引用解析同时匹配表 id 与 type——文档示例
    [签到:monthly.本月天数] 用 type 限定，表 id 为 checkin_monthly，两口径皆须可解析）。
    """

    __slots__ = ("checkin_ids", "table_types", "item_ids", "currency_ids")

    def __init__(self) -> None:
        self.checkin_ids: Set[str] = set()  # 本池合法表 ID（校验过程中收集）
        self.table_types: Dict[str, str] = {}  # id → 生效 type（引用解析双口径）
        self.item_ids: Optional[Set[str]] = None
        self.currency_ids: Tuple[str, ...] = ()


# -------------------------------------------------------------------------------------
# 时间窗本地镜像（【工程补白】4：镜像 A3 core/dayroll.is_window_open，不 import core）
# -------------------------------------------------------------------------------------
_TZ_UTC8 = timezone(timedelta(hours=8))


def _parse_time_str(s: object) -> Optional[int]:
    """时间串 \"YYYY-MM-DD[ HH:MM]\"（UTC+8）→ epoch 秒；时间缺省 = 当日 00:00；非法 → None。"""
    if not isinstance(s, str):
        return None
    t = s.strip()
    try:
        if len(t) < 10 or t[4] != "-" or t[7] != "-":
            return None
        d = date.fromisoformat(t[:10])
        rest = t[10:].strip().lstrip("T")
        h = m = 0
        if rest:
            parts = rest.split(":")
            h = int(parts[0])
            if len(parts) > 1:
                m = int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return int(datetime(d.year, d.month, d.day, h, m, 0, tzinfo=_TZ_UTC8).timestamp())
    except (ValueError, IndexError):
        return None


def _window_status(start: object, end: object, now: int) -> Optional[str]:
    """时间窗判定（闭区间）：now<start → \"not_started\"；now>end → \"expired\"；否则 \"open\"。
    start/end 缺省或解析失败 → None（消费方跳过）。镜像 core/dayroll.is_window_open。"""
    s = _parse_time_str(start)
    e = _parse_time_str(end)
    if s is not None and now < s:
        return "not_started"
    if e is not None and now > e:
        return "expired"
    return "open"


def _effective_cycle(period: object, eff_type: str) -> int:
    """生效周期天数（校验口径）：显式 cycle_days > 类型默认（loop/activity=7；monthly=31 上限）。"""
    if isinstance(period, Mapping) and isinstance(period.get("cycle_days"), int) \
            and not isinstance(period.get("cycle_days"), bool) and period["cycle_days"] >= 1:
        return period["cycle_days"]  # type: ignore[return-value]  # 已判 int
    if eff_type == "monthly":
        return CHECKIN_MAX_MONTH_DAYS
    return CHECKIN_CYCLE_DAYS_DEFAULT


# -------------------------------------------------------------------------------------
# period / rewards / makeup / bonus 子对象校验
# -------------------------------------------------------------------------------------
def _check_period_defaults(report: object, base: str, node_id: str, eff_type: str,
                           period: object = None) -> None:
    """循环表缺 cycle_days → 黄提示「已按默认 7 补全」（定稿 L151 / TC-03）。"""
    if eff_type != "loop":
        return
    has = isinstance(period, Mapping) and period.get("cycle_days") is not None
    if not has:
        _warn(report, f"{base}.cycle_days", "Y-4", rule="checkin_cycle_days_default",
              node_id=node_id, default=CHECKIN_CYCLE_DAYS_DEFAULT,
              msg="循环表缺 cycle_days → 已按默认 %s 补全（定稿 L151 / TC-03）"
                  % (CHECKIN_CYCLE_DAYS_DEFAULT,))


def _check_period(report: object, period: object, base: str, node_id: str, eff_type: str) -> None:
    """period 结构校验（4 key：start/end/cycle_days/reset_on_break）。

    红拦：period 非对象 / start/end 非 str / cycle_days 非 ≥1 整数 / reset_on_break 非 bool /
          activity 缺 start/end（定稿 L130 活动表必填）。
    黄提示：常驻表（loop/monthly）配了时间窗（常驻=null）；循环表缺 cycle_days 默认 7 补全。
    """
    if period is None:
        _check_period_defaults(report, base, node_id, eff_type, None)
        if eff_type == "activity":
            # 活动表 start/end 必填（定稿 L130）——period 整体缺省也须拦（活动表必有时间窗）
            _err(report, f"{base}.start", "R-4", rule="checkin_activity_start_required",
                 node_id=node_id, msg="活动表 period.start 必填（定稿 L130：活动表必填）")
            _err(report, f"{base}.end", "R-4", rule="checkin_activity_end_required",
                 node_id=node_id, msg="活动表 period.end 必填（定稿 L130：活动表必填）")
        return  # 常驻表缺省常驻默认（D-07：漏配 period 绝不报错）
    if not isinstance(period, Mapping):
        _err(report, base, "R-5", rule="checkin_period_not_object", node_id=node_id,
             got=type(period).__name__,
             msg="period 要填对象 {start, end, cycle_days, reset_on_break}")
        _check_period_defaults(report, base, node_id, eff_type, None)
        if eff_type == "activity":
            _err(report, f"{base}.start", "R-4", rule="checkin_activity_start_required",
                 node_id=node_id, msg="活动表 period.start 必填（定稿 L130：活动表必填）")
            _err(report, f"{base}.end", "R-4", rule="checkin_activity_end_required",
                 node_id=node_id, msg="活动表 period.end 必填（定稿 L130：活动表必填）")
        return
    start = period.get("start")
    end = period.get("end")
    if start is not None and not isinstance(start, str):
        _err(report, f"{base}.start", "R-1", rule="checkin_period_start_invalid",
             node_id=node_id, value=start, msg="period.start 需字符串（\"YYYY-MM-DD[ HH:MM]\"）")
    if end is not None and not isinstance(end, str):
        _err(report, f"{base}.end", "R-1", rule="checkin_period_end_invalid",
             node_id=node_id, value=end, msg="period.end 需字符串（\"YYYY-MM-DD[ HH:MM]\"）")
    if eff_type == "activity":
        # 活动表必填 start/end（定稿 L130/L78；未开始/已过期 → 运行期自动停用）
        if not isinstance(start, str) or not start:
            _err(report, f"{base}.start", "R-4", rule="checkin_activity_start_required",
                 node_id=node_id, msg="活动表 period.start 必填（定稿 L130：活动表必填）")
        if not isinstance(end, str) or not end:
            _err(report, f"{base}.end", "R-4", rule="checkin_activity_end_required",
                 node_id=node_id, msg="活动表 period.end 必填（定稿 L130：活动表必填）")
    elif start is not None or end is not None:
        _warn(report, base, "Y-4", rule="checkin_resident_window", node_id=node_id,
              start=start, end=end,
              msg="常驻表（loop/monthly）配了时间窗 start/end——常驻表应为 null，确认？"
                  "（定稿 L130 常驻=null）")
    cd = period.get("cycle_days")
    if cd is not None and (not isinstance(cd, int) or isinstance(cd, bool) or cd < 1):
        _err(report, f"{base}.cycle_days", "R-2", rule="checkin_cycle_days_invalid",
             node_id=node_id, cycle_days=cd,
             msg="period.cycle_days 需 ≥1 整数（monthly 自动=当月天数可不配，定稿 L131）")
    rob = period.get("reset_on_break")
    if rob is not None and not isinstance(rob, bool):
        _err(report, f"{base}.reset_on_break", "R-1", rule="checkin_reset_on_break_invalid",
             node_id=node_id, value=rob,
             msg="period.reset_on_break 需 bool（true=断签归 1 / false=断签不重来，定稿 L132）")
    _check_period_defaults(report, base, node_id, eff_type, period)


def _check_item(report: object, item: object, base: str, node_id: str, refs: _Refs) -> None:
    """单条物品条目 items[]{id|item, count, bound} 校验（定稿 L60 / 细化_2b5 §1.5）。

    红拦：物品条目非对象 / 缺 id（item 别名亦可）/ 未知键 / id 非空串 / 引用不存在（items 模块存在时）
          / count 非 ≥1 整数 / bound 非 bool。
    """
    if not isinstance(item, Mapping):
        _err(report, base, "R-5", rule="checkin_item_not_object", node_id=node_id,
             got=type(item).__name__, msg="items[] 条目需对象 {id, count}（定稿 L60）")
        return
    keys = set(item.keys())
    item_key = next((k for k in REWARD_ITEM_KEYS if k in item), None)
    if item_key is None:
        _err(report, base, "R-5", rule="checkin_item_missing_id", node_id=node_id,
             keys=sorted(keys), msg="物品条目需含物品键（id/item，定稿 L60 items[]{id,count}）")
        return
    unknown = keys - {item_key, REWARD_COUNT_KEY, REWARD_BOUND_KEY}
    if unknown:
        _err(report, base, "R-5", rule="checkin_item_unknown_key", node_id=node_id,
             keys=sorted(unknown), msg="物品条目多余键 %s（合法：%s/count/bound）" % (sorted(unknown), item_key))
    iid = item[item_key]
    if not isinstance(iid, str) or not iid:
        _err(report, f"{base}.{item_key}", "R-5", rule="checkin_item_id_invalid",
             node_id=node_id, item_id=iid, msg="物品条目 %s 需非空字符串（items.json 键）" % (item_key,))
    elif refs.item_ids is not None and iid not in refs.item_ids:
        _err(report, f"{base}.{item_key}", "R-4", rule="checkin_item_ref_missing",
             node_id=node_id, item=iid, registered=sorted(refs.item_ids),
             msg="签到奖励物品 %r 在 items.json 中不存在，先去物品页添加（定稿 L142/L60）" % (iid,))
    if REWARD_COUNT_KEY in item:
        count = item[REWARD_COUNT_KEY]
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            _err(report, f"{base}.count", "R-2", rule="checkin_item_count_invalid",
                 node_id=node_id, count=count,
                 msg="物品 count 需 ≥1 整数（缺省 1；负数/零 → 「奖励数量不能是负数哦」，定稿 L143）")
    if REWARD_BOUND_KEY in item and not isinstance(item[REWARD_BOUND_KEY], bool):
        _err(report, f"{base}.bound", "R-1", rule="checkin_item_bound_invalid",
             node_id=node_id, value=item[REWARD_BOUND_KEY],
             msg="物品 bound 需 bool（缺省 true=绑定，定稿 L60 防套利）")


def _check_reward_entry(report: object, entry: Mapping[str, object], base: str, node_id: str,
                        refs: _Refs, wrapper: str, eff_cycle: int) -> None:
    """单条签到奖励条目校验：{wrapper(day|days), items[], coins, gem, exp, rep}。

    红拦：未知键 / 包装键（day/days）缺或非 ≥1 整数 / items 非数组 / 物品条目结构错 / scalar 非 ≥0 整数
          / 货币键未注册 / 物品引用不存在。
    黄提示：每日 day 超周期（定稿 L55 day 1..N 轮转）。
    """
    keys = set(entry.keys())
    unknown = keys - set(CHECKIN_ENTRY_ALLOWED_KEYS)
    if unknown:
        _err(report, base, "R-5", rule="checkin_entry_unknown_key", node_id=node_id,
             keys=sorted(unknown), allowed=list(CHECKIN_ENTRY_ALLOWED_KEYS),
             msg="签到奖励条目多余键 %s（合法：%s 单键 + items/coins/gem/exp/rep）"
                 % (sorted(unknown), wrapper))
    wv = entry.get(wrapper)
    if wv is None:
        _err(report, f"{base}.{wrapper}", "R-5", rule="checkin_wrapper_missing", node_id=node_id,
             wrapper=wrapper, keys=sorted(keys),
             msg="签到奖励条目缺 %s（每日用 day / 里程碑用 days，定稿 L133-135）" % (wrapper,))
    elif not isinstance(wv, int) or isinstance(wv, bool) or wv < 1:
        _err(report, f"{base}.{wrapper}", "R-2", rule="checkin_wrapper_invalid", node_id=node_id,
             wrapper=wrapper, value=wv, msg="%s 需 ≥1 整数（周期内第几天/连签第 N 天）" % (wrapper,))
    if "items" in entry:
        arr = entry["items"]
        if not isinstance(arr, list):
            _err(report, f"{base}.items", "R-5", rule="checkin_items_not_list", node_id=node_id,
                 got=type(arr).__name__, msg="items 需数组（items[]{id,count}，定稿 L60）")
        else:
            for ii, it in enumerate(arr):
                _check_item(report, it, f"{base}.items.{ii}", node_id, refs)
    for key in REWARD_SCALAR_KEYS:
        if key in entry:
            v = entry[key]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                _err(report, f"{base}.{key}", "R-2", rule="checkin_reward_value_invalid",
                     node_id=node_id, key=key, value=v,
                     msg="标量奖励 %s 需 ≥0 整数（负数 → 「奖励数量不能是负数哦」，定稿 L143）" % (key,))
            elif key in ("coins", "gem") and refs.currency_ids and key not in refs.currency_ids:
                _err(report, f"{base}.{key}", "R-4", rule="checkin_reward_currency_unregistered",
                     node_id=node_id, currency=key, registered=list(refs.currency_ids),
                     msg="奖励货币键 %r 未注册（settings.currencies 键空间，定稿 L60）" % (key,))
    # 黄提示：每日 day 超周期（定稿 L55：day 1..N 轮转；N=loop/activity 周期 / monthly 当月天数）
    if wrapper == CHECKIN_DAILY_WRAPPER and isinstance(wv, int) and not isinstance(wv, bool) \
            and wv > eff_cycle:
        _warn(report, f"{base}.{wrapper}", "Y-4", rule="checkin_daily_day_over_cycle",
              node_id=node_id, day=wv, cycle=eff_cycle,
              msg="每日奖励 day=%s 超周期 %s 天——该档永远不会被轮到，确认？（定稿 L55 day 1..N 轮转）"
                  % (wv, eff_cycle))


def _check_rewards(report: object, rewards: object, base: str, node_id: str,
                   refs: _Refs, eff_type: str, eff_cycle: int) -> None:
    """rewards 三通道校验（daily/streak/monthly_total）。

    红拦：rewards 非对象 / 通道非数组 / 条目非对象 / 条目结构错 / 连签与月度累计阈值非严格递增
          （【工程补白】3）。
    黄提示：streak.days > cycle_days（定稿 L148/TC-06）/ 每日 day 重复（【工程补白】8）。
    """
    if rewards is None:
        return  # 缺省三通道 []（D-07：绝不报错）
    if not isinstance(rewards, Mapping):
        _err(report, base, "R-5", rule="checkin_rewards_not_object", node_id=node_id,
             got=type(rewards).__name__,
             msg="rewards 要填对象 {daily:[], streak:[], monthly_total:[]}")
        return
    for channel, wrapper in (("daily", CHECKIN_DAILY_WRAPPER),
                             ("streak", CHECKIN_MILESTONE_WRAPPER),
                             ("monthly_total", CHECKIN_MILESTONE_WRAPPER)):
        arr = rewards.get(channel)
        if arr is None:
            continue  # 缺省 []（D-07）
        if not isinstance(arr, list):
            _err(report, f"{base}.{channel}", "R-5", rule="checkin_channel_not_list",
                 node_id=node_id, channel=channel, got=type(arr).__name__,
                 msg="rewards.%s 需数组（{day|days, 统一 reward 条目数组}，定稿 L133-135）" % (channel,))
            continue
        prev_days: Optional[int] = None
        seen_days: Set[int] = set()
        for i, ent in enumerate(arr):
            ebase = f"{base}.{channel}.{i}"
            if not isinstance(ent, Mapping):
                _err(report, ebase, "R-5", rule="checkin_entry_not_object", node_id=node_id,
                     got=type(ent).__name__, msg="rewards.%s 条目需对象" % (channel,))
                continue
            _check_reward_entry(report, ent, ebase, node_id, refs, wrapper, eff_cycle)
            wv = ent.get(wrapper)
            if isinstance(wv, int) and not isinstance(wv, bool):
                if channel == "daily":
                    if wv in seen_days:
                        _warn(report, ebase, "Y-4", rule="checkin_daily_day_duplicate",
                              node_id=node_id, day=wv,
                              msg="每日奖励 day=%s 重复——后条目遮蔽前条目，确认？（定稿 L55 按天轮转）"
                                  % (wv,))
                    seen_days.add(wv)
                else:
                    if prev_days is not None and wv <= prev_days:
                        _err(report, ebase, "R-5", rule="checkin_milestone_not_increasing",
                             node_id=node_id, channel=channel, days=wv, prev=prev_days,
                             msg="%s 里程碑 days 需严格递增（%s <= %s）——阈值倒挂/重复确认？"
                                 % (channel, wv, prev_days))
                    prev_days = wv
                    if channel == "streak" and wv > eff_cycle:
                        _warn(report, ebase, "Y-4", rule="checkin_streak_over_cycle",
                              node_id=node_id, days=wv, cycle=eff_cycle,
                              msg="连签 %s 天才给，但周期只有 %s 天——该里程碑永远达不到，确认？"
                                  "（定稿 L148/TC-06）" % (wv, eff_cycle))


def _check_makeup(report: object, makeup: object, base: str, node_id: str, refs: _Refs) -> None:
    """makeup 补签配置校验（3 key：enabled/cost/max_per_month；默认关）。

    红拦：makeup 非对象 / enabled 非 bool / cost 非对象 / 费用负数（定稿 L143）/ cost 货币键未注册
          / max_per_month 负数（0=不限）。
    黄提示：补签开启但无任何费用通道（定稿 L149「补签不花钱？确认」）/ 补签费超常见区间（L149）。
    """
    if makeup is None:
        return  # 默认关（D-07：绝不报错）
    if not isinstance(makeup, Mapping):
        _err(report, base, "R-5", rule="checkin_makeup_not_object", node_id=node_id,
             got=type(makeup).__name__,
             msg="makeup 要填对象 {enabled, cost, max_per_month}（定稿 L136）")
        return
    enabled = makeup.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        _err(report, f"{base}.enabled", "R-1", rule="checkin_makeup_enabled_invalid",
             node_id=node_id, value=enabled, msg="makeup.enabled 需 bool（默认 false=关，定稿 L136）")
    cost = makeup.get("cost")
    if cost is None:
        cost = {}
    if not isinstance(cost, Mapping):
        _err(report, f"{base}.cost", "R-5", rule="checkin_makeup_cost_not_object",
             node_id=node_id, got=type(cost).__name__,
             msg="makeup.cost 需对象（settings 货币键值，如 {coins:100}，定稿 L136/L58）")
    else:
        for ckey, cval in cost.items():
            if not isinstance(cval, int) or isinstance(cval, bool) or cval < 0:
                _err(report, f"{base}.cost.{ckey}", "R-2", rule="checkin_makeup_cost_negative",
                     node_id=node_id, currency=ckey, value=cval,
                     msg="补签费不能是负数哦（定稿 L143：奖励数量不能是负数）")
            elif isinstance(cval, int) and cval > CHECKIN_MAKEUP_COST_WARN_MAX:
                _warn(report, f"{base}.cost.{ckey}", "Y-4", rule="checkin_makeup_cost_high",
                      node_id=node_id, currency=ckey, value=cval,
                      max=CHECKIN_MAKEUP_COST_WARN_MAX,
                      msg="补签费 %s=%s 超常见区间（>%s），确认？（定稿 L149 补签费超常见区间）"
                          % (ckey, cval, CHECKIN_MAKEUP_COST_WARN_MAX))
            if isinstance(ckey, str) and refs.currency_ids and ckey not in refs.currency_ids:
                _err(report, f"{base}.cost.{ckey}", "R-4",
                     rule="checkin_makeup_cost_currency_unregistered", node_id=node_id,
                     currency=ckey, registered=list(refs.currency_ids),
                     msg="补签费货币键 %r 未注册（settings.currencies 键空间，定稿 L136）" % (ckey,))
    mpm = makeup.get("max_per_month")
    if mpm is not None and (not isinstance(mpm, int) or isinstance(mpm, bool) or mpm < 0):
        _err(report, f"{base}.max_per_month", "R-2", rule="checkin_makeup_max_per_month_invalid",
             node_id=node_id, value=mpm,
             msg="makeup.max_per_month 需 ≥0 整数（0=不限，定稿 L58/L16）")
    # 补签开启但无任何费用通道（定稿 L149）：补签卡经 reward 发放无配置字段，此处仅认货币付费 cost
    is_enabled = enabled if isinstance(enabled, bool) else False
    if is_enabled and not cost:
        _warn(report, base, "Y-4", rule="checkin_makeup_no_cost", node_id=node_id,
              msg="补签开启但无任何费用通道——补签不花钱？确认（定稿 L149）")


def _check_bonus(report: object, bonus: object, base: str, node_id: str) -> None:
    """bonus 活动加成对象校验（2b5 §1.7：运营页挂载倍率；D-04 乘算语义归 core/checkin.py）。

    红拦：bonus 非对象 / mult 非法（非 ≥0 数值）。
    结构宽松（运营页挂载形态未定稿）：只认对象 + mult 数值合法。
    """
    if bonus is None:
        return  # 缺省无（D-07）
    if not isinstance(bonus, Mapping):
        _err(report, base, "R-5", rule="checkin_bonus_not_object", node_id=node_id,
             got=type(bonus).__name__, msg="bonus 要填对象（运营页活动挂载倍率，2b5 §1.7）")
        return
    mult = bonus.get("mult")
    if mult is not None and (isinstance(mult, bool) or not isinstance(mult, (int, float)) or mult < 0):
        _err(report, f"{base}.mult", "R-2", rule="checkin_bonus_mult_invalid", node_id=node_id,
             value=mult, msg="bonus.mult 需 ≥0 数值（结算时统一乘算，D-04 向下取整）")


def _check_window_status(report: object, period: object, base: str, node_id: str,
                         eff_type: str, now: int) -> None:
    """活动表时间窗状态黄提示（定稿 L147 未开始/已过期；【工程补白】4：best-effort）。

    语义级启停（自动停用不报错）权威在 core/checkin.py 运行时（2b5 §2.2）；此处仅配置期提示。
    """
    if eff_type != "activity" or not isinstance(period, Mapping):
        return
    start = period.get("start")
    end = period.get("end")
    status = _window_status(start, end, now)
    if status == "not_started":
        _warn(report, f"{base}.start", "Y-4", rule="checkin_activity_not_started", node_id=node_id,
              start=start, end=end, now=now,
              msg="签到表时间窗口未开始——自动停用不报错，确认运营期？（定稿 L147/L78）")
    elif status == "expired":
        _warn(report, f"{base}.end", "Y-4", rule="checkin_activity_expired", node_id=node_id,
              start=start, end=end, now=now,
              msg="签到表时间窗口已过期——自动停用不报错，确认运营期？（定稿 L147/L78）")


# -------------------------------------------------------------------------------------
# 单表校验
# -------------------------------------------------------------------------------------
def _check_checkin(report: object, entry: Mapping[str, object], idx: int, node_id: str,
                   refs: _Refs, seen_ids: Set[str], now: object) -> None:
    """单表校验：顶层 7 字段 + period/rewards/makeup/bonus 子对象。"""
    ctype = entry.get("type")
    if ctype is not None and (not isinstance(ctype, str) or ctype not in CHECKIN_TYPES):
        _err(report, f"checkin.{idx}.type", "R-1", rule="checkin_type_invalid", node_id=node_id,
             value=ctype, allowed=list(CHECKIN_TYPES),
             msg="type %r 不认识（三表类型：%s，缺省 loop，定稿 L129）"
                 % (ctype, "/".join(CHECKIN_TYPES)))
    eff_type = ctype if isinstance(ctype, str) and ctype in CHECKIN_TYPES else CHECKIN_TYPE_DEFAULT

    cid = entry.get("id")
    if not isinstance(cid, str) or not cid:
        _err(report, f"checkin.{idx}.id", "R-5", rule="checkin_id_required", node_id=node_id,
             msg="签到表 id 必填（全局唯一，checkin_state 按表 ID 键控，定稿 L127/L110）")
    elif cid in seen_ids:
        _err(report, f"checkin.{idx}.id", "R-5", rule="checkin_id_duplicate", node_id=node_id,
             id=cid, msg="签到表 id %r 重复（全局唯一，定稿 L142 ID 重复硬拦）" % (cid,))
    else:
        seen_ids.add(cid)
        refs.checkin_ids.add(cid)
        refs.table_types[cid] = eff_type  # 引用解析双口径（表 id + 生效 type，裁决⑧）

    name = entry.get("name")
    if not isinstance(name, str) or not name:
        _err(report, f"checkin.{idx}.name", "R-5", rule="checkin_name_required", node_id=node_id,
             name=name, msg="签到表 name 必填（玩家可见表名，定稿 L128）")
    elif len(name) > CHECKIN_NAME_MAX_LEN:
        _warn(report, f"checkin.{idx}.name", "Y-4", rule="checkin_name_too_long", node_id=node_id,
              name=name, max_len=CHECKIN_NAME_MAX_LEN,
              msg="签到表 name %s 超 %s 字上限（定稿 L128：≤20 字）——过长显示截断确认？"
                  % (len(name), CHECKIN_NAME_MAX_LEN))

    if "desc" in entry and entry["desc"] is not None and not isinstance(entry["desc"], str):
        _err(report, f"checkin.{idx}.desc", "R-1", rule="checkin_desc_invalid", node_id=node_id,
             value=entry["desc"], msg="desc 需字符串（表描述，缺省 \"\"，定稿 L39）")

    period = entry.get("period")
    eff_cycle = _effective_cycle(period, eff_type)
    _check_period(report, period, f"checkin.{idx}.period", node_id, eff_type)
    _check_rewards(report, entry.get("rewards"), f"checkin.{idx}.rewards", node_id,
                   refs, eff_type, eff_cycle)
    _check_makeup(report, entry.get("makeup"), f"checkin.{idx}.makeup", node_id, refs)
    _check_bonus(report, entry.get("bonus"), f"checkin.{idx}.bonus", node_id)
    if isinstance(now, (int, float)) and not isinstance(now, bool):
        _check_window_status(report, period, f"checkin.{idx}.period", node_id, eff_type, int(now))


# -------------------------------------------------------------------------------------
# [签到:*] 三键跨模块引用校验（裁决⑧ + 定稿 L150）
# -------------------------------------------------------------------------------------
def _collect_checkin_keys(modules: Mapping[str, object]) -> Tuple[Set[str], List[str]]:
    """扫描 quest/npc/shop 条件引擎 var 键中的 [签到:*] 键 → (引用表名集合, 格式非法键列表)。

    通用深扫：任何 var 键值以 "[签到:" 开头即收集（schema 无关）；递归 any/all/not 嵌套由 walk 天然覆盖。
    """
    tables: Set[str] = set()
    malformed: List[str] = []

    def walk(obj: object) -> None:
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                if k == "var" and isinstance(v, str):
                    s = v.strip()
                    if s.startswith(CHECKIN_KEY_PREFIX) and s.endswith("]"):
                        parsed = parse_checkin_key(s)
                        if parsed is not None:
                            tables.add(parsed[0])
                        else:
                            malformed.append(s)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    for modname in CHECKIN_REF_MODULES:
        data = modules.get(modname)
        walk(data)
    return tables, malformed


def _check_checkin_references(report: object, modules: Mapping[str, object], refs: _Refs) -> None:
    """[签到:*] 三键跨模块引用校验（裁决⑧ 表名限定 + 定稿 L150 无人引用）。

    黄提示：
      - 条件键格式非法（字段 ∉ 三值）→「键格式不认识」
      - 条件引用的表 id 不存在 →「引用签到表不存在」（缺省表名=loop）
      - 多表包且接线机制启用（包内存在 [签到:*] 键）时，非 loop 表未被引用 →「无人引用」（L150，
        【工程补白】6：best-effort，活动 bonus 挂载在运营页 content 层不可见）
    """
    referenced, malformed = _collect_checkin_keys(modules)
    for var in malformed:
        _warn(report, CHECKIN_MODULE, "Y-4", rule="checkin_key_format_invalid", var=var,
              fields=list(CHECKIN_KEY_FIELDS),
              msg="条件键 %r 格式不认识（裁决⑧：[签到:<表名>.<字段>]，字段三值：连续天数/本月天数/"
                  "今日已签）" % (var,))
    # 引用解析双口径（裁决⑧）：限定符匹配表 id 或生效 type（文档示例 [签到:monthly.本月天数] 用
    # type 限定，表 id 为 checkin_monthly，两口径皆可解析）
    for tbl in sorted(referenced):
        if tbl not in refs.checkin_ids and tbl not in refs.table_types.values():
            _warn(report, CHECKIN_MODULE, "Y-4", rule="checkin_key_table_ref_missing",
                  table=tbl, registered=sorted(refs.checkin_ids),
                  types=sorted(set(refs.table_types.values())),
                  msg="条件键 [签到:%s.*] 引用签到表 %r 不存在（裁决⑧：缺省表名=主表 loop，确认表名？）"
                      % (tbl, tbl))
    # 无人引用（定稿 L150，【工程补白】6 保守口径）：多表包 + 接线机制启用（包内存在 [签到:*] 键）时，
    # 未被任何条件键引用的非 loop 表提示；loop 主表默认入口豁免（裁决⑧ 缺省表名=loop）
    if len(refs.table_types) >= 2 and referenced:
        for cid in sorted(refs.table_types):
            if refs.table_types[cid] == CHECKIN_DEFAULT_TABLE:
                continue  # loop 主表默认入口豁免
            if cid in referenced or refs.table_types[cid] in referenced:
                continue
            _warn(report, CHECKIN_MODULE, "Y-4", rule="checkin_table_unreferenced", table=cid,
                  table_type=refs.table_types[cid], registered=sorted(refs.checkin_ids),
                  msg="签到表 %r 没有绑定任何活动/默认入口——无人引用确认？（定稿 L150；loop 为主表"
                      "默认入口豁免，裁决⑧）" % (cid,))


# -------------------------------------------------------------------------------------
# 入口
# -------------------------------------------------------------------------------------
def validate_checkins(modules: Mapping[str, object], report: object, now: object = None) -> None:
    """checkin 模块专项校验（M4 批次5·路F1：CheckinDef 多表 + 奖励三通道 + 补签 + 里程碑 + [签到:*] 三键）。
    纯函数，无副作用。

    入口：主 agent 收口时在 check_pack 的 _Checker.run() 尾部调用
        validate_checkins(modules, checker)  （checker._err/_warn 签名与 _emit 一致）
    或自建收集器（暴露 error(module, field, kind, **detail) / warning(...)）。
    返回 None；红拦/黄提示全部经 report 追加（一次给全量）。

    modules: 模块名（无 .json 后缀）→ parsed JSON（含 "checkin" 与可选 "items"/"settings"/"quest"/
             "npc"/"shop"）。checkin 未声明 → 默认放行（细化_3e §2.3）；引用目标模块未声明 →
             跳过对应引用检查。
    now:    可选 UTC+8 秒级时间戳（【工程补白】4：活动表时间窗状态黄提示；缺省 None → 跳过，保确定性）。

    覆盖验收（2b5 §1.8 + 定稿 §八 + 裁决⑦⑧）：
      - TC-01 三表并存（loop/monthly/activity）同文件多表 id 唯一 → 零红拦（多表并存）
      - TC-02 monthly 不配 cycle_days → 不报错（自动=当月天数，运行期 D-01）
      - TC-03 loop 缺 cycle_days → 黄提示「已按默认 7 补全」
      - TC-04 奖励物品引用不存在 → 红拦（R-4）
      - TC-05 补签费/奖励数负数 → 红拦「奖励数量不能是负数哦」
      - TC-06 streak.days=30 而 cycle_days=7 → 黄提示「连签 30 天才给，但周期只有 7 天」；补签开启
        无费用通道 → 黄提示
      - 里程碑阈值严格递增（【工程补白】3）；每日 day 结构（1..N）/重复/超周期
      - makeup：默认关 / enabled/cost/max_per_month 结构 / 货币键注册 / 0=不限
      - 裁决⑧：[签到:*] 三键解析 + 表名限定引用校验；裁决⑦ 补签只计不补发语义归 core/checkin.py 运行
        （模型侧承载配置结构，不落数据）
    """
    if not isinstance(modules, Mapping):
        return
    checkins = modules.get(CHECKIN_MODULE)
    if checkins is None:
        return  # 未声明 checkin 模块：默认放行
    if not isinstance(checkins, list):
        _err(report, CHECKIN_MODULE, "R-5", rule="module_structure", expect="list")
        return

    refs = _Refs()
    refs.item_ids = _id_set(modules, "items")
    refs.currency_ids = _settings_currency_ids(modules)

    seen_ids: Set[str] = set()
    for idx, entry in enumerate(checkins):
        if not isinstance(entry, Mapping):
            _err(report, f"checkin.{idx}", "R-5", rule="checkin_not_object",
                 node_id=f"#{idx}", got=type(entry).__name__, msg="签到表条目需对象")
            continue
        node_id = entry.get("id")
        if not isinstance(node_id, str) or not node_id:
            node_id = f"<checkin.{idx}>"
        _check_checkin(report, entry, idx, node_id, refs, seen_ids, now)

    _check_checkin_references(report, modules, refs)


__all__ = [
    # 常量
    "CHECKIN_MODULE",
    "CHECKIN_TYPES",
    "CHECKIN_TYPE_DEFAULT",
    "CHECKIN_TYPE_NAMES",
    "CHECKIN_PERIOD_KEYS",
    "CHECKIN_CYCLE_DAYS_DEFAULT",
    "CHECKIN_RESET_ON_BREAK_DEFAULT",
    "CHECKIN_MAX_MONTH_DAYS",
    "CHECKIN_NAME_MAX_LEN",
    "CHECKIN_RESET_TIME_KEY",
    "CHECKIN_RESET_TIME_DEFAULT",
    "CHECKIN_DAILY_WRAPPER",
    "CHECKIN_MILESTONE_WRAPPER",
    "CHECKIN_ITEM_CONTAINER_KEY",
    "REWARD_ITEM_KEYS",
    "REWARD_COUNT_KEY",
    "REWARD_BOUND_KEY",
    "REWARD_SCALAR_KEYS",
    "CHECKIN_ENTRY_ALLOWED_KEYS",
    "CHECKIN_MAKEUP_MAX_PER_MONTH_DEFAULT",
    "CHECKIN_MAKEUP_COST_WARN_MAX",
    # [签到:*] 三键（裁决⑧）
    "CHECKIN_KEY_PREFIX",
    "CHECKIN_DEFAULT_TABLE",
    "CHECKIN_KEY_STREAK",
    "CHECKIN_KEY_MONTHLY",
    "CHECKIN_KEY_TODAY",
    "CHECKIN_KEY_FIELDS",
    "CHECKIN_REF_MODULES",
    # Def 类型
    "PeriodDef",
    "RewardEntryDef",
    "RewardsDef",
    "MakeupDef",
    "CheckinDef",
    # 函数
    "parse_checkin_key",
    "parse_checkins",
    "validate_checkins",
]
