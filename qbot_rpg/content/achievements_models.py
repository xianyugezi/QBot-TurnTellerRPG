"""成就配置校验器（qbot_rpg/content/achievements_models.py · M11 批1 路1B）。

依据：
  - docs/细化/细化_4c_成就系统契约.md（成就 schema / ACH-01~13 规则 / TC-18~22）
  - docs/m11_成就摸底.md §2.8（field_meta/loader/validator 接线点）+ §五 批1 1B
  - qbot_rpg/content/quest_models.py（同族校验器先例：_err/_warn/_cond_var_ok/
    _cond_op_ok/_cond_event_name/_id_set/_check_reward_entry 镜像模式）

【工程补白 · 显式标注】
  B-1  content 层禁止 import engine/core（G0 单向依赖：content→data），条件结构校验
       用本地镜像（_cond_var_ok/_cond_op_ok/_cond_event_name），规则与
       engine/condition_engine.validate_condition 完全一致（同 quest_models 先例）。
  B-2  clue_ref 空 = 硬提示软拦（warning 不红拦），对齐 4c §1.3 clue_ref 语义。
  B-3  称号引用靶 = proficiency 模块各条目 titles[].id 并集；模块缺失/无 titles →
       跳过引用检查（宽松，对齐 _id_set None 口径）。
  B-4  坏引用（t_fake 等）只放单测构造的 modules dict，不放 test_demo fixture——
       保持 demo 包零红拦。
"""

from typing import Dict, List, Mapping, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# 常量（对齐 4c §1.2 顶层 8 字段 + §1.3 hidden 3 key）
# ---------------------------------------------------------------------------
ACHIEVEMENT_MODULE: str = "achievements"

TOP_FIELDS: Tuple[str, ...] = (
    "id", "name", "desc", "conditions", "trigger", "once", "hidden", "reward",
)
HIDDEN_FIELDS: Tuple[str, ...] = ("mode", "reveal_text", "clue_ref")
HIDDEN_MODES: Tuple[str, ...] = ("locked", "hide")

# 条件原语（4c §二：{var,op,value,param}）
COND_VARS: Dict[str, str] = {
    "codex": "图鉴完成度（总册或 param 分册）",
    "gain_count": "物品历史累计获得",
    "item_count": "当前背包持有",
    "level": "玩家等级",
    # 事件型 var 以 [事件:xxx] 前缀动态匹配（同 quest_models _cond_event_name）
}
COND_VAR_ALIASES: Dict[str, str] = {
    "图鉴完成度": "codex",
    "累计获得": "gain_count",
    "持有数量": "item_count",
    "等级": "level",
}
COND_VAR_ALIAS_PREFIXES: Tuple[str, ...] = ("[事件:", "[签到:", "x_",)
COND_OPERATORS: Tuple[str, ...] = ("gt", "ge", "lt", "le", "eq", "ne", "between", "is", "not")
COND_OP_SYMBOLS: Tuple[str, ...] = (">", ">=", "<", "<=", "=", "!=")
COND_EVENT_PRESETS: Tuple[str, ...] = (
    "[事件:图鉴新增]", "[事件:隐藏发现]", "[事件:神鱼支线完成]",
    "[事件:副本通关]", "[事件:钓鱼王]", "[事件:锻造王]",
)

# reward 条目键（4c §三：物品/货币键值/组合/称号）
REWARD_ITEM_KEYS: Tuple[str, ...] = ("item", "id")
REWARD_SCALAR_KEYS: Tuple[str, ...] = ("coins", "gem", "exp", "rep", "prof")
REWARD_TITLE_KEY: str = "title"
REWARD_COUNT_KEY: str = "count"
REWARD_BOUND_KEY: str = "bound"

NAME_MAX: int = 20
DESC_MAX: int = 50
GAIN_COUNT_SUSPECT_MAX: int = 999  # 黄提示阈值（条件永假怀疑）

