"""M43 时间回归探针（零定时器 / 确定性；快照完整性占位）。

依据：细化_2a4a_时间引擎（§1.3 零定时器懒计算 / §二 锚点整除公式 / §六 TC-05 无状态重算）
      + 规划_路2a_地图副本.md M43（回归防线：① 零定时器 ② 确定性 ③ 快照完整性；
      旧实现三面镜子：定时器推周期 / 天气真随机 / 快照断裂）
      + m3_shared_contract §八 铁律 1（零定时器）/2（确定性）/10（快照完整性）。

探针范围（时间相关两条 + 占位一条）：
  ① 零定时器 —— glob 扫 qbot_rpg/engine/worldtime.py + time_query.py 源码，断言无
     time.sleep / threading / Timer / schedule 字样（周期值只由锚点公式得出）。
  ② 确定性 —— 同 now 两次 cycle_tick 同值；不同 now 跨年不溢出（大时间戳为有限整数，
     季节/时段索引始终落 0..3 / 0..4）。
  ③ 快照完整性 —— 战斗快照续玩（ai_state+combo_state+换区上下文逐字段一致）由批次 7
     （M27-M30，细化_1g3 快照续战）覆盖，本路登记 skip 占位 + 注释。
"""
from __future__ import annotations

import datetime
import glob
import re
from pathlib import Path

import pytest

from qbot_rpg.engine.worldtime import DEFAULT_POOL, ANCHOR, WorldTime

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))

# 仓库根 = tests/unit/test_time_regression.py 上溯三级
_REPO_ROOT = Path(__file__).resolve().parents[2]

# M43① 零定时器探针：禁止的定时器驱动字样（周期值只能由锚点公式得出）
_TIMER_TOKENS = re.compile(r"time\.sleep|\bthreading\b|\bTimer\b|\bschedule\b")


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（与引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=_TZ_UTC8).timestamp())


def default_cfg() -> dict:
    """默认 time_cycle 配置（细化_2a4a §1.3 拍板值；对齐 test_time_cycle_config）。"""
    return {"time_cycle": {
        "enabled": True,
        "season": {"season_days": 7},
        "period": {"period_minutes": 60},
        "weather": {"weather_minutes": 60, "default_pool": list(DEFAULT_POOL)},
        "broadcast": {"enabled": False, "mode": "lazy"},
    }}


def _engine_sources() -> list:
    """glob 扫 qbot_rpg/engine/{worldtime,time_query}.py；文件缺失时探针大声失败。"""
    files = []
    for pattern in ("worldtime.py", "time_query.py"):
        hits = sorted(glob.glob(str(_REPO_ROOT / "qbot_rpg" / "engine" / pattern)))
        assert hits, f"M43①: 引擎源码缺失 {pattern}（glob 未命中）"
        files.extend(hits)
    return files


# -------------------------------------------------------------------------------------
# ① 零定时器：周期值只由锚点公式得出，无定时器驱动
# -------------------------------------------------------------------------------------
def test_m43_zero_timer_in_engine_sources():
    sources = _engine_sources()
    assert len(sources) >= 2  # worldtime.py + time_query.py 均在扫描范围内
    for path in sources:
        src = Path(path).read_text(encoding="utf-8")
        hits = sorted(set(_TIMER_TOKENS.findall(src)))
        assert not hits, f"M43① 零定时器违反：{path} 含定时器字样 {hits}"


# -------------------------------------------------------------------------------------
# ② 确定性：同 now 两次 cycle_tick 同值；不同 now 跨年不溢出
# -------------------------------------------------------------------------------------
def test_m43_determinism_same_now_same_tick():
    wt = WorldTime(default_cfg())
    now = _ts(2026, 8, 16)
    for kind in ("season", "period", "weather"):
        assert wt.cycle_tick(kind, now) == wt.cycle_tick(kind, now)


def test_m43_determinism_across_years_no_overflow():
    wt = WorldTime(default_cfg())
    for y in (2030, 2099, 2999, 9999):
        now = _ts(y, 12, 31, 23, 59, 59)
        s = wt.cycle_tick("season", now)
        p = wt.cycle_tick("period", now)
        w = wt.cycle_tick("weather", now)
        # 索引恒为有限整数且季节/时段落枚举范围内（0..3 / 0..4），跨年不溢出
        assert isinstance(s, int) and 0 <= s <= 3
        assert isinstance(p, int) and 0 <= p <= 4
        assert isinstance(w, int)
        # 同 now 重算一致（确定性跨年成立）
        assert w == wt.cycle_tick("weather", now)
    # 极端大时间戳（9999 年末）weather_tick 为有限正整数
    assert wt.cycle_tick("weather", _ts(9999, 12, 31, 23, 59, 59)) > 0


def test_m43_anchor_before_negative_diff_deterministic():
    # 锚点前（负数 diff）同样确定：同 now 两次同值，且与大时间戳均不溢出
    wt = WorldTime(default_cfg())
    now = ANCHOR - 86400
    assert wt.cycle_tick("season", now) == wt.cycle_tick("season", now)
    assert wt.cycle_tick("period", now) == wt.cycle_tick("period", now)
    assert wt.cycle_tick("weather", now) == wt.cycle_tick("weather", now)


# -------------------------------------------------------------------------------------
# ③ 快照完整性占位：战斗快照续玩由批次 7 覆盖，本路登记 skip + 注释
# -------------------------------------------------------------------------------------
@pytest.mark.skip(reason="战斗快照续玩（ai_state+combo_state+换区上下文逐字段一致）由批次 7 "
                         "（M27-M30，细化_1g3 快照续战与测试）覆盖，本路仅登记 M43③ 占位；"
                         "批次 7 落地后在此补真实断言")
def test_m43_snapshot_integrity_placeholder():
    """M43 回归③ 占位：快照完整性（中断 → 续玩状态字段一致）。

    旧实现第三条死因 = 快照断裂：战斗中断续玩丢 combo_state/换区上下文，续玩=重打
    （规划_路2a_地图副本.md 〇 三面镜子）。批次 7（M27 快照完整性 / M30 死亡复活）
    实现战斗快照续玩链路后，在此断言 ai_state + combo_state + 换区上下文逐字段一致；
    当前战斗快照链路未落地，登记 skip，不做假断言冒充通过。
    """
    assert False  # 占位：批次 7 落地后替换为真实快照字段断言（skip 状态，不会执行）