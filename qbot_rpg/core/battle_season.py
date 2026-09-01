"""M13 批10 路10B · 6c 换季结算边界引擎（qbot_rpg/core/battle_season.py）。

文件名：qbot_rpg/core/battle_season.py
创建时间：2026-09-02
作者：Hermes 子agent-10B（M13 6c 季节技能组实现组批10路10B：并发同仓，仅新建
  本文件 + tests/unit/test_battle_season.py；不碰兄弟文件——10A 独占季节判定
  （skill_season.py）、10C 独占条件键+事件；battle.py 接线由主 agent 收口，
  本引擎只提供挂点函数与最小装配透传位）

功能描述：6c 换季结算边界引擎（细化_6c §2.3 机制 M6 · 流程 F-R2）——
  战斗内换季检测/待结算/切换/展示过滤/普攻防御兜底的纯函数引擎：
  1) 战斗内换季检测（F-R2 ②）：check_changes 复用（IF09 缓存索引对比，
     worldtime 现成；本引擎不 import engine 层，检测结果经注入通道传入，
     G0 core 只依赖 data 口径）→ 检测到季节差异 → 标记「换季待结算」；
  2) 待结算期（F-R2 ②③ / D-05）：检测到差异的当回合行动按旧组校验
     （旧季节技能照常可用，SC-1）；新季节下一回合才生效；
  3) 切换时点（F-R2 ③ 结算边界）：回合结束 tick 之后、下一回合开始之前
     → 技能组切换为新季节组；切换幂等（SC-3：连续两回合同季节 → 无差异、
     不标记、不触发，恰一次原则）；
  4) 保留项（F-R2 ④）：MP / 连段段数 / 印记 / 冷却剩余 / 全部进行中 buff
     全保留——本引擎切换只改「生效季节」引用，不触碰任何战斗状态段
     （快照/资源/效果全不动，保留由「不触碰」天然成立）；
  5) 展示过滤（EFF-3）：技能列表按当季过滤/置灰——非当季技能标记
     （grayscale=True + 「此术式与当前时节不合」提示语义键），供 /技能
     展示消费；普攻「四时术」与防御指令全年可用（兜底零空窗 EFF-3/
     F-R2 ④：普攻/防御不属于 season 技能组，过滤天然放行）；
  6) 事件钩子（F-R2 ⑤）：切换完成时返回触发信号（on_season_change 事件
     挂载点，恰一次；E1/E5），具体 proc 触发由装配层（effects 容器）
     消费，本引擎零 proc 执行——零模板输出（换季文案归展示层）。

依据：
  - docs/细化/细化_6c_资源轴与职业机制.md（497 行 v1.0）：
    §2.2 EFF-2（进战懒加载）/ EFF-3（展示过滤置灰 + 普攻防御兜底）/
    EFF-5（行动校验引用在回合开始懒重读时更新——SC-2 引擎零新状态机）；
    §2.3 机制 M6 流程 F-R2 全六步（① 懒重读 ② 检测标记待结算 ③ 回合结束
    tick 后切换 ④ 保留项 ⑤ 反馈+on_season_change ⑥ 战斗外不切换）；
    §2.3 SC-1（待结算期按旧组校验）/ SC-2（引擎零新状态机）/ SC-3（切换
    幂等恰一次）；§2.5 E1（on_season_change 事件）/ E5（战斗内才触发，
    同一结算边界只触发一次）；§0.3 D-05（换季待结算期行动口径）；
    §六 TC-11（换季结算边界全链路断言）。
  - docs/m13_6c摸底.md：M6 缺口（battle.end_turn L1653 是天然挂点但无季节
    检测；season 互译键已就绪 condition_engine L164）；§八 批9 路9B
    （换季检测 check_changes IF09 复用 → 标记待结算 → 切换季节组 → 恰一次
    on_season_change 触发 + 一行换季文案；普攻/防御兜底零空窗）。
  - 批10 路10A 已落盘：qbot_rpg/core/skill_season.py（SEASONS/SEASON_ANY/
    skill_in_season/validate_skill_action 判定引擎，本文件消费其判定语义）。
  - 模式参考：qbot_rpg/core/resource_lifecycle.py（构造器注入注册表 + 缺省
    {} 兜底 + 零 NoneBot）、qbot_rpg/core/transform_revert.py（纯函数 tick/
    挂点函数 + 状态段携带）、qbot_rpg/core/skill_season.py（ctx 注入 +
    结构化返回）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  P-1  检测通道注入：check_changes 属 engine 层（IF09），core 层 G0 不
       import engine——本引擎经构造器注入 season_now（当前季节读取器）与
       season_idx（当前季节索引）双通道；世界时间引擎联动（season_now
       = worldtime.season_now / season_idx = worldtime.cycle_tick("season")
       或 time_state.season_idx 缓存）由装配层接线时注入，引擎零 import。
  P-2  生效季节状态段：换季状态落在 battle_state 顶层键 battle_season
       （结构 {season, pending}；pending=True = 换季待结算标记）。
       season 字段 = 当前生效季节（行动校验消费的「当前季节组」引用）；
       pending = 本回合已检测到差异但尚未切换（D-05 待结算期）。
       战斗开始缺省：season=SEASON_ANY（无季节环境全技能可用，EFF-1
       战斗外口径延伸），pending=False。
  P-3  检测时序（F-R2 ②）：detect_season_change 在回合开始懒重读时调用
       （对齐 EFF-5「引用在回合开始懒重读时更新」）——当前季节 ≠ 生效
       季节 → 置 pending=True（本回合不变更，行动照旧组校验 SC-1）；
       当前季节 == 生效季节 → 清 pending（幂等复位，SC-3）。
  P-4  切换时点（F-R2 ③）：settle_season_change 在回合结束 tick 之后、
       下一回合开始之前调用（battle.end_turn ⑥⑦ 之间挂点）——仅当
       pending=True 且存在可切换目标时切换：生效季节 ← 当前季节，
       pending 复位 False；返回切换事件 {switched, season, from, to,
       message_key, on_season_change}（on_season_change=True = 装配层
       触发四时调和 proc 的信号，恰一次 E5）。非 pending 调用 → 幂等
       无操作（switched=False）。
  P-5  保留项零触碰（F-R2 ④）：切换仅改 battle_season 段，MP/连段/印记/
       冷却/buff 段不读不写——「全保留」由不触碰天然成立，本引擎零
       拷贝零清理（与 resource_lifecycle 被控保留同精神）。
  P-6  展示过滤（EFF-3）：filter_skills 消费 skill_in_season 判定——输出
       {skill_id, season, available, grayscale, hint_key}；非当季技能
       grayscale=True + hint_key=SEASON_HINT_KEY（「此术式与当前时节
       不合」文案键，模糊提示不写条件公式 EFF-3；文案渲染归展示层模板，
       本引擎零模板输出）。普攻/防御指令（type=basic / guard）不参与
       季节过滤（全年可用，EFF-3 兜底）；基本技条目过滤时恒放行。
  P-7  战斗外换季（F-R2 ⑥）：本引擎只处理战斗内换季状态；战斗外换季
       无技能组概念、不触发任何切换——装配层在战斗外不调用本引擎
       （detect/settle 均只操作 battle_state 段，无战斗快照即无操作
       降级返回，防御）。
  P-8  换季反馈文案：返回 message_key=SEASON_CHANGE_MESSAGE_KEY（语义
       键，一行换季文案「本轮消息附一行」F-R2 ⑤）；具体文案（含季节
       中文名）由展示层模板消费本引擎返回的 from/to 渲染，本引擎零
       模板输出。
  P-9  零定时器/零睡眠：本引擎不含任何 sleep/定时器字面量——换季检测
       依赖注入的当前季节快照值，切换时点由战斗层回合边界驱动，引擎
       零时间依赖零轮询。
  P-10 大小写敏感（对齐 6c D-06）：season 值比较一律精确字符串比较；
       注入的当前季节非四枚举 → 回落 SEASON_ANY（无季节环境兜底，
       全技能可用，与 skill_season.parse_season 同口径）。

铁律：零 NoneBot import（G0 门禁）；core 层只依赖 data（季节经注入通道，
零 import engine/content）；纯函数确定性（同刻同参必同值）；完整类型标注
（typing 3.9 兼容）；零定时器/零睡眠（本文件不含任何 sleep/定时器字面量
——引擎零定时器零睡眠，无时间依赖）；不引入随机；不 git commit；只写
本文件 + 自己的测试。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple

# =====================================================================================
# 常量（细化_6c §2.3 F-R2 / §2.2 EFF-3 契约口径）
# =====================================================================================

# 四季枚举（对齐 skill_season.SEASONS；顺序即换季循环序）
SEASONS: Tuple[str, ...] = ("spring", "summer", "autumn", "winter")

# 通用季节（缺省 = 通用 = 全年可用；无季节环境兜底）
SEASON_ANY: str = "general"

# battle_state 顶层换季状态段键（P-2：battle_season = {season, pending}）
BATTLE_SEASON_KEY: str = "battle_season"

# battle_season 段内键（P-2）
SEASON_STATE_KEY: str = "season"      # 当前生效季节（行动校验消费引用）
PENDING_STATE_KEY: str = "pending"    # 换季待结算标记（D-05 待结算期）

# ctx 当前季节键（装配层注入 worldtime.season_now；懒重读数据源，对齐
# skill_season.SEASON_CTX_KEY 同键名，单口登记防碎片化）
SEASON_CTX_KEY: str = "season_now"

# ctx 当前季节索引键（装配层注入 worldtime.cycle_tick("season") 或
# time_state.season_idx；P-1 检测通道索引通道，可选）
SEASON_IDX_CTX_KEY: str = "season_idx"

# 展示过滤提示语义键（EFF-3：非当季技能置灰提示「此术式与当前时节不合」，
# 模糊提示不写条件公式；文案渲染归展示层模板）
SEASON_HINT_KEY: str = "season_mismatch"

# 换季一行反馈语义键（F-R2 ⑤：切换时本轮消息附一行换季文案；模板可配，
# 只报状态不教规则——具体文案由展示层消费 from/to 渲染，P-8）
SEASON_CHANGE_MESSAGE_KEY: str = "season_change"

# on_season_change 事件信号键（F-R2 ⑤ / E1：切换完成时返回 True，装配层
# 据此触发四时调和 proc；恰一次 E5/SC-3）
ON_SEASON_CHANGE_KEY: str = "on_season_change"

# 技能 type 过滤豁免（EFF-3 兜底：basic=普攻「四时术」全年可用；
# guard/defense=防御指令全年可用，F-R2 ④ 零空窗）
_TYPE_BASIC: Tuple[str, ...] = ("basic",)
_TYPE_GUARD: Tuple[str, ...] = ("guard", "defense")


# =====================================================================================
# battle_season 状态段读写（P-2：惰性建段 + 防御降级）
# =====================================================================================


def _season_state_of(battle_state: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """读 battle_season 段（缺段/非 Mapping → 空骨架，不改引用）。"""
    raw = battle_state.get(BATTLE_SEASON_KEY) if isinstance(battle_state, Mapping) else None
    if isinstance(raw, MutableMapping):
        return raw
    return {}


def init_battle_season(
    battle_state: MutableMapping[str, Any],
    season: Optional[str] = None,
) -> Dict[str, Any]:
    """战斗开始初始化换季状态段（EFF-2 进战懒加载；P-2 缺省骨架）。

    入参：
      battle_state —— 战斗快照 dict（就地写 battle_season 段）；
      season       —— 初始生效季节（进战当前季节；缺省 SEASON_ANY）。
    出参：battle_season 段 dict {season, pending}（就地写入 battle_state）。
    语义：覆盖式写入（战斗开始重复调用幂等）；season 非法 → 回落
      SEASON_ANY（P-10 防御，无季节环境 = 全技能可用 EFF-1 精神）。
    """
    norm = _normalize_season(season)
    seg: Dict[str, Any] = {
        SEASON_STATE_KEY: norm,
        PENDING_STATE_KEY: False,
    }
    if isinstance(battle_state, MutableMapping):
        battle_state[BATTLE_SEASON_KEY] = seg
    return seg


def effective_season(battle_state: Mapping[str, Any]) -> str:
    """当前生效季节（行动校验消费引用：技能 ∈ 生效季节组 ∪ 通用组）。

    战斗开始未 init / 段缺失 → SEASON_ANY（P-2 缺省兜底，全技能可用，
    零空窗）；段内 season 非法 → 回落 SEASON_ANY（P-10 防御）。
    """
    seg = _season_state_of(battle_state)
    return _normalize_season(seg.get(SEASON_STATE_KEY))


def pending_flag(battle_state: Mapping[str, Any]) -> bool:
    """换季待结算标记（D-05 待结算期：True = 本回合已检测差异未切换）。"""
    seg = _season_state_of(battle_state)
    return bool(seg.get(PENDING_STATE_KEY, False))


def _normalize_season(value: Any) -> str:
    """季节值归一（P-10：四枚举原样；缺省/非法/大小写变体 → SEASON_ANY）。"""
    if isinstance(value, str) and value in SEASONS:
        return value
    return SEASON_ANY


# =====================================================================================
# 战斗内换季检测（F-R2 ① 懒重读 + ② 检测标记待结算；P-3）
# =====================================================================================


def detect_season_change(
    battle_state: MutableMapping[str, Any],
    current_season: Any,
) -> Dict[str, Any]:
    """回合开始懒重读检测（F-R2 ②）：当前季节 ≠ 生效季节 → 标记待结算。

    入参：
      battle_state   —— 战斗快照 dict（就地改 battle_season.pending）；
      current_season —— 懒重读的当前世界季节（装配层注入 worldtime.
                        season_now；非四枚举 → SEASON_ANY 兜底 P-10）。
    出参：检测结果 dict：
      {changed, pending, season, detected}
      - changed=True：当前季节 ≠ 生效季节 → pending 置 True（本回合
        不变更，行动照旧组校验 D-05/SC-1）；
      - changed=False：当前季节 == 生效季节 → pending 复位 False
        （SC-3 幂等：连续两回合同季节无差异不标记）。
      detected 恒等于 changed（本次检测是否检测到差异的语义键）。
    语义：本方法只改 pending 标记，不切换生效季节（切换归
      settle_season_change，P-4）；战斗结束/无 battle_season 段 → 惰性
      建段后检测（防御，战斗层每回合调用前先 init）。
    """
    if not isinstance(battle_state, MutableMapping):
        return {"changed": False, "pending": False, "season": SEASON_ANY,
                "detected": False}
    seg = battle_state.get(BATTLE_SEASON_KEY)
    if not isinstance(seg, MutableMapping):
        seg = init_battle_season(battle_state)
    cur = _normalize_season(current_season)
    eff = _normalize_season(seg.get(SEASON_STATE_KEY))
    changed = cur != eff
    seg[PENDING_STATE_KEY] = changed
    return {
        "changed": changed,
        "pending": changed,
        "season": cur,
        "detected": changed,
    }


# =====================================================================================
# 换季结算切换（F-R2 ③ 结算边界：回合结束 tick 之后、下一回合开始之前；P-4）
# =====================================================================================


def settle_season_change(
    battle_state: MutableMapping[str, Any],
    current_season: Any,
) -> Dict[str, Any]:
    """换季结算切换（F-R2 ③ 结算边界挂点函数）。

    调用时点：回合结束 tick 之后、下一回合开始之前（battle.end_turn
      ⑥⑦ 之间挂点）——仅当 pending=True（本回合检测到差异、待结算期
      已按旧组校验完毕）且存在可切换目标时切换。

    入参：
      battle_state   —— 战斗快照 dict（就地改 battle_season：生效季节 ←
                        当前季节，pending 复位 False）；
      current_season —— 当前世界季节（懒重读值；非四枚举 → SEASON_ANY
                        兜底 P-10）。
    出参：切换结果 dict（P-4/P-8）：
      {switched, season, from, to, pending, message_key, on_season_change}
      - switched=True：已切换（生效季节 ← 当前季节，pending 复位）；
        返回 from=旧生效季节 / to=新生效季节 / message_key=
        SEASON_CHANGE_MESSAGE_KEY（一行换季文案语义键）/ on_season_change=
        True（装配层触发四时调和 proc 的信号，恰一次 E5/SC-3）；
      - switched=False：未切换（非 pending 幂等无操作，SC-3；或
        当前季节 == 生效季节无差异），message_key/on_season_change
        恒 False/空。
    语义：切换只改 battle_season 段——MP/连段/印记/冷却/buff 全保留
      （P-5 零触碰，F-R2 ④）；战斗结束/段缺失 → 惰性建段后幂等判定
      （防御）；切换在当回合行动阶段之后发生 → 待结算期旧组校验已
      完成，新季节下一回合开始生效（D-05）。
    """
    if not isinstance(battle_state, MutableMapping):
        return {
            "switched": False, "season": SEASON_ANY, "from": None, "to": None,
            "pending": False, "message_key": "", "on_season_change": False,
        }
    seg = battle_state.get(BATTLE_SEASON_KEY)
    if not isinstance(seg, MutableMapping):
        seg = init_battle_season(battle_state)
    cur = _normalize_season(current_season)
    eff = _normalize_season(seg.get(SEASON_STATE_KEY))
    pending = bool(seg.get(PENDING_STATE_KEY, False))
    if not pending:
        # SC-3 幂等：无待结算标记（未检测差异 / 已切换）→ 无操作
        return {
            "switched": False, "season": eff, "from": None, "to": None,
            "pending": False, "message_key": "", "on_season_change": False,
        }
    if cur == eff:
        # 防御：pending 但当前季节 == 生效季节（检测与结算间世界季节
        # 又轮转回来）→ 无差异不切换，复位 pending（SC-3 恰一次）
        seg[PENDING_STATE_KEY] = False
        return {
            "switched": False, "season": eff, "from": None, "to": None,
            "pending": False, "message_key": "", "on_season_change": False,
        }
    old = eff
    seg[SEASON_STATE_KEY] = cur
    seg[PENDING_STATE_KEY] = False
    return {
        "switched": True,
        "season": cur,
        "from": old,
        "to": cur,
        "pending": False,
        "message_key": SEASON_CHANGE_MESSAGE_KEY,
        "on_season_change": True,
    }


# =====================================================================================
# 展示过滤（EFF-3：非当季技能置灰 + 普攻/防御兜底全年可用；P-6）
# =====================================================================================


def _skill_type_of(skill: Any) -> Optional[str]:
    """技能条目 type 字段读取（Mapping 直取 / 协议对象属性取；缺省 None）。"""
    if isinstance(skill, Mapping):
        v = skill.get("type")
    elif skill is not None and hasattr(skill, "type"):
        v = getattr(skill, "type")
        v = v() if callable(v) else v
    else:
        return None
    return v if isinstance(v, str) and v else None


def _skill_season_of(skill: Any) -> str:
    """技能条目 season 字段读取（缺省 SEASON_ANY；防御回落）。"""
    if isinstance(skill, Mapping):
        v = skill.get("season")
    elif skill is not None and hasattr(skill, "season"):
        v = getattr(skill, "season")
        v = v() if callable(v) else v
    else:
        v = None
    return _normalize_season(v)


def _skill_id_of(skill: Any) -> Optional[str]:
    """技能条目 id 字段读取（非字符串/空 → None，防御）。"""
    if isinstance(skill, Mapping):
        v = skill.get("id")
    elif skill is not None and hasattr(skill, "id"):
        v = getattr(skill, "id")
        v = v() if callable(v) else v
    else:
        v = None
    return v if isinstance(v, str) and v else None


def filter_skills(
    skills: Any,
    season: Any,
) -> List[Dict[str, Any]]:
    """技能列表展示过滤（EFF-3：非当季置灰 + 提示；普攻/防御兜底）。

    入参：
      skills —— 技能条目列表（Mapping / 协议对象均可，G0 注入；
                非列表 → 空列表，防御降级）；
      season —— 当前季节（四枚举之一；SEASON_ANY → 全部可用）。
    出参：按输入顺序的过滤结果列表，每项：
      {skill_id, season, available, grayscale, hint_key}
      - available=True：可用（当季技能 / 通用技能 / 普攻 basic / 防御
        guard 全年可用 EFF-3 兜底）；
      - grayscale=True：非当季技能置灰标记（EFF-3：供 /技能 展示消费，
        置灰 + 「此术式与当前时节不合」提示）；
      - hint_key=SEASON_HINT_KEY：提示语义键（非当季技能；文案渲染归
        展示层模板，零模板输出）；available=True 时 hint_key 为空串。
    语义：普攻（type=basic）与防御（type=guard/defense）不参与季节过滤
      ——全年可用（EFF-3/F-R2 ④ 兜底零空窗，换季空窗零技能可用时
      普攻/防御仍可用）；season=SEASON_ANY 时全部技能 available=True
      （EFF-1 战斗外口径：无季节组概念）。
    """
    norm = _normalize_season(season)
    out: List[Dict[str, Any]] = []
    if not isinstance(skills, (list, tuple)):
        return out
    for skill in skills:
        sk = _skill_season_of(skill)
        stype = _skill_type_of(skill)
        if norm == SEASON_ANY:
            available = True  # 无季节环境 = 全部可用（EFF-1 精神，P-10）
        elif stype in _TYPE_BASIC or stype in _TYPE_GUARD:
            available = True  # 普攻/防御兜底全年可用（EFF-3，F-R2 ④）
        else:
            available = sk in (norm, SEASON_ANY)
        out.append({
            "skill_id": _skill_id_of(skill),
            "season": sk,
            "available": available,
            "grayscale": not available,
            "hint_key": "" if available else SEASON_HINT_KEY,
        })
    return out


# =====================================================================================
# 季节过滤快捷（skill_season.skill_in_season 的展示侧消费；对齐 10A 判定语义）
# =====================================================================================


def skill_available(
    skill: Any,
    season: Any,
) -> bool:
    """单技能当季可用判定（EFF-3 展示/行动侧共用）。

    入参：skill —— 技能条目（Mapping / 协议对象）；season —— 当前季节。
    出参：bool —— True = 可用（当季 / 通用 / 普攻 basic / 防御 guard）；
      False = 非当季置灰。
    语义：与 filter_skills 同口径（普攻/防御兜底豁免；SEASON_ANY 全可用），
      供展示层/行动校验侧直接消费。
    """
    norm = _normalize_season(season)
    if norm == SEASON_ANY:
        return True
    stype = _skill_type_of(skill)
    if stype in _TYPE_BASIC or stype in _TYPE_GUARD:
        return True
    return _skill_season_of(skill) in (norm, SEASON_ANY)


# =====================================================================================
# 挂点辅助（battle.py 接线用：end_turn tick 后 settle、回合开始 detect）
# =====================================================================================


def tick_season_boundary(
    battle_state: MutableMapping[str, Any],
    current_season: Any,
) -> Dict[str, Any]:
    """换季结算边界挂点（battle.end_turn ⑥ tick 之后调用，F-R2 ③）。

    组合 detect + settle 的便捷入口：回合结束 tick 后先补一次检测
    （懒重读当前季节，对齐 F-R2 ① 每回合重读语义），若标记待结算则
    立即切换（本回合行动阶段已结束，旧组校验已完成，D-05 切换时点
    成立）。等价于先 detect_season_change 再 settle_season_change，
    幂等无副作用（未检测差异 → settle 无操作 SC-3）。

    入参：battle_state —— 战斗快照 dict；current_season —— 当前世界
      季节（懒重读值）。
    出参：settle_season_change 结果 dict（switched 语义同上；未切换 →
      switched=False）。
    """
    if not isinstance(battle_state, MutableMapping) or not battle_state:
        # 无战斗快照（战斗外/已结束）→ 降级无操作（F-R2 ⑥ / P-7）
        return {"switched": False, "season": SEASON_ANY, "from": None,
                "to": None, "pending": False, "message_key": "",
                ON_SEASON_CHANGE_KEY: False}
    detect_season_change(battle_state, current_season)
    return settle_season_change(battle_state, current_season)


__all__ = [
    # 常量
    "SEASONS",
    "SEASON_ANY",
    "BATTLE_SEASON_KEY",
    "SEASON_STATE_KEY",
    "PENDING_STATE_KEY",
    "SEASON_CTX_KEY",
    "SEASON_IDX_CTX_KEY",
    "SEASON_HINT_KEY",
    "SEASON_CHANGE_MESSAGE_KEY",
    "ON_SEASON_CHANGE_KEY",
    # 状态段读写
    "init_battle_season",
    "effective_season",
    "pending_flag",
    # 换季检测（F-R2 ②）
    "detect_season_change",
    # 换季结算切换（F-R2 ③）
    "settle_season_change",
    # 展示过滤（EFF-3）
    "filter_skills",
    "skill_available",
    # 挂点辅助
    "tick_season_boundary",
]