# ACH 规则表（对齐 4c §1.4：硬拦 4 类 + 黄提示 6 类）
ACH_RULES: Dict[str, str] = {
    "ACH-01": "达成判定 100% 由 conditions 三原语驱动，trigger 仅 check",
    "ACH-02": "id 全局唯一",
    "ACH-03": "name ≤20 字 / desc ≤50 字",
    "ACH-04": "条件全与 AND（D-02），条件求值失败 fail-safe False（D-03）",
    "ACH-05": "奖励统一 reward 解析器（D-04 单事务）",
    "ACH-06": "状态只增不减（ACH-08）",
    "ACH-07": "once=true 幂等不重发",
    "ACH-08": "热重载删配置 → 存档保留 + 列表降级提示",
    "ACH-09": "隐藏成就默认 locked（D-06）；reveal_text 达成瞬间一次性输出（D-08）",
    "ACH-10": "不提供 /秘密 列表指令",
    "ACH-11": "默认值兜底（D-09）：trigger=check/once=true/hidden=false/reward=[]",
    "ACH-12": "condition 单对象 ≡ conditions 数组（D-01）；同给异值 → 黄提示",
    "ACH-13": "奖励条目 title 引用必须注册（titles 注册表）",
}


# ---------------------------------------------------------------------------
# 条件校验（本地镜像 quest_models._cond_* 模式）
# ---------------------------------------------------------------------------
def _cond_var_ok(var: object) -> bool:
    """var 键注册判定（镜像 condition_engine.normalize_var 接受集合）。"""
    if not isinstance(var, str) or not var:
        return False
    v = var.strip()
    if not v:
        return False
    if v in COND_VARS or v in COND_VAR_ALIASES:
        return True
    for prefix in COND_VAR_ALIAS_PREFIXES:
        if v.startswith(prefix) and v.endswith("]") and len(v) > len(prefix):
            return True
    if v.startswith("[事件:") and v.endswith("]"):
        return True
    if v.startswith("[签到:") and v.endswith("]"):
        return True
    if v.startswith("x_"):
        return True
    return False


def _cond_op_ok(op: object) -> bool:
    if not isinstance(op, str) or not op:
        return False
    o = op.strip().lower()
    return o in COND_OPERATORS or o in COND_OP_SYMBOLS


def _cond_event_name(var: str) -> str:
    """事件名内嵌目标剥离：[事件:副本通关:熔岩洞窟] → [事件:副本通关]。"""
    inner = var[len("[事件:"):]
    if inner.endswith("]"):
        inner = inner[:-1]
    if ":" in inner:
        name, _ = inner.rsplit(":", 1)
        if name:
            return "[事件:" + name + "]"
    return var


def _check_condition(report: object, cond: object, base_field: str, node_id: str) -> None:
    """条件表达式结构校验（镜像 quest_models._check_condition 规则）。

    红拦：var 未注册 / op 非法 / 条件非对象 / 空条件。
    黄提示：旧格式 {type,var,op,value} / 事件 var 未在预置注册表。
    """
    if cond is None:
        return
    if isinstance(cond, (list, tuple)):
        for c in cond:
            _check_condition(report, c, base_field, node_id)
        return
    if not isinstance(cond, Mapping):
        _err(report, base_field, "R-1", rule="condition_not_object",
             node_id=node_id, got=type(cond).__name__,
             msg="条件表达式要填对象 {var,op,value,param} 或 any/all/not 组合")
        return
    if "var" in cond:
        var = cond.get("var")
        if not _cond_var_ok(var):
            _err(report, f"{base_field}.var", "R-1", rule="var_not_registered",
                 node_id=node_id, var=var, allowed=sorted(COND_VARS),
                 msg="条件变量键 %r 未注册" % (var,))
        elif cond.get("op") is not None and not _cond_op_ok(cond.get("op")):
            _err(report, f"{base_field}.op", "R-1", rule="op_invalid",
                 node_id=node_id, op=cond.get("op"),
                 allowed=list(COND_OPERATORS) + list(COND_OP_SYMBOLS),
                 msg="条件运算符 %r 不认识（9 种：%s，符号双写 >= > <= < = !=）"
                     % (cond.get("op"), "/".join(COND_OPERATORS)))
        elif cond.get("type"):
            _warn(report, f"{base_field}.type", "CND", rule="legacy_format", node_id=node_id,
                  msg="旧格式 {type,var,op,value}，建议迁移为 {var,op,value,param}（type 忽略）")
        if isinstance(var, str) and var.startswith("[事件:") and var.endswith("]"):
            ev = _cond_event_name(var)
            if ev not in COND_EVENT_PRESETS:
                _warn(report, f"{base_field}.var", "CND", rule="event_not_registered",
                      node_id=node_id, var=var, presets=list(COND_EVENT_PRESETS),
                      msg="事件 %r 未在事件注册表登记，确认拼写或先登记（4c §2.3）" % (var,))
        return
    if "all" in cond:
        for c in cond["all"] if isinstance(cond["all"], (list, tuple)) else [cond["all"]]:
            _check_condition(report, c, base_field, node_id)
        return
    if "any" in cond:
        for c in cond["any"] if isinstance(cond["any"], (list, tuple)) else [cond["any"]]:
            _check_condition(report, c, base_field, node_id)
        return
    if "not" in cond:
        _check_condition(report, cond["not"], base_field, node_id)
        return
    if cond.get("type") == "event" and isinstance(cond.get("event"), str):
        _warn(report, base_field, "CND", rule="legacy_format", node_id=node_id,
              msg="旧 event 原语 {type:event,...}，建议迁移为 {var:'[事件:x]',op:'ge',"
                  "value:count,param:target}")
        return
    _err(report, base_field, "R-1", rule="condition_empty", node_id=node_id,
         msg="条件表达式缺 var 或 any/all/not 键")


