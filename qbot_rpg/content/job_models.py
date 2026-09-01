"""M13 职业库数据层 · 独立模块（批4 路4A）：jobs.json 数据模型 JobDef 顶层 + growth。

文件名：job_models.py
创建时间：2026-09-02
作者：Hermes 子agent-4A（M13 职业库实现组批4路4A：并发同仓，仅新建本文件 +
tests/unit/test_job_models.py；transform 段字段注册位留 4B 追加）

功能描述：
  - JobDef frozen dataclass（继承 BaseDef 承载 id+name 冗余镜像 raw；ID/名称
    冗余铁律9 同 skill_models/forge_models 先例）：顶层 11 字段访问器
    （#1~#11）+ growth 9 子字段（#12~#20），全部默认值兜底——漏配 = 合理默认
    不是报错（三铁律②，细化_6b §1 字段表：仅 id/name/difficulty/playstyle/
    recommended_newbie/resource_axes/growth 必填，缺省兜底不报错）。
  - GrowthDef frozen dataclass（growth 9 子字段：str/int/con/spr/foc/agi/lck/
    hp/mp，缺省 0——细化_6b §1.2 字段表「缺省 0」；狂战士示例仅配 6 项）。
  - jobs_fields() 返回顶层 11 + growth 9 的 FieldMeta 注册表（transform/
    state_policy/技能挂点/链挂点字段注册位留路4B 追加，本文件以注释标明），
    供主 agent 收口接线 field_meta（jobs 模块登记/校验器专项 V1~V8），本文件
    自身零登记、零 import 兄弟模块。

依据：
  - docs/细化/细化_6b_职业库与变换引擎.md（409 行 v1.0）：
    §1.1 顶层字段表（#1~#11：id/name/difficulty/playstyle/recommended_newbie/
    resource_axes/mechanic_tags/weapon_types/growth/transform/description，
    逐字段类型/必填/语义/引用行号）；
    §1.2 growth 子对象（#12~#20：str/int/con/spr/foc/agi/lck/hp/mp 九属性
    职业成长率，缺省 0；默认四职业成长率锚点 路3 B5 L103）；
    §1.3~§1.6（transform 段 11 + state_policy 3 + 技能挂点 4 + 链挂点 1 =
    39 配置字段，字段计数核对 L134——其中 transform 段归批4路4B，本文件只
    留注册位）。
  - docs/m13_6b摸底.md（缺口：39 配置字段零登记；已就绪：4f 注册契约
    resolve_job/default_job——default_job 兜底链消费 recommended_newbie）。
  - 模式参考：qbot_rpg/content/skill_models.py（SkillDef dataclass +
    skills_fields() 登记表模式）、qbot_rpg/content/models.py（BaseDef/FieldMeta/
    ModuleMeta）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  1. growth 九属性键口径 = 3b 玩家属性九预置键（hp/mp/str/int/con/spr/foc/
     agi/lck，player_attributes 九键 / levelup attr_registry 同源）：细化_6b
     §1.2 字段表以 str/int/con/spr/foc/agi/lck/hp/mp 九键表述（怪物 stats 九键
     luk 拼写仅用于怪物侧），本层按玩家侧九键实现（默认四职业锚点 路3 B5
     L103 的 str/con/int/spr/lck/agi/hp 均在键空间内）；GrowthDef 提供
     growth_map() 返回 {属性键: 数值} 映射供 levelup growth 注入直用
     （levelup.py L59-76 growth map 消费形态）。
  2. growth 仅接受纯数值（int/float，拒绝 bool），非数值/缺省 → 0.0 兜底
     （§1.2「缺省 0」；负值不在此层拦截，范围校验归批4 校验器专项）。
  3. 顶层 11 枚举：difficulty ∈ {simple, advanced, complex}（§1.1 #3 软标注，
     校验器只 warning 不拦截——本层只兜底不判定，值域校验归校验器专项）；
     playstyle ≤20 字为展示约束（#4），本层只读不判长。
  4. recommended_newbie 默认 False（#5 必填但缺省兜底 False——4f B7/REG-04
     缺省职业链消费该标记）；name 由 BaseDef.from_entry 兜底为 id（先例同
     skill_models）。
  5. transform 段访问器：本层仅结构呈现（transform_obj() 防御性读取，缺省
     None=无形态切换职业，§1.1 #10「缺省=无形态切换职业」）；transform 段
     11 字段（#21~#31）与 state_policy 3 字段（#32~#34）的访问器与 FieldMeta
     注册位由批4路4B 在 jobs_fields() 的 transform 键 children 内追加，
     本文件以 `# 4B:` 注释标明注册位（并发同仓纪律，不写兄弟路文件）。
  6. jobs_fields() 的 growth 键注册为 FieldMeta(type="obj",
     children=GROWTH_CHILDREN)（obj 子字段登记先例：field_meta enemies
     ENEMY_STATS_CHILDREN）；transform 键暂注册 FieldMeta(type="obj",
     soft_label=True) 占位（无 children，字段计数不含 4B 段），4B 追加 children。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；
纯函数；确定性；零定时器/零睡眠（不引入实时计时调用）；不引入随机；
不 git commit。仅依赖 qbot_rpg.content.models（BaseDef/FieldMeta）与标准库。
"""
from __future__ import annotations

