"""内容包领域模型 —— M4 批次3·路D1（商店 C1-C6）：ShopDef（14 顶层字段 + 12 条目字段）+ validate_shops 专项校验。

依据：
  - m4_shared_contract §3.2（商店 C1-C6：五类型 normal/npc/reputation/event/blackmarket；stock 0=无限；
    sold_out_once 售出永久下架不随刷新恢复；**库存+个人限购同条目并存（用户裁决⑤）**；个人限购清零以条目
    period 为准；refresh 四模式 daily/weekly/once/none；**不配置 = 永不刷新（用户裁决⑥）**；刷新三件事
    （库存回满/限购清零/黑市重抽）同刻发生；原子防双扣；当前商店机制；/商店 /购买 /出售 + /商店 列表）
  - 细化_2b3_商店引擎契约.md（shop.json 字段级 schema：14 顶层字段 §1.2 / 12 条目字段 §1.4 /
    refresh 四模式×5 key §1.3 / 5 类商店类型 §1.5 / 校验器边界 §1.6 / 购买校验链 §2.2 /
    验收 TC-01~TC-42 + 2026-08-27 审查裁决 P1-1~P1-4：scope 扩展并存（P1-2）/ 限购清零以 period 为准
    （P1-3）/ 默认 refresh=none 永不刷新（P1-4））
  - 商店系统设计定稿.md（顶层字段表 L128-143 / 条目字段表 L168-181 / refresh §七 L278-302 /
    商品范围 §六 L252-274 / 黑市机制 L214-218 / 购买校验链 L338-345 / 校验器 §十一 L408-433 /
    示例 shop.json L437-511 / 旧字段兼容 L183）
  - 2026-08-27 裁决⑤⑥（m4_shared_contract §0.5-6）：**裁决⑤** stock+per_player 同条目并存（scope 只管
    默认侧，L450/L465 型无损表达）；**裁决⑥** 不配置 refresh = 永不刷新（TC-36 一致）

本文件为批次 3·路D1 的**独立模块**（主 agent 收口时并入 content/models.py + validator.py 的
check_pack，同 npc_models 批次 2 收口模式）：
  - 零冲突：不修改 models.py / validator.py / loader.py / __init__.py 既有内容；
    models.ShopDef（如有空壳）在收口时替换为本模块 ShopDef 即可（同 map_models.MapDef 模式）。
  - validate_shops(modules, report) 为纯函数（无副作用），report 鸭子类型（见 _emit 说明），
    主 agent 收口时直接接入 check_pack 的 _Checker 实例或自建收集器。

【工程补白】（契约/定稿未显式定义处，显式标注供审查，不冒充定稿行号）：
  1. 任务派单内联条目字段表（item/price/currency/stock/per_player/per_player_period/limit_pool/
     stock_pool/price_fluctuation/weight/open_condition/sold_out_once）与权威 细化_2b3 §1.4
     12 条目字段表（item/price/currency/scope/stock/refresh/limit/period/reputation_required/
     min_level/discount/sold_out_once）不一致：limit_pool/stock_pool/price_fluctuation/weight/
     open_condition 不在任何权威字段表内（price_fluctuation/open_condition 为**顶层**字段，
     weight 属 NPC dealer 牌池非商店条目）。本实现以权威 12 条目字段表为准；per_player/
     per_player_period 为定稿 L183 旧字段兼容（裁决⑤ L450/L465 型并存），提供只读访问器与兼容解析。
  2. 黑市上架数量 N 来源：定稿 14 顶层字段表无「上架数量」字段，仅编辑器 §十 L393 提「上架数量」滑条
     （L216 字面「按 items 配置数量从池中抽 N 个上架」）。本实现新增可选顶层字段 `listing_count`
     （int ≥0，黑市专用，【工程补白】命名）承接编辑器「上架数量」；N 解析：
     listing_count > 0 → N = listing_count；否则 N = len(items)（对齐 L216 字面口径）；
     两者皆缺省 → N=0（不上架任何商品）+ 黄提示「黑市未配上架数量」。
  3. open_condition 条件结构校验本地镜像 engine/condition_engine 规则（同 npc_models 补白 1 口径：
     content 层仅允许依赖 data，不得反向依赖 engine——content → data 单向铁律，细化_3a §2.2）。
  4. 「同物不同价」（定稿 L427）/「未使用商店」（定稿 L426）黄提示在引用靶模块（items / npc）**已声明**
     时才触发（防未接线内容包全量噪音，同 npc_models 补白 4 口径）。
  5. 声望门槛 5 级制取值 L1陌生/L2熟悉/L3信赖/L4崇敬/L5传说（细化_2c5b REP-04）；level 0=无门槛；
     level >5 或 <0 → 黄提示「声望门槛可能永不可达」（定稿 L420 黄提示族）。
  6. 混合支付总价过高试算（定稿 L428）依赖数值模拟引擎，本模块不实现（仅价格结构/键注册校验）。
  7. 条目级 refresh 仅 global 侧语义（库存回满时间覆盖商店级，定稿 L175）；条目级个人限购清零以条目
     period 独立驱动（P1-3），不与刷新三件事②（旧 per_player 兼容期清零）混淆。
  8. refresh daily/weekly 的 hour 缺省 5（05:00，与 quest_daily/签到同刻对齐）；once 时间窗仅做结构
     校验（start/end 非空字符串 + 规范格式提示），语义判定归 core/shop.py 运行时（A3 dayroll 系）。

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
# 权威枚举（细化_2b3 §1.2/§1.3/§1.4/§1.5 + 定稿 + 裁决⑤⑥）
# =====================================================================================
# 5 类商店类型（定稿 L133/L201-207 / 细化_2b3 §1.5；type 只影响入口/可见性/刷新默认值，购买引擎同一套）
SHOP_TYPES: Tuple[str, ...] = ("normal", "npc", "reputation", "event", "blackmarket")
SHOP_TYPE_DEFAULT: str = "normal"  # 细化_2b3 §1.2#4：type 选填默认 normal
SHOP_TYPE_NAMES: Dict[str, str] = {  # 定稿 L201-207 中文对照（供提示/编辑器）
    "normal": "普通商店",
    "npc": "NPC 商店",
    "reputation": "声望商店",
    "event": "活动商店",
    "blackmarket": "黑市",
}

# refresh 四模式（定稿 L281-285 / 细化_2b3 §1.3；裁决⑥：缺省 none=永不刷新）
REFRESH_MODES: Tuple[str, ...] = ("daily", "weekly", "once", "none")
REFRESH_MODE_DEFAULT: str = "none"  # 裁决⑥ / P1-4：不配置 refresh = 永不刷新（TC-36 一致）
REFRESH_HOUR_DEFAULT: int = 5  # daily 缺省 05:00（与 quest_daily/签到同刻对齐，细化_2b3 D-07 口径）
REFRESH_WEEKDAY_DEFAULT: int = 1  # weekly 缺省周一 05:00（定稿 L283 示例 weekday:1）
REFRESH_ONCE_FMT: str = "%Y-%m-%d %H:%M"  # once 时间窗规范格式（定稿 L284 示例）

# 商品范围（定稿 L173 / 细化_2b3 §1.4#4；用户拍板两分制）
SCOPES: Tuple[str, ...] = ("global", "personal")
SCOPE_DEFAULT: str = "global"

# 限购周期（定稿 L177 / 细化_2b3 §1.4#8；裁决 P1-3：限购清零以条目 period 独立驱动）
LIMIT_PERIODS: Tuple[str, ...] = ("day", "week", "month")
LIMIT_PERIOD_DEFAULT: str = "day"

# 声望门槛 5 级制（细化_2c5b REP-04：L1陌生0/L2熟悉100/L3信赖300/L4崇敬600/L5传说1000；
# 定稿 L136 {level:N}；level 0=无门槛默认）
REPUTATION_LEVELS: Tuple[int, ...] = (1, 2, 3, 4, 5)
REPUTATION_LEVEL_NAMES: Dict[int, str] = {1: "陌生", 2: "熟悉", 3: "信赖", 4: "崇敬", 5: "传说"}

# 数值域（定稿 L141/L180/L44/L344 / 细化_2b3 §1.6）
PRICE_FLUCTUATION_MAX: int = 50  # 黑市浮动率 0~50（定稿 L141）
PRICE_FLUCTUATION_WARN: int = 30  # >30% 黄提示（定稿 L424「价格波动较大，确认？」）
MAX_BUY_QTY_DEFAULT: int = 99  # 数量上限默认 ≤99，可配（定稿 L44/L344，提示不拦截 D-05）
DISCOUNT_MAX: int = 100  # discount 0~100 减价百分比（定稿 L180）
STOCK_SMALL_MAX: int = 4  # 全服库存过小（stock 1~4）→ 黄提示「抢购玩法确认？」（定稿 L422）
MIN_STOCK_GLOBAL: int = 1

# 旧字段兼容（定稿 L183 / D-08 / 裁决⑤：旧 stock/per_player/per_player_period 自动映射）
LEGACY_PER_PLAYER: str = "per_player"  # 旧 personal 限购 → limit 语义
LEGACY_PER_PLAYER_PERIOD: str = "per_player_period"  # 旧 period → period 语义

# 【工程补白】2：黑市上架数量 N（编辑器「上架数量」落点，不在定稿 14 顶层字段表内）
BLACKMARKET_LISTING_FIELD: str = "listing_count"
BLACKMARKET_LISTING_DEFAULT: int = 0  # 0=按 items 数量（L216 字面口径）

# 条件引擎镜像常量（【工程补白】3：本地镜像 engine/condition_engine，不 import engine）
COND_OPERATORS: Tuple[str, ...] = ("gt", "ge", "lt", "le", "eq", "ne", "between", "is", "not")
COND_OP_SYMBOLS: Dict[str, str] = {">=": "ge", ">": "gt", "<=": "le", "<": "lt", "=": "eq", "!=": "ne"}
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
# Def 类型（风格对齐 NPCDef/MapDef：BaseDef + 字段访问器；子表 RefreshDef/ShopItemDef）
# =====================================================================================


@dataclass(frozen=True)
class RefreshDef:
    """refresh 刷新子对象（细化_2b3 §1.3：四模式 daily/weekly/once/none × 5 key）。

    mode/hour/weekday/start/end。缺省 mode=none（裁决⑥：不配置 refresh = 永不刷新）；
    daily 缺省 hour=5（05:00）；weekly 缺省 weekday=1（周一）。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "RefreshDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def mode(self) -> Optional[str]:
        v = self.raw.get("mode")
        return v if isinstance(v, str) else None

    @property
    def hour(self) -> Optional[int]:
        v = self.raw.get("hour")
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def weekday(self) -> Optional[int]:
        v = self.raw.get("weekday")
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def start(self) -> Optional[str]:
        v = self.raw.get("start")
        return v if isinstance(v, str) else None

    @property
    def end(self) -> Optional[str]:
        v = self.raw.get("end")
        return v if isinstance(v, str) else None


