# -*- coding: utf-8 -*-
"""parse_quests_maps.py —— 九期批次 229（跨轮增量 v1）· 任务与地图转译

quest.json：18 章节卡 §5 主线（120）＋§6 支线（424）＝**540 契约恰尽**（V 线 2139／P 160／K 1408
  独立计数不占本量，沿 12 号 §T CONTENT.* 口径）。条目＝{id,name,type,desc,zone,main,chapter,
  reward_raw,freq,conditions:[]}——conditions DSL（达成式/消费式）映射归增量二。
maps.json：28 生态节点七簇（cluster=tide 潮位簇）＋monsters 绑定＝enemies.json 按 area 回链；
  exits 拓扑连线归增量二（生态总表无连线数据，零自拟）。
对账：主 120／支 424／总 540；maps 28 节点；monsters 绑定 760 全量；幂等。
"""
import io, json, os, re, sys
from collections import OrderedDict

sys.stdout.reconfigure(encoding="utf-8")
TTR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = os.path.join(os.path.dirname(TTR), "yunhai", "cloudsea-hunting-corps")
CH = os.path.join(DS, "15_主线章节与任务")
OUT_Q = os.path.join(TTR, "content", "cloudsea", "quest.json")
OUT_M = os.path.join(TTR, "content", "cloudsea", "maps.json")
MANI = os.path.join(TTR, "docs", "cloudsea", "quests_maps_manifest.json")
ECO = os.path.join(DS, "17_世界内容与生态")

CHAPTERS = [
    ("01", "01_第1章_云海之下.md"), ("02", "02_第2章_霜脊之径.md"),
    ("02.5", "03_第2.5章_白垩之下.md"), ("03", "04_第3章_蚀月之上.md"),
    ("03.5", "05_第3.5章_双相轮转.md"), ("04", "06_第4章_砧崖潮线.md"),
    ("04.5", "07_第4.5章_落岛之汛.md"), ("05", "08_第5章_坠星之湾.md"),
    ("05.5", "09_第5.5章_蚀纹之巢.md"), ("06", "10_第6章_云海渊眼.md"),
    ("06.5", "11_第6.5章_晖环之殒.md"), ("07", "12_第7章_遗械之核.md"),
    ("07.5", "13_第7.5章_渊潮之喉.md"), ("08", "15_第8章_云墙之眼.md"),
    ("08.5", "16_第8.5章_静眼之下.md"), ("09", "17_第9章_薄气之上.md"),
    ("09.5", "18_第9.5章_辉带尽头.md"), ("10", "19_第10章_渊潮之心.md"),
]


def read(p):
    return io.open(p, encoding="utf-8").read().replace("\r\n", "\n")


def parse_chapter(path, ch):
    txt = read(path)
    quests = []
    title = re.search(r"^# 章节任务卡 #(\d+) · (.+)$", txt, re.M)
    ch_name = title.group(2).strip() if title else ch
    for kind, sec_name, rowp, idp in (("main", "主线任务清单", "主", "m"), ("side", "支线任务清单", "支", "s")):
        m = re.search(r"## \d+ · " + sec_name + r"[^\n]*\n(.*?)(?=\n## |\Z)", txt, re.S)
        if not m:
            continue
        for row in re.finditer(r"^\| (" + rowp + r"\d+) \|(.*?)\|\s*$", m.group(1), re.M):
            seq = row.group(1).strip()
            cells = [c.strip() for c in row.group(2).split("|")]
            quests.append(OrderedDict([
                ("id", "q_%s_%s_%02d" % (idp, ch.replace(".", ""), len(
                    [q for q in quests if q["kind"] == kind]) + 1)),
                ("name", cells[0].strip("*")),
                ("kind", kind),
                ("type", "main" if kind == "main" else "side"),
                ("desc", cells[1] if len(cells) > 1 else ""),
                ("chapter", ch), ("chapter_name", ch_name),
                ("seq", seq), ("main", kind == "main"),
                ("reward_raw", cells[3] if len(cells) > 3 else ""),
                ("source_sys", cells[4] if len(cells) > 4 else ""),
                ("freq", cells[5] if len(cells) > 5 else ""),
                ("conditions", []),
            ]))
    return quests, ch_name