import builtins
import copy
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

from qbot_rpg.content.models import BaseDef, FieldMeta

# =====================================================================================
# 常量 / 枚举注册表（细化_6b §1.1 字段表逐字段枚举 + §1.2 growth 九属性）
# =====================================================================================

# #3 三档难度（§1.1 #3：simple/advanced/complex；软标注——校验器只 warning
# 不拦截，本层只兜底不判定）
JOB_DIFFICULTIES: Tuple[str, ...] = ("simple", "advanced", "complex")

# growth 九属性键（§1.2 #12~#20：str/int/con/spr/foc/agi/lck/hp/mp 九属性职业
# 成长率；键口径 = 3b 玩家属性九预置键 hp/mp/str/int/con/spr/foc/agi/lck，
# 补白 1）
GROWTH_KEYS: Tuple[str, ...] = ("str", "int", "con", "spr", "foc", "agi", "lck", "hp", "mp")

# 顶层字段 #5 recommended_newbie 缺省（§1.1 #5 必填但缺省兜底 False——4f B7/
# REG-04 缺省职业链消费该标记，补白 4）
DEFAULT_RECOMMENDED_NEWBIE: bool = False

# growth 子字段 #12~#20 缺省（§1.2：缺省 0；狂战士示例仅配 6 项）
DEFAULT_GROWTH: float = 0.0

# 顶层字段 #3 difficulty 缺省（§1.1 #3 必填但缺省兜底 simple——软标注字段，
# 展示缺省最保守档）
DEFAULT_DIFFICULTY: str = "simple"

# 顶层字段 #4 playstyle / #6 resource_axes 缺省（#4 必填但缺省兜底空串展示
# 安全；#6 必填但缺省空元组 = 无资源轴职业）
DEFAULT_PLAYSTYLE: str = ""
DEFAULT_RESOURCE_AXES: Tuple[str, ...] = ()


# =====================================================================================
# GrowthDef（growth 9 子字段，§1.2 #12~#20）
# =====================================================================================