@dataclass(frozen=True)
class ShopItemDef:
    """items[] / pool[] 商品条目（细化_2b3 §1.4：12 条目字段）。

    12 字段（权威口径）：item/price/currency/scope/stock/refresh/limit/period/
    reputation_required/min_level/discount/sold_out_once。
    旧字段兼容（定稿 L183 / 裁决⑤）：per_player → 个人限购（limit 语义）、
    per_player_period → 限购周期（period 语义），与 stock 可**同条目并存**（L450/L465 型无损表达）。
    scope 只管默认侧：条目同时配 stock + per_player 时两制并存，scope 不再排他。

    访问器均为防御性读取（类型不符 → None/空），缺省兜底语义由校验器/引擎侧负责（本层不伪造默认值）。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "ShopItemDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    # ---- 数值/字符串/映射辅助 ----
    def _int(self, key: str) -> Optional[int]:
        v = self.raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    # ---- 12 条目字段（细化_2b3 §1.4）----
    @property
    def item(self) -> Optional[str]:
        """items.json 物品引用（1，必填；显示按名字、存储按 ID）。"""
        return self._str("item")

    @property
    def price(self) -> object:
        """单价覆盖（2）：int=覆盖价 / Mapping=混合支付 {coins:50,gems:5}；缺省=items 基准价。"""
        return self.raw.get("price")

    @property
    def currency(self) -> Optional[str]:
        """条目级货币覆盖（3）：settings 货币键；缺省=商店 currency。"""
        return self._str("currency")

    @property
    def scope(self) -> Optional[str]:
        """商品范围（4）：global（默认）/personal；缺省兜底 global 见 effective_scope。"""
        return self._str("scope")

    @property
    def stock(self) -> Optional[int]:
        """全服库存（5）：≥0；0=无限；仅 global 侧。"""
        return self._int("stock")

    @property
    def refresh(self) -> RefreshDef:
        """条目级库存刷新（6）：仅 global 侧，覆盖商店级 refresh。"""
        return RefreshDef.from_entry(self.raw.get("refresh"))

    @property
    def limit(self) -> Optional[int]:
        """个人每周期限购（7）：≥0；0=不限；仅 personal 侧。"""
        return self._int("limit")

    @property
    def period(self) -> Optional[str]:
        """限购周期（8）：day（默认）/week/month；裁决 P1-3 以此驱动限购清零。"""
        return self._str("period")

    @property
    def reputation_required(self) -> Mapping[str, object]:
        """条目级声望门槛（9）：{level:N} 覆盖且更严于商店级。"""
        return self._mapping("reputation_required")

    @property
    def min_level(self) -> Optional[int]:
        """条目级等级门槛（10）：0=不限。"""
        return self._int("min_level")

    @property
    def discount(self) -> Optional[int]:
        """折扣（11）：0~100 减价百分比；标记时原价划线。"""
        return self._int("discount")

    @property
    def sold_out_once(self) -> bool:
        """一次性售罄（12）：仅 global；售出后永久下架，刷新不恢复。"""
        return self.raw.get("sold_out_once") is True

    # ---- 旧字段兼容访问器（定稿 L183 / D-08 / 裁决⑤）----
    @property
    def per_player(self) -> Optional[int]:
        """旧 personal 限购字段（兼容读，语义=limit；与 stock 同条目并存，L450/L465 型）。"""
        return self._int(LEGACY_PER_PLAYER)

    @property
    def per_player_period(self) -> Optional[str]:
        """旧 per_player_period 字段（兼容读，语义=period）。"""
        return self._str(LEGACY_PER_PLAYER_PERIOD)

    # ---- 派生/生效侧（裁决⑤：scope 只管默认侧）----
    @property
    def effective_scope(self) -> str:
        """生效 scope：显式 scope 优先；否则旧 per_player 存在 → personal；否则默认 global。

        裁决⑤：scope 只管默认侧——条目同时声明 stock 与 per_player 时两制并存，
        effective_scope 只表达「未显式声明侧的默认归属」。
        """
        if self.scope is not None:
            return self.scope
        if self.raw.get(LEGACY_PER_PLAYER) is not None:
            return "personal"
        return SCOPE_DEFAULT

    @property
    def has_global_side(self) -> bool:
        """global 库存侧是否生效：显式 stock（新键或旧键同键）或生效 scope=global（缺省=无限库存）。

        裁决⑤：scope 只管默认侧——stock/per_player 显式声明即激活对应侧，scope 不再排他。
        """
        if self.stock is not None:
            return True
        return self.effective_scope == "global"

    @property
    def has_personal_side(self) -> bool:
        """personal 限购侧是否生效：显式 limit/per_player 或 scope=personal。"""
        if self.limit is not None or self.raw.get(LEGACY_PER_PLAYER) is not None:
            return True
        return self.scope == "personal"

    @property
    def uses_legacy_fields(self) -> bool:
        """是否使用了旧 per_player/per_player_period 字段（兼容读，黄提示迁移用）。"""
        return LEGACY_PER_PLAYER in self.raw or LEGACY_PER_PLAYER_PERIOD in self.raw


@dataclass(frozen=True)
class ShopDef(BaseDef):
    """shop.json 条目（细化_2b3 §1.2：14 顶层字段 + items/pool/refresh 子结构）。

    顶层 14 字段：id/name/icon/type/currency/level_required/reputation_required/open_condition/
    refresh/items/pool/price_fluctuation/visible/desc。
    注：id/name 由 BaseDef 承载（from_entry 冗余镜像 raw），其余字段访问器见下。
    【工程补白】2：另含可选 listing_count（黑市上架数量，不在定稿 14 字段表内）。
    """

    # ---- 数值/字符串/映射/列表辅助（与 NPCDef 同风格）----
    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _int(self, key: str) -> Optional[int]:
        v = self.raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    def _entries(self, key: str) -> Tuple[ShopItemDef, ...]:
        v = self.raw.get(key)
        return tuple(ShopItemDef.from_entry(e) for e in v if isinstance(e, Mapping)) \
            if isinstance(v, list) else ()

    # ---- 顶层字段访问器（F03-F14；F01/F02 由 BaseDef）----
    @property
    def icon(self) -> Optional[str]:
        """列表/卡片图标（1 个 emoji，细化_2b3 §1.2#3）。"""
        return self._str("icon")

    @property
    def type(self) -> Optional[str]:
        """5 类商店类型：normal/npc/reputation/event/blackmarket（§1.2#4，缺省 normal）。"""
        return self._str("type")

    @property
    def currency(self) -> Optional[str]:
        """整店默认货币（settings 货币键；缺省 settings 第一货币，§1.2#5）。"""
        return self._str("currency")

    @property
    def level_required(self) -> Optional[int]:
        """等级门槛（商店级，0=不限，§1.2#6）。"""
        return self._int("level_required")

    @property
    def reputation_required(self) -> Mapping[str, object]:
        """声望门槛（商店级 {level:N} 5 级制，§1.2#7）。"""
        return self._mapping("reputation_required")

    @property
    def open_condition(self) -> object:
        """开放条件（统一条件引擎 {var,op,value}；不满足 →「这家店还没开门」，§1.2#8）。"""
        return self.raw.get("open_condition")

    @property
    def refresh(self) -> RefreshDef:
        """刷新配置（四模式；缺省 mode=none 永不刷新 = 裁决⑥，§1.2#9/§1.3）。"""
        return RefreshDef.from_entry(self.raw.get("refresh"))

    @property
    def items(self) -> Tuple[ShopItemDef, ...]:
        """商品条目列表（§1.2#10，必填）。"""
        return self._entries("items")

    @property
    def pool(self) -> Tuple[ShopItemDef, ...]:
        """黑市候选商品池（§1.2#11，黑市专用；条目格式同 items）。"""
        return self._entries("pool")

    @property
    def price_fluctuation(self) -> Optional[int]:
        """黑市价格随机浮动 ±%（0=固定价，0~50；§1.2#12）。"""
        return self._int("price_fluctuation")

    @property
    def visible(self) -> bool:
        """是否可见（false=隐藏商店条件解锁；§1.2#13，缺省 true）。"""
        v = self.raw.get("visible")
        return v if isinstance(v, bool) else True

    @property
    def desc(self) -> Optional[str]:
        """列表页副标题（§1.2#14）。"""
        return self._str("desc")

    # ---- 【工程补白】2：黑市上架数量 N ----
    @property
    def listing_count(self) -> Optional[int]:
        """黑市上架数量（【工程补白】命名，承接编辑器「上架数量」；≥0，0=按 items 数量）。"""
        return self._int(BLACKMARKET_LISTING_FIELD)

    @property
    def blackmarket_listing_n(self) -> int:
        """黑市每次刷新上架数量 N 的解析结果：listing_count>0 → 该值；否则 len(items)
        （定稿 L216「按 items 配置数量从池中抽 N 个上架」字面口径；两者皆缺省 → 0）。"""
        if self.listing_count is not None and self.listing_count > 0:
            return self.listing_count
        return len(self.items)


