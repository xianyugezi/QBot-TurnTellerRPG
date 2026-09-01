"""M13 批8 路8B · 6c energy_gain/energy_cost 运行时（qbot_rpg/core/resource_axis.py）。

文件名：qbot_rpg/core/resource_axis.py
创建时间：2026-09-02
作者：Hermes 子agent-8B（M13 6c 资源轴实现组批8路8B：并发同仓，仅新建本文件 +
  tests/unit/test_resource_axis.py；不碰兄弟文件——8A 独占 stats.json 注册段
  schema 扩展（icon/reset/display/max_per_pool/pools/pool_icons），8C 独占
  resource_state 快照段；若 8A 未落盘 stats 扩展，本路测试一律用内存 fixtures，
  引擎按字段口径防御读取，缺字段回落合理默认）

功能描述：6c 资源轴运行引擎核心（细化_6c §1.2 M2 / §1.3 F-R1 资源侧语义）——
  1) 两型注册段读取（D-01 判别：注册段含 pools = 子池型，无 pools = 数值型）：
     - ResourceAxis 数据类：数值型（rage）/ 子池型（element_energy）统一封装，
       max_per_pool / pools / pool_icons 防御读取（8A 未落盘也可用，缺省回落）；
     - axis_of() 从 ctx 注入的 stats 注册段（ctx["stats"] / ctx["resource_axes"]
       / ctx["stats_def"]）按资源 ID 定位注册条目，未注册 → 返回 None
       （RS-5 降级口径：该资源无增减不报错）；
     - normalize_axis() 注册段字段级防御归一（name/type/base/max/reset/display/
       max_per_pool/pools/pool_icons；type=resource_custom 归一为 resource，D-01b；
       max 缺省 100 / max=0 不限 / reset 缺省 battle）。
  2) energy_gain 结算（M2 E1，§1.3 成功结算段）：
     - gain_energy()：技能施放成功后追加（与 mark_add 同拍，命中判定后/结算末尾），
       数值型 ≤ max（0=不限），子池型每池 ≤ max_per_pool，超出部分不累计不回滚；
     - 多资源同时增减 {rage:10, heat:5}（K6）；值为 0 无操作（D-06）；
       负值防御钳 0（V3 校验器黄提示归批11，运行时防御不写负数）；
     - 未注册资源键 / 非 int 值 → 跳过不报错（三铁律② 防御兜底）；
     - apply_gain()：按 skill def 的 energy_gain 段批量结算（技能/派生/proc 通用）。
  3) energy_cost 施放前检查（M2 E2，§1.3 施放前段）：
     - check_cost()：施放前检查消耗是否足够——不足 → 被拒不耗回合（复用
       combo.should_reject 被拒管道语义：能量/怒气不变、连段不变、可反复尝试）；
     - 数值型键 = 资源 ID（K1）；子池型键 = 池名 + any 键（K2/D-02：any:n 为
       总量门，任意池合计 ≥ n）；any 与具名键互斥（K3，防御：并存时 any 优先）；
     - cost_breakdown()：对子池型消耗返回「按池扣减方案」（具名键逐池扣 + any
       余量从富余池按池序均摊，确定性），供战斗层 F-C2 按锁定组合行扣减复用；
     - pay_cost()：施放成功扣减（原子：先 check 后 pay，不半扣）。
  4) 触发类 energy_cost 语义（D-03）：
     - check_trigger_cost()：proc/trigger 内挂 energy_cost（元素能量屏障受击耗 1）
       触发事件发生时检查；不足 → 本次触发不生效、不耗能量、不计触发上限；
     - 生效后才计入「每回合 N 次」上限（TC-06③ 语义：不足不计数、生效计数）。
  5) 两型统一读写接口（数值型单值 / 子池型池级）：
     - get_value() / set_value() / add_value() / total_of()：数值型直接读写单值，
       子池型读写池级 {pool: value} 展开（D-04 池级原子粒度 RS-6）——统一入口
       按轴型分派，战斗层/快照层（8C）共用同一读写语义；
     - 战斗内资源槽 = ctx["resource_state"][side]（8C 快照段，本路只读写不落
       快照时序；侧缺省 player，PVP enemy 由调用方传 side）。
  6) ResourceAxisEngine 引擎注入模式（对齐 fishing.py / transform.py）：
     - 构造器注入 stats（注册表）/ resource_state（战斗资源槽）；
       缺省 → 运行时读 ctx["stats"] / ctx["resource_state"]；
     - 方法：gain_skill / check_skill / pay_skill / check_trigger / pay_trigger /
       trigger_energy_cost —— 技能级便捷入口（energy_gain/energy_cost 段从
       skill def 读取，G0 注入），返回结构化 dict（ok/message/events 等）。

依据：docs/细化/细化_6c_资源轴与职业机制.md：
  - §1.2 M2 字段级 schema（E1 energy_gain 成功结算时 / E2 energy_cost 施放前
    检查；K1~K6 键空间：数值型键=资源 ID、子池型键=池名+any、any 与具名互斥、
    多资源增减、0=无操作、负值笔误）；
  - §1.3 F-R1 回合结清（施放前 energy_cost 门禁不足被拒不耗回合 / 成功结算
    energy_gain 追加封顶 ≤max（0=不限）·子池型每池 ≤max_per_pool 超出不累计
    不回滚 / proc 时点同规则 / D-03 触发类不足不生效不耗不计上限）；
  - §0.3 ADR：D-01（pools 判别两型）/ D-01b（type 归一 resource）/ D-02
    （any:n 总量门 + 多重集匹配）/ D-03（触发类语义）/ D-06（0=无操作、负数笔误）；
  - §1.4 RS-5（恢复时注册已删 → 按字段缺失降级不报错）/ RS-6（池级原子粒度）；
  - §六 TC-02（命中 +15 / 未命中不变 / 95→100 封顶）/ TC-03（不足被拒不耗回合）
    / TC-06③（屏障不足不生效不耗不计上限）/ TC-08（池独立增减 + fire 封顶 3）。
  - docs/m13_6c摸底.md：M2 缺口（全库零命中 energy_gain/energy_cost；施放前
    检查 combo.py L856 should_reject + battle.py L1215-1229 rejected 管道现成；
    成功结算后增加无挂点——本路产出独立引擎，接线由主 agent 收口 battle）。
  - 模式参考：qbot_rpg/core/fishing.py（FishingEngine 注入三件套 + ctx 键
    惰性挂回 + 缺省兜底）、qbot_rpg/core/transform.py（TransformEngine 构造器
    注入钩子缺省 = 模块级纯函数默认行为 + G0 零 import content）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  B-1  资源槽落点 = ctx["resource_state"][side]：M4 契约 resource_state 为
       battle_state 快照段（per-actor 数值型当前值），8C 负责快照时序落盘与
       恢复；本路作为运行时引擎**只读写**该段（战斗层接线时挂
       ctx["resource_state"]），缺省不存在时惰性建段挂回（对齐 _ps_init 形态）。
  B-2  注册表读取链：ctx["stats"] → ctx["resource_axes"] → ctx["stats_def"]；
       3e2 热重载后 stats 段形态（map 形态 entry_type="map"，键 = 属性 ID）
       与 6a 职业 resource_axes 段（list 形态条目带 id）兼容读取；缺省 → 空。
  B-3  any 键与具名键并存（K3 互斥本应校验器红拦）：运行时防御处理 = any 键
       优先（总量门），具名键忽略——不抛异常（校验红拦归批11 V7）。
  B-4  触发类 energy_cost 计数（D-03）：引擎不持有计数状态（proc 上限计数归
       1b effects 容器 max_triggers_per_turn/per_battle 现成），本路只返回
       {ok, applied}——不足 → {ok:False, applied:False}（调用方不计触发上限）；
       生效 → {ok:True, applied:True}（调用方计入上限）。语义保证：不足路径
       绝不消耗能量、绝不返回 applied:True。
  B-5  cost 扣减方案（cost_breakdown）：具名键逐池扣减 + any 余量按池序
       （pools 注册顺序）从富余池均摊（确定性，零随机）；返回 None = 总量
       不足/无法满足（调用方应走被拒路径，不半扣）。
  B-6  gain 负值防御钳 0（D-06/V3：负数=笔误校验器黄提示；运行时钳 0 不写
       负值，避免资源越界）；gain 值 0 = 无操作（不写事件不写审计）。
  B-7  上限 0=不限（§1.1 字段表 #5 max：0=不限）：数值型 max=0 时封顶跳过；
       max 缺省 100（字段表默认）；子池型 max_per_pool 缺省 3（元素法师实例值）。
  B-8  事件形态：本路产出 {type: "energy_gain"/"energy_cost", ...} 结构化
       事件列表（对齐 battle side_effects 惯例），接线方合入消息/审计；
       文案不写死模板（零模板输出，仅 reason 语义键）。

铁律：零 NoneBot import（G0 门禁）；core 层只依赖 data（本文件零 import
content/data，资源注册/技能数据经 ctx 注入）；纯函数确定性（同刻同参必同值）；
完整类型标注（typing 3.9 兼容）；零定时器/零睡眠（本文件不含任何 sleep/
定时器字面量——引擎零定时器零睡眠，无时间依赖）；不引入随机；不 git
commit；只写本文件 + 自己的测试。
"""
from __future__ import annotations

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Tuple,
)

