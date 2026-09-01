"""技能/行动双库数据模型（6a · 路1B）。

ActionDef dataclass + ActionCore 元数据单点 + 行动库专项校验器。
文件名：skill_action_models.py
创建时间：2026-09-02
作者：Hermes 子agent（M13 批1 路1B：skill_actions.json 行动库）

功能描述：
  - ActionCore 元数据单点（ACTION_CORE_FIELDS + ACTION_CORE_DEFAULTS）：skills.json 与
    action.json 共用同一份 ActionCore 7 字段（id/name/kind/power/attack_type/element/effects）
    定义（契约 §2.1「ActionCore 元数据单点定义」/ §⑦ 编辑器元数据注册表 / V-11 判定依据）。
  - ActionDef dataclass：行动库条目 = ActionCore 7 字段（同构）+ 目标字段 G06 + 怪物侧扩展
    G01-G05（weight/probability/intent/chain/cooldown）+ AI 登记接口 G08-G16
    （condition/hungry/armor/interrupt/tags/charge_*/preview/preview_chain/reveal_condition）
    + G07 trigger_limit（契约 §2.3 全字段表）+ F21 desc 细化定型（§1.2-D F21）。
    与 models.ActionDef 同构（BaseDef 派生 + raw 只读镜像 + 防御性访问器，缺省兜底不报错，
    三铁律②「漏配 = 合理默认不是报错」）。
  - validate_actions(modules, report) 纯函数专项校验器（对齐 M4/M8/M10/M11 同族形态）：
    V-11 未登记字段红拦（仅本行动库收紧，不动 field_meta 既有 action 放行——摸底 §8-2 裁决）、
    V-10 库内 ID 唯一、V-9 probability ∈ {0,1} 红拦 + weight 全 0 且无链/条件「纯脚本怪？」黄提示、
    V-13 基础门禁（id/name 非空、kind 五枚举、attack_type 五枚举、power 数值域、target 六枚举）、
    V-4 元素 ∈ 8 元素注册表。
  - skill_action_meta() -> ModuleMeta：供主 agent 收口接线 field_meta（schema 之家单向持有
    模式，防循环 import）；本文件不改动任何既有文件。

依据：
  - docs/细化/细化_6a_技能库契约.md（349 行 v1.0）：
    §2.1 库级结构 / §2.2 ActionCore 共用块（F01-F07 逐字段同构、逐约束同源）/
    §2.3 怪物侧扩展 G01-G07 + AI 登记字段 G08-G16 / §2.4 目标解析（G06 六枚举）/
    ③ 校验器 V-1~V-13（V-4/V-9/V-10/V-11/V-13）/ ⑥ TC-01/TC-07/TC-10/TC-12/TC-13。
  - docs/m13_6a摸底.md：A1（ActionCore 7 字段已在 field_meta action_fields 登记 492-525）、
    §8-2（V-11 收紧范围限定 skills/行动库，不动既有 action 放行）、§9 批1 路1B。
  - 模式参考：qbot_rpg/content/fishing_models.py（Def dataclass + validate + ModuleMeta 工厂 +
    _emit/_err/_warn 三形态收集器）；qbot_rpg/content/forge_settings.py（ModuleMeta 工厂
    供 field_meta 登记）；qbot_rpg/content/models.py（BaseDef/ActionDef 防御性访问器风格）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  P-1  契约 §2.3 行动库字段表 G01-G07 + G08-G16 未给 F21 desc 是否适用的显式声明；
       按 §1.2-D F21（一句话说明，动作卡名称文本框扩展 [L154-165]）与行动卡同一卡编辑
       （§1.5「一卡编辑：技能页/行动页同卡」）推定行动条目同样承载 desc —— 登记 desc，
       缺省 None（【工程补白】标注，宽松不拦）。
  P-2  G07 trigger_limit 默认值 = F20 同款 {per_round:10, per_battle:99}（契约「同 F20」），
       本模型缺省 None（引擎 1g2 侧兜底），登记元数据供 V-11 放行与编辑器表单。
  P-3  kind 契约五枚举（damage/heal/status/control/utility）；既有内容包（test_demo/legal
       action.json）使用 basic/active 旧值（摸底 §8-4 内容包与契约枚举不一致）——校验器
       kind 枚举检查对 basic/active 旧值放行（读兼容），新枚举值由 6a 全量内容层收口。
  P-4  attack_type 契约五枚举（slash/blunt/pierce/magic/none）；既有内容包用中文
       斩/打/突/魔 —— 校验器放行中文旧值（读兼容），与 P-3 同口径。
  P-5  element 契约要求 ∈ 8 元素注册表（V-4 红拦）；既有内容包 element 均为注册表内
       英文值（earth/wind/fire/crystal…）——V-4 对既有包零命中；中文/未知值红拦。
  P-6  本行动库未登记字段红拦（V-11）只作用于本模块校验器（字段 ∈ 元数据注册表）；
       field_meta 泛型对 action 模块保持既有放行（摸底 §8-2 裁决），两路并行不冲突。
  P-7  行动级 target 与 effects[].target 分层（§2.4-1）：本模型只承载行动级 G06；
       效果级寻址由 effects.json 校验器（1b）承接。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；纯函数；
确定性；零定时器/零睡眠（本文件不含任何 sleep/定时器字面量）；不引入随机；不 git commit。
仅依赖 qbot_rpg.content.models（BaseDef/FieldMeta/ModuleMeta）与标准库。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Set, Tuple

from qbot_rpg.content.models import BaseDef, FieldMeta, ModuleMeta

# =====================================================================================
# 常量 / 枚举注册表（契约 §1.2 / §2.2 / §2.3 / §2.4）
# =====================================================================================

ACTION_CORE_FIELDS: Tuple[str, ...] = (
    "id", "name", "kind", "power", "attack_type", "element", "effects",
)
"""ActionCore 共用核心 7 字段（契约 §2.2：F01-F07 逐字段同构、逐约束同源）。"""

ACTION_CORE_DEFAULTS: Dict[str, object] = {
    "kind": "damage",          # F03 自动推断（f1：power>0 且无状态类效果 → damage）
    "power": 100,              # F04 默认 100（契约 L48 滑条 10-500）
    "attack_type": "slash",    # F05 默认按怪物模板/攻击部位（1e 承接；字段缺省值取 slash）
    "element": None,           # F06 默认 null
    "effects": (),             # F07 默认 []（效果引用 + 原子动作双形态，1b 承接）
}
"""ActionCore 缺省兜底表（三铁律②：漏配 = 合理默认不是报错）。"""

ACTION_KIND_VALUES: Tuple[str, ...] = (
    "damage", "heal", "status", "control", "utility",
)
"""kind 五枚举（契约 F03 [L35/L47]）。"""

# 【工程补白 P-3】既有内容包旧值（basic/active 读兼容，摸底 §8-4；新枚举由 6a 内容层收口）
ACTION_KIND_LEGACY_VALUES: Tuple[str, ...] = ("basic", "active")

ATTACK_TYPE_VALUES: Tuple[str, ...] = (
    "slash", "blunt", "pierce", "magic", "none",
)
"""attack_type 五枚举（契约 F05 [L49]）。"""

# 【工程补白 P-4】既有内容包中文旧值（斩/打/突/魔 读兼容，摸底 §8-4）
ATTACK_TYPE_LEGACY_VALUES: Tuple[str, ...] = ("斩", "打", "突", "魔")

ELEMENT_VALUES: Tuple[str, ...] = (
    "earth", "fire", "water", "wind", "thunder", "crystal", "moon", "void",
)
"""8 元素注册表（契约 F06 [数 L220-221]；与 validator._DEFAULT_ELEMENTS 同源镜像）。"""

TARGET_VALUES: Tuple[str, ...] = (
    "enemy_single", "enemy_all", "ally_single", "ally_all", "self", "random_enemy",
)
"""行动级目标 G06 六枚举（契约 §2.4 [细化定型]）。"""

INTENT_VALUES: Tuple[str, ...] = (
    "damage", "defense", "charge", "heal", "control", "buff", "debuff", "mark", "utility",
)
"""意图预告 G03 九枚举（契约 §2.3 [L102]）。"""

PROBABILITY_VALUES: Tuple[int, ...] = (0, 1)
"""入池开关 G02 枚举（契约：0=锚点行动 / 1=参与随机池；必须 ∈ {0,1}）。"""

DEFAULT_TRIGGER_LIMIT: Dict[str, int] = {"per_round": 10, "per_battle": 99}
"""G07 trigger_limit 默认值（契约「同 F20」[L208]：每回合 10 / 每场 99，0=不限）。"""

# 行动库全字段注册表（V-11 判定依据：字段 ∈ 本表 + charge_* 前缀登记键）
# 登记口径：ActionCore 7 + G01-G07 + G08-G16 AI 登记接口 + desc（P-1）+ 读兼容旧键
# （type/cost/cool/apply_status/apply_mark/require_status/skill——field_meta action_fields
#  既有键，6a 契约未禁，宽松登记防误拦既有内容包）
ACTION_FIELD_REGISTRY: Tuple[str, ...] = (
    # ---- ActionCore 7（契约 §2.2）----
    "id", "name", "kind", "power", "attack_type", "element", "effects",
    # ---- 怪物侧扩展 G01-G05 + 目标 G06 + 触发上限 G07（契约 §2.3）----
    "weight", "probability", "intent", "chain", "cooldown",
    "target", "trigger_limit",
    # ---- AI 登记接口 G08-G16（契约 §2.3：登记接口不展开，结构以 1e/1f 为准）----
    "condition", "hungry", "armor", "interrupt", "tags",
    "charge", "preview", "preview_chain", "reveal_condition",
    # ---- 细化定型 F21 desc（P-1）----
    "desc",
    # ---- 读兼容旧键（field_meta action_fields 既有登记，P-3/P-4 同口径）----
    "type", "cost", "cool",
    "require_status", "apply_status", "apply_mark", "skill",
)

ACTION_CHARGE_PREFIX: str = "charge_"
"""charge_* 蓄力字段前缀登记（契约 §2.3「charge_* 前缀」；键名前缀登记，结构 1d 系落地）。"""


# =====================================================================================
# ActionDef dataclass（契约 §2：ActionCore 7 + G01-G07 + AI 登记接口 G08-G16 + desc）
# =====================================================================================


@dataclass(frozen=True)
class ActionDef(BaseDef):
    """action.json 行动条目（6a 契约 §2：ActionCore 共用块 + 怪物侧扩展 + AI 登记接口）。

    与 models.ActionDef 同构：BaseDef 派生（id/name/raw 冗余镜像）+ 防御性访问器
    （类型不符/缺失 → 缺省兜底不报错，三铁律②）。BaseDef.kind 为注册表 kind
    （"action"）；行动条目的 ActionCore `kind` 经 raw.get("kind") 读取。
    """

    # ---- 数值/字符串/列表/映射辅助（与 models.ActionDef 同风格）----
    def _num(self, key: str) -> Optional[float]:
        v = self.raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _int(self, key: str) -> Optional[int]:
        v = self.raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _str_list(self, key: str) -> Tuple[str, ...]:
        v = self.raw.get(key)
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    # ---- ActionCore 7（契约 §2.2：与 skills.json F01-F07 逐字段同构）----
    @property
    def power(self) -> Optional[float]:
        """倍率（F04；缺省兜底 100 由加载侧/引擎取 ACTION_CORE_DEFAULTS）。"""
        return self._num("power")

    @property
    def attack_type(self) -> Optional[str]:
        """攻击类型（F05：slash/blunt/pierce/magic/none；默认按怪物模板/攻击部位，1e 承接）。"""
        return self._str("attack_type")

    @property
    def element(self) -> Optional[str]:
        """元素 ID（F06：∈ 8 元素注册表，V-4 红拦；默认 null）。"""
        return self._str("element")

    @property
    def effects(self) -> Tuple[object, ...]:
        """效果引用列表（F07：effects.json 唯一数据源 + overrides + x_ 例外；双形态）。"""
        v = self.raw.get("effects")
        return tuple(v) if isinstance(v, list) else ()

    # ---- 怪物侧扩展 G01-G05 + 目标 G06 + 触发上限 G07（契约 §2.3）----
    @property
    def weight(self) -> Optional[float]:
        """随机权重（G01：≥0；归一化 = 概率；仅 probability=1 时参与随机池）。"""
        return self._num("weight")

    @property
    def probability(self) -> Optional[float]:
        """入池开关（G02：0=锚点行动 / 1=参与随机池；必须 ∈ {0,1}，V-9 红拦）。"""
        return self._num("probability")

    @property
    def intent(self) -> Optional[str]:
        """意图预告（G03：damage/defense/charge/heal/control/buff/debuff/mark/utility）。"""
        return self._str("intent")

    @property
    def chain(self) -> Tuple[str, ...]:
        """连招（G04：历史写法读兼容；新配置一律走 enemies 顶层 chains 表，1e S2）。"""
        return self._str_list("chain")

    @property
    def cooldown(self) -> Optional[float]:
        """冷却回合（G05：≥0 整数；默认 0）。"""
        return self._num("cooldown")

    @property
    def target(self) -> Optional[str]:
        """行动级目标（G06：enemy_single/enemy_all/ally_single/ally_all/self/random_enemy）。"""
        return self._str("target")

    @property
    def trigger_limit(self) -> Optional[Mapping[str, object]]:
        """触发上限（G07：{per_round, per_battle}，0=不限；缺省同 F20 由引擎兜底）。"""
        return self._mapping("trigger_limit") or None

    # ---- AI 登记接口 G08-G16（契约 §2.3：登记接口不展开，结构/语义以 1e/1f 为准）----
    @property
    def condition(self) -> object:
        """条件权重修正（G08；obj/string 双形态，缺省 None）。"""
        return self.raw.get("condition")

    @property
    def hungry(self) -> Optional[float]:
        """饥饿保底（G09：连续 N 回合未选中则强制选，默认 0=关）。"""
        return self._num("hungry")

    @property
    def armor(self) -> object:
        """霸体免疫打断（G10；true=霸体，效果归口 effects.json）。"""
        return self.raw.get("armor")

    @property
    def interrupt(self) -> object:
        """打断行动标记（G11；T19 interrupt 唯一归口）。"""
        return self.raw.get("interrupt")

    @property
    def tags(self) -> Tuple[str, ...]:
        """行动标签（G12）。"""
        return self._str_list("tags")

    @property
    def charge(self) -> Optional[Mapping[str, object]]:
        """蓄力子对象（G13：charge 键防御性读取；结构以 1d 系细化为准）。"""
        v = self.raw.get("charge")
        return v if isinstance(v, Mapping) else None

    def charge_fields(self) -> Mapping[str, object]:
        """所有 `charge_` 前缀蓄力字段（G14 键名前缀登记；结构待 1d 系落地）。"""
        return {
            k: v
            for k, v in self.raw.items()
            if isinstance(k, str) and k.startswith(ACTION_CHARGE_PREFIX)
        }

    @property
    def preview(self) -> object:
        """意图预告配置（G15；结构以 1d 系/A2 为准）。"""
        return self.raw.get("preview")

    @property
    def preview_chain(self) -> object:
        """连招预告配置（G16a；结构以 1d 系/A2 为准）。"""
        return self.raw.get("preview_chain")

    @property
    def reveal_condition(self) -> object:
        """预告揭示条件（G16b）。"""
        return self.raw.get("reveal_condition")

    # ---- 细化定型 / 读兼容 ----
    @property
    def desc(self) -> Optional[str]:
        """一句话说明（F21 细化定型 P-1；行动卡悬浮提示用）。"""
        return self._str("desc")

    @property
    def type(self) -> Optional[str]:
        """旧键兼容（field_meta action_fields「type 旧键兼容」；6a 契约行动库无 type 字段）。"""
        return self._str("type")

    def ai_fields(self) -> Mapping[str, object]:
        """AI 登记接口全集（G08-G16 键名 → raw 值，供 AI 引擎/编辑器聚合消费）。"""
        return {k: v for k, v in self.raw.items() if k in ACTION_AI_KEYS}


# AI 登记接口键全集（G08-G16，契约 §2.3；charge_* 前缀键单独归 charge_fields）
ACTION_AI_KEYS: Tuple[str, ...] = (
    "condition", "hungry", "armor", "interrupt", "tags",
    "charge", "preview", "preview_chain", "reveal_condition",
)


# =====================================================================================
# 行动库专项校验器（契约 ③：V-4 / V-9 / V-10 / V-11 / V-13）
# =====================================================================================


def _emit(report: object, level: str, field: str, kind: str, **detail: object) -> None:
    """向收集器发一条校验记录（error/warning 两态，三形态收集器兼容）。

    优先级：_Checker._err/_warn（module 首参）→ dict/list 形态（rec 直接 append）→
    鸭子类型 error/warning（带 module 首参）兜底。
    """
    if hasattr(report, "_err") and level == "error":
        report._err("action", field, kind, **detail)
        return
    if hasattr(report, "_warn") and level == "warning":
        report._warn("action", field, kind, **detail)
        return
    if isinstance(report, dict):
        rec = {"field": field, "kind": kind, "level": level, **detail}
        bucket = report.setdefault("errors" if level == "error" else "warnings", [])
        bucket.append(rec)
        return
    if isinstance(report, list):
        rec = {"field": field, "kind": kind, "level": level, **detail}
        report.append(rec)
        return
    if hasattr(report, "error") and level == "error":
        report.error("action", field, kind, **detail)
        return
    if hasattr(report, "warning") and level == "warning":
        report.warning("action", field, kind, **detail)
        return
    rec = {"field": field, "kind": kind, "level": level, **detail}
    if isinstance(report, Mapping):
        bucket = report.setdefault("errors" if level == "error" else "warnings", [])  # type: ignore[attr-defined]
        bucket.append(rec)


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", field, kind, **detail)


def _check_entry(report: object, entry: object, idx: int, seen_ids: Set[str]) -> None:
    """单条行动条目校验（V-10/V-13 基础门禁 + V-9 概率语义 + V-4 元素 + V-11 未登记字段）。"""
    base = f"[{idx}]"
    if not isinstance(entry, Mapping):
        _err(report, base, "R-5", rule="action_not_object",
             node_id=str(idx), got=type(entry).__name__,
             msg="action.json 每条行动需对象")
        return

    # ---- V-11 未登记字段拒绝（红拦；防 schema 漂移，契约 [L243]）----
    # 注意：dict 收集器形态下 _err 直接 append rec（不走 _Checker），
    # 而 _err/_warn 的 hasattr 分支以鸭子类型优先——_Report.error 双形态兼容。
    unknown = sorted(
        k for k in entry.keys()
        if isinstance(k, str)
        and k not in ACTION_FIELD_REGISTRY
        and not k.startswith(ACTION_CHARGE_PREFIX)
    )
    for k in unknown:
        _err(report, f"{base}.{k}", "R-5", rule="unregistered_field",
             node_id=str(idx), unknown_field=k, registry=sorted(ACTION_FIELD_REGISTRY),
             msg="未登记字段：%r（V-11：新增字段先登记 ActionCore 元数据单点）" % (k,))

    # ---- V-10 库内 ID 唯一（红拦，契约 [L210]）----
    aid = entry.get("id")
    if not isinstance(aid, str) or not aid:
        _err(report, f"{base}.id", "R-1", rule="action_id_invalid",
             node_id=str(idx), id=aid, msg="行动 id 需非空字符串（V-13 基础门禁）")
        return
    if aid in seen_ids:
        _err(report, f"{base}.id", "R-1", rule="action_id_duplicate",
             node_id=aid, msg="行动 id %r 重复（V-10 库内唯一）" % (aid,))
    seen_ids.add(aid)

    # ---- V-13 基础门禁：name 非空 ----
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        _err(report, f"{base}.name", "R-1", rule="action_name_invalid",
             node_id=aid, name=name, msg="行动 name 需非空字符串（V-13 基础门禁）")

    # ---- V-13 基础门禁：kind 五枚举（P-3：basic/active 旧值读兼容放行）----
    kind = entry.get("kind")
    if kind is not None and not isinstance(kind, str):
        _err(report, f"{base}.kind", "R-1", rule="kind_type_invalid",
             node_id=aid, value=kind, msg="行动 kind 需字符串")
    elif kind not in (None, *ACTION_KIND_VALUES, *ACTION_KIND_LEGACY_VALUES):
        _err(report, f"{base}.kind", "R-5", rule="kind_enum_invalid",
             node_id=aid, value=kind, allowed=list(ACTION_KIND_VALUES),
             msg="行动 kind %r 不在五枚举（damage/heal/status/control/utility）（V-13）" % (kind,))

    # ---- V-13 基础门禁：attack_type 五枚举（P-4：中文旧值读兼容放行）----
    at = entry.get("attack_type")
    if at is not None and not isinstance(at, str):
        _err(report, f"{base}.attack_type", "R-1", rule="attack_type_type_invalid",
             node_id=aid, attack_type=at, msg="行动 attack_type 需字符串")
    elif at not in (None, *ATTACK_TYPE_VALUES, *ATTACK_TYPE_LEGACY_VALUES):
        _err(report, f"{base}.attack_type", "R-5", rule="attack_type_enum_invalid",
             node_id=aid, attack_type=at, allowed=list(ATTACK_TYPE_VALUES),
             msg="行动 attack_type %r 不在五枚举（slash/blunt/pierce/magic/none）（V-13）" % (at,))

    # ---- V-13 基础门禁：power 数值域（≥0，类型校验）----
    power = entry.get("power")
    if power is not None and (not isinstance(power, (int, float)) or isinstance(power, bool)):
        _err(report, f"{base}.power", "R-1", rule="power_type_invalid",
             node_id=aid, power=power, msg="行动 power 需数值（缺省 100）")
    elif isinstance(power, (int, float)) and not isinstance(power, bool) and power < 0:
        _err(report, f"{base}.power", "R-2", rule="power_negative",
             node_id=aid, power=power, msg="行动 power 不能为负数（V-13 数值域）")

    # ---- V-13 基础门禁：cooldown 非负 ----
    cd = entry.get("cooldown")
    if cd is not None and (not isinstance(cd, (int, float)) or isinstance(cd, bool)):
        _err(report, f"{base}.cooldown", "R-1", rule="cooldown_type_invalid",
             node_id=aid, cooldown=cd, msg="行动 cooldown 需数值（缺省 0）")
    elif isinstance(cd, (int, float)) and not isinstance(cd, bool) and cd < 0:
        _err(report, f"{base}.cooldown", "R-2", rule="cooldown_negative",
             node_id=aid, cooldown=cd, msg="行动 cooldown 不能为负数（V-13 数值域）")

    # ---- V-4 元素 ∈ 注册表（红拦，契约 [L204] / [数 L220-221]）----
    element = entry.get("element")
    if element is not None:
        if not isinstance(element, str):
            _err(report, f"{base}.element", "R-1", rule="element_type_invalid",
                 node_id=aid, element=element, msg="行动 element 需字符串或 null")
        elif element not in ELEMENT_VALUES:
            _err(report, f"{base}.element", "R-5", rule="element_not_registered",
                 node_id=aid, element=element, allowed=list(ELEMENT_VALUES),
                 msg="行动 element %r 不在 8 元素注册表（V-4）" % (element,))

    # ---- G06 target 六枚举（V-13 基础门禁）----
    target = entry.get("target")
    if target is not None:
        if not isinstance(target, str):
            _err(report, f"{base}.target", "R-1", rule="target_type_invalid",
                 node_id=aid, target=target, msg="行动 target 需字符串")
        elif target not in TARGET_VALUES:
            _err(report, f"{base}.target", "R-5", rule="target_enum_invalid",
                 node_id=aid, target=target, allowed=list(TARGET_VALUES),
                 msg=(
                     "行动 target %r 不在六枚举"
                     "（enemy_single/enemy_all/ally_single/ally_all/self/"
                     "random_enemy）（G06）" % (target,)
                 ))

    # ---- V-9 概率语义：probability ∈ {0,1}（红拦，契约 [L101/L112/L209]）----
    prob = entry.get("probability")
    if prob is not None and (not isinstance(prob, (int, float)) or isinstance(prob, bool)):
        _err(report, f"{base}.probability", "R-1", rule="probability_type_invalid",
             node_id=aid, probability=prob, msg="行动 probability 需数值（0=锚点 / 1=入池）")
    elif isinstance(prob, (int, float)) and not isinstance(prob, bool) and prob not in (0, 1):
        # P-8 读兼容：既有内容包（test_demo/legal）probability 用 0.5 表达入池权重（旧语义，
        # 摸底 §8-4 枚举不一致）——非 0/1 正值按「等价 1 入池」放行（与 models.ActionDef
        # probability 文档「其他正值等价 1」口径一致），仅 0/1 之外的非正值红拦。
        if prob < 0:
            _err(report, f"{base}.probability", "R-5", rule="probability_not_01",
                 node_id=aid, probability=prob, allowed=[0, 1],
                 msg="行动 probability %r 必须 ∈ {0,1}（V-9：0=锚点行动 / 1=参与随机池）" % (prob,))

    # ---- V-9 纯脚本怪提示（黄提示不拦截，契约 [L209]）----
    weight = entry.get("weight")
    has_weight = isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight > 0
    has_chain = isinstance(entry.get("chain"), list) and bool(entry["chain"])
    has_condition = entry.get("condition") is not None
    if not has_weight and not has_chain and not has_condition:
        _warn(report, f"{base}.weight", "V-9", rule="pure_script_monster",
              node_id=aid, weight=weight,
             chain=entry.get("chain"), condition=entry.get("condition"),
              msg="weight 全 0 且无 chain/condition → 纯脚本怪？（V-9 黄提示不拦截）")

    # ---- weight 数值域（V-13：≥0）----
    if isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight < 0:
        _err(report, f"{base}.weight", "R-2", rule="weight_negative",
             node_id=aid, weight=weight, msg="行动 weight 不能为负数（V-13 数值域）")


def validate_actions(modules: Mapping[str, object], report: object) -> None:
    """行动库专项校验主入口（契约 ③：V-4/V-9/V-10/V-11/V-13；loader/validator 专项路由调用）。

    入参:
      modules: 全量内容模块（action 键为行动条目数组；缺失 → 跳过，对齐既有校验器
               「模块未接线默认放行」惯例）。
      report:  收集器（_err/_warn 三形态兼容：_Checker / dict {"errors":[]} / list）。
    出参: 无（红拦/黄提示全部经 report 收集，红拦由 loader 聚合拒绝加载）。
    """
    data = modules.get("action")
    if data is None:
        return
    if not isinstance(data, list):
        _err(report, "action", "R-5", rule="action_not_list",
             node_id=None, got=type(data).__name__,
             msg="action.json 需顶层数组（每条行动一个对象，契约 §2.1）")
        return
    seen_ids: Set[str] = set()
    for i, entry in enumerate(data):
        _check_entry(report, entry, i, seen_ids)


# =====================================================================================
# ActionCore 元数据单点（V-11 判定依据；供 field_meta 登记与编辑器注册表消费）
# =====================================================================================


def action_core_meta() -> Dict[str, FieldMeta]:
    """ActionCore 共用块字段元数据（F01-F07，契约 §2.2）。

    skills.json 与 action.json 共用同一份定义（元数据单点 [L243]）；由主 agent
    收口接线 field_meta（schema 之家单向持有模式，防循环 import）。
    """
    return {
        "id": FieldMeta(type="str", required=True),
        "name": FieldMeta(type="str"),
        "kind": FieldMeta(type="enum", enum=ACTION_KIND_VALUES, default="damage"),
        "power": FieldMeta(type="number", range_min=0, range_max=500, default=100),
        "attack_type": FieldMeta(type="str"),  # 枚举判定（P-4：含中文旧值）由专项校验器全权
        "element": FieldMeta(type="str"),      # 8 元素注册表引用检查（V-4）由专项校验器全权
        "effects": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="effect")),
    }


def skill_action_meta() -> ModuleMeta:
    """行动库模块元数据工厂（供主 agent 收口接线 field_meta 模块表）。

    字段口径 = ActionCore 7 + G01-G07 + AI 登记接口 G08-G16 + desc + 读兼容旧键；
    深结构校验（V-4/V-9/V-10/V-11/V-13）由 validate_actions 专项全权（对齐
    quest/npc/achievements 专项全权口径：fields 宽松登记防泛型误拦）。
    """
    fields: Dict[str, FieldMeta] = {
        # ---- ActionCore 7（契约 §2.2）----
        "id": FieldMeta(type="str", required=True),
        "name": FieldMeta(type="str"),
        "kind": FieldMeta(type="str"),  # 五枚举 + 旧值兼容判定由专项校验器全权
        "power": FieldMeta(type="number", range_min=0, range_max=500, default=100),
        "attack_type": FieldMeta(type="str"),
        "element": FieldMeta(type="str"),
        "effects": FieldMeta(type="list", element=FieldMeta(type="ref", ref_target="effect")),
        # ---- G01-G07（契约 §2.3 / §2.4）----
        "weight": FieldMeta(type="number", range_min=0, range_max=100, default=0),
        "probability": FieldMeta(type="number", range_min=0, range_max=1, default=0),
        "intent": FieldMeta(type="str"),
        "chain": FieldMeta(type="list", element=FieldMeta(type="str")),
        "cooldown": FieldMeta(type="number", range_min=0, range_max=999, default=0),
        "target": FieldMeta(type="enum", enum=TARGET_VALUES, default="enemy_single"),
        "trigger_limit": FieldMeta(type="obj", children={
            "per_round": FieldMeta(type="int", range_min=0, default=10),
            "per_battle": FieldMeta(type="int", range_min=0, default=99),
        }),
        # ---- AI 登记接口 G08-G16（登记接口不展开，结构以 1e/1f 为准）----
        "condition": FieldMeta(type="obj"),  # obj/string 双形态（1e A03b）宽松登记
        "hungry": FieldMeta(type="number", range_min=0, range_max=999, default=0),
        "armor": FieldMeta(type="bool"),
        "interrupt": FieldMeta(type="bool"),
        "tags": FieldMeta(type="list", element=FieldMeta(type="str")),
        "preview": FieldMeta(type="obj"),
        "preview_chain": FieldMeta(type="obj"),
        "reveal_condition": FieldMeta(type="str"),
        # ---- 细化定型 F21 desc（P-1）----
        "desc": FieldMeta(type="str"),
        # ---- 读兼容旧键（field_meta action_fields 既有登记）----
        "type": FieldMeta(type="str"),
        "cost": FieldMeta(type="number", range_min=0, range_max=9999),
        "cool": FieldMeta(type="number", range_min=0, range_max=9999),
        "require_status": FieldMeta(type="ref", ref_target="status"),
        "apply_status": FieldMeta(type="ref", ref_target="status"),
        "apply_mark": FieldMeta(type="ref", ref_target="mark"),
        "skill": FieldMeta(type="ref", ref_target="skill_or_any"),
    }
    return ModuleMeta(
        entry_type="list",
        fields=fields,
        kind="action",
        namespace="action_lib",
    )


__all__ = [
    "ACTION_CORE_FIELDS",
    "ACTION_CORE_DEFAULTS",
    "ACTION_KIND_VALUES",
    "ATTACK_TYPE_VALUES",
    "ELEMENT_VALUES",
    "TARGET_VALUES",
    "INTENT_VALUES",
    "PROBABILITY_VALUES",
    "DEFAULT_TRIGGER_LIMIT",
    "ACTION_FIELD_REGISTRY",
    "ACTION_CHARGE_PREFIX",
    "ACTION_AI_KEYS",
    "ActionDef",
    "validate_actions",
    "action_core_meta",
    "skill_action_meta",
]
