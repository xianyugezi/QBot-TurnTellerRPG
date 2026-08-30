"""M9 锻造数据层 · 独立模块（路 0A）：forge.json 数据模型 Def 类 + 专项校验器。

文件名：forge_models.py
创建时间：2026-08-30
作者：Hermes 子agent-0A（M9 锻造实现组路0A：并发同仓，仅新建本文件 +
tests/unit/test_forge_models.py）

功能描述：
  - ForgeTree / ForgeNode / MaterialReq / SetSkill / ForgeSet / AugmentRow /
    LimitByRarity / ForgeSettings 八个 frozen dataclass（ID/名称冗余铁律9：
    树/节点/套装/客制项继承 BaseDef 承载 id+name 冗余镜像 raw；行内子结构
    MaterialReq/SetSkill/LimitByRarity 与全局段 ForgeSettings 为独立 frozen）。
  - validate_forge(modules, report) 纯函数（(modules, report) 鸭子类型）：
    V1~V15 硬校验（失败写红=加载失败）+ V16/W1~W6 黄提示（不阻断）+
    2c2d V1~V8 硬/W1~W4 黄（针对 sets/augments），规则全表见共享契约 §六。
  - forge_module_meta() 返回 ModuleMeta（供主 agent 收口接线 field_meta；
    注意 forge.json 顶层是 obj 非 list——entry_type="object"，对齐 manifest/
    settings 形态；loader 走独立 parse 或 obj 模块形态由主 agent 收口裁决）。
  - merge_node_item(items_def, node) 双源仲裁辅助函数（AR-1~5：items 基础 +
    节点改造覆盖/追加/品质仲裁；实例快照入档归批1路1A，本批只做数据层合并）。

依据：
  - docs/m9_shared_contract.md（共享契约 §〇~§八：字段表/校验规则/接口签名权威）：
    §一 ForgeTree(T-01~05) / §二 ForgeNode(N-01~17)+MaterialReq(M-01~04)+双源仲裁
    AR-1~5 / §三 ForgeSettings(S-01~05+2c2d 补白键) / §四 Set(SET-01~08)+SetSkill
    (SK-01~04) / §五 Augment+LIM / §六 校验器规则（V1-V15 硬 / V16+W1-W6 黄 /
    2c2d V1-V8 硬 / W1-W4 黄）/ §七 接口签名 / §八 loader+field_meta 登记。
  - docs/细化/细化_2c2a_锻造派生树schema.md（§一 字段 schema / §五 校验器 /
    §六 验收 TC-01~27）。
  - docs/细化/细化_2c2d_锻造套装与客制.md（SET/AUG/LIM 字段 + 校验器 V1-V8/W1-W4）。
  - docs/m9_接口摸底.md（M8 复用件与坑位：loader 只收 list 模块时 forge 走独立
    parse——DEF_CLASSES 无专属 Def → BaseDef 回退 + core 层 parse_* 读取 raw）。
  - 模式参考：qbot_rpg/content/alchemy_models.py（Def dataclass + validate 函数
    独立模块形态 + _emit/_err/_warn 鸭子类型）；qbot_rpg/content/map_models.py
    （validate_maps(modules, report) 形态）；qbot_rpg/content/alchemy_settings.py
    （ModuleMeta 工厂模式供 field_meta 登记）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  1. forge.json 顶层是 obj 非 list（共享契约 §〇）。validate_forge 读取
     modules["forge"] 为 Mapping：trees/sets/augments/settings 四段；非 Mapping
     （缺失/形态异常）→ 跳过不硬拦（对齐既有校验器「模块未接线默认放行」惯例）。
  2. 2c2d V7 三子项级别仲裁：共享契约 §六 2c2a W3/W4 与 2c2d W3/W4 编号重名。
     本实现统一按「黄提示不阻断」输出——king_only level<7 → 黄（rule=king_only_
     level，2c2d V7 语义）；final_tier 非 final+legendary → 黄（rule=final_tier）；
     augmentable 非 final 武器 → 黄（rule=augmentable，复用 2c2a V16 文案）。硬
     拦截仅保留 2c2d V1~V6 + V8 结构/引用类。编号冲突在文件头补白声明。
  3. V6 叶子判定：子引用 = 其它节点 parent 指向该节点（branch 为出边不算子）。
     叶子（无 parent 指向）必须 final=true；final=true 不得被 parent 指向。
  4. V9 改造键空间：节点 stats 键须 ∈ (items 条目实际键 ∪ FORGE_STAT_KEY_SPACE
     标准属性键 ∪ 8 元素键)，防新键漂移；items 缺失/无该条目 → 跳过（放行）。
  5. V10 材料类判定：items 条目 type=="material" 或含 material_tier 键（契约
     §八 材料类扩展）→ 材料类；items 缺失 → 引用存在性跳过（对齐既有惯例）。
  6. W4 素材死锁风险：settings.synth_ratio_3to1==false 且 forge 素材需求中出现
     稀有素材（material_tier=rare 或行覆写 tier=rare）→ 黄提示（缺 3:1 升档渠道）。
  7. W5 规模：武器树节点总数>500 / 防具树节点总数>800 → 黄（契约 §六 W5）。
  8. 2c2d V3 档位连续性口径：同一 skill 的档位集合须为 {2,3,5} 的连续前缀
     （从 2 起无跳档）——合法 {2}/{2,3}/{2,3,5}；拦 {2,5}/{3,5}/{3}/{5} 及
     非法 piece_count（TC-23：2,4,5 缺 3 → V3 拦：4 非法+3 缺失）。「缺 5 档
     留 2/3」按跳档（2,3 到 5 之间留档不完整）口径不拦（满配可后补，不制造
     非预期激活曲线；TC-23 负例全部红拦）。
  9. W3（settings 关但数据存在）取 forge.settings 段 sets_enabled/augments_
     enabled（默认 true）；settings 段缺失 → 视为开（不提示）。
  10. augments 段形态：共享契约 §五 为 {augments:[], limit_by_rarity:[]} 对象；
      2c2a D-04 写 array<Augment>（登记点未展开）。本实现兼容双形态：Mapping →
      取 augments 键/lmit_by_rarity 键；list → 视为 augments 数组（limit 空）。
  11. report 收集器三形态：report.error/warning 方法 → report._err/_warn 方法 →
      {"errors":[],"warnings":[]} dict（_emit 兜底，任务强制）。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；
纯函数；确定性；不写定时器/睡眠调用；不引入随机；不 git commit。
仅依赖 qbot_rpg.content.models（BaseDef/FieldMeta/ModuleMeta）与标准库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Set, Tuple, cast

from qbot_rpg.content.models import BaseDef, FieldMeta, ModuleMeta

# =====================================================================================
# 常量 / 枚举注册表（共享契约 §一~§五 + 细化 2c2a/2c2d）
# =====================================================================================

# 部位枚举（T-03 / N-04 / 2c2d V2 防具五部位）
FORGE_TREE_TYPES: Tuple[str, ...] = (
    "weapon", "armor_head", "armor_body", "armor_hand", "armor_leg", "armor_foot",
)
ARMOR_TYPES: Tuple[str, ...] = (
    "armor_head", "armor_body", "armor_hand", "armor_leg", "armor_foot",
)

# 品质四档（N-12 / V13；历史整数 1-4 兼容映射）
RARITY_TIERS: Tuple[str, ...] = ("normal", "fine", "epic", "legendary")
RARITY_INT_MAP: Dict[int, str] = {1: "normal", 2: "fine", 3: "epic", 4: "legendary"}

# 素材档位两档（M-03 / V11；与装备品质四档独立，不混用——共享契约 §十 坑位4）
MATERIAL_TIERS: Tuple[str, ...] = ("normal", "rare")

# 孔位等级（N-09 / V14；框架 3.5 slot_level）
SLOT_LEVELS: Tuple[int, ...] = (1, 2, 3)

# 元素注册表（N-08 stats.element；content 层常量镜像，G0 单向依赖不 import core）
FORGE_ELEMENTS: Tuple[str, ...] = (
    "earth", "fire", "water", "wind", "thunder", "crystal", "moon", "void",
)

# 改造键空间（V9 防新键漂移；items 条目实际键 ∪ 此标准属性键空间 ∪ 元素键）
FORGE_STAT_KEY_SPACE: Tuple[str, ...] = (
    "atk", "def", "str", "int", "con", "spr", "foc", "agi", "luk",
    "hp", "mp", "crit", "element", "element_value",
)

# 套装变体（SET-03 / 2c2d V1）
SET_VARIANTS: Tuple[str, ...] = ("alpha", "beta")

# 套装技能档位（SK-01 / 2c2d V3）
SET_PIECE_COUNTS: Tuple[int, ...] = (2, 3, 5)

# 客制项 kind（AUG-03 / 2c2d V4）
AUGMENT_KINDS: Tuple[str, ...] = ("numeric", "slot")

# 客制次数表 quality 白名单（LIM-01：epic/legendary 参与客制；V6 四档枚举硬拦）
LIMIT_RARITY_QUALITIES: Tuple[str, ...] = ("normal", "fine", "epic", "legendary")

# 规模建议（2c2a §2.3 / W5：超量黄提示不阻断）
WEAPON_NODE_LIMIT: int = 500
ARMOR_NODE_LIMIT: int = 800

# 套装技能默认封顶（SK-03 / 2c2d W4；内容包可改上限，本层按默认 3 检）
SET_LEVEL_MAX: int = 3

# 铸造王专属配方节点最低等级（N-16 / 2c2d V7 king_only → level≥7 黄）
KING_ONLY_LEVEL_MIN: int = 7


# =====================================================================================
# Def 类型（ID/名称冗余铁律9：树/节点/套装/客制项继承 BaseDef 冗余镜像 raw）
# =====================================================================================


@dataclass(frozen=True)
class ForgeTree(BaseDef):
    """forge.json trees[] 一棵派生树（契约 §一 T-01~05）。

    id/name 由 BaseDef 承载（from_entry 冗余镜像 raw）；type/roots/nodes 访问器见下。
    """

    @property
    def tree_type(self) -> Optional[str]:
        v = self.raw.get("type")
        return v if isinstance(v, str) else None

    @property
    def roots(self) -> Tuple[str, ...]:
        v = self.raw.get("roots")
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    @property
    def nodes(self) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get("nodes")
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    def node_defs(self) -> Tuple["ForgeNode", ...]:
        """nodes → ForgeNode 元组（含原始索引 index 供诊断定位）。"""
        out: List[ForgeNode] = []
        for i, e in enumerate(self.nodes):
            n = ForgeNode.from_entry(e)
            out.append(cast(ForgeNode, n))
        return tuple(out)


@dataclass(frozen=True)
class ForgeNode(BaseDef):
    """forge 树节点（契约 §二 N-01~17；item/output_item 别名二选一）。

    id/name 由 BaseDef 承载；其余字段访问器见下。materials → MaterialReq 元组。
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

    def _entries(self, key: str) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get(key)
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    @property
    def item(self) -> Optional[str]:
        """产物装备引用（N-03；item/output_item 别名二选一，不双写——TC-08）。"""
        return self._str("item") or self._str("output_item")

    @property
    def item_alias_duplicate(self) -> bool:
        """item 与 output_item 双写（TC-08 硬错：别名二选一不双写）。"""
        return bool(self.raw.get("item")) and bool(self.raw.get("output_item"))

    @property
    def node_type(self) -> Optional[str]:
        return self._str("type")

    @property
    def level(self) -> Optional[int]:
        return self._int("level")

    @property
    def parent(self) -> Optional[str]:
        v = self.raw.get("parent")
        return v if isinstance(v, str) and v else None

    @property
    def branch(self) -> Tuple[str, ...]:
        v = self.raw.get("branch")
        return tuple(x for x in v if isinstance(x, str) and x) if isinstance(v, list) else ()

    @property
    def stats(self) -> Mapping[str, object]:
        return self._mapping("stats")

    @property
    def slots(self) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get("slots")
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    @property
    def materials(self) -> Tuple[Mapping[str, object], ...]:
        return self._entries("materials")

    def material_defs(self) -> Tuple["MaterialReq", ...]:
        return tuple(MaterialReq.from_entry(e, index=i)
                     for i, e in enumerate(self.materials))

    @property
    def cost(self) -> Mapping[str, object]:
        return self._mapping("cost")

    @property
    def rarity(self) -> object:
        return self.raw.get("rarity")

    @property
    def monster_source(self) -> Optional[str]:
        return self._str("monster_source")

    @property
    def is_final(self) -> Optional[bool]:
        return self._bool("final")

    @property
    def augmentable(self) -> Optional[bool]:
        return self._bool("augmentable")

    @property
    def king_only(self) -> Optional[bool]:
        return self._bool("king_only")

    @property
    def final_tier(self) -> Optional[bool]:
        return self._bool("final_tier")


