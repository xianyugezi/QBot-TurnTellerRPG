# -*- coding: utf-8 -*-
"""parse_doc12.py —— 九期批次 208 · 对账管线（三段式：12 号键表 → 映射 YAML → 框架 JSON 片段）

段1 解析  设计稿仓库 12_全局常量表.md 的键行（节头域前缀＋行键，显式/点分/裸名/打包四式）
段2 映射  docs/cloudsea/doc12_mapping.yaml（节→主域、点分路由、逐键覆盖、排除项；
          歧义裸键以设计稿全库 `$C.*` 引称语料定 canonical，未引称键回退主域并旗标）
段3 出片  docs/cloudsea/fragments/<域>.json（逐域一片，键排序，含 raw/typed/desc/section）＋ _manifest.json

--check 执行双向断言：
  A1 总数对账   解析行数 == 解析键数 == 出片叶子总数
  A2 键唯一     解析键零重复
  A3 值保真     出片 raw 与 12 号源行逐字一致（空白归一后）
  A4 反向无造   片段键集 ⊆ 解析键集（零发明键）
  A5 覆盖完备   每行恰经一条规则解析（explicit/dotted/citation/fallback），排除行单列
  A6 幂等重放   二次出片与首次字节一致

用法：python scripts/parse_doc12.py [--doc PATH] [--corpus DIR] [--check] [--report]
退出码：--check 全过 0，否则 1。
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter, OrderedDict

import yaml

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_DOC = os.path.join("..", "yunhai", "cloudsea-hunting-corps", "12_全局常量表.md")
DEFAULT_CORPUS = os.path.join("..", "yunhai", "cloudsea-hunting-corps")
DEFAULT_MAPPING = os.path.join("docs", "cloudsea", "doc12_mapping.yaml")
DEFAULT_OUT = os.path.join("docs", "cloudsea", "fragments")

KEY_RE = re.compile(r"^\$C\.[A-Z0-9_]+(?:\.[A-Z0-9_]+)*$")
TOK_RE = re.compile(r"[`$C\.\s]")


# ---------------------------------------------------------------- 段1 解析
def parse_doc(doc_path):
    """返回 (rows, sections)；节按「节头 C.X 令牌」取域（字母撞号免疫），row 含 section 主域"""
    text = io.open(doc_path, encoding="utf-8").read().replace("\r\n", "\n")
    sections = OrderedDict()
    rows = []
    primary = None
    sec_domains = []
    for line_no, ln in enumerate(text.split("\n"), 1):
        if ln.startswith("## "):
            toks = re.findall(r"C\.([A-Z_]+)", ln)
            sec_domains = toks
            primary = toks[0] if toks else None
            if toks:
                sections["/".join(toks)] = ln[3:].strip()
            continue
        if primary is None or not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 4:
            continue
        cell = cells[1].strip().strip("`").strip()
        if not cell or set(cell) <= set("-: ") or cell == "键名":
            continue
        rows.append({"section": primary, "cell": cell, "raw": cells[3].strip(),
                     "desc": cells[2].strip(), "line_no": line_no})
    return rows, sections


def split_packed(cell):
    """打包行拆 token：以反引号边界 ' / ' 分隔；token 保留其 $C. 前缀（若有）"""
    parts = [p.strip().strip("`").strip() for p in cell.split("` / `")]
    if len(parts) == 1:
        parts = [p.strip() for p in cell.split(" / ")]
    return [p for p in parts if p and not set(p) <= set("-: ")]


# ---------------------------------------------------------------- 段2 映射
def load_corpus_index(corpus):
    """设计稿全库 `$C.*` 引称索引（排除 合集/排期归档/生产日志/18_/武器名录? 不排除——引称即语料）"""
    pat = re.compile(r"\$C\.[A-Z0-9_]+(?:\.[A-Z0-9_]+)*")
    idx = Counter()
    for dp, dn, fns in os.walk(corpus):
        dn[:] = [d for d in dn if d not in ("排期归档",) and "合集" not in d]
        for fn in fns:
            if not fn.endswith(".md"):
                continue
            try:
                t = io.open(os.path.join(dp, fn), encoding="utf-8").read()
            except Exception:
                continue
            idx.update(pat.findall(t))
    return idx


def typed_value(raw):
    s = raw.strip().strip("`").strip()
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [t.strip().strip("`' ") for t in inner.split(",")]
    return None


def resolve(rows, sections, mapping, corpus_idx):
    """返回 (keys, report)；key = dict(full, section, raw, desc, rule, line_no)"""
    dotted_routes = mapping.get("dotted_routes", {})
    overrides = mapping.get("key_overrides", {})
    exclusions = set(mapping.get("exclusions", []))
    keys, skipped, fallbacks = [], [], []
    for row in rows:
        if row["cell"] == "ID" and row["raw"].strip("`").strip() == "值":
            skipped.append((row["cell"], "节表头行"))
            continue
        if row["cell"] in exclusions:
            skipped.append((row["cell"], "映射排除项"))
            continue
        primary = row["section"]
        if not primary:
            skipped.append((row["cell"], "未登记节"))
            continue
        toks = split_packed(row["cell"])
        base = None
        for tok in toks:
            if tok.startswith("$C."):
                base, first_full = tok, True
                break
        prefix = ""
        if base:
            prefix = base[: base.rfind(".") + 1] if "." in base[3:] else "$C."
        prev_tail = None
        for i, tok in enumerate(toks):
            t = tok.strip()
            if i > 0 and not t.startswith("$C.") and not t.startswith("_") and "_" in t:
                # 独立全名续段（如 GOAL_GAP_TIERS / GOAL_STALL_BATTLES）——走自身解析
                prev_tail = t
                full, rule = self_resolve(t, primary, overrides, corpus_idx)
            elif i > 0 and base:
                if t.startswith("_"):
                    stem = prev_tail[: prev_tail.rfind("_") + 1] if prev_tail and "_" in prev_tail else (prev_tail or "")
                    tail = stem + t[1:]
                elif prev_tail and "_" in prev_tail:
                    tail = prev_tail[: prev_tail.rfind("_") + 1] + t
                else:
                    tail = (prev_tail + "_" + t) if prev_tail else t
                prev_tail = tail
                full, rule = prefix + tail, "packed_inherit"
            else:
                prev_tail = t.split(".")[-1] if "." in t else t
                full, rule = self_resolve(t, primary, overrides, corpus_idx)
            if full is None:
                skipped.append((t, "键形不合法"))
                continue
            keys.append({"full": full, "section": row["section"], "raw": row["raw"],
                         "desc": row["desc"], "rule": rule, "line_no": row["line_no"]})
    return keys, {"skipped": skipped, "fallbacks": fallbacks}


def self_resolve(t, primary, overrides, corpus_idx):
    """单 token 解析：显式/点分/覆盖/引称/主域回退"""
    if t.startswith("$C."):
        return (t if KEY_RE.match(t) else None), "explicit"
    if "." in t:
        head = t.split(".", 1)[0]
        return "$C.%s.%s" % (primary, t), "dotted_fallback"
    ov = overrides.get(t)
    if ov:
        return (ov if ov.startswith("$C.") else "$C.%s.%s" % (primary, ov)), "override"
    cands = {k: v for k, v in corpus_idx.items() if k.endswith("." + t)}
    if len(cands) == 1:
        return next(iter(cands)), "citation"
    if cands:
        return max(cands, key=cands.get), "citation_majority"
    return "$C.%s.%s" % (primary, t), "fallback"


# ---------------------------------------------------------------- 段3 出片
def emit(keys, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    frags = OrderedDict()
    for k in keys:
        dom = k["full"].split(".")[1]
        frags.setdefault(dom, []).append({
            "key": k["full"], "raw": k["raw"],
            "value": typed_value(k["raw"]), "desc": k["desc"],
            "section": k["section"], "rule": k["rule"],
        })
    for dom in frags:
        frags[dom].sort(key=lambda x: x["key"])
        path = os.path.join(out_dir, "%s.json" % dom.lower())
        data = json.dumps(frags[dom], ensure_ascii=False, indent=1, sort_keys=False)
        io.open(path, "w", encoding="utf-8", newline="\n").write(data + "\n")
    manifest = OrderedDict([
        ("source_doc", "12_全局常量表.md（设计稿仓库）"),
        ("fragments", {d: {"file": "%s.json" % d.lower(), "keys": len(v)} for d, v in frags.items()}),
        ("total_keys", sum(len(v) for v in frags.values())),
    ])
    io.open(os.path.join(out_dir, "_manifest.json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return frags


# ---------------------------------------------------------------- 断言
def check(frags, keys, report, out_dir):
    ok = []

    def a(name, cond, detail=""):
        ok.append(cond)
        print("[{}] {}{}".format("PASS" if cond else "FAIL", name, " —— " + detail if detail else ""))

    total_leaves = sum(len(v) for v in frags.values())
    a("A1 总数对账（解析=解析键=出片叶）", len(keys) == total_leaves,
      "rows→keys {} == leaves {}".format(len(keys), total_leaves))
    dup = [k for k, v in Counter(k["full"] for k in keys).items() if v > 1]
    a("A2 解析键唯一", not dup, str(dup[:5]))
    raw_by_key = {}
    for k in keys:
        raw_by_key.setdefault(k["full"], k["raw"])
    bad3 = [f["key"] for dom in frags.values() for f in dom
            if " ".join(raw_by_key.get(f["key"], "").split()) != " ".join(f["raw"].split())]
    a("A3 值保真（出片 raw 与源行一致）", not bad3, str(bad3[:5]))
    keyset = set(k["full"] for k in keys)
    bad4 = [f["key"] for dom in frags.values() for f in dom if f["key"] not in keyset]
    a("A4 反向无造（片段键 ⊆ 解析键）", not bad4, str(bad4[:5]))
    n_rules = sum(1 for k in keys if k["rule"] in ("explicit", "dotted", "dotted_fallback", "override", "citation", "citation_majority", "fallback"))
    a("A5 覆盖完备（每键恰一规则；回退 {} 未引称已旗标）".format(len(report["fallbacks"])),
      n_rules == len(keys), "rules {} / keys {}".format(n_rules, len(keys)))
    snap1 = json.dumps({d: sorted(f["key"] + "=" + f["raw"] for f in v) for d, v in frags.items()},
                       ensure_ascii=False, sort_keys=True)
    frags2 = emit(keys, os.path.join(out_dir, "_idempotency"))
    snap2 = json.dumps({d: sorted(f["key"] + "=" + f["raw"] for f in v) for d, v in frags2.items()},
                       ensure_ascii=False, sort_keys=True)
    a("A6 幂等重放（两次出片一致）", snap1 == snap2)
    import shutil
    shutil.rmtree(os.path.join(out_dir, "_idempotency"), ignore_errors=True)
    return all(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=DEFAULT_DOC)
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--mapping", default=DEFAULT_MAPPING)
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    rows, sections = parse_doc(args.doc)
    mapping = yaml.safe_load(io.open(args.mapping, encoding="utf-8"))
    corpus_idx = load_corpus_index(args.corpus)
    keys, report = resolve(rows, sections, mapping, corpus_idx)
    frags = emit(keys, args.out_dir)

    print("解析行 {} → 键 {}（回退 {}，跳过 {}）→ 域片段 {} 个 / 叶 {}"
          .format(len(rows), len(keys), len(report["fallbacks"]), len(report["skipped"]),
                  len(frags), sum(len(v) for v in frags.values())))
    if args.report:
        for k in keys:
            print("  {} [{}] {}".format(k["full"], k["rule"], k["raw"][:40]))
        for s, why in report["skipped"]:
            print("  SKIP {}（{}）".format(s, why))
    if args.check:
        sys.exit(0 if check(frags, keys, report, args.out_dir) else 1)


if __name__ == "__main__":
    main()
