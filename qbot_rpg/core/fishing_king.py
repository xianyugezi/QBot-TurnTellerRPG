"""M10 钓鱼·批4·路4B（主 agent 收口补齐）：鱼王事件服务（触发判定 + 每日窗口 + 胜利计次）。

文件名：qbot_rpg/core/fishing_king.py
创建时间：2026-08-31
作者：Hermes 主 agent（路4B 子 agent 撞迭代上限零落盘，按侦察结论补齐）

功能描述（T15 · 细化_2c1a §三 + 细化_2c1c §一）：
  - king_event_available(ctx, species_id, rng=None)：鱼王触发判定——king_event.enabled
    ∧ 当日触发尝试 < window_daily ∧ 该鱼种有 king 行 ∧ 单次 chance roll（注入 rng，
    种子 42/2026 可复现）；返回 {ok, king_row, hint, triggered, reason}。
  - 每日窗口记账：fish_state 或 codex __meta__ 内 {king_trigger_count,
    king_victory_count}（当日）+ 跨日懒重置（dayroll today_of 05:00）；门控用
    触发尝试计（无论胜负），授权/补全用胜利计（R-02）。
  - king_victory_record(ctx)：讨伐胜利计 1 次（king_victory_count+1，供批5 图鉴补全）。
  - 金闪隔离：金闪只可能出现在猛烈鱼讯（violent），微动/拉扯永不携带（TC-13）——
    king_event_available 只被猛烈鱼讯消费（调用方把关）。

依据：细化_2c1a §三（K-01~K-07 + 触发契约 + TC-12~14）+ 细化_2c1c §一
      （R-01 触发链路 / R-02 每日窗口纪律 / R-03 讨伐结算 + TC-01~04）
      + docs/m10_shared_contract.md §四 R-01~R-04 + docs/m10_接口摸底.md §五
模式参考：
  - qbot_rpg/core/fishing.py（_resolve_rng：参数 rng → ctx["rng"] → random 模块兜底）
  - qbot_rpg/core/quest.py _daily_node（dayroll today_of 05:00 懒重置）
  - qbot_rpg/core/fishing_codex.py fish_meta（codex __meta__ king_victory_count 读改写）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  K-1  窗口计数落点：codex_state["fish"]["__meta__"]（fish_meta 已含
       king_victory_count 默认 0）；另加 king_trigger_count 键（当日触发尝试）。
       跨日懒重置：__meta__ 内存 {window_key: "YYYY-MM-DD"}，today_of 判定跨日清零。
  K-2  chance 缺省：king 行 chance 优先（行级覆写 > settings.king_event.chance 0.3）；
       window_daily 同理（行级 > settings 2）。
  K-3  king 表读取：fishing.json 顶层 king[]（ctx["fishing"]["king"] 或
       ctx["fish_table"] 旁路）——species_id 匹配；无 king 行 → reason=no_king_row。
  K-4  BOSS 战接线：本服务只做触发判定+窗口记账+胜利计次；实际 BattleEngine
       开战由批6 指令壳接线（king_row.enemy_id 引用 enemies.json 实体）。

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器/零睡眠（时间戳懒判）；
      rng 注入（种子 42/2026）禁裸 random；docstring 勿写字面定时器调用字样
      （M43 探针）；零 emoji；不 git commit。
"""

from __future__ import annotations

import random
from typing import Any, Mapping, MutableMapping

from qbot_rpg.core.dayroll import today_of
from qbot_rpg.core.fishing_codex import KING_VICTORY_COUNT_KEY, fish_meta
from qbot_rpg.core.fishing_settings import fishing_cfg

__all__ = [
    "KING_TRIGGER_COUNT_KEY",
    "KING_WINDOW_KEY",
    "king_event_available",
    "king_victory_record",
    "king_trigger_count",
]

# 窗口计数键（codex __meta__ 内）
KING_TRIGGER_COUNT_KEY: str = "king_trigger_count"
# 窗口日键（跨日懒重置用）
KING_WINDOW_KEY: str = "king_window_date"


def _resolve_rng(rng: Any, ctx: Mapping[str, Any]) -> Any:
    """rng 注入单源：参数 rng 优先 → ctx["rng"] → random 模块兜底（对齐 fishing）。"""
    if rng is not None:
        return rng
    r = ctx.get("rng")
    if r is not None:
        return r
    return random


def _to_int(v: object, default: int) -> int:
    """非负 int 收窄（bool 排除）；非法 → default。"""
    if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
        return v
    return default


def _to_float(v: object, default: float) -> float:
    """正数 float 收窄（bool 排除）；非法 → default。"""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) >= 0:
        return float(v)
    return default


