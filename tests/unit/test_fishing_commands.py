"""M10 批2·路2A：/钓鱼 钓点列举指令壳单测（tests/unit/test_fishing_commands.py）。

文件名：tests/unit/test_fishing_commands.py
创建时间：2026-08-31
作者：Hermes 子agent-2A（M10 钓鱼实现组批2·路2A：/钓鱼 钓点列举指令壳）

功能：qbot_rpg.commands.fishing_commands 指令壳纯函数直测（零 NoneBot、确定性、
      零定时器/零睡眠——壳层零等待判定，无任何实时计时）：
  - 无参列举：有钓点列出（TC-01：名称/时段偏好/稀有度标记 + 鱼讯参考说明三组
    关键词逐字）/ 无钓点空态（TC-02）/ off 拒绝（TC-09）
  - 候选规则：当前季节/时段过滤（2c1a §1.4 白名单；空=不限）+ spots 双形态引用
    （采集点 id 与 "map:spot" 组合 id）
  - 稀有度标记 = 候选鱼种最高 rarity（gold > rare > normal）
  - 时段偏好 = 候选鱼种 periods 并集中文（空=全天）
  - 季节/时段中文形态归一（秋/黄昏 → autumn/dusk）
  - 有参下钩转发：core.fishing_cast 未落盘 → 工程补白兜底（ImportError 探活）
  - 装配：register_fishing_commands 注册 /钓鱼（白名单标记 + make_context 注入/
    缺失抛 RuntimeError）

依据：
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §一（1.1 列钓点/1.2 下钩）+ §2.3
    （GU-01 off 拒绝）+ §六 验收 TC-01/02/09
  - docs/m10_shared_contract.md §二（FishDef 访问器 + spots 引用形态）/ §五 铁律
  - 模式参考：tests/unit/test_forge_commands.py（parse_command + Router 注册测试
    风格）/ tests/unit/test_fishing.py（_ctx/_species 夹具风格）

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠措辞（M43 探针避开字面
      time.sleep）；无 emoji（仅 ✅/❌ + 排版符号）。
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from qbot_rpg.commands.fishing_commands import (
    FISH_CAST_FALLBACK,
    FISH_CMD,
    FISH_INTENT_REF,
    cmd_fishing,
    first_fishable_spot,
    list_fishable_spots,
    normalize_period,
    normalize_season,
    register_fishing_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import Router

# =====================================================================================
# 夹具
# =====================================================================================

# 地图（list 形态，对齐装配 ctx["maps"]）：gloom_forest 双钓点 / abandoned_mine 单钓点 /
# calm_lake 具名钓点（combo 引用靶）/ empty_map 无 gather_points
_MAPS: List[Dict[str, Any]] = [
    {
        "id": "gloom_forest", "name": "幽光林地",
        "gather_points": [
            {"id": "gp_moon_grass", "item": "moon_grass", "rate": 0.4, "rarity": "normal"},
            {"id": "gp_reed_bank", "item": "reed", "rate": 0.3, "rarity": "normal"},
        ],
    },
    {
        "id": "abandoned_mine", "name": "废弃矿坑",
        "gather_points": [
            {"id": "gp_star_iron", "item": "star_iron", "rate": 0.35, "rarity": "rare"},
        ],
    },
    {
        "id": "calm_lake", "name": "静谧湖泊",
        "gather_points": [
            {
                "id": "deep_hole", "name": "深潭",
                "item": "water_lily", "rate": 0.5, "rarity": "normal",
            },
        ],
    },
    {"id": "empty_map", "name": "空荡平原"},
]

# 鱼种池（fish_table 形态：id → raw dict）
_FISH_TABLE: Dict[str, Dict[str, Any]] = {
    "silver_carp": {
        "id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
        "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
        "seasons": ["spring", "summer", "autumn"], "periods": ["dawn", "noon", "dusk"],
        "spots": ["gp_moon_grass"], "preferred_bait": [],
    },
    "golden_koi": {
        "id": "golden_koi", "name": "金鳞鲤", "rarity": "gold",
        "size_min": 20.0, "size_max": 90.0, "weight_min": 1.0, "weight_max": 12.0,
        "seasons": [], "periods": [],
        "spots": ["gp_moon_grass"], "preferred_bait": [],
    },
    "rare_loach": {
        "id": "rare_loach", "name": "赤纹泥鳅", "rarity": "rare",
        "size_min": 5.0, "size_max": 30.0, "weight_min": 0.1, "weight_max": 1.0,
        "seasons": ["summer"], "periods": ["night"],
        "spots": ["gp_star_iron"], "preferred_bait": [],
    },
    "autumn_carp": {
        "id": "autumn_carp", "name": "秋鲤", "rarity": "normal",
        "size_min": 8.0, "size_max": 40.0, "weight_min": 0.2, "weight_max": 2.0,
        "seasons": ["autumn"], "periods": [],
        "spots": ["gp_star_iron"], "preferred_bait": [],
    },
    # "map:spot" 组合引用形态（共享契约 §二 备注）：spot 段 ":" 后段匹配采集点 id
    "combo_fish": {
        "id": "combo_fish", "name": "深潭银鱼", "rarity": "normal",
        "size_min": 3.0, "size_max": 25.0, "weight_min": 0.1, "weight_max": 0.8,
        "seasons": [], "periods": [],
        "spots": ["calm_lake:deep_hole"], "preferred_bait": [],
    },
    "reed_fish": {
        "id": "reed_fish", "name": "芦丛鲫", "rarity": "normal",
        "size_min": 5.0, "size_max": 20.0, "weight_min": 0.1, "weight_max": 0.5,
        "seasons": [], "periods": [],
        "spots": ["gp_reed_bank"], "preferred_bait": [],
    },
}


def _fish_table(species: Optional[Mapping[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """鱼种池拷贝（独立可变，防跨测试污染）。"""
    src: Mapping[str, Dict[str, Any]] = species if species is not None else _FISH_TABLE
    return {str(k): dict(v) for k, v in src.items()}


def _ctx(
    location: str = "gloom_forest",
    season: str = "spring",
    period: str = "dawn",
    mode: str = "full",
    maps: Optional[List[Dict[str, Any]]] = None,
    species: Optional[Mapping[str, Dict[str, Any]]] = None,
    *,
    with_fishing_cfg: bool = True,
) -> Dict[str, Any]:
    """构造测试 ctx：maps/season/period/fish_table/fishing_cfg 注入（对齐装配层）。"""
    ctx: Dict[str, Any] = {
        "qid": "u2a_test",
        "location": location,
        "season": season,
        "period": period,
        "maps": list(maps) if maps is not None else _MAPS,
        "fish_table": _fish_table(species),
        "settings": {"fishing": {"mode": mode}},
        "rng": random.Random(42),
        "player": {"persistent_state": {}},
    }
    if with_fishing_cfg:
        ctx["fishing_cfg"] = {"mode": mode}
    return ctx


def _parsed(raw: str) -> Any:
    """parse_command 真实解析（白名单扩展 /钓鱼——装配收口后进 DEFAULT_WHITELIST）。"""
    return parse_command(raw, whitelist=DEFAULT_WHITELIST | {FISH_CMD})


def _run(raw: str, ctx: MutableMapping[str, Any]) -> str:
    """cmd_fishing 直调（确定性：ctx 由 _ctx 注入，无随机）。"""
    return cmd_fishing(_parsed(raw), ctx)


# =====================================================================================
# A. 无参列举（TC-01：有钓点列出 + 字段齐全）
# =====================================================================================

def test_tc01_no_arg_lists_spots_with_fields() -> None:
    """TC-01：有钓点地图 /钓鱼（无参）→ 列出当前地图全部可钓鱼点。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    out = _run("/钓鱼", ctx)
    # 头部含当前地图名
    assert "幽光林地" in out
    # 两个垂钓点均列出（gp_moon_grass 银鳞鲤+金鳞鲤 / gp_reed_bank 芦丛鲫）
    assert "gp_moon_grass" in out
    assert "gp_reed_bank" in out
    # 字段齐全：名称/时段偏好/稀有度标记
    assert "时段：" in out
    assert "稀有度：" in out
    # 稀有度标记 = 候选最高 gold（金鳞鲤）
    assert "金色" in out


