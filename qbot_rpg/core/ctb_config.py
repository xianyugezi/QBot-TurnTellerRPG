"""CTB 配置装配层（内容包 recovery 解析 + 规则配置构造 + settings 读取）。

归属：CTB 重写 · 架构修复（2026-09-10 主 Agent）。
拆分由来：原 `qbot_rpg/data/ctb.py` 同时承载「数据」与「逻辑」，且 `data` 层
import `core` 违反 TC-03 依赖矩阵（`data` 允许依赖集 = `set()`，细化_3a §1.4）。
现按分层契约拆为：

  - `qbot_rpg/data/ctb.py`      —— **纯数据**（种类标识 / 默认恢复值 / 键名 / 默认 settings）
  - `qbot_rpg/core/ctb_config.py`（本文件）—— **装配逻辑**（解析 / 合并 / 构造配置）

本层属 core，按 §1.4 可依赖 `data` 与 `core` 自身，故可自由组合两者。

依据：
  - docs/ctb/02_wave_a_decisions.md 裁决 1（recovery = 总行动恢复值，覆盖关系）
  - docs/ctb/01_asset_inventory.md §0.2 事件位点词典
  - 细化_3a §1.4 依赖矩阵 + §3.2 契约类型

职责：
  1) resolve_action_recovery(action, default)   内容包 action def 的 recovery 键解析
  2) default_recovery_for_kind(kind)            按行动种类的默认恢复值查询
  3) build_recovery_table(actions)              内容包 action.json 全量 → {id: recovery} 覆盖表
  4) resolve_recovery_config(source, actions)   组装 CtbRuleConfig（基础 + 覆盖表）
  5) recovery_for_action(action, config)        行动 → 该行动的总恢复值（引擎注入用）
  6) resolve_ctb_settings(settings) / ctb_enabled(settings)   settings["ctb"] 段读取

内容包 action.json 说明：真实数据文件位于 content/<pack>/action.json（不在源码包内，
由 Registry 装载为 modules_raw["action"]）；本层只做 **schema 读取/默认值兜底**，
不修改任何内容包数据文件。

硬约束（对齐仓库规范）：
  - 零 NoneBot import；仅标准库 + qbot_rpg.core.ctb_rules + qbot_rpg.data.ctb。
  - 无 IO / 无随机 / 无定时器；同刻同参必同值；异常一律兜底不崩。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from qbot_rpg.core.ctb_rules import (
    DEFAULT_ACTION_TIME,
    DEFAULT_AIR_EXTEND,
    DEFAULT_AIR_TIME,
    DEFAULT_RECOVERY,
    DEFAULT_TURN_COST,
    TIME_UNIT,
    CtbRuleConfig,
    recovery_for,
    resolve_rule_config,
)
from qbot_rpg.data.ctb import (
    ACTION_RECOVERY_TABLE,
    DEFAULT_ACTION_RECOVERY,
    DEFAULT_CTB_SETTINGS,
    RECOVERY_KEY,
    RECOVERY_KEY_CN,
    ActionRecoveryTable,
)
from qbot_rpg.data.ctb import DEFAULT_ACTION_TIME as DATA_DEFAULT_ACTION_TIME
from qbot_rpg.data.ctb import DEFAULT_AIR_EXTEND as DATA_DEFAULT_AIR_EXTEND
from qbot_rpg.data.ctb import DEFAULT_AIR_TIME as DATA_DEFAULT_AIR_TIME
from qbot_rpg.data.ctb import DEFAULT_TIME_UNIT as DATA_DEFAULT_TIME_UNIT
from qbot_rpg.data.ctb import DEFAULT_TURN_COST as DATA_DEFAULT_TURN_COST

__all__ = [
    "resolve_action_recovery",
    "default_recovery_for_kind",
    "build_recovery_table",
    "resolve_recovery_config",
    "recovery_for_action",
    "resolve_ctb_settings",
    "ctb_enabled",
]

_logger = logging.getLogger("qbot_rpg.core.ctb_config")

#: recovery 键的中英候选（与 data/ctb.py 常量同口径）
_RECOVERY_KEYS = (RECOVERY_KEY, RECOVERY_KEY_CN)


# ---------------------------------------------------------------------------
# 零、数据/规则数值一致性校验（防 data 层与 core 层两处落值漂移）
# ---------------------------------------------------------------------------
def _assert_no_value_drift() -> None:
    """校验 data 层字面量与 core 规则常量一致（不一致 → 记日志，不抛错）。

    data/ctb.DEFAULT_ACTION_RECOVERY 与 core/ctb_rules.DEFAULT_RECOVERY 是**分层
    职责分离**的两处同名值（data 给字面量、core 给运行期规则）。本函数在装配时
    做一次比对，若未来有人只改一边，日志会立刻暴露。
    """
    try:
        if float(DEFAULT_ACTION_RECOVERY) != float(DEFAULT_RECOVERY):
            _logger.warning(
                "CTB 默认恢复值存在分层漂移：data.DEFAULT_ACTION_RECOVERY=%s "
                "vs core.DEFAULT_RECOVERY=%s（请同步两处）",
                DEFAULT_ACTION_RECOVERY, DEFAULT_RECOVERY,
            )
        if float(DATA_DEFAULT_TIME_UNIT) != float(TIME_UNIT):
            _logger.warning(
                "CTB 时间单位存在分层漂移：data.DEFAULT_TIME_UNIT=%s "
                "vs core.TIME_UNIT=%s（请同步两处）",
                DATA_DEFAULT_TIME_UNIT, TIME_UNIT,
            )
        if float(DATA_DEFAULT_ACTION_TIME) != float(DEFAULT_ACTION_TIME):
            _logger.warning(
                "CTB 行动时间缺省存在分层漂移：data.DEFAULT_ACTION_TIME=%s "
                "vs core.DEFAULT_ACTION_TIME=%s（请同步两处）",
                DATA_DEFAULT_ACTION_TIME, DEFAULT_ACTION_TIME,
            )
        if float(DATA_DEFAULT_AIR_TIME) != float(DEFAULT_AIR_TIME):
            _logger.warning(
                "CTB 跃空维持存在分层漂移：data.DEFAULT_AIR_TIME=%s "
                "vs core.DEFAULT_AIR_TIME=%s（请同步两处）",
                DATA_DEFAULT_AIR_TIME, DEFAULT_AIR_TIME,
            )
        if float(DATA_DEFAULT_AIR_EXTEND) != float(DEFAULT_AIR_EXTEND):
            _logger.warning(
                "CTB 空中延长存在分层漂移：data.DEFAULT_AIR_EXTEND=%s "
                "vs core.DEFAULT_AIR_EXTEND=%s（请同步两处）",
                DATA_DEFAULT_AIR_EXTEND, DEFAULT_AIR_EXTEND,
            )
        if float(DATA_DEFAULT_TURN_COST) != float(DEFAULT_TURN_COST):
            _logger.warning(
                "CTB 转向成本存在分层漂移：data.DEFAULT_TURN_COST=%s "
                "vs core.DEFAULT_TURN_COST=%s（请同步两处）",
                DATA_DEFAULT_TURN_COST, DEFAULT_TURN_COST,
            )
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("_assert_no_value_drift 失败")


_assert_no_value_drift()


# ---------------------------------------------------------------------------
# 一、内容包 action def 的 recovery 解析
# ---------------------------------------------------------------------------
def _lookup_raw(action: Any, key: str) -> Any:
    """从 action def（Mapping / 对象）取键；缺失 → None。"""
    if isinstance(action, Mapping):
        return action.get(key)
    return getattr(action, key, None)


def _coerce_recovery(value: Any) -> Optional[float]:
    """把 recovery 值规范为 float；不可用 → None（bool 视为非法数值）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def _action_kind(action: Any) -> str:
    """取 action 的种类标识（缺省空串）。"""
    raw = _lookup_raw(action, "kind")
    if raw is None:
        raw = _lookup_raw(action, "type")
    return str(raw or "").strip().lower()


