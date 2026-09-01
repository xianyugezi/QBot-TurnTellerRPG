"""M13 批10 路10B · 6c 换季结算边界引擎单元测试（tests/unit/test_battle_season.py）。

文件名：test_battle_season.py
创建时间：2026-09-02
作者：Hermes 子agent-10B（M13 6c 季节技能组实现组批10路10B：并发同仓，仅新建
  本文件 + qbot_rpg/core/battle_season.py；不改动兄弟路文件）

依据：docs/细化/细化_6c_资源轴与职业机制.md：
  - §2.2 EFF-2（进战懒加载）/ EFF-3（展示过滤置灰 + 普攻防御兜底全年可用）；
  - §2.3 机制 M6 流程 F-R2 全六步（① 懒重读 ② 检测标记待结算 ③ 回合结束
    tick 后切换 ④ 保留项 ⑤ 反馈+on_season_change ⑥ 战斗外不切换）；
  - §2.3 SC-1（待结算期按旧组校验）/ SC-2（引擎零新状态机）/ SC-3（切换
    幂等恰一次）；§2.5 E1/E5（on_season_change 事件：战斗内换季才触发，
    同一结算边界只触发一次）；§0.3 D-05（换季待结算期行动口径）；
  - §六 TC-11（换季结算边界全链路断言）。
测试目标：qbot_rpg.core.battle_season.{SEASONS, SEASON_ANY, BATTLE_SEASON_KEY,
  SEASON_HINT_KEY, SEASON_CHANGE_MESSAGE_KEY, ON_SEASON_CHANGE_KEY,
  init_battle_season, effective_season, pending_flag, detect_season_change,
  settle_season_change, filter_skills, skill_available, tick_season_boundary}。

覆盖矩阵（18 用例 = A 状态段 3 + B 换季检测 5 + C 换季结算切换 4 +
  D 展示过滤置灰 3 + E 兜底/幂等 3）：
  A init/effective/pending（EFF-2 进战懒加载 + P-2 缺省骨架）
  B detect_season_change（F-R2 ② 标记待结算 / SC-1 当回合旧组 / SC-3 幂等
    复位 / 懒重读差异检测 / 防御建段）
  C settle_season_change（F-R2 ③ 结算边界切换 / 保留项零触碰 F-R2 ④ /
    恰一次 on_season_change E5 / 非 pending 幂等无操作 SC-3 / 防御回环）
  D filter_skills / skill_available（EFF-3 非当季置灰 + 提示语义键 /
    当季+通用常亮 / 普攻 basic + 防御 guard 全年可用兜底）
  E tick_season_boundary（F-R2 ①→③ 组合挂点 / SEASON_ANY 无季节环境全
    可用 / 战斗外无快照降级）

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（docstring 不写
睡眠/定时器字样）；不引入随机；只写本文件。
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from qbot_rpg.core.battle_season import (
    BATTLE_SEASON_KEY,
    ON_SEASON_CHANGE_KEY,
    PENDING_STATE_KEY,
    SEASON_ANY,
    SEASON_CHANGE_MESSAGE_KEY,
    SEASON_HINT_KEY,
    SEASON_STATE_KEY,
    detect_season_change,
    effective_season,
    filter_skills,
    init_battle_season,
    pending_flag,
    settle_season_change,
    skill_available,
    tick_season_boundary,
)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------


def _battle_state() -> Dict[str, Any]:
    """战斗快照骨架（含玩家 buff/连段/印记/冷却等保留项载体，F-R2 ④）。"""
    return {
        "status": "active",
        "turn": 1,
        "player": {"hp": 500, "mp": 100, "buff_ids": ["atk_up"]},
        "enemy": {"hp": 500},
        "combo_state": {"count": 3},
        "marks_state": {"player": ["mark_a"]},
        "cooldown_state": {"skill_x": 2},
    }


def _skill(
    sid: str,
    season: Any = None,
    stype: str = "active",
) -> Dict[str, Any]:
    """技能条目（season 可选，缺省通用；type 可指定 basic/guard 等）。"""
    entry: Dict[str, Any] = {"id": sid, "name": sid, "type": stype}
    if season is not None:
        entry["season"] = season
    return entry


class _ProtoSkill:
    """协议对象技能（模拟 SkillDef 属性访问器形态；G0 注入）。"""

    def __init__(self, sid: str, season: Any = None, stype: str = "active") -> None:
        self._id = sid
        self._season = season
        self._type = stype

    @property
    def id(self) -> str:  # noqa: A003
        return self._id

    @property
    def season(self) -> Any:
        return self._season

    @property
    def type(self) -> str:  # noqa: A003
        return self._type


@pytest.fixture()
def battle_state() -> Dict[str, Any]:
    """战斗快照夹具（每用例独立实例）。"""
    return _battle_state()


# ===========================================================================
# A 状态段读写（EFF-2 进战懒加载 + P-2 缺省骨架）
# ===========================================================================


def test_init_battle_season_defaults_to_general() -> None:
    """进战懒加载：初始生效季节 = 当前季节；缺省回落通用（P-2）。"""
    bs = _battle_state()
    seg = init_battle_season(bs)
    assert bs[BATTLE_SEASON_KEY] == seg
    assert seg[SEASON_STATE_KEY] == SEASON_ANY
    assert seg[PENDING_STATE_KEY] is False
    # 显式初始季节
    seg2 = init_battle_season(bs, season="spring")
    assert seg2[SEASON_STATE_KEY] == "spring"
    assert seg2[PENDING_STATE_KEY] is False
    # 非法季节回落通用（P-10 防御）
    seg3 = init_battle_season(bs, season="sumer")
    assert seg3[SEASON_STATE_KEY] == SEASON_ANY


def test_effective_season_reads_state() -> None:
    """生效季节读取：已 init → 段内值；未 init / 段缺失 → 通用兜底。"""
    bs = _battle_state()
    assert effective_season(bs) == SEASON_ANY  # 未 init 兜底
    init_battle_season(bs, season="summer")
    assert effective_season(bs) == "summer"
    # 非 Mapping 快照防御
    assert effective_season(None) == SEASON_ANY  # type: ignore[arg-type]


def test_pending_flag_reads_marker() -> None:
    """待结算标记读取：未 init → False；置位后 → True。"""
    bs = _battle_state()
    assert pending_flag(bs) is False
    init_battle_season(bs, season="spring")
    assert pending_flag(bs) is False
    bs[BATTLE_SEASON_KEY][PENDING_STATE_KEY] = True
    assert pending_flag(bs) is True


# ===========================================================================
# B 换季检测（F-R2 ② 懒重读检测差异 → 标记待结算）
# ===========================================================================


def test_detect_marks_pending_on_season_diff() -> None:
    """检测到差异 → 标记待结算（F-R2 ②），本回合不变更（SC-1）。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    result = detect_season_change(bs, current_season="summer")
    assert result["changed"] is True
    assert result["detected"] is True
    assert result["pending"] is True
    # 标记已写回快照；生效季节仍是 spring（当回合行动照旧组校验，D-05）
    assert pending_flag(bs) is True
    assert effective_season(bs) == "spring"
    assert bs[BATTLE_SEASON_KEY][SEASON_STATE_KEY] == "spring"