def test_tc01_no_arg_intent_ref_three_keywords_verbatim() -> None:
    """TC-01：鱼讯参考说明三组关键词逐字（微动=小鱼 / 拉扯=中鱼 / 猛烈=大鱼或鱼王！）。"""
    assert FISH_INTENT_REF == "微动=小鱼 / 拉扯=中鱼 / 猛烈=大鱼或鱼王！"
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    out = _run("/钓鱼", ctx)
    assert "微动=小鱼 / 拉扯=中鱼 / 猛烈=大鱼或鱼王！" in out


def test_no_arg_period_preference_union_cn() -> None:
    """无参：时段偏好 = 候选鱼种 periods 并集中文（银鳞鲤 晨/午/昏 + 金鳞鲤 全天）。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    out = _run("/钓鱼", ctx)
    line = next((ln for ln in out.splitlines() if "gp_moon_grass" in ln), "")
    assert "晨/午/昏" in line


def test_no_arg_all_day_period_when_empty() -> None:
    """无参：候选鱼种 periods 全空（芦丛鲫 全年全天）→ 时段偏好 全天。"""
    ctx = _ctx(location="gloom_forest", season="winter", period="night")
    out = _run("/钓鱼", ctx)
    line = next((ln for ln in out.splitlines() if "gp_reed_bank" in ln), "")
    assert "全天" in line


def test_no_arg_rarity_marker_normal_when_only_normal_candidates() -> None:
    """无参：稀有度标记 normal（仅普通鱼种候选）→ 普通。"""
    # 只保留银鳞鲤（normal）——去掉金鳞鲤（gold）
    species = {"silver_carp": _FISH_TABLE["silver_carp"]}
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn", species=species)
    out = _run("/钓鱼", ctx)
    line = next((ln for ln in out.splitlines() if "gp_moon_grass" in ln), "")
    assert "稀有度：普通" in line


def test_no_arg_rarity_marker_rare_from_rare_candidate() -> None:
    """无参：稀有度标记 rare（赤纹泥鳅 稀有）→ 稀有。"""
    ctx = _ctx(location="abandoned_mine", season="summer", period="night")
    out = _run("/钓鱼", ctx)
    line = next((ln for ln in out.splitlines() if "gp_star_iron" in ln), "")
    assert "稀有度：稀有" in line


def test_no_arg_spot_order_follows_gather_points() -> None:
    """无参：多钓点顺序跟随 gather_points 原序。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    out = _run("/钓鱼", ctx)
    idx_moon = out.find("gp_moon_grass")
    idx_reed = out.find("gp_reed_bank")
    assert 0 <= idx_moon < idx_reed


