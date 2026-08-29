"""炼金指令壳单测（M8 批4B · qbot_rpg/commands/alchemy_commands.py 的 /炼金 + /投料）。

文件：tests/unit/test_alchemy_commands.py
创建：2026-08-29
作者：Hermes 子agent-4B
功能：cmd_alchemy（/炼金：开会话/自动子词/批量 *N）+ cmd_feed（/投料：链式/追加子词）异步直测。
  真实引擎消费：AlchemyCore / EnergyBar / AutoFeed / ProficiencyEngine / QualitySystem +
  async fake session_mgr（内存 dict 模拟 get_active/acquire/suspend/release）。

覆盖矩阵（每条正例 + 负例，断言精确文本/数值/快照字段；asyncio_mode=auto 直接 await）：
  /炼金：无炼金职业拒绝 / 开会话面板（配方Lv/材料/刻度/特性位/PP/投入次数）/ 已有会话互斥
    （调合进行中 + 已有活跃 + acquire 冲突）/ 能量不足拒绝（energy_enabled=true）/ 默认关直通 /
    能量消耗 -1 / 触媒非专家拒绝 / 触媒=合法（type=触媒 校验 + 方向改变属性）/ 触媒非法拒绝 /
    触媒未注册提示不阻断 / 自动子词配平成功 / 自动子词配平失败差异全拒 / 批量 *N 原子成功
    （扣料/能量/金币/平均品质/熟练经验）/ 批量材料不足全拒差异 / 批量超限提示不拦截 /
    批量能量不足全拒 / 配方不存在 / 缺参 TPL-12
  /投料：无会话拒绝「当前没有调合会话…」/ 战斗中拦截 / 成功（连锁段数+可继承特性清单）/
    追加子词（链追加+version 递增）/ 超槽位拒绝 / 材料不足差异 / 非调合会话拒绝 / 数量 *N 解析 /
    缺参 TPL-12
  装配：register_alchemy_commands 注册 炼金/投料

依据：docs/m8_contract_指令契约.md §2 /炼金（GU-05~08/F-02/M-02）+ §3 /投料（GU-09~12/F-03/
  M-03）+ docs/m8_contract_核心机制.md §六（FEED/AUTO/BATCH/CAT）+ 细化_2c4f（TC-01~20）。
测试风格对齐 tests/unit/test_synthesis_commands.py（parse_command 直调 + 全字段 ctx）+
  tests/unit/test_alchemy_core.py（items/traits/recipe 注册表夹具）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from qbot_rpg.commands.alchemy_commands import (
    ALCHEMY_CMD,
    FEED_CMD,
    SYNTH_CMD,
    cmd_alchemy,
    cmd_feed,
    register_alchemy_commands,
)
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.world.session import SessionConflictError

# ---------------------------------------------------------------------------
# 夹具：items/traits/recipe 注册表 + settings（对齐 content/test_demo 形态）
# ---------------------------------------------------------------------------

ITEMS: Dict[str, dict] = {
    "fire_crystal": {"id": "fire_crystal", "name": "火晶石", "type": "material",
                     "elements": {"fire": 4}, "traits": ["trait_burn_boost"]},
    "ice_crystal": {"id": "ice_crystal", "name": "冰晶", "type": "material",
                    "elements": {"water": 4}},
    "herb": {"id": "herb", "name": "草药", "type": "material"},
    "moon_grass": {"id": "moon_grass", "name": "月光草", "type": "material"},
    # 批量平均品质材料（quality 档 → 档位代表分，BATCH-02）
    "mat_a": {"id": "mat_a", "name": "精良矿石", "type": "material", "quality": "uncommon",
              "elements": {"earth": 1}},
    "mat_b": {"id": "mat_b", "name": "传说精华", "type": "material", "quality": "legendary",
              "elements": {"fire": 1}},
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
    "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable"},
    # 触媒（type=触媒，CAT-05）
    "catalyst_fire": {"id": "catalyst_fire", "name": "爆裂壶", "type": "触媒",
                      "elements": {"fire": 5}},
}

TRAITS: Dict[str, dict] = {
    "trait_burn_boost": {"id": "trait_burn_boost", "name": "灼烧强化",
                         "rarity": "normal", "source": "素材"},
}

RECIPES: Dict[str, dict] = {
    "rcp_flame": {"id": "rcp_flame", "name": "火焰弹", "level": 5, "slots": 5,
                  "pp_budget": 5, "traits_inherit": 2,
                  "materials": [{"id": "moon_grass", "count": 2}],
                  "element_req": {"fire": [{"threshold": 6, "effect": "范围爆炸"}]},
                  "cost": {"coins": 100, "gem": 0},
                  "output": {"item": "flame_bomb", "count": 1}},
    "rcp_batch": {"id": "rcp_batch", "name": "批量药水", "level": 3, "slots": 4,
                  "pp_budget": 2, "traits_inherit": 1,
                  "materials": [{"id": "mat_a", "count": 1}, {"id": "mat_b", "count": 1}],
                  "cost": {"coins": 50, "gem": 0},
                  "output": {"item": "mana_potion", "count": 1}},
}

SETTINGS: Dict[str, Any] = {
    "currencies": [{"id": "coins", "name": "金币"}, {"id": "gem", "name": "宝石"}],
    "alchemy": {
        "mode": "full",
        "energy_enabled": False,          # R-08 默认关
        "catalyst_unlock_tier": "expert",  # R-07 专家解锁
        "max_qty": 2147483647,            # 拍板⑤
        "quality_tiers": {"common": [0, 39], "uncommon": [40, 59],
                          "rare": [60, 79], "legendary": [80, 100]},
        "quality_coef": {"common": 0.8, "uncommon": 1.0, "rare": 1.2, "legendary": 1.5},
        "chain_map": {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6},
        "pp_cost": {"normal": 1, "super": 2},
        "job_tier_map": {
            "见习": [1, 5], "正式": [6, 15], "精通": [16, 25], "专家": [26, 35],
            "大师": [36, 45], "宗师": [46, 60], "王": [61, 99],
        },
    },
}


def _alchemy_node(level: int = 3) -> dict:
    """炼金职业节点（level = 档位索引 0~6；3=专家，触媒解锁 R-07）。"""
    return {"level": level, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}}


class FakeSessions:
    """async 会话 fake：内存 dict 模拟 get_active/acquire/suspend/release。

    view 形态 = {session_type, payload, version}（dict 视图，is_alchemy_session/_view_payload
    鸭子兼容）。acquire 冲突抛真实 SessionConflictError（is_conflict 鸭子判定路径）。
    """

    def __init__(self) -> None:
        self.store: Dict[str, dict] = {}
        self.calls: list = []
        self.conflict_on_acquire: bool = False

    async def get_active(self, qid: str) -> Optional[dict]:
        self.calls.append(("get_active", qid))
        return self.store.get(qid)

    async def acquire(self, qid: str, session_type: str,
                      payload: Any = None) -> dict:
        self.calls.append(("acquire", qid, session_type))
        if self.conflict_on_acquire or qid in self.store:
            raise SessionConflictError(f"玩家 {qid} 已有活跃会话，拒绝新建")
        self.store[qid] = {"session_type": session_type, "payload": payload, "version": 1}
        return self.store[qid]

    async def suspend(self, qid: str, snapshot: Any) -> None:
        self.calls.append(("suspend", qid))
        cur = self.store.get(qid, {})
        self.store[qid] = {
            "session_type": cur.get("session_type", "alchemy"),
            "payload": snapshot,
            "version": int(cur.get("version", 1)) + 1,
        }

    async def release(self, qid: str) -> None:
        self.calls.append(("release", qid))
        self.store.pop(qid, None)


def make_ctx(**over: Any) -> dict:
    """全字段炼金 ctx（player 字段在 ctx 顶层——_player_of 兜底口径，对齐 test_synthesis）：
    proficiency/currencies/inventory/persistent_state + items/traits/recipe/settings/session_mgr。
    """
    base: dict = {
        "qid": "u1",
        "proficiency": {"alchemy": _alchemy_node(3)},
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {"fire_crystal": 20, "ice_crystal": 10, "herb": 10,
                      "moon_grass": 5, "catalyst_fire": 2, "mat_a": 10, "mat_b": 10},
        "items": ITEMS,
        "traits": TRAITS,
        "recipe": RECIPES,
        "settings": SETTINGS,
        "session_mgr": FakeSessions(),
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# /炼金：GU-05 无炼金职业拒绝
# ---------------------------------------------------------------------------
async def test_alchemy_no_job_rejected() -> None:
    """GU-05 负例：proficiency 无 alchemy 节点 → 「❌ 等级不足」（L344）。"""
    ctx = make_ctx(proficiency={})
    out = await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    assert "等级不足" in out
    assert out.startswith("❌")


# ---------------------------------------------------------------------------
# /炼金：开会话成功（F-02/M-02 面板）
# ---------------------------------------------------------------------------
async def test_alchemy_open_session_panel_ok() -> None:
    """F-02 正例：有炼金职业开会话 → 面板含 配方Lv/材料/刻度/特性位/PP/投入次数；快照落库。"""
    ctx = make_ctx()
    out = await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    assert "火焰弹（配方Lv5）" in out
    assert "材料：月光草×2" in out
    assert '属性刻度：火≥6 显现"范围爆炸"' in out
    assert "特性位 0/2" in out
    assert "PP 0/5" in out
    assert "投入次数 0/5" in out
    sm = ctx["session_mgr"]
    assert ("acquire", "u1", "alchemy") in sm.calls
    assert sm.store["u1"]["session_type"] == "alchemy"
    snap = sm.store["u1"]["payload"]
    assert snap["recipe_id"] == "rcp_flame"
    assert snap["version"] == 1
    # 默认关（R-08）：不扣能量、无 persistent_state 写
    assert "persistent_state" not in ctx


async def test_alchemy_recipe_not_found() -> None:
    """负例：配方不存在 → 「❌ 配方不存在：xxx」。"""
    ctx = make_ctx()
    out = await cmd_alchemy(parse_command("/炼金 不存在配方"), ctx)
    assert "配方不存在" in out


async def test_alchemy_missing_arg_tpl12() -> None:
    """负例：/炼金 缺参 → TPL-12（指令不正确）。"""
    ctx = make_ctx()
    out = await cmd_alchemy(parse_command("/炼金"), ctx)
    assert "指令不正确" in out


# ---------------------------------------------------------------------------
# /炼金：GU-07 会话互斥（MUT-02 全局互斥）
# ---------------------------------------------------------------------------
async def test_alchemy_mutex_alchemy_active() -> None:
    """GU-07 负例：已有调合会话 → 「调合进行中！/放弃 退出 或 /调合续 继续」（定稿 L176）。"""
    ctx = make_ctx()
    ctx["session_mgr"].store["u1"] = {"session_type": "alchemy", "payload": {}, "version": 1}
    out = await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    assert "调合进行中" in out


async def test_alchemy_mutex_other_session_active() -> None:
    """GU-07 负例：已有非调合会话（battle）→ 「已有活跃会话」（行3 全局互斥）。"""
    ctx = make_ctx()
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    assert "已有活跃会话" in out


async def test_alchemy_mutex_acquire_conflict() -> None:
    """GU-07 负例（acquire 竞态）：get_active=None 但 acquire 抛 SessionConflictError →
    捕获 → 「已有活跃会话」（§7.2/IF-16）。"""
    ctx = make_ctx()
    ctx["session_mgr"].conflict_on_acquire = True
    out = await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    assert "已有活跃会话" in out
    assert "u1" not in ctx["session_mgr"].store  # 冲突拒绝不建会话


# ---------------------------------------------------------------------------
# /炼金：GU-06 能量（ENG-04/R-08）
# ---------------------------------------------------------------------------
async def test_alchemy_energy_insufficient_rejected() -> None:
    """GU-06 负例：energy_enabled=true 且能量 0 →
    「能量 0/…，等 30 分钟回 1 格，或 /合成 保底」。"""
    settings = {"alchemy": dict(SETTINGS["alchemy"], energy_enabled=True)}
    ctx = make_ctx(settings=settings,
                   persistent_state={"energy_current": 0, "energy_last_regen_ts": 10 ** 12})
    out = await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    assert "能量" in out and "0" in out
    assert "等 30 分钟回 1 格" in out
    assert "/合成 保底" in out
    assert "u1" not in ctx["session_mgr"].store  # 能量不足不建会话（防孤儿）


async def test_alchemy_energy_off_bypass() -> None:
    """GU-06/R-08 正例：energy_enabled=false（默认关）→ 能量 0 也直通开会话、不扣。"""
    ctx = make_ctx(persistent_state={"energy_current": 0, "energy_last_regen_ts": 10 ** 12})
    out = await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    assert "火焰弹" in out
    assert "能量" not in out


async def test_alchemy_energy_consumed_one() -> None:
    """ENG-04 正例：energy_enabled=true 能量 5 → 开会话扣 1 格（5 → 4）。"""
    settings = {"alchemy": dict(SETTINGS["alchemy"], energy_enabled=True)}
    ctx = make_ctx(settings=settings,
                   persistent_state={"energy_current": 5, "energy_last_regen_ts": 10 ** 12})
    out = await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    assert "火焰弹" in out
    assert ctx["persistent_state"]["energy_current"] == 4


# ---------------------------------------------------------------------------
# /炼金：GU-08 触媒（R-07/CAT-01~05）
# ---------------------------------------------------------------------------
async def test_alchemy_catalyst_not_expert_rejected() -> None:
    """GU-08/R-07 负例：精通（index 2 < 专家 3）+ 触媒 → 「❌ 等级不足」（CAT-01/L344）。"""
    ctx = make_ctx(proficiency={"alchemy": _alchemy_node(2)})
    out = await cmd_alchemy(parse_command("/炼金 火焰弹 触媒=爆裂壶"), ctx)
    assert "等级不足" in out
    assert "u1" not in ctx["session_mgr"].store


async def test_alchemy_catalyst_valid_records_and_panel() -> None:
    """GU-08/CAT-05 正例：专家 + 触媒=爆裂壶（type=触媒）→ 开会话，快照 catalyst 记录。"""
    ctx = make_ctx()
    out = await cmd_alchemy(parse_command("/炼金 火焰弹 触媒=爆裂壶"), ctx)
    assert "火焰弹" in out
    snap = ctx["session_mgr"].store["u1"]["payload"]
    assert snap["catalyst"] == "爆裂壶"


async def test_alchemy_catalyst_invalid_rejected() -> None:
    """CAT-05/L344 负例：触媒=草药（type≠触媒）→ 「触媒无效」。"""
    ctx = make_ctx()
    out = await cmd_alchemy(parse_command("/炼金 火焰弹 触媒=草药"), ctx)
    assert "触媒无效" in out
    assert "u1" not in ctx["session_mgr"].store


async def test_alchemy_catalyst_unregistered_hint_not_block() -> None:
    """CAT-03 负例：未注册触媒 → 仅提示不阻断（提示行 + 面板照常）。"""
    ctx = make_ctx()
    out = await cmd_alchemy(parse_command("/炼金 火焰弹 触媒=未注册壶"), ctx)
    assert "未注册" in out
    assert "火焰弹" in out
    assert ctx["session_mgr"].store["u1"]["payload"]["catalyst"] is None


async def test_alchemy_catalyst_changes_element_direction() -> None:
    """CAT-02 正例（方向修饰）：带爆裂壶（火方向）投 冰晶 → 反馈「⚗️ 火+4」（触媒改变属性判定）。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹 触媒=爆裂壶"), ctx)
    out = await cmd_feed(parse_command("/投料 冰晶"), ctx)
    assert "火+4" in out  # 触媒方向修饰后主元素=火


