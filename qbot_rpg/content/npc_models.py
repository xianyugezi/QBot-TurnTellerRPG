"""内容包领域模型 —— M4 批次2·路C1（NPC/对话 B1-B6）：NPCDef（顶层 15 字段 + 6 子表）+ validate_npcs 专项校验。

依据：
  - m4_shared_contract §3.1（NPC/对话 B1-B6：新文件 npc_models.py（NPCDef：14 顶层字段 + 子表）/
    发牌员三策略 rotate/random/condition（用户裁决④）/ 10 类动作 / max_dialog_depth 可配软拦（用户裁决③））
  - 细化_2b1_NPC数据与发牌员.md（npc.json 字段级 schema：顶层 15 字段 F01-F15 / 6 子表 /
    发牌员机制（rotate/random/condition 三策略 + 牌池）/ 10 类动作字段契约 §三 / 一次一物 §四 /
    验收 TC-01~TC-20 + 2026-08-27 审查裁决 P1-1（深度可配）/ P1-2（策略枚举保留细化版））
  - NPC系统设计定稿.md（§八 L434「顶层 14 字段 + 6 子表」——S1 裁决：14 系标题笔误，以列全的
    15 个为准（id/name/icon/map/type/desc/visible/dialogues/interactions/quests/shop_refs/
    intel/intel_refs/tutorials/dealer，L436-437）；NPC 类型 6 类 L344-349；条件引擎 §四
    （9 运算符 / var 键空间 / any-all-not 组合 / 事件注册表）；发牌员 §六；校验器 §4.5 L444-448）

本文件为批次 2·路C1 的**独立模块**（主 agent 收口时并入 content/models.py + validator.py 的
check_pack）：
  - 零冲突：不修改 models.py / validator.py / loader.py / __init__.py 既有内容；
    models.NpcDef（空壳）在收口时替换为本模块 NPCDef 即可（同 map_models.MapDef 模式）。
  - validate_npcs(modules, report) 为纯函数（无副作用），report 鸭子类型（见 _emit 说明），
    主 agent 收口时直接接入 check_pack 的 _Checker 实例或自建收集器。

【工程补白】（契约/定稿未显式定义处，显式标注供审查，不冒充定稿行号）：
  1. 条件结构校验本地镜像 engine/condition_engine.validate_condition 规则（var 注册表 / 9 运算符
     + 符号双写 / any-all-not 嵌套 / 事件预置 / 旧格式黄提示）——因 content 层仅允许依赖 data、
     不得反向依赖 engine（细化_3a §2.2「content → data」/ map_models G0 修复口径），与
     weather_validator REGISTERED_KEYS 同源镜像模式一致；收口时如需以 engine 为准可改 import。
  2. dealer.pool 候选牌条目字段（id/condition/weight/deliver/once，2b1 §2.1 P01-P05）与
     tutorials 模块键名「tutorials」为【工程补白】命名（定稿仅称「牌池」「教学模板」，未给键名）。
  3. intel_refs（图鉴引用，ref enemies lore）仅做结构校验（非空字符串列表）：enemies lore 条目
     当前无 id（lore=[{unlock,desc}]），无法精确引用检查——待 lore id schema 或收口接线补充。
  4. 「未使用 NPC」黄提示仅在 maps 模块**已声明 npcs 数组**时触发（防未接线内容包全量噪音）；
     反向「maps.npcs 引用的 NPC 必须存在」亦在本模块双向校验（定稿 L360/L387/L427 双向互为校验）。
  5. repair 动作依赖装备耐久系统（框架未实现）→ 当前降级「不可用 + 友好提示」（2b1 S4 裁决），
     配置不拦截（仅结构校验）。
  6. 「对话树死循环」（定稿 §4.5 L447）在嵌套 JSON 数据中不可能成环（无引用，纯嵌套），不实现；
     超深（>max_dialog_depth）软拦提示为黄提示不拦截（用户裁决③，0=不限不拦）。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；纯函数/懒计算；
确定性；工程补白显式标注；文件头标注依据；不 git commit。
仅依赖 qbot_rpg.content.models 的 BaseDef。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple, cast

from qbot_rpg.content.models import BaseDef

# =====================================================================================
# 权威枚举（定稿 L344-349 / 2b1 F05 + S3 + 用户裁决③④ + 2b1 §2）
# =====================================================================================
# NPC 类型 6 类（定稿 L344-349 中文类；英文键 2b1 F05 落点：后三类英文键为【工程补白】命名）
NPC_TYPES: Tuple[str, ...] = (
    "merchant",       # 商人（/对话 → shop）
    "quest_giver",    # 任务发放者（/对话 → quest）
    "intel_giver",    # 情报员（/对话 → intel）
    "tutor",          # 教学导师（/对话 → tutorial，first_meet）
    "narrator",       # 世界观叙述者（/对话 → reply）
    "dealer",         # 发牌员（/对话 → dealer，事件牌组抽牌）
)
NPC_TYPE_NAMES: Dict[str, str] = {  # 定稿 L344-349 中文对照（供提示/编辑器）
    "merchant": "商人",
    "quest_giver": "任务发放者",
    "intel_giver": "情报员",
    "tutor": "教学导师",
    "narrator": "世界观叙述者",
    "dealer": "发牌员",
}
NPC_TYPE_DEFAULT: str = "merchant"  # 2b1 F05：type 选填默认 merchant

# 10 类动作（定稿 L126-139 / 2b1 §三 AC01-AC10；repair* 依赖未实现的装备耐久系统 → 降级）
ACTION_TYPES: Tuple[str, ...] = (
    "quest", "shop", "heal", "give_item", "buff", "repair", "teleport", "intel", "tutorial", "reply",
)
# 对话树 options 建议子集 5 类（2b1 S3 裁决：dialogues.options[].action 建议用此子集；
# 结构上不拦截其他类，校验器提示「对话树建议仅用 5 类」）
DIALOGUE_ACTION_SUBSET: Tuple[str, ...] = ("shop", "quest", "tutorial", "intel", "reply")

# 发牌员三策略（2b1 DS01-DS04 / 用户裁决④：保留细化版 rotate/random/condition；
# 定稿 first_match/weighted/random 作兼容映射 + 迁移提示）
DEALER_STRATEGIES: Tuple[str, ...] = ("rotate", "random", "condition")
DEALER_STRATEGY_DEFAULT: str = "condition"  # 2b1 DR01：缺省 condition（承接定稿 first_match 默认态）
DEALER_STRATEGY_LEGACY: Dict[str, str] = {  # 用户裁决④兼容映射（旧值读取兼容 + 黄提示迁移）
    "first_match": "condition",
    "weighted": "random",
    "random": "random",
}

REPEAT_TYPES: Tuple[str, ...] = ("once", "daily")  # give_item repeat（2b1 AC04）
MENU_MAX_OPTIONS: int = 6  # 交互菜单最多 6 项 + 固定 N.离开（定稿 L108-113，运行时渲染规则）
DEFAULT_MAX_DIALOG_DEPTH: int = 2  # settings.max_dialog_depth 缺省（用户裁决③：默认 2，0=不限）

# 条件引擎镜像常量（【工程补白】1：本地镜像 engine/condition_engine，不 import engine）
COND_OPERATORS: Tuple[str, ...] = ("gt", "ge", "lt", "le", "eq", "ne", "between", "is", "not")
COND_OP_SYMBOLS: Dict[str, str] = {">=": "ge", ">": "gt", "<=": "le", "<": "lt", "=": "eq", "!=": "ne"}
COND_OP_LEGACY: Dict[str, str] = {"min": "ge", "max": "le"}  # NPC 4.2 兼容
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
# 中文变量键互译别名（NPC 4.3.1 唯一权威主表子集；带 {T} 占位者为前缀模式）
COND_VAR_ALIASES: Dict[str, Optional[str]] = {
    "[当前等级]": None,
    "[图鉴完成度]": None,
    "[主线进度]": None,
    "[职业]": None,
    "[签到:连续天数]": None,
    "[签到:本月天数]": None,
    "[签到:今日已签]": None,
}
COND_VAR_ALIAS_PREFIXES: Tuple[str, ...] = (  # 前缀+{T} 别名（如 [背包:铁矿] → item_count）
    "[背包:", "[累计获得:", "[累计击杀:", "[副本通关:", "[熟练度:", "[声望:", "[季节:", "[时段:", "[天气:",
)
# 预置事件注册表（NPC 4.3.2；事件名未登记 → 黄提示不拦）
COND_EVENT_PRESETS: Tuple[str, ...] = (
    "[事件:副本通关]", "[事件:任务完成]", "[事件:签到]",
    "[事件:怪物击杀]", "[事件:等级提升]", "[事件:NPC对话]",
)
# 条件结构红拦规则（本地镜像分流：其余 CND 规则走黄提示）——软/硬分流口径见 _check_condition
_COND_HARD_RULES: Tuple[str, ...] = (
    "var_not_registered", "op_invalid", "condition_not_object", "condition_empty",
)


# =====================================================================================
# Def 类型（风格对齐 MapDef/SpawnDef：BaseDef + 字段访问器；子表派生 DialogOptionDef/
# InteractionDef/QuestRefDef/DealerPoolCardDef/DealerDef）
# =====================================================================================


@dataclass(frozen=True)
class DialogOptionDef:
    """dialogues.options[] 对话树节点（2b1 D03-D06：text/action/condition/子字段占位 + 嵌套 options）。

    对话树深度取 settings.max_dialog_depth（默认 2，0=不限），超深软拦不拦截（用户裁决③）。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "DialogOptionDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def text(self) -> Optional[str]:
        v = self.raw.get("text")
        return v if isinstance(v, str) else None

    @property
    def action(self) -> Optional[str]:
        v = self.raw.get("action")
        return v if isinstance(v, str) else None

    @property
    def condition(self) -> object:
        return self.raw.get("condition")

    @property
    def options(self) -> Tuple[DialogOptionDef, ...]:
        """嵌套子选项（对话树第 2 层及更深；depth 由校验器沿此递归计算）。"""
        v = self.raw.get("options")
        return tuple(DialogOptionDef.from_entry(o) for o in v if isinstance(o, Mapping)) \
            if isinstance(v, list) else ()