# =====================================================================================
# B. 候选规则（2c1a §1.4：当前季节/时段存在候选鱼种的钓点；空=不限）
# =====================================================================================

def test_candidate_filter_by_season_excludes_spot() -> None:
    """候选规则：季节过滤——废弃矿坑鱼种仅夏季/秋季 → 春季无候选 → 空态。"""
    ctx = _ctx(location="abandoned_mine", season="spring", period="dawn")
    out = _run("/钓鱼", ctx)
    assert "本图暂无可钓鱼点" in out
    assert "gp_star_iron" not in out


def test_candidate_filter_by_period_excludes_spot() -> None:
    """候选规则：时段过滤——赤纹泥鳅仅夜晚 → 夏季正午无候选（秋鲤秋季）→ 空态。"""
    ctx = _ctx(location="abandoned_mine", season="summer", period="noon")
    out = _run("/钓鱼", ctx)
    assert "本图暂无可钓鱼点" in out


def test_candidate_empty_seasons_periods_unrestricted() -> None:
    """候选规则：seasons/periods 空=不限——金鳞鲤冬季夜晚仍候选（gp_moon_grass 列出）。"""
    ctx = _ctx(location="gloom_forest", season="winter", period="midnight")
    out = _run("/钓鱼", ctx)
    assert "gp_moon_grass" in out
    assert "金色" in out


def test_candidate_spot_combo_map_colon_reference() -> None:
    """候选规则：spots \"map:spot\" 组合引用——calm_lake:deep_hole 命中 深潭 采集点。"""
    ctx = _ctx(location="calm_lake", season="spring", period="noon")
    out = _run("/钓鱼", ctx)
    assert "深潭" in out
    assert "gp_moon_grass" not in out


def test_no_arg_chinese_season_period_normalized() -> None:
    """无参：中文季节/时段形态归一（夏/夜 → summer/night）→ 赤纹泥鳅候选列出。"""
    ctx = _ctx(location="abandoned_mine", season="夏", period="夜")
    out = _run("/钓鱼", ctx)
    assert "gp_star_iron" in out
    assert "稀有度：稀有" in out


