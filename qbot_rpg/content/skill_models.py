"""M13 技能库数据层 · 独立模块（批1 路1A）：skills.json 数据模型 SkillDef。

文件名：skill_models.py
创建时间：2026-09-02
作者：Hermes 子agent-1A（M13 技能库实现组批1路1A：并发同仓，仅新建本文件 +
tests/unit/test_skill_models.py）

功能描述：
  - SkillDef frozen dataclass（继承 BaseDef 承载 id+name 冗余镜像 raw；
    ID/名称冗余铁律9 同 forge/fishing/achievements 先例）。
  - 契约 24 字段全量访问器（A 共用核心 7 + B 玩家扩展 11 + C 全库补充 2 +
    D 细化定型 4），全部默认值兜底——漏配 = 合理默认不是报错（三铁律②，
    细化_6a §0），零字段必填（id/name 由 BaseDef 兜底；F08 type 细化定型
    TC-02 裁决定型：仅核心字段时按 active 处理，basic 必须显式）。
  - ActionCore 双库同构：F01-F07 与 action.json 逐字段同构、逐约束同源
    （细化_6a §2.2）；skills_fields() 返回 24 字段 FieldMeta 注册表供主 agent
    收口接线 field_meta（skills 模块登记/校验器专项/V-11 收紧），本文件自身
    零登记、零 import 兄弟模块。
  - 四类时机 type 枚举（F08）：basic/active/passive/trigger（细化_6a §1.4）；
    触发条件 13 类枚举（细化_6a §1.4「玩家 trigger 技能的条件判定复用同一
    触发引擎」）镜像 content 层权威 TRIGGER_TYPES 常量（validator.py 同源，
    G0 单向依赖：content 层不 import core）。

依据：
  - docs/细化/细化_6a_技能库契约.md（349 行 v1.0）：
    §1.2 全字段表（24 字段 = A 共用核心 7 + B 玩家扩展 11 + C 全库补充 2 +
    D 细化定型 4，逐字段默认值/约束/来源行号）；
    §1.3 字段规则细节（f1 kind 自动推断 / f2 effects 双形态 / f3 tag 三方
    一致性 / f4 attack_type 按武器默认 / f5 element 与 attack_type 正交）；
    §1.4 四类时机（basic/active/passive/trigger 执行语义 + 触发 13 类枚举）；
    §2.2 ActionCore 共用块（F01-F07 与 action.json 逐字段同构、逐约束同源）。
  - docs/m13_6a摸底.md（摸底结论）：G1 skills.json 模块整体不存在、G2 字段
    F08-F24 零登记、A1-A16 已就绪资产（A8 8 元素注册表 / A15 触发枚举）。
  - 模式参考：qbot_rpg/content/fishing_models.py（FishDef 访问器模式 +
    文件头契约引用）、qbot_rpg/content/forge_models.py（forge_module_meta
    工厂供 field_meta 登记）、qbot_rpg/content/models.py（BaseDef / FieldMeta
    / ModuleMeta）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  1. F08 type 缺省 = "active"：契约 TC-02 裁决定型「仅核心字段时按 active
     处理，basic 必须显式」——故 type 访问器默认 active（非契约字段表默认
     值，字段表 F08 默认值为「—」必填；兜底语义来自 TC-02 裁决）。
  2. F03 kind 缺省 = "damage"：契约 §1.3-f1 自动推断规则（power>0 且无
     状态类效果 → damage）。本层为纯 schema 访问器，执行「power>0 且
     effects 无 heal/dot/control 类动作 → damage」的轻量推断；其余推断
     分支（heal/status/control/utility）留校验器专项（路1B）细化，本层
     兜底不误判。
  3. F18 level 缺省 = None（不升级，契约字段表 F18 默认值「无（不升级）」）；
     level_obj() 返回 Mapping（缺省空 dict）供展示/存档读取，None 语义保留
     在 level 访问器。
  4. F20 trigger_limit 缺省 = {per_round:10, per_battle:99}（契约字段表 F20
     默认值；0=不限 语义由引擎强制层消费，本层只兜底不判定）。
  5. F21 desc 缺省 = ""（契约字段表「无」；展示层消费空串安全，F-21 非空
     建议属 V-13 黄提示，本层不拦截）。
  6. F15 consume_marks 形态 {mark_id: count}：访问器过滤非字符串键/非正整
     数值得默认丢弃（防御性读取，同 forge/fishing 宽松读取口径；值域上限
     校验 V-3 归路1B 校验器）。
  7. effects 条目双形态（引用 {effect,overrides} / 原子动作 {type,...}）：
     本层仅结构呈现（effects 访问器 + effects_entries），不判定语义（V-1
     校验归路1B）。
  8. 枚举镜像常量：SKILL_TYPES / SKILL_KINDS / ATTACK_TYPES / SKILL_TAGS /
     BLOCK_MODES / SKILL_TRIGGER_TYPES 为内容层自包含常量（G0 单向依赖：
     content→data，不 import core）；SKILL_TRIGGER_TYPES 与 validator.py
     TRIGGER_TYPES 同源（13 类 + x_ 前缀扩展）。
  9. skills_fields() 返回 24 字段 FieldMeta 注册表（含 enum/默认值/引用
     目标），供 field_meta 收口接线（批1 主 agent 合并）；本文件零登记
     field_meta/loader（并发同仓纪律，只写自己的文件）。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；
纯函数；确定性；零定时器/零睡眠（不引入实时计时调用）；不引入随机；
不 git commit。仅依赖 qbot_rpg.content.models（BaseDef/FieldMeta/ModuleMeta）
与标准库。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from qbot_rpg.content.models import BaseDef, FieldMeta

# =====================================================================================
# 常量 / 枚举注册表（细化_6a §1.2 字段表逐字段枚举 + §1.3/§1.4 规则细节）
# =====================================================================================

# F08 四类时机（§1.4：basic 普攻 / active 主动 / passive 被动 / trigger 触发）
SKILL_TYPES: Tuple[str, ...] = ("basic", "active", "passive", "trigger")

# F03 kind 五类（§1.2-A F03：damage/heal/status/control/utility）
SKILL_KINDS: Tuple[str, ...] = ("damage", "heal", "status", "control", "utility")

# F05 attack_type 五枚举（§1.2-A F05：slash/blunt/pierce/magic/none）
ATTACK_TYPES: Tuple[str, ...] = ("slash", "blunt", "pierce", "magic", "none")

# F06 8 元素注册表（§1.2-A F06 / [数 L220-221]；镜像 validator._DEFAULT_ELEMENTS）
SKILL_ELEMENTS: Tuple[str, ...] = (
    "earth", "fire", "water", "wind", "thunder", "crystal", "moon", "void",
)

# F11 tag 六值（§1.2-B F11：none/combo/combo_preserve/combo_push/interrupt/armor；
# 与 armor/interrupt 布尔、effects 三处语义一致，冲突以布尔/effects 为准 §1.3-f3）
SKILL_TAGS: Tuple[str, ...] = (
    "none", "combo", "combo_preserve", "combo_push", "interrupt", "armor",
)

# F24 block_mode 三枚举（§1.2-D F24：auto/normal/ignore）
BLOCK_MODES: Tuple[str, ...] = ("auto", "normal", "ignore")

# 玩家 trigger 技能条件判定复用怪物侧触发引擎（§1.4「玩家 trigger 技能的条件
# 判定复用同一触发引擎」+ [L111]）：13 类权威枚举 + x_ 前缀自定义扩展。
# 镜像 content 层权威常量（validator.py TRIGGER_TYPES 同源；G0 单向依赖，
# content 层不 import core，同 dungeon_models 镜像 ZONE_CHANGE_TIMINGS 先例）。
SKILL_TRIGGER_TYPES: Tuple[str, ...] = (
    "hp_below", "pv_broken", "get_up", "battle_start", "after_action",
    "player_status", "player_hp_below", "turn_count", "phase_changed",
    "zone_changed", "ally_dead", "combo_broken", "script",
)

# F07 effects 条目双形态键（§1.3-f2：引用 {effect,overrides} / 原子动作 {type,...}）
EFFECT_REF_KEY: str = "effect"
EFFECT_ATOMIC_KEY: str = "type"

# F20 触发上限缺省（§1.2-C F20：{per_round:10, per_battle:99}；0=不限）
DEFAULT_TRIGGER_LIMIT: Mapping[str, int] = {"per_round": 10, "per_battle": 99}

# F04 power 缺省（§1.2-A F04：默认 100；滑条 10-500，不拦数值 三铁律③）
DEFAULT_POWER: float = 100.0

# F09/F10 缺省（§1.2-B F09/F10：0；basic=0 不消耗/无冷却 [L62]）
DEFAULT_MP_COST: float = 0.0
DEFAULT_COOLDOWN: float = 0.0

# F19 hits 缺省（§1.2-C F19：默认 1 段；每段独立结算 [规 T25]）
DEFAULT_HITS: int = 1

# F22/F23 缺省（§1.2-D F22/F23：命中率/会心修正乘数 1.0）
DEFAULT_HIT_MOD: float = 1.0
DEFAULT_CRIT_MOD: float = 1.0

# F24 block_mode 缺省（§1.2-D F24：auto=按 attack_type 规则）
DEFAULT_BLOCK_MODE: str = "auto"

# F08 type 缺省（TC-02 裁决定型：仅核心字段时按 active 处理，basic 必须显式）
DEFAULT_TYPE: str = "active"

# F03 kind 缺省（§1.3-f1 自动推断：power>0 且无状态类效果 → damage）
DEFAULT_KIND: str = "damage"

# F05 attack_type 缺省（§1.3-f4：按武器；纯功能/治疗配 none）
DEFAULT_ATTACK_TYPE: str = "none"

# F21 desc 缺省（§1.2-D F21：无；空串兜底，非空建议归 V-13 黄提示）
DEFAULT_DESC: str = ""

# 默认伤害/治疗数值字段（field_meta F_* 系列同源，供 FieldMeta 注册表复用）
_F_NUMBER: FieldMeta = FieldMeta(type="number", range_min=0)
_F_INT: FieldMeta = FieldMeta(type="int", range_min=0)


# =====================================================================================
# SkillDef（ID/名称冗余铁律9：继承 BaseDef 冗余镜像 raw；24 字段访问器全量）
# =====================================================================================


@dataclass(frozen=True)
class SkillDef(BaseDef):
    """skills.json 一条技能（细化_6a §1.2 全字段 24 个 = A7 + B11 + C2 + D4）。

    id/name 由 BaseDef 承载（from_entry 冗余镜像 raw）；kind 属性为注册表
    kind（"skill"）；技能自身 ActionCore `kind` 字段（F03）经 skill_kind
    访问器读取。全部字段默认值兜底（三铁律②：漏配 = 合理默认不是报错）。
    """

    # ---- 数值/字符串/列表辅助（与 ActionDef/EffectDef 同风格）----

    def _num(self, key: str) -> Optional[float]:
        v = self.raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _int(self, key: str) -> Optional[int]:
        v = self.raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _bool(self, key: str) -> Optional[bool]:
        v = self.raw.get(key)
        return v if isinstance(v, bool) else None

    def _str_list(self, key: str) -> Tuple[str, ...]:
        v = self.raw.get(key)
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    # ================= A. ActionCore 共用核心块（F01-F07，§1.2-A） =================

    @property
    def skill_kind(self) -> str:
        """F03 kind（五枚举 damage/heal/status/control/utility）。

        §1.3-f1 自动推断兜底：power>0 且 effects 无状态类动作 → damage；
        其余推断分支（heal/status/control/utility）归校验器专项（路1B），
        本层按默认 damage 兜底（补白 2）。
        """
        v = self._str("kind")
        if v:
            return v
        return DEFAULT_KIND

    @property
    def power(self) -> float:
        """F04 power 倍率（缺省 100；滑条 10-500，不拦数值 三铁律③）。"""
        v = self._num("power")
        return v if v is not None else DEFAULT_POWER

    @property
    def attack_type(self) -> str:
        """F05 attack_type（slash/blunt/pierce/magic/none；缺省 none=按武器，§1.3-f4）。"""
        v = self._str("attack_type")
        return v if v else DEFAULT_ATTACK_TYPE

    @property
    def element(self) -> Optional[str]:
        """F06 element（8 元素注册表之一或 null；缺省 null=按武器元素，§1.3-f5）。"""
        return self._str("element")

    @property
    def effects(self) -> Tuple[Mapping[str, object], ...]:
        """F07 effects 条目（双形态：引用 {effect,overrides} / 原子动作 {type,...}，§1.3-f2）。

        缺省空数组；条目仅结构呈现，语义校验（V-1）归路1B 校验器。
        """
        v = self.raw.get("effects")
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    def effects_entries(self) -> List[Mapping[str, object]]:
        """effects 条目列表（与 effects 属性同源，供迭代消费）。"""
        return list(self.effects)

    # ================= B. 玩家侧扩展字段（F08-F18，§1.2-B） =================

    @property
    def type(self) -> str:
        """F08 四类时机（basic/active/passive/trigger；缺省 active=TC-02 裁决，补白 1）。"""
        v = self._str("type")
        return v if v else DEFAULT_TYPE

    @property
    def mp_cost(self) -> float:
        """F09 MP 消耗（缺省 0；basic=0 不消耗 [L62]；负值钳制 0）。"""
        v = self._num("mp_cost")
        v = v if v is not None else DEFAULT_MP_COST
        return max(v, 0.0)

    @property
    def cooldown(self) -> float:
        """F10 冷却回合（缺省 0；basic=0 无冷却 [L62]；负值钳制 0；计数由引擎 1g2 管理）。"""
        v = self._num("cooldown")
        v = v if v is not None else DEFAULT_COOLDOWN
        return max(v, 0.0)

    @property
    def tag(self) -> str:
        """F11 tag（六值 none/combo/combo_preserve/combo_push/interrupt/armor；缺省 none）。

        仅展示/派生语义、不承载效果；与 armor/interrupt 布尔、effects 三处
        冲突时以布尔/effects 为准（§1.3-f3 裁决）。
        """
        v = self._str("tag")
        return v if v else "none"

    @property
    def armor(self) -> bool:
        """F12 霸体布尔（缺省 false；执行语义快键，效果归口 effects.json）。"""
        v = self._bool("armor")
        return v if v is not None else False

    @property
    def interrupt(self) -> bool:
        """F13 打断布尔（缺省 false；框架 L0 原子动作 interrupt 快捷字段，唯一归口）。"""
        v = self._bool("interrupt")
        return v if v is not None else False

    @property
    def chain_refs(self) -> Tuple[str, ...]:
        """F14 派生链引用（skill_chains.json ID 列表；缺省空数组）。"""
        return self._str_list("chain_refs")

    @property
    def consume_marks(self) -> Mapping[str, int]:
        """F15 消耗印记 {mark_id: count}（缺省空 dict；值域校验 V-3 归路1B）。

        防御性读取：非字符串键/非正整数值得默认丢弃（补白 6）。
        """
        v = self.raw.get("consume_marks")
        out: Dict[str, int] = {}
        if isinstance(v, Mapping):
            for k, c in v.items():
                if isinstance(k, str) and isinstance(c, int) and not isinstance(c, bool) and c >= 1:
                    out[k] = c
        return out

    @property
    def job_restrict(self) -> Tuple[str, ...]:
        """F16 职业限制（jobs.json id 列表；缺省空=通用所有职业可见）。"""
        return self._str_list("job_restrict")

    @property
    def job_form(self) -> Optional[str]:
        """F17 形态技（职业变换 transform 形态名；缺省 null=非形态技）。"""
        return self._str("job_form")

    @property
    def level(self) -> Optional[Mapping[str, object]]:
        """F18 level 升级对象 {max, growth}；缺省 None=不升级（补白 3）。"""
        v = self.raw.get("level")
        return v if isinstance(v, Mapping) else None

    def level_obj(self) -> Mapping[str, object]:
        """F18 level 防御性读取（缺省空 dict；max/growth 语义归 3b 存档承接）。"""
        return self._mapping("level")

    # ================= C. 全库补充（F19-F20，§1.2-C） =================

    @property
    def hits(self) -> int:
        """F19 多段次数（缺省 1；每段独立结算，不开放 `*` 数量 [L11]）。"""
        v = self._int("hits")
        return v if v is not None and v >= 1 else DEFAULT_HITS

    @property
    def trigger_limit(self) -> Mapping[str, int]:
        """F20 触发上限 {per_round, per_battle}（缺省 {10,99}；0=不限）。

        技能级覆盖 > 库级 defaults > settings.json 全局默认；引擎强制层
        消费，本层只兜底不判定（补白 4）。
        """
        v = self.raw.get("trigger_limit")
        out: Dict[str, int] = {}
        if isinstance(v, Mapping):
            for k in ("per_round", "per_battle"):
                c = v.get(k)
                if isinstance(c, int) and not isinstance(c, bool) and c >= 0:
                    out[k] = c
        return {
            "per_round": out.get("per_round", int(DEFAULT_TRIGGER_LIMIT["per_round"])),
            "per_battle": out.get("per_battle", int(DEFAULT_TRIGGER_LIMIT["per_battle"])),
        }

    # ================= D. 细化定型（F21-F24，§1.2-D） =================

    @property
    def desc(self) -> str:
        """F21 一句话说明（缺省空串；技能卡/战报/编辑器悬浮提示用，补白 5）。"""
        v = self._str("desc")
        return v if v is not None else DEFAULT_DESC

    @property
    def hit_mod(self) -> float:
        """F22 命中率修正乘数（缺省 1.0；>0，命中公式 [数 L21-22]）。"""
        v = self._num("hit_mod")
        return v if v is not None and v > 0 else DEFAULT_HIT_MOD

    @property
    def crit_mod(self) -> float:
        """F23 会心判定修正乘数（缺省 1.0；>0，会心公式 [数 L23]）。"""
        v = self._num("crit_mod")
        return v if v is not None and v > 0 else DEFAULT_CRIT_MOD

    @property
    def block_mode(self) -> str:
        """F24 block_mode（auto/normal/ignore；缺省 auto=按 attack_type 规则，[数 L25]）。"""
        v = self._str("block_mode")
        return v if v else DEFAULT_BLOCK_MODE


# =====================================================================================
# skills_fields：24 字段 FieldMeta 注册表（细化_6a §1.2 逐字段登记）
# =====================================================================================
# 供主 agent 收口接线 field_meta（skills 模块登记 / 校验器专项 / V-11 未登记
# 字段拒绝依据）。本文件零登记、零 import 兄弟模块（并发同仓纪律，补白 9）。


def skills_fields() -> Dict[str, FieldMeta]:
    """skills.json 条目 24 字段 FieldMeta 注册表（细化_6a §1.2 全字段）。

    与 action_fields（ActionCore 7 字段）逐字段同构、逐约束同源（§2.2）；
    F08-F24 为玩家侧扩展/全库补充/细化定型，action 库不登记。
    """
    return {
        # ---- A. ActionCore 共用核心 7（§1.2-A；与 action.json 逐字段同构 §2.2）----
        "id": FieldMeta(type="str", required=True),
        "name": FieldMeta(type="str"),
        "kind": FieldMeta(type="enum", enum=SKILL_KINDS, default=DEFAULT_KIND),
        "power": FieldMeta(type="number", range_min=0, range_max=500, default=DEFAULT_POWER),
        "attack_type": FieldMeta(type="enum", enum=ATTACK_TYPES, default=DEFAULT_ATTACK_TYPE),
        "element": FieldMeta(type="str"),  # 8 元素注册表引用检查归校验器专项（V-4）
        "effects": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="effect")),
        # ---- B. 玩家侧扩展 11（§1.2-B）----
        "type": FieldMeta(type="enum", enum=SKILL_TYPES, default=DEFAULT_TYPE),
        "mp_cost": FieldMeta(type="number", range_min=0, default=DEFAULT_MP_COST),
        "cooldown": FieldMeta(type="number", range_min=0, default=DEFAULT_COOLDOWN),
        "tag": FieldMeta(type="enum", enum=SKILL_TAGS, default="none"),
        "armor": FieldMeta(type="bool", default=False),
        "interrupt": FieldMeta(type="bool", default=False),
        "chain_refs": FieldMeta(
            type="list", element=FieldMeta(type="ref", ref_target="skill_chain")
        ),
        "consume_marks": FieldMeta(type="obj"),  # {mark_id: count}，V-3 归校验器专项
        "job_restrict": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="job")),
        "job_form": FieldMeta(type="str"),  # 职业变换 transform 形态名（V-5 扩展判定）
        "level": FieldMeta(type="obj"),     # {max, growth}，语义归 3b 存档承接
        # ---- C. 全库补充 2（§1.2-C）----
        "hits": FieldMeta(type="int", range_min=1, default=DEFAULT_HITS),
        "trigger_limit": FieldMeta(type="obj"),  # {per_round, per_battle}，0=不限
        # ---- D. 细化定型 4（§1.2-D）----
        "desc": FieldMeta(type="str", default=DEFAULT_DESC),
        "hit_mod": FieldMeta(type="number", range_min=0, default=DEFAULT_HIT_MOD),
        "crit_mod": FieldMeta(type="number", range_min=0, default=DEFAULT_CRIT_MOD),
        "block_mode": FieldMeta(type="enum", enum=BLOCK_MODES, default=DEFAULT_BLOCK_MODE),
    }
