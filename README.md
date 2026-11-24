# 字典与标签的 Redis 缓存

FastAPI 提供字典标签树和别名映射的读取接口。PostgreSQL 保存字典版本、标签和别名，Redis 按版本缓存读取结果。

## 本地运行

准备 Python 3.11+、PostgreSQL 16 和 Redis 7。验收使用专用数据库和 Redis 实例。以下示例使用 Bash，替换主机、端口和专用数据库连接信息。

```bash
python -m venv .venv
source .venv/bin/activate   # Windows Git Bash 使用 source .venv/Scripts/activate
python -m pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg://taxonomy@127.0.0.1:5432/taxonomy'
export REDIS_URL='redis://127.0.0.1:6379/0'
python -m alembic upgrade head
python -m alembic check
python -m pytest -v --no-header
python -m bench.hit_rate
```

安装 PostgreSQL 的本地驱动和服务后，请先创建 `taxonomy` 数据库及可执行迁移的角色。`DATABASE_URL` 接受 PostgreSQL 的 `postgresql+psycopg` SQLAlchemy URL。`REDIS_URL` 接受 `redis://` 和 `rediss://`。接入时由 S2-INFRA 注入这些环境变量。

运行 `TAXONOMY_DEMO_MODE=true python -m app` 可启动本地接口，监听 `127.0.0.1:8000`。测试和压测自行创建并清理虚构字典。手工调用前可在本地创建样例字典及标签，或使用现有集成环境的字典。

| GET 路径 | 返回 |
| --- | --- |
| `/taxonomy/dictionaries/{dictionary_id}/tree` | `roots` 是根节点 UUID 数组。`nodes` 以 UUID 为键，包含 `code`、`label`、`status` 和有序 `children` UUID 数组。 |
| `/taxonomy/dictionaries/{dictionary_id}/aliases` | `aliases` 将字符串映射到当前生效的标签 UUID。 |

停用标签在树中保留 `inactive` 状态。合并标签退出树，别名沿合并链解析到有效目标。找不到有效目标的别名从映射移除。树与别名快照都排除软删除记录。标签按 `code` 排序，演示数据中重复别名按排序后的首个有效来源解析。正式系统将别名唯一性、树结构和合并规则交给标签域。

## 缓存键与过期时间

| 数据 | 键 |
| --- | --- |
| 标签树 | `taxonomy:{org_id}:{dict_id}:v{version}:tree` |
| 别名映射 | `taxonomy:{org_id}:{dict_id}:v{version}:alias` |

`dict_id` 使用全局唯一的 UUID。命中前从 PostgreSQL 按调用者的 `org_id`、`site_id` 检查字典和版本。版本从 `1` 开始；键内的数据封装含字典 UUID、版本和结构化快照。写入时设置 TTL，命中时保留原过期时间。旧键保留原 TTL 自然过期。

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `DATABASE_URL` | 必填 | PostgreSQL 连接 |
| `REDIS_URL` | 必填 | Redis 连接 |
| `TAXONOMY_CACHE_TTL_SECONDS` | `86400`（24 小时） | 每个新键的 TTL，范围 `1–2147483647` 秒 |
| `TAXONOMY_CACHE_TIMEOUT_MS` | `200` | 每次 Redis GET 或 SET 的等待上限，范围 `1–60000` 毫秒 |
| `TAXONOMY_DEMO_MODE` | `false` | 本地演示时从 `X-Org-ID`、`X-Site-ID` 取作用域 |

Redis GET 因连接、超时或无效内容失败时，响应使用当前事务的 PostgreSQL 数据。正常未命中时写入缓存。Redis SET 失败时仍返回已查询的数据。每个应用实例对同一原因每分钟最多记录一条 WARNING。在后续请求中自动尝试 Redis，因此连接恢复后自动恢复缓存使用。数据库故障由 API 宿主的常规错误处理接管。

## 失效与集成

写入方在 PostgreSQL 默认 `READ COMMITTED` 事务中先调用 `lock_dictionary(conn, scope, dict_id)`，再执行已有的标签业务写入，然后在同一连接和事务中调用 `bump_version(conn, scope, dict_id)` 一次。生效、修改、停用与合并都使用这一顺序，影响读投影的其他写入也应使用同样的钩子。一次逻辑写入由调用者负责业务幂等。并发写按字典行锁串行处理，失败事务同时回滚标签与版本。`TaxonomyService.change` 提供真实数据库上的本地接入样例。

读请求使用 PostgreSQL `REPEATABLE READ`，确保缓存未命中时版本和标签行来自同一快照。读请求跨越并发提交时仍按它读取到的版本处理。提交后开始的新请求读取新版本。数据库读取使用主库，避免复制延迟改变上述保证。

本地迁移 `0001_standalone_schema` 提供独立的字典与标签表，`0002_dictionary_version` 添加计数列并将存量记录初始化为 `1`。正式接入时将第二个迁移接到项目已有的字典表迁移链，并将仓库中的模型映射到正式表。由认证中间件将经过验证的 `Scope` 写入 `request.state.taxonomy_scope`，默认配置下缺少该作用域时返回 403。S2-INFRA 提供连接配置、Redis 实例、日志采集和 CI 依赖服务。日志以 `app.taxonomy.cache` 为记录器，便于采集告警。

## 验证材料

- [全量 pytest 原始记录](docs/test_result.md)
- [本地缓存命中率压测记录与口径](docs/bench_result.md)