@dataclass(frozen=True)
class MaterialReq:
    """素材需求行（契约 §二 M-01~04：item/count/tier/source_override）。

    行内结构（无 id），独立 frozen；from_entry 轻量容错解析。
    """

    item: Optional[str]
    count: Optional[int]
    tier: Optional[str]  # normal/rare 覆写（M-03；缺省派生自 items material_tier）
    source_override: Optional[str]  # 来源提示覆写（M-04）
    index: int = field(default=0)  # 【补白】行序号（非 schema 字段，仅诊断定位用）

    @classmethod
    def from_entry(cls, entry: Mapping[str, object], index: int = 0) -> "MaterialReq":
        item = entry.get("item")
        count = entry.get("count")
        tier = entry.get("tier")
        src = entry.get("source_override")
        return cls(
            item=item if isinstance(item, str) else None,
            count=count if isinstance(count, int) and not isinstance(count, bool) else None,
            tier=tier if isinstance(tier, str) else None,
            source_override=src if isinstance(src, str) else None,
            index=index,
        )


@dataclass(frozen=True)
class SetSkill:
    """套装技能档位（契约 §四 SK-01~04：piece_count/skill/level/effect_ref）。

    行内结构（无 id），独立 frozen；from_entry 轻量容错解析。
    """

    piece_count: Optional[int]
    skill: Optional[str]
    level: Optional[int]
    effect_ref: str = ""

    @classmethod
    def from_entry(cls, entry: Mapping[str, object]) -> "SetSkill":
        pc = entry.get("piece_count")
        skill = entry.get("skill")
        lv = entry.get("level")
        er = entry.get("effect_ref")
        return cls(
            piece_count=pc if isinstance(pc, int) and not isinstance(pc, bool) else None,
            skill=skill if isinstance(skill, str) else None,
            level=lv if isinstance(lv, int) and not isinstance(lv, bool) else None,
            effect_ref=er if isinstance(er, str) else "",
        )


@dataclass(frozen=True)
class ForgeSet(BaseDef):
    """forge.json sets[] 一条套装记录 = 一个 variant（契约 §四 SET-01~08）。

    id/name 由 BaseDef 承载（族 id 由 raw["id"] 冗余）；skills → SetSkill 元组。
    """

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _bool(self, key: str) -> Optional[bool]:
        v = self.raw.get(key)
        return v if isinstance(v, bool) else None

    @property
    def variant(self) -> Optional[str]:
        return self._str("variant")

    @property
    def pieces(self) -> Tuple[str, ...]:
        v = self.raw.get("pieces")
        return tuple(x for x in v if isinstance(x, str) and x) if isinstance(v, list) else ()

    @property
    def skills(self) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get("skills")
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    def skill_defs(self) -> Tuple[SetSkill, ...]:
        return tuple(SetSkill.from_entry(e) for e in self.skills)

    @property
    def desc(self) -> Optional[str]:
        return self._str("desc")

    @property
    def enabled(self) -> Optional[bool]:
        return self._bool("enabled")

    @property
    def codex_group(self) -> Optional[str]:
        return self._str("codex_group")


@dataclass(frozen=True)
class AugmentRow(BaseDef):
    """forge.json augments.augments[] 一条客制项（契约 §五 AUG-01~12）。

    id/name 由 BaseDef 承载；cost → 消耗行元组。
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

    @property
    def aug_kind(self) -> Optional[str]:
        """客制归口渠道 numeric/slot（AUG-03；命名 aug_kind 避 BaseDef.kind 冲突，同
        RecipeDef.recipe_kind 口径）。"""
        return self._str("kind")

    @property
    def effect(self) -> Optional[str]:
        return self._str("effect")

    @property
    def stat_key(self) -> Optional[str]:
        return self._str("stat_key")

    @property
    def value(self) -> Mapping[str, object]:
        return self._mapping("value")

    @property
    def cost(self) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get("cost")
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    @property
    def repeatable(self) -> Optional[bool]:
        return self._bool("repeatable")

    @property
    def max_repeat(self) -> Optional[int]:
        return self._int("max_repeat")

    @property
    def slot_level(self) -> Optional[int]:
        return self._int("slot_level")

    @property
    def disabled(self) -> Optional[bool]:
        return self._bool("disabled")

    @property
    def trace(self) -> Optional[bool]:
        return self._bool("trace")


@dataclass(frozen=True)
class LimitByRarity:
    """客制次数行（契约 §五 LIM-01~03：quality/times/final_only）。

    行内结构（无 id），独立 frozen；from_entry 轻量容错解析。
    """

    quality: Optional[str]
    times: Optional[int]
    final_only: Optional[bool]
    index: int = field(default=0)  # 【补白】行序号（非 schema 字段，仅诊断定位用）

    @classmethod
    def from_entry(cls, entry: Mapping[str, object], index: int = 0) -> "LimitByRarity":
        q = entry.get("quality")
        t = entry.get("times")
        fo = entry.get("final_only")
        return cls(
            quality=q if isinstance(q, str) else None,
            times=t if isinstance(t, int) and not isinstance(t, bool) else None,
            final_only=fo if isinstance(fo, bool) else None,
            index=index,
        )


@dataclass(frozen=True)
class ForgeSettings:
    """forge.json settings 段（契约 §三 S-01~05 + 2c2d 补白键）。

    全局段（无 id），独立 frozen；from_entry 轻量容错解析；缺省默认值兜底。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: object) -> "ForgeSettings":
        return cls(raw=entry if isinstance(entry, Mapping) else {})

    def _val(self, key: str) -> object:
        return self.raw.get(key)

    @property
    def forge_fee(self) -> object:
        return self._val("forge_fee")

    @property
    def synth_ratio_3to1(self) -> bool:
        v = self._val("synth_ratio_3to1")
        return v if isinstance(v, bool) else True  # 默认 true（S-02）

    @property
    def straight_forge(self) -> bool:
        v = self._val("straight_forge")
        return v if isinstance(v, bool) else True  # 默认 true（S-03）

    @property
    def decompose_rate(self) -> Mapping[str, object]:
        v = self._val("decompose_rate")
        return v if isinstance(v, Mapping) else {}

    @property
    def exp_per_forge(self) -> object:
        return self._val("exp_per_forge")

    @property
    def sets_enabled(self) -> bool:
        v = self._val("sets_enabled")
        return v if isinstance(v, bool) else True  # 2c2d 补白键默认 true

    @property
    def augments_enabled(self) -> bool:
        v = self._val("augments_enabled")
        return v if isinstance(v, bool) else True  # 2c2d 补白键默认 true

    @property
    def set_piece_counts(self) -> Tuple[int, ...]:
        """套装技能档位集合（P1-1 裁决 2026-08-30 配置化）：settings.forge.set_piece_counts
        正整数列表，去重升序；缺省/非合法 → 默认 (2, 3, 5)。"""
        v = self._val("set_piece_counts")
        if isinstance(v, (list, tuple)):
            cleaned = tuple(sorted({x for x in v
                                    if isinstance(x, int) and not isinstance(x, bool) and x >= 1}))
            if cleaned:
                return cleaned
        return (2, 3, 5)

    @property
    def set_tier_exact(self) -> bool:
        """套装激活语义（P1-1 裁决配置化）：true=达到档位件数才激活该档效果；
        false=未达到档位也能激活低档效果（回落语义）。缺省 true。"""
        v = self._val("set_tier_exact")
        return v if isinstance(v, bool) else True


