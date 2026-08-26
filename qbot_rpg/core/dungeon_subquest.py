"""M3 批次5·路P：副本子任务五形式判定（M22）+ 奖励与可选性（M23）——纯逻辑承载与判定骨架。

依据：
  - docs/规划/规划_路2a_地图副本.md 章5 M21-M23（M21 五形式配置 / M22 五形式进度判定 /
    M23 子任务奖励与可选性——奖励驱动、不做也能打 BOSS）
  - docs/m3_shared_contract.md §4.3（副本子任务五形式：到达指定区域 / 击败指定怪 / 收集指定物 /
    完成指定交互 / 达成指定条件；zone 限定副本 ID；进副本自动激活（不占板槽位）；
    奖励与可选性——不完成可进 BOSS）
  - m3_shared_contract §4.1（dungeon.json `subquests: string[]` 引用 quest.json）+ 细化_3e §2.3
    （缺失字段默认放行口径）

工程补白（定稿/契约未明示处，显式标注，不冒充定稿）：
  1. quest.json 正式任务结构由 M5 任务系统定稿对齐；本路只做副本子任务承载与判定骨架。quest.json
     未定义时按 subquest 条目结构承接：{id, kind, target, count, reward:{items, exp, gold}}
     （reward.items 元素 = {item, count}）。
  2. 五形式键归一：契约 §4.3 给中文五形式；规划 M21 给 quest.json type 五值（explore 探索 /
     collect 收集 / clear 清剿 / mechanic 机制学习 / intel 情报）。本路取事件驱动口径统一为
     SUBQUEST_KINDS = ("reach_zone", "defeat", "collect", "interact", "condition")：
       reach_zone = 到达指定区域（走图命中，对齐 M22 explore 到达区域计数）
       defeat     = 击败指定怪（击杀计数，对齐 M22 clear 击败精英计数）
       collect    = 收集指定物（获得物品计数，对齐 M22 collect 采集计数）
       interact   = 完成指定交互（交互计数，对齐 M22 mechanic 触发地图机制计数）
       condition  = 达成指定条件（条件满足，对齐 M22 intel 图鉴/情报类进度）
     quest.json type 五值 ↔ 本路键的归一映射由 M5 任务系统收口时做（本路不实现映射）。
  3. condition 形式 target = 条件表达式 {var, op, value, param}（value 参与比较、param 兜底；
     契约形态 {var, op, param} 等价，对齐既有 weather_conditions.eval_condition 键空间）。
     本路内置最小求值器 eval_condition（fail-safe，对齐 2a1d LC-D「求值失败默认不满足」）；
     通用条件引擎统一求值链由 M5 任务系统接线，本函数仅判定骨架。
  4. 进度存储：挂在玩家会话 session[SUBQUEST_SESSION_KEY]（副本会话内进度 dict，随副本会话
     持久化，M30）；本路无板槽概念，activate 仅建副本内进度——「不占板槽位」天然成立。
  5. 奖励：claim_reward 返回奖励形态 {items:[{item,count}], exp, gold} 并标记已领（防重复）；
     实际入账由收口走统一 reward 管线（规划 M23 引用路1 T48），本路不触碰 player_ctx 数值。
  6. 可选性：子任务完成度不阻塞 BOSS 战入口（规划 M23 / 契约 §4.3）。本路无 BOSS 门逻辑——
     未完成仅表现为 is_complete=False / claim 拒绝 not_complete，调用方照常可进 BOSS。

铁律：零 NoneBot import；纯函数无 IO（不读文件/不碰网络/不访问全局时钟；session / player_ctx
均为调用方传入的内存 dict，session 的 SUBQUEST_SESSION_KEY 写入为本路唯一副作用点）；
完整类型标注（typing 3.9 兼容）。本模块为新建文件，零冲突（不改动任何既有文件）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

__all__ = [
    "SUBQUEST_KINDS",
    "SUBQUEST_SESSION_KEY",
    "ProgressTracker",
    "normalize_subquest",
    "eval_condition",
]

# -------------------------------------------------------------------------------------
# 五形式权威枚举（工程补白 2：契约 §4.3 中文五形式 → 事件驱动键）
# -------------------------------------------------------------------------------------
SUBQUEST_KINDS: Tuple[str, ...] = (
    "reach_zone",  # 到达指定区域（走图命中）
    "defeat",      # 击败指定怪（击杀计数）
    "collect",     # 收集指定物（获得物品计数）
    "interact",    # 完成指定交互（交互计数）
    "condition",   # 达成指定条件（条件满足）
)

SUBQUEST_SESSION_KEY: str = "dungeon_subquests"
# 副本子任务进度在玩家会话中的挂载键（副本会话内进度 dict；M30 随副本会话持久化）。

# 条件运算符白名单（工程补白 3：对齐 weather_conditions 的 eq/== 兼容别名口径）
_OPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("eq", ("eq", "==")),
    ("ne", ("ne", "!=")),
    ("gt", ("gt", ">")),
    ("gte", ("gte", ">=")),
    ("lt", ("lt", "<")),
    ("lte", ("lte", "<=")),
)


def _op_group(op: object) -> Optional[str]:
    """运算符 → 语义组（eq/ne/gt/gte/lt/lte）；未知/非字符串 → None（fail-safe）。"""
    if not isinstance(op, str):
        return None
    for group, aliases in _OPS:
        if op in aliases:
            return group
    return None


def eval_condition(cond: object, state: object) -> bool:
    """最小条件求值（condition 形式判定骨架）：{var, op, value, param} → bool。

    cond:  条件表达式；op 缺省 eq；比较值取 `value` 键，缺省回退 `param`（契约形态等价）。
    state: 玩家/副本状态 dict（var → 当前值）。
    fail-safe（对齐 2a1d LC-D）：非 Mapping / 未知 var / 未知 op / 值缺失 / 无法比较 → False，
    不抛错。【工程补白 3】通用条件引擎统一求值链由 M5 任务系统接线。
    """
    if not isinstance(cond, Mapping) or not isinstance(state, Mapping):
        return False
    var = cond.get("var")
    if not isinstance(var, str) or not var or var not in state:
        return False
    op = _op_group(cond.get("op", "eq"))
    if op is None:
        return False
    if "value" in cond:
        want = cond["value"]
    elif "param" in cond:
        want = cond["param"]
    else:
        return False
    got = state[var]
    try:
        if op == "eq":
            return bool(got == want)
        if op == "ne":
            return bool(got != want)
        return _compare(op, got, want)
    except Exception:
        return False  # fail-safe：不可比较 → 不满足


def _compare(op: str, got: object, want: object) -> bool:
    """序比较（gt/gte/lt/lte）；类型不可比由调用方 except 兜底为 False。"""
    if op == "gt":
        return bool(got > want)  # type: ignore[operator]
    if op == "gte":
        return bool(got >= want)  # type: ignore[operator]
    if op == "lt":
        return bool(got < want)  # type: ignore[operator]
    if op == "lte":
        return bool(got <= want)  # type: ignore[operator]
    return False


# -------------------------------------------------------------------------------------
# subquest 条目结构（工程补白 1：quest.json 未定义时的承接结构）
# -------------------------------------------------------------------------------------
def _normalize_reward(reward: object) -> Dict[str, Any]:
    """reward 子段规范化：{items:[{item,count}], exp, gold}；缺省空（细元素坏值丢弃/回退）。"""
    if not isinstance(reward, Mapping):
        return {"items": [], "exp": 0, "gold": 0}
    items: List[Dict[str, Any]] = []
    items_raw = reward.get("items")
    if isinstance(items_raw, list):
        for it in items_raw:
            if not isinstance(it, Mapping):
                continue
            item_id = it.get("item")
            if not isinstance(item_id, str) or not item_id:
                continue
            cnt = it.get("count", 1)
            if not isinstance(cnt, int) or isinstance(cnt, bool) or cnt < 1:
                cnt = 1
            items.append({"item": item_id, "count": cnt})
    exp = reward.get("exp", 0)
    gold = reward.get("gold", 0)
    return {
        "items": items,
        "exp": exp if isinstance(exp, int) and not isinstance(exp, bool) else 0,
        "gold": gold if isinstance(gold, int) and not isinstance(gold, bool) else 0,
    }


def normalize_subquest(entry: object) -> Optional[Dict[str, Any]]:
    """subquest 条目规范化（工程补白 1：quest.json 未定义前的承接结构）。

    输入：{id, kind, target, count, reward:{items:[{item,count}], exp, gold}}。
    返回规范形态 {id, kind, target, count, reward}；非法条目（非 dict / 缺 id / kind 不在
    五形式 / count 非正整数 / 缺 target）→ None（fail-safe 不抛错，红拦归校验器/收口）。
    count 缺省 = 1；reward 缺省 = 空（缺失字段默认放行，细化_3e §2.3）。
    """
    if not isinstance(entry, Mapping):
        return None
    sid = entry.get("id")
    if not isinstance(sid, str) or not sid:
        return None
    kind = entry.get("kind")
    if not isinstance(kind, str) or kind not in SUBQUEST_KINDS:
        return None
    if "target" not in entry or entry.get("target") is None:
        return None
    count = entry.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return None
    return {
        "id": sid,
        "kind": kind,
        "target": entry["target"],
        "count": count,
        "reward": _normalize_reward(entry.get("reward")),
    }


# -------------------------------------------------------------------------------------
# 进度追踪器（M22 判定 + M23 奖励/可选性骨架）
# -------------------------------------------------------------------------------------
class ProgressTracker:
    """副本子任务进度追踪（M22 五形式判定 + M23 奖励/可选性）。

    session:   玩家会话（MutableMapping）；副本内进度挂在 session[SUBQUEST_SESSION_KEY]，
               不占板槽位（本路无板槽概念），随副本会话持久化（M30）。写入该键为本路唯一副作用。
    subquests: subquest 条目可迭代对象（原始/规范形态均可，内部 normalize_subquest 规范化；
               非法条目跳过——红拦由校验器/收口负责）。
    """

    def __init__(
        self,
        session: MutableMapping[str, Any],
        subquests: Sequence[object],
    ) -> None:
        self._session = session
        self._configs: Dict[str, Dict[str, Any]] = {}
        for entry in subquests:
            norm = normalize_subquest(entry)
            if norm is not None:
                self._configs[norm["id"]] = norm
        if SUBQUEST_SESSION_KEY not in self._session:
            self._session[SUBQUEST_SESSION_KEY] = {}

    # ---- 内部：进度读写 ---------------------------------------------------------
    def _progress_dict(self) -> MutableMapping[str, Any]:
        d = self._session.get(SUBQUEST_SESSION_KEY)
        if not isinstance(d, MutableMapping):
            d = {}
            self._session[SUBQUEST_SESSION_KEY] = d
        return d

    def _make_entry(self, sid: str) -> Dict[str, Any]:
        return {
            "current": 0,
            "target": self._configs[sid]["count"],
            "done": False,
            "claimed": False,
        }

    # ---- 公开 API ---------------------------------------------------------------
    def activate(self, subquest_id: str) -> bool:
        """进副本自动激活（契约 §4.3：进副本自动激活，不占板槽位——仅建副本内进度）。

        未知 id → False；已激活 → False（幂等，不重复建）；首次激活 → 建进度并返回 True。
        """
        if subquest_id not in self._configs:
            return False
        prog = self._progress_dict()
        if subquest_id in prog:
            return False
        prog[subquest_id] = self._make_entry(subquest_id)
        return True

    def record(self, event: str, target: object, count: int = 1) -> List[str]:
        """事件推进五形式（M22）：event ∈ SUBQUEST_KINDS，target 命中即推进。

        事件语义（对齐五形式键）：reach_zone = 走图命中（到达地图）/ defeat = 击杀怪物 /
        collect = 获得物品 / interact = 交互完成 / condition = 条件满足（target = 条件表达式
        字典，字典相等判定；是否满足由调用方用 eval_condition 对玩家状态求值后触发）。
        对 kind==event 且 target 相等的所有未完成子任务计数 += count（钳制到 target 上限）；
        首个达到上限者标记完成并返回完成提示串（一次 record 可同时完成多个子任务）。
        未知 event / count<=0 / 无匹配 → []（no-op，不抛错）。未显式 activate 的子任务在
        首次命中事件时隐式激活（进副本语义，activate 为入口预激活钩子）。
        """
        if event not in SUBQUEST_KINDS:
            return []
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return []
        prog = self._progress_dict()
        completed: List[str] = []
        for sid, cfg in self._configs.items():
            if cfg["kind"] != event or cfg["target"] != target:
                continue
            if sid not in prog:
                prog[sid] = self._make_entry(sid)  # 隐式激活（首次命中事件）
            pe = prog[sid]
            if pe["done"]:
                continue
            pe["current"] = min(pe["target"], pe["current"] + count)
            if pe["current"] >= pe["target"]:
                pe["done"] = True
                completed.append(f"副本子任务完成：{sid}")
        return completed

    def progress(self, subquest_id: str) -> Dict[str, Any]:
        """完成度查询：{current, target, done}。未激活 → config 基线（0/count/False）；
        未知 id → 全 0。"""
        cfg = self._configs.get(subquest_id)
        if cfg is None:
            return {"current": 0, "target": 0, "done": False}
        pe = self._progress_dict().get(subquest_id)
        if pe is None:
            return {"current": 0, "target": cfg["count"], "done": False}
        return {"current": pe["current"], "target": pe["target"], "done": pe["done"]}

    def is_complete(self, subquest_id: str) -> bool:
        """是否完成（未激活/未知 → False）。"""
        pe = self._progress_dict().get(subquest_id)
        return bool(pe is not None and pe.get("done"))

    def claim_reward(
        self,
        subquest_id: str,
        player_ctx: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """奖励发放（M23）：完成的子任务发放 reward 形态并标记已领（防重复）。

        player_ctx：预留玩家上下文（本路不触碰其数值；入账由收口走统一 reward 管线，
        规划 M23 引用路1 T48）。返回：
          完成且未领  → {"ok": True, "granted": True, "subquest_id", "items", "exp", "gold"}
          完成但已领  → {"ok": True, "granted": False, "reason": "already_claimed"}
          未完成/未激活 → {"ok": False, "reason": "not_complete"}
          未知 id     → {"ok": False, "reason": "unknown_subquest"}
        可选性（规划 M23 / 契约 §4.3）：本路无 BOSS 门——未完成仅表现为 not_complete 拒绝，
        不抛错、不阻塞调用方进 BOSS。
        """
        cfg = self._configs.get(subquest_id)
        if cfg is None:
            return {"ok": False, "reason": "unknown_subquest"}
        prog = self._progress_dict()
        pe = prog.get(subquest_id)
        if pe is None or not pe.get("done"):
            return {"ok": False, "subquest_id": subquest_id, "reason": "not_complete"}
        if pe.get("claimed"):
            return {
                "ok": True,
                "granted": False,
                "subquest_id": subquest_id,
                "reason": "already_claimed",
            }
        pe["claimed"] = True
        reward = cfg["reward"]
        items = [dict(it) for it in reward["items"]]  # 深拷贝，防外部篡改污染配置
        return {
            "ok": True,
            "granted": True,
            "subquest_id": subquest_id,
            "items": items,
            "exp": reward["exp"],
            "gold": reward["gold"],
        }