def test_detect_rereread_same_diff_keeps_pending() -> None:
    """待结算期重复检测（同回合）：差异仍在 → pending 保持（SC-3 幂等，
    结算前不丢失待结算标记；生效季节未切换前差异持续）。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    detect_season_change(bs, current_season="summer")
    assert pending_flag(bs) is True
    # 生效仍为 spring、当前仍为 summer → 差异持续，pending 保持
    result = detect_season_change(bs, current_season="summer")
    assert result["changed"] is True
    assert pending_flag(bs) is True


def test_detect_after_settle_same_season_clears_pending() -> None:
    """切换后连续同季 → 无差异、不标记（SC-3 恰一次原则复位）。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    detect_season_change(bs, current_season="summer")
    settle_season_change(bs, current_season="summer")  # 生效 → summer
    assert effective_season(bs) == "summer"
    # 下一回合懒重读：当前 == 生效 → 无差异，pending 复位
    result = detect_season_change(bs, current_season="summer")
    assert result["changed"] is False
    assert pending_flag(bs) is False


def test_detect_same_season_no_marker() -> None:
    """当前季节 == 生效季节 → 不标记（SC-3 恰一次原则）。"""
    bs = _battle_state()
    init_battle_season(bs, season="winter")
    result = detect_season_change(bs, current_season="winter")
    assert result["changed"] is False
    assert pending_flag(bs) is False