# =====================================================================================
# 收集器鸭子类型（三形态：report.error/warning 方法 → report._err/_warn 方法 →
# {"errors":[],"warnings":[]} dict；照 shop_models/alchemy_models._emit 模式）
# =====================================================================================
def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    """收集器鸭子类型适配，兼容三形态（任务强制）：

    1) report.error(...)/report.warning(...) 方法（如 validator 校验器注入形态）；
    2) report._err(...)/report._warn(...) 方法（validator._Checker）；
    3) report 为 dict {"errors":[], "warnings":[]}（JSON 收集器兜底）。
    """
    fn = getattr(report, method, None)
    if not callable(fn):
        _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)
        return
    # dict 形态兜底：{"errors": [], "warnings": []}
    if isinstance(report, dict):
        key = {"error": "errors", "warning": "warnings", "note": "notes"}.get(method)
        lst = report.get(key)
        if isinstance(lst, list):
            lst.append({"method": method, "args": args, "kwargs": dict(kwargs)})


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", "forge", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", "forge", field, kind, **detail)


# =====================================================================================
# 引用靶收集（items/enemies 模块形态；缺失 → None：调用方跳过引用红拦，降级放行）
# =====================================================================================
def _items_map(modules: Mapping[str, object]) -> Optional[Dict[str, Mapping[str, object]]]:
    """items 模块 → {id: 条目 dict}；非 list/空 → None（放行）。"""
    data = modules.get("items")
    if not isinstance(data, list):
        return None
    out: Dict[str, Mapping[str, object]] = {}
    for e in data:
        if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
            out[e["id"]] = e
    return out if out else None


def _enemy_element_weaknesses(modules: Mapping[str, object]) -> Optional[Set[str]]:
    """enemies 模块 → 弱点元素键集（enemies[].weakness.elements 字典键）。

    非 list → None（W2 放行：无怪物表可判定时跳过）；list（含空弱点集）→
    返回元素键集合（可为空 set——此时 W2 判定走 `elem not in empty` 触发黄，
    TC-24b：怪物表存在但无弱该属性怪 → 黄）。"""
    data = modules.get("enemies")
    if not isinstance(data, list):
        return None
    out: Set[str] = set()
    for e in data:
        if not isinstance(e, Mapping):
            continue
        w = e.get("weakness")
        if isinstance(w, Mapping):
            elems = w.get("elements")
            if isinstance(elems, Mapping):
                for k in elems.keys():
                    if isinstance(k, str) and k:
                        out.add(k)
    return out


# =====================================================================================
# 双源仲裁（AR-1~5：items 基础 + 节点改造合并；实例快照入档归批1路1A，本批只做合并函数）
# =====================================================================================
def merge_node_item(items_def: Mapping[str, object], node: object) -> Dict[str, object]:
    """双源仲裁合并：items 基础 + 节点改造 → 装备实例 dict（AR-1~5）。

    AR-1 覆盖：节点声明的键（stats.*/slots/rarity/monster_source/final/augmentable/
      king_only/final_tier/cost/level）以节点为准，覆盖 items 同键基础值。
    AR-2 追加：节点未声明键继承 items 基础值（stats 内键级合并：节点 stats 覆盖
      items stats 同键，items 其它 stats 键保留）。
    AR-3 品质：节点 rarity 声明 → 覆盖 items.quality；未声明 → 继承 items.quality。
    AR-4 配置模式：只建议不限制（本函数天然支持瘦/富双模式）。
    AR-5 实例快照：本函数即「items 基础 + 节点改造」合并核心，快照入档归批1路1A。

    入参：items_def = items.json 条目 dict（Mapping）；node = ForgeNode 或节点
      raw dict（Mapping）。返回合并后 dict（深拷贝，不改写入参）。
    """
    base: Dict[str, object] = dict(items_def) if isinstance(items_def, Mapping) else {}
    raw: Mapping[str, object] = node.raw if isinstance(node, BaseDef) else (
        node if isinstance(node, Mapping) else {}
    )
    out: Dict[str, object] = dict(base)

    # ---- stats 键级合并（AR-1 覆盖 / AR-2 追加）----
    node_stats = raw.get("stats")
    if isinstance(node_stats, Mapping):
        merged_stats: Dict[str, object] = {}
        base_stats = base.get("stats")
        if isinstance(base_stats, Mapping):
            merged_stats.update(dict(base_stats))
        for k, v in node_stats.items():
            merged_stats[str(k)] = v
        out["stats"] = merged_stats

    # ---- 顶层改造键覆盖（AR-1：节点声明键为准）----
    for key in ("slots", "monster_source", "final", "augmentable",
                "king_only", "final_tier", "cost", "level", "name", "type"):
        if key in raw:
            out[key] = raw[key]

    # ---- 品质仲裁（AR-3：节点 rarity 覆盖 / 未声明继承 items.quality）----
    node_rarity = raw.get("rarity")
    if node_rarity is not None:
        out["rarity"] = node_rarity
    elif "quality" in base:
        out["rarity"] = base["quality"]

    # ---- 产物 item 引用解析（N-03 item/output_item 别名）----
    item_ref = raw.get("item") or raw.get("output_item")
    if isinstance(item_ref, str) and item_ref:
        out["item_id"] = item_ref

    # ---- ID/名称冗余（铁律9）：节点 id 作为产物来源标识（快照追溯用）----
    node_id = raw.get("id")
    if isinstance(node_id, str) and node_id:
        out["node_id"] = node_id
    if not out.get("id") and isinstance(base.get("id"), str):
        out["id"] = base["id"]

    return out


# =====================================================================================
# forge_module_meta（供主 agent 收口接线 field_meta；对齐 alchemy_settings
# slots_module_meta() 工厂模式；forge.json 顶层是 obj 非 list → entry_type="object"）
# =====================================================================================
# 顶层四段字段表（共享契约 §〇 / §八：forge.json 顶层 obj）
FORGE_TOP_FIELD_DEFS: Dict[str, FieldMeta] = {
    "schema_version": FieldMeta(type="str"),
    "trees": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "id": FieldMeta(type="str"),
        "name": FieldMeta(type="str"),
        "type": FieldMeta(type="str"),
        "roots": FieldMeta(type="list", element=FieldMeta(type="str")),
        "nodes": FieldMeta(type="list", element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str"),
            "name": FieldMeta(type="str"),
            "item": FieldMeta(type="str"),
            "output_item": FieldMeta(type="str"),
            "type": FieldMeta(type="str"),
            "level": FieldMeta(type="int", range_min=1),
            "parent": FieldMeta(type="str"),
            "branch": FieldMeta(type="list", element=FieldMeta(type="str")),
            "stats": FieldMeta(type="obj"),
            "slots": FieldMeta(type="list", element=FieldMeta(type="obj", children={
                "level": FieldMeta(type="int", range_min=1, range_max=3),
            })),
            "materials": FieldMeta(type="list", element=FieldMeta(type="obj", children={
                "item": FieldMeta(type="str"),
                "count": FieldMeta(type="int", range_min=1),
                "tier": FieldMeta(type="str"),
                "source_override": FieldMeta(type="str"),
            })),
            "cost": FieldMeta(type="obj"),
            "rarity": FieldMeta(type="str"),
            "monster_source": FieldMeta(type="str"),
            "final": FieldMeta(type="bool"),
            "augmentable": FieldMeta(type="bool"),
            "king_only": FieldMeta(type="bool"),
            "final_tier": FieldMeta(type="bool"),
        })),
    })),
    "sets": FieldMeta(type="list", element=FieldMeta(type="obj", children={
        "id": FieldMeta(type="str"),
        "name": FieldMeta(type="str"),
        "variant": FieldMeta(type="str"),
        "pieces": FieldMeta(type="list", element=FieldMeta(type="str")),
        "skills": FieldMeta(type="list", element=FieldMeta(type="obj", children={
            "piece_count": FieldMeta(type="int"),
            "skill": FieldMeta(type="str"),
            "level": FieldMeta(type="int"),
            "effect_ref": FieldMeta(type="str"),
        })),
        "desc": FieldMeta(type="str"),
        "enabled": FieldMeta(type="bool"),
        "codex_group": FieldMeta(type="str"),
    })),
    "augments": FieldMeta(type="obj", children={
        "augments": FieldMeta(type="list", element=FieldMeta(type="obj", children={
            "id": FieldMeta(type="str"),
            "name": FieldMeta(type="str"),
            "kind": FieldMeta(type="str"),
            "effect": FieldMeta(type="str"),
            "stat_key": FieldMeta(type="str"),
            "value": FieldMeta(type="obj"),
            "cost": FieldMeta(type="list", element=FieldMeta(type="obj", children={
                "item": FieldMeta(type="str"),
                "count": FieldMeta(type="int", range_min=1),
            })),
            "repeatable": FieldMeta(type="bool"),
            "max_repeat": FieldMeta(type="int"),
            "slot_level": FieldMeta(type="int"),
            "disabled": FieldMeta(type="bool"),
            "trace": FieldMeta(type="bool"),
        })),
        "limit_by_rarity": FieldMeta(type="list", element=FieldMeta(type="obj", children={
            "quality": FieldMeta(type="str"),
            "times": FieldMeta(type="int", range_min=1),
            "final_only": FieldMeta(type="bool"),
        })),
    }),
    "settings": FieldMeta(type="obj", children={
        "forge_fee": FieldMeta(type="str"),
        "synth_ratio_3to1": FieldMeta(type="bool"),
        "straight_forge": FieldMeta(type="bool"),
        "decompose_rate": FieldMeta(type="obj"),
        "exp_per_forge": FieldMeta(type="str"),
        "sets_enabled": FieldMeta(type="bool"),
        "augments_enabled": FieldMeta(type="bool"),
    }),
}


