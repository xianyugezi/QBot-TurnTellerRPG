"""M13 6c 资源轴注册段数据模型（细化_6c §1.1 M1：资源轴两型注册段 10 字段）。

文件名：resource_axis_models.py
创建时间：2026-09-02
依据：docs/细化/细化_6c_资源轴与职业机制.md（497 行 v1.0）：
  - M1 资源轴两型注册段 10 字段：name/type/icon/base/max/reset/display/
    max_per_pool/pools/pool_icons；
  - D-01 两型判别：数值型（rage 单值）/ 子池型（element_energy 池级展开）；
    D-01b type 归一：resource_custom → resource（兼容旧内容包）。

功能描述：
  - ResourceAxisDef frozen dataclass（10 字段，默认值兜底——漏配=合理默认不报错）；
  - is_pooled 判别：pools 非空 → 子池型；
  - resource_axis_fields() 10 键 FieldMeta 登记表（供 field_meta/校验器使用）。

工程补白（契约/细化未显式定义处的实现口径，显式标注供审查）：
  P-1  type 归一：stats.json 既有条目 type=resource（hp/mp），6c 契约两型
        rage/element_energy 为细分——本模块 type 字段宽松接受
        resource/resource_custom/rage/element_energy，is_pooled 以 pools
        非空为准（D-01b）。
  P-2  base/max 缺省 0/100（对齐 8B core/resource_axis.ResourceAxis 缺省）。
  P-3  reset 缺省 "battle"（契约三枚举 battle/keep/battle_start，战斗结束清零默认）。

铁律：零 NoneBot import；G0：content 层零 engine/core import（resource_axis
数据经 ctx 注入）；零定时器/零睡眠；不 git commit。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from qbot_rpg.content.models import FieldMeta  # noqa: F401 - 类型标注

# =====================================================================================
# 常量
# =====================================================================================

# 资源轴类型（契约 M1：数值型/子池型；P-1 兼容旧键）
AXIS_TYPES_NUMERIC: Tuple[str, ...] = ("rage", "resource")
AXIS_TYPES_POOLED: Tuple[str, ...] = ("element_energy", "resource_custom")
AXIS_TYPES: Tuple[str, ...] = AXIS_TYPES_NUMERIC + AXIS_TYPES_POOLED

# reset 三枚举（契约 M3：战斗结束清零/保留/下次战斗开始置 base）
RESET_BATTLE: str = "battle"
RESET_KEEP: str = "keep"
RESET_BATTLE_START: str = "battle_start"
RESET_VALUES: Tuple[str, ...] = (RESET_BATTLE, RESET_KEEP, RESET_BATTLE_START)

# 默认值（P-2/P-3）
DEFAULT_BASE: int = 0
DEFAULT_MAX: int = 100
DEFAULT_RESET: str = RESET_BATTLE
DEFAULT_MAX_PER_POOL: int = 3


# =====================================================================================
# ResourceAxisDef
# =====================================================================================

class ResourceAxisDef:
    """资源轴注册条目（M1 10 字段；frozen 语义——只读访问器 + raw 冗余镜像）。

    对齐 8B core/resource_axis.ResourceAxis 的读取器形态（core 层不 import
    content——两处字段口径同源，防键空间分裂）。
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw: Dict[str, Any] = dict(raw or {})

    # ---- 冗余镜像 ----
    @property
    def raw(self) -> Dict[str, Any]:
        return dict(self._raw)

    # ---- 字段读取器（默认值兜底）----
    @property
    def name(self) -> str:
        v = self._raw.get("name")
        return v if isinstance(v, str) and v else ""

    @property
    def type(self) -> str:
        v = self._raw.get("type")
        if isinstance(v, str) and v:
            # P-1：type 归一（resource_custom → element_energy 语义）
            return "element_energy" if v == "resource_custom" else v
        return "resource"

    @property
    def icon(self) -> str:
        v = self._raw.get("icon")
        return v if isinstance(v, str) else ""

    @property
    def base(self) -> int:
        v = self._raw.get("base")
        return v if isinstance(v, int) and not isinstance(v, bool) else DEFAULT_BASE

    @property
    def max(self) -> int:
        v = self._raw.get("max")
        return v if isinstance(v, int) and not isinstance(v, bool) else DEFAULT_MAX

    @property
    def reset(self) -> str:
        v = self._raw.get("reset")
        if isinstance(v, str) and v in RESET_VALUES:
            return v
        return DEFAULT_RESET

    @property
    def display(self) -> str:
        v = self._raw.get("display")
        return v if isinstance(v, str) else ""

    @property
    def max_per_pool(self) -> int:
        v = self._raw.get("max_per_pool")
        return v if isinstance(v, int) and not isinstance(v, bool) else DEFAULT_MAX_PER_POOL

    @property
    def pools(self) -> Tuple[str, ...]:
        v = self._raw.get("pools")
        if isinstance(v, list):
            return tuple(p for p in v if isinstance(p, str) and p)
        return ()

    @property
    def pool_icons(self) -> Dict[str, str]:
        v = self._raw.get("pool_icons")
        if isinstance(v, Mapping):
            return {str(k): str(x) for k, x in v.items() if isinstance(x, str)}
        return {}

    # ---- 两型判别（D-01）----
    @property
    def is_pooled(self) -> bool:
        """子池型：pools 非空（D-01：数值型单值 / 子池型池级展开）。"""
        return bool(self.pools)


# =====================================================================================
# 登记表（供 field_meta/校验器）
# =====================================================================================

def resource_axis_fields() -> Dict[str, FieldMeta]:
    """M1 注册段 10 键 FieldMeta 登记表（stats.json 子条目 children 用）。"""
    return {
        "name": FieldMeta(type="str"),
        "type": FieldMeta(type="enum", enum=AXIS_TYPES, default="resource"),
        "icon": FieldMeta(type="str", soft_label=True),
        "base": FieldMeta(type="number", range_min=0, default=DEFAULT_BASE),
        "max": FieldMeta(type="number", range_min=0, default=DEFAULT_MAX),
        "reset": FieldMeta(type="enum", enum=RESET_VALUES, default=DEFAULT_RESET),
        "display": FieldMeta(type="str", soft_label=True),
        "max_per_pool": FieldMeta(type="number", range_min=0, default=DEFAULT_MAX_PER_POOL),
        "pools": FieldMeta(type="list", element=FieldMeta(type="str"), soft_label=True),
        "pool_icons": FieldMeta(type="obj", soft_label=True),
    }


__all__ = [
    "AXIS_TYPES", "AXIS_TYPES_NUMERIC", "AXIS_TYPES_POOLED",
    "RESET_BATTLE", "RESET_KEEP", "RESET_BATTLE_START", "RESET_VALUES",
    "DEFAULT_BASE", "DEFAULT_MAX", "DEFAULT_RESET", "DEFAULT_MAX_PER_POOL",
    "ResourceAxisDef", "resource_axis_fields",
]
