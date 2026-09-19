"""通用 CSV 编解码（编辑器批34 · 框架 §6.7 / §6.11 / §6.12-05 / §6.12-20）。

定位：**纯函数层**——只依赖 `qbot_rpg.content.models` 的字段元数据（FieldMeta /
ModuleMeta），不 import web 层、不读盘、不写盘。CSV 的读/写/校验编排在
`qbot_rpg/web/csv_ops.py`（复用既有校验器 / 原子写 / 备份 / 回退）。

设计口径（本批自定，写进 `docs/编辑器使用说明.md` §十一）：

一、**列头 = 元数据字段**（一号原则：框架登记的全部字段都出列，包里未配置也出）：
  · list 模块：`ModuleMeta.fields` 全字段（含 `id_field`）；
  · map 模块：`id_field` 键列 + `value_meta`（对象值 → children；标量值 → 单列）；
  · 包数据里出现但元数据未登记的键（extra）→ 追加列，列头 `*键名`（值固定 JSON 编码）；
  · 单元格文本：有中文名 → `中文名(键)`；无中文名 / 键列 → `键`。
  导入时按「精确键 / `中文名(键)` / `*键名`」三种列头还原；认不出的列 → 忽略并给人话提示。

二、**单元格编码**（可逆；`encode_cell` / `decode_cell` 严格互逆）：
  · 键缺失（未配置）→ 空单元格；
  · `null` → `\\N`；
  · 文本里的前导反斜杠做一次转义（`\\` → `\\\\`），保证字面 `\\N` 与 null 不混；
  · list / obj / map 型字段 → JSON 文本（`json.dumps`，保序、紧凑分隔符）；
  · bool → `true` / `false`；int / float / number → JSON 数字文本；
  · 其余（str / ref / enum / formula / 未登记）→ 文本原样（经注入中和与反斜杠转义）。

三、**公式注入中和**（§6.12-20；只作用于文本单元格，数字/布尔不受影响）：
  · 导出：文本以 `=` `+` `-` `@` 开头（或「若干个 `'` + 危险字符」）→ 前置一个 `'`；
  · 导入：同形单元格 → 去掉一个 `'`（还原我们导出的值）；裸危险文本 →
    中和为 `'` 前缀后再写入内容包（防未经我们导出的 CSV 把公式带进包）。
  该规则对文本可逆（见 `test_csv_codec.py` 往返 + 注入用例）。

四、**编码**：导出文本 = UTF-8 带 BOM（`CSV_BOM`），行尾统一 `\\n`；
  导入由 `qbot_rpg/web/csv_ops.decode_bytes` 自动检测 UTF-8(BOM) / GBK（§6.11）。
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.content.models import FieldMeta, ModuleMeta

# UTF-8 BOM：Excel 双击打开不乱码（§6.7「导出编码」）。
CSV_BOM: str = "\ufeff"
# null 哨兵（PostgreSQL 风格；字面 `\N` 文本经前导反斜杠转义区分）。
CELL_NULL: str = "\\N"
# 显式空串哨兵（与「键缺失 = 空单元格」区分；字面 `\E` 文本同样经反斜杠转义区分）。
CELL_EMPTY: str = "\\E"
# 「字段声明类型 ≠ 实际取值类型」的文本列 JSON 标记（如 bool 字段里存对象、str 字段里存对象）。
# 数字 / 布尔列不需要标记：解不出标量时回退 JSON 解析即可（见 decode_cell）。
CELL_JSON_MARK: str = "\\J"
# 公式注入危险前缀（§6.12-20）。
DANGER_PREFIXES: str = "=+-@"
# 需要 JSON 文本编码的字段类型。
JSON_TYPES: Tuple[str, ...] = ("list", "obj", "map")
# extra 列（元数据未登记键）的列头前缀。
EXTRA_PREFIX: str = "*"
# extra 列在 schema 里的伪类型标记。
JSON_COLUMN_TYPE: str = "json"

_ABSENT = object()
_INT_RE = re.compile(r"^[+-]?[0-9]+$")


class CsvCodecError(ValueError):
    """CSV 形态非法（如对象形态模块 / 列头全空 / 行宽异常）：人话消息。"""


class UnsupportedModuleError(CsvCodecError):
    """本模块形态无法用「每行一条条目」的 CSV 表达（object 形态）。"""


# =====================================================================================
# 列 / 表结构
# =====================================================================================
@dataclass(frozen=True)
class Column:
    """一个 CSV 列（= 一个元数据字段或合成键列 / extra 列）。"""

    key: str
    label: str = ""
    type: str = "str"
    ref_target: str = ""
    element: Optional["Column"] = None
    children: Tuple["Column", ...] = ()
    json: bool = False       # extra 列：值固定 JSON 编码
    is_key: bool = False     # 合成键列（map 模块的键 / list 模块补出的 id_field）


@dataclass(frozen=True)
class CsvSchema:
    """一个模块的 CSV 表结构（导入/导出共用同一构建入口）。"""

    module: str
    entry_type: str               # "list" | "map"
    key_field: str
    value_mode: str               # "fields" | "map_obj" | "map_scalar"
    columns: Tuple[Column, ...] = ()

    def column(self, key: str) -> Optional[Column]:
        for c in self.columns:
            if c.key == key:
                return c
        return None

    def header_cells(self) -> List[str]:
        return [header_cell(c) for c in self.columns]


def _column_from_field(key: str, fm: Optional[FieldMeta]) -> Column:
    if fm is None:
        return Column(key=key, type="str")
    children = tuple(_column_from_field(k, v) for k, v in (fm.children or {}).items())
    element = _column_from_field("", fm.element) if fm.element is not None else None
    return Column(
        key=key,
        label=str(getattr(fm, "label", "") or ""),
        type=str(fm.type or "str"),
        ref_target=str(fm.ref_target or ""),
        element=element,
        children=children,
    )


def schema_for(mmeta: Optional[ModuleMeta], *, entry_type: Optional[str] = None,
               extra_keys: Iterable[str] = ()) -> CsvSchema:
    """模块元数据 → CSV 表结构（通用；不认任何业务模块/字段名）。

    `entry_type` 显式给出时优先（模块无元数据时由调用方用 `api._entry_type` 推断）。
    object 形态无法「每行一条条目」→ `UnsupportedModuleError`（本批如实不支持）。
    """
    etype = str(entry_type or (mmeta.entry_type if mmeta is not None else "list") or "list")
    key_field = str((mmeta.id_field if mmeta is not None and mmeta.id_field else "id"))
    columns: List[Column] = []
    if etype == "list":
        declared = dict(mmeta.fields) if mmeta is not None else {}
        if key_field not in declared:
            columns.append(Column(key=key_field, type="str", is_key=True))
        for key, fm in declared.items():
            if any(c.key == str(key) for c in columns):
                continue
            columns.append(_column_from_field(str(key), fm))
        value_mode = "fields"
    elif etype == "map":
        columns.append(Column(key=key_field, type="str", is_key=True))
        vm = mmeta.value_meta if mmeta is not None else None
        if vm is not None and vm.type == "obj" and vm.children:
            for key, fm in vm.children.items():
                columns.append(_column_from_field(str(key), fm))
            value_mode = "map_obj"
        else:
            columns.append(_column_from_field("value", vm))
            value_mode = "map_scalar"
    else:
        raise UnsupportedModuleError(
            f"模块「{mmeta and mmeta.kind or ''}」是单对象形态，"
            "没有「每行一条条目」的概念，本版 CSV 不适用。")

    seen = {c.key for c in columns}
    for key in extra_keys:
        k = str(key)
        if k in seen:
            continue
        seen.add(k)
        columns.append(Column(key=k, type=JSON_COLUMN_TYPE, json=True))
    return CsvSchema(module="", entry_type=etype, key_field=key_field,
                     value_mode=value_mode, columns=tuple(columns))


def header_cell(c: Column) -> str:
    """列头文本：extra → `*键`；键列 / 无中文名 → `键`；否则 `中文名(键)`。"""
    if c.json:
        return EXTRA_PREFIX + c.key
    if c.is_key or not c.label or c.label == c.key:
        return c.key
    return f"{c.label}({c.key})"


# =====================================================================================
# 单元格编码 / 解码
# =====================================================================================
def _neutralize(text: str) -> str:
    """危险文本 → 前置一个 `'`（若干前导 `'` 也算危险，保证可逆，见模块 docstring）。"""
    k = 0
    while k < len(text) and text[k] == "'":
        k += 1
    if k < len(text) and text[k] in DANGER_PREFIXES:
        return "'" + text
    return text


def _deescape_text(text: str) -> str:
    """`_escape_text` 的逆：先撤销注入中和，再撤销前导反斜杠转义。"""
    k = 0
    while k < len(text) and text[k] == "'":
        k += 1
    if k < len(text) and text[k] in DANGER_PREFIXES:
        text = text[1:] if k >= 1 else ("'" + text)
    if text.startswith("\\"):
        text = text[1:]
    return text


def _escape_text(text: str) -> str:
    """文本 → 单元格文本：前导反斜杠转义 + 公式注入中和（顺序固定，导入逆序还原）。"""
    if text.startswith("\\"):
        text = "\\" + text
    return _neutralize(text)


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _type_compatible(value: object, t: str) -> bool:
    """值是否与列声明类型相符（不符 → 用 JSON 文本保真，见 `encode_cell`）。"""
    if t in JSON_TYPES:
        return isinstance(value, (list, Mapping))
    if t == "bool":
        return isinstance(value, bool)
    if t == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if t in ("float", "number"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)   # str / ref / enum / formula / 未登记


def encode_cell(value: object, col: Column) -> str:
    """值 → 单元格文本；`_ABSENT` → 空。数字/布尔不做注入中和（负号是合法数值）。"""
    if value is _ABSENT:
        return ""
    if value is None:
        return CELL_NULL
    if col.json or col.type in JSON_TYPES:
        return _json_text(value)
    t = col.type
    if not _type_compatible(value, t):
        # 声明类型与实际取值不符（真实数据存在，如 bool 字段写对象）：
        # 文本列加 `\\J` 标记保真；数字/布尔列直接 JSON 文本，解码回退 JSON 解析。
        if t in ("bool", "int", "float", "number"):
            return _json_text(value)
        return CELL_JSON_MARK + _json_text(value)
    if t == "bool":
        return "true" if value is True else "false"
    if t in ("int", "float", "number"):
        return _json_text(value)
    text = value if isinstance(value, str) else str(value)
    if text == "":
        return CELL_EMPTY
    return _escape_text(text)


def decode_cell(text: str, col: Column) -> object:
    """单元格文本 → 值；空 → `_ABSENT`；非法 → `CsvCodecError`（行级报错用）。"""
    if text is None or text == "":
        return _ABSENT
    if text == CELL_NULL:
        return None
    if text == CELL_EMPTY:
        return ""
    if text.startswith(CELL_JSON_MARK):
        try:
            return json.loads(text[len(CELL_JSON_MARK):])
        except (ValueError, TypeError) as exc:
            raise CsvCodecError(
                f"列「{header_cell(col)}」的值形如 JSON 标记但解析失败：{exc}") from exc
    if col.json:
        try:
            return json.loads(text)
        except (ValueError, TypeError) as exc:
            raise CsvCodecError(f"列「{header_cell(col)}」要求 JSON，解析失败：{exc}") from exc
    t = col.type
    if t in JSON_TYPES:
        try:
            return json.loads(text)
        except (ValueError, TypeError) as exc:
            raise CsvCodecError(
                f"列「{header_cell(col)}」是列表/对象字段，要求 JSON 文本，解析失败：{exc}"
            ) from exc
    if t == "bool":
        low = text.strip().lower()
        if low in ("true", "1", "yes", "是"):
            return True
        if low in ("false", "0", "no", "否"):
            return False
        return _decode_json_fallback(text, col)
    if t == "int":
        s = text.strip()
        if _INT_RE.match(s):
            return int(s)
        return _decode_json_fallback(text, col)
    if t in ("float", "number"):
        s = text.strip()
        if _INT_RE.match(s):
            return int(s)   # 保真：JSON 整数不因列类型是 number 而变成浮点
        try:
            return float(s)
        except ValueError:
            return _decode_json_fallback(text, col)
    return _deescape_text(text)


def _decode_json_fallback(text: str, col: Column) -> object:
    """数字/布尔列解不出标量时，回退 JSON 解析（保真「声明类型 ≠ 实际取值」的字段）。"""
    try:
        return json.loads(text)
    except (ValueError, TypeError) as exc:
        raise CsvCodecError(
            f"列「{header_cell(col)}」的取值既不是 {col.type} 也不是合法 JSON：{text!r}"
        ) from exc


# =====================================================================================
# 导出
# =====================================================================================
def _cell_of(entry_key: str, entry_value: object, col: Column,
             value_mode: str) -> str:
    if col.is_key:
        if value_mode == "fields":
            val = entry_value.get(col.key, _ABSENT) if isinstance(entry_value, Mapping) else _ABSENT
        else:
            val = entry_key
    elif value_mode == "map_scalar":
        val = entry_value
    else:
        val = entry_value.get(col.key, _ABSENT) if isinstance(entry_value, Mapping) else _ABSENT
    return encode_cell(val, col)


def encode_csv(schema: CsvSchema, entries: Sequence[Tuple[str, object]]) -> str:
    """条目序列 `(键, 值)` → CSV 文本（含 BOM；行序 = 传入顺序）。只读，不写盘。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(schema.header_cells())
    for key, value in entries:
        writer.writerow([_cell_of(str(key), value, c, schema.value_mode)
                         for c in schema.columns])
    return CSV_BOM + buf.getvalue()