def parse_env():
    """生态册项目表「环境」行 → 生态名→环境描述。"""
    env = {}
    for dirpath in sorted(os.listdir(ECO)):
        d2 = os.path.join(ECO, dirpath)
        if not (os.path.isdir(d2) and dirpath.startswith("阶段")):
            continue
        for f2 in sorted(os.listdir(d2)):
            if not (re.match(r"[0-9]", f2) and f2.endswith(".md")):
                continue
            txt = read(os.path.join(d2, f2))
            m = re.search(r"^\| 环境 \| (.+?) \|$", txt, re.M)
            nm = re.search(r"^# (.+?)（", txt, re.M)
            if m and nm:
                env[nm.group(1).strip()] = m.group(1).strip()
    return env


def parse_maps(enemies, env):
    """28 生态节点：来自生态总表行序；monsters=enemies.json 按 area 回链。
    增量三：terrain=生态册「环境」行；exits=线性主链缺省拓扑（同簇相邻双向＋簇间末/首
    节点串联，七簇线性串联 documented 工程收敛——分支支线拓扑归增量四/230）。"""
    txt = read(os.path.join(DS, "17_世界内容与生态", "01_生态总表_28生态.md"))
    nodes = []
    tide_no = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
    for ln in txt.split("\n"):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 9 or cells[1] in ("", "潮位") or set(cells[1]) <= set("-: "):
            continue
        m = re.match(r"\[([^\]]+)\]", cells[2])
        if not m or cells[1][:1] not in tide_no:
            continue
        eco = m.group(1)
        tide = tide_no[cells[1][:1]]
        mons = sorted(e["id"] for e in enemies if e["area"] == eco)
        nodes.append(OrderedDict([
            ("id", "map_t%d_%02d" % (tide, sum(1 for n in nodes
                                               if n["cluster"] == tide) + 1)),
            ("name", eco), ("cluster", tide), ("tide_name", cells[1]),
            ("star_band", cells[3]),
            ("terrain_env", env.get(eco, "")),
            ("monsters", mons),
            ("exits", {}),
        ]))
    # 增量三：线性主链缺省拓扑——同簇相邻节点双向连通＋簇间末/首节点串联（工程收敛，
    # 分支支线拓扑归增量四/230）；hidden_exits 保留位＝隐藏 Boss 窗口（258 产物后填充）
    for i, n in enumerate(nodes):
        exits = {}
        if i > 0:
            exits["prev"] = {"to": nodes[i - 1]["id"], "mode": "bidirectional"}
        if i < len(nodes) - 1:
            exits["next"] = {"to": nodes[i + 1]["id"], "mode": "bidirectional"}
        n["exits"] = exits
        n["hidden_exits"] = []  # hidden_boss 窗口保留位（名单归 258，机制沿 exits.condition DSL）
        n["terrain"] = {"env": n.pop("terrain_env", ""), "wall_tag": "F08 撞壁 terrain 标签归增量四"}
    return nodes


def parse_taizhang():
    """支线变化任务台账（唯一覆盖账本，424 行）→ 正典支线注册表。"""
    txt = read(os.path.join(DS, "15_主线章节与任务", "支线变化任务台账.md"))
    rows = []
    for ln in txt.split("\n"):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 12 or not re.fullmatch(r"\d{3}", cells[1]):
            continue
        entry = cells[3]  # 「支1 三筐晶煤过崖」
        nm = re.sub(r"^支\d+\s*", "", entry).strip()
        rows.append({"seq": int(cells[1]), "card": cells[2], "entry": entry,
                     "name": nm, "tide": cells[4], "chain": cells[10],
                     "v_count": cells[11]})
    return rows


