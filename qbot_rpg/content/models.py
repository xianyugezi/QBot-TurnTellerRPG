"""内容包领域模型：校验报告类型 / 字段元数据表 / 配置 Def 类型 / Manifest / Pack。

依据：
  - 细化_3e_loader校验接线 §5.1（PackError/PackWarning/ValidationReport 接口定义，红拦 R-1~R-5、黄提示 Y-1~Y-8）
  - 细化_3e_loader校验接线 §5.3（字段元数据表 = 校验唯一数据源：名称/类型/默认值/范围/引用目标；缺失字段默认放行）
  - 细化_3a_架构分层契约 §3.3 U2（配置类型 Def 系落 content/，运行时实例落 data/）+ §3.4（配置/运行分工）
  - 细化_3e_loader校验接线 §1.7（PackLoadError 领域异常放 loader.py；本文件只定义校验/元数据/Def 结构）

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
class ValidationReport:
    """整包校验报告：errors 非空即阻断（D-01/D-02）。"""

    errors: Tuple[PackError, ...] = ()
    warnings: Tuple[PackWarning, ...] = ()

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
    def from_entry(cls, entry: Mapping[str, object], name_field: str = "name") -> "BaseDef":
        eid = str(entry.get("id", ""))
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
    """action.json 条目。"""


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
    """enemies.json 条目。"""

    @property
    def hp(self) -> Optional[float]:
        v = self.raw.get("hp")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def atk(self) -> Optional[float]:
        v = self.raw.get("atk")
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


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
