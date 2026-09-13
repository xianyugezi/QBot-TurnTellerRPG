# -*- coding: utf-8 -*-
"""assemble_enemies_226.py —— 九期批次 226 · 怪物七潮位包 I–III（微澜/潮涌/湍流 → 包 enemies 面）

源＝content/cloudsea/enemies_t1–t3.json（批次 217 管线产物）；出片＝content/cloudsea/enemies.json
（test_demo enemies schema 同构超集：id/name/tier/area/stats/weakness/resistance/actions/pv/lore +
 provenance 面 skeleton/bio_class/parts/actions_unresolved 等，供 238 探针）。
actions＝actions_ref→{action, weight:50 缺省}（权重特化细表归 217 增量/238 校准）；
lore＝生态册猎获档案（217 tiers 已载 mech，本器补猎获列）；drops＝flag（素材面归增量二）。
对账：I–III 287 恰尽（105/93/89）；id 唯一；actions id 100% 在 actions.json；power/pv 不变式。
"""
import io, json, os, re, sys
from collections import OrderedDict

sys.stdout.reconfigure(encoding="utf-8")
TTR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUD = os.path.join(TTR, "content", "cloudsea")
DS = os.path.join(os.path.dirname(TTR), "yunhai", "cloudsea-hunting-corps")
ECO = os.path.join(DS, "17_世界内容与生态")
TIDES_DEFAULT = (1, 2, 3)
OUT = os.path.join(CLOUD, "enemies.json")
MANI = os.path.join(TTR, "docs", "cloudsea", "enemies_226_manifest.json")

ECO_FILES = {
    "云顶针叶林": "阶段一_微澜/01_云顶针叶林.md", "悬瀑苔崖": "阶段一_微澜/02_悬瀑苔崖.md",
    "岛根垂荫": "阶段一_微澜/03_岛根垂荫.md", "灰岗旧港": "阶段一_微澜/04_灰岗旧港.md",
    "浮滩浅礁": "阶段二_潮涌/01_浮滩浅礁.md", "升降岛链": "阶段二_潮涌/02_升降岛链.md",
    "沉岛云渊": "阶段二_潮涌/03_沉岛云渊.md",
    "碎屿浮岩": "阶段三_湍流/01_碎屿浮岩.md", "涡旋岩廊": "阶段三_湍流/02_涡旋岩廊.md",
    "乱涡深穴": "阶段三_湍流/03_乱涡深穴.md",
}


def read(p):
    return io.open(p, encoding="utf-8").read().replace("\r\n", "\n")


def parse_lore():
    """生态册 猎获档案（行末列）→ 怪名→档案句。"""
    lore = {}
    for eco, rel in ECO_FILES.items():
        txt = read(os.path.join(ECO, rel))
        for row in re.finditer(r"^\| \d+ \|(.*?)\|\s*$", txt, re.M):
            cells = [c.strip() for c in row.group(1).split("|")]
            if len(cells) < 4:
                continue
            nm = re.match(r"\*\*(.+?)\*\*", cells[0])
            if nm:
                lore[nm.group(1).strip()] = cells[-1]
    return lore


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tides", default=",".join(str(x) for x in TIDES_DEFAULT))
    ap.add_argument("--merge", action="store_true", help="保留 enemies.json 中非本轮潮位条目（增量扩装）")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    tides = tuple(int(x) for x in args.tides.split(","))
    acts = json.load(io.open(os.path.join(CLOUD, "action.json"), encoding="utf-8"))
    valid_ids = {e["id"] for e in acts}
    lore = parse_lore()

    out = []
    per = {}
    if getattr(args, "merge", False):
        kept = 0
        if os.path.exists(OUT):
            for e in json.load(io.open(OUT, encoding="utf-8")):
                if e.get("source_tide") not in tides:
                    out.append(e)
                    kept += 1
        print("merge 保留既有", kept, "只")
    for t in tides:
        rows = json.load(io.open(os.path.join(CLOUD, "generated", "enemies_t%d.json" % t), encoding="utf-8"))
        per[t] = len(rows)
        for e in rows:
            actions = [{"action": aid, "weight": 50} for aid in e.get("actions_ref", [])]
            out.append(OrderedDict([
                ("id", e["id"]), ("name", e["name"]),
                ("tier", {"常规巨兽": "normal", "空兽": "normal", "杂兽": "normal",
                          "终盘巨兽": "elite"}.get(e["tier"], "normal")),
                ("cloudsea_tier", e["tier"]),
                ("area", e["area"]),
                ("desc", e.get("mech", "")),
                ("stats", {"hp": e["hp"]}),
                ("weakness", e.get("weakness", {"rule_gen": True})),
                ("resistance", e.get("resistance", {})),
                ("pv", e.get("parts_total_threshold")),
                ("parts", e.get("parts", [])),
                ("actions", actions),
                ("drops", {"rule_gen": "素材面归增量二（18_/06 十四类挂口）"}),
                ("lore", [{"unlock": 10, "desc": lore.get(e["name"], e.get("mech", ""))[:80]}]),
                ("skeleton", e.get("skeleton")), ("bio_class", e.get("bio_class")),
                ("actions_unresolved", e.get("moves_unresolved", [])),
                ("source_tide", t),
            ]))
    per = {}
    for e in out:
        per[e["source_tide"]] = per.get(e["source_tide"], 0) + 1
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    mani = {"batch": "226/227", "tides": list(tides), "total": len(out), "per_tide": per,
            "actions_resolved": sum(1 for e in out for a in e["actions"]),
            "lore_filled": sum(1 for e in out if e["lore"][0]["desc"])}
    io.open(MANI, "w", encoding="utf-8", newline="\n").write(
        json.dumps(mani, ensure_ascii=False, indent=1) + "\n")
    print("enemies.json 出片", len(out), "只；", per)
    if args.check:
        ok = []
        ids = [e["id"] for e in out]
        ok.append(("A1 分潮位合计一致", sum(per.values()) == len(out), str(per)))
        ok.append(("A2 id 唯一", len(set(ids)) == len(ids), f"{len(set(ids))}"))
        bad3 = [a["action"] for e in out for a in e["actions"] if a["action"] not in valid_ids]
        ok.append(("A3 actions 全在动作库", not bad3, str(bad3[:3])))
        bad4 = [e["id"] for e in out if not e["stats"]["hp"] or not e["name"]]
        ok.append(("A4 必备键齐", not bad4, str(bad4[:3])))
        for name, cond, det in ok:
            print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" —— {det}" if det else ""))
        sys.exit(0 if all(c for _, c, _ in ok) else 1)


if __name__ == "__main__":
    main()