# ---------------------------------------------------------------------------
# /炼金：自动子词（AUTO-01~03）
# ---------------------------------------------------------------------------
async def test_alchemy_auto_balance_ok() -> None:
    """AUTO-02 正例：/炼金 火焰弹 自动 → 自动配平入链（element_req 优先 火晶石×2）→ 面板。"""
    ctx = make_ctx(inventory={"fire_crystal": 3, "moon_grass": 5})
    out = await cmd_alchemy(parse_command("/炼金 火焰弹 自动"), ctx)
    assert "火焰弹" in out
    assert "火晶石×2" in out
    assert "投入次数 2/5" in out
    snap = ctx["session_mgr"].store["u1"]["payload"]
    # apply_feed 单条记录 count=2（A-1 链位在 compute_chain 展开）
    assert [(r["item"], r["count"]) for r in snap["materials"]] == [("fire_crystal", 2)]


async def test_alchemy_auto_balance_fail_diff() -> None:
    """AUTO-03 负例：背包无法配平（缺月光草）→ 全拒 + 差异「缺 月光草×1」，不建会话。"""
    ctx = make_ctx(inventory={"moon_grass": 1})
    out = await cmd_alchemy(parse_command("/炼金 火焰弹 自动"), ctx)
    assert "缺 月光草×1" in out
    assert "u1" not in ctx["session_mgr"].store  # 原子拒绝零消耗