def forge_module_meta() -> ModuleMeta:
    """forge 模块 ModuleMeta（entry_type=object——forge.json 顶层是 obj 非 list）。

    对齐 dungeon/npc/shop/quest/checkin 专项全权口径：fields={} 空表防泛型误拦
    （根节点 parent=null / items 可空字段会被泛型 R-1 当 type 红拦）——深结构校验
    由 validate_forge 专项全权（V1-V15/W + 2c2d V1-V8/W1-W4）。
    FORGE_TOP_FIELD_DEFS（详细字段表）保留导出，供 M12 编辑器元数据驱动复用。
    """
    return ModuleMeta(entry_type="object", fields={}, kind="forge")


# =====================================================================================
# validate_forge：forge 模块专项校验（共享契约 §六 V1-V15 硬 + V16/W1-W6 黄 +
# 2c2d V1-V8 硬/W1-W4 黄，针对 sets/augments）
# =====================================================================================
# 级别：红拦=error（加载失败）/ 黄=warning（不阻断）。
# 规则速览：
#   树级：V1 type/id 唯一、trees 非空；V2 节点 id 全局唯一 + type 与树一致；
#     V3 parent/roots 引用；V4 无环+可达根；V5 branch 可达；V6 叶子=final。
#   节点：V7 item 引用（别名二选一）；V8 items 类型匹配；V9 改造键空间；
#     V10 素材引用材料类；V11 素材数量/档位；V12 level；V13 rarity；V14 slots；
#     V15 级联复查（红名引用）。
#   黄：V16 augmentable 非最终武器；W1 同键冲突覆盖；W2 元素无弱点怪；
#     W3 settings 关但数据存在；W4 素材死锁；W5 超规模；W6 根 level≠1。
#   2c2d：V1 套装族唯一+变体；V2 pieces 引用+防具五部位+不重复+≤5；
#     V3 技能档位 2/3/5 连续+level∈{1,2,3}；V4 客制项枚举结构；V5 客制消耗引用；
#     V6 次数表；V7 节点扩展（king_only/final_tier/augmentable 黄）；
#     V8 全段 disabled 黄；W1 α/β 孔位；W2 trace 追溯；W3 settings 关；
#     W4 技能 level 超封顶。


def _check_tree_shape(
    report: object,
    forge: Mapping[str, object],
    trees: list,
) -> Tuple[Dict[str, str], Dict[str, Mapping[str, object]]]:
    """V1：树级唯一——trees 非空；树 id 唯一；树 type 全文件唯一（每部位一棵）。

    返回 (node_id→tree_type, tree_id→tree raw)；供后续 V2~V6 复用。
    """
    if not trees:
        _err(report, "forge.trees", "V1", rule="trees_empty",
             msg="trees 必填 ≥1（每部位一棵，全空防空池——共享契约 §十 坑位5）")
        return {}, {}
    seen_type: Set[str] = set()
    seen_id: Set[str] = set()
    node_type_by_tree: Dict[str, str] = {}
    for i, tree in enumerate(trees):
        if not isinstance(tree, Mapping):
            _err(report, f"forge.trees.{i}", "V1", rule="tree_not_object",
                 got=type(tree).__name__)
            continue
        tid = tree.get("id")
        ttype = tree.get("type")
        if not isinstance(tid, str) or not tid:
            _err(report, f"forge.trees.{i}.id", "V1", rule="tree_id_required",
                 msg="树 id 必填非空（全文件唯一）")
        elif tid in seen_id:
            _err(report, f"forge.trees.{i}.id", "V1", rule="tree_id_duplicate", id=tid,
                 msg="树 id %r 重复（全文件唯一）" % tid)
        else:
            seen_id.add(tid)
        if not isinstance(ttype, str) or ttype not in FORGE_TREE_TYPES:
            _err(report, f"forge.trees.{i}.type", "V1", rule="tree_type_invalid",
                 value=ttype, allowed=list(FORGE_TREE_TYPES),
                 msg="树 type %r 不认识（六部位之一，全文件唯一）" % (ttype,))
        elif ttype in seen_type:
            _err(report, f"forge.trees.{i}.type", "V1", rule="tree_type_duplicate",
                 type=ttype, msg="每部位一棵树：type %r 全文件唯一（重复=V1）" % ttype)
        else:
            seen_type.add(ttype)
        node_type_by_tree[tid if isinstance(tid, str) else f"#{i}"] = (
            ttype if isinstance(ttype, str) else ""
        )
    tree_raw: Dict[str, Mapping[str, object]] = {
        cast(str, t["id"]): t
        for t in trees if isinstance(t, Mapping) and isinstance(t.get("id"), str)
    }
    return node_type_by_tree, tree_raw


def _normalize_rarity(value: object) -> Optional[str]:
    """V13：品质归一——四档枚举原样；历史整数 1-4 映射；其它 → None（非法）。"""
    if isinstance(value, str) and value in RARITY_TIERS:
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in RARITY_INT_MAP:
        return RARITY_INT_MAP[value]
    return None


