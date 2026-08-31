"""M10 钓鱼·批5·路5A（主 agent 收口补齐）：钓鱼职业熟练度 + 钓鱼王授予。

文件名：qbot_rpg/core/fishing_job.py
创建时间：2026-09-01
作者：Hermes 主 agent（路5A 子 agent 撞迭代上限零落盘，按侦察结论补齐）

功能描述（T16 · 细化_2c1c §四 R-13/R-14 + 定稿 §1 M9）：
  - grant_fishing_exp(ctx, amount, source="gather")：钓鱼职业经验入账（包装
    ProficiencyEngine.gain_prof_exp，exp_sources.gather 倍率 1.0）→
    {ok, exp_gained, level, tier_to, sp_gained}。
  - fish_king_eligible(ctx) -> {eligible, complete, missing_species,
    king_victory_count, has_title, reason}：钓鱼王资格判定——图鉴全亮
    （fishing.json species[] 每条 codex caught_count≥1）∧ king_victory_count ≥ 2
    （R-07 补全判定 + R-14 钓鱼王语义）。
  - grant_fishing_king(ctx)：委托 ProficiencyEngine.grant_king_title(player,
    "fishing", codex_all_lit=all_lit) 即时落账（对齐 forge_king.grant_forge_king）；
    幂等（已拥有不重复授予）。
  - king_bonus(settings) -> {key, percent, pct, enabled}：钓鱼王称号全属性+X%
    （settings.fishing.king_bonus_pct 缺省 5；对齐 forge_king.king_bonus 形态；
    装配层接线归批6/装配层，本路只提供纯函数+测试）。

依据：细化_2c1c §四（R-13/R-14）+ §二 2.4（R-07）+ §六 TC-14~18
      + docs/m10_shared_contract.md §二 IF-13/IF-14 + docs/m10_接口摸底.md §六
模式参考：
  - qbot_rpg/core/forge_king.py（king_eligible/grant_forge_king/king_bonus 完整先例）
  - qbot_rpg/core/fishing_codex.py fish_meta（king_victory_count 读）
  - qbot_rpg/core/fishing_settle.py _grant_prof_exp（经验入账模式）

【工程补白】：
  F-1  钓鱼王资格 = 图鉴全亮 ∧ king_victory_count≥2（比 forge 的仅全亮多讨伐条件——
       细化 R-07 补全判定 + R-14 语义）；等级不参与（与 KF-01 同构）。
  F-2  授予幂等：grant_king_title 内部已处理已拥有（granted=False），本模块透传。
  F-3  king_bonus 装配层接线归批6（对齐 forge_king 现状：纯函数+测试，不接
       ctx["attr_final"]）。

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器/零睡眠；docstring 勿写字面
      定时器调用字样（M43 探针）；零 emoji；不 git commit。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from qbot_rpg.core.fishing_codex import KING_VICTORY_COUNT_KEY, fish_meta
from qbot_rpg.core.proficiency import ProficiencyEngine

__all__ = [
    "FISHING_JOB_ID",
    "KING_TITLE_ID",
    "DEFAULT_KING_BONUS_PCT",
    "KING_MIN_VICTORIES",
    "fish_king_eligible",
    "grant_fishing_exp",
    "grant_fishing_king",
    "king_bonus",
]

FISHING_JOB_ID: str = "fishing"
KING_TITLE_ID: str = FISHING_JOB_ID
DEFAULT_KING_BONUS_PCT: float = 5.0
KING_MIN_VICTORIES: int = 2


def _codex_fish_state(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """codex_state["fish"] 分册可变引用（缺省空 dict 挂回）。"""
    st = ctx.get("codex_state")
    if not isinstance(st, MutableMapping):
        st = {}
        ctx["codex_state"] = st
    fish = st.get("fish")
    if not isinstance(fish, MutableMapping):
        fish = {}
        st["fish"] = fish
    return fish


def _fish_species_ids(ctx: Mapping[str, Any]) -> tuple:
    """fishing.json species[] 全部鱼种 id（ctx["fishing"]["species"] 或 fish_table）。"""
    fishing = ctx.get("fishing")
    if isinstance(fishing, Mapping):
        rows = fishing.get("species")
        if isinstance(rows, list):
            return tuple(
                str(r["id"]) for r in rows
                if isinstance(r, Mapping) and isinstance(r.get("id"), str)
            )
    ft = ctx.get("fish_table")
    if isinstance(ft, Mapping):
        raw = ft.get("__species__")
        if isinstance(raw, list):
            return tuple(
                str(r["id"]) for r in raw
                if isinstance(r, Mapping) and isinstance(r.get("id"), str)
            )
    return ()


def _has_title(player: Mapping[str, Any]) -> bool:
    """player 是否已拥有「钓鱼王」称号（title_state.owned 含 KING_TITLE_ID）。"""
    ts = player.get("title_state")
    if not isinstance(ts, Mapping):
        return False
    owned = ts.get("owned")
    if not isinstance(owned, (list, tuple, set)):
        return False
    return KING_TITLE_ID in {str(x) for x in owned}


# ---------------------------------------------------------------------------
# 经验入账（R-13）
# ---------------------------------------------------------------------------
def grant_fishing_exp(
    ctx: MutableMapping[str, Any],
    amount: object,
    *,
    source: str = "gather",
) -> dict:
    """钓鱼职业经验入账（R-13：exp_sources.gather 倍率默认 1.0，与出鱼结算联动）。

    入参 ctx：player（player.persistent_state.proficiency 或 ctx["proficiency"]）；
    amount：经验量（int/float，非正/非法 → 0 不报错）；source：经验来源（缺省
    "gather"，对齐 settle 出鱼结算 source=gather）。
    出参 {ok, exp_gained, level, tier_to, sp_gained}；经验入 player["proficiency"]
    ["fishing"]（就地改，_ps_init 挂 ps 形态即落档）。
    """
    amt = int(amount) if isinstance(amount, (int, float)) and not isinstance(amount, bool) else 0
    if amt <= 0:
        return {"ok": True, "exp_gained": 0, "level": 0, "tier_to": 0, "sp_gained": 0}

    player = ctx.get("player")
    if not isinstance(player, Mapping):
        # 直传 proficiency 形态（对齐 settle _grant_prof_exp 兜底）
        prof = ctx.get("proficiency")
        if not isinstance(prof, MutableMapping):
            return {"ok": False, "reason": "no_player", "exp_gained": 0}
        node = prof.setdefault(FISHING_JOB_ID, {"exp": 0, "level": 0, "sp_earned": 0})
        node["exp"] = int(node.get("exp", 0) or 0) + amt
        return {"ok": True, "exp_gained": amt, "level": int(node.get("level", 0)),
                "tier_to": int(node.get("level", 0)), "sp_gained": 0}

    eng = ProficiencyEngine()
    res = eng.gain_prof_exp(player, FISHING_JOB_ID, amt, source=source)
    return {
        "ok": bool(res.get("ok", True)),
        "exp_gained": int(res.get("exp_gained", amt)),
        "level": int(res.get("level", 0)),
        # tier_to 为档位名（中文，如「见习」）——非数字，直接透传
        "tier_to": res.get("tier_to", ""),
        "sp_gained": int(res.get("sp_gained", 0)),
    }


# ---------------------------------------------------------------------------
# 钓鱼王资格判定（R-07 + R-14）
# ---------------------------------------------------------------------------
def fish_king_eligible(ctx: MutableMapping[str, Any]) -> dict:
    """钓鱼王资格判定（R-07 补全 + R-14 讨伐门槛，与等级解耦）。

    判定链（三者同时）：① fishing.json species[] 每条 codex 条目 caught_count≥1
    （图鉴全亮）② codex 鱼综述 king_victory_count ≥ 2（讨伐门槛）③ 无其它未点亮鱼种。
    出参 {eligible, complete, missing_species, king_victory_count, has_title,
    reason}——eligible：图鉴全亮 ∧ 讨伐≥2；reason 未达时给
    "codex_incomplete" / "king_victories_insufficient"。
    """
    fish = _codex_fish_state(ctx)
    species_ids = _fish_species_ids(ctx)
    missing = [
        sid for sid in species_ids
        if not (
            isinstance(fish.get(sid), Mapping)
            and int(fish[sid].get("caught_count", 0) or 0) >= 1
        )
    ]
    meta = fish_meta(ctx)
    victories = int(meta.get(KING_VICTORY_COUNT_KEY, 0) or 0)
    complete = not missing
    eligible = complete and victories >= KING_MIN_VICTORIES
    p = ctx.get("player")
    player_m = p if isinstance(p, Mapping) else {}
    return {
        "eligible": eligible,
        "complete": complete,
        "missing_species": missing,
        "king_victory_count": victories,
        "has_title": _has_title(player_m),
        "reason": None if eligible else (
            "codex_incomplete" if not complete else "king_victories_insufficient"
        ),
    }


# ---------------------------------------------------------------------------
# 授予（R-14：委托 ProficiencyEngine 即时落账；幂等）
# ---------------------------------------------------------------------------
def grant_fishing_king(ctx: MutableMapping[str, Any]) -> dict:
    """钓鱼王称号即时结算（R-14，对齐 forge_king.grant_forge_king）。

    流程：fish_king_eligible → 全亮∧讨伐≥2 → 委托 ProficiencyEngine.grant_king_title(
    player, "fishing", codex_all_lit=all_lit) 即时落账。
    出参 {ok, granted, title_id, reason, all_lit, lit_count, total,
    king_victory_count}——已拥有 → 幂等 granted=False。
    """
    player = ctx.get("player")
    if not isinstance(player, Mapping):
        return {"ok": False, "granted": False, "reason": "no_player"}
    st = fish_king_eligible(ctx)
    eng = ProficiencyEngine()
    res = eng.grant_king_title(player, KING_TITLE_ID, codex_all_lit=bool(st["complete"]))
    return {
        "ok": bool(res.get("ok")),
        "granted": bool(res.get("granted")),
        "title_id": res.get("title_id"),
        "reason": res.get("reason"),
        "all_lit": bool(st["complete"]),
        "lit_count": len(_fish_species_ids(ctx)) - len(st["missing_species"]),
        "total": len(_fish_species_ids(ctx)),
        "king_victory_count": int(st["king_victory_count"]),
    }


# ---------------------------------------------------------------------------
# 称号加成（R-14：全属性+X%，装配层接线归批6）
# ---------------------------------------------------------------------------
def king_bonus(settings: object) -> dict:
    """钓鱼王称号全属性+X% 加成配置（对齐 forge_king.king_bonus 形态）。

    settings.fishing.king_bonus_pct 缺省 5.0；非法/非正 → 缺省。
    出参 {key, percent, pct, enabled}——装配层接线时消费（本路只提供纯函数+测试）。
    """
    pct = DEFAULT_KING_BONUS_PCT
    if isinstance(settings, Mapping):
        seg = settings.get("fishing")
        if isinstance(seg, Mapping):
            raw = seg.get("king_bonus_pct")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and float(raw) >= 0:
                pct = float(raw)
    return {"key": "fishing_king_bonus", "percent": pct, "pct": pct / 100.0, "enabled": pct > 0}