@dataclass(frozen=True)
class GrowthDef:
    """jobs.json growth 子对象（细化_6b §1.2 #12~#20 九属性职业成长率）。

    纯结构访问器：九键各自访问器（str/int/con/spr/foc/agi/lck/hp/mp）缺省
    0.0（§1.2「缺省 0」）；growth_map() 返回 {属性键: 数值} 映射供 levelup
    growth 注入直用（levelup.py L59-76 消费形态，补白 1）。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    def _growth(self, key: str) -> float:
        v = self.raw.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        return DEFAULT_GROWTH

    # ---- 九属性访问器（#12~#20；缺省 0.0）----

    @property
    def str(self) -> float:  # noqa: A003  # 属性名对齐契约字段名 str
        """#12 力量成长率（缺省 0.0）。"""
        return self._growth("str")

    @property
    def int(self) -> float:  # noqa: A003  # 属性名对齐契约字段名 int
        """#13 智力成长率（缺省 0.0）。"""
        return self._growth("int")

    @property
    def con(self) -> float:
        """#14 体质成长率（缺省 0.0）。"""
        return self._growth("con")

    @property
    def spr(self) -> float:
        """#15 精神成长率（缺省 0.0）。"""
        return self._growth("spr")

    @property
    def foc(self) -> float:
        """#16 专注成长率（缺省 0.0）。"""
        return self._growth("foc")

    @property
    def agi(self) -> float:
        """#17 敏捷成长率（缺省 0.0）。"""
        return self._growth("agi")

    @property
    def lck(self) -> float:
        """#18 幸运成长率（缺省 0.0）。"""
        return self._growth("lck")

    @property
    def hp(self) -> float:
        """#19 生命成长率（缺省 0.0）。"""
        return self._growth("hp")

    @property
    def mp(self) -> float:
        """#20 魔力成长率（缺省 0.0）。"""
        return self._growth("mp")

    def growth_map(self) -> Dict[builtins.str, float]:
        """九属性成长率映射 {属性键: 数值}（供 levelup growth 注入直用）。

        仅含 raw 中实际出现的纯数值键（缺省键不注入，消费侧按 0 处理，
        对齐 levelup.py「无成长 → 白值重算按 0 处理」口径）。
        """
        out: Dict[builtins.str, float] = {}
        for key in GROWTH_KEYS:
            if key in self.raw:
                out[key] = self._growth(key)
        return out

    def as_mapping(self) -> Mapping[builtins.str, float]:
        """九属性全量映射（含缺省 0.0 键，供展示/快照消费）。"""
        return {key: self._growth(key) for key in GROWTH_KEYS}


# =====================================================================================
# JobDef（ID/名称冗余铁律9：继承 BaseDef 冗余镜像 raw；顶层 11 + growth 9 访问器）
# =====================================================================================


@dataclass(frozen=True)
class JobDef(BaseDef):
    """jobs.json 一条职业（细化_6b §1.1 顶层 11 + §1.2 growth 9）。

    id/name 由 BaseDef 承载（from_entry 冗余镜像 raw）；kind 属性为注册表
    kind（"job"）。全部字段默认值兜底（三铁律②：漏配 = 合理默认不是报错）：
    仅 id/name/difficulty/playstyle/recommended_newbie/resource_axes/growth
    为契约必填（§1.1 字段表），漏配按合理默认兜底（补白 3/4）。
    transform 段（§1.1 #10）本层仅结构呈现，11 字段访问器归批4路4B。
    """

    # ---- 数值/字符串/布尔/列表辅助（与 SkillDef/EnemyDef 同风格）----

    def _num(self, key: str) -> Optional[float]:
        v = self.raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

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

    # ================= 顶层字段（#1~#11，§1.1） =================

    @property
    def difficulty(self) -> str:
        """#3 三档难度（simple/advanced/complex；缺省 simple，软标注只读不判）。"""
        v = self._str("difficulty")
        return v if v else DEFAULT_DIFFICULTY

    @property
    def playstyle(self) -> str:
        """#4 玩法一句话（≤20 字展示约束；缺省空串展示安全）。"""
        v = self._str("playstyle")
        return v if v is not None else DEFAULT_PLAYSTYLE

    @property
    def recommended_newbie(self) -> bool:
        """#5 推荐新手？/ 注册缺省职业取推荐标记（4f B7/REG-04 兜底链消费；缺省 False）。"""
        v = self._bool("recommended_newbie")
        return v if v is not None else DEFAULT_RECOMMENDED_NEWBIE

    @property
    def resource_axes(self) -> Tuple[str, ...]:
        """#6 资源轴列表（mp/combo/mark/rage 等；stats.json 注册表引用校验归校验器专项）。"""
        return self._str_list("resource_axes")

    @property
    def mechanic_tags(self) -> Tuple[str, ...]:
        """#7 机制标签（展示/筛选用软标注；缺省空元组）。"""
        return self._str_list("mechanic_tags")

    @property
    def weapon_types(self) -> Tuple[str, ...]:
        """#8 职业可用武器类型（联动 4b 穿戴校验 weapon_types×slot；缺省空=不限）。"""
        return self._str_list("weapon_types")

    @property
    def growth(self) -> GrowthDef:
        """#9 职业成长率对象（GrowthDef；缺省空对象 = 全 0 成长率，§1.2「缺省 0」）。"""
        return GrowthDef(raw=self._mapping("growth"))

    # transform 段（#10）：本层仅结构呈现，11 字段访问器（#21~#31）与
    # state_policy 3 字段（#32~#34）由批4路4B 在本文件追加。
    def transform_obj(self) -> Optional[Mapping[str, object]]:
        """#10 transform 段（形态切换引擎配置）；缺省 None=无形态切换职业（§1.1 #10）。

        结构呈现占位（补白 5）：transform 段 11 字段访问器归批4路4B；
        4B 完成后此方法由 4B 的 transform_obj() 访问器取代或保留双轨。
        """
        v = self.raw.get("transform")
        return v if isinstance(v, Mapping) else None

    @property
    def description(self) -> Optional[str]:
        """#11 职业介绍文案（选职业界面模板化文案，随 3d 注册表渲染；缺省 None）。"""
        return self._str("description")