def test_no_arg_unknown_season_period_unrestricted() -> None:
    """无参：季节/时段缺失或不可识别（--）→ 视为不限（宁多勿少，不误杀）。"""
    ctx = _ctx(location="gloom_forest", season="--", period="--")
    out = _run("/钓鱼", ctx)
    assert "gp_moon_grass" in out


# =====================================================================================
# C. 空态（TC-02）与数据缺失兜底
# =====================================================================================

def test_tc02_empty_map_no_gather_points() -> None:
    """TC-02：无钓点地图（无 gather_points）→ 空态文案，不含任何钓点实体。"""
    ctx = _ctx(location="empty_map", season="spring", period="dawn")
    out = _run("/钓鱼", ctx)
    assert "本图暂无可钓鱼点" in out
    assert "gp_" not in out
    assert "鱼讯参考" not in out


def test_tc02_map_missing_from_maps() -> None:
    """TC-02：location 不在 ctx[\"maps\"] → 空态（不崩）。"""
    ctx = _ctx(location="nowhere_map", season="spring", period="dawn")
    out = _run("/钓鱼", ctx)
    assert "本图暂无可钓鱼点" in out


def test_tc02_maps_missing_ctx() -> None:
    """TC-02：ctx[\"maps\"] 缺失/None → 空态（不崩）。"""
    ctx = _ctx(location="gloom_forest")
    ctx["maps"] = None
    out = _run("/钓鱼", ctx)
    assert "本图暂无可钓鱼点" in out


def test_tc02_no_species_data() -> None:
    """TC-02：鱼种池为空（fish_table 空）→ 无可钓鱼点 → 空态（不崩）。"""
    ctx = _ctx(location="gloom_forest", species={})
    out = _run("/钓鱼", ctx)
    assert "本图暂无可钓鱼点" in out


def test_fishing_cfg_missing_self_fallback() -> None:
    """mode 读 ctx[\"fishing_cfg\"] 优先；缺失 → fishing_cfg(ctx) 自兜底（默认 full）。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn",
               with_fishing_cfg=False)
    out = _run("/钓鱼", ctx)
    assert "gp_moon_grass" in out


# =====================================================================================
# D. off 模式拒绝（GU-01 / TC-09）
# =====================================================================================

def test_tc09_off_mode_no_arg_rejected() -> None:
    """TC-09：off 模式 /钓鱼（无参）→ 拒绝「钓鱼功能已关闭」。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn", mode="off")
    out = _run("/钓鱼", ctx)
    assert "钓鱼功能已关闭" in out
    assert "gp_moon_grass" not in out


def test_tc09_off_mode_with_arg_rejected() -> None:
    """TC-09：off 模式 /钓鱼 <钓点> → 同样拒绝（GU-01 全拒绝）。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn", mode="off")
    out = _run("/钓鱼 gp_moon_grass", ctx)
    assert "钓鱼功能已关闭" in out
    assert "gp_moon_grass" not in out


def test_off_mode_from_settings_fallback() -> None:
    """off 判定经 settings.fishing.mode 兜底（fishing_cfg 缺失时）同样拒绝。"""
    ctx = _ctx(location="gloom_forest", with_fishing_cfg=False)
    ctx["settings"] = {"fishing": {"mode": "off"}}
    out = _run("/钓鱼", ctx)
    assert "钓鱼功能已关闭" in out


# =====================================================================================
# E. 有参下钩转发（路2B core/fishing_cast 同批并行落盘 → 真转发；ImportError → 工程补白兜底）
# =====================================================================================

def test_cast_forward_blank_spot_defaults_first_fishable() -> None:
    """下钩转发：空白钓点参数 → 缺省默认选中第一个可钓点（细化 1.2 实现层约定）。"""
    from qbot_rpg.commands.fishing_commands import _cast_forward

    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    ctx["now"] = 1_800_000_000
    out = _cast_forward(ctx, "   ")
    # 空白参 → first_fishable_spot(gp_moon_grass) → 真转发下钩
    assert "已抛竿" in out
    assert "gp_moon_grass" in out


def test_with_arg_forwards_to_cast_fishing() -> None:
    """有参：core.fishing_cast 已落盘（同批并行）→ 真转发 cast_fishing，返回下钩成功消息。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    ctx["now"] = 1_800_000_000
    out = _run("/钓鱼 gp_moon_grass", ctx)
    # 真转发消息（cast_fishing：已抛竿 + 钓点 + 等待 + 今日已抛）
    assert "已抛竿" in out
    assert "gp_moon_grass" in out
    assert "今日已抛" in out
    # 下钩为有副作用写入：fish_state 进入 S2（引擎已写 ctx 键即挂 ps 落档）
    fs = ctx.get("fish_state")
    assert isinstance(fs, Mapping) and fs.get("state") == "S2"


