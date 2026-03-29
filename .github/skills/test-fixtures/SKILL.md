---
name: test-fixtures
description: >
  Domain knowledge for the agentic-text2sql test suite. Use when writing or fixing
  pytest tests, working with conftest.py, the seeded_conn or engine fixtures, in-memory
  SQLite, StaticPool, ATTACH DATABASE, pytest-asyncio, or any file under tests/.
  Trigger phrases: pytest, conftest, seeded_conn, engine fixture, StaticPool,
  in-memory SQLite, ATTACH, test_fts, test_retrieval, test_dbml_gen, async test.
argument-hint: "Test file or fixture to work on (e.g. 'test_fts.py', 'async test')"
---

# Test Fixtures

## Key Constraint: One Connection Rule

SQLite in-memory databases created via `ATTACH DATABASE ':memory:'` live **only as long as
the connection that ATTACHed them**. Breaking this causes `no such table` errors.

**Always use `seeded_conn` (not `engine`) inside tests that query the meta-schema.**  
Never call `engine.connect()` or `engine.begin()` inside a test — use the yielded connection.

---

## Fixtures (`tests/conftest.py`)

### `engine` fixture

```python
@pytest.fixture(scope="function")
def engine() -> Engine:
    """Fresh in-memory SQLite engine per test (StaticPool)."""
    return make_engine("sqlite:///:memory:")
```

- `StaticPool` ensures all `engine.connect()` calls share the **same underlying DBAPI connection**
- ATTACHed `:memory:` databases persist for the engine's lifetime
- Scope is `function` — fresh DB per test, no state leakage

### `seeded_conn` fixture

```python
@pytest.fixture(scope="function")
def seeded_conn(engine):
    with engine.begin() as conn:
        seed_meta(conn)
        build_fts_index(conn)
    with engine.connect() as conn:
        yield conn
```

- Runs `seed_meta` + `build_fts_index` in one transaction, then opens a read connection
- The re-opened `engine.connect()` works because `StaticPool` returns the same underlying connection
- **Always inject `seeded_conn` in tests that call `search_tables`, `search_columns`, `generate_dbml`**

---

## Writing Tests

### Sync tests (most tests)
```python
def test_something(seeded_conn):
    results = search_tables(seeded_conn, "order revenue", top_k=5)
    assert any(r.table_name == "orders" for r in results)
```

### Async tests (pipeline tests)
```python
import pytest

@pytest.mark.asyncio
async def test_pipeline(seeded_conn):
    ...
```

`pytest-asyncio` is configured in `pyproject.toml` under `[tool.pytest.ini_options]`.  
No need for `asyncio_mode = "auto"` — use the explicit `@pytest.mark.asyncio` decorator.

---

## Test Files

| File | What it tests |
|---|---|
| `tests/test_fts.py` | `search_tables`, `search_columns` — BM25 results + score types |
| `tests/test_retrieval.py` | `expand_queries`, end-to-end retrieval pipeline |
| `tests/test_dbml_gen.py` | `generate_dbml` output structure |

---

## Running Tests

```bash
# All tests
uv run pytest

# Specific file
uv run pytest tests/test_fts.py -v

# Stop on first failure
uv run pytest -x

# Show log output
uv run pytest -s
```

---

## Common Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `no such table: meta.table_registry` | Used `engine.connect()` after `seeded_conn` closed | Always use the yielded `seeded_conn` |
| `no such table: fts_tables` | `build_fts_index` not called | Use `seeded_conn` fixture, not bare `engine` |
| Async test hangs | Missing `@pytest.mark.asyncio` | Add the decorator |
| Tests pass individually but fail together | Shared state via module-scope fixture | Keep fixtures at `function` scope |