def _check_node(
    report: object,
    node: Mapping[str, object],
    tree_idx: int,
    tree_type: str,
    node_idx: int,
    all_node_ids: Set[str],
    same_tree_ids: Set[str],
    items: Optional[Dict[str, Mapping[str, object]]],
    enemy_weak: Optional[Set[str]],
    settings: ForgeSettings,
    seen_node_ids: Set[str],
    parent_refs: Dict[str, List[str]],
    branch_refs: Dict[str, List[str]],
    node_type_map: Dict[str, str],
    node_level_map: Dict[str, Optional[int]],
) -> None:
    """单节点校验（V2/V3/V5/V6/V7/V8/V9/V10/V11/V12/V13/V14/V16/W1/W2/W6 + 2c2d V7）。"""
    base = f"forge.trees.{tree_idx}.nodes.{node_idx}"
    nid = node.get("id")
    ntype = node.get("type")
    is_valid_id = isinstance(nid, str) and bool(nid)

    # ---- V2：节点 id 全文件唯一 + type 与所属树一致 ----
    if not is_valid_id:
        _err(report, f"{base}.id", "V2", rule="node_id_required",
             msg="节点 id 必填非空（全文件唯一）")
    else:
        nid_s = cast(str, nid)
        if nid_s in seen_node_ids:
            _err(report, f"{base}.id", "V2", rule="node_id_duplicate", id=nid_s,
                 msg="节点 id %r 全文件重复（V2）" % nid_s)
        seen_node_ids.add(nid_s)
        if isinstance(ntype, str) and ntype != tree_type and tree_type:
            _err(report, f"{base}.type", "V2", rule="node_type_tree_mismatch",
                 node_type=ntype, tree_type=tree_type,
                 msg="节点 type %r 与所属树 type %r 不一致（V2）" % (ntype, tree_type))
    if is_valid_id and isinstance(ntype, str):
        node_type_map[cast(str, nid)] = ntype

    # ---- V3：parent 引用（非空须已定义且同树）+ V4 环检测准备 ----
    parent = node.get("parent")
    if parent is not None:
        if not isinstance(parent, str) or not parent:
            _err(report, f"{base}.parent", "V3", rule="parent_invalid", value=parent,
                 msg="parent 须为节点 id 或 null")
        elif not is_valid_id:
            pass  # 节点 id 非法无法判定同树，交 V2
        else:
            if parent not in all_node_ids:
                _err(report, f"{base}.parent", "V3", rule="parent_missing", parent=parent,
                     msg="parent %r 本文件未定义（V3）" % parent)
            elif parent not in same_tree_ids:
                _err(report, f"{base}.parent", "V3", rule="parent_cross_tree",
                     parent=parent, tree_type=tree_type,
                     msg="parent %r 不在本树（V3：父节点须同树）" % parent)
            else:
                parent_refs.setdefault(str(parent), []).append(
                    cast(str, nid) if is_valid_id else base)

    # ---- V3：roots 引用存在（树级统一查；此处在节点级收集 parent=null 根候选）----
    # roots 校验放在树级（_check_tree_nodes）收口，此处只收集 parent==null 节点。

    # ---- V5：branch 可达（每 id 已定义；重复去重告警）----
    branch = node.get("branch")
    if branch is not None:
        if not isinstance(branch, list):
            _err(report, f"{base}.branch", "V5", rule="branch_not_list",
                 got=type(branch).__name__)
        else:
            seen_b: Set[str] = set()
            for b in branch:
                if not isinstance(b, str) or not b:
                    _err(report, f"{base}.branch", "V5", rule="branch_entry_invalid",
                         value=b)
                    continue
                if b not in all_node_ids:
                    _err(report, f"{base}.branch", "V5", rule="branch_missing", branch=b,
                         msg="branch %r 本文件未定义（V5）" % b)
                if b in seen_b:
                    _warn(report, f"{base}.branch", "V5", rule="branch_duplicate",
                          branch=b, msg="branch 重复 id %r（去重告警，V5 黄）" % b)
                else:
                    seen_b.add(b)
                    branch_refs.setdefault(str(b), []).append(
                        cast(str, nid) if is_valid_id else base)

    # ---- V7：node.item 引用存在（items 装备条目；别名 item/output_item 二选一）----
    item = node.get("item")
    output_item = node.get("output_item")
    if item is not None and output_item is not None:
        _err(report, f"{base}.item", "V7", rule="item_alias_duplicate",
             item=item, output_item=output_item,
             msg="item 与 output_item 别名二选一，不双写（TC-08 硬错）")
    item_ref = item if isinstance(item, str) and item else (
        output_item if isinstance(output_item, str) and output_item else None
    )
    if item_ref is None:
        _err(report, f"{base}.item", "V7", rule="item_required",
             msg="node.item（或别名 output_item）必填，引用 items.json 装备条目（V7）")
    elif items is not None and item_ref not in items:
        _err(report, f"{base}.item", "V7", rule="item_missing", item=item_ref,
             msg="node.item %r 在 items.json 中不存在（V7）" % item_ref)
    # 节点 id 记入 item 引用靶（V15 红名判定：item 缺失的节点被引用）
    if is_valid_id:
        parent_refs.setdefault("__node_item__", [])

    # ---- V8：items 条目类型与 node.type 匹配 ----
    if item_ref is not None and items is not None and item_ref in items:
        entry = items[item_ref]
        entry_type = entry.get("type")
        if isinstance(ntype, str) and isinstance(entry_type, str) and ntype != entry_type:
            _err(report, f"{base}.type", "V8", rule="item_type_mismatch",
                 item=item_ref, node_type=ntype, item_type=entry_type,
                 msg="node.item %r 类型 %r 与 node.type %r 不匹配（V8）"
                     % (item_ref, entry_type, ntype))

    # ---- V9：改造键空间（stats.* ∈ items 条目键 ∪ 标准属性键 ∪ 元素键）----
    stats = node.get("stats")
    if stats is not None:
        if not isinstance(stats, Mapping):
            _err(report, f"{base}.stats", "V9", rule="stats_not_object",
                 got=type(stats).__name__)
        else:
            item_keys: Set[str] = set()
            if item_ref is not None and items is not None and item_ref in items:
                ik = items[item_ref].get("stats")
                if isinstance(ik, Mapping):
                    item_keys.update(str(k) for k in ik.keys())
                else:
                    item_keys.update(str(k) for k in items[item_ref].keys())
            for sk, sv in stats.items():
                skey = str(sk)
                if skey in FORGE_STAT_KEY_SPACE or skey in FORGE_ELEMENTS or skey in item_keys:
                    # W1：改造键与 items 同键冲突 → 覆盖生效黄提示（不阻断）
                    if skey in item_keys:
                        _warn(report, f"{base}.stats.{skey}", "W1",
                              rule="stat_override_items", key=skey, item=item_ref,
                              msg="改造键 %s 与 items 同键冲突，节点值覆盖生效（W1）"
                                  % skey)
                else:
                    _err(report, f"{base}.stats.{skey}", "V9", rule="stat_key_drift",
                         key=skey,
                         msg="改造键 %s 不在 items 元数据键空间内（防新键漂移，V9）" % skey)
            # 元素键合法检查（N-08 元素走 formula 注册表镜像常量）
            elem = stats.get("element")
            if elem is not None:
                if not isinstance(elem, str) or elem not in FORGE_ELEMENTS:
                    _err(report, f"{base}.stats.element", "V9", rule="element_invalid",
                         value=elem, allowed=list(FORGE_ELEMENTS),
                         msg="元素 %r 不在注册表（地水火风雷晶月无，V9）" % (elem,))
                else:
                    # W2：元素武器但怪物表无弱该属性怪 → 黄（enemies 存在时判定）
                    if enemy_weak is not None and elem not in enemy_weak:
                        _warn(report, f"{base}.stats.element", "W2",
                              rule="element_no_weak_enemy", element=elem,
                              msg="元素武器 %s 无弱该属性怪，元素武器无发挥空间（W2）"
                                  % elem)

    # ---- V10/V11：素材引用（items 材料类）+ 数量/档位 + ≥1 行 ----
    materials = node.get("materials")
    if materials is None or (isinstance(materials, list) and not materials):
        _err(report, f"{base}.materials", "V11", rule="materials_required",
             msg="materials 每节点 ≥1 行（V11）")
    elif not isinstance(materials, list):
        _err(report, f"{base}.materials", "V11", rule="materials_not_list",
             got=type(materials).__name__)
    else:
        for mi, m in enumerate(materials):
            mbase = f"{base}.materials.{mi}"
            if not isinstance(m, Mapping):
                _err(report, mbase, "V11", rule="material_row_not_object",
                     got=type(m).__name__)
                continue
            m_item = m.get("item")
            if not isinstance(m_item, str) or not m_item:
                _err(report, f"{mbase}.item", "V10", rule="material_item_required",
                     msg="素材 item 必填（items.json 材料类引用，V10）")
            elif items is not None:
                if m_item not in items:
                    _err(report, f"{mbase}.item", "V10", rule="material_item_missing",
                         item=m_item,
                         msg="素材 %r 在 items.json 中不存在（V10）" % m_item)
                else:
                    entry = items[m_item]
                    is_mat = entry.get("type") == "material" or "material_tier" in entry
                    if not is_mat:
                        _err(report, f"{mbase}.item", "V10",
                             rule="material_not_material_class", item=m_item,
                             msg="素材 %r 非材料类条目（V10：须 items 材料类）" % m_item)
            count = m.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                _err(report, f"{mbase}.count", "V11", rule="material_count_invalid",
                     count=count, msg="素材 count 需 ≥1 正整数（V11）")
            tier = m.get("tier")
            if tier is not None and (not isinstance(tier, str) or tier not in MATERIAL_TIERS):
                _err(report, f"{mbase}.tier", "V11", rule="material_tier_invalid",
                     tier=tier, allowed=list(MATERIAL_TIERS),
                     msg="素材 tier %r 不认识（normal/rare 两档，V11）" % (tier,))

    # ---- V12：等级合法（≥1 整数）----
    level = node.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or level < 1:
        _err(report, f"{base}.level", "V12", rule="node_level_invalid", level=level,
             msg="节点 level 需 ≥1 整数（职业门槛，V12）")
    if is_valid_id:
        node_level_map[cast(str, nid)] = (
            level if isinstance(level, int) and not isinstance(level, bool) else None)

    # ---- V13：品质合法（四档；历史整数 1-4 兼容）----
    rarity = node.get("rarity")
    if rarity is not None and _normalize_rarity(rarity) is None:
        _err(report, f"{base}.rarity", "V13", rule="rarity_invalid", rarity=rarity,
             allowed=list(RARITY_TIERS),
             msg="rarity %r 不认识（四档 normal/fine/epic/legendary；历史整数 1-4 兼容，V13）"
                 % (rarity,))

    # ---- V14：孔位合法（slots[].level ∈ {1,2,3}）----
    slots = node.get("slots")
    if slots is not None:
        if not isinstance(slots, list):
            _err(report, f"{base}.slots", "V14", rule="slots_not_list",
                 got=type(slots).__name__)
        else:
            for si, s in enumerate(slots):
                if not isinstance(s, Mapping):
                    _err(report, f"{base}.slots.{si}", "V14", rule="slot_row_not_object",
                         got=type(s).__name__)
                    continue
                sl = s.get("level")
                if not isinstance(sl, int) or isinstance(sl, bool) or sl not in SLOT_LEVELS:
                    _err(report, f"{base}.slots.{si}.level", "V14", rule="slot_level_invalid",
                         level=sl, allowed=list(SLOT_LEVELS),
                         msg="孔位 level %r 不认识（{1,2,3}，框架 3.5，V14）" % (sl,))

    # ---- V16 黄：augmentable=true 且 final=false 或非武器 ----
    augmentable = node.get("augmentable")
    if augmentable is True:
        final = node.get("final")
        if final is not True or ntype != "weapon":
            _warn(report, f"{base}.augmentable", "V16",
                  rule="augmentable_not_final_weapon", node_type=ntype, final=final,
                  msg="仅最终强化武器可客制（V16 黄）")

    # ---- 2c2d V7 黄：king_only/final_tier 节点扩展合法性 ----
    king_only = node.get("king_only")
    if king_only is True:
        if not isinstance(level, int) or isinstance(level, bool) or level < KING_ONLY_LEVEL_MIN:
            _warn(report, f"{base}.king_only", "2c2d-V7", rule="king_only_level",
                  level=level, msg="king_only 节点建议 level ≥ %d（2c2d V7 黄）"
                                   % KING_ONLY_LEVEL_MIN)
    final_tier = node.get("final_tier")
    if final_tier is True:
        final = node.get("final")
        r_norm = _normalize_rarity(node.get("rarity"))
        if final is not True or r_norm != "legendary":
            _warn(report, f"{base}.final_tier", "2c2d-V7", rule="final_tier_invalid",
                  final=final, rarity=node.get("rarity"),
                  msg="final_tier 仅 final=true 且 rarity=legendary 可 true（2c2d V7 黄）")
    if king_only is not None and not isinstance(king_only, bool):
        _err(report, f"{base}.king_only", "2c2d-V7", rule="king_only_not_bool",
             value=king_only)
    if final_tier is not None and not isinstance(final_tier, bool):
        _err(report, f"{base}.final_tier", "2c2d-V7", rule="final_tier_not_bool",
             value=final_tier)

    # ---- W6 黄：根节点 level≠1（根判定在树级收口，此处不重复）----
    # 根节点 = parent==null 且 ∈ roots；树级统一判 W6。


def _check_cycle_and_reach(
    report: object,
    tree_idx: int,
    tree: Mapping[str, object],
    tree_id: str,
    nodes: List[Mapping[str, object]],
    node_ids: List[str],
    node_type_map: Dict[str, str],
) -> None:
    """V4：树无环（沿 parent 正向遍历无自环）+ 每节点可达某一根。"""
    by_id: Dict[str, Mapping[str, object]] = {}
    for n in nodes:
        nid = n.get("id")
        if isinstance(nid, str) and nid:
            by_id[nid] = n
    roots = tree.get("roots")
    if not isinstance(roots, list) or not roots:
        _err(report, f"forge.trees.{tree_idx}.roots", "V3", rule="roots_required",
             msg="roots 必填 ≥1（根节点 id 列表，V3）")
        roots = []
    root_set = {r for r in roots if isinstance(r, str) and r}
    # roots 每 id 存在（V3）
    for r in roots:
        if isinstance(r, str) and r and r not in by_id:
            _err(report, f"forge.trees.{tree_idx}.roots", "V3", rule="root_missing",
                 root=r, msg="root %r 本树未定义（V3）" % r)

    # V4：DFS 沿 parent 链检测自环 + 可达根
    for nid, n in by_id.items():
        visited: Set[str] = set()
        cur: Optional[str] = nid
        path: List[str] = []
        while cur is not None:
            if cur in visited:
                path.append(cur)
                _err(report, f"forge.trees.{tree_idx}.nodes.{cur}", "V4",
                     rule="parent_cycle", cycle=path,
                     msg="parent 链成环 %s（V4）" % "→".join(path))
                break
            visited.add(cur)
            path.append(cur)
            p = by_id[cur].get("parent")
            if p is None:
                # 到达根（parent=null）：须 ∈ roots（可达某一根）
                if cur not in root_set:
                    _err(report, f"forge.trees.{tree_idx}.nodes.{cur}", "V4",
                         rule="root_not_declared", node=cur,
                         msg="节点 %r 沿 parent 到根 %r 但未在 roots 声明（V4 可达根）"
                             % (nid, cur))
                break
            if not isinstance(p, str) or p not in by_id:
                break  # V3 已报悬空
            if p == cur:
                path.append(cur)
                _err(report, f"forge.trees.{tree_idx}.nodes.{cur}", "V4",
                     rule="parent_self_cycle", cycle=path,
                     msg="节点 parent 指向自身成环（V4）")
                break
            cur = p