def test_detect_lazy_reread_new_season() -> None:
    """懒重读检测：回合开始重读当前季节，跨多季直接检测最新差异。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    # 世界已到冬季（离线跨多周期只报最新值，check_changes 同口径）
    result = detect_season_change(bs, current_season="winter")
    assert result["changed"] is True
    assert result["season"] == "winter"
    assert pending_flag(bs) is True


def test_detect_without_init_lazy_builds_segment() -> None:
    """未 init 直接检测 → 惰性建段（防御，战斗层每回合调用前先 init）。"""
    bs = _battle_state()
    result = detect_season_change(bs, current_season="autumn")
    assert bs[BATTLE_SEASON_KEY][SEASON_STATE_KEY] == SEASON_ANY
    assert result["changed"] is True  # 通用 → autumn 有差异
    assert pending_flag(bs) is True


# ===========================================================================
# C 换季结算切换（F-R2 ③ 结算边界：回合结束 tick 后、下一回合开始前）
# ===========================================================================


def test_settle_switches_season_at_boundary() -> None:
    """待结算期结束后切换：生效季节 ← 当前季节（F-R2 ③ 结算边界）。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    detect_season_change(bs, current_season="summer")
    # 当回合行动阶段已过（旧组校验完毕）→ 结算边界切换
    result = settle_season_change(bs, current_season="summer")
    assert result["switched"] is True
    assert result["from"] == "spring"
    assert result["to"] == "summer"
    assert result["season"] == "summer"
    assert result["message_key"] == SEASON_CHANGE_MESSAGE_KEY
    assert result[ON_SEASON_CHANGE_KEY] is True
    # 快照侧：生效季节已切换、pending 复位
    assert effective_season(bs) == "summer"
    assert pending_flag(bs) is False


def test_settle_preserves_battle_state() -> None:
    """切换保留项（F-R2 ④）：MP/连段/印记/冷却/buff 全保留（零触碰）。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    detect_season_change(bs, current_season="autumn")
    settle_season_change(bs, current_season="autumn")
    # 除 battle_season 段外，快照其余键原样（P-5 零触碰）
    assert bs["player"] == {"hp": 500, "mp": 100, "buff_ids": ["atk_up"]}
    assert bs["enemy"] == {"hp": 500}
    assert bs["combo_state"] == {"count": 3}
    assert bs["marks_state"] == {"player": ["mark_a"]}
    assert bs["cooldown_state"] == {"skill_x": 2}
    assert bs["status"] == "active"
    assert bs["turn"] == 1


def test_settle_without_pending_is_noop() -> None:
    """非待结算期调用 → 幂等无操作（SC-3：不切换、不触发事件）。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    result = settle_season_change(bs, current_season="summer")
    assert result["switched"] is False
    assert result["message_key"] == ""
    assert result[ON_SEASON_CHANGE_KEY] is False
    assert effective_season(bs) == "spring"  # 未切换


