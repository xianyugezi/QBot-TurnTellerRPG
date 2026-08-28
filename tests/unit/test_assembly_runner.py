"""tests/unit/test_assembly_runner.py — A-03 processing 驱动与发送出口（M7 RA-08~RA-10）。

依据：docs/细化/细化_M7_装配层契约.md 三、A-03（RA-08 完整链路 / RA-09 发送出口 /
RA-10 清理调度 + ADR-08 超时收口）+ 验收 TCA-03（装配冒烟端到端）/ TCA-04（幂等链路）/
TCA-05（per-player 队列）/ TCA-06（发送出口前缀）/ TCA-07（清理调度）。

覆盖：
  - 端到端：真 Router 注册 status 指令组 + FakeRepo → run_command("状态", event)
    返回回复串（含前缀注入 / 发送出口 Sender.delivered / 幂等键落库）
  - 幂等重发（同 message_id → 「该指令已处理，请勿重复发送」，业务零执行）
  - per-player 队列（同玩家并发 3 指令 FIFO 按序；异玩家互不阻塞）
  - 权限校验（GM 指令：非 GM 静默零出站；GM 走 GmResult 消息/审计分发）
  - 错误兜底（handler 抛异常 → 失败人话 + 事务回滚无孤儿键；deps 缺 router → TPL-12）
  - 清理调度（schedule_cleanup → repo.cleanup_idem_keys 被调用）
  - 队列超时（deps.queue_timeout 挂起消费者 → TIMEOUT_MESSAGE 兜底）

铁律：零 NoneBot import；确定性；FakeRepo 替代真实 DB（幂等键三元组内存态）。
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import Any

from qbot_rpg.assembly.context import AssemblyDeps, make_context
from qbot_rpg.assembly.runner import TIMEOUT_MESSAGE, run_command, schedule_cleanup
from qbot_rpg.commands.gm_commands import GmResult
from qbot_rpg.commands.processing import PerPlayerQueue
from qbot_rpg.commands.router import CommandSpec, Router
from qbot_rpg.commands.sender import Sender
from qbot_rpg.commands.status_commands import register_status_commands
from qbot_rpg.content.registry import Registry
from qbot_rpg.data import EquipmentSlot, ItemInstance, Player, PlayerAttributes


# =============================================================================
# 夹具（自含，避免依赖 tests 包）
# =============================================================================
def make_player(qid: str = "10001", **over: object) -> Player:
    """构造已注册 Player（覆盖 conftest make_player，自含）。"""
    attrs = PlayerAttributes(
        base={"hp": 100.0, "mp": 50.0, "str": 15.0},
        bonus={"flat": {"str": 5.0}, "pct": {"hp": 10.0}},
    )
    inv = (
        ItemInstance(item_id="potion", name="药水", count=2, quality="normal", bound=False),
        ItemInstance(item_id="iron_sword", name="铁剑", count=1, quality="rare",
                     bound=True, slot="weapon"),
    )
    base: dict = dict(
        qid=qid, name="阿伟", job_id="warrior", level=35, exp=1200, hp=220, mp=60,
        currencies={"gold": 350, "gem": 8},
        inventory=inv,
        equipment={"weapon": EquipmentSlot(item_id="iron_sword", name="铁剑", slot_level=3)},
        attributes=attrs,
        title_state={"current": "斩龙者"},
        persistent_state={
            "location": "town_center",
            "active_effects": {"poison": {"effect": "poison", "turns": 2, "refreshed": 0}},
            "quest_active": ["q1"],
            "quest_completed": ["q0"],
            "quest_daily": {"key": "2026-08-28", "completed": 1},
            "event_counts": {"battle:slime": 5},
            "checkin": {"last_key": "2026-08-27", "count": 3},
            "shortcuts": {"药水": "使用 药水"},
            "dialog_active": False,
            "personal_buys": {},
        },
        longline_counters={"battle_wins": 12},
        codex_state={},
    )
    base.update(over)
    return Player(**base)


class FakeTx:
    """事务替身：幂等查询/写入（内存态，同事务语义由 FakeRepo 承担）。"""

    def __init__(self, repo: "FakeRepo") -> None:
        self._repo = repo

    async def idem_exists(self, key: Any) -> bool:
        return self._repo.has(key)

    async def write_idem_key(self, key: Any) -> None:
        self._repo.put(key)


class FakeRepo:
    """鸭子类型 Repository：load_player + idem_claim + tx + cleanup_idem_keys。

    幂等键三元组 (message_id, group_id, player_qid) 内存态；无真实 DB。
    """

    def __init__(self, player: object = None) -> None:
        self._player = player
        self._keys: dict = {}
        self.cleanup_calls = 0

    async def load_player(self, qid: str):  # noqa: ANN001
        p = self._player
        if p is not None and p.qid == str(qid):  # type: ignore[attr-defined]
            return p
        return None

    async def idem_claim(self, key: Any) -> bool:
        return self.has(key)

    def has(self, key: Any) -> bool:
        return (key.message_id, key.group_id, key.player_qid) in self._keys

    def put(self, key: Any) -> None:
        self._keys[(key.message_id, key.group_id, key.player_qid)] = key.result_hash

    @contextlib.asynccontextmanager
    async def tx(self):
        yield FakeTx(self)

    async def cleanup_idem_keys(self, retention_days: float = 7.0, *, now: "str | None" = None):  # noqa: ANN001
        self.cleanup_calls += 1
        return 0


class StubGameWorld:
    """兄弟路 game_world 未实装方法全部 NotImplementedError（兜底不抛）。"""

    def get_map(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError

    def monster_pool(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError

    def get_npcs(self, map_id: str):  # noqa: ANN001
        raise NotImplementedError


class SessionMgrNone:
    def get_active(self, qid: str):  # noqa: ANN001
        return None


def make_registry() -> Registry:
    """内容注册表（job/effect/item/shop 表，name 冗余）。"""
    return Registry(
        pack_id="t", generation=1,
        tables={
            "job": {"warrior": SimpleNamespace(name="战士")},
            "effect": {"poison": SimpleNamespace(name="中毒")},
            "item": {"potion": SimpleNamespace(name="药水"),
                     "iron_sword": SimpleNamespace(name="铁剑")},
            "shop": {"shop1": SimpleNamespace(name="杂货店")},
        },
        names={"warrior": "战士", "poison": "中毒",
               "potion": "药水", "iron_sword": "铁剑", "shop1": "杂货店"},
        modules_raw={},
    )


def make_settings(**over: object) -> dict:
    s: dict = {
        "default_map": "newbie_village",
        "level_cap": 45,
        "shortcut_max": 20,
        "resource_pct": False,
        "exp_curve": lambda lv: 100 * lv,
        "conditional_rules": [],
        "attr_types": {"hp": "resource", "mp": "resource", "str": "combat"},
        "imprints": {"slot1": "印记A"},
        "stats": {"hp": {"base": 100}, "str": {"base": 10}},
    }
    s.update(over)
    return s


def make_event(**over: object) -> dict:
    e: dict = {
        "group_id": "123456",
        "user_id": "10001",
        "message": "/状态",
        "channel": "group",
        "message_id": "m-001",
    }
    e.update(over)
    return e


async def build_env(player: object = None, **over: object) -> dict:
    """构造完整装配环境：Router（status 组 + 可选扩展）/ PerPlayerQueue / deps。

    返回 dict：{deps, router, queue, repo, sender, event, ctx}。status 指令组的
    make_context 注入 = 测试预构建 ctx（真实 make_context 产物），与 runner 内部
    make_context 双份等价（同一玩家读档）。
    """
    repo = FakeRepo(player)
    queue = PerPlayerQueue(repo)  # type: ignore[arg-type]
    router = Router()
    sender = Sender()
    event = make_event(**{k: v for k, v in over.items() if k in (
        "group_id", "user_id", "qq_id", "message", "channel", "message_id",
        "group_name", "to", "per_channel")})
    deps = AssemblyDeps(repo=repo, game_world=StubGameWorld(),
                        registry=make_registry(), settings=make_settings(),
                        session_mgr=SessionMgrNone())
    deps.router = router  # type: ignore[attr-defined]
    deps.queue = queue
    deps.sender = sender  # type: ignore[attr-defined]
    # status 指令组的 make_context（register 契约：ParsedCommand → ctx dict，同步形态）
    ctx = await make_context(event, deps)
    register_status_commands(router, make_context=lambda parsed: ctx)
    return {"deps": deps, "router": router, "queue": queue, "repo": repo,
            "sender": sender, "event": event, "ctx": ctx}


# =============================================================================
# TCA-03 端到端：状态 → 回复串（含前缀注入 / 发送出口 / 幂等键落库）
# =============================================================================
async def test_end_to_end_status_reply() -> None:
    """TCA-03：run_command("状态", event) → 回复串；前缀首行注入；发送出口记录。"""
    env = await build_env(make_player())
    reply = await run_command(env["event"], env["deps"])
    # 回复串：前缀首行 + 状态面板
    assert reply.startswith("Lv35.阿伟 -斩龙者-"), f"前缀缺失: {reply!r}"
    assert "【等级】35" in reply and "阿伟" in reply
    # 发送出口（Sender 缺省收集 delivered）：分条记录 = 完整回复
    delivered = env["sender"].delivered
    assert delivered and delivered[0] == reply
    # 幂等键已落库（业务成功 → write_idem_key 同事务，IDEM-4）
    from qbot_rpg.storage.repository import IdemKey
    key = IdemKey(message_id=env["event"]["message_id"], group_id="123456", player_qid="10001",
                  command="状态")
    assert env["repo"].has(key), "业务成功后应落幂等键"


async def test_end_to_end_idempotent_replay() -> None:
    """TCA-04：同 message_id 重发 → 幂等返回「该指令已处理，请勿重复发送」，业务零执行。"""
    env = await build_env(make_player())
    r1 = await run_command(env["event"], env["deps"])
    assert "【等级】35" in r1
    # 重发同一事件（message_id 不变）
    r2 = await run_command(env["event"], env["deps"])
    assert r2 == "该指令已处理，请勿重复发送"
    # 发送出口只发了一次（幂等重放 send=False，IDEM-5 业务零执行零发送）
    assert len(env["sender"].delivered) == 1


# =============================================================================
# TCA-05 per-player 队列（同玩家 FIFO / 异玩家隔离）
# =============================================================================
async def test_per_player_queue_fifo_order() -> None:
    """TCA-05：同玩家并发 3 指令 → per-player 单消费者 FIFO 按序执行。"""
    env = await build_env(make_player())
    order: list = []
    for i, name in enumerate(("测试甲", "测试乙", "测试丙")):
        env["router"].register(CommandSpec(
            name, handler=lambda parsed, n=name, i=i: (order.append(i), f"{n}完成")[1]))  # type: ignore[func-returns-value]

    async def one(msg: str, mid: str) -> str:
        return await run_command(make_event(message=msg, message_id=mid), env["deps"])

    results = await asyncio.gather(
        one("测试甲", "m-a"), one("测试乙", "m-b"), one("测试丙", "m-c"),
    )
    assert order == [0, 1, 2], f"per-player FIFO 序被破坏: {order}"
    # 回复含前缀首行（注册玩家注入前缀）+ 各指令完成串
    for i, n in enumerate(("测试甲", "测试乙", "测试丙")):
        assert results[i].startswith("Lv35.阿伟 -斩龙者-"), results[i]
        assert results[i].endswith(f"{n}完成"), results[i]
    # 同玩家：队列排空（单消费者串行消费，无积压）
    assert env["queue"].qsize("10001") == 0


async def test_per_player_queue_parallel_players() -> None:
    """TCA-05：异玩家指令互不阻塞（各自队列/消费者独立，并行完成）。"""
    env = await build_env(make_player())
    env["router"].register(CommandSpec("测试", handler=lambda parsed: "测试完成"))

    async def one(qid: str, mid: str) -> str:
        ev = make_event(message="测试", message_id=mid, user_id=qid)
        return await run_command(ev, env["deps"])

    r = await asyncio.gather(one("10001", "m-1"), one("20002", "m-2"))
    # 10001 已注册 → 前缀注入；20002 未注册 → 直发正文
    assert "测试完成" in r[0] and r[0].startswith("Lv35.阿伟 -斩龙者-")
    assert r[1] == "测试完成"


# =============================================================================
# RA-10 权限校验：GM 指令（非 GM 静默 / GM 消息 + 审计）
# =============================================================================
async def test_gm_command_non_gm_silent() -> None:
    """RA-10：GM 指令（/重载）非 GM 发起 → 静默零出站零审计零幂等键。"""
    env = await build_env(make_player())
    env["router"].register(CommandSpec("重载", is_gm=True,
                                       handler=lambda parsed: GmResult(
                                           ok=True, message="重载完成")))
    reply = await run_command(make_event(message="/重载", message_id="m-gm1"), env["deps"])
    assert reply == ""
    assert env["sender"].delivered == []
    from qbot_rpg.storage.repository import IdemKey
    assert not env["repo"].has(IdemKey(message_id="m-gm1", group_id="123456",
                                       player_qid="10001", command="重载"))


async def test_gm_command_gm_dispatch() -> None:
    """RA-10：GM 指令有权限 → GmResult 消息分发 + 审计接线（audit_store 收到记录）。"""
    from qbot_rpg.commands.gm_commands import record_audit

    env = await build_env(make_player())
    audit_store: list = []
    env["deps"].permission_store = SimpleNamespace(is_gm=lambda qid: True)
    env["deps"].audit_store = audit_store

    def gm_handler(parsed, *a, **k):
        # 模拟 handle_gm_command 的审计行为：record_audit 写 ctx["audit_store"]
        # （ctx 由 runner 注入 audit_store/permission_store，验证装配层接线）
        record_audit(k["ctx"], {"command": "重载", "result": "success",
                                "qq": str(k["ctx"].get("qq_id"))})
        return GmResult(ok=True, message="重载完成",
                        audit={"command": "重载", "result": "success"})

    env["router"].register(CommandSpec("重载", is_gm=True, handler=gm_handler))
    reply = await run_command(make_event(message="/重载", message_id="m-gm2"), env["deps"])
    assert "重载完成" in reply and reply.startswith("Lv35.阿伟 -斩龙者-")
    assert env["sender"].delivered == [reply]
    # 审计：runner 注入 audit_store → handle_gm_command 同款 record_audit 落库
    assert len(audit_store) == 1 and audit_store[0]["command"] == "重载"
    assert audit_store[0]["qq"] == "10001"


async def test_gm_silent_success_no_reply() -> None:
    """RA-10：GM 静默执行成功（message=None）→ 不回显（send=False）。"""
    env = await build_env(make_player())
    env["deps"].permission_store = SimpleNamespace(is_gm=lambda qid: True)
    env["router"].register(CommandSpec(
        "封禁", is_gm=True,
        handler=lambda parsed: GmResult(ok=True, message=None, audit={"command": "封禁"})))
    reply = await run_command(make_event(message="/封禁", message_id="m-gm3"), env["deps"])
    assert reply == ""
    assert env["sender"].delivered == []


# =============================================================================
# 错误兜底（RA-10：异常 → 失败人话 + 事务回滚；顶层异常 → TPL-12 + 日志）
# =============================================================================
async def test_handler_exception_rollback_no_orphan_key() -> None:
    """handler 抛异常 → 失败人话回复；事务回滚无孤儿幂等键（IDEM-6，可重试）。"""
    env = await build_env(make_player())

    def boom(parsed):  # noqa: ANN001
        raise RuntimeError("业务写失败")

    env["router"].register(CommandSpec("炸", handler=boom))
    reply = await run_command(make_event(message="炸", message_id="m-boom"), env["deps"])
    assert "指令处理失败（已回滚，可重试）" in reply
    # 无孤儿键：同 message_id 重发按全新处理（不幂等空吞）
    from qbot_rpg.storage.repository import IdemKey
    assert not env["repo"].has(IdemKey(message_id="m-boom", group_id="123456",
                                       player_qid="10001", command="炸"))


async def test_unexpected_error_tpl12_fallback() -> None:
    """顶层未预期异常（deps 缺 router）→ TPL-12 统一报错 + 日志，不裸崩。"""
    env = await build_env(make_player())
    deps = env["deps"]
    # 模拟装配缺口：router 未注入
    deps_router = SimpleNamespace(**{k: v for k, v in vars(deps).items()})
    del deps_router.router
    reply = await run_command(make_event(message="状态", message_id="m-tpl"), deps_router)
    assert reply.startswith("❌ 指令不正确：")


# =============================================================================
# ADR-08 PerPlayerQueue 超时（wait_for 包层：丢弃等待，幂等键兜底）
# =============================================================================
async def test_queue_timeout_drop_with_idem_fallback() -> None:
    """ADR-08：消费者挂起超时 → 返回 TIMEOUT_MESSAGE（背景消费者继续，幂等键兜底）。"""
    env = await build_env(make_player())
    env["deps"].queue_timeout = 0.01
    # 先入队一条慢指令占住该玩家消费者（挂起 10s）
    from qbot_rpg.commands.processing import QueueItem
    from qbot_rpg.storage.repository import IdemKey
    await env["queue"].enqueue(QueueItem(
        player_qid="10001",
        idem_key=IdemKey(message_id="m-slow", group_id="123456", player_qid="10001",
                         command="状态"),
        handler=lambda tx: asyncio.sleep(10),  # type: ignore[arg-type,return-value]
    ))
    # 第二条指令排队等消费者 → wait_for 超时 → 丢弃等待，返回超时文案
    reply = await run_command(make_event(message="状态", message_id="m-fast"), env["deps"])
    assert reply == TIMEOUT_MESSAGE
    # 清理：取消消费者，避免悬挂（背景慢指令由 close 一并取消）
    await env["queue"].close()


# =============================================================================
# TCA-07 清理调度（schedule_cleanup → repo.cleanup_idem_keys）
# =============================================================================
async def test_schedule_cleanup_calls_repo() -> None:
    """TCA-07：schedule_cleanup 懒清理——启动即清理，周期续跑，可取消。"""
    env = await build_env(make_player())
    task = schedule_cleanup(env["repo"], interval=0.01)
    # 启动即清理一次（懒清理首拍）
    await asyncio.sleep(0)
    assert env["repo"].cleanup_calls >= 1
    # 周期续跑
    await asyncio.sleep(0.03)
    assert env["repo"].cleanup_calls >= 2
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# =============================================================================
# RA-09 发送出口（前缀注入 + CQ 转义 + 分片 4000）
# =============================================================================
async def test_sender_prefix_and_cq_escape() -> None:
    """RA-09：发送出口——前缀首行注入 + CQ 码转义（防注入）。"""
    env = await build_env(make_player())
    env["router"].register(CommandSpec("转义", handler=lambda parsed: "正文 [CQ:face,id=1] & 符号"))
    reply = await run_command(make_event(message="转义", message_id="m-cq"), env["deps"])
    # run_command 返回逻辑回复串（前缀 + 原文，未做传输层转义）
    assert "正文 [CQ:face,id=1] & 符号" in reply
    # 发送出口（Sender.send）：CQ 段级转义（& → &amp; → [ → &#91;）防伪造 CQ 段
    delivered = env["sender"].delivered
    assert delivered and "&#91;CQ:face,id=1&#93;" in delivered[0]
    assert "[CQ:face" not in delivered[0]
    assert "&amp;" in delivered[0]


async def test_sender_long_reply_segmented() -> None:
    """RA-09：超长回复 → 4000 字分片多条发送，不吞内容（Sender.segment_by_length）。"""
    env = await build_env(make_player())
    long_text = "长" * 8500
    env["router"].register(CommandSpec("长文", handler=lambda parsed: long_text))
    await run_command(make_event(message="长文", message_id="m-long"), env["deps"])
    delivered = env["sender"].delivered
    assert len(delivered) >= 2, "超长应分多条"
    joined = "".join(delivered)
    # 前缀在首条首行；正文完整（去前缀后拼接 == 原文）
    assert joined.startswith("Lv35.阿伟 -斩龙者-\n")
    body = joined.split("\n", 1)[1]
    assert body == long_text, "分片不吞内容"
    for seg in delivered:
        assert len(seg) <= 4000, "单条不超 4000 字上限"