# =====================================================================================
# 常量（细化_6c §1.1/§1.2 契约口径）
# =====================================================================================

# 资源轴 type 枚举（D-01b：resource_custom 为兼容别名，加载归一为 resource）
TYPE_RESOURCE: str = "resource"
TYPE_RESOURCE_CUSTOM: str = "resource_custom"

# reset 清零策略三枚举（§1.1 字段表 #6）
RESET_BATTLE: str = "battle"
RESET_KEEP: str = "keep"
RESET_BATTLE_START: str = "battle_start"
RESET_VALUES: Tuple[str, ...] = (RESET_BATTLE, RESET_KEEP, RESET_BATTLE_START)

# 数值型 max 缺省（字段表 #5 默认 100）；0 = 不限（B-7）
DEFAULT_MAX: int = 100
# 子池型 max_per_pool 缺省（元素法师实例值，B-7）
DEFAULT_MAX_PER_POOL: int = 3
# 子池型 base 缺省（元素法师示例各池初始 0）
DEFAULT_POOL_BASE: int = 0

# 资源槽段键（M4 §1.4：battle_state 顶层 resource_state；8C 同键，本地镜像防循环依赖）
RESOURCE_STATE_KEY: str = "resource_state"

# any 键（K2/D-02：任意池通用总量门，仅子池型合法）
ANY_KEY: str = "any"

# 事件类型（B-8 结构化事件形态）
EVENT_GAIN: str = "energy_gain"
EVENT_COST: str = "energy_cost"

# =====================================================================================
# 防御性读取辅助（类型校验 + 钳制，不抛异常——三铁律② 缺省兜底口径）
# =====================================================================================


def _norm_int(v: Any, default: int = 0) -> int:
    """整数归一（bool 除外）；非 int / 非法 → default（防御读取）。"""
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return default


def _norm_nonneg(v: Any, default: int = 0) -> int:
    """非负整数归一（负值钳 0）。"""
    return max(0, _norm_int(v, default))


def _norm_str(v: Any) -> str:
    """字符串归一：非 str → 空串（防御读取）。"""
    return v if isinstance(v, str) else ""


def _norm_str_list(v: Any) -> Tuple[str, ...]:
    """字符串列表归一：非 list → 空元组（防御读取）。"""
    if not isinstance(v, (list, tuple)):
        return ()
    return tuple(x for x in v if isinstance(x, str) and x)


def _norm_pools(v: Any) -> Tuple[str, ...]:
    """池枚举归一（去重保序，D-01 判别源）。"""
    return tuple(dict.fromkeys(_norm_str_list(v)))


# =====================================================================================
# ResourceAxis：两型注册段统一封装（D-01：pools 判别）
# =====================================================================================