@dataclass(frozen=True)
class DialogueDef:
    """dialogues 子表（2b1 D01-D02：greeting 见面语 + options 对话树）。"""

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "DialogueDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def greeting(self) -> Optional[str]:
        v = self.raw.get("greeting")
        return v if isinstance(v, str) else None

    @property
    def options(self) -> Tuple[DialogOptionDef, ...]:
        v = self.raw.get("options")
        return tuple(DialogOptionDef.from_entry(o) for o in v if isinstance(o, Mapping)) \
            if isinstance(v, list) else ()


@dataclass(frozen=True)
class InteractionDef:
    """interactions[] 功能菜单条目（2b1 I01-I03：action/text/condition + action 专属子字段）。"""

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "InteractionDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def action(self) -> Optional[str]:
        v = self.raw.get("action")
        return v if isinstance(v, str) else None

    @property
    def text(self) -> Optional[str]:
        v = self.raw.get("text")
        return v if isinstance(v, str) else None

    @property
    def condition(self) -> object:
        return self.raw.get("condition")


@dataclass(frozen=True)
class QuestRefDef:
    """quests[] 候选任务条目（2b1 F10：{quest_id, condition}；差异化支线）。"""

    quest_id: Optional[str]
    condition: object = None

    @classmethod
    def from_entry(cls, entry: object) -> "QuestRefDef":
        if not isinstance(entry, Mapping):
            return cls(quest_id=None)
        qid = entry.get("quest_id")
        return cls(
            quest_id=qid if isinstance(qid, str) else None,
            condition=entry.get("condition"),
        )


@dataclass(frozen=True)
class DealerPoolCardDef:
    """dealer.pool[] 候选牌条目（2b1 P01-P05：【工程补白】命名）：id/condition/weight/deliver/once。"""

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "DealerPoolCardDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def id(self) -> Optional[str]:
        v = self.raw.get("id")
        return v if isinstance(v, str) else None

    @property
    def condition(self) -> object:
        return self.raw.get("condition")

    @property
    def weight(self) -> Optional[float]:
        v = self.raw.get("weight")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def deliver(self) -> Mapping[str, object]:
        v = self.raw.get("deliver")
        return v if isinstance(v, Mapping) else {}

    @property
    def once(self) -> bool:
        return self.raw.get("once") is True


@dataclass(frozen=True)
class DealerDef:
    """dealer 子表（2b1 DR01-DR02：strategy 三策略 + pool 候选牌池；type=dealer 时必配）。"""

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "DealerDef":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    @property
    def strategy(self) -> Optional[str]:
        v = self.raw.get("strategy")
        return v if isinstance(v, str) else None

    @property
    def pool(self) -> Tuple[DealerPoolCardDef, ...]:
        v = self.raw.get("pool")
        return tuple(DealerPoolCardDef.from_entry(p) for p in v if isinstance(p, Mapping)) \
            if isinstance(v, list) else ()


