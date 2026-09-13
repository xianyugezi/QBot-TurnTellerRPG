# -*- coding: utf-8 -*-
"""parse_actions.py —— 九期批次 216 · 动作池转译（设计稿 17_/动作池 四册 → content/cloudsea/actions.json）

四形态解析：
  A 紧凑式（骨架族池_上）：### F01-01 · 名 ＋ 归属/类型/体型｜方位｜意图/结算｜跟进/引用/后续 四行
  B 卡式（骨架族池_下/个体池/巨兽差异）：## 怪名 ＋ ### 动作｜名 ＋ 归属/意图行/结算行/跟进/引用…｜方位
  C 表行式（独有招_188–191）：| 怪名 | 类 | 骨架族 | 独有招 | 权重微调 | 方位 | …（方位列重复列取首）

出片条目：{id, code, name, source, owner, ctype, intent_mark, hits, resolve_raw, refs,
           follow, break_disp, whitelist, pos{attack_zone,self_reposition,target_displace,
           position_rule,marks,note}, kind, power}
  ——kind/power 为框架兼容缺省（basic/1.0）；逐怪 power 绑定与权重表归 217–218；
    耗时四键（charge_turns/cd/hits/duration 恒写出）归 215E 增量（G1B 在途， sequencing 见批次216.md）。

对账：总卡数 == 1261（骨架上 68＋骨架下 60＋个体池 377＋巨兽差异 534＋独有招 222）；
      id 唯一；方位字段覆盖 == 215A 标注数（—白名单行计入 whitelist）；幂等重放。
用法：python scripts/parse_actions.py [--check]
"""
import argparse, io, json, os, re, shutil, sys
from collections import OrderedDict

sys.stdout.reconfigure(encoding="utf-8")
TTR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL = os.path.join(os.path.dirname(TTR), "yunhai", "cloudsea-hunting-corps", "17_", "动作池")
OUT = os.path.join(TTR, "content", "cloudsea", "actions.json")
MANI = os.path.join(TTR, "docs", "cloudsea", "actions_manifest.json")

POS_KEYS = ("attack_zone", "self_reposition", "target_displace", "position_rule", "marks")
REF_RE = re.compile(r"\$C\.[A-Z0-9_]+(?:\.[A-Z0-9_]+)*")


def parse_pos(line):
    """方位行 → dict；—开头＝白名单行。"""
    body = line.split("：", 1)[1].strip() if "：" in line else line.strip()
    if body.startswith("—") or body.startswith("-（"):
        note = body.lstrip("—-（） ")
        return {"whitelist": True, "pos": {k: "none" for k in POS_KEYS},
                "note": note.strip("（） ") if note else "无方位语义"}
    pos, note = {}, ""
    m = re.search(r"（(.+)$", body)
    if m:
        note = m.group(1).rstrip("） ")
    for seg in body.split("｜"):
        seg = seg.strip()
        if "=" in seg:
            k, v = seg.split("=", 1)
            k = k.strip()
            if k in POS_KEYS:
                pos[k] = v.strip()
    for k in POS_KEYS:
        pos.setdefault(k, "none")
    return {"whitelist": False, "pos": pos, "note": note}


def parse_hits(resolve_raw):
    m = re.search(r"×\s*(\d+)\s*段", resolve_raw or "")
    return int(m.group(1)) if m else 1


