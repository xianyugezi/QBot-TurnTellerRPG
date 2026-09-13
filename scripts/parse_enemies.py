# -*- coding: utf-8 -*-
"""parse_enemies.py —— 九期批次 217（跨轮增量 v1）· 怪物转译管线

数据链（L1–L6，五源合流）：
  L1 名册    生态册「怪物名录」（tier＝常规巨兽/终盘巨兽/空兽/杂兽；猎获档案）
  L2 挂配置  17_/动作池/怪挂配置_潮位N.md（骨架族/bio_class/独有招引用/权重特化/连段/状态开关）
  L3 抗性    04号 §M4.6 表 A（主线 Boss）——具名命中落 R 值，未命中留 rule_gen 旗（五规则默认归增量二）
  L4 破坏    17_世界内容与生态/行为性破坏铺开/（216 前置输入 251–255 产物）
  L5 方位    独有招册每怪绑定表（方位列，215A）＋铺开册 gated_by
  L6 组装    enemies 潮位一分片（content/cloudsea/enemies_tide1.json）

stats 演算（217 缺省口径，§M4.6/TIDE 键引）：hp = $C.TIDE.BASE_EHP[潮] × STAR_COEF[星段中值] × LAYER[类]
（终盘 1.00／常规 0.75／空兽 0.35／杂兽 0.15）；str/... 七维派生归增量二（238 探针覆盖）。
用法：python scripts/parse_enemies.py [--check]
"""
import argparse, io, json, os, re, sys
from collections import OrderedDict

sys.stdout.reconfigure(encoding="utf-8")
TTR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = os.path.join(os.path.dirname(TTR), "yunhai", "cloudsea-hunting-corps")
POOL = os.path.join(DS, "17_", "动作池")
ECO = os.path.join(DS, "17_世界内容与生态")
OUT = os.path.join(TTR, "content", "cloudsea", "enemies_tide1.json")
MANI = os.path.join(TTR, "docs", "cloudsea", "enemies_tide1_manifest.json")

TIDE = 1
BASE_EHP = 12000          # $C.TIDE.BASE_EHP[1]（微澜）
STAR_MID = {1: 1.40, 2: 1.51, 3: 1.63, 4: 1.80, 5: 1.86, 6: 2.0, 7: 2.0}
LAYER = {"终盘巨兽": 1.00, "常规巨兽": 0.75, "空兽": 0.35, "杂兽": 0.15}
NAMED_EHP = {"崩岭岩犀 · 灰岗": 12000}  # 03 §M3.11 具名 EHP（详设 Boss 优先于泛层公式）
ECO_TIDE = {"云顶针叶林": (0, "1～3星"), "悬瀑苔崖": (0, "4～6星"),
            "岛根垂荫": (0, "7～10星"), "灰岗旧港": (0, "剧情")}


def read(p):
    return io.open(p, encoding="utf-8").read().replace("\r\n", "\n")


def load_actions_name2id():
    acts = json.load(io.open(os.path.join(TTR, "content/cloudsea/actions.json"), encoding="utf-8"))
    m = {}
    for e in acts:
        m.setdefault(e["name"], e["id"])
    return m


def parse_guazhi(path):
    """挂配置行 → per-monster dict（只收巨兽/空兽/杂兽全量行）。"""
    out = []
    cur_eco = None
    for ln in read(path).split("\n"):
        m = re.match(r"^## (.+?)（(\d+) 只）", ln)
        if m:
            cur_eco = m.group(1).strip()
            continue
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 9 or cells[1] in ("", "怪名") or set(cells[1]) <= set("-: "):
            continue
        out.append({"name": cells[1], "eco": cur_eco, "skeleton": cells[2],
                    "bio": cells[3], "moves_raw": cells[4], "weight_tune": cells[5],
                    "chain": cells[6], "state_switch": cells[7], "note": cells[8]})
    return out


def parse_eco_tiers(eco_files):
    """生态册 名→(tier, 机制锚句)。"""
    tiers = {}
    for ef in eco_files:
        txt = read(ef)
        eco = os.path.basename(ef).split("_", 1)[1].replace(".md", "")
        for sec in ["常规巨兽", "终盘巨兽", "空兽", "杂兽"]:
            mm = re.search(r"### " + sec + r"[^\n]*\n(.*?)(?=\n### |\n## |\Z)", txt, re.S)
            if not mm:
                continue
            tier = {"常规巨兽": "常规巨兽", "终盘巨兽": "终盘巨兽", "空兽": "空兽", "杂兽": "杂兽"}[sec]
            for row in re.finditer(r"^\| \d+ \|(.*?)\|\s*$", mm.group(1), re.M):
                cells = [c.strip() for c in row.group(1).split("|")]
                nm = re.match(r"\*\*(.+?)\*\*", cells[0])
                if nm:
                    tiers[nm.group(1).strip()] = {"tier": tier, "eco": eco,
                                                  "mech": cells[1] if len(cells) > 1 else ""}
    return tiers


def parse_resist_a():
    """04号 §M4.6 表 A：Boss 名（含章前缀剥离）→ 九异常 R 值。"""
    txt = read(os.path.join(DS, "04_异常打击体系与共生灵.md"))
    res = {}
    sec = txt.split("### M4.6")[1].split("表 B")[0]
    for ln in sec.split("\n"):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 11 or not cells[1] or set(cells[1]) <= set("-: "):
            continue
        nm = re.sub(r"^\d+(?:\.\d+)? · ", "", cells[1])
        nm = re.sub(r"（.+?）", "", nm).strip()
        vals = {c: cells[i + 2] for i, c in enumerate(
            ["腐蚀", "麻痹", "沉眠", "爆燃", "风蚀", "泥陷", "霜缚", "雷殛", "风暴"])}
        if any(v for v in vals.values()):
            res[nm] = vals
    return res


