"""内容包：loader/validator/registry/hot_reload 四件套（细化_3e / 细化_3e2）。零 NoneBot import。

分层（细化_3a §2.2）：content 依赖方向仅 ↓ data；Def 配置类型与校验规则引擎全在本层（U2 铁律）。
"""

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.hot_reload import (
    DEFAULT_MAX_CONSECUTIVE_FAILURES,
    DEFAULT_POLL_INTERVAL_S,
    HotReloadWatcher,
    ReloadResult,
)
from qbot_rpg.content.loader import PackLoadError, build_pack, load_pack
from qbot_rpg.content.models import (
    ActionDef,
    BaseDef,
    EffectDef,
    EnemyDef,
    FieldMeta,
    FieldMetaTable,
    ItemDef,
    Manifest,
    MapDef,
    MarkDef,
    ModuleMeta,
    NpcDef,
    Pack,
    PackError,
    PackWarning,
    SkillChainDef,
    StatDef,
    StatusDef,
    TraitDef,
    ValidationReport,
)
from qbot_rpg.content.registry import Registry, RegistrySnapshot
from qbot_rpg.content.validator import check_pack, check_formula

__all__ = [
    # models
    "PackError",
    "PackWarning",
    "ValidationReport",
    "Pack",
    "Manifest",
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
    "FieldMeta",
    "ModuleMeta",
    "FieldMetaTable",
    # validator
    "check_pack",
    "check_formula",
    # registry
    "Registry",
    "RegistrySnapshot",
    # loader
    "PackLoadError",
    "load_pack",
    "build_pack",
    # hot_reload
    "HotReloadWatcher",
    "ReloadResult",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_MAX_CONSECUTIVE_FAILURES",
    # field_meta
    "default_field_meta_table",
]
