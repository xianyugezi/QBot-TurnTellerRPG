"""公式安全求值引擎（M1 · core/formula_engine.py）—— JS 表达式沙箱 + 中文占位符 + AST 黑名单 + 10ms 超时兜底。

依据（勿编造行号，仅引节号）：
  - 《效果表达式变量体系定稿》v1.2 §1.1（公式=JS 表达式）、§1.2（vm.runInNewContext 隔离 /
    AST 黑名单 / 4KB 长度 / 结果类型白名单 / 10ms 超时 / 失败兜底 / 随机数一致性）、
    §1.5（求值时机表：非事件时点 [本次*]=0 显式声明 → F-4）、
    §二 变量大全 ①基础属性 ②战斗状态 ③战斗情境/事件 ④长线进度 ⑤印记/连段/状态 ⑥制造侧、
    §四（只建议不限制：未知占位符 → 0 + warning）
  - 《细化_1b_效果系统契约》§5 F 组 F-1~F-5（F-6 为校验器侧 int/string 双路径，不在此引擎）
  - qbot_rpg/content/validator.py check_formula（M0 词法扫描安全例外，语义对齐：长度上限 4096 /
    FORMAT_BLACKLIST / new 表达式；本模块为其后续升级复用点，validate_expr 返回同构 dict）

安全三层设计（对应定稿 §1.2）：
  1) 执行隔离：调用附带 Node 宿主脚本（本模块同目录 _js_runner.js）以 vm.runInNewContext +
     'use strict' 在只读 JSON 快照沙箱中求值；Python 侧纯函数，零 NoneBot，不读文件/不碰状态。
  2) AST/词法双保险黑名单：JS 感知 tokenizer 扫描 + 字面量剥离正则扫描（双保险），拦截
     constructor / __proto__ / prototype / Function / eval / globalThis / process / require /
     fetch / setTimeout / setInterval / import / module / exports / self / window / document
     （Identifier）与 `new Xxx(...)`（NewExpression）。
  3) 资源上限：公式原始长度 ≤ 4096B；结果类型白名单 int/float（NaN / Infinity / boolean /
     string / 其他类型 = 失败兜底 0）；Node vm 单次求值超时 = 10ms 执行预算 + 冷启动补偿
     （合计 30ms 有效 watchdog；死循环 ≤30ms 真实中断，见 FORMULA_TIMEOUT_MS/_VM_CTX_SLACK_MS）。

失败兜底（§1.2、§四）：运行期异常 / 超时 / 黑名单命中 / 未知占位符 → 返回 0 + warning 收集，
不崩溃。求值期黑名单命中亦返回 0（双保险之运行期侧）。

随机一致性（§1.2「随机数一致性」）：rng_state 注入确定性 PRNG（mulberry32）；同一结算内多次
evaluate 复用同一 seed → 预览/结算一致（F-5）。单次结算内 Math.random 缓存即由此语义达成：
调用方给同一批 evaluate 传入相同 rng_state。

性能专项（F-20 · M1-批2 前置）：求值分三级，公开签名不变——
  ① 占位符展开（现有）→ ② Python 白名单快路径（ast.parse + 白名单节点/名称求值，μs~ms 级，
    大部分公式命中）→ ③ 快路径拒绝/异常才降级既有 Node vm 子进程（安全兜底，不回退语义）。
  快路径白名单：ast.Expression/Constant/BinOp/UnaryOp/Compare/IfExp/List/Tuple/Subscript(数字
  索引) + 名称集合（Math.min/max/floor/ceil/round/abs/sqrt/pow、Math.PI/E、this_battle_round、
  Math.random→mulberry32 确定性 PRNG）。任何白名单外节点/名称/混合类型运算 → 立即降级 Node。
  简单公式（[我方攻击]*2 等）实测 <0.2ms/次（Node 版 ~100-150ms）；黑名单/结果类型/超时/兜底
  语义与 Node 路径完全一致。

┌─────── 共享契约（批1/批2 import 依据）───────
evaluate(expr: str, ctx: EvaluatorCtx) -> float
validate_expr(expr: str) -> Optional[dict]        # None=通过；否则 {"rule":..., ...}（对齐 check_formula）
EvaluatorCtx(attacker: Mapping, target: Mapping, battle: Mapping, rng_state: Optional[int])

ctx 键空间（占位符 → slot.key）：slot ∈ {attacker(我方), target(对方), battle(事件/全局)}。
变量大全全清单映射见 _FIXED_PLACEHOLDERS 与 _PARAM_RULES；未知占位符 → 0 + warning。
额外兼容：定稿 §1.1 示例 v1 的裸标识符 this_battle_round（= battle.round），在 JS 侧作为全局注入。
└────────────────────────────────────────
"""

from __future__ import annotations

import ast
import json
import logging
import math
import os
import random
import re
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

_LOGGER = logging.getLogger("qbot_rpg.formula")

# 公式长度上限（定稿 §1.2 / validator.py FORMULA_MAX_LENGTH=4096）
FORMULA_MAX_LENGTH = 4096
# 单次求值超时（定稿 §1.2：vm timeout 10ms）—— JS 执行预算常量（契约字面值）。
FORMULA_TIMEOUT_MS = 10
# runInNewContext 冷启动补偿：Node v22 实测 vm 上下文/脚本创建耗时 ~15ms，该开销也被计入
# timeout 命中的 watchdog 预算，10ms 字面值会使冷进程中任何公式都被误判超时。补偿后实际
# 传入 vm 的有效预算 = 10 + 20 = 30ms：普通公式执行本身 <1ms 充足富余；`while(true){}` 类
# 死循环仍被 watchdog 以 ≤30ms 真实中断（实证：budget=30/100 时死循环分别于 30/100ms 中断）——
# F-3「超时 -> 0 + 不崩溃」成立。此为对「10ms」的工程化落地（定稿 §1.2 意图=防 CPU 死循环/ReDoS）。
_VM_CTX_SLACK_MS = 20
_VM_EFFECTIVE_TIMEOUT_MS = FORMULA_TIMEOUT_MS + _VM_CTX_SLACK_MS
# 整体子进程兜底超时（仅防 Node 启动/管道挂死/异常路径；JS 求值受上者 watchdog 约束）
_SUBPROCESS_TIMEOUT_S = 20