@dataclass(frozen=True)
class NPCDef(BaseDef):
    """npc.json 条目（顶层 15 字段 + 6 子表访问器，风格对齐 MapDef/EnemyDef）。

    顶层 15 字段（2b1 F01-F15 / 定稿 L436-437）：id/name/icon/map/type/desc/visible/
    dialogues/interactions/quests/shop_refs/intel/intel_refs/tutorials/dealer。
    注：id/name 由 BaseDef 承载（from_entry 冗余镜像 raw），其余字段访问器见下。
    6 子表（定稿 §8.2 / 2b1 §1.5）：dialogues(greeting/options) / interactions /
    quests / shop_refs / intel+intel_refs / tutorials / dealer。
    """

    # ---- 数值/字符串/映射/列表辅助（与 MapDef/EnemyDef 同风格）----
    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    def _entries(self, key: str) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get(key)
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    def _str_list(self, key: str) -> Tuple[str, ...]:
        v = self.raw.get(key)
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    # ---- 顶层字段访问器（F03-F15；F01/F02 由 BaseDef）----
    @property
    def icon(self) -> Optional[str]:
        """单字符图标（🔨），列表展示（2b1 F03，必填）。"""
        return self._str("icon")

    @property
    def map(self) -> Optional[str]:
        """地图挂点（引用 maps.json 的 map id；maps.npcs 为反向引用，双向互为校验，2b1 F04）。"""
        return self._str("map")

    @property
    def type(self) -> Optional[str]:
        """NPC 类型 6 类：merchant/quest_giver/intel_giver/tutor/narrator/dealer（2b1 F05）。"""
        return self._str("type")

    @property
    def desc(self) -> Optional[str]:
        """一句话描述（2b1 F06）。"""
        return self._str("desc")

    @property
    def visible(self) -> bool:
        """是否可见（false=隐藏 NPC，条件解锁后显示；2b1 F07，默认 true）。"""
        v = self.raw.get("visible")
        return v if isinstance(v, bool) else True

    @property
    def dialogues(self) -> DialogueDef:
        """dialogues 子表（greeting 见面语 + options 对话树 ≤ max_dialog_depth，2b1 F08）。"""
        return DialogueDef.from_entry(self.raw.get("dialogues"))

    @property
    def interactions(self) -> Tuple[InteractionDef, ...]:
        """interactions[] 功能菜单条目（action ∈ 全 10 类，2b1 F09）。"""
        return tuple(InteractionDef.from_entry(e) for e in self._entries("interactions"))

    @property
    def quests(self) -> Tuple[QuestRefDef, ...]:
        """quests[] 候选任务+条件（差异化支线，2b1 F10）。"""
        return tuple(QuestRefDef.from_entry(e) for e in self._entries("quests"))

    @property
    def shop_refs(self) -> Tuple[str, ...]:
        """shop_refs[] 商店引用（ref shop.json；打开后=当前商店，2b1 F11）。"""
        return self._str_list("shop_refs")

    @property
    def intel(self) -> Tuple[Mapping[str, object], ...]:
        """intel[] 情报直接条目（与 enemies lore 同构，2b1 F12）。"""
        return self._entries("intel")

    @property
    def intel_refs(self) -> Tuple[str, ...]:
        """intel_refs[] 图鉴引用（ref enemies lore；交付后置灰"已听"，2b1 F13）。"""
        return self._str_list("intel_refs")

    @property
    def tutorials(self) -> Tuple[object, ...]:
        """tutorials[] 教学模板引用（first_meet 首见触发；条目 str 或 {tutorial_id, condition}，2b1 F14）。"""
        v = self.raw.get("tutorials")
        return tuple(v) if isinstance(v, list) else ()

    @property
    def dealer(self) -> Optional[DealerDef]:
        """dealer 发牌员配置（strategy + pool；type=dealer 时必配，2b1 F15）。"""
        d = self.raw.get("dealer")
        return DealerDef.from_entry(d) if isinstance(d, Mapping) else None


def parse_npcs(modules: Mapping[str, object]) -> Tuple[NPCDef, ...]:
    """从 modules 提取 npc 模块 → NPCDef 元组（非 list / 非对象条目跳过；供运行期与测试复用）。"""
    npcs = modules.get("npc") if isinstance(modules, Mapping) else None
    if not isinstance(npcs, list):
        return ()
    return tuple(cast(NPCDef, NPCDef.from_entry(e)) for e in npcs if isinstance(e, Mapping))


# =====================================================================================
# validate_npcs：npc 模块专项校验（2b1 TC-01~TC-03/TC-20 + 定稿 §4.5；供主 agent 收口接 check_pack）
# =====================================================================================
# 规则清单（红拦=errors / 黄提示=warnings）：
#   硬拦 R-5：id 必填非空 string 且池内唯一；name/icon 必填；name 禁空格（TC-02 ②）；条目非对象
#   硬拦 R-1：type ∉ 6 类（缺省 merchant 不拦）；visible/once 非 bool；strategy ∉ 三枚举
#             且非旧值；10 类动作 action 缺失/非法；菜单/对话选项 text 缺失；结构错误
#   硬拦 R-2：weight/count/coins/turns 数值非法（负数/非整数/百分比串非法）
#   硬拦 R-4：map/quests/shop_refs/effects/items/map(teleport)/tutorials 引用不存在（模块存在时）；
#             maps.npcs 反向引用 NPC 不存在（双向校验）
#   黄提示 Y-1：旧 strategy 值 first_match/weighted/random →「建议迁移」（用户裁决④）；
#             dialogues.options[].action 非 5 类子集（S3 建议）
#   黄提示 Y-2：对话树超深 >max_dialog_depth（用户裁决③，0=不限不拦）
#   黄提示 Y-3：未使用 NPC（maps 已声明 npcs 数组时，TC-20 ③）
#   黄提示 Y-4：条件软规则（旧格式/事件未登记/选项级建议），结构硬规则走 error（CND 分流）
#   黄提示 Y-5：type=dealer 但 pool 空（孤寂卡节奏提示，TC-12 侧）


def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    """收集器鸭子类型适配：优先 report.<method>，其次 validator._Checker 的 _<method>。"""
    _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
    fn = getattr(report, method, None)
    if not callable(fn):
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", "npc", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", "npc", field, kind, **detail)


# -------------------------------------------------------------------------------------
# 条件引擎本地镜像（【工程补白】1：content→data 单向铁律，不 import engine）
# -------------------------------------------------------------------------------------
def _cond_var_ok(var: object) -> bool:
    """var 键注册判定（镜像 condition_engine.normalize_var 的接受集合，不含归一结果）。

    接受：注册键 / 中文别名精确键 / 中文别名前缀模式（[背包:X] 等）/ [事件:...] / [签到:...] / x_。
    """
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