class ResourceAxis:
    """两型资源轴统一封装（数值型 / 子池型，D-01 按 pools 判别）。

    字段（§1.1 字段表 1~10，防御读取）：name/type/icon/base/max/reset/display/
    max_per_pool/pools/pool_icons；type=resource_custom 归一为 resource（D-01b）；
    max 缺省 100、0=不限（B-7）；reset 缺省 battle。
    """

    __slots__ = (
        "_raw",
        "_name",
        "_type",
        "_icon",
        "_base",
        "_max",
        "_reset",
        "_display",
        "_max_per_pool",
        "_pools",
        "_pool_icons",
    )

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._raw = dict(raw) if isinstance(raw, Mapping) else {}
        self._name = _norm_str(self._raw.get("name"))
        self._type = _norm_str(self._raw.get("type")) or TYPE_RESOURCE
        if self._type == TYPE_RESOURCE_CUSTOM:
            self._type = TYPE_RESOURCE  # D-01b：兼容别名归一
        self._icon = _norm_str(self._raw.get("icon"))
        self._base = _norm_nonneg(self._raw.get("base"), 0)
        self._max = _norm_nonneg(self._raw.get("max"), DEFAULT_MAX)
        reset = _norm_str(self._raw.get("reset"))
        self._reset = reset if reset in RESET_VALUES else RESET_BATTLE
        self._display = _norm_str(self._raw.get("display"))
        self._max_per_pool = max(1, _norm_int(self._raw.get("max_per_pool"), DEFAULT_MAX_PER_POOL))
        self._pools = _norm_pools(self._raw.get("pools"))
        pi = self._raw.get("pool_icons")
        self._pool_icons: Dict[str, str] = {}
        if isinstance(pi, Mapping):
            for k, v in pi.items():
                if isinstance(k, str) and isinstance(v, str):
                    self._pool_icons[k] = v

    @property
    def id(self) -> str:  # noqa: A003
        """资源 ID（注册键，防御兜底 raw 内 id/name）。"""
        v = _norm_str(self._raw.get("id"))
        if v:
            return v
        return self._name

    @property
    def raw(self) -> Dict[str, Any]:
        """原始注册段副本（只读语义）。"""
        return dict(self._raw)

    @property
    def name(self) -> str:
        """显示名（缺省 ""）。"""
        return self._name

    @property
    def type(self) -> str:
        """归一后 type（恒 resource，D-01b）。"""
        return self._type

    @property
    def icon(self) -> str:
        """状态栏图标（缺省 ""）。"""
        return self._icon

    @property
    def base(self) -> int:
        """初始值（战斗开始值；子池型 = 各池初始值，缺省 0）。"""
        return self._base

    @property
    def max(self) -> int:
        """数值型封顶（0 = 不限，B-7）。"""
        return self._max

    @property
    def reset(self) -> str:
        """清零策略（battle/keep/battle_start，缺省 battle）。"""
        return self._reset

    @property
    def display(self) -> str:
        """状态栏可见性（status_line/hidden，缺省 ""）。"""
        return self._display

    @property
    def max_per_pool(self) -> int:
        """子池型：每池上限（≥1，缺省 3）。"""
        return self._max_per_pool

    @property
    def pools(self) -> Tuple[str, ...]:
        """子池型：池枚举（空元组 = 数值型，D-01 判别源）。"""
        return self._pools

    @property
    def pool_icons(self) -> Dict[str, str]:
        """子池型：池图标映射（键 = pools 池名）。"""
        return dict(self._pool_icons)

    @property
    def is_pooled(self) -> bool:
        """两型判别（D-01）：pools 非空 = 子池型。"""
        return bool(self._pools)

    def cap_of(self, key: str) -> int:
        """单键封顶：数值型 → max（0=不限）；子池型 → max_per_pool（池键）。"""
        if self.is_pooled:
            return self._max_per_pool if key in self._pools else 0
        return self._max

    def base_value(self) -> int:
        """初始值：数值型 → base；子池型 → base（各池初始值）。"""
        return self._base


def normalize_axis(raw: Mapping[str, Any]) -> ResourceAxis:
    """注册段 → ResourceAxis 防御归一（畸形值回落合理默认，不抛异常）。"""
    return ResourceAxis(raw)


def axis_of(ctx: Mapping[str, Any], axis_id: str) -> Optional[ResourceAxis]:
    """从 ctx 注入的注册表按资源 ID 定位注册条目（未注册 → None，RS-5 降级）。

    读取链（B-2）：ctx["stats"]（map 形态，键 = 属性 ID）→ ctx["resource_axes"]
    （list 形态，条目带 id）→ ctx["stats_def"]（6a 职业段）。任一形态取到即返。
    3e2 热重载后 stats 段键空间一致，按 ID 精确匹配（大小写敏感，D-06）。
    """
    if not isinstance(axis_id, str) or not axis_id:
        return None
    stats = ctx.get("stats")
    if isinstance(stats, Mapping):
        entry = stats.get(axis_id)
        if isinstance(entry, Mapping):
            return ResourceAxis(entry)
    ra = ctx.get("resource_axes")
    if isinstance(ra, (list, tuple)):
        for e in ra:
            if isinstance(e, Mapping) and _norm_str(e.get("id")) == axis_id:
                return ResourceAxis(e)
    sd = ctx.get("stats_def")
    if isinstance(sd, Mapping):
        entry = sd.get(axis_id)
        if isinstance(entry, Mapping):
            return ResourceAxis(entry)
    return None


def axes_of(ctx: Mapping[str, Any]) -> Dict[str, ResourceAxis]:
    """注册表全量 → {axis_id: ResourceAxis}（map/list 形态兼容，B-2）。"""
    out: Dict[str, ResourceAxis] = {}
    stats = ctx.get("stats")
    if isinstance(stats, Mapping):
        for k, v in stats.items():
            if isinstance(k, str) and isinstance(v, Mapping):
                out[k] = ResourceAxis(v)
    ra = ctx.get("resource_axes")
    if isinstance(ra, (list, tuple)):
        for e in ra:
            if isinstance(e, Mapping):
                aid = _norm_str(e.get("id"))
                if aid and aid not in out:
                    out[aid] = ResourceAxis(e)
    sd = ctx.get("stats_def")
    if isinstance(sd, Mapping):
        for k, v in sd.items():
            if isinstance(k, str) and isinstance(v, Mapping) and k not in out:
                out[k] = ResourceAxis(v)
    return out


# =====================================================================================
# 资源槽读写（两型统一接口：数值型单值 / 子池型池级，RS-6 池级原子粒度）
# =====================================================================================


