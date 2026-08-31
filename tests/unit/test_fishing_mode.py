"""M10 批5·路5B：钓鱼模式三态路由单测（tests/unit/test_fishing_mode.py）。

文件名：tests/unit/test_fishing_mode.py
创建时间：2026-08-31
作者：Hermes 子agent-5B（M10 钓鱼实现组批5·路5B：mode 三态路由）

覆盖（T17 · 细化_2c1b §2.4 + §六 TC-09/14 + 定稿 v1.0.1 L4/L67/L73）：
  - mode_of：三态归一（full/simple/off）+ 非法回落 full + 缺失/非 str 兜底
  - mode_matrix：三态行为矩阵断言（full 完整 FSM / simple 短接直出 / off 全拒）
  - feature_available：full 专属功能门控——wait/bite/reel/king 三态可达性 +
    simple 下 king 不可达 → 金闪永不出现（TC-13）+ off 全拒
  - direct_catch / rejects_all：单消息直出（simple）/ 全拒绝（off）门控
  - command_allowed：指令可达性（/钓鱼 /收杆 /鱼讯）三态矩阵（TC-09）
  - simple 接线端到端：start_fishing 短接 → settle_catch 直接结算（出鱼结算链路
    可达：bite_check 不经过、鱼王不可达），补白 M-1（构造器注入 ctx 后 start_fishing
    simple 返回无 wait_sec 键 → 指令壳 cast_fishing 0 兜底已就位）
  - 确定性：同 mode 同 ctx → mode_of/mode_matrix 恒同（纯函数零 IO 零定时器）
用例数：18 例（≥14 硬性要求；TC-09/TC-13/TC-14 全覆盖）。

依据：
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §2.4（模式前缀）/ §六 TC-09/13/14
  - 定稿 v1.0.1 L4（simple 直出）/ L67（off 拒绝）/ L73（mode 三态）
  - docs/m10_shared_contract.md §三（mode 路由）/ §四（R-04 mode 约束）
  - docs/m10_接口摸底.md §九（坑位：M43 探针措辞）
铁律：零 NoneBot import；确定性测试种子化（无裸 random）；docstring 不含
      定时器调用字样字面量（M43 探针，用「零定时器/零睡眠」措辞）；无 emoji。
"""

from __future__ import annotations

import random
from typing import Any, Dict, MutableMapping, cast

from qbot_rpg.content.fishing_models import FishDef
from qbot_rpg.core.fishing import FishingEngine, STATE_IDLE, STATE_REELED
from qbot_rpg.core.fishing_mode import (
    CMD_BITE,
    CMD_FISH,
    CMD_REEL,
    FEATURE_BITE,
    FEATURE_KING,
    FEATURE_REEL,
    FEATURE_WAIT,
    MATRIX_KEYS,
    MODE_FULL,
    MODE_OFF,
    MODE_SIMPLE,
    command_allowed,
    direct_catch,
    feature_available,
    king_available,
    mode_matrix,
    mode_of,
    rejects_all,
)
from qbot_rpg.core.fishing_settle import settle_catch

# =====================================================================================
# 夹具
# =====================================================================================

SPOT = "gp_moon_grass"

# 夹具鱼种（对齐 test_fishing.py 口径：SPOT 候选三档 rarity）
_SPECIES_RAW: Dict[str, Dict[str, Any]] = {
    "silver_carp": {
        "id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
        "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
        "spots": [SPOT], "preferred_bait": ["饵_蚯蚓"],
    },
    "rare_loach": {
        "id": "rare_loach", "name": "赤纹泥鳅", "rarity": "rare",
        "size_min": 5.0, "size_max": 30.0, "weight_min": 0.1, "weight_max": 1.0,
        "spots": [SPOT], "preferred_bait": ["饵_面团"],
    },
    "golden_koi": {
        "id": "golden_koi", "name": "金鳞鲤", "rarity": "gold",
        "size_min": 20.0, "size_max": 90.0, "weight_min": 1.0, "weight_max": 12.0,
        "spots": [SPOT], "preferred_bait": ["饵_黄金虫"],
    },
}

BASE_NOW = 1_800_000_000  # 固定时钟（UTC+8 epoch 秒，远离 dayroll 05:00 日界）


def _fish(id: str) -> FishDef:
    return cast(FishDef, FishDef.from_entry(_SPECIES_RAW[id]))


