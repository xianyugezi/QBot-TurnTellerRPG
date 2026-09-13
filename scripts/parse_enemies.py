# -*- coding: utf-8 -*-
"""parse_enemies.py v2 —— 九期批次 217 增量二 · 怪物转译管线（七潮位全量）

数据链五源合流（v1 同构，扩七潮位）：
  L1 名册＝生态册（tier/机制锚）｜L2 挂配置＝怪挂配置_潮位N（骨架族/bio/独有招引用/权重微调）
  L3 抗性＝04 §M4.6 表 A（主线 Boss 18）＋表 B（异相种）；非具名怪 rule_gen 旗（五规则默认归增量三）
  L4 破坏＝行为性破坏铺开五分册｜L5 方位＝独有招绑定表（215A）｜L6 组装＝enemies_t{N}.json ×7

EHP 缺省演算＝$C.TIDE.BASE_EHP[潮] × STAR_COEF[星段中值] × TIDE.LAYER[类]；
具名 Boss 走详设 NAMED_EHP（灰岗 12000＝03 §M3.11）。
生态→(潮,星段中值) 自 01_生态总表_28生态.md 行解析（剧情专属星段取潮位中值）。
对账：760 恰尽＝分潮位合计；每生态 tier 计数 == 生态总表行（巨兽/空兽/杂兽三列）。
"""
import argparse, io, json, os, re, sys
from collections import OrderedDict

sys.stdout.reconfigure(encoding="utf-8")
TTR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = os.path.join(os.path.dirname(TTR), "yunhai", "cloudsea-hunting-corps")
POOL = os.path.join(DS, "17_", "动作池")
ECO = os.path.join(DS, "17_世界内容与生态")
OUTDIR = os.path.join(TTR, "content", "cloudsea")
MANI = os.path.join(TTR, "docs", "cloudsea", "enemies_manifest.json")

BASE_EHP = [12000, 14500, 19000, 23100, 29300, 36600, 45800]  # $C.TIDE.BASE_EHP（波段化后）
STAR_COEF = {1: 1.40, 2: 1.51, 3: 1.63, 4: 1.80, 5: 1.86, 6: 1.92, 7: 1.97, 8: 2.03, 9: 2.09, 10: 2.18}
LAYER = {"终盘巨兽": 1.00, "常规巨兽": 0.75, "空兽": 0.35, "杂兽": 0.15}
NAMED_EHP = {"崩岭岩犀 · 灰岗": 12000}  # 03 §M3.11 详设 EHP（具名优先）
TIDE_NO = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
ANOM = ["腐蚀", "麻痹", "沉眠", "爆燃", "风蚀", "泥陷", "霜缚", "雷殛", "风暴"]
CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七"}


def read(p):
    return io.open(p, encoding="utf-8").read().replace("\r\n", "\n")


def parse_total_table():
    """01_生态总表 → {生态名: {tide, star_mid, exp tiers 计数}}；并返回 per-tide 生态名清单。"""
    txt = read(os.path.join(DS, "17_世界内容与生态", "01_生态总表_28生态.md"))
    ecos, per_tide = {}, {}
    for ln in txt.split("\n"):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 9 or cells[1] in ("", "潮位") or set(cells[1]) <= set("-: "):
            continue
        tide_name, eco_cell, star, _ty, beast, kong, za = cells[1], cells[2], cells[3], cells[4], cells[5], cells[6], cells[7]
        m = re.match(r"\[([^\]]+)\]", eco_cell)
        if not m or tide_name[:1] not in TIDE_NO:
            continue
        eco = m.group(1)
        tide = TIDE_NO.get(tide_name[:1])
        rng = re.match(r"(\d+)～(\d+)星", star)
        if rng:
            smid = (int(rng.group(1)) + int(rng.group(2))) / 2
        else:  # 剧情专属
            smid = min(10.0, max(1.0, 2 + (tide - 1) * 1.5))  # 剧情专属缺省：随潮位线性，钳 [1,10]
        bz = int(re.match(r"(\d+)", beast).group(1))
        zp = int(re.search(r"（(\d+)）", beast).group(1)) if "（" in beast else 0
        kong_n = int(kong)
        za_n = int(za)
        ecos[eco] = {"tide": tide, "star_mid": smid,
                     "exp": {"常规巨兽": bz - zp, "终盘巨兽": zp, "空兽": kong_n, "杂兽": za_n}}
        per_tide.setdefault(tide, []).append(eco)
    return ecos, per_tide