def default_recovery_for_kind(kind: Any) -> float:
    """按行动种类取默认恢复值（未命中 → DEFAULT_ACTION_RECOVERY）。

    :param kind: 行动种类（basic/skill/item/guard/flee；大小写不敏感）
    :return: 该种类的默认总恢复值
    """
    try:
        key = str(kind or "").strip().lower()
        return float(ACTION_RECOVERY_TABLE.get(key, DEFAULT_ACTION_RECOVERY))
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("default_recovery_for_kind 失败，回退 DEFAULT_ACTION_RECOVERY")
        return float(DEFAULT_ACTION_RECOVERY)


def resolve_action_recovery(action: Any, *, default: Any = None) -> float:
    """解析单个 action 的**总**行动恢复值。

    优先级（覆盖关系）：裸值 → action 显式 recovery 键 → kind 种类表 → 兜底默认值。

    :param action: action def（Mapping / 对象 / **裸数值**；内容包 action.json 的一条）
    :param default: 调用方指定的兜底值（None → DEFAULT_ACTION_RECOVERY）
    :return: 该 action 的总恢复值（绝不抛错）
    """
    try:
        # 裸数值（int/float）→ 直接视作该 action 的总恢复值
        if isinstance(action, (int, float)) and not isinstance(action, bool):
            v = _coerce_recovery(action)
            if v is not None:
                return v
        for key in _RECOVERY_KEYS:
            v = _coerce_recovery(_lookup_raw(action, key))
            if v is not None:
                return v
        if default is not None:
            d = _coerce_recovery(default)
            if d is not None:
                return d
        return default_recovery_for_kind(_action_kind(action))
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("resolve_action_recovery 失败，回退 DEFAULT_ACTION_RECOVERY")
        return float(DEFAULT_ACTION_RECOVERY)


