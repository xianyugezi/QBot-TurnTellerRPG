# -*- coding: utf-8 -*-
"""云海异步底盘 cloudsea_async.py（九期批次 234 · G5 指令交互）。

四组件（任务书：决策超时托管层＋autoplay 决策点推进器＋outbox 战报队列＋长眠
策略参数化）——独立分账模块（235H/232 独立分账同型），零触碰 battle.py 回合调
度/damage.py/既有 content 包/现有指令词面（红线）；装配层显式调用 → 生效，未
装配 → 零行为（可选加载承诺，映射表台账登记）。

时间轴：**零墙钟**（215H 游戏日模型）——全部计数走「回合/场/游戏日」三轴：
- 超时代管＝连续无指令**回合**数（`$C.ASYNC.CUSTODY_AFTER_TURNS`=2，§J 既有）
- 战报合并＝**结算批次**回合窗（`$C.ASYNC.OUTBOX_BATCH_TURNS`=1，本批申报）
- 长眠＝无结算**游戏日**数（`$C.ASYNC.LONGSLEEP_DAYS`=7，本批申报；215H
  「长眠（≥7 游戏日无结算）」口径的参数化承载）

游戏日 D 读取：`game_day(ctx)`＝ctx["game_day"] 注入优先（215H 合成时钟），
缺省 0。控制类豁免：托管/autoplay **不触发战斗调和**（`08` §M8.13/215 口径）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional

__all__ = [
    "TurnoutGuard", "AutoplayDriver", "OutboxQueue", "LongSleepPolicy",
    "game_day",
]

# ---------------------------------------------------------------- 键缺省（12 §J 申报值）
DEF_CUSTODY_TURNS = 2       # $C.ASYNC.CUSTODY_AFTER_TURNS（§J 既有）
DEF_LONGSLEEP_DAYS = 7      # $C.ASYNC.LONGSLEEP_DAYS（本批申报）
DEF_OUTBOX_BATCH_TURNS = 1  # $C.ASYNC.OUTBOX_BATCH_TURNS（本批申报）
DEF_CUSTODY_QUALITY = 0.75  # $C.ASYNC.CUSTODY_EFFICIENCY（§J 既有，代打质量）
SLOW_QUALITY = 0.95         # $C.ASYNC.CUSTODY_SLOW_RATE（守拙档，§J 既有）


def game_day(ctx: Optional[Mapping[str, Any]] = None) -> int:
    """游戏日号 D（215H）：ctx["game_day"] 注入优先；缺省 0。"""
    if not ctx:
        return 0
    try:
        return max(int(ctx.get("game_day", 0)), 0)
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------- ① 决策超时托管层
class TurnoutGuard:
    """玩家回合级出勤守卫：连续无指令回合计数 → 触发代打。

    `08` §M8.1 超时参数表（215H 改写后口径）：连续 2 回合无指令 = 代打；
    连续 4 回合 = 预案①（防御+打最软部位）。守拙档（挂 N 稳）只改质量与
    时长倍率，不改触发回合数（§J 既有键语义）。
    """

    def __init__(self, threshold: int = DEF_CUSTODY_TURNS, quality: float = DEF_CUSTODY_QUALITY) -> None:
        self.threshold = max(int(threshold), 1)
        self.quality = float(quality)
        self._idle: Dict[str, int] = {}

    def record(self, player_id: str, acted: bool) -> Optional[Dict[str, Any]]:
        """记录一回合出勤；达阈值返回代打事件（dict），否则 None。"""
        n = self._idle.get(player_id, 0)
        if acted:
            if n:
                self._idle[player_id] = 0
            return None
        n += 1
        self._idle[player_id] = n
        if n >= self.threshold:
            self._idle[player_id] = 0
            return {
                "type": "custody_takeover",
                "player": player_id,
                "idle_turns": n,
                "quality": self.quality,
                "mode": "preset",
            }
        return {"type": "custody_warn", "player": player_id, "idle_turns": n}

    def escalate(self, player_id: str) -> Dict[str, Any]:
        """二段升级（预案①：防御+打最软部位）——由调用方在二段窗口显式触发。"""
        self._idle[player_id] = 0
        return {"type": "custody_escalate", "player": player_id, "plan": "plan_1"}


# ---------------------------------------------------------------- ② autoplay 决策点推进器
class AutoplayDriver:
    """预案串步骤推进器：把战前预案串翻译为回合行动序列。

    豁免口径（`08` §M8.13/215）：托管回合**不触发战斗调和**——步骤含
    「调和」时跳过并落 skip 事件；「炮台守 side:X」（232 方位枚举）透传
    为带方位的行动。步骤形态＝`→` 分隔的字符串（232 presets 模板同构）。
    """

    FORBIDDEN_IN_CUSTODY = ("调和",)

    def __init__(self, quality: float = DEF_CUSTODY_QUALITY, slow: bool = False) -> None:
        self.quality = SLOW_QUALITY if slow else float(quality)

    def drive(self, preset_body: str, turn: int) -> Dict[str, Any]:
        steps = [s.strip() for s in (preset_body or "").replace("｜", "→").split("→") if s.strip()]
        if not steps:
            return {"type": "autoplay", "turn": turn, "action": "defend", "quality": self.quality, "skipped": []}
        idx = (turn - 1) % len(steps) if steps else 0
        action = steps[idx]
        skipped: List[str] = []
        for bad in self.FORBIDDEN_IN_CUSTODY:
            if bad in action:
                skipped.append(action)
                action = "defend"
                break
        side = ""
        if "炮台守" in action and "side:" in action:
            side = action.split("side:", 1)[1].strip().split("）")[0].split(")")[0]
        return {
            "type": "autoplay", "turn": turn, "action": action, "quality": self.quality,
            "skipped": skipped, **({"side": side} if side else {}),
        }


# ---------------------------------------------------------------- ③ outbox 战报队列
class OutboxQueue:
    """战报外发队列：按**结算批次回合窗**合并（零墙钟），@ 白名单直通。

    push(report, *, turn, at_whitelist=False)：普通战报按回合窗缓冲；
    白名单类（轮到你/结算/广播/私聊，215 D-01 @ 白名单四类同族）绕过
    缓冲即时可发。drain(current_turn) 返回到期批次的合并报文列表。
    """

    def __init__(self, batch_turns: int = DEF_OUTBOX_BATCH_TURNS) -> None:
        self.batch = max(int(batch_turns), 1)
        self._buf: List[Dict[str, Any]] = []
        self._last_turn = 0

    def push(self, report: str, *, turn: int, at_whitelist: bool = False) -> Optional[str]:
        if at_whitelist:
            return report  # 白名单直通（不缓存）
        self._buf.append({"turn": int(turn), "report": report})
        self._last_turn = max(self._last_turn, int(turn))
        return None

    def drain(self, current_turn: int) -> List[str]:
        due = [b for b in self._buf if current_turn - b["turn"] >= self.batch - 1]
        if not due:
            return []
        self._buf = [b for b in self._buf if b not in due]
        return [b["report"] for b in due]


# ---------------------------------------------------------------- ④ 长眠策略参数化
class LongSleepPolicy:
    """长眠判定与参数化：≥ LONGSLEEP_DAYS 游戏日无结算 → 冻结建议。

    `08` §M8.1「长眠（≥7 游戏日无结算）」口径的参数化承载（215H 改写）；
    零墙钟——天数差由调用方以游戏日号 D 传入（D_now - D_last_settle）。
    """

    def __init__(self, days: int = DEF_LONGSLEEP_DAYS) -> None:
        self.days = max(int(days), 1)

    def check(self, day_now: int, day_last_settle: int) -> Dict[str, Any]:
        gap = max(int(day_now) - int(day_last_settle), 0)
        if gap >= self.days:
            return {"type": "longsleep_freeze", "gap_days": gap, "frozen": True,
                    "note": "存档长期保留（零墙钟）；回归发 局面 续"}
        return {"type": "longsleep_ok", "gap_days": gap, "frozen": False}