def _species() -> list:
    return [_fish("silver_carp"), _fish("rare_loach"), _fish("golden_koi")]


def _settings(mode: str = MODE_FULL) -> Dict[str, Any]:
    """settings 全量（fishing 段 9 契约键 + mode 三态）。"""
    return {
        "fishing": {
            "mode": mode,
            "bait_ids": ["饵_蚯蚓", "饵_面团", "饵_小鱼", "饵_黄金虫", "饵_龙涎"],
            "bait_bonus": {"rare": 8, "gold": 2},
            "rod_full_bonus": {"rare": 4, "gold": 2},
            "crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95},
            "wait_sec": {"min": 0, "max": 0},
            "daily_limit": 20,
            "energy": {"enabled": False},
            "king_event": {"enabled": True, "window_daily": 2, "chance": 0.3},
        }
    }


def _ctx(mode: str = MODE_FULL, **kw: Any) -> Dict[str, Any]:
    """构造测试 ctx：settings / now / rng / fish_table / player 注入。"""
    ctx: Dict[str, Any] = {
        "now": BASE_NOW,
        "settings": _settings(mode),
        "rng": random.Random(42),
        "fish_table": {sid: dict(raw) for sid, raw in _SPECIES_RAW.items()},
        "player": {"persistent_state": {}},
    }
    ctx.update(kw)
    return ctx


def _engine(ctx: MutableMapping[str, Any], **kw: Any) -> FishingEngine:
    """构造引擎：species 走构造器注入（确定性；simple 结算全链路用）。"""
    return FishingEngine(species=_species(), rng=ctx.get("rng"), **kw)


# =====================================================================================
# A. mode_of 三态归一（TC-09）
# =====================================================================================
def test_mode_of_full_simple_off() -> None:
    """TC-09 前缀：三态全归一（full/simple/off 各自原样返回）。"""
    assert mode_of(_ctx(mode="full")) == "full"
    assert mode_of(_ctx(mode="simple")) == "simple"
    assert mode_of(_ctx(mode="off")) == "off"


def test_mode_of_illegal_falls_back_full() -> None:
    """非法 mode（非枚举值）→ 回落 full（V4 枚举硬错归校验器，读段不拦）。"""
    assert mode_of(_ctx(mode="hard")) == "full"
    assert mode_of(_ctx(mode="")) == "full"
    assert mode_of(_ctx(mode="FULL")) == "full"


def test_mode_of_missing_or_nonstr_falls_back_full() -> None:
    """缺失/非 str mode → 回落 full（fishing_cfg A-4 兜底口径）。"""
    assert mode_of({}) == "full"
    assert mode_of({"fishing": {}}) == "full"
    assert mode_of({"fishing": {"mode": 3}}) == "full"
    assert mode_of({"fishing": {"mode": None}}) == "full"


def test_mode_of_section_or_ctx_forms() -> None:
    """入参三态容错：settings 全量 / fishing 段本身 / ctx 形态 同结果。"""
    seg = {"mode": "simple"}
    assert mode_of({"fishing": seg}) == "simple"
    assert mode_of(seg) == "simple"
    assert mode_of({"settings": {"fishing": seg}}) == "simple"


# =====================================================================================
# B. mode_matrix 三态行为矩阵（细化 §2.4 / TC-09/14）
# =====================================================================================
def test_matrix_three_modes_and_key_order() -> None:
    """矩阵三行齐全 + 行键序固定（MATRIX_KEYS：path/wait/bite/reel/king/direct/
    reject_all）。"""
    m = mode_matrix()
    assert set(m.keys()) == {MODE_FULL, MODE_SIMPLE, MODE_OFF}
    for mode in (MODE_FULL, MODE_SIMPLE, MODE_OFF):
        assert tuple(m[mode].keys()) == MATRIX_KEYS


def test_matrix_full_complete_fsm() -> None:
    """full：S0→S1→S2→S3→{ST,SL,BOSS} 完整状态机——等待+鱼讯+收杆三选一+鱼王。"""
    row = mode_matrix()[MODE_FULL]
    assert row["path"] == "S0->S1->S2->S3->{ST,SL,BOSS}"
    assert row["wait"] is True and row["bite"] is True
    assert row["reel"] is True and row["king"] is True
    assert row["direct"] is False and row["reject_all"] is False


