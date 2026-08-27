# 新手包 demo_lv15（M6 五档数据包 · 第 2 档）

依据：D4《细化_M6_内容包冒烟》§五（PCK-02/05，F-08）+【框架】§4.3 新手包 1-15 + §15 content/demo_lv15。

- 档位：新手 1-15（normal 怪 + 木桩）。
- 模块集【工程补白】= settings/stats/formula/effects/statuses/marks/items/equipment/action/enemies/maps
  （demo_blank 之上 + 效果家族完整 + 装备 + 怪物行动库 + 敌人 + 自洽地图两节点）。
- 内容基线 = tests/fixtures/packs/legal 数据子集（PCK-11）：
  enemies = rock_weasel（normal 新手怪）/ training_dummy（木桩）；action 子集 4 招；maps 自洽两节点
  （地图 exits 目标限定本档内，防 R-4 悬空引用）。
- 至少由本档起可模拟一局战斗（PCK-10：含合法怪）。
