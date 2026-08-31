"""M10 钓鱼·批0·路0B：fishing.json 鱼种数据 CSV 双向导入导出（纯函数层）。

文件名：qbot_rpg/core/fishing_csv.py
创建时间：2026-08-31
作者：Hermes 子agent-0B（M10 钓鱼实现组批0·路0B：并发同仓，仅新建本文件 +
content/test_demo/fishing.json + tests/fixtures/packs/legal/fishing.json +
tests/unit/test_fishing_csv.py；不改动任何已有实现文件）

依据：docs/细化/细化_2c1a_鱼种数据与冠级.md §一 1.4（CSV 列对齐【钓鱼】L104）+
docs/m10_shared_contract.md §二（Fish 行字段表 F-01~F-14 + 13 列固定序 +
空数组语义）+ 定稿 §三（鱼种行 L81-88）+ 定稿 §五（CSV 列 L104）。

功能描述：
  - fishing_to_csv(species) -> str：鱼种 dict 列表 → 13 列 CSV 文本（含表头）。
    列序固定：id/name/rarity/size_min/size_max/weight_min/weight_max/
    seasons/periods/hours/spots/preferred_bait/codex_text（2c1a §1.4）。
    数组列（seasons/periods/hours/spots/preferred_bait）序列化为逗号分隔
    字符串；空数组序列化为空字符串（空=不限制语义保留，TC-02）。codex_text
    为单个 JSON 单元格（json.dumps，ensure_ascii=False）。
  - csv_to_fishing(text, strict=False) -> list[dict]：CSV 文本 → 鱼种 dict
    列表（反向解析）。容错：空行/表头自动跳过；非法行（列数不符 / 数值不可
    解析 / codex_text JSON 损坏）默认跳过不中断（strict=True 时抛 ValueError
    暴露坏行）。空字符串单元格解析回空数组；空 codex_text 单元格解析回 None。

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器（零睡眠调用）；无随机；
无 emoji；未知键默认放行（CSV 只承载 13 列，king 等额外键不导出不导入）。
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, cast

# 13 列固定序（2c1a §1.4 / 定稿 §五 L104）
CSV_COLUMNS: Tuple[str, ...] = (
    "id",
    "name",
    "rarity",
    "size_min",
    "size_max",
    "weight_min",
    "weight_max",
    "seasons",
    "periods",
    "hours",
    "spots",
    "preferred_bait",
    "codex_text",
)

# 数组列（逗号分隔序列化）
_ARRAY_COLUMNS: Tuple[str, ...] = (
    "seasons",
    "periods",
    "hours",
    "spots",
    "preferred_bait",
)

# 数值列（float 口径）
_NUMERIC_COLUMNS: Tuple[str, ...] = (
    "size_min",
    "size_max",
    "weight_min",
    "weight_max",
)


def _format_array(value: object) -> str:
    """数组列 → 逗号分隔字符串；空数组/None → 空字符串（空=不限制）。"""
    if not value:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)


def _parse_array(text: str) -> List[str]:
    """逗号分隔字符串 → 数组列；空字符串 → []（空=不限制语义保留）。"""
    if text == "":
        return []
    return [part.strip() for part in text.split(",") if part.strip() != ""]


def _format_number(value: object) -> str:
    """数值列 → str(float)；None → 空字符串。"""
    if value is None:
        return ""
    return str(float(cast(Any, value)))


def _parse_number(text: str) -> float:
    """数值列反向解析；空字符串 → 0.0（容错默认）。"""
    if text == "":
        return 0.0
    return float(text)


def _format_codex(value: object) -> str:
    """codex_text → 单个 JSON 单元格；None → 空字符串。"""
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_codex(text: str) -> Any:
    """单个 JSON 单元格 → codex_text dict；空字符串 → None。"""
    if text == "":
        return None
    return json.loads(text)


def _parse_row(raw: Sequence[str], strict: bool) -> Optional[Dict[str, Any]]:
    """单行解析；非法行 strict=False 时返回 None（跳过），strict=True 抛错。"""
    if len(raw) != len(CSV_COLUMNS):
        if strict:
            raise ValueError(f"CSV 行列数不符：期望 {len(CSV_COLUMNS)} 列，实际 {len(raw)}")
        return None
    out: Dict[str, Any] = {}
    for col, cell in zip(CSV_COLUMNS, raw):
        try:
            if col in _ARRAY_COLUMNS:
                out[col] = _parse_array(cell)
            elif col == "codex_text":
                out[col] = _parse_codex(cell)
            elif col in _NUMERIC_COLUMNS:
                out[col] = _parse_number(cell)
            else:
                out[col] = cell
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            if strict:
                raise ValueError(f"CSV 行字段 {col} 解析失败：{exc!r}") from exc
            return None
    return out


def fishing_to_csv(species: Iterable[Mapping[str, object]]) -> str:
    """鱼种 dict 列表 → 13 列 CSV 文本（含表头行）。

    参数：
      species：可迭代的鱼种 dict（每项含 CSV_COLUMNS 对应字段；额外键如 king
      不导出，符合 13 列固定契约）。
    返回：
      CSV 文本（utf-8 可写；表头 = CSV_COLUMNS；行间以 \\n 分隔）。
    确定性：同一输入恒产生同一文本（无随机、无顺序漂移）。
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for sp in species:
        row: List[str] = []
        for col in CSV_COLUMNS:
            value = sp.get(col)
            if col in _ARRAY_COLUMNS:
                row.append(_format_array(value))
            elif col == "codex_text":
                row.append(_format_codex(value))
            elif col in _NUMERIC_COLUMNS:
                row.append(_format_number(value))
            else:
                row.append("" if value is None else str(value))
        writer.writerow(row)
    return buf.getvalue()


def csv_to_fishing(text: str, strict: bool = False) -> List[Dict[str, Any]]:
    """CSV 文本 → 鱼种 dict 列表（fishing_to_csv 的逆操作，双向无损）。

    参数：
      text：CSV 文本。首行若恰为表头（== CSV_COLUMNS）自动跳过；空行跳过；
      无表头纯数据亦接受。
      strict：True 时非法行抛 ValueError（暴露坏行）；False（默认）时跳过
      非法行容错返回。
    返回：
      鱼种 dict 列表，每项含 13 个 CSV_COLUMNS 键；codex_text 单元格解析回
      dict/None；数组列解析回 list（空字符串 → []）。
    """
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    result: List[Dict[str, Any]] = []
    for i, raw in enumerate(rows):
        if not raw or (len(raw) == 1 and raw[0] == ""):
            continue  # 空行跳过
        if i == 0 and tuple(raw) == CSV_COLUMNS:
            continue  # 表头跳过
        parsed = _parse_row(raw, strict=strict)
        if parsed is not None:
            result.append(parsed)
    return result