# =====================================================================================
# jobs_fields：顶层 11 + growth 9 字段 FieldMeta 注册表（细化_6b §1.1/§1.2）
# =====================================================================================
# 供主 agent 收口接线 field_meta（jobs 模块登记 / 校验器专项 V1~V8 / 未登记
# 字段拒绝依据）。本文件零登记、零 import 兄弟模块（并发同仓纪律）。
# transform 段（#21~#31）+ state_policy（#32~#34）字段注册位由批4路4B 在
# "transform" 键 children 内追加；技能挂点（#35~#38）/ 链挂点（#39）分别
# 登记于 skills/skill_chains 模块（随 6a 收口）。


def jobs_fields() -> Dict[str, FieldMeta]:
    """jobs.json 条目 顶层 11 + growth 9 字段 FieldMeta 注册表（细化_6b §1.1/§1.2）。

    契约必填 7 键（id/name/difficulty/playstyle/recommended_newbie/
    resource_axes/growth）中 id 设 required=True，其余按「缺省兜底不报错」
    口径不设 required（补白 3/4，对齐 skills_fields 先例：仅 id required）。
    transform 键暂注册 obj 占位（soft_label 不拦截），children 由路4B 追加。
    """
    return {
        # ---- 顶层 11（§1.1 #1~#11）----
        "id": FieldMeta(type="str", required=True),
        "name": FieldMeta(type="str"),
        "difficulty": FieldMeta(
            type="enum", enum=JOB_DIFFICULTIES, default=DEFAULT_DIFFICULTY
        ),
        "playstyle": FieldMeta(type="str", default=DEFAULT_PLAYSTYLE),
        "recommended_newbie": FieldMeta(type="bool", default=DEFAULT_RECOMMENDED_NEWBIE),
        "resource_axes": FieldMeta(
            type="list", element=FieldMeta(type="str")
        ),  # stats.json 注册表引用校验归校验器专项
        "mechanic_tags": FieldMeta(type="list", element=FieldMeta(type="str")),
        "weapon_types": FieldMeta(
            type="list", element=FieldMeta(type="str")
        ),  # 联动 4b 穿戴校验 weapon_types×slot
        "growth": FieldMeta(type="obj", children=GROWTH_CHILDREN),
        # transform 段注册位（§1.1 #10）：11 字段 #21~#31 + state_policy 3
        # 字段 #32~#34 已由批4路4B 合写追加 children（TRANSFORM_CHILDREN 经
        # _job_transform_children() 惰性挂载，见文末 4B 落点小节）；
        # soft_label 保留——transform 缺省 = 无形态切换职业，合法不拦截
        "transform": FieldMeta(type="obj", soft_label=True, children=TRANSFORM_CHILDREN),
        "description": FieldMeta(type="str"),
    }