def parse_shops(modules: Mapping[str, object]) -> Tuple[ShopDef, ...]:
    """从 modules 提取 shop 模块 → ShopDef 元组（非 list / 非对象条目跳过；供运行期与测试复用）。"""
    shops = modules.get("shop") if isinstance(modules, Mapping) else None
    if not isinstance(shops, list):
        return ()
    return tuple(cast(ShopDef, ShopDef.from_entry(e)) for e in shops if isinstance(e, Mapping))


# =====================================================================================
# validate_shops：shop 模块专项校验（细化_2b3 §1.6 + 定稿 §十一 + 裁决⑤⑥；供主 agent 收口接 check_pack）
# =====================================================================================
# 规则清单（红拦=errors / 黄提示=warnings）：
#   硬拦 R-1：id 必填非空 string 且池内唯一；name 必填且禁空格；items 缺失/非数组；条目非对象
#   硬拦 R-2：type ∉ 5 类（缺省 normal 不拦）；scope ∉ global/personal；period ∉ day/week/month；
#             refresh.mode ∉ 四枚举；refresh 数值非法（hour/weekday）；sold_out_once/visible 非 bool；
#             listing_count 负数
#   硬拦 R-4：item 引用不存在（items 模块存在时）；currency/price 对象键 未注册（settings 货币注册表）；
#             refresh once 缺 start/end 时间窗
#   硬拦 R-5：price 负数/非数字/bool/空对象（混合支付缺货币键）；stock/limit/discount/per_player/
#             min_level/level_required 负数或非整数；reputation_required.level 非法；price_fluctuation
#             超 0~50；open_condition 结构硬规则（CND 分流）
#   黄提示 Y-1：空商店（items 空）→「这家店空空的？」
#   黄提示 Y-2：全服库存过小（stock 1~4）→「抢购玩法确认？」
#   黄提示 Y-3：price=0 常驻商品 →「免费商品确认？」
#   黄提示 Y-4：黑市浮动 >30% →「价格波动较大，确认？」；黑市 pool 空 / 未配上架数量
#   黄提示 Y-5：声望门槛 5 级制外（<0 或 >5）→「可能永不可达」
#   黄提示 Y-6：旧 per_player/per_player_period 使用 →「建议迁移」（裁决⑤兼容 + 迁移提示）
#   黄提示 Y-7：同物不同价（items 模块存在时，多条目同 item 不同 price）
#   黄提示 Y-8：未使用商店（npc 模块已声明 shop_refs 时，非 normal 店未被任何 NPC 引用）