def parse_tier_counts_by_eco(eco_name, eco_rel):
    """生态册 tier 实数（tier → n）。"""
    txt = read(os.path.join(ECO, eco_rel))
    counts = {}
    for sec in ["常规巨兽", "终盘巨兽", "空兽", "杂兽"]:
        mm = re.search(r"### " + sec + r"[^\n]*\n(.*?)(?=\n### |\n## |\Z)", txt, re.S)
        if mm:
            counts[sec] = sum(1 for x in re.finditer(r"^\| \d+ \|", mm.group(1), re.M))
    return counts


def parse_guazhi_names(path):
    """挂配置行：保序怪名＋字段。"""
    out, cur_eco = [], None
    for ln in read(path).split("\n"):
        m = re.match(r"^## (.+?)（", ln)
        if m:
            cur_eco = m.group(1).strip()
            continue
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 9 or cells[1] in ("", "怪名") or set(cells[1]) <= set("-: "):
            continue
        out.append({"name": cells[1], "eco": cur_eco, "skeleton": cells[2], "bio": cells[3],
                    "moves_raw": cells[4], "weight_tune": cells[5], "note": cells[8]})
    return out


def parse_eco_tiers(eco_rel):
    txt = read(eco_rel)
    eco = os.path.basename(eco_rel).split("_", 1)[1].replace(".md", "")
    tiers = {}
    for sec in ["常规巨兽", "终盘巨兽", "空兽", "杂兽"]:
        mm = re.search(r"### " + sec + r"[^\n]*\n(.*?)(?=\n### |\n## |\Z)", txt, re.S)
        if not mm:
            continue
        for row in re.finditer(r"^\| \d+ \|(.*?)\|\s*$", mm.group(1), re.M):
            cells = [c.strip() for c in row.group(1).split("|")]
            nm = re.match(r"\*\*(.+?)\*\*", cells[0])
            if nm:
                tiers[nm.group(1).strip()] = {"tier": sec, "eco": eco,
                                              "mech": cells[1] if len(cells) > 1 else ""}
    return tiers


def parse_resists():
    """04 §M4.6 表 A＋表 B → 名（归一）→ R 值面。"""
    txt = read(os.path.join(DS, "04_异常打击体系与共生灵.md"))
    sec = txt.split("### M4.6")[1]
    res = {}
    for ln in sec.split("\n"):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 11 or not cells[1] or set(cells[1]) <= set("-: "):
            continue
        vals = {c: cells[i + 2] for i, c in enumerate(ANOM)}
        if not any(vals.values()):
            continue
        nm = re.sub(r"^\d+(?:\.\d+)? · ", "", cells[1])
        nm = re.sub(r"（.+?）", "", nm).strip()
        res.setdefault(nm, vals)
    return res


def parse_breaks():
    binds = {}
    d = os.path.join(ECO, "行为性破坏铺开")
    for sub in sorted(os.listdir(d)):
        if not sub.endswith(".md"):
            continue
        txt = read(os.path.join(d, sub))
        for chunk in re.split(r"\n### ", txt)[1:]:
            header = chunk.split("\n", 1)[0].strip()
            nm = re.sub(r"（.*$", "", header).strip()
            if "挂起" in header:
                continue
            for blk in re.findall(r"```yaml\n(.*?)```", chunk, re.S):
                pm = re.match(r"(.+?)（(.+?)）:", blk)
                if not pm:
                    continue
                for mv in re.findall(r"([^\s{:}]+): \{ gated_by:", blk):
                    binds.setdefault(nm, []).append({"part": pm.group(1).strip(), "move": mv.strip()})
    return binds


def parse_duyou():
    binds = {}
    d = os.path.join(POOL, "独有招")
    for sub in sorted(os.listdir(d)):
        for ln in read(os.path.join(d, sub)).split("\n"):
            if not ln.startswith("|"):
                continue
            cells = [c.strip() for c in ln.split("|")]
            if len(cells) < 7 or cells[1] in ("", "怪名") or set(cells[1]) <= set("-: "):
                continue
            poscell = next((c for c in cells[5:] if c.startswith("attack_zone")), "")
            moves = [x.strip() for x in cells[4].split("／") if x.strip() and x.strip() != "—"]
            binds.setdefault(cells[1], {"moves": moves, "pos": poscell})
    return binds