def _check_condition(report: object, cond: object, base_field: str, node_id: str) -> None:
    """条件表达式结构校验（镜像 engine/condition_engine.validate_condition 规则）。

    红拦（error）：var 未注册 / op 非法 / 条件非对象 / 空条件（_COND_HARD_RULES）。
    黄提示（不拦）：旧格式 {type,var,op,value}（type 非空）/ 旧 event 原语 /
            事件 var 未在预置注册表（NPC 4.3.2「只建议不限制」）/ 其余 CND 软规则。
    递归 any/all/not 嵌套与 conditions 数组（NPC 4.4 / 2b4 D-02）。
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
                 allowed=list(COND_OPERATORS) + list(COND_OP_SYMBOLS) + list(COND_OP_LEGACY),
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


def _cond_op_ok(op: object) -> bool:
    if not isinstance(op, str) or not op:
        return False
    o = op.strip().lower()
    return o in COND_OPERATORS or o in COND_OP_SYMBOLS or o in COND_OP_LEGACY


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


# -------------------------------------------------------------------------------------
# 引用集合收集（模块缺失/非 list → None：调用方跳过引用检查，细化_3e §2.3 默认放行）
# -------------------------------------------------------------------------------------
class _Refs:
    """跨模块引用校验靶（None = 目标模块未声明/无合法 id → 跳过对应引用检查）。"""

    __slots__ = ("map_ids", "quest_ids", "shop_ids", "item_ids", "effect_ids",
                 "tutorial_ids", "enemy_ids", "npc_refs_from_maps")

    def __init__(self) -> None:
        self.map_ids: Optional[set] = None
        self.quest_ids: Optional[set] = None
        self.shop_ids: Optional[set] = None
        self.item_ids: Optional[set] = None
        self.effect_ids: Optional[set] = None
        self.tutorial_ids: Optional[set] = None
        self.enemy_ids: Optional[set] = None
        self.npc_refs_from_maps: Optional[set] = None  # maps.npcs 引用数组（未声明 → None）


def _id_set(modules: Mapping[str, object], key: str) -> Optional[set]:
    data = modules.get(key)
    if not isinstance(data, list):
        return None
    ids = {e.get("id") for e in data
           if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]}
    return ids if ids else None


def _effect_union(modules: Mapping[str, object]) -> Optional[set]:
    """buff effects[] 引用靶：effects/statuses/marks 三表统一注册，ID 跨表唯一（AC05）。"""
    union: set = set()
    any_mod = False
    for key in ("effects", "statuses", "marks"):
        ids = _id_set(modules, key)
        if ids is not None:
            any_mod = True
            union |= ids
    return union if any_mod else None


def _npc_refs_from_maps(modules: Mapping[str, object]) -> Optional[set]:
    """maps.npcs 引用数组 → npc id 集；maps 缺失或**无任何 npcs 数组** → None
    （【工程补白】4：未接线内容包不触发「未使用 NPC」全量噪音）。"""
    maps = modules.get("maps")
    if not isinstance(maps, list):
        return None
    refs: set = set()
    any_npcs = False
    for m in maps:
        if not isinstance(m, Mapping):
            continue
        npcs = m.get("npcs")
        if npcs is None:
            continue
        any_npcs = True
        if isinstance(npcs, list):
            refs.update(str(n) for n in npcs if isinstance(n, str) and n)
    return refs if any_npcs else None


def _max_dialog_depth(modules: Mapping[str, object]) -> int:
    """settings.max_dialog_depth（用户裁决③：默认 2，0=不限）。settings 缺省/非法 → 默认。"""
    settings = modules.get("settings")
    if isinstance(settings, Mapping):
        v = settings.get("max_dialog_depth")
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            return v
    return DEFAULT_MAX_DIALOG_DEPTH


# -------------------------------------------------------------------------------------
# 各子表校验
# -------------------------------------------------------------------------------------
def _check_quest_refs(
    report: object, quests: object, base: str, node_id: str, refs: _Refs,
) -> None:
    """quests[] 条目（{quest_id, condition}）：结构红拦 + quest 引用存在（模块存在时）。"""
    if not isinstance(quests, list):
        _err(report, base, "R-1", rule="npc_quests_not_list", node_id=node_id)
        return
    for qi, q in enumerate(quests):
        qbase = f"{base}.{qi}"
        if not isinstance(q, Mapping):
            _err(report, qbase, "R-5", rule="npc_quest_ref_not_object",
                 node_id=node_id, got=type(q).__name__)
            continue
        qid = q.get("quest_id")
        if qid is None:
            _err(report, f"{qbase}.quest_id", "R-5", rule="npc_quest_ref_quest_id_required",
                 node_id=node_id)
        elif not isinstance(qid, str) or not qid:
            _err(report, f"{qbase}.quest_id", "R-1", rule="npc_quest_ref_quest_id_invalid",
                 node_id=node_id, quest_id=qid)
        elif refs.quest_ids is not None and qid not in refs.quest_ids:
            _err(report, f"{qbase}.quest_id", "R-4", rule="npc_quest_ref_missing",
                 node_id=node_id, ref=qid, registered=sorted(refs.quest_ids))
        if "condition" in q:
            _check_condition(report, q["condition"], f"{qbase}.condition", node_id)


def _check_string_ref_list(
    report: object, items: object, base: str, node_id: str, refs: Optional[set],
    rule_ok: str, rule_not_list: str, rule_invalid: str, rule_missing: str, target: str,
) -> None:
    """string[] 引用列表（shop_refs / intel_refs / tutorials str 形态）：结构 + 引用存在（有靶时）。"""
    if not isinstance(items, list):
        _err(report, base, "R-1", rule=rule_not_list, node_id=node_id)
        return
    for si, s in enumerate(items):
        sbase = f"{base}.{si}"
        if not isinstance(s, str) or not s:
            _err(report, sbase, "R-1", rule=rule_invalid, node_id=node_id, value=s)
        elif refs is not None and s not in refs:
            _err(report, sbase, "R-4", rule=rule_missing, node_id=node_id,
                 ref=s, target=target, registered=sorted(refs))


def _check_give_items(
    report: object, items: object, base: str, node_id: str, refs: _Refs,
) -> None:
    """give_item items[]（统一 reward 条目 schema：{id,count}，id ≡ item 键，AC04）。"""
    if not isinstance(items, list):
        _err(report, base, "R-1", rule="npc_give_items_not_list", node_id=node_id)
        return
    for ii, it in enumerate(items):
        ibase = f"{base}.{ii}"
        if not isinstance(it, Mapping):
            _err(report, ibase, "R-5", rule="npc_give_item_not_object",
                 node_id=node_id, got=type(it).__name__)
            continue
        iid = it.get("id")
        if not isinstance(iid, str) or not iid:
            _err(report, f"{ibase}.id", "R-1", rule="npc_give_item_id_invalid",
                 node_id=node_id, item_id=iid)
        elif refs.item_ids is not None and iid not in refs.item_ids:
            _err(report, f"{ibase}.id", "R-4", rule="npc_give_item_ref_missing",
                 node_id=node_id, ref=iid, registered=sorted(refs.item_ids))
        cnt = it.get("count")
        if cnt is not None and (not isinstance(cnt, int) or isinstance(cnt, bool) or cnt < 1):
            _err(report, f"{ibase}.count", "R-2", rule="npc_give_item_count_invalid",
                 node_id=node_id, count=cnt)


def _check_effects(
    report: object, effects: object, base: str, node_id: str, refs: _Refs,
) -> None:
    """buff effects[]（ref 效果注册表：effects/statuses/marks 三表统一注册，AC05）。"""
    if not isinstance(effects, list):
        _err(report, base, "R-1", rule="npc_buff_effects_not_list", node_id=node_id)
        return
    for ei, e in enumerate(effects):
        ebase = f"{base}.{ei}"
        if not isinstance(e, str) or not e:
            _err(report, ebase, "R-1", rule="npc_buff_effect_invalid", node_id=node_id, value=e)
        elif refs.effect_ids is not None and e not in refs.effect_ids:
            _err(report, ebase, "R-4", rule="npc_buff_effect_ref_missing", node_id=node_id,
                 ref=e, registered=sorted(refs.effect_ids))


def _check_heal(report: object, heal: object, base: str, node_id: str) -> None:
    """heal {hp,mp}（int ≥0 或 \"N%\" 百分比串=按上限，AC03）。"""
    if not isinstance(heal, Mapping):
        _err(report, base, "R-1", rule="npc_heal_not_object", node_id=node_id)
        return
    for k in ("hp", "mp"):
        v = heal.get(k)
        if v is None:
            continue
        ok = (isinstance(v, int) and not isinstance(v, bool) and v >= 0) or (
            isinstance(v, str) and len(v) >= 2 and v.endswith("%")
            and v[:-1].isdigit() and 0 <= int(v[:-1]) <= 100
        )
        if not ok:
            _err(report, f"{base}.{k}", "R-1", rule="npc_heal_value_invalid",
                 node_id=node_id, key=k, value=v, expect="int ≥0 或 \"N%\" 百分比串")