def test_matrix_simple_shortcut() -> None:
    """simple：S0→S1→ST 短接——/钓鱼 单消息直出（无等待/鱼讯/鱼王）。"""
    row = mode_matrix()[MODE_SIMPLE]
    assert row["path"] == "S0->S1->ST"
    assert row["direct"] is True
    assert row["wait"] is False and row["bite"] is False
    assert row["reel"] is False and row["king"] is False
    assert row["reject_all"] is False


def test_matrix_off_reject_all() -> None:
    """off：所有钓鱼指令拒绝，不进入任何状态（GU-01 / 定稿 L67）。"""
    row = mode_matrix()[MODE_OFF]
    assert row["reject_all"] is True
    assert row["wait"] is False and row["bite"] is False
    assert row["reel"] is False and row["king"] is False
    assert row["direct"] is False


# =====================================================================================
# C. feature_available 门控（full 专属功能可达性）
# =====================================================================================
def test_feature_full_all_reachable() -> None:
    """full：等待/鱼讯/收杆/鱼王 全可达（完整流程）。"""
    for feat in (FEATURE_WAIT, FEATURE_BITE, FEATURE_REEL, FEATURE_KING):
        assert feature_available("full", feat) is True


def test_feature_simple_none_reachable_king_isolated() -> None:
    """simple：等待/鱼讯/收杆/鱼王 全不可达——king_event 不可达 → 金闪永不出现
    （TC-13 金闪隔离；无 S2/S3 实例 TC-14）。"""
    for feat in (FEATURE_WAIT, FEATURE_BITE, FEATURE_REEL, FEATURE_KING):
        assert feature_available("simple", feat) is False
    assert king_available("simple") is False


def test_feature_off_none_reachable() -> None:
    """off：全不可达（不进入任何状态，GU-01）。"""
    for feat in (FEATURE_WAIT, FEATURE_BITE, FEATURE_REEL, FEATURE_KING):
        assert feature_available("off", feat) is False


def test_feature_unknown_feature_or_mode_fallback() -> None:
    """未知 feature → False 保守拒绝；非法 mode 回落 full 后按 full 判定。"""
    assert feature_available("full", "nonsense") is False
    assert feature_available("simple", "nonsense") is False
    assert feature_available("bogus", FEATURE_WAIT) is True  # 非法 mode → full
    assert feature_available("", FEATURE_WAIT) is True


def test_direct_catch_and_rejects_all_gates() -> None:
    """单消息直出（仅 simple）/ 全拒绝（仅 off）便捷门控。"""
    assert direct_catch("simple") is True
    assert direct_catch("full") is False and direct_catch("off") is False
    assert rejects_all("off") is True
    assert rejects_all("full") is False and rejects_all("simple") is False


# =====================================================================================
# D. command_allowed 指令可达性（GU-01 模式路由 / TC-09）
# =====================================================================================
def test_command_full_all_three() -> None:
    """full：/钓鱼 /鱼讯 /收杆 三指令全可达。"""
    for cmd in (CMD_FISH, CMD_BITE, CMD_REEL):
        assert command_allowed("full", cmd) is True


def test_command_simple_only_fish() -> None:
    """simple：仅 /钓鱼 可达（单消息直出）；/鱼讯 /收杆 拒绝（无 S2/S3 实例）。"""
    assert command_allowed("simple", CMD_FISH) is True
    assert command_allowed("simple", CMD_BITE) is False
    assert command_allowed("simple", CMD_REEL) is False


def test_command_off_all_rejected() -> None:
    """off：/钓鱼 /收杆 /鱼讯 全拒（GU-01 / TC-09）。"""
    for cmd in (CMD_FISH, CMD_BITE, CMD_REEL):
        assert command_allowed("off", cmd) is False


def test_command_unknown_rejected() -> None:
    """未知指令 → False 保守拒绝（不炸）。"""
    assert command_allowed("full", "unknown_cmd") is False
    assert command_allowed("simple", "unknown_cmd") is False
    assert command_allowed("off", "unknown_cmd") is False