# =====================================================================================
# 导入
# =====================================================================================
@dataclass(frozen=True)
class DecodedRow:
    """一行数据（line = CSV 物理行号，1 起；表头是第 1 行）。"""

    line: int
    key: str
    values: Dict[str, Any] = dc_field(default_factory=dict)

    def entry(self, schema: CsvSchema) -> object:
        """还原条目值：list → 含 id_field 的字段对象；map_obj → 去掉键列的值对象；
        map_scalar → 标量。"""
        if schema.value_mode == "map_scalar":
            return self.values.get("value")
        if schema.value_mode == "map_obj":
            return {k: v for k, v in self.values.items() if k != schema.key_field}
        return dict(self.values)


@dataclass(frozen=True)
class DecodeIssue:
    """行级解码问题（人在界面上看：第几行 / 哪列 / 为什么）。"""

    line: int
    field: str
    message: str
    header: str = ""


@dataclass(frozen=True)
class DecodeResult:
    rows: List[DecodedRow]
    issues: List[DecodeIssue]
    notes: List[str]
    columns: Tuple[Optional[Column], ...]


def _resolve_header(cell: str, schema: CsvSchema) -> Optional[Column]:
    """列头单元格 → 列；认不出 → None（调用方忽略并记 note）。"""
    text = (cell or "").strip()
    if not text:
        return None
    for c in schema.columns:
        if text == c.key:
            return c
    for c in schema.columns:
        if c.label and text == f"{c.label}({c.key})":
            return c
    if text.startswith(EXTRA_PREFIX):
        key = text[len(EXTRA_PREFIX):]
        if key:
            hit = schema.column(key)
            if hit is not None:
                return hit
            return Column(key=key, type=JSON_COLUMN_TYPE, json=True)
    return None