# ---------------------------------------------------------------------------
# 引用靶收集（模块缺失/非 list → None：调用方跳过引用检查，宽松放行）
# ---------------------------------------------------------------------------
def _id_set(modules: Mapping[str, object], key: str) -> Optional[Set[str]]:
    data = modules.get(key)
    if not isinstance(data, list):
        return None
    ids: Set[str] = set()
    for e in data:
        if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
            ids.add(e["id"])
    return ids if ids else None


def _title_ids(modules: Mapping[str, object]) -> Optional[Set[str]]:
    """称号引用靶：proficiency 模块各条目 titles[].id 并集（B-3）。

    proficiency.json 为 list，titles 段在各条目内（alchemy 条目有
    contest_champion / achievement_100_craft 等）。模块缺失/无 titles → None（跳过）。
    """
    data = modules.get("proficiency")
    if not isinstance(data, list):
        return None
    ids: Set[str] = set()
    any_titles = False
    for e in data:
        if not isinstance(e, Mapping):
            continue
        titles = e.get("titles")
        if not isinstance(titles, list):
            continue
        for t in titles:
            if isinstance(t, Mapping) and isinstance(t.get("id"), str) and t["id"]:
                any_titles = True
                ids.add(t["id"])
    return ids if any_titles else None


def _settings_currency_ids(modules: Mapping[str, object]) -> Tuple[str, ...]:
    """settings 货币键空间（settings.currencies[].id）；缺省 → 默认模板。"""
    settings = modules.get("settings")
    if not isinstance(settings, Mapping):
        return ("coins", "diamond")
    raw = settings.get("currencies")
    ids: List[str] = []
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
                ids.append(e["id"])
    return tuple(ids) or ("coins", "diamond")


# ---------------------------------------------------------------------------
# reward 结构校验（镜像 quest_models._check_reward_entry + title 型扩展）
# ---------------------------------------------------------------------------
class _Refs:
    """成就跨模块引用校验靶（None = 目标模块未声明 → 跳过对应引用检查）。"""

    __slots__ = ("item_ids", "title_ids", "currency_ids")

    def __init__(self) -> None:
        self.item_ids: Optional[Set[str]] = None
        self.title_ids: Optional[Set[str]] = None
        self.currency_ids: Tuple[str, ...] = ("coins", "diamond")


def _check_reward(report: object, reward: object, base: str, node_id: str,
                  refs: _Refs) -> None:
    """reward 统一条目校验（物品/货币键值/组合/称号；内联串=糖放行）。

    硬拦：条目非对象 / 同条目同时含物品与标量键 / 未知键 / count 非正整数 /
          标量值非法 / 物品引用不存在 / 货币键未注册 / title 引用不存在（ACH-13）。
    """
    if reward is None:
        return  # 缺省空奖励（D-09：reward=空，绝不报错）
    if isinstance(reward, str):
        return  # 内联键值串结构展开归 core/reward 导入器（D-05），本层放行
    entries = reward if isinstance(reward, list) else [reward]
    for i, entry in enumerate(entries):
        ebase = f"{base}.{i}" if isinstance(reward, list) else base
        if not isinstance(entry, Mapping):
            _err(report, ebase, "R-5", rule="reward_entry_not_object",
                 node_id=node_id, got=type(entry).__name__,
                 msg="reward 条目需对象 {item,count} / {coins|gem|exp|rep:N} / {title:ID}")
            continue
        _check_reward_entry(report, entry, ebase, node_id, refs)