def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    """收集器鸭子类型适配：优先 report.<method>，其次 validator._Checker 的 _<method>。"""
    _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
    fn = getattr(report, method, None)
    if not callable(fn):
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", "shop", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", "shop", field, kind, **detail)


# -------------------------------------------------------------------------------------
# 条件引擎本地镜像（【工程补白】3：content→data 单向铁律，不 import engine）
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
    递归 any/all/not 嵌套（NPC 4.4 / 2b4 D-02）。求值失败默认 False（D-03 安全失败）由引擎侧保证。
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


def _npc_shop_refs(modules: Mapping[str, object]) -> Optional[Set[str]]:
    """npc 模块声明的全部 shop_refs（顶层 + interactions[].shop_refs）→ 引用集。
    npc 模块缺失/非 list 或**无任何 shop_refs** → None（【工程补白】4：未接线不触发「未使用商店」噪音）。"""
    npcs = modules.get("npc")
    if not isinstance(npcs, list):
        return None
    refs: Set[str] = set()
    any_refs = False
    for n in npcs:
        if not isinstance(n, Mapping):
            continue
        top = n.get("shop_refs")
        if isinstance(top, list):
            for r in top:
                if isinstance(r, str) and r:
                    any_refs = True
                    refs.add(r)
        inter = n.get("interactions")
        if isinstance(inter, list):
            for it in inter:
                if not isinstance(it, Mapping):
                    continue
                sr = it.get("shop_refs")
                if isinstance(sr, list):
                    for r in sr:
                        if isinstance(r, str) and r:
                            any_refs = True
                            refs.add(r)
    return refs if any_refs else None


# -------------------------------------------------------------------------------------
# 引用靶构建
# -------------------------------------------------------------------------------------
class _Refs:
    """shop 模块跨模块引用校验靶（None = 目标模块未声明/无合法 id → 跳过对应引用检查）。"""

    __slots__ = ("item_ids", "currency_ids", "npc_shop_refs")

    def __init__(self) -> None:
        self.item_ids: Optional[Set[str]] = None
        self.currency_ids: Tuple[str, ...] = ()
        self.npc_shop_refs: Optional[Set[str]] = None