# growth 子字段（§1.2 #12~#20：九属性职业成长率，缺省 0；obj 子字段登记先例
# field_meta ENEMY_STATS_CHILDREN）
GROWTH_CHILDREN: Mapping[str, FieldMeta] = {
    "str": FieldMeta(type="number", range_min=0, default=DEFAULT_GROWTH),
    "int": FieldMeta(type="number", range_min=0, default=DEFAULT_GROWTH),
    "con": FieldMeta(type="number", range_min=0, default=DEFAULT_GROWTH),
    "spr": FieldMeta(type="number", range_min=0, default=DEFAULT_GROWTH),
    "foc": FieldMeta(type="number", range_min=0, default=DEFAULT_GROWTH),
    "agi": FieldMeta(type="number", range_min=0, default=DEFAULT_GROWTH),
    "lck": FieldMeta(type="number", range_min=0, default=DEFAULT_GROWTH),
    "hp": FieldMeta(type="number", range_min=0, default=DEFAULT_GROWTH),
    "mp": FieldMeta(type="number", range_min=0, default=DEFAULT_GROWTH),
}


def _transform_children() -> Mapping[str, FieldMeta]:
    """transform 段 11 字段 children（细化_6b §1.3 #21~#31）。

    与 transform_fields() 同源：函数体在调用期经 globals() 取同名函数
    （jobs_fields() 于模块导入期构造，此时 transform_fields() 尚未定义，
    直接引用会 NameError；模块导入完成后 globals() 可取到，无循环 import）。
    """
    fn = globals().get("transform_fields")
    out = fn() if callable(fn) else {}
    return out if isinstance(out, Mapping) else {}


def _state_policy_children() -> Mapping[str, FieldMeta]:
    """state_policy 3 字段 children（细化_6b §1.4 #32~#34，与 state_policy_fields() 同源）。"""
    fn = globals().get("state_policy_fields")
    out = fn() if callable(fn) else {}
    return out if isinstance(out, Mapping) else {}


def _job_transform_children() -> Mapping[str, FieldMeta]:
    """jobs_fields()['transform'] 的 children 挂载（4B 追加位落点）。"""
    return dict(_transform_children())


# 4B 追加位：transform 段 children（#21~#31）+ state_policy 3 字段（#32~#34）
# 由批4路4B 定义 TRANSFORM_CHILDREN / STATE_POLICY_CHILDREN 并挂入
# jobs_fields()["transform"].children；技能挂点（#35~#38）/ 链挂点（#39）
# 随 6a 登记于 skills/skill_chains 模块（本文件不登记）。


# =====================================================================================
# 【批4 路4B 落点】transform 段数据模型（细化_6b §1.3 #21~#31 + §1.4 #32~#34）
# =====================================================================================
# 路4B 于 2026-09-02 落盘：TransformDef / StatePolicyDef / transform_fields() /
# state_policy_fields() 定义于本文件末尾（见文末同名小节）。本文件 = 路4A 顶层
# schema（JobDef/GrowthDef/jobs_fields）+ 路4B transform 段 schema 合写产物。
# transform 键 children 经 _transform_children()（globals 惰性解析）挂载，
# TRANSFORM_CHILDREN / STATE_POLICY_CHILDREN 常量在文末 transform_fields()
# 定义之后赋值（模块导入期安全，见文末）。


# =====================================================================================
# JobDef.from_entry 工厂（BaseDef.from_entry 兜底 name；kind 注入）
# =====================================================================================


def job_from_entry(entry: Mapping[str, object]) -> JobDef:
    """从 jobs.json 配置条目构造 JobDef（kind="job" 注入，供 registry/loader 收口）。

    BaseDef.from_entry 已兜底 id/name（name 缺省 = id，先例同 SkillDef）；
    本工厂经 object.__new__ + fields 显式构造并注入注册表 kind，避免调用方
    每次 cast（frozen dataclass 构造路径：BaseDef 四个字段全量显式）。
    """
    raw = dict(entry)
    eid = str(entry.get("id", ""))
    name = str(entry.get("name", "") or eid)
    return JobDef(id=eid, name=name, raw=raw, kind="job")


# =====================================================================================
# 【批4 路4B 落点 · 实现区】transform 段数据模型（细化_6b §1.3 #21~#31 + §1.4 #32~#34）
# =====================================================================================
# 路4B 于 2026-09-02 落盘：TransformDef / StatePolicyDef / transform_fields() /
# state_policy_fields() 定义于此（本文件末尾，jobs_fields() 之后——模块导入期
# jobs_fields() 构造时经 _transform_children()（globals 惰性解析）取本区函数，
# 导入完成后 TRANSFORM_CHILDREN / STATE_POLICY_CHILDREN 常量在此赋值，安全）。