def build():
    ecos, per_tide = parse_total_table()
    name2id = {}
    acts = json.load(io.open(os.path.join(OUTDIR, "actions.json"), encoding="utf-8"))
    for e in acts:
        name2id.setdefault(e["name"], e["id"])
    all_tiers = {}
    for dirpath in sorted(os.listdir(ECO)):
        d2 = os.path.join(ECO, dirpath)
        if os.path.isdir(d2) and dirpath.startswith("阶段"):
            for f2 in sorted(os.listdir(d2)):
                if re.match(r"[0-9]", f2) and f2.endswith(".md"):
                    all_tiers.update(parse_eco_tiers(os.path.join(d2, f2)))
    resist = parse_resists()
    breaks = parse_breaks()
    dyb = parse_duyou()

    all_out, manifests = [], {}
    unres = sorted(set())
    for tide in range(1, 8):
        gz = parse_guazhi_names(os.path.join(POOL, "怪挂配置_潮位%s.md" % CN[tide]))
        rows = []
        for g in gz:
            nm = g["name"]
            eco_meta = ecos.get(g["eco"], {})
            tide_i = eco_meta.get("tide", tide)
            smid = eco_meta.get("star_mid", 2)
            tier = all_tiers.get(nm, {}).get("tier", "常规巨兽")
            ehp = BASE_EHP[tide_i - 1] * STAR_COEF[int(round(smid))] * LAYER.get(tier, 0.75)
            if nm in NAMED_EHP:
                ehp = NAMED_EHP[nm]
            moves = [x.strip() for x in re.split("／", g["moves_raw"]) if x.strip() and x.strip() != "—"]
            mids = [name2id[m] for m in moves if m in name2id]
            unres += [m for m in moves if m not in name2id]
            rows.append(OrderedDict([
                ("id", "cs_t%d_%03d" % (tide, len(rows) + 1)), ("name", nm),
                ("tide", tide_i), ("area", g["eco"]), ("tier", tier),
                ("skeleton", g["skeleton"]), ("bio_class", g["bio"]),
                ("hp", round(ehp)), ("ehp_named", nm in NAMED_EHP),
                ("weakness", {"rule_gen": "三级默认归增量三"}),
                ("resistance", resist.get(nm, {"rule_gen": "五规则默认归增量三"})),
                ("actions_ref", mids),
                ("moves_unresolved", [m for m in moves if m not in name2id]),
                ("weight_tune", g["weight_tune"]),
                ("duyou_pos", dyb.get(nm, {}).get("pos", "")),
                ("break_bindings", breaks.get(nm, [])),
            ]))
            all_out.append(rows[-1])
        path = os.path.join(OUTDIR, "enemies_t%d.json" % tide)
        io.open(path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
        manifests[tide] = {"total": len(rows),
                           "ecos": {eco: {"count": None, "exp": ecos[eco]["exp"]}
                                    for eco in per_tide[tide]}}
    # 层级对账：每生态 tier 实数 == 总表行
    mism = []
    for tide in range(1, 8):
        path = os.path.join(OUTDIR, "enemies_t%d.json" % tide)
        rows = json.load(io.open(path, encoding="utf-8"))
        cnt = {}
        for r in rows:
            cnt.setdefault(r["area"], {}).setdefault(r["tier"], 0)
            cnt[r["area"]][r["tier"]] += 1
        for eco, info in manifests[tide]["ecos"].items():
            got = cnt.get(eco, {})
            exp = info["exp"]
            for k in ("常规巨兽", "空兽", "杂兽"):
                if got.get(k, 0) != exp[k]:
                    mism.append((eco, k, got.get(k, 0), exp[k]))
            info["count"] = sum(got.values())
    return all_out, manifests, mism, unres


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    all_out, manifests, mism, unres = build()
    per = {t: m["total"] for t, m in manifests.items()}
    io.open(MANI, "w", encoding="utf-8", newline="\n").write(
        json.dumps({"per_tide": per, "total": len(all_out),
                    "unresolved_moves": sorted(set(unres))},
                   ensure_ascii=False, indent=1) + "\n")
    print("七潮位", per, "总", len(all_out), "；未解析招", len(unres), "；层级对账错位", len(mism))
    if args.check:
        ok = []
        ok.append(("A1 760 恰尽（分潮位合计）", len(all_out) == 760 and sum(per.values()) == 760, str(per)))
        ok.append(("A2 每生态 tier 计数 == 生态总表三列", not mism, str(mism[:4])))
        ok.append(("A3 独有招引用全解析", not unres, str(sorted(set(unres))[:5])))
        ids = [e["id"] for e in all_out]
        ok.append(("A4 id 唯一", len(set(ids)) == len(ids), f"{len(set(ids))}"))
        bad5 = [e["id"] for e in all_out if e["hp"] <= 0]
        ok.append(("A5 hp 演算全正", not bad5, str(bad5[:3])))
        for name, cond, det in ok:
            print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" —— {det}" if det else ""))
        sys.exit(0 if all(c for _, c, _ in ok) else 1)


if __name__ == "__main__":
    main()