def _check_reward_entry(report: object, entry: Mapping[str, object], base: str,
                        node_id: str, refs: _Refs) -> None:
    """单条 reward 条目校验（含 title 型）。"""
    keys = set(entry.keys())
    item_keys = [k for k in REWARD_ITEM_KEYS if k in entry]
    scalar_keys = [k for k in REWARD_SCALAR_KEYS if k in entry]
    has_title = REWARD_TITLE_KEY in entry

    # title 型（ACH-13：引用必须注册；与物品/标量互斥）
    if has_title:
        if item_keys or scalar_keys:
            _err(report, base, "R-5", rule="reward_entry_title_mixed",
                 node_id=node_id, keys=sorted(keys),
                 msg="称号条目不能与物品/货币键值同条目（{title:ID} 独占）")
            return
        title_id = entry[REWARD_TITLE_KEY]
        if not isinstance(title_id, str) or not title_id:
            _err(report, f"{base}.title", "R-5", rule="reward_title_id_invalid",
                 node_id=node_id, title=title_id,
                 msg="称号条目 title 需非空字符串")
        elif refs.title_ids is not None and title_id not in refs.title_ids:
            _err(report, f"{base}.title", "R-4", rule="reward_title_ref_missing",
                 node_id=node_id, title=title_id, registered=sorted(refs.title_ids),
                 msg="奖励称号 %r 未在 proficiency.json titles 注册，先去称号页添加（ACH-13）"
                     % (title_id,))
        return

    # 物品/标量条目（镜像 quest_models）
    if item_keys and scalar_keys:
        _err(report, base, "R-5", rule="reward_entry_mixed",
             node_id=node_id, item_keys=item_keys, scalar_keys=scalar_keys,
             msg="reward 条目不能同时是物品与货币键值（%s + %s）"
                 % ("/".join(item_keys), "/".join(scalar_keys)))
        return
    if not item_keys and not scalar_keys:
        _err(report, base, "R-5", rule="reward_entry_structure",
             node_id=node_id, keys=sorted(keys),
             msg="reward 条目需含物品键（item/id）或标量键（coins/gem/exp/rep）或 title")
        return
    if item_keys:
        item_key = item_keys[0]
        item_id = entry[item_key]
        unknown = keys - {item_key, REWARD_COUNT_KEY, REWARD_BOUND_KEY}
        if unknown:
            _err(report, base, "R-5", rule="reward_entry_unknown_key",
                 node_id=node_id, keys=sorted(unknown),
                 msg="物品条目多余键 %s（合法：%s/count/bound）" % (sorted(unknown), item_key))
        if not isinstance(item_id, str) or not item_id:
            _err(report, f"{base}.{item_key}", "R-5", rule="reward_item_id_invalid",
                 node_id=node_id, item_id=item_id, msg="物品条目 %s 需非空字符串" % (item_key,))
        elif refs.item_ids is not None and item_id not in refs.item_ids:
            _err(report, f"{base}.{item_key}", "R-4", rule="reward_item_ref_missing",
                 node_id=node_id, item=item_id, registered=sorted(refs.item_ids),
                 msg="奖励物品 %r 在 items.json 中不存在，先去物品页添加（4c §三）"
                     % (item_id,))
        if REWARD_COUNT_KEY in entry:
            count = entry[REWARD_COUNT_KEY]
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                _err(report, f"{base}.count", "R-2", rule="reward_count_invalid",
                     node_id=node_id, count=count, msg="物品 count 需 ≥1 整数（缺省 1）")
        if REWARD_BOUND_KEY in entry and not isinstance(entry[REWARD_BOUND_KEY], bool):
            _err(report, f"{base}.bound", "R-1", rule="reward_bound_invalid",
                 node_id=node_id, value=entry[REWARD_BOUND_KEY],
                 msg="物品 bound 需 bool（缺省 true=绑定）")
        return

    # 标量条目
    for sk in scalar_keys:
        val = entry[sk]
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            _err(report, f"{base}.{sk}", "R-2", rule="reward_scalar_invalid",
                 node_id=node_id, key=sk, value=val,
                 msg="标量奖励 %s 需数值（货币/经验/声望）" % (sk,))
        elif val < 0:
            _err(report, f"{base}.{sk}", "R-2", rule="reward_scalar_negative",
                 node_id=node_id, key=sk, value=val, msg="标量奖励 %s 不能为负数" % (sk,))
        elif sk in ("coins", "gem") and refs.currency_ids and sk not in refs.currency_ids:
            _err(report, f"{base}.{sk}", "R-4", rule="reward_currency_unregistered",
                 node_id=node_id, key=sk, registered=list(refs.currency_ids),
                 msg="货币键 %r 未在 settings.currencies 注册" % (sk,))


