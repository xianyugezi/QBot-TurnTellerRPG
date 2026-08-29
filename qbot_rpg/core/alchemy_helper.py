"""代工助手引擎（M8 批10-1·路B · qbot_rpg/core/alchemy_helper.py）——HelperEngine。

文件名：qbot_rpg/core/alchemy_helper.py
创建时间：2026-08-29
作者：Hermes 子agent-10B（并发同仓：仅新建本文件 + tests/unit/test_alchemy_helper.py；
      兄弟路 A 在写 core/alchemy_harvest.py（种植收获），只读勿探查）

功能描述：HelperEngine 承载第 2 层【代工助手】（定稿 §11.4 L458-465 / 指令契约 §21 / 细化_2c5c
  ASST-01~09）的全部业务逻辑——/代工 设定持续代采/代调（GU-62 炼金职业 ≥ 精通 → GU-63 消耗能源道具 →
  F-22 状态存档）、后台定时产出 tick（现实时间 × 周期 → 产出队列累计）、/收取 入包 + 队列
  清空（ASST-06）、助手等级提升（随累计产出 → 特性更多/采集品质更高，L464/ASST-07）。纯逻辑零 IO 零
  NoneBot；操作对象 = ctx 玩家表示（就地改写 player["helpers"] 助手状态 + 背包）；返回 dict 结果、
  拒绝场景 {ok: False, reason, message} 不抛异常。

依据：
  - docs/审查参考/炼金系统设计定稿.md §11.4 L458-465（代工助手：/雇工 设定「持续代采 X / 代调 Y」→
    消耗能源道具（糖果/馅饼类，L461）→ 后台定时产出 → 上线 /收取（L462）→ 助手等级提升 → 特性更多/
    采集品质更高（L464））；§10.5 L403（代工助手：状态+产出队列存档）。
  - docs/m8_contract_指令契约.md §21 /雇工（P-22/SEP-22：键值列表 `代采=材料*数量,代调=配方*数量` =
    定键、, 分隔、* 数量，规范 L49 原例语法；GU-62/63 前置守卫；F-22 流程；M-22 消息模板；收取用
    /收取 独立指令名）——2026-08-28 用户拍板指令名 /雇工 改名 /代工，本文件全用「代工」语义。
  - docs/细化/细化_2c5c_种植品评代工.md §三 ASST-01~09（精通解锁 ASST-01/持续委托 ASST-02/能源道具
    消耗 ASST-03/后台 tick 产出 ASST-04/队列上限 ASST-05/收取 ASST-06/助手等级成长 ASST-07/保底产物
    ASST-08/存档减负 ASST-09）+ §5.1/5.2 assistant JSON 样例与字段表 +
    §5.3 assistant_state 存档 schema。
  - 已落地：qbot_rpg/core/proficiency.py（ProficiencyEngine tier 判定，精通=档位索引 2）、
    qbot_rpg/core/alchemy_core.py（ALCHEMY_JOB_ID / PROFICIENT_TIER_INDEX）、qbot_rpg/core/
    synthesis.py（resolve_recipe 配方解析 + ctx hook 模式）。
  - 模式参考：core/synthesis.py（构造器配置注入 + 快照-回滚原子）、core/shop.py（ctx hook：
    ctx["items"]/["recipe"] 注册表、ctx["add_item"]/["remove_item"]/["count_item"] 钩子）、
    core/reward.py（ctx hook 消费 + 条目级失败跳过）。

【工程补白 · 显式标注】（定稿/细化未给口径处，本引擎最小必要推导，不得新增定稿外机制行为）：
  B-1  配置落点 = 构造器注入 settings（单源，确定性；指令壳注入 content 配置到构造器）。config 读取
       顺序 = settings["assistant"]（细化 profession.json assistant 段）→ settings["alchemy"]
       ["assistant"]（m8 契约 alchemy 设置段兜底）→ {}（全缺省兜底）。
  B-2  模块开关 assistant.enabled 缺省 True【工程补白：细化 ASST-01「默认关」指生活系统整体默认关，
       指令壳/内容包显式 enabled:false 可整模块关闭；引擎缺省放行以保证 /代工 开箱可用，与 m8 契约
       批10 路10B 排期一致】。
  B-3  能源道具 energy_items 缺省 ("糖果","馅饼")（L461 糖果/馅饼类，M-22 示例「糖果×1」）。
       消耗顺序 = 配置序逐项找第一项持有 ≥1；全部不足 → 拒「缺少能源道具」。能源道具按配置键直接
       count/remove（id 或名称均可，由内容包保证与背包一致）。
  B-4  周期 assistant.queue.tick_sec 缺省 1800 秒（30 分钟，ASST-04【工程补白】）；tick 按现实时间
       结算、离线累积：tick 数 = (now - last_tick_at) // tick_sec，余数顺延（不丢不重）。
  B-5  代采产出量 = 配置 count × 助手 gather_rate × tick 数（向下取整；
       ASST-04 基础量×助手系数×tick 数）；
       代调产出量 = 配方 output.count × 配置 count × tick 数（代调为固定保底合成产物 ASST-08，不乘
       系数、保底产物不缩放——工程补白）。
  B-6  队列形态 = player["helpers"][助手名]["queue"] dict {item_id: 数量}（任务书指定落点：
       player.helpers dict {助手名: {config, started_at, queue}}）；max_slots 缺省 3（ASST-05）：
       新任务物品种类
       并入现有队列后超 max_slots → 拒 queue_full（已产出项保留，收取腾位后可再委托）。
  B-7  助手等级（ASST-07/L464）：level = produced_total（终身累计产出）对照
       assistant.level_thresholds
       缺省 (0,100,300,700,1500)（镜像 proficiency 成长曲线口径）→ 1~5 级；加成 = (level-1) ×
       {trait_bonus_per_level 缺省 1（特性更多）, quality_bonus_per_level 缺省 5（采集品质更高）}。
       produced_total 存 helper config（终身累计，收取不清零 → 等级只升不降）。
  B-8  now 参数：tick 的 now / assign·collect 的 ctx["now"] 为时钟注入点（引擎唯一非纯点；注入优先，
       缺省读墙钟 time.time()——指令壳可传 bot 当前服务器时间，测试一律注入）。
  B-9  消息渲染按 M5 裁决零装饰 emoji（全仓 emoji_discipline 扫描）：M-22 模板「⚒/📦」emoji 降级
       纯文本——设定「小助手 开始代采 矿石*5（消耗 糖果×1）」、收取「收取：矿石×5」。
  B-10 收取入包 = ctx["add_item"] hook；某物项入包失败 → 留队列不伪装已发放（对齐 reward P1-1），
       其余项正常清空；入包失败项随返回 skipped 提示。
  B-11 代调配方解析 = synthesis.resolve_recipe（id → name → 序号）；assign 时配方不存在 →
       拒 recipe_not_found（校验器精神）；代调产出按 assign 时配方快照（对齐 L511 热重载语义）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；工程补白显式标注；不新增定稿外行为。
"""
from __future__ import annotations

