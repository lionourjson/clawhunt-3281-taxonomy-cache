# 字典与标签的 Redis 缓存

FastAPI 提供字典标签树和别名映射的读取接口。PostgreSQL 保存字典版本、标签和别名，Redis 按版本缓存读取结果。

## 本地运行

准备 Python 3.11+、PostgreSQL 16 和 Redis 7。依赖安装与全量集成测试已经在 Windows CPython 3.11.18 和 3.14.3 上验证。以下示例使用 Bash，请提供专用数据库和 Redis 实例的连接信息。

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

安装 PostgreSQL 服务后，请先创建 `taxonomy` 数据库及可执行迁移、创建测试专用 schema 的角色。`DATABASE_URL` 接受 PostgreSQL 的 `postgresql+psycopg` SQLAlchemy URL。`REDIS_URL` 接受 `redis://` 和 `rediss://`。接入时由 S2-INFRA 注入这些环境变量。

运行 `TAXONOMY_DEMO_MODE=true python -m app` 可启动本地接口，监听 `127.0.0.1:8000`。测试和压测自行创建并清理虚构字典。手工调用前可在本地创建样例字典及标签，或使用现有集成环境的字典。

| GET 路径 | 返回 |
| --- | --- |
| `/taxonomy/dictionaries/{dictionary_id}/tree` | `roots` 是根节点 UUID 数组。`nodes` 以 UUID 为键，包含 `code`、`label`、`status` 和有序 `children` UUID 数组。 |
| `/taxonomy/dictionaries/{dictionary_id}/aliases` | `aliases` 将字符串映射到当前生效的标签 UUID。 |

停用标签在树中保留 `inactive` 状态。合并标签退出树，别名沿合并链解析到有效目标。找不到有效目标的别名从映射移除。树与别名快照都排除软删除记录。标签按 `code` 排序，演示数据中重复别名按排序后的首个有效来源解析。正式系统将别名唯一性、树结构和合并规则交给标签域。

## 缓存键与过期时间

| 数据 | 键 |
| --- | --- |
| 标签树 | `taxonomy:{org_id}:{dict_id}:g{generation}:v{version}:tree` |
| 别名映射 | `taxonomy:{org_id}:{dict_id}:g{generation}:v{version}:alias` |

`dict_id` 是全局唯一的 UUID，`generation` 是 PostgreSQL 为该字典分配的缓存代次 UUID。命中前按调用者的 `org_id`、`site_id` 从 PostgreSQL 读取代次及版本，版本从 `1` 开始。缓存值封装含字典 UUID、版本和结构化快照。写入时设置 TTL，命中时保留原过期时间。旧代次或旧版本的键按原 TTL 自然过期。

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `DATABASE_URL` | 必填 | PostgreSQL 连接 |
| `REDIS_URL` | 必填 | Redis 连接 |
| `TAXONOMY_CACHE_TTL_SECONDS` | `86400`（24 小时） | 每个新键的 TTL，范围 `1–2147483647` 秒 |
| `TAXONOMY_CACHE_TIMEOUT_MS` | `200` | 每次 Redis GET 或 SET 的等待上限，范围 `1–60000` 毫秒 |
| `TAXONOMY_DEMO_MODE` | `false` | 本地演示时从 `X-Org-ID`、`X-Site-ID` 取作用域 |

Redis GET 因连接、超时或无效内容失败时，响应使用当前事务的 PostgreSQL 数据。树快照的根和每层子节点都必须存在于 `nodes` 中，悬空引用按无效内容处理。正常未命中时写入缓存。Redis SET 失败时仍返回已查询的数据。每个应用实例对同一原因每分钟最多记录一条 WARNING。在后续请求中自动尝试 Redis，因此连接恢复后自动恢复缓存使用。数据库故障由 API 宿主的常规错误处理接管。

## 失效与集成

写入方在 PostgreSQL 默认 `READ COMMITTED` 事务中先调用 `lock_dictionary(conn, scope, dict_id)`，再执行已有的标签业务写入，然后在同一连接和事务中调用 `bump_version(conn, scope, dict_id)` 一次。生效、修改、停用与合并都使用这一顺序，影响读投影的其他写入也应使用同样的钩子。一次逻辑写入由调用者负责业务幂等。并发写按字典行锁串行处理，失败事务同时回滚标签与版本。`TaxonomyService.change` 提供真实数据库上的本地接入样例。

读请求使用 PostgreSQL `REPEATABLE READ`，确保缓存未命中时版本和标签行来自同一快照。读请求跨越并发提交时仍按它读取到的版本处理。提交后开始的新请求读取新版本。数据库读取使用主库，避免复制延迟改变上述保证。

本地迁移 `0001_standalone_schema` 提供独立字典与标签表。`0002_dictionary_version` 添加计数列并将存量记录初始化为 `1`。`0003_cache_generation` 为存量字典和以后新建的字典生成代次。正式接入时将后两个迁移接入已有字典表的迁移链，并映射到正式表。

### 迁移往返

停用使用当前表结构的应用进程，执行 `python -m alembic downgrade 0002_dictionary_version` 回退代次列，或执行 `python -m alembic downgrade 0001_standalone_schema` 同时回退数字版本列。需要在 `0002` 运行旧版应用时，为旧版设置指向独立空 Redis 实例或逻辑库的 `REDIS_URL`。执行 `python -m alembic upgrade head` 再启动当前应用。重新添加代次列时 PostgreSQL 为每条存量字典重新生成 UUID，即使数字版本回到 `1`，新请求也只按新代次读写。当前应用可继续使用原 Redis，旧键保留原 TTL。往返回归在独立 schema 中改动标签与别名，验证升级后两个接口均返回新值。

由认证中间件将经过验证的 `Scope` 写入 `request.state.taxonomy_scope`，默认配置下缺少该作用域时返回 403。S2-INFRA 提供连接配置、Redis 实例、日志采集和 CI 依赖服务。日志以 `app.taxonomy.cache` 为记录器，便于采集告警。

## 验证材料

- [全量 pytest 原始记录](docs/test_result.md)
- [本地缓存命中率压测记录与口径](docs/bench_result.md)