# ---------------------------------------------------------------------------
# 二、内容包全量 → recovery 覆盖表
# ---------------------------------------------------------------------------
def build_recovery_table(actions: Any = None) -> ActionRecoveryTable:
    """把内容包 action 定义全量解析为 {action 标识: recovery} 覆盖表。

    仅供 `CtbRuleConfig(recovery_table=...)` 注入；**只收录显式给出 recovery 键**的
    action（未给键的走种类表/默认值，不进覆盖表，保持表精简）。

    :param actions: action 定义集合（Mapping{id: def} / 序列[{id,name,...}] / None）
    :return: {action 标识: 总恢复值}（异常 → 空表）
    """
    try:
        table: Dict[str, float] = {}
        if actions is None:
            return table
        items: Iterable[Tuple[Any, Any]]
        if isinstance(actions, Mapping):
            items = actions.items()
        else:
            _pairs: List[Tuple[Any, Any]] = []
            for i, a in enumerate(actions or ()):
                if isinstance(a, Mapping):
                    aid = a.get("id") or a.get("action_id") or a.get("key")
                    _pairs.append((aid if aid is not None else str(i), a))
            items = _pairs
        for aid, adef in items:
            if aid is None:
                continue
            rec: Optional[float] = None
            for key in _RECOVERY_KEYS:
                rec = _coerce_recovery(_lookup_raw(adef, key))
                if rec is not None:
                    break
            if rec is not None:
                table[str(aid)] = rec
        return table
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("build_recovery_table 失败，回退空覆盖表")
        return {}


# ---------------------------------------------------------------------------
# 三、组装 CTB 规则配置
# ---------------------------------------------------------------------------
def resolve_recovery_config(source: Any = None, actions: Any = None) -> CtbRuleConfig:
    """组装 CTB 规则配置：ctb_rules 缺省 + 本层「按 kind 的默认恢复值」+ 内容包覆盖表。

    合并顺序（后者覆盖前者，均为**覆盖**关系）：
      1) ctb_rules.resolve_rule_config(source) 的基础配置（settings 段可覆盖公式三参）；
      2) 内容包 action.json 全量解析出的 recovery 覆盖表（build_recovery_table）；
      3) 若 source 已自带 recovery_table，则与本层解析结果合并（source 优先）。

    :param source: 配置来源（CtbRuleConfig / settings Mapping / None）
    :param actions: 内容包 action.json 定义序列（None → 不注入覆盖表）
    :return: 规范化后的 CtbRuleConfig（绝不抛错）
    """
    try:
        base = resolve_rule_config(source)
        merged: Dict[str, float] = dict(build_recovery_table(actions))
        if base.recovery_table:
            merged.update(dict(base.recovery_table))  # source 显式覆盖优先
        if not merged:
            return base
        return CtbRuleConfig(
            speed_reference=base.speed_reference,
            min_speed=base.min_speed,
            action_delay=base.action_delay,
            default_recovery=base.default_recovery,
            recovery_table=merged,
        )
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("resolve_recovery_config 失败，回退默认规则配置")
        return CtbRuleConfig()


def recovery_for_action(action: Any, config: Optional[CtbRuleConfig] = None) -> float:
    """取某 action 在给定配置下的**总**行动恢复值（引擎注入点用）。

    :param action: action def 或 action 标识（str）
    :param config: 规则配置（None → 默认配置）
    :return: 该 action 的总恢复值
    """
    try:
        return float(recovery_for(action, config))
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("recovery_for_action 失败，回退默认值解析")
        return resolve_action_recovery(action)


# ---------------------------------------------------------------------------
# 四、settings["ctb"] 段读取
# ---------------------------------------------------------------------------
def resolve_ctb_settings(settings: Any = None) -> Dict[str, Any]:
    """读取 settings 的 "ctb" 段（与 DEFAULT_CTB_SETTINGS 合并；缺省 → 默认）。

    :param settings: 全量 settings（Mapping / 对象 / None）
    :return: 合并后的 ctb 段（绝不抛错）
    """
    try:
        out: Dict[str, Any] = dict(DEFAULT_CTB_SETTINGS)
        seg: Any = None
        if isinstance(settings, Mapping):
            seg = settings.get("ctb")
        elif settings is not None:
            seg = getattr(settings, "ctb", None)
        if isinstance(seg, Mapping):
            out.update(dict(seg))
        return out
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("resolve_ctb_settings 失败，回退默认 ctb 段")
        return dict(DEFAULT_CTB_SETTINGS)


def ctb_enabled(settings: Any = None) -> bool:
    """CTB 总开关（settings["ctb"]["enabled"]；缺省 True）。

    False → 供灰度/回滚开关使用。

    :param settings: 全量 settings（Mapping / 对象 / None）
    :return: 是否启用 CTB
    """
    try:
        return bool(resolve_ctb_settings(settings).get("enabled", True))
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("ctb_enabled 失败，回退 True")
        return True
