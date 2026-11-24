# 本地缓存命中率压测记录

## 运行与口径

命令 `python -m bench.hit_rate`。PostgreSQL 与 Redis 为本地专用实例。脚本在同一进程内经 ASGI 调用 FastAPI 路由，通过真实连接访问 PostgreSQL 与 Redis。每轮送出全部字典的标签树和别名映射请求。首轮从空缓存开始，后续周期先逐个字典提交一次标签修改，再进入读取轮次。

命中率为 Redis `INFO stats` 的 `keyspace_hits` 增量除以 `keyspace_hits + keyspace_misses` 增量。脚本校验计数合计等于完成的 HTTP 读取数。吞吐量按包含写入的整段窗口计算。p50 与 p95 按单个读取请求持续时间的最近秩计算，数值包含应用、数据库连接池和 Redis 往返时间。样例结果用于本地复跑参考。

## 原始输出

```text
OS=Windows 11 Python=3.12.14
PostgreSQL=16.10 Redis=7.0.15
dictionaries=12 tags_per_dictionary=48 cycles=3 rounds_per_cycle=20
concurrent_reads_per_round=24 writes=24 http_2xx=1440
redis_hits=1368 redis_misses=72 hit_rate=95.00%
elapsed_seconds=14.897 reads_per_second=96.66 p50_ms=192.98 p95_ms=266.59
```