# ---------------------------------------------------------------------------
# /炼金：批量 *N（BATCH-01~05，不开会话）
# ---------------------------------------------------------------------------
async def test_alchemy_batch_atomic_ok() -> None:
    """BATCH-01~05 正例：/炼金 批量药水*3 → 原子扣料/金币/能量 + 平均品质产出 + 熟练经验；
    不开会话。"""
    settings = {"alchemy": dict(SETTINGS["alchemy"], energy_enabled=True)}
    ctx = make_ctx(settings=settings, inventory={"mat_a": 10, "mat_b": 10},
                   persistent_state={"energy_current": 5, "energy_last_regen_ts": 10 ** 12})
    out = await cmd_alchemy(parse_command("/炼金 批量药水*3"), ctx)
    # 平均品质：mat_a(uncommon→49) + mat_b(legendary→90) → 均值 69.5 → 70 → rare（史诗）
    assert "魔力药水 ×3" in out
    assert "平均品质 70·史诗" in out
    assert "能量 -3" in out
    # 扣料：mat_a×3、mat_b×3；金币 50×3=150
    assert ctx["inventory"]["mat_a"] == 7 and ctx["inventory"]["mat_b"] == 7
    assert ctx["currencies"]["coins"] == 1000 - 150
    assert ctx["persistent_state"]["energy_current"] == 5 - 3
    # 产出：魔力药水 ×3 入包
    assert ctx["inventory"]["mana_potion"] == 3
    # 熟练经验：配方等级 3 × N 3 = 9（craft 倍率 1.0 兜底）
    assert ctx["proficiency"]["alchemy"]["exp"] == 9
    # 不开会话（批量无投料/继承/确认链）
    assert "u1" not in ctx["session_mgr"].store


