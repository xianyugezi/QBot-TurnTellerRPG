"""世界时间引擎（M3 实装 · 本里程碑仅骨架占位）。

M3 实装依据：细化_2a4a_时间引擎（白天/夜晚轮转、时刻换算、驳接 weather/period；
零定时器，懒计算）；细化_2a4c_时间天气接口（公开接口 IF01~IF12：季节/时段/天气
三周期查询、生效池、确定性抽签、变化检测、懒广播、存档、配置重排）。
WorldState 唯一落点 data/world_state.py（3a D-03）。

本里程碑（M0）仅定义模块职责与占位签名（**与 2a4c IF01~IF12 签名对齐**，
M3 直接填充实现），不写业务逻辑；零 NoneBot import（3a R1）。

P1-1（2026-08-24 M0 复查）：原骨架 `now/is_daytime/tick_forward` 与 2a4c 接口
（IF01~IF12：is_enabled/season_now/period_now/weather_now/map_pool/cycle_tick/
time_remaining/map_weather/check_changes/maybe_broadcast/load_time_state/
save_time_state/recalc_on_config_change）**完全不对齐**，且 `now` 语义与契约
「UTC+8 秒级时间戳参数」相反——已按 IF01~IF12 重建占位；里程碑标注 M1→M3
（时间天气属里程碑计划 M3 地图副本时间）。
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

__all__ = ["WorldTime"]

_NOT_IMPL_MSG = "M3 实装：世界时间引擎（细化_2a4a / 细化_2a4c IF01~IF12）"


class WorldTime:
    """时间引擎：三周期（季节/时段/天气）懒计算时钟。M3 实装，本里程碑仅签名。"""

    # IF01 系统总开关
    def is_enabled(self) -> bool:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF02 季节查询（now: UTC+8 秒级时间戳，缺省=当前；纯函数）
    def season_now(self, now: Optional[int] = None) -> str:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF03 时段查询（dawn/noon/dusk/night/midnight）
    def period_now(self, now: Optional[int] = None) -> str:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF04 天气查询（玩家当前所在图，上下文绑定）
    def weather_now(self, map_id: str, now: Optional[int] = None) -> str:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF05 生效池（覆盖池 else 默认池）
    def map_pool(self, map_id: str) -> List[str]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF06 周期索引/节拍（kind ∈ season/period/weather）
    def cycle_tick(self, kind: str, now: Optional[int] = None) -> int:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF07 倒计时（距下次变化秒数）
    def time_remaining(self, kind: str, now: Optional[int] = None) -> int:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF08 确定性抽签（同 tick 同池跨群/进程/重启同值）
    def map_weather(self, map_id: str, tick: int, now: Optional[int] = None) -> str:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF09 变化检测钩子（每条指令处理前调用）
    def check_changes(self, player: Any, map_id: str) -> List[Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF10 懒广播（broadcast.enabled 默认 false）
    def maybe_broadcast(self, changes: Sequence[Any], ctx: Any) -> None:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF11 世界状态存档（读写 world_state.time_state）
    async def load_time_state(self) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    async def save_time_state(self) -> None:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # IF12 配置变更重排（旧缓存索引失效自动重算 + 黄提示）
    def recalc_on_config_change(self) -> None:
        raise NotImplementedError(_NOT_IMPL_MSG)
