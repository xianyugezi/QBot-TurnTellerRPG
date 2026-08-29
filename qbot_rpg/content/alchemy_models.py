"""M8 炼金数据层 · 独立模块（路 0A）：recipe/traits/proficiency 数据模型类 + 专项校验器。

文件名：alchemy_models.py
创建时间：2026-08-29
作者：Hermes 子agent-0A（并发同仓：仅新建本文件 + tests/unit/test_alchemy_models.py）

功能描述：
  - RecipeDef / TraitDef / ProficiencyDef 三个 frozen dataclass（extends BaseDef，from_entry
    轻量容错解析，照 shop_models.ShopDef 模式：防御性读取访问器，不伪造默认值，兜底归校验/引擎侧）。
  - validate_recipes(modules, report) / validate_traits(modules, report) /
    validate_proficiency(modules, report) 三个纯函数（(modules, report) 鸭子类型，
    report 优先 error/warning/note，回退 _err/_warn/_note，照 shop_models._emit 模式）。
  - ALCHEMY_ELEMENTS 8 元素注册表（content 层常量，G0 单向依赖禁止 import core/damage）。

依据：
  - docs/m8_contract_数据与校验.md §一 recipe.json 字段表（1.1 逐字段 + 1.2 kind=upgrade 四实例）、
    §二 traits.json 字段表（2.1 TSC-04~10 + 2.2 JSON 样例）、
    §三 proficiency.json 字段表（3.1 逐行）、
    §六 6.2 校验器规则清单（REC-01~16 / TRT-01~09 / PRF-01~10，级别：红拦=error/黄=warning）。
  - 炼金定稿 v2.3 §10（L348-424）+ 细化_2c4c/2c4e（修订版）+ 细化_2c5a + 用户拍板①②③④⑤。
  - 模式参考：qbot_rpg/content/shop_models.py（validate_shops 签名 + _emit/_err/_warn 辅助 +
    引用靶缺失降级惯例）+ qbot_rpg/content/validator.py L1692（_check_chain_cycle DFS 成环思路）。

【工程补白】（契约/定稿未显式定义处的实现口径，显式标注供审查，不冒充定稿行号）：
  1. ALCHEMY_ELEMENTS：content 层 8 元素注册表常量，键集与 qbot_rpg/core/damage.py
     DEFAULT_ELEMENTS 一致（earth/fire/water/wind/thunder/crystal/moon/void，已读该文件确认键集，
     但不 import core——G0 单向依赖：content → data，禁止 content → core）。契约 REC-05 归属批0 在
     formula.json element 表登记，本模块以常量镜像提供校验基准（formula 段未接线时仍可校验）。
  2. evolve_to.condition.source 枚举：契约仅言「来源枚举（进化线逐级计次）」（定稿 L357/L200 /
     CASC-05「低阶配方炼金产出 N 次，合成不计」），未给出枚举值。本实现取 EVOLVE_SOURCES =
     ("alchemy", "synthesis")（炼金产出计次 / 合成产出不计），显式补充，供审查（REC-09 红拦）。
  3. PRF-01 jobs 引用降级：jobs 职业引擎 M13 未落地，仅当 modules 含 jobs 模块（list 且有 id）时做
     id 存在性硬拦；缺 jobs 模块时降级为 note（信息级），避免无 jobs.json 的合法包被误拦。
  4. 跨模块引用（items/effects）存在性：当 modules 缺对应模块（非 list）时降级为 note 不硬拦，
     对齐既有校验器惯例（shop_models §2.3 默认放行）；仅当目标模块存在时才红拦。
  5. REC-14 synth_allowed：规则清单（6.2）与字段表（1.1）口径相反——6.2 写「深度配方设 false→提示」，
     1.1 写「改 true 提示将绕过深度炼金玩法」。本实现按 6.2 规则清单为准：synth_allowed 非布尔 →
     黄提示（类型）；synth_allowed=false → 黄提示「深度配方…绕过深度炼金玩法确认？」（只提示不拦）。
  6. job_tier_map 区间格式：契约仅给「见习 1-5 … 王 51+」语义。本实现兼容两种写法：2 元数组
     [lo, hi] 或对象 {min, max}（max/lo 可缺省→None=+∞，承接「王 51+」开口区间）；区间单调 =
     相邻称号 lo_后 > hi_前（不重叠递增）。job_tier_map=="settings"（继承 settings）时跳过。
  7. TRT-08 快照/存档引用冗余：data 层无消费者上下文无法核验快照引用，落为「特性缺显式 name
     （BaseDef 回退 id）或 name==id 时黄提示：快照/存档须冗余存 ID+名称，删配置降级显示才不报错
     （STO-05/L511）」。TRT-07 负责 name 空/缺失红拦，TRT-08 负责冗余性提示（两者语义不同）。
  8. TRT-04 互斥组校验的「同特性不登记进多个互斥组」：group 字段表为单 string，多组登记只能以
     list 形态出现 → group 为 list（或多值）即红拦；另 group==自身 id（组内自引用）红拦；
     group 非空字符串约束（组内成员存在性）。
  9. effects 原子动作引用双形态解析：effects 条目可为字符串（效果 ID）或对象（取 type 键为效果 ID，
     对齐 traits.json §2.2 样例 {type,element,value}）；引用对 effects id 集判定（REC-06/TRT-03）。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；纯函数；确定性；
【工程补白】显式标注；文件头标注依据；不 git commit。仅依赖 qbot_rpg.content.models.BaseDef。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Set, Tuple

from qbot_rpg.content.models import BaseDef

# =====================================================================================
# 常量 / 枚举注册表（契约 §一/§二/§三 + 拍板①②③④⑤ + 【工程补白】）
# =====================================================================================

# 【工程补白】1：8 元素注册表（content 层常量；键集与 damage.DEFAULT_ELEMENTS 一致，不 import core）
ALCHEMY_ELEMENTS: Mapping[str, str] = {
    "earth": "地",
    "fire": "火",
    "water": "水",
    "wind": "风",
    "thunder": "雷",
    "crystal": "晶",
    "moon": "月",
    "void": "无",
}

# 品质档键集（拍板②：只允许 common/uncommon/rare/legendary；中文 普通/精良/史诗/传说）
QUALITY_TIERS: Tuple[str, ...] = ("common", "uncommon", "rare", "legendary")
QUALITY_TIER_NAMES: Dict[str, str] = {
    "common": "普通",
    "uncommon": "精良",
    "rare": "史诗",
    "legendary": "传说",
}

# ---- recipe（契约 §一 1.1 / 定稿 L354-357）----
RECIPE_KINDS: Tuple[str, ...] = ("craft", "combine", "upgrade")
RECIPE_LEVEL_MIN: int = 1
RECIPE_LEVEL_MAX: int = 99
RECIPE_SLOTS_MIN: int = 2
RECIPE_SLOTS_MAX: int = 10
RECIPE_TRAITS_INHERIT_MIN: int = 1
RECIPE_TRAITS_INHERIT_MAX: int = 3
# id 命名禁保留字符（REC-16/TRT-01【工程补白：对齐定稿 L12 分隔符规范 / L58 命名铁律】）
RESERVED_ID_CHARS: Tuple[str, ...] = ("*", ",", "=", "+")
# 【工程补白】2：evolve_to.condition.source 来源枚举（进化线逐级计次；定稿未给枚举值）
EVOLVE_SOURCES: Tuple[str, ...] = ("炼金产出", "合成产出")

# ---- traits（契约 §二 2.1 / 定稿 L373-376）----
TRAIT_RARITIES: Tuple[str, ...] = ("normal", "super")
TRAIT_SOURCES: Tuple[str, ...] = ("素材", "成品", "金色素材")

# ---- proficiency（契约 §三 3.1 / 细化_2c5a）----
DEFAULT_TIER_NAMES: Tuple[str, ...] = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")
# 【补白数值】成长曲线默认 7 档（定稿仅要求「成长曲线」字段存在，键名/数值为细化_2c5a 补白）
DEFAULT_JOB_RANK_LEVELS: Tuple[int, ...] = (0, 100, 300, 700, 1500, 3000, 6000)
EXP_SOURCE_KEYS: Tuple[str, ...] = ("craft", "gather", "combat")
TITLE_SOURCES: Tuple[str, ...] = ("king", "contest", "achievement", "custom")
SP_PANEL_FIELDS: Tuple[str, ...] = ("id", "name", "cost", "repeatable", "max_repeat", "desc")
DEFAULT_ENERGY: Mapping[str, object] = {
    "enabled": False,
    "max_by_tier": [5, 8, 10, 12, 15, 18, 20],
    "regen_sec": 1800,
}
# job_tier_map 默认 = "settings"（继承 settings.json，契约 §三 3.1）
JOB_TIER_MAP_DEFAULT: str = "settings"


# =====================================================================================
# Def 类型（风格对齐 ShopDef：BaseDef + 字段访问器；防御性读取，不伪造默认值）
# =====================================================================================


@dataclass(frozen=True)
class RecipeDef(BaseDef):
    """recipe.json 条目（契约 §一 1.1：id/name/kind/level/synth_allowed/master_only/materials/
    inputs/output/cost/slots/element_req/effects/traits_inherit/catalyst/combine_from/evolve_to/
    pp_budget）。

    id/name 由 BaseDef 承载（from_entry 冗余镜像 raw），其余字段访问器见下。
    双 schema 口径：kind∈{craft,combine} 用 materials[{id,count}]；kind=upgrade 用
    inputs[{item,count}] + output{item,count}（与 materials 互斥）。
    【工程补白】pp_budget 为定稿表 L353-358 未单列的可选字段（落 traits_inherit 段附近）。
    """

    # ---- 数值/字符串/映射/列表辅助（与 ShopDef 同风格）----
    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _int(self, key: str) -> Optional[int]:
        v = self.raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def _bool(self, key: str) -> Optional[bool]:
        v = self.raw.get(key)
        return v if isinstance(v, bool) else None

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    def _entries(self, key: str) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get(key)
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    # ---- 顶层字段访问器 ----
    @property
    def recipe_kind(self) -> Optional[str]:
        """三类配方：craft/combine/upgrade（REC-01 枚举红拦）。

        命名 recipe_kind 而非 kind：BaseDef.kind 为注册表 kind（\"recipe\"），
        不设同名访问器（同 ActionDef 口径，见 models.py ActionDef 注释）。
        """
        return self._str("kind")

    @property
    def level(self) -> Optional[int]:
        """配方等级 1-99（REC-02；准入判定 job_tier_map 区间，synth_exp=等级×1）。"""
        return self._int("level")

    @property
    def synth_allowed(self) -> Optional[bool]:
        """防「合成绕过深度」字段（定稿 L505；深度配方默认 false，REC-14 黄提示）。"""
        return self._bool("synth_allowed")

    @property
    def master_only(self) -> Optional[bool]:
        """大师独占配方（REC-15 值类型黄提示）。"""
        return self._bool("master_only")

    @property
    def materials(self) -> Tuple[Mapping[str, object], ...]:
        """craft/combine 素材数组 [{id,count}]（REC-03；与 upgrade inputs/output 互斥）。"""
        return self._entries("materials")

    @property
    def inputs(self) -> Tuple[Mapping[str, object], ...]:
        """upgrade N 入 [{item,count}]（REC-11）。"""
        return self._entries("inputs")

    @property
    def output(self) -> Mapping[str, object]:
        """upgrade 1 出 {item,count}（REC-11：item 引用存在、count=1）。"""
        return self._mapping("output")

    @property
    def output_item(self) -> Optional[str]:
        v = self.output.get("item")
        return v if isinstance(v, str) else None

    @property
    def output_count(self) -> Optional[int]:
        v = self.output.get("count")
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def cost(self) -> Mapping[str, object]:
        """{coins, gem} 非负整数（REC-04；gem 可缺省=0；复制费基准=cost.coins 拍板④）。"""
        return self._mapping("cost")

    def cost_value(self, key: str) -> Optional[int]:
        v = self.cost.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def slots(self) -> Optional[int]:
        """投料槽位上限（默认 4，可配 2-10；REC-13 黄提示）。"""
        return self._int("slots")

    @property
    def element_req(self) -> Mapping[str, object]:
        """{元素: [{阈值, 效果}]}（REC-05：元素∈8 注册表、阈值≥0、效果引用存在）。"""
        return self._mapping("element_req")

    @property
    def effects(self) -> Tuple[str, ...]:
        """原子动作 ID 列表（REC-06；字符串条目或对象 type 键双形态，见 _effect_ids）。"""
        return _effect_ids(self.raw.get("effects"))

    @property
    def traits_inherit(self) -> Optional[int]:
        """可继承特性位数（默认 1，可配 1-3；REC-12 黄提示）。"""
        return self._int("traits_inherit")

    @property
    def catalyst(self) -> Tuple[str, ...]:
        """触媒 items 引用列表（REC-07：引用 items type=触媒）。"""
        v = self.raw.get("catalyst")
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    @property
    def combine_from(self) -> Tuple[str, ...]:
        """组合合成输入配方引用（REC-08：引用 recipe 存在）。"""
        v = self.raw.get("combine_from")
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    @property
    def evolve_to(self) -> Mapping[str, object]:
        """{id, condition:{count, source}}（REC-09/10：目标引用、count≥1、source 枚举、无环）。"""
        return self._mapping("evolve_to")

    @property
    def evolve_to_id(self) -> Optional[str]:
        v = self.evolve_to.get("id")
        return v if isinstance(v, str) else None

    @property
    def evolve_to_condition(self) -> Mapping[str, object]:
        v = self.evolve_to.get("condition")
        return v if isinstance(v, Mapping) else {}

    @property
    def pp_budget(self) -> Optional[int]:
        """配方卡 PP 上限（【工程补白】字段，int ≥0；定稿 L414 pp_cost 计价联动）。"""
        return self._int("pp_budget")


@dataclass(frozen=True)
class TraitDef(BaseDef):
    """traits.json 条目（契约 §二 2.1：id/name/rarity/effects/group/repeatable/source +
    gold_slot_exclusive 可选）。

    id/name 由 BaseDef 承载；rarity ∈ normal/super；source ∈ 素材/成品/金色素材。
    gold_slot_exclusive 为 rarity=super 第 4 位独占可配项（TRT-09，布尔）。
    """

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _bool(self, key: str) -> Optional[bool]:
        v = self.raw.get(key)
        return v if isinstance(v, bool) else None

    @property
    def rarity(self) -> Optional[str]:
        """normal（默认）/super（金色超特性，PP 消耗翻倍，TSC-11）。"""
        return self._str("rarity")

    @property
    def effects(self) -> Tuple[str, ...]:
        """L0 原子动作 ID 列表（TRT-03；字符串或对象 type 双形态）。"""
        return _effect_ids(self.raw.get("effects"))

    @property
    def group(self) -> object:
        """互斥组（单 string；组内最多 1 项，TRT-04 红拦）。"""
        return self.raw.get("group")

    @property
    def repeatable(self) -> Optional[bool]:
        """false=不可多次继承/成品不重复；true=允许重复（TRT-05 布尔黄提示）。"""
        return self._bool("repeatable")

    @property
    def source(self) -> Optional[str]:
        """素材/成品/金色素材（TRT-06 枚举红拦；决定进入哪个可继承池）。"""
        return self._str("source")

    @property
    def gold_slot_exclusive(self) -> Optional[bool]:
        """rarity=super 第 4 位独占可配项（TRT-09 布尔黄提示）。"""
        return self._bool("gold_slot_exclusive")


@dataclass(frozen=True)
class ProficiencyDef(BaseDef):
    """proficiency.json 条目（契约 §三 3.1：id/tier_names/job_rank_levels/exp_sources/
    sp_per_level/sp_panel/energy/job_tier_map/titles）。

    管「职业的等级尺子」（7 级默认名/成长曲线/SP 面板/能量条，通用框架机制·代码层）。
    id 对应 jobs.json 职业（生活职业，如 alchemy；PRF-01）。
    """

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _int(self, key: str) -> Optional[int]:
        v = self.raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def _bool(self, key: str) -> Optional[bool]:
        v = self.raw.get(key)
        return v if isinstance(v, bool) else None

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    def _str_list(self, key: str) -> Tuple[str, ...]:
        v = self.raw.get(key)
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    def _int_list(self, key: str) -> Tuple[int, ...]:
        v = self.raw.get(key)
        return tuple(x for x in v if isinstance(x, int) and not isinstance(x, bool)) \
            if isinstance(v, list) else ()

    def _entries(self, key: str) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get(key)
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    # ---- 顶层字段访问器 ----
    @property
    def tier_names(self) -> Tuple[str, ...]:
        """7 级称号可改名（内容包自定义；长度 ≥2 且与 job_rank_levels 一一对应，PRF-02）。"""
        return self._str_list("tier_names")

    @property
    def job_rank_levels(self) -> Tuple[int, ...]:
        """成长曲线累计熟练阈值（单调递增、首项=0，PRF-03；【补白数值】默认 7 档）。"""
        return self._int_list("job_rank_levels")

    @property
    def exp_sources(self) -> Mapping[str, object]:
        """三来源经验倍率 {craft/gather/combat: ≥0}（PRF-04 红拦）。"""
        return self._mapping("exp_sources")

    @property
    def sp_per_level(self) -> Optional[int]:
        """升级获得 SP 点数（≥0，PRF-05 红拦）。"""
        return self._int("sp_per_level")

    @property
    def sp_panel(self) -> Tuple[Mapping[str, object], ...]:
        """分支自选解锁项 {id,name,cost,repeatable,max_repeat,desc}（PRF-06 黄提示）。"""
        return self._entries("sp_panel")

    @property
    def energy(self) -> Mapping[str, object]:
        """可选软节奏模块 {enabled,max_by_tier,regen_sec}（PRF-07 黄提示；enabled 默认 false）。"""
        return self._mapping("energy")

    @property
    def energy_enabled(self) -> Optional[bool]:
        v = self.energy.get("enabled")
        return v if isinstance(v, bool) else None

    @property
    def energy_max_by_tier(self) -> Tuple[int, ...]:
        v = self.energy.get("max_by_tier")
        return tuple(x for x in v if isinstance(x, int) and not isinstance(x, bool)) \
            if isinstance(v, list) else ()

    @property
    def energy_regen_sec(self) -> Optional[int]:
        v = self.energy.get("regen_sec")
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @property
    def job_tier_map(self) -> object:
        """称号→配方等级区间（主落点 settings；默认 "settings" 继承；PRF-08 红拦）。"""
        return self.raw.get("job_tier_map")

    @property
    def titles(self) -> Tuple[Mapping[str, object], ...]:
        """通用称号注册表 {id,name,icon,source,desc}（PRF-09/10）。"""
        return self._entries("titles")


# =====================================================================================
# 效果原子动作 ID 双形态解析（REC-06/TRT-03/REC-05 element_req 效果）
# =====================================================================================
def _effect_ids(raw: object) -> Tuple[str, ...]:
    """effects 数组 → 效果 ID 元组：字符串条目按原样，对象条目取 type 键（对齐 traits.json §2.2
    样例 {type,element,value}）。非数组/非字符串/无 type → 跳过（引用存在性交校验器红拦）。"""
    if not isinstance(raw, list):
        return ()
    out: List[str] = []
    for e in raw:
        if isinstance(e, str):
            if e:
                out.append(e)
        elif isinstance(e, Mapping):
            t = e.get("type")
            if isinstance(t, str) and t:
                out.append(t)
    return tuple(out)


# =====================================================================================
# 收集器鸭子类型（照 shop_models._emit：优先 report.error/warning/note，回退 _err/_warn/_note）
# =====================================================================================
def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
    fn = getattr(report, method, None)
    if not callable(fn):
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", "alchemy", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", "alchemy", field, kind, **detail)


def _note(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "note", "alchemy", field, kind, **detail)


# =====================================================================================
# 引用靶收集（模块缺失/非 list/无 id → None：调用方跳过红拦，降级 note——【工程补白】4）
# =====================================================================================
def _id_set(modules: Mapping[str, object], key: str) -> Optional[Set[str]]:
    data = modules.get(key)
    if not isinstance(data, list):
        return None
    ids: Set[str] = set()
    for e in data:
        if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
            ids.add(e["id"])
    return ids if ids else None


def _items_type_map(modules: Mapping[str, object]) -> Optional[Dict[str, str]]:
    """items 模块 id → type 映射（REC-07 触媒判定用）；items 缺失/非 list → None。"""
    data = modules.get("items")
    if not isinstance(data, list):
        return None
    out: Dict[str, str] = {}
    for e in data:
        if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
            t = e.get("type")
            if isinstance(t, str):
                out[e["id"]] = t
    return out


def _same_module_id_set(entries: object) -> Optional[Set[str]]:
    """同模块（recipe）条目 id 集：从正被校验的 list 收集，恒可用。"""
    if not isinstance(entries, list):
        return None
    ids: Set[str] = set()
    for e in entries:
        if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
            ids.add(e["id"])
    return ids or None


# =====================================================================================
# id 命名保留字符（REC-16 / TRT-01：禁 `* , = +` 空格）
# =====================================================================================
def _id_has_reserved(raw_id: object) -> bool:
    if not isinstance(raw_id, str):
        return False
    for ch in RESERVED_ID_CHARS:
        if ch in raw_id:
            return True
    return any(c.isspace() for c in raw_id)


# =====================================================================================
# validate_recipes（契约 §六 6.2：REC-01 ~ REC-16）
# =====================================================================================
# 级别：红拦=error / 黄=warning；引用靶缺失降级 note（【工程补白】4）。
# 规则速览：
#   REC-01 kind 枚举；REC-02 level ∈[1,99]；REC-03 materials 引用 items+count≥1；
#   REC-04 cost 非负；REC-05 element_req（元素注册表/阈值/效果引用）；REC-06 effects 引用；
#   REC-07 catalyst 引用 items type=触媒；REC-08 combine_from 引用 recipe；
#   REC-09 evolve_to（id 引用/count≥1/source 枚举）；REC-10 进化线无环（自写 DFS）；
#   REC-11 upgrade inputs/output 引用 + output.count=1 + 与 materials 互斥；
#   REC-12 traits_inherit ∈1-3；REC-13 slots ∈2-10；REC-14 synth_allowed 布尔（深度配方黄提示）；
#   REC-15 master_only 布尔；REC-16 id 禁保留字符。


def _check_recipe_cost(report: object, recipe: Mapping[str, object], node_id: str) -> None:
    """REC-04：cost.coins/cost.gem 非负整数（gem 可缺省=0）。"""
    cost = recipe.get("cost")
    if cost is None:
        return  # 可配缺省
    if not isinstance(cost, Mapping):
        _err(report, f"recipe.{node_id}.cost", "R-5", rule="REC-04",
             node_id=node_id, got=type(cost).__name__,
             msg="cost 要填对象 {coins, gem}（非负整数；gem 可缺省=0）")
        return
    for key in ("coins", "gem"):
        if key not in cost:
            continue
        v = cost[key]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            _err(report, f"recipe.{node_id}.cost.{key}", "R-5", rule="REC-04",
                 node_id=node_id, key=key, value=v,
                 msg="cost.%s 需 ≥0 整数（gem 可缺省=0；复制费基准=cost.coins 拍板④）" % key)


def _check_recipe_ref_entries(report: object, entries: object, ref_key: str, rule: str,
                              field_base: str, node_id: str, item_ids: Optional[Set[str]]) -> None:
    """材料/输入条目通用引用校验：[{<ref_key>: id, count: N}]。

    红拦：条目非对象；ref_key 缺失/非空串；count 非 ≥1 整数；item_ids 存在且 id 引用不存在。
    item_ids 缺失（items 未接线）→ 引用存在性降级 note（【工程补白】4），结构校验仍红拦。
    """
    if not isinstance(entries, list):
        return
    for i, e in enumerate(entries):
        field = f"{field_base}.{i}"
        if not isinstance(e, Mapping):
            _err(report, field, "R-5", rule=rule, node_id=node_id, got=type(e).__name__,
                 msg="条目需对象 {id|item, count}")
            continue
        rid = e.get(ref_key)
        if not isinstance(rid, str) or not rid:
            _err(report, f"{field}.{ref_key}", "R-5", rule=rule, node_id=node_id, value=rid,
                 msg="%s 必填（items.json 引用）" % ref_key)
        elif item_ids is not None and rid not in item_ids:
            _err(report, f"{field}.{ref_key}", "R-5", rule=rule, node_id=node_id, ref=rid,
                 ref_target="items", msg="%s %r 在 items.json 中不存在" % (ref_key, rid))
        count = e.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            _err(report, f"{field}.count", "R-5", rule=rule, node_id=node_id, count=count,
                 msg="count 需 ≥1 整数")


def _check_recipe_evolve(report: object, recipe: Mapping[str, object], node_id: str,
                         recipe_ids: Optional[Set[str]]) -> None:
    """REC-09：evolve_to{id, condition:{count, source}} 结构校验。"""
    et = recipe.get("evolve_to")
    if et is None:
        return
    if not isinstance(et, Mapping):
        _err(report, f"recipe.{node_id}.evolve_to", "R-5", rule="REC-09",
             node_id=node_id, got=type(et).__name__,
             msg="evolve_to 要填对象 {id, condition:{count, source}}")
        return
    tid = et.get("id")
    if not isinstance(tid, str) or not tid:
        _err(report, f"recipe.{node_id}.evolve_to.id", "R-5", rule="REC-09",
             node_id=node_id, value=tid, msg="evolve_to.id 必填（目标配方引用）")
    elif recipe_ids is not None and tid not in recipe_ids:
        _err(report, f"recipe.{node_id}.evolve_to.id", "R-5", rule="REC-09",
             node_id=node_id, ref=tid, ref_target="recipe",
             msg="evolve_to.id %r 在 recipe.json 中不存在" % (tid,))
    cond = et.get("condition")
    if cond is not None:
        if not isinstance(cond, Mapping):
            _err(report, f"recipe.{node_id}.evolve_to.condition", "R-5", rule="REC-09",
                 node_id=node_id, got=type(cond).__name__,
                 msg="evolve_to.condition 要填对象 {count, source}")
        else:
            count = cond.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                _err(report, f"recipe.{node_id}.evolve_to.condition.count", "R-5",
                     rule="REC-09", node_id=node_id, count=count,
                     msg="condition.count 需 ≥1（低阶炼金产出 N 次，合成不计）")
            src = cond.get("source")
            if src is not None and (not isinstance(src, str) or src not in EVOLVE_SOURCES):
                _err(report, f"recipe.{node_id}.evolve_to.condition.source", "R-5",
                     rule="REC-09", node_id=node_id, source=src, allowed=list(EVOLVE_SOURCES),
                     msg="condition.source %r 不认识（%s；【工程补白】来源枚举：炼金/合成计次）"
                         % (src, "/".join(EVOLVE_SOURCES)))


def _check_recipe_evolve_cycle(report: object, recipes: list, node_id_map: Dict[str, str]) -> None:
    """REC-10：进化线无环（自实现 DFS，照 validator._check_chain_cycle L1692 思路）。

    边 = recipe.evolve_to.id（有向）。成环（含自环）→ 红拦一次（沿栈提取环路径）。
    进化为可选链：仅对声明了 evolve_to 的配方建边；目标 id 不在本模块 → 不建边（REC-09 已红拦）。
    """
    adj: Dict[str, List[str]] = {}
    for e in recipes:
        if not isinstance(e, Mapping):
            continue
        eid = e.get("id")
        if not isinstance(eid, str) or not eid:
            continue
        et = e.get("evolve_to")
        if isinstance(et, Mapping):
            tid = et.get("id")
            if isinstance(tid, str) and tid:
                adj.setdefault(eid, []).append(tid)
    if not adj:
        return
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {}
    for n in adj:
        color.setdefault(n, WHITE)
        for v in adj[n]:
            color.setdefault(v, WHITE)
    reported = False

    def dfs(u: str, stack: List[str]) -> Optional[List[str]]:
        nonlocal reported
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, []):
            if color.get(v) == GRAY:
                reported = True
                i = stack.index(v)
                cycle = stack[i:] + [v]
                node = node_id_map.get(u, u)
                _err(report, f"recipe.{node}.evolve_to.id", "R-5", rule="REC-10",
                     node_id=node, cycle=cycle,
                     msg="进化线成环 %s（低阶→目标配方，须无环，定稿 §13/细化_2c4c §2.2）"
                         % "→".join(cycle))
                return cycle
            if color.get(v) == WHITE:
                res = dfs(v, stack)
                if res is not None:
                    return res
        color[u] = BLACK
        stack.pop()
        return None

    for n in adj:
        if color.get(n) == WHITE and not reported:
            dfs(n, [])


def _check_recipe(report: object, recipe: Mapping[str, object], node_id: str,
                  recipe_ids: Optional[Set[str]], item_ids: Optional[Set[str]],
                  items_type: Optional[Dict[str, str]], effect_ids: Optional[Set[str]],
                  seen_ids: Set[str]) -> None:
    """单配方校验（REC-01 ~ REC-16 全量；红拦=error / 黄=warning）。"""
    # REC-16：id 禁保留字符 `* , = +` 空格（【工程补白】对齐定稿 L12/L58）
    rid = recipe.get("id")
    if isinstance(rid, str):
        if _id_has_reserved(rid):
            _err(report, f"recipe.{node_id}.id", "R-5", rule="REC-16",
                 node_id=node_id, id=rid, chars=list(RESERVED_ID_CHARS),
                 msg="配方 id 禁保留字符 `* , = +` 与空格（对齐定稿 L12/L58 分隔符规范）")
        if rid in seen_ids:
            _err(report, f"recipe.{node_id}.id", "R-5", rule="REC-01",
                 node_id=node_id, id=rid, msg="配方 id %r 重复（recipe_lib 全局唯一）" % rid)
        seen_ids.add(rid)

    # REC-01：kind 枚举 {craft, combine, upgrade}
    rkind = recipe.get("kind")
    if not isinstance(rkind, str) or rkind not in RECIPE_KINDS:
        _err(report, f"recipe.{node_id}.kind", "R-5", rule="REC-01",
             node_id=node_id, value=rkind, allowed=list(RECIPE_KINDS),
             msg="配方 kind %r 不认识（三类：%s）" % (rkind, "/".join(RECIPE_KINDS)))
        return  # kind 决定后续双 schema 口径，非法即中止本条目其余结构校验（避免噪音）

    # REC-02：level ∈ [1,99] 整数
    level = recipe.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not (
            RECIPE_LEVEL_MIN <= level <= RECIPE_LEVEL_MAX):
        _err(report, f"recipe.{node_id}.level", "R-5", rule="REC-02",
             node_id=node_id, level=level,
             msg="配方 level 需 %s-%s 整数（准入判定 job_tier_map 区间）"
                 % (RECIPE_LEVEL_MIN, RECIPE_LEVEL_MAX))

    # 双 schema 口径（契约 §一 1.1 注：upgrade 用 inputs/output，与 materials 互斥）
    is_upgrade = rkind == "upgrade"
    if is_upgrade:
        # REC-11：upgrade 实例 inputs/output 引用 + output.count=1 + 与 materials 互斥
        if "materials" in recipe:
            _err(report, f"recipe.{node_id}.materials", "R-5", rule="REC-11",
                 node_id=node_id, msg="kind=upgrade 实例不得写 materials（与 inputs/output 互斥）")
        _check_recipe_ref_entries(report, recipe.get("inputs"), "item", "REC-11",
                                  f"recipe.{node_id}.inputs", node_id, item_ids)
        out = recipe.get("output")
        if out is None:
            _err(report, f"recipe.{node_id}.output", "R-5", rule="REC-11",
                 node_id=node_id, msg="kind=upgrade 实例必填 output {item, count=1}")
        elif not isinstance(out, Mapping):
            _err(report, f"recipe.{node_id}.output", "R-5", rule="REC-11",
                 node_id=node_id, got=type(out).__name__, msg="output 要填对象 {item, count}")
        else:
            oitem = out.get("item")
            if not isinstance(oitem, str) or not oitem:
                _err(report, f"recipe.{node_id}.output.item", "R-5", rule="REC-11",
                     node_id=node_id, value=oitem, msg="output.item 必填（items.json 引用）")
            elif item_ids is not None and oitem not in item_ids:
                _err(report, f"recipe.{node_id}.output.item", "R-5", rule="REC-11",
                     node_id=node_id, ref=oitem, ref_target="items",
                     msg="output.item %r 在 items.json 中不存在" % (oitem,))
            ocount = out.get("count")
            if ocount != 1:
                _err(report, f"recipe.{node_id}.output.count", "R-5", rule="REC-11",
                     node_id=node_id, count=ocount, msg="output.count 必须 =1（N 入→1 出）")
    else:
        # REC-03：craft/combine materials[{id,count}] 引用 items + count ≥1
        # 双 schema 口径【收口裁决 2026-08-29】：契约 §1.1 仅「upgrade 必填 output」，
        # 未禁 craft/combine 写 output——output 为 craft/combine 的产物声明（0C fixtures 用法），
        # 校验：output.item 引用存在 + count ≥1 整数；inputs 属 upgrade 专属，craft/combine 禁写。
        if "inputs" in recipe:
            _err(report, f"recipe.{node_id}.inputs", "R-5", rule="REC-11",
                 node_id=node_id,
                 msg="kind=%s 用 materials，不得写 inputs（inputs/output 为 upgrade 专属）" % rkind)
        out = recipe.get("output")
        if out is not None:
            if not isinstance(out, Mapping):
                _err(report, f"recipe.{node_id}.output", "R-5", rule="REC-11",
                     node_id=node_id, got=type(out).__name__, msg="output 要填对象 {item, count}")
            else:
                oitem = out.get("item")
                if not isinstance(oitem, str) or not oitem:
                    _err(report, f"recipe.{node_id}.output.item", "R-5", rule="REC-11",
                         node_id=node_id, value=oitem, msg="output.item 必填（items.json 引用）")
                elif item_ids is not None and oitem not in item_ids:
                    _err(report, f"recipe.{node_id}.output.item", "R-5", rule="REC-11",
                         node_id=node_id, ref=oitem, ref_target="items",
                         msg="output.item %r 在 items.json 中不存在" % (oitem,))
                ocount = out.get("count")
                if not isinstance(ocount, int) or isinstance(ocount, bool) or ocount < 1:
                    _err(report, f"recipe.{node_id}.output.count", "R-5", rule="REC-11",
                         node_id=node_id, count=ocount, msg="output.count 需 ≥1 整数")
        _check_recipe_ref_entries(report, recipe.get("materials"), "id", "REC-03",
                                  f"recipe.{node_id}.materials", node_id, item_ids)
    if item_ids is None and ("materials" in recipe or "output" in recipe or is_upgrade):
        _note(report, f"recipe.{node_id}", "N-1", rule="REC-11" if is_upgrade else "REC-03",
              node_id=node_id, ref_target="items",
              msg="【工程补白】items 模块未接线，材料/输入/输出 items 引用存在性未核（降级 note）")

    # REC-04：cost
    _check_recipe_cost(report, recipe, node_id)

    # REC-05：element_req {元素: [{阈值, 效果}]}
    er = recipe.get("element_req")
    if er is not None:
        if not isinstance(er, Mapping):
            _err(report, f"recipe.{node_id}.element_req", "R-5", rule="REC-05",
                 node_id=node_id, got=type(er).__name__,
                 msg="element_req 要填对象 {元素: [{阈值, 效果}]}")
        else:
            for elem, v in er.items():
                if elem not in ALCHEMY_ELEMENTS:
                    _err(report, f"recipe.{node_id}.element_req.{elem}", "R-5", rule="REC-05",
                         node_id=node_id, element=elem, allowed=sorted(ALCHEMY_ELEMENTS),
                         msg="元素 %r 不在 8 元素注册表（%s；地水火风雷晶月无）"
                             % (elem, "/".join(sorted(ALCHEMY_ELEMENTS))))
                    continue
                if not isinstance(v, list):
                    _err(report, f"recipe.{node_id}.element_req.{elem}", "R-5", rule="REC-05",
                         node_id=node_id, element=elem, got=type(v).__name__,
                         msg="元素 %r 的阈值-效果表需数组 [{阈值, 效果}]" % elem)
                    continue
                for j, t in enumerate(v):
                    tf = f"recipe.{node_id}.element_req.{elem}.{j}"
                    if not isinstance(t, Mapping):
                        _err(report, tf, "R-5", rule="REC-05", node_id=node_id,
                             got=type(t).__name__, msg="阈值-效果条目需对象 {阈值, 效果}")
                        continue
                    thr = t.get("阈值", t.get("threshold"))
                    if not isinstance(thr, (int, float)) or isinstance(thr, bool) or thr < 0:
                        _err(report, f"{tf}.阈值", "R-5", rule="REC-05", node_id=node_id,
                             threshold=thr, msg="阈值需 ≥0 数值")
                    fx = t.get("效果", t.get("effect"))
                    if isinstance(fx, str) and fx:
                        if effect_ids is not None and fx not in effect_ids:
                            _err(report, f"{tf}.效果", "R-5", rule="REC-05", node_id=node_id,
                                 ref=fx, ref_target="effects",
                                 msg="效果 %r 不在效果注册表中" % (fx,))
                    elif fx is not None:
                        _err(report, f"{tf}.效果", "R-5", rule="REC-05", node_id=node_id,
                             value=fx, msg="效果需为效果注册表 ID 字符串")

    # REC-06：effects 原子动作 ID 引用存在（效果注册表）
    fx_list = recipe.get("effects")
    if fx_list is not None:
        if not isinstance(fx_list, list):
            _err(report, f"recipe.{node_id}.effects", "R-5", rule="REC-06",
                 node_id=node_id, got=type(fx_list).__name__, msg="effects 需数组（原子动作 ID）")
        else:
            for fx in _effect_ids(fx_list):
                if effect_ids is not None and fx not in effect_ids:
                    _err(report, f"recipe.{node_id}.effects", "R-5", rule="REC-06",
                         node_id=node_id, ref=fx, ref_target="effects",
                         msg="效果 %r 不在效果注册表中" % (fx,))
    if effect_ids is None and fx_list is not None:
        _note(report, f"recipe.{node_id}.effects", "N-1", rule="REC-06",
              node_id=node_id, ref_target="effects",
              msg="【工程补白】effects 模块未接线，效果引用存在性未核（降级 note）")

    # REC-07：catalyst[] 引用 items type=触媒（引用不存在红拦；存在但未注册触媒 → 黄提示）
    cat = recipe.get("catalyst")
    if cat is not None:
        if not isinstance(cat, list):
            _err(report, f"recipe.{node_id}.catalyst", "R-5", rule="REC-07",
                 node_id=node_id, got=type(cat).__name__, msg="catalyst 需数组（触媒 items 引用）")
        else:
            for c in cat:
                if not isinstance(c, str) or not c:
                    _err(report, f"recipe.{node_id}.catalyst", "R-5", rule="REC-07",
                         node_id=node_id, value=c, msg="catalyst 条目需 items id 字符串")
                    continue
                if item_ids is not None:
                    if c not in item_ids:
                        _err(report, f"recipe.{node_id}.catalyst", "R-5", rule="REC-07",
                             node_id=node_id, ref=c, ref_target="items",
                             msg="触媒 %r 在 items.json 中不存在（红拦）" % (c,))
                    elif items_type is not None and items_type.get(c) != "触媒":
                        _warn(report, f"recipe.{node_id}.catalyst", "Y-1", rule="REC-07",
                              node_id=node_id, ref=c, type=items_type.get(c),
                              msg="触媒 %r 已注册但 type≠触媒，未注册仅提示（批5B）" % (c,))

    # REC-08：combine_from[] 引用 recipe 存在（同模块 id 集恒可用）
    cf = recipe.get("combine_from")
    if cf is not None:
        if not isinstance(cf, list):
            _err(report, f"recipe.{node_id}.combine_from", "R-5", rule="REC-08",
                 node_id=node_id, got=type(cf).__name__, msg="combine_from 需数组（配方引用）")
        else:
            for c in cf:
                if not isinstance(c, str) or not c:
                    _err(report, f"recipe.{node_id}.combine_from", "R-5", rule="REC-08",
                         node_id=node_id, value=c, msg="combine_from 条目需配方 id 字符串")
                elif recipe_ids is not None and c not in recipe_ids:
                    _err(report, f"recipe.{node_id}.combine_from", "R-5", rule="REC-08",
                         node_id=node_id, ref=c, ref_target="recipe",
                         msg="组合合成输入配方 %r 在 recipe.json 中不存在" % (c,))

    # REC-09：evolve_to 结构
    _check_recipe_evolve(report, recipe, node_id, recipe_ids)

    # REC-12：traits_inherit ∈ 1-3（黄提示；定稿 L356 字段范围，总上限 1-6 由 SP 扩展承载 INH-06）
    ti = recipe.get("traits_inherit")
    if ti is not None and (not isinstance(ti, int) or isinstance(ti, bool)
                           or not RECIPE_TRAITS_INHERIT_MIN <= ti <= RECIPE_TRAITS_INHERIT_MAX):
        _warn(report, f"recipe.{node_id}.traits_inherit", "Y-1", rule="REC-12",
              node_id=node_id, value=ti,
              msg="traits_inherit 需 %s-%s（定稿 L356；总上限 1-6 由 SP/等级扩展承载）"
                  % (RECIPE_TRAITS_INHERIT_MIN, RECIPE_TRAITS_INHERIT_MAX))

    # REC-13：slots ∈ 2-10（黄提示；默认 4）
    slots = recipe.get("slots")
    if slots is not None and (not isinstance(slots, int) or isinstance(slots, bool)
                              or not RECIPE_SLOTS_MIN <= slots <= RECIPE_SLOTS_MAX):
        _warn(report, f"recipe.{node_id}.slots", "Y-1", rule="REC-13",
              node_id=node_id, value=slots,
              msg="slots 需 %s-%s 整数（默认 4）" % (RECIPE_SLOTS_MIN, RECIPE_SLOTS_MAX))

    # REC-14：synth_allowed 类型校验（黄提示）。
    # 【收口裁决 2026-08-29】契约 6.2「深度配方设 false→提示」对正确默认值（深度配方默认 false）
    # 发警告 → 合法包无法零黄，判为噪音弃用；「改 true 提示将绕过深度炼金玩法」属运行时语义
    # （合成引擎 /合成 对 synth_allowed=false 配方的绕过提示，批2A 承接），静态校验只查类型。
    sa = recipe.get("synth_allowed")
    if sa is not None and not isinstance(sa, bool):
        _warn(report, f"recipe.{node_id}.synth_allowed", "Y-1", rule="REC-14",
              node_id=node_id, value=sa, msg="synth_allowed 需 bool（默认 true）")

    # REC-15：master_only 布尔（值类型黄提示）
    mo = recipe.get("master_only")
    if mo is not None and not isinstance(mo, bool):
        _warn(report, f"recipe.{node_id}.master_only", "Y-1", rule="REC-15",
              node_id=node_id, value=mo, msg="master_only 需 bool（默认 false）")

    # pp_budget（【工程补白】字段）：int ≥0（黄提示，契约 §一 1.1）
    pp = recipe.get("pp_budget")
    if pp is not None and (not isinstance(pp, int) or isinstance(pp, bool) or pp < 0):
        _warn(report, f"recipe.{node_id}.pp_budget", "Y-1", rule="REC-pp_budget",
              node_id=node_id, value=pp, msg="pp_budget 需 ≥0 整数（【工程补白】配方 PP 上限）")


def validate_recipes(modules: Mapping[str, object], report: object) -> None:
    """recipe 模块专项校验（契约 §六 6.2：REC-01 ~ REC-16 全量）。纯函数，无副作用。

    入参：
      modules: 模块名（无 .json 后缀）→ parsed JSON（含 "recipe" 与可选 "items"/"effects"）。
      report:  鸭子类型收集器（error/warning/note 或 validator._Checker 的 _err/_warn/_note）。
    出参：None；红拦/黄提示/降级 note 全部经 report 追加（一次给全量）。

    核心逻辑：逐配方跑 _check_recipe（REC-01~09/11~16 单条+引用），再跑 _check_recipe_evolve_cycle
    （REC-10 进化线成环 DFS）。items/effects 模块缺失 → 引用存在性降级 note（【工程补白】4）。
    """
    recipes = modules.get("recipe")
    if not isinstance(recipes, list):
        return  # 未接线 recipe 模块 → 跳过（§2.3 默认放行）

    item_ids = _id_set(modules, "items")
    items_type = _items_type_map(modules)
    effect_ids = _id_set(modules, "effects")
    recipe_ids = _same_module_id_set(recipes)

    node_id_map: Dict[str, str] = {}
    seen_ids: Set[str] = set()
    for i, entry in enumerate(recipes):
        node_id = str(entry.get("id")) if isinstance(entry, Mapping) else f"#{i}"
        node_id_map[str(entry.get("id"))] = node_id
        if not isinstance(entry, Mapping):
            _err(report, f"recipe.{i}", "R-5", rule="REC-01",
                 node_id=node_id, got=type(entry).__name__, msg="配方条目需对象")
            continue
        _check_recipe(report, entry, node_id, recipe_ids, item_ids, items_type,
                      effect_ids, seen_ids)

    _check_recipe_evolve_cycle(report, recipes, node_id_map)


# =====================================================================================
# validate_traits（契约 §六 6.2：TRT-01 ~ TRT-09）
# =====================================================================================
# 级别：红拦=error / 黄=warning；effects 引用靶缺失降级 note（【工程补白】4）。
# 规则速览：
#   TRT-01 id 禁保留字符；TRT-02 rarity 枚举；TRT-03 effects 引用；TRT-04 互斥组结构；
#   TRT-05 repeatable 布尔；TRT-06 source 枚举；TRT-07 name 非空；TRT-08 快照冗余 name 提示；
#   TRT-09 gold_slot_exclusive 布尔。


def _check_trait(report: object, trait: Mapping[str, object], node_id: str,
                 effect_ids: Optional[Set[str]], seen_ids: Set[str]) -> None:
    """单特性校验（TRT-01 ~ TRT-09 全量）。"""
    tid = trait.get("id")
    # TRT-01：id 禁保留字符 `* , = +` 空格（【工程补白】对齐定稿 L12/L58）
    if isinstance(tid, str) and _id_has_reserved(tid):
        _err(report, f"traits.{node_id}.id", "R-5", rule="TRT-01",
             node_id=node_id, id=tid, chars=list(RESERVED_ID_CHARS),
             msg="特性 id 禁保留字符 `* , = +` 与空格（对齐定稿 L12/L58）")
    if isinstance(tid, str) and tid in seen_ids:
        _err(report, f"traits.{node_id}.id", "R-5", rule="TRT-01",
             node_id=node_id, id=tid, msg="特性 id %r 重复（trait_lib 全局唯一）" % tid)
    if isinstance(tid, str):
        seen_ids.add(tid)

    # TRT-07：name 非空（红拦）
    name = trait.get("name")
    if not isinstance(name, str) or not name.strip():
        _err(report, f"traits.{node_id}.name", "R-5", rule="TRT-07",
             node_id=node_id, value=name,
             msg="特性 name 必填非空（展示名，投料反馈/成品消息//继承 参数按 name 匹配）")

    # TRT-02：rarity ∈ {normal, super}
    rarity = trait.get("rarity")
    if rarity is not None and (not isinstance(rarity, str) or rarity not in TRAIT_RARITIES):
        _err(report, f"traits.{node_id}.rarity", "R-5", rule="TRT-02",
             node_id=node_id, rarity=rarity, allowed=list(TRAIT_RARITIES),
             msg="rarity %r 不认识（normal/super；super=金色超特性，PP 消耗翻倍）" % (rarity,))

    # TRT-03：effects L0 原子动作 ID 引用存在（效果注册表）
    fx_list = trait.get("effects")
    if fx_list is None:
        _err(report, f"traits.{node_id}.effects", "R-5", rule="TRT-03",
             node_id=node_id, msg="特性 effects 必填（L0 原子动作列表，不内联实现逻辑 TSC-02）")
    elif not isinstance(fx_list, list):
        _err(report, f"traits.{node_id}.effects", "R-5", rule="TRT-03",
             node_id=node_id, got=type(fx_list).__name__, msg="effects 需数组（原子动作 ID 列表）")
    else:
        for fx in _effect_ids(fx_list):
            if effect_ids is not None and fx not in effect_ids:
                _err(report, f"traits.{node_id}.effects", "R-5", rule="TRT-03",
                     node_id=node_id, ref=fx, ref_target="effects",
                     msg="效果 %r 不在效果注册表中（TRT-03，热重载自动迁移）" % (fx,))
        if effect_ids is None:
            _note(report, f"traits.{node_id}.effects", "N-1", rule="TRT-03",
                  node_id=node_id, ref_target="effects",
                  msg="【工程补白】effects 模块未接线，效果引用存在性未核（降级 note）")

    # TRT-04：互斥组结构校验（INH-13/L492；【工程补白】8）
    group = trait.get("group")
    if group is not None:
        if isinstance(group, list):
            _err(report, f"traits.{node_id}.group", "R-5", rule="TRT-04",
                 node_id=node_id, value=group,
                 msg="同特性不得登记进多个互斥组（group 为单字符串）")
        elif not isinstance(group, str) or not group:
            _err(report, f"traits.{node_id}.group", "R-5", rule="TRT-04",
                 node_id=node_id, value=group, msg="group 需非空字符串（互斥组键）")
        elif isinstance(tid, str) and group == tid:
            _err(report, f"traits.{node_id}.group", "R-5", rule="TRT-04",
                 node_id=node_id, group=group,
                 msg="组内自引用：group 不得等于自身特性 id")

    # TRT-05：repeatable 布尔（默认 false，黄提示）
    rp = trait.get("repeatable")
    if rp is not None and not isinstance(rp, bool):
        _warn(report, f"traits.{node_id}.repeatable", "Y-1", rule="TRT-05",
              node_id=node_id, value=rp, msg="repeatable 需 bool（默认 false）")

    # TRT-06：source 枚举 {素材, 成品, 金色素材}
    src = trait.get("source")
    if src is not None and (not isinstance(src, str) or src not in TRAIT_SOURCES):
        _err(report, f"traits.{node_id}.source", "R-5", rule="TRT-06",
             node_id=node_id, source=src, allowed=list(TRAIT_SOURCES),
             msg="source %r 不认识（三值：%s；决定进入哪个可继承池）"
                 % (src, "/".join(TRAIT_SOURCES)))

    # TRT-08：快照/存档引用冗余 ID+名称（黄提示；【工程补白】7——name 缺失回退 id 或 name==id）
    if (not isinstance(name, str) or not name.strip()) or (
            isinstance(name, str) and isinstance(tid, str) and name == tid):
        _warn(report, f"traits.{node_id}.name", "Y-1", rule="TRT-08",
              node_id=node_id, id=tid, name=name,
              msg="特性缺显式 name 或 name==id：快照/存档须冗余存 ID+名称，"
                  "删配置降级显示才不报错（STO-05/L511）")

    # TRT-09：rarity=super 第 4 位独占 gold_slot_exclusive 可配项合法（布尔，黄提示）
    gse = trait.get("gold_slot_exclusive")
    if gse is not None and not isinstance(gse, bool):
        _warn(report, f"traits.{node_id}.gold_slot_exclusive", "Y-1", rule="TRT-09",
              node_id=node_id, value=gse,
              msg="gold_slot_exclusive 需 bool（rarity=super 第 4 位独占可配项）")


def validate_traits(modules: Mapping[str, object], report: object) -> None:
    """traits 模块专项校验（契约 §六 6.2：TRT-01 ~ TRT-09 全量）。纯函数，无副作用。

    入参：modules（含 "traits" 与可选 "effects"）；report 鸭子类型收集器。
    出参：None；红拦/黄提示/降级 note 全部经 report 追加。

    核心逻辑：逐特性跑 _check_trait（TRT-01~09）；effects 模块缺失 → 引用存在性降级 note
    （【工程补白】4）。现 traits 模块已登记（field_meta L418），本函数供 validator._check_module
    "traits" 分支挂接（现不存在，需主 agent 收口新增）。
    """
    traits = modules.get("traits")
    if not isinstance(traits, list):
        return  # 未接线 traits 模块 → 跳过（§2.3 默认放行）

    effect_ids = _id_set(modules, "effects")
    seen_ids: Set[str] = set()
    for i, entry in enumerate(traits):
        node_id = str(entry.get("id")) if isinstance(entry, Mapping) else f"#{i}"
        if not isinstance(entry, Mapping):
            _err(report, f"traits.{i}", "R-5", rule="TRT-01",
                 node_id=node_id, got=type(entry).__name__, msg="特性条目需对象")
            continue
        _check_trait(report, entry, node_id, effect_ids, seen_ids)


# =====================================================================================
# validate_proficiency（契约 §六 6.2：PRF-01 ~ PRF-10）
# =====================================================================================
# 级别：红拦=error / 黄=warning；PRF-01 jobs 引用靶缺失降级 note（【工程补白】3）。
# 规则速览：
#   PRF-01 id 引用 jobs 职业存在；PRF-02 tier_names 长度 ≥2 且与 job_rank_levels 一一对应；
#   PRF-03 job_rank_levels 单调递增、首项=0；PRF-04 exp_sources 子键+值 ≥0；
#   PRF-05 sp_per_level 非负整数；PRF-06 sp_panel 项 id 唯一/cost≥1/repeatable 布尔/max_repeat≥1；
#   PRF-07 energy.enabled 布尔 + enabled 时 max_by_tier 长度一致 + regen_sec ≥0；
#   PRF-08 job_tier_map 称号引用 tier_names + 区间单调；PRF-09 titles source 枚举；
#   PRF-10 source=king 自动生成提示（不手写）。


def _parse_interval(value: object) -> Optional[Tuple[Optional[int], Optional[int]]]:
    """【工程补白】6：job_tier_map 区间解析 → (lo, hi)；hi=None=+∞（「王 51+」开口）。
    支持 2 元数组 [lo,hi] 或对象 {min,max}/{lo,hi}。非法形态 → None。"""
    lo: Optional[int] = None
    hi: Optional[int] = None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        a, b = value[0], value[1]
        lo = a if isinstance(a, int) and not isinstance(a, bool) else None
        hi = b if isinstance(b, int) and not isinstance(b, bool) else None
    elif isinstance(value, Mapping):
        lo = value.get("min", value.get("lo"))
        hi = value.get("max", value.get("hi"))
        lo = lo if isinstance(lo, int) and not isinstance(lo, bool) else None
        hi = hi if isinstance(hi, int) and not isinstance(hi, bool) else None
    else:
        return None
    if lo is None and hi is None:
        return None
    return (lo, hi)


def _check_proficiency(report: object, prof: Mapping[str, object], node_id: str,
                       jobs_ids: Optional[Set[str]]) -> None:
    """单职业熟练度配置校验（PRF-01 ~ PRF-10 全量）。"""
    # PRF-01：id 引用 jobs.json 职业存在（jobs 模块缺失 → note 降级，【工程补白】3）
    pid = prof.get("id")
    if not isinstance(pid, str) or not pid:
        _err(report, f"proficiency.{node_id}.id", "R-5", rule="PRF-01",
             node_id=node_id, value=pid, msg="proficiency id 必填（对应 jobs.json 职业）")
    elif jobs_ids is not None and pid not in jobs_ids:
        _err(report, f"proficiency.{node_id}.id", "R-5", rule="PRF-01",
             node_id=node_id, ref=pid, ref_target="jobs",
             msg="职业 id %r 在 jobs.json 中不存在" % (pid,))
    elif jobs_ids is None:
        _note(report, f"proficiency.{node_id}.id", "N-1", rule="PRF-01",
              node_id=node_id, ref_target="jobs",
              msg="【工程补白】jobs 职业引擎 M13 未落地，缺 jobs 模块，id 存在性未核（降级 note）")

    # PRF-02：tier_names 长度 ≥2 且与 job_rank_levels 一一对应
    tiers = prof.get("tier_names")
    ranks = prof.get("job_rank_levels")
    if not isinstance(tiers, list) or not tiers:
        _err(report, f"proficiency.{node_id}.tier_names", "R-5", rule="PRF-02",
             node_id=node_id, value=tiers,
             msg="tier_names 必填（7 级称号可改名；长度 ≥2 且与 job_rank_levels 一一对应）")
    elif len(tiers) < 2:
        _err(report, f"proficiency.{node_id}.tier_names", "R-5", rule="PRF-02",
             node_id=node_id, count=len(tiers), msg="tier_names 长度需 ≥2（最小 2、默认 7）")
    if isinstance(tiers, list) and isinstance(ranks, list) and len(tiers) != len(ranks):
        _err(report, f"proficiency.{node_id}.tier_names", "R-5", rule="PRF-02",
             node_id=node_id, tiers=len(tiers), ranks=len(ranks),
             msg="tier_names 长度 %s 与 job_rank_levels 长度 %s 不一致（须一一对应）"
                 % (len(tiers), len(ranks)))

    # PRF-03：job_rank_levels 单调递增、首项=0
    if isinstance(ranks, list):
        bad = False
        for r in ranks:
            if not isinstance(r, int) or isinstance(r, bool) or r < 0:
                bad = True
                break
        if not bad:
            if not ranks or ranks[0] != 0:
                bad = True
        if not bad:
            for a, b in zip(ranks, ranks[1:]):
                if b <= a:
                    bad = True
                    break
        if bad:
            _err(report, f"proficiency.{node_id}.job_rank_levels", "R-5", rule="PRF-03",
                 node_id=node_id, value=ranks,
                 msg="job_rank_levels 需非负整数、单调递增、首项=0（成长曲线累计阈值）")
        elif not ranks:
            _err(report, f"proficiency.{node_id}.job_rank_levels", "R-5", rule="PRF-02",
                 node_id=node_id, msg="job_rank_levels 必填（与 tier_names 一一对应）")

    # PRF-04：exp_sources 子键 ∈ {craft,gather,combat}、值 ≥0
    es = prof.get("exp_sources")
    if es is not None:
        if not isinstance(es, Mapping):
            _err(report, f"proficiency.{node_id}.exp_sources", "R-5", rule="PRF-04",
                 node_id=node_id, got=type(es).__name__,
                 msg="exp_sources 要填对象 {craft/gather/combat: 倍率≥0}")
        else:
            for k, v in es.items():
                if k not in EXP_SOURCE_KEYS:
                    _err(report, f"proficiency.{node_id}.exp_sources.{k}", "R-5", rule="PRF-04",
                         node_id=node_id, key=k, allowed=list(EXP_SOURCE_KEYS),
                         msg="经验来源键 %r 不认识（三来源：%s）" % (k, "/".join(EXP_SOURCE_KEYS)))
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                    _err(report, f"proficiency.{node_id}.exp_sources.{k}", "R-5", rule="PRF-04",
                         node_id=node_id, key=k, value=v, msg="经验倍率需 ≥0 数值")

    # PRF-05：sp_per_level 非负整数
    spl = prof.get("sp_per_level")
    if spl is not None and (not isinstance(spl, int) or isinstance(spl, bool) or spl < 0):
        _err(report, f"proficiency.{node_id}.sp_per_level", "R-5", rule="PRF-05",
             node_id=node_id, value=spl, msg="sp_per_level 需 ≥0 整数（升级获得 SP 点数）")

    # PRF-06：sp_panel 项 id 唯一、cost ≥1、repeatable 布尔、max_repeat ≥1（黄提示）
    panel = prof.get("sp_panel")
    if panel is not None:
        if not isinstance(panel, list):
            _warn(report, f"proficiency.{node_id}.sp_panel", "Y-1", rule="PRF-06",
                  node_id=node_id, got=type(panel).__name__, msg="sp_panel 需数组")
        else:
            seen_panel: Set[str] = set()
            for j, p in enumerate(panel):
                pf = f"proficiency.{node_id}.sp_panel.{j}"
                if not isinstance(p, Mapping):
                    _warn(report, pf, "Y-1", rule="PRF-06", node_id=node_id,
                          got=type(p).__name__, msg="sp_panel 条目需对象")
                    continue
                pid_ = p.get("id")
                if not isinstance(pid_, str) or not pid_:
                    _warn(report, f"{pf}.id", "Y-1", rule="PRF-06", node_id=node_id,
                          value=pid_, msg="sp_panel 项 id 必填")
                elif pid_ in seen_panel:
                    _warn(report, f"{pf}.id", "Y-1", rule="PRF-06", node_id=node_id,
                          id=pid_, msg="sp_panel 项 id %r 重复（须唯一）" % (pid_,))
                else:
                    seen_panel.add(pid_)
                cost = p.get("cost")
                if not isinstance(cost, int) or isinstance(cost, bool) or cost < 1:
                    _warn(report, f"{pf}.cost", "Y-1", rule="PRF-06", node_id=node_id,
                          value=cost, msg="sp_panel 项 cost 需 ≥1（SP 消耗）")
                rp = p.get("repeatable")
                if rp is not None and not isinstance(rp, bool):
                    _warn(report, f"{pf}.repeatable", "Y-1", rule="PRF-06", node_id=node_id,
                          value=rp, msg="sp_panel 项 repeatable 需 bool")
                mr = p.get("max_repeat")
                if mr is not None and (not isinstance(mr, int) or isinstance(mr, bool) or mr < 1):
                    _warn(report, f"{pf}.max_repeat", "Y-1", rule="PRF-06", node_id=node_id,
                          value=mr, msg="sp_panel 项 max_repeat 需 ≥1（可多次上限）")

    # PRF-07：energy.enabled 布尔；enabled=true 时 max_by_tier 长度一致、regen_sec ≥0（黄提示）
    en = prof.get("energy")
    if en is not None:
        if not isinstance(en, Mapping):
            _warn(report, f"proficiency.{node_id}.energy", "Y-1", rule="PRF-07",
                  node_id=node_id, got=type(en).__name__, msg="energy 需对象")
        else:
            enabled = en.get("enabled")
            if enabled is not None and not isinstance(enabled, bool):
                _warn(report, f"proficiency.{node_id}.energy.enabled", "Y-1", rule="PRF-07",
                      node_id=node_id, value=enabled,
                      msg="energy.enabled 需 bool（默认 false 非炼金职业默认关）")
            if enabled is True:
                mbt = en.get("max_by_tier")
                if isinstance(mbt, list) and isinstance(tiers, list) and len(mbt) != len(tiers):
                    _warn(report, f"proficiency.{node_id}.energy.max_by_tier", "Y-1",
                          rule="PRF-07", node_id=node_id, max_by_tier=len(mbt), tiers=len(tiers),
                          msg="energy.max_by_tier 长度 %s 与 tier_names %s 不一致"
                              % (len(mbt), len(tiers)))
                rs = en.get("regen_sec")
                if rs is not None and (not isinstance(rs, int) or isinstance(rs, bool) or rs < 0):
                    _warn(report, f"proficiency.{node_id}.energy.regen_sec", "Y-1",
                          rule="PRF-07", node_id=node_id, value=rs,
                          msg="energy.regen_sec 需 ≥0 整数（默认 1800=30 分钟回 1 格）")

    # PRF-08：job_tier_map 称号引用 tier_names 存在、区间单调（【工程补白】6 区间解析）
    jtm = prof.get("job_tier_map")
    if jtm is not None and not isinstance(jtm, str):
        if not isinstance(jtm, Mapping):
            _err(report, f"proficiency.{node_id}.job_tier_map", "R-5", rule="PRF-08",
                 node_id=node_id, got=type(jtm).__name__,
                 msg="job_tier_map 需对象 {称号: 区间}（默认 \"settings\" 继承 settings.json）")
        else:
            tier_list = tiers if isinstance(tiers, list) else []
            for k, v in jtm.items():
                if tier_list and k not in tier_list:
                    _err(report, f"proficiency.{node_id}.job_tier_map.{k}", "R-5",
                         rule="PRF-08", node_id=node_id, tier=k, allowed=tier_list,
                         msg="job_tier_map 称号 %r 不在 tier_names 中" % (k,))
                iv = _parse_interval(v)
                if iv is None:
                    _err(report, f"proficiency.{node_id}.job_tier_map.{k}", "R-5",
                         rule="PRF-08", node_id=node_id, value=v,
                         msg="job_tier_map %r 区间需 [lo,hi] 或 {min,max}（hi 可缺省=51+）" % (k,))
                    continue
                lo, hi = iv
                if lo is not None and hi is not None and hi < lo:
                    _err(report, f"proficiency.{node_id}.job_tier_map.{k}", "R-5",
                         rule="PRF-08", node_id=node_id, lo=lo, hi=hi,
                         msg="job_tier_map %r 区间 hi(%s) < lo(%s)" % (k, hi, lo))
            # 区间单调：按 tier_names 顺序相邻区间不重叠递增
            if tier_list:
                prev_hi: Optional[int] = None
                for k in tier_list:
                    v = jtm.get(k)
                    iv = _parse_interval(v) if v is not None else None
                    if iv is None:
                        continue
                    lo, _hi = iv
                    if lo is not None and prev_hi is not None and lo <= prev_hi:
                        _err(report, f"proficiency.{node_id}.job_tier_map", "R-5",
                             rule="PRF-08", node_id=node_id, tier=k, lo=lo, prev_hi=prev_hi,
                             msg="job_tier_map 区间不单调：%r 的 lo(%s) ≤ 上一档 hi(%s)"
                                 % (k, lo, prev_hi))
                        break
                    if _hi is not None:
                        prev_hi = _hi
                    elif lo is not None:
                        prev_hi = lo  # 开口区间（51+）：以 lo 作单调下界

    # PRF-09：titles source 枚举（黄提示）
    titles = prof.get("titles")
    if titles is not None:
        if not isinstance(titles, list):
            _warn(report, f"proficiency.{node_id}.titles", "Y-1", rule="PRF-09",
                  node_id=node_id, got=type(titles).__name__, msg="titles 需数组")
        else:
            for j, t in enumerate(titles):
                tf = f"proficiency.{node_id}.titles.{j}"
                if not isinstance(t, Mapping):
                    _warn(report, tf, "Y-1", rule="PRF-09", node_id=node_id,
                          got=type(t).__name__, msg="titles 条目需对象")
                    continue
                src = t.get("source")
                if src is not None and (not isinstance(src, str) or src not in TITLE_SOURCES):
                    _warn(report, f"{tf}.source", "Y-1", rule="PRF-09", node_id=node_id,
                          source=src, allowed=list(TITLE_SOURCES),
                          msg="titles.source %r 不认识（四枚举：%s）"
                              % (src, "/".join(TITLE_SOURCES)))
                # PRF-10：source=king 王称号自动生成（id=职业 ID），手写 → 提示
                if src == "king":
                    _warn(report, tf, "Y-1", rule="PRF-10", node_id=node_id,
                          source="king",
                          msg="source=king 王称号自动生成（id=职业 ID，TTL-03），无需手写配置")


def validate_proficiency(modules: Mapping[str, object], report: object) -> None:
    """proficiency 模块专项校验（契约 §六 6.2：PRF-01 ~ PRF-10 全量）。纯函数，无副作用。

    入参：modules（含 "proficiency" 与可选 "jobs"）；report 鸭子类型收集器。
    出参：None；红拦/黄提示/降级 note 全部经 report 追加。

    核心逻辑：逐职业配置跑 _check_proficiency；PRF-01 jobs 引用存在性仅当 jobs 模块存在时硬拦，
    缺 jobs 模块 → note 降级（【工程补白】3：M13 职业引擎未落地，避免无 jobs.json 合法包被误拦）。
    """
    profs = modules.get("proficiency")
    if not isinstance(profs, list):
        return  # 未接线 proficiency 模块 → 跳过（§2.3 默认放行）

    jobs_ids = _id_set(modules, "jobs")
    for i, entry in enumerate(profs):
        node_id = str(entry.get("id")) if isinstance(entry, Mapping) else f"#{i}"
        if not isinstance(entry, Mapping):
            _err(report, f"proficiency.{i}", "R-5", rule="PRF-01",
                 node_id=node_id, got=type(entry).__name__, msg="proficiency 条目需对象")
            continue
        _check_proficiency(report, entry, node_id, jobs_ids)


__all__ = [
    # 常量 / 注册表
    "ALCHEMY_ELEMENTS",
    "QUALITY_TIERS", "QUALITY_TIER_NAMES",
    "RECIPE_KINDS", "RECIPE_LEVEL_MIN", "RECIPE_LEVEL_MAX",
    "RECIPE_SLOTS_MIN", "RECIPE_SLOTS_MAX",
    "RECIPE_TRAITS_INHERIT_MIN", "RECIPE_TRAITS_INHERIT_MAX",
    "RESERVED_ID_CHARS", "EVOLVE_SOURCES",
    "TRAIT_RARITIES", "TRAIT_SOURCES",
    "DEFAULT_TIER_NAMES", "DEFAULT_JOB_RANK_LEVELS",
    "EXP_SOURCE_KEYS", "TITLE_SOURCES", "SP_PANEL_FIELDS", "DEFAULT_ENERGY",
    "JOB_TIER_MAP_DEFAULT",
    # Def 类型
    "RecipeDef", "TraitDef", "ProficiencyDef",
    # 校验函数
    "validate_recipes", "validate_traits", "validate_proficiency",
]