def test_settle_pending_but_season_loopback_noop() -> None:
    """防御回环：pending 但当前季节 == 生效季节（检测与结算间轮转回来）
    → 不切换、复位 pending（SC-3 恰一次）。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    detect_season_change(bs, current_season="summer")
    # 结算时世界季节又回到 spring（与生效季节一致）→ 无差异不切换
    result = settle_season_change(bs, current_season="spring")
    assert result["switched"] is False
    assert result[ON_SEASON_CHANGE_KEY] is False
    assert effective_season(bs) == "spring"
    assert pending_flag(bs) is False  # 复位


# ===========================================================================
# D 展示过滤（EFF-3：非当季置灰 + 提示；当季/通用常亮）
# ===========================================================================


def test_filter_skills_greyscale_out_of_season() -> None:
    """非当季技能置灰 + 提示语义键；当季/通用常亮（EFF-3 / TC-10）。"""
    skills: List[Dict[str, Any]] = [
        _skill("spring_bloom", season="spring"),
        _skill("summer_blaze", season="summer"),
        _skill("autumn_gale", season="autumn"),
        _skill("winter_veil", season="winter"),
        _skill("four_seasons", season=None),  # 通用（全年可用）
    ]
    rows = filter_skills(skills, season="spring")
    by_id = {r["skill_id"]: r for r in rows}
    # 春组 + 通用常亮
    assert by_id["spring_bloom"]["available"] is True
    assert by_id["spring_bloom"]["grayscale"] is False
    assert by_id["spring_bloom"]["hint_key"] == ""
    assert by_id["four_seasons"]["available"] is True
    # 夏/秋/冬置灰 + 提示
    for sid in ("summer_blaze", "autumn_gale", "winter_veil"):
        assert by_id[sid]["available"] is False, sid
        assert by_id[sid]["grayscale"] is True, sid
        assert by_id[sid]["hint_key"] == SEASON_HINT_KEY, sid


def test_filter_skills_basic_guard_always_available() -> None:
    """普攻（basic）与防御（guard/defense）全年可用（EFF-3 兜底零空窗）。"""
    skills: List[Dict[str, Any]] = [
        _skill("four_seasons_art", season=None, stype="basic"),   # 普攻「四时术」
        _skill("guard", season=None, stype="guard"),               # 防御指令
        _skill("defend", season="summer", stype="defense"),        # 防御别名
        _skill("summer_skill", season="summer", stype="active"),   # 对照：非当季
    ]
    rows = filter_skills(skills, season="spring")
    by_id = {r["skill_id"]: r for r in rows}
    assert by_id["four_seasons_art"]["available"] is True
    assert by_id["four_seasons_art"]["grayscale"] is False
    assert by_id["guard"]["available"] is True
    assert by_id["defend"]["available"] is True  # 防御兜底豁免季节
    assert by_id["summer_skill"]["available"] is False  # 普通技能仍置灰


def test_filter_skills_general_environment_all_available() -> None:
    """无季节环境（SEASON_ANY）→ 全部技能可用（EFF-1 战斗外口径 / P-10）。"""
    skills: List[Dict[str, Any]] = [
        _skill("summer_blaze", season="summer"),
        _skill("winter_veil", season="winter"),
    ]
    rows = filter_skills(skills, season=SEASON_ANY)
    assert all(r["available"] for r in rows)
    assert all(not r["grayscale"] for r in rows)
    # 非列表防御降级
    assert filter_skills(None, season="spring") == []
    assert filter_skills("oops", season="spring") == []


def test_skill_available_single_check() -> None:
    """单技能当季可用判定（skill_available，EFF-3 展示/行动侧共用）。"""
    assert skill_available(_skill("spring_bloom", season="spring"), "spring") is True
    assert skill_available(_skill("summer_blaze", season="summer"), "spring") is False
    assert skill_available(_skill("four_seasons"), "winter") is True  # 通用
    assert skill_available(_skill("four_seasons_art", stype="basic"), "winter") is True
    assert skill_available(_skill("guard", stype="guard"), "winter") is True
    assert skill_available(_skill("summer_blaze", season="summer"), SEASON_ANY) is True
    # 协议对象形态（G0 注入）
    proto = _ProtoSkill("spring_bloom", season="spring")
    assert skill_available(proto, "spring") is True
    assert skill_available(proto, "winter") is False


# ===========================================================================
# E 挂点组合 / 兜底 / 降级（F-R2 ①→③ 全链路）
# ===========================================================================


def test_tick_season_boundary_full_cycle() -> None:
    """挂点全链路（TC-11）：检测差异 → 待结算 → 边界切换 → 事件信号。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    # 回合 1：春季，无差异
    r1 = tick_season_boundary(bs, current_season="spring")
    assert r1["switched"] is False
    assert effective_season(bs) == "spring"
    # 回合 2 开始：懒重读发现已到夏季（标记待结算）
    detect_season_change(bs, current_season="summer")
    assert pending_flag(bs) is True
    # 回合 2 结束 tick 后：结算边界切换（tick_season_boundary 组合入口）
    r2 = tick_season_boundary(bs, current_season="summer")
    assert r2["switched"] is True
    assert r2["to"] == "summer"
    assert r2[ON_SEASON_CHANGE_KEY] is True
    # 回合 3：新季节生效，技能列表 = 夏组 + 通用
    assert effective_season(bs) == "summer"
    r3 = tick_season_boundary(bs, current_season="summer")
    assert r3["switched"] is False  # 幂等：连续同季不重复触发（SC-3）
    assert r3[ON_SEASON_CHANGE_KEY] is False


def test_tick_season_boundary_noop_without_state() -> None:
    """无战斗快照（战斗外/已结束）→ 降级无操作（F-R2 ⑥ / P-7 防御）。"""
    result = tick_season_boundary({}, current_season="summer")
    assert result["switched"] is False
    assert result[ON_SEASON_CHANGE_KEY] is False
    # 非 Mapping 快照
    result2 = tick_season_boundary(None, current_season="summer")  # type: ignore[arg-type]
    assert result2["switched"] is False


def test_pending_round_old_group_validation_semantics() -> None:
    """D-05/SC-1：待结算期行动按旧组校验——引擎不切换生效季节，
    展示过滤在待结算期仍按旧季节判定（新季节技能下一回合才生效）。"""
    bs = _battle_state()
    init_battle_season(bs, season="spring")
    detect_season_change(bs, current_season="summer")
    # 待结算期：生效季节仍是 spring
    assert effective_season(bs) == "spring"
    # 展示侧：春组可用（旧组照常），夏组置灰（下一回合才生效）
    rows = filter_skills(
        [_skill("spring_bloom", season="spring"),
         _skill("summer_blaze", season="summer")],
        season=effective_season(bs),
    )
    by_id = {r["skill_id"]: r for r in rows}
    assert by_id["spring_bloom"]["available"] is True
    assert by_id["summer_blaze"]["available"] is False
    # 结算边界切换后：新季节生效，夏组可用
    settle_season_change(bs, current_season="summer")
    rows2 = filter_skills(
        [_skill("spring_bloom", season="spring"),
         _skill("summer_blaze", season="summer")],
        season=effective_season(bs),
    )
    by_id2 = {r["skill_id"]: r for r in rows2}
    assert by_id2["summer_blaze"]["available"] is True
    assert by_id2["spring_bloom"]["available"] is False