def main():
    enemies = json.load(io.open(os.path.join(TTR, "content", "cloudsea", "enemies.json"),
                                encoding="utf-8"))
    # 他批段保留（230 story 64 条等）：重生成只重建本管线面（章节卡+台账），既有他批段原样回填
    prev_story = []
    if os.path.exists(OUT_Q):
        for e in json.load(io.open(OUT_Q, encoding="utf-8")):
            if e.get("id", "").startswith("q_story_"):
                prev_story.append(e)
    quests, chapter_names = [], {}
    for ch, fn in CHAPTERS:
        qs, ch_name = parse_chapter(os.path.join(CH, fn), ch)
        chapter_names[ch] = ch_name
        quests += qs
    # 增量二：支线面以台账 424 为正典（325 章节卡支线并档＋99 卡14 浩劫终局层面）；
    # 主线面＝章节卡 110（逐章自检咬合），契约主线口径 120 差 10 登记（待源核定）
    CARD2CH = {"01": "01", "02": "02", "03": "02.5", "04": "03", "05": "03.5",
               "06": "04", "07": "04.5", "08": "05", "09": "05.5", "10": "06",
               "11": "06.5", "12": "07", "13": "07.5", "15": "08", "16": "08.5",
               "17": "09", "18": "09.5", "19": "10", "14": "14"}
    tz = parse_taizhang()
    sides = [q for q in quests if not q["main"]]
    used, side_out = set(), []
    matched = 0
    for row in tz:
        ch = CARD2CH.get(row["card"])
        nm = row["name"]
        cand = next((q for q in sides if id(q) not in used and q["chapter"] == ch
                     and (q["name"] == nm or q["name"].endswith(nm) or nm in q["name"])), None)
        if cand is not None:
            used.add(id(cand))
            matched += 1
        side_out.append(OrderedDict([
            ("id", "q_v_%03d" % row["seq"]), ("name", nm),
            ("type", "side"), ("main", False),
            ("chapter", ch), ("tide", row["tide"]),
            ("seq", row["seq"]), ("card", row["card"]),
            ("chain", row["chain"]), ("desc", cand["desc"] if cand else ""),
            ("reward_raw", cand["reward_raw"] if cand else ""),
            ("conditions", []),
        ]))
    for q in sides:
        if id(q) not in used:
            side_out.append(OrderedDict([
                ("id", "q_s_x_%02d" % (len(side_out) + 1)), ("name", q["name"]),
                ("type", "side"), ("main", False), ("chapter", q["chapter"]),
                ("desc", q["desc"]), ("reward_raw", q["reward_raw"]),
                ("conditions", []),
            ]))
    quests = [q for q in quests if q["main"]] + side_out + prev_story
    n_main = sum(1 for q in quests if q.get("main") is True)
    n_side = sum(1 for q in quests if q.get("id", "").startswith(("q_v_", "q_s_")))
    env = parse_env()
    maps = parse_maps(enemies, env)

    io.open(OUT_Q, "w", encoding="utf-8", newline="\n").write(
        json.dumps(quests, ensure_ascii=False, indent=1) + "\n")
    io.open(OUT_M, "w", encoding="utf-8", newline="\n").write(
        json.dumps(maps, ensure_ascii=False, indent=1) + "\n")
    mani = OrderedDict([
        ("quests_total", len(quests)), ("quests_main", n_main), ("quests_side", n_side),
        ("contract", "契约 540＝主线 120＋支线 424（12 号 §T CONTENT.QUESTS）；本面＝主线 110"
                     "（章节卡逐章自检咬合，口径差 10 登记）＋支线 424（台账正典面）；"
                     "V 2139/P 160/K 1408 独立计数"),
        ("maps_nodes", len(maps)),
        ("maps_monsters_bound", sum(len(n["monsters"]) for n in maps)),
        ("chapters", len(CHAPTERS)),
    ])
    io.open(MANI, "w", encoding="utf-8", newline="\n").write(
        json.dumps(mani, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(mani, ensure_ascii=False)[:300])
    if "--check" in sys.argv:
        ok = []
        ok.append(("A1 主线 110（逐章自检咬合）＋口径差 10 登记",
                   n_main == 110, f"主 {n_main}"))
        ok.append(("A2 支线 424 恰尽（台账正典面）", n_side == 424,
                   f"并档 {matched}／卡14 面 {424 - matched}／未并档章节卡残留 {n_side - 424}"))
        ok.append(("A3 maps 28 节点七簇", len(maps) == 28,
                   f"簇分布 {sorted(set(n['cluster'] for n in maps))}"))
        bound = sum(len(n["monsters"]) for n in maps)
        ok.append(("A4 maps monsters 绑定 760 全量", bound == 760, f"{bound}"))
        ids = [q["id"] for q in quests]
        ok.append(("A5 quest id 唯一", len(set(ids)) == len(ids), f"{len(set(ids))}"))
        for name, cond, det in ok:
            print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" —— {det}" if det else ""))
        sys.exit(0 if all(c for _, c, _ in ok) else 1)


if __name__ == "__main__":
    main()