import time
from typing import Any, Mapping, MutableMapping, Optional, Sequence

from qbot_rpg.core.alchemy_core import ALCHEMY_JOB_ID, PROFICIENT_TIER_INDEX
from qbot_rpg.core.proficiency import ProficiencyEngine
from qbot_rpg.core.synthesis import resolve_recipe

__all__ = [
    "DEFAULT_ENERGY_ITEMS",
    "DEFAULT_TICK_SEC",
    "DEFAULT_QUEUE_MAX_SLOTS",
    "DEFAULT_LEVEL_THRESHOLDS",
    "DEFAULT_TRAIT_BONUS_PER_LEVEL",
    "DEFAULT_QUALITY_BONUS_PER_LEVEL",
    "parse_task_spec",
    "HelperEngine",
]

# ---------------------------------------------------------------------------
# 缺省默认值（L461 能源道具 / ASST-04 tick 周期 / ASST-05 队列上限 / ASST-07 等级成长）
# ---------------------------------------------------------------------------
DEFAULT_ENERGY_ITEMS: Sequence[str] = ("糖果", "馅饼")
DEFAULT_TICK_SEC: int = 1800
DEFAULT_QUEUE_MAX_SLOTS: int = 3
DEFAULT_LEVEL_THRESHOLDS: Sequence[int] = (0, 100, 300, 700, 1500)
DEFAULT_TRAIT_BONUS_PER_LEVEL: int = 1
DEFAULT_QUALITY_BONUS_PER_LEVEL: int = 5

# 键值列表键名（SEP-22：= 定键；中文原例 代采/代调 + 解析层别名 gather/craft）
_TASK_KEYS_CN: Mapping[str, str] = {"代采": "gather", "代调": "craft"}