# ---------------------------------------------------------------------------
# 成就条目校验 + 主入口
# ---------------------------------------------------------------------------
def _check_entry(report: object, entry: object, idx: int,
                 refs: _Refs, seen_ids: Set[str]) -> None:
    base = f"[{idx}]"
    if not isinstance(entry, Mapping):
        _err(report, base, "R-5", rule="achievement_not_object",
             node_id=str(idx), got=type(entry).__name__,
             msg="achievements.json 每条成就需对象")
        return

    # id / name 必填（ACH-02/03）
    aid = entry.get("id")
    if not isinstance(aid, str) or not aid:
        _err(report, f"{base}.id", "R-1", rule="achievement_id_invalid",
             node_id=str(idx), id=aid, msg="成就 id 需非空字符串")
        return
    if aid in seen_ids:
        _err(report, f"{base}.id", "R-1", rule="achievement_id_duplicate",
             node_id=aid, msg="成就 id %r 重复（ACH-02 全局唯一）" % (aid,))
    seen_ids.add(aid)

    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        _err(report, f"{base}.name", "R-1", rule="achievement_name_invalid",
             node_id=aid, name=name, msg="成就 name 需非空字符串")
    elif len(name) > NAME_MAX:
        _warn(report, f"{base}.name", "R-3", rule="achievement_name_too_long",
              node_id=aid, length=len(name), max=NAME_MAX,
              msg="成就 name %d 字超 %d 字上限（ACH-03 黄提示）" % (len(name), NAME_MAX))

    desc = entry.get("desc")
    if desc is not None and isinstance(desc, str) and len(desc) > DESC_MAX:
        _warn(report, f"{base}.desc", "R-3", rule="achievement_desc_too_long",
              node_id=aid, length=len(desc), max=DESC_MAX,
              msg="成就 desc %d 字超 %d 字上限（ACH-03 黄提示）" % (len(desc), DESC_MAX))

    # trigger（ACH-01/11：仅 check）
    trigger = entry.get("trigger")
    if trigger is not None and trigger != "check":
        _err(report, f"{base}.trigger", "R-5", rule="trigger_not_check",
             node_id=aid, trigger=trigger,
             msg="trigger 仅支持 check（达成检测），%r 是结构错误（ACH-01）" % (trigger,))

    # conditions（D-01/D-02/D-09：缺省 [] 接取即达成，黄提示）
    cond_alias = entry.get("condition")
    conditions = entry.get("conditions")
    if cond_alias is not None and conditions is not None and cond_alias != conditions:
        _warn(report, f"{base}.condition", "CND", rule="condition_alias_conflict",
              node_id=aid, msg="condition 单对象与 conditions 数组同给且异值（D-01 黄提示）")
    if conditions is not None and not isinstance(conditions, list):
        _err(report, f"{base}.conditions", "R-5", rule="conditions_not_list",
             node_id=aid, got=type(conditions).__name__,
             msg="conditions 需数组（单对象请用 condition 或包一层）")
        return
    if isinstance(conditions, list) and not conditions and cond_alias is None:
        _warn(report, f"{base}.conditions", "CND", rule="conditions_empty",
              node_id=aid, msg="conditions 为空 = 接取即达成（ACH-11 黄提示不拦）")
    for i, cond in enumerate(conditions or []):
        _check_condition(report, cond, f"{base}.conditions.{i}", aid)

    # once=false 通胀提示
    once = entry.get("once", True)
    if once is False:
        _warn(report, f"{base}.once", "ACH", rule="once_false_inflation",
              node_id=aid, msg="once=false 可重复达成重复发奖（成就通胀，黄提示）")

    # hidden（D-06/D-08/D-09）
    hidden = entry.get("hidden")
    hidden_obj: Optional[Mapping[str, object]] = None
    if hidden is True:
        hidden_obj = {"mode": "locked"}
    elif isinstance(hidden, Mapping):
        hidden_obj = hidden
    elif hidden is not None and hidden is not False:
        _err(report, f"{base}.hidden", "R-5", rule="hidden_invalid",
             node_id=aid, got=type(hidden).__name__,
             msg="hidden 需 bool 或 {mode,reveal_text,clue_ref} 对象")
    if hidden_obj is not None:
        mode = hidden_obj.get("mode", "locked")
        if mode not in HIDDEN_MODES:
            _err(report, f"{base}.hidden.mode", "R-5", rule="hidden_mode_invalid",
                 node_id=aid, mode=mode, allowed=list(HIDDEN_MODES),
                 msg="hidden.mode 需 locked 或 hide（%r 非法）" % (mode,))
        reveal_text = hidden_obj.get("reveal_text")
        if reveal_text is None or not isinstance(reveal_text, str) or not reveal_text.strip():
            _warn(report, f"{base}.hidden.reveal_text", "ACH", rule="hidden_no_reveal",
                  node_id=aid, msg="隐藏成就缺 reveal_text（达成瞬间无揭示文案，建议补全）")
        clue_ref = hidden_obj.get("clue_ref")
        if clue_ref is None or (isinstance(clue_ref, list) and not clue_ref):
            _warn(report, f"{base}.hidden.clue_ref", "ACH", rule="hidden_no_clue",
                  node_id=aid, msg="隐藏成就 clue_ref 空（硬提示软拦：可能永不可发现）")

    # reward（D-05/D-09：缺省 []）
    reward_alias = entry.get("rewards")
    reward = entry.get("reward")
    if reward_alias is not None and reward is not None and reward_alias != reward:
        _warn(report, f"{base}.rewards", "ACH", rule="reward_alias_conflict",
              node_id=aid, msg="reward 与 rewards 同给且异值（别名冲突黄提示）")
    _check_reward(report, reward if reward is not None else reward_alias,
                  f"{base}.reward", aid, refs)


