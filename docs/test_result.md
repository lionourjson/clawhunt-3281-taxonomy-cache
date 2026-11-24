# 测试记录

Windows 11、Python 3.12.14、PostgreSQL 16.10、Redis 7.0.15。按 README 设置测试数据库和 Redis 连接后，运行了全量 `python -m pytest -v --no-header`。

```text
============================= test session starts =============================
collecting ... collected 28 items

tests/test_cache_fallback.py::test_unreachable_redis_returns_database_data_and_throttles_warning PASSED [  3%]
tests/test_cache_fallback.py::test_disconnect_mid_command_and_automatic_recovery[GET] PASSED [  7%]
tests/test_cache_fallback.py::test_disconnect_mid_command_and_automatic_recovery[SET] PASSED [ 10%]
tests/test_cache_fallback.py::test_timeout_falls_back_without_attempting_cache_fill PASSED [ 14%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[\xff] PASSED [ 17%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[{] PASSED [ 21%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[{"data":{"nodes":{}},"version":1}] PASSED [ 25%]
tests/test_cache_fallback.py::test_corrupt_values_fall_back_without_overwriting[wrong_version] PASSED [ 28%]
tests/test_cache_fallback.py::test_invalid_utf8_with_redis_response_decoding PASSED [ 32%]
tests/test_cache_fallback.py::test_keys_defaults_empty_snapshots_cache_hits_and_configured_expiry PASSED [ 35%]
tests/test_cache_fallback.py::test_request_scope_and_soft_deleted_dictionary PASSED [ 39%]
tests/test_cache_fallback.py::test_config_bounds_and_bad_types[cache_ttl_seconds-2147483647] PASSED [ 42%]
tests/test_cache_fallback.py::test_config_bounds_and_bad_types[cache_timeout_ms-60000] PASSED [ 46%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[activate] PASSED [ 50%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[modify] PASSED [ 53%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[deactivate] PASSED [ 57%]
tests/test_cache_invalidation.py::test_four_writes_invalidate_both_keys[merge] PASSED [ 60%]
tests/test_cache_invalidation.py::test_external_write_hook_publishes_new_alias_snapshot PASSED [ 64%]
tests/test_cache_invalidation.py::test_chained_merge_and_disabled_target PASSED [ 67%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[self] PASSED [ 71%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[descendant] PASSED [ 75%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[missing] PASSED [ 78%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[soft_deleted] PASSED [ 82%]
tests/test_cache_invalidation.py::test_invalid_merge_leaves_version_and_cache[inactive] PASSED [ 85%]
tests/test_cache_invalidation.py::test_label_input_boundaries PASSED     [ 89%]
tests/test_cache_invalidation.py::test_transaction_failure_rolls_back_payload_and_version PASSED [ 92%]
tests/test_cache_invalidation.py::test_concurrent_writes_each_increment_and_dictionaries_are_independent PASSED [ 96%]
tests/test_cache_invalidation.py::test_inflight_miss_cannot_fill_old_key_with_new_rows PASSED [100%]

============================= 28 passed in 5.81s ==============================
```

## 已有字典的迁移

在另一个专用数据库运行 `python -m alembic upgrade 0001_standalone_schema`，以 `INSERT INTO dictionary(id,org_id,site_id,created_by) VALUES (...)` 插入一条虚构字典，再执行 `python -m alembic upgrade head`。以 `SELECT version FROM dictionary` 核对回填，运行 `python -m alembic check`，然后 `python -m alembic downgrade 0001_standalone_schema` 用 `SELECT count(*) FROM dictionary` 核对保留行数。再次升级后执行 `python -m alembic current`。

```text
INSERT 0 1
existing_dictionary_version=1
No new upgrade operations detected.
existing_dictionaries_after_downgrade=1
0002_dictionary_version (head)
```
