"""炼金终态指令壳单测（M8 批6 · alchemy_commands.py 的 /确认 /放弃 /调合续 /分解）。

文件：tests/unit/test_confirm_commands.py
创建：2026-08-29
作者：Hermes 子agent-6A（并发同仓：仅新建本文件 + 追加 commands/alchemy_commands.py；兄弟路 6B
  在写 core/gem_wallet.py 宝石货币引擎——本测试用 FakeWallet 实现其接口契约，勿 import 勿探查）

功能：直测 async 指令处理器（真实引擎消费）：
  - /确认（SettleEngine.confirm 9 步管线 + 终态幂等 gate + TraitInherit 结算复核）：
    成功 M-05 品质 72·史诗 渲染 / 材料不足全拒差异 / 重复确认「已结算」幂等 /
    message_id 缺失保守不落键 / 无会话模板 / 战斗拦截 / 互斥组冲突复核拒绝；
  - /放弃（SettleEngine.abandon 终态，材料不结算）：成功 / 重复放弃幂等 / 无会话 / 战斗拦截；
  - /调合续（GU-18 恢复挂起(战斗)）：成功渲染面板 / 已有活跃拒绝 / 无挂起拒绝；
  - /分解（gem_wallet 鸭子类型消费）：成功两段式 / 标准版拒绝透传 / 回收减半透传 /
    道具不存在 / 缺参 TPL-12 / *数量解析 / async 钱包兼容；
  - 装配：register_alchemy_commands 注册 4 终态指令 + ctx 注入 handler。

覆盖规则（每条正反例，断言精确文本/数值/幂等键调用）：
  /确认：GU-17（会话中/无会话模板）、GU-19（全量复核差异）、F-05（品质结算 9 步）、
    M-05（品质 72·史诗 渲染）、ATO-04（重复确认「已结算」）、§10 铁律 3（settle:confirm 幂等键）、
    GU-10/MUT-04（战斗拦截）、INH-10/11（结算复核互斥组）；
  /放弃：GU-17、F-05（材料不结算）、§10 铁律 3（settle:abandon 幂等键）、M-05（已放弃）；
  /调合续：GU-18（挂起成功/已有活跃拒绝/无挂起拒绝）、§7.1 行7（恢复面板渲染）、行8/L177（模板）；
  /分解：GU-32/33（标准版拒/回收减半/道具不存在）、F-10/GEM-15（两段式消息）、
    拍板①（宝石平铺基础值不乘回收率）、P-10/*N 数量。

依据：docs/m8_contract_指令契约.md §5（GU-17~19/F-05/M-05）+ §10（GU-32/33/F-10/M-10）+
  §三 MUT-04/05 + §四 ATO-04/铁律 3 + docs/m8_contract_核心机制.md §7.1 行7/8 + §7.2 +
  docs/m8_contract_战斗资源.md GEM-13~15（分解两段式/回收率/平铺宝石）。
测试风格对齐 tests/unit/test_alchemy_commands.py（parse_command 直调 + 全字段 ctx + async fake
  session_mgr）+ tests/unit/test_alchemy_settle.py（SettleEngine 真实引擎 + ctx hook 背包改写）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from qbot_rpg.commands.alchemy_commands import (
    ABANDON_CMD,
    CONFIRM_CMD,
    DECOMPOSE_CMD,
    RESUME_CMD,
    cmd_abandon,
    cmd_confirm,
    cmd_decompose,
    cmd_resume,
    register_alchemy_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.world.session import SessionConflictError

# 终态 4 指令白名单（DEFAULT_WHITELIST 未含；批11 路11A 装配 IF-34 补齐——本测试注入同款）
W = DEFAULT_WHITELIST | {"确认", "放弃", "调合续", "分解"}


# ---------------------------------------------------------------------------
# 夹具：items/traits/recipe 注册表 + settings（对齐 test_alchemy_commands 形态）
# ---------------------------------------------------------------------------

ITEMS: Dict[str, dict] = {
    "fire_crystal": {"id": "fire_crystal", "name": "火晶石", "type": "material",
                     "elements": {"fire": 4}},
    "moon_grass": {"id": "moon_grass", "name": "月光草", "type": "material"},
    "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable",
                   "base_effects": {"fire_damage": 30}},
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
}

SETTINGS: Dict[str, Any] = {
    "currencies": [{"id": "coins", "name": "金币"}, {"id": "gem", "name": "宝石"}],
    "alchemy": {
        "mode": "full",
        "energy_enabled": False,            # R-08 默认关
        "catalyst_unlock_tier": "expert",
        "max_qty": 2147483647,              # 拍板⑤
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
    """炼金职业节点（level = 档位索引 0~6；3=专家）。"""
    return {"level": level, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}}


class FakeSessions:
    """async 会话 fake（get_active/acquire/suspend/settle_alchemy）。

    settle_alchemy 幂等（仿 settle_exit_idempotent，§10 铁律 3）：首次记键返回 True，重复返回
    False（已结算）；不删会话行（保留以测引擎幂等 gate 路径，真实 delete_session 由 storage
    层同事务承担）。view 形态 = {session_type, payload, version}（dict 视图，鸭子兼容）。
    """

    def __init__(self) -> None:
        self.store: Dict[str, dict] = {}
        self.idem: set = set()
        self.calls: list = []
        self.settle_always_false: bool = False

    async def get_active(self, qid: str) -> Optional[dict]:
        self.calls.append(("get_active", qid))
        return self.store.get(qid)

    async def acquire(self, qid: str, session_type: str, payload: Any = None) -> dict:
        self.calls.append(("acquire", qid, session_type))
        if qid in self.store:
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

    async def settle_alchemy(
        self, qid: str, message_id: str, settlement_kind: str, session_view: Any = None
    ) -> bool:
        self.calls.append(("settle_alchemy", qid, message_id, settlement_kind))
        key = (qid, str(message_id), settlement_kind)
        if self.settle_always_false or key in self.idem:
            return False
        self.idem.add(key)
        return True


class FakeWallet:
    """gem_wallet 接口契约 fake（兄弟路 B：decompose/decompose_rate/gem_base_value/grant_gem）。

    decompose 返回由构造参数定制（成功两段式 / 标准版拒绝 / 回收减半），缺省成功样例：
    `{ok, materials:[{item_id,name,count}], gem, standard}`。
    """

    def __init__(
        self,
        result: Optional[dict] = None,
        rate: float = 0.6,
    ) -> None:
        self.result = result
        self.rate = rate
        self.calls: list = []
        self.base_values: Dict[str, int] = {
            "common": 1, "uncommon": 3, "rare": 8, "legendary": 20,  # 拍板① 平铺基础值
        }

    def decompose(
        self, ctx: MappingAny, item_def: dict, count: int = 1, *, job_tier_index: Any = None
    ) -> dict:
        self.calls.append(("decompose", item_def.get("id"), count, job_tier_index))
        if self.result is not None:
            return self.result
        return {
            "ok": True,
            "materials": [{"item_id": "fire_crystal", "name": "火晶石", "count": 2}],
            "gem": 3,                    # 精良基础值 3（拍板① 不乘回收率）
            "standard": False,
            "message": "",
        }

    def decompose_rate(self, job_tier_index: Any) -> float:
        return self.rate

    def gem_base_value(self, quality: str) -> int:
        return self.base_values.get(quality, 0)

    def grant_gem(self, ctx: Any, amount: int) -> dict:
        return {"ok": True, "granted": amount}


class AsyncWallet:
    """async decompose 变体（兄弟路引擎若为 async 亦兼容，壳层 inspect.isawaitable 防御）。

    独立类非 FakeWallet 子类（鸭子类型零继承——async 覆写 sync 会被 mypy 标记不兼容覆写）。
    """

    def __init__(self) -> None:
        self.calls: list = []

    async def decompose(
        self, ctx: Any, item_def: dict, count: int = 1, *, job_tier_index: Any = None
    ) -> dict:
        self.calls.append(("decompose", item_def.get("id"), count, job_tier_index))
        return {
            "ok": True,
            "materials": [{"item_id": "fire_crystal", "name": "火晶石", "count": 2}],
            "gem": 3,
            "standard": False,
            "message": "",
        }

    def decompose_rate(self, job_tier_index: Any) -> float:
        return 0.6

    def gem_base_value(self, quality: str) -> int:
        return {"common": 1, "uncommon": 3, "rare": 8, "legendary": 20}.get(quality, 0)

    def grant_gem(self, ctx: Any, amount: int) -> dict:
        return {"ok": True, "granted": amount}


# MappingAny 别名（fake 方法签名宽容，测试零严格类型耦合）
MappingAny = Dict[str, Any]


def _snap(
    recipe_id: str = "rcp_flame",
    materials: Optional[list] = None,
    element_scores: Optional[dict] = None,
    **over: Any,
) -> dict:
    """调合会话快照（§7.1 形态：配方ID+材料链+连锁+刻度+特性+PP+步骤+version）。

    缺省材料链 = 月光草×1（quality=72 → 均值 72 → rare 史诗，M-05）；element_scores 达标
    火≥6（刻度达标不降级 QLT-10）。
    """
    snap: dict = {
        "recipe_id": recipe_id,
        "materials": materials if materials is not None else [
            {"item": "moon_grass", "count": 1, "quality": 72},
        ],
        "chain": {"segments": 1, "effect_level": 1},
        "element_scores": element_scores if element_scores is not None else {"fire": 6},
        "pool": {"normal": [], "gold": [], "awaken": []},
        "catalyst": None,
        "pp": {"used": 0, "budget": 5},
        "step": "feed",
        "version": 3,
        "job_tier": "expert",
        "job_tier_index": 3,
    }
    snap.update(over)
    return snap


def _make_remove_item(ctx: Dict[str, Any]):
    """remove_item hook（SettleEngine 扣料 Q-S8：就地扣减 ctx 背包 dict）。"""

    def _ri(item_id: str, count: int) -> bool:
        cur = int(ctx.get("inventory", {}).get(item_id, 0))
        if cur < count:
            return False
        ctx["inventory"][item_id] = cur - count
        return True

    return _ri


def _make_add_item(ctx: Dict[str, Any]):
    """add_item hook（SettleEngine 产出入包 F-05⑦：就地累加 + 记录 _added 供断言）。"""

    def _ai(item_id: str, count: int, bound: bool = False, **kw: Any) -> bool:
        ctx.setdefault("inventory", {})
        ctx["inventory"][item_id] = int(ctx.get("inventory", {}).get(item_id, 0)) + count
        ctx.setdefault("_added", []).append(
            {"item_id": item_id, "count": count, "bound": bound, **kw}
        )
        return True

    return _ai


def make_ctx(**over: Any) -> dict:
    """全字段炼金终态 ctx（player 字段在 ctx 顶层 + remove_item/add_item hook 注入）。

    settings/session_mgr/wallet 可覆盖；message_id 缺省 None（保守不落幂等键路径）。
    """
    base: dict = {
        "qid": "u1",
        "proficiency": {"alchemy": _alchemy_node(3)},
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {"fire_crystal": 10, "moon_grass": 5, "flame_bomb": 1},
        "items": ITEMS,
        "traits": TRAITS,
        "recipe": RECIPES,
        "settings": SETTINGS,
        "session_mgr": FakeSessions(),
        "wallet": FakeWallet(),
        "message_id": None,
    }
    base["remove_item"] = _make_remove_item(base)
    base["add_item"] = _make_add_item(base)
    base.update(over)
    return base


def _open_alchemy(ctx: dict, payload: Optional[dict] = None, version: int = 3) -> None:
    """直接预置调合会话（acquire 等价行形态，避免走 /炼金 全链）。"""
    ctx["session_mgr"].store["u1"] = {
        "session_type": "alchemy",
        "payload": payload if payload is not None else _snap(),
        "version": version,
    }


# ---------------------------------------------------------------------------
# /确认：F-05 品质结算成功（M-05 品质 72·史诗）
# ---------------------------------------------------------------------------
async def test_confirm_success_quality_72_epic() -> None:
    """F-05/M-05 正例：/确认 → 「确认成功：火焰弹（品质 72·史诗）」；
    扣料+产出入包（F-05⑦⑧）+ 终态幂等键 settle:confirm（§10 铁律 3）。"""
    ctx = make_ctx(message_id="m1")
    _open_alchemy(ctx)
    out = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert "确认成功：火焰弹（品质 72·史诗）" in out
    assert "品质 72·史诗" in out
    # 扣料（moon_grass 5→4）+ 产出入包（flame_bomb 1→2，quality=rare 史诗）
    assert ctx["inventory"]["moon_grass"] == 4
    assert ctx["inventory"]["flame_bomb"] == 2
    added = ctx["_added"]
    assert added and added[0]["item_id"] == "flame_bomb"
    assert added[0]["quality"] == "rare"
    # 终态幂等 gate（§10 铁律 3 command="settle:confirm"）
    assert ("settle_alchemy", "u1", "m1", "confirm") in ctx["session_mgr"].calls


async def test_confirm_no_message_id_conservative() -> None:
    """保守路径：message_id 缺失 → 结算照常但**不落幂等键**（settle_alchemy 不被调用）。"""
    ctx = make_ctx(message_id=None)
    _open_alchemy(ctx)
    out = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert "确认成功" in out
    assert not [c for c in ctx["session_mgr"].calls if c[0] == "settle_alchemy"]


# ---------------------------------------------------------------------------
# /确认：GU-19 材料不足全拒差异
# ---------------------------------------------------------------------------
async def test_confirm_materials_insufficient_diff() -> None:
    """GU-19/FEED-10 负例：材料被移走（过期快照）→ 全拒 + 差异「缺 月光草×2」，零业务写。"""
    ctx = make_ctx(message_id="m1", inventory={"moon_grass": 0, "fire_crystal": 10})
    snap = _snap(materials=[{"item": "moon_grass", "count": 2, "quality": 72}])
    _open_alchemy(ctx, snap)
    out = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert "材料不足" in out
    assert "缺 月光草×2" in out
    assert ctx["inventory"]["moon_grass"] == 0      # 全拒零扣
    assert "flame_bomb" not in ctx["inventory"]     # 全拒零产出


# ---------------------------------------------------------------------------
# /确认：ATO-04 重复确认「已结算」幂等
# ---------------------------------------------------------------------------
async def test_confirm_repeat_settled_idempotent() -> None:
    """ATO-04/M-05 正例：重复确认 → fake settle 幂等（第二次 settle_alchemy=False）→「已结算」，
    零二次业务写。"""
    ctx = make_ctx(message_id="m1")
    _open_alchemy(ctx)
    out1 = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert "确认成功" in out1
    assert ctx["inventory"]["flame_bomb"] == 2
    out2 = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert out2 == "已结算"
    assert ctx["inventory"]["flame_bomb"] == 2      # 幂等零二次产出
    assert ctx["inventory"]["moon_grass"] == 4      # 幂等零二次扣料


async def test_confirm_already_settled_first_call() -> None:
    """ATO-04 负例：首次即已结算（settle 幂等 gate False）→ 「已结算」，零业务写。"""
    ctx = make_ctx(message_id="m1")
    ctx["session_mgr"].settle_always_false = True
    _open_alchemy(ctx)
    out = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert out == "已结算"
    assert ctx["inventory"]["moon_grass"] == 5
    assert ctx["inventory"]["flame_bomb"] == 1


# ---------------------------------------------------------------------------
# /确认：GU-17 无会话 / 非调合 / GU-10 战斗拦截
# ---------------------------------------------------------------------------
async def test_confirm_no_session_rejected() -> None:
    """GU-17 负例：无会话 /确认 → 「当前没有调合会话，先 /炼金 <配方> 开始」（L175）。"""
    ctx = make_ctx()
    out = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


async def test_confirm_non_alchemy_session_rejected() -> None:
    """GU-17 负例：活跃会话非调合类（battle，非战斗场景）→ 无会话模板（P-6 防御）。"""
    ctx = make_ctx()
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


async def test_confirm_battle_intercept() -> None:
    """GU-10/MUT-04 负例：战斗中 /确认 → 「战斗中使用 /即时调合 <配方>」（L295）。"""
    ctx = make_ctx(in_battle=True)
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert "战斗中使用 /即时调合 <配方>" in out


# ---------------------------------------------------------------------------
# /确认：INH-10/11 结算复核（TraitInherit.check_placement_conflict）
# ---------------------------------------------------------------------------
async def test_confirm_placement_conflict_rejected() -> None:
    """INH-10 负例：快照特性含互斥组冲突（同 group 两项）→ 结算复核拒绝，零业务写。"""
    traits = {
        "t_att": {"id": "t_att", "name": "攻击强化", "group": "attack", "repeatable": False},
        "t_pro": {"id": "t_pro", "name": "攻击精通", "group": "attack", "repeatable": False},
    }
    ctx = make_ctx(traits=traits)
    snap = _snap(traits=["t_att", "t_pro"])
    _open_alchemy(ctx, snap)
    out = await cmd_confirm(parse_command("/确认", whitelist=W), ctx)
    assert "结算校验" in out
    assert "冲突" in out
    assert ctx["inventory"]["moon_grass"] == 5      # 复核拒绝零扣料
    assert ctx["inventory"]["flame_bomb"] == 1      # 复核拒绝零产出


# ---------------------------------------------------------------------------
# /放弃：F-05 终态（材料不结算）
# ---------------------------------------------------------------------------
async def test_abandon_success() -> None:
    """F-05 正例：/放弃 → 「已放弃」；材料不结算（不扣不还，moon_grass 保持 5）；
    终态幂等键 settle:abandon（§10 铁律 3）。"""
    ctx = make_ctx(message_id="m1")
    _open_alchemy(ctx)
    out = await cmd_abandon(parse_command("/放弃", whitelist=W), ctx)
    assert out == "已放弃"
    assert ctx["inventory"]["moon_grass"] == 5      # 材料不结算（F-05）
    assert ("settle_alchemy", "u1", "m1", "abandon") in ctx["session_mgr"].calls


async def test_abandon_repeat_settled() -> None:
    """负例：重复放弃 → 幂等透传「已放弃」（already_settled 不双结算）。"""
    ctx = make_ctx(message_id="m1")
    _open_alchemy(ctx)
    out1 = await cmd_abandon(parse_command("/放弃", whitelist=W), ctx)
    assert out1 == "已放弃"
    out2 = await cmd_abandon(parse_command("/放弃", whitelist=W), ctx)
    assert out2 == "已放弃"


async def test_abandon_no_session_rejected() -> None:
    """GU-17 负例：无会话 /放弃 → 无会话模板。"""
    ctx = make_ctx()
    out = await cmd_abandon(parse_command("/放弃", whitelist=W), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


async def test_abandon_battle_intercept() -> None:
    """GU-10/MUT-04 负例：战斗中 /放弃 → 战斗拦截模板。"""
    ctx = make_ctx(in_battle=True)
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_abandon(parse_command("/放弃", whitelist=W), ctx)
    assert "战斗中使用 /即时调合 <配方>" in out


# ---------------------------------------------------------------------------
# /调合续：GU-18 恢复挂起(战斗)（§7.1 行7/8 + MUT-05）
# ---------------------------------------------------------------------------
async def test_resume_suspended_ok() -> None:
    """GU-18 正例：挂起(战斗) 调合会话 → 恢复渲染面板（行7：快照原样，特性/PP 不丢）。"""
    ctx = make_ctx()
    snap = _snap(
        materials=[{"item": "fire_crystal", "name": "火晶石", "count": 1,
                    "main_element": "fire", "elements": {"fire": 4}}],
        state="suspended",  # 【工程补白 S-1】挂起标记
    )
    _open_alchemy(ctx, snap)
    out = await cmd_resume(parse_command("/调合续", whitelist=W), ctx)
    assert "火焰弹（配方Lv5）" in out
    assert "火晶石×1" in out
    assert "材料：" in out


async def test_resume_active_session_rejected() -> None:
    """GU-18/MUT-05 负例：已有活跃（未挂起调合会话）→ 「已有一个调合会话进行中」（L177）。"""
    ctx = make_ctx()
    _open_alchemy(ctx)
    out = await cmd_resume(parse_command("/调合续", whitelist=W), ctx)
    assert "已有一个调合会话进行中" in out


async def test_resume_battle_session_rejected() -> None:
    """GU-18 负例：活跃会话为 battle（非调合，占用槽位）→ 已有一个调合会话进行中。"""
    ctx = make_ctx()
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_resume(parse_command("/调合续", whitelist=W), ctx)
    assert "已有一个调合会话进行中" in out


async def test_resume_no_session_rejected() -> None:
    """GU-18 负例：无挂起（无会话）→ 无会话模板。"""
    ctx = make_ctx()
    out = await cmd_resume(parse_command("/调合续", whitelist=W), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


# ---------------------------------------------------------------------------
# /分解：F-10/GEM-15 两段式消息（gem_wallet 鸭子类型消费）
# ---------------------------------------------------------------------------
async def test_decompose_success_two_segment() -> None:
    """F-10/M-10/GEM-15 正例：两段式消息 `✅ 火晶石×2 + 宝石×3（回收 60%）`——
    材料回收段 + 宝石段；宝石 = 精良平铺基础值 3（拍板① 不乘回收率）。"""
    ctx = make_ctx()
    ctx["wallet"] = FakeWallet(result={
        "ok": True,
        "materials": [{"item_id": "fire_crystal", "name": "火晶石", "count": 2}],
        "gem": 3,
        "standard": False,
        "message": "",
    }, rate=0.6)
    out = await cmd_decompose(parse_command("/分解 火晶石", whitelist=W), ctx)
    assert out == "✅ 火晶石×2 + 宝石×3（回收 60%）"
    assert "火晶石×2" in out and "宝石×3" in out


async def test_decompose_standard_rejected() -> None:
    """GU-32/GEM-14 负例：标准版默认不可分解 → 钱包拒绝消息透传（防商店套宝石漏洞）。"""
    ctx = make_ctx()
    ctx["wallet"] = FakeWallet(result={
        "ok": False,
        "reason": "standard_not_decomposable",
        "message": "标准版不可分解",
    })
    out = await cmd_decompose(parse_command("/分解 火晶石", whitelist=W), ctx)
    assert "标准版不可分解" in out


async def test_decompose_standard_diminish_half_recovery() -> None:
    """GU-32 回收减半（内容包可配备选）：透传钱包减半数值（材料×1/宝石×1/回收 30%）。"""
    ctx = make_ctx()
    ctx["wallet"] = FakeWallet(result={
        "ok": True,
        "materials": [{"item_id": "fire_crystal", "name": "火晶石", "count": 1}],
        "gem": 1,
        "standard": True,
        "message": "",
    }, rate=0.3)
    out = await cmd_decompose(parse_command("/分解 火晶石", whitelist=W), ctx)
    assert "火晶石×1" in out
    assert "宝石×1" in out
    assert "（回收 30%）" in out


async def test_decompose_item_not_found() -> None:
    """GU-33 负例：道具不存在 → 「❌ 道具不存在：xxx」。"""
    ctx = make_ctx()
    out = await cmd_decompose(parse_command("/分解 不存在的东西", whitelist=W), ctx)
    assert "道具不存在" in out
    assert out.startswith("❌")


async def test_decompose_missing_arg_tpl12() -> None:
    """负例：/分解 缺参 → TPL-12（指令不正确）。"""
    ctx = make_ctx()
    out = await cmd_decompose(parse_command("/分解", whitelist=W), ctx)
    assert "指令不正确" in out


async def test_decompose_star_quantity() -> None:
    """P-10/*N 数量正例：`/分解 火晶石*3` → count=3 传入钱包（壳层 _star_qty 兜底解析）。"""
    ctx = make_ctx()
    wallet = FakeWallet()
    ctx["wallet"] = wallet
    await cmd_decompose(parse_command("/分解 火晶石*3", whitelist=W), ctx)
    assert wallet.calls and wallet.calls[0][1] == "fire_crystal"
    assert wallet.calls[0][2] == 3


async def test_decompose_async_wallet_compatible() -> None:
    """鸭子类型防御：钱包 decompose 为 async（兄弟路引擎异步化）→ 壳层 await 兼容。"""
    ctx = make_ctx()
    wallet = AsyncWallet()
    ctx["wallet"] = wallet
    out = await cmd_decompose(parse_command("/分解 火晶石", whitelist=W), ctx)
    assert "宝石×3" in out
    assert wallet.calls and wallet.calls[0][1] == "fire_crystal"


# ---------------------------------------------------------------------------
# 装配：register_alchemy_commands 注册 4 终态指令 + ctx 注入 handler
# ---------------------------------------------------------------------------
async def test_register_alchemy_commands_terminal_four() -> None:
    """装配：注册 确认/放弃/调合续/分解 四条 CommandSpec（独立指令名，whitelisted）。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: make_ctx())
    for name in (CONFIRM_CMD, ABANDON_CMD, RESUME_CMD, DECOMPOSE_CMD):
        assert router.has(name)
        spec = router.get(name)
        assert spec is not None and spec.whitelisted


async def test_register_confirm_handler_injectable_ctx() -> None:
    """装配：/确认 handler 支持 k.get("ctx") 注入（async 处理器 await 执行，runner 口径）。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: {})
    spec = router.get(CONFIRM_CMD)
    assert spec is not None and spec.handler is not None
    ctx = make_ctx(message_id="m1")
    _open_alchemy(ctx)
    out = await spec.handler(parse_command("/确认", whitelist=W), ctx=ctx)
    assert "确认成功" in out