def validate_achievements(modules: Mapping[str, object], report: object) -> None:
    """成就模块校验主入口（loader/validator 专项路由调用）。

    入参:
      modules: 全量内容模块（achievements 键为 list；proficiency/items/settings 供引用靶）。
      report:  收集器（_err/_warn 三形态兼容：_Checker / 列表 / {"errors":[]}）。
    出参: 无（红拦/黄提示全部经 report 收集，红拦由 loader 聚合拒绝加载）。
    """
    data = modules.get(ACHIEVEMENT_MODULE)
    if data is None:
        return
    if not isinstance(data, list):
        _err(report, f"{ACHIEVEMENT_MODULE}", "R-5", rule="achievements_not_list",
             node_id=None, got=type(data).__name__,
             msg="achievements.json 需顶层数组（每条成就一个对象）")
        return

    refs = _Refs()
    refs.item_ids = _id_set(modules, "items")
    refs.title_ids = _title_ids(modules)
    refs.currency_ids = _settings_currency_ids(modules)

    seen_ids: Set[str] = set()
    for i, entry in enumerate(data):
        _check_entry(report, entry, i, refs, seen_ids)


# ---------------------------------------------------------------------------
# 收集器兼容（_err/_warn 三形态，对齐 quest_models L495-504）
# ---------------------------------------------------------------------------
def _emit(report: object, level: str, field: str, kind: str, **detail: object) -> None:
    """向收集器发一条校验记录（error/warning 两态，兼容三种收集器）。"""
    rec = {"field": field, "kind": kind, "level": level, **detail}
    if hasattr(report, "_err") and level == "error":
        report._err(field, kind, **detail)
        return
    if hasattr(report, "_warn") and level == "warning":
        report._warn(field, kind, **detail)
        return
    if isinstance(report, dict):
        bucket = report.setdefault("errors" if level == "error" else "warnings", [])
        bucket.append(rec)
        return
    if isinstance(report, list):
        report.append(rec)


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", field, kind, **detail)
