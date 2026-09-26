"""通用效果事件分派器（qbot_rpg/core/event_dispatcher.py · 功能三批 1）。

依据：docs/框架_功能三_通用效果事件分派器_设计.md（§2.1 事件枚举 / §2.2 数据源 /
§2.3 分派器核心 / §四 验收 / §五 风险）——把散落的硬编码时点特例（battle_start /
on_death / 季节 / 状态施加移除）收敛为统一可配置事件分派。

定位：纯规则引擎，零 NoneBot、零跨层 import（可 import 同 core 层 effects）。
不持有状态：快照/注册表/EffectRuntime 全注入。未配置事件 / 无候选 → []（零行为变化）。

数据源（纯配置，两处）：
  A. effects.json 条目带 `trigger` 字段（值 ∈ EVENT_POINTS）→ 该事件时执行其 actions：
     {"id":"thorns","class":"special","type":"pursuit","trigger":"on_hit",
      "actions":[...]}
     （effects 定义形态：class=special/L2 带 actions 容器；trigger 事件字段 1b §2.5）
  B. statuses.json 条目带 `on_gain`/`on_lose`/`on_expire`（值 = 效果引用列表
     [{"effect": id, "overrides": {...}}] 或 actions 列表）→ 状态获得/消失/过期时触发：
     {"id":"shield_break","type":"buff","on_lose":[{"effect":"explode_damage"}]}
     （status 定义既有 on_tick/effects 字段先例，test_demo statuses.json）
  C. 装配注入 procs（season_procs 同款形态，可选）——ctx_vars 传 procs 列表。

chance 三态 / 每次行动每场上限 / 递归深度：全部复用 effects.EffectRuntime 既有语义
（increment_trigger / trigger_counts / reset_turn_triggers / config.max_triggers_* /
config.chain_depth / _chance_roll）。效果动作执行复用 execute_action（功能二引用归一
+ condition 门控已通）。

事件时点枚举（EVENT_POINTS，模块级常量）：
  battle_start / battle_end / action_start / action_end / turn_start / turn_end /
  status_gain / status_lose / mark_gain / mark_lose / death / revive /
  on_attack / on_hit / on_skill / on_kill / season_change
（与 1b §2.5 effects trigger 事件枚举对齐；on_tick 特例二期收编，本期不接）

批51 补点 `on_kill` 的语义（**与 `death` 分清，不得混用**）：
  · `death`   = **任一侧死亡**，派发给**死者自己**（副作用的 target 相对死者侧）；
  · `on_kill` = **我击杀敌**，派发给**击杀者侧**（1v1 里的另一侧）——「击杀回血
    /击杀叠层/击杀免冷却」这类特效写 `on_kill`；写 `death` 会挂到死者身上。
  两者都在 `battle._death_check_side` 的唯一死亡判定点派发（`dead_mark` 门控，
  每次击杀恰好一次；同归于尽/战斗已结束 → 不派发 on_kill）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# 2026-09-10 环打破：DamageCtx / chance_roll 自 effects 下沉至 core/effect_types.py，
# 本模块改为顶层单向引入（原「函数内 lazy import effects」是环的补丁，现依赖方向为
# effect_types ← event_dispatcher，与 effects 同向，环已消除）。
from qbot_rpg.core.effect_types import DamageCtx, chance_roll
# 2026-09-10 环打破：本模块 → effects 为单向依赖（effects 已改为回调注入，不再
# reverse import 本模块），故此处可由原「函数内 lazy import」提升为顶层 import。
from qbot_rpg.core.effects import execute_action, register_event_dispatcher
from qbot_rpg.data.event_points import (
    EVENT_POINT_INDEX,
    EVENT_POINT_TABLE,
    EVENT_POINTS as EVENT_POINTS_SOURCE,
    is_dispatched,
    undispatched_points,
)

__all__ = [
    "EVENT_POINTS",
    "EVENT_POINT_TABLE",
    "EVENT_POINT_INDEX",
    "is_dispatched",
    "undispatched_points",
    "dispatch_event",
]

# 效果定义 trigger 字段键 / 状态定义 on_xxx 字段键（零硬编码，常量集中）
TRIGGER_KEY: str = "trigger"
ON_GAIN_KEY: str = "on_gain"
ON_LOSE_KEY: str = "on_lose"
ON_EXPIRE_KEY: str = "on_expire"
ACTIONS_KEY: str = "actions"

# 事件时点权威枚举（批51：唯一源迁至 data 层 `data/event_points.py`——使 content 层
# 校验器可按分层契约 `content → {data}` 校验 trigger 取值域而无需反向 import core；
# 本模块**原样再导出**，`from qbot_rpg.core.event_dispatcher import EVENT_POINTS` 不变）。
EVENT_POINTS: Tuple[str, ...] = EVENT_POINTS_SOURCE

# 状态定义 on_xxx 事件键 → 触发事件映射（status 条目声明在 on_gain/on_lose/on_expire）
_STATUS_EVENT_KEYS: Dict[str, str] = {
    ON_GAIN_KEY: "status_gain",
    ON_LOSE_KEY: "status_lose",
    ON_EXPIRE_KEY: "status_lose",  # 过期归入消失语义（同一事件，来源区分在侧信息）
}

# 状态施加/消失的触发事件（dispatch_event 处理 status 条目 on_xxx 的入口事件）
_STATUS_POINTS: Tuple[str, ...] = ("status_gain", "status_lose")


def _iter_candidates(
    event: str,
    registry: Any,
    status_id: Optional[str] = None,
    owner_effect_ids: Optional[Sequence[str]] = None,
    claimed_effect_ids: Optional[Sequence[str]] = None,
) -> List[Tuple[str, Mapping[str, Any], str]]:
    """扫描注册表产出候选（effect_id, raw, kind）。

    - event 是纯效果事件（trigger 字段匹配）：遍历 effects 定义（kind="effect"），
      raw.get("trigger") == event → 候选；
    - event ∈ status_gain/status_lose：若给了 status_id，取该 status 定义对应
      on_gain/on_lose/on_expire 字段（值 = 效果引用列表）；未给 status_id →
      遍历全部 status 定义，收集 on_xxx 字段（供批 2 接线方按需过滤）。

    批51 · **归属过滤**（`owner_effect_ids` / `claimed_effect_ids`，纯效果事件分支）：
      · 两者皆 `None`（缺省）→ 全库扫描 = 本机制引入前的旧行为，逐字段一致（零变化基线）；
      · `owner_effect_ids` 给出 → 本侧**拥有**的 effect id 集（谁装备/谁施加的
        effect 只能由其宿主触发）；
      · `claimed_effect_ids` 给出 → **本场战斗内被任一持侧认领**的 effect id 全集；
        未被任何持侧认领的 effect 视为**全局效果**，对任何侧照常触发（避免归属
        过滤把既有全局触发静默吞掉——「登记了不生效 = 陷阱」的同族风险）。
      判定式：`eid ∈ owner` 或 `eid ∉ claimed`（claimed=None 视为无全局豁免）。
      判定用 effects 定义的注册 id（`all_ids("effect")` 的键）；状态事件分支不受
      本参数影响（status on_xxx 由 `status_id` 精确定位，本已归属到状态持有侧）。
    """
    out: List[Tuple[str, Mapping[str, Any], str]] = []
    resolve = getattr(registry, "resolve", None)
    all_ids = getattr(registry, "all_ids", None)
    if not callable(resolve) or not callable(all_ids):
        return out

    def _def_raw(defn: Any) -> Optional[Mapping[str, Any]]:
        if defn is None:
            return None
        raw = getattr(defn, "raw", None)
        return raw if isinstance(raw, Mapping) else (defn if isinstance(defn, Mapping) else None)

    if event in _STATUS_POINTS:
        # 状态 on_gain/on_lose/on_expire 数据源（按 status_id 精确取，或全扫）
        if status_id:
            status_ids: Sequence[str] = [status_id]
        else:
            _ids = all_ids("status")
            status_ids = list(_ids) if isinstance(_ids, (list, tuple)) else []
        for sid in status_ids:
            raw = _def_raw(resolve(sid, "status"))
            if not raw:
                continue
            for key, ev in _STATUS_EVENT_KEYS.items():
                if ev != event:
                    continue
                val = raw.get(key)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, Mapping):
                            out.append((str(item.get("effect") or item.get("id") or ""),
                                        dict(item), "status_effect"))
        return out

    # 纯效果事件：effects 定义 trigger 字段匹配
    # 批51 · 归属过滤：owner=本侧拥有集；claimed=本场被任一持侧认领集
    # （未认领 = 全局效果，对任何侧照常触发；两者皆 None = 全库扫描旧行为）。
    owner = None if owner_effect_ids is None else {str(x) for x in owner_effect_ids}
    claimed = None if claimed_effect_ids is None else {str(x) for x in claimed_effect_ids}
    for eid in all_ids("effect"):
        if owner is not None or claimed is not None:
            sid = str(eid)
            if not ((owner is not None and sid in owner)
                    or (claimed is not None and sid not in claimed)):
                continue
        raw = _def_raw(resolve(eid, "effect"))
        if not raw:
            continue
        if str(raw.get(TRIGGER_KEY) or "") == event:
            out.append((eid, raw, "effect"))
    return out


def _build_ctx(
    event: str,
    side: str,
    snapshot: Mapping[str, Any],
    attacker: str,
    target: str,
    variables: Optional[Mapping[str, Any]],
) -> Any:
    """构造 execute_action 的 DamageCtx（snapshot 必须含 combatant）。

    2026-09-10：DamageCtx 自 effect_types 顶层引入（原 lazy import effects 已消除）。
    """
    vmap: Dict[str, Any] = dict(variables or {})
    vmap.setdefault("event", event)
    return DamageCtx(
        raw_damage=0,
        attack_type="skill",
        attacker=attacker,
        target=target,
        snapshot=snapshot,
        variables=vmap,
    )


def _run_candidate(
    eid: str,
    raw: Mapping[str, Any],
    kind: str,
    event: str,
    side: str,
    snapshot: Mapping[str, Any],
    runtime: Any,
    ctx: Any,
    depth: int,
) -> List[Dict[str, Any]]:
    """执行单个候选（计数/深度/chance 门 + execute_action）。返回 side_effects。"""
    if runtime is None:
        return []
    # 计数上限（per_turn / per_battle；effect_id 用 eid 或条目 id）
    effect_id = str(raw.get("id") or eid or "event_fx")
    per_turn, per_battle = runtime.trigger_counts(side, effect_id)
    max_turn = int(runtime.config.get("max_triggers_per_turn", 10) or 10)
    max_battle = int(runtime.config.get("max_triggers_per_battle", 99) or 99)
    if per_turn >= max_turn or per_battle >= max_battle:
        return []
    # 深度上限
    limit = int(runtime.config.get("chain_depth", 3) or 3)
    if depth >= limit:
        return []
    # chance 三态（-1 必定 / 0-100 固定 / lucky；复用 effects._chance_roll）
    chance = raw.get("chance")
    if chance is not None:
        try:
            if not chance_roll(chance, ctx):
                return []
        except Exception:  # noqa: BLE001 —— chance 求值异常 → 不触发（安全失败）
            return []
    # 执行（引用归一 + condition 门控由 execute_action 内部处理）
    # 2026-09-10：execute_action 顶层引入（环打破后无需 lazy）。

    if kind == "effect":
        # 候选 raw 是 effects 定义：包成引用执行（execute_action 会查表展开）。
        # execute_action 经 runtime._resolver 查 effects 定义——若 runtime 未注入
        # registry（resolver 恒 None），临时包 resolver 指向 registry.resolve
        # （resolver 是 callable(id, kind) -> Def；registry.resolve 同形）
        act: Dict[str, Any] = {"effect": eid}
        ov = raw.get("overrides")
        if isinstance(ov, Mapping):
            act["overrides"] = dict(ov)
        res = execute_action(act, ctx, runtime, depth=depth + 1)
    else:
        # status on_xxx 条目（kind="status_effect"：引用形态 {effect, overrides}
        # 或裸 action）。状态事件的效果默认作用在状态持有侧（side）：动作未显式
        # target → 补 target=side（heal 状态获得回自己、爆炸打对方由动作显式指定）
        act = dict(raw)
        act.setdefault("target", side)
        res = execute_action(act, ctx, runtime, depth=depth + 1)
    if res.ok:
        try:
            runtime.increment_trigger(side, effect_id, "per_turn")
            runtime.increment_trigger(side, effect_id, "per_battle")
        except Exception:  # noqa: BLE001 —— 计数异常不阻断执行结果
            pass
    return list(res.side_effects)


def dispatch_event(
    event: str,
    side: str,
    snapshot: Mapping[str, Any],
    registry: Any,
    *,
    status_id: Optional[str] = None,
    attacker: Optional[str] = None,
    variables: Optional[Mapping[str, Any]] = None,
    runtime: Any = None,
    depth: int = 0,
    extra_candidates: Optional[Sequence[Tuple[str, Mapping[str, Any], str]]] = None,
    owner_effect_ids: Optional[Sequence[str]] = None,
    claimed_effect_ids: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """在战斗时点 fire 匹配事件的效果/proc/状态 on_xxx 动作（功能三 §2.3）。

    参数：
      event:     事件时点（EVENT_POINTS 之一；未知事件 → [] 安全失败）
      side:      触发侧（"player"/"enemy"）
      snapshot:  战斗快照（含 combatant 与五块；execute_action 消费）
      registry:  内容注册表（resolve/all_ids）或带同形方法的对象
      status_id: 状态事件（status_gain/status_lose）精确指定状态；None = 全扫
      attacker:  执行效果时的施放侧（缺省 = side）
      variables: 执行 ctx 变量（可传 event 上下文，如本次伤害值）
      runtime:   EffectRuntime（计数/深度/chance config；None → 不计数直接执行）
      depth:     递归深度（防 on_hit→反伤→on_hit 无限）
      extra_candidates：批48 · 调用方追加的候选（同 `_iter_candidates` 三元组形态
                 `(effect_id, raw_like, kind)`）——用于**只对特定持侧生效**的效果源
                （符文声明效果）；缺省 None → 与既有行为逐字段一致（零新增）。
      owner_effect_ids：批51 · **归属作用域**（纯效果事件分支的候选白名单）：
                 None（缺省）→ 全库扫描（本机制引入前旧行为，逐字段一致）；
                 非 None → 只有 id 在该序列内的 effects 定义才是候选——调用方
                 按「本侧拥有的效果集」传入（装配层展开的装备被动效果），
                 避免带 `trigger` 的效果对所有单位全局误触发。
                 对 `extra_candidates` 不生效（后者已由调用方按持侧自过滤）。
      claimed_effect_ids：批51 · **全局豁免集**：本场战斗内**被任一持侧认领**的
                 effect id 全集。未在其中的 effect 视为全局效果，对任何侧照常触发
                 （调用方两参数同时给出时 = 「自己的 ∪ 未被任何人认领的」）；
                 两者皆 None → 与既有行为逐字段一致。

    返回：合并的 side_effects 列表（无候选/未配置 → []，零行为变化）。
    """
    if event not in EVENT_POINTS:
        return []
    if not isinstance(snapshot, Mapping):
        return []
    cands = _iter_candidates(event, registry, status_id=status_id,
                             owner_effect_ids=owner_effect_ids,
                             claimed_effect_ids=claimed_effect_ids)
    if extra_candidates:
        cands = list(cands) + [
            c for c in extra_candidates
            if isinstance(c, tuple) and len(c) == 3
        ]
    if not cands:
        return []
    # runtime 查表指向 registry.resolve（resolver 形态 (id, kind) -> Def，供
    # execute_action 引用归一查 effects 定义）。dispatch 语义 = 事件效果查传入的
    # registry；runtime 若被外部注入过特定 resolver（如 battle 已绑 registry）
    # 则保留不动——registry 与 runtime 同源时行为一致。
    if runtime is not None:
        reg_resolve = getattr(registry, "resolve", None)
        cur = getattr(runtime, "_resolver", None)
        if callable(reg_resolve) and (cur is None or cur(
                "__probe__", "effect") is None):
            runtime._resolver = reg_resolve
    atk = attacker or side
    tgt = "enemy" if atk == "player" else "player"
    ctx = _build_ctx(event, side, snapshot, atk, tgt, variables)
    effects_out: List[Dict[str, Any]] = []
    for eid, raw, kind in cands:
        effects_out.extend(
            _run_candidate(eid, raw, kind, event, side, snapshot, runtime, ctx, depth)
        )
    return effects_out


# ---------------------------------------------------------------------------
# 回调注册（2026-09-10 环打破 · 见 effects.register_event_dispatcher docstring）
#
# effects.execute_action 在状态施加/移除后需要触发 status_gain/status_lose 事件分派，
# 但 effects 不得 import 本模块（否则成环）。故由本模块在加载末尾主动注入 dispatch_event
# 至 effects 的回调槽——依赖单向：本模块 → effects。
# ---------------------------------------------------------------------------

register_event_dispatcher(dispatch_event)
