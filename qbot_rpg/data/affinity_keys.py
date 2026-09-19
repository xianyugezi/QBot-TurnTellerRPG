"""相性通用层键空间注册表（批38 · ④；data 层纯数据模块）。

唯一源：相性池类型 / 材料互动类型 / settings 段键 / 词条行 `requires_affinity` 读取口径——
`core/affinity.py`（计算/查询）与 `content/validator.py`（校验）共用本表，避免两处各写一套枚举
（G0 依赖矩阵 `content → data`、`core → data` 均允许；`content -/-> core`，故共用常量必须落
data 层，与 `data/gear_stats.py` 同先例）。

零 import、零 IO、零业务名（相性 id / 池 id / 词条键全部由内容包声明）。
"""
from __future__ import annotations

from typing import Any, Mapping, Tuple

__all__ = [
    "POOL_COMMON",
    "POOL_EXCLUSIVE",
    "POOL_LINKAGE",
    "POOL_KINDS",
    "REACTION_CONFLICT",
    "REACTION_AMPLIFY",
    "REACTION_REVERSE",
    "REACTION_KINDS",
    "AFFINITY_KEYS",
    "affinity_requires",
]

# 池类型（内容包声明 kind；框架只认这三类结构语义）
POOL_COMMON = "common"
POOL_EXCLUSIVE = "exclusive"
POOL_LINKAGE = "linkage"
POOL_KINDS: Tuple[str, ...] = (POOL_COMMON, POOL_EXCLUSIVE, POOL_LINKAGE)

# 材料互动三类（原案 §12：互相减少 / 互相增加 / A→B 转换）
REACTION_CONFLICT = "conflict"
REACTION_AMPLIFY = "amplify"
REACTION_REVERSE = "reverse"
REACTION_KINDS: Tuple[str, ...] = (REACTION_CONFLICT, REACTION_AMPLIFY, REACTION_REVERSE)

# settings 顶层四段（唯一数据落点；引擎/校验/编辑器共用）
AFFINITY_KEYS: Tuple[str, ...] = (
    "affinities", "affinity_pools", "affinity_linkage", "affinity_reactions",
)


def affinity_requires(entry: Any) -> Tuple[str, ...]:
    """词条行 `requires_affinity`（str 或 list）→ 相性 id 元组（缺省空 = 通用）。"""
    if not isinstance(entry, Mapping):
        return ()
    req = entry.get("requires_affinity")
    if isinstance(req, str):
        return (req,) if req else ()
    if isinstance(req, (list, tuple)):
        return tuple(str(x) for x in req if isinstance(x, str) and x)
    return ()