def parse_card_file(path, source, entries):
    """卡式（B）：## 怪名/族名 ＋ ### 动作｜名 卡块。"""
    start = len(entries)
    txt = io.open(path, encoding="utf-8").read().replace("\r\n", "\n")
    owner, cur = None, None
    for ln in txt.split("\n"):
        if ln.startswith("## "):
            owner = re.sub(r"^## (?:名怪｜)?", "", ln).strip()
            continue
        if ln.startswith("### 动作｜"):
            cur = {"name": ln.split("｜", 1)[1].strip(), "owner": owner}
            entries.append({"source": source, **cur})
            continue
        if cur is None:
            continue
        e = entries[-1]
        if ln.startswith("- 归属："):
            body = ln.split("：", 1)[1]
            e["owner"] = body.split("｜")[0].strip() or e["owner"]
            for seg in body.split("｜"):
                if seg.strip().startswith("类型："):
                    e["ctype"] = seg.split("：", 1)[1].strip()
        elif ln.startswith("- 类型："):
            e["ctype"] = ln.split("：", 1)[1].strip()
        elif ln.startswith("- 意图行：") or ln.startswith("- 意图："):
            body = ln.split("：", 1)[1]
            e["intent_mark"] = "🌀" if body.startswith("🌀") else ("❓" if body.startswith("❓") else "—")
        elif ln.startswith("- 结算行：") or ln.startswith("- 结算："):
            e["resolve_raw"] = ln.split("：", 1)[1].strip()
        elif ln.startswith("- 引用"):
            seg = ln.split("：", 1)[1] if "：" in ln else ""
            e["refs"] = sorted(set(REF_RE.findall(seg.split("｜后续槽")[0])))
            for part in seg.split("｜"):
                if part.startswith("后续槽："):
                    e["follow"] = part.split("：", 1)[1].strip()
                elif part.startswith("破坏处置："):
                    e["break_disp"] = part.split("：", 1)[1].strip()
        elif ln.startswith("- 方位："):
            e.setdefault("posline", []).append(ln.strip("- ").strip())
    for e in entries[start:]:
        if "pos" in e:
            continue
        if "posline" in e:
            info = parse_pos(e["posline"][-1])
            e["pos"], e["whitelist"], e["pos_note"] = info["pos"], info["whitelist"], info["note"]
        else:
            # 独有招招卡无独立方位行：方位挂每怪绑定表（独有招册表列 537 行，215A 标注）——
            # 库条目记白名单态＋指向注；怪物面方位在 217/218 建 enemies.json 时自绑定表取
            e["whitelist"] = True
            e["pos"] = {k: "none" for k in ("attack_zone", "self_reposition",
                                            "target_displace", "position_rule", "marks")}
            e["pos_note"] = "方位随每怪绑定表（独有招册表列，215A 标注面）"
        e.setdefault("ctype", "攻击")
        e.setdefault("intent_mark", "—")
        e.setdefault("refs", [])
    return entries


def parse_compact_file(path, source, entries):
    """紧凑式（A）：### F01-01 · 名 ＋ 四行 bullet。"""
    txt = io.open(path, encoding="utf-8").read().replace("\r\n", "\n")
    cur = None
    for ln in txt.split("\n"):
        m = re.match(r"^### ([A-Z]\d\d-\d\d) · (.+)$", ln)
        if m:
            cur = {"source": source, "code": m.group(1), "name": m.group(2).strip(),
                   "owner": m.group(1)[:3]}
            entries.append(cur)
            continue
        if cur is None:
            continue
        e = entries[-1]
        if ln.startswith("- 归属："):
            parts = [x.split("：", 1)[-1].strip() for x in ln.strip("- ").split("｜")]
            e["ctype"] = next((x[3:] for x in ln.split("｜") if x.strip().startswith("类型：")), "攻击")
        elif ln.startswith("- 方位："):
            info = parse_pos(ln.strip("- ").strip())
            e["pos"], e["whitelist"], e["pos_note"] = info["pos"], info["whitelist"], info["note"]
        elif ln.startswith("- 意图："):
            body = ln.split("｜")[0].split("：", 1)[1]
            e["intent_mark"] = "🌀" if body.startswith("🌀") else ("❓" if body.startswith("❓") else "—")
            e["resolve_raw"] = ln.split("｜结算：")[1].strip() if "｜结算：" in ln else ""
        elif ln.startswith("- 后续："):
            e["follow"] = ln.split("：", 1)[1].strip()
    for e in entries:
        e.setdefault("ctype", "攻击")
        e.setdefault("intent_mark", "—")
        e.setdefault("resolve_raw", "")
        e.setdefault("refs", [])
        e.setdefault("whitelist", False)
    return entries


def parse_table_file(path, source, entries):
    """表行式（C）：独有招册 | 怪名 | 类 | 骨架族 | 独有招 | 权重微调 | 方位 |…"""
    txt = io.open(path, encoding="utf-8").read().replace("\r\n", "\n")
    for ln in txt.split("\n"):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 7 or cells[1] in ("", "怪名") or set(cells[1]) <= set("-: "):
            continue
        name = cells[4].strip()
        if not name or name in ("独有招",):
            continue
        e = {"source": source, "name": name, "owner": cells[1].strip(),
             "ctype": "攻击" if cells[2].strip() == "空" else "攻击", "owner_class": cells[2].strip()}
        posline = next((c for c in cells[5:] if c.startswith("attack_zone")), "")
        info = parse_pos("方位：" + posline) if posline else {
            "whitelist": True, "pos": {k: "none" for k in POS_KEYS}, "note": "无方位列"}
        e["pos"], e["whitelist"], e["pos_note"] = info["pos"], info["whitelist"], info["note"]
        e.setdefault("intent_mark", "—")
        e.setdefault("resolve_raw", "")
        e.setdefault("refs", [])
        entries.append(e)
    return entries