def _check_tree_nodes(
    report: object,
    forge: Mapping[str, object],
    trees: list,
    items: Optional[Dict[str, Mapping[str, object]]],
    enemy_weak: Optional[Set[str]],
    settings: ForgeSettings,
    all_node_ids: Set[str],
    seen_node_ids: Set[str],
    node_type_map: Dict[str, str],
    node_level_map: Dict[str, Optional[int]],
    parent_refs: Dict[str, List[str]],
    branch_refs: Dict[str, List[str]],
) -> None:
    """遍历各树节点：V2~V14/V16/W1/W2/W6 + 树级 V3 roots/V4 环/V6 叶子 + W5/W6。"""
    tree_node_counts: Dict[str, int] = {"weapon": 0, "armor": 0}
    for i, tree in enumerate(trees):
        if not isinstance(tree, Mapping):
            continue
        tree_id = cast(str, tree.get("id") if isinstance(tree.get("id"), str) else f"#{i}")
        tree_type = cast(str, tree.get("type") if isinstance(tree.get("type"), str) else "")
        nodes_raw = tree.get("nodes")
        if not isinstance(nodes_raw, list):
            _err(report, f"forge.trees.{i}.nodes", "V2", rule="nodes_not_list",
                 got=type(nodes_raw).__name__, tree_id=tree_id)
            continue
        nodes: List[Mapping[str, object]] = [
            e for e in nodes_raw if isinstance(e, Mapping)
        ]
        node_ids = [
            str(e["id"]) for e in nodes if isinstance(e.get("id"), str) and e["id"]
        ]
        same_tree_ids = set(node_ids)
        all_node_ids.update(same_tree_ids)
        # 节点级校验
        for ni, n in enumerate(nodes):
            _check_node(
                report, n, i, tree_type, ni, all_node_ids, same_tree_ids,
                items, enemy_weak, settings, seen_node_ids,
                parent_refs, branch_refs, node_type_map, node_level_map,
            )
        # 树级 V4 环 + V3 roots + W6 根 level
        _check_cycle_and_reach(report, i, tree, tree_id, nodes, node_ids, node_type_map)
        # W6：根节点 level≠1 → 黄（roots 每 id 的节点）
        roots = tree.get("roots")
        if isinstance(roots, list):
            for r in roots:
                if isinstance(r, str) and r in node_level_map and \
                        node_level_map[r] not in (None, 1):
                    _warn(report, f"forge.trees.{i}.roots", "W6", rule="root_level_not_1",
                          root=r, level=node_level_map[r],
                          msg="根节点 %r level≠1，建议根=1（W6 黄）" % r)
        # 规模统计（W5）
        if tree_type == "weapon":
            tree_node_counts["weapon"] += len(node_ids)
        elif tree_type in ARMOR_TYPES:
            tree_node_counts["armor"] += len(node_ids)

    # ---- V6：叶子=最终强化（全文件父引用判定）----
    for i, tree in enumerate(trees):
        if not isinstance(tree, Mapping):
            continue
        tree_id = cast(str, tree.get("id") if isinstance(tree.get("id"), str) else f"#{i}")
        nodes_raw = tree.get("nodes")
        if not isinstance(nodes_raw, list):
            continue
        for ni, n in enumerate(nodes_raw):
            if not isinstance(n, Mapping):
                continue
            nid = n.get("id")
            if not isinstance(nid, str) or not nid:
                continue
            is_leaf = nid not in parent_refs  # 无节点 parent 指向它
            final = n.get("final")
            if final is not True and is_leaf:
                _err(report, f"forge.trees.{i}.nodes.{ni}.final", "V6",
                     rule="leaf_not_final", node=nid,
                     msg="线终点（叶子）%r 必须 final=true（V6）" % nid)
            if final is True and not is_leaf:
                _err(report, f"forge.trees.{i}.nodes.{ni}.final", "V6",
                     rule="final_has_child", node=nid,
                     msg="final=true 节点 %r 不得有子节点（V6）" % nid)
            if final is not None and not isinstance(final, bool):
                _err(report, f"forge.trees.{i}.nodes.{ni}.final", "V6",
                     rule="final_not_bool", value=final)

    # ---- V15：级联删除复查（红名节点 = item 引用缺失的节点；父链完整 + branch 已清）----
    red_nodes: Set[str] = set()
    for i, tree in enumerate(trees):
        if not isinstance(tree, Mapping):
            continue
        nodes_raw = tree.get("nodes")
        if not isinstance(nodes_raw, list):
            continue
        for ni, n in enumerate(nodes_raw):
            if not isinstance(n, Mapping):
                continue
            nid = n.get("id")
            if not isinstance(nid, str) or not nid:
                continue
            item_ref = n.get("item") or n.get("output_item")
            if not isinstance(item_ref, str) or not item_ref:
                red_nodes.add(nid)
            elif items is not None and item_ref not in items:
                red_nodes.add(nid)
    if red_nodes:
        for i, tree in enumerate(trees):
            if not isinstance(tree, Mapping):
                continue
            nodes_raw = tree.get("nodes")
            if not isinstance(nodes_raw, list):
                continue
            for ni, n in enumerate(nodes_raw):
                if not isinstance(n, Mapping):
                    continue
                nid = n.get("id")
                if not isinstance(nid, str) or not nid:
                    continue
                if nid not in red_nodes:
                    continue
                # 红名节点不得被引用为 parent（残留悬空）
                if nid in parent_refs:
                    _err(report, f"forge.trees.{i}.nodes.{ni}.item", "V15",
                         rule="red_name_referenced", node=nid,
                         refs=parent_refs.get(nid, []),
                         msg="红名节点 %r 仍被 parent 引用（级联删除未清，V15）" % nid)
                # 红名节点 branch 已清
                br = n.get("branch")
                if isinstance(br, list) and br:
                    _err(report, f"forge.trees.{i}.nodes.{ni}.branch", "V15",
                         rule="red_name_branch_not_cleared", node=nid, branch=br,
                         msg="红名节点 %r branch 未清（级联删除复查，V15）" % nid)

    # ---- W5：规模黄提示 ----
    if tree_node_counts["weapon"] > WEAPON_NODE_LIMIT:
        _warn(report, "forge.trees", "W5", rule="weapon_scale",
              count=tree_node_counts["weapon"], limit=WEAPON_NODE_LIMIT,
              msg="武器树节点总量 %d 超建议 %d（配置负担预警，W5 黄）"
                  % (tree_node_counts["weapon"], WEAPON_NODE_LIMIT))
    if tree_node_counts["armor"] > ARMOR_NODE_LIMIT:
        _warn(report, "forge.trees", "W5", rule="armor_scale",
              count=tree_node_counts["armor"], limit=ARMOR_NODE_LIMIT,
              msg="防具树节点总量 %d 超建议 %d（配置负担预警，W5 黄）"
                  % (tree_node_counts["armor"], ARMOR_NODE_LIMIT))