# AST 黑名单标识符（Identifier；与 validator.py FORMAT_BLACKLIST 对齐）
FORMULA_BLACKLIST: Tuple[str, ...] = (
    "constructor",
    "__proto__",
    "prototype",
    "Function",
    "eval",
    "globalThis",
    "process",
    "require",
    "fetch",
    "setTimeout",
    "setInterval",
    "import",
    "module",
    "exports",
    "self",
    "window",
    "document",
)

# 装备/调合品质档位 → 数值（供 [装备品质:X]/[调合品质] 解析为数值；品质唯一注册表见框架 4.2.2）
_QUALITY_RANK: Mapping[str, int] = {
    "普通": 0,
    "精良": 1,
    "史诗": 2,
    "传说": 3,
}

# 占位符正则：`[...]` 不含嵌套（中文变量体系采用扁平中括号）
_PLACEHOLDER_RE = re.compile(r"\[([^\[\]]+)\]")

# JS 标识符正则（词法扫描用）
_JS_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
# 'new' 之后的标识符为构造器名
_NEW_EXPR_RE = re.compile(r"\bnew\s+([A-Za-z_$][A-Za-z0-9_$]*)")


# -------------------------------------------------------------------------------------
# EvaluatorCtx —— 求值上下文（frozen，纯数据）
# -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluatorCtx:
    """求值上下文（frozen；变量体系定稿 §1.5 / 细化_1b F 组）。

    attacker: 我方（self）快照映射 —— [我方X]/[我方已损失X]/战斗状态/印记/连段/长线进度等。
    target:   对方（enemy）快照映射 —— [对方X]/[对方已损失X]/[对方PV]/[怪物意图] 等。
    battle:   战斗情境/事件映射 —— [当前回合数]/[本次伤害值]/[本次暴击]/[本次命中]/[本场击杀数] 等。
    rng_state: 可选随机种子；传入则 Math.random 为确定性 PRNG（同一结算内复用 → 预览/结算一致，F-5）。
              None 时使用宿主真随机。

    事件内变量（[本次伤害值]/[本次暴击]/[本次命中]）仅 on_attack/on_hit/on_death 等事件结算时点
    存在于 battle；其他时点（on_skill 等）缺失 → 解析为 0 + warning，不报错（F-4，定稿 §1.5）。
    """

    attacker: Mapping[str, object] = field(default_factory=dict)
    target: Mapping[str, object] = field(default_factory=dict)
    battle: Mapping[str, object] = field(default_factory=dict)
    rng_state: Optional[int] = None


# -------------------------------------------------------------------------------------
# 变量大全 → ctx 键空间映射（技能变量体系定稿 §二 ①~⑥）
# -------------------------------------------------------------------------------------

