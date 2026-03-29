---
applyTo: "**"
---

# agentic-text2sql — Copilot Workspace Instructions

## Skills & Agents Maintenance

This project has four skills and four custom agents under `.github/`. **Keep them in sync
with the codebase.** When a code change affects a skill or agent's documented behaviour,
update the corresponding file in the same PR/commit.

### Skills to maintain

| Skill | File | Update when… |
|---|---|---|
| `pipeline-architecture` | `.github/skills/pipeline-architecture/SKILL.md` | `text2sql.py` changes: new stage, new env var, changed model routing, ModelRetry logic, `PipelineDeps` fields |
| `meta-schema` | `.github/skills/meta-schema/SKILL.md` | `meta_schema.py`, `fts.py`, `dbml_gen.py`, `seed_meta.py` changes: new table, column schema change, FTS tokenisation, FK expansion |
| `eval-workflow` | `.github/skills/eval-workflow/SKILL.md` | `run_eval.py`, `eval_examples.jsonl` structure changes: new complexity tier, judge prompt, scoring rubric, output fields |
| `test-fixtures` | `.github/skills/test-fixtures/SKILL.md` | `conftest.py` changes: new fixtures, scope changes, new test files added |

### Agents to maintain

| Agent | File | Update when… |
|---|---|---|
| `eval-analyst` | `.github/agents/eval-analyst.agent.md` | `eval_results.jsonl` schema changes, new score fields |
| `sql-case-generator` | `.github/agents/sql-case-generator.agent.md` | New complexity tiers added, schema tables added/removed |
| `schema-expander` | `.github/agents/schema-expander.agent.md` | `seed_meta.py` or `seed_data.py` structural changes, new test patterns |
| `pipeline-debugger` | `.github/agents/pipeline-debugger.agent.md` | New pipeline stages, new agent tools, changed retry logic |

### When to update

- **Renamed or moved source file** → update all path references in skills/agents
- **New env var added** → add it to the `pipeline-architecture` skill table
- **New complexity tier** → add to the tier table in both `eval-workflow` skill and `sql-case-generator` agent
- **New table added to `seed_meta.py`** → update the table list in `meta-schema` skill and `sql-case-generator` agent
- **New pytest fixture in `conftest.py`** → document it in `test-fixtures` skill
- **New pipeline stage** → document it in `pipeline-architecture` skill and update `pipeline-debugger` agent

---

## Project Conventions

- **Package**: `text2sql_mvp/app/` — all core modules live here
- **CLI**: `cli.py` using Typer; entry point `text2sql` via `uv run text2sql <command>`
- **Dependency management**: `uv` — use `uv run` for all commands, `uv add` for dependencies
- **Tests**: `uv run pytest` — always use `seeded_conn` fixture for tests that touch the meta-schema
- **Models**: always prefixed `azure:` when passed to Pydantic AI (e.g. `f"azure:{SQL_MODEL}"`)
- **SQL dialect**: target SQLite (tests) and PostgreSQL (production) — no dialect-specific syntax unless guarded by `dialect(conn.engine)`
- **No raw f-string SQL**: always use `sqlalchemy.text()` for raw queries; use ORM expressions where possible
