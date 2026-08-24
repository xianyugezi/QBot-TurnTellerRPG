"""内容包校验器 —— 结构断言唯一落点（细化_3e §5.1；【规则】L92「全部结构断言收敛于此」）。

依据：
  - 细化_3e_loader校验接线 §2.1：红拦 R-1~R-5（封闭清单，硬约束）
  - 细化_3e_loader校验接线 §2.2：黄提示 Y-1~Y-8（开放清单，只进 warnings 不阻断）
  - 细化_3e_loader校验接线 §2.3：默认放行兜底（红拦清单封闭、黄提示开放，未知字段默认放行）
  - 细化_3e_loader校验接线 §3.3：formula 安全例外（AST 黑名单 / new 表达式 / 长度>4KB → 红拦，不受只建议不限制覆盖）
  - 细化_3e_loader校验接线 §5.2：每模块校验清单（ID 唯一 / 链成环 / 部位互斥环 / stats 键空间等）
  - 细化_3e_loader校验接线 §5.3：字段元数据表 = 校验唯一数据源；校验器只实现规则引擎，不硬编码字段名
  - 细化_3e2_热重载契约 BLK-1：校验二分法（红色拦截仅 5 类）

纯函数无副作用：check_pack(modules, meta) -> ValidationReport（D-01：errors/warnings 全量收集，一次给全）。
零 NoneBot；仅依赖 qbot_rpg.content.models / qbot_rpg.data.types。
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.models import (
    FieldMeta,
    FieldMetaTable,
    ModuleMeta,
    PackError,
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
# 校验引擎
# -------------------------------------------------------------------------------------


class _Checker:
    """整包校验器实例：持有元数据表与累积报告。单次使用，纯函数式（无副作用）。"""

    def __init__(self, modules: Mapping[str, object], meta: FieldMetaTable) -> None:
        self._modules = modules
        self._meta = meta
        self.errors: List[PackError] = []
        self.warnings: List[PackWarning] = []
        # kind -> {id: 条目来源位置}（跨命名空间 ID 唯一性 + R-4 引用查询）
        self._id_space: Dict[str, Dict[str, str]] = {}
        self._location: Dict[str, Dict[str, str]] = {}  # kind -> id -> 位置原样串（供 detail）
        # 命名空间 -> 已注册 id（跨表唯一）
        self._ns_registered: Dict[str, Dict[str, str]] = {}

    # ---- 报告构建 ----
    def _err(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append(PackError(module=module, field=field, kind=kind, detail=dict(detail)))

    def _warn(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append(PackWarning(module=module, field=field, kind=kind, detail=dict(detail)))

    # ---- 入口 ----
    def run(self) -> ValidationReport:
        self._collect_ids()
        for module_name in self._ordered_defined_modules():
            self._check_module(module_name)
        return ValidationReport(errors=tuple(self.errors), warnings=tuple(self.warnings))

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

    # ---- map 形态模块值校验（stats/formula）----
    def _check_map_value(
        self, module_name: str, path: str, value: object, vmeta: FieldMeta
    ) -> None:
        if vmeta.type == "formula":
            # formula 模块：值为公式字符串，或 {formula: 表达式, ...}
            if isinstance(value, str):
                self._check_value(module_name, path, "formula", value, vmeta)
            elif isinstance(value, Mapping):
                expr = value.get("formula")
                if isinstance(expr, str):
                    self._check_value(module_name, f"{path}.formula", "formula", expr, vmeta)
                else:
                    self._err(module_name, path, "R-5", rule="formula_missing", name="formula")
            else:
                self._err(module_name, path, "R-1", rule="type", expect="formula|obj",
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
            fmeta = mmeta.fields.get(key)
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
            all_reg = {e for ids in self._id_space.values() for e in ids}
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
            nxt = entry_map.get(mmeta.chain_field)
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
            excl = entry_map.get(mmeta.mutex_field)
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


def check_pack(
    modules: Mapping[str, object], meta: Optional[FieldMetaTable] = None
) -> ValidationReport:
    """整包校验：逐模块过 §5.2 规则表；errors/warnings 全量收集（D-01）。纯函数，无副作用。

    modules: 模块名（无 .json 后缀）→ parsed JSON 数据；meta: 字段元数据表（缺省用 default_field_meta_table）。
    """
    if meta is None:
        meta = default_field_meta_table()
    return _Checker(modules, meta).run()


__all__ = [
    "PackError",
    "PackWarning",
    "ValidationReport",
    "check_pack",
    "check_formula",
    "FORMULA_BLACKLIST",
    "FORMULA_MAX_LENGTH",
    "FieldMeta",
    "FieldMetaTable",
]