# ---------------------------------------------------------------------------
# 常量 / 枚举注册表（细化_6b §1.3 / §1.4 字段表逐字段枚举与默认值）
# ---------------------------------------------------------------------------

# #23 duration 两枚举（§1.3 #23：turns=回合制持续（配 turns）/ battle=整场不还原）
TRANSFORM_DURATION_VALUES: Tuple[str, ...] = ("turns", "battle")

# #32~#34 state_policy 三键枚举值域（§1.4 注：值域收敛为 {clear, keep} 二值，
# 不放行自定义策略值——V5 红拦依据）
STATE_POLICY_VALUES: Tuple[str, ...] = ("clear", "keep")

# #21 触发技能 ID 缺省（§1.3 #21 必填；空串 = 未配置，V2 归属校验归专项）
DEFAULT_TRANSFORM_SKILL: str = ""

# #22 变换目标形态 ID 缺省（§1.3 #22 必填；空串 = 未配置，V1 存在性校验归专项）
DEFAULT_TRANSFORM_TO: str = ""

# #23 duration 缺省（§1.3 #23 必填无默认值；兜底 turns = 定稿主示例语义，P-1）
DEFAULT_DURATION: str = "turns"

# #24 turns 缺省（§1.3 #24 条件必填 >0；0 = 未配置哨兵，强制归校验器/引擎，P-2）
DEFAULT_TURNS: int = 0

# #25 revert 缺省（§1.3 #25 必填无默认值；bool 兜底 false，battle+true 红拦 V4）
DEFAULT_REVERT: bool = False

# #26 cooldown 缺省（§1.3 #26 明文「默认 5」；从「触发」起算，P-3）
DEFAULT_COOLDOWN: int = 5

# #27 dispel_reverts 缺省（§1.3 #27：默认 true = 形态被驱散→触发还原钩子）
DEFAULT_DISPEL_REVERTS: bool = True

# #32 combo 缺省（§1.4 #32：clear=清连段+清活跃链 / keep=保留；默认 clear）
DEFAULT_STATE_POLICY_COMBO: str = "clear"

# #33 marks 缺省（§1.4 #33：keep=保留（狂战士默认示例）/ clear=清印记；默认 keep）
DEFAULT_STATE_POLICY_MARKS: str = "keep"

# #34 buff 缺省（§1.4 #34：keep=战嚎减伤/药剂临时层跨形态保留 / clear=全清；默认 keep）
DEFAULT_STATE_POLICY_BUFF: str = "keep"

# #29 形态技能组 ID 缺省（§1.3 #29 必填；空串 = 未配置，V8 完整性校验归专项）
DEFAULT_SKILL_SET: str = ""


# ---------------------------------------------------------------------------
# StatePolicyDef（细化_6b §1.4 #32~#34：state_policy 子对象 3 字段）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatePolicyDef:
    """state_policy 子对象（细化_6b §1.4 #32~#34：combo/marks/buff 三键）。

    变换/还原瞬间的资源处理策略（连段/印记/buff 三键 clear|keep）；枚举值域收敛
    {clear, keep} 二值（V5 红拦，§1.4 注）。非 BaseDef 派生（无 id/name 语义），
    raw 深拷贝镜像；缺省三键全部合理默认（三铁律②）。
    """

    raw: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, entry: Mapping[str, object]) -> "StatePolicyDef":
        """从配置子对象构造（raw 深拷贝快照，防外部改写）。"""
        return cls(raw=copy.deepcopy(dict(entry)))

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    @property
    def combo(self) -> str:
        """#32 连段处理（clear=清连段+清活跃链 / keep=保留；默认 clear，[狂战士 L129]）。"""
        v = self._str("combo")
        return v if v else DEFAULT_STATE_POLICY_COMBO

    @property
    def marks(self) -> str:
        """#33 印记处理（keep=保留 / clear=清印记；默认 keep，[狂战士 L130]）。"""
        v = self._str("marks")
        return v if v else DEFAULT_STATE_POLICY_MARKS

    @property
    def buff(self) -> str:
        """#34 buff 处理（keep=跨形态保留 / clear=全清；默认 keep，[狂战士 L131]）。"""
        v = self._str("buff")
        return v if v else DEFAULT_STATE_POLICY_BUFF


