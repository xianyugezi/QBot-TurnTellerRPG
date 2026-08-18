"""领域基础类型别名（TypeAlias / 公共枚举）——全框架最底层，仅标准库。

依据：
  - 细化_3a_架构分层契约 §2.2 line 141（`data/types.py` # TypeAlias / 公共枚举
    （stats 键空间等）【框架】L682-701）
  - 细化_3a_架构分层契约 §3.1 类型约束总则（Python 3.9 兼容写法：TypeAlias +
    Optional/List/Dict，不追求 ``|`` 新语法）
  - 共享接口契约（M0 data 层）：PlayerQID / ItemID / StatusID / MarkID /
    EffectID / SkillID / AttrID 全部 TypeAlias（运行时即 str）
  - 细化_3a_架构分层契约 §3.4（配置类型 Def 系落 content/，本文件只提供
    TypeAlias/NewType 供类型标注；content/ 层只 import 本文件）

说明：
  - 玩家侧 ID（PlayerQID/AttrID 等）为 TypeAlias：`PlayerQID = str`，类型透明，
    可直接用普通 str 赋值（供 core/world/storage/B-C 组 import）。
  - 内容包侧 ID（PackID/ModuleName/...）为 NewType：运行时仍是 str，仅静态检查
    区分语义，供 content/registry 与 content/validator 类型标注。
"""

from typing import NewType, TypeAlias  # Python >=3.10；Python 3.9 由 typing_extensions 兜底

# ---------------------------------------------------------------------------
# M0 共享接口契约：玩家数据层 TypeAlias（B/C 组按此 import，字段名/类型不可改）
# ---------------------------------------------------------------------------
PlayerQID: TypeAlias = str        # 玩家数据 key = QQ 号（全局，跨群/私聊同一角色）
ItemID: TypeAlias = str           # 物品实例引用 ID（ID+名称冗余存储）
StatusID: TypeAlias = str         # 状态实例引用 ID
MarkID: TypeAlias = str           # 印记/标记引用 ID
EffectID: TypeAlias = str         # 效果引用 ID
SkillID: TypeAlias = str          # 技能/行动引用 ID
AttrID: TypeAlias = str           # 属性引用 ID（stats.json 注册键，细化_3b §4.1）

# ---------------------------------------------------------------------------
# 内容包 ID 空间（同一类型 ID 在此收敛，供 content/registry 与 content/validator）
# ---------------------------------------------------------------------------
PackID = NewType("PackID", str)                  # 内容包 ID（目录名）
ModuleName = NewType("ModuleName", str)          # 模块名（无 .json 后缀），如 "effects"
SkillChainID = NewType("SkillChainID", str)      # 连段链 ID（skill_chains）
ActionID = NewType("ActionID", str)              # 动作 ID（action）
TraitID = NewType("TraitID", str)                # 特质 ID（traits）
EnemyID = NewType("EnemyID", str)                # 怪物 ID（enemies）
MapID = NewType("MapID", str)                    # 地图 ID（maps）
StatKey = NewType("StatKey", str)                # stats.json 键空间键（小写 snake_case）
NpcID = NewType("NpcID", str)                    # NPC ID（npc）
SlotID = NewType("SlotID", str)                  # 装备部位 ID（equipment 部位互斥图节点）
TaskID = NewType("TaskID", str)                  # 任务 ID（引用目标之一，M4 起消费）
RegistryKind = NewType("RegistryKind", str)      # 例："effect"/"status"/"item"/"stat"…

# 内容包侧 ItemID/EffectID/StatusID/MarkID/SkillID 由共享 TypeAlias 同义复用
# （运行时均为 str，静态检查按上下文）。

_CONTENT_ID_ALIASES = ("PackID", "ModuleName", "SkillChainID", "ActionID",
                       "TraitID", "EnemyID", "MapID", "StatKey", "NpcID",
                       "SlotID", "TaskID", "RegistryKind")

__all__ = [
    "TypeAlias",
    "NewType",
    "PlayerQID",
    "ItemID",
    "StatusID",
    "MarkID",
    "EffectID",
    "SkillID",
    "AttrID",
    *_CONTENT_ID_ALIASES,
]
