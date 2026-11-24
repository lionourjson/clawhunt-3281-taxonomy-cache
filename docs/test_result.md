# 测试记录

在 Windows 11 的两个全新虚拟环境上运行。PostgreSQL 为 16.10，Redis 为 7.0.15。两个环境均执行 `python -m pip install -r requirements.txt` 与 `python -m pip check`，psycopg 及其二进制 wheel 均安装为 3.2.13，`pip check` 输出 `No broken requirements found.`。两份专用数据库均执行 `python -m alembic upgrade head`，`python -m alembic current` 输出 `0003_cache_generation (head)`，`python -m alembic check` 输出 `No new upgrade operations detected.`。

## 迁移与缓存回归

`test_migration_round_trip_uses_new_keys_with_same_numeric_version` 从 `0002_dictionary_version` 开始，插入存量字典并升级。它在 Redis 中保留两种带旧代次的键及两种首版无代次的键。测试降到 `0001_standalone_schema` 或 `0002_dictionary_version`、修改标签与别名，再升级到 head。两个分支都断言版本仍是 1、代次已更新、两个路由返回新值，并且新旧键在 Redis 中共存。一轮测试使用一个隔离的 PostgreSQL schema，结束时清理该 schema 和本测试的 Redis 键。

`test_dangling_tree_references_log_and_return_database_tree` 将引用缺失根节点或孙节点的 JSON 写入 Redis，断言 HTTP 200、返回完整 PostgreSQL 树且记录 `GET failed (invalid value)`。

## 全量输出

命令 `python -m pytest -v --no-header --tb=short`。

### Windows CPython 3.11.18

```text
============================= test session starts =============================
collecting ... collected 32 items

tests/test_cache_fallback.py::test_unreachable_redis_returns_database_data_and_throttles_warning PASSED [  3%]
tests/test_cache_fallback.py::test_disconnect_mid_command_and_automatic_recovery[GET] PASSED [  6%]
tests/test_cache_fallback.py::test_disconnect_mid_command_and_automatic_recovery[SET] PASSED [  9%]
tests/test_cache_fallback.py::test_timeout_falls_back_without_attempting_cache_fill PASSED [ 12%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[\xff] PASSED [ 15%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[{] PASSED [ 18%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[{"data":{"nodes":{}},"version":1}] PASSED [ 21%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[wrong_version] PASSED [ 25%]
tests/test_cache_fallback.py::test_dangling_tree_references_log_and_return_database_tree[root] PASSED [ 28%]
tests/test_cache_fallback.py::test_dangling_tree_references_log_and_return_database_tree[grandchild] PASSED [ 31%]
tests/test_cache_fallback.py::test_invalid_utf8_with_redis_response_decoding PASSED [ 34%]
tests/test_cache_fallback.py::test_keys_defaults_empty_snapshots_cache_hits_and_configured_expiry PASSED [ 37%]
tests/test_cache_fallback.py::test_request_scope_and_soft_deleted_dictionary PASSED [ 40%]
tests/test_cache_fallback.py::test_config_bounds_and_bad_types[cache_ttl_seconds-2147483647] PASSED [ 43%]
tests/test_cache_fallback.py::test_config_bounds_and_bad_types[cache_timeout_ms-60000] PASSED [ 46%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[activate] PASSED [ 50%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[modify] PASSED [ 53%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[deactivate] PASSED [ 56%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[merge] PASSED [ 59%]
tests/test_cache_invalidation.py::test_external_write_hook_publishes_new_alias_snapshot PASSED [ 62%]
tests/test_cache_invalidation.py::test_chained_merge_and_disabled_target PASSED [ 65%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[self] PASSED [ 68%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[descendant] PASSED [ 71%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[missing] PASSED [ 75%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[soft_deleted] PASSED [ 78%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[inactive] PASSED [ 81%]
tests/test_cache_invalidation.py::test_label_input_boundaries PASSED     [ 84%]
tests/test_cache_invalidation.py::test_transaction_failure_rolls_back_payload_and_version PASSED [ 87%]
tests/test_cache_invalidation.py::test_concurrent_writes_each_increment_and_dictionaries_are_independent PASSED [ 90%]
tests/test_cache_invalidation.py::test_inflight_miss_cannot_fill_old_key_with_new_rows PASSED [ 93%]
tests/test_cache_migration.py::test_migration_round_trip_uses_new_keys_with_same_numeric_version[0001_standalone_schema] PASSED [ 96%]
tests/test_cache_migration.py::test_migration_round_trip_uses_new_keys_with_same_numeric_version[0002_dictionary_version] PASSED [100%]

============================= 32 passed in 7.19s ==============================
```

### Windows CPython 3.14.3

```text
============================= test session starts =============================
collecting ... collected 32 items

tests/test_cache_fallback.py::test_unreachable_redis_returns_database_data_and_throttles_warning PASSED [  3%]
tests/test_cache_fallback.py::test_disconnect_mid_command_and_automatic_recovery[GET] PASSED [  6%]
tests/test_cache_fallback.py::test_disconnect_mid_command_and_automatic_recovery[SET] PASSED [  9%]
tests/test_cache_fallback.py::test_timeout_falls_back_without_attempting_cache_fill PASSED [ 12%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[\xff] PASSED [ 15%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[{] PASSED [ 18%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[{"data":{"nodes":{}},"version":1}] PASSED [ 21%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[wrong_version] PASSED [ 25%]
tests/test_cache_fallback.py::test_dangling_tree_references_log_and_return_database_tree[root] PASSED [ 28%]
tests/test_cache_fallback.py::test_dangling_tree_references_log_and_return_database_tree[grandchild] PASSED [ 31%]
tests/test_cache_fallback.py::test_invalid_utf8_with_redis_response_decoding PASSED [ 34%]
tests/test_cache_fallback.py::test_keys_defaults_empty_snapshots_cache_hits_and_configured_expiry PASSED [ 37%]
tests/test_cache_fallback.py::test_request_scope_and_soft_deleted_dictionary PASSED [ 40%]
tests/test_cache_fallback.py::test_config_bounds_and_bad_types[cache_ttl_seconds-2147483647] PASSED [ 43%]
tests/test_cache_fallback.py::test_config_bounds_and_bad_types[cache_timeout_ms-60000] PASSED [ 46%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[activate] PASSED [ 50%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[modify] PASSED [ 53%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[deactivate] PASSED [ 56%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[merge] PASSED [ 59%]
tests/test_cache_invalidation.py::test_external_write_hook_publishes_new_alias_snapshot PASSED [ 62%]
tests/test_cache_invalidation.py::test_chained_merge_and_disabled_target PASSED [ 65%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[self] PASSED [ 68%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[descendant] PASSED [ 71%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[missing] PASSED [ 75%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[soft_deleted] PASSED [ 78%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[inactive] PASSED [ 81%]
tests/test_cache_invalidation.py::test_label_input_boundaries PASSED     [ 84%]
tests/test_cache_invalidation.py::test_transaction_failure_rolls_back_payload_and_version PASSED [ 87%]
tests/test_cache_invalidation.py::test_concurrent_writes_each_increment_and_dictionaries_are_independent PASSED [ 90%]
tests/test_cache_invalidation.py::test_inflight_miss_cannot_fill_old_key_with_new_rows PASSED [ 93%]
tests/test_cache_migration.py::test_migration_round_trip_uses_new_keys_with_same_numeric_version[0001_standalone_schema] PASSED [ 96%]
tests/test_cache_migration.py::test_migration_round_trip_uses_new_keys_with_same_numeric_version[0002_dictionary_version] PASSED [100%]

============================= 32 passed in 6.99s ==============================
```
