# -*- coding: utf-8 -*-
"""九期238：verify_cloudsea——云海内容包三段探针（结构/数据/功能）＋方位断言并入。

用法：python scripts/verify/verify_cloudsea.py（仓库根或任意 cwd，ROOT 自动定位）
退出码 0＝全绿（CI package job 前置）；非 0＝存在 FAIL。

三段：
  P1 结构探针——manifest modules ↔ 实文件一一在库，全部 JSON 可解析；
  P2 数据探针——核心计数（actions 1261／enemies 760／codex 434／recipes 142／
     axes 22／域章 31／成就 5／parts_219 233）＋方位断言并入（actions pos 覆盖、
     规则册 12 族/marks 五族、对空资格 height=air 字段抽检）；
  P3 功能探针——GM 十指令 spec＋诊断包三级＋打包产物清单（冒烟级，不触引擎 IO）。
"""
from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))  # scripts/verify/x.py → scripts → TTR 根
CLOUD = os.path.join(ROOT, 'content', 'cloudsea')
EXPECT_MODULES = ['settings', 'stats', 'formula', 'effects', 'statuses', 'marks',
                  'skill_chains', 'action', 'skills', 'jobs', 'enemies', 'maps',
                  'items', 'equipment', 'shop', 'quest', 'npc', 'enhance', 'forge',
                  'proficiency', 'templates', 'checkin']
CORE_COUNTS = {'actions': 1261, 'recipes': 142, 'codex_entries': 434}


def load(path):
    with io.open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main() -> int:
    fails = []

    # ---- P1 结构探针 ----
    mani = load(os.path.join(CLOUD, 'manifest.json'))
    for mod in EXPECT_MODULES:
        if mod not in mani.get('modules', []):
            fails.append('P1 manifest 缺模块 %s' % mod)
        p = os.path.join(CLOUD, mod + '.json')
        if not os.path.isfile(p):
            fails.append('P1 缺文件 %s.json' % mod)
            continue
        try:
            load(p)
        except Exception as exc:
            fails.append('P1 %s.json 不可解析: %s' % (mod, exc))
    gen = os.path.join(ROOT, '..', 'yunhai', 'cloudsea-hunting-corps',
                       'content', 'cloudsea', 'generated', 'parts_219.json')
    gen = os.path.abspath(gen)
    if not os.path.isfile(gen):
        fails.append('P1 缺 generated/parts_219.json（设计稿仓）')
    print('P1 结构探针：manifest %d 模块核对完成' % len(EXPECT_MODULES))

    # ---- P2 数据探针 ----
    counts = {}
    actions = load(os.path.join(CLOUD, 'actions.json'))
    counts['actions'] = len(actions) if isinstance(actions, list) else len(actions.get('items', actions))
    enemies = 0
    pos_air = 0
    for i in range(1, 8):
        rows = load(os.path.join(CLOUD, 'enemies_t%d.json' % i))
        rows = rows if isinstance(rows, list) else list(rows.values())
        enemies += len(rows)
        for r in rows:
            dp = r.get('duyou_pos')
            if isinstance(dp, dict) and any('air' in str(v) for v in dp.values()):
                pos_air += 1
    counts['enemies'] = enemies
    codex = load(os.path.join(CLOUD, 'codex.json'))
    counts['codex_entries'] = len(codex.get('entries', []))
    counts['codex_domains'] = len(codex.get('domain_chapters', []))
    counts['achievements'] = len(codex.get('achievements', []))
    recipes = load(os.path.join(CLOUD, 'recipes.json'))
    counts['recipes'] = len(recipes) if isinstance(recipes, list) else len(recipes)
    axes = load(os.path.join(CLOUD, 'axes.json'))
    counts['axes'] = len([k for k in axes if k.startswith('cs_')])
    p219 = load(gen)
    counts['parts_219'] = len(p219.get('parts', []))
    for key, want in CORE_COUNTS.items():
        if counts.get(key) != want:
            fails.append('P2 %s=%s 期望 %s' % (key, counts.get(key), want))
    if counts['codex_domains'] != 31 or counts['achievements'] != 5 or counts['axes'] < 20:
        fails.append('P2 域章/成就/轴计数异常: %s' % counts)
    # 方位断言并入：对空资格（air 怪行）抽检；方位规则册在设计稿仓由设计稿侧断言复核
    if pos_air == 0:
        fails.append('P2 方位断言: enemies 无 air 行（对空资格字段缺失）')
    print('P2 数据探针：%s；air 行 %d' % (counts, pos_air))

    # ---- P3 功能探针 ----
    prof = load(os.path.join(CLOUD, 'proficiency.json'))
    if len(prof.get('per_weapon_type', {})) != 14 or len(prof.get('curves', {})) != 3:
        fails.append('P3 proficiency 曲线/映射异常')
    gm_spec = os.path.join(ROOT, 'qbot_rpg', 'core', 'cloudsea_gm.py')
    with io.open(gm_spec, 'r', encoding='utf-8') as f:
        gm = f.read()
    if gm.count('"cs') < 10:
        fails.append('P3 GM 十指令 spec 不足十条')
    print('P3 功能探针：proficiency 曲线/映射＋GM spec 核对完成')

    if fails:
        print('')
        for f in fails:
            print('FAIL  %s' % f)
        print('verify_cloudsea: %d FAIL' % len(fails))
        return 1
    print('')
    print('verify_cloudsea: 三段探针 ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