def _persistent_state_of(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """persistent_state 可变容器定位（对齐 fishing.py/_ps_init 形态）。"""
    ps = ctx.get("persistent_state")
    if isinstance(ps, MutableMapping):
        return ps
    player = ctx.get("player")
    if isinstance(player, Mapping):
        ps2 = player.get("persistent_state")
        if isinstance(ps2, MutableMapping):
            return ps2
    if isinstance(ctx, MutableMapping):
        return ctx
    return None


def _resource_state_of(
    ctx: MutableMapping[str, Any],
    side: str = "player",
) -> MutableMapping[str, Any]:
    """资源槽段定位（B-1）：ctx["resource_state"][side] 惰性建段挂回。

    resource_state 段形态 = {side: {axis_id: value|{pool: value}}}（D-04 池级
    展开）；8C 快照时序落盘/恢复由接线方收口，本路只读写不落快照时序。
    """
    rs = ctx.get(RESOURCE_STATE_KEY)
    if not isinstance(rs, MutableMapping):
        rs = {}
        ps = _persistent_state_of(ctx)
        if isinstance(ps, MutableMapping):
            ps[RESOURCE_STATE_KEY] = rs
        ctx[RESOURCE_STATE_KEY] = rs
    seg = rs.get(side)
    if not isinstance(seg, MutableMapping):
        seg = {}
        rs[side] = seg
    return seg


def _pool_values(seg: MutableMapping[str, Any], axis_id: str) -> MutableMapping[str, Any]:
    """子池型池级段定位（池级原子粒度，RS-6）：seg[axis_id] 恒为 {pool: value}。"""
    node = seg.get(axis_id)
    if not isinstance(node, MutableMapping):
        node = {}
        seg[axis_id] = node
    return node


def get_value(
    ctx: Mapping[str, Any],
    axis_id: str,
    key: Optional[str] = None,
    side: str = "player",
) -> int:
    """统一读取（数值型单值 / 子池型池级，缺省回落 base）。

    - 数值型：key=None → 轴单值；key 非 None → 0（数值型无池键）。
    - 子池型：key=None → 0（池级轴本身无单值）；key=池名 → 该池值。
    - 槽缺失 / 注册缺失 / 值非 int → 回落 base（RS-5 降级语义：不报错不悬空）。
    """
    axis = axis_of(ctx, axis_id)
    base = axis.base_value() if axis is not None else 0
    seg = _resource_state_of(ctx, side)  # type: ignore[arg-type]
    if axis is not None and axis.is_pooled:
        if key is None:
            return 0
        if key not in axis.pools:
            return 0
        node = seg.get(axis_id)
        if isinstance(node, Mapping):
            return _norm_int(node.get(key), base)
        return base
    if key is not None:
        return 0
    return _norm_int(seg.get(axis_id), base)


def set_value(
    ctx: MutableMapping[str, Any],
    axis_id: str,
    value: int,
    key: Optional[str] = None,
    side: str = "player",
) -> Dict[str, Any]:
    """统一写入（数值型单值 / 子池型池级，钳制非负；返回 {ok, axis, key, value}）。

    子池型 key=None 时按池序全池置 base（对齐战斗开始语义）；池名非法 → 拒绝
    {ok:False}（不抛异常）。未注册资源 → 降级写入槽段（RS-5：注册已删仍可
    按字段缺失降级，不报错不悬空；8C 恢复同口径）。
    """
    axis = axis_of(ctx, axis_id)
    seg = _resource_state_of(ctx, side)
    if axis is not None and axis.is_pooled:
        if key is None:
            base = axis.base_value()
            node: MutableMapping[str, Any] = {}
            for p in axis.pools:
                node[p] = base
            seg[axis_id] = node
            return {"ok": True, "axis": axis_id, "key": None, "value": base}
        if key not in axis.pools:
            return {"ok": False, "axis": axis_id, "key": key, "value": value,
                    "reason": "unknown_pool"}
        node = _pool_values(seg, axis_id)
        node[key] = max(0, _norm_int(value, 0))
        return {"ok": True, "axis": axis_id, "key": key, "value": node[key]}
    if key is not None:
        return {"ok": False, "axis": axis_id, "key": key, "value": value,
                "reason": "no_pool_key_for_numeric"}
    seg[axis_id] = max(0, _norm_int(value, 0))
    return {"ok": True, "axis": axis_id, "key": None, "value": seg[axis_id]}


def add_value(
    ctx: MutableMapping[str, Any],
    axis_id: str,
    delta: int,
    key: Optional[str] = None,
    side: str = "player",
) -> Dict[str, Any]:
    """统一增减（数值型单值 / 子池型池级，追加后封顶；返回 {ok, before, after, capped}）。

    封顶（§1.3 成功结算段）：数值型 ≤ max（0=不限，B-7）；子池型每池 ≤
    max_per_pool——超出部分不累计不回滚（TC-02③/TC-08②）。未注册资源 → 无
    封顶信息按注册缺失降级（RS-5）：仅钳非负，不封顶不报错。
    """
    axis = axis_of(ctx, axis_id)
    delta = _norm_int(delta, 0)
    seg = _resource_state_of(ctx, side)
    if axis is not None and axis.is_pooled:
        if key is None or key not in axis.pools:
            return {"ok": False, "axis": axis_id, "key": key, "delta": delta,
                    "reason": "unknown_pool"}
        node = _pool_values(seg, axis_id)
        before = _norm_int(node.get(key), axis.base_value())
        after = max(0, before + delta)
        cap = axis.max_per_pool
        capped = after > cap
        if capped:
            after = cap
        node[key] = after
        return {"ok": True, "axis": axis_id, "key": key, "delta": delta,
                "before": before, "after": after, "capped": capped}
    if key is not None:
        return {"ok": False, "axis": axis_id, "key": key, "delta": delta,
                "reason": "no_pool_key_for_numeric"}
    before = _norm_int(seg.get(axis_id), axis.base_value() if axis is not None else 0)
    after = max(0, before + delta)
    capped = False
    if axis is not None and axis.max > 0:
        capped = after > axis.max
        if capped:
            after = axis.max
    seg[axis_id] = after
    return {"ok": True, "axis": axis_id, "key": None, "delta": delta,
            "before": before, "after": after, "capped": capped}


def total_of(ctx: Mapping[str, Any], axis_id: str, side: str = "player") -> int:
    """子池型总量（各池和，D-04 展示键 [我方资源:axis] 数据源）；数值型 = 单值。"""
    axis = axis_of(ctx, axis_id)
    seg = _resource_state_of(ctx, side)  # type: ignore[arg-type]
    if axis is not None and axis.is_pooled:
        node = seg.get(axis_id)
        if not isinstance(node, Mapping):
            return 0
        total = 0
        for p in axis.pools:
            total += _norm_int(node.get(p), axis.base_value())
        return total
    return _norm_int(seg.get(axis_id), axis.base_value() if axis is not None else 0)


# =====================================================================================
# energy_cost 施放前检查（M2 E2 / F-R1 施放前段；不足 → 被拒不耗回合）
# =====================================================================================


def _cost_map_of(segment: Any) -> Dict[str, int]:
    """energy_gain/energy_cost 段防御归一：非 Mapping → 空；键 → 非负 int。

    负值钳 0（D-06 运行时防御，V3 校验器黄提示归批11）；0 值键保留（D-06：
    0 = 无操作，由调用方跳过）；键大小写敏感（K6）。
    """
    if not isinstance(segment, Mapping):
        return {}
    out: Dict[str, int] = {}
    for k, v in segment.items():
        if isinstance(k, str) and k:
            out[k] = _norm_nonneg(v, 0)
    return out


def check_cost(
    ctx: Mapping[str, Any],
    axis_id: str,
    cost: Mapping[str, int],
    side: str = "player",
) -> Dict[str, Any]:
    """energy_cost 施放前检查（E2/K1-K3/D-02）：不足 → 被拒不耗回合。

    判定（确定性，短路返回）：
      - cost 空（{}/None）→ ok（无消耗）；0 值键 = 无操作（D-06）；
      - 数值型（K1）：具名键 = 资源 ID，要求 当前值 ≥ 消耗；
      - 子池型（K2）：具名键 = 池名，要求 该池 ≥ 消耗；any:n = 总量门
        （D-02：任意池合计 ≥ n）；any 与具名键并存时 any 优先（B-3）；
      - 未注册资源 → 降级放行 ok（RS-5：注册缺失不报错；校验红拦归 V1）。
    返回 {ok, reason, missing: [{axis, key, need, have}]}（reason 语义键，
    文案模板化归接线方，B-8）。
    """
    cost_map = _cost_map_of(cost)
    if not cost_map:
        return {"ok": True, "reason": "", "missing": []}
    axis = axis_of(ctx, axis_id)
    if axis is None:
        # RS-5 降级：注册已删 → 该资源无增减不报错不悬空
        return {"ok": True, "reason": "", "missing": []}
    missing: List[Dict[str, Any]] = []
    if axis.is_pooled:
        if ANY_KEY in cost_map:
            need = cost_map[ANY_KEY]
            if need > 0:
                have = total_of(ctx, axis_id, side)
                if have < need:
                    missing.append({"axis": axis_id, "key": ANY_KEY,
                                    "need": need, "have": have})
        else:
            for key, need in cost_map.items():
                if need <= 0:
                    continue
                if key not in axis.pools:
                    continue  # 未知池键跳过（V8 校验红拦归批11，运行时防御）
                have = get_value(ctx, axis_id, key, side)
                if have < need:
                    missing.append({"axis": axis_id, "key": key,
                                    "need": need, "have": have})
    else:
        for key, need in cost_map.items():
            if need <= 0:
                continue
            have = get_value(ctx, axis_id, None, side)
            if have < need:
                missing.append({"axis": axis_id, "key": key,
                                "need": need, "have": have})
    if missing:
        return {"ok": False, "reason": "energy_insufficient", "missing": missing}
    return {"ok": True, "reason": "", "missing": []}


def cost_breakdown(
    ctx: Mapping[str, Any],
    axis_id: str,
    cost: Mapping[str, int],
    side: str = "player",
) -> Optional[List[Dict[str, Any]]]:
    """子池型消耗扣减方案（B-5，F-C2 按锁定组合行扣池复用）。

    具名键逐池扣减（该池值 ≥ 消耗才可行）+ any 余量按池序（pools 注册顺序）
    从**非具名消耗池**（any 覆盖池，未出现在具名键中的池）均摊——具名键
    已显式锁定的池不参与 any 均摊（防双扣同池：具名键锁定的池值已被扣减，
    不再作为 any 富余源）。返回 [{"pool": p, "amount": n}, ...]；总量不足 /
    数值型调用 / 无法满足 → None（调用方应走被拒路径，不半扣）。
    """
    cost_map = _cost_map_of(cost)
    if not cost_map:
        return []
    axis = axis_of(ctx, axis_id)
    if axis is None or not axis.is_pooled:
        return None
    seg = _resource_state_of(ctx, side)  # type: ignore[arg-type]
    node = seg.get(axis_id)
    if not isinstance(node, Mapping):
        node = {}
    avail: Dict[str, int] = {}
    for p in axis.pools:
        avail[p] = _norm_int(node.get(p), axis.base_value())
    plan: List[Dict[str, Any]] = []
    named_total = 0
    named_keys: List[str] = []
    if ANY_KEY in cost_map:
        named_total = cost_map[ANY_KEY]
    else:
        for key, need in cost_map.items():
            if need <= 0:
                continue
            if key not in axis.pools:
                return None  # 未知池键 → 无法满足（V8 红拦归批11）
            if avail[key] < need:
                return None  # 具名池不足 → 不半扣
            avail[key] -= need
            named_keys.append(key)
            plan.append({"pool": key, "amount": need})
    if named_total > 0:
        remaining = named_total
        for p in axis.pools:
            if remaining <= 0:
                break
            if p in named_keys:
                continue  # 具名键已锁定扣减的池不参与 any 均摊（防双扣同池）
            take = min(avail[p], remaining)
            if take > 0:
                avail[p] -= take
                remaining -= take
                plan.append({"pool": p, "amount": take})
        if remaining > 0:
            return None  # 总量不足 → 不半扣
    return plan


def pay_cost(
    ctx: MutableMapping[str, Any],
    axis_id: str,
    cost: Mapping[str, int],
    side: str = "player",
) -> Dict[str, Any]:
    """施放成功扣减（原子：先 check 后 pay，不半扣；返回 {ok, paid, events}）。

    数值型：扣单值（不足 → 拒绝，调用方应已先 check）；子池型：按
    cost_breakdown 方案扣池（无方案 → 拒绝）。扣减后钳非负（防御）。
    返回结构化事件（B-8）供消息/审计。
    """
    cost_map = _cost_map_of(cost)
    if not cost_map:
        return {"ok": True, "paid": [], "events": []}
    axis = axis_of(ctx, axis_id)
    if axis is None:
        return {"ok": False, "paid": [], "events": [], "reason": "axis_missing"}
    events: List[Dict[str, Any]] = []
    if axis.is_pooled:
        plan = cost_breakdown(ctx, axis_id, cost, side)
        if plan is None:
            return {"ok": False, "paid": [], "events": [], "reason": "insufficient"}
        seg = _resource_state_of(ctx, side)
        node = _pool_values(seg, axis_id)
        paid: List[Dict[str, Any]] = []
        for item in plan:
            p = _norm_str(item.get("pool"))
            amt = _norm_nonneg(item.get("amount"), 0)
            if not p or amt <= 0:
                continue
            before = _norm_int(node.get(p), axis.base_value())
            after = max(0, before - amt)
            node[p] = after
            paid.append({"pool": p, "amount": amt, "before": before, "after": after})
            events.append({"type": EVENT_COST, "axis": axis_id, "key": p,
                           "amount": amt, "before": before, "after": after})
        return {"ok": True, "paid": paid, "events": events}
    need = 0
    for key, v in cost_map.items():
        if v > 0:
            need = v
            break
    seg = _resource_state_of(ctx, side)
    before = _norm_int(seg.get(axis_id), axis.base_value())
    if before < need:
        return {"ok": False, "paid": [], "events": [], "reason": "insufficient"}
    after = before - need
    seg[axis_id] = after
    events.append({"type": EVENT_COST, "axis": axis_id, "key": None,
                   "amount": need, "before": before, "after": after})
    return {"ok": True, "paid": [{"key": None, "amount": need,
                                  "before": before, "after": after}],
            "events": events}


# =====================================================================================
# energy_gain 结算（M2 E1 / §1.3 成功结算段；与 mark_add 同拍，命中判定后）
# =====================================================================================


def gain_energy(
    ctx: MutableMapping[str, Any],
    axis_id: str,
    gain: Mapping[str, int],
    side: str = "player",
    source: str = "skill",
) -> Dict[str, Any]:
    """单资源轴 energy_gain 追加（E1/K6/B-6）：封顶后写回，返回 {ok, gained, events}。

    - 多键并存（K6 可同时多资源增减）由 apply_gain 逐轴调用；本函数处理单轴：
      数值型键 = 资源 ID（K1）；子池型键 = 池名（K2，any 键对 gain 无意义跳过）；
    - 值 0 = 无操作（D-06）；负值钳 0（B-6，V3 黄提示归批11）；
    - 封顶（§1.3）：数值型 ≤ max（0=不限）；子池型每池 ≤ max_per_pool，超出
      部分不累计不回滚（TC-02③/TC-08②）；
    - 未注册资源 → 降级跳过不报错（RS-5；V1 红拦归批11）。
    """
    gain_map = _cost_map_of(gain)
    if not gain_map:
        return {"ok": True, "gained": [], "events": []}
    axis = axis_of(ctx, axis_id)
    if axis is None:
        return {"ok": True, "gained": [], "events": [], "reason": "axis_missing"}
    events: List[Dict[str, Any]] = []
    gained: List[Dict[str, Any]] = []
    if axis.is_pooled:
        for key, amount in gain_map.items():
            if amount <= 0 or key == ANY_KEY or key not in axis.pools:
                continue  # 0 无操作（D-06）；any 对 gain 无意义（K2）；未知池跳过
            r = add_value(ctx, axis_id, amount, key=key, side=side)
            gained.append({"key": key, "amount": amount,
                           "before": r.get("before"), "after": r.get("after"),
                           "capped": r.get("capped", False)})
            events.append({"type": EVENT_GAIN, "axis": axis_id, "key": key,
                           "amount": amount, "before": r.get("before"),
                           "after": r.get("after"), "capped": r.get("capped", False),
                           "source": source})
        return {"ok": True, "gained": gained, "events": events}
    for key, amount in gain_map.items():
        if amount <= 0:
            continue  # 0 无操作（D-06）
        r = add_value(ctx, axis_id, amount, key=None, side=side)
        gained.append({"key": key, "amount": amount,
                       "before": r.get("before"), "after": r.get("after"),
                       "capped": r.get("capped", False)})
        events.append({"type": EVENT_GAIN, "axis": axis_id, "key": key,
                       "amount": amount, "before": r.get("before"),
                       "after": r.get("after"), "capped": r.get("capped", False),
                       "source": source})
        break  # 数值型单值：只取首个正键（多键并存防御）
    return {"ok": True, "gained": gained, "events": events}


def apply_gain(
    ctx: MutableMapping[str, Any],
    energy_gain: Any,
    side: str = "player",
    source: str = "skill",
) -> Dict[str, Any]:
    """技能/派生/proc 的 energy_gain 段批量结算（E1/K6：可同时多资源增减）。

    energy_gain 段 = {axis_id: {key: amount}} 或 {axis_id: amount}（数值型
    简写）——两种形态均防御接受（契约 §1.2 字段表 map（资源键→int）为准，
    简写形态为工程补白 B-9 兼容 6a 技能库既有写法）。返回 {ok, gained, events}。
    """
    if not isinstance(energy_gain, Mapping):
        return {"ok": True, "gained": [], "events": []}
    events: List[Dict[str, Any]] = []
    gained: List[Dict[str, Any]] = []
    for axis_id, value in energy_gain.items():
        if not isinstance(axis_id, str) or not axis_id:
            continue
        if isinstance(value, Mapping):
            r = gain_energy(ctx, axis_id, value, side=side, source=source)
        else:
            r = gain_energy(ctx, axis_id, {axis_id: _norm_nonneg(value, 0)},
                            side=side, source=source)
        gained.extend(r.get("gained", []))
        events.extend(r.get("events", []))
    return {"ok": True, "gained": gained, "events": events}


# =====================================================================================
# 触发类 energy_cost 语义（D-03：触发事件发生时检查；不足 → 不生效不耗不计上限）
# =====================================================================================


def check_trigger_cost(
    ctx: Mapping[str, Any],
    energy_cost: Any,
    side: str = "player",
) -> Dict[str, Any]:
    """触发类 energy_cost 检查（D-03）：不足 → 本次触发不生效、不耗、不计上限。

    与主动技能 check_cost 同构（E2 语义 + 触发时点），但返回契约对齐 D-03：
      - ok=True（能量足）→ 触发可生效，调用方执行效果并**计入**「每回合 N 次」
        上限（TC-06③：生效后才计数）；
      - ok=False（不足）→ 本次触发不生效、不耗能量、**不计**触发上限
        （调用方跳过效果且不计数）。
    energy_cost 段 = {axis_id: {key: amount}}（多资源）或 {axis_id: amount}
    （简写，B-9）；空/无消耗 → ok。
    """
    if not isinstance(energy_cost, Mapping) or not energy_cost:
        return {"ok": True, "missing": []}
    missing: List[Dict[str, Any]] = []
    for axis_id, value in energy_cost.items():
        if not isinstance(axis_id, str) or not axis_id:
            continue
        if isinstance(value, Mapping):
            r = check_cost(ctx, axis_id, value, side=side)
        else:
            r = check_cost(ctx, axis_id, {axis_id: _norm_nonneg(value, 0)}, side=side)
        if not r.get("ok"):
            missing.extend(r.get("missing", []))
    if missing:
        return {"ok": False, "reason": "energy_insufficient", "missing": missing}
    return {"ok": True, "reason": "", "missing": []}


def pay_trigger_cost(
    ctx: MutableMapping[str, Any],
    energy_cost: Any,
    side: str = "player",
    source: str = "trigger",
) -> Dict[str, Any]:
    """触发类 energy_cost 扣减（D-03 生效路径）：先 check 后 pay（原子）。

    仅当 check_trigger_cost ok 时调用（生效才耗）；不足路径绝不耗能量
    （B-4）。返回 {ok, paid, events}；未注册资源降级不扣不报错（RS-5）。
    """
    if not isinstance(energy_cost, Mapping) or not energy_cost:
        return {"ok": True, "paid": [], "events": []}
    gate = check_trigger_cost(ctx, energy_cost, side=side)
    if not gate.get("ok"):
        return {"ok": False, "paid": [], "events": [], "reason": "insufficient"}
    paid: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    for axis_id, value in energy_cost.items():
        if not isinstance(axis_id, str) or not axis_id:
            continue
        if isinstance(value, Mapping):
            r = pay_cost(ctx, axis_id, value, side=side)
        else:
            r = pay_cost(ctx, axis_id, {axis_id: _norm_nonneg(value, 0)}, side=side)
        if not r.get("ok"):
            return {"ok": False, "paid": paid, "events": events, "reason": "insufficient"}
        paid.extend(r.get("paid", []))
        events.extend(r.get("events", []))
    return {"ok": True, "paid": paid, "events": events}


def trigger_energy_cost(
    ctx: MutableMapping[str, Any],
    energy_cost: Any,
    side: str = "player",
    source: str = "trigger",
) -> Dict[str, Any]:
    """触发类 energy_cost 一站式判定（D-03 完整语义，TC-06③ 断言口径）。

    返回 {ok, applied, missing, paid, events}：
      - ok=True + applied=True：能量足且已扣（生效路径，调用方计入触发上限）；
      - ok=False + applied=False：不足 → 不生效、不耗、不计上限（D-03，
        调用方不计触发上限）；ok=False 且 applied=False 时绝不消耗能量。
    """
    gate = check_trigger_cost(ctx, energy_cost, side=side)
    if not gate.get("ok"):
        return {"ok": False, "applied": False, "missing": gate.get("missing", []),
                "paid": [], "events": []}
    r = pay_trigger_cost(ctx, energy_cost, side=side, source=source)
    if not r.get("ok"):
        return {"ok": False, "applied": False, "missing": [],
                "paid": [], "events": []}
    return {"ok": True, "applied": True, "missing": [],
            "paid": r.get("paid", []), "events": r.get("events", [])}


# =====================================================================================
# 技能级便捷入口（skill def 的 energy_gain/energy_cost 段，G0 注入）
# =====================================================================================


def _segment_of(skill: Any, key: str) -> Any:
    """skill def 段读取：Mapping 直取；协议对象（hasattr）属性取；缺省 None。"""
    if isinstance(skill, Mapping):
        return skill.get(key)
    if skill is not None and hasattr(skill, key):
        v = getattr(skill, key)
        return v() if callable(v) else v
    return None


def check_skill_cost(
    ctx: Mapping[str, Any],
    skill: Any,
    side: str = "player",
) -> Dict[str, Any]:
    """技能施放前 energy_cost 总检查（skill def 段，K4 与 mp_cost 互补并存）。

    返回 {ok, reason, missing, axes}；axes = 本次涉及的资源轴 ID 列表（供
    接线方组合消息）。energy_cost 段缺省/空 → ok（无资源消耗）。
    """
    seg = _segment_of(skill, "energy_cost")
    if not isinstance(seg, Mapping) or not seg:
        return {"ok": True, "reason": "", "missing": [], "axes": []}
    missing: List[Dict[str, Any]] = []
    axes: List[str] = []
    for axis_id, value in seg.items():
        if not isinstance(axis_id, str) or not axis_id:
            continue
        axes.append(axis_id)
        if isinstance(value, Mapping):
            r = check_cost(ctx, axis_id, value, side=side)
        else:
            r = check_cost(ctx, axis_id, {axis_id: _norm_nonneg(value, 0)}, side=side)
        if not r.get("ok"):
            missing.extend(r.get("missing", []))
    if missing:
        return {"ok": False, "reason": "energy_insufficient",
                "missing": missing, "axes": axes}
    return {"ok": True, "reason": "", "missing": [], "axes": axes}


def pay_skill_cost(
    ctx: MutableMapping[str, Any],
    skill: Any,
    side: str = "player",
    source: str = "skill",
) -> Dict[str, Any]:
    """技能施放成功 energy_cost 扣减（先 check 后 pay 原子；返回 {ok, paid, events}）。"""
    seg = _segment_of(skill, "energy_cost")
    if not isinstance(seg, Mapping) or not seg:
        return {"ok": True, "paid": [], "events": []}
    gate = check_skill_cost(ctx, skill, side=side)
    if not gate.get("ok"):
        return {"ok": False, "paid": [], "events": [], "reason": "insufficient"}
    paid: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    for axis_id, value in seg.items():
        if not isinstance(axis_id, str) or not axis_id:
            continue
        if isinstance(value, Mapping):
            r = pay_cost(ctx, axis_id, value, side=side)
        else:
            r = pay_cost(ctx, axis_id, {axis_id: _norm_nonneg(value, 0)}, side=side)
        if not r.get("ok"):
            return {"ok": False, "paid": paid, "events": events, "reason": "insufficient"}
        paid.extend(r.get("paid", []))
        events.extend(r.get("events", []))
    return {"ok": True, "paid": paid, "events": events}


def gain_skill_energy(
    ctx: MutableMapping[str, Any],
    skill: Any,
    side: str = "player",
    source: str = "skill",
) -> Dict[str, Any]:
    """技能成功结算 energy_gain 追加（与 mark_add 同拍：命中判定后/结算末尾）。

    skill def 的 energy_gain 段 = {axis_id: {key: amount}}（契约形态）或
    {axis_id: amount}（简写，B-9）；段缺省/空 → 无操作。返回 {ok, gained, events}。
    """
    seg = _segment_of(skill, "energy_gain")
    if not isinstance(seg, Mapping) or not seg:
        return {"ok": True, "gained": [], "events": []}
    return apply_gain(ctx, seg, side=side, source=source)


# =====================================================================================
# ResourceAxisEngine（引擎注入模式：构造器注入 stats / resource_state，缺省 ctx 兜底）
# =====================================================================================


class ResourceAxisEngine:
    """资源轴运行引擎（对齐 fishing.py / transform.py 注入模式）。

    构造器注入（均可缺省，缺省 → 运行时读 ctx）：
      stats:           注册表（map 形态 {axis_id: raw} 或 list 形态条目带 id；
                       缺省读 ctx["stats"] → ctx["resource_axes"] → ctx["stats_def"]）。
      resource_state:  战斗资源槽（{side: {axis_id: value|{pool: value}}}；
                       缺省读 ctx["resource_state"]，不存在惰性建段挂回，B-1）。
      audit:           审计观察口 callable(str)（记录 ok/axis/事件摘要）。

    方法（技能级便捷入口，skill def 经 ctx 注入 G0）：
      check(skill, side)   —— 施放前 energy_cost 检查（不足 → 被拒不耗回合）；
      pay(skill, side)     —— 施放成功 energy_cost 扣减（原子）；
      gain(skill, side)    —— 成功结算 energy_gain 追加（封顶）；
      check_trigger / pay_trigger / trigger_energy —— D-03 触发类语义；
      gain_axis / pay_axis —— 轴级直接增减（proc/派生内部调用）。
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
            ctx.setdefault(RESOURCE_STATE_KEY, self._resource_state)
        return ctx

    def _audit_log(self, message: str) -> None:
        if self._audit is not None:
            self._audit(message)

    # ---- 技能级 ----
    def check(
        self, ctx: MutableMapping[str, Any], skill: Any, side: str = "player"
    ) -> Dict[str, Any]:
        """施放前 energy_cost 检查（不足 → 被拒不耗回合，复用 should_reject 管道语义）。"""
        result = check_skill_cost(self._inject(ctx), skill, side=side)
        self._audit_log("resource_cost_check: ok=%s axes=%s" % (
            result.get("ok"), ",".join(result.get("axes", []))))
        return result

    def pay(
        self, ctx: MutableMapping[str, Any], skill: Any, side: str = "player"
    ) -> Dict[str, Any]:
        """施放成功 energy_cost 扣减（原子：先 check 后 pay，不半扣）。"""
        result = pay_skill_cost(self._inject(ctx), skill, side=side, source="skill")
        self._audit_log("resource_cost_pay: ok=%s paid=%s" % (
            result.get("ok"), len(result.get("paid", []))))
        return result

    def gain(
        self, ctx: MutableMapping[str, Any], skill: Any, side: str = "player"
    ) -> Dict[str, Any]:
        """成功结算 energy_gain 追加（封顶 ≤max/max_per_pool，超出不累计不回滚）。"""
        result = gain_skill_energy(self._inject(ctx), skill, side=side, source="skill")
        self._audit_log("resource_gain: ok=%s gained=%s" % (
            result.get("ok"), len(result.get("gained", []))))
        return result

    # ---- 触发类（D-03）----
    def check_trigger(
        self, ctx: MutableMapping[str, Any], skill: Any, side: str = "player"
    ) -> Dict[str, Any]:
        """触发类 energy_cost 检查（D-03：不足 → 本次触发不生效、不耗、不计上限）。"""
        seg = _segment_of(skill, "energy_cost")
        result = check_trigger_cost(self._inject(ctx), seg, side=side)
        self._audit_log("resource_trigger_check: ok=%s" % result.get("ok"))
        return result

    def pay_trigger(
        self, ctx: MutableMapping[str, Any], skill: Any, side: str = "player"
    ) -> Dict[str, Any]:
        """触发类 energy_cost 扣减（生效路径；不足绝不耗能量，B-4）。"""
        seg = _segment_of(skill, "energy_cost")
        result = pay_trigger_cost(self._inject(ctx), seg, side=side, source="trigger")
        self._audit_log("resource_trigger_pay: ok=%s" % result.get("ok"))
        return result

    def trigger_energy(
        self, ctx: MutableMapping[str, Any], skill: Any, side: str = "player"
    ) -> Dict[str, Any]:
        """触发类 energy_cost 一站式判定（D-03 完整语义：applied 标志供计数）。"""
        seg = _segment_of(skill, "energy_cost")
        result = trigger_energy_cost(self._inject(ctx), seg, side=side, source="trigger")
        self._audit_log("resource_trigger: ok=%s applied=%s" % (
            result.get("ok"), result.get("applied")))
        return result

    # ---- 轴级（proc/派生内部调用）----
    def gain_axis(
        self,
        ctx: MutableMapping[str, Any],
        axis_id: str,
        gain: Mapping[str, int],
        side: str = "player",
        source: str = "proc",
    ) -> Dict[str, Any]:
        """轴级 energy_gain 追加（proc 容器内增减同规则，§1.3 proc 时点）。"""
        result = gain_energy(self._inject(ctx), axis_id, gain, side=side, source=source)
        self._audit_log("resource_gain_axis: ok=%s axis=%s" % (result.get("ok"), axis_id))
        return result

    def pay_axis(
        self,
        ctx: MutableMapping[str, Any],
        axis_id: str,
        cost: Mapping[str, int],
        side: str = "player",
    ) -> Dict[str, Any]:
        """轴级 energy_cost 扣减（主动路径，不足拒绝不半扣）。"""
        result = pay_cost(self._inject(ctx), axis_id, cost, side=side)
        self._audit_log("resource_pay_axis: ok=%s axis=%s" % (result.get("ok"), axis_id))
        return result


__all__ = [
    # 常量
    "TYPE_RESOURCE",
    "TYPE_RESOURCE_CUSTOM",
    "RESET_BATTLE",
    "RESET_KEEP",
    "RESET_BATTLE_START",
    "RESET_VALUES",
    "DEFAULT_MAX",
    "DEFAULT_MAX_PER_POOL",
    "DEFAULT_POOL_BASE",
    "RESOURCE_STATE_KEY",
    "ANY_KEY",
    "EVENT_GAIN",
    "EVENT_COST",
    # 注册段封装
    "ResourceAxis",
    "normalize_axis",
    "axis_of",
    "axes_of",
    # 统一读写
    "get_value",
    "set_value",
    "add_value",
    "total_of",
    # energy_cost
    "check_cost",
    "cost_breakdown",
    "pay_cost",
    # energy_gain
    "gain_energy",
    "apply_gain",
    # 触发类（D-03）
    "check_trigger_cost",
    "pay_trigger_cost",
    "trigger_energy_cost",
    # 技能级入口
    "check_skill_cost",
    "pay_skill_cost",
    "gain_skill_energy",
    # 引擎
    "ResourceAxisEngine",
]
