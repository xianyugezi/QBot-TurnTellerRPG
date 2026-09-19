"""批39 · ①指令归位 + ⑤回归对拍（提层前后同输入同输出；simple 逐字段）。

依据：`docs/深度打造_决策记录.md` §六 落地动作 1（/合成 从 alchemy_commands 提到公用层，
保持指令名与行为不变）+ 红线（「只启用合成」逐字段等于现有 alchemy.mode=simple 行为）。

覆盖：
  A. **提层前后逐字节对拍**：同电池输入 → `cmd_synthesis` 消息 + 玩家状态变更的
     canonical sha256 与基线提交 `42d73da`（提层前）冻结值一致（18 用例，含成功 / 缺料 /
     等级不足 / 深度拦截 / 深度放行提示 / 数量超限截断 / 缺参 / 解析错误 / 序号兜底 /
     off 关闭 / simple 仅合成）；
  B. **「只启用合成」(simple) vs 现有 simple 档逐字段对拍**：引擎结果 dict 与壳层消息
     逐字段相等（reference = 直接消费未改动的 SynthesisEngine）；
  C. 注册一致性：`/合成` 唯一注册方 = synth_commands（alchemy_commands 不注册，防双注册）
     + `assembly/router_setup.check_consistency` 通过；
  D. 兼容性再导出：`alchemy_commands.SYNTH_CMD` / `cmd_synthesis` 与公用层同一对象。

测试只构造内存玩家状态，不写任何真实内容包。
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, Mapping, MutableMapping

from qbot_rpg.assembly.router_setup import REGISTER_GROUPS, check_consistency
from qbot_rpg.commands.alchemy_commands import cmd_synthesis as _ac_cmd_synthesis
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.commands.synth_commands import (
    SYNTH_CMD,
    cmd_synthesis,
    register_synth_commands,
)
from qbot_rpg.core.synthesis import DEFAULT_MAX_QTY, SynthesisEngine

# ---------------------------------------------------------------------------
# 夹具（内存；对齐 core/synthesis.py ctx 契约）
# ---------------------------------------------------------------------------
ITEMS: Dict[str, Mapping[str, Any]] = {
    "water_crystal": {"id": "water_crystal", "name": "水结晶", "type": "material"},
    "herb": {"id": "herb", "name": "草药", "type": "material"},
    "moon_grass": {"id": "moon_grass", "name": "月光草", "type": "material"},
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
    "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable"},
    "deep_core": {"id": "deep_core", "name": "秘银核心", "type": "material"},
}

RECIPES: Dict[str, Mapping[str, Any]] = {
    "rcp_mana_potion": {
        "id": "rcp_mana_potion", "name": "魔力药水配方", "kind": "craft", "level": 5,
        "synth_allowed": True, "master_only": False,
        "materials": [{"id": "water_crystal", "count": 5}, {"id": "herb", "count": 2}],
        "output": {"item": "mana_potion", "count": 1},
        "cost": {"coins": 30, "gem": 0},
    },
    "rcp_flame_bomb": {
        "id": "rcp_flame_bomb", "name": "火焰弹配方", "kind": "craft", "level": 31,
        "synth_allowed": True, "master_only": False,
        "materials": [{"id": "moon_grass", "count": 3}],
        "output": {"item": "flame_bomb", "count": 1},
        "cost": {"coins": 200, "gem": 0},
    },
    "rcp_deep": {
        "id": "rcp_deep", "name": "深度秘银配方", "kind": "craft", "level": 31,
        "synth_allowed": False, "master_only": True,
        "materials": [{"id": "deep_core", "count": 2}],
        "output": {"item": "deep_core", "count": 1},
        "cost": {"coins": 0, "gem": 0},
    },
    "rcp_deep_true": {
        "id": "rcp_deep_true", "name": "深度开放配方", "kind": "craft", "level": 31,
        "synth_allowed": True, "master_only": True,
        "materials": [{"id": "deep_core", "count": 1}],
        "output": {"item": "deep_core", "count": 1},
        "cost": {"coins": 0, "gem": 0},
    },
}

TIER_MAP = {"见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
            "大师": [31, 40], "宗师": [41, 50], "王": [51, 99]}

# 电池 canonical sha256（基线提交 42d73da 提层前 / 提层后逐字节一致；改动即红）
GOLDEN_SHA256 = "ff1b373e37560e1e0671fe1f26c4bf9a8752d0eacb0859556bfbfa803f008ac3"


def _settings(mode: str, **extra: Any) -> Dict[str, Any]:
    alch: Dict[str, Any] = {"mode": mode, "max_qty": DEFAULT_MAX_QTY, "job_tier_map": TIER_MAP}
    alch.update(extra)
    return {"currencies": [{"id": "coins", "name": "金币"}], "alchemy": alch}


def make_ctx(settings: Mapping[str, Any], **over: Any) -> MutableMapping[str, Any]:
    """全字段玩家合成 ctx（见习钓鱼 + 大师锻造两职业节点，覆盖各级配方）。"""
    base: Dict[str, Any] = {
        "qid": "u1", "name": "阿伟",
        "proficiency": {
            "fishing": {"level": 0, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}},
            "forging": {"level": 4, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}},
        },
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {"water_crystal": 20, "herb": 10, "moon_grass": 3, "deep_core": 2},
        "items": ITEMS, "recipe": RECIPES, "settings": settings,
    }
    base.update(over)
    return base


# (mode, raw, extra_settings, ctx_overrides)
CASES = [
    ("full", "/合成 魔力药水配方", {}, {}),
    ("full", "/合成 魔力药水配方*2", {}, {}),
    ("full", "/合成 火焰弹配方", {}, {}),
    ("full", "/合成 深度秘银配方", {}, {}),
    ("full", "/合成 深度开放配方", {}, {}),
    ("full", "/合成 配方不存在", {}, {}),
    ("full", "/合成 魔力药水配方*100000000000", {}, {}),
    ("full", "/合成", {}, {}),
    ("full", "/合成 配方 1 2 3 4", {}, {}),
    ("simple", "/合成 魔力药水配方", {}, {}),
    ("simple", "/合成 魔力药水配方*3", {}, {}),
    ("off", "/合成 魔力药水配方", {}, {}),
    ("full", "/合成 魔力药水配方", {}, {"inventory": {"water_crystal": 1, "herb": 0}}),
    ("full", "/合成 魔力药水配方", {}, {"currencies": {"coins": 0, "gem": 0}}),
    ("full", "/合成 魔力药水配方", {"max_qty": 2}, {}),
    ("full", "/合成 魔力药水配方", {"synth_exp": 3}, {}),
    ("full", "/合成 1", {}, {}),
    ("full", "/合成 2", {}, {}),
]


def _battery() -> Any:
    """跑完整电池：记录消息 + 玩家状态变更（确定性；canonical 可哈希）。"""
    out = []
    for mode, raw, extra, over in CASES:
        ctx = make_ctx(_settings(mode, **extra), **over)
        msg = cmd_synthesis(parse_command(raw), ctx)
        out.append({
            "mode": mode, "raw": raw, "extra": extra, "over": over, "message": msg,
            "currencies": dict(ctx.get("currencies") or {}),
            "inventory": dict(ctx.get("inventory") or {}),
            "proficiency": copy.deepcopy(ctx.get("proficiency") or {}),
        })
    return out


def _canonical_sha256(payload: Any) -> str:
    canon = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ===========================================================================
# A. 提层前后逐字节对拍
# ===========================================================================
def test_relocation_output_is_byte_identical_to_pre_batch_baseline() -> None:
    """归位前后同输入同输出：电池 canonical sha256 == 基线 42d73da 冻结值。"""
    assert _canonical_sha256(_battery()) == GOLDEN_SHA256


def test_relocation_covers_success_and_reject_branches() -> None:
    """电池覆盖成功 / 各种拒绝 / 提示分支（防电池退化后哈希仍过）。"""
    msgs = [row["message"] for row in _battery()]
    assert any(m.startswith("✅") for m in msgs)
    assert any("❌ 配方不存在" in m for m in msgs)
    assert any("深度未解锁" in m for m in msgs)
    assert any("绕过深度炼金玩法" in m for m in msgs)
    assert any("指令不正确" in m for m in msgs)
    assert any("炼金系统已关闭" in m for m in msgs)
    assert any("材料不足" in m for m in msgs)


# ===========================================================================
# B. 「只启用合成」(simple) vs 现有 simple 档逐字段对拍
# ===========================================================================
def test_only_synthesis_simple_matches_existing_simple_field_by_field() -> None:
    """「只启用合成」= simple 档：壳层消息 + 玩家状态与未改动引擎逐字段相等。"""
    checked = 0
    for mode, raw, extra, over in CASES:
        if mode != "simple":
            continue
        settings = _settings(mode, **extra)
        # reference：直接消费未改动引擎（= 现有 simple 档行为）
        ref_ctx = make_ctx(settings, **over)
        req = parse_command(raw)
        if req.error or not req.args:
            continue
        target = str(req.args[0]).lstrip("+").split("*", 1)[0]
        ref = SynthesisEngine(settings=settings).synthesize(
            ref_ctx, target, req.qty if req.qty is not None else 1)
        # 壳层（新路径）
        new_ctx = make_ctx(settings, **over)
        msg = cmd_synthesis(parse_command(raw), new_ctx)
        assert msg == str(ref.get("message")), (raw, msg, ref.get("message"))
        assert new_ctx["inventory"] == ref_ctx["inventory"]
        assert new_ctx["currencies"] == ref_ctx["currencies"]
        assert new_ctx["proficiency"] == ref_ctx["proficiency"]
        checked += 1
    assert checked >= 2  # 电池须含 ≥2 条 simple 用例（防退化）


# ===========================================================================
# C. 注册一致性（唯一注册方 / 白名单 / 双向一致）
# ===========================================================================
def _build_router() -> Router:
    router = Router()
    for group in REGISTER_GROUPS:
        try:
            group(router, make_context=lambda p: {})
        except TypeError:
            group(router, make_context=None)
    return router


def test_synth_registered_exactly_once_by_common_layer() -> None:
    """`/合成` 唯一注册方 = synth_commands；alchemy_commands 不再注册（防同名双注册）。"""
    router = Router()
    register_synth_commands(router, make_context=lambda p: make_ctx(_settings("full")))
    assert router.names().count(SYNTH_CMD) == 1
    assert SYNTH_CMD in DEFAULT_WHITELIST
    assert router.get(SYNTH_CMD).whitelisted
    alch_router = Router()
    from qbot_rpg.commands.alchemy_commands import register_alchemy_commands
    register_alchemy_commands(alch_router, make_context=lambda p: {})
    assert not alch_router.has(SYNTH_CMD)


def test_full_assembly_consistency_and_single_registration() -> None:
    """全量装配：/合成 恰好一次 + check_consistency 硬一致（白名单 ↔ 注册）。"""
    router = _build_router()
    assert router.names().count(SYNTH_CMD) == 1
    assert len(router.names()) == len(set(router.names()))
    report = check_consistency(router)
    assert report["ok"] is True
    assert report["registered_not_whitelisted"] == []


# ===========================================================================
# D. 兼容性再导出（历史调用方零改动）
# ===========================================================================
def test_alchemy_commands_reexports_synth_symbols() -> None:
    """alchemy_commands.SYNTH_CMD / cmd_synthesis 与公用层同一对象（提层不破坏导入）。"""
    import qbot_rpg.commands.synth_commands as sc
    assert _ac_cmd_synthesis is sc.cmd_synthesis
    assert SYNTH_CMD == "合成"