def _check_sets(
    report: object,
    forge: Mapping[str, object],
    node_type_map: Dict[str, str],
    all_node_ids: Set[str],
    slot_count_by_node: Dict[str, int],
    settings: ForgeSettings,
) -> None:
    """2c2d V1/V2/V3 + W1/W4 黄（sets 段）。"""
    sets = forge.get("sets")
    if sets is None:
        return
    if not isinstance(sets, list):
        _err(report, "forge.sets", "2c2d-V1", rule="sets_not_list",
             got=type(sets).__name__)
        return
    if not sets:
        return  # 空段放行
    seen_combo: Set[Tuple[str, str]] = set()
    # 同族 variant → 记录（W1 α/β 孔位对照）
    family: Dict[str, Dict[str, List[str]]] = {}
    for si, s in enumerate(sets):
        if not isinstance(s, Mapping):
            _err(report, f"forge.sets.{si}", "2c2d-V1", rule="set_not_object",
                 got=type(s).__name__)
            continue
        base = f"forge.sets.{si}"
        sid = s.get("id")
        variant = s.get("variant")
        # V1：(id, variant) 组合唯一；族 id 可被 α/β 双记录共用（VAR-01 合法形态，
        # 契约 V1「族级唯一」实际约束落在 (id, variant) 组合 + variant ∈ {alpha,beta}，
        # 见 test_2c2d_v1_set_family_variant_unique 注释）——族 id 重复本身不红拦
        if not isinstance(sid, str) or not sid:
            _err(report, f"{base}.id", "2c2d-V1", rule="set_id_required",
                 msg="套装 id 必填（族键，α/β 共用，V1）")
        if not isinstance(variant, str) or variant not in SET_VARIANTS:
            _err(report, f"{base}.variant", "2c2d-V1", rule="set_variant_invalid",
                 variant=variant, allowed=list(SET_VARIANTS),
                 msg="variant %r 不认识（alpha/beta，V1）" % (variant,))
        elif isinstance(sid, str) and sid:
            combo = (sid, variant)
            if combo in seen_combo:
                _err(report, f"{base}.variant", "2c2d-V1", rule="set_variant_duplicate",
                     id=sid, variant=variant,
                     msg="(id, variant)=%r 组合重复（V1）" % (combo,))
            seen_combo.add(combo)
            family.setdefault(sid, {})[variant] = []

        # V2：pieces 引用 + 防具五部位 + 不重复 + ≤5
        pieces = s.get("pieces")
        if not isinstance(pieces, list) or not pieces:
            _err(report, f"{base}.pieces", "2c2d-V2", rule="set_pieces_required",
                 msg="pieces 必填（≥1 个 forge 树节点 id，V2）")
            pieces = []
        else:
            if len(pieces) > 5:
                _err(report, f"{base}.pieces", "2c2d-V2", rule="set_pieces_too_many",
                     count=len(pieces), msg="pieces ≤5 项（V2）")
            seen_piece: Set[str] = set()
            for pi, p in enumerate(pieces):
                if not isinstance(p, str) or not p:
                    _err(report, f"{base}.pieces.{pi}", "2c2d-V2",
                         rule="set_piece_invalid", value=p)
                    continue
                if p not in all_node_ids:
                    _err(report, f"{base}.pieces.{pi}", "2c2d-V2",
                         rule="set_piece_missing", piece=p,
                         msg="套装件 %r forge 树未定义（V2 悬空）" % p)
                    continue
                ptype = node_type_map.get(p)
                if ptype not in ARMOR_TYPES:
                    _err(report, f"{base}.pieces.{pi}", "2c2d-V2",
                         rule="set_piece_not_armor", piece=p, node_type=ptype,
                         msg="套装件 %r type %r 非防具五部位（V2）" % (p, ptype))
                if p in seen_piece:
                    _err(report, f"{base}.pieces.{pi}", "2c2d-V2",
                         rule="set_piece_duplicate", piece=p,
                         msg="套装件 %r 部位重复（V2）" % p)
                seen_piece.add(p)
                if isinstance(sid, str) and sid and variant in SET_VARIANTS:
                    family[sid][variant].append(p)

        # V3：技能档位 ∈ 配置集合 + level ∈ {1,2,3}（P1-1 裁决 2026-08-30：
        #   档位集合可配 set_piece_counts，缺省 {2,3,5}；缺档/跳档降黄提示不拦）
        allowed_pc: Tuple[int, ...] = settings.set_piece_counts
        skills = s.get("skills")
        if not isinstance(skills, list) or not skills:
            _err(report, f"{base}.skills", "2c2d-V3", rule="set_skills_required",
                 msg="skills 必填 ≥1 行（V3）")
            skills = []
        else:
            by_skill: Dict[str, Set[int]] = {}
            for ki, k in enumerate(skills):
                kbase = f"{base}.skills.{ki}"
                if not isinstance(k, Mapping):
                    _err(report, kbase, "2c2d-V3", rule="set_skill_not_object",
                         got=type(k).__name__)
                    continue
                pc = k.get("piece_count")
                skill = k.get("skill")
                lv = k.get("level")
                if not isinstance(pc, int) or isinstance(pc, bool) or pc not in allowed_pc:
                    _err(report, f"{kbase}.piece_count", "2c2d-V3",
                         rule="set_skill_piece_count_invalid", piece_count=pc,
                         allowed=list(allowed_pc),
                         msg="piece_count %r 不在配置档位集合 %s（V3）" % (pc, list(allowed_pc)))
                if not isinstance(skill, str) or not skill:
                    _err(report, f"{kbase}.skill", "2c2d-V3", rule="set_skill_id_required",
                         msg="skill 必填（6a 技能库 id，V3）")
                if not isinstance(lv, int) or isinstance(lv, bool) or not (
                        1 <= lv <= SET_LEVEL_MAX):
                    _err(report, f"{kbase}.level", "2c2d-V3", rule="set_skill_level_invalid",
                         level=lv, allowed_max=SET_LEVEL_MAX,
                         msg="level ∈ {1,2,3}（默认封顶，V3 硬；超封顶 W4 黄）")
                if isinstance(skill, str) and isinstance(pc, int) and not isinstance(pc, bool):
                    by_skill.setdefault(skill, set()).add(pc)
            # 同一 skill 档位：在配置集合内缺中间档（如配置 {2,3,5} 写 [2,5] 缺 3）
            # → 黄提示不拦（P1-1 裁决：档位集合可配后作者自选档位组合——只建议）
            for skill, pcs in by_skill.items():
                if not pcs:
                    continue
                ordered = sorted(pcs)
                if list(pcs) != ordered:
                    _warn(report, f"{base}.skills", "2c2d-V3",
                          rule="set_skill_order_warn", skill=skill, pieces=sorted(pcs),
                          msg="skill %r 档位未按升序（建议递增，仅提示）" % skill)
                # 缺中间档判定：配置集合中存在 between(相邻档位) 的档位未写
                for a, b in zip(ordered, ordered[1:]):
                    between = [x for x in allowed_pc if a < x < b]
                    if between:
                        _warn(report, f"{base}.skills", "2c2d-V3",
                              rule="set_skill_gap_warn", skill=skill, pieces=sorted(pcs),
                              msg="skill %r 档位 %s 缺中间档（配置集合可含跳档，仅提示）"
                                  % (skill, sorted(pcs)))
                        break
            # W4 黄：level 超默认封顶 3
            for ki, k in enumerate(skills):
                if isinstance(k, Mapping):
                    lv = k.get("level")
                    if isinstance(lv, int) and not isinstance(lv, bool) and lv > SET_LEVEL_MAX:
                        _warn(report, f"{base}.skills.{ki}.level", "2c2d-W4",
                              rule="set_skill_level_over_cap", level=lv,
                              msg="套装技能 level %d 超默认封顶 %d（数值膨胀风险，W4 黄）"
                                  % (lv, SET_LEVEL_MAX))

    # ---- W1 黄：α/β 孔位对照（同族两版：α ≤ β 孔位总数）----
    for sid, variants in family.items():
        alpha_pieces = variants.get("alpha")
        beta_pieces = variants.get("beta")
        if alpha_pieces and beta_pieces:
            alpha_slots = sum(slot_count_by_node.get(p, 0) for p in alpha_pieces)
            beta_slots = sum(slot_count_by_node.get(p, 0) for p in beta_pieces)
            if alpha_slots > beta_slots:
                _warn(report, f"forge.sets.{sid}", "2c2d-W1", rule="alpha_beta_slot_mismatch",
                      id=sid, alpha_slots=alpha_slots, beta_slots=beta_slots,
                      msg="α/β 孔位对照：α %d > β %d（技能多孔少/技能少孔多，W1 黄）"
                          % (alpha_slots, beta_slots))

    # ---- W3 黄：settings 关闭 P1 但 sets 数据存在（2c2a W3 同文）----
    if not settings.sets_enabled:
        _warn(report, "forge.sets", "W3", rule="sets_disabled_but_data",
              msg="settings.sets_enabled=false 但 sets 数据存在，该段不生效（W3 黄）")


