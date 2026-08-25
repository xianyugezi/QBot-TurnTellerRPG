"""全局世界状态：地图/怪物池/野图 BOSS/全体限购/刷新补刷 + 会话互斥 + 战斗世界边界

（细化_3a §2.1）。零 NoneBot import。

模块：
  - game_world.py     全局世界 GameWorld（M3 实装，本里程碑仅签名）
  - session.py        会话互斥 SessionManager（M1/M4 实装）
  - spawn.py          刷怪/补刷 Spawner（M3 实装）
  - battle_boundary.py 战斗世界边界逻辑层（M2 C2 路：细化_1g4 怪物丢失/脱战回血/
    死亡惩罚/跨群竞争/战斗时间线 —— 纯函数 + 数据结构 + 接口预留）
"""
