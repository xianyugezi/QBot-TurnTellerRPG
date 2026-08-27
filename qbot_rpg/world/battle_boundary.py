"""战斗世界边界逻辑层（M2 怪物体系 · C2 路：细化_1g4 世界边界）。

依据：细化_1g4_战斗世界边界.md（权威契约 v1.1：LOST×6 / HR×5 / DEATH×8 / RACE×6 /
TIME×7 规则 + 字段 F-01~F-08 + 裁定 J-01~J-06 + 验收 TC-01~17；判定链见 §1.1/§2.1/
§3.1/§4.1）+ docs/m2_shared_contract.md 第七节（1g4 世界边界：lost_pending 快照扩展
形态 / 脱战回血事务要求 / death_penalty 配置段 F-01~F-04 / 跨群锁 wild_lock 形态 /
校验器要求）+ 第八节铁律。

职责（本路范围）：**逻辑层纯函数 + 数据结构 + death_penalty 配置解析 + 接口预留**。
五主题各一块：
  ① 怪物丢失（LOST-01~06）：lost_pending 快照扩展构造/形态校验 + 判定链纯函数
     （目标是否仍在场 → 丢失挂起 → 有刷新等刷新/无刷新按退出；时段边界 LOST-06）
  ② 脱战回血（HR-01~05）：三事件源（解除锁定/离开地图/战斗失败）→ HP 回满 + 锁释放
     判定；副本 BOSS 不恢复（J-01）、木桩豁免（HR-04）；原子事务接口签名预留（HR-05）
  ③ 死亡惩罚（DEATH-01~08）：death_penalty 配置 schema 解析（F-01~F-04）+ 结算链纯
     函数（货币/经验/物品扣除 + 绑定免疫 + 虚弱施加 + 复活点 BFS 最近安全区）
  ④ 跨群竞争（RACE-01~06）：wild_lock 锁数据结构（F-07）+ 先到先得判定 + CAS 语义
     接口预留 + 会话互斥提示判定（RACE-03/04）
  ⑤ 战斗时间线（TIME-01~07）：无超时断言 + 僵尸回收判定 + 退出结算幂等接口预留

**不做完整接线**（接口预留点全带 NotImplementedError + docstring，接线 TODO）：
  - 战斗会话挂接（BattleSnapshot.lost_pending 读写、丢失判定挂到指令流）→ M4 指令路由
  - 刷怪/刷新判定（spawn 行存在/可刷新/补刷）→ M3 spawn（2a1b R17/R23）
  - 存储事务（回血+解锁 CAS 写、锁写入、30 天回收扫描）→ M4/4a（TX-3/IDEM/RC）
    ⚠️ **例外：退出结算幂等入口 `settle_exit_idempotent` 已按 IDEM-8 实装**（M6 批2·路A，
    真实事务结算 + 写幂等键；见函数 docstring 工程补白——TIME-06 接口预留即带 repository）
  - 内容包 settings 校验接线 → content/validator.py `_check_settings_1g4`（本模块不含校验器）

铁律：纯逻辑零 IO（无真实数据库写——事务接口仅签名 + docstring 说明）；平台无关零
NoneBot import（细化_3a R1）；不拼用户文案（R4：返回约定值/抛领域异常，由壳层翻译）；
随机一律走注入 rng（铁律 6，可复现）；概率/比例输出一律小数 fraction（铁律 5）；
文件头标注「依据：细化_1g4」（铁律 1）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from qbot_rpg.data.battle import BattleSnapshot
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import Player
from qbot_rpg.storage.repository import IdemKey

__all__ = [
    # ① 丢失（LOST）
    "TargetRef", "LostPending",
    "LOST_RESOLVE_NORMAL", "LOST_ENTER_PENDING", "LOST_WAIT_REFRESH", "LOST_RESPAWNED",
    "LOST_EXIT_NO_RESPAWN", "LOST_EXIT_PERIOD_END", "LOST_EXIT_BY_PLAYER",
    "build_lost_pending", "is_valid_lost_pending", "decide_lost",
    "apply_lost_pending", "clear_lost_pending",
    # ② 脱战回血（HR）
    "HEAL_SOURCE_UNLOCK", "HEAL_SOURCE_LEAVE_MAP", "HEAL_SOURCE_BATTLE_FAIL",
    "HEAL_SOURCE_KILL", "HEAL_SOURCES", "HealAndUnlock",
    "is_heal_exempt", "heal_instance_to_full", "decide_heal_and_unlock", "heal_and_unlock_tx",
    # ③ 死亡惩罚（DEATH）
    "CurrencyDrop", "ExpDropCfg", "ItemDropCfg", "DeathPenaltyConfig", "DeathSettlement",
    "DEFAULT_WEAK_DURATION_SEC", "DEFAULT_CURRENCY_IDS", "WEAK_UNTIL_KEY",
    "DEFAULT_RESPAWN_POINT",
    "settle_currency_drops", "settle_exp_drop", "settle_item_drops",
    "apply_weakness", "weak_remaining_sec", "is_weak",
    "find_nearest_respawn_point", "settle_death",
    # ④ 跨群竞争（RACE）
    "WildLock", "WILD_LOCK_PREFIX", "wild_lock_key", "LockAttempt",
    "try_acquire_lock", "acquire_wild_lock_tx", "release_wild_lock",
    "SessionMutexDecision", "session_mutex_decision",
    # ⑤ 战斗时间线（TIME）
    "ZOMBIE_RECYCLE_DAYS",
    "find_battle_timeout_keys", "assert_no_battle_timeout", "assert_turn_no_timeout",
    "should_zombie_recycle", "settle_exit_idempotent",
]

# =====================================================================================
# ① 怪物丢失（LOST-01~06）—— lost_pending 快照扩展（F-08）+ 判定链
# =====================================================================================

# 判定链输出（细化_1g4 §1.1；字符串常量 JSON 友好，不引入 enum 依赖）
LOST_RESOLVE_NORMAL = "resolve_normal"          # ① 目标仍在场 → 正常结算本回合（回 1g1a 主循环）
LOST_ENTER_PENDING = "enter_lost_pending"       # ② 目标不在场 → 提示「怪物丢失」+ 写入 lost_pending（F-08）
LOST_WAIT_REFRESH = "wait_refresh"              # ③ 有刷新行未到刷新时刻 → 继续挂起（无时限 LOST-01）
LOST_RESPAWNED = "respawned_continue"           # ③ 目标已刷新 → 新实例满血 + 「战斗继续」（LOST-03/J-03）
LOST_EXIT_NO_RESPAWN = "exit_no_respawn"        # ④ 无刷新行（spawn 删除/出没条件不满足）→ 按退出结算（LOST-04/05）
LOST_EXIT_PERIOD_END = "exit_period_end"        # LOST-06 战斗中时段结束 → 提示「对方逃跑了」→ 按退出结算
LOST_EXIT_BY_PLAYER = "exit_by_player"          # 玩家主动 /逃跑 /放弃 → 按退出结算（LOST-05）


@dataclass(frozen=True)
class TargetRef:
    """目标实例引用（F-08 / [4a·SCHEMA-5]：id 为主键 + name 冗余显示，热重载改名不悬空）。"""

    id: str
    name: str

    def to_dict(self) -> Dict[str, str]:
        return {"id": self.id, "name": self.name}

    @classmethod
    def from_dict(cls, d: object) -> "TargetRef":
        m = d if isinstance(d, Mapping) else {}
        return cls(id=str(m.get("id", "")), name=str(m.get("name", "") or m.get("id", "")))


@dataclass(frozen=True)
class LostPending:
    """丢失挂起子态（F-08 / 细化_1g4 §6.2）：`battle_snapshot.lost_pending`。"""

    target_ref: TargetRef
    map_id: str
    pending_since: int  # epoch 秒（挂起起始时间）

    def to_dict(self) -> Dict[str, object]:
        return {"target_ref": self.target_ref.to_dict(), "map_id": self.map_id,
                "pending_since": self.pending_since}

    @classmethod
    def from_dict(cls, d: object) -> "LostPending":
        m = d if isinstance(d, Mapping) else {}
        return cls(target_ref=TargetRef.from_dict(m.get("target_ref")),
                   map_id=str(m.get("map_id", "")),
                   pending_since=int(m.get("pending_since", 0) or 0))


def build_lost_pending(target_id: str, target_name: str, map_id: str,
                       pending_since: int) -> Dict[str, object]:
    """构造 F-08 lost_pending 快照扩展 dict（供 BattleSnapshot.lost_pending 直接存 JSON）。

    语义（LOST-02）：目标被他人击败 → 玩家操作时提示「怪物丢失」→ 会话进入丢失挂起
    子态；快照只持目标引用（id+name 冗余），不持实例对象（实例由世界层管理，1g4 §1.1）。
    """
    return LostPending(TargetRef(target_id, target_name), map_id, pending_since).to_dict()


def is_valid_lost_pending(d: object) -> bool:
    """F-08 形态校验：target_ref.id 为必填非空字符串；map_id 字符串；pending_since 数值。"""
    m = d if isinstance(d, Mapping) else {}
    tr = m.get("target_ref")
    if not isinstance(tr, Mapping):
        return False
    if not isinstance(tr.get("id"), str) or not tr["id"]:
        return False
    if not isinstance(m.get("map_id"), str):
        return False
    return isinstance(m.get("pending_since"), (int, float)) and not isinstance(m.get("pending_since"), bool)


def decide_lost(
    *,
    target_present: bool,
    has_pending: bool,
    spawn_row_exists: bool,
    can_respawn: bool,
    refreshed: bool,
    period_ended: bool = False,
    player_exited: bool = False,
) -> str:
    """丢失判定链纯函数（细化_1g4 §1.1 / LOST-01~06）。

    输入语义：
      - target_present   目标实例是否仍在场（LOST-02 惰性查询结果；懒计算对齐 [2a1b·R19]）
      - has_pending      battle_snapshot.lost_pending 是否已写入（F-08）
      - spawn_row_exists 当前 spawn 表是否仍有该怪行（[2a1b·R23]；热重载删行=配置变更 LOST-04）
      - can_respawn      刷新条件满足（未达 count 上限 / 出没条件满足，[2a1b·R17/R23]）
      - refreshed        目标实例已刷新补位（新实例满血，J-03 目标替换）
      - period_ended     战斗中出没时段已结束（LOST-06 / 框架 L322「对方逃跑了」）
      - player_exited    玩家主动 /逃跑 或放弃（LOST-05 按退出结算）

    判定链（与 §1.1 一一对应）：
      player_exited                     → LOST_EXIT_BY_PLAYER（按退出结算）
      period_ended                      → LOST_EXIT_PERIOD_END（LOST-06 按退出结算）
      挂起中（has_pending）：
        refreshed / target_present      → LOST_RESPAWNED（LOST-03/J-03：新实例满血、玩家侧保留）
        spawn_row_exists and can_respawn→ LOST_WAIT_REFRESH（等刷新，无时限 LOST-01）
        否则                            → LOST_EXIT_NO_RESPAWN（LOST-04/05 按退出）
      未挂起：
        target_present                  → LOST_RESOLVE_NORMAL（正常结算本回合）
        否则                            → LOST_ENTER_PENDING（提示丢失 + 写入 lost_pending）
    """
    if player_exited:
        return LOST_EXIT_BY_PLAYER
    if period_ended:
        return LOST_EXIT_PERIOD_END
    if has_pending:
        if refreshed or target_present:  # 挂起后目标重新在场 = 已补位（防漏传 refreshed 标志）
            return LOST_RESPAWNED
        if spawn_row_exists and can_respawn:
            return LOST_WAIT_REFRESH
        return LOST_EXIT_NO_RESPAWN
    if target_present:
        return LOST_RESOLVE_NORMAL
    return LOST_ENTER_PENDING


def apply_lost_pending(snapshot: BattleSnapshot, lost_pending: Dict[str, object]) -> BattleSnapshot:
    """写入丢失挂起子态（LOST-02）：返回替换 lost_pending 后的新快照（frozen，replace）。"""
    return replace(snapshot, lost_pending=dict(lost_pending))


def clear_lost_pending(snapshot: BattleSnapshot) -> BattleSnapshot:
    """清除丢失挂起（LOST-03 刷新后续战 / LOST-05 按退出结算 / TIME-05 回收时）。"""
    return replace(snapshot, lost_pending=None)


# =====================================================================================
# ② 脱战回血（HR-01~05）—— 三事件源 → HP 回满 + 锁释放
# =====================================================================================

# 脱战事件源三件套（HR-01 / 细化_1g4 §2.1 事件源清单）
HEAL_SOURCE_UNLOCK = "unlock"        # 解除锁定（持有者放弃/被夺/释放；含 30 天回收 TIME-05）
HEAL_SOURCE_LEAVE_MAP = "leave_map"  # 离开地图（实例转移/移除；野图场景，副本换区不在此列 HR-03）
HEAL_SOURCE_BATTLE_FAIL = "battle_fail"  # 战斗失败（持有者败北/逃跑/丢失按退出 LOST-04/05）
HEAL_SOURCES: Tuple[str, ...] = (
    HEAL_SOURCE_UNLOCK, HEAL_SOURCE_LEAVE_MAP, HEAL_SOURCE_BATTLE_FAIL,
)
# 战斗胜利（玩家侧目标被击杀）→ 实例死亡进入刷新流程（[2a1b·R23]），**非脱战回血**
HEAL_SOURCE_KILL = "kill"


@dataclass(frozen=True)
class HealAndUnlock:
    """脱战回血判定结果（HR-01/HR-05 前置纯判定）。"""

    heal: bool           # 是否 HP 回满
    release_lock: bool   # 是否释放野图实例锁


def is_heal_exempt(heal_source: str, *, is_dungeon_boss: bool, is_dummy: bool) -> bool:
    """脱战回血适用边界（HR-03 J-01 / HR-04 / HR 边界）：

      - 非三事件源（如战斗胜利 kill）→ 豁免（击杀走刷新流程，回血 ≠ 重生，§七 联动）
      - 副本内 BOSS（J-01 裁决）→ 不恢复（换区=阶段切换残血保留，归 2a3 R19/R30）
      - 训练木桩（HR-04，怪物定稿 L372）→ 豁免（不在地图内、不适用锁定/丢失/回血）
    """
    if heal_source not in HEAL_SOURCES:
        return True
    if is_dungeon_boss:
        return True
    if is_dummy:
        return True
    return False


def heal_instance_to_full(instance: Mapping[str, object]) -> Dict[str, object]:
    """脱战回血：HP 回满（HR-01；纯函数，返回新 dict，不改入参）。

    世界实例 dict 形态（M3 实装为准，此处防御读取）：顶层 `hp`/`max_hp`，或八段
    `stats.hp`（max_hp 缺省 = stats.hp）。实例被击杀走刷新流程，不调用本函数。
    """
    out = dict(instance)
    stats = instance.get("stats")
    max_hp = instance.get("max_hp")
    if not isinstance(max_hp, (int, float)) or isinstance(max_hp, bool):
        if isinstance(stats, Mapping):
            shp = stats.get("hp")
            if isinstance(shp, (int, float)) and not isinstance(shp, bool):
                max_hp = shp
    if isinstance(max_hp, (int, float)) and not isinstance(max_hp, bool):
        out["hp"] = max_hp
    return out


def decide_heal_and_unlock(heal_source: str, *, is_dungeon_boss: bool, is_dummy: bool) -> HealAndUnlock:
    """脱战回血 + 锁释放判定（HR-01/HR-02/HR-05 前置纯判定）。

    三事件源 → heal=True + release_lock=True；边界豁免（副本 BOSS J-01 / 木桩 HR-04 /
    非三事件源）→ 不触发回血（锁处理随各场景语义，木桩无锁 HR-04）。
    注意（HR-05）：heal + release_lock 的**落地**必须在同一世界状态事务内（原子写），
    见 heal_and_unlock_tx；本函数只做纯判定，不写任何状态。
    """
    exempt = is_heal_exempt(heal_source, is_dungeon_boss=is_dungeon_boss, is_dummy=is_dummy)
    if exempt:
        return HealAndUnlock(heal=False, release_lock=not is_dummy)  # 木桩本就无锁（HR-04）
    return HealAndUnlock(heal=True, release_lock=True)


async def heal_and_unlock_tx(
    monster_key: str,
    heal_source: str,
    *,
    world_state: object,
    repository: object,
    expected_versions: Mapping[str, int],
    now: str = "",
) -> bool:
    """接口预留（HR-05 / 4a TX-3）：回血 + 解锁 = 世界状态**原子写**（CAS）。

    语义：脱战判定、锁释放、HP 回满三步在同一事务内提交；挑战者在回血完成前抢先出手
    → CAS 失败重读，按回满后的新对局处理（HR-02 抢怪者从头打，防竞争窗口，J-06）。
    前置判定见 decide_heal_and_unlock；本函数为 M4 接线存根（写 world_state 行：
    map_boss/<monster_key> 回满 + 删 wild_lock:<monster_key>）。

    接线 TODO（M4/4a）：
      1. repository.load_world_state() 读当前锁 + 实例 + 版本
      2. decide_heal_and_unlock 判 eligible
      3. repository.save_world_state(new_ws, expected_versions) 单事务写回（CAS）
      4. False → 重读按新对局处理
    """
    raise NotImplementedError("M4 实装：脱战回血+解锁原子事务（细化_4a TX-3 / 细化_1g4 HR-05）")


# =====================================================================================
# ③ 死亡惩罚与虚弱（DEATH-01~08）—— death_penalty 配置（F-01~F-04）+ 结算链
# =====================================================================================

DEFAULT_WEAK_DURATION_SEC: int = 60          # F-01 虚弱时长默认 60 秒【框架 L285】
DEFAULT_CURRENCY_IDS: Tuple[str, ...] = ("coins", "diamond")  # 默认模板货币键空间（3h §5.1 / 框架 L1096-1097）
WEAK_UNTIL_KEY: str = "weak_until"           # 虚弱状态存放键（玩家 persistent_state，QQ 承载 DEATH-02）
DEFAULT_RESPAWN_POINT: str = "newbie_village"  # F-06 复活点缺省指向新手村（DEATH-07 / 框架 L291）


@dataclass(frozen=True)
class CurrencyDrop:
    """F-02 掉落货币条目 {currency, ratio}。ratio ∈ (0,1]（6.3 数值合法，硬拦）。"""

    currency: str
    ratio: float


@dataclass(frozen=True)
class ExpDropCfg:
    """F-03 掉落经验配置 {enabled, percent}。enabled=false 时 percent 惰性不校验（6.3）。"""

    enabled: bool = False
    percent: float = 0.0


@dataclass(frozen=True)
class ItemDropCfg:
    """F-04 掉落物品配置 {enabled, count}。count ≥ 1 整数；上限=背包普通物品数【工程补白】。"""

    enabled: bool = False
    count: int = 1


@dataclass(frozen=True)
class DeathPenaltyConfig:
    """settings.death_penalty 段（F-01~F-04 / 细化_1g4 §6.1）。默认=无惩罚（DEATH-01）。"""

    weak_duration_sec: int = DEFAULT_WEAK_DURATION_SEC
    drop_currency: Tuple[CurrencyDrop, ...] = ()
    drop_exp: ExpDropCfg = field(default_factory=ExpDropCfg)
    drop_items: ItemDropCfg = field(default_factory=ItemDropCfg)

    @property
    def has_any_loss(self) -> bool:
        """是否有任一掉落项（DEATH-01：默认全关 = 无惩罚，仅复活+虚弱）。"""
        return bool(self.drop_currency) or self.drop_exp.enabled or self.drop_items.enabled

    @classmethod
    def from_settings(cls, settings: object) -> "DeathPenaltyConfig":
        """从 settings dict 解析（F-01~F-04；容错缺省，红拦归属 content 校验器）。

        惰性语义（6.3）：drop_exp.enabled=false 时 percent 不校验任意取值。
        类型不合法字段回退默认值（运行期兜底不炸，越界/引用问题由校验器硬拦）。
        """
        dp = settings.get("death_penalty") if isinstance(settings, Mapping) else None
        if not isinstance(dp, Mapping):
            return cls()
        w = dp.get("weak_duration_sec")
        weak = w if isinstance(w, int) and not isinstance(w, bool) and w >= 0 else DEFAULT_WEAK_DURATION_SEC
        drops: Tuple[CurrencyDrop, ...] = ()
        raw_cur = dp.get("drop_currency")
        if isinstance(raw_cur, list):
            items = []
            for e in raw_cur:
                if not isinstance(e, Mapping):
                    continue
                cur = e.get("currency")
                ratio = e.get("ratio")
                if isinstance(cur, str) and cur and isinstance(ratio, (int, float)) \
                        and not isinstance(ratio, bool):
                    items.append(CurrencyDrop(currency=cur, ratio=float(ratio)))
            drops = tuple(items)
        de = dp.get("drop_exp")
        exp = ExpDropCfg()
        if isinstance(de, Mapping):
            exp = ExpDropCfg(
                enabled=de.get("enabled") is True,
                percent=float(de.get("percent", 0.0))
                if isinstance(de.get("percent"), (int, float)) and not isinstance(de.get("percent"), bool)
                else 0.0,
            )
        di = dp.get("drop_items")
        items_cfg = ItemDropCfg()
        if isinstance(di, Mapping):
            cnt = di.get("count")
            items_cfg = ItemDropCfg(
                enabled=di.get("enabled") is True,
                count=cnt if isinstance(cnt, int) and not isinstance(cnt, bool) and cnt >= 1 else 1,
            )
        return cls(weak_duration_sec=weak, drop_currency=drops, drop_exp=exp, drop_items=items_cfg)


@dataclass(frozen=True)
class DeathSettlement:
    """野图死亡结算结果（细化_1g4 §3.1 ③④⑤ 输出；纯数据，落库归 M4/4a）。"""

    new_player: Player
    lost_currency: Dict[str, int]        # 货币 ID → 掉量（DEATH-03）
    lost_exp: int                        # 掉量（DEATH-04；不足 1 点不下掉）
    lost_items: Tuple[ItemInstance, ...]  # 掉出物品（DEATH-05；绑定/关键物品豁免）
    respawn_map: str                     # 复活点（DEATH-07 / F-06）
    weak_until: Optional[str]            # 虚弱截止 ISO-8601 UTC（DEATH-02 / F-01）


def settle_currency_drops(
    currencies: Mapping[str, int],
    drops: Sequence[CurrencyDrop],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """③ 货币掉落（DEATH-03 / F-02）：按 {currency:ratio} 逐项扣减。

    - 货币**不豁免**掉落（DEATH-06 仅物品豁免；若需某货币免掉，由内容包自行不配置）
    - 向下取整（int(cur * ratio)），至少不掉 0【工程补白】
    返回 (扣后余额, 各币种掉量)。纯函数，不改入参。
    """
    balance = dict(currencies)
    lost: Dict[str, int] = {}
    for d in drops:
        cur = balance.get(d.currency, 0)
        if cur <= 0:
            continue
        # M2 审查 P2-6：ratio>1 脏配置（绕过校验器）→ 防超扣负货币（防御性 clamp）
        amount = min(cur, int(cur * d.ratio))
        if amount <= 0:
            continue
        balance[d.currency] = cur - amount
        lost[d.currency] = lost.get(d.currency, 0) + amount
    return balance, lost


def settle_exp_drop(exp: int, percent: float, enabled: bool) -> Tuple[int, int]:
    """③ 经验掉落（DEATH-04 / F-03）：按 percent 扣当前等级经验；不足 1 点不下掉【工程补白】。

    percent 单位为百分比（F-03 0~100，如 5=5%，与 F-02 ratio 的 0~1 小数区分开）。
    enabled=False → 不掉（F-03 默认关）。返回 (扣后经验, 掉量)。
    """
    if not enabled or exp <= 0:
        return exp, 0
    amount = int(exp * percent / 100.0)
    if amount < 1:
        return exp, 0
    return max(0, exp - amount), amount


def settle_item_drops(
    inventory: Sequence[ItemInstance],
    count: int,
    enabled: bool,
    *,
    protected_item_ids: Sequence[str] = (),
    rng: Optional[random.Random] = None,
) -> Tuple[Tuple[ItemInstance, ...], Tuple[ItemInstance, ...]]:
    """③ 物品掉落（DEATH-05 / F-04）：随机选背包**普通物品** count 件移除。

    - 绑定物品豁免（DEATH-06：ItemInstance.bound 免疫一切掉落）
    - 关键物品保护（DEATH-05【工程补白】：settings/世界状态标记不可掉落 id 集，非绑定也豁免）
    - count 上限 = 背包普通物品数【工程补白】；count 语义=件数（条目级）
    返回 (剩余背包, 掉出物品)。纯函数；随机走注入 rng（铁律 6）。
    """
    if not enabled or count < 1:
        return tuple(inventory), ()
    rng = rng if rng is not None else random.Random()
    protected = frozenset(protected_item_ids)
    candidates = [it for it in inventory if not it.bound and it.item_id not in protected]
    if not candidates:
        return tuple(inventory), ()
    pick_n = min(count, len(candidates))
    picked = rng.sample(candidates, pick_n)
    picked_ids = {id(p) for p in picked}
    remaining = tuple(it for it in inventory if id(it) not in picked_ids)
    return remaining, tuple(picked)


def apply_weakness(player: Player, weak_duration_sec: int, now_iso: str) -> Player:
    """⑤ 施加虚弱（DEATH-02 / F-01）：玩家状态（QQ 承载，随全局世界），非战斗状态。

    落点 = Player.persistent_state[WEAK_UNTIL_KEY] = now + duration（ISO-8601 UTC）。
    weak_duration_sec=0 → 不虚弱（F-01 仅建议不拦截，语义由配置方自担）。纯函数（replace）。
    """
    if weak_duration_sec <= 0 or not now_iso:
        return player
    until = _add_iso_seconds(now_iso, weak_duration_sec)
    if until is None:
        return player
    ps = dict(player.persistent_state)
    ps[WEAK_UNTIL_KEY] = until
    return replace(player, persistent_state=ps)


def weak_remaining_sec(player: Player, now_iso: str) -> int:
    """虚弱剩余秒数（≤0 = 未虚弱）。供 TPL-1G4-04 带剩余秒数 / DEATH-02 禁入判定。"""
    raw = player.persistent_state.get(WEAK_UNTIL_KEY)
    if not isinstance(raw, str) or not raw:
        return 0
    try:
        until = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return 0
    delta = until - now
    if delta.total_seconds() <= 0:
        return 0
    return int(delta.total_seconds())


def is_weak(player: Player, now_iso: str) -> bool:
    """虚弱期间无法进入非安全区地图（DEATH-02 / TC-09）。"""
    return weak_remaining_sec(player, now_iso) > 0


def find_nearest_respawn_point(
    death_map_id: str,
    *,
    adjacency: Mapping[str, Iterable[str]],
    respawn_points: Mapping[str, str],
    safe_zones: Iterable[str],
    default: str = DEFAULT_RESPAWN_POINT,
) -> str:
    """⑦ 复活点（DEATH-07 / F-06）：死亡回**最近安全区**（按地图连通关系 BFS）。

    - respawn_points（F-06）：死亡地图 → 复活点指向；若命中直接用（含指向安全区）
    - 否则从死亡地图 BFS 最近连通的安全区（safe_zones，F-05）
    - 无连通路径 → 返回 default（新手村，框架 L291 默认）
    纯函数（图论 BFS，F-06「最近算法」【工程补白】）。
    """
    respawn_map = respawn_points.get(death_map_id)
    if respawn_map:
        return respawn_map
    if death_map_id in frozenset(safe_zones):
        return death_map_id
    # BFS 最近安全区
    visited = {death_map_id}
    frontier = [death_map_id]
    while frontier:
        nxt: list = []
        for m in frontier:
            for neighbor in adjacency.get(m, ()):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                if neighbor in frozenset(safe_zones):
                    return neighbor
                nxt.append(neighbor)
        frontier = nxt
    return default


def settle_death(
    player: Player,
    config: DeathPenaltyConfig,
    *,
    death_map_id: str,
    adjacency: Mapping[str, Iterable[str]],
    respawn_points: Mapping[str, str],
    safe_zones: Iterable[str],
    now_iso: str = "",
    rng: Optional[random.Random] = None,
    protected_item_ids: Sequence[str] = (),
) -> DeathSettlement:
    """野图死亡结算链（细化_1g4 §3.1 ③④⑤；纯函数编排，不落库）。

    ⚠️ 适用边界（DEATH-08）：本链仅野图（非副本）死亡；副本内死亡走【副本】§2.2
    （2a3 R26-R32）；PVP 击杀惩罚走 3.19 独立配置——界别判定由调用方先行。

    流程：③ 掉落结算（F-02/F-03/F-04；默认全关=无惩罚 DEATH-01）→ ④ 复活（最近安全区）
    → ⑤ 施加虚弱（F-01，默认 60 秒）。死亡 ≠ 战斗中断（[1g3·C-05]，无快照续玩）。
    落库/消息归 M4（结算幂等入口 settle_exit_idempotent / 4a IDEM）。
    """
    currencies, lost_currency = settle_currency_drops(player.currencies, config.drop_currency)
    exp, lost_exp = settle_exp_drop(player.exp, config.drop_exp.percent, config.drop_exp.enabled)
    inventory, lost_items = settle_item_drops(
        player.inventory, config.drop_items.count, config.drop_items.enabled,
        protected_item_ids=protected_item_ids, rng=rng,
    )
    respawn_map = find_nearest_respawn_point(
        death_map_id, adjacency=adjacency, respawn_points=respawn_points,
        safe_zones=safe_zones,
    )
    mid = replace(player, currencies=currencies, exp=exp, inventory=inventory)
    weak_until = _add_iso_seconds(now_iso, config.weak_duration_sec) if config.weak_duration_sec > 0 and now_iso else None
    new_player = apply_weakness(mid, config.weak_duration_sec, now_iso)
    return DeathSettlement(
        new_player=new_player,
        lost_currency=lost_currency,
        lost_exp=lost_exp,
        lost_items=lost_items,
        respawn_map=respawn_map,
        weak_until=weak_until,
    )


def _add_iso_seconds(iso: str, seconds: int) -> Optional[str]:
    """ISO-8601 UTC 字符串 + 秒 → ISO-8601 UTC（失败返回 None）。"""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return (dt + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# =====================================================================================
# ④ 跨群竞争与世界锁定（RACE-01~06）—— wild_lock（F-07）+ 先到先得 + 会话互斥
# =====================================================================================

WILD_LOCK_PREFIX: str = "wild_lock:"   # world_state 存储键前缀（F-07；key 全局，RACE-05）


@dataclass(frozen=True)
class WildLock:
    """野图实例锁定记录（F-07 / 细化_1g4 §6.2）：`world_state.wild_lock:<monster_key>`。

    RACE-02 先到先得：首个发起战斗者获得锁定（原子 CAS 写入）；锁未释放期间其他玩家
    对实例发起战斗 → 拒绝并提示「正在被玩家[X]挑战中」（TPL-1G4-03）；J-05 无锁定时长
    （自然终结=脱战三事件 HR-01 + 30 天回收 TIME-05）；J-06 挂起不占锁不阻塞。
    """

    holder_qid: str    # 锁定持有者 QQ 号（RACE-05：玩家状态 key=QQ 号）
    since: int         # 锁定起始 epoch 秒
    battle_ref: str    # 会话引用（如 "sess:<qid>"，TIME-06 幂等结算时关联）

    def to_dict(self) -> Dict[str, object]:
        return {"holder_qid": self.holder_qid, "since": self.since, "battle_ref": self.battle_ref}

    @classmethod
    def from_dict(cls, d: object) -> "WildLock":
        m = d if isinstance(d, Mapping) else {}
        return cls(holder_qid=str(m.get("holder_qid", "")),
                   since=int(m.get("since", 0) or 0),
                   battle_ref=str(m.get("battle_ref", "") or ""))


def wild_lock_key(monster_key: str) -> str:
    """世界锁存储键（RACE-05 key 纪律：世界状态 key=全局不区分群；monster_key=enemies id 主键）。"""
    return f"{WILD_LOCK_PREFIX}{monster_key}"


@dataclass(frozen=True)
class LockAttempt:
    """锁定尝试结果（RACE-02 先到先得）。"""

    acquired: bool
    lock: Optional[WildLock]  # acquired=True → 新锁；否则 → 现存锁（供 TPL-1G4-03 显示 holder）


def try_acquire_lock(
    current_lock: Optional[WildLock],
    holder_qid: str,
    since: int,
    battle_ref: str,
) -> LockAttempt:
    """④ 先到先得锁定判定（RACE-02 / F-07）：锁空闲 → 获得；被占 → 拒绝并暴露 holder。

    纯函数（CAS 语义接口预留见 acquire_wild_lock_tx）：当前锁为 None 即可获得；
    锁存在（未释放）→ 拒绝（含自身重复挑战场景由调用方结合会话互斥先行拦截）。
    J-06：新实例出生无主锁，任何挑战者先到先得，挂起持有者无优先权。
    """
    if current_lock is None:
        new_lock = WildLock(holder_qid=holder_qid, since=since, battle_ref=battle_ref)
        return LockAttempt(acquired=True, lock=new_lock)
    return LockAttempt(acquired=False, lock=current_lock)


async def acquire_wild_lock_tx(
    monster_key: str,
    holder_qid: str,
    battle_ref: str,
    *,
    repository: object,
    now: str = "",
) -> bool:
    """接口预留（RACE-02 / 4a TX-3）：锁记录**原子 CAS 写**（world_state.wild_lock:<key>）。

    语义：读锁 → 空闲则 CAS 写（期望版本比对，后写者失败重试）；脱战/胜利时随
    heal_and_unlock_tx 同事务清除（RACE-06 / HR-05）。J-06 并发写由 TX-3 CAS 兜底。

    接线 TODO（M4/4a）：
      1. repository.load_world_state() 读 wild_lock:<monster_key>（含 version）
      2. try_acquire_lock 判定
      3. acquired → repository.save_world_state({...锁写入...}, expected_versions) 单事务
      4. False → 拒绝提示 holder（TPL-1G4-03）
    """
    raise NotImplementedError("M4 实装：野图锁先到先得原子写（细化_4a TX-3 / 细化_1g4 RACE-02）")


def release_wild_lock(current_lock: Optional[WildLock]) -> Optional[WildLock]:
    """锁随脱离释放（RACE-06 / HR-01）：脱战三事件/胜利 → 回血+解锁（同事务 HR-05）。

    返回 None=已释放（写入侧置空 wild_lock:<key>）。纯函数。
    """
    return None


@dataclass(frozen=True)
class SessionMutexDecision:
    """会话互斥判定结果（RACE-03/04 + TIME-03）。"""

    blocked: bool
    reason: str                        # "" | "already_in_battle"
    active_origin_group: Optional[str]  # 活跃会话发起群（提示指向，RACE-04 归属=发起指令所在群）


def session_mutex_decision(
    active_session: Optional[Mapping[str, object]],
    command_kind: str,
) -> SessionMutexDecision:
    """③ 会话互斥提示判定（RACE-03/04 + TIME-03）：同一玩家多群并发。

    - 已有战斗会话（active_session.session_type == "battle"）+ 战斗类指令 → 拒绝
      「已在战斗中」并指向原会话所在群（RACE-04 提示归属=发起指令所在群，TPL-1G4-02）
    - 非战斗指令（/状态 /商店 /签到）不受限可并行（TIME-03 / 框架 L248）
    纯函数；会话互斥的实际挂起/恢复归 SessionManager（world/session.py，M1/M4）。
    """
    if active_session is None:
        return SessionMutexDecision(blocked=False, reason="",
                                     active_origin_group=None)
    is_battle = active_session.get("session_type") == "battle"
    if is_battle and command_kind == "battle":
        origin = active_session.get("origin_group")
        return SessionMutexDecision(
            blocked=True, reason="already_in_battle",
            active_origin_group=str(origin) if origin else None,
        )
    return SessionMutexDecision(blocked=False, reason="",
                                 active_origin_group=str(origin) if (origin := active_session.get("origin_group")) else None)


# =====================================================================================
# ⑤ 战斗时间线（TIME-01~07）—— 无超时 / 挂起 / 回收 / 幂等
# =====================================================================================

ZOMBIE_RECYCLE_DAYS: int = 30  # 僵尸战斗回收：30 天无操作（TIME-05 / 框架 L332）


def find_battle_timeout_keys(settings: Mapping[str, object]) -> Tuple[str, ...]:
    """扫描 settings 顶层键中的「战斗超时」类键（LOST-01/TIME-01：无超时设计）。

    命中规则：键名含 "timeout"（大小写不敏感）或 "超时"。返回命中键清单（供 load
    警告 + 忽略，细化_1g4 §6.3 校验器「超时类键不识别」；运行期不设任何计时器，J-04）。
    """
    hit: list = []
    for key in settings:
        k = str(key)
        if "timeout" in k.lower() or "超时" in k:
            hit.append(k)
    return tuple(hit)


def assert_no_battle_timeout(settings: Mapping[str, object]) -> Tuple[str, ...]:
    """① 无超时断言（LOST-01/TIME-01）：战斗会话不设任何回合/战斗超时计时器。

    与 find_battle_timeout_keys 同源：命中超时键 → load 警告 + 忽略（配置项不存在，
    编辑器/内容包均无此键，校验器不识别）。返回命中键清单（空=无超时配置，符合契约）。
    """
    return find_battle_timeout_keys(settings)


def assert_turn_no_timeout() -> None:
    """② 回合等待无超时断言（TIME-01/02）：空实现，声明语义。

    玩家回合无任何时限约束——不自动跳过/不代打/不踢出；无倒计时、无催促（TIME-07
    等待即静默，J-04）；固定玩家先手（框架 L114），玩家不操作 → 战斗自然静止在玩家
    回合，无 AI 空转/无后台自动过回合（TIME-02）。本函数为接线锚点（调用即校验无
    计时器接入），不执行任何动作。
    """


def should_zombie_recycle(
    last_active_at: str,
    now_iso: str,
    zombie_days: int = ZOMBIE_RECYCLE_DAYS,
) -> bool:
    """⑤ 僵尸回收判定（TIME-05 / TC-16）：30 天无操作 → 自动按退出结算。

    回收是**唯一**战斗会话生命周期终结器（J-04：无其他时限；锁定亦随之释放 HR-01）。
    纯函数（ISO-8601 UTC 比较）；解析失败返回 False（保守不误回收）。
    """
    try:
        last = datetime.fromisoformat(last_active_at.replace("Z", "+00:00"))
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return (now - last) >= timedelta(days=zombie_days)


# 结算幂等键 group_id 哨兵：settle_exit_idempotent 不接收指令 group_id，幂等键语义
# (player_qid, settlement_kind, message_id) 不含群（IDEM-8），缺失时以 "dm" 兜底
# （D2 §1.4 边界异常；与 commands/processing.py 的 DM_GROUP_SENTINEL 同值，附录 A：
# 装配层落地时统一在 ctx 构建处收敛一处定义）。
DM_GROUP_SENTINEL: str = "dm"


def _session_player_qid(session: object) -> str:
    """从会话对象/字典提取 player_qid（settle_exit_idempotent 幂等键要素之一）。"""
    if isinstance(session, Mapping):
        return str(session.get("player_qid", "") or "")
    return str(getattr(session, "player_qid", "") or "")


def _session_group_id(session: object) -> str:
    """结算幂等键的 group_id：优先会话携带的发起群（origin_group/context.group_id），
    缺失 → "dm" 哨兵兜底（D2 §1.4 边界异常）。"""
    if isinstance(session, Mapping):
        g = session.get("group_id") or session.get("origin_group")
        payload = session.get("payload")
    else:
        g = getattr(session, "group_id", None) or getattr(session, "origin_group", None)
        payload = getattr(session, "payload", None)
    if g:
        return str(g)
    if isinstance(payload, Mapping):
        g = payload.get("origin_group") or payload.get("group_id")
        if not g:
            ctx = payload.get("context")
            if isinstance(ctx, Mapping):
                g = ctx.get("group_id") or ctx.get("origin_group")
        if g:
            return str(g)
    return DM_GROUP_SENTINEL


async def settle_exit_idempotent(
    *,
    session: object,
    settlement_kind: str,
    message_id: str,
    repository: object,
) -> bool:
    """退出结算幂等入口——**唯一**退出结算接口（IDEM-8 实装 / TIME-06 / TC-04）。

    丢失按退出（LOST-05）/ 逃跑 / 僵尸回收（TIME-05）/ 主动放弃共用同一入口；以
    幂等键（player_qid + settlement_kind + message_id）防双扣/重复结算（4a IDEM-3 /
    框架 L343）。结算语义 = [1g1b·主迁移⑥] 逃跑结算：清空战斗内资源（连段清零，
    [1c1b·⑦]）、退出战场回地图/战前入口。

    ⚠️ 接线要求（IDEM-8 / 细化_4a TX-1 单指令单事务）：本函数自行开事务，调用方
    **不得**在已持有的 repo.tx() 内调用（connection.py _tx_owner 拒绝同任务嵌套 tx）。

    幂等键构成：
      - message_id        = 触发结算的 QQ 消息 id（IDEM-8 键要素）
      - player_qid        = session.player_qid（任务约束：session 为 object 取 qid）
      - settlement_kind   = 并入 command 字段，形如 "settle:{kind}"（IDEM-8；F-IDEM-04
        command 供审计/幂等重放识别）
      - group_id          = 会话携带的发起群；缺失 → "dm" 哨兵兜底（D2 §1.4 边界异常）
    注（schema 约束）：idempotency_keys 复合主键 = (message_id, group_id, player_qid)
    （schema.py L71-81），command **不参与去重**——同 message_id+group+qid 的不同结算
    类型视为已结算（先到者胜，不双结算），kind 仅落 command 列供审计；不同 message_id
    结算各自独立。

    流程（IDEM-3/4/6 语义）：
      ① repository.idem_claim 只读查重（快速路径）→ 命中 → 返回 False（已结算，不双结算）
      ② 未命中 → 单事务【结算 + write_idem_key】：
           tx.idem_exists 二次确认（权威判定，D2 §1.4）→ 命中 → False
           未命中 → tx.delete_session(player_qid)（清空战斗会话：连段/战斗资源随会话
                   删除即清零，退出战场回地图）+ tx.write_idem_key(key) → COMMIT
      ③ 事务内异常 → tx() 已 ROLLBACK（IDEM-6：无孤儿键、无半结算），异常向上抛
         （调用方按 POOL-4 转人话消息；结算失败未落键，可干净重试）
    返回 True = 本次完成结算（未结算过）；False = 已结算/无法建立幂等键（不双结算）。

    【工程补白 · 显式标注】
      - 本函数为 IDEM-8 / 【批5A】P1-1 明确要求的例外：TIME-06 接口预留即带 repository
        参数，实装为**真实事务结算入口**；battle_boundary 模块其余部分仍保持纯逻辑零 IO。
      - 「连段清零/资源清空」由删除战斗会话原子达成（会话即战斗内资源唯一载体），
        不另改玩家行——玩家侧战斗标记清理归装配层会话流程（批次6/7）。
    """
    qid = _session_player_qid(session)
    if not qid or not message_id or not settlement_kind:
        # 幂等键要素缺失 → 无法建立键，保守不结算（不写键不删会话，防误删战斗状态）
        return False
    key = IdemKey(
        message_id=message_id,
        group_id=_session_group_id(session),
        player_qid=qid,
        command=f"settle:{settlement_kind}",
    )
    # ① 入口只读查重（IDEM-3 只查不插；命中 → 已结算，不双结算）
    if await repository.idem_claim(key):  # type: ignore[attr-defined]
        return False
    # ② 单事务结算 + 写键（IDEM-4；异常由 tx() ROLLBACK 后向上抛，IDEM-6）
    async with repository.tx() as tx:  # type: ignore[attr-defined]
        if await tx.idem_exists(key):
            return False
        await tx.delete_session(qid)
        await tx.write_idem_key(key)
    return True
