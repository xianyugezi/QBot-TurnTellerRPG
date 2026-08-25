"""内容包领域模型：校验报告类型 / 字段元数据表 / 配置 Def 类型 / Manifest / Pack。

依据：
  - 细化_3e_loader校验接线 §5.1（PackError/PackWarning/ValidationReport 接口定义，红拦 R-1~R-5、黄提示 Y-1~Y-8）
  - 细化_3e_loader校验接线 §5.3（字段元数据表 = 校验唯一数据源：名称/类型/默认值/范围/引用目标；缺失字段默认放行）
  - 细化_3a_架构分层契约 §3.3 U2（配置类型 Def 系落 content/，运行时实例落 data/）+ §3.4（配置/运行分工）
  - 细化_3e_loader校验接线 §1.7（PackLoadError 领域异常放 loader.py；本文件只定义校验/元数据/Def 结构）
  - 细化_1e_怪物八段schema §1.1~1.6 + m2_shared_contract 第一、四节（M2 A1 路：EnemyDef 八段 18 字段访问器 / ActionDef 怪物侧 AI 字段访问器）

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；仅依赖 qbot_rpg.data 的 TypeAlias。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.data.types import (
    ActionID,
    EffectID,
    EnemyID,
    ItemID,
    MapID,
    MarkID,
    ModuleName,
    NpcID,
    PackID,
    SkillChainID,
    SkillID,
    StatKey,
    StatusID,
    TraitID,
)

# =====================================================================================
# 校验报告三类（细化_3e §5.1，逐字段对齐）
# =====================================================================================


@dataclass(frozen=True)
class PackError:
    """红拦条目（细化_3e §2.1：R-1~R-5 五类封闭清单；§3.3 安全例外亦以 R-5 表达）。"""

    module: str  # 模块文件名（无后缀），如 "effects"
    field: str  # 字段路径，如 "items.0.effects.1"
    kind: str  # R-1..R-5（五类之一）
    detail: Mapping[str, object]  # 结构化参数（供 commands 层拼人话，§1.7；validator/loader 不拼用户体验文案 D-06）


@dataclass(frozen=True)
class PackWarning:
    """黄提示条目（细化_3e §2.2：Y-1~Y-8 开放清单；只进 report.warnings 不阻断）。"""

    module: str
    field: str
    kind: str  # Y-1..Y-8
    detail: Mapping[str, object]


@dataclass(frozen=True)
class PackNote:
    """信息级提示条目（细化_1e §⑤ 提示级：模板补全 / 别名规范化 / 档区间确认 / 链成环提示等）。

    三分级之一（拦截=errors / 警告=warnings / 提示=notes）；只进 report.notes 不阻断，
    语义为「建议信息」——供编辑器/命令层聚合展示（D-03 同款聚合机制），与 PackWarning 同结构。
    """

    module: str
    field: str
    kind: str  # N-1..N-5（提示家族）
    detail: Mapping[str, object]


@dataclass(frozen=True)
class ValidationReport:
    """整包校验报告：errors 非空即阻断（D-01/D-02）；warnings/notes 均不阻断。"""

    errors: Tuple[PackError, ...] = ()
    warnings: Tuple[PackWarning, ...] = ()
    notes: Tuple[PackNote, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors  # 红拦为空才可挂载（细化_3e §5.1 / D-02）


# =====================================================================================
# 字段元数据表（细化_3e §5.3：校验唯一数据源；缺失字段按"未知字段"默认放行）
# =====================================================================================


@dataclass(frozen=True)
class FieldMeta:
    """单字段元数据：类型/必填/默认/引用目标/枚举/常见区间/概率/上限 0=不限/软标注。

    判定口径全部来自细化_3e §2.1（R-1~R-5）与 §2.2（Y-1~Y-8）：
      - type: int|float|number|str|bool|enum|ref|obj|list|map|formula（R-1 类型口径，【规则】L143）
      - ref_target: 引用目标注册表 kind（R-4；stat 特殊 → Y-7 未注册键空间）
      - range_min/range_max: 常见区间（仅 Y-1 提示用，不红拦）
      - probability: 概率字段 → Y-2
      - zero_unlimited: 上限字段 0=不限 → Y-4（不报错）
      - soft_label: 软标注字段 → 永不红拦（Y-5）
      - allow_negative: 允许负数的数值字段（默认数值字段 <0 → R-2）
    """

    type: str
    required: bool = False
    default: object = None
    ref_target: Optional[str] = None  # 注册表 kind；provide 时 type 应为 "ref"
    enum: Tuple[str, ...] = ()
    range_min: Optional[float] = None  # 仅 Y-1 黄提示
    range_max: Optional[float] = None
    probability: bool = False  # Y-2
    zero_unlimited: bool = False  # Y-4
    soft_label: bool = False  # Y-5
    allow_negative: bool = False  # 默认数值字段 <0 → R-2
    element: Optional["FieldMeta"] = None  # type=="list" 时元素元数据
    children: Mapping[str, "FieldMeta"] = field(default_factory=dict)  # type=="obj" 时子字段


@dataclass(frozen=True)
class ModuleMeta:
    """单模块元数据：条目形态 + 顶层字段表 + 结构算法开关（链成环 / 部位互斥）。"""

    entry_type: str = "list"  # list（条目数组）| object（单对象，如 manifest）| map（键→对象，如 stats/formula）
    fields: Mapping[str, FieldMeta] = field(default_factory=dict)  # 条目顶层字段
    id_field: str = "id"
    kind: Optional[str] = None  # 注册表 kind（None → 用模块名）
    namespace: Optional[str] = None  # ID 全局唯一作用域（无则仅模块内唯一）
    chain_field: Optional[str] = None  # 条目内指向后继 ID 的列表字段（链成环 R-5，skill_chains 等）
    mutex_field: Optional[str] = None  # 条目内部位互斥列表字段（互斥成环 R-5，equipment 等）
    key_regex: Optional[str] = None  # map 形态模块的键命名约束（stats 小写 snake_case）
    value_meta: Optional["FieldMeta"] = None  # map 形态模块的值字段元数据（stats 值对象 / formula 公式）


@dataclass(frozen=True)
class FieldMetaTable:
    """全量字段元数据表：modules（模块名→ModuleMeta）+ namespaces（kind→模块组，跨模块 ID 唯一）。

    细化_3e §5.3 硬约束：校验器不手写字段清单，全部从本表读取；本表缺失某字段 → 按未知字段默认放行。
    """

    modules: Mapping[str, ModuleMeta] = field(default_factory=dict)
    namespaces: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)

    def module(self, name: str) -> Optional[ModuleMeta]:
        return self.modules.get(name)

    def namespace_of(self, module_name: str) -> str:
        """返回模块所属命名空间（ID 全局唯一作用域名）；默认回退为模块名。"""
        for ns, mods in self.namespaces.items():
            if module_name in mods:
                return ns
        return module_name


# =====================================================================================
# 配置 Def 类型（细化_3a §3.3 U2：配置类型落 content/，schema 镜像）
# =====================================================================================


@dataclass(frozen=True)
class BaseDef:
    """配置定义基类：ID + 显示名（冗余，供旧局快照 L177）+ 原始 JSON 结构只读镜像。

    raw 为 parsed JSON 的深拷贝快照，保证 registry 内共享定义不被外部改写。
    """

    id: str
    name: str
    raw: Mapping[str, object] = field(default_factory=dict)
    kind: str = ""  # 注册表 kind，如 "effect"

    def get(self, key: str, default: object = None) -> object:
        return self.raw.get(key, default)

    @classmethod
    def from_entry(cls, entry: Mapping[str, object], name_field: str = "name",
                   id_override: Optional[str] = None) -> "BaseDef":
        """从配置条目构造 Def。

        P1-3（2026-08-24 M0 复查）：map 形态模块（stats/formula 对象值）的
        「键 = ID」由 loader 显式传 id_override——否则值对象无 id 键时
        Def.id 为空串，违反 §1.5「ID → 定义对象」与名称冗余契约。
        """
        eid = str(id_override if id_override is not None else entry.get("id", ""))
        name = str(entry.get(name_field, "") or eid)
        return cls(id=eid, name=name, raw=copy.deepcopy(dict(entry)))


@dataclass(frozen=True)
class EffectDef(BaseDef):
    """effects.json 条目。"""

    def _f(self, key: str) -> Optional[float]:
        v = self.raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def power(self) -> Optional[float]:
        return self._f("power")

    @property
    def duration(self) -> Optional[float]:
        return self._f("duration")


@dataclass(frozen=True)
class StatusDef(BaseDef):
    """statuses.json 条目。"""

    @property
    def max_stack(self) -> Optional[float]:
        v = self.raw.get("max_stack")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


@dataclass(frozen=True)
class MarkDef(BaseDef):
    """marks.json 条目。"""


@dataclass(frozen=True)
class SkillChainDef(BaseDef):
    """skill_chains.json 条目（连段链）。"""

    @property
    def next(self) -> Tuple[str, ...]:
        v = self.raw.get("next")
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()


@dataclass(frozen=True)
class ActionDef(BaseDef):
    """action.json 条目（ActionCore + 怪物侧 AI 字段，m2_shared_contract §四 / 细化_1e 1.4 / T26）。

    依据：细化_1e §1.4（A01~A03d）+ m2_shared_contract 第四节（T24-T26 ActionCore + AI 字段）。
    注意：BaseDef.kind 为注册表 kind（"action"），action.json 的 ActionCore `kind`
    （basic/active/...）经 raw.get("kind") / BaseDef.get("kind") 读取，不设同名访问器。
    """

    # ---- 数值/字符串/列表辅助（与 EffectDef._f 同风格）----
    def _num(self, key: str) -> Optional[float]:
        v = self.raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _str_list(self, key: str) -> Tuple[str, ...]:
        v = self.raw.get(key)
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    # ---- AI 字段（怪物侧扩展，T26 / m2 §四；缺省兜底不报错）----
    @property
    def weight(self) -> Optional[float]:
        """随机池内归一化权重（≥0，缺省兜底）。"""
        return self._num("weight")

    @property
    def probability(self) -> Optional[float]:
        """入池开关：0=锚点（只被链/条件/状态机触发）、1=入池、其他正值等价 1；漏配默认 0。"""
        return self._num("probability")

    @property
    def intent(self) -> Optional[str]:
        """意图预告类别（伤害/防御/蓄力/治疗/控制/buff/debuff/印记/功能；枚举校验 A2 路）。"""
        return self._str("intent")

    @property
    def cooldown(self) -> Optional[float]:
        """行动冷却回合数（默认 0）。"""
        return self._num("cooldown")

    @property
    def condition(self) -> object:
        """条件权重修正（如 pv_broken 时 ×2），默认 None（obj 形态由 A2 放宽）。"""
        return self.raw.get("condition")

    @property
    def hungry(self) -> Optional[float]:
        """饥饿保底：连续 N 回合未选中则强制选，默认 0=关。"""
        return self._num("hungry")

    @property
    def chain(self) -> Tuple[str, ...]:
        """连招（历史写法，S2 兼容解析）：行动 ID 列表；新配置一律走 enemies 顶层 chains 表。"""
        return self._str_list("chain")

    @property
    def charge(self) -> Optional[Mapping[str, object]]:
        """蓄力子对象（charge 键，防御性读取）；结构以 1d 系细化为准。"""
        v = self.raw.get("charge")
        return v if isinstance(v, Mapping) else None

    def charge_fields(self) -> Mapping[str, object]:
        """所有 `charge_` 前缀蓄力字段（键名前缀登记，结构待 1d 系落地；A2 路专项校验）。"""
        return {k: v for k, v in self.raw.items() if isinstance(k, str) and k.startswith("charge_")}

    @property
    def preview(self) -> object:
        """意图预告配置（意图分级显示用；结构以 1d 系/A2 为准）。"""
        return self.raw.get("preview")

    @property
    def preview_chain(self) -> object:
        """连招预告配置（意图分级显示用）。"""
        return self.raw.get("preview_chain")

    @property
    def reveal_condition(self) -> object:
        """预告揭示条件。"""
        return self.raw.get("reveal_condition")

    @property
    def armor(self) -> object:
        """霸体免疫打断（AI 定稿 §八：true=霸体）。"""
        return self.raw.get("armor")

    @property
    def interrupt(self) -> object:
        """打断行动标记（T19 interrupt 唯一归口）。"""
        return self.raw.get("interrupt")

    @property
    def tags(self) -> Tuple[str, ...]:
        """行动标签。"""
        return self._str_list("tags")


@dataclass(frozen=True)
class ItemDef(BaseDef):
    """items.json / equipment.json 条目。"""

    @property
    def price(self) -> Optional[float]:
        v = self.raw.get("price")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def atk(self) -> Optional[float]:
        v = self.raw.get("atk")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


@dataclass(frozen=True)
class TraitDef(BaseDef):
    """traits.json 条目。"""


@dataclass(frozen=True)
class EnemyDef(BaseDef):
    """enemies.json 条目（八段结构 18 顶层字段，细化_1e §1.1；m2_shared_contract 第一节权威）。

    依据：细化_1e §1.1~1.6（F01~F18 / stats 九键 / weakness / actions / special_actions /
    chains / drops / lore）+ m2_shared_contract 第一节。
    M0 旧键 hp/atk 保留顶层读兼容（旧包可继续解析）；八段 schema 下生命/攻击落在
    stats.hp / stats.str 等九键（stats_hp / stats_str... 访问器）。
    """

    # ---- 数值/字符串/映射/列表辅助（与 EffectDef._f 同风格）----
    def _num(self, key: str) -> Optional[float]:
        v = self.raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    def _entries(self, key: str) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get(key)
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    # ---- M0 旧键兼容（顶层 hp/atk；废弃但保留解析——测试依赖 R-2/Y-1 行为）----
    @property
    def hp(self) -> Optional[float]:
        """旧 schema 顶层 hp（M0）；八段 schema 请用 stats_hp / stats.hp。"""
        return self._num("hp")

    @property
    def atk(self) -> Optional[float]:
        """旧 schema 顶层 atk（M0）；八段 schema 请用 stats_str / stats.str。"""
        return self._num("atk")

    # ---- 八段：基础（F01-F06）----
    @property
    def tier(self) -> Optional[str]:
        """难度档：normal/elite/boss/training（F03；默认 normal 由 A2/模板路）。"""
        return self._str("tier")

    @property
    def type(self) -> Optional[str]:
        """"dummy" 标记（F04；tier:training 或 type:dummy 任一命中=木桩）。"""
        return self._str("type")

    @property
    def area(self) -> Optional[str]:
        """出没地图名（F05；木桩不配）。"""
        return self._str("area")

    @property
    def desc(self) -> Optional[str]:
        """一句话描述（F06）。"""
        return self._str("desc")

    # ---- stats（F07 / 1.2 九键；漏配键按难度模板补全）----
    @property
    def stats(self) -> Mapping[str, object]:
        """九属性对象（hp/mp/str/int/con/spr/foc/agi/luk）；缺省空对象。"""
        return self._mapping("stats")

    def stat(self, key: str) -> Optional[float]:
        """按键取九属性数值（类型不符/缺失 → None）。"""
        v = self.stats.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def stats_hp(self) -> Optional[float]:
        return self.stat("hp")

    @property
    def stats_mp(self) -> Optional[float]:
        return self.stat("mp")

    @property
    def stats_str(self) -> Optional[float]:
        return self.stat("str")

    @property
    def stats_int(self) -> Optional[float]:
        return self.stat("int")

    @property
    def stats_con(self) -> Optional[float]:
        return self.stat("con")

    @property
    def stats_spr(self) -> Optional[float]:
        return self.stat("spr")

    @property
    def stats_foc(self) -> Optional[float]:
        return self.stat("foc")

    @property
    def stats_agi(self) -> Optional[float]:
        return self.stat("agi")

    @property
    def stats_luk(self) -> Optional[float]:
        return self.stat("luk")

    # ---- 弱点 / PV / 抗性（F08-F11 / 1.3）----
    @property
    def weakness(self) -> Mapping[str, object]:
        """双维弱点 {types: string[], elements: {元素ID: 倍率}}（F08）。"""
        return self._mapping("weakness")

    @property
    def pv(self) -> Optional[float]:
        """防护值（F09；≥0，档默认 10/75/300；木桩强制 0）。"""
        return self._num("pv")

    @property
    def pv_recover(self) -> Optional[str]:
        """战斗结束 PV 是否重置：battle_end/none（F10）。"""
        return self._str("pv_recover")

    @property
    def resistance(self) -> Mapping[str, object]:
        """初始抗性 map（负面效果 ID → 0-100）+ immune 数组（F11 / W03-W04）。"""
        return self._mapping("resistance")

    # ---- 行动表 / 特殊行动 / 连招（F12-F14 / 1.4）----
    @property
    def actions(self) -> Tuple[Mapping[str, object], ...]:
        """行动表条目（A01-A03d：action/probability/weight/condition/cooldown/hungry）。"""
        return self._entries("actions")

    @property
    def special_actions(self) -> Tuple[Mapping[str, object], ...]:
        """特殊行动条目（A04-A15：id/action/trigger/once/priority/.../chain_ref）。"""
        return self._entries("special_actions")

    @property
    def chains(self) -> Tuple[Mapping[str, object], ...]:
        """顶层连招表条目（F14：{id, actions:[{action, chance, role, armor}]}，连招唯一载体）。"""
        return self._entries("chains")

    # ---- 掉落 / 图鉴（F15-F16 / 1.5-1.6）----
    @property
    def drops(self) -> Mapping[str, object]:
        """三类掉落容器 {battle:[], special:[], death:[]}（F15）。"""
        return self._mapping("drops")

    @property
    def lore(self) -> Tuple[Mapping[str, object], ...]:
        """图鉴情报条目 {unlock: 1-100 递增, desc}（F16）。"""
        return self._entries("lore")

    # ---- 木桩向（F17-F18）----
    @property
    def def_base(self) -> Optional[float]:
        """防御基准（F17；≥0；配置=直读，未配=映射 stats.con）。"""
        return self._num("def_base")

    @property
    def elem_res(self) -> Mapping[str, object]:
        """元素抗性基准（F18；元素 ID → 正=减伤/负=增伤）。"""
        return self._mapping("elem_res")


@dataclass(frozen=True)
class MapDef(BaseDef):
    """maps.json 条目。"""


@dataclass(frozen=True)
class StatDef(BaseDef):
    """stats.json 键空间条目（键 = id）。"""


@dataclass(frozen=True)
class NpcDef(BaseDef):
    """npc.json 条目。"""


# 模块/kind → Def 类映射（loader 构建 registry 时使用）
DEF_CLASSES: Mapping[str, Any] = {
    "effect": EffectDef,
    "status": StatusDef,
    "mark": MarkDef,
    "skill_chain": SkillChainDef,
    "action": ActionDef,
    "item": ItemDef,
    "equipment": ItemDef,
    "trait": TraitDef,
    "enemy": EnemyDef,
    "map": MapDef,
    "stat": StatDef,
    "npc": NpcDef,
    "conditional": BaseDef,  # 条件加成规则（细化_3b §3.2）——BaseDef 承载 id+raw，无专属字段
}


# =====================================================================================
# Manifest（细化_3e §1.2：@dataclass frozen，必填字段 name/version/schema_version/modules）
# =====================================================================================


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    schema_version: int
    author: str
    modules: Tuple[str, ...]  # 启用模块清单（无 .json 后缀）
    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Manifest":
        raw_modules = data.get("modules", [])
        modules = [str(m) for m in raw_modules if isinstance(m, str)] if isinstance(raw_modules, list) else []
        sv = data.get("schema_version", 0)
        schema_version = int(sv) if isinstance(sv, (int, float)) and not isinstance(sv, bool) else 0
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "")),
            schema_version=schema_version,
            author=str(data.get("author", "") or ""),
            modules=tuple(modules),
            raw=copy.deepcopy(dict(data)),
        )


# =====================================================================================
# Pack（loader 返回值，细化_3e §5.1 load_pack -> Pack）
# =====================================================================================

# 前向引用"打标"（避免 content.models 反向 import registry）；由 loader 组装。
# Pack.registry 类型标注用 TYPE_CHECKING 引用。
if False:  # pragma: no cover
    from qbot_rpg.content.registry import Registry  # noqa: F401


@dataclass(frozen=True)
class Pack:
    """一次成功加载的内容包：五段管线 A→D 的产物（细化_3e §1.1）。"""

    pack_id: str  # 内容包目录名
    manifest: Manifest
    modules: Mapping[str, object]  # 模块名 → parsed JSON（结构化数据）
    report: ValidationReport
    registry: "Any"  # Registry 实例（D 阶段构建；见 content/registry.py）

    @property
    def warnings(self) -> Tuple[PackWarning, ...]:
        return self.report.warnings


__all__ = [
    "PackError",
    "PackWarning",
    "ValidationReport",
    "FieldMeta",
    "ModuleMeta",
    "FieldMetaTable",
    "BaseDef",
    "EffectDef",
    "StatusDef",
    "MarkDef",
    "SkillChainDef",
    "ActionDef",
    "ItemDef",
    "TraitDef",
    "EnemyDef",
    "MapDef",
    "StatDef",
    "NpcDef",
    "DEF_CLASSES",
    "Manifest",
    "Pack",
]