def _as_int(value: Any) -> Optional[int]:
    """int 归一（bool 除外）；非 int/bool/可转数字串 → None（对齐 synthesis._as_int）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def parse_task_spec(spec: Any) -> dict:
    """键值列表解析（P-22/SEP-22：= 定键、, 分隔、* 数量，规范 L49 原例语法）。

    入参：spec —— '代采=矿石*5,代调=药剂*2'（或 None/空串 → 无任务）。
    出参：{ok, raw, gather?, craft?}；gather/craft = {target, count}（count 缺省 1）；
      非法段/未知键/重复键/非正整数量 → {ok: False, reason, message}。
    """
    if spec is None:
        return {"ok": True, "raw": spec}
    if not isinstance(spec, str):
        return {"ok": False, "reason": "invalid_spec", "message": "任务格式非法"}
    text = spec.strip()
    out: dict = {"ok": True, "raw": spec}
    seen: set = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, rest = part.partition("=")
        if not sep or not rest:
            return {"ok": False, "reason": "invalid_spec", "message": f"无法解析的任务段：{part}"}
        key = key.strip()
        if key in _TASK_KEYS_CN:
            field = _TASK_KEYS_CN[key]
        elif key in ("gather", "craft"):
            field = key
        else:
            return {"ok": False, "reason": "invalid_spec", "message": f"未知任务键：{key}"}
        if field in seen:
            return {"ok": False, "reason": "invalid_spec", "message": f"重复任务键：{key}"}
        seen.add(field)
        value = rest.strip()
        target, mul, cnt_s = value.partition("*")
        target = target.strip()
        if not target:
            return {"ok": False, "reason": "invalid_spec", "message": f"任务目标为空：{part}"}
        if mul:
            cnt = _as_int(cnt_s.strip())
            if cnt is None or cnt <= 0:
                return {"ok": False, "reason": "invalid_spec", "message": f"任务数量非法：{part}"}
        else:
            cnt = 1
        out[field] = {"target": target, "count": cnt}
    if "gather" not in out and "craft" not in out:
        return {"ok": False, "reason": "invalid_spec", "message": "任务段为空"}
    return out


class HelperEngine:
    """第 2 层【代工助手】引擎（GU-62/63 / F-22 / M-22 / ASST-01~09）。

    操作对象为 ctx 玩家表示（就地改写 player["helpers"] 与背包）；返回 dict 结果、拒绝场景
    {ok: False, reason, message} 不抛异常；纯函数零 IO 零 NoneBot（唯一非纯点 = 时钟注入兜底）。
    """

    def __init__(
        self,
        prof: Optional[ProficiencyEngine] = None,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """构造代工引擎（构造器配置注入 + 缺省兜底，对齐 SynthesisEngine B-1 模式）。

        入参：
          - prof：ProficiencyEngine（GU-62 精通档位判定）；None → 内部缺省构造
            ProficiencyEngine(settings=settings)（B-1 配置单源）。
          - settings：settings dict（assistant 段：enabled/energy_items/queue/helpers/等级成长）；
            缺省 {} → 默认值兜底。
        """
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
        if isinstance(prof, ProficiencyEngine):
            self._prof: ProficiencyEngine = prof
        else:
            self._prof = ProficiencyEngine(settings=self._settings)

    # ------------------------------------------------------------------
    # 配置读取（B-1 单源 + 缺省兜底）
    # ------------------------------------------------------------------
    def _assistant_cfg(self) -> Mapping[str, Any]:
        """assistant 配置段（B-1：settings.assistant 主 → alchemy.assistant 兜底 → {}）。"""
        a = self._settings.get("assistant")
        if isinstance(a, Mapping):
            return a
        alchemy = self._settings.get("alchemy")
        if isinstance(alchemy, Mapping):
            a2 = alchemy.get("assistant")
            if isinstance(a2, Mapping):
                return a2
        return {}

    def _enabled(self) -> bool:
        """模块开关（B-2：显式 bool 取显式值；缺省 True 保证 /代工 开箱可用）。"""
        v = self._assistant_cfg().get("enabled")
        return True if v is None else bool(v)

    def _energy_items(self) -> Sequence[str]:
        """能源道具键列表（L461/B-3：assistant.energy_items 可配；缺省 糖果/馅饼）。"""
        raw = self._assistant_cfg().get("energy_items")
        if isinstance(raw, (list, tuple)) and raw:
            return [str(x) for x in raw]
        return DEFAULT_ENERGY_ITEMS

    def _tick_sec(self) -> int:
        """后台产出周期（秒）（ASST-04/B-4：assistant.queue.tick_sec 可配；缺省 1800）。"""
        q = self._assistant_cfg().get("queue")
        if isinstance(q, Mapping):
            v = _as_int(q.get("tick_sec"))
            if v is not None and v > 0:
                return v
        return DEFAULT_TICK_SEC

    def _queue_max_slots(self) -> int:
        """队列容量（ASST-05/B-6：assistant.queue.max_slots 可配；缺省 3）。"""
        q = self._assistant_cfg().get("queue")
        if isinstance(q, Mapping):
            v = _as_int(q.get("max_slots"))
            if v is not None and v > 0:
                return v
        return DEFAULT_QUEUE_MAX_SLOTS

    def _level_thresholds(self) -> Sequence[int]:
        """等级成长阈值（B-7：assistant.level_thresholds 可配；缺省 (0,100,300,700,1500)）。"""
        raw = self._assistant_cfg().get("level_thresholds")
        if isinstance(raw, (list, tuple)) and raw:
            vals: list = []
            for x in raw:
                v = _as_int(x)
                if v is not None and v >= 0:
                    vals.append(v)
            if vals:
                return vals
        return DEFAULT_LEVEL_THRESHOLDS

    def _trait_bonus_per_level(self) -> int:
        """每级特性加成（ASST-07/L464「特性更多」；可配，缺省 1）。"""
        v = _as_int(self._assistant_cfg().get("trait_bonus_per_level"))
        return v if v is not None and v >= 0 else DEFAULT_TRAIT_BONUS_PER_LEVEL

    def _quality_bonus_per_level(self) -> int:
        """每级品质加成（ASST-07/L464「采集品质更高」；可配，缺省 5）。"""
        v = _as_int(self._assistant_cfg().get("quality_bonus_per_level"))
        return v if v is not None and v >= 0 else DEFAULT_QUALITY_BONUS_PER_LEVEL

    def _helper_def(self, assistant: str) -> Optional[Mapping[str, Any]]:
        """助手表条目（ASST-07 helpers[] {id,name,tier,gather_rate,trait_bonus,quality_bonus}）。

        按 id 或 name 匹配；helpers[] 配置非空 → 查无返回 None（assign 拒绝）；表空/未配置 → {}
        （任意助手名可用默认系数，B-5）。
        """
        raw = self._assistant_cfg().get("helpers")
        if isinstance(raw, (list, tuple)) and raw:
            for h in raw:
                if not isinstance(h, Mapping):
                    continue
                if str(h.get("id")) == assistant or str(h.get("name")) == assistant:
                    return h
            return None
        return {}

    def _gather_rate(self, assistant: str) -> float:
        """助手采集/代采系数（ASST-04「助手系数」；gather_rate 可配，缺省 1.0）。"""
        hd = self._helper_def(assistant)
        if hd:
            try:
                return float(hd.get("gather_rate", 1.0))
            except (TypeError, ValueError):
                return 1.0
        return 1.0

    # ------------------------------------------------------------------
    # 玩家状态读写（B-6：player["helpers"] dict {助手名: {config, started_at, queue}}）
    # ------------------------------------------------------------------
    @staticmethod
    def _helpers(
        player: MutableMapping[str, Any], *, create: bool = False
    ) -> Optional[MutableMapping[str, Any]]:
        """player["helpers"] 桶（不存在时 create=True 建 {} 并挂回 player）。"""
        h = player.get("helpers")
        if not isinstance(h, MutableMapping):
            if not create:
                return None
            h = {}
            player["helpers"] = h
        return h

    @staticmethod
    def _helper_entry(
        player: MutableMapping[str, Any], assistant: str, *, create: bool = False
    ) -> Optional[MutableMapping[str, Any]]:
        """助手状态条目（create=True 建默认结构 {assistant, config, started_at, last_tick_at,
        last_collect_at, queue} 并挂回 player）。"""
        helpers = HelperEngine._helpers(player, create=create)
        if helpers is None:
            return None
        entry = helpers.get(assistant)
        if not isinstance(entry, MutableMapping):
            if not create:
                return None
            entry = {
                "assistant": assistant,
                "config": {},
                "started_at": 0,
                "last_tick_at": 0,
                "last_collect_at": None,
                "queue": {},
            }
            helpers[assistant] = entry
        return entry

    @staticmethod
    def _queue(entry: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        """产出队列桶归一（dict {item_id: 数量}；就地初始化）。"""
        q = entry.get("queue")
        if not isinstance(q, MutableMapping):
            q = {}
            entry["queue"] = q
        return q

    def _alchemy_level(self, player: Mapping[str, Any]) -> int:
        """炼金职业熟练档位索引（GU-62 判定输入；无建档 → 0 见习）。"""
        profs = player.get("proficiency")
        if isinstance(profs, Mapping):
            node = profs.get(ALCHEMY_JOB_ID)
            if isinstance(node, Mapping):
                v = _as_int(node.get("level"))
                if v is not None and v >= 0:
                    return v
        return 0

    # ------------------------------------------------------------------
    # ctx hook（对齐 shop/synthesis：注册表 + add/remove/count 钩子 + in-memory 兜底）
    # ------------------------------------------------------------------
    @staticmethod
    def _item_name(item_id: str, ctx: Mapping[str, Any]) -> str:
        """物品 id → 显示名（ctx["items"] 注册表或 resolve_item 解析器；缺省回退原值）。"""
        if not isinstance(item_id, str):
            return str(item_id)
        items = ctx.get("items")
        if isinstance(items, Mapping):
            hit = items.get(item_id)
            if isinstance(hit, Mapping):
                name = hit.get("name")
                if isinstance(name, str) and name:
                    return name
        resolver = ctx.get("resolve_item")
        if callable(resolver):
            try:
                hit = resolver(item_id)
            except Exception:
                hit = None
            if isinstance(hit, Mapping):
                name = hit.get("name")
                if isinstance(name, str) and name:
                    return name
        return item_id

    @staticmethod
    def _resolve_item_id(ctx: Mapping[str, Any], key: str) -> str:
        """名称/id → 物品 id（B-10：id 精确 → name 反查 → resolve_item 钩子 → 原值兜底）。"""
        if not isinstance(key, str) or not key:
            return key
        items = ctx.get("items")
        if isinstance(items, Mapping):
            if key in items:
                return key
            for iid, it in items.items():
                if isinstance(it, Mapping) and it.get("name") == key:
                    return iid
        resolver = ctx.get("resolve_item")
        if callable(resolver):
            try:
                hit = resolver(key)
            except Exception:
                hit = None
            if isinstance(hit, Mapping):
                hid = hit.get("id")
                if isinstance(hid, str) and hid:
                    return hid
        return key

    def _count_item(self, ctx: Mapping[str, Any], item_id: str) -> int:
        """持有计数（ctx["count_item"] 钩子 → inventory in-memory 兜底）。"""
        hook = ctx.get("count_item")
        if callable(hook):
            try:
                raw: Any = hook(item_id)
                return int(raw)
            except Exception:
                return 0
        inv = ctx.get("inventory")
        if isinstance(inv, Mapping):
            return int(inv.get(item_id, 0))
        return 0

    def _remove_item(self, ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
        """扣减（不部分扣减：ctx["remove_item"] 钩子 → inventory in-memory 兜底）。"""
        hook = ctx.get("remove_item")
        if callable(hook):
            try:
                return bool(hook(item_id, count))
            except Exception:
                return False
        inv = ctx.get("inventory")
        if isinstance(inv, MutableMapping):
            cur = int(inv.get(item_id, 0))
            if cur < count:
                return False
            inv[item_id] = cur - count
            return True
        return False

    def _add_item(self, ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
        """入包（ctx["add_item"] 钩子 → inventory in-memory 兜底；B-10 失败不伪装已发放）。"""
        hook = ctx.get("add_item")
        if callable(hook):
            try:
                return bool(hook(item_id, count, False))
            except Exception:
                return False
        inv = ctx.get("inventory")
        if isinstance(inv, MutableMapping):
            inv[item_id] = int(inv.get(item_id, 0)) + count
            return True
        return False

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _now(now: Any, ctx: Optional[Mapping[str, Any]] = None) -> int:
        """时间戳归一（B-8：显式 now 优先 → ctx["now"] 注入 → 墙钟；唯一非纯点，注入保纯）。"""
        if isinstance(now, (int, float)) and not isinstance(now, bool):
            return int(now)
        if ctx is not None:
            c = ctx.get("now")
            if isinstance(c, (int, float)) and not isinstance(c, bool):
                return int(c)
        return int(time.time())

    @staticmethod
    def _norm_task(task: Any) -> Optional[dict]:
        """任务参数归一（gather/craft 入参形态：None / "矿石*5" 字符串 / {target, count} 映射）。

        出参：{target, count}（count 缺省 1）或 None；非法 → 抛 ValueError（assign 捕获转拒绝）。
        """
        if task is None:
            return None
        if isinstance(task, str):
            s = task.strip()
            if not s:
                return None
            target, mul, cnt_s = s.partition("*")
            target = target.strip()
            if not target:
                raise ValueError("任务目标为空")
            if mul:
                cnt = _as_int(cnt_s.strip())
                if cnt is None or cnt <= 0:
                    raise ValueError("任务数量非法")
            else:
                cnt = 1
            return {"target": target, "count": cnt}
        if isinstance(task, Mapping):
            raw_t = task.get("target") or task.get("item") or task.get("name")
            if not isinstance(raw_t, str) or not raw_t.strip():
                raise ValueError("任务目标为空")
            cnt = _as_int(task.get("count", 1))
            if cnt is None or cnt <= 0:
                raise ValueError("任务数量非法")
            return {"target": raw_t.strip(), "count": cnt}
        raise ValueError("任务形态非法")

    def _level_from_total(self, total: int) -> int:
        """累计产出 → 助手等级（B-7：对照 level_thresholds，1 基起，钳制到阈值表末档）。"""
        thresholds = self._level_thresholds()
        level = 1
        for i, t in enumerate(thresholds):
            if total >= t:
                level = i + 1
        return level

    def _per_tick(self, ctx: Mapping[str, Any], assistant: str, cfg: Mapping[str, Any]) -> dict:
        """单 tick 产出明细（B-5：代采 = count × gather_rate；代调 = output.count × count）。"""
        out: dict = {}
        g = cfg.get("gather")
        if isinstance(g, Mapping):
            rate = self._gather_rate(assistant)
            amt = int(g.get("count", 0) * rate)
            iid = g.get("item_id") or g.get("target")
            if amt > 0 and iid:
                out[iid] = amt
        c = cfg.get("craft")
        if isinstance(c, Mapping):
            amt = int(c.get("item_count", 1) or 1) * int(c.get("count", 0) or 0)
            iid = c.get("item")
            if amt > 0 and iid:
                out[iid] = out.get(iid, 0) + amt
        return out

    # ------------------------------------------------------------------
    # 公开接口：/代工 设定（GU-62/63 + F-22）
    # ------------------------------------------------------------------
    def assign(
        self,
        player: MutableMapping[str, Any],
        ctx: MutableMapping[str, Any],
        assistant: str,
        *,
        gather: Any = None,
        craft: Any = None,
    ) -> dict:
        """`/代工 <助手> [代采=材料*数量,代调=配方*数量]` 设定持续代采/代调（GU-62/63/F-22/M-22）。

        入参：
          - player：玩家状态 dict（就地改写 player["helpers"]）。
          - ctx：玩家表示 + 物品/配方注册表（读 items/recipe + count_item/remove_item 钩子）。
          - assistant：助手名（须在 assistant.helpers[] 表内，表空时任意名可用）。
          - gather/craft：代采/代调任务（"矿石*5" 字符串 或 {target, count} 映射；由壳层
            parse_task_spec 解析键值列表后传入）。
        校验链（GU-62 → GU-63，F-22）：
          1) GU-62：炼金职业 ≥ 精通（档位索引 ≥ 2）→ 否则拒 level_insufficient。
          2) 任务至少一项 → 否则拒 no_task；配方存在 → 否则拒 recipe_not_found。
          3) ASST-05：新任务物品种类并入现有队列超 max_slots → 拒 queue_full。
          4) GU-63：消耗 1 个能源道具（energy_items 序找第一项持有 ≥1）→ 全不足拒 no_energy_item。
          5) F-22：状态存档（助手名/代采代调配置/启动时间/产出队列）；既有队列与累计产出保留。
        出参：{ok, assistant, gather?, craft?, energy_item, energy_item_name, message, started_at,
          level}；拒绝 reason 见上。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player", "message": "玩家状态非法"}
        if not isinstance(assistant, str) or not assistant.strip():
            return {"ok": False, "reason": "assistant_invalid", "message": "助手名非法"}
        assistant = assistant.strip()
        if not self._enabled():
            return {"ok": False, "reason": "module_disabled", "message": "代工系统未开启"}
        try:
            g = self._norm_task(gather)
            c = self._norm_task(craft)
        except ValueError as exc:
            return {"ok": False, "reason": "invalid_task", "message": f"任务格式非法：{exc}"}
        if g is None and c is None:
            return {
                "ok": False,
                "reason": "no_task",
                "message": "请指定 代采 或 代调 任务（如 代采=矿石*5,代调=药剂*2）",
            }
        # GU-62 炼金职业 ≥ 精通
        prof_level = self._alchemy_level(player)
        if self._prof.tier_index_for_level(ALCHEMY_JOB_ID, prof_level) < PROFICIENT_TIER_INDEX:
            return {
                "ok": False,
                "reason": "level_insufficient",
                "message": "等级不足：代工助手需炼金职业 ≥ 精通",
            }
        # 助手表校验（helpers[] 配置非空 → 必须在表内）
        if self._helper_def(assistant) is None:
            return {
                "ok": False, "reason": "assistant_not_found",
                "message": f"没有这个助手：{assistant}",
            }
        # 任务配置构建（配方在此解析，B-11；配置快照供 tick 使用）
        cfg: dict = {"assistant": assistant, "gather": None, "craft": None, "produced_total": 0}
        if g is not None:
            cfg["gather"] = {
                "target": g["target"],
                "item_id": self._resolve_item_id(ctx, g["target"]),
                "count": g["count"],
            }
        if c is not None:
            recipe = resolve_recipe(ctx, c["target"])
            if recipe is None:
                return {
                    "ok": False, "reason": "recipe_not_found",
                    "message": f"代调配方不存在：{c['target']}",
                }
            ro = recipe.get("output")
            oitem = ro.get("item") if isinstance(ro, Mapping) else None
            ocnt = _as_int(ro.get("count")) if isinstance(ro, Mapping) else None
            cfg["craft"] = {
                "target": c["target"],
                "count": c["count"],
                "item": oitem if isinstance(oitem, str) else c["target"],
                "item_count": ocnt if ocnt and ocnt > 0 else 1,
            }
        # ASST-05 队列容量：新任务并入现有队列超 max_slots → 拒（只读不建条目，防零写入）
        existing = self._helper_entry(player, assistant, create=False)
        existing_q = existing.get("queue") if existing is not None else None
        q = existing_q if isinstance(existing_q, MutableMapping) else {}
        prospective = set(q.keys())
        if cfg["gather"] is not None:
            prospective.add(cfg["gather"]["item_id"])
        if cfg["craft"] is not None:
            prospective.add(cfg["craft"]["item"])
        max_slots = self._queue_max_slots()
        if max_slots > 0 and len(prospective) > max_slots:
            return {
                "ok": False, "reason": "queue_full",
                "message": "产出队列已满，请先 /收取 腾出空间",
            }
        # GU-63 消耗能源道具（L461；不足 → 提示缺能源道具）
        consumed = None
        for eid in self._energy_items():
            if self._count_item(ctx, eid) >= 1:
                consumed = eid
                break
        if consumed is None:
            items = " / ".join(str(x) for x in self._energy_items())
            return {
                "ok": False,
                "reason": "no_energy_item",
                "message": f"缺少能源道具：需要 {items}（商店或合成获取）",
            }
        if not self._remove_item(ctx, consumed, 1):
            return {
                "ok": False, "reason": "energy_item_deduct_failed",
                "message": "能源道具扣减失败",
            }
        # F-22 设定持续代采/代调 → 状态存档（助手名/配置/启动时间/产出队列）
        now_ts = self._now(None, ctx)
        entry = self._helper_entry(player, assistant, create=True)
        assert entry is not None  # create=True 必建
        old_cfg = entry.get("config")
        if isinstance(old_cfg, Mapping):
            cfg["produced_total"] = int(old_cfg.get("produced_total", 0) or 0)
        entry["config"] = cfg
        entry["started_at"] = now_ts
        entry["last_tick_at"] = now_ts
        # queue 保留既有产出（ASST-05 已产出项保留）；produced_total 终身累计（B-7 只升不降）
        parts: list = []
        if cfg["gather"] is not None:
            parts.append(f"开始代采 {cfg['gather']['target']}*{cfg['gather']['count']}")
        if cfg["craft"] is not None:
            parts.append(f"代调 {cfg['craft']['target']}*{cfg['craft']['count']}")
        msg = f"{assistant} " + "，".join(parts) + f"（消耗 {self._item_name(consumed, ctx)}×1）"
        return {
            "ok": True,
            "assistant": assistant,
            "gather": cfg["gather"],
            "craft": cfg["craft"],
            "energy_item": consumed,
            "energy_item_name": self._item_name(consumed, ctx),
            "message": msg,
            "started_at": now_ts,
            "level": self.level_of(player, assistant),
        }

    # ------------------------------------------------------------------
    # 公开接口：后台定时产出（F-22 / ASST-04）
    # ------------------------------------------------------------------
    def tick(
        self, player: MutableMapping[str, Any], ctx: Mapping[str, Any], *, now: Any = None
    ) -> dict:
        """后台定时产出（F-22/ASST-04/B-4）：按现实时间 × 周期 → 产出队列累计，离线累积。

        入参：player（读 helpers）、ctx（读配方/物品注册表）、now（结算时间戳，缺省墙钟 B-8）。
        核心逻辑：对每个助手 entry，elapsed = now - last_tick_at；tick 数 = elapsed // tick_sec；
          逐 tick 累计 代采（count×gather_rate）/代调（output.count×count）→ 队列与 produced_total；
          last_tick_at 顺延 last + n×tick_sec（余数顺延不丢不重）。
        出参：{ok, now, tick_sec, produced: {助手: {item_id: 数量}}, total_ticks, skipped}。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player", "message": "玩家状态非法"}
        now_ts = self._now(now)
        tick_sec = self._tick_sec()
        helpers = self._helpers(player, create=False)
        if helpers is None:
            return {
                "ok": True, "now": now_ts, "tick_sec": tick_sec,
                "produced": {}, "total_ticks": 0, "skipped": [],
            }
        produced: dict = {}
        skipped: list = []
        total_ticks = 0
        for name, entry in list(helpers.items()):
            if not isinstance(entry, MutableMapping):
                continue
            cfg = entry.get("config")
            if not isinstance(cfg, MutableMapping):
                continue
            last = entry.get("last_tick_at")
            if last is None:
                last = entry.get("started_at")
            if last is None:
                last = now_ts
            elapsed = now_ts - last
            if elapsed <= 0:
                continue
            n = int(elapsed // tick_sec) if tick_sec > 0 else 0
            if n <= 0:
                continue
            total_ticks += n
            per = self._per_tick(ctx, name, cfg)
            q = self._queue(entry)
            node = produced.setdefault(name, {})
            for item, amt in per.items():
                total_amt = amt * n
                q[item] = q.get(item, 0) + total_amt
                cfg["produced_total"] = int(cfg.get("produced_total", 0) or 0) + total_amt
                node[item] = node.get(item, 0) + total_amt
            if not per:
                skipped.append({"assistant": name, "reason": "no_producible_task"})
            entry["last_tick_at"] = last + n * tick_sec
        return {
            "ok": True, "now": now_ts, "tick_sec": tick_sec,
            "produced": produced, "total_ticks": total_ticks, "skipped": skipped,
        }

    # ------------------------------------------------------------------
    # 公开接口：/收取（F-22 / ASST-06）
    # ------------------------------------------------------------------
    def collect(self, player: MutableMapping[str, Any], ctx: MutableMapping[str, Any]) -> dict:
        """`/收取`（F-22/ASST-06/M-22）：产出队列 → 入包（材料/成品）→ 队列清空。

        入参：player（读 helpers 各队列并清空）、ctx（add_item 钩子/inventory 入包落点）。
        核心逻辑：汇总全部助手队列 → 逐物项入包（B-10：失败项留队列不伪装已发放）→ 成功项队列清空 →
          记 last_collect_at；消息纯文本「收取：矿石×5、药剂×2」（M-22 降级纯文本，B-9）。
        出参：{ok, collected:[{item, item_name, count}], skipped, message, last_collect_at}；
          空队列 → {ok: False, reason: "queue_empty", message}。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player", "message": "玩家状态非法"}
        helpers = self._helpers(player, create=False)
        totals: dict = {}
        if helpers is not None:
            for entry in helpers.values():
                if not isinstance(entry, MutableMapping):
                    continue
                q = entry.get("queue")
                if isinstance(q, Mapping):
                    for item, amt in q.items():
                        v = _as_int(amt)
                        if v and v > 0:
                            totals[item] = totals.get(item, 0) + v
        if not totals:
            return {"ok": False, "reason": "queue_empty", "message": "当前没有待收取的代工产出"}
        now_ts = self._now(None, ctx)
        collected: list = []
        skipped: list = []
        failed: dict = {}
        for item, amt in totals.items():
            iid = self._resolve_item_id(ctx, item)
            if self._add_item(ctx, iid, amt):
                collected.append(
                    {"item": iid, "item_name": self._item_name(iid, ctx), "count": amt}
                )
            else:
                failed[item] = amt
                skipped.append({"item": item, "reason": "item_add_failed"})
        if helpers is not None:
            for entry in helpers.values():
                if not isinstance(entry, MutableMapping):
                    continue
                q = entry.get("queue")
                if isinstance(q, MutableMapping):
                    for item in list(q.keys()):
                        if item not in failed:
                            q.pop(item, None)
                entry["last_collect_at"] = now_ts
        parts = [f"{x['item_name']}×{x['count']}" for x in collected]
        msg = "收取：" + "、".join(parts)
        return {
            "ok": True, "collected": collected, "skipped": skipped,
            "message": msg, "last_collect_at": now_ts,
        }

    # ------------------------------------------------------------------
    # 公开接口：助手等级（ASST-07 / L464）
    # ------------------------------------------------------------------
    def level_of(self, player: MutableMapping[str, Any], assistant: str) -> int:
        """助手等级（B-7）：随累计产出 produced_total 对照 level_thresholds 提升。

        入参：player、assistant。出参：等级 int（无该助手/未建档 → 1）。
        """
        if not isinstance(player, MutableMapping):
            return 1
        entry = self._helper_entry(player, assistant, create=False)
        if entry is None:
            return 1
        cfg = entry.get("config")
        total = int(cfg.get("produced_total", 0) or 0) if isinstance(cfg, Mapping) else 0
        return self._level_from_total(total)

    def level_bonus(self, player: MutableMapping[str, Any], assistant: str) -> dict:
        """等级加成（ASST-07/L464「特性更多 / 采集品质更高」；供壳层渲染 收取 时消费）。

        入参：player、assistant。出参：{level, trait_bonus, quality_bonus}。
        """
        level = self.level_of(player, assistant)
        return {
            "level": level,
            "trait_bonus": (level - 1) * self._trait_bonus_per_level(),
            "quality_bonus": (level - 1) * self._quality_bonus_per_level(),
        }