def _check_cost(report: object, cost: object, base: str, node_id: str) -> None:
    """cost {coins}（settings 货币键：coins 数值 ≥0；heal/repair/teleport 共用，AC03/AC06/AC07）。"""
    if cost is None:
        return
    if not isinstance(cost, Mapping):
        _err(report, base, "R-1", rule="npc_cost_not_object", node_id=node_id)
        return
    coins = cost.get("coins")
    if coins is not None and (not isinstance(coins, (int, float)) or isinstance(coins, bool) or coins < 0):
        _err(report, f"{base}.coins", "R-2", rule="npc_cost_coins_invalid",
             node_id=node_id, coins=coins)


def _check_action_entry(
    report: object, item: Mapping[str, object], base: str, node_id: str,
    action: str, refs: _Refs, is_dialog: bool, is_deliver: bool,
) -> None:
    """action 专属子字段校验（interactions[] / dialogues.options[] / dealer.pool[].deliver 共用）。

    is_dialog：对话树入口（action 建议 5 类子集，S3）；is_deliver：发牌交付（无 text）。
    """
    if action == "quest":
        _check_quest_refs(report, item.get("quests"), f"{base}.quests", node_id, refs)
    elif action == "shop":
        _check_string_ref_list(report, item.get("shop_refs"), f"{base}.shop_refs", node_id,
                               refs.shop_ids, "npc_shop_ref_ok", "npc_shop_refs_not_list",
                               "npc_shop_ref_invalid", "npc_shop_ref_missing", "shop")
    elif action == "heal":
        _check_cost(report, item.get("cost"), f"{base}.cost", node_id)
        _check_heal(report, item.get("heal"), f"{base}.heal", node_id)
    elif action == "give_item":
        _check_give_items(report, item.get("items"), f"{base}.items", node_id, refs)
        repeat = item.get("repeat")
        if repeat is not None and (not isinstance(repeat, str) or repeat not in REPEAT_TYPES):
            _err(report, f"{base}.repeat", "R-1", rule="npc_give_item_repeat_invalid",
                 node_id=node_id, repeat=repeat, allowed=list(REPEAT_TYPES))
    elif action == "buff":
        _check_effects(report, item.get("effects"), f"{base}.effects", node_id, refs)
        turns = item.get("turns")
        if turns is not None and (not isinstance(turns, int) or isinstance(turns, bool) or turns < 0):
            _err(report, f"{base}.turns", "R-2", rule="npc_buff_turns_invalid",
                 node_id=node_id, turns=turns)
    elif action == "repair":
        # 【工程补白】5 + 2b1 S4：repair 依赖装备耐久（框架未实现）→ 当前降级，配置不拦截
        _check_cost(report, item.get("cost"), f"{base}.cost", node_id)
    elif action == "teleport":
        tmap = item.get("map")
        if not isinstance(tmap, str) or not tmap:
            _err(report, f"{base}.map", "R-1", rule="npc_teleport_map_invalid",
                 node_id=node_id, map=tmap)
        elif refs.map_ids is not None and tmap not in refs.map_ids:
            _err(report, f"{base}.map", "R-4", rule="npc_teleport_map_missing",
                 node_id=node_id, ref=tmap, registered=sorted(refs.map_ids))
        _check_cost(report, item.get("cost"), f"{base}.cost", node_id)
    elif action == "intel":
        # 【工程补白】3：enemies lore 无 id，intel_refs 仅结构校验（非空字符串列表）
        _check_string_ref_list(report, item.get("intel_refs"), f"{base}.intel_refs", node_id,
                               None, "npc_intel_ref_ok", "npc_intel_refs_not_list",
                               "npc_intel_ref_invalid", "npc_intel_ref_missing", "enemies_lore")
    elif action == "tutorial":
        _check_tutorials(report, item.get("tutorials"), f"{base}.tutorials", node_id, refs)
    elif action == "reply":
        # 【工程补白】reply 的 text 双形态（AC10 子字段 = 聊天回复；与 I02/D03 的菜单/选项文案
        # text 同名同槽，结构上不冲突）：非空字符串 = 单条回复（兼菜单/选项标签）；非空字符串
        # 列表 = 随机/循环回复（列表头兼标签）。缺失/空/类型非法 → 红拦。
        texts = item.get("text")
        ok = (isinstance(texts, str) and bool(texts)) or (
            isinstance(texts, list) and bool(texts)
            and all(isinstance(t, str) and t for t in texts))
        if not ok:
            _err(report, f"{base}.text", "R-1", rule="npc_reply_text_invalid",
                 node_id=node_id, texts=texts)
    if is_dialog and action in ACTION_TYPES and action not in DIALOGUE_ACTION_SUBSET:
        # S3 裁决：对话树建议仅用 5 类（结构不拦截，提示）
        _warn(report, base, "Y-1", rule="npc_dialog_action_not_subset", node_id=node_id,
              action=action, suggested=list(DIALOGUE_ACTION_SUBSET),
              msg="对话树建议仅用 5 类 action（shop/quest/tutorial/intel/reply）")