# -------------------------------------------------------------------------------------
# refresh 子对象校验（细化_2b3 §1.3 + 定稿 L281-285/L417；裁决⑥ 缺省 none 不拦）
# -------------------------------------------------------------------------------------
def _check_refresh(report: object, refresh: object, base: str, node_id: str,
                   *, shop_mode_default: bool) -> None:
    """refresh 结构校验。

    shop_mode_default=True：商店级 refresh，缺省（未配置）= mode none（裁决⑥，不拦）。
    条目级 refresh（shop_mode_default=False）：仅 global 侧语义，缺省=跟随商店级（不拦）。
    红拦：mode 非四枚举；daily hour 非法（非 0-23 整数）；weekly weekday 非法（非 1-7 整数）；
          once 缺 start/end 或非字符串。
    """
    if refresh is None:
        return  # 缺省 mode=none（裁决⑥）：配置才刷新，不配置永不刷新
    if not isinstance(refresh, Mapping):
        _err(report, base, "R-5", rule="shop_refresh_not_object",
             node_id=node_id, got=type(refresh).__name__,
             msg="refresh 要填对象 {mode,...}")
        return
    mode = refresh.get("mode")
    if mode is None:
        _err(report, f"{base}.mode", "R-1", rule="shop_refresh_mode_required",
             node_id=node_id,
             msg="refresh 缺 mode（四模式：daily/weekly/once/none；不配置=永不刷新）")
        return
    if not isinstance(mode, str) or mode not in REFRESH_MODES:
        _err(report, f"{base}.mode", "R-1", rule="shop_refresh_mode_invalid",
             node_id=node_id, mode=mode, allowed=list(REFRESH_MODES),
             msg="refresh.mode %r 不认识（四模式：%s）" % (mode, "/".join(REFRESH_MODES)))
        return
    if mode == "daily":
        hour = refresh.get("hour")
        if hour is not None and (not isinstance(hour, int) or isinstance(hour, bool)
                                 or not 0 <= hour <= 23):
            _err(report, f"{base}.hour", "R-2", rule="shop_refresh_hour_invalid",
                 node_id=node_id, hour=hour, msg="daily hour 需 0-23 整数（缺省 5=05:00）")
    elif mode == "weekly":
        weekday = refresh.get("weekday")
        if weekday is not None and (not isinstance(weekday, int) or isinstance(weekday, bool)
                                    or not 1 <= weekday <= 7):
            _err(report, f"{base}.weekday", "R-2", rule="shop_refresh_weekday_invalid",
                 node_id=node_id, weekday=weekday,
                 msg="weekly weekday 需 1-7 整数（1=周一…7=周日，缺省 1）")
        hour = refresh.get("hour")
        if hour is not None and (not isinstance(hour, int) or isinstance(hour, bool)
                                 or not 0 <= hour <= 23):
            _err(report, f"{base}.hour", "R-2", rule="shop_refresh_hour_invalid",
                 node_id=node_id, hour=hour, msg="weekly hour 需 0-23 整数（缺省 5=05:00）")
    elif mode == "once":
        start = refresh.get("start")
        end = refresh.get("end")
        if not isinstance(start, str) or not start:
            _err(report, f"{base}.start", "R-4", rule="shop_refresh_once_start_missing",
                 node_id=node_id, msg="once 模式需 start 时间窗（如 \"2026-09-01 00:00\"）")
        if not isinstance(end, str) or not end:
            _err(report, f"{base}.end", "R-4", rule="shop_refresh_once_end_missing",
                 node_id=node_id, msg="once 模式需 end 时间窗（如 \"2026-09-07 23:59\"）")
        # 【工程补白】8：once 时间窗仅结构校验，格式不符 → 黄提示（语义判定归 core/shop.py 运行时）
        for key in ("start", "end"):
            v = refresh.get(key)
            if isinstance(v, str) and v:
                try:
                    from datetime import datetime
                    datetime.strptime(v, REFRESH_ONCE_FMT)
                except ValueError:
                    _warn(report, f"{base}.{key}", "Y-8", rule="shop_refresh_once_format",
                          node_id=node_id, value=v, fmt=REFRESH_ONCE_FMT,
                          msg="once 时间窗格式建议 %s（当前：%r）" % (REFRESH_ONCE_FMT, v))


# -------------------------------------------------------------------------------------
# 声望门槛校验（细化_2b3 §1.2#7/#9 / 细化_2c5b REP-04：5 级制；level 0=无门槛）
# -------------------------------------------------------------------------------------
def _check_reputation(report: object, rep: object, base: str, node_id: str) -> None:
    """reputation_required 结构校验：对象 + level 非负整数；5 级制外 → 黄提示（可能永不可达）。"""
    if rep is None:
        return
    if not isinstance(rep, Mapping):
        _err(report, base, "R-5", rule="shop_reputation_not_object",
             node_id=node_id, got=type(rep).__name__,
             msg="reputation_required 要填对象 {level:N}（5 级制：陌生/熟悉/信赖/崇敬/传说）")
        return
    level = rep.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or level < 0:
        _err(report, f"{base}.level", "R-2", rule="shop_reputation_level_invalid",
             node_id=node_id, level=level, msg="reputation_required.level 需 ≥0 整数（0=无门槛）")
        return
    if level > REPUTATION_LEVELS[-1]:
        _warn(report, f"{base}.level", "Y-5", rule="shop_reputation_unreachable",
              node_id=node_id, level=level, max_level=REPUTATION_LEVELS[-1],
              msg="声望门槛 level=%s 超出 5 级制（1~5：%s），可能永不可达？确认"
                  % (level, "/".join(str(x) for x in REPUTATION_LEVELS)))


# -------------------------------------------------------------------------------------
# 商品条目校验（细化_2b3 §1.4/§1.6 + 定稿 L411-427 + 裁决⑤）
# -------------------------------------------------------------------------------------
def _price_invalid(price: object) -> Optional[str]:
    """价格校验：返回非法原因；None=合法（int ≥0 或 Mapping 混合支付）。

    硬拦规则（定稿 L413）：负数 / 非数字 / 结构错误（对象缺货币键）。
    Mapping 内每个键值须 ≥0 整数；键注册判定归 _check_entry（需 currency_ids）。
    """
    if isinstance(price, bool):
        return "bool 不是合法价格"
    if isinstance(price, int):
        return None if price >= 0 else "负数"
    if isinstance(price, Mapping):
        if not price:
            return "混合支付对象缺货币键（空对象）"
        for k, v in price.items():
            if isinstance(v, bool) or not isinstance(v, int):
                return "混合支付键 %r 的值非整数" % (k,)
            if v < 0:
                return "混合支付键 %r 的值为负数" % (k,)
        return None
    return "非整数/非对象"


