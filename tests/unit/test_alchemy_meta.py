"""AlchemyMeta 单测（M8 批8-1 · 路B）——图鉴成长 / 教学目录 / 技能面板引擎。

文件名：tests/unit/test_alchemy_meta.py
创建时间：2026-08-29
作者：Hermes 子agent-8B（M8 批8-1 路B）
功能描述：qbot_rpg.core.alchemy_meta.AlchemyMeta 纯函数直测（对齐 test_codex/test_proficiency
 模式）：/图鉴 进度（F-19 lit/total/ratio/all_lit）、成长奖励 idempotent（L210）、王称号条件
 （TTL-01/TC-11/TC-19/TC-20：图鉴全亮 vs 未亮、与等级解耦）、/技能面板 查看 SP+已解锁项
 （TC-12）、SP 解锁成功+SP 不足拒绝（TC-13/14/16）、/教学 目录+机制名/未知名回目录（M-23）、
 升大师公告 6 预览（L482）。每条正反例。

依据：
  - docs/m8_contract_指令契约.md §18 /图鉴 与 /技能面板、§22 /教学
  - docs/细化/细化_2c4d_炼金指令表.md §19/§23、TC-11/12/13/14/16/27/31
  - docs/细化/细化_2c5a_职业等级与SP.md TTL-01/03、SP-02/04/05/06、§5.1 样例
  - docs/审查参考/炼金系统设计定稿.md §2.2 L63-75、§2.3 L87-89、§5.2#12 L210、§十二 L480-485

【工程补白 · 注记】
  - 炼金图鉴分母 = registry kind "recipe"+"item"（补白 1）；测试假注册表 4 配方 + 2 道具 = 6。
  - 成长奖励表经 settings.alchemy.codex_rewards 注入（补白 2），另测内置缺省表。
  - 教学表经 settings.alchemy.tutorials 注入（补白 3），另测内置缺省。
  - 6 深度机制预览 = 连锁奖励/核心镶嵌/分解回炉/量贩复制/图鉴成长/战斗即时调合（补白 4/L59）。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence

from qbot_rpg.core.alchemy_meta import (
    DEFAULT_TIER_NAMES,
    AlchemyMeta,
)
from qbot_rpg.core.proficiency import ProficiencyEngine

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

# 细化 §5.1 JSON 样例形态（8 项 sp_panel：品质/投入/特性位/复制/进化/挑战/采集量/连锁上限）
_ALCHEMY_ENTRY: Dict[str, Any] = {
    "id": "alchemy",
    "tier_names": list(DEFAULT_TIER_NAMES),
    "job_rank_levels": [0, 100, 300, 700, 1500, 3000, 6000],
    "exp_sources": {"craft": 1.0, "gather": 1.0, "combat": 1.0},
    "sp_per_level": 1,
    "sp_panel": [
        {"id": "quality_cap_10", "name": "品质上限+10", "cost": 1, "repeatable": True,
         "max_repeat": 5},
        {"id": "input_count_1", "name": "投入次数+1", "cost": 1, "repeatable": True,
         "max_repeat": 3},
        {"id": "trait_slot_1", "name": "特性位+1", "cost": 1, "repeatable": True,
         "max_repeat": 3},
        {"id": "unlock_copy", "name": "解锁复制", "cost": 1, "repeatable": False},
        {"id": "unlock_evolve", "name": "解锁进化", "cost": 1, "repeatable": False},
        {"id": "unlock_challenge", "name": "解锁挑战", "cost": 1, "repeatable": False},
        {"id": "gather_amount_1", "name": "采集量+1", "cost": 1, "repeatable": False},
        {"id": "chain_limit_1", "name": "连锁上限+1", "cost": 1, "repeatable": False},
    ],
    "energy": {"enabled": False, "max_by_tier": [5, 8, 10, 12, 15, 18, 20], "regen_sec": 1800},
    "job_tier_map": {
        "见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
        "大师": [31, 40], "宗师": [41, 50], "王": [51, 99],
    },
    "titles": [
        {"id": "contest_champion", "name": "品评冠军", "icon": "🏆", "source": "contest",
         "desc": "每周品评会冠军"},
    ],
}

# 成长奖励表（补白 2：点亮 N 格 → 经验/新配方）
_REWARD_TABLE: list = [
    {"lit": 2, "exp": 15, "recipes": ["rcp_bonus_2"]},
    {"lit": 4, "exp": 30, "recipes": ["rcp_bonus_4"]},
]

# 教学文案表（补白 3：内容包可配）
_TUTORIALS: list = [
    {"name": "连锁奖励", "example": "连续投入同属性材料 ≥3 段触发连锁奖励",
     "text": "链式投料达到 3 段及以上触发连锁奖励，段数映射效果等级上限。"},
    {"name": "核心镶嵌", "example": "/镶核心 核心物品 → 品质上限+X",
     "text": "深度炼金：消耗核心物品嵌入，提升品质上限并适配属性。"},
]

# 6 深度机制预览（补白 4：settings.alchemy.deep_mechanisms 可配）
_DEEP_MECHANISMS: list = [
    {"name": "连锁奖励", "preview": "连续投入同属性材料 ≥3 段触发连锁奖励"},
    {"name": "核心镶嵌", "preview": "/镶核心 核心物品 → 品质上限+X"},
    {"name": "分解回炉", "preview": "/分解 回收 40-60% 材料 + 产出宝石"},
    {"name": "量贩复制", "preview": "/登记 后 /复制 批量量产标准版"},
    {"name": "图鉴成长", "preview": "新条目点亮 → 点亮 N 格 → 经验/新配方"},
    {"name": "战斗即时调合", "preview": "战斗中 /即时调合 一步出结果"},
]


class _FakeRegistry:
    """内容注册表替身（all_ids 按 kind 返回 id 元组）。"""

    def __init__(self, tables: Mapping[str, tuple]) -> None:
        self._tables = tables

    def all_ids(self, kind: str) -> tuple:
        return self._tables.get(kind, ())

    def resolve_name(self, rid: str):
        for kind_ids in self._tables.values():
            if rid in kind_ids:
                return rid.upper()
        return None


def _registry() -> _FakeRegistry:
    # 炼金图鉴分母：recipe 4 + item 2 = 6（补白 1）
    return _FakeRegistry({
        "recipe": ("rcp_a", "rcp_b", "rcp_c", "rcp_d"),
        "item": ("alch_out_1", "alch_out_2"),
    })


def _ctx(**overrides: Any) -> MutableMapping[str, Any]:
    ctx: MutableMapping[str, Any] = {
        "registry": _registry(),
        "codex_state": {"alchemy": {}},
        "event_counts": {},
        "settings": {},
    }
    ctx.update(overrides)
    return ctx


def _player(*, level: int = 5, sp_earned: int = 3, sp_used: int = 0,
            unlocks: Optional[Mapping[str, int]] = None,
            owned: Optional[Sequence[str]] = None) -> MutableMapping[str, Any]:
    return {
        "id": "P1",
        "proficiency": {
            "alchemy": {
                "level": level, "exp": 0, "sp_earned": sp_earned, "sp_used": sp_used,
                "unlocks": dict(unlocks or {}),
            },
        },
        "title_state": {"owned": list(owned or []), "equipped": None},
    }


def _prof_engine(**overrides: Any) -> ProficiencyEngine:
    entry = copy.deepcopy(_ALCHEMY_ENTRY)
    entry.update(overrides)
    return ProficiencyEngine([entry], {"alchemy": {"job_tier_map": _ALCHEMY_ENTRY["job_tier_map"]}})


def _meta(**meta_overrides: Any) -> AlchemyMeta:
    """默认引擎：真 ProficiencyEngine（3 SP 起始）+ 自定义奖励/教学/深度机制配置。"""
    prof = meta_overrides.pop("prof", None)
    if prof is None:
        prof = _prof_engine()
    settings = {
        "alchemy": {
            "codex_rewards": _REWARD_TABLE,
            "tutorials": _TUTORIALS,
            "deep_mechanisms": _DEEP_MECHANISMS,
        },
    }
    settings["alchemy"].update(meta_overrides.pop("alchemy_cfg", {}))
    return AlchemyMeta(prof=prof, settings=settings)


def _light(ctx: MutableMapping[str, Any], n: int) -> None:
    """点亮炼金图鉴前 n 条（按 recipe 表序；n 超出 4 配方则续 item）。"""
    cat = ctx["codex_state"]["alchemy"]
    recipes = _registry().all_ids("recipe")
    items = _registry().all_ids("item")
    ids = list(recipes) + list(items)
    for rid in ids[:n]:
        cat[rid] = {"name": rid, "seen": True, "killed": False, "lore_unlocked": False}


# ---------------------------------------------------------------------------
# /图鉴 进度（F-19/GU-58）
# ---------------------------------------------------------------------------
def test_codex_summary_empty_and_partial_and_full() -> None:
    """进度三态：0/6 → 4/6 → 6/6 all_lit。"""
    ctx = _ctx()
    m = _meta()
    s0 = m.codex_summary(ctx)
    assert s0["ok"] is True and s0["category"] == "alchemy"
    assert (s0["lit"], s0["total"], s0["ratio"], s0["all_lit"]) == (0, 6, 0.0, False)
    _light(ctx, 4)
    s1 = m.codex_summary(ctx)
    assert (s1["lit"], s1["total"], s1["all_lit"]) == (4, 6, False)
    assert abs(s1["ratio"] - 4 / 6) < 1e-9
    _light(ctx, 6)
    s2 = m.codex_summary(ctx)
    assert s2["all_lit"] is True


def test_codex_summary_unknown_category() -> None:
    """未知分册 → ok=False 不崩。"""
    m = _meta()
    assert m.codex_summary(_ctx(), "fossil")["ok"] is False


def test_codex_reward_reserved_key_not_counted() -> None:
    """保留键 _rewards 不计入点亮数（结算后 lit 不虚增）。"""
    ctx = _ctx()
    m = _meta()
    _light(ctx, 4)
    m.codex_reward(ctx)
    assert m.codex_summary(ctx)["lit"] == 4


# ---------------------------------------------------------------------------
# 图鉴成长奖励（L210）
# ---------------------------------------------------------------------------
def test_codex_reward_reached_and_idempotent() -> None:
    """点亮 3 格 → 领 lit=2 档（经验 15 + 配方）；重复调用不重发（D-07 幂等）。"""
    ctx = _ctx()
    m = _meta()
    _light(ctx, 3)
    r1 = m.codex_reward(ctx)
    assert r1["ok"] is True and r1["granted"] is True
    assert r1["newly_claimed"] == [2]
    assert r1["reward"] == {"exp": 15, "recipes": ["rcp_bonus_2"]}
    assert r1["lit"] == 3 and r1["total"] == 6
    r2 = m.codex_reward(ctx)
    assert r2["granted"] is False and r2["newly_claimed"] == []
    assert r2["reward"] == {"exp": 0, "recipes": []}


def test_codex_reward_multi_threshold() -> None:
    """点亮 5 格 → 连领 lit=2 与 lit=4 两档（exp 累加、配方并集）。"""
    ctx = _ctx()
    m = _meta()
    _light(ctx, 5)
    r = m.codex_reward(ctx)
    assert r["granted"] is True
    assert r["newly_claimed"] == [2, 4]
    assert r["reward"] == {"exp": 45, "recipes": ["rcp_bonus_2", "rcp_bonus_4"]}


def test_codex_reward_below_threshold() -> None:
    """点亮 1 格（阈值最低 2）→ 无新奖励。"""
    ctx = _ctx()
    m = _meta()
    _light(ctx, 1)
    r = m.codex_reward(ctx)
    assert r["granted"] is False and r["newly_claimed"] == []
    assert r["reward"] == {"exp": 0, "recipes": []}


def test_codex_reward_default_table() -> None:
    """无配置 → 内置缺省表（点亮 5 格 → 首档 exp 10）。"""
    ctx = _ctx()
    m = AlchemyMeta(prof=_prof_engine(), settings={})
    _light(ctx, 5)
    r = m.codex_reward(ctx)
    assert r["granted"] is True and r["newly_claimed"] == [5]
    assert r["reward"]["exp"] == 10


def test_codex_reward_unknown_category() -> None:
    """未知分册 → ok=False。"""
    m = _meta()
    assert m.codex_reward(_ctx(), "fossil")["ok"] is False


# ---------------------------------------------------------------------------
# 王称号条件（TTL-01/TC-11/TC-19/TC-20：图鉴全亮 vs 未亮，与等级解耦）
# ---------------------------------------------------------------------------
def test_king_eligible_all_lit_grants_title() -> None:
    """图鉴全亮 → 授予炼金王（title_id=alchemy，TTL-03），进入 title_state.owned。"""
    ctx = _ctx()
    m = _meta()
    _light(ctx, 6)
    player = _player(level=5)
    r = m.king_eligible(player, ctx, job_id="alchemy")
    assert r["ok"] is True and r["granted"] is True
    assert r["title_id"] == "alchemy" and r["codex_all_lit"] is True
    assert "alchemy" in player["title_state"]["owned"]


def test_king_eligible_not_lit_refused_even_at_king_tier() -> None:
    """TC-11/TC-20：等级 60（王区间）但图鉴未全亮 → 不授予（王条件与等级解耦）。"""
    ctx = _ctx()
    m = _meta()
    _light(ctx, 4)
    player = _player(level=60)  # 王区间
    r = m.king_eligible(player, ctx, job_id="alchemy")
    assert r["ok"] is False and r["reason"] == "codex_incomplete"
    assert r["codex_all_lit"] is False
    assert "alchemy" not in player["title_state"]["owned"]


def test_king_eligible_low_level_still_grants_when_lit() -> None:
    """TC-19 反例：低等级（见习）但图鉴全亮 → 仍授予（条件仅图鉴全亮，与等级无关）。"""
    ctx = _ctx()
    m = _meta()
    _light(ctx, 6)
    player = _player(level=1)
    r = m.king_eligible(player, ctx, job_id="alchemy")
    assert r["ok"] is True and r["granted"] is True


def test_king_eligible_idempotent() -> None:
    """已拥有 → 幂等 {ok: True, granted: False, title_id}，不重复入列表。"""
    ctx = _ctx()
    m = _meta()
    _light(ctx, 6)
    player = _player(level=5, owned=["alchemy"])
    r = m.king_eligible(player, ctx, job_id="alchemy")
    assert r["ok"] is True and r["granted"] is False and r["title_id"] == "alchemy"
    assert player["title_state"]["owned"] == ["alchemy"]


def test_king_eligible_no_prof_failsafe() -> None:
    """prof 未注入 → engine_unavailable（fail-safe，不越权授予）。"""
    ctx = _ctx()
    m = AlchemyMeta(prof=None, settings={})
    _light(ctx, 6)
    r = m.king_eligible(_player(), ctx, job_id="alchemy")
    assert r["ok"] is False and r["reason"] == "engine_unavailable"
    assert r["codex_all_lit"] is True


# ---------------------------------------------------------------------------
# /技能面板 查看（F-19/TC-12/M-19）
# ---------------------------------------------------------------------------
def test_skill_panel_view_shows_sp_and_branches() -> None:
    """SP 可用 3、8 分支、未解锁 unlocked_count=0（TC-12/TC-13 未购买不生效）。"""
    player = _player(sp_earned=3)
    m = _meta()
    v = m.skill_panel_view(player)
    assert v["ok"] is True and v["job_id"] == "alchemy"
    assert v["sp_available"] == 3
    assert len(v["items"]) == 8
    assert all(i["unlocked_count"] == 0 for i in v["items"])
    assert v["total_unlocked"] == 0
    ids = {i["id"] for i in v["items"]}
    assert {"quality_cap_10", "input_count_1", "trait_slot_1", "unlock_copy",
            "unlock_evolve", "unlock_challenge", "gather_amount_1",
            "chain_limit_1"} <= ids


def test_skill_panel_view_reflects_purchased() -> None:
    """已解锁 2 次 → unlocked_count=2、total_unlocked=2（M-19「已 2 次」口径）。"""
    player = _player(sp_earned=3, sp_used=2, unlocks={"quality_cap_10": 2})
    m = _meta()
    v = m.skill_panel_view(player)
    qc = next(i for i in v["items"] if i["id"] == "quality_cap_10")
    assert qc["unlocked_count"] == 2 and v["total_unlocked"] == 2
    assert v["sp_available"] == 1


def test_skill_panel_view_no_prof_failsafe() -> None:
    """prof 未注入 → engine_unavailable。"""
    m = AlchemyMeta(prof=None, settings={})
    v = m.skill_panel_view(_player())
    assert v["ok"] is False and v["reason"] == "engine_unavailable"


# ---------------------------------------------------------------------------
# /技能面板 解锁（SP-02/04/05，TC-13/14/16）
# ---------------------------------------------------------------------------
def test_skill_panel_unlock_success_double_count() -> None:
    """TC-14 双计：解锁后 sp_used 0→1、sp_earned 不变、unlocks 计数 +1、剩余 SP 2。"""
    player = _player(sp_earned=3)
    m = _meta()
    r = m.skill_panel_unlock(player, "alchemy", "quality_cap_10")
    assert r["ok"] is True
    assert r["sp_remaining"] == 2 and r["sp_used_delta"] == 1
    assert r["unlock_count"] == 1 and r["panel_id"] == "quality_cap_10"
    node = player["proficiency"]["alchemy"]
    assert node["sp_earned"] == 3 and node["sp_used"] == 1  # 双计，sp_earned 不变
    assert node["unlocks"]["quality_cap_10"] == 1
    assert "已解锁「品质上限+10」×1（剩余 SP 2）" in r["message"]


def test_skill_panel_unlock_sp_insufficient() -> None:
    """TC-16：SP=0 → 拒绝 sp_insufficient，不扣点。"""
    player = _player(sp_earned=0)
    m = _meta()
    r = m.skill_panel_unlock(player, "alchemy", "quality_cap_10")
    assert r["ok"] is False and r["reason"] == "sp_insufficient"
    assert player["proficiency"]["alchemy"]["sp_used"] == 0


def test_skill_panel_unlock_not_repeatable() -> None:
    """repeatable=false 已购 → 拒绝 not_repeatable（SP-05）。"""
    player = _player(sp_earned=3, sp_used=1, unlocks={"unlock_copy": 1})
    m = _meta()
    r = m.skill_panel_unlock(player, "alchemy", "unlock_copy")
    assert r["ok"] is False and r["reason"] == "not_repeatable"


def test_skill_panel_unlock_unknown_panel() -> None:
    """未知面板项 → panel_not_found。"""
    m = _meta()
    r = m.skill_panel_unlock(_player(sp_earned=3), "alchemy", "no_such_panel")
    assert r["ok"] is False and r["reason"] == "panel_not_found"


def test_skill_panel_unlock_no_prof_failsafe() -> None:
    """prof 未注入 → engine_unavailable。"""
    m = AlchemyMeta(prof=None, settings={})
    r = m.skill_panel_unlock(_player(), "alchemy", "quality_cap_10")
    assert r["ok"] is False and r["reason"] == "engine_unavailable"


def test_skill_panel_unlock_repeatable_up_to_max() -> None:
    """repeatable=true 多次解锁：第 1 次成功、SP 递减（TC-13 品质上限购买才生效）。"""
    player = _player(sp_earned=3)
    m = _meta()
    r1 = m.skill_panel_unlock(player, "alchemy", "quality_cap_10")
    r2 = m.skill_panel_unlock(player, "alchemy", "quality_cap_10")
    assert r1["ok"] is True and r2["ok"] is True
    assert r2["unlock_count"] == 2 and r2["sp_remaining"] == 1
    v = m.skill_panel_view(player)
    qc = next(i for i in v["items"] if i["id"] == "quality_cap_10")
    assert qc["unlocked_count"] == 2  # TC-13：购买后计数生效（未购买=0 不生效）


# ---------------------------------------------------------------------------
# /教学 目录 + 机制教学（F-23/GU-64/M-23）
# ---------------------------------------------------------------------------
def test_tutorial_catalog_lists_mechanisms() -> None:
    """教学目录：返回 {name, example} 列表（配置注入）。"""
    m = _meta()
    cat = m.tutorial_catalog()
    names = [c["name"] for c in cat]
    assert names == ["连锁奖励", "核心镶嵌"]  # 配置顺序
    assert all(c["example"] for c in cat)


def test_tutorial_show_known_mechanism() -> None:
    """已知机制名 → 回看完整教学（name/example/text）。"""
    m = _meta()
    r = m.tutorial_show("连锁奖励")
    assert r["ok"] is True and r["name"] == "连锁奖励"
    assert "≥3 段" in r["example"] and r["text"]


def test_tutorial_show_unknown_returns_catalog() -> None:
    """M-23：未知名 → ok=False + catalog（回目录）。"""
    m = _meta()
    r = m.tutorial_show("不存在机制")
    assert r["ok"] is False and r["reason"] == "unknown_mechanism"
    assert isinstance(r["catalog"], list) and len(r["catalog"]) == 2


def test_tutorial_show_empty_name_returns_catalog() -> None:
    """空名（/教学 无参）→ 回目录。"""
    m = _meta()
    r = m.tutorial_show("")
    assert r["ok"] is False and r["reason"] == "empty_name"
    assert isinstance(r["catalog"], list)


def test_tutorial_default_catalog_builtin() -> None:
    """无配置 → 内置教学表（含 6 深度机制）。"""
    m = AlchemyMeta(prof=None, settings={})
    names = {c["name"] for c in m.tutorial_catalog()}
    assert {"连锁奖励", "核心镶嵌", "分解回炉", "量贩复制", "图鉴成长",
            "战斗即时调合"} <= names


# ---------------------------------------------------------------------------
# 升大师公告（L482/F-23：6 深度机制一句话预览，tier ≥ 大师）
# ---------------------------------------------------------------------------
def test_master_announcement_at_master() -> None:
    """tier_index=4（大师）→ 解锁，6 深度机制一句话预览。"""
    m = _meta()
    r = m.master_announcement(4)
    assert r["ok"] is True and r["unlocked"] is True
    assert r["tier_index"] == 4 and r["tier_name"] == "大师"
    names = [x["name"] for x in r["mechanisms"]]
    assert names == ["连锁奖励", "核心镶嵌", "分解回炉", "量贩复制",
                     "图鉴成长", "战斗即时调合"]
    assert all(x["preview"] for x in r["mechanisms"])


def test_master_announcement_below_master() -> None:
    """tier_index=3（专家）→ not_master 拒绝，无预览。"""
    m = _meta()
    r = m.master_announcement(3)
    assert r["ok"] is False and r["reason"] == "not_master"
    assert r["unlocked"] is False and r["mechanisms"] == []
    assert r["master_tier_index"] == 4


def test_master_announcement_higher_tier_still_unlocked() -> None:
    """tier_index=6（王）→ 仍解锁（tier ≥ 大师即触发）。"""
    m = _meta()
    r = m.master_announcement(6)
    assert r["ok"] is True and r["unlocked"] is True
    assert r["tier_name"] == "王"


def test_master_announcement_default_builtin_previews() -> None:
    """无配置 → 内置缺省 6 机制预览（从内置教学表取 example）。"""
    m = AlchemyMeta(prof=None, settings={})
    r = m.master_announcement(4)
    assert r["ok"] is True and len(r["mechanisms"]) == 6
    assert all(x["preview"] for x in r["mechanisms"])