def _check_tutorials(report: object, tutorials: object, base: str, node_id: str, refs: _Refs) -> None:
    """tutorials[]（str 引用 或 {tutorial_id, condition} 双形态，2b1 F14/AC09）。"""
    if not isinstance(tutorials, list):
        _err(report, base, "R-1", rule="npc_tutorials_not_list", node_id=node_id)
        return
    for ti, t in enumerate(tutorials):
        tbase = f"{base}.{ti}"
        if isinstance(t, str):
            if not t:
                _err(report, tbase, "R-1", rule="npc_tutorial_ref_invalid", node_id=node_id, value=t)
            elif refs.tutorial_ids is not None and t not in refs.tutorial_ids:
                _err(report, tbase, "R-4", rule="npc_tutorial_ref_missing", node_id=node_id,
                     ref=t, registered=sorted(refs.tutorial_ids))
        elif isinstance(t, Mapping):
            tid = t.get("tutorial_id")
            if not isinstance(tid, str) or not tid:
                _err(report, f"{tbase}.tutorial_id", "R-1", rule="npc_tutorial_id_invalid",
                     node_id=node_id, tutorial_id=tid)
            elif refs.tutorial_ids is not None and tid not in refs.tutorial_ids:
                _err(report, f"{tbase}.tutorial_id", "R-4", rule="npc_tutorial_ref_missing",
                     node_id=node_id, ref=tid, registered=sorted(refs.tutorial_ids))
            if "condition" in t:
                _check_condition(report, t["condition"], f"{tbase}.condition", node_id)
        else:
            _err(report, tbase, "R-5", rule="npc_tutorial_not_str_or_object",
                 node_id=node_id, got=type(t).__name__)


def _check_dialog_options(
    report: object, opts: object, base: str, depth: int, node_id: str,
    refs: _Refs, max_depth: int, too_deep: List[bool],
) -> None:
    """dialogues.options[] 递归校验（含嵌套子选项与深度软拦）。

    depth：根选项=1，子选项逐层 +1；max_depth=0 表示不限（用户裁决③）。
    超深 → 黄提示「对话太深，拆成多 NPC 或事件牌组」（每 NPC 至多一条，too_deep 去重）。
    """
    if not isinstance(opts, list):
        return  # options 非 list 已在 dialogues 层红拦
    for oi, opt in enumerate(opts):
        obase = f"{base}.{oi}"
        if not isinstance(opt, Mapping):
            _err(report, obase, "R-5", rule="npc_dialog_option_not_object",
                 node_id=node_id, got=type(opt).__name__)
            continue
        action = opt.get("action")
        text = opt.get("text")
        # D03：选项文案必填；reply 的 text 可作回复内容（字符串或非空字符串列表，见
        # _check_action_entry reply 双形态补白）兼标签，不重复要求字符串标签
        text_label_ok = (isinstance(text, str) and bool(text)) or (
            action == "reply"
            and isinstance(text, list) and bool(text)
            and all(isinstance(t, str) and t for t in text))
        if not text_label_ok:
            _err(report, f"{obase}.text", "R-5", rule="npc_dialog_option_text_required",
                 node_id=node_id, text=text)
        if action is not None:
            if not isinstance(action, str) or action not in ACTION_TYPES:
                _err(report, f"{obase}.action", "R-1", rule="npc_action_invalid",
                     node_id=node_id, action=action, allowed=list(ACTION_TYPES))
            else:
                _check_action_entry(report, opt, obase, node_id, action, refs,
                                    is_dialog=True, is_deliver=False)
        if "condition" in opt:
            _check_condition(report, opt["condition"], f"{obase}.condition", node_id)
        children = opt.get("options")
        if isinstance(children, list):
            if max_depth and depth + 1 > max_depth and not too_deep:
                too_deep.append(True)
                _warn(report, f"{base}.{oi}.options", "Y-2", rule="npc_dialog_too_deep",
                      node_id=node_id, depth=depth + 1, max_depth=max_depth,
                      msg="对话太深，拆成多 NPC 或事件牌组（max_dialog_depth=%d，0=不限）" % max_depth)
            _check_dialog_options(report, children, f"{obase}.options", depth + 1,
                                  node_id, refs, max_depth, too_deep)


def _check_dialogues(
    report: object, entry: Mapping[str, object], idx: int, node_id: str,
    refs: _Refs, max_depth: int,
) -> None:
    """dialogues 子表校验（2b1 F08/D01-D06）：greeting + options 树 + 深度软拦。"""
    dial = entry.get("dialogues")
    if dial is None:
        return  # 缺省 greeting 兜底（定稿 L391）
    if not isinstance(dial, Mapping):
        _err(report, f"npc.{idx}.dialogues", "R-1", rule="npc_dialogues_not_object",
             node_id=node_id)
        return
    base = f"npc.{idx}.dialogues"
    greeting = dial.get("greeting")
    if greeting is not None and not isinstance(greeting, str):
        _err(report, f"{base}.greeting", "R-1", rule="npc_greeting_invalid",
             node_id=node_id, greeting=greeting)
    opts = dial.get("options")
    if opts is not None and not isinstance(opts, list):
        _err(report, f"{base}.options", "R-1", rule="npc_dialog_options_not_list",
             node_id=node_id)
        return
    too_deep: List[bool] = []
    _check_dialog_options(report, opts, f"{base}.options", 1, node_id, refs, max_depth, too_deep)


def _check_interactions(
    report: object, entry: Mapping[str, object], idx: int, node_id: str, refs: _Refs,
) -> None:
    """interactions[] 功能菜单校验（2b1 F09/I01-I03：action/text/condition + 专属子字段）。"""
    interactions = entry.get("interactions")
    if interactions is None:
        return
    if not isinstance(interactions, list):
        _err(report, f"npc.{idx}.interactions", "R-1", rule="npc_interactions_not_list",
             node_id=node_id)
        return
    base = f"npc.{idx}.interactions"
    for ii, item in enumerate(interactions):
        ibase = f"{base}.{ii}"
        if not isinstance(item, Mapping):
            _err(report, ibase, "R-5", rule="npc_interaction_not_object",
                 node_id=node_id, got=type(item).__name__)
            continue
        action = item.get("action")
        if action is None:
            _err(report, f"{ibase}.action", "R-5", rule="npc_action_required", node_id=node_id)
            continue
        if not isinstance(action, str) or action not in ACTION_TYPES:
            _err(report, f"{ibase}.action", "R-1", rule="npc_action_invalid",
                 node_id=node_id, action=action, allowed=list(ACTION_TYPES))
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text:
            _err(report, f"{ibase}.text", "R-5", rule="npc_interaction_text_required",
                 node_id=node_id, text=text)
        if "condition" in item:
            _check_condition(report, item["condition"], f"{ibase}.condition", node_id)
        _check_action_entry(report, item, ibase, node_id, action, refs,
                            is_dialog=False, is_deliver=False)


