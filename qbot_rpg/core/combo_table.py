"""M13 批11 路11A · 6c combo_table 组合表达 schema + 触发判定（qbot_rpg/core/combo_table.py）。

文件名：qbot_rpg/core/combo_table.py
创建时间：2026-09-02
作者：Hermes 子agent-11A（M13 6c 组合表达实现组批11路11A：并发同仓，仅新建本文件 +
  tests/unit/test_combo_table.py；不碰兄弟文件——11B 独占组合结算执行
  （F-C2 行为执行接线）、11C 独占季节+组合测试集；本路产出组合表达引擎
  （schema 解析 + 触发判定 + 匹配/扣减原语），战斗接线由主 agent 收口）

功能描述：6c 组合表达 combo_table 引擎核心（细化_6c §三 机制 M8）——
  1) combo_table 行 schema 解析（§3.1 C1~C7 七字段）：
     - ComboRow 数据类：combo（多重集 string[]）/name/kind/power/element/
       hits/effects 全量防御读取（缺省回落合理默认，三铁律②）；
     - rows_of() 从 skill def 读 combo_table 段（Mapping 直取 / 协议对象
       属性取），畸形行防御归一不抛异常（校验红拦归批12 V8）；
     - combo_multiset() 多重集归一（去重保序计数 + 出现次数表，D-02
       [fire,fire] 要求 fire 出现次数 2 语义）。
  2) 多重集匹配（D-02 / CM-1，TC-14 核心）：
     - multiset_matches()：combo 行多重集 ⊆ 当前池分布（行 [fire,fire]
       要求池 fire 当前值 ≥ 2；[fire,water] 要求 fire ≥ 1 且 water ≥ 1）；
     - match_combo_row()：遍历 combo_table 行，返回首个匹配行
       （表序 = 作者声明优先级，确定性零随机）；
     - match_combos()：全部匹配行列表（F-C1 ③ 提示「可用：火火·高伤 /
       火水·控制」数据源，CM-3）。
  3) 触发判定三重门禁（F-C1，TC-14 全验）：
     - gate_conventional()：① 常规门禁——mp_cost/cooldown/条件由调用方
       （combo.should_reject 管道）先行，本函数占位返回 ok（无状态引擎
       零定时器零睡眠，冷却计数归战斗层）；
     - gate_total()：② 总量门——energy_cost 全键求和（any:n 计 n）≤
       当前可用能量总数（resource_axis.total_of，D-02）；不足 → 被拒不耗；
     - gate_combination()：③ 组合匹配——遍历 combo_table 行多重集匹配
       当前池分布，匹配成功 → 锁定该行为本次行为（CM-2 先匹配后消耗：
       匹配阶段零扣减）；全部不匹配 → 被拒不耗（能量不变，D-02/CM-3）；
     - resolve_trigger()：一站式 F-C1 判定——常规 → 总量 → 组合三重门禁
       短路返回 {ok, rejected, reason, row, axis, total, available}，
       不执行任何消耗（消耗归结算 F-C2 阶段，11B）。
  4) 先匹配后消耗原语（CM-2）：
     - row_cost_plan()：锁定行 → 该行池分布扣减方案 [{"pool","amount"}]
       （[fire,fire] → fire 扣 2），供 F-C2 结算阶段按行扣池（RS-6 池级
       原子由 resource_axis.pay_cost 承接）；
     - combo_cost_plan()：energy_cost 总量门 any:n 的扣减方案
       （resource_axis.cost_breakdown 承接，B-5 确定性池序均摊）——本文件
       不直接扣减（先匹配后消耗：判定零副作用）。
  5) ComboTableEngine 引擎注入模式（对齐 resource_axis.py / transform.py）：
     - 构造器注入 stats / resource_state / audit；缺省 → 运行时读 ctx；
     - 方法：rows(skill) / match(skill, ctx) / resolve(skill, ctx, side) /
       suggest(skill, ctx, side)（可用组合提示，CM-3 数据源）。

依据：docs/细化/细化_6c_资源轴与职业机制.md：
  - §3.1 行字段表（C1 combo 多重集 / C2 name / C3 kind 枚举 damage|utility|
    heal|control / C4 power 0-400 / C5 element ∈ 8 元素注册表 / C6 hits /
    C7 effects 引用）+ 编排约束（行数 ≤ C(|pools|+1,2) 无重组合上限）；
  - §3.2 F-C1 触发判定（① 常规门禁 → ② 总量门 any:n → ③ 组合匹配 →
    ④ 锁定行，结算阶段扣减）+ CM-1（多重集匹配口径）/ CM-2（先匹配后
    消耗）/ CM-3（无可匹配行 → 被拒，能量不变，提示可用组合）；
  - §0.3 ADR：D-02（any:n 总量门 + 组合行多重集匹配双重校验——满足总量
    但池分布不满足该组合行时该行不可用、技能被拒不耗能量）；
  - §六 TC-14（六组合逐一匹配 / 能量分布不满足任一组合行 → 被拒不耗 /
    匹配提示「可用：火火·高伤 / 火水·控制」）。
  - docs/m13_6c摸底.md：M8 缺口（combo.py 为连段引擎非组合表达，F-C1
    全缺；battle.py L1215-1229 rejected 管道现成——本路产出独立判定引擎，
    接线由主 agent 收口）。
  - 模式参考：qbot_rpg/core/resource_axis.py（两型注册读取 + check_cost/
    total_of 现成原语）、qbot_rpg/core/transform.py（引擎注入模式）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  B-1  组合行表序 = 匹配优先级：F-C1 ③「遍历 combo_table 行」未定义多行
       同时可匹配时的锁定规则，本引擎按表序取首个匹配行（确定性零随机，
       作者声明顺序即优先级；编辑器的达摩克利斯提示引导唯一性）。
  B-2  匹配范围 = 技能所属资源轴池全集：combo 行元素按轴 pools 校验，
       未知池元素行在匹配阶段视为不匹配（V8 红拦归批12，运行时防御）。
  B-3  单技能无 combo_table 段 → 常规技能语义：resolve_trigger 在无行时
       直接 ok（gate_combination 空表放行），不拦截普通技能。
  B-4  空 combo 行（combo 缺省/空数组）视为不匹配：无组合键无法分派
       行为，匹配阶段跳过（V8 结构校验归批12）。
  B-5  总量门与组合门的关系：总量门通过 ≠ 组合行可用（D-02 双重校验）——
       any:2 总量满足但池分布不满足任一组合行 → 组合门拒绝，能量不变。
  B-6  多行同时匹配时 suggest 返回全部匹配行（CM-3 提示数据源），resolve
       锁定首个（B-1）；两者语义分离，供接线方各自消费。
  B-7  事件形态：本路产出 {type: "combo_gate", ...} 结构化事件（对齐
       battle side_effects 惯例）；文案不写死模板（零模板输出，仅 reason
       语义键，CM-4 状态提示归接线方）。

铁律：零 NoneBot import（G0 门禁）；core 层只依赖 data（本文件零 import
content/data，技能数据经 ctx/skill 注入）；纯函数确定性（同刻同参必同值）；
完整类型标注（typing 3.9 兼容）；零定时器/零睡眠（本文件不含任何 sleep/
定时器字面量——引擎零定时器零睡眠，无时间依赖）；不引入随机；不 git
commit；只写本文件 + 自己的测试。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple

# =====================================================================================
# 常量（细化_6c §3.1 契约口径）
# =====================================================================================

# 组合行 kind 枚举（§3.1 C3：对齐 ActionCore kind 枚举；control 为工程补白扩展）
KIND_DAMAGE: str = "damage"
KIND_UTILITY: str = "utility"
KIND_HEAL: str = "heal"
KIND_CONTROL: str = "control"
COMBO_KINDS: Tuple[str, ...] = (KIND_DAMAGE, KIND_UTILITY, KIND_HEAL, KIND_CONTROL)

# power 倍率缺省（§3.1 C4：0 = 无伤害，如护盾/治疗/控制行）
DEFAULT_COMBO_POWER: float = 0.0
# hits 多段缺省（§3.1 C6：缺省 1 段；每段独立取整）
DEFAULT_COMBO_HITS: int = 1
# kind 缺省（§3.1 C3：行为类别，缺省 damage）
DEFAULT_COMBO_KIND: str = KIND_DAMAGE

# 触发判定 reason 语义键（F-C1 门禁短路，CM-3；文案模板化归接线方）
REASON_OK: str = ""
REASON_TOTAL_INSUFFICIENT: str = "energy_total_insufficient"
REASON_NO_MATCH: str = "no_combo_match"
REASON_NO_ROWS: str = "no_combo_rows"

# 事件类型（B-7 结构化事件形态）
EVENT_COMBO_GATE: str = "combo_gate"


# =====================================================================================
# 防御性读取辅助（与 resource_axis.py 同风格：类型校验 + 钳制，不抛异常）
# =====================================================================================


def _norm_str(v: Any) -> str:
    """字符串归一：非 str → 空串（防御读取）。"""
    return v if isinstance(v, str) else ""


def _norm_str_list(v: Any) -> Tuple[str, ...]:
    """字符串列表归一：非 list/tuple → 空元组（防御读取）。"""
    if not isinstance(v, (list, tuple)):
        return ()
    return tuple(x for x in v if isinstance(x, str) and x)


def _norm_float(v: Any, default: float = 0.0) -> float:
    """浮点归一（bool 除外）；非数值 / 非法 → default（防御读取）。"""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return default


def _norm_int(v: Any, default: int = 0) -> int:
    """整数归一（bool 除外）；非 int / 非法 → default（防御读取）。"""
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return default


def _norm_nonneg_float(v: Any, default: float = 0.0) -> float:
    """非负浮点归一（负值钳 0）。"""
    return max(0.0, _norm_float(v, default))


def _norm_nonneg_int(v: Any, default: int = 0) -> int:
    """非负整数归一（负值钳 0）。"""
    return max(0, _norm_int(v, default))


# =====================================================================================
# ComboRow：组合行统一封装（§3.1 C1~C7 七字段，防御读取）
# =====================================================================================


class ComboRow:
    """combo_table 一行（§3.1 行字段表 C1~C7，防御读取）。

    - combo：多重集 string[]（元素爆发 = 从 element_energy 三池取 2）；
    - name：组合名（技能卡/战报展示）；
    - kind：行为类别枚举（damage/utility/heal/control，C3）；
    - power：倍率（0 = 无伤害，如护盾/治疗/控制行，C4）；
    - element：伤害元素通道（∈ formula 8 元素注册表，可 null，C5）；
    - hits：多段次数（每段独立取整，C6）；
    - effects：效果引用数组（effects.json 唯一数据源 + 模板 + overrides，C7）。
    全部字段缺省回落合理默认（三铁律②），畸形行不抛异常（V8 归批12）。
    """

    __slots__ = ("_raw", "_combo", "_name", "_kind", "_power", "_element", "_hits",
                 "_effects", "_counts")

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = dict(raw) if isinstance(raw, Mapping) else {}
        combo = _norm_str_list(self._raw.get("combo"))
        self._combo: Tuple[str, ...] = tuple(dict.fromkeys(combo))
        self._counts: Dict[str, int] = {}
        for c in combo:
            self._counts[c] = self._counts.get(c, 0) + 1
        self._name = _norm_str(self._raw.get("name"))
        kind = _norm_str(self._raw.get("kind"))
        self._kind = kind if kind in COMBO_KINDS else DEFAULT_COMBO_KIND
        self._power = _norm_nonneg_float(self._raw.get("power"), DEFAULT_COMBO_POWER)
        self._element = _norm_str(self._raw.get("element")) or None
        self._hits = max(1, _norm_int(self._raw.get("hits"), DEFAULT_COMBO_HITS))
        effects = self._raw.get("effects")
        self._effects: Tuple[Mapping[str, Any], ...] = (
            tuple(e for e in effects if isinstance(e, Mapping))
            if isinstance(effects, (list, tuple)) else ()
        )

    @property
    def raw(self) -> Dict[str, Any]:
        """原始行副本（只读语义）。"""
        return dict(self._raw)

    @property
    def combo(self) -> Tuple[str, ...]:
        """组合多重集（去重保序的池名序列；[fire,fire] → ("fire",)）。"""
        return self._combo

    @property
    def combo_counts(self) -> Dict[str, int]:
        """组合多重集出现次数表（D-02/CM-1：[fire,fire] → {"fire": 2}）。"""
        return dict(self._counts)

    @property
    def combo_size(self) -> int:
        """组合元素总数（[fire,fire] → 2；空行 → 0）。"""
        return sum(self._counts.values())

    @property
    def name(self) -> str:
        """组合名（缺省 ""）。"""
        return self._name

    @property
    def kind(self) -> str:
        """行为类别（枚举外回落 damage，C3）。"""
        return self._kind

    @property
    def power(self) -> float:
        """倍率（0 = 无伤害；负值钳 0，C4）。"""
        return self._power

    @property
    def element(self) -> Optional[str]:
        """伤害元素通道（null/空 = 无元素，C5）。"""
        return self._element

    @property
    def hits(self) -> int:
        """多段次数（≥1，缺省 1；负值/0 钳 1，C6）。"""
        return self._hits

    @property
    def effects(self) -> Tuple[Mapping[str, Any], ...]:
        """效果引用条目（effects.json 模板引用 + overrides，C7）。"""
        return self._effects

    def matches(self, pool_values: Mapping[str, int]) -> bool:
        """多重集匹配（D-02/CM-1，TC-14 核心原语）。

        行 combo 多重集 ⊆ 当前池分布：行 [fire,fire] 要求池 fire 当前值 ≥ 2
        （出现次数）；行 [fire,water] 要求 fire ≥ 1 且 water ≥ 1。空 combo
        行恒 False（B-4：无组合键无法分派行为）。
        """
        if not self._counts:
            return False
        for pool, need in self._counts.items():
            have = pool_values.get(pool)
            if not isinstance(have, int) or isinstance(have, bool):
                return False
            if have < need:
                return False
        return True


def combo_multiset(combo: Any) -> Dict[str, int]:
    """combo 多重集归一：出现次数表（D-02 口径，[fire,fire] → {"fire": 2}）。

    独立工具函数（不依赖 ComboRow），供接线方/校验方统计使用；非字符串
    元素防御丢弃。
    """
    items = _norm_str_list(combo)
    out: Dict[str, int] = {}
    for c in items:
        out[c] = out.get(c, 0) + 1
    return out


def rows_of(skill: Any) -> Tuple[ComboRow, ...]:
    """skill def 的 combo_table 段 → ComboRow 元组（防御归一，畸形行不抛异常）。

    Mapping 直取 "combo_table"；协议对象（hasattr）属性取；段缺省/非列表
    → 空元组（B-3：无组合表 = 常规技能语义）。行顺序 = 表序（B-1 匹配优先级）。
    """
    if isinstance(skill, Mapping):
        seg = skill.get("combo_table")
    elif skill is not None and hasattr(skill, "combo_table"):
        v = getattr(skill, "combo_table")
        seg = v() if callable(v) else v
    else:
        seg = None
    if not isinstance(seg, (list, tuple)):
        return ()
    return tuple(ComboRow(e) for e in seg if isinstance(e, Mapping))


# =====================================================================================
# 多重集匹配（D-02 / CM-1）
# =====================================================================================


def pool_values_of(
    ctx: Mapping[str, Any],
    axis_id: str,
    pools: Tuple[str, ...],
    side: str = "player",
) -> Dict[str, int]:
    """当前池分布快照（匹配判定数据源，纯读取零副作用）。

    逐池读 resource_axis.get_value（子池型池级原子读取，RS-6 口径）；
    轴未注册/槽缺失 → 全 0（RS-5 降级：匹配失败不报错，校验红拦归批12）。
    防御导入 resource_axis（模块级惰性，G0 单向依赖 data 不变）。
    """
    try:
        from qbot_rpg.core import resource_axis
    except Exception:  # pragma: no cover - 防御兜底（同刻同参必同值）
        return {p: 0 for p in pools}
    out: Dict[str, int] = {}
    for p in pools:
        out[p] = resource_axis.get_value(ctx, axis_id, key=p, side=side)
    return out


def multiset_matches(row: ComboRow, pool_values: Mapping[str, int]) -> bool:
    """多重集匹配（D-02/CM-1 语义等价封装：ComboRow.matches 模块级入口）。"""
    return row.matches(pool_values)


def match_combo_row(
    rows: Tuple[ComboRow, ...],
    pool_values: Mapping[str, int],
) -> Optional[ComboRow]:
    """遍历 combo_table 行，返回首个匹配行（B-1 表序 = 优先级，确定性）。

    F-C1 ③ 组合匹配：全部行不匹配 → None（调用方走被拒不耗路径，D-02/CM-3）。
    """
    for row in rows:
        if row.matches(pool_values):
            return row
    return None


def match_combos(
    rows: Tuple[ComboRow, ...],
    pool_values: Mapping[str, int],
) -> List[ComboRow]:
    """全部匹配行列表（B-6：CM-3「可用：火火·高伤 / 火水·控制」提示数据源）。"""
    return [row for row in rows if row.matches(pool_values)]


def available_hints(
    rows: Tuple[ComboRow, ...],
    pool_values: Mapping[str, int],
) -> List[Dict[str, Any]]:
    """可用组合提示条目（CM-3 数据源：名称 + 组合键 + 行为摘要）。

    返回 [{combo, name, kind, power}]（不写死模板文案，零模板输出 B-7）；
    无匹配 → 空列表（接线方按契约提示「能量已耗尽，继续积蓄元素吧」类
    文案归 CM-4 模板层）。
    """
    out: List[Dict[str, Any]] = []
    for row in match_combos(rows, pool_values):
        out.append({
            "combo": list(row.combo),
            "name": row.name,
            "kind": row.kind,
            "power": row.power,
        })
    return out


# =====================================================================================
# F-C1 三重门禁（① 常规 → ② 总量 any:n → ③ 组合多重集匹配）
# =====================================================================================


def _axis_of(ctx: Mapping[str, Any], axis_id: str) -> Any:
    """轴注册定位（防御导入 resource_axis；未注册 → None，RS-5 降级）。"""
    try:
        from qbot_rpg.core import resource_axis
        return resource_axis.axis_of(ctx, axis_id)
    except Exception:  # pragma: no cover - 防御兜底
        return None


def _energy_cost_of(skill: Any) -> Dict[str, Any]:
    """skill def 的 energy_cost 段归一（{axis_id: {key: amount}} 或简写）。"""
    if isinstance(skill, Mapping):
        seg = skill.get("energy_cost")
    elif skill is not None and hasattr(skill, "energy_cost"):
        v = getattr(skill, "energy_cost")
        seg = v() if callable(v) else v
    else:
        seg = None
    return dict(seg) if isinstance(seg, Mapping) else {}


def gate_conventional(
    ctx: Mapping[str, Any],  # noqa: ARG001 - 占位签名，语义归调用方管道
    skill: Any,  # noqa: ARG001 - 占位签名，语义归调用方管道
    side: str = "player",  # noqa: ARG001 - 占位签名，语义归调用方管道
) -> Dict[str, Any]:
    """① 常规门禁占位（F-C1 ①：mp_cost/cooldown/条件 → 任一不足被拒不耗回合）。

    mp_cost/cooldown/条件判定由战斗层既有管道承载（combo.should_reject +
    battle rejected 短路，摸底 L856/L1215-1229），本引擎不重复实现：
    返回 ok 占位，供 resolve_trigger 保持「常规 → 总量 → 组合」三段短路
    结构完整。冷却计数归战斗层（引擎零定时器零睡眠，无时间依赖）。
    """
    return {"ok": True, "reason": REASON_OK}


def gate_total(
    ctx: Mapping[str, Any],
    skill: Any,
    axis_id: str,
    side: str = "player",
) -> Dict[str, Any]:
    """② 总量门（F-C1 ② / D-02）：energy_cost 全键求和 ≤ 当前可用能量总数。

    - 子池型：energy_cost {any:2} → 需要 2 ≤ total_of（各池和）；具名键
      {fire:1,water:1} → 求和 2（具名键同为能量消耗，K2 口径）；
    - 数值型：energy_cost {rage:100} → 100 ≤ 轴单值（资源 ID 键，K1）；
    - 无 energy_cost 段 / 未注册轴 → 放行 ok（RS-5 降级，V1 红拦归批12）；
    - 不足 → {ok:False, reason:energy_total_insufficient}（被拒不耗回合）。
    返回 {ok, reason, need, have}（need = 全键求和，have = 当前可用总数）。
    """
    cost = _energy_cost_of(skill)
    if not cost:
        return {"ok": True, "reason": REASON_OK, "need": 0, "have": 0}
    # 形态兼容：契约 {axis_id: {key: amount}} 包装 / 6c §3.1 原例 {any: 2}
    # 裸键形态（轴隐式 = 本技能轴）——两者均防御接受
    sub = cost.get(axis_id) if isinstance(cost.get(axis_id), Mapping) else cost
    try:
        from qbot_rpg.core import resource_axis
        axis = resource_axis.axis_of(ctx, axis_id)
        if axis is None:
            # RS-5 降级：注册已删 → 该资源无增减不报错不悬空
            return {"ok": True, "reason": REASON_OK, "need": 0, "have": 0}
        need = 0
        sub_map: Mapping[str, Any] = sub if isinstance(sub, Mapping) else {}
        for key, amt in sub_map.items():
            if isinstance(key, str) and key:
                need += _norm_nonneg_int(amt, 0)
        have = resource_axis.total_of(ctx, axis_id, side)
    except Exception:  # pragma: no cover - 防御兜底
        return {"ok": True, "reason": REASON_OK, "need": 0, "have": 0}
    if need > have:
        return {"ok": False, "reason": REASON_TOTAL_INSUFFICIENT, "need": need, "have": have}
    return {"ok": True, "reason": REASON_OK, "need": need, "have": have}


def gate_combination(
    ctx: Mapping[str, Any],
    skill: Any,
    axis_id: str,
    side: str = "player",
) -> Dict[str, Any]:
    """③ 组合匹配门（F-C1 ③ / D-02 / CM-1）：多重集匹配当前池分布。

    - 遍历 combo_table 行（B-1 表序 = 优先级），首个匹配行锁定为本次行为；
    - 全部不匹配 / 无组合表行 → {ok:False, reason:no_combo_match}（被拒不耗，
      能量不变；B-3/B-5）；空表 → {ok:False, reason:no_combo_rows}；
    - 匹配阶段零扣减（CM-2 先匹配后消耗，消耗归 F-C2 结算阶段）。
    返回 {ok, reason, row, matched, hints}：
      row = 锁定行（ComboRow）；matched = 全部匹配行（B-6 提示数据源）；
      hints = available_hints 条目（CM-3 数据源）。
    """
    rows = rows_of(skill)
    if not rows:
        return {"ok": True, "reason": REASON_OK, "row": None,
                "matched": [], "hints": []}
    try:
        from qbot_rpg.core import resource_axis
        axis = resource_axis.axis_of(ctx, axis_id)
        pools = axis.pools if axis is not None else ()
    except Exception:  # pragma: no cover - 防御兜底
        pools = ()
    values = pool_values_of(ctx, axis_id, pools, side)
    row = match_combo_row(rows, values)
    matched = match_combos(rows, values)
    hints = available_hints(rows, values)
    if row is None:
        return {"ok": False, "reason": REASON_NO_MATCH, "row": None,
                "matched": matched, "hints": hints}
    return {"ok": True, "reason": REASON_OK, "row": row,
            "matched": matched, "hints": hints}


def resolve_trigger(
    ctx: Mapping[str, Any],
    skill: Any,
    axis_id: str,
    side: str = "player",
) -> Dict[str, Any]:
    """F-C1 一站式触发判定（① 常规 → ② 总量 → ③ 组合三重门禁短路）。

    返回 {ok, rejected, reason, row, axis, total, need, matched, hints,
    events}：
      - ok=True → 门禁全过，row = 锁定组合行（F-C2 结算阶段按行扣池）；
      - ok=False + rejected=True → 被拒不耗回合（能量/MP/连段不变，可反复
        尝试；D-02/CM-3）；reason ∈ total_insufficient / no_combo_match /
        no_combo_rows；
      - 无 combo_table 段 → ok=True + row=None（B-3 常规技能语义）；
      - 本函数零副作用：不扣能量、不扣 MP、不写快照（CM-2 先匹配后消耗）。
    events = [{type: "combo_gate", ...}]（B-7 结构化事件，供消息/审计）。
    """
    g1 = gate_conventional(ctx, skill, side)
    if not g1.get("ok"):
        return {"ok": False, "rejected": True, "reason": g1.get("reason"),
                "row": None, "axis": axis_id, "total": 0, "need": 0,
                "matched": [], "hints": [], "events": []}
    g2 = gate_total(ctx, skill, axis_id, side)
    if not g2.get("ok"):
        return {"ok": False, "rejected": True, "reason": g2.get("reason"),
                "row": None, "axis": axis_id, "total": g2.get("have", 0),
                "need": g2.get("need", 0), "matched": [], "hints": [],
                "events": [{"type": EVENT_COMBO_GATE, "stage": "total",
                            "ok": False, "reason": g2.get("reason"),
                            "need": g2.get("need", 0), "have": g2.get("have", 0)}]}
    g3 = gate_combination(ctx, skill, axis_id, side)
    if not g3.get("ok"):
        return {"ok": False, "rejected": True, "reason": g3.get("reason"),
                "row": None, "axis": axis_id, "total": g2.get("have", 0),
                "need": g2.get("need", 0), "matched": g3.get("matched", []),
                "hints": g3.get("hints", []),
                "events": [{"type": EVENT_COMBO_GATE, "stage": "combination",
                            "ok": False, "reason": g3.get("reason")}]}
    return {"ok": True, "rejected": False, "reason": REASON_OK,
            "row": g3.get("row"), "axis": axis_id, "total": g2.get("have", 0),
            "need": g2.get("need", 0), "matched": g3.get("matched", []),
            "hints": g3.get("hints", []),
            "events": [{"type": EVENT_COMBO_GATE, "stage": "all",
                        "ok": True, "row": g3.get("row").name  # type: ignore[union-attr]
                        if g3.get("row") is not None else None}]}


# =====================================================================================
# 先匹配后消耗原语（CM-2：判定零副作用，扣减方案归 F-C2 结算阶段）
# =====================================================================================


def row_cost_plan(row: ComboRow) -> List[Dict[str, Any]]:
    """锁定行 → 按该行池分布扣减方案（CM-2/F-C2 ①）。

    [fire,fire] → [{"pool": "fire", "amount": 2}]；[fire,water] →
    [{"pool": "fire", "amount": 1}, {"pool": "water", "amount": 1}]。
    方案 = 组合多重集逐池出现次数（确定性零随机）；扣减执行由接线方经
    resource_axis.pay_cost 逐池原子扣（RS-6 池级原子，F-C2 ①）。
    """
    plan: List[Dict[str, Any]] = []
    for pool, amount in row.combo_counts.items():
        plan.append({"pool": pool, "amount": amount})
    return plan


def combo_cost_plan(
    ctx: Mapping[str, Any],
    skill: Any,
    axis_id: str,
    side: str = "player",
) -> Optional[List[Dict[str, Any]]]:
    """energy_cost 总量门 any:n 的扣减方案（B-5 承接 resource_axis.cost_breakdown）。

    - 子池型 {any:2} → cost_breakdown 确定性池序均摊方案；不足 → None
      （调用方走被拒路径，不半扣）；
    - 具名键/数值型 → None（F-C2 扣减走 skill 级 pay_skill_cost，非组合行
      池分布口径——组合行锁定后按 row_cost_plan 扣池）。
    本函数仅计算不扣减（CM-2 先匹配后消耗）。
    """
    cost = _energy_cost_of(skill)
    if not cost:
        return []
    # 形态兼容（同 gate_total）：包装形态取子段，裸键形态轴隐式 = 本技能轴
    sub = cost.get(axis_id) if isinstance(cost.get(axis_id), Mapping) else cost
    if not isinstance(sub, Mapping):
        return None
    try:
        from qbot_rpg.core import resource_axis
        return resource_axis.cost_breakdown(ctx, axis_id, sub, side)
    except Exception:  # pragma: no cover - 防御兜底
        return None


# =====================================================================================
# ComboTableEngine（引擎注入模式：构造器注入 stats / resource_state / audit）
# =====================================================================================


class ComboTableEngine:
    """组合表达引擎（对齐 resource_axis.ResourceAxisEngine 注入模式）。

    构造器注入（均可缺省，缺省 → 运行时读 ctx）：
      stats:           注册表（map/list 形态；缺省读 ctx["stats"]）。
      resource_state:  战斗资源槽（缺省读 ctx["resource_state"]）。
      audit:           审计观察口 callable(str)。

    方法：
      rows(skill)                —— combo_table 行解析（ComboRow 元组）；
      match(skill, ctx, side)    —— 多重集匹配（全部匹配行 + 首个锁定行）；
      resolve(skill, ctx, side)  —— F-C1 三重门禁一站式判定（零副作用）；
      suggest(skill, ctx, side)  —— 可用组合提示（CM-3 数据源）。
    """

    def __init__(
        self,
        stats: Optional[Mapping[str, Any]] = None,
        resource_state: Optional[MutableMapping[str, Any]] = None,
        audit: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._stats: Optional[Mapping[str, Any]] = stats
        self._resource_state: Optional[MutableMapping[str, Any]] = resource_state
        self._audit: Optional[Callable[[str], None]] = audit

    def _inject(self, ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        """把构造器注入挂 ctx（仅缺省键不覆盖调用方显式注入，幂等）。"""
        if self._stats is not None:
            ctx.setdefault("stats", self._stats)
        if self._resource_state is not None:
            ctx.setdefault("resource_state", self._resource_state)
        return ctx

    def _audit_log(self, message: str) -> None:
        if self._audit is not None:
            self._audit(message)

    def rows(self, skill: Any) -> Tuple[ComboRow, ...]:
        """combo_table 行解析（防御归一，畸形行不抛异常）。"""
        return rows_of(skill)

    def match(
        self,
        skill: Any,
        ctx: MutableMapping[str, Any],
        axis_id: str,
        side: str = "player",
    ) -> Dict[str, Any]:
        """多重集匹配（D-02）：{row, matched, hints}（零副作用）。"""
        ctx = self._inject(ctx)
        rows = rows_of(skill)
        try:
            from qbot_rpg.core import resource_axis
            axis = resource_axis.axis_of(ctx, axis_id)
            pools = axis.pools if axis is not None else ()
        except Exception:  # pragma: no cover - 防御兜底
            pools = ()
        values = pool_values_of(ctx, axis_id, pools, side)
        matched = match_combos(rows, values)
        result = {
            "row": match_combo_row(rows, values),
            "matched": matched,
            "hints": available_hints(rows, values),
        }
        self._audit_log("combo_match: matched=%s" % len(matched))
        return result

    def resolve(
        self,
        skill: Any,
        ctx: MutableMapping[str, Any],
        axis_id: str,
        side: str = "player",
    ) -> Dict[str, Any]:
        """F-C1 一站式触发判定（零副作用；消耗归 F-C2 结算阶段）。"""
        result = resolve_trigger(self._inject(ctx), skill, axis_id, side)
        self._audit_log("combo_resolve: ok=%s reason=%s" % (
            result.get("ok"), result.get("reason")))
        return result

    def suggest(
        self,
        skill: Any,
        ctx: MutableMapping[str, Any],
        axis_id: str,
        side: str = "player",
    ) -> List[Dict[str, Any]]:
        """可用组合提示（CM-3 数据源：名称 + 组合键 + 行为摘要）。"""
        ctx = self._inject(ctx)
        rows = rows_of(skill)
        try:
            from qbot_rpg.core import resource_axis
            axis = resource_axis.axis_of(ctx, axis_id)
            pools = axis.pools if axis is not None else ()
        except Exception:  # pragma: no cover - 防御兜底
            pools = ()
        values = pool_values_of(ctx, axis_id, pools, side)
        return available_hints(rows, values)


__all__ = [
    # 常量
    "KIND_DAMAGE",
    "KIND_UTILITY",
    "KIND_HEAL",
    "KIND_CONTROL",
    "COMBO_KINDS",
    "DEFAULT_COMBO_POWER",
    "DEFAULT_COMBO_HITS",
    "DEFAULT_COMBO_KIND",
    "REASON_OK",
    "REASON_TOTAL_INSUFFICIENT",
    "REASON_NO_MATCH",
    "REASON_NO_ROWS",
    "EVENT_COMBO_GATE",
    # 行封装
    "ComboRow",
    "combo_multiset",
    "rows_of",
    # 多重集匹配
    "pool_values_of",
    "multiset_matches",
    "match_combo_row",
    "match_combos",
    "available_hints",
    # F-C1 三重门禁
    "gate_conventional",
    "gate_total",
    "gate_combination",
    "resolve_trigger",
    # 先匹配后消耗原语（CM-2）
    "row_cost_plan",
    "combo_cost_plan",
    # 引擎
    "ComboTableEngine",
]
