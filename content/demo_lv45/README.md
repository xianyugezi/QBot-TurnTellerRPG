# 进阶包 demo_lv45（M6 五档数据包 · 第 4 档）

依据：D4《细化_M6_内容包冒烟》§五（PCK-02/05，F-08）+【框架】§4.3 进阶包 1-45 + §15 content/demo_lv45。

- 档位：进阶 1-45（+ M4 交互系统 npc/shop/quest/checkin）。
- 模块集【工程补白】= demo_lv30 之上 + npc/shop/quest/checkin（M4 四模块，m4_shared_contract §2.3/§3.1~3.4）；
  内容 = NPC 3 只（blacksmith_zhou/quest_giver_ling/traveling_dealer，省略 elder_mo）/ 商店 village_shop /
  quest q_potion_supply / checkin 2 表（loop/monthly）。
- 内容基线 = tests/fixtures/packs/legal 数据子集（PCK-11）；跨模块引用闭环：npc→shop/maps/quest、
  quest→items/maps/npc、shop→items、checkin→items 全部可 resolve。