def test_with_arg_cast_reject_guard_transparent() -> None:
    """有参：cast_fishing 引擎拒绝（off）→ 拒绝消息透传（守卫 GU-01 由引擎拦）。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn", mode="off")
    out = _run("/钓鱼 gp_moon_grass", ctx)
    assert "钓鱼功能已关闭" in out


def test_with_arg_cast_spot_not_found() -> None:
    """有参：钓点解析失败（未知钓点）→ cast_fishing 返回「钓点不存在」消息。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    out = _run("/钓鱼 nowhere_spot", ctx)
    assert "钓点不存在" in out


def test_with_arg_import_error_falls_back(monkeypatch: Any) -> None:
    """ImportError 探活：core.fishing_cast 导入失败 → 工程补白兜底文案返回。"""
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *a: Any, **k: Any) -> Any:
        if name == "qbot_rpg.core.fishing_cast":
            raise ModuleNotFoundError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    out = _run("/钓鱼 gp_moon_grass", ctx)
    assert out == FISH_CAST_FALLBACK
    assert "工程补白" in out


# =====================================================================================
# F. 纯函数工具（list_fishable_spots / first_fishable_spot / normalize_*）
# =====================================================================================

def test_list_fishable_spots_structure() -> None:
    """list_fishable_spots 返回结构：id/name/periods/rarity/rarity_cn 齐全。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    spots = list_fishable_spots(ctx)
    assert len(spots) == 2
    for sp in spots:
        assert set(sp) >= {"id", "name", "periods", "rarity", "rarity_cn"}
    assert spots[0]["id"] == "gp_moon_grass"
    assert spots[0]["rarity"] == "gold"
    assert spots[0]["rarity_cn"] == "金色"


def test_first_fishable_spot_returns_first() -> None:
    """first_fishable_spot：当前地图首个可钓点 id；无可钓点 → None。"""
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    assert first_fishable_spot(ctx) == "gp_moon_grass"
    ctx2 = _ctx(location="empty_map", season="spring", period="dawn")
    assert first_fishable_spot(ctx2) is None


def test_normalize_season_period_bilingual() -> None:
    """normalize_season/period 双形态归一：中文 → 英文枚举；英文原样；非法 → None。"""
    assert normalize_season("秋") == "autumn"
    assert normalize_season("summer") == "summer"
    assert normalize_season("not_a_season") is None
    assert normalize_season(None) is None
    assert normalize_period("黄昏") == "dusk"
    assert normalize_period("dawn") == "dawn"
    assert normalize_period("中午") is None
    assert normalize_period("--") is None


# =====================================================================================
# G. 装配：register_fishing_commands
# =====================================================================================

def test_register_fishing_commands_specs() -> None:
    """装配：register_fishing_commands 注册 /钓鱼（CommandSpec 白名单标记）。"""
    router = Router()
    register_fishing_commands(router, make_context=lambda p: {})
    assert router.has(FISH_CMD)
    spec = router.get(FISH_CMD)
    assert spec is not None and spec.whitelisted
    assert callable(spec.handler)


def test_register_fishing_make_context_injection() -> None:
    """装配：handler 支持 k.get(\"ctx\") 注入；无 make_context → RuntimeError。"""
    import pytest

    router = Router()
    register_fishing_commands(router, make_context=None)
    spec = router.get(FISH_CMD)
    assert spec is not None and spec.handler is not None
    # 无 make_context 且无 ctx 注入 → RuntimeError（【待接线】装配层注入）
    with pytest.raises(RuntimeError):
        spec.handler(_parsed("/钓鱼"))
    # ctx 注入形态直接可用
    ctx = _ctx(location="gloom_forest", season="spring", period="dawn")
    out = spec.handler(_parsed("/钓鱼"), ctx=ctx)
    assert "gp_moon_grass" in out
