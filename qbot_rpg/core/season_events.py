"""M13 6c on_season_change 换季事件引擎（细化_6c §2.5 M7：E1~E6）。

文件名：season_events.py
创建时间：2026-09-02
依据：docs/细化/细化_6c_资源轴与职业机制.md（497 行 v1.0）：
  - M7 on_season_change 事件：换季触发 L2 proc（E3 上限字段；
    max_triggers_per_turn=10 / per_battle=99 由 effects 容器强制）；
  - 恰一次幂等（E5/SC-3）：换季只触发一次，防重复；
  - 战斗外不触发（E5）；
  - 事件枚举登记表（V11 依赖：自有登记表，effects trigger 无白名单）。

功能描述：
  - ON_SEASON_CHANGE 事件常量 + SEASON_EVENTS 枚举登记表；
  - trigger_season_event(state, ctx, *, runtime) 换季事件触发：
      恰一次幂等（season_event_state.last_season_idx 对比当前季节索引）→
      L2 proc 经 execute_proc_action 容器执行（走 max_triggers 双重封顶）；
  - proc 列表注入位：四时调和被动等由内容包配置（引擎留接口）。

工程补白（契约/细化未显式定义处的实现口径，显式标注供审查）：
  P-1  事件枚举登记表为自有表（SEASON_EVENTS）——effects L1655 trigger 无
       白名单，V11「未登记事件红拦」依赖本表（对齐 condition_engine.EVENT_PRESETS 先例）。
  P-2  恰一次幂等键：battle_state 顶层 season_event_state{last_season_idx}
       （战斗外/缺段 → 缺省 -1 → 首次换季必触发）。
  P-3  proc 注入形态：runtime 注入 + proc 列表经 ctx["season_procs"] 读取
       （内容包装配，缺省空 → 无 proc 只登记事件）。

铁律：零 NoneBot import；G0：core 层零 import engine/content（季节/proc
数据经 ctx 注入）；零定时器/零睡眠；纯函数确定性；不 git commit。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

# =====================================================================================
# 常量（契约 §2.5 M7）
# =====================================================================================

# 换季事件 trigger 名（proc 容器 trigger 键）
ON_SEASON_CHANGE: str = "on_season_change"

# 事件枚举登记表（V11 依赖；P-1 自有表）
SEASON_EVENTS: tuple = (ON_SEASON_CHANGE,)

# 幂等状态段（battle_state 顶层）
SEASON_EVENT_STATE_KEY: str = "season_event_state"
LAST_SEASON_IDX_KEY: str = "last_season_idx"


# =====================================================================================
# 状态读取辅助
# =====================================================================================

def _event_state_of(state: Mapping[str, Any]) -> Dict[str, Any]:
    """读 battle_state.season_event_state（缺省 -1 → 首次换季必触发）。"""
    seg = state.get(SEASON_EVENT_STATE_KEY)
    if isinstance(seg, Mapping):
        return dict(seg)
    return {LAST_SEASON_IDX_KEY: -1}


def _idx_of(seg: Mapping[str, Any]) -> int:
    """幂等索引读取（0 是合法季节索引——勿用 `or` 吞 0）。"""
    v = seg.get(LAST_SEASON_IDX_KEY, -1)
    return v if isinstance(v, int) and not isinstance(v, bool) else -1


def _season_index(season: Any, seasons: tuple = ("spring", "summer", "autumn", "winter")) -> int:
    """季节 → 索引（未知 → -1）。"""
    if isinstance(season, str):
        try:
            return seasons.index(season)
        except ValueError:
            return -1
    return -1


# =====================================================================================
# 换季事件触发
# =====================================================================================

def season_changed(state: Mapping[str, Any], current_season: Any) -> bool:
    """换季判定（幂等基）：当前季节索引 ≠ 生效季节索引 → 换季待触发。"""
    seg = _event_state_of(state)
    return _season_index(current_season) != _idx_of(seg)


def trigger_season_event(
    state: Dict[str, Any],
    current_season: Any,
    *,
    procs: Optional[List[Mapping[str, Any]]] = None,
    runtime: Any = None,
    proc_runner: Any = None,
) -> Dict[str, Any]:
    """on_season_change 换季事件触发（恰一次幂等 + L2 proc 容器）。

    流程：
      1. 换季判定（season_changed）：未换季 → 无操作（ok=True triggered=False）；
      2. 幂等标记：season_event_state.last_season_idx ← 当前季节索引；
      3. L2 proc 执行：procs 列表每条经 proc_runner（缺省 execute_proc_action
         语义由装配层注入；engine 不直接 import effects——G0）逐条跑；
      4. 返回 {ok, triggered, from_idx, to_idx, proc_results}。

    :param state: battle_state（可变 dict，幂等标记写回）
    :param current_season: 当前季节（"spring"/...）
    :param procs: 换季事件 proc 列表（内容包装配，缺省空）
    :param runtime: EffectRuntime（proc 容器需要）
    :param proc_runner: proc 执行器（callable(proc, ctx, runtime) → ActionResult；
                       缺省 None → 只登记不执行——战斗层接线后注入）
    """
    seg = _event_state_of(state)
    old_idx = _idx_of(seg)
    new_idx = _season_index(current_season)
    if new_idx == old_idx:
        return {"ok": True, "triggered": False, "from_idx": old_idx, "to_idx": new_idx,
                "proc_results": []}
    # 幂等标记写回
    seg[LAST_SEASON_IDX_KEY] = new_idx
    state[SEASON_EVENT_STATE_KEY] = seg
    # L2 proc 执行
    proc_results: List[Dict[str, Any]] = []
    for proc in procs or ():
        if not isinstance(proc, Mapping):
            continue
        if proc_runner is not None and runtime is not None:
            try:
                res = proc_runner(proc, runtime)
                proc_results.append({"proc": proc.get("id") or proc.get("type") or "proc",
                                     "ok": bool(getattr(res, "ok", True))})
            except Exception:  # noqa: BLE001 - proc 异常不阻断换季
                proc_results.append({"proc": proc.get("id") or proc.get("type") or "proc",
                                     "ok": False, "error": "proc_exception"})
        else:
            proc_results.append({"proc": proc.get("id") or proc.get("type") or "proc",
                                 "ok": None, "skipped": "runner_not_injected"})
    return {"ok": True, "triggered": True, "from_idx": old_idx, "to_idx": new_idx,
            "proc_results": proc_results}


# =====================================================================================
# 战斗结束清理
# =====================================================================================

def clear_season_event_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """战斗结束清理（对齐 transform/resource 清零模式）：幂等段复位 -1。"""
    state[SEASON_EVENT_STATE_KEY] = {LAST_SEASON_IDX_KEY: -1}
    return state


__all__ = [
    "ON_SEASON_CHANGE", "SEASON_EVENTS", "SEASON_EVENT_STATE_KEY",
    "LAST_SEASON_IDX_KEY",
    "season_changed", "trigger_season_event", "clear_season_event_state",
]