def _check_entry(
    report: object,
    entry: Mapping[str, object],
    base: str,
    node_id: str,
    refs: _Refs,
) -> None:
    """单条目校验（items[] / pool[] 通用，12 条目字段 + 旧字段兼容 + 裁决⑤）。"""
    item = entry.get("item")
    if not isinstance(item, str) or not item:
        _err(report, f"{base}.item", "R-5", rule="shop_entry_item_required",
             node_id=node_id, msg="条目 item 必填（items.json 物品引用）")
    elif refs.item_ids is not None and item not in refs.item_ids:
        _err(report, f"{base}.item", "R-4", rule="shop_item_ref_missing",
             node_id=node_id, item=item, msg="商品引用 %r 在 items.json 中不存在" % (item,))

    # price（int/obj 混合支付；缺省=items 基准价由引擎侧兜底）
    if "price" in entry:
        why = _price_invalid(entry["price"])
        if why is not None:
            _err(report, f"{base}.price", "R-5", rule="shop_price_invalid",
                 node_id=node_id, price=entry["price"], why=why,
                 msg="price 非法：%s（需 ≥0 整数或 {货币键:数量} 混合支付对象）" % (why,))
        elif isinstance(entry["price"], Mapping):
            for k in entry["price"]:
                if k not in refs.currency_ids:
                    _err(report, f"{base}.price.{k}", "R-4",
                         rule="shop_price_currency_unregistered",
                         node_id=node_id, currency=k, registered=list(refs.currency_ids),
                         msg="混合支付货币键 %r 未注册" % (k,))
        if isinstance(entry["price"], int) and entry["price"] == 0:
            _warn(report, f"{base}.price", "Y-3", rule="shop_price_zero",
                  node_id=node_id, msg="price=0 免费商品确认？（定稿 L423）")

    # currency 条目级货币覆盖（缺省=商店 currency）
    currency = entry.get("currency")
    if currency is not None and (not isinstance(currency, str) or currency not in refs.currency_ids):
        _err(report, f"{base}.currency", "R-4", rule="shop_currency_unregistered",
             node_id=node_id, currency=currency, registered=list(refs.currency_ids),
             msg="条目货币 %r 未注册（settings.currencies 键空间）" % (currency,))

    # scope 枚举
    scope = entry.get("scope")
    if scope is not None and (not isinstance(scope, str) or scope not in SCOPES):
        _err(report, f"{base}.scope", "R-1", rule="shop_entry_scope_invalid",
             node_id=node_id, scope=scope, allowed=list(SCOPES),
             msg="scope %r 不认识（global/personal，缺省 global）" % (scope,))

    # stock / limit / discount / per_player / per_player_period（裁决⑤：可同条目并存）
    for key, rule in (("stock", "shop_stock_invalid"), ("limit", "shop_limit_invalid"),
                      ("discount", "shop_discount_invalid"), (LEGACY_PER_PLAYER, "shop_per_player_invalid")):
        if key in entry:
            v = entry[key]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                _err(report, f"{base}.{key}", "R-2", rule=rule, node_id=node_id, value=v,
                     msg="%s 需 ≥0 整数（0=无限/不限）" % (key,))
            elif key == "discount" and v > DISCOUNT_MAX:
                _err(report, f"{base}.discount", "R-2", rule="shop_discount_invalid",
                     node_id=node_id, value=v, msg="discount 需 0~100 减价百分比")
            elif key == "stock" and isinstance(v, int) and 0 < v <= STOCK_SMALL_MAX:
                _warn(report, f"{base}.stock", "Y-2", rule="shop_stock_small",
                      node_id=node_id, stock=v, msg="全服库存 stock=%s 过小（1~4）抢购玩法确认？" % (v,))

    # period 三值（条目级限购周期；裁决 P1-3：限购清零以此为准）
    for key in ("period", LEGACY_PER_PLAYER_PERIOD):
        if key in entry:
            v = entry[key]
            if not isinstance(v, str) or v not in LIMIT_PERIODS:
                _err(report, f"{base}.{key}", "R-1", rule="shop_entry_period_invalid",
                     node_id=node_id, period=v, allowed=list(LIMIT_PERIODS),
                     msg="%s %r 不认识（三值：%s）" % (key, v, "/".join(LIMIT_PERIODS)))

    # 条目级 refresh（仅 global 侧库存回满时间覆盖；结构同商店级）
    if "refresh" in entry:
        _check_refresh(report, entry["refresh"], f"{base}.refresh", node_id,
                       shop_mode_default=False)

    # 条目级声望门槛（覆盖且更严于商店级）
    if "reputation_required" in entry:
        _check_reputation(report, entry["reputation_required"], f"{base}.reputation_required",
                          node_id)

    # min_level 条目级等级门槛
    if "min_level" in entry:
        v = entry["min_level"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            _err(report, f"{base}.min_level", "R-2", rule="shop_entry_min_level_invalid",
                 node_id=node_id, value=v, msg="min_level 需 ≥0 整数（0=不限）")

    # sold_out_once 一次性售罄（bool）
    if "sold_out_once" in entry and not isinstance(entry["sold_out_once"], bool):
        _err(report, f"{base}.sold_out_once", "R-1", rule="shop_entry_sold_out_once_invalid",
             node_id=node_id, value=entry["sold_out_once"], msg="sold_out_once 需 bool")

    # 旧字段兼容黄提示（裁决⑤兼容 + 迁移建议，同 npc_models 旧 strategy 迁移提示模式）
    if LEGACY_PER_PLAYER in entry or LEGACY_PER_PLAYER_PERIOD in entry:
        _warn(report, base, "Y-6", rule="shop_legacy_fields",
              node_id=node_id, fields=[k for k in (LEGACY_PER_PLAYER, LEGACY_PER_PLAYER_PERIOD)
                                       if k in entry],
              msg="旧字段 per_player/per_player_period 已自动映射（stock→scope=global、"
                  "per_player→scope=personal），建议迁移为 scope/limit/period 新字段（定稿 L183）")


# -------------------------------------------------------------------------------------
# 单商店校验
# -------------------------------------------------------------------------------------
def _check_shop(report: object, shop: Mapping[str, object], node_id: str, refs: _Refs,
                seen_ids: Set[str]) -> None:
    """单商店校验：14 顶层字段 + items/pool/refresh/open_condition + 黑市专项。"""
    sid = shop.get("id")
    if not isinstance(sid, str) or not sid:
        _err(report, "shop.id", "R-5", rule="shop_id_required", node_id=node_id,
             msg="商店 id 必填（全局唯一，被 npc.json shop_refs 引用）")
    elif sid in seen_ids:
        _err(report, "shop.id", "R-5", rule="shop_id_duplicate", node_id=node_id, id=sid,
             msg="商店 id %r 重复（全局唯一）" % (sid,))
    else:
        seen_ids.add(sid)

    name = shop.get("name")
    if not isinstance(name, str) or not name:
        _err(report, "shop.name", "R-5", rule="shop_name_required", node_id=node_id,
             msg="商店 name 必填（玩家可见店名）")
    elif " " in name:
        _err(report, "shop.name", "R-5", rule="shop_name_space_forbidden", node_id=node_id,
             name=name, msg="商店名禁空格（允许 ·/Ⅱ）")

    # type（先解析供 items 空/黑市例外与黑市专项使用；枚举红拦见下）
    stype = shop.get("type")
    if not isinstance(stype, str):
        stype = None

    # items 必填数组（定稿 L416：id/name/items 缺失）
    items = shop.get("items")
    if items is None:
        _err(report, "shop.items", "R-5", rule="shop_items_required", node_id=node_id,
             msg="商店 items 必填（商品条目数组，可为 []）")
    elif not isinstance(items, list):
        _err(report, "shop.items", "R-5", rule="shop_items_not_list", node_id=node_id,
             got=type(items).__name__, msg="商店 items 需数组")
    elif not items:
        # Y-1 空商店：黑市例外——黑市货架由 pool 刷新驱动，items 为空是定稿 L507 示例的正典形态
        # （pool 为空另有专用黄提示 shop_blackmarket_pool_empty）
        if stype != "blackmarket":
            _warn(report, "shop.items", "Y-1", rule="shop_empty", node_id=node_id,
                  msg="这家店空空的？确认（定稿 L421）")

    # type 枚举（缺省 normal 不拦）
    if stype is not None and stype not in SHOP_TYPES:
        _err(report, "shop.type", "R-1", rule="shop_type_invalid", node_id=node_id,
             type=stype, allowed=list(SHOP_TYPES),
             msg="商店 type %r 不认识（五类：%s，缺省 normal）"
                 % (stype, "/".join(SHOP_TYPES)))

    # currency 商店级货币（缺省 settings 第一货币）
    currency = shop.get("currency")
    if currency is not None and (not isinstance(currency, str) or currency not in refs.currency_ids):
        _err(report, "shop.currency", "R-4", rule="shop_currency_unregistered", node_id=node_id,
             currency=currency, registered=list(refs.currency_ids),
             msg="商店货币 %r 未注册（settings.currencies 键空间）" % (currency,))

    # 等级门槛
    for key, rule in (("level_required", "shop_level_required_invalid"),):
        if key in shop:
            v = shop[key]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                _err(report, f"shop.{key}", "R-2", rule=rule, node_id=node_id, value=v,
                     msg="%s 需 ≥0 整数（0=不限）" % (key,))

    # 声望门槛（商店级）
    if "reputation_required" in shop:
        _check_reputation(report, shop["reputation_required"], "shop.reputation_required", node_id)

    # 开放条件（统一条件引擎；不满足 →「这家店还没开门」）
    if "open_condition" in shop and shop["open_condition"] is not None:
        _check_condition(report, shop["open_condition"], "shop.open_condition", node_id)

    # refresh（裁决⑥：缺省 none 永不刷新）
    _check_refresh(report, shop.get("refresh"), "shop.refresh", node_id, shop_mode_default=True)

    # visible / desc
    if "visible" in shop and not isinstance(shop["visible"], bool):
        _err(report, "shop.visible", "R-1", rule="shop_visible_invalid", node_id=node_id,
             value=shop["visible"], msg="visible 需 bool")

    # price_fluctuation（黑市浮动率 0~50；>30% 黄提示）
    if "price_fluctuation" in shop:
        v = shop["price_fluctuation"]
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= PRICE_FLUCTUATION_MAX:
            _err(report, "shop.price_fluctuation", "R-2", rule="shop_price_fluctuation_invalid",
                 node_id=node_id, value=v, max=PRICE_FLUCTUATION_MAX,
                 msg="price_fluctuation 需 0~%s 整数（0=固定价）" % (PRICE_FLUCTUATION_MAX,))
        elif v > PRICE_FLUCTUATION_WARN:
            _warn(report, "shop.price_fluctuation", "Y-4", rule="shop_fluctuation_high",
                  node_id=node_id, value=v, warn_above=PRICE_FLUCTUATION_WARN,
                  msg="黑市浮动率 %s%% >30%%，价格波动较大，确认？（定稿 L424）" % (v,))

    # 【工程补白】2：黑市上架数量 listing_count
    if BLACKMARKET_LISTING_FIELD in shop:
        v = shop[BLACKMARKET_LISTING_FIELD]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            _err(report, f"shop.{BLACKMARKET_LISTING_FIELD}", "R-2",
                 rule="shop_listing_count_invalid", node_id=node_id, value=v,
                 msg="%s 需 ≥0 整数（0=按 items 数量；【工程补白】黑市上架数量）"
                     % (BLACKMARKET_LISTING_FIELD,))

    # items[] / pool[] 条目（同一 ShopItemDef 12 字段；pool 黑市专用）
    if isinstance(items, list):
        for i, e in enumerate(items):
            if not isinstance(e, Mapping):
                _err(report, f"shop.items.{i}", "R-5", rule="shop_entry_not_object",
                     node_id=node_id, got=type(e).__name__, msg="商品条目需对象")
                continue
            _check_entry(report, e, f"shop.items.{i}", node_id, refs)
    pool = shop.get("pool")
    if pool is not None and not isinstance(pool, list):
        _err(report, "shop.pool", "R-5", rule="shop_pool_not_list", node_id=node_id,
             got=type(pool).__name__, msg="pool 需数组（黑市专用候选池）")
    elif isinstance(pool, list):
        for i, e in enumerate(pool):
            if not isinstance(e, Mapping):
                _err(report, f"shop.pool.{i}", "R-5", rule="shop_pool_entry_not_object",
                     node_id=node_id, got=type(e).__name__, msg="池条目需对象")
                continue
            _check_entry(report, e, f"shop.pool.{i}", node_id, refs)

    # 黑市专项黄提示（定稿 §四 黑市机制 / L216 上架数量）
    if stype == "blackmarket":
        if not pool:
            _warn(report, "shop.pool", "Y-4", rule="shop_blackmarket_pool_empty",
                  node_id=node_id, msg="黑市商品池 pool 为空，无候选可抽？（定稿 L140/L216）")
        # 上架数量 N 解析（【工程补白】2）：listing_count 与 items 皆缺省 → N=0 黄提示
        listing = shop.get(BLACKMARKET_LISTING_FIELD)
        item_count = len(items) if isinstance(items, list) else 0
        n = listing if isinstance(listing, int) and not isinstance(listing, bool) and listing > 0 \
            else item_count
        if n <= 0:
            _warn(report, f"shop.{BLACKMARKET_LISTING_FIELD}", "Y-4",
                  rule="shop_blackmarket_no_listing", node_id=node_id,
                  msg="黑市未配上架数量（%s 与 items 均空）→ 每次刷新不上架任何商品？确认"
                      % (BLACKMARKET_LISTING_FIELD,))


def _check_unused_shops(report: object, shops: List[Mapping[str, object]],
                        npc_shop_refs: Optional[Set[str]]) -> None:
    """未使用商店黄提示（定稿 L426）：npc 模块已声明 shop_refs 时，非 normal 店未被任何 NPC 引用。"""
    if npc_shop_refs is None:
        return  # npc 模块缺失/未接线 → 不触发噪音（【工程补白】4）
    for i, shop in enumerate(shops):
        sid = shop.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        if shop.get("type") == "normal":
            continue  # normal 兜底可达，免提示
        if sid not in npc_shop_refs:
            _warn(report, f"shop.{i}.id", "Y-8", rule="shop_unused", node_id=sid,
                  id=sid, msg="商店 %r 未被任何 NPC 引用（无 NPC 挂载且非 normal 默认）→ 这家店没人知道怎么进？确认"
                               % (sid,))


def _check_price_consistency(report: object, shops: List[Mapping[str, object]],
                             item_ids: Optional[Set[str]]) -> None:
    """同物不同价黄提示（定稿 L427）：items 模块存在时，多条目同 item 不同 price。"""
    if item_ids is None:
        return  # items 模块未声明 → 跳过（【工程补白】4）
    price_by_item: Dict[str, Set[str]] = {}
    for shop in shops:
        for key in ("items", "pool"):
            arr = shop.get(key)
            if not isinstance(arr, list):
                continue
            for e in arr:
                if not isinstance(e, Mapping):
                    continue
                item = e.get("item")
                if not isinstance(item, str) or not item:
                    continue
                price = e.get("price")
                if price is None:
                    continue  # 缺省=items 基准价，无法在配置层比较（引擎侧兜底）
                norm = repr(price) if isinstance(price, Mapping) else str(price)
                price_by_item.setdefault(item, set()).add(norm)
    for item, prices in sorted(price_by_item.items()):
        if len(prices) > 1:
            _warn(report, "shop", "Y-7", rule="shop_same_item_diff_price", item=item,
                  prices=sorted(prices),
                  msg="物品 %r 在不同条目价格不一致（%s），同物不同价确认？（定稿 L427）"
                      % (item, "/".join(sorted(prices))))


def validate_shops(modules: Mapping[str, object], report: object) -> None:
    """shop 模块专项校验（M4 批次3·路D1：ShopDef 14 顶层字段 + 12 条目字段 + 裁决⑤⑥）。纯函数，无副作用。

    入口：主 agent 收口时在 check_pack 的 _Checker.run() 尾部调用
        validate_shops(modules, checker)  （checker._err/_warn 签名与 _emit 一致）
    或自建收集器（暴露 error(module, field, kind, **detail) / warning(...)）。
    返回 None；红拦/黄提示全部经 report 追加（一次给全量）。

    modules: 模块名（无 .json 后缀）→ parsed JSON（含 "shop" 与可选 "items"/"settings"/"npc"）。
    引用靶缺失/未接线 → 跳过对应引用检查（细化_3e §2.3 默认放行）。

    规则速览（细化_2b3 §1.6 + 定稿 §十一 + 裁决⑤⑥）：
      红拦：type/scope/period/refresh.mode 枚举、id/name/items 必填、name 禁空格、
            item/currency 引用悬空、refresh once 缺时间窗、price 非法（负数/非数字/空对象）、
            stock/limit/discount/per_player/min_level/level_required 负数、
            reputation_required.level 非法、price_fluctuation 越界、open_condition 结构错误
      黄提示：空商店 / stock 1~4 / price=0 / 黑市浮动>30% / 黑市 pool 空或未配上架数量 /
            声望门槛 5 级制外 / 旧 per_player 迁移建议 / 同物不同价 / 未使用商店
    """
    shops = modules.get("shop")
    if not isinstance(shops, list):
        return  # 未接线 shop 模块 → 跳过（§2.3 默认放行）

    refs = _Refs()
    refs.item_ids = _id_set(modules, "items")
    refs.currency_ids = _settings_currency_ids(modules)
    refs.npc_shop_refs = _npc_shop_refs(modules)

    shop_entries: List[Mapping[str, object]] = []
    seen_ids: Set[str] = set()
    for i, entry in enumerate(shops):
        node_id = str(entry.get("id")) if isinstance(entry, Mapping) else f"#{i}"
        if not isinstance(entry, Mapping):
            _err(report, f"shop.{i}", "R-5", rule="shop_not_object",
                 node_id=node_id, got=type(entry).__name__, msg="商店条目需对象")
            continue
        shop_entries.append(entry)
        _check_shop(report, entry, node_id, refs, seen_ids)

    _check_unused_shops(report, shop_entries, refs.npc_shop_refs)
    _check_price_consistency(report, shop_entries, refs.item_ids)


__all__ = [
    # 枚举/常量
    "SHOP_TYPES", "SHOP_TYPE_DEFAULT", "SHOP_TYPE_NAMES",
    "REFRESH_MODES", "REFRESH_MODE_DEFAULT", "REFRESH_HOUR_DEFAULT",
    "REFRESH_WEEKDAY_DEFAULT", "REFRESH_ONCE_FMT",
    "SCOPES", "SCOPE_DEFAULT",
    "LIMIT_PERIODS", "LIMIT_PERIOD_DEFAULT",
    "REPUTATION_LEVELS", "REPUTATION_LEVEL_NAMES",
    "PRICE_FLUCTUATION_MAX", "PRICE_FLUCTUATION_WARN", "MAX_BUY_QTY_DEFAULT",
    "DISCOUNT_MAX", "STOCK_SMALL_MAX",
    "LEGACY_PER_PLAYER", "LEGACY_PER_PLAYER_PERIOD",
    "BLACKMARKET_LISTING_FIELD", "BLACKMARKET_LISTING_DEFAULT",
    # Def 类型
    "RefreshDef", "ShopItemDef", "ShopDef",
    # 函数
    "parse_shops", "validate_shops",
]