async def test_alchemy_batch_materials_shortfall_reject() -> None:
    """BATCH-05 负例：材料不足 → 全拒 + 差异「缺 精良矿石×3」；零扣减（原子）。"""
    ctx = make_ctx(inventory={"mat_a": 2, "mat_b": 10})
    out = await cmd_alchemy(parse_command("/炼金 批量药水*3"), ctx)
    assert "材料不足" in out
    assert "缺 精良矿石×1" in out  # need 3 have 2 → 缺 1
    assert ctx["inventory"]["mat_a"] == 2 and ctx["inventory"]["mat_b"] == 10
    assert ctx["currencies"]["coins"] == 1000
    assert "mana_potion" not in ctx["inventory"]


async def test_alchemy_batch_over_limit_hint_not_block() -> None:
    """BATCH-04 拍板⑤：超 max_qty → 「最多一次使用 N 个」提示不拦截，照常执行。"""
    settings = {"alchemy": dict(SETTINGS["alchemy"], max_qty=2)}
    ctx = make_ctx(settings=settings, inventory={"mat_a": 10, "mat_b": 10})
    out = await cmd_alchemy(parse_command("/炼金 批量药水*3"), ctx)
    assert "最多一次使用 2 个" in out
    assert "魔力药水 ×3" in out
    assert ctx["inventory"]["mana_potion"] == 3


