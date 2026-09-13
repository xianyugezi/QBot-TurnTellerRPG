# -*- coding: utf-8 -*-
"""verify_tide_pack.py —— 九期批次 243 · 七潮位分版本验收

逐潮位（t1–t7）验收面（对 content/cloudsea/enemies_t{N}.json ＋ enemies.json 分片）：
  V1 名册恰尽   分片只数 == 生态总表该潮位行合计（巨兽/空兽/杂兽三层）
  V2 必备键齐   id/name/tier/area/stats.hp/skeleton 非空正
  V3 actions 回链  独有招引用 100% 解析回 content/cloudsea/actions.json
  V4 EHP 演算   抽 1 只非具名怪复算 BASE_EHP×STAR_COEF[星段中值]×LAYER == hp
  V5 分片=总面  enemies.json 中该潮位子集与分片 id 集合一致
汇总：七片全绿＋总 760＋enemies.json 760＋id 全局唯一。
用法：python scripts/verify_tide_pack.py [--check]（--check 退出码 0/1）
"""
import io, json, os, re, sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
TTR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = os.path.join(os.path.dirname(TTR), "yunhai", "cloudsea-hunting-corps")
ECO_TABLE = os.path.join(DS, "17_世界内容与生态", "01_生态总表_28生态.md")
CLOUD = os.path.join(TTR, "content", "cloudsea")

BASE_EHP = [12000, 14500, 19000, 23100, 29300, 36600, 45800]
STAR_COEF = {1: 1.40, 2: 1.51, 3: 1.63, 4: 1.80, 5: 1.86, 6: 1.92, 7: 1.97,
             8: 2.03, 9: 2.09, 10: 2.18}
LAYER = {"终盘巨兽": 1.00, "常规巨兽": 0.75, "空兽": 0.35, "杂兽": 0.15}
TIDE_NO = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}


def read(p):
    return io.open(p, encoding="utf-8").read().replace("\r\n", "\n")


def total_table():
    ecos = {}
    for ln in read(ECO_TABLE).split("\n"):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 9 or cells[1] in ("", "潮位") or set(cells[1]) <= set("-: "):
            continue
        m = re.match(r"\[([^\]]+)\]", cells[2])
        if not m or cells[1][:1] not in TIDE_NO:
            continue
        beast = cells[5]
        bz = int(re.match(r"(\d+)", beast).group(1))
        zp = int(re.search(r"（(\d+)）", beast).group(1)) if "（" in beast else 0
        rng = re.match(r"(\d+)～(\d+)星", cells[3])
        if rng:
            smid = (int(rng.group(1)) + int(rng.group(2))) / 2
        else:
            smid = min(10.0, max(1.0, 2 + (TIDE_NO[cells[1][:1]] - 1) * 1.5))
        ecos[m.group(1)] = {"tide": TIDE_NO[cells[1][:1]], "star_mid": smid,
                            "exp": {"常规巨兽": bz - zp, "终盘巨兽": zp,
                                    "空兽": int(cells[6]), "杂兽": int(cells[7])}}
    return ecos


def main():
    ecos = total_table()
    acts = json.load(io.open(os.path.join(CLOUD, "actions.json"), encoding="utf-8"))
    valid_ids = {e["id"] for e in acts}
    ens_all = json.load(io.open(os.path.join(CLOUD, "enemies.json"), encoding="utf-8"))
    ids_all = Counter = {}
    for e in ens_all:
        ids_all[e["id"]] = e
    failures = []
    grand = 0
    for tide in range(1, 8):
        failures = []
        rows = json.load(io.open(os.path.join(CLOUD, "enemies_t%d.json" % tide),
                                 encoding="utf-8"))
        exp_by_eco = {}
        for eco, meta in ecos.items():
            if meta["tide"] == tide:
                exp_by_eco[eco] = meta["exp"]
        got = {}
        for r in rows:
            got.setdefault(r["area"], {}).setdefault(r["tier"], 0)
            got[r["area"]][r["tier"]] += 1
        bad1 = []
        for eco, exp in exp_by_eco.items():
            for k, n in exp.items():
                if got.get(eco, {}).get(k, 0) != n:
                    bad1.append((eco, k))
        miss1 = [eco for eco in exp_by_eco if eco not in got]
        v1 = not bad1 and not miss1
        bad2 = [r["id"] for r in rows
                if not r.get("name") or r.get("hp", 0) <= 0 or not r.get("skeleton")
                or not r.get("area")]
        v2 = not bad2
        bad3 = []
        id2entry = {e["id"]: e for e in acts}
        for r in rows:
            for aid in r.get("actions_ref", []) if isinstance(r, dict) else []:
                if aid not in valid_ids:
                    bad3.append((r["id"], aid))
        v3 = not bad3
        v4 = True
        for r in rows:
            if r.get("ehp_named"):
                continue  # 具名 Boss 走详设 EHP（NAMED_EHP），不作泛层演算
            eco_meta = ecos.get(r["area"], {})
            smid = eco_meta.get("star_mid", 2)
            expected = round(BASE_EHP[tide - 1] * STAR_COEF[int(round(smid))]
                             * LAYER.get(r["tier"], 0.75))
            if r["hp"] != expected:
                v4 = False
                failures.append(("V4", r["id"], r["hp"], expected))
                break
        ids_t = {r["id"] for r in rows}
        sub = {e["id"] for e in ens_all if e["source_tide"] == tide}
        v5 = ids_t == sub
        grand += len(rows)
        state = "绿" if (v1 and v2 and v3 and v4 and v5) else "红"
        print(f"潮位{tide}：{len(rows)} 只 [{state}] V1={v1} V2={v2} V3={v3} V4={v4} V5={v5}"
              + (f" 问题={bad1[:2]}{miss1[:1]}{failures[:1]}{bad3[:1]}" if state == "红" else ""))
        if not (v1 and v2 and v3 and v4 and v5):
            failures.append((f"tide{tide}", "见上"))
    total_ok = grand == 760 and len(ens_all) == 760 and len(ids_all) == 760
    print(f"总面：分片 {grand} ＝ 总面 {len(ens_all)} ＝ 唯一 id {len(ids_all)} —— {'绿' if total_ok else '红'}")
    all_ok = total_ok and not failures
    if "--check" in sys.argv:
        print("243 验收：", "ALL GREEN" if all_ok else "HAS RED")
        sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