# ---------------------------------------------------------------------------
# TransformDef（细化_6b §1.3 #21~#31：transform 段 11 字段，专属机制挂点）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransformDef(BaseDef):
    """jobs.json transform 段（细化_6b §1.3 #21~#31 十一字段，专属机制挂点）。

    id/name 由 BaseDef 承载（from_entry 冗余镜像 raw；本段随 JobDef.transform_def()
    嵌套消费，id/name 无独立语义，BaseDef 兜底安全）。全部字段默认值兜底
    （三铁律②：漏配 = 合理默认不是报错）；必填/条件必填/枚举外值的红拦判定
    归 V1~V8 专项校验器，本层只呈现结构。
    """

    # ---- 数值/字符串/列表/映射辅助（与 SkillDef 同风格）----

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

    # ---- transform 段 11 字段（#21~#31，§1.3）----

    @property
    def transform_skill(self) -> str:
        """#21 触发技能 ID（必填；一次行动技能，成功结算后触发变换；V2 归属校验）。"""
        v = self._str("transform_skill")
        return v if v else DEFAULT_TRANSFORM_SKILL

    @property
    def transform_to(self) -> str:
        """#22 变换目标形态 ID（必填；job_form 值域来源；V1 存在性/V3 自指环）。"""
        v = self._str("transform_to")
        return v if v else DEFAULT_TRANSFORM_TO

    @property
    def duration(self) -> str:
        """#23 持续模式（turns=回合制持续（配 turns）/ battle=整场不还原；兜底 turns，P-1）。"""
        v = self._str("duration")
        return v if v else DEFAULT_DURATION

    @property
    def turns(self) -> int:
        """#24 形态持续回合数（条件必填：duration=turns 时 >0；0=未配置哨兵，P-2）。"""
        v = self._int("turns")
        return v if v is not None and v >= 1 else DEFAULT_TURNS

    @property
    def revert(self) -> bool:
        """#25 结束后是否还原（必填；battle 模式配 true → 红拦矛盾，V4/D-04）。"""
        v = self._bool("revert")
        return v if v is not None else DEFAULT_REVERT

    @property
    def cooldown(self) -> int:
        """#26 形态冷却（必填；默认 5，从「触发」起算；负值钳 0，P-3）。"""
        v = self._int("cooldown")
        v = v if v is not None else DEFAULT_COOLDOWN
        return max(v, 0)

    @property
    def dispel_reverts(self) -> bool:
        """#27 形态被驱散→触发还原钩子（默认 true；false=形态免疫驱散，[狂战士 L288/L301]）。"""
        v = self._bool("dispel_reverts")
        return v if v is not None else DEFAULT_DISPEL_REVERTS

    @property
    def state_policy(self) -> Mapping[str, object]:
        """#28 变换/还原瞬间资源处理策略（必填；3 子字段见 §1.4，V5 枚举红拦）。"""
        v = self.raw.get("state_policy")
        return v if isinstance(v, Mapping) else {}

    def state_policy_def(self) -> StatePolicyDef:
        """#28 state_policy 防御性读取（缺省三键兜底 clear/keep/keep）。"""
        return StatePolicyDef.from_entry(self.state_policy)

    @property
    def skill_set(self) -> str:
        """#29 形态技能组 ID（必填；技能位随形态重排为改组；V8 完整性校验）。"""
        v = self._str("skill_set")
        return v if v else DEFAULT_SKILL_SET

    @property
    def equip_restrict(self) -> Tuple[str, ...]:
        """#30 形态装备限制（可空；空=不限制，联动 4b 自动卸下逻辑，SH-4）。"""
        return self._str_list("equip_restrict")

    @property
    def derive_chains(self) -> Tuple[str, ...]:
        """#31 形态专属派生链 ID 列表（链 job_scope=该形态；切换后重新评估，V8）。"""
        return self._str_list("derive_chains")


