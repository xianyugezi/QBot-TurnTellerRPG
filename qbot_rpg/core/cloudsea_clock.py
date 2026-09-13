# -*- coding: utf-8 -*-
"""云海游戏日合成时钟（九期批次 235 · G5 增量；设计稿 215H 游戏日模型承接）。

依据：设计稿 15_主线章节与任务/生产排期_适配期_九期.md §二 G1B「215 增量」——
    游戏日合成时钟接入（dayroll 注入）；215H 模型＝存档内单调递增游戏日号 D
    （推进信号＝冷启动且上次推进后 ≥1 场结算）、零墙钟、游戏周 W=D//7；
    框架接入＝合成时钟注入 now=锚点epoch+D×86400+12h（dayroll/今日重置类逻辑
    零改动生效——不采纳真实 05:00，离线多日回来破坏丰饶符节奏）。

红线：纯函数零 IO 零引擎 import；不改 battle.py 回合调度/damage.py；
    本模块只提供「D → 合成 now」换算与当日窗口判定，装配层（234 异步底盘／
    238 验收探针）按需调用；框架既有时间源零触碰。
"""
from __future__ import annotations

# 合成时钟锚点（固定常量：2026-09-14T00:00:00Z 的 Unix 秒；215H「锚点 epoch」的落定值，
# 存档迁移不改——游戏日号 D 单调递增，锚点仅决定 epoch 映射的绝对位置）
CLOUDSEA_EPOCH_ANCHOR: int = 1789411200
NOON_OFFSET_SECONDS: int = 12 * 3600          # +12h：日中点结算位（215H「+12h」）
SECONDS_PER_DAY: int = 86400
SYNTH_CLOCK_KEY: str = "cloudsea_synth_now"   # ctx 注入键（装配层写入，231/234 消费）


def synth_now(game_day: int) -> int:
    """游戏日号 D → 合成时钟 now（Unix 秒）＝锚点 + D×86400 + 12h。

    dayroll/今日重置类逻辑消费该值即零改动生效（215H 口径）：D 不变则
    now 不变（同日重进＝同日，零结算重进堵重开刷投喂）。
    """
    d = int(game_day)
    if d < 0:
        d = 0
    return CLOUDSEA_EPOCH_ANCHOR + d * SECONDS_PER_DAY + NOON_OFFSET_SECONDS


def game_week(game_day: int) -> int:
    """游戏周 W = D // 7（215H 游戏周口径：残片每游戏周 3 片／异相种每游戏周 2 只）。"""
    return max(0, int(game_day)) // 7


def is_in_beast_window(game_day: int, *, windows_per_day: int = 1) -> bool:
    """巨兽窗日窗条件（economy.json beast_window：每日 1 窗，窗＝游戏日全天）。

    每日 1 窗口径下，游戏日内恒在窗（窗边界＝游戏日切换）；保留 windows_per_day
    参数位供未来多窗扩展（1=恒在；>1 时按日内时段均分——现契约只有 1）。
    """
    return windows_per_day >= 1


__all__ = [
    "CLOUDSEA_EPOCH_ANCHOR", "NOON_OFFSET_SECONDS", "SECONDS_PER_DAY",
    "SYNTH_CLOCK_KEY", "synth_now", "game_week", "is_in_beast_window",
]