# 固定占位符 → (slot, key)。slot: attacker / target / battle / aloss / tloss
# aloss/tloss: 已损失 = max_<res> - <res>（res ∈ hp/mp）
_FIXED_PLACEHOLDERS: Dict[str, Tuple[str, str]] = {
    # ① 基础属性（我方/对方双套，定稿 §二①）
    "[我方生命上限]": ("attacker", "max_hp"),
    "[我方剩余生命]": ("attacker", "hp"),
    "[我方魔法上限]": ("attacker", "max_mp"),
    "[我方剩余魔法]": ("attacker", "mp"),
    "[我方剩余MP]": ("attacker", "mp"),  # 别名（定稿 §二②）
    "[我方攻击]": ("attacker", "atk"),
    "[我方防御]": ("attacker", "def"),
    "[我方体质]": ("attacker", "con"),
    "[我方精神]": ("attacker", "spr"),
    "[我方力量]": ("attacker", "str"),
    "[我方智力]": ("attacker", "int"),
    "[我方专注]": ("attacker", "foc"),
    "[我方敏捷]": ("attacker", "agi"),
    "[我方幸运]": ("attacker", "lck"),
    "[对方生命上限]": ("target", "max_hp"),
    "[对方剩余生命]": ("target", "hp"),
    "[对方魔法上限]": ("target", "max_mp"),
    "[对方剩余魔法]": ("target", "mp"),
    "[对方攻击]": ("target", "atk"),
    "[对方防御]": ("target", "def"),
    "[对方体质]": ("target", "con"),
    "[对方精神]": ("target", "spr"),
    "[对方力量]": ("target", "str"),
    "[对方智力]": ("target", "int"),
    "[对方专注]": ("target", "foc"),
    "[对方敏捷]": ("target", "agi"),
    "[对方幸运]": ("target", "lck"),
    # 已损失（定稿 §二① 推导式：上限-剩余）
    "[我方已损失生命]": ("aloss", "hp"),
    "[我方已损失魔法]": ("aloss", "mp"),
    "[对方已损失生命]": ("tloss", "hp"),
    "[对方已损失魔法]": ("tloss", "mp"),
    # ② 战斗状态类（定稿 §二②）
    "[我方护盾值]": ("attacker", "shield"),
    "[对方护盾值]": ("target", "shield"),
    "[对方PV]": ("target", "pv"),
    "[对方PV上限]": ("target", "pv_max"),
    "[我方减伤层数]": ("attacker", "mitigation"),
    "[对方减伤层数]": ("target", "mitigation"),
    "[我方格挡状态]": ("attacker", "block"),
    "[我方能量]": ("attacker", "energy"),
    "[我方怒气]": ("attacker", "rage"),
    "[我方剑气]": ("attacker", "sword_qi"),
    "[我方本回合受击次数]": ("attacker", "hit_taken_this_round"),
    "[我方累计伤害]": ("attacker", "dmg_total"),
    "[我方累计受击]": ("attacker", "dmg_taken_total"),
    "[我方连续命中]": ("attacker", "hit_streak"),
    "[我方连续miss]": ("attacker", "miss_streak"),
    "[我方会心率]": ("attacker", "crit_rate"),  # 实时计算（√幸运×0.5%+crit_bonus）由调用方结算
    "[我方上次暴击]": ("attacker", "last_crit"),
    "[我方超会心等级]": ("attacker", "super_crit_lv"),
    # ③ 战斗情境/事件类（定稿 §二③）
    "[当前回合数]": ("battle", "round"),
    "[本场击杀数]": ("battle", "kills"),
    "[本次伤害值]": ("battle", "this_damage"),
    "[本次暴击]": ("battle", "this_crit"),
    "[本次命中]": ("battle", "this_hit"),
    "[怪物意图]": ("target", "intent"),
    "[怪物行动计数]": ("target", "action_count"),
    "[怪物行动状态]": ("target", "action_state"),
    "[当前地图]": ("battle", "map_id"),
    "[BOSS阶段]": ("battle", "boss_phase"),
    # ④ 长线进度/养成类（定稿 §二④；战斗外快照纳入结算引用）
    "[当前等级]": ("attacker", "level"),
    "[当前经验]": ("attacker", "exp"),
    "[金币]": ("attacker", "gold"),
    "[宝石]": ("attacker", "gem"),
    "[图鉴完成度]": ("attacker", "codex_pct"),
    "[签到天数]": ("attacker", "signin_days"),
    "[在线时长]": ("attacker", "online_time"),
    "[离线时长]": ("attacker", "offline_time"),
    # ⑤ 印记/连段/状态（定稿 §二⑤）
    "[我方印记总数]": ("attacker", "marks_total"),
    "[对方印记总数]": ("target", "marks_total"),
    "[我方连段]": ("attacker", "chain_total"),
    # ⑥ 制造侧变量（定稿 §二⑥）
    "[连锁段数]": ("attacker", "combo_steps"),
    "[调合品质]": ("attacker", "craft_quality"),
    "[强化成功率]": ("attacker", "enhance_rate"),
    "[晶石数]": ("attacker", "crystal"),
}

# 参数化占位符前缀 → (slot, 容器key)。[前缀:ID] → slot[key][ID]
_PARAM_RULES: Tuple[Tuple[str, str, str], ...] = (
    ("我方印记:", "attacker", "marks"),
    ("对方印记:", "target", "marks"),
    ("我方状态:", "attacker", "statuses"),
    ("对方状态:", "target", "statuses"),
    ("状态剩余回合:", "attacker", "status_remain_round"),
    ("状态剩余次数:", "attacker", "status_remain_times"),
    ("技能冷却:", "attacker", "skill_cooldown"),
    ("技能就绪:", "attacker", "skill_ready"),
    ("技能连段:", "attacker", "chain"),
    ("货币:", "attacker", "currency"),
    ("熟练度:", "attacker", "prof"),
    ("背包:", "attacker", "bag"),
    ("强化等级:", "attacker", "enhance_lv"),
    ("装备品质:", "attacker", "equip_quality"),
    ("副本通关:", "attacker", "dungeon_clear"),
    ("装饰珠数:", "attacker", "deco"),
)


# -------------------------------------------------------------------------------------
# 词法/AST 黑名单扫描（Python 侧双保险）
# -------------------------------------------------------------------------------------

# 前置标识符是这些关键字时，`/` 开始的是正则字面量而非除法（用于除正则消歧）
_KEYWORDS_BEFORE_REGEX = frozenset(
    {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "do", "else",
     "case", "yield", "await"}
)


def _regex_allowed(prev_code_token: Optional[Tuple[str, str]]) -> bool:
    """判定当前位置的 `/` 是否开始正则字面量（标准启发式：若前一 token 允许表达式开始 → 正则）。"""
    if prev_code_token is None:
        return True
    kind, text = prev_code_token
    if kind == "id":
        return text in _KEYWORDS_BEFORE_REGEX
    if kind == "op":  # 运算符/标点后为表达式起始
        return True
    return False  # 数字/字符串/正则/`)`/`]`/`}` 之后 → 除法