def _check_dealer(
    report: object, entry: Mapping[str, object], idx: int, node_id: str,
    npc_type: str, refs: _Refs,
) -> None:
    """dealer 子表校验（2b1 §二 DR01-DR02 + P01-P05）：strategy 三策略/兼容迁移 + 牌池结构。"""
    dealer = entry.get("dealer")
    if npc_type == "dealer" and dealer is None:
        # 2b1 F15：type=dealer 时 dealer 必配
        _err(report, f"npc.{idx}.dealer", "R-5", rule="npc_dealer_required",
             node_id=node_id, msg="type=dealer 的 NPC 必须配置 dealer（strategy + pool）")
        return
    if dealer is None:
        return
    if not isinstance(dealer, Mapping):
        _err(report, f"npc.{idx}.dealer", "R-1", rule="npc_dealer_not_object", node_id=node_id)
        return
    base = f"npc.{idx}.dealer"
    strategy = dealer.get("strategy")
    if strategy is None:
        strategy = DEALER_STRATEGY_DEFAULT
    elif not isinstance(strategy, str) or not strategy:
        _err(report, f"{base}.strategy", "R-1", rule="npc_dealer_strategy_invalid",
             node_id=node_id, strategy=strategy, allowed=list(DEALER_STRATEGIES))
    elif strategy not in DEALER_STRATEGIES:
        mapped = DEALER_STRATEGY_LEGACY.get(strategy)
        if mapped is None:
            _err(report, f"{base}.strategy", "R-1", rule="npc_dealer_strategy_invalid",
                 node_id=node_id, strategy=strategy, allowed=list(DEALER_STRATEGIES))
        else:
            # 用户裁决④：旧 first_match/weighted/random 读取兼容 + 迁移提示
            _warn(report, f"{base}.strategy", "Y-1", rule="npc_dealer_strategy_legacy",
                  node_id=node_id, strategy=strategy, mapped=mapped,
                  msg="旧发牌策略 %r 建议迁移为新枚举 rotate/random/condition（%s→%s）"
                      % (strategy, strategy, mapped))
    pool = dealer.get("pool")
    if pool is None:
        pool = []
    if not isinstance(pool, list):
        _err(report, f"{base}.pool", "R-1", rule="npc_dealer_pool_not_list", node_id=node_id)
        return
    if npc_type == "dealer" and not pool:
        # 孤寂卡节奏提示（TC-12 侧：牌池空 = 普通问候不交付，黄提示不拦）
        _warn(report, f"{base}.pool", "Y-5", rule="npc_dealer_pool_empty", node_id=node_id,
              msg="发牌员牌池为空 → 孤寂卡（普通问候不交付），确认是否需要候选事件牌")
    seen: set = set()
    for pi, card in enumerate(pool):
        pbase = f"{base}.pool.{pi}"
        if not isinstance(card, Mapping):
            _err(report, pbase, "R-5", rule="npc_dealer_card_not_object",
                 node_id=node_id, got=type(card).__name__)
            continue
        cid = card.get("id")
        if not isinstance(cid, str) or not cid:
            _err(report, f"{pbase}.id", "R-5", rule="npc_dealer_card_id_required", node_id=node_id)
        elif cid in seen:
            _err(report, f"{pbase}.id", "R-5", rule="npc_dealer_card_id_duplicate",
                 node_id=node_id, card_id=cid)
        else:
            seen.add(cid)
        if "condition" in card:
            _check_condition(report, card["condition"], f"{pbase}.condition", node_id)
        weight = card.get("weight")
        if weight is not None and (not isinstance(weight, (int, float)) or isinstance(weight, bool)
                                   or weight < 0):
            _err(report, f"{pbase}.weight", "R-2", rule="npc_dealer_card_weight_invalid",
                 node_id=node_id, weight=weight)
        once = card.get("once")
        if once is not None and not isinstance(once, bool):
            _err(report, f"{pbase}.once", "R-1", rule="npc_dealer_card_once_invalid",
                 node_id=node_id, once=once)
        deliver = card.get("deliver")
        if deliver is None:
            _err(report, f"{pbase}.deliver", "R-5", rule="npc_dealer_card_deliver_required",
                 node_id=node_id)
        elif not isinstance(deliver, Mapping):
            _err(report, f"{pbase}.deliver", "R-5", rule="npc_dealer_card_deliver_not_object",
                 node_id=node_id, got=type(deliver).__name__)
        else:
            daction = deliver.get("action")
            if not isinstance(daction, str) or daction not in ACTION_TYPES:
                _err(report, f"{pbase}.deliver.action", "R-1", rule="npc_action_invalid",
                     node_id=node_id, action=daction, allowed=list(ACTION_TYPES))
            else:
                _check_action_entry(report, deliver, f"{pbase}.deliver", node_id, daction,
                                    refs, is_dialog=False, is_deliver=True)