def _now(ctx: Mapping[str, Any]) -> int:
    """当前 UTC+8 epoch 秒（ctx["now"]，缺省 0 防御）。"""
    n = ctx.get("now")
    return int(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else 0


def _king_rows(ctx: Mapping[str, Any]) -> tuple:
    """fishing.json king[] 行元组（ctx["fishing"]["king"] 或 fish_table 旁路）。"""
    fishing = ctx.get("fishing")
    if isinstance(fishing, Mapping):
        rows = fishing.get("king")
        if isinstance(rows, list):
            return tuple(r for r in rows if isinstance(r, Mapping))
    # fish_table 旁路（批2 装配注入形态）
    ft = ctx.get("fish_table")
    if isinstance(ft, Mapping):
        raw = ft.get("__king__")
        if isinstance(raw, list):
            return tuple(r for r in raw if isinstance(r, Mapping))
    return ()


def _king_event_cfg(ctx: Mapping[str, Any]) -> Mapping[str, object]:
    """settings.fishing.king_event 段（fishing_cfg 归一，缺省 {enabled,window_daily,chance}）。"""
    cfg = fishing_cfg(ctx)
    ke = cfg.get("king_event")
    return ke if isinstance(ke, Mapping) else {}


def _window_state(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """窗口记账可变引用（codex __meta__ 内；跨日懒重置）。

    返回 {king_trigger_count, king_victory_count, king_window_date} 所在 meta dict；
    跨日（today_of 判定 window_date != 今日）→ 触发计数清零、window_date 更新。
    胜利计数（king_victory_count）不随日清零（累计，供图鉴补全 R-07）。
    """
    meta = fish_meta(ctx)
    today = today_of(meta.get(KING_WINDOW_KEY), _now(ctx), {"refresh_time": 0})
    today_str = str(today.get("today") or "")
    if meta.get(KING_WINDOW_KEY) != today_str:
        meta[KING_WINDOW_KEY] = today_str
        meta[KING_TRIGGER_COUNT_KEY] = 0
    meta.setdefault(KING_TRIGGER_COUNT_KEY, 0)
    meta.setdefault(KING_VICTORY_COUNT_KEY, 0)
    return meta


def king_trigger_count(ctx: MutableMapping[str, Any]) -> int:
    """当日触发尝试计数（门控用，无论胜负；R-02）。"""
    meta = _window_state(ctx)
    return int(meta.get(KING_TRIGGER_COUNT_KEY, 0) or 0)


def king_event_available(
    ctx: MutableMapping[str, Any],
    species_id: str,
    rng: Any = None,
) -> dict:
    """鱼王触发判定（R-01/R-02，确定性）。

    判定链（短路）：king_event.enabled（总开关）→ 该鱼种有 king 行 → 当日触发
    尝试 < window_daily（行级覆写 > settings）→ 单次 chance roll（行级覆写 >
    settings 0.3，注入 rng）。
    命中 → {ok, king_row, hint, triggered:True} + 触发尝试计数 +1（无论后续是否
    真正开战——R-02 门控用尝试计）；
    未命中 → {ok:False, reason: disabled|no_king_row|window_exhausted|chance_miss,
    triggered:False}。
    """
    ke = _king_event_cfg(ctx)
    if ke.get("enabled") is False:
        return {"ok": False, "reason": "disabled", "triggered": False}

    rows = _king_rows(ctx)
    row = next((r for r in rows if r.get("species_id") == species_id), None)
    if row is None:
        return {"ok": False, "reason": "no_king_row", "triggered": False}

    row_window = row.get("window_daily")
    if isinstance(row_window, int) and not isinstance(row_window, bool):
        window = row_window
    else:
        window = _to_int(ke.get("window_daily"), 2)
    meta = _window_state(ctx)
    if int(meta.get(KING_TRIGGER_COUNT_KEY, 0) or 0) >= window:
        return {"ok": False, "reason": "window_exhausted", "triggered": False}

    row_chance = row.get("chance")
    if isinstance(row_chance, (int, float)) and not isinstance(row_chance, bool):
        chance = float(row_chance)
    else:
        chance = _to_float(ke.get("chance"), 0.3)
    r = _resolve_rng(rng, ctx)
    hit = float(r.random()) < chance

    # 触发尝试计数 +1（无论 roll 结果——R-02 门控用尝试计）
    meta[KING_TRIGGER_COUNT_KEY] = int(meta.get(KING_TRIGGER_COUNT_KEY, 0) or 0) + 1

    if not hit:
        return {"ok": False, "reason": "chance_miss", "triggered": False}
    hint = row.get("hint") if isinstance(row.get("hint"), str) and row["hint"] else "金闪"
    return {"ok": True, "king_row": dict(row), "hint": str(hint), "triggered": True}


def king_victory_record(ctx: MutableMapping[str, Any]) -> dict:
    """讨伐胜利计 1 次（R-03：king_victory_count+1，供图鉴补全 R-07 读取）。"""
    meta = _window_state(ctx)
    meta[KING_VICTORY_COUNT_KEY] = int(meta.get(KING_VICTORY_COUNT_KEY, 0) or 0) + 1
    return {"ok": True, "king_victory_count": int(meta[KING_VICTORY_COUNT_KEY])}
