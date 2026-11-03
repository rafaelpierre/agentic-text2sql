---
name: meta-schema
description: >
  Domain knowledge for the agentic-text2sql meta-schema layer. Use when working on
  table_registry, column_registry, schema_registry, seed_meta, FTS index, BM25 search,
  search_tables, search_columns, FK-neighbour expansion, DBML generation, generate_dbml,
  or adding / modifying database tables in the e-commerce schema.
  Trigger phrases: meta-schema, table_registry, column_registry, seed_meta, FTS,
  BM25, search_tables, search_columns, generate_dbml, fk_references, add table.
argument-hint: "Table name or operation (e.g. 'add reviews table', 'FTS search tuning')"
---

# Meta-Schema

## Two-Database Layout

The project uses **two separate logical databases** (SQLite: two ATTACHed files; Postgres: two schemas):

| Logical name | SQLite file | Postgres schema | Contains |
|---|---|---|---|
| `meta` | `text2sql_meta.db` | `meta` | Schema descriptions for FTS + DBML |
| `ecommerce` | `text2sql_ecommerce.db` | `ecommerce` | Actual e-commerce data |

In tests both are `:memory:` via `StaticPool` + `ATTACH DATABASE ':memory:'`.

---

## Meta-Schema Tables (`text2sql_mvp/app/meta_schema.py`)

### `meta.schema_registry`
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `schema_name` | Text | unique, e.g. `"ecommerce"` |
| `overview` | Text | High-level description used in system prompt |

### `meta.table_registry`
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `schema_id` | FK → schema_registry | |
| `table_name` | Text | e.g. `"orders"` |
| `description` | Text | Human-readable description for display |
| `search_doc` | Text | Denormalised text for FTS indexing |

### `meta.column_registry`
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `table_id` | FK → table_registry | |
| `column_name` | Text | |
| `data_type` | Text | e.g. `"integer"`, `"varchar(255)"`, `"numeric(10,2)"` |
| `is_pk` | Boolean | |
| `is_fk` | Boolean | |
| `fk_references` | Text\|None | e.g. `"users.id"` |
| `description` | Text | Column-level description |
| `search_doc` | Text | Denormalised text for FTS indexing |

---

## FTS Index (`text2sql_mvp/app/fts.py`)

Two virtual FTS tables mirror the meta tables:
- `fts_tables` — indexed on `search_doc`
- `fts_columns` — indexed on `search_doc`

**SQLite**: FTS5 with `tokenize='unicode61'`  
**Postgres**: `tsvector` + GIN index

### Building the index
```python
from text2sql_mvp.app.fts import build_fts_index
build_fts_index(conn)   # call after seed_meta()
```

### Searching
```python
from text2sql_mvp.app.fts import search_tables, search_columns
tables: list[TableMatch] = search_tables(conn, query, top_k=5)
columns: list[ColumnMatch] = search_columns(conn, query, top_k=5)
```

`TableMatch` → `(table_id, table_name, score: float)`  
`ColumnMatch` → `(column_id, table_id, column_name, score: float)`

### Lemmatisation
All `search_doc` text is pre-lemmatised at index time using `lemmatize()` (WordNetLemmatizer).  
Queries are also lemmatised before FTS lookup.

---

## FK-Neighbour Expansion

After FTS returns top-K tables, related tables are pulled in via FK edges:

```python
from text2sql_mvp.app.meta_schema import get_fk_neighbour_table_ids
neighbour_ids = get_fk_neighbour_table_ids(conn, table_ids)
```

Hard cap: `MAX_TABLES = 8` total tables after expansion.

---

## DBML Generation (`text2sql_mvp/app/dbml_gen.py`)

```python
from text2sql_mvp.app.dbml_gen import generate_dbml, generate_full_dbml

# Subset of tables (used in pipeline)
dbml = generate_dbml(conn, table_names=["orders", "users"], include_notes=True)

# Full schema (used by `text2sql dbml show` CLI)
dbml = generate_full_dbml(conn)
```

Output is a DBML string compatible with dbdiagram.io.  
`include_notes=True` emits `note: '...'` for column descriptions — remove for tighter prompts.

---

## Seeding (`text2sql_mvp/app/seed_meta.py`)

The `TABLES` list drives seeding. Each entry is a dict:

```python
{
    "table_name": "orders",
    "description": "...",
    "columns": [
        # (column_name, data_type, is_pk, is_fk, fk_references, description)
        ("id", "integer", True, False, None, "..."),
        ("user_id", "integer", False, True, "users.id", "..."),
    ]
}
```

The `search_doc` for each table/column is auto-generated from `description` + column names.

### Current e-commerce tables
`users`, `products`, `orders`, `order_items`, `categories`, `reviews`, `addresses`, `shipping_zones`, `discount_codes`, `payments`

---

## Adding a New Table

1. Add an entry to `TABLES` in `seed_meta.py`
2. Add corresponding rows to `seed_data.py`
3. Run `uv run text2sql seed-meta && uv run text2sql seed-data && uv run text2sql build-fts`
4. Add FTS search assertions in `tests/test_fts.py`
5. Add at least 2 eval examples in `eval/eval_examples.jsonl`