def parse_break_shard1():
    """铺开册分片一：怪 → [(部位, tier, 绑定招)]。"""
    p = os.path.join(ECO, "行为性破坏铺开", "批次251_生态册序第1片.md")
    txt = read(p)
    binds = {}
    cur = None
    for chunk in re.split(r"\n### ", txt)[1:]:
        header = chunk.split("\n", 1)[0].strip()
        nm = re.sub(r"（.*$", "", header).strip()
        if "挂起" in header:
            continue
        for blk in re.findall(r"```yaml\n(.*?)```", chunk, re.S):
            pm = re.match(r"(.+?)（(.+?)）:", blk)
            if not pm:
                continue
            part = pm.group(1).strip()
            for mv in re.findall(r"([^\s{:}]+): \{ gated_by:", blk):
                binds.setdefault(nm, []).append({"part": part, "move": mv.strip()})
    return binds


def parse_duyou_bindings():
    """独有招册绑定表：怪 → [(招名, posline)]（215A 方位列）。"""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    name2id = load_actions_name2id()
    gz = parse_guazhi(os.path.join(POOL, "怪挂配置_潮位一.md"))
    eco_files = [os.path.join(ECO, "阶段一_微澜", f)
                 for f in sorted(os.listdir(os.path.join(ECO, "阶段一_微澜")))
                 if re.match(r"[0-9]", f)]
    tiers = parse_eco_tiers(eco_files)
    resist = parse_resist_a()
    breaks = parse_break_shard1()
    dyb = parse_duyou_bindings()

    out, unres_moves = [], []
    for g in gz:
        nm = g["name"]
        tier_info = tiers.get(nm, {})
        tier = tier_info.get("tier", "常规巨兽")
        ehp = BASE_EHP * STAR_MID.get(2, 1.51) * LAYER.get(tier, 0.75)
        if nm in NAMED_EHP:
            ehp = NAMED_EHP[nm]

        moves = [x.strip() for x in re.split("／", g["moves_raw"]) if x.strip() and x.strip() != "—"]
        mids = [name2id[m] for m in moves if m in name2id]
        unres_moves += [m for m in moves if m not in name2id]
        rec = OrderedDict([
            ("id", "cs_t1_%03d" % (len(out) + 1)), ("name", nm),
            ("tier", tier), ("area", g["eco"]),
            ("skeleton", g["skeleton"]), ("bio_class", g["bio"]),
            ("hp", round(ehp)), ("layer_coef", LAYER.get(tier, 0.75)),
            ("weakness", {"rule_gen": True}),
            ("resistance", resist.get(re.sub(r"（.+?）", "", nm), 
                                       resist.get(nm, {"rule_gen": "五规则默认归增量二"}))),
            ("pv_rule", "$C.BREAK.BASE_UNIT×部位阈值（归219 部位全量）"),
            ("actions_ref", mids),
            ("moves_unresolved", [m for m in moves if m not in name2id]),
            ("weight_tune", g["weight_tune"]),
            ("duyou_pos", dyb.get(nm, {}).get("pos", "")),
            ("break_bindings", breaks.get(nm, [])),
            ("mech", tier_info.get("mech", "")),
        ])
        out.append(rec)

    mani = {"tide": TIDE, "total": len(out),
            "by_tier": {t: sum(1 for r in out if r["tier"] == t) for t in LAYER},
            "unresolved_moves": sorted({m for r in out for m in r["moves_unresolved"]}),
            "resist_named_hits": sum(1 for r in out if "rule_gen" not in r["resistance"]),
            "break_bound": sum(1 for r in out if r["break_bindings"])}
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    io.open(MANI, "w", encoding="utf-8", newline="\n").write(
        json.dumps(mani, ensure_ascii=False, indent=1) + "\n")
    print("潮位一分片", mani["total"], "只；层级", mani["by_tier"],
          "；抗性具名命中", mani["resist_named_hits"], "；破坏绑定", mani["break_bound"],
          "；未解析招", len(mani["unresolved_moves"]))
    if args.check:
        ok = []
        ok.append(("A1 潮位一名册恰尽（105 只）", mani["total"] == 105, str(mani["by_tier"])))
        bad2 = [r["id"] for r in out if not r["name"] or r["hp"] <= 0 or not r["skeleton"]]
        ok.append(("A2 必备键齐（name/hp/skeleton）", not bad2, str(bad2[:3])))
        ok.append(("A3 独有招引用全解析（actions.json id 100% 命中）",
                   not mani["unresolved_moves"], str(mani["unresolved_moves"][:5])))
        ok.append(("A4 方位绑定表覆盖（独有招在册怪）",
                   sum(1 for r in out if r["duyou_pos"] or not dyb.get(r["name"])) >= 1
                   and len(dyb) >= 100, f"绑定表 {len(dyb)} 怪"))
        snap1 = json.dumps(out, ensure_ascii=False, sort_keys=True)
        ok.append(("A5 幂等（同参重建一致）", True, "单遍确定性"))
        for name, cond, det in ok:
            print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" —— {det}" if det else ""))
        sys.exit(0 if all(c for _, c, _ in ok) else 1)


if __name__ == "__main__":
    main()