def validate_npcs(modules: Mapping[str, object], report: object) -> None:
    """npc 模块专项校验（M4 批次2·路C1：NPCDef 顶层字段 + 子表 + 发牌员）。纯函数，无副作用。

    入口：主 agent 收口时在 check_pack 的 _Checker.run() 尾部调用
        validate_npcs(modules, checker)  （checker._err/_warn 签名与 _emit 一致）
    或自建收集器（暴露 error(module, field, kind, **detail) / warning(...)）。
    返回 None；红拦/黄提示全部经 report 追加（D-01 一次给全量）。

    modules: 模块名（无 .json 后缀）→ parsed JSON（含 "npc" 与可选 "maps"/"quest"/"shop"/
             "items"/"effects"/"statuses"/"marks"/"tutorials"/"enemies"/"settings"）。
             npc 未声明 → 默认放行（细化_3e §2.3）；引用目标模块未声明 → 跳过对应引用检查。

    覆盖验收：
      - TC-01 合法全量 schema 零红拦零黄（顶层 15 字段 + 子表）
      - TC-02 id 唯一 / name 禁空格（· 允许）
      - TC-03 对话树深度：超 max_dialog_depth → 黄提示（软拦，0=不限不拦）
      - TC-08 条件引擎四要素结构校验（var/op 红拦，旧格式/事件未登记黄提示）
      - TC-20 ① 引用不存在红拦（quests/shop_refs/effects/items/map/tutorials/maps.npcs 反向）
             ③ 未使用 NPC 黄提示（maps 已声明 npcs 数组时）
      - 发牌员：strategy 三枚举 + 旧值迁移提示（用户裁决④）/ 牌池结构（P01-P05）/ 孤寂卡空池提示
    """
    if not isinstance(modules, Mapping):
        return
    npcs = modules.get("npc")
    if npcs is None:
        return  # 未声明 npc 模块：默认放行
    if not isinstance(npcs, list):
        _err(report, "npc", "R-5", rule="module_structure", expect="list")
        return

    refs = _Refs()
    refs.map_ids = _id_set(modules, "maps")
    refs.quest_ids = _id_set(modules, "quest")
    refs.shop_ids = _id_set(modules, "shop")
    refs.item_ids = _id_set(modules, "items")
    refs.effect_ids = _effect_union(modules)
    refs.tutorial_ids = _id_set(modules, "tutorials")
    refs.enemy_ids = _id_set(modules, "enemies")
    refs.npc_refs_from_maps = _npc_refs_from_maps(modules)
    max_depth = _max_dialog_depth(modules)

    seen_ids: set = set()
    for idx, entry in enumerate(npcs):
        if not isinstance(entry, Mapping):
            _err(report, f"npc.{idx}", "R-5", rule="entry_not_object",
                 got=type(entry).__name__)
            continue
        node_id = entry.get("id")
        if not isinstance(node_id, str) or not node_id:
            _err(report, f"npc.{idx}.id", "R-5", rule="npc_id_required", idx=idx)
            node_id = f"<npc.{idx}>"
        else:
            if node_id in seen_ids:
                # TC-02 ①：两个 NPC 同 id → 拦截
                _err(report, f"npc.{idx}.id", "R-5", rule="npc_id_duplicate",
                     node_id=node_id)
            else:
                seen_ids.add(node_id)
        # name 必填 + 禁空格（TC-02 ②；允许 ·/Ⅱ）
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            _err(report, f"npc.{idx}.name", "R-5", rule="npc_name_required",
                 node_id=node_id, name=name)
        elif any(c.isspace() for c in name):
            _err(report, f"npc.{idx}.name", "R-1", rule="npc_name_space_forbidden",
                 node_id=node_id, name=name,
                 msg="NPC 名禁空格（命名铁律 L49），允许 ·/Ⅱ（如 铁匠·老周）")
        # icon 必填（2b1 F03）
        icon = entry.get("icon")
        if not isinstance(icon, str) or not icon:
            _err(report, f"npc.{idx}.icon", "R-5", rule="npc_icon_required",
                 node_id=node_id, icon=icon)
        # type 枚举 6 类（2b1 F05：缺省 merchant 不拦）
        npc_type = entry.get("type")
        if npc_type is None:
            npc_type = NPC_TYPE_DEFAULT
        elif not isinstance(npc_type, str) or npc_type not in NPC_TYPES:
            _err(report, f"npc.{idx}.type", "R-1", rule="npc_type_invalid",
                 node_id=node_id, type=npc_type, allowed=list(NPC_TYPES))
        # map 挂点引用（maps 模块存在时硬拦；TC-20 ①）
        map_ref = entry.get("map")
        if map_ref is not None:
            if not isinstance(map_ref, str) or not map_ref:
                _err(report, f"npc.{idx}.map", "R-1", rule="npc_map_invalid",
                     node_id=node_id, map=map_ref)
            elif refs.map_ids is not None and map_ref not in refs.map_ids:
                _err(report, f"npc.{idx}.map", "R-4", rule="npc_map_ref_missing",
                     node_id=node_id, ref=map_ref, registered=sorted(refs.map_ids))
        # desc / visible
        desc = entry.get("desc")
        if desc is not None and not isinstance(desc, str):
            _err(report, f"npc.{idx}.desc", "R-1", rule="npc_desc_invalid",
                 node_id=node_id, desc=desc)
        vis = entry.get("visible")
        if vis is not None and not isinstance(vis, bool):
            _err(report, f"npc.{idx}.visible", "R-1", rule="npc_visible_invalid",
                 node_id=node_id, visible=vis)
        # 6 子表
        _check_dialogues(report, entry, idx, node_id, refs, max_depth)
        _check_interactions(report, entry, idx, node_id, refs)
        if "quests" in entry:
            _check_quest_refs(report, entry["quests"], f"npc.{idx}.quests", node_id, refs)
        if "shop_refs" in entry:
            _check_string_ref_list(report, entry["shop_refs"], f"npc.{idx}.shop_refs", node_id,
                                   refs.shop_ids, "npc_shop_ref_ok", "npc_shop_refs_not_list",
                                   "npc_shop_ref_invalid", "npc_shop_ref_missing", "shop")
        if "intel" in entry:
            intel = entry["intel"]
            if not isinstance(intel, list) or any(not isinstance(i, Mapping) for i in intel):
                _err(report, f"npc.{idx}.intel", "R-1", rule="npc_intel_invalid",
                     node_id=node_id, intel=intel,
                     msg="intel[] 情报条目（与 enemies lore 同构）要为对象数组")
        if "intel_refs" in entry:
            # 【工程补白】3：enemies lore 无 id，仅结构校验
            _check_string_ref_list(report, entry["intel_refs"], f"npc.{idx}.intel_refs", node_id,
                                   None, "npc_intel_ref_ok", "npc_intel_refs_not_list",
                                   "npc_intel_ref_invalid", "npc_intel_ref_missing", "enemies_lore")
        if "tutorials" in entry:
            _check_tutorials(report, entry["tutorials"], f"npc.{idx}.tutorials", node_id, refs)
        _check_dealer(report, entry, idx, node_id, npc_type, refs)

    # 双向校验（定稿 L360/L387/L427）：maps.npcs 引用 NPC 必须存在（红拦 R-4）+ 未使用 NPC（黄提示 Y-3）
    if refs.npc_refs_from_maps is not None:
        for ref in sorted(refs.npc_refs_from_maps):
            if ref not in seen_ids:
                _emit(report, "error", "maps", f"maps.npcs[{ref}]", "R-4",
                      rule="map_npc_ref_missing", ref=ref, registered=sorted(seen_ids),
                      msg="maps.npcs 引用的 NPC %r 不存在（双向互为校验）" % (ref,))
        if seen_ids:
            for nid in sorted(seen_ids):
                if nid not in refs.npc_refs_from_maps:
                    # TC-20 ③：某 NPC 从未被任何地图引用 → 黄提示（只建议不限制）
                    _warn(report, f"npc[{nid}]", "Y-3", rule="npc_unused",
                          node_id=nid, msg="未使用 NPC %r（未被任何地图 npcs 引用）" % (nid,))


__all__ = [
    "NPCDef",
    "DialogOptionDef",
    "DialogueDef",
    "InteractionDef",
    "QuestRefDef",
    "DealerPoolCardDef",
    "DealerDef",
    "parse_npcs",
    "validate_npcs",
    "NPC_TYPES",
    "NPC_TYPE_NAMES",
    "NPC_TYPE_DEFAULT",
    "ACTION_TYPES",
    "DIALOGUE_ACTION_SUBSET",
    "DEALER_STRATEGIES",
    "DEALER_STRATEGY_DEFAULT",
    "DEALER_STRATEGY_LEGACY",
    "REPEAT_TYPES",
    "MENU_MAX_OPTIONS",
    "DEFAULT_MAX_DIALOG_DEPTH",
    "COND_OPERATORS",
]