async def test_alchemy_batch_energy_insufficient_reject() -> None:
    """BATCH-03/05 负例：energy_enabled=true 能量 < N → 全拒（能量不足模板），零扣减。"""
    settings = {"alchemy": dict(SETTINGS["alchemy"], energy_enabled=True)}
    ctx = make_ctx(settings=settings, inventory={"mat_a": 10, "mat_b": 10},
                   persistent_state={"energy_current": 2, "energy_last_regen_ts": 10 ** 12})
    out = await cmd_alchemy(parse_command("/炼金 批量药水*3"), ctx)
    assert "能量" in out and "或 /合成 保底" in out
    assert ctx["inventory"]["mat_a"] == 10 and ctx["inventory"]["mat_b"] == 10
    assert ctx["currencies"]["coins"] == 1000
    assert "mana_potion" not in ctx["inventory"]


# ---------------------------------------------------------------------------
# /投料：GU-09 无会话 / GU-10 战斗拦截
# ---------------------------------------------------------------------------
async def test_feed_no_session_rejected() -> None:
    """GU-09 负例：无会话发 /投料 → 「当前没有调合会话，先 /炼金 <配方> 开始」（L175）。"""
    ctx = make_ctx()
    out = await cmd_feed(parse_command("/投料 火晶石"), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


async def test_feed_battle_intercept() -> None:
    """GU-10/MUT-04 负例：战斗中发 /投料 → 「战斗中使用 /即时调合 <配方>」（L295）。"""
    ctx = make_ctx(in_battle=True)
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_feed(parse_command("/投料 火晶石"), ctx)
    assert "战斗中使用 /即时调合 <配方>" in out


async def test_feed_non_alchemy_session_rejected() -> None:
    """GU-09 负例：活跃会话非调合类（battle，非战斗场景）→ 无会话模板（P-6 防御）。"""
    ctx = make_ctx()
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_feed(parse_command("/投料 火晶石"), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


async def test_feed_missing_arg_tpl12() -> None:
    """负例：/投料 缺参 → TPL-12。"""
    ctx = make_ctx()
    out = await cmd_feed(parse_command("/投料"), ctx)
    assert "指令不正确" in out


# ---------------------------------------------------------------------------
# /投料：F-03 链式投料成功（M-03 反馈）
# ---------------------------------------------------------------------------
async def test_feed_ok_chain_and_inherit_feedback() -> None:
    """F-03/M-03 正例：投 火晶石,火晶石 → 「⚗️ 火+8 | 连锁 1 段 | 可继承特性：灼烧强化(PP1)」。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    out = await cmd_feed(parse_command("/投料 火晶石,火晶石"), ctx)
    assert "火+8" in out
    assert "连锁 1 段" in out
    assert "可继承特性：灼烧强化(PP1)" in out
    # 快照持久化（suspend 后 version 递增：acquire=1 → feed 后=2）
    snap = ctx["session_mgr"].store["u1"]["payload"]
    assert [r["item"] for r in snap["materials"]] == ["fire_crystal", "fire_crystal"]
    assert ctx["session_mgr"].store["u1"]["version"] == 2


async def test_feed_append_subword() -> None:
    """FEED-02 追加正例：/投料 追加 草药 → 追加入链（version 再递增，§7.1 行4）。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 火晶石"), ctx)
    out = await cmd_feed(parse_command("/投料 追加 草药"), ctx)
    assert "连锁 0 段" in out  # 追加后全链重算（火 + 无属性 → 0 段）
    snap = ctx["session_mgr"].store["u1"]["payload"]
    items = [r["item"] for r in snap["materials"]]
    assert items == ["fire_crystal", "herb"]  # 追加不覆盖原链
    assert ctx["session_mgr"].store["u1"]["version"] == 3  # acquire1 → feed2 → append3


async def test_feed_quantity_parse() -> None:
    """P-03/SEP-03 正例：/投料 火晶石*2,冰晶 → 单项数量解析（火晶石×2 入链，A-1 链位）。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 火晶石*2,冰晶"), ctx)
    snap = ctx["session_mgr"].store["u1"]["payload"]
    counts = [(r["item"], r["count"]) for r in snap["materials"]]
    assert ("fire_crystal", 2) in counts and ("ice_crystal", 1) in counts


async def test_feed_slots_overflow() -> None:
    """GU-11/FEED-04 负例：投满 5 槽再追加 → 「投料超槽位」（L344）。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)  # slots=5
    await cmd_feed(parse_command("/投料 火晶石*5"), ctx)
    out = await cmd_feed(parse_command("/投料 追加 冰晶"), ctx)
    assert "投料超槽位" in out
    # 拒绝不改快照（原子）
    snap = ctx["session_mgr"].store["u1"]["payload"]
    assert len(snap["materials"]) == 1 and snap["materials"][0]["count"] == 5


async def test_feed_materials_insufficient_diff() -> None:
    """GU-12/FEED-05 负例：材料不足 → 「材料不足：缺 火晶石×2」（差异，原子全拒）。
    槽位上限（slots=5）内数量不足才走持有校验（apply_feed 校验链顺序：槽位 → 持有）。"""
    ctx = make_ctx(inventory={"fire_crystal": 3})
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    out = await cmd_feed(parse_command("/投料 火晶石*5"), ctx)
    assert "材料不足" in out
    assert "缺 火晶石×2" in out
    # 零扣减（原子口径）：快照无变化
    snap = ctx["session_mgr"].store["u1"]["payload"]
    assert snap["materials"] == []


# ---------------------------------------------------------------------------
# 装配：register_alchemy_commands（批11 接线前置）
# ---------------------------------------------------------------------------
async def test_register_alchemy_commands_feed_and_alchemy() -> None:
    """装配：register_alchemy_commands 注册 合成/炼金/投料 三条 CommandSpec。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: make_ctx())
    assert router.has(SYNTH_CMD)
    assert router.has(ALCHEMY_CMD)
    assert router.has(FEED_CMD)
    assert {SYNTH_CMD, ALCHEMY_CMD, FEED_CMD} <= set(router.names())
    a_spec = router.get(ALCHEMY_CMD)
    f_spec = router.get(FEED_CMD)
    assert a_spec is not None and a_spec.whitelisted
    assert f_spec is not None and f_spec.whitelisted


async def test_register_handlers_injectable_ctx() -> None:
    """装配：handler 支持 k.get("ctx") 注入（async 处理器 await 执行，
    runner _invoke_handler 口径）。"""
    router = Router()
    ctx = make_ctx()
    register_alchemy_commands(router, make_context=lambda p: {})
    a_spec = router.get(ALCHEMY_CMD)
    assert a_spec is not None and a_spec.handler is not None
    out = await a_spec.handler(
        parse_command("/炼金 火焰弹"), ctx=ctx
    )
    assert "火焰弹（配方Lv5）" in out