# =====================================================================================
# E. simple 接线端到端（出鱼结算链路可达：bite_check 不经过、鱼王不可达）
# =====================================================================================
def test_simple_start_direct_settle_chain() -> None:
    """simple 接线：start_fishing 短接（S0→S1→ST）→ settle_catch 直接结算出鱼
    （补白 M-1：构造器注入 ctx 后 simple 分支返回无 wait_sec 键 → 指令壳
    cast_fishing 0 兜底已就位，链路可达）。"""
    ctx = _ctx(mode="simple")
    eng = _engine(ctx)
    got = eng.start_fishing(ctx, SPOT)
    assert got["ok"] is True
    assert got["state"] == STATE_REELED
    assert got["direct"] is True
    assert got["settle_pending"] is True
    assert ctx["fish_state"]["state"] == STATE_REELED
    # 直接结算：消费 start_fishing 返回（simple 分支无 wait_sec 键）
    settled = settle_catch(ctx, got)
    assert settled["ok"] is True
    assert settled["species_id"] in _SPECIES_RAW
    assert settled["size"] > 0 and settled["weight"] > 0
    assert settled["crown"] in ("normal", "silver", "gold", "big_silver", "big_gold", "reverse")
    # 图鉴点亮（保留鱼种/图鉴/冠级/饵/熟练——simple 不砍结算内容）
    entry = ctx["codex_state"]["fish"][settled["species_id"]]
    assert entry["seen"] is True
    assert entry["caught_count"] == 1
    # 日计数 +1 保留
    assert ctx["fish_state"]["casts"] == 1


def test_simple_king_unreachable_via_gate() -> None:
    """simple 接线：鱼王不可达——king_available(simple)=False 且引擎 bite_check
    拒绝（无 S2/S3 实例），金闪永不出现（TC-13/14）。"""
    ctx = _ctx(mode="simple")
    eng = _engine(ctx)
    assert eng.start_fishing(ctx, SPOT)["ok"] is True
    bite = eng.bite_check(ctx, king_hit=True)
    assert bite["ok"] is False
    assert bite["reason"] == "simple_no_wait"
    assert bite["bite"] is False
    # 金闪隔离：king_hit 传 True 也不会产生金闪（simple 下鱼讯实例不存在）
    assert "golden" not in bite or bite["golden"] is False
    assert king_available("simple") is False


def test_simple_deterministic_and_no_wait_sec_key() -> None:
    """确定性 + 返回形态：simple 分支返回无 wait_sec/cast_at 键（无等待期）；
    同 seed 同 ctx 两次调用恒同。"""
    ctx = _ctx(mode="simple")
    eng = _engine(ctx)
    first = eng.start_fishing(ctx, SPOT)
    assert "wait_sec" not in first and "cast_at" not in first
    assert first["message"] == "已下钩并直接出鱼（simple 模式无等待/鱼讯）"
    # 同 seed 重放 → 恒同（纯状态机确定性；日计数两次独立 ctx 相同）
    ctx2 = _ctx(mode="simple")
    eng2 = _engine(ctx2)
    second = eng2.start_fishing(ctx2, SPOT)
    assert second["ok"] is True and second["state"] == STATE_REELED
    assert second["direct"] is True and second["settle_pending"] is True


# =====================================================================================
# F. off 拒绝一致性（引擎 + 矩阵 + 指令门控三方一致）
# =====================================================================================
def test_off_engine_and_gates_consistent() -> None:
    """off 一致性：引擎三方法全拒（GU-01）且 command_allowed 全拒、矩阵
    reject_all=True——三方一致（TC-09）。"""
    ctx = _ctx(mode="off")
    eng = _engine(ctx)
    assert eng.start_fishing(ctx, SPOT)["guard"] == "GU-01"
    assert eng.bite_check(ctx)["guard"] == "GU-01"
    assert eng.reel_in(ctx, "auto")["guard"] == "GU-01"
    for cmd in (CMD_FISH, CMD_BITE, CMD_REEL):
        assert command_allowed("off", cmd) is False
    assert mode_matrix()[MODE_OFF]["reject_all"] is True
    # 引擎状态不被触碰（不进入任何状态）：off 拒绝路径不写入任何会话字段——
    # 引擎 _fish_state_of 惰性建空节点（state 键不存在），守卫 GU-01 短路于其前
    fs = ctx.get("fish_state")
    assert fs is not None and fs.get("state") in (None, STATE_IDLE)
    assert "spot_id" not in fs and "cast_at" not in fs and "last" not in fs
    assert ctx["player"]["persistent_state"]["fish_state"] is fs
