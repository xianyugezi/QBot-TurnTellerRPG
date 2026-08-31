"""M10 钓鱼·批2·路2C：/鱼讯 + /收杆 指令壳单测（主 agent 收口补齐）。

文件名：tests/unit/test_fishing_reel_commands.py
创建时间：2026-08-31
作者：Hermes 主 agent（路2C 子 agent 撞 429 半落盘，测试由主 agent 补齐）

覆盖：细化_2c1b §四（收杆三选一 TC-15~20）/ §五（/鱼讯 TC-21~23）。
"""

from __future__ import annotations

from types import SimpleNamespace

from qbot_rpg.commands.fishing_reel_commands import (
    cmd_fish_bite,
    cmd_fish_reel,
)
from qbot_rpg.core.fishing import (
    STATE_BITE,
    STATE_IDLE,
    STATE_WAITING,
    FishingEngine,
)


def _parsed(*tokens: str) -> SimpleNamespace:
    return SimpleNamespace(tokens=list(tokens), args=[])


def _ctx(**kw: object) -> dict:
    ctx: dict = {
        "now": 1000,
        "settings": {},
        "fish_state": {},
        "rng": None,
    }
    ctx.update(kw)
    return ctx


# ---------------------------------------------------------------------------
# /鱼讯（TC-21/22/23）
# ---------------------------------------------------------------------------
def test_bite_idle_no_session() -> None:
    """空闲态 /鱼讯 → 空态「无进行中钓局」不报错（TC-23）。"""
    ctx = _ctx(fish_state={})
    out = cmd_fish_bite(_parsed("鱼讯"), ctx)
    assert "无进行中钓局" in out


def test_bite_waiting() -> None:
    """S2 等待中 /鱼讯 → 钓点/已耗时/等待中（TC-21）。"""
    ctx = _ctx(fish_state={"state": STATE_WAITING, "spot_id": "gp_moon_grass",
                           "cast_at": 900})
    out = cmd_fish_bite(_parsed("鱼讯"), ctx)
    assert "gp_moon_grass" in out
    assert "等待中" in out
    assert "100" in out  # 已耗时 100s


def test_bite_triggered() -> None:
    """S3 已触发 /鱼讯 → 鱼讯类别 + 收杆提醒（TC-22）。"""
    ctx = _ctx(fish_state={"state": STATE_BITE, "spot_id": "gp_moon_grass",
                           "bite_kind": "tug", "golden": False})
    out = cmd_fish_bite(_parsed("鱼讯"), ctx)
    assert "拉扯" in out
    assert "收杆" in out


def test_bite_triggered_golden_line() -> None:
    """S3 金闪 → 金闪标记行（鱼王预告，批4 接线）。"""
    ctx = _ctx(fish_state={"state": STATE_BITE, "spot_id": "gp_moon_grass",
                           "bite_kind": "violent", "golden": True})
    out = cmd_fish_bite(_parsed("鱼讯"), ctx)
    assert "金闪" in out


def test_bite_off_mode() -> None:
    """off 模式 /鱼讯 → 拒绝（GU-01）。"""
    ctx = _ctx(settings={"fishing": {"mode": "off"}}, fish_state={})
    out = cmd_fish_bite(_parsed("鱼讯"), ctx)
    assert "关闭" in out


# ---------------------------------------------------------------------------
# /收杆 三选一（TC-15~20）
# ---------------------------------------------------------------------------
def _reel_ctx(state: str = STATE_BITE, **kw: object) -> dict:
    fs: dict = {"state": state, "spot_id": "gp_moon_grass",
                "cast_at": 900, "bite_kind": "micro", "golden": False}
    fs_extra = kw.pop("fs", None)
    if isinstance(fs_extra, dict):
        fs.update(fs_extra)
    ctx = _ctx(fish_state=fs, **kw)
    return ctx


def test_reel_stop_no_roll() -> None:
    """止损 → 不 roll，饵已计耗不返还、无收益（TC-17）。"""
    ctx = _reel_ctx()
    out = cmd_fish_reel(_parsed("收杆", "止损"), ctx)
    assert "止损" in out
    assert "无鱼获" in out


def test_reel_auto_default() -> None:
    """无参 /收杆 → 默认自动（细化 §4.1）。"""
    ctx = _reel_ctx()
    out = cmd_fish_reel(_parsed("收杆"), ctx)
    assert "收杆成功" in out


def test_reel_auto_explicit() -> None:
    """/收杆 自动 → 基础 roll 出鱼。"""
    ctx = _reel_ctx()
    out = cmd_fish_reel(_parsed("收杆", "自动"), ctx)
    assert "收杆成功" in out


def test_reel_full() -> None:
    """/收杆 满力 → 升级 roll 出鱼（+稀有度/冠级概率）。"""
    ctx = _reel_ctx()
    out = cmd_fish_reel(_parsed("收杆", "满力"), ctx)
    assert "收杆成功" in out


def test_reel_bad_choice() -> None:
    """非法 choice → 提示三选一（R-2，不报错）。"""
    ctx = _reel_ctx()
    out = cmd_fish_reel(_parsed("收杆", "乱来"), ctx)
    assert "满力" in out and "自动" in out and "止损" in out


def test_reel_timeout_lost() -> None:
    """决策窗超时 → TR-07 跑鱼（TC-08）。"""
    eng = FishingEngine(settings={}, rng=None)
    # 引擎构造后强制 fish_state 过期：bite_ts 很久前（注意 bite_ts=0 会被 or now 吞）
    ctx = _reel_ctx(fs={"state": STATE_BITE, "spot_id": "gp_moon_grass",
                        "cast_at": 0, "bite_ts": 1, "bite_kind": "micro"})
    ctx["now"] = 100000  # 距 bite_ts=1 已 99999s >> carry_sec 90
    ctx["fishing_engine"] = eng
    out = cmd_fish_reel(_parsed("收杆", "自动"), ctx)
    assert "跑" in out or "超时" in out


def test_reel_off_mode() -> None:
    """off 模式 /收杆 → 拒绝（GU-01）。"""
    ctx = _reel_ctx(settings={"fishing": {"mode": "off"}})
    out = cmd_fish_reel(_parsed("收杆", "自动"), ctx)
    assert "关闭" in out


def test_reel_idle_no_session() -> None:
    """无进行中钓局 /收杆 → 空态（不报错）。"""
    ctx = _ctx(fish_state={"state": STATE_IDLE})
    out = cmd_fish_reel(_parsed("收杆", "自动"), ctx)
    assert "无进行中钓局" in out


def test_reel_engine_injected_reused() -> None:
    """ctx 已注入 fishing_engine → 复用（对齐路2B 引擎复用）。"""
    eng = FishingEngine(settings={}, rng=None)
    ctx = _reel_ctx(fishing_engine=eng)
    cmd_fish_reel(_parsed("收杆", "止损"), ctx)
    assert ctx["fishing_engine"] is eng