def _skip_quoted(expr: str, i: int, quote: str) -> int:
    """跳过以 expr[i]==quote 开头的字符串/模板整体（含转义），返回跳过后的下标。"""
    n = len(expr)
    i += 1
    while i < n:
        c = expr[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        if c == "\n":
            return i  # 未闭合直接中止（词法边界，交由 Node 语法层兜底）
        i += 1
    return n


def _skip_regex(expr: str, i: int) -> int:
    """跳过正则字面量 /.../flags（处理字符类与转义），返回跳过后的下标。"""
    n = len(expr)
    j = i + 1
    in_class = False
    while j < n:
        c = expr[j]
        if c == "\\":
            j += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            j += 1
            break
        elif c == "\n":
            break
        j += 1
    while j < n and (expr[j].isalpha() or expr[j] in "_$"):
        j += 1
    return j


def _find_template_end(expr: str, i: int) -> int:
    """定位模板字面量收尾反引号下标（expr[i]=='`'），正确处理 ${...} 嵌套；找不到返回 n。"""
    n = len(expr)
    i += 1
    depth: List[int] = []  # 栈记录 ${} 花括号深度
    while i < n:
        c = expr[i]
        if c == "\\":
            i += 2
            continue
        if c == "$" and i + 1 < n and expr[i + 1] == "{":
            depth.append(1)
            i += 2
            continue
        if depth:
            if c == "{":
                depth[-1] += 1
            elif c == "}":
                depth[-1] -= 1
                if depth[-1] == 0:
                    depth.pop()
            elif c in ("'", '"', "`"):
                inner_until = _skip_quoted(expr, i, c)
                i = inner_until
                continue
            i += 1
            continue
        if c == "`":
            return i + 1
        i += 1
    return n


class _ForbiddenHit:
    """黑名单命中记录（可序列化为 check_formula 同构 dict）。"""

    __slots__ = ("rule", "detail")

    def __init__(self, rule: str, detail: Mapping[str, object]) -> None:
        self.rule = rule
        self.detail = dict(detail)

    def as_dict(self) -> Dict[str, object]:
        out: Dict[str, object] = {"rule": self.rule}
        out.update(self.detail)
        return out


def _scan_tokens(expr: str) -> Optional[_ForbiddenHit]:
    """JS 感知 tokenizer 扫描：黑名单 Identifier / NewExpression。返回首次命中或 None。

    跳过字符串/模板纯文本/正则/注释内容；模板 ${...} 插值表达式原样扫描（防绕过，对齐
    validator P1-1 修复目标）。tokenizer 为 Python 侧双保险之第一层；权威隔离由 Node vm 承担。
    """
    i, n = 0, len(expr)
    prev_code: Optional[Tuple[str, str]] = None  # (kind, text) 上一代码 token
    new_seen = False  # 上一代码 token 为 'new' 关键字（NewExpression 检测）
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c == "/" and i + 1 < n:
            nxt = expr[i + 1]
            if nxt == "/":  # 行注释
                j = expr.find("\n", i)
                i = n if j < 0 else j + 1
                continue
            if nxt == "*":  # 块注释
                j = expr.find("*/", i + 2)
                i = n if j < 0 else j + 2
                continue
            if _regex_allowed(prev_code):
                i = _skip_regex(expr, i)
                prev_code = None
                new_seen = False
                continue
        if c in ("'", '"'):
            i = _skip_quoted(expr, i, c)
            prev_code = None
            new_seen = False
            continue
        if c == "`":
            end = _find_template_end(expr, i)
            segment = expr[i:end]
            for inner in _TEMPLATE_CODE_RE.findall(segment):
                hit = _scan_tokens(inner)  # 插值段按其独立代码扫描（prev 重置，可接受的边界近似）
                if hit is not None:
                    return hit
            i = end
            prev_code = None
            new_seen = False
            continue
        m = _JS_IDENT_RE.match(expr, i)
        if m:
            name = m.group(0)
            if name in FORMULA_BLACKLIST:
                return _ForbiddenHit("formula_ast_blacklist", {"identifier": name})
            if new_seen:
                return _ForbiddenHit("formula_new_expression", {"constructor_name": name})
            new_seen = name == "new"
            prev_code = ("id", name)
            i = m.end()
            continue
        new_seen = False
        if c.isdigit() or (c == "." and i + 1 < n and expr[i + 1].isdigit()):
            while i < n and (expr[i].isalnum() or expr[i] in "._eE+-"):
                i += 1
            prev_code = None
            continue
        # 运算符/标点（含多字符运算符）
        op = expr[i]
        if op in "+-=*/%<>&|^!?:,;()[]{}.":
            if i + 1 < n and expr[i : i + 2] in {
                "++", "--", "&&", "||", "**", ">>", "<<", ">=", "<=", "==", "!=", "===", "!==", "=>",
                "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "??", "?.",
            }:
                prev_code = ("op", expr[i : i + 2])
                i += 2
            else:
                prev_code = ("op", op)
                i += 1
            continue
        prev_code = None
        i += 1  # 未识别字符（JS 中多为语法错误），跳过交由 Node 层
    return None


# 模板 ${...} 插值提取（占位段内容重新扫描为代码）
_TEMPLATE_CODE_RE = re.compile(r"\$\{([^{}]*)\}")

# 字面量剥离正则层（双保险之第二层；语义对齐 validator._strip_literals 思路——字符串/模板/注释
# 剥离后 regex 扫描标识符与 `new Xxx`）。用局部极简字面量剥离：仅为补 tokenizer 可能漏网情形。
_LITERALS_STRIP_RE = re.compile(r"`[^`]*`|'[^']*'|\"[^\"]*\"|//[^\n]*|/\*.*?\*/")


def _scan_regex_insurance(expr: str) -> Optional[_ForbiddenHit]:
    """字面量剥离后的正则扫描（双保险）：黑名单标识符 + new 表达式。"""
    stripped = _LITERALS_STRIP_RE.sub(" ", expr)
    for m in _JS_IDENT_RE.finditer(stripped):
        if m.group(0) in FORMULA_BLACKLIST:
            return _ForbiddenHit("formula_ast_blacklist", {"identifier": m.group(0)})
    m = _NEW_EXPR_RE.search(stripped)
    if m is not None:
        return _ForbiddenHit("formula_new_expression", {"constructor_name": m.group(1)})
    return None


# -------------------------------------------------------------------------------------
# 中文占位符解析
# -------------------------------------------------------------------------------------


def _to_number(value: object, key: str, warnings: List[str]) -> object:
    """把解析值规整为 JS 字面量可序列化对象；未知/非数值 → 0 + warning。

    品质类字符串（普通/精良/史诗/传说）映射回档位数值（品质唯一注册表，框架 4.2.2）。
    """
    if isinstance(value, bool):
        return value  # 0/1 布尔保留（JS 中匹配 === 语义与数值语义）
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        rank = _QUALITY_RANK.get(value)
        if rank is not None:
            return rank
        return value  # 意图/行动状态等字符串值原样注入（如 [怪物意图]==='蓄力'）
    warnings.append(f"unknown_value:{key}->{type(value).__name__}")
    return 0


def _slot_map(slot: str, attacker: Mapping[str, object], target: Mapping[str, object],
              battle: Mapping[str, object]) -> Optional[Mapping[str, object]]:
    if slot == "attacker":
        return attacker
    if slot == "target":
        return target
    if slot == "battle":
        return battle
    return None


def _lookup(slot: str, key: str, attacker: Mapping[str, object],
            target: Mapping[str, object], battle: Mapping[str, object]) -> Tuple[object, bool]:
    """返回 (值, found)。aloss/tloss 按 上限-剩余 推导。"""
    if slot == "aloss":
        hi, lo = attacker.get(f"max_{key}"), attacker.get(key)
        if isinstance(hi, (int, float)) and isinstance(lo, (int, float)):
            return hi - lo, True
        return 0, False
    if slot == "tloss":
        hi, lo = target.get(f"max_{key}"), target.get(key)
        if isinstance(hi, (int, float)) and isinstance(lo, (int, float)):
            return hi - lo, True
        return 0, False
    m = _slot_map(slot, attacker, target, battle)
    if m is None:
        return 0, False
    if key in m:
        return m[key], True
    return 0, False


def _resolve_placeholder(name: str, attacker: Mapping[str, object],
                         target: Mapping[str, object], battle: Mapping[str, object],
                         warnings: List[str]) -> object:
    """解析单个中文占位符（name 为不含 `[` `]` 的内文）→ ctx 值；未知 → 0 + warning（定稿 §四 只建议不限制）。"""
    fixed = _FIXED_PLACEHOLDERS.get(f"[{name}]")
    if fixed is not None:
        slot, key = fixed
        value, found = _lookup(slot, key, attacker, target, battle)
        if not found:
            warnings.append(f"unknown_placeholder:[{name}]")
            return 0
        return _to_number(value, f"{slot}.{key}", warnings)
    for prefix, slot, container in _PARAM_RULES:
        if name.startswith(prefix):
            ident = name[len(prefix):]
            m = _slot_map(slot, attacker, target, battle)
            if m is None:
                break
            inner = m.get(container)
            if isinstance(inner, Mapping):
                if ident in inner:
                    return _to_number(inner[ident], f"{slot}.{container}.{ident}", warnings)
                # 泛化引用缺省 → 0 + warning（不崩）
                warnings.append(f"unknown_placeholder:[{name}]")
                return 0
            warnings.append(f"unknown_placeholder:[{name}]")
            return 0
    warnings.append(f"unknown_placeholder:[{name}]")
    return 0


def _expand_placeholders(expr: str, ctx: EvaluatorCtx, warnings: List[str]) -> str:
    """占位符预处理替换为安全字面量引用（定稿 §1.1：`[我方攻击] → ctx 值`，数值/字符串 JSON 字面量）。"""
    attacker, target, battle = ctx.attacker, ctx.target, ctx.battle

    def _replace(m: "re.Match[str]") -> str:
        value = _resolve_placeholder(m.group(1), attacker, target, battle, warnings)
        return json.dumps(value, ensure_ascii=False)

    return _PLACEHOLDER_RE.sub(_replace, expr)


# -------------------------------------------------------------------------------------
# Python 白名单快路径（M1-批2 前置 · formula 性能专项 F-20）
# -------------------------------------------------------------------------------------
# 设计（零新增依赖，Node 降级兜底）：
#   - 占位符展开后的 js_expr 为纯 JS 字面量表达式；用 Python ast.parse 解析为表达式树，
#     仅当整棵树命中下述白名单节点/名称时才用 Python 求值（μs~ms 级），任何不在白名单的
#     节点/名称/混合类型运算 → 立即降级既有 Node vm 子进程（安全兜底，不回退语义）。
#   - 白名单外层已保证的语义：①evaluate_detail 先过 Python 词法/AST 双保险黑名单（eval /
#     constructor / new Xxx ... 原始表达式命中即 0）；②快路径只接受纯字面量/算术/比较/三元/
#     Math 白名单调用 → 天然不可能触达任何黑名单标识符或不安全构造（模板插值/`new`/函数构造等
#     无法通过 ast.parse + 节点白名单，一律降级 Node 由 AST 黑名单 + vm 隔离兜底）。
#   - 随机一致性（定稿 §1.2 / F-5）：Math.random 注入确定性 PRNG（mulberry32，Python 移植与
#     _js_runner.js 逐位一致，实测种子一致时输出完全相同）；单次 evaluate 内多次 Math.random
#     依序消耗同一 PRNG 流（与 Node 单次结算内行为一致）。rng_state 为空 → 宿主真随机。
#   - 结果类型白名单（定稿 §1.2）：布尔/字符串/NaN/Infinity → 0 + warning（对齐 Node 侧）。

# ---- 白名单集合（节点类型 / 运算 / 名称）----
_FAST_BINOPS = frozenset({ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod})  # ** 明确排除→降级 Node
_FAST_UNARYOPS = frozenset({ast.UAdd, ast.USub, ast.Not, ast.Invert})
_FAST_CMPOPS = frozenset({ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE})

# 值节点白名单（ast.Expression / Constant / BinOp / UnaryOp / Compare / IfExp / List / Tuple /
# Subscript(数字索引) / Name / Attribute / Call —— 对应任务白名单，其余节点类型一律降级）
_FAST_CALL_NAMES = frozenset({
    "Math.min", "Math.max", "Math.floor", "Math.ceil", "Math.round",
    "Math.abs", "Math.sqrt", "Math.pow", "Math.random",
})
_FAST_ATTR_NAMES = frozenset(_FAST_CALL_NAMES | {"Math.PI", "Math.E"})
_FAST_ROOT_NAMES = frozenset({"Math", "this_battle_round"})

_MATH_FUNCS = {
    "Math.min": min,
    "Math.max": max,
    "Math.floor": math.floor,
    "Math.ceil": math.ceil,
    "Math.round": lambda x: math.floor(x + 0.5),  # JS Math.round：.5 ≥ 向 +∞（含负数半值）
    "Math.abs": abs,
    "Math.sqrt": math.sqrt,
    "Math.pow": math.pow,
}
_MATH_CONSTS = {"Math.PI": math.pi, "Math.E": math.e}


class _FastReject(Exception):
    """快路径白名单外 / 无法安全求值 → 调用方降级 Node fallback。"""

    __slots__ = ()


def _is_num(v: object) -> bool:
    """JS 数值操作数：int/float 且非 bool（bool 在 JS 是 number 可参与运算，但占位符已归一为 0/1）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _js_to_number(s: str) -> Optional[float]:
    """JS ToNumber(string) 的实用近似：十进制字面量；不可解析 → None（JS 得 NaN）。"""
    try:
        return float(s.strip())
    except ValueError:
        return None


def _js_eq(a: object, b: object) -> bool:
    """JS 宽松相等 == / != 的实用近似（游戏公式域内与 JS 一致的子集）。

    同型数值/同型字符串=值比较；number-vs-string 走 ToNumber(string)（本例 ['5'==5→True] 对齐 JS）；
    其余混合组合（bool-vs-str 等）保守返回 False（此类组合在游戏公式中不存在且语义晦涩，降级由
    Node 侧精确处理——此处仅供快路径常见情形保持 JS 语义）。
    """
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) \
            and not isinstance(b, bool):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, str) and isinstance(b, (int, float)) and not isinstance(b, bool):
        nb = _js_to_number(a)
        return nb is not None and nb == b
    if isinstance(b, str) and isinstance(a, (int, float)) and not isinstance(a, bool):
        na = _js_to_number(b)
        return na is not None and na == a
    return False


def _js_mod(a: float, b: float) -> float:
    """JS 取余运算符 %：符号随被除数（与 Python % 不同）→ math.fmod。"""
    return math.fmod(a, b)


def _mulberry32(seed: int) -> "object":
    """确定性 PRNG：Python 移植 _js_runner.js 的 mulberry32（与 Node 逐位一致，实证 7×50 项全匹配）。

    JS: a|=0; a=(a+0x6D2B79F5)|0; t=imul(a^(a>>>15),1|a);
        t=(t+imul(t^(t>>>7),61|t))^t; return (t^(t>>>14))>>>0 / 2^32
    注意第二行 `^t` 使用上一轮 t（右值整体求值后再赋值），Python 版需保存 t1。
    """
    _MASK = 0xFFFFFFFF
    _INCR = 0x6D2B79F5
    a = seed & _MASK

    def _rand() -> float:
        nonlocal a
        a = (a + _INCR) & _MASK
        t1 = (a ^ (a >> 15)) & _MASK
        t1 = (t1 * ((1 | a) & _MASK)) & _MASK          # imul(a^(a>>>15), 1|a) 低 32 位
        u = ((t1 ^ (t1 >> 7)) & _MASK) * ((61 | t1) & _MASK)
        u &= _MASK                                     # imul(t1^(t1>>>7), 61|t1)
        t2 = (t1 + u) & _MASK
        t2 ^= t1                                       # JS: (t+imul(...))^t —— 用旧 t1
        t2 &= _MASK
        # JS: ((t ^ (t >>> 14)) >>> 0) / 2^32 —— 注意 Python 中 `&` 优先于 `/`，先掩码再除
        return ((t2 ^ (t2 >> 14)) & _MASK) / 4294967296.0

    return _rand


class _FastEvaluator:
    """白名单表达式求值器（节点白名单外 → _FastReject → 降级 Node）。"""

    __slots__ = ("_rand", "_round", "_round_ok")

    def __init__(self, ctx: EvaluatorCtx) -> None:
        seed = ctx.rng_state
        if isinstance(seed, int) and not isinstance(seed, bool):
            self._rand = _mulberry32(seed & 0xFFFFFFFF)
        else:
            self._rand = None  # 无种子 → 宿主真随机（Python random），与 Node 无种子语义一致
        round_val = ctx.battle.get("round") if isinstance(ctx.battle, Mapping) else None
        self._round_ok = isinstance(round_val, (int, float)) and not isinstance(round_val, bool)
        self._round = float(round_val) if self._round_ok else None

    # ---- 求值 ----
    def eval_node(self, node: "ast.AST") -> object:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            left = self.eval_node(node.left)
            right = self.eval_node(node.right)
            op = type(node.op)
            if not (_is_num(left) and _is_num(right)):
                raise _FastReject
            if op is ast.Add:
                return left + right
            if op is ast.Sub:
                return left - right
            if op is ast.Mult:
                return left * right
            if op is ast.Div:
                return left / right
            if op is ast.Mod:
                return _js_mod(left, right)
            raise _FastReject
        if isinstance(node, ast.UnaryOp):
            operand = self.eval_node(node.operand)
            op = type(node.op)
            if op is ast.Not:
                return not operand
            if not _is_num(operand):
                raise _FastReject
            if op is ast.UAdd:
                return +operand
            if op is ast.USub:
                return -operand
            if op is ast.Invert:  # JS ~x（int 域；float 在 JS 先截断，Python 抛异常→降级）
                if isinstance(operand, float) or abs(operand) > 0x7FFFFFFF:
                    raise _FastReject
                return ~int(operand)
            raise _FastReject
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                raise _FastReject  # Python 链式比较 vs JS 左结合 -> 降级
            left = self.eval_node(node.left)
            right = self.eval_node(node.comparators[0])
            op = type(node.ops[0])
            if op in (ast.Eq, ast.NotEq):
                eq = _js_eq(left, right)
                return eq if op is ast.Eq else (not eq)
            if _is_num(left) and _is_num(right):
                return {ast.Lt: left < right, ast.LtE: left <= right,
                        ast.Gt: left > right, ast.GtE: left >= right}[op]
            if isinstance(left, str) and isinstance(right, str):
                return {ast.Lt: left < right, ast.LtE: left <= right,
                        ast.Gt: left > right, ast.GtE: left >= right}[op]
            raise _FastReject  # 混合类型序比较 → JS 先行 ToNumber 语义不明 → 降级
        if isinstance(node, ast.IfExp):
            test = self.eval_node(node.test)
            # JS 真值语义（0/""/NaN/false 假）与 Python 真值在本域一致（bool 占位符已归一 0/1）
            return self.eval_node(node.body if bool(test) else node.orelse)
        if isinstance(node, ast.List):
            return [self.eval_node(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self.eval_node(e) for e in node.elts)
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Index):  # py<3.9 兼容
                sl = sl.value
            assert isinstance(sl, ast.Constant) and isinstance(sl.value, int) and sl.value >= 0
            container = self.eval_node(node.value)
            idx = sl.value
            if not isinstance(container, (list, tuple, str)):
                raise _FastReject
            if idx >= len(container):
                raise _FastReject  # 越界：JS 得 undefined（Node 兜底 result_type 0）
            return container[idx]
        if isinstance(node, ast.Name):
            if node.id == "this_battle_round":
                if self._round_ok:
                    return self._round
                raise _FastReject
            raise _FastReject  # 裸 Math 非合法值（仅作属性根）
        if isinstance(node, ast.Attribute):
            name = _fast_fullname(node)
            if name in _MATH_CONSTS:
                return _MATH_CONSTS[name]
            raise _FastReject
        if isinstance(node, ast.Call):
            name = _fast_fullname(node.func)
            args = [self.eval_node(a) for a in node.args]
            if name == "Math.random":
                return self._rand() if self._rand is not None else random.random()
            func = _MATH_FUNCS.get(name)
            if func is None or not all(_is_num(a) for a in args):
                raise _FastReject
            try:
                return func(*args)
            except (ValueError, OverflowError):
                raise _FastReject  # 例如 math.sqrt(-1)/pow 域外 → JS NaN → Node 兜底 result_type
        raise _FastReject

    def maybe_expr(self, node: "ast.AST") -> None:
        """整树白名单预检：任一处不合规 → _FastReject（含未求值分支，符合「任何不在白名单→降级」）。"""
        if isinstance(node, ast.Expression):
            self.maybe_expr(node.body)
            return
        if isinstance(node, ast.Constant):
            return
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _FAST_BINOPS:
                raise _FastReject
            self.maybe_expr(node.left)
            self.maybe_expr(node.right)
            return
        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in _FAST_UNARYOPS:
                raise _FastReject
            self.maybe_expr(node.operand)
            return
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or type(node.ops[0]) not in _FAST_CMPOPS:
                raise _FastReject
            self.maybe_expr(node.left)
            for c in node.comparators:
                self.maybe_expr(c)
            return
        if isinstance(node, ast.IfExp):
            self.maybe_expr(node.test)
            self.maybe_expr(node.body)
            self.maybe_expr(node.orelse)
            return
        if isinstance(node, ast.List) or isinstance(node, ast.Tuple):
            for e in node.elts:
                self.maybe_expr(e)
            return
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Index):
                sl = sl.value
            if not (isinstance(sl, ast.Constant) and isinstance(sl.value, int)
                    and not isinstance(sl.value, bool) and sl.value >= 0):
                raise _FastReject
            self.maybe_expr(node.value)
            return
        if isinstance(node, ast.Name):
            if node.id not in _FAST_ROOT_NAMES:
                raise _FastReject
            if node.id == "this_battle_round" and not self._round_ok:
                raise _FastReject
            return
        if isinstance(node, ast.Attribute):
            if _fast_fullname(node) not in _FAST_ATTR_NAMES:
                raise _FastReject
            return
        if isinstance(node, ast.Call):
            if _fast_fullname(node.func) not in _FAST_CALL_NAMES:
                raise _FastReject
            if node.keywords:
                raise _FastReject
            for a in node.args:
                self.maybe_expr(a)
            return
        if isinstance(node, ast.Load):  # Name/Attribute 的 ctx（eval 模式下恒为 Load）
            return
        raise _FastReject  # 其他节点类型 → 降级


def _fast_fullname(node: "ast.AST") -> Optional[str]:
    """值节点的点分全名：Name→id；Attribute→base.attr；其余→None。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _fast_fullname(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _evaluate_fast(js_expr: str, ctx: EvaluatorCtx) -> Optional[Tuple[float, List[str]]]:
    """白名单快路径求值。

    返回 (数值, warnings)（已过结果类型白名单）或 None（任何拒绝/异常 → 降级 Node）。
    不产生副作用（Math.random 消耗的本路径随机流在降级时丢弃，Node 以同 rng_state 重启）。
    """
    try:
        tree = ast.parse(js_expr, mode="eval")
    except (SyntaxError, ValueError):
        return None  # e.g. `===` / `true` / 空串 → 降级 Node
    ev = _FastEvaluator(ctx)
    try:
        ev.maybe_expr(tree)          # 整树白名单预检
        value = ev.eval_node(tree.body)
    except Exception:  # noqa: BLE001 —— 白名单求值异常（算术异常/越界等）→ 降级 Node（F-3 兜底）
        return None
    # 结果类型白名单（定稿 §1.2，对齐 Node `_invoke_runner` 侧）
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0, [f"result_type:{type(value).__name__ if value is not None else 'none'}"]
    if isinstance(value, float) and not math.isfinite(value):
        return 0.0, ["result_type:non_finite"]
    try:
        return float(value), []
    except (OverflowError, ValueError):
        return None  # 超巨整数无法转 float → Node（Infinity → result_type 0）



# -------------------------------------------------------------------------------------
# 公共 API
# -------------------------------------------------------------------------------------


def validate_expr(expr: str) -> Optional[Dict[str, object]]:
    """加载期公式校验：None=通过；否则返回命中 dict（对齐 validator.check_formula，供其升级复用）。

    双保险（AST/词法）：①JS 感知 tokenizer 扫描 ②字面量剥离正则扫描；另含长度上限
    （定稿 §1.2 / validator.py §3.3 formula 安全例外）。纯函数，不触发 Node（加载期零开销）。
    """
    if not isinstance(expr, str):
        return {"rule": "formula_type", "got": type(expr).__name__}
    if len(expr) > FORMULA_MAX_LENGTH:
        return {"rule": "formula_too_long", "length": len(expr), "max": FORMULA_MAX_LENGTH}
    hit = _scan_tokens(expr)
    if hit is not None:
        return hit.as_dict()
    hit = _scan_regex_insurance(expr)
    if hit is not None:
        return hit.as_dict()
    return None


_NODE_RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_js_runner.js")


def _invoke_runner(code: str, sandbox: Mapping[str, object]) -> Tuple[bool, object, str]:
    """子进程调用 _js_runner.js（vm.runInNewContext + 10ms 超时）。"""
    try:
        payload = json.dumps({"code": code, "sandbox": dict(sandbox), "timeout_ms": _VM_EFFECTIVE_TIMEOUT_MS})
        proc = subprocess.run(
            ["node", _NODE_RUNNER],
            input=payload,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
        )
    except FileNotFoundError:
        return False, None, "runner_unavailable"
    except subprocess.TimeoutExpired:
        return False, None, "runner_timeout"
    try:
        out = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False, (proc.stderr or "invalid_runner_output").strip(), "runner_output"
    if out.get("ok"):
        return True, out.get("value"), ""
    return False, out.get("value"), str(out.get("error") or "unknown")


def evaluate_detail(expr: str, ctx: EvaluatorCtx) -> Tuple[float, Tuple[str, ...]]:
    """安全求值，返回 (数值, warnings)。evaluate 的明细变体：warnings 一并给出（纯函数）。

    流程（防御纵深，性能专项 F-20）：
      1) 长度 ≤4KB（定稿 §1.2）
      2) Python 词法/AST 双保险黑名单 → 命中即 0 + warning（求值期兜底）
      3) 占位符 → ctx 字面量替换（未知 → 0 + warning）
      4) Python 白名单快路径（ast.parse + 白名单节点/名称求值，μs~ms 级）——大部分公式命中；
         任何白名单外节点/名称/运算异常 → 降级第 5 步（Node fallback，不回退语义）
      5) Node vm.runInNewContext 隔离求值，10ms 超时（F-3）
      6) 结果类型白名单 int/float；NaN/Infinity/其他类型 → 0 + warning
    """
    warnings: List[str] = []
    if not isinstance(expr, str):
        warnings.append(f"expr_type:{type(expr).__name__}")
        return 0.0, tuple(warnings)
    if len(expr) > FORMULA_MAX_LENGTH:
        warnings.append("formula_too_long")
        return 0.0, tuple(warnings)
    hit = _scan_tokens(expr)
    if hit is None:
        hit = _scan_regex_insurance(expr)
    if hit is not None:
        warnings.append("blacklist:" + json.dumps(hit.as_dict(), ensure_ascii=False))
        return 0.0, tuple(warnings)

    js_expr = _expand_placeholders(expr, ctx, warnings)

    # ② Python 白名单快路径（大部分公式直接命中；拒绝/异常 → ③ Node fallback）
    fast = _evaluate_fast(js_expr, ctx)
    if fast is not None:
        value, fast_warnings = fast
        warnings.extend(fast_warnings)
        return float(value), tuple(warnings)

    sandbox: Dict[str, object] = {}
    round_val = ctx.battle.get("round") if isinstance(ctx.battle, Mapping) else None
    if isinstance(round_val, (int, float)) and not isinstance(round_val, bool):
        sandbox["this_battle_round"] = round_val  # 定稿 §1.1 示例标识符兼容
    if ctx.rng_state is not None:
        sandbox["__rng_seed"] = ctx.rng_state

    ok, value, err = _invoke_runner(js_expr, sandbox)
    if not ok:
        warnings.append(f"eval_failed:{err}")
        return 0.0, tuple(warnings)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        warnings.append(f"result_type:{type(value).__name__ if value is not None else 'none'}")
        return 0.0, tuple(warnings)
    return float(value), tuple(warnings)


def evaluate(expr: str, ctx: EvaluatorCtx) -> float:
    """安全求值公式 → float；运行期异常/超时/黑名单/未知占位符 → 0（F-1~F-5，定稿 §1.2）。"""
    value, _warnings = evaluate_detail(expr, ctx)
    for w in _warnings:
        _LOGGER.warning("formula[%s] %s", expr[:60], w)
    return value