def decode_csv(schema: CsvSchema, text: str) -> DecodeResult:
    """CSV 文本 → 行序列 + 解码问题。不写盘；引用/冲突/落盘在 web 层。"""
    if text.startswith(CSV_BOM):
        text = text[len(CSV_BOM):]
    try:
        records = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise CsvCodecError(f"CSV 解析失败：{exc}") from exc
    if not records:
        raise CsvCodecError("CSV 是空的（至少要有列头与一行数据）。")

    header = records[0]
    active: List[Optional[Column]] = [_resolve_header(cell, schema) for cell in header]
    notes: List[str] = []
    unknown: List[str] = []
    for idx, col in enumerate(active):
        if col is None and (header[idx] or "").strip():
            unknown.append(str(header[idx]).strip())
    if unknown:
        notes.append("已忽略认不出的列：" + "、".join(unknown)
                     + "（列头应为元数据字段，或 `*` 开头的扩展列）。")
    if all(c is None for c in active):
        raise CsvCodecError("列头一行没有任何可识别的字段列。")

    rows: List[DecodedRow] = []
    issues: List[DecodeIssue] = []
    for offset, record in enumerate(records[1:], start=1):
        line = offset + 1
        if not any((cell or "").strip() for cell in record):
            continue  # 整行空白：跳过（不当作条目）
        values: Dict[str, Any] = {}
        for pos, col in enumerate(active):
            if col is None or pos >= len(record):
                continue
            raw = record[pos]
            if raw == "":
                continue
            try:
                val = decode_cell(raw, col)
            except CsvCodecError as exc:
                issues.append(DecodeIssue(line=line, field=col.key,
                                          message=str(exc), header=header_cell(col)))
                continue
            if val is not _ABSENT:
                values[col.key] = val
        raw_key = values.get(schema.key_field)
        key = raw_key if isinstance(raw_key, str) else (
            "" if raw_key is None else str(raw_key))
        rows.append(DecodedRow(line=line, key=key, values=values))
    return DecodeResult(rows=rows, issues=issues, notes=notes, columns=tuple(active))


__all__ = [
    "CELL_EMPTY",
    "CELL_JSON_MARK",
    "CELL_NULL",
    "CSV_BOM",
    "DANGER_PREFIXES",
    "Column",
    "CsvCodecError",
    "CsvSchema",
    "DecodeIssue",
    "DecodeResult",
    "DecodedRow",
    "JSON_TYPES",
    "UnsupportedModuleError",
    "decode_cell",
    "decode_csv",
    "encode_cell",
    "encode_csv",
    "header_cell",
    "schema_for",
]
