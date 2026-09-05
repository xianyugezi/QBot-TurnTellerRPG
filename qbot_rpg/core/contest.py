"""品评会引擎（2c5c CT-01~09：周赛投稿 + 四维评分 + 排行 + 冠军奖励 + 声望）。

文件名：contest.py
创建时间：2026-09-06
作者：Hermes 主代理（指令缺口补全批3路2）

配置源：ctx["contest_cfg"]（settings.contest 段）：
  {enabled, schedule: {weekday: 7, open_hour: 20}, score_weights: {quality:0.4,
   trait:0.3, awaken:0.2, potential:0.1}, reward: {title: "品评冠军", gem: 100,
   reputation: {submit: 5, win: 30}}}
四维评分（CT-04）：品质档位分/特性条数/觉醒分/潜力分归一化 0-100 → 加权求和。
品质：normal 25 / fine 50 / epic 75 / legendary 100（缺省 0）
特性：min(条数×25, 100)（缺省 0）
觉醒/潜力：行内数值键（awaken/potential 0-100；缺省 0）
全局投稿：world_state key="contest_board"（JSON {week_key, entries[], settled_week}）；
  每玩家每期限投 1 件（CT-03）——防重靠玩家 ctx 记录（persistent_state
  contest_entries 本期已投标记）。
结算（CT-06/07/09 懒计算）：新周首次投稿/看榜时，若上周有投稿未结算 →
  给最高分者发称号/宝石/声望（同事务，写 world_state + 获奖玩家存档）。
"""
from __future__ import annotations

import time
from typing import Any, Mapping, Tuple

_QUALITY_SCORE: Mapping[str, int] = {
    "normal": 25, "普通": 25,
    "fine": 50, "精良": 50,
    "epic": 75, "史诗": 75,
    "legendary": 100, "传说": 100,
}


def cfg_of(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    c = ctx.get("contest_cfg")
    return c if isinstance(c, Mapping) else {}


def enabled(ctx: Mapping[str, Any]) -> bool:
    c = cfg_of(ctx)
    return c.get("enabled", False) is True  # 默认关（CT：默认关防配置负担）


def week_key_of(ts: int) -> str:
    """周键（周一起算 ISO 周）。"""
    lt = time.localtime(ts)
    return time.strftime("%Y-W%W", lt)


def _quality_score(q: Any) -> int:
    if isinstance(q, (int, float)) and not isinstance(q, bool):
        return min(100, max(0, int(q)))
    return _QUALITY_SCORE.get(str(q), 0)


def score_item(row: Any, weights: Mapping[str, float]) -> Tuple[float, dict]:
    """四维评分（CT-04）：row 行（ItemInstance/dict 鸭子读）。返回 (总分, 维度分)。"""
    def _g(key: str, dflt: Any) -> Any:
        if isinstance(row, Mapping):
            return row.get(key, dflt)
        return getattr(row, key, dflt)

    quality = _quality_score(_g("quality", "normal"))
    traits = _g("traits", ()) or ()
    n_trait = len(traits) if isinstance(traits, (list, tuple)) else 0
    trait = min(n_trait * 25, 100)
    awaken = _num(_g("awaken", None))
    potential = _num(_g("potential", None))
    wq = float(weights.get("quality", 0.4) or 0.4)
    wt = float(weights.get("trait", 0.3) or 0.3)
    wa = float(weights.get("awaken", 0.2) or 0.2)
    wp = float(weights.get("potential", 0.1) or 0.1)
    total = quality * wq + trait * wt + awaken * wa + potential * wp
    return round(total, 1), {
        "quality": quality, "trait": trait, "awaken": awaken, "potential": potential,
    }


def _num(v: Any) -> float:
    if isinstance(v, bool):
        return 0.0
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def in_window(ctx: Mapping[str, Any], ts: int) -> Tuple[bool, str]:
    """周赛窗口判定（CT-01）：schedule {weekday 1-7(周一=1), open_hour}；
    周日=7。窗口=每周 weekday 的 open_hour 起 2 小时。返回 (可投, 提示)。"""
    sch = cfg_of(ctx).get("schedule")
    if not isinstance(sch, Mapping):
        return True, ""
    wd = int(sch.get("weekday", 7) if sch.get("weekday") is not None else 7)
    oh_raw = sch.get("open_hour")
    oh = int(oh_raw if oh_raw is not None else 20)
    lt = time.localtime(ts)
    cur_wd = lt.tm_wday + 1  # 周一=1
    if cur_wd < wd:
        return False, f"品评会每周 {'日一二三四五六'[wd % 7]} {oh}:00 开放，敬请期待"
    if cur_wd == wd and lt.tm_hour < oh:
        return False, f"品评会今日 {oh}:00 开放，敬请期待"
    if cur_wd > wd:
        return False, "本期品评会已结束，下期再投"
    return True, ""


def _board_row_key() -> str:
    return "contest_board"


def entry_exists(record: Any, week: str, qid: str) -> bool:
    """本期已投判定（CT-03：record = persistent_state contest_entries 或 ctx 内）。"""
    if not isinstance(record, Mapping):
        return False
    sub = record.get(week)
    if isinstance(sub, Mapping):
        return str(sub.get("qid", "")) == qid or bool(sub)
    return week in record


__all__ = [
    "cfg_of", "enabled", "week_key_of", "score_item", "in_window",
    "entry_exists", "_board_row_key",
]