# ---------------------------------------------------------------------------
# 字段登记表：transform_fields（11 字段）/ state_policy_fields（3 字段）
# ---------------------------------------------------------------------------
# 供主 agent 收口接线 field_meta（jobs 模块登记 / 校验器 V1~V8 依据 / 编辑器表单）。
# 本文件零登记、零 import 兄弟模块（并发同仓纪律）。


def state_policy_fields() -> Dict[str, FieldMeta]:
    """state_policy 子对象 3 字段 FieldMeta 注册表（细化_6b §1.4 #32~#34）。

    三键枚举值域统一 {clear, keep}（V5 红拦依据，§1.4 注）；默认 clear/keep/keep。
    """
    return {
        "combo": FieldMeta(
            type="enum", enum=STATE_POLICY_VALUES, default=DEFAULT_STATE_POLICY_COMBO,
        ),
        "marks": FieldMeta(
            type="enum", enum=STATE_POLICY_VALUES, default=DEFAULT_STATE_POLICY_MARKS,
        ),
        "buff": FieldMeta(
            type="enum", enum=STATE_POLICY_VALUES, default=DEFAULT_STATE_POLICY_BUFF,
        ),
    }


def transform_fields() -> Dict[str, FieldMeta]:
    """transform 段 11 字段 FieldMeta 注册表（细化_6b §1.3 #21~#31 全字段）。

    必填 7（transform_skill/transform_to/duration/revert/cooldown/state_policy/
    skill_set）+ 条件必填 1（turns）+ 可选 3（dispel_reverts/equip_restrict/
    derive_chains），逐字段对齐契约类型/默认/引用（P-1~P-4 口径见文件头）。
    """
    return {
        # #21 触发技能 ID（ref skills 注册表 kind="skill"，V2 归属校验归专项）
        "transform_skill": FieldMeta(type="ref", ref_target="skill", required=True),
        # #22 变换目标形态 ID（job_form 值域，V1 存在性校验归专项；P-4）
        "transform_to": FieldMeta(type="str", required=True),
        # #23 持续模式（两枚举；必填但兜底 turns，P-1）
        "duration": FieldMeta(
            type="enum", enum=TRANSFORM_DURATION_VALUES,
            required=True, default=DEFAULT_DURATION,
        ),
        # #24 形态持续回合（条件必填：duration=turns 时 >0；0=哨兵，P-2）
        "turns": FieldMeta(type="int", range_min=1, default=DEFAULT_TURNS),
        # #25 结束后是否还原（battle+true 矛盾红拦 V4 归专项）
        "revert": FieldMeta(type="bool", required=True, default=DEFAULT_REVERT),
        # #26 形态冷却（默认 5，从「触发」起算；P-3）
        "cooldown": FieldMeta(
            type="int", range_min=0, required=True, default=DEFAULT_COOLDOWN,
        ),
        # #27 驱散还原钩子（默认 true；V7 联动检查归专项）
        "dispel_reverts": FieldMeta(type="bool", default=DEFAULT_DISPEL_REVERTS),
        # #28 state_policy 子对象（三键枚举 V5 归专项；children = state_policy_fields）
        "state_policy": FieldMeta(type="obj", required=True, children=state_policy_fields()),
        # #29 形态技能组 ID（V8 完整性校验归专项；P-4）
        "skill_set": FieldMeta(type="str", required=True),
        # #30 形态装备限制（空=不限制；联动 4b 卸下逻辑归专项）
        "equip_restrict": FieldMeta(type="list", element=FieldMeta(type="str")),
        # #31 形态专属派生链（ref skill_chains 注册表 kind="skill_chain"，V8 归专项）
        "derive_chains": FieldMeta(
            type="list", element=FieldMeta(type="ref", ref_target="skill_chain"),
        ),
    }


# transform 段 11 字段 FieldMeta（§1.3 #21~#31；与 transform_fields() 同源单点）
TRANSFORM_CHILDREN: Mapping[str, FieldMeta] = transform_fields()

# state_policy 3 字段 FieldMeta（§1.4 #32~#34；与 state_policy_fields() 同源单点）
STATE_POLICY_CHILDREN: Mapping[str, FieldMeta] = state_policy_fields()
