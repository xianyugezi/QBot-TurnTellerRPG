# 完整包 demo_full（M6 五档数据包 · 第 5 档）

依据：D4《细化_M6_内容包冒烟》§五（PCK-02/05，F-08）+【框架】§4.3 完整包 + §15 content/demo_full。

- 档位：完整包（legal 全量镜像 + settings，16 模块全量内容）。
- 模块集【工程补白】= demo_lv45 之上 + boss 烬火龙 ember_drake + 灭世龙息 doomsday_breath +
  讨伐副本 molten_dungeon_boss（boss 版，boss_room/boss 必填且引用存在）+ 全 NPC 4 只 + 全商店 2 家 +
  全 checkin 3 表 + 隐藏通道（hidden exit 带 condition）。
- 内容基线 = tests/fixtures/packs/legal 全量镜像（PCK-11）+ settings；legal 全模块文件逐字复制，
  仅按本档地图集裁剪 maps.exits（exits 目标限定档内地图，防 R-4 悬空引用）。
