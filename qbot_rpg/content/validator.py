"""内容包校验器 —— 结构断言唯一落点（细化_3e §5.1；【规则】L92「全部结构断言收敛于此」）。

依据：
  - 细化_3e_loader校验接线 §2.1：红拦 R-1~R-5（封闭清单，硬约束）
  - 细化_3e_loader校验接线 §2.2：黄提示 Y-1~Y-8（开放清单，只进 warnings 不阻断）
  - 细化_3e_loader校验接线 §2.3：默认放行兜底（红拦清单封闭、黄提示开放，未知字段默认放行）
  - 细化_3e_loader校验接线 §3.3：formula 安全例外（AST 黑名单 / new 表达式 / 长度>4KB → 红拦，不受只建议不限制覆盖）
  - 细化_3e_loader校验接线 §5.2：每模块校验清单（ID 唯一 / 链成环 / 部位互斥环 / stats 键空间等）
  - 细化_3e_loader校验接线 §5.3：字段元数据表 = 校验唯一数据源；校验器只实现规则引擎，不硬编码字段名
  - 细化_3e2_热重载契约 BLK-1：校验二分法（红色拦截仅 5 类）
  - 细化_1e_怪物八段schema §⑤：校验器规则 R1-R15（enemies 八段专项；级别=拦截/警告/提示三分）
    + §② 难度模板（stats 漏配键补全 + pv 档默认 10/75/300）+ §④ 木桩特例（tier:training / type:dummy）
    + m2_shared_contract 第一~三节（八段字段表 / 难度模板 / 木桩特例）
  - 细化_1g4_战斗世界边界 §6.3 + m2_shared_contract 第七节（settings 段 1g4 专项：
    F-02 货币引用存在 / F-02·F-04 数值合法 / F-03 disabled 惰性 / F-05·F-06 引用存在 /
    超时类键不识别 —— `_check_settings_1g4`）
  - m4_shared_contract §2.3（批次 6 校验器+manifest 注册）+ §3.1~3.4 + 细化_2b1/2b3/2b4/2b5
    （M4 交互系统：npc/shop/quest/checkin 四模块专项校验器接线，`_check_module` 分支调用
    validate_npcs / validate_shops / validate_quests / validate_checkins，专项全权 + 泛型并行）
  - m5_shared_contract §1.4 + 细化_3d 附·校验器行 L358 +【前缀】§九 L110-121
    （M5-02 message_prefix 段校验：`_check_message_prefix`，红拦 kind=MP-1 / 黄提示 kind=MP-2；
    3h V9~V12 通用黄提示不覆盖 message_prefix）
  - 细化_6a_技能库契约 §1/§3（M13 技能库：skills 专项校验器接线——`_check_module`
    分派 validate_skills（批2 路2A/2B 落盘 qbot_rpg/content/skill_validator.py），
    专项全权（V-7~V-13）+ 泛型并行；分派位见 _check_module「M13 技能库」分支）

纯函数无副作用：check_pack(modules, meta) -> ValidationReport（D-01：errors/warnings/notes 全量收集，一次给全）。
零 NoneBot；仅依赖 qbot_rpg.content.models / qbot_rpg.content.field_meta / qbot_rpg.data.types。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.content.field_meta import DEFAULT_CURRENCY_IDS, default_field_meta_table
from qbot_rpg.data.affinity_keys import (
    ENTRY_PAYLOAD_ENHANCE_AFFIX,
    ENTRY_PAYLOAD_KEYS,
    POOL_KINDS,
    REACTION_AMPLIFY,
    REACTION_CONFLICT,
    REACTION_KINDS,
    affinity_requires,
)
from qbot_rpg.data.event_points import EVENT_POINTS
from qbot_rpg.data.gear_stats import (
    DEPRECATED_EFFECT_AXES,
    EFFECT_AGGREGATES,
    EFFECT_GATE_MODES,
    EFFECT_UNKNOWN_MODES,
    GEAR_DISPLAY_KEYS,
    GEAR_EFFECT_KEYS,
    OVERHEAL_KEY,
    PANEL_AXIS_STEMS,
    check_effect_budget,
    effect_axis_stem,
    effect_values_of,
    normalize_effect_axes,
    normalize_effect_budget,
)
from qbot_rpg.content.models import (
    FieldMeta,
    FieldMetaTable,
    ModuleMeta,
    PackError,
    PackNote,
    PackWarning,
    ValidationReport,
)

# -------------------------------------------------------------------------------------
# formula 安全例外（细化_3e §3.3；【规则】L448）
# -------------------------------------------------------------------------------------
FORMULA_MAX_LENGTH = 4096  # 公式长度 >4KB → 拒绝（L449）
# AST 黑名单标识符（L448）：abstract 解析在标识符词法/`new` 表达式两个层面
FORMULA_BLACKLIST: Tuple[str, ...] = (
    "constructor",
    "__proto__",
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
_FORMULA_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def check_formula(expr: str) -> Optional[Mapping[str, object]]:
    """formula 安全例外：返回 None=通过；否则返回命中详情（红拦）。

    简化词法扫描（M0 无外部 JS 解析器依赖）：剥离字符串字面量/注释后检查
    标识符黑名单与 `new Xxx` 表达式；长度上限独立检查（L449）。

    P1-1（2026-08-24 M0 复查）补两条绕过封堵：
      - Unicode 转义归一化：`F\\u0061nction` → `Function`（否则标识符正则遇
        反斜杠断词，黑名单不可见）；
      - 方括号字符串键：`a["constructor"]["constructor"]("return process")()`
        的字面量键被 _strip_literals 整体剥离导致黑名单不可见 → 对原始表达式
        单独检查 `[ "黑名单词" ]` 形态（与字符串字面量内含词区分）。
    """
    if len(expr) > FORMULA_MAX_LENGTH:
        return {"rule": "formula_too_long", "length": len(expr), "max": FORMULA_MAX_LENGTH}
    # P1-1：先归一化 Unicode/十六进制转义（\uXXXX / \xXX → 字符），防断词绕过
    normalized = _normalize_unicode_escapes(expr)
    stripped = _strip_literals(normalized)
    tokens = _FORMULA_IDENT_RE.findall(stripped)
    for tok in tokens:
        if tok in FORMULA_BLACKLIST:
            return {"rule": "formula_ast_blacklist", "identifier": tok}
    # P1-1：方括号字符串键取构造器——`x["constructor"]["constructor"](...)` 经典 RCE 链。
    # 对归一化后的原始表达式扫描（stripped 已把键字面量剥离，看不到）；
    # 与「字符串字面量内含黑名单词」区分：仅命中 `[ '词' ]` / `[ "词" ]` 访问器形态。
    for m in re.finditer(r"\[\s*([\"'])(.*?)\1\s*\]", normalized):
        key = m.group(2)
        if key in FORMULA_BLACKLIST:
            return {"rule": "formula_ast_blacklist", "identifier": key}
    # `new Xxx(...)` 表达式：剥离后找 "new" 且下一词为标识符
    for m in re.finditer(r"\bnew\s+([A-Za-z_$][A-Za-z0-9_$]*)", stripped):
        return {"rule": "formula_new_expression", "constructor_name": m.group(1)}
    return None


def _normalize_unicode_escapes(expr: str) -> str:
    """Unicode/十六进制转义归一化（P1-1）：`\\uXXXX` / `\\xXX` → 对应字符。

    防止标识符经转义断词绕过黑名单（如 `F\\u0061nction` 归一化为 `Function`、
    `ev\\x61l` → `eval`）。仅处理字符转义；反斜杠本身（路径等）原样保留。
    """
    expr = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), expr)
    expr = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), expr)
    return expr


def _strip_literals(expr: str) -> str:
    """剥离字符串字面量 / 模板串字面量部分 / 注释，保留模板插值 `${...}` 继续扫描。

    修复（2026-08-18 dsh 审查 P1-1）：
      - 模板串 `${eval(...)}` 插值此前随反引号整体剥离 → 黑名单绕过；现插值表达式
        原样保留进 out，供标识符检查（`${` 配对用花括号 depth + 内部字符串跳过）。
      - `/* ... */` 块注释未剥离 → 注释内黑名单词误红拦；现一并剥离。
    """
    out: List[str] = []
    i, n = 0, len(expr)
    while i < n:
        c = expr[i]
        if c in ("'", '"'):
            quote = c
            i += 1
            while i < n:
                if expr[i] == "\\":
                    i += 2
                    continue
                if expr[i] == quote:
                    break
                i += 1
            i += 1
            continue
        if c == "`":
            # 模板串：剥离纯文本字面量；`${...}` 插值表达式保留（内部引号/花括号正确处理）
            i += 1
            while i < n:
                e = expr[i]
                if e == "\\":
                    i += 2
                    continue
                if e == "$" and i + 1 < n and expr[i + 1] == "{":
                    # 收集插值内容（丢弃 ${ 标记本身——否则 $ 与后续标识符合并成
                    # '$eval' 单 token 绕过黑名单检查；JS 词法里 ${} 是分隔符）
                    i += 2
                    depth = 1
                    while i < n and depth > 0:
                        ch = expr[i]
                        if ch in ("'", '"', "`"):
                            q = ch
                            i += 1
                            while i < n:
                                if expr[i] == "\\":
                                    i += 2
                                    continue
                                if expr[i] == q:
                                    break
                                i += 1
                            i += 1
                            continue
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                        if depth > 0:
                            out.append(ch)
                        i += 1
                    continue
                i += 1
            i += 1  # 跳过收尾反引号
            continue
        if c == "/" and i + 1 < n:
            nxt = expr[i + 1]
            if nxt == "/":  # `//` 行注释
                while i < n and expr[i] != "\n":
                    i += 1
                continue
            if nxt == "*":  # `/* ... */` 块注释
                i += 2
                while i + 1 < n and not (expr[i] == "*" and expr[i + 1] == "/"):
                    i += 1
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


# -------------------------------------------------------------------------------------
# M2 怪物八段：权威枚举 / 难度模板 / 木桩判定 / 元素注册表（依据：细化_1e §⑤ + §② + §④）
# -------------------------------------------------------------------------------------
# 依据：细化_1e §⑤ R1-R15（规则表权威）+ §② 难度模板 + §④ 木桩特例 + m2_shared_contract 第一~三节。
# 字段口径从 field_meta.py 的 FieldMetaTable 读（stats 九键 / tier 枚举），本处常量仅作缺省兜底与派生语义。

# 八段新格式判定标记（M0 旧简档 = 顶层 hp/atk/def/drop_rate，无以下任一键 → 走旧泛型路径保持零提示零拦截）
_ENEMY_8SEG_MARKERS: Tuple[str, ...] = (
    "tier", "stats", "pv", "weakness", "drops", "lore", "special_actions",
    "chains", "pv_recover", "resistance", "def_base", "elem_res",
)

# tier 枚举与 stats 九键缺省兜底（运行时优先读 FieldMetaTable.enemies）
_ENEMY_TIERS_DEFAULT: Tuple[str, ...] = ("normal", "elite", "boss", "training")
_ENEMY_STAT_KEYS_DEFAULT: Tuple[str, ...] = (
    "hp", "mp", "str", "int", "con", "spr", "foc", "agi", "luk",
)

# 触发类型权威 15 类（细化_1e 1.4 A06 / S3；权威=怪物行动AI定稿 §二 13 类 + 印记扩展
# 2 类 enemy_mark/player_mark（2026-09-02 框架级新增）；`x_` 前缀可自定义扩展）
TRIGGER_TYPES: frozenset = frozenset({
    "hp_below", "pv_broken", "get_up", "battle_start", "after_action",
    "player_status", "player_hp_below", "turn_count", "phase_changed",
    "zone_changed", "ally_dead", "combo_broken", "script",
    "enemy_mark", "player_mark",
})
# 旧枚举别名（1e 1.4 A06 兼容别名：可写不拦截；S4 仅三例有权威归一目标 → R12 提示迁移）
TRIGGER_ALIASES: Mapping[str, str] = {
    "broken": "pv_broken",
    "revive": "get_up",
    "enter_phase": "battle_start",
}
# 其余旧枚举（无权威归一目标，接受不提示，X-02 口径：与 drop condition 两套独立枚举）
TRIGGER_LEGACY: frozenset = frozenset({
    "phase_below", "cooldown_ready", "turn_elapsed", "chain_complete",
    "tag_trigger", "delayed",
})
TRIGGER_TIMINGS: Tuple[str, ...] = ("current_turn", "next_turn", "first_turn")
# 阈值类触发（必带 trigger.value，R11）
_TRIGGER_VALUE_REQUIRED: frozenset = frozenset({"hp_below", "player_hp_below"})
# 印记类触发（2026-09-02 框架级新增；必带 trigger.mark = 印记 id/冗余名；可带
# min/max 层数阈值与 absent 反向；参数名集中在常量，校验/引擎共用同一键名契约）
MARK_TRIGGER_TYPES: frozenset = frozenset({"enemy_mark", "player_mark"})
MARK_TRIGGER_MARK_KEY: str = "mark"
MARK_TRIGGER_MIN_KEY: str = "min"
MARK_TRIGGER_MAX_KEY: str = "max"
MARK_TRIGGER_ABSENT_KEY: str = "absent"

# 掉落条件枚举（R13；与 trigger.type 两套独立枚举，X-02；`after_action:<action_id>` 为细化定型）
DROP_CONDITIONS: Tuple[str, ...] = ("pv_broken", "no_damage")
DROP_AFTER_ACTION_PREFIX: str = "after_action:"

# 8 元素注册表（细化_1a §1.1 / 数值层 L220-221；引擎 core/damage.py DEFAULT_ELEMENTS 同源。
# content 层依赖方向仅 data（细化_3a §1.4），不 import core，故镜像常量并标注来源；
# 若内容包 formula.json 声明 `elements` 段则以包内注册表为准（R3/R14 引用检查）。
_DEFAULT_ELEMENTS: Tuple[str, ...] = (
    "earth", "fire", "water", "wind", "thunder", "crystal", "moon", "void",
)

# 难度模板（细化_1e §②；低=normal / 中=elite / 高=boss；木桩不套模板 §④ L340）
# stats 漏配键补全基准 = 玩家同级（L43）→ 取 stats 键空间缺省基准（hp 100 / mp 50 / 其余 10，细化_1a 同源）
_TEMPLATE_BASE_STATS: Mapping[str, float] = {
    "hp": 100.0, "mp": 50.0, "str": 10.0, "int": 10.0, "con": 10.0,
    "spr": 10.0, "foc": 10.0, "agi": 10.0, "luk": 10.0,
}
# 攻击=力量/智力（物理/魔法通道），防御=体质/精神（细化_1a L28：攻击=力量[物]|智力[魔]，防御对位=精神）
_ATK_KEYS: Tuple[str, ...] = ("str", "int")
_DEF_KEYS: Tuple[str, ...] = ("con", "spr")
# 各档乘区 + PV 档默认（中=HP×2.5/攻×1.2/防×1.3；高=HP×10[下限]/攻×1.3/防×1.5；其余 1×）
DIFFICULTY_TEMPLATES: Mapping[str, Mapping[str, object]] = {
    "normal": {"hp_mult": 1.0, "atk_mult": 1.0, "def_mult": 1.0, "pv": 10},
    "elite":  {"hp_mult": 2.5, "atk_mult": 1.2, "def_mult": 1.3, "pv": 75},
    "boss":   {"hp_mult": 10.0, "atk_mult": 1.3, "def_mult": 1.5, "pv": 300},
}
# PV 常见档区间（仅提示，R4；普通 0-20 / 精英 50-100 / BOSS 200-500）
PV_RANGES: Mapping[str, Tuple[float, float]] = {
    "normal": (0.0, 20.0), "elite": (50.0, 100.0), "boss": (200.0, 500.0),
}


def is_dummy_enemy(entry: Mapping[str, object]) -> bool:
    """木桩判定（依据：细化_1e §④：tier:"training" 或 type:"dummy" 任一命中）。"""
    return entry.get("tier") == "training" or entry.get("type") == "dummy"


# -------------------------------------------------------------------------------------
# 1g4 世界边界 settings 校验（细化_1g4 §6.3 / m2_shared_contract 第七节）
# -------------------------------------------------------------------------------------
def _is_battle_timeout_key(key: str) -> bool:
    """超时类键判定（细化_1g4 §6.3：任何「战斗超时」配置键一律不识别 → load 警告+忽略）。

    无超时设计（LOST-01/TIME-01，框架 L99）：编辑器/内容包均无此键，命中即警告不阻断。
    """
    k = key.lower()
    return "timeout" in k or "超时" in k


def apply_enemy_difficulty_template(
    stats: Optional[Mapping[str, object]], tier: str
) -> Tuple[Dict[str, float], Optional[float], List[str]]:
    """难度模板 stats 补全（依据：细化_1e §② / R9）——纯函数，供校验器提示与加载器/编辑器复用。

    返回 (补全后 9 键 stats, pv 档默认或 None, 本次补全的键清单)。
    木桩不套模板（§④ L340）——调用方自行判断（dummy → 不调用本函数）。
    """
    tmpl = DIFFICULTY_TEMPLATES.get(tier, DIFFICULTY_TEMPLATES["normal"])
    src = stats if isinstance(stats, Mapping) else {}
    completed: Dict[str, float] = {}
    filled: List[str] = []
    for key in _ENEMY_STAT_KEYS_DEFAULT:
        raw = src.get(key)
        if raw is not None and isinstance(raw, (int, float)) and not isinstance(raw, bool):
            completed[key] = float(raw)
            continue
        base = _TEMPLATE_BASE_STATS[key]
        if key == "hp":
            mult = float(tmpl["hp_mult"])  # type: ignore[arg-type]
        elif key in _ATK_KEYS:
            mult = float(tmpl["atk_mult"])  # type: ignore[arg-type]
        elif key in _DEF_KEYS:
            mult = float(tmpl["def_mult"])  # type: ignore[arg-type]
        else:
            mult = 1.0
        completed[key] = base * mult
        filled.append(key)
    pv_default = tmpl.get("pv")
    return completed, (float(pv_default) if isinstance(pv_default, (int, float)) else None), filled


# -------------------------------------------------------------------------------------
# M5-02 message_prefix 段校验（【前缀】§九 L110-121 + 细化_3d 附·校验器行 L358 /
# m5_shared_contract §1.4；3h V9~V12 通用黄提示不覆盖 message_prefix）
# -------------------------------------------------------------------------------------
# 占位符白名单 5 个（【前缀】§四 L66-72 / 3d §1.2）：等级 / 玩家名 / 称号 / 群名 / 职业
MESSAGE_PREFIX_PLACEHOLDERS: Tuple[str, ...] = ("等级", "玩家名", "称号", "群名", "职业")
# per_channel 枚举（【前缀】L45/L59：all 群聊+私聊 / group 仅群聊 / private 仅私聊）
MESSAGE_PREFIX_PER_CHANNEL: Tuple[str, ...] = ("all", "group", "private")
# 默认格式模板 TPL-01（【前缀】L43/L127；content 层依赖方向仅 data，不 import core，
# 镜像 prefix_render.DEFAULT_PREFIX_FORMAT 并标注来源——同 _DEFAULT_ELEMENTS 口径）
MESSAGE_PREFIX_DEFAULT_FORMAT: str = "Lv[等级].[玩家名] -[称号]-"
# format 超长 >80 字符 或 占位符 >10 个 → 「模板有点长，注意前缀别刷屏」（【前缀】L119）
MESSAGE_PREFIX_FORMAT_MAX_LEN: int = 80
MESSAGE_PREFIX_PLACEHOLDER_MAX: int = 10
# prefix_max_len 超常见区间 >200 → 确认提示（【前缀】L121）
MESSAGE_PREFIX_MAX_LEN_COMMON: int = 200
# 占位符提取正则（[xxx] 原样 token；含未知，供黄提示原样输出）
_MESSAGE_PREFIX_PLACEHOLDER_RE = re.compile(r"\[([^\]]+)\]")


def message_prefix_unknown_placeholders(format_str: str) -> List[str]:
    """模板中未知占位符清单（不在【前缀】§四 5 个白名单内；返回 `[xxx]` 原样 token）。

    未知占位符原样输出 + 黄提示「模板里有不认识的东西 [xxx]，会原样显示，确认？」，
    不拦截加载（【前缀】L75/L117）；渲染层同样原样透传（prefix_render TC-06）。
    """
    unknown: List[str] = []
    for name in _MESSAGE_PREFIX_PLACEHOLDER_RE.findall(format_str):
        if name not in MESSAGE_PREFIX_PLACEHOLDERS:
            unknown.append(f"[{name}]")
    return unknown


# -------------------------------------------------------------------------------------
# 校验引擎
# -------------------------------------------------------------------------------------


class _Checker:
    """整包校验器实例：持有元数据表与累积报告。单次使用，纯函数式（无副作用）。"""

    def __init__(self, modules: Mapping[str, object], meta: FieldMetaTable) -> None:
        self._modules = modules
        self._meta = meta
        self.errors: List[PackError] = []
        self.warnings: List[PackWarning] = []
        self.notes: List[PackNote] = []
        # kind -> {id: 条目来源位置}（跨命名空间 ID 唯一性 + R-4 引用查询）
        self._id_space: Dict[str, Dict[str, str]] = {}
        self._location: Dict[str, Dict[str, str]] = {}  # kind -> id -> 位置原样串（供 detail）
        # 命名空间 -> 已注册 id（跨表唯一）
        self._ns_registered: Dict[str, Dict[str, str]] = {}
        # 元素注册表（懒构建缓存：包内 formula.json `elements` 段 ∪ 缺省 8 元素）
        self._element_reg: Optional[frozenset] = None
        # 云海九期（cloudsea-pack）207 性能修复①：skill_or_any 引用校验并集惰性缓存
        # （注册即失效，见 _register_id / _check_ref；同 _element_reg 先例）。
        self._all_ref_ids_cache: Optional[set] = None

    # ---- 报告构建 ----
    def _err(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append(PackError(module=module, field=field, kind=kind, detail=dict(detail)))

    def _warn(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append(PackWarning(module=module, field=field, kind=kind, detail=dict(detail)))

    def _note(self, module: str, field: str, kind: str, **detail: object) -> None:
        """信息级提示（细化_1e §⑤ 提示级：模板补全/别名规范化/档区间/成环提示；不阻断）。"""
        self.notes.append(PackNote(module=module, field=field, kind=kind, detail=dict(detail)))

    # ---- 入口 ----
    def run(self) -> ValidationReport:
        self._collect_ids()
        for module_name in self._ordered_defined_modules():
            self._check_module(module_name)
        return ValidationReport(errors=tuple(self.errors), warnings=tuple(self.warnings),
                                notes=tuple(self.notes))

    # ---- 模块顺序（细化_3e §1.3：效果家族先注册；供确定性报告排序）----
    _PRIORITY: Tuple[str, ...] = ("effects", "statuses", "marks", "skill_chains", "action")

    def _ordered_defined_modules(self) -> List[str]:
        # manifest 也是受检模块之一（细化_3e §1.2 / §5.2 manifest 行）；其余按固定注册顺序
        defined = [m for m in self._modules if m != "manifest"]
        by_priority: List[str] = []
        if "manifest" in self._modules:
            by_priority.append("manifest")
        for p in self._PRIORITY:
            if p in defined:
                by_priority.append(p)
        for m in defined:
            if m not in by_priority:
                by_priority.append(m)
        return by_priority

    # ---- ID 空间收集（ID 全局唯一 + R-4 引用查表）----
    def _collect_ids(self) -> None:
        for module_name in self._ordered_defined_modules():
            mmeta = self._meta.module(module_name)
            if mmeta is None:
                continue
            data = self._modules.get(module_name)
            for idx, entry in self._iter_entries(module_name, data, mmeta):
                if mmeta.entry_type == "map":
                    eid = idx if isinstance(idx, str) else None
                else:
                    emap = self._as_mapping(entry)
                    eid = emap.get(mmeta.id_field) if emap is not None else None
                if not isinstance(eid, str) or not eid:
                    continue
                kind = mmeta.kind or module_name
                namespace = mmeta.namespace or module_name
                self._register_id(kind, namespace, eid, module_name)

    def _register_id(self, kind: str, namespace: str, eid: str, module_name: str) -> None:
        self._id_space.setdefault(kind, {}).setdefault(eid, module_name)
        self._all_ref_ids_cache = None  # 云海九期（cloudsea-pack）207：注册面变化 → 并集缓存失效
        if eid in self._ns_registered.setdefault(namespace, {}):
            prev = self._ns_registered[namespace][eid]
            self._err(
                module_name,
                f"{module_name}.?  id={eid}",
                "R-5",
                rule="id_duplicate",
                id=eid,
                namespace=namespace,
                previous_module=prev,
            )
        else:
            self._ns_registered[namespace][eid] = module_name

    # ---- 迭代条目 ----
    def _iter_entries(
        self, module_name: str, data: object, mmeta: ModuleMeta
    ) -> Iterable[Tuple[int, object]]:
        if mmeta.entry_type == "object":
            if isinstance(data, dict):
                yield 0, data
            return
        if mmeta.entry_type == "map":
            if isinstance(data, dict):
                for k, v in data.items():
                    yield k, v  # idx = 键（map 模块的 id 即键）
            return
        # list
        if isinstance(data, list):
            for i, v in enumerate(data):
                yield i, v
        # 非数组/字典（结构错误由 _check_module 报 R-5），此处静默

    def _as_mapping(self, value: object) -> Optional[Mapping[str, object]]:
        return value if isinstance(value, Mapping) else None

    # ---- 单模块校验 ----
    def _check_module(self, module_name: str) -> None:
        mmeta = self._meta.module(module_name)
        data = self._modules.get(module_name)
        if mmeta is None:
            return  # 未登记模块：默认放行（§2.3 兜底）
        # 顶层结构形态检查
        expected = mmeta.entry_type
        if expected == "object":
            if not isinstance(data, Mapping):
                self._err(module_name, module_name, "R-5", rule="module_structure", expect="object")
                return
        elif expected == "map":
            if not isinstance(data, Mapping):
                self._err(module_name, module_name, "R-5", rule="module_structure", expect="map")
                return
        else:
            if not isinstance(data, list):
                self._err(module_name, module_name, "R-5", rule="module_structure", expect="list")
                return
        # 键空间命名约束（stats 小写 snake_case，细化_3e §5.2）
        if expected == "map" and mmeta.key_regex is not None:
            data_map = data if isinstance(data, Mapping) else {}
            keys = [str(k) for k in data_map.keys()]
            rx = re.compile(mmeta.key_regex)
            for k in keys:
                if not rx.fullmatch(k):
                    self._err(
                        module_name, f"{module_name}.{k}",
                        "R-5",
                        rule="key_invalid", key=k, key_regex=mmeta.key_regex,
                    )
        # map 形态模块：按 value_meta 校验每个值（stats 值对象 / formula 公式）
        if expected == "map":
            if mmeta.value_meta is not None:
                data_map = data if isinstance(data, Mapping) else {}
                for k, v in data_map.items():
                    self._check_map_value(module_name, f"{module_name}.{k}", v, mmeta.value_meta)
            return
        # M2 怪物八段（细化_1e §⑤ R1-R15）：enemies 全量校验收敛到 _check_enemies
        # （八段格式 → 专项 R1-R15；M0 旧简档 → 内部路由泛型 _check_entry 保持既有行为）
        if module_name == "enemies":
            self._check_enemies(module_name, data, mmeta)
            return
        # M3 地图专项（m3_shared_contract §2）：maps 新结构（spawn/exits/dungeon_entrances）
        # 由 map_models.validate_maps 补深结构校验；随后继续泛型 _check_entry（旧 maps_fields
        # 的 min/max 死配置检测保留，新结构未知字段默认放行 §2.3 不误伤）
        if module_name == "maps":
            from qbot_rpg.content.map_models import validate_maps
            validate_maps(self._modules, self)
        if module_name == "dungeon":
            from qbot_rpg.content.dungeon_models import validate_dungeons
            # dungeon_models 为 ValidationReport 合并模式（非 _Checker 鸭子类型）→ 桥接回填
            vrep = validate_dungeons(self._modules, None)
            for e in vrep.errors:
                self._err(e.module, e.field, e.kind, **e.detail)
            for w in vrep.warnings:
                self._warn(w.module, w.field, w.kind, **w.detail)
            for n in vrep.notes:
                self._note(n.module, n.field, n.kind, **n.detail)
            return
        # M4 交互系统（m4_shared_contract §3.1~3.4 + §2.3 批次6 校验器接线）：npc/shop/quest/checkin
        # 专项校验器 + 泛型并行（同 maps 模式：专项全权深结构后继续泛型 _check_entry；字段口径
        # fields={} 空表 → 泛型仅结构/ID 收集与死配置检测，未知字段 §2.3 默认放行不误伤）。
        # 依据：细化_2b1（validate_npcs）/ 细化_2b3（validate_shops）/ 细化_2b4（validate_quests）/
        #       细化_2b5（validate_checkins）——四者均为 (modules, report) 纯函数，report 鸭子类型
        #       （_Checker._err/_warn/_note 与各 _emit 签名一致）。
        if module_name == "npc":
            from qbot_rpg.content.npc_models import validate_npcs
            validate_npcs(self._modules, self)
        if module_name == "shop":
            from qbot_rpg.content.shop_models import validate_shops
            validate_shops(self._modules, self)
        if module_name == "quest":
            from qbot_rpg.content.quest_models import validate_quests
            validate_quests(self._modules, self)
        if module_name == "checkin":
            from qbot_rpg.content.checkin_models import validate_checkins
            validate_checkins(self._modules, self)
        # M8 炼金（m8_contract_数据与校验 §六）：recipe/traits/proficiency/slots 专项
        # （鸭子类型模式 validate_xxx(modules, report)，同 npc/shop/quest/checkin 口径；
        #  slots 定义来自 alchemy_settings）
        if module_name == "recipe":
            from qbot_rpg.content.alchemy_models import validate_recipes
            validate_recipes(self._modules, self)
        if module_name == "traits":
            from qbot_rpg.content.alchemy_models import validate_traits
            validate_traits(self._modules, self)
        if module_name == "proficiency":
            from qbot_rpg.content.alchemy_models import validate_proficiency
            validate_proficiency(self._modules, self)
        if module_name == "slots":
            from qbot_rpg.content.alchemy_settings import validate_slots
            validate_slots(self._modules, self)
        # 批46 · 符文地基（43-A）：runes 专项校验（RUNE-01~07；鸭子类型 validate_xxx
        # 口径同 recipe/traits/slots——阶枚举/差异表 default+覆盖/stats 键空间/effects
        # 引用存在性/family 必填）。
        if module_name == "runes":
            from qbot_rpg.content.rune_models import validate_runes
            validate_runes(self._modules, self)
        # M9 锻造（m9_shared_contract §六）：forge 专项校验 V1-V15 硬 + V16/W1-W6 黄 +
        # 2c2d V1-V8 硬/W1-W4 黄（同 npc/shop/quest/checkin 鸭子类型 validate_xxx 口径）
        if module_name == "forge":
            from qbot_rpg.content.forge_models import validate_forge
            validate_forge(self._modules, self)
        # M12.5 强化（2c3a §5.2 V1~V7）：enhance 专项校验（同鸭子类型 validate_xxx 口径）
        if module_name == "enhance":
            from qbot_rpg.content.enhance_models import validate_enhance
            validate_enhance(self._modules, self)
        # M11 成就（m11 启动包 §2.1）：achievements 专项校验 ACH-01~13（同鸭子类型口径）
        if module_name == "achievements":
            from qbot_rpg.content.achievements_models import validate_achievements
            validate_achievements(self._modules, self)
        # M13 技能库（细化_6a_技能库契约 §3：skills 专项校验器 V-1~V-13 全权，
        # 批2 路2A/2B 落盘 skill_validator.py——validate_skills(modules, report)
        # 鸭子类型口径同 npc/shop/quest/checkin；随后继续泛型 _check_entry：
        # skills_fields 24 键登记表驱动泛型字段校验 + 未知字段默认放行不误伤）
        if module_name == "skills":
            from qbot_rpg.content.skill_validator import validate_skills
            validate_skills(self._modules, self)
        # 批29 α4：skill_chains 条件专项（新增 level/job/quest 三类红拦；未使用三新键的
        # 既有链零影响）。形态机制同 skills 专项（validate_xxx(modules, report) 鸭子类型）。
        if module_name == "skill_chains":
            from qbot_rpg.content.skill_validator import validate_skill_chains
            validate_skill_chains(self._modules, self)
        # M13 职业库（细化_6b_职业库与变换引擎契约 §五：jobs 专项校验器 V1~V8 全权，
        # 批5 路5A/5B 落盘 job_validator.py——validate_jobs(modules, report) 鸭子类型口径
        # 同 npc/shop/quest/checkin；随后继续泛型 _check_entry：jobs_fields 39 键登记表
        # 驱动泛型字段校验（V5 state_policy 枚举 / V4 duration 枚举基底）+ 未知字段默认
        # 放行不误伤。5A/5B 未落盘时 try/except ImportError 兜底跳过——专项未接线期间
        # 泛型登记表仍全量生效（对齐 6b 摸底⑧ 既有缺口语义，不阻塞装配）。
        # 先例：field_meta jobs 登记注释（L826-827「V1~V8 专项归 job_models.validate_jobs
        # 全权」）——分派目标以 job_validator.validate_jobs 为准（job_models 为纯数据层）。
        if module_name == "jobs":
            try:  # 5A/5B 未落盘时 ImportError 兜底跳过（专项未接线期间泛型登记表仍全量生效）
                from qbot_rpg.content.job_validator import validate_jobs
                from qbot_rpg.content.job_validator_v58 import validate_jobs_v58
            except ImportError:  # pragma: no cover - 5A/5B 未落盘时的装配兜底
                validate_jobs = None  # type: ignore[assignment]
                validate_jobs_v58 = None  # type: ignore[assignment]
            if validate_jobs is not None:
                validate_jobs(self._modules, self)
            # M13 6b 批5 收口：V5~V8（技能挂点引用/派生链作用域/死配置/battle+revert 红拦）
            # 独立文件 job_validator_v58.py（与 5A 分文件防并发覆盖），此处双分派
            if validate_jobs_v58 is not None:
                validate_jobs_v58(self._modules, self)
        # M13 6c（细化_6c §1.5：stats 资源轴注册段专项校验器 V1~V4）
        if module_name == "stats":
            try:
                from qbot_rpg.content.resource_axis_validator import validate_resource_axes
            except ImportError:  # pragma: no cover - 批8 未落盘时的装配兜底
                validate_resource_axes = None  # type: ignore[assignment]
            if validate_resource_axes is not None:
                validate_resource_axes(self._modules, self)
        # 批22 · A2：items/equipment 使用等级硬口径（use_level ≥ 1 → IV-1 红拦；
        # 引用类 job_restrict 走元数据 ref_target="job" 的泛型 R-4，此处不重复）。
        if module_name in ("items", "equipment"):
            from qbot_rpg.content.item_validator import validate_equipment, validate_items
            if module_name == "items":
                validate_items(self._modules, self)
            else:
                validate_equipment(self._modules, self)
        # 批50 · 特效轴地基：内容侧轴取值越界红拦（items/equipment 词条 + runes 数值档；
        # 范围取 settings.effect_axes 有效声明，缺省 = 登记表建议范围）。
        if module_name in ("items", "equipment", "runes"):
            self._check_effect_axis_values(module_name, data)
            # 批55 · 特效强度预算：条目级特效等效越界（仅 enabled=true 时；越界呈现按
            # gate_mode：warn=黄提示 Y-20 / red=红拦 R-5 / off=静默）。
            self._check_effect_budget_entries(module_name, data)
        # 批18 效果扩展（gain_currency / learn_skill）：类型相关必填/范围/引用存在性
        # 专项（泛型 R-1/R-2/R-4 仍在下方逐条目跑；本钩子补「仅在该 type 下才要求」的键）。
        if module_name == "effects":
            self._check_effects_18(module_name, data)
        # 批51 · 事件补点：`trigger` 时点取值域专项（effects 条目 + runes 效果引用条目）。
        # 未知时点 → 黄提示 Y-19（分派器只认 EVENT_POINTS，未知值 = 永不触发）；
        # 非字符串 → 红拦 R-1。唯一源 data/event_points.EVENT_POINTS（不反向 import core）。
        if module_name in ("effects", "runes"):
            self._check_effect_trigger_points(module_name, data)
        # 逐条目校验
        for idx, entry in self._iter_entries(module_name, data, mmeta):
            self._check_entry(module_name, idx, entry, mmeta)
        # 结构算法：链成环 / 部位互斥环
        if mmeta.chain_field:
            self._check_chain_cycle(module_name, data, mmeta)
        if mmeta.mutex_field:
            self._check_mutex_cycle(module_name, data, mmeta)
        # 条件加成（细化_3b §3.2 / TC-05 / ADR-05）：source/target 引用 stats 键空间（R-4）
        # + 依赖图环（含自环）→ R-5。口径说明：3b ADR-05「未注册键红拦」vs 3e Y-7「未注册键
        # 黄提示」为跨文档冲突（dsh 审查 P2-9，上报用户/仲裁）；此处按 3b 场景语义取红。
        if module_name == "conditional":
            self._check_conditional(module_name, data)
        # 1g4 世界边界 settings 专项（细化_1g4 §6.3 / m2_shared_contract 第七节）：
        # F-02 货币引用存在（硬拦）/ F-02·F-04 数值合法（硬拦）/ F-03 disabled 惰性 /
        # 超时类键不识别（load 警告+忽略）。泛型字段校验已在上方逐条目循环跑（R-1~R-5）。
        if module_name == "settings":
            self._check_settings_1g4(module_name, data)
            # 批37 X12：settings.post_battle_recovery 战后恢复段专项
            # （【框架】L294/L298-300 + 3h §4.2/L234；容器 soft_label 泛型短路 → 显式区间红拦）
            self._check_post_battle_recovery(module_name, data)
            # 批38 · H7 副手：settings.equipment_offhand 开关 + slot_defs.<部位>.role
            # （段结构/类型/区间红拦 + 「开关关闭却声明副手部位」黄提示，不硬拦）
            self._check_equipment_offhand(module_name, data)
            # 批45 · 装备占比校准：settings.panel_budget（装备面板倍率/预算份）
            # + settings.monster_scaling（怪物 hp/atk/防御补偿）——结构/类型/区间红拦
            self._check_panel_budget(module_name, data)
            self._check_monster_scaling(module_name, data)
            # 批55 · 特效强度预算：settings.effect_budget 另立上限（结构/类型/枚举红拦 +
            # 权表 calib=0 黄提示）；缺段 → enabled=false → 零行为。
            self._check_effect_budget(module_name, data)
            # 批50 · 特效轴地基：settings.effect_axes 逐轴声明（越界红拦 / 未知轴黄提示 /
            # 轴名不得与面板三轴 stem 冲突）+ 内容侧轴取值越界红拦。
            self._check_effect_axes(module_name, data)
            # 批56 · 过量治疗开关：settings.overheal（结构/类型红拦；缺段 = 关闭 = 现状）
            self._check_overheal(module_name, data)
            # 批57 · 精粹产出率：settings.forge.essence_rate（结构/类型/枚举红拦 +
            # 「enabled 但精粹货币未登记」红拦；缺段 = 未启用 = 现状）
            self._check_essence_rate(module_name, data)
            # 批38 · ④ 相性通用层（settings 四段结构/枚举/引用 + 材料相性引用存在性）
            self._check_affinity(module_name, data)
            # 批39 · 合成/炼金/打造启用矩阵：settings.deep_craft 打造路径开关
            # （段结构/类型红拦 + 「打造已开但合成层关」黄提示，不硬拦）
            self._check_deep_craft(module_name, data)
            # M8 settings.alchemy 段校验（m8_contract_数据与校验 §六 ALC-01~24 + §五）
            # 鸭子类型纯函数；段缺失/空段默认值兜底（alchemy_settings P-6）
            from qbot_rpg.content.alchemy_settings import check_settings_alchemy
            check_settings_alchemy(data if isinstance(data, Mapping) else {}, self)
            # M5-02 message_prefix 段校验（【前缀】§九 L112-121 + 细化_3d 附·校验器行 L358 /
            # m5_shared_contract §1.4）：红拦 MP-1（enabled 非布尔 / format 非字符串 /
            # prefix_max_len 负数 / 段结构错误）+ 黄提示 MP-2（未知占位符 / format 空补全 /
            # format 超长或占位符过多 / per_channel 非法按 all / prefix_max_len>200）。
            # 3h V9~V12 通用黄提示不覆盖 message_prefix → 本段独立 校验行。
            self._check_message_prefix(module_name, data)
            # M3 时间引擎配置（M31 · m3_shared_contract §5.2/§6.2）：time_cycle 段 V1-V4 校验
            # （G0 架构修复：校验函数在 content 层，避免 content→engine 反向依赖）
            from qbot_rpg.content.time_validator import validate_time_cycle
            validate_time_cycle(data if isinstance(data, Mapping) else {}, self)
            # M3 天气池对象形态校验（M41 · 细化_2a4b §1.2 R3/R4 · 审查 M3 批次2 P1-4）：
            # default_pool {key,name,emoji} 对象条目「键+中文名齐全」红拦——收口接入 check_pack
            # （与 validate_time_cycle V4 并存：字符串池键形态前者已覆盖，本函数按对象形态补强）
            from qbot_rpg.content.time_validator import validate_weather_pool
            validate_weather_pool(data if isinstance(data, Mapping) else {}, self)
            # M3 天气校验（M41 · m3_shared_contract §6.2）：V5-V8 硬校验 + 黄提示（依赖 modules 消费方扫描）
            from qbot_rpg.content.weather_validator import validate_weather
            validate_weather(self._modules, data if isinstance(data, Mapping) else {}, self)
        # 批41 · 深度打造：材料/图纸条目的引用与范围（图纸档/产出/部位/配方引用存在性，
        # 材料等级/成本范围，材料品质 ∈ 品质颜色空间，等级带 min≤max，随机条数 ≤2）。
        if module_name in ("items", "equipment"):
            self._check_deep_craft_entries(module_name, data)

    # ---- M2 怪物八段专项（依据：细化_1e §⑤ R1-R15 / §② 模板 / §④ 木桩）----
    def _check_enemies(self, module_name: str, data: object, mmeta: Optional[ModuleMeta]) -> None:
        """enemies 全量校验入口（细化_1e §⑤）。

        双轨：M0 旧简档（无八段标记）→ 泛型 _check_entry（保持既有 R-1~R-5 / Y-1~Y-8 行为，
        零新增提示，兼容既有 fixtures）；八段格式 → _check_enemy_8seg（R1-R15 全量）。
        """
        if not isinstance(data, list):
            return  # 顶层结构错误已由 _check_module 泛型报
        for idx, entry in enumerate(data):
            if not isinstance(entry, Mapping):
                self._err(module_name, f"{module_name}.{idx}", "R-1",
                          rule="entry_not_object", got=type(entry).__name__)
                continue
            if not self._enemy_is_8seg(entry):
                if mmeta is not None:
                    self._check_entry(module_name, idx, entry, mmeta)
                continue
            self._check_enemy_8seg(module_name, idx, entry)

    @staticmethod
    def _enemy_is_8seg(entry: Mapping[str, object]) -> bool:
        """八段格式判定：type:"dummy" 或任一八段新字段命中即按八段校验（M0 旧简档=零提示零拦截）。"""
        if entry.get("type") == "dummy":
            return True  # 八段木桩语义：entry["type"]=="dummy" 即命中（M0 旧简档=零提示零拦截）
        return any(k in entry for k in _ENEMY_8SEG_MARKERS)

    def _check_enemy_8seg(self, module_name: str, idx: int, entry: Mapping[str, object]) -> None:
        """单只八段怪 R1-R15 全量校验（拦截/警告/提示三分）。"""
        base = f"{module_name}.{idx}"
        dummy = is_dummy_enemy(entry)
        self._check_enemy_required(module_name, base, entry, dummy)        # R8
        self._check_enemy_stats(module_name, base, entry, dummy)           # R9 + 模板补全
        self._check_enemy_weakness(module_name, base, entry, dummy)        # R3
        self._check_enemy_pv(module_name, base, entry, dummy)              # R4 + R7(pv)
        self._check_enemy_actions(module_name, base, entry, dummy)         # R1/R10 + R7
        self._check_enemy_special_actions(module_name, base, entry, dummy)  # R2/R11/R12
        self._check_enemy_chains(module_name, base, entry, dummy)          # R15
        self._check_enemy_drops(module_name, base, entry, dummy)           # R5/R13 + R7
        self._check_enemy_lore(module_name, base, entry, dummy)            # R6 + R7
        self._check_enemy_dummy_numeric(module_name, base, entry, dummy)   # R14
        self._check_enemy_parts(module_name, base, entry, dummy)           # R16（方位 v0.6 §三.3）

    # ---- meta 辅助（校验器走 FieldMetaTable 泛化驱动：键/枚举从表读，缺省常量兜底）----
    def _enemy_meta_fields(self) -> Optional[Mapping[str, FieldMeta]]:
        mmeta = self._meta.module("enemies")
        return mmeta.fields if mmeta is not None else None

    def _enemy_stat_keys(self) -> Tuple[str, ...]:
        f = self._enemy_meta_fields()
        if f is not None:
            stats_meta = f.get("stats")
            if stats_meta is not None and stats_meta.children:
                return tuple(stats_meta.children.keys())
        return _ENEMY_STAT_KEYS_DEFAULT

    def _enemy_tier_enum(self) -> Tuple[str, ...]:
        f = self._enemy_meta_fields()
        if f is not None:
            tier_meta = f.get("tier")
            if tier_meta is not None and tier_meta.enum:
                return tuple(tier_meta.enum)
        return _ENEMY_TIERS_DEFAULT

    def _element_registry(self) -> frozenset:
        """元素注册表（R3/R14 引用检查）：缺省 8 元素 ∪ 包内 formula.json `elements` 段键。"""
        if self._element_reg is None:
            reg: set = set(_DEFAULT_ELEMENTS)
            formula = self._modules.get("formula")
            if isinstance(formula, Mapping):
                elems = formula.get("elements")
                if isinstance(elems, Mapping):
                    reg.update(k for k in elems if isinstance(k, str))
            self._element_reg = frozenset(reg)
        return self._element_reg

    def _check_action_ref(self, module_name: str, path: str, aid: str) -> None:
        """行动 ID 引用存在（R1；R2/R11/R13/R15 复用；action.json 未声明 → 按引用不存在红拦）。"""
        if aid not in self._id_space.get("action", {}):
            self._err(module_name, path, "R-4", rule="R1_action_ref", ref=aid, ref_target="action")

    def _check_enemy_parts(self, module_name: str, base: str, entry: Mapping[str, object],
                           dummy: bool) -> None:
        """R16 部位破坏段（方位 v0.6 §三.3/附录 A Step 2）：结构/枚举/引用红拦。

        parts = [{id, name, positions{side[], height[]}, break_threshold,
                  target_priority, on_break{knockdown, marks[], effects[]}}]
        语义：id 必填唯一；positions 必填且 side/height 轴枚举数组（非法值红拦）；
        break_threshold 非负数值；target_priority 非负整数（缺省 0）；on_break 内
        knockdown 非负整数（缺省 1）/marks 字符串数组（引用存在 R-4）/effects 条目数组。
        只拦非法形状与引用缺失，不限制组合。
        """
        parts = entry.get("parts")
        if parts is None:
            return
        if not isinstance(parts, list):
            if not dummy:
                self._err(module_name, f"{base}.parts", "R-1", rule="R16_parts_type",
                          expect="list", got=type(parts).__name__)
            return
        if dummy:
            self._warn(module_name, f"{base}.parts", "Y-10", rule="R7_dummy_ignored",
                       field_name="parts")
            return
        seen: set = set()
        for pi, part in enumerate(parts):
            pth = f"{base}.parts.{pi}"
            if not isinstance(part, Mapping):
                self._err(module_name, pth, "R-1", rule="R16_part_type",
                          expect="obj", got=type(part).__name__)
                continue
            pid = part.get("id")
            if not isinstance(pid, str) or not pid:
                self._err(module_name, f"{pth}.id", "R-5", rule="R16_part_id_required",
                          name="id")
            elif pid in seen:
                self._err(module_name, f"{pth}.id", "R-5", rule="R16_part_id_duplicate",
                          id=pid)
            else:
                seen.add(pid)
            pos = part.get("positions")
            if not isinstance(pos, Mapping):
                self._err(module_name, f"{pth}.positions", "R-5",
                          rule="R16_part_positions_required", name="positions")
            else:
                for axis, allowed in (("side", ("front", "back", "left", "right")),
                                      ("height", ("ground", "air"))):
                    raw = pos.get(axis)
                    if raw is None:
                        self._err(module_name, f"{pth}.positions.{axis}", "R-5",
                                  rule="R16_part_positions_axis_required", axis=axis)
                        continue
                    if not isinstance(raw, list):
                        self._err(module_name, f"{pth}.positions.{axis}", "R-1",
                                  rule="R16_part_positions_axis_type", axis=axis,
                                  expect="list[str]", got=type(raw).__name__)
                        continue
                    for v in raw:
                        if not isinstance(v, str) or v not in allowed:
                            self._err(module_name, f"{pth}.positions.{axis}", "R-5",
                                      rule="R16_part_positions_enum", axis=axis,
                                      value=v, allowed=list(allowed),
                                      msg=("part.positions.%s 值 %s 不在枚举 %s"
                                           % (axis, v, list(allowed))))
            bt = part.get("break_threshold")
            if bt is not None:
                if isinstance(bt, bool) or not isinstance(bt, (int, float)):
                    self._err(module_name, f"{pth}.break_threshold", "R-1",
                              rule="R16_part_threshold_type", expect="number",
                              got=type(bt).__name__)
                elif bt < 0:
                    self._err(module_name, f"{pth}.break_threshold", "R-2",
                              rule="R16_part_threshold_negative", value=bt)
            tp = part.get("target_priority")
            if tp is not None:
                if isinstance(tp, bool) or not isinstance(tp, (int, float)):
                    self._err(module_name, f"{pth}.target_priority", "R-1",
                              rule="R16_part_priority_type", expect="number",
                              got=type(tp).__name__)
                elif tp < 0:
                    self._err(module_name, f"{pth}.target_priority", "R-2",
                              rule="R16_part_priority_negative", value=tp)
            ob = part.get("on_break")
            if ob is not None:
                if not isinstance(ob, Mapping):
                    self._err(module_name, f"{pth}.on_break", "R-1",
                              rule="R16_part_onbreak_type", expect="obj",
                              got=type(ob).__name__)
                else:
                    kd = ob.get("knockdown")
                    if kd is not None and (isinstance(kd, bool)
                                           or not isinstance(kd, (int, float)) or kd < 0):
                        self._err(module_name, f"{pth}.on_break.knockdown", "R-2",
                                  rule="R16_part_knockdown_negative", value=kd)
                    marks = ob.get("marks")
                    if marks is not None:
                        if not isinstance(marks, list):
                            self._err(module_name, f"{pth}.on_break.marks", "R-1",
                                      rule="R16_part_marks_type", expect="list[str]",
                                      got=type(marks).__name__)
                        else:
                            for mk in marks:
                                if not isinstance(mk, str) or not mk:
                                    self._err(module_name, f"{pth}.on_break.marks", "R-5",
                                              rule="R16_part_marks_entry", value=mk)
                                elif "mark" in self._id_space and mk not in self._id_space["mark"]:
                                    self._err(module_name, f"{pth}.on_break.marks", "R-4",
                                              rule="R16_part_mark_ref", ref=mk,
                                              ref_target="mark")
                    fx = ob.get("effects")
                    if fx is not None and not isinstance(fx, list):
                        self._err(module_name, f"{pth}.on_break.effects", "R-1",
                                  rule="R16_part_effects_type", expect="list",
                                  got=type(fx).__name__)
                    for k in ob:
                        if k not in ("knockdown", "marks", "effects"):
                            self._err(module_name, f"{pth}.on_break.{k}", "R-5",
                                      rule="R16_part_onbreak_unknown_key", key=k,
                                      msg="on_break 未知键 %r（仅 knockdown/marks/effects）" % (k,))
            for k in part:
                # 云海九期（cloudsea-pack）238：白名单放行云海两键——cls（件型标注）与 break_behavior
                # （03 §M3.1B 部位破坏绑定面，251–255/219 产出；破坏行为结算
                # 走 cloudsea 增量 hook 面，非 combo/effects/marks 既有行为改动）
                if k in ("cls", "break_behavior"):
                    continue
                if k not in ("id", "name", "positions", "break_threshold",
                             "target_priority", "on_break"):
                    self._err(module_name, f"{pth}.{k}", "R-5",
                              rule="R16_part_unknown_key", key=k,
                              msg="part 未知键 %r（id/name/positions/break_threshold/"
                                  "target_priority/on_break）" % (k,))

    def _check_enemy_required(self, module_name: str, base: str, entry: Mapping[str, object],
                              dummy: bool) -> None:
        """R8：id/name 非空；tier 枚举；普通怪必填 actions/drops（F12/F15 必填(普通怪)）。"""
        eid = entry.get("id")
        if not isinstance(eid, str) or not eid.strip():
            self._err(module_name, f"{base}.id", "R-5", rule="R8_id_required", name="id")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            self._err(module_name, f"{base}.name", "R-5", rule="R8_name_required", name="name")
        tier = entry.get("tier")
        if tier is not None and (not isinstance(tier, str) or tier not in self._enemy_tier_enum()):
            self._err(module_name, f"{base}.tier", "R-1", rule="R8_tier_enum",
                      got=str(tier), enum=list(self._enemy_tier_enum()))
        if not dummy:
            # pv 缺省取档默认（R4 note）不拦；actions/drops 结构缺失 → 拦截
            for fname in ("actions", "drops"):
                if fname not in entry or entry.get(fname) is None:
                    self._err(module_name, f"{base}.{fname}", "R-5",
                              rule="R8_required_missing", name=fname)

    def _check_enemy_stats(self, module_name: str, base: str, entry: Mapping[str, object],
                           dummy: bool) -> None:
        """R9：stats 九键合法、数值≥0；漏配键按难度模板补全+提示（木桩不套模板）。"""
        stats = entry.get("stats")
        stat_keys = self._enemy_stat_keys()
        if stats is None:
            self._err(module_name, f"{base}.stats", "R-5", rule="R9_stats_required", name="stats")
            return
        if not isinstance(stats, Mapping):
            self._err(module_name, f"{base}.stats", "R-1", rule="R9_stats_type", expect="obj",
                      got=type(stats).__name__)
            return
        for key, value in stats.items():
            if key not in stat_keys:
                self._err(module_name, f"{base}.stats.{key}", "R-1", rule="R9_stats_key",
                          key=key, valid_keys=list(stat_keys))
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self._err(module_name, f"{base}.stats.{key}", "R-1", rule="R9_stats_value_type",
                          expect="number", got=type(value).__name__)
            elif math.isnan(value) or math.isinf(value):
                self._err(module_name, f"{base}.stats.{key}", "R-3", rule="R9_stats_nan",
                          value=value)
            elif value < 0:
                self._err(module_name, f"{base}.stats.{key}", "R-2", rule="R9_stats_negative",
                          value=value)
        if dummy:
            return  # 木桩不套模板（§④ L340）
        tier = str(entry.get("tier") or "normal")
        completed, _pv_default, filled = apply_enemy_difficulty_template(stats, tier)
        for key in filled:
            self._note(module_name, f"{base}.stats.{key}", "N-1", rule="R9_template_fill",
                       key=key, tier=tier, value=completed[key])

    def _check_enemy_weakness(self, module_name: str, base: str, entry: Mapping[str, object],
                              dummy: bool) -> None:
        """R3：无弱点 → 警告（木桩豁免 ≥1 约束）；元素 ID ∈ 注册表（拦截）。"""
        weakness = entry.get("weakness")
        if weakness is None or weakness == {}:
            if not dummy:
                self._warn(module_name, f"{base}.weakness", "Y-9", rule="R3_no_weakness")
            return
        if not isinstance(weakness, Mapping):
            self._err(module_name, f"{base}.weakness", "R-1", rule="R3_weakness_type",
                      expect="obj", got=type(weakness).__name__)
            return
        types = weakness.get("types")
        if types is not None:
            if not isinstance(types, list):
                self._err(module_name, f"{base}.weakness.types", "R-1", rule="R3_types_type",
                          expect="list", got=type(types).__name__)
            else:
                for i, t in enumerate(types):
                    if not isinstance(t, str):
                        self._err(module_name, f"{base}.weakness.types.{i}", "R-1",
                                  rule="R3_types_elem", expect="str", got=type(t).__name__)
        elements = weakness.get("elements")
        if elements is not None:
            if not isinstance(elements, Mapping):
                self._err(module_name, f"{base}.weakness.elements", "R-1", rule="R3_elements_type",
                          expect="obj", got=type(elements).__name__)
            else:
                reg = self._element_registry()
                for eid, mult in elements.items():
                    if eid not in reg:
                        self._err(module_name, f"{base}.weakness.elements.{eid}", "R-4",
                                  rule="R3_element_ref", ref=eid, registry=sorted(reg))
                    if isinstance(mult, bool) or not isinstance(mult, (int, float)):
                        self._err(module_name, f"{base}.weakness.elements.{eid}", "R-1",
                                  rule="R3_element_mult_type", expect="number",
                                  got=type(mult).__name__)
                    elif math.isnan(mult) or math.isinf(mult):
                        self._err(module_name, f"{base}.weakness.elements.{eid}", "R-3",
                                  rule="R3_element_mult_nan", value=mult)
                    elif mult < 0:
                        self._err(module_name, f"{base}.weakness.elements.{eid}", "R-2",
                                  rule="R3_element_mult_negative", value=mult)

    def _check_enemy_pv(self, module_name: str, base: str, entry: Mapping[str, object],
                        dummy: bool) -> None:
        """R4：PV 非负（拦截）；档常见区间仅提示；缺省取档默认 10/75/300。R7：木桩 pv 强制 0。"""
        pv = entry.get("pv")
        if dummy:
            if pv is not None:
                if isinstance(pv, bool) or not isinstance(pv, (int, float)):
                    self._err(module_name, f"{base}.pv", "R-1", rule="R4_pv_type",
                              expect="number", got=type(pv).__name__)
                elif pv != 0:
                    self._warn(module_name, f"{base}.pv", "Y-10", rule="R7_dummy_ignored",
                               field_name="pv", pv=pv)
            return
        tier = str(entry.get("tier") or "normal")
        if pv is None:
            tmpl = DIFFICULTY_TEMPLATES.get(tier, DIFFICULTY_TEMPLATES["normal"])
            self._note(module_name, f"{base}.pv", "N-2", rule="R4_pv_default",
                       tier=tier, pv_default=tmpl["pv"])
            return
        if isinstance(pv, bool) or not isinstance(pv, (int, float)):
            self._err(module_name, f"{base}.pv", "R-1", rule="R4_pv_type",
                      expect="number", got=type(pv).__name__)
            return
        if math.isnan(pv) or math.isinf(pv):
            self._err(module_name, f"{base}.pv", "R-3", rule="R4_pv_nan", value=pv)
            return
        if pv < 0:
            self._err(module_name, f"{base}.pv", "R-2", rule="R4_pv_negative", value=pv)
            return
        lo, hi = PV_RANGES.get(tier, (0.0, 500.0))
        if not (lo <= pv <= hi):
            self._note(module_name, f"{base}.pv", "N-3", rule="R4_pv_range",
                       tier=tier, pv=pv, range_min=lo, range_max=hi)
        # P2-1 修复：pv_recover 枚举（1e F10：battle_end/none）——8seg 路径此前静默放行
        pvr = entry.get("pv_recover")
        if pvr is not None and pvr not in ("battle_end", "none"):
            self._err(module_name, f"{base}.pv_recover", "R-1", rule="R1_pv_recover_enum",
                      value=pvr, valid=("battle_end", "none"))

    def _check_enemy_actions(self, module_name: str, base: str, entry: Mapping[str, object],
                             dummy: bool) -> None:
        """R1 行动引用存在 + R10 概率语义（硬拦仅类型/负数/结构；空随机池黄提示）+ R7 木桩忽略。"""
        actions = entry.get("actions")
        if actions is None:
            return  # 必填缺失已由 R8 报
        if not isinstance(actions, list):
            if not dummy:
                self._err(module_name, f"{base}.actions", "R-1", rule="R1_actions_type",
                          expect="list", got=type(actions).__name__)
            return
        if not actions:
            if not dummy:
                self._err(module_name, f"{base}.actions", "R-5", rule="R8_required_missing",
                          name="actions")
            return
        if dummy:
            self._warn(module_name, f"{base}.actions", "Y-10", rule="R7_dummy_ignored",
                       field_name="actions")
            return
        in_pool = 0
        pool_weight_sum = 0.0
        for i, a in enumerate(actions):
            apath = f"{base}.actions.{i}"
            if isinstance(a, str):
                # M0 旧写法：直接行动 ID 引用（R1）
                self._check_action_ref(module_name, apath, a)
                continue
            if not isinstance(a, Mapping):
                self._err(module_name, apath, "R-1", rule="R1_action_entry_type",
                          expect="obj", got=type(a).__name__)
                continue
            aid = a.get("action")
            if not isinstance(aid, str) or not aid:
                self._err(module_name, f"{apath}.action", "R-5", rule="R1_action_required",
                          name="action")
            else:
                self._check_action_ref(module_name, f"{apath}.action", aid)
            # R10 概率语义：缺省 0=锚点；1=入池；其他正值等价 1（不拦截）；硬拦仅类型/负数
            prob = a.get("probability")
            if prob is None:
                prob_eff = 0
            elif isinstance(prob, bool) or not isinstance(prob, (int, float)):
                self._err(module_name, f"{apath}.probability", "R-1", rule="R10_prob_type",
                          expect="number", got=type(prob).__name__)
                prob_eff = 0
            elif math.isnan(prob) or math.isinf(prob):
                self._err(module_name, f"{apath}.probability", "R-3", rule="R10_prob_nan",
                          value=prob)
                prob_eff = 0
            elif prob < 0:
                self._err(module_name, f"{apath}.probability", "R-2", rule="R10_prob_negative",
                          value=prob)
                prob_eff = 0
            else:
                prob_eff = 1 if prob > 0 else 0  # 其他正值等价 1（S1/R10）
            in_pool += prob_eff
            # weight / cooldown / hungry 非负（硬拦；数值大小不限制，只建议不限制）
            for k in ("weight", "cooldown", "hungry"):
                v = a.get(k)
                if v is None:
                    continue
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    self._err(module_name, f"{apath}.{k}", "R-1", rule="R10_field_type",
                              field_name=k, expect="number", got=type(v).__name__)
                elif math.isnan(v) or math.isinf(v):
                    self._err(module_name, f"{apath}.{k}", "R-3", rule="R10_field_nan",
                              field_name=k, value=v)
                elif v < 0:
                    self._err(module_name, f"{apath}.{k}", "R-2", rule="R10_field_negative",
                              field_name=k, value=v)
                elif k == "weight" and prob_eff:
                    pool_weight_sum += float(v)
        # R10 空随机池：行动表非空但无一入池（全锚点）→ 黄提示
        if in_pool == 0:
            self._warn(module_name, f"{base}.actions", "Y-11", rule="R10_empty_pool")
        elif pool_weight_sum <= 0:
            # R10 概率总和为 0：有入池但权重全 0 → 归一化 0/0 除零隐患，黄提示（1e §⑤ R10）
            self._warn(module_name, f"{base}.actions", "Y-11",
                       rule="R10_pool_weight_zero", pool_weight_sum=pool_weight_sum)

    def _check_enemy_special_actions(self, module_name: str, base: str, entry: Mapping[str, object],
                                     dummy: bool) -> None:
        """R2 触发类型合法+action 引用 / R11 参数完整性 / R12 别名规范化 / R15 chain_ref。"""
        sas = entry.get("special_actions")
        if sas is None:
            return
        if not isinstance(sas, list):
            if not dummy:
                self._err(module_name, f"{base}.special_actions", "R-1", rule="R2_sa_type",
                          expect="list", got=type(sas).__name__)
            return
        if not sas:
            return
        if dummy:
            self._warn(module_name, f"{base}.special_actions", "Y-10",
                       rule="R7_dummy_ignored", field_name="special_actions")
            return
        seen_ids = set()
        for i, sa in enumerate(sas):
            spath = f"{base}.special_actions.{i}"
            if not isinstance(sa, Mapping):
                self._err(module_name, spath, "R-1", rule="R2_sa_entry_type",
                          expect="obj", got=type(sa).__name__)
                continue
            sid = sa.get("id")
            if sid is not None:
                if not isinstance(sid, str) or not sid:
                    self._err(module_name, f"{spath}.id", "R-5", rule="R2_sa_id_invalid",
                              name="id")
                elif sid in seen_ids:
                    self._err(module_name, f"{spath}.id", "R-5", rule="R2_sa_id_duplicate",
                              id=sid)
                else:
                    seen_ids.add(sid)
            aid = sa.get("action")
            if not isinstance(aid, str) or not aid:
                self._err(module_name, f"{spath}.action", "R-5", rule="R2_sa_action_required",
                          name="action")
            else:
                self._check_action_ref(module_name, f"{spath}.action", aid)
            trigger = sa.get("trigger")
            if not isinstance(trigger, Mapping):
                self._err(module_name, f"{spath}.trigger", "R-5", rule="R2_trigger_required",
                          name="trigger")
            else:
                self._check_trigger(module_name, spath, trigger)
            for k in ("priority", "trigger_cooldown", "max_triggers"):
                v = sa.get(k)
                if v is None:
                    continue
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    self._err(module_name, f"{spath}.{k}", "R-1", rule="R11_num_type",
                              field_name=k, expect="number", got=type(v).__name__)
                elif v < 0:
                    self._err(module_name, f"{spath}.{k}", "R-2", rule="R11_num_negative",
                              field_name=k, value=v)
            once = sa.get("once")
            if once is not None and not isinstance(once, bool):
                self._err(module_name, f"{spath}.once", "R-1", rule="R2_once_type",
                          expect="bool", got=type(once).__name__)
            ps = sa.get("post_state")
            if ps is not None:
                if not isinstance(ps, Mapping):
                    self._err(module_name, f"{spath}.post_state", "R-1",
                              rule="R11_post_state_type", expect="obj", got=type(ps).__name__)
                else:
                    turns = ps.get("turns")
                    if turns is not None:
                        if isinstance(turns, bool) or not isinstance(turns, (int, float)):
                            self._err(module_name, f"{spath}.post_state.turns", "R-1",
                                      rule="R11_post_state_turns_type", expect="number",
                                      got=type(turns).__name__)
                        elif turns < 0:
                            self._err(module_name, f"{spath}.post_state.turns", "R-2",
                                      rule="R11_post_state_turns_negative", value=turns)
            cref = sa.get("chain_ref")
            if cref is not None:
                if not isinstance(cref, str):
                    self._err(module_name, f"{spath}.chain_ref", "R-1",
                              rule="R15_chain_ref_type", expect="str", got=type(cref).__name__)
                elif not self._chains_have_id(entry, cref):
                    self._err(module_name, f"{spath}.chain_ref", "R-4",
                              rule="R15_chain_ref_missing", ref=cref, ref_target="chains.id")

    @staticmethod
    def _chains_have_id(entry: Mapping[str, object], cid: str) -> bool:
        chains = entry.get("chains")
        if not isinstance(chains, list):
            return False
        return any(isinstance(c, Mapping) and c.get("id") == cid for c in chains)

    def _check_trigger(self, module_name: str, spath: str, trigger: Mapping[str, object]) -> None:
        """特殊行动 trigger 专项：R2 13 类枚举 / R11 参数完整性 / R12 别名规范化。"""
        ttype = trigger.get("type")
        if not isinstance(ttype, str) or not ttype:
            self._err(module_name, f"{spath}.trigger.type", "R-5",
                      rule="R2_trigger_type_required", name="type")
            return
        tpath = f"{spath}.trigger.type"
        if ttype in TRIGGER_TYPES:
            pass
        elif ttype in TRIGGER_ALIASES:
            self._note(module_name, tpath, "N-4", rule="R12_trigger_alias",
                       alias=ttype, canonical=TRIGGER_ALIASES[ttype])
        elif ttype in TRIGGER_LEGACY:
            pass  # 其余旧枚举兼容别名：可写不拦截（1e 1.4 A06）
        elif ttype.startswith("x_"):
            pass  # x_ 前缀自定义扩展（A06）
        else:
            self._err(module_name, tpath, "R-1", rule="R2_trigger_type_invalid",
                      got=ttype, enum=sorted(TRIGGER_TYPES))
            return  # 类型非法：参数完整性判定不适用
        # A07 value：阈值类必带（R11）
        if ttype in _TRIGGER_VALUE_REQUIRED and ("value" not in trigger or trigger.get("value") is None):
            self._err(module_name, f"{spath}.trigger.value", "R-5",
                      rule="R11_trigger_value_required", trigger_type=ttype)
        value = trigger.get("value")
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self._err(module_name, f"{spath}.trigger.value", "R-1", rule="R11_value_type",
                          expect="number", got=type(value).__name__)
            elif value < 0:
                self._err(module_name, f"{spath}.trigger.value", "R-2",
                          rule="R11_value_negative", value=value)
        # A09 after_action 必带 action + chance 0-100（R11）
        if ttype == "after_action":
            ta = trigger.get("action")
            if not isinstance(ta, str) or not ta:
                self._err(module_name, f"{spath}.trigger.action", "R-5",
                          rule="R11_after_action_required", name="action")
            else:
                self._check_action_ref(module_name, f"{spath}.trigger.action", ta)
            chance = trigger.get("chance")
            if chance is None:
                self._err(module_name, f"{spath}.trigger.chance", "R-5",
                          rule="R11_after_action_chance_required", name="chance")
            elif isinstance(chance, bool) or not isinstance(chance, (int, float)):
                self._err(module_name, f"{spath}.trigger.chance", "R-1", rule="R11_chance_type",
                          expect="number", got=type(chance).__name__)
            elif chance < 0 or chance > 100:
                self._err(module_name, f"{spath}.trigger.chance", "R-2", rule="R11_chance_range",
                          value=chance, range_min=0, range_max=100)
        # position_match 方位触发参数（方位 v0.6 §三.2/附录 A Step 1）：
        # which ∈ {self, player}（缺省 self）；side/height 轴 = 枚举字符串数组（缺省/空=全量）
        if ttype == "position_match":
            _pm_which = trigger.get("which")
            if _pm_which is not None and _pm_which not in ("self", "player"):
                self._err(module_name, f"{spath}.trigger.which", "R-5",
                          rule="R11_position_which_invalid", value=_pm_which,
                          allowed=["self", "player"],
                          msg="position_match.which 需 self（怪物自己）或 player（玩家）")
            for _axis, _allowed in (("side", ("front", "back", "left", "right")),
                                    ("height", ("ground", "air"))):
                _raw = trigger.get(_axis)
                if _raw is None:
                    continue
                if isinstance(_raw, str):
                    _values = [_raw]
                elif isinstance(_raw, list):
                    _values = _raw
                else:
                    self._err(module_name, f"{spath}.trigger.{_axis}", "R-1",
                              rule="R11_position_axis_type", axis=_axis,
                              expect="list[str]", got=type(_raw).__name__)
                    continue
                for _v in _values:
                    if not isinstance(_v, str) or _v not in _allowed:
                        self._err(module_name, f"{spath}.trigger.{_axis}", "R-5",
                                  rule="R11_position_axis_enum", axis=_axis, value=_v,
                                  allowed=list(_allowed),
                                  msg=("position_match.%s 值 %s 不在枚举 %s"
                                       % (_axis, _v, list(_allowed))))
        # A08 timing 枚举（R11）
        timing = trigger.get("timing")
        if timing is not None and timing not in TRIGGER_TIMINGS:
            self._err(module_name, f"{spath}.trigger.timing", "R-1", rule="R11_timing_enum",
                      got=str(timing), enum=list(TRIGGER_TIMINGS))
        # 印记类触发参数（enemy_mark/player_mark，2026-09-02）：mark 必填字符串；
        # min/max 非负整数；absent bool；absent=true 与 min/max 并存 → 提示（语义歧义）
        if ttype in MARK_TRIGGER_TYPES:
            mark = trigger.get(MARK_TRIGGER_MARK_KEY)
            if not isinstance(mark, str) or not mark:
                self._err(module_name, f"{spath}.trigger.{MARK_TRIGGER_MARK_KEY}", "R-5",
                          rule="R11_mark_trigger_mark_required", name=MARK_TRIGGER_MARK_KEY,
                          trigger_type=ttype)
            for key in (MARK_TRIGGER_MIN_KEY, MARK_TRIGGER_MAX_KEY):
                val = trigger.get(key)
                if val is None:
                    continue
                if isinstance(val, bool) or not isinstance(val, int):
                    self._err(module_name, f"{spath}.trigger.{key}", "R-1",
                              rule="R11_mark_trigger_threshold_type",
                              expect="int", got=type(val).__name__, trigger_type=ttype)
                elif val < 0:
                    self._err(module_name, f"{spath}.trigger.{key}", "R-2",
                              rule="R11_mark_trigger_threshold_negative",
                              value=val, trigger_type=ttype)
            absent = trigger.get(MARK_TRIGGER_ABSENT_KEY)
            if absent is not None and not isinstance(absent, bool):
                self._err(module_name, f"{spath}.trigger.{MARK_TRIGGER_ABSENT_KEY}", "R-1",
                          rule="R11_mark_trigger_absent_type",
                          expect="bool", got=type(absent).__name__, trigger_type=ttype)
            if absent is True and any(k in trigger for k in
                                     (MARK_TRIGGER_MIN_KEY, MARK_TRIGGER_MAX_KEY)):
                self._note(module_name, f"{spath}.trigger", "N-4",
                           rule="R12_mark_trigger_absent_with_threshold",
                           trigger_type=ttype,
                           msg="absent=true 与 min/max 并存：absent 优先，min/max 被忽略")

    def _check_enemy_chains(self, module_name: str, base: str, entry: Mapping[str, object],
                            dummy: bool) -> None:
        """R15：chains 节点 action 引用 / chance 0-1 / role 枚举（拦截）；成环 → 提示不拦截。"""
        chains = entry.get("chains")
        if chains is None:
            return
        if not isinstance(chains, list):
            if not dummy:
                self._err(module_name, f"{base}.chains", "R-1", rule="R15_chains_type",
                          expect="list", got=type(chains).__name__)
            return
        seen = set()
        for i, ch in enumerate(chains):
            cpath = f"{base}.chains.{i}"
            if not isinstance(ch, Mapping):
                self._err(module_name, cpath, "R-1", rule="R15_chain_entry_type",
                          expect="obj", got=type(ch).__name__)
                continue
            cid = ch.get("id")
            if not isinstance(cid, str) or not cid:
                self._err(module_name, f"{cpath}.id", "R-5", rule="R15_chain_id_required",
                          name="id")
                cid = None
            elif cid in seen:
                self._err(module_name, f"{cpath}.id", "R-5", rule="R15_chain_id_duplicate",
                          id=cid)
            else:
                seen.add(cid)
            nodes = ch.get("actions")
            if nodes is None:
                continue
            if not isinstance(nodes, list):
                self._err(module_name, f"{cpath}.actions", "R-1", rule="R15_chain_nodes_type",
                          expect="list", got=type(nodes).__name__)
                continue
            action_count: Dict[str, int] = {}
            for j, node in enumerate(nodes):
                npath = f"{cpath}.actions.{j}"
                if not isinstance(node, Mapping):
                    self._err(module_name, npath, "R-1", rule="R15_node_type",
                              expect="obj", got=type(node).__name__)
                    continue
                naction = node.get("action")
                if not isinstance(naction, str) or not naction:
                    self._err(module_name, f"{npath}.action", "R-5",
                              rule="R15_node_action_required", name="action")
                else:
                    self._check_action_ref(module_name, f"{npath}.action", naction)
                    action_count[naction] = action_count.get(naction, 0) + 1
                chance = node.get("chance")
                if chance is None:
                    self._err(module_name, f"{npath}.chance", "R-5",
                              rule="R15_node_chance_required", name="chance")
                elif isinstance(chance, bool) or not isinstance(chance, (int, float)):
                    self._err(module_name, f"{npath}.chance", "R-1", rule="R15_node_chance_type",
                              expect="number", got=type(chance).__name__)
                elif not (0 <= chance <= 1):
                    self._err(module_name, f"{npath}.chance", "R-2", rule="R15_node_chance_range",
                              value=chance, range_min=0, range_max=1)
                elif chance < 0.6:
                    # R15 接续概率 <60% → 黄提示（1f ⑤5.5/§八：骨架锚点→收尾必接 ≥60%，
                    # 低接续连招建议作者提高；只建议不限制）
                    self._warn(module_name, f"{npath}.chance", "Y-12",
                               rule="R15_chain_continuation_lt60",
                               chance=chance, suggest="≥0.60")
                role = node.get("role")
                if role is not None and role not in ("chain", "finisher"):
                    self._err(module_name, f"{npath}.role", "R-1", rule="R15_node_role_enum",
                              got=str(role), enum=["chain", "finisher"])
                armor = node.get("armor")
                if armor is not None and not isinstance(armor, bool):
                    self._err(module_name, f"{npath}.armor", "R-1", rule="R15_node_armor_type",
                              expect="bool", got=type(armor).__name__)
            # 链成环提示（细化派生：环形链=有意的循环连招，X-04；提示不拦截）
            loop_actions = [k for k, c in action_count.items() if c > 1]
            if loop_actions:
                self._note(module_name, f"{cpath}.actions", "N-6", rule="R15_chain_cycle",
                           actions=loop_actions)

    def _check_enemy_drops(self, module_name: str, base: str, entry: Mapping[str, object],
                           dummy: bool) -> None:
        """R5 掉落 item 引用 + chance 0-100；R13 掉落扩展域（condition/count）；R7 木桩忽略。"""
        drops = entry.get("drops")
        if drops is None:
            return  # 必填缺失已由 R8 报
        if not isinstance(drops, Mapping):
            if not dummy:
                self._err(module_name, f"{base}.drops", "R-1", rule="R5_drops_type",
                          expect="obj", got=type(drops).__name__)
            return
        if dummy:
            if any(drops.values()):
                self._warn(module_name, f"{base}.drops", "Y-10", rule="R7_dummy_ignored",
                           field_name="drops")
            return
        for container in ("battle", "special", "death"):
            items = drops.get(container)
            if items is None:
                continue  # 三类容器缺省 []（F15）
            if not isinstance(items, list):
                self._err(module_name, f"{base}.drops.{container}", "R-1",
                          rule="R5_drop_container_type", expect="list",
                          got=type(items).__name__)
                continue
            for j, d in enumerate(items):
                dpath = f"{base}.drops.{container}.{j}"
                if not isinstance(d, Mapping):
                    self._err(module_name, dpath, "R-1", rule="R5_drop_entry_type",
                              expect="obj", got=type(d).__name__)
                    continue
                item = d.get("item")
                if not isinstance(item, str) or not item:
                    self._err(module_name, f"{dpath}.item", "R-5", rule="R5_item_required",
                              name="item")
                elif item not in self._id_space.get("item", {}):
                    self._err(module_name, f"{dpath}.item", "R-4", rule="R5_item_ref",
                              ref=item, ref_target="item")
                chance = d.get("chance")
                if chance is None:
                    self._err(module_name, f"{dpath}.chance", "R-5", rule="R5_chance_required",
                              name="chance")
                elif isinstance(chance, bool) or not isinstance(chance, (int, float)):
                    self._err(module_name, f"{dpath}.chance", "R-1", rule="R5_chance_type",
                              expect="number", got=type(chance).__name__)
                elif chance < 0 or chance > 100:
                    self._err(module_name, f"{dpath}.chance", "R-2", rule="R5_chance_range",
                              value=chance, range_min=0, range_max=100)
                cond = d.get("condition")
                if cond is not None:
                    if not isinstance(cond, str):
                        self._err(module_name, f"{dpath}.condition", "R-1",
                                  rule="R13_condition_type", expect="str",
                                  got=type(cond).__name__)
                    elif cond.startswith(DROP_AFTER_ACTION_PREFIX):
                        ref = cond[len(DROP_AFTER_ACTION_PREFIX):]
                        if not ref:
                            self._err(module_name, f"{dpath}.condition", "R-5",
                                      rule="R13_condition_ref_empty",
                                      name="after_action:<action_id>")
                        else:
                            self._check_action_ref(module_name, f"{dpath}.condition", ref)
                    elif cond not in DROP_CONDITIONS:
                        self._err(module_name, f"{dpath}.condition", "R-1",
                                  rule="R13_condition_enum", got=cond,
                                  enum=["pv_broken", "no_damage", "after_action:<action_id>"])
                count = d.get("count")
                if count is None:
                    continue  # 默认 1（D04）
                if isinstance(count, bool):
                    self._err(module_name, f"{dpath}.count", "R-1", rule="R13_count_type",
                              expect="number|[min,max]", got="bool")
                elif isinstance(count, list):
                    if len(count) != 2:
                        self._err(module_name, f"{dpath}.count", "R-1",
                                  rule="R13_count_range_shape", got_len=len(count))
                    else:
                        lo, hi = count
                        if (isinstance(lo, bool) or not isinstance(lo, (int, float))
                                or isinstance(hi, bool) or not isinstance(hi, (int, float))):
                            self._err(module_name, f"{dpath}.count", "R-1",
                                      rule="R13_count_range_type", expect="number",
                                      got=f"{type(lo).__name__}/{type(hi).__name__}")
                        elif lo < 0 or hi < 0:
                            self._err(module_name, f"{dpath}.count", "R-2",
                                      rule="R13_count_negative", lo=lo, hi=hi)
                        elif lo > hi:
                            self._err(module_name, f"{dpath}.count", "R-5",
                                      rule="R13_count_min_max", lo=lo, hi=hi)
                elif not isinstance(count, (int, float)):
                    self._err(module_name, f"{dpath}.count", "R-1", rule="R13_count_type",
                              expect="number|[min,max]", got=type(count).__name__)
                elif count < 0:
                    self._err(module_name, f"{dpath}.count", "R-2", rule="R13_count_negative",
                              value=count)

    def _check_enemy_lore(self, module_name: str, base: str, entry: Mapping[str, object],
                          dummy: bool) -> None:
        """R6：unlock 1-100 且递增（拦截）；desc 必填；R7 木桩忽略图鉴。"""
        lore = entry.get("lore")
        if lore is None:
            return
        if not isinstance(lore, list):
            if not dummy:
                self._err(module_name, f"{base}.lore", "R-1", rule="R6_lore_type",
                          expect="list", got=type(lore).__name__)
            return
        if not lore:
            return
        if dummy:
            self._warn(module_name, f"{base}.lore", "Y-10", rule="R7_dummy_ignored", field_name="lore")
            return
        prev: Optional[float] = None
        for i, l in enumerate(lore):
            lpath = f"{base}.lore.{i}"
            if not isinstance(l, Mapping):
                self._err(module_name, lpath, "R-1", rule="R6_lore_entry_type",
                          expect="obj", got=type(l).__name__)
                continue
            unlock = l.get("unlock")
            if isinstance(unlock, bool) or not isinstance(unlock, (int, float)):
                self._err(module_name, f"{lpath}.unlock", "R-1", rule="R6_unlock_type",
                          expect="number", got=type(unlock).__name__)
            elif not (1 <= unlock <= 100):
                self._err(module_name, f"{lpath}.unlock", "R-5", rule="R6_unlock_range",
                          value=unlock, range_min=1, range_max=100)
            elif prev is not None and unlock <= prev:
                self._err(module_name, f"{lpath}.unlock", "R-5", rule="R6_unlock_increasing",
                          value=unlock, previous=prev)
            else:
                prev = unlock
            desc = l.get("desc")
            if not isinstance(desc, str) or not desc:
                self._err(module_name, f"{lpath}.desc", "R-5", rule="R6_desc_required",
                          name="desc")

    def _check_enemy_dummy_numeric(self, module_name: str, base: str, entry: Mapping[str, object],
                                   dummy: bool) -> None:
        """R14：HP/def_base 非负（拦截）；elem_res 键 ∈ 注册表；def_base 直读 vs con 映射二选一提示。"""
        def_base = entry.get("def_base")
        if def_base is not None:
            if isinstance(def_base, bool) or not isinstance(def_base, (int, float)):
                self._err(module_name, f"{base}.def_base", "R-1", rule="R14_def_base_type",
                          expect="number", got=type(def_base).__name__)
            elif def_base < 0:
                self._err(module_name, f"{base}.def_base", "R-2", rule="R14_def_base_negative",
                          value=def_base)
        elem_res = entry.get("elem_res")
        if elem_res is not None:
            if not isinstance(elem_res, Mapping):
                self._err(module_name, f"{base}.elem_res", "R-1", rule="R14_elem_res_type",
                          expect="obj", got=type(elem_res).__name__)
            else:
                reg = self._element_registry()
                for eid, v in elem_res.items():
                    if eid not in reg:
                        self._err(module_name, f"{base}.elem_res.{eid}", "R-4",
                                  rule="R14_elem_res_ref", ref=eid, registry=sorted(reg))
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        self._err(module_name, f"{base}.elem_res.{eid}", "R-1",
                                  rule="R14_elem_res_value_type", expect="number",
                                  got=type(v).__name__)
        # F17 def_base 直读 vs stats.con 映射二选一（同配 → 提示一致性；R14）
        if def_base is not None:
            stats = entry.get("stats")
            if isinstance(stats, Mapping) and "con" in stats:
                self._note(module_name, f"{base}.def_base", "N-5", rule="R14_def_base_dual",
                           hint="def_base 直读与 stats.con 映射二选一")

    def _check_conditional(self, module_name: str, data: object) -> None:
        """条件加成专项（P1-1 接线：加载期红拦可达，3b TC-05/ADR-05）。"""
        if not isinstance(data, Mapping):
            return  # 结构错误已由泛型 _check_module 报
        rules = data.get("conditional")
        if not isinstance(rules, list):
            return
        stat_keys: set = set(self._id_space.get("stat", {}).keys())
        edges: Dict[str, set] = {}
        seen: set = set()
        for idx, rule in enumerate(rules):
            rm = rule if isinstance(rule, Mapping) else {}
            rid = str(rm.get("id") or "")
            src = str(rm.get("source") or "")
            tgt = str(rm.get("target") or "")
            base = f"{module_name}.conditional.{idx}"
            if not rid:
                self._err(module_name, base, "R-5", rule="required_missing", name="id")
            elif rid in seen:
                self._err(module_name, base, "R-5", rule="id_duplicate", id=rid)
            else:
                seen.add(rid)
            for key, label in ((src, "source"), (tgt, "target")):
                if key and key not in stat_keys:
                    self._err(module_name, f"{base}.{label}", "R-4",
                              rule="ref_missing", ref=key, ref_kind="stat")
            if src and tgt:
                edges.setdefault(src, set()).add(tgt)
        if self._graph_has_cycle(edges):
            self._err(module_name, "conditional", "R-5", rule="conditional_cycle",
                      edges={k: sorted(v) for k, v in edges.items()})

    @staticmethod
    def _graph_has_cycle(edges: Dict[str, set]) -> bool:
        """有向图 DFS 三色判环（含自环 source==target）。"""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {}

        def dfs(u: str) -> bool:
            color[u] = GRAY
            for v in edges.get(u, ()):
                c = color.get(v, WHITE)
                if c == GRAY:
                    return True
                if c == WHITE and dfs(v):
                    return True
            color[u] = BLACK
            return False

        for u in list(edges):
            if color.get(u, WHITE) == WHITE and dfs(u):
                return True
        return False

    # ---- 1g4 世界边界 settings 专项（细化_1g4 §6.3 / m2_shared_contract 第七节）----
    def _check_settings_1g4(self, module_name: str, data: object) -> None:
        """settings 段 1g4 专项校验（泛型 R-1~R-5 已在上方逐条目循环覆盖）。

        - F-02 货币引用存在：drop_currency[].currency ∈ 已配置货币键空间（硬拦 R-4）
        - F-02/F-04 数值合法：ratio ∈ (0,1]、count ≥ 1 整数（硬拦 R-1；越界拦截，6.3）
        - F-03 disabled 惰性：drop_exp.enabled=false 时 percent 不校验（免改双处，6.3）
        - F-05/F-06 引用存在：maps[].respawn_point ∈ 已注册地图 id（泛型 ref→map R-4）
        - 超时类键不识别：任何「战斗超时」键 → load 警告 + 忽略（LOST-01/TIME-01）
        """
        if not isinstance(data, Mapping):
            return
        currency_ids = self._settings_currency_ids(data)
        dp = data.get("death_penalty")
        if isinstance(dp, Mapping):
            self._check_death_penalty_1g4(module_name, "settings.death_penalty", dp, currency_ids)
        for key in data:
            if _is_battle_timeout_key(str(key)):
                self._warn(module_name, f"settings.{key}", "Y-8",
                           rule="battle_timeout_key_unrecognized", key=str(key))

    @staticmethod
    def _settings_currency_ids(data: Mapping[str, object]) -> Tuple[str, ...]:
        """已配置货币键空间（settings.currencies[].id）；缺省=默认模板（coins/diamond，3h §5.1）。"""
        raw = data.get("currencies")
        ids: List[str] = []
        if isinstance(raw, list):
            for e in raw:
                if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]:
                    ids.append(e["id"])
        return tuple(ids) or DEFAULT_CURRENCY_IDS

    def _check_death_penalty_1g4(
        self, module_name: str, base: str, dp: Mapping[str, object], currency_ids: Tuple[str, ...]
    ) -> None:
        """death_penalty 段 F-02 货币引用存在 + F-02/F-04 数值合法（硬拦）。"""
        # F-02 drop_currency：currency ∈ 货币键空间（硬拦）；ratio ∈ (0,1]（硬拦）
        dc = dp.get("drop_currency")
        if isinstance(dc, list):
            for i, entry in enumerate(dc):
                path = f"{base}.drop_currency.{i}"
                if not isinstance(entry, Mapping):
                    continue
                cur = entry.get("currency")
                if isinstance(cur, str) and cur not in currency_ids:
                    self._err(module_name, f"{path}.currency", "R-4",
                              rule="currency_ref_missing", currency=cur,
                              currency_space=sorted(currency_ids))
                ratio = entry.get("ratio")
                if isinstance(ratio, (int, float)) and not isinstance(ratio, bool) \
                        and not (0.0 < ratio <= 1.0):
                    self._err(module_name, f"{path}.ratio", "R-1",
                              rule="drop_ratio_out_of_range", ratio=ratio, low=0.0, high=1.0)
        # F-03 drop_exp：enabled=false 时 percent 惰性不校验（6.3）——此处无校验即惰性；
        # enabled=true 时 percent 走泛型（负数 R-2 / 超 100 Y-1），不额外硬拦（6.3 未列）。
        # F-04 drop_items：count ≥ 1 整数（硬拦）
        di = dp.get("drop_items")
        if isinstance(di, Mapping):
            cnt = di.get("count")
            if isinstance(cnt, bool) or (isinstance(cnt, (int, float))
                                         and (not isinstance(cnt, int) or cnt < 1)):
                self._err(module_name, f"{base}.drop_items.count", "R-1",
                          rule="drop_item_count_invalid", count=cnt)

    # ---- 批37 X12：settings.post_battle_recovery 战后恢复专项 ----
    def _check_post_battle_recovery(self, module_name: str, data: object) -> None:
        """settings.post_battle_recovery 段校验（批37 · X12）。

        依据：【框架】L294/L298-300（口径：胜利后按比例回 HP/MP、默认关）；
        3h §4.2（schema：enabled/heal_ratio/safe_zone_heal 三键）+ L234（V5 越界红拦 /
        V9 ratio>0.5 黄提示）+ L510（V9 阈值清单）。

        分级：
          · 段结构错误（null / 非对象）→ **红拦 R-1**（人话提示）；
          · `enabled` 非布尔 → **红拦 R-1**；
          · ratio 类型错（非数值/布尔）/ NaN/Inf → **红拦 R-1/R-3**；
          · ratio ∉ [0,1] → **红拦 V5**（3h L234；`_soft_display` 容器泛型短路，
            故此处必须显式兜住区间）；
          · ratio > 0.5 → **黄提示 V9**（补白：阈值 0.5 无定稿依据，见实现口径 §四 D7）。
        未知键 / 缺键：默认放行（3h D-02 顶层平铺；缺键走引擎默认值）。
        """
        if not isinstance(data, Mapping):
            return
        if "post_battle_recovery" not in data:
            return  # 段未配置 → 默认关闭（定稿 L299），无需校验
        base = "settings.post_battle_recovery"
        pbr = data["post_battle_recovery"]
        if pbr is None:
            self._err(module_name, base, "R-1", rule="section_structure", got="null",
                      msg="post_battle_recovery 段是空值 null，请填对象 { ... }"
                          "（如 {\"enabled\": true, \"heal_ratio\": 0.2}）或删掉该段")
            return
        if not isinstance(pbr, Mapping):
            self._err(module_name, base, "R-1", rule="section_structure",
                      got=type(pbr).__name__,
                      msg="post_battle_recovery 段要填对象（配置块 { ... }），"
                          "请检查 settings.json 该段的写法")
            return
        enabled = pbr.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            self._err(module_name, f"{base}.enabled", "R-1", rule="type", expect="bool",
                      got=type(enabled).__name__)
        for key in ("heal_ratio", "safe_zone_heal"):
            if key not in pbr:
                continue
            val = pbr[key]
            path = f"{base}.{key}"
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                self._err(module_name, path, "R-1", rule="type", expect="number",
                          got=("bool" if isinstance(val, bool) else type(val).__name__))
                continue
            if math.isnan(val) or math.isinf(val):
                self._err(module_name, path, "R-3", rule="not_a_number", value=val)
                continue
            if not (0.0 <= float(val) <= 1.0):
                # V5（3h L234）：越界红拦
                self._err(module_name, path, "R-2", rule="ratio_out_of_range",
                          value=val, range_min=0, range_max=1)
            elif float(val) > 0.5:
                # V9（3h L234/L510）：回复过高会击穿「花钱治疗=资源循环」设计
                self._warn(module_name, path, "Y-13", rule="recovery_ratio_high",
                           value=val, threshold=0.5)

    # ---- 批38 · H7：settings.equipment_offhand 副手开关 + slot_defs.role 部位角色专项 ----
    def _check_equipment_offhand(self, module_name: str, data: object) -> None:
        """settings.equipment_offhand 段 + settings.slot_defs.<部位>.role 校验（批38 · H7）。

        依据：docs/深度打造_决策记录.md §一 H7 + §五 5.2（开关默认 false / 关闭零变化）。

        分级：
          · 段结构错误（null / 非对象）→ **红拦 R-1**（人话提示）；
          · `enabled` 非布尔 → **红拦 R-1**；
          · `single_hand_scale` 非数值/布尔/NaN/Inf → **红拦 R-1/R-3**；∉[0,1] → **红拦 R-2**；
          · `slot_defs.<部位>.role` 非 `main`/`offhand` → **红拦 R-1**（枚举）；
          · `role=offhand` 但开关未开（缺段 / enabled≠true）→ **黄提示 Y-14**（不硬拦；
            用户可按自己数据情况先声明部位再开开关，故只提示）。
        未知键 / 缺键：默认放行（缺段走引擎默认「关闭」）。
        """
        if not isinstance(data, Mapping):
            return
        base = "settings.equipment_offhand"
        enabled = False
        cfg = data.get("equipment_offhand")
        if cfg is not None:
            if not isinstance(cfg, Mapping):
                self._err(module_name, base, "R-1", rule="section_structure",
                          got=type(cfg).__name__,
                          msg="equipment_offhand 段要填对象（配置块 { ... }，如 "
                              "{\"enabled\": true, \"single_hand_scale\": 0.5}）或删掉该段")
            else:
                en = cfg.get("enabled")
                if en is not None and not isinstance(en, bool):
                    self._err(module_name, f"{base}.enabled", "R-1", rule="type",
                              expect="bool", got=type(en).__name__)
                enabled = en is True
                sc = cfg.get("single_hand_scale")
                if sc is not None:
                    scpath = f"{base}.single_hand_scale"
                    if isinstance(sc, bool) or not isinstance(sc, (int, float)):
                        self._err(module_name, scpath, "R-1", rule="type", expect="number",
                                  got=("bool" if isinstance(sc, bool) else type(sc).__name__))
                    elif math.isnan(float(sc)) or math.isinf(float(sc)):
                        self._err(module_name, scpath, "R-3", rule="not_a_number", value=sc)
                    elif not (0.0 <= float(sc) <= 1.0):
                        self._err(module_name, scpath, "R-2", rule="ratio_out_of_range",
                                  value=sc, range_min=0, range_max=1)
        slot_defs = data.get("slot_defs")
        if not isinstance(slot_defs, Mapping):
            return
        for part in sorted(str(k) for k in slot_defs.keys()):
            sd = slot_defs.get(part)
            if not isinstance(sd, Mapping) or "role" not in sd:
                continue
            role = sd.get("role")
            path = f"settings.slot_defs.{part}.role"
            if role not in ("main", "offhand"):
                self._err(module_name, path, "R-1", rule="enum_invalid", got=role,
                          allowed=["main", "offhand"])
                continue
            if role == "offhand" and not enabled:
                self._warn(module_name, path, "Y-14", rule="offhand_role_without_switch",
                           msg="部位角色声明为 offhand（副手），但 settings.equipment_offhand"
                               ".enabled 未开启 → 副手规则当前不生效（不阻断；开启开关后生效）")

    # ---- 批45 · 装备占比校准：settings.panel_budget / settings.monster_scaling 专项 ----
    def _check_panel_budget(self, module_name: str, data: object) -> None:
        """settings.panel_budget 段校验（批45 · 装备占比校准）。

        依据：docs/深度打造_决策记录.md §三 补充 1（装备 8→18 ×2.25；白值 7/buff 5 不动）。
        落点：qbot_rpg/core/panel_budget.normalize_panel_budget（引擎读时参数化）。

        分级：
          · 段结构错误（非对象）→ **红拦 R-1**（人话提示）；
          · `white/equip/buff/equip_stat_mult` 非数值/布尔 → **红拦 R-1**；
          · NaN/Inf → **红拦 R-3**；负值 → **红拦 R-2**（份/倍率 ≥0）；
          · `white+equip+buff == 0` → **黄提示 Y-16**（占比无意义，不硬拦）。
        缺段/缺键：默认放行（引擎缺省 7:8:5 / 倍率 1.0 = 现状）。
        """
        if not isinstance(data, Mapping):
            return
        base = "settings.panel_budget"
        cfg = data.get("panel_budget")
        if cfg is None:
            return
        if not isinstance(cfg, Mapping):
            self._err(module_name, base, "R-1", rule="section_structure",
                      got=type(cfg).__name__,
                      msg="panel_budget 段要填对象（配置块 { ... }，如 {\"white\": 7, "
                          "\"equip\": 8, \"buff\": 5, \"equip_stat_mult\": 2.25}）或删掉该段")
            return
        vals: Dict[str, float] = {}
        for key in ("white", "equip", "buff", "equip_stat_mult"):
            if key not in cfg:
                continue
            v = cfg.get(key)
            path = f"{base}.{key}"
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                self._err(module_name, path, "R-1", rule="type", expect="number",
                          got=("bool" if isinstance(v, bool) else type(v).__name__))
                continue
            fv = float(v)
            if math.isnan(fv) or math.isinf(fv):
                self._err(module_name, path, "R-3", rule="not_a_number", value=v)
                continue
            if fv < 0.0:
                self._err(module_name, path, "R-2", rule="value_below_min", value=v,
                          range_min=0)
                continue
            vals[key] = fv
        if vals.get("white", 7.0) + vals.get("equip", 8.0) + vals.get("buff", 5.0) <= 0.0:
            self._warn(module_name, base, "Y-16", rule="panel_budget_all_zero",
                       msg="panel_budget 的 white/equip/buff 全为 0，装备占比无意义"
                           "（不阻断；请至少给一份 >0）")

    def _check_monster_scaling(self, module_name: str, data: object) -> None:
        """settings.monster_scaling 段校验（批45 · 怪物数值倍率）。

        依据：docs/深度打造_决策记录.md §三 补充 1（怪物侧按面板总功率 +50% 同步，保斩杀回合）。
        落点：qbot_rpg/commands/battle_launch_commands._enemy_combatant（combatant 构造）。

        分级：
          · 段结构错误（非对象）→ **红拦 R-1**；
          · `hp_mult/atk_mult/def_factor/def_k` 非数值/布尔 → **红拦 R-1**；
          · NaN/Inf → **红拦 R-3**；负值 → **红拦 R-2**；
          · `def_factor` 极端（∉[0.5, 2.0]）→ **黄提示 Y-17**（可能破坏斩杀回合，不硬拦）。
        缺段/缺键：默认放行（引擎缺省全 1.0 = 现状）。
        """
        if not isinstance(data, Mapping):
            return
        base = "settings.monster_scaling"
        cfg = data.get("monster_scaling")
        if cfg is None:
            return
        if not isinstance(cfg, Mapping):
            self._err(module_name, base, "R-1", rule="section_structure",
                      got=type(cfg).__name__,
                      msg="monster_scaling 段要填对象（配置块 { ... }，如 {\"hp_mult\": 1.5, "
                          "\"atk_mult\": 1.5, \"def_factor\": 1.0828}）或删掉该段")
            return
        for key in ("hp_mult", "atk_mult", "def_factor", "def_k",
                    "effect_hp_mult", "effect_atk_mult"):
            if key not in cfg:
                continue
            v = cfg.get(key)
            path = f"{base}.{key}"
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                self._err(module_name, path, "R-1", rule="type", expect="number",
                          got=("bool" if isinstance(v, bool) else type(v).__name__))
                continue
            fv = float(v)
            if math.isnan(fv) or math.isinf(fv):
                self._err(module_name, path, "R-3", rule="not_a_number", value=v)
                continue
            if fv < 0.0:
                self._err(module_name, path, "R-2", rule="value_below_min", value=v,
                          range_min=0)
                continue
            if key == "def_factor" and not (0.5 <= fv <= 2.0):
                self._warn(module_name, path, "Y-17", rule="def_factor_out_of_band",
                           msg="def_factor 超出建议带 [0.5, 2.0] → 怪物防御补偿幅度异常，"
                               "可能破坏「斩杀回合不变」（不阻断）")

    # ---- 批55 · 特效强度预算：settings.effect_budget 段 + 条目级越界两态 ----
    def _check_effect_budget(self, module_name: str, data: object) -> None:
        """`settings.effect_budget` 段校验（批55 · 特效强度预算）。

        依据：`docs/特效强度预算_设计.md` §二方案 B（另立特效强度上限，主方案）
        + §三.2 参数默认与范围 + §四 红线守护清单。
        唯一源：`data/gear_stats`（`normalize_effect_budget` / `EFFECT_*` 枚举）。

        分级：
          · 段结构错误（非对象）→ **红拦 R-1**（人话提示）；
          · `enabled` / `report_effective_share` 非布尔 → **红拦 R-1**；
          · `cap_equiv_pct` 非数值 → R-1、NaN/Inf → R-3、负值 → R-2；
          · `aggregate` / `gate_mode` / `unknown_axis` ∉ 登记枚举 → **红拦 R-1**（枚举）；
          · `tier_mult` 非对象 → R-1；条目值非数值 → R-1、NaN/Inf → R-3、负值 → R-2；
          · `axis_weights` 非对象 / 条目非对象 → R-1；`calib/output/survival` 非数值 → R-1、
            NaN/Inf → R-3；`calib == 0` → **黄提示 Y-20**（该键永不参与折算，多半是笔误）。
        缺段：默认放行（`enabled=false` → 聚合器返回 0 / gate 静默 = 零行为）。
        """
        if not isinstance(data, Mapping):
            return
        base = "settings.effect_budget"
        cfg = data.get("effect_budget")
        if cfg is None:
            return
        if not isinstance(cfg, Mapping):
            self._err(module_name, base, "R-1", rule="section_structure",
                      got=type(cfg).__name__,
                      msg="effect_budget 段要填对象（配置块 { ... }，如 {\"enabled\": true, "
                          "\"cap_equiv_pct\": 8, \"gate_mode\": \"warn\"}）或删掉该段"
                          "（删掉 = 不启用特效预算闸）")
            return
        for key in ("enabled", "report_effective_share"):
            if key in cfg and not isinstance(cfg.get(key), bool):
                v = cfg.get(key)
                self._err(module_name, f"{base}.{key}", "R-1", rule="type", expect="bool",
                          got=("bool" if isinstance(v, bool) else type(v).__name__))
        for key, allowed in (("aggregate", EFFECT_AGGREGATES),
                             ("gate_mode", EFFECT_GATE_MODES),
                             ("unknown_axis", EFFECT_UNKNOWN_MODES)):
            if key not in cfg:
                continue
            v = cfg.get(key)
            if not isinstance(v, str) or v not in allowed:
                self._err(module_name, f"{base}.{key}", "R-1", rule="enum_invalid",
                          got=v, allowed=list(allowed))
        if "cap_equiv_pct" in cfg:
            self._check_number_field(module_name, f"{base}.cap_equiv_pct",
                                     cfg.get("cap_equiv_pct"), min_value=0.0)
        tm = cfg.get("tier_mult")
        if tm is not None:
            if not isinstance(tm, Mapping):
                self._err(module_name, f"{base}.tier_mult", "R-1", rule="type", expect="obj",
                          got=type(tm).__name__)
            else:
                for raw_tier, raw_mult in tm.items():
                    self._check_number_field(module_name,
                                             f"{base}.tier_mult.{raw_tier}", raw_mult,
                                             min_value=0.0)
        aw = cfg.get("axis_weights")
        if aw is not None:
            if not isinstance(aw, Mapping):
                self._err(module_name, f"{base}.axis_weights", "R-1", rule="type",
                          expect="obj", got=type(aw).__name__)
            else:
                for raw_axis, raw_entry in aw.items():
                    apath = f"{base}.axis_weights.{raw_axis}"
                    if not isinstance(raw_entry, Mapping):
                        self._err(module_name, apath, "R-1", rule="type", expect="obj",
                                  got=type(raw_entry).__name__)
                        continue
                    for field in ("calib", "output", "survival"):
                        if field not in raw_entry:
                            continue
                        self._check_number_field(module_name, f"{apath}.{field}",
                                                 raw_entry.get(field))
                    calib = raw_entry.get("calib")
                    if (isinstance(calib, (int, float)) and not isinstance(calib, bool)
                            and float(calib) == 0.0):
                        self._warn(module_name, f"{apath}.calib", "Y-20",
                                   rule="effect_weight_zero_calib",
                                   msg="权表 calib=0 → 该键永不参与等效折算"
                                       "（多半是笔误；不阻断）")

    def _check_number_field(self, module_name: str, path: str, value: object,
                            min_value: Optional[float] = None) -> None:
        """通用「数值字段」红拦：非数值/布尔 → R-1；NaN/Inf → R-3；低于下界 → R-2。"""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._err(module_name, path, "R-1", rule="type", expect="number",
                      got=("bool" if isinstance(value, bool) else type(value).__name__))
            return
        fv = float(value)
        if math.isnan(fv) or math.isinf(fv):
            self._err(module_name, path, "R-3", rule="not_a_number", value=value)
            return
        if min_value is not None and fv < float(min_value):
            self._err(module_name, path, "R-2", rule="value_below_min", value=value,
                      range_min=min_value)

    def _check_effect_budget_entries(self, module_name: str, data: object) -> None:
        """条目级特效等效越界（`items`/`equipment` 词条 + `runes` 数值档；批55）。

        独立钩子（不依赖 settings 模块是否先校验）：只有 `settings.effect_budget.enabled
        == true` 时才生效；**条目配额 = `cap_equiv_pct`**（无档位语境，故不乘 `tier_mult`）。
        越界 / 权表未登记轴的呈现方式由 `gate_mode` / `unknown_axis` 决定：
          · `warn` → **黄提示 Y-20**（不阻断）；`red` → **红拦 R-5**（拒绝）；
          · `off` / `ignore` → 静默（只判不报）。只读遍历，不改任何数据。
        """
        modules = self._modules
        settings = modules.get("settings")
        cfg = settings.get("effect_budget") if isinstance(settings, Mapping) else None
        if not isinstance(cfg, Mapping):
            return
        if not bool(normalize_effect_budget(cfg)["enabled"]):
            return
        path_fn = _effect_rune_paths if module_name == "runes" else _effect_entry_paths
        for path, bag in path_fn(module_name, data):
            values = effect_values_of(bag, cfg)
            if not values:
                continue
            res = check_effect_budget(values, None, cfg)
            if res["action"] == "ok":
                continue
            if res["over"]:
                msg = (f"条目特效等效 {res['equiv_pct']:.2f}% 超条目配额 "
                       f"{res['cap_pct']:.2f}%（输出等效 {res['output_pct']:.2f}% / "
                       f"生存等效 {res['survival_pct']:.2f}%）")
            else:
                msg = f"条目命中权表未登记的特效轴（等效 {res['equiv_pct']:.2f}%）"
            if res["unknown"]:
                msg += f"；未登记轴：{'、'.join(res['unknown'])}"
            detail = {"value": res["equiv_pct"], "range_max": res["cap_pct"],
                      "axis": res["unknown"], "msg": msg}
            if res["action"] == "red":
                self._err(module_name, path, "R-5",
                          rule="effect_budget_entry_over_cap", **detail)
            else:
                self._warn(module_name, path, "Y-20",
                           rule="effect_budget_entry_over_cap", **detail)

    # ---- 批50 · 特效轴地基：settings.effect_axes 逐轴声明 + 内容侧取值越界 ----
    def _check_effect_axes(self, module_name: str, data: object) -> None:
        """`settings.effect_axes` 段 + 特效轴取值专项校验（批50 · 特效轴地基）。

        依据：`特效整理设计_1_修正轴全集.md` §2/§3 + `特效整理设计_3_落点与分期.md`
        §1.0（表示口径：百分点增量轴，默认 0）+ §二「批48」（= 本批，旧编号）。
        登记表唯一源：`data.gear_stats.EFFECT_AXIS_SPECS` / `GEAR_EFFECT_KEYS`。

        分级（三条按批次要求，另加两条卫生检查）：
          · 段结构错误（非对象）→ **红拦 R-1**；
          · 轴条目非对象 / min/max/default 非数值（含布尔）→ **红拦 R-1**；
          · NaN/Inf → **红拦 R-3**；
          · `min > max`、`default ∉ [min, max]` → **红拦 R-2**（越界红拦）；
          · 轴名 stem ∈ 面板三轴 stem（`PANEL_AXIS_STEMS`）→ **红拦 R-4**（撞名会让
            `route_bonus_into` 与面板属性 pct 层混淆）；
          · 已按 D 组裁决**废弃**的轴（`DEPRECATED_EFFECT_AXES`，如
            `action_recovery_pct`）→ **黄提示 Y-18**（不硬拦；提示改用替代轴——D2 裁决
            行动速度/后摇二选一，并存会指数级加速）；
          · 未登记轴（不在 `GEAR_EFFECT_KEYS`）→ **黄提示 Y-18**（自造轴，不硬拦）；
          · `stack`/`display.mode` 取值不在册 → **黄提示 Y-18**（不硬拦）。
        内容侧取值越界（**越界红拦**）：`items` / `equipment` 顶层词条键 + `runes` 的
        `by_equip_type[*].stats`，凡命中特效轴且超出有效范围 → **红拦 R-2**。
        缺段：默认放行（登记表建议缺省 = 恒等 → 引擎零变化）。
        """
        if not isinstance(data, Mapping):
            return
        base = "settings.effect_axes"
        cfg = data.get("effect_axes")
        if cfg is None:
            return  # 未声明该段：登记表建议缺省 = 恒等 → 零红零黄（内容侧取值另钩子）
        if not isinstance(cfg, Mapping):
            self._err(module_name, base, "R-1", rule="section_structure",
                      got=type(cfg).__name__,
                      msg="effect_axes 段要填对象（{轴键: {min/max/default/display/stack}}）"
                          "或删掉该段（删掉 = 用框架登记的建议缺省）")
            return
        known = set(GEAR_EFFECT_KEYS)
        panel_stems = set(PANEL_AXIS_STEMS)
        effective = normalize_effect_axes(cfg)
        for raw_axis, raw_entry in cfg.items():
            axis = str(raw_axis)
            path = f"{base}.{axis}"
            if axis not in known:
                dep = DEPRECATED_EFFECT_AXES.get(axis)
                if dep is not None:
                    replacement, why = dep
                    self._warn(module_name, path, "Y-18", rule="effect_axis_deprecated",
                               axis=axis, replacement=replacement,
                               msg=f"轴「{axis}」已按裁决废弃，请改用「{replacement}」"
                                   f"（{why}）")
                else:
                    self._warn(module_name, path, "Y-18", rule="effect_axis_unknown",
                               axis=axis, key_space=sorted(known),
                               msg=f"未登记的特效轴「{axis}」：框架登记表里没有它，"
                                   "该声明不会被任何消费点读取（不阻断）")
            stem = effect_axis_stem(axis)
            if stem in panel_stems:
                self._err(module_name, path, "R-4", rule="effect_axis_stem_conflict",
                          axis=axis, stem=stem, key_space=sorted(panel_stems),
                          msg=f"轴名「{axis}」的属性 stem「{stem}」与面板轴撞名——"
                              "会与面板属性百分比层混淆，请换名")
            if not isinstance(raw_entry, Mapping):
                self._err(module_name, path, "R-1", rule="type", expect="obj",
                          got=type(raw_entry).__name__)
                continue
            nums: Dict[str, float] = {}
            for field in ("min", "max", "default"):
                if field not in raw_entry:
                    continue
                val = raw_entry.get(field)
                fpath = f"{path}.{field}"
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._err(module_name, fpath, "R-1", rule="type", expect="number",
                              got=("bool" if isinstance(val, bool) else type(val).__name__))
                    continue
                fv = float(val)
                if math.isnan(fv) or math.isinf(fv):
                    self._err(module_name, fpath, "R-3", rule="not_a_number", value=val)
                    continue
                nums[field] = fv
            lo = nums.get("min", effective.get(axis, {}).get("min"))
            hi = nums.get("max", effective.get(axis, {}).get("max"))
            if lo is not None and hi is not None and float(lo) > float(hi):
                self._err(module_name, path, "R-2", rule="effect_axis_range_inverted",
                          min=lo, max=hi, msg="下限大于上限，区间无效")
            dflt = nums.get("default")
            if dflt is not None:
                if lo is not None and dflt < float(lo):
                    self._err(module_name, f"{path}.default", "R-2",
                              rule="effect_axis_default_out_of_range", value=dflt,
                              range_min=lo, range_max=hi)
                elif hi is not None and dflt > float(hi):
                    self._err(module_name, f"{path}.default", "R-2",
                              rule="effect_axis_default_out_of_range", value=dflt,
                              range_min=lo, range_max=hi)
            stack = raw_entry.get("stack")
            if stack is not None and str(stack) not in ("add", "mult"):
                self._warn(module_name, f"{path}.stack", "Y-18", rule="effect_axis_stack_unknown",
                           got=str(stack), msg="聚合方式不在册（add/mult），消费点将按缺省 add")
            disp = raw_entry.get("display")
            if isinstance(disp, Mapping):
                mode = disp.get("mode")
                if mode is not None and str(mode) not in ("mult", "delta"):
                    self._warn(module_name, f"{path}.display.mode", "Y-18",
                               rule="effect_axis_display_mode_unknown", got=str(mode),
                               msg="显示口径不在册（mult/delta），编辑器将按缺省 mult")

    def _check_effect_axis_values(self, module_name: str, data: object) -> None:
        """内容侧特效轴取值越界红拦（R-2）：装备/物品词条 + 符文数值档（批50）。

        独立钩子（在 items/equipment/runes 分派处调用，**不依赖 settings 模块是否存在**）：
        范围取 `settings.effect_axes` 有效声明（缺省 = 登记表建议范围），由
        `normalize_effect_axes` 合并。只读遍历，不改任何数据；未命中特效轴 → 零检查零提示。
        """
        modules = self._modules
        settings = modules.get("settings")
        cfg = settings.get("effect_axes") if isinstance(settings, Mapping) else None
        effective = normalize_effect_axes(cfg)
        axes = set(GEAR_EFFECT_KEYS)
        path_fn = _effect_rune_paths if module_name == "runes" else _effect_entry_paths
        for path, bag in path_fn(module_name, data):
            for key, val in bag.items():
                axis = str(key)
                if axis not in axes:
                    dep = DEPRECATED_EFFECT_AXES.get(axis)
                    if dep is not None:
                        replacement, why = dep
                        self._warn(module_name, f"{path}.{axis}", "Y-18",
                                   rule="effect_axis_deprecated", axis=axis,
                                   replacement=replacement,
                                   msg=f"词条「{axis}」已按裁决废弃，请改用"
                                       f"「{replacement}」（{why}）")
                    continue
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    continue
                fv = float(val)
                if math.isnan(fv) or math.isinf(fv):
                    continue
                rng = effective.get(axis) or {}
                lo, hi = rng.get("min"), rng.get("max")
                fpath = f"{path}.{axis}"
                if lo is not None and fv < float(lo):
                    self._err(module_name, fpath, "R-2",
                              rule="effect_axis_value_out_of_range",
                              value=fv, range_min=lo, range_max=hi,
                              msg="特效轴取值低于声明下限")
                elif hi is not None and fv > float(hi):
                    self._err(module_name, fpath, "R-2",
                              rule="effect_axis_value_out_of_range",
                              value=fv, range_min=lo, range_max=hi,
                              msg="特效轴取值高于声明上限")

    # ---- 批56 · 过量治疗：settings.overheal 开关（D4 / 轴全集 §4-E5）----
    def _check_overheal(self, module_name: str, data: object) -> None:
        """`settings.overheal` 段校验（批56 · D4 / `特效整理设计_1_修正轴全集.md` §4-E5）。

        E5 口径 = **布尔开关**（治疗可否超过最大 HP），不是数值轴。分级：
          · 段结构非对象（且非裸布尔）→ **红拦 R-1**；
          · `enabled` 存在但非布尔 → **红拦 R-1**；
          · 未知键 / 缺段 → 默认放行（缺段 = 关闭 = 与现状一致：过量部分**丢弃**）。
        裸布尔（`overheal: true`）为宽松兼容形态，不拦。
        """
        if not isinstance(data, Mapping):
            return
        base = f"settings.{OVERHEAL_KEY}"
        cfg = data.get(OVERHEAL_KEY)
        if cfg is None or isinstance(cfg, bool):
            return
        if not isinstance(cfg, Mapping):
            self._err(module_name, base, "R-1", rule="section_structure",
                      got=type(cfg).__name__,
                      msg="overheal 段要填对象（如 {\"enabled\": true}）或删掉该段"
                          "（删掉 = 关闭 = 与现状一致：过量部分丢弃）")
            return
        enabled = cfg.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            self._err(module_name, f"{base}.enabled", "R-1", rule="type", expect="bool",
                      got=type(enabled).__name__)

    # ---- 批57 · 精粹产出率：settings.forge.essence_rate ----
    def _check_essence_rate(self, module_name: str, data: object) -> None:
        """`settings.forge.essence_rate` 段校验（批57 · 报告 §3.1/§3.4 + 主 agent ①/②）。

        分级：
          · 段结构非对象 → **红拦 R-1**；
          · `enabled`/数值/枚举/区间非法 → **红拦 R-1**；
          · `enabled=true` 但 `essence_currency` 不在 `settings.currencies`（也不在
            `items`）注册表 → **红拦 R-4**（报告 V8：否则运行时入账被静默拒绝）；
          · 缺段 / enabled=false / 未知键 → 默认放行（未启用 = 现状逐字段一致）。
        """
        if not isinstance(data, Mapping):
            return
        base = "settings.forge.essence_rate"
        forge = data.get("forge")
        if not isinstance(forge, Mapping):
            return
        cfg = forge.get("essence_rate")
        if cfg is None:
            return
        if not isinstance(cfg, Mapping):
            self._err(module_name, base, "R-1", rule="section_structure",
                      got=type(cfg).__name__,
                      msg="essence_rate 段要填对象（删掉该段 = 未启用精粹 = 与现状一致）")
            return
        en = cfg.get("enabled")
        if en is not None and not isinstance(en, bool):
            self._err(module_name, f"{base}.enabled", "R-1", rule="type", expect="bool",
                      got=type(en).__name__)
        _NUM = {"k1": (0.0, None), "k2": (0.0, None), "beta": (0.0, None),
                "v_fixed": (0.0, None), "v_per_level": (0.0, None),
                "refund_decay": (0.0, 1.0)}
        for k, (lo, hi) in _NUM.items():
            if k not in cfg:
                continue
            v = cfg.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                self._err(module_name, f"{base}.{k}", "R-1", rule="type", expect="number",
                          got=type(v).__name__)
                continue
            if v < lo or (hi is not None and v > hi):
                self._err(module_name, f"{base}.{k}", "R-1", rule="range",
                          value=v, msg=f"{k} 须在 [{lo},{hi if hi is not None else '∞'}]")
        tr = cfg.get("temper_refund")
        if tr is not None and (isinstance(tr, bool) or not isinstance(tr, int) or tr < 0):
            self._err(module_name, f"{base}.temper_refund", "R-1", rule="type",
                      msg="temper_refund 须为非负整数")
        rnd = cfg.get("rounding")
        if rnd is not None and rnd not in ("floor", "round", "ceil"):
            self._err(module_name, f"{base}.rounding", "R-1", rule="enum",
                      got=rnd, msg="rounding 须 floor/round/ceil")
        sc = cfg.get("scope")
        if sc is not None and sc not in ("crafted_equipment", "all_equipment"):
            self._err(module_name, f"{base}.scope", "R-1", rule="enum", got=sc,
                      msg="scope 须 crafted_equipment/all_equipment")
        # V8（报告）：启用精粹时，精粹货币须登记在 currencies（或 items）注册表。
        if en is True:
            cur = cfg.get("essence_currency")
            if not isinstance(cur, str) or not cur:
                self._err(module_name, f"{base}.essence_currency", "R-4", rule="required",
                          msg="启用精粹必须声明 essence_currency")
            else:
                ids = self._settings_currency_ids(data)
                items = data.get("items")
                in_items = isinstance(items, list) and any(
                    isinstance(e, Mapping) and str(e.get("id") or "") == cur for e in items
                )
                if cur not in ids and not in_items:
                    self._err(module_name, f"{base}.essence_currency", "R-4",
                              rule="currency_ref_missing", currency=cur,
                              msg=f"精粹货币「{cur}」未登记在 settings.currencies（或 items）"
                                  "——运行时入账会被拒绝")

    # ---- 批39 · 合成/炼金/打造启用矩阵：settings.deep_craft 打造路径开关 ----
    def _check_deep_craft(self, module_name: str, data: object) -> None:
        """settings.deep_craft 段校验（批39 · 打造路径开关）。

        依据：docs/深度打造_决策记录.md §六（三条启用路径：合成 / 合成+炼金 / 合成+打造）；
        推导唯一入口 core/craft_paths.py（obj + enabled，默认关，对齐批38 equipment_offhand）。

        分级：
          · 段结构错误（非对象）→ **红拦 R-1**；
          · `enabled` 非布尔 → **红拦 R-1**；
          · `enabled=true` 但 `settings.alchemy.mode=off`（公用合成层已关）→ **黄提示 Y-15**
            （打造只做深度层，基础合成走公用层；合成关时打造不可用，只提示不拦，用户可先开
            合成再开打造）。
        未知键 / 缺段：默认放行（缺段 = 打造关闭 = 本系统引入前行为）。
        """
        if not isinstance(data, Mapping):
            return
        base = "settings.deep_craft"
        cfg = data.get("deep_craft")
        if cfg is None:
            return
        if not isinstance(cfg, Mapping):
            self._err(module_name, base, "R-1", rule="section_structure",
                      got=type(cfg).__name__,
                      msg="deep_craft 段要填对象（配置块 { ... }，如 {\"enabled\": true}）"
                          "或删掉该段")
            return
        en = cfg.get("enabled")
        if en is not None and not isinstance(en, bool):
            self._err(module_name, f"{base}.enabled", "R-1", rule="type",
                      expect="bool", got=type(en).__name__)
            return
        if en is True:
            alchemy = data.get("alchemy")
            mode = alchemy.get("mode") if isinstance(alchemy, Mapping) else None
            if mode == "off":
                self._warn(module_name, base, "Y-15", rule="forge_without_synthesis",
                           msg="深度打造已开启，但 settings.alchemy.mode=off（公用合成层已关闭）"
                               "→ 打造路径当前不可用（深度打造的基础合成走公用合成层）；"
                               "不阻断，开启合成层后生效")
        # ---- 批41 · 打造参数段 / 品质颜色 / 图纸档位 / 品质概率阶梯 ----
        # 分级：结构/类型/枚举/范围非法 → R-1；id 缺失/重复 → R-5；概率阶梯行权重和
        # 非 100 → Y 提示（概率表允许按比例缩放，不硬拦）；顶档颜色出现在第 10 行之前
        # → R-1（原案 §6「红色只有 10 级品质有 5% 的概率」）。
        rules = cfg.get("craft_rules")
        if rules is not None and not isinstance(rules, Mapping):
            self._err(module_name, f"{base}.craft_rules", "R-1", rule="type",
                      expect="obj", got=type(rules).__name__)
        elif isinstance(rules, Mapping):
            self._check_deep_craft_rules(module_name, f"{base}.craft_rules", rules)
        raw_colors = cfg.get("quality_colors")
        color_ids: List[str] = []
        if raw_colors is not None:
            if not isinstance(raw_colors, list):
                self._err(module_name, f"{base}.quality_colors", "R-1", rule="type",
                          expect="list", got=type(raw_colors).__name__)
            else:
                seen_c: set = set()
                for i, e in enumerate(raw_colors):
                    m = e if isinstance(e, Mapping) else None
                    path = f"{base}.quality_colors.{i}"
                    if m is None:
                        self._err(module_name, path, "R-1", rule="entry_not_object",
                                  got=type(e).__name__)
                        continue
                    cid = m.get("id")
                    if not isinstance(cid, str) or not cid:
                        self._err(module_name, path, "R-5", rule="required_missing", name="id")
                    elif cid in seen_c:
                        self._err(module_name, path, "R-5", rule="duplicate_id", id=cid)
                    else:
                        seen_c.add(cid)
                        color_ids.append(cid)
        raw_grades = cfg.get("blueprint_grades")
        if raw_grades is not None:
            if not isinstance(raw_grades, list):
                self._err(module_name, f"{base}.blueprint_grades", "R-1", rule="type",
                          expect="list", got=type(raw_grades).__name__)
            else:
                seen_g: set = set()
                for i, e in enumerate(raw_grades):
                    m = e if isinstance(e, Mapping) else None
                    path = f"{base}.blueprint_grades.{i}"
                    if m is None:
                        self._err(module_name, path, "R-1", rule="entry_not_object",
                                  got=type(e).__name__)
                        continue
                    gid = m.get("id")
                    if not isinstance(gid, str) or not gid:
                        self._err(module_name, path, "R-5", rule="required_missing", name="id")
                    elif gid in seen_g:
                        self._err(module_name, path, "R-5", rule="duplicate_id", id=gid)
                    else:
                        seen_g.add(gid)
                    lo = m.get("level_offset")
                    if lo is not None and (isinstance(lo, bool) or not isinstance(lo, int)
                                           or lo < 0):
                        self._err(module_name, f"{path}.level_offset", "R-2",
                                  rule="range", got=lo, min=0)
                    cc = m.get("cost_cap")
                    if cc is not None and (isinstance(cc, bool) or not isinstance(cc, int)
                                           or cc < 0):
                        self._err(module_name, f"{path}.cost_cap", "R-2",
                                  rule="range", got=cc, min=0)
        table = cfg.get("quality_draw_table")
        if table is not None:
            if not isinstance(table, Mapping):
                self._err(module_name, f"{base}.quality_draw_table", "R-1", rule="type",
                          expect="obj", got=type(table).__name__)
            else:
                ladder = table.get("ladder")
                if ladder is not None and not isinstance(ladder, Mapping):
                    self._err(module_name, f"{base}.quality_draw_table.ladder", "R-1",
                              rule="type", expect="obj", got=type(ladder).__name__)
                elif isinstance(ladder, Mapping):
                    top = color_ids[-1] if color_ids else None
                    for row_key, row in ladder.items():
                        path = f"{base}.quality_draw_table.ladder.{row_key}"
                        if not isinstance(row, Mapping):
                            self._err(module_name, path, "R-1", rule="entry_not_object",
                                      got=type(row).__name__)
                            continue
                        row_no = None
                        if isinstance(row_key, str) and row_key.isdigit():
                            row_no = int(row_key)
                        total = 0.0
                        for ck, wv in row.items():
                            if isinstance(wv, bool) or not isinstance(wv, (int, float)):
                                self._err(module_name, f"{path}.{ck}", "R-1", rule="type",
                                          expect="number", got=type(wv).__name__)
                                continue
                            if wv < 0:
                                self._err(module_name, f"{path}.{ck}", "R-2", rule="range",
                                          got=wv, min=0)
                            total += float(wv)
                            if color_ids and ck not in color_ids:
                                self._err(module_name, f"{path}.{ck}", "R-4",
                                          rule="color_ref_missing", color=ck,
                                          color_space=sorted(color_ids))
                        if total > 0 and abs(total - 100.0) > 1e-6:
                            self._warn(module_name, path, "Y-16", rule="row_sum",
                                       total=total,
                                       msg=f"品质阶梯第 {row_no if row_no else row_key} 行"
                                           "权重和不为 100（按比例抽取，仅提示）")
                        if top and row_no is not None and row_no < 10 and top in row:
                            self._err(module_name, f"{path}.{top}", "R-1",
                                      rule="top_color_row", row=row_no,
                                      msg="顶档品质只能出现在第 10 行及以后（原案 §6）")

    def _check_deep_craft_rules(self, module_name: str, base: str,
                                rules: Mapping[str, object]) -> None:
        """settings.deep_craft.craft_rules 子字段校验（批41；范围/枚举/阈值单调）。"""
        rng_keys = ("cost_base", "cost_per_kind", "max_per_kind", "max_kinds")
        for key in rng_keys:
            v = rules.get(key)
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                self._err(module_name, f"{base}.{key}", "R-2", rule="range", got=v, min=0)
        for key in ("slot_decay", "cost_floor_ratio", "global_decay"):
            v = rules.get(key)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                  or v < 0):
                self._err(module_name, f"{base}.{key}", "R-2", rule="range", got=v, min=0)
        bonus = rules.get("quality_exp_affinity_bonus")
        if bonus is not None and (isinstance(bonus, bool)
                                  or not isinstance(bonus, (int, float)) or bonus < 0):
            self._err(module_name, f"{base}.quality_exp_affinity_bonus", "R-2",
                      rule="range", got=bonus, min=0)
        tb = rules.get("type_bonus")
        if tb is not None and (isinstance(tb, bool) or not isinstance(tb, (int, float))
                               or tb < 0):
            self._err(module_name, f"{base}.type_bonus", "R-2", rule="range", got=tb, min=0)
        rnd = rules.get("level_rounding")
        if rnd is not None and rnd not in ("floor", "round", "ceil"):
            self._err(module_name, f"{base}.level_rounding", "R-1", rule="enum_invalid",
                      got=rnd, allowed=["floor", "round", "ceil"])
        w = rules.get("material_level_weight")
        if w is not None and not isinstance(w, Mapping):
            self._err(module_name, f"{base}.material_level_weight", "R-1", rule="type",
                      expect="obj", got=type(w).__name__)
        th = rules.get("quality_level_thresholds")
        if th is not None:
            if not isinstance(th, list) or not th:
                self._err(module_name, f"{base}.quality_level_thresholds", "R-1",
                          rule="type", expect="list", got=type(th).__name__)
            else:
                prev = None
                for i, x in enumerate(th):
                    if isinstance(x, bool) or not isinstance(x, int) or x < 0:
                        self._err(module_name, f"{base}.quality_level_thresholds.{i}", "R-2",
                                  rule="range", got=x, min=0)
                        continue
                    if prev is not None and x < prev:
                        self._err(module_name, f"{base}.quality_level_thresholds.{i}", "R-1",
                                  rule="not_monotonic", got=x, prev=prev)
                    prev = x
        for key in ("random_stat_count", "random_set_affix_count"):
            v = rules.get(key)
            if v is not None and not isinstance(v, Mapping):
                self._err(module_name, f"{base}.{key}", "R-1", rule="type",
                          expect="obj", got=type(v).__name__)
        # ---- 批44 · 投入概率暴击（§七；结构/类型/范围/枚举红拦，只增不减）----
        crit = rules.get("quality_exp_crit")
        if crit is not None and not isinstance(crit, Mapping):
            self._err(module_name, f"{base}.quality_exp_crit", "R-1", rule="type",
                      expect="obj", got=type(crit).__name__)
        elif isinstance(crit, Mapping):
            self._check_quality_exp_crit(module_name, f"{base}.quality_exp_crit", crit)

    def _check_quality_exp_crit(self, module_name: str, base: str,
                                crit: Mapping[str, object]) -> None:
        """`craft_rules.quality_exp_crit`（批44 投入概率暴击）子字段校验。

        分级：结构/类型/枚举非法 → R-1；范围越界 → R-2；`enabled=true` 但所有生效档位
        概率 ≤0 → **黄提示 Y-17**（永不触发，仅提示不拦）。只增不减、不放宽既有门禁。
        """
        def _is_num(v: object) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        en = crit.get("enabled")
        if en is not None and not isinstance(en, bool):
            self._err(module_name, f"{base}.enabled", "R-1", rule="type",
                      expect="bool", got=type(en).__name__)
        grades = crit.get("grades")
        if grades is not None:
            if not isinstance(grades, list):
                self._err(module_name, f"{base}.grades", "R-1", rule="type",
                          expect="list", got=type(grades).__name__)
            else:
                for i, g in enumerate(grades):
                    if not isinstance(g, str) or not g:
                        self._err(module_name, f"{base}.grades.{i}", "R-1", rule="type",
                                  expect="str", got=type(g).__name__)
        for key, lo, hi in (("chance_by_grade", 0.0, 1.0), ("mult_by_grade", 0.0, None)):
            m = crit.get(key)
            if m is None:
                continue
            if not isinstance(m, Mapping):
                self._err(module_name, f"{base}.{key}", "R-1", rule="type",
                          expect="obj", got=type(m).__name__)
                continue
            for gk, gv in m.items():
                path = f"{base}.{key}.{gk}"
                if not isinstance(gk, str) or not gk:
                    self._err(module_name, path, "R-1", rule="type",
                              expect="str", got=type(gk).__name__)
                    continue
                if not _is_num(gv):
                    self._err(module_name, path, "R-1", rule="type",
                              expect="number", got=type(gv).__name__)
                elif gv < lo or (hi is not None and gv > hi):
                    self._err(module_name, path, "R-2", rule="range", got=gv,
                              min=lo, max=hi)
        cd = crit.get("chance_default")
        if cd is not None and (_is_num(cd) is False or cd < 0 or cd > 1):
            self._err(module_name, f"{base}.chance_default", "R-2", rule="range",
                      got=cd, min=0, max=1)
        md = crit.get("mult_default")
        if md is not None and (_is_num(md) is False or md < 0):
            self._err(module_name, f"{base}.mult_default", "R-2", rule="range",
                      got=md, min=0)
        ad = crit.get("additive_exp")
        if ad is not None and not _is_num(ad):
            self._err(module_name, f"{base}.additive_exp", "R-1", rule="type",
                      expect="number", got=type(ad).__name__)
        scope = crit.get("applies_to")
        if scope is not None and scope != "quality_exp":
            self._err(module_name, f"{base}.applies_to", "R-1", rule="enum_invalid",
                      got=scope, allowed=["quality_exp"])
        affects = crit.get("affects_quality_level")
        if affects is not None and not isinstance(affects, bool):
            self._err(module_name, f"{base}.affects_quality_level", "R-1", rule="type",
                      expect="bool", got=type(affects).__name__)
        rolls = crit.get("rolls_per_craft")
        if rolls is not None and (isinstance(rolls, bool) or not isinstance(rolls, int)
                                  or rolls < 1 or rolls > 2):
            self._err(module_name, f"{base}.rolls_per_craft", "R-2", rule="range",
                      got=rolls, min=1, max=2)
        cap = crit.get("exp_cap")
        if cap is not None and cap not in ("none", "last_threshold"):
            if not _is_num(cap):
                self._err(module_name, f"{base}.exp_cap", "R-1", rule="enum_invalid",
                          got=cap, allowed=["none", "last_threshold", "number"])
            elif cap < 0:
                self._err(module_name, f"{base}.exp_cap", "R-2", rule="range", got=cap, min=0)
        stream = crit.get("rng_stream")
        if stream is not None and stream != "player":
            self._err(module_name, f"{base}.rng_stream", "R-1", rule="enum_invalid",
                      got=stream, allowed=["player"])
        # 黄提示：启用但所有生效档位概率 ≤0 → 永不触发（不拦）。
        if en is True:
            chance_default = cd if _is_num(cd) else None
            by_grade = crit.get("chance_by_grade")
            vals: List[float] = []
            if isinstance(by_grade, Mapping):
                vals += [float(v) for v in by_grade.values() if _is_num(v)]
            if chance_default is not None:
                vals.append(float(chance_default))
            if vals and max(vals) <= 0:
                self._warn(module_name, base, "Y-17", rule="crit_never_triggers",
                           msg="已启用投入暴击，但所有档位概率 ≤0 → 永不触发（仅提示，不拦）")

    def _check_deep_craft_entries(self, module_name: str, data: object) -> None:
        """items/equipment 条目：材料打造字段 + 图纸模板字段（批41 深度打造）。

        分级：
          · `material_level` int≥1 / `craft_cost` int≥0 / `blueprint_cost_cap` int≥0 → R-2；
          · `material_quality` ∉ 品质颜色空间 → R-4；
          · 图纸 `blueprint_grade` ∉ 图纸档位空间 → R-4；
            `blueprint_output` ∉ 物品 id 空间 → R-4；`blueprint_slot` ∉ slot_defs → R-4；
            `blueprint_recipe` 非空但不在 recipe id 空间 → R-4；
          · `blueprint_level_band` min/max 非法或 min>max → R-1/R-2；
          · `blueprint_material_slots[].role` ∉ {main,free} → R-1；`item` 引用缺失 → R-4；
          · 随机属性/套装词条条数 min>max 或 >2 → R-2。
        仅当条目带打造字段时校验（普通物品/材料零新增拦截）。
        """
        if not isinstance(data, list):
            return
        settings = self._modules.get("settings")
        settings = settings if isinstance(settings, Mapping) else {}
        dc = settings.get("deep_craft")
        dc = dc if isinstance(dc, Mapping) else {}
        color_space = {
            str(r.get("id")) for r in dc.get("quality_colors") or []
            if isinstance(r, Mapping) and isinstance(r.get("id"), str) and r.get("id")
        }
        grade_space = {
            str(r.get("id")) for r in dc.get("blueprint_grades") or []
            if isinstance(r, Mapping) and isinstance(r.get("id"), str) and r.get("id")
        }
        slot_defs = settings.get("slot_defs")
        slot_space = set()
        if isinstance(slot_defs, Mapping):
            slot_space = {str(k) for k in slot_defs.keys()}
        # items ∪ equipment 同库（namespace=item_lib）；未声明该 namespace 时回落两 kind 并集。
        item_space = set(self._ns_registered.get("item_lib", {}))
        if not item_space:
            item_space = set(self._id_space.get("item", {})) | set(
                self._id_space.get("equipment", {}))
        recipe_space = set(self._id_space.get("recipe", {}))
        # 批42 · C：固定被动的 trait 引用空间 + 随机套装词条池引用空间（settings 相性段）。
        trait_space = set(self._id_space.get("trait", {}))
        pool_space = {
            str(r.get("id")) for r in settings.get("affinity_pools") or []
            if isinstance(r, Mapping) and isinstance(r.get("id"), str) and r.get("id")
        }

        for i, e in enumerate(data):
            m = e if isinstance(e, Mapping) else None
            if m is None:
                continue
            base = f"{module_name}.{i}"
            # ---- 材料 ----
            lv = m.get("material_level")
            if lv is not None and (isinstance(lv, bool) or not isinstance(lv, int) or lv < 1):
                self._err(module_name, f"{base}.material_level", "R-2", rule="range",
                          got=lv, min=1)
            mc = m.get("craft_cost")
            if mc is not None and (isinstance(mc, bool) or not isinstance(mc, int) or mc < 0):
                self._err(module_name, f"{base}.craft_cost", "R-2", rule="range", got=mc, min=0)
            mq = m.get("material_quality")
            if isinstance(mq, str) and mq and color_space and mq not in color_space:
                self._err(module_name, f"{base}.material_quality", "R-4",
                          rule="color_ref_missing", color=mq, color_space=sorted(color_space))
            # ---- 图纸 ----
            grade = m.get("blueprint_grade")
            if grade is not None:
                if not isinstance(grade, str) or not grade:
                    self._err(module_name, f"{base}.blueprint_grade", "R-5",
                              rule="required_missing", name="blueprint_grade")
                elif grade_space and grade not in grade_space:
                    self._err(module_name, f"{base}.blueprint_grade", "R-4",
                              rule="grade_ref_missing", grade=grade,
                              grade_space=sorted(grade_space))
            for key, space, rule in (("blueprint_output", item_space, "item_ref_missing"),
                                     ("blueprint_slot", slot_space, "slot_ref_missing"),
                                     ("blueprint_recipe", recipe_space, "recipe_ref_missing")):
                v = m.get(key)
                if isinstance(v, str) and v and space and v not in space:
                    self._err(module_name, f"{base}.{key}", "R-4", rule=rule, ref=v,
                              ref_space=sorted(space))
            cap = m.get("blueprint_cost_cap")
            if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int)
                                    or cap < 0):
                self._err(module_name, f"{base}.blueprint_cost_cap", "R-2", rule="range",
                          got=cap, min=0)
            band = m.get("blueprint_level_band")
            if band is not None:
                if not isinstance(band, Mapping):
                    self._err(module_name, f"{base}.blueprint_level_band", "R-1",
                              rule="type", expect="obj", got=type(band).__name__)
                else:
                    lo = band.get("min")
                    hi = band.get("max")
                    for k, v in (("min", lo), ("max", hi)):
                        if v is not None and (isinstance(v, bool)
                                              or not isinstance(v, int) or v < 1):
                            self._err(module_name, f"{base}.blueprint_level_band.{k}", "R-2",
                                      rule="range", got=v, min=1)
                    if (isinstance(lo, int) and not isinstance(lo, bool)
                            and isinstance(hi, int) and not isinstance(hi, bool) and lo > hi):
                        self._err(module_name, f"{base}.blueprint_level_band", "R-1",
                                  rule="band_reversed", min=lo, max=hi)
            slots = m.get("blueprint_material_slots")
            if slots is not None:
                if not isinstance(slots, list):
                    self._err(module_name, f"{base}.blueprint_material_slots", "R-1",
                              rule="type", expect="list", got=type(slots).__name__)
                else:
                    for j, s in enumerate(slots):
                        sp = f"{base}.blueprint_material_slots.{j}"
                        if not isinstance(s, Mapping):
                            self._err(module_name, sp, "R-1", rule="entry_not_object",
                                      got=type(s).__name__)
                            continue
                        role = s.get("role")
                        if role is not None and role not in ("main", "free"):
                            self._err(module_name, f"{sp}.role", "R-1", rule="enum_invalid",
                                      got=role, allowed=["main", "free"])
                        sid = s.get("item")
                        if isinstance(sid, str) and sid and item_space and sid not in item_space:
                            self._err(module_name, f"{sp}.item", "R-4",
                                      rule="item_ref_missing", ref=sid)
            for key in ("blueprint_random_stat_count", "blueprint_random_set_affix_count"):
                cnt = m.get(key)
                if cnt is None:
                    continue
                if not isinstance(cnt, Mapping):
                    self._err(module_name, f"{base}.{key}", "R-1", rule="type",
                              expect="obj", got=type(cnt).__name__)
                    continue
                lo = cnt.get("min")
                hi = cnt.get("max")
                for k, v in (("min", lo), ("max", hi)):
                    if v is not None and (isinstance(v, bool) or not isinstance(v, int)
                                          or v < 0 or v > 2):
                        self._err(module_name, f"{base}.{key}.{k}", "R-2", rule="range",
                                  got=v, min=0, max=2)
                if (isinstance(lo, int) and not isinstance(lo, bool)
                        and isinstance(hi, int) and not isinstance(hi, bool) and lo > hi):
                    self._err(module_name, f"{base}.{key}", "R-1", rule="count_reversed",
                              min=lo, max=hi)
            # ---- 批42 · C：固定被动 trait 引用 / 随机套装词条池引用 ----
            passive = m.get("blueprint_passive")
            passive_ids = [passive] if isinstance(passive, str) else (
                passive if isinstance(passive, list) else [])
            for pid in passive_ids:
                if isinstance(pid, str) and pid and trait_space and pid not in trait_space:
                    self._err(module_name, f"{base}.blueprint_passive", "R-4",
                              rule="trait_ref_missing", ref=pid,
                              ref_space=sorted(trait_space))
            sp = m.get("blueprint_random_set_affix_pool")
            if isinstance(sp, str) and sp and pool_space and sp not in pool_space:
                self._err(module_name, f"{base}.blueprint_random_set_affix_pool", "R-4",
                          rule="pool_ref_missing", pool=sp, pool_space=sorted(pool_space))


    # ---- 批38 · ④：settings 相性通用层（定义/池/联动/互动 + 跨模块引用存在性）----
    def _check_affinity(self, module_name: str, data: object) -> None:
        """相性通用层校验（批38 · ④；打造与深度炼金共用，settings 顶层四段）。

        依据：docs/深度打造_决策记录.md §三 补充 2；原案 §8/§12；引擎 core/affinity.py。

        分级（红拦 = 引用缺失/枚举非法/ID 缺失重复 = 死配置；不硬拦其余）：
          · `affinities[].id` 缺失/重复 → R-5；`exclusive_pool` 非空但不在池 id 空间 → R-4；
          · `affinity_pools[].id` 缺失/重复 → R-5；`kind` ∉ {common,exclusive,linkage} → R-1；
            `entries[].requires_affinity` 不在相性 id 空间 → R-4；
          · `affinity_linkage[].main/sub/override_pool` 引用缺失 → R-4；
          · `affinity_reactions[].kind` ∉ {conflict,amplify,reverse} → R-1；
            conflict/amplify 缺 `pair`（2 个相性）或引用缺失 → R-4；reverse 缺 `from/to`
            或引用缺失 → R-4；
          · 材料/图纸（items/equipment 条目 `affinities` 的键）不在相性 id 空间 → R-4
            （图纸是物品的一种，故同表覆盖「材料 + 图纸」相性声明）。
        段缺失/空段：不报（无相性 = 通用池仍可查，非死配置）。
        """
        if not isinstance(data, Mapping):
            return
        base = "settings"
        raw_aff = data.get("affinities")
        aff_ids: List[str] = []
        if raw_aff is not None:
            if not isinstance(raw_aff, list):
                self._err(module_name, f"{base}.affinities", "R-1", rule="type",
                          expect="list", got=type(raw_aff).__name__)
            else:
                seen: set = set()
                for i, e in enumerate(raw_aff):
                    m = e if isinstance(e, Mapping) else None
                    path = f"{base}.affinities.{i}"
                    if m is None:
                        self._err(module_name, path, "R-1", rule="entry_not_object",
                                  got=type(e).__name__)
                        continue
                    aid = m.get("id")
                    if not isinstance(aid, str) or not aid:
                        self._err(module_name, path, "R-5", rule="required_missing", name="id")
                        continue
                    if aid in seen:
                        self._err(module_name, path, "R-5", rule="duplicate_id", id=aid)
                        continue
                    seen.add(aid)
                    aff_ids.append(aid)
        aff_space = set(aff_ids)

        pool_ids: List[str] = []
        raw_pools = data.get("affinity_pools")
        if raw_pools is not None and not isinstance(raw_pools, list):
            self._err(module_name, f"{base}.affinity_pools", "R-1", rule="type",
                      expect="list", got=type(raw_pools).__name__)
        elif isinstance(raw_pools, list):
            seen_pool: set = set()
            for i, e in enumerate(raw_pools):
                m = e if isinstance(e, Mapping) else None
                path = f"{base}.affinity_pools.{i}"
                if m is None:
                    self._err(module_name, path, "R-1", rule="entry_not_object",
                              got=type(e).__name__)
                    continue
                pid = m.get("id")
                if not isinstance(pid, str) or not pid:
                    self._err(module_name, path, "R-5", rule="required_missing", name="id")
                elif pid in seen_pool:
                    self._err(module_name, path, "R-5", rule="duplicate_id", id=pid)
                else:
                    seen_pool.add(pid)
                    pool_ids.append(pid)
                kind = m.get("kind")
                if kind is not None and kind not in POOL_KINDS:
                    self._err(module_name, f"{path}.kind", "R-1", rule="enum_invalid",
                              got=kind, allowed=list(POOL_KINDS))
                entries = m.get("entries")
                if isinstance(entries, list):
                    for j, ent in enumerate(entries):
                        if not isinstance(ent, Mapping):
                            continue
                        for req in affinity_requires(ent):
                            if req not in aff_space:
                                self._err(module_name, f"{path}.entries.{j}.requires_affinity",
                                          "R-4", rule="affinity_ref_missing", affinity=req,
                                          affinity_space=sorted(aff_space))
                        # 批42 · C：词条行载荷键类型（stat/set_affix/effect_ref）+ 权重/数值。
                        # 批43：载荷键唯一源 = data/affinity_keys.ENTRY_PAYLOAD_KEYS
                        # （新增 enhance_affix）；受门禁覆盖。
                        for key in ENTRY_PAYLOAD_KEYS:
                            v = ent.get(key)
                            if v is not None and (not isinstance(v, str) or not v):
                                self._err(module_name, f"{path}.entries.{j}.{key}", "R-1",
                                          rule="type", expect="str", got=type(v).__name__)
                        # 批43：强化特殊词条键须落在 gear_stats 唯一键空间（含占位键；
                        # 红拦新造键——占位键如冷却缩减可登记/可抽但引擎不消费）。
                        ea = ent.get(ENTRY_PAYLOAD_ENHANCE_AFFIX)
                        if isinstance(ea, str) and ea and ea not in GEAR_DISPLAY_KEYS:
                            self._err(module_name, f"{path}.entries.{j}.{ENTRY_PAYLOAD_ENHANCE_AFFIX}",
                                      "R-4", rule="gear_key_missing", key=ea,
                                      key_space=sorted(GEAR_DISPLAY_KEYS))
                        wv = ent.get("weight")
                        if wv is not None and (isinstance(wv, bool)
                                               or not isinstance(wv, (int, float)) or wv < 0):
                            self._err(module_name, f"{path}.entries.{j}.weight", "R-2",
                                      rule="range", got=wv, min=0)
                        val = ent.get("value")
                        if val is not None and (isinstance(val, bool)
                                                or not isinstance(val, (int, float))):
                            self._err(module_name, f"{path}.entries.{j}.value", "R-1",
                                      rule="type", expect="number", got=type(val).__name__)
        pool_space = set(pool_ids)

        # 专属池引用 / 联动引用
        for i, e in enumerate(raw_aff if isinstance(raw_aff, list) else []):
            m = e if isinstance(e, Mapping) else {}
            ep = m.get("exclusive_pool")
            if isinstance(ep, str) and ep and ep not in pool_space:
                self._err(module_name, f"{base}.affinities.{i}.exclusive_pool", "R-4",
                          rule="pool_ref_missing", pool=ep, pool_space=sorted(pool_space))
        raw_link = data.get("affinity_linkage")
        if raw_link is not None and not isinstance(raw_link, list):
            self._err(module_name, f"{base}.affinity_linkage", "R-1", rule="type",
                      expect="list", got=type(raw_link).__name__)
        elif isinstance(raw_link, list):
            for i, e in enumerate(raw_link):
                m = e if isinstance(e, Mapping) else None
                path = f"{base}.affinity_linkage.{i}"
                if m is None:
                    self._err(module_name, path, "R-1", rule="entry_not_object",
                              got=type(e).__name__)
                    continue
                for key in ("main", "sub"):
                    v = m.get(key)
                    if isinstance(v, str) and v and v not in aff_space:
                        self._err(module_name, f"{path}.{key}", "R-4",
                                  rule="affinity_ref_missing", affinity=v,
                                  affinity_space=sorted(aff_space))
                op = m.get("override_pool")
                if isinstance(op, str) and op and op not in pool_space:
                    self._err(module_name, f"{path}.override_pool", "R-4",
                              rule="pool_ref_missing", pool=op, pool_space=sorted(pool_space))

        # 材料互动
        raw_react = data.get("affinity_reactions")
        if raw_react is not None and not isinstance(raw_react, list):
            self._err(module_name, f"{base}.affinity_reactions", "R-1", rule="type",
                      expect="list", got=type(raw_react).__name__)
        elif isinstance(raw_react, list):
            for i, e in enumerate(raw_react):
                m = e if isinstance(e, Mapping) else None
                path = f"{base}.affinity_reactions.{i}"
                if m is None:
                    self._err(module_name, path, "R-1", rule="entry_not_object",
                              got=type(e).__name__)
                    continue
                kind = m.get("kind")
                if kind not in REACTION_KINDS:
                    self._err(module_name, f"{path}.kind", "R-1", rule="enum_invalid",
                              got=kind, allowed=list(REACTION_KINDS))
                    continue
                if kind in (REACTION_CONFLICT, REACTION_AMPLIFY):
                    pair = m.get("pair")
                    if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                        self._err(module_name, f"{path}.pair", "R-4", rule="pair_required",
                                  kind=kind)
                        continue
                    for k, ref in enumerate(pair):
                        if not isinstance(ref, str) or ref not in aff_space:
                            self._err(module_name, f"{path}.pair.{k}", "R-4",
                                      rule="affinity_ref_missing", affinity=ref,
                                      affinity_space=sorted(aff_space))
                else:  # reverse
                    for key in ("from", "to"):
                        v = m.get(key)
                        if not isinstance(v, str) or not v:
                            self._err(module_name, f"{path}.{key}", "R-5",
                                      rule="required_missing", name=key)
                        elif v not in aff_space:
                            self._err(module_name, f"{path}.{key}", "R-4",
                                      rule="affinity_ref_missing", affinity=v,
                                      affinity_space=sorted(aff_space))

        # 跨模块：材料/图纸相性声明（items/equipment 条目 affinities 的键）
        for mod in ("items", "equipment"):
            entries = self._modules.get(mod)
            if not isinstance(entries, list):
                continue
            for i, e in enumerate(entries):
                m = e if isinstance(e, Mapping) else None
                if m is None:
                    continue
                aff = m.get("affinities")
                if not isinstance(aff, Mapping):
                    continue
                for key in aff.keys():
                    if not isinstance(key, str) or not key:
                        continue
                    if key not in aff_space:
                        self._err(mod, f"{mod}.{i}.affinities.{key}", "R-4",
                                  rule="affinity_ref_missing", affinity=key,
                                  affinity_space=sorted(aff_space))

    # ---- 批18 效果扩展专项：gain_currency / learn_skill ----
    def _check_effects_18(self, module_name: str, data: object) -> None:
        """effects 段批18 新类型专项（类型相关必填/范围/引用存在性）。

        分级依据（与既有口径对齐）：
          · **红拦 R-5 required_missing**：`gain_currency` 缺 `currency` / 两个金额键都缺
            （用了却不生效 = 死配置，对齐 §2.1 R-5「死配置红拦」）；`learn_skill` 缺 `skill`；
          · **红拦 R-5 dead_range**：`amount_min > amount_max`（区间倒置，死配置）；
          · **红拦 R-4 currency_ref_missing**：`currency` 不在 `settings.currencies[].id`
            键空间（对齐 1g4 `_check_death_penalty_1g4` 的 F-02 货币引用硬拦口径；settings
            缺省 → DEFAULT_CURRENCY_IDS）；
          · **红拦 R-1 skill_level_invalid**：`level` 给了但非 ≥1 整数（负数由泛型 R-2 拦，
            0 不在泛型判定内，此处补齐；缺省 = 1 级，不报错）；
          · **不在此处**：`amount_*` 负数/非整数 → 泛型 R-2/R-1（字段元数据 int + allow_negative
            False）；`skill` 引用存在性 → 泛型 ref R-4（字段元数据 ref_target="skill"）。
        """
        if not isinstance(data, list):
            return
        settings = self._modules.get("settings")
        currency_ids = (
            self._settings_currency_ids(settings)
            if isinstance(settings, Mapping) else DEFAULT_CURRENCY_IDS
        )
        for idx, entry in enumerate(data):
            emap = self._as_mapping(entry)
            if emap is None:
                continue
            etype = emap.get("type")
            base = f"{module_name}.{idx}"
            if etype == "gain_currency":
                self._check_gain_currency(module_name, base, emap, currency_ids)
            elif etype == "learn_skill":
                self._check_learn_skill(module_name, base, emap)

    def _check_effect_trigger_points(self, module_name: str, data: object) -> None:
        """`trigger` 事件时点取值域校验（批51 · 事件补点）。

        依据：`特效整理设计_1_修正轴全集.md` §3 P0 第 1 项（I01 触发时点）；
        唯一源 `data/event_points.EVENT_POINTS`（content 层按分层契约 `content → {data}`
        只依赖 data 层，**不**反向 import core）。

        分级：
          · `trigger` 缺省 / 空串 → 放行（非事件型效果：主动作与状态 on_xxx 走各自链路）；
          · 非字符串 → **红拦 R-1**（`effects.trigger` 在 field_meta 里是 soft 展示键，
            泛型类型校验不覆盖，故在此补齐）；
          · 值 ∉ EVENT_POINTS → **黄提示 Y-19**（拼错 / 自造 / 未来时点：分派器只认
            EVENT_POINTS，该效果**永不触发**；不硬拦——允许内容包先行声明未来时点，
            对齐批50「未知轴黄提示 Y-18」的既有口径）。

        覆盖两处声明面（批48 起 `trigger` 实际被书写的两处）：
          · `effects.<idx>.trigger`；
          · `runes.<idx>.effects.<j>.trigger`（符文效果引用条目）。
        """
        if not isinstance(data, list):
            return
        known = tuple(EVENT_POINTS)
        for idx, entry in enumerate(data):
            emap = self._as_mapping(entry)
            if emap is None:
                continue
            base = f"{module_name}.{idx}"
            if module_name == "effects":
                pairs: List[Tuple[str, Mapping[str, object]]] = [(f"{base}.trigger", emap)]
            elif module_name == "runes":
                rows = emap.get("effects")
                rows = rows if isinstance(rows, list) else []
                pairs = [
                    (f"{base}.effects.{j}.trigger", r)
                    for j, r in enumerate(rows) if isinstance(r, Mapping)
                ]
            else:  # pragma: no cover —— 调用点只传 effects/runes
                pairs = []
            for path, bag in pairs:
                tv = bag.get("trigger")
                if tv is None or tv == "":
                    continue
                if not isinstance(tv, str):
                    self._err(module_name, path, "R-1", rule="type",
                              expect="str", got=type(tv).__name__)
                    continue
                if tv not in known:
                    self._warn(module_name, path, "Y-19", rule="trigger_event_unknown",
                               event=tv, key_space=list(known),
                               msg=f"未登记的触发时点「{tv}」：分派器只认 EVENT_POINTS，"
                                   "该效果在当前框架下不会触发（拼写错误？或需先由框架登记该时点）")

    def _check_gain_currency(
        self, module_name: str, base: str, entry: Mapping[str, object],
        currency_ids: Tuple[str, ...],
    ) -> None:
        """`gain_currency` 必填/范围/货币引用存在性（批18）。"""
        currency = entry.get("currency")
        if not isinstance(currency, str) or not currency:
            self._err(module_name, f"{base}.currency", "R-5",
                      rule="required_missing", name="currency", effect_type="gain_currency")
        elif currency not in currency_ids:
            self._err(module_name, f"{base}.currency", "R-4",
                      rule="currency_ref_missing", currency=currency,
                      currency_space=sorted(currency_ids))
        lo = entry.get("amount_min")
        hi = entry.get("amount_max")
        if lo is None and hi is None:
            self._err(module_name, f"{base}.amount_min/amount_max", "R-5",
                      rule="gain_currency_amount_missing", effect_type="gain_currency")
        elif (isinstance(lo, int) and not isinstance(lo, bool)
              and isinstance(hi, int) and not isinstance(hi, bool) and lo > hi):
            self._err(module_name, f"{base}.amount_min/amount_max", "R-5",
                      rule="dead_range", lo_key="amount_min", hi_key="amount_max",
                      lo=lo, hi=hi)

    def _check_learn_skill(
        self, module_name: str, base: str, entry: Mapping[str, object],
    ) -> None:
        """`learn_skill` 必填技能 + 等级范围（批18）。"""
        skill = entry.get("skill")
        if not isinstance(skill, str) or not skill:
            self._err(module_name, f"{base}.skill", "R-5",
                      rule="required_missing", name="skill", effect_type="learn_skill")
        level = entry.get("level")
        # 缺省 = 1 级（不报错）；0 由本条红拦（泛型 range_min 只黄提示、且 0 非负数）；
        # 负数 → 泛型 R-2；非整数 → 泛型 R-1（同键会叠加两条红，属如实并列，不静默）。
        if isinstance(level, int) and not isinstance(level, bool) and level == 0:
            self._err(module_name, f"{base}.level", "R-1",
                      rule="skill_level_invalid", level=level)

    def _check_message_prefix(self, module_name: str, data: object) -> None:
        """settings.message_prefix 段校验（M5-02，【前缀】§九 L112-121 + 细化_3d 附·校验器行 L358）。

        红拦（kind=MP-1，拒绝加载）：enabled 非布尔 / format 非字符串 / prefix_max_len 负数 /
            结构错误（message_prefix 段非对象 → 人话模板 msg）。字段全部有默认值
            （【前缀】§3.1 字段表全列默认；§十 示例 5 `{enabled:false}` 合法）→ 段内无强制
            必填键；JSON 格式坏由 loader 解析层拦截，校验器侧「必填缺失/结构错误」= 段形态错误。
        黄提示（kind=MP-2，可加载）：未知占位符原样输出 / format 空按默认补全 /
            format 超长（>80 字符）或占位符过多（>10 个）/ per_channel 枚举非法按 all 补全 /
            prefix_max_len>200 确认。
        """
        if not isinstance(data, Mapping):
            return
        if "message_prefix" not in data:
            return  # 段未配置 → 走默认模板（3d §1.2），无需校验
        base = "settings.message_prefix"
        mp = data["message_prefix"]
        # 结构错误（红，人话模板）：段显式 null / 非对象 → 拒绝加载
        if mp is None:
            self._err(module_name, base, "MP-1", rule="section_structure", got="null",
                      msg="message_prefix 段是空值 null，请填对象 { ... }"
                          "（如 {\"enabled\": true, \"format\": \"...\"}）或删掉该段")
            return
        if not isinstance(mp, Mapping):
            self._err(module_name, base, "MP-1", rule="section_structure",
                      got=type(mp).__name__,
                      msg="message_prefix 段要填对象（配置块 { ... }），"
                          "请检查 settings.json 该段的写法")
            return
        # enabled 非布尔（红）
        enabled = mp.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            self._err(module_name, f"{base}.enabled", "MP-1", rule="enabled_type",
                      got=type(enabled).__name__,
                      msg="message_prefix.enabled 要填 true/false（是否启用前缀），请改成布尔值")
        # format 非字符串（红）；非字符串无法做占位符/长度分析 → 直接返回
        fmt = mp.get("format")
        if fmt is not None and not isinstance(fmt, str):
            self._err(module_name, f"{base}.format", "MP-1", rule="format_type",
                      got=type(fmt).__name__,
                      msg="message_prefix.format 要填字符串（前缀格式模板），请改成文本")
            return
        # prefix_max_len 负数（红，提示按 0=不限 修正）
        pml = mp.get("prefix_max_len")
        if isinstance(pml, (int, float)) and not isinstance(pml, bool) and pml < 0:
            self._err(module_name, f"{base}.prefix_max_len", "MP-1",
                      rule="prefix_max_len_negative", value=pml,
                      msg="message_prefix.prefix_max_len 不能是负数，"
                          "请改成 0（=不限长度）或正数")
        # ---- 黄提示（可加载，kind=MP-2）----
        if isinstance(fmt, str):
            if not fmt.strip():
                # format 空 → 按默认补全提示（【前缀】L118）
                self._warn(module_name, f"{base}.format", "MP-2", rule="format_empty",
                           default=MESSAGE_PREFIX_DEFAULT_FORMAT,
                           msg="message_prefix.format 是空的，已按默认格式补全："
                               f"{MESSAGE_PREFIX_DEFAULT_FORMAT}")
            else:
                # 未知占位符 → 原样输出 + 黄提示（【前缀】L117/L75；不拦截加载）
                for token in message_prefix_unknown_placeholders(fmt):
                    self._warn(module_name, f"{base}.format", "MP-2",
                               rule="placeholder_unknown", placeholder=token,
                               msg=f"模板里有不认识的东西 {token}，会原样显示，确认？")
                # format 超长（>80 字符）或占位符过多（>10 个）→ 防刷屏提示（【前缀】L119）
                count = len(_MESSAGE_PREFIX_PLACEHOLDER_RE.findall(fmt))
                if len(fmt) > MESSAGE_PREFIX_FORMAT_MAX_LEN or count > MESSAGE_PREFIX_PLACEHOLDER_MAX:
                    self._warn(module_name, f"{base}.format", "MP-2",
                               rule="format_too_long", length=len(fmt),
                               placeholder_count=count,
                               msg="模板有点长，注意前缀别刷屏")
        # per_channel 枚举非法 → 按默认 all 补全提示（【前缀】L120）
        pc = mp.get("per_channel")
        if pc is not None and pc not in MESSAGE_PREFIX_PER_CHANNEL:
            self._warn(module_name, f"{base}.per_channel", "MP-2",
                       rule="per_channel_invalid", got=pc,
                       allowed=list(MESSAGE_PREFIX_PER_CHANNEL),
                       msg="message_prefix.per_channel 只能填 all/group/private，"
                           "已按默认 all 补全")
        # prefix_max_len 超常见区间（>200）→ 确认提示（【前缀】L121）
        if isinstance(pml, (int, float)) and not isinstance(pml, bool) \
                and pml > MESSAGE_PREFIX_MAX_LEN_COMMON:
            self._warn(module_name, f"{base}.prefix_max_len", "MP-2",
                       rule="prefix_max_len_large", value=pml,
                       msg="message_prefix.prefix_max_len 超过 200，确认是故意的？"
                           "（前缀可能刷屏）")

    # ---- map 形态模块值校验（stats/formula）----
    def _check_map_value(
        self, module_name: str, path: str, value: object, vmeta: FieldMeta
    ) -> None:
        if vmeta.type == "formula":
            # formula 模块：值为公式字符串，或 {formula: 表达式, ...}，或段级参数容器
            # （细化_M6 测试体系强化 D6 FIX-1：damage/hit/crit/.../elements 段，细化_1a §2.1）。
            if isinstance(value, str):
                self._check_value(module_name, path, "formula", value, vmeta)
            elif isinstance(value, Mapping):
                expr = value.get("formula")
                if isinstance(expr, str):
                    self._check_value(module_name, f"{path}.formula", "formula", expr, vmeta)
                elif "formula" in value:
                    self._err(module_name, path, "R-5", rule="formula_missing", name="formula")
                # M6 批6·路A FIX-1（D6 FIX-8）：无 formula 键的段级参数容器 → 透传不红拦
                # （_element_registry 已按 elements 段消费引用存在校验，validator.py L644-652）；
                # 15 条段参数红黄校验（hit 0.05-1 / cap 10-100 / tiers 低<中<高等）归
                # 实现层规划 T01「formula.json 唯一配置源与校验器」，此处不重复实现。
                # M12.5 需求1 批C3：stat_map 段宽松黄校验——value 自身即 stat_map
                # 段容器（formula 顶层键 stat_map 的值，键=语义键），各值须为非空
                # 字符串（指向 combatant 键，内容包自定义 stat 全量透传后任意键合法）；
                # 非字符串 → 黄提示不红拦（只建议不限制，未知键名是内容包自定义权利）。
                # 仅当路径末端为 .stat_map 时触发（防误伤 damage/hit 等数值段容器）。
                if path.endswith(".stat_map"):
                    for sm_key, sm_val in value.items():
                        if not (isinstance(sm_val, str) and sm_val.strip()):
                            self._warn(module_name, f"{path}.{sm_key}", "Y-1",
                                       rule="stat_map_value_not_string", value=repr(sm_val))
            else:
                # M6 批6·路A/批6B FIX-2（D6 §三 FIX-1 / §3.4 边界异常）：formula 模块允许
                # 顶层数值标量参数透传（如 monster_def_rate: 1.0 怪物防御率公式系数）——
                # 红拦仅留给明确非法类型（list/None 等非公式/非对象/非数值结构）。
                # P2-2 修复（批6B 审查）：bool 排除——与全库数字语义一致（_check_number
                # 明确 bool→R-1，避免 float(True)=1.0 在 FIX 读取器侧静默变真值）。
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return
                self._err(module_name, path, "R-1", rule="type", expect="formula|obj|number",
                          got=type(value).__name__)
            return
        if vmeta.type == "obj":
            if not isinstance(value, Mapping):
                self._err(module_name, path, "R-1", rule="type", expect="obj",
                          got=type(value).__name__)
                return
            for child, cmeta in vmeta.children.items():
                cpath = f"{path}.{child}"
                if cmeta.required and child not in value:
                    self._err(module_name, cpath, "R-5", rule="required_missing", name=child)
                if child in value:
                    self._check_value(module_name, cpath, child, value[child], cmeta)
            return  # 未知子字段默认放行（§2.3）
        self._check_value(module_name, path, "value", value, vmeta)

    # ---- 单条目校验 ----
    def _check_entry(self, module_name: str, idx: int, entry: object, mmeta: ModuleMeta) -> None:
        base = f"{module_name}.{idx}"
        entry_map = self._as_mapping(entry)
        if entry_map is None:
            self._err(module_name, base, "R-1", rule="entry_not_object", got=type(entry).__name__)
            return
        # 必填缺失（R-5，细化_3e §2.1 第 5 类）
        for fname, fmeta in mmeta.fields.items():
            if fmeta.required and (fname not in entry_map or entry_map.get(fname) is None):
                self._err(module_name, f"{base}.{fname}", "R-5", rule="required_missing", name=fname)
        # 已知字段 + 未知字段（默认放行；x_ 前缀放行，细化_3e §2.2 Y-8 / §2.3 兜底）
        for key, value in entry_map.items():
            fmeta = mmeta.fields.get(key)  # type: ignore[assignment]
            path = f"{base}.{key}"
            if fmeta is None:
                continue  # 未知字段默认放行（§2.3）
            self._check_value(module_name, path, key, value, fmeta)
        self._check_dead_config(module_name, base, entry_map)

    def _check_dead_config(self, module_name: str, base: str, entry: Mapping[str, object]) -> None:
        """死配置 R-5（细化_3e §2.1 R-5 判定口径：min>max；reset mode eq≠max；battle+revert 矛盾）。"""
        # 区间类：min > max 或 lower > upper（均存在且为数值时）
        for lo_key, hi_key in (("min", "max"), ("lower", "upper")):
            lo, hi = entry.get(lo_key), entry.get(hi_key)
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and not isinstance(lo, bool) and not isinstance(hi, bool):
                if lo > hi:
                    self._err(module_name, f"{base}.{lo_key}/{hi_key}", "R-5",
                              rule="dead_range", lo_key=lo_key, hi_key=hi_key, lo=lo, hi=hi)
        # reset.mode == "eq" 但 value != max（L157 示例）
        reset = entry.get("reset")
        if isinstance(reset, Mapping):
            mode = reset.get("mode")
            max_v = entry.get("max")
            if mode == "eq" and isinstance(max_v, (int, float)) and not isinstance(max_v, bool):
                rv = reset.get("value")
                if isinstance(rv, (int, float)) and not isinstance(rv, bool) and float(rv) != float(max_v):
                    self._err(module_name, f"{base}.reset", "R-5",
                              rule="reset_eq_mismatch", value=rv, max=max_v)
        # battle + revert 矛盾（互斥语义同时开启）
        battle = entry.get("battle")
        revert = entry.get("revert")
        if battle is True and revert is True:
            self._err(module_name, f"{base}.battle/revert", "R-5",
                      rule="battle_revert_conflict")

    # ---- 值级校验 ----
    def _check_value(
        self, module_name: str, path: str, key: str, value: object, fmeta: FieldMeta
    ) -> None:
        t = fmeta.type
        if fmeta.soft_label:
            return  # 软标注字段永不红拦（Y-5，细化_3e §2.2）
        if t in ("int", "float", "number"):
            self._check_number(module_name, path, key, value, fmeta, integer=(t == "int"))
        elif t == "str":
            if not isinstance(value, str):
                self._err(module_name, path, "R-1", rule="type", expect="str",
                          got=type(value).__name__)
        elif t == "bool":
            if not isinstance(value, bool):
                self._err(module_name, path, "R-1", rule="type", expect="bool",
                          got=type(value).__name__)
        elif t == "enum":
            if not isinstance(value, str) or value not in fmeta.enum:
                self._err(module_name, path, "R-1", rule="enum",
                          got=str(value), enum=list(fmeta.enum))
        elif t == "ref":
            if not isinstance(value, str):
                self._err(module_name, path, "R-1", rule="ref_not_str",
                          got=type(value).__name__, ref_target=fmeta.ref_target or "")
            else:
                self._check_ref(module_name, path, key, value, fmeta)
        elif t == "list":
            if not isinstance(value, list):
                self._err(module_name, path, "R-1", rule="type", expect="list",
                          got=type(value).__name__)
            elif fmeta.element is not None:
                for i, el in enumerate(value):
                    self._check_value(module_name, f"{path}.{i}", key, el, fmeta.element)
        elif t == "obj":
            if not isinstance(value, Mapping):
                self._err(module_name, path, "R-1", rule="type", expect="obj",
                          got=type(value).__name__)
                return
            for sub_key, sub_meta in fmeta.children.items():
                sub_path = f"{path}.{sub_key}"
                if sub_meta.required and sub_key not in value:
                    self._err(module_name, sub_path, "R-5", rule="required_missing", name=sub_key)
                if sub_key in value:
                    self._check_value(module_name, sub_path, sub_key, value[sub_key], sub_meta)
        elif t == "formula":
            if not isinstance(value, str):
                self._err(module_name, path, "R-1", rule="type", expect="formula",
                          got=type(value).__name__)
            else:
                hit = check_formula(value)
                if hit is not None:
                    detail = dict(hit)
                    detail["rule"] = "formula_safety"
                    self._err(module_name, path, "R-5", **detail)

    def _check_number(
        self, module_name: str, path: str, key: str, value: object, fmeta: FieldMeta, integer: bool
    ) -> None:
        if isinstance(value, bool):
            self._err(module_name, path, "R-1", rule="type", expect="number",
                      got="bool")
            return
        if isinstance(value, str):
            # 字符串数字「12」算类型错误 R-1（细化_3e §2.1 R-1；【规则】L153）
            self._err(module_name, path, "R-1", rule="type", expect="number", got="str")
            return
        if isinstance(value, (int, float)):
            if integer and not isinstance(value, int):
                self._err(module_name, path, "R-1", rule="type", expect="int",
                          got=type(value).__name__)
            if math.isnan(value) or math.isinf(value):
                # NaN/Infinity 统一归 R-3（细化_3e §2.1 R-3；【规则】L155）
                self._err(module_name, path, "R-3", rule="not_a_number", value=value)
                return
            if not fmeta.allow_negative and value < 0:
                self._err(module_name, path, "R-2", rule="negative", value=value)
                return
            self._hint_number(path, key, value, fmeta)
            return
        # 其它非数字内容 → R-1（数字填成文字）
        self._err(module_name, path, "R-1", rule="type", expect="number",
                  got=type(value).__name__)

    def _hint_number(self, path: str, key: str, value: object, fmeta: FieldMeta) -> None:
        v = float(value) if isinstance(value, (int, float)) else 0.0
        # Y-4：上限字段 0=不限（细化_3e §2.2 Y-4；【规则】L161/L375）
        if fmeta.zero_unlimited and v == 0:
            self._warn(path.split(".")[0], path, "Y-4", rule="zero_unlimited", value=0)
        # Y-2：概率过高/过低（>95% 或 <5%）
        if fmeta.probability:
            if v > 0.95 or v < 0.05:
                self._warn(path.split(".")[0], path, "Y-2", rule="probability_extreme",
                           value=value, hint="high" if v > 0.95 else "low")
        # Y-1：数值超出常见区间（range 列仅提示用，细化_3e §2.2 Y-1）
        if fmeta.range_min is not None and v < fmeta.range_min:
            self._warn(path.split(".")[0], path, "Y-1", rule="out_of_common_range",
                       value=value, range_min=fmeta.range_min, range_max=fmeta.range_max)
            return
        if fmeta.range_max is not None and v > fmeta.range_max:
            self._warn(path.split(".")[0], path, "Y-1", rule="out_of_common_range",
                       value=value, range_min=fmeta.range_min, range_max=fmeta.range_max)

    def _check_ref(self, module_name: str, path: str, key: str, ref_id: str, fmeta: FieldMeta) -> None:
        target = fmeta.ref_target or ""
        if target == "stat":
            # 未注册键空间 → 黄提示 Y-7（细化_3e §2.2 Y-7；【规则】L146），不红拦
            if target not in self._id_space or ref_id not in self._id_space[target]:
                self._warn(module_name, path, "Y-7", rule="stat_key_unregistered", ref=ref_id)
            return
        if target == "skill_or_any":
            # 兼容宽松引用：命中任一注册 kind 即通过（M0 无技能库模块场景）
            # 云海九期（cloudsea-pack）207 性能修复①：并集惰性缓存（原实现每次全量重建
            # O(全库 id)，12MB 包逐条目引用校验热路径放大；_register_id 写面即失效）。
            if self._all_ref_ids_cache is None:
                self._all_ref_ids_cache = {e for ids in self._id_space.values() for e in ids}
            all_reg = self._all_ref_ids_cache
            if ref_id not in all_reg:
                self._err(module_name, path, "R-4", rule="ref_missing", ref=ref_id,
                          ref_target=target)
            return
        # R-4：引用不存在（细化_3e §2.1 第 4 类；【规则】L156）
        ids = self._id_space.get(target, {})
        if ref_id not in ids:
            self._err(module_name, path, "R-4", rule="ref_missing", ref=ref_id,
                      ref_target=target)

    # ---- 结构算法 ----
    def _check_chain_cycle(self, module_name: str, data: object, mmeta: ModuleMeta) -> None:
        """连段链成环 A→B→A → R-5（细化_3e §5.2 skill_chains；【规则】L157）。"""
        adj: Dict[str, List[str]] = {}
        id_set = set()
        for _, entry in self._iter_entries(module_name, data, mmeta):
            entry_map = self._as_mapping(entry)
            if entry_map is None:
                continue
            eid = entry_map.get(mmeta.id_field)
            if not isinstance(eid, str):
                continue
            id_set.add(eid)
            nxt = entry_map.get(mmeta.chain_field)  # type: ignore[arg-type]
            if isinstance(nxt, list):
                adj.setdefault(eid, []).extend(x for x in nxt if isinstance(x, str))
        # 环检测（有向）DFS
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {n: WHITE for n in id_set}
        cycle_reported = False

        def dfs(u: str, stack: List[str]) -> Optional[List[str]]:
            nonlocal cycle_reported
            color[u] = GRAY
            stack.append(u)
            for v in adj.get(u, []):
                if v not in color:
                    continue
                if color[v] == GRAY:
                    cycle_reported = True
                    i = stack.index(v)
                    cycle = stack[i:] + [v]
                    self._err(module_name, f"{module_name}.{u}.{mmeta.chain_field}", "R-5",
                              rule="chain_cycle", cycle=cycle)
                    return cycle
                if color[v] == WHITE:
                    res = dfs(v, stack)
                    if res is not None:
                        return res
            color[u] = BLACK
            stack.pop()
            return None

        for n in id_set:
            if color[n] == WHITE and not cycle_reported:
                dfs(n, [])

    def _check_mutex_cycle(self, module_name: str, data: object, mmeta: ModuleMeta) -> None:
        """部位互斥成环 → R-5（细化_3e §5.2 equipment；【规则】L167「互相排斥形成了一个圈」）。

        互斥边为无向边：A 与 B 互斥 = 一条边 {A,B}；含环（≥3 条边）→ 环上任一部位都与其它冲突，
        谁都装不上。互斥声明为 entry.{mutex_field} = [部位 id, ...]，配 entry.slot 作自方节点。
        修复记录（M0 测试验收 2026-08-18）：原实现把每条互斥的两端都加进邻接表，
        导致互斥对（武器↔盾 双向）被当作两条边重复 union，二次处理时两端已同集 →
        任意 f含 excludes 的合法装备包都误判成环 R-5。现改为先去重为无向边集合再并查集。
        """
        undirected: set = set()  # {frozenset{a,b}, ...} 无向边去重（杜绝对称重复导致误报）
        for _, entry in self._iter_entries(module_name, data, mmeta):
            entry_map = self._as_mapping(entry)
            if entry_map is None:
                continue
            self_id = entry_map.get(mmeta.id_field)
            slot = entry_map.get("slot")
            core = slot if isinstance(slot, str) else (self_id if isinstance(self_id, str) else None)
            if core is None:
                continue
            excl = entry_map.get(mmeta.mutex_field)  # type: ignore[arg-type]
            if not isinstance(excl, list):
                continue
            for other in excl:
                if isinstance(other, str) and other != core:
                    undirected.add(frozenset((core, other)))
        # 无向环检测（并查集：新增边两端已在同一集合 → 有环）
        parent: Dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> bool:
            ra, rb = find(a), find(b)
            if ra == rb:
                return False
            parent[ra] = rb
            return True

        for pair in undirected:
            u, v = tuple(pair)
            if not union(u, v):
                self._err(module_name, f"{module_name}.? ({u} <-> {v})", "R-5",
                          rule="slot_mutex_cycle", slots=[u, v])
                return


# -------------------------------------------------------------------------------------
# 公共入口（细化_3e §5.1 接口签名）
# -------------------------------------------------------------------------------------


def _effect_entry_paths(module: str, entries: object) -> Iterable[Tuple[str, Mapping[str, Any]]]:
    """`items`/`equipment` 条目 → `(字段路径前缀, 条目映射)`（非映射条目跳过）。

    批50：只用于**读**词条里的特效轴取值；不改任何数据。
    """
    if not isinstance(entries, list):
        return
    for idx, entry in enumerate(entries):
        if isinstance(entry, Mapping):
            yield f"{module}.{idx}", entry


def _effect_rune_paths(module: str, entries: object) -> Iterable[Tuple[str, Mapping[str, Any]]]:
    """`runes` 条目 → `(字段路径前缀, 数值映射)`：逐 `by_equip_type[*].stats`。

    批50：符文数值档是特效轴取值的共用站点之一（口径 §4.1）；只读遍历。
    """
    if not isinstance(entries, list):
        return
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        by_type = entry.get("by_equip_type")
        if not isinstance(by_type, Mapping):
            continue
        for equip_type, spec in by_type.items():
            if not isinstance(spec, Mapping):
                continue
            stats = spec.get("stats")
            if isinstance(stats, Mapping):
                yield f"{module}.{idx}.by_equip_type.{equip_type}.stats", stats


def check_pack(
    modules: Mapping[str, object], meta: Optional[FieldMetaTable] = None
) -> ValidationReport:
    """整包校验：逐模块过 §5.2 规则表；errors/warnings 全量收集（D-01）。纯函数，无副作用。

    modules: 模块名（无 .json 后缀）→ parsed JSON 数据；meta: 字段元数据表（缺省用 default_field_meta_table）。
    """
    if meta is None:
        meta = default_field_meta_table()
    return _Checker(modules, meta).run()


def collect_ref_id_space(
    modules: Mapping[str, object], meta: Optional[FieldMetaTable] = None
) -> Dict[str, Dict[str, str]]:
    """引用目标 id 空间（kind → {id: 来源模块}）——与 R-4 引用判定**同一注册逻辑**。

    批34（通用 CSV 导入逐行引用校验）复用：只调用 `_Checker._collect_ids()` 收集注册表，
    不跑任何规则、不产生报告；返回的正是 `_check_ref` 查询的 `_id_space`。
    纯函数，无副作用；不写盘。
    """
    if meta is None:
        meta = default_field_meta_table()
    checker = _Checker(modules, meta)
    checker._collect_ids()
    return checker._id_space


__all__ = [
    "PackError",
    "PackNote",
    "PackWarning",
    "ValidationReport",
    "check_pack",
    "collect_ref_id_space",
    "check_formula",
    "FORMULA_BLACKLIST",
    "FORMULA_MAX_LENGTH",
    "FieldMeta",
    "FieldMetaTable",
    # M2 怪物八段（细化_1e §⑤ / ② / ④）
    "apply_enemy_difficulty_template",
    "is_dummy_enemy",
    "DIFFICULTY_TEMPLATES",
    "PV_RANGES",
    "TRIGGER_TYPES",
    "TRIGGER_ALIASES",
    "TRIGGER_LEGACY",
    "TRIGGER_TIMINGS",
    "DROP_CONDITIONS",
    # M5-02 message_prefix（【前缀】§九 / 3d 附·校验器行 L358 / m5_shared_contract §1.4）
    "message_prefix_unknown_placeholders",
    "MESSAGE_PREFIX_PLACEHOLDERS",
    "MESSAGE_PREFIX_PER_CHANNEL",
    "MESSAGE_PREFIX_DEFAULT_FORMAT",
    "MESSAGE_PREFIX_FORMAT_MAX_LEN",
    "MESSAGE_PREFIX_PLACEHOLDER_MAX",
    "MESSAGE_PREFIX_MAX_LEN_COMMON",
    # M13 技能库（细化_6a_技能库契约 §3：skills 专项校验器分派入口，
    # validate_skills 经 _check_module 延迟导入，不入 __all__——同 forge/achievements 先例）
]