def _check_augments(
    report: object,
    forge: Mapping[str, object],
    items: Optional[Dict[str, Mapping[str, object]]],
    settings: ForgeSettings,
) -> None:
    """2c2d V4/V5/V6/V8 + W2 黄（augments 段）。"""
    aug = forge.get("augments")
    if aug is None:
        return
    aug_rows_raw: object
    limit_raw: object
    if isinstance(aug, list):
        aug_rows_raw = aug
        limit_raw = []
    elif isinstance(aug, Mapping):
        aug_rows_raw = aug.get("augments")
        limit_raw = aug.get("limit_by_rarity")
    else:
        _err(report, "forge.augments", "2c2d-V4", rule="augments_not_object",
             got=type(aug).__name__)
        return

    # ---- V4：客制项枚举与结构 ----
    if aug_rows_raw is None:
        aug_rows = []
    elif isinstance(aug_rows_raw, list):
        aug_rows = aug_rows_raw
    else:
        _err(report, "forge.augments.augments", "2c2d-V4", rule="augments_rows_not_list",
             got=type(aug_rows_raw).__name__)
        aug_rows = []
    seen_aug_ids: Set[str] = set()
    all_disabled = bool(aug_rows)  # V8：全段 disabled 判定（空段不提示）
    for ai, a in enumerate(aug_rows):
        base = f"forge.augments.augments.{ai}"
        if not isinstance(a, Mapping):
            _err(report, base, "2c2d-V4", rule="augment_not_object",
                 got=type(a).__name__)
            all_disabled = False
            continue
        aid = a.get("id")
        if not isinstance(aid, str) or not aid:
            _err(report, f"{base}.id", "2c2d-V4", rule="augment_id_required",
                 msg="客制项 id 必填（全段唯一，V4）")
        elif aid in seen_aug_ids:
            _err(report, f"{base}.id", "2c2d-V4", rule="augment_id_duplicate", id=aid,
                 msg="客制项 id %r 全段重复（V4）" % aid)
        else:
            seen_aug_ids.add(aid)
        kind = a.get("kind")
        if not isinstance(kind, str) or kind not in AUGMENT_KINDS:
            _err(report, f"{base}.kind", "2c2d-V4", rule="augment_kind_invalid",
                 got=kind, allowed=list(AUGMENT_KINDS),
                 msg="kind %r 不认识（numeric/slot，V4）" % (kind,))
        else:
            if kind == "numeric":
                sk = a.get("stat_key")
                if not isinstance(sk, str) or not sk:
                    _err(report, f"{base}.stat_key", "2c2d-V4",
                         rule="augment_numeric_stat_key_required",
                         msg="numeric 项必填 stat_key（V4）")
            else:  # slot
                sl = a.get("slot_level")
                if not isinstance(sl, int) or isinstance(sl, bool) or sl not in SLOT_LEVELS:
                    _err(report, f"{base}.slot_level", "2c2d-V4",
                         rule="augment_slot_level_invalid", slot_level=sl,
                         allowed=list(SLOT_LEVELS),
                         msg="slot 项必填 slot_level ∈ {1,2,3}（V4）")
        cost = a.get("cost")
        if cost is None or (isinstance(cost, list) and not cost):
            _err(report, f"{base}.cost", "2c2d-V4", rule="augment_cost_required",
                 msg="cost ≥1 行（V4）")
        elif not isinstance(cost, list):
            _err(report, f"{base}.cost", "2c2d-V4", rule="augment_cost_not_list",
                 got=type(cost).__name__)
        else:
            # V5：客制消耗引用（items 存在；龙脉石 rare；宝石存在）
            for ci, c in enumerate(cost):
                cbase = f"{base}.cost.{ci}"
                if not isinstance(c, Mapping):
                    _err(report, cbase, "2c2d-V4", rule="augment_cost_row_not_object",
                         got=type(c).__name__)
                    continue
                c_item = c.get("item")
                if not isinstance(c_item, str) or not c_item:
                    _err(report, f"{cbase}.item", "2c2d-V5",
                         rule="augment_cost_item_required",
                         msg="客制消耗 item 必填（V5）")
                elif items is not None:
                    if c_item not in items:
                        _err(report, f"{cbase}.item", "2c2d-V5",
                             rule="augment_cost_item_missing", item=c_item,
                             msg="客制消耗 %r 在 items.json 中不存在（V5）" % c_item)
                    else:
                        entry = items[c_item]
                        mt = entry.get("material_tier")
                        if isinstance(mt, str) and mt != "rare":
                            _err(report, f"{cbase}.item", "2c2d-V5",
                                 rule="augment_cost_not_rare", item=c_item,
                                 material_tier=mt,
                                 msg="客制消耗龙脉石类须 material_tier:rare（V5）")
                c_count = c.get("count")
                if not isinstance(c_count, int) or isinstance(c_count, bool) or c_count < 1:
                    _err(report, f"{cbase}.count", "2c2d-V4",
                         rule="augment_cost_count_invalid", count=c_count,
                         msg="客制消耗 count ≥1（V4）")
        disabled = a.get("disabled")
        trace = a.get("trace")
        if disabled is True:
            pass  # 保留 disabled 项计数
        else:
            all_disabled = False
        # W2 黄：追溯行 trace → 提示"回复已砍不生效"
        if trace is True:
            _warn(report, f"{base}.trace", "2c2d-W2", rule="augment_trace_legacy",
                  id=aid, name=a.get("name"),
                  msg="追溯行 %r 已砍（不生效，不出面板；W2 黄）" % (aid,))

    # ---- V8 黄：客制全段 disabled 且 settings 开 → 配置意图存疑 ----
    if aug_rows and all_disabled and settings.augments_enabled:
        _warn(report, "forge.augments.augments", "2c2d-V8",
              rule="augments_all_disabled",
              msg="客制全段 disabled 且 augments_enabled=true，配置意图存疑；"
                  "若有意关闭请设 augments_enabled=false（2c2d V8 黄）")

    # ---- V6：次数表合法 ----
    if limit_raw is None:
        limit_rows = []
    elif isinstance(limit_raw, list):
        limit_rows = limit_raw
    else:
        _err(report, "forge.augments.limit_by_rarity", "2c2d-V6",
             rule="limit_not_list", got=type(limit_raw).__name__)
        limit_rows = []
    by_quality: Dict[str, int] = {}
    for li, lim_row in enumerate(limit_rows):
        base = f"forge.augments.limit_by_rarity.{li}"
        if not isinstance(lim_row, Mapping):
            _err(report, base, "2c2d-V6", rule="limit_row_not_object",
                 got=type(lim_row).__name__)
            continue
        q = lim_row.get("quality")
        if not isinstance(q, str) or q not in LIMIT_RARITY_QUALITIES:
            _err(report, f"{base}.quality", "2c2d-V6", rule="limit_quality_invalid",
                 quality=q, allowed=list(LIMIT_RARITY_QUALITIES),
                 msg="quality %r 不认识（四档枚举，禁整数/R 口径，V6）" % (q,))
        else:
            by_quality[q] = by_quality.get(q, 0) + 1
        times = lim_row.get("times")
        if not isinstance(times, int) or isinstance(times, bool) or times < 1:
            _err(report, f"{base}.times", "2c2d-V6", rule="limit_times_invalid",
                 times=times, msg="times ≥1 整数（V6）")
        fo = lim_row.get("final_only")
        if fo is not None and not isinstance(fo, bool):
            _err(report, f"{base}.final_only", "2c2d-V6", rule="limit_final_only_not_bool",
                 final_only=fo)
        if fo is True and q != "legendary":
            _err(report, f"{base}.final_only", "2c2d-V6",
                 rule="limit_final_only_requires_legendary", quality=q,
                 msg="final_only=true 行必须 quality=legendary（V6）")
    for q, cnt in by_quality.items():
        if cnt > 2:
            _err(report, f"forge.augments.limit_by_rarity.{q}", "2c2d-V6",
                 rule="limit_quality_too_many", quality=q, count=cnt,
                 msg="quality %r 至多 2 行（1 普通 + 1 final_only，V6）" % q)

    # ---- W3 黄：settings 关闭 P2 但 augments 数据存在（2c2a W3 同文）----
    if not settings.augments_enabled and (aug_rows or limit_rows):
        _warn(report, "forge.augments", "W3", rule="augments_disabled_but_data",
              msg="settings.augments_enabled=false 但 augments 数据存在，该段不生效（W3 黄）")


def validate_forge(modules: Mapping[str, object], report: object) -> None:
    """forge 模块专项校验（共享契约 §六 V1-V15 硬 + V16/W1-W6 黄 + 2c2d V1-V8 硬/W1-W4 黄）。

    入参：
      modules: 模块名（无 .json 后缀）→ parsed JSON（含 "forge" 与可选 "items"/"enemies"；
               forge 顶层是 obj 非 list——trees/sets/augments/settings 四段）。
      report:  鸭子类型收集器：error/warning 方法 或 _err/_warn 方法 或
               {"errors":[],"warnings":[]} dict（_emit 三形态兜底）。
    出参：None；红拦（error=加载失败）/ 黄提示（warning=不阻断）经 report 追加（一次给全量）。
    forge 模块缺失/非 Mapping → 跳过（对齐既有校验器「模块未接线默认放行」惯例）。
    """
    forge = modules.get("forge")
    if not isinstance(forge, Mapping):
        return

    # 引用靶
    items = _items_map(modules)
    enemy_weak = _enemy_element_weaknesses(modules)
    settings = ForgeSettings.from_entry(forge.get("settings"))

    # 树级
    trees = forge.get("trees")
    if not isinstance(trees, list):
        _err(report, "forge.trees", "V1", rule="trees_not_list",
             got=type(trees).__name__)
        return
    node_type_by_tree, tree_raw = _check_tree_shape(report, forge, trees)

    all_node_ids: Set[str] = set()
    seen_node_ids: Set[str] = set()
    node_type_map: Dict[str, str] = {}
    node_level_map: Dict[str, Optional[int]] = {}
    parent_refs: Dict[str, List[str]] = {}
    branch_refs: Dict[str, List[str]] = {}
    slot_count_by_node: Dict[str, int] = {}

    # 收集孔位计数（W1 α/β 对照用）
    for i, tree in enumerate(trees):
        if not isinstance(tree, Mapping):
            continue
        nodes_raw = tree.get("nodes")
        if not isinstance(nodes_raw, list):
            continue
        for ni, n in enumerate(nodes_raw):
            if not isinstance(n, Mapping):
                continue
            nid = n.get("id")
            if not isinstance(nid, str) or not nid:
                continue
            slots = n.get("slots")
            if isinstance(slots, list):
                slot_count_by_node[nid] = sum(
                    1 for s in slots if isinstance(s, Mapping))
            else:
                slot_count_by_node[nid] = 0

    # 预收集全文件全部树节点 id（V3 跨树判定基准：先全集后逐节点，
    # 防增量收集把跨树 parent 误判为 parent_missing——test_v3_parent_cross_tree）
    for tree in trees:
        if not isinstance(tree, Mapping):
            continue
        nodes_raw = tree.get("nodes")
        if not isinstance(nodes_raw, list):
            continue
        for n in nodes_raw:
            if not isinstance(n, Mapping):
                continue
            nid = n.get("id")
            if isinstance(nid, str) and nid:
                all_node_ids.add(nid)

    _check_tree_nodes(
        report, forge, trees, items, enemy_weak, settings,
        all_node_ids, seen_node_ids, node_type_map, node_level_map,
        parent_refs, branch_refs,
    )

    # sets（2c2d V1/V2/V3 + W1/W4 + W3）
    _check_sets(report, forge, node_type_map, all_node_ids,
                slot_count_by_node, settings)

    # augments（2c2d V4/V5/V6/V8 + W2/W3）
    _check_augments(report, forge, items, settings)

    # ---- W4 黄：synth_ratio_3to1=false 且素材死锁风险（稀有素材缺替代升档渠道）----
    if not settings.synth_ratio_3to1:
        rare_seen = False
        for i, tree in enumerate(trees):
            if not isinstance(tree, Mapping):
                continue
            nodes_raw = tree.get("nodes")
            if not isinstance(nodes_raw, list):
                continue
            for n in nodes_raw:
                if not isinstance(n, Mapping):
                    continue
                materials = n.get("materials")
                if not isinstance(materials, list):
                    continue
                for m in materials:
                    if not isinstance(m, Mapping):
                        continue
                    tier = m.get("tier")
                    if tier == "rare":
                        rare_seen = True
                        break
                    mitem = m.get("item")
                    if isinstance(mitem, str) and items is not None and mitem in items:
                        mt = items[mitem].get("material_tier")
                        if mt == "rare":
                            rare_seen = True
                            break
                if rare_seen:
                    break
            if rare_seen:
                break
        if rare_seen:
            _warn(report, "forge.settings.synth_ratio_3to1", "W4",
                  rule="synth_off_deadlock_risk",
                  msg="synth_ratio_3to1=false 且存在稀有素材需求，素材死锁风险"
                      "（对策：合成+商店+分解，W4 黄）")