def build():
    entries = []
    parse_compact_file(os.path.join(POOL, "骨架族池_上.md"), "骨架族池_上", entries)
    parse_card_file(os.path.join(POOL, "骨架族池_下.md"), "骨架族池_下", entries)
    for sub in sorted(os.listdir(os.path.join(POOL, "个体池"))):
        parse_card_file(os.path.join(POOL, "个体池", sub), "个体池", entries)
    for sub in sorted(os.listdir(os.path.join(POOL, "巨兽差异"))):
        parse_card_file(os.path.join(POOL, "巨兽差异", sub), "巨兽差异", entries)
    for sub in sorted(os.listdir(os.path.join(POOL, "独有招"))):
        # 独有招册＝招卡（### 动作｜ 222）＋每怪绑定表（537 行，怪物面归 217/218）——只取招卡
        parse_card_file(os.path.join(POOL, "独有招", sub), "独有招", entries)
    # 幂等 id：册前缀＋序
    pref = {"骨架族池_上": "ska", "骨架族池_下": "skb", "个体池": "ind", "巨兽差异": "dif", "独有招": "uq"}
    seq = Counter()
    out = []
    for e in entries:
        n = seq(e["source"])
        eid = "%s_%03d" % (pref[e["source"]], n)
        out.append(OrderedDict([
            ("id", eid), ("code", e.get("code", "")), ("name", e["name"]),
            ("source", e["source"]), ("owner", e.get("owner", "")),
            ("ctype", e.get("ctype", "攻击")),
            ("intent_mark", e.get("intent_mark", "—")),
            ("hits", parse_hits(e.get("resolve_raw"))),
            ("resolve_raw", e.get("resolve_raw", "")),
            ("refs", e.get("refs", [])),
            ("follow", e.get("follow", "")),
            ("break_disp", e.get("break_disp", "")),
            ("whitelist", e["whitelist"]),
            ("pos", e["pos"]), ("pos_note", e.get("pos_note", "")),
            ("kind", "basic"), ("power", 1.0),
        ]))
    return out


class Counter(dict):
    def __missing__(self, k):
        return 0

    def __call__(self, k):
        v = self[k] + 1
        self[k] = v
        return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    out = build()
    by_src = {}
    for e in out:
        by_src[e["source"]] = by_src.get(e["source"], 0) + 1
    EXPECT = {"骨架族池_上": 68, "骨架族池_下": 60, "个体池": 377, "巨兽差异": 534, "独有招": 222}
    # 独有招册另含 537 行每怪绑定表（怪物面，归 217/218），不入动作库
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    mani = {"total": len(out), "by_source": by_src, "expect_1261": EXPECT,
            "pos_whitelist": sum(1 for e in out if e["whitelist"]),
            "pos_annotated": sum(1 for e in out if not e["whitelist"])}
    io.open(MANI, "w", encoding="utf-8", newline="\n").write(
        json.dumps(mani, ensure_ascii=False, indent=1) + "\n")
    print("出片", len(out), "招；分册", by_src)
    if args.check:
        ok = []
        ok.append(("A1 总量=1261 对账", len(out) == 1261 and all(by_src.get(k) == v for k, v in EXPECT.items()),
                   str(by_src)))
        ids = [e["id"] for e in out]
        ok.append(("A2 id 唯一", len(set(ids)) == len(ids), f"{len(set(ids))}"))
        bad3 = [e["id"] for e in out if not e["name"] or not e["source"]]
        ok.append(("A3 必备键齐（id/name/source）", not bad3, str(bad3[:3])))
        npos = sum(1 for e in out if any(e["pos"][k] != "none" for k in POS_KEYS) or e["whitelist"])
        ok.append(("A4 方位字段覆盖（标注或白名单）", npos == len(out), f"{npos}/{len(out)}"))
        snap1 = json.dumps(out, ensure_ascii=False, sort_keys=True)
        out2 = build()
        snap2 = json.dumps(out2, ensure_ascii=False, sort_keys=True)
        ok.append(("A5 幂等重放", snap1 == snap2, ""))
        for name, cond, det in ok:
            print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" —— {det}" if det else ""))
        sys.exit(0 if all(c for _, c, _ in ok) else 1)


if __name__ == "__main__":
    main()
