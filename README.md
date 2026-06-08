# Hubexo Natural Language Search

Python platform that converts free-text search requests into **structured query intents** and optional **validated SQL** for the Hubexo gold-layer model (projects, companies, people, workplaces).

Built from the architecture in `nl-chatgpt-suggestion.odt` and requirements in `nl2sql-hubexo.odt`.

## Features

| Capability | Implementation |
|------------|----------------|
| Structured intent (AC-1) | `QueryIntent` with `resultType`, `mode`, `filters`, `sort`, `geo`, `aggregation` |
| Mode routing (AC-2) | structured / keyword / semantic / geo / aggregation / temporal / cross-entity |
| No silent drops (AC-3) | `dropped_constraints` + explanation in response |
| Normalization (AC-4) | SEK currency, Europe/Stockholm dates, gazetteer, role/stage synonyms |
| Default exclusions (AC-5) | Cancelled/archived projects, active persons |
| Licence scope (AC-6) | Hard post-filter via `LicenseFilter` |
| Multi-turn (AC-7) | Session store: additive / replace / pivot / reset |
| Ambiguity (AC-8) | `NoCoverageResponse` / clarification for ambiguous places |
| LLM intent (Rune) | Optional **Rune Query Understanding Engine** — schema-aware JSON intent, no SQL from LLM |
| Web UI | Static UI at `/` — async search, categorized result tables, multi-turn sessions |
| Live warehouse SQL | Intent logical fields → **FK joins** on Mimir gold (not denormalized columns on `project_fields`) |

## Architecture

```
User → API Gateway → Query Orchestrator
                         ├─ Intent Analyzer (rules) ─┐
                         ├─ LLM Intent (Rune, optional) ─┘ → QueryIntent
                         ├─ Semantic Layer (glossary + schema RAG)
                         ├─ Session Memory
                         ├─ SQL Generator (gold-layer joins)
                         ├─ SQL Validator
                         ├─ License + Default governance
                         └─ Databricks SQL Warehouse → Result Formatter
```

## Gold-layer schema (Mimir)

NL search targets `europe_prod_catalog.mimir_model_gold` with **`project_fields`** as the hub table. Related tables include `site_address` (geo), `project_roles` / `project_role_contacts` (companies/people), `contract_stages` / `planning_stages` / `project_statuses` (three-dimension stage model), and `project_green_building` (semantic sustainability).

Field mapping lives in `src/nlsearch/semantic/gold_layer.py`. Intent filters use logical names (`project_value`, `contract_stage`, `building_use_group`, `postal_town`, …) and `SQLGenerator` emits joined SQL with fully qualified table names.

### Live warehouse vs schema metadata

Synced Unity Catalog metadata can list logical/denormalized column names that **do not exist** on the live gold tables. The SQL generator always joins dimension tables instead:

| Logical field | SQL pattern |
|---------------|-------------|
| `development_type` | `LEFT JOIN development_types dt` → `dt.development_type` |
| `building_use_group` / `sector` | `project_building_uses` + `building_use_definitions` → `bud.building_use_group` |
| `contract_stage` / `planning_stage` / `stage` | `contract_stages.key` / `planning_stages.key` (via `*_stage_id` FKs) |
| `project_status` | `project_statuses.key` |
| FQN paths from LLM | `sql_column()` maps e.g. `…contract_stages.key` → `cs.key` |

Default project queries anchor on `project_fields pf` with standard LEFT JOINs to `site_address`, stage dimensions, development type, and primary building use.

### Patch / “my patch” queries

There is **no** `territory_polygon` geometry column in the gold layer. Queries like “everything live in my patch”:

- Record `geo: { kind: "within_polygon", polygon_id: "territory" }` in intent (UI / clarification only)
- Scope SQL via **`sa.admin_level_1 IN (licensed_regions)`** from request `context`, `user_region`, or `NLSEARCH_LICENSED_REGIONS`
- “Live” adds tender + construction `contract_stage` keys (`TCI`, `TCR`, `ATR`, …)

Pass regions in the API body when they differ from defaults:

```bash
curl -s -X POST http://localhost:8080/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Everything live in my patch", "context": {"licensed_regions": ["Stockholm", "Uppsala"]}, "execute": false}'
```

### Ontology / synonyms (from live data)

Dimension-table values are synced into `src/nlsearch/vocabulary/data/*.json`:

```bash
python scripts/sync_ontology.py
```

See `src/nlsearch/vocabulary/data/README.md` for file list and gaps (Company Registry, stage history, etc.).

Refresh metadata after catalog changes:

```bash
curl -X POST http://localhost:8080/v1/admin/schema/sync
```

## Quick start

```bash
cd nlsearchv2
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
cp .env.example .env   # set Databricks host, HTTP path, optional token
pytest -q --ignore=tests/test_unity_catalog.py
uvicorn nlsearch.api.main:app --reload --port 8080
```

For fast local tests without Databricks CLI auth (avoids long hangs):

```bash
PYTHONPATH=src NLSEARCH_SKIP_DATABRICKS_CLI=true pytest tests/ -q --ignore=tests/test_unity_catalog.py
```

Open **http://localhost:8080/** for the web UI:

- Natural-language query box with optional **Execute SQL**, **Use LLM**, and **Intent mode**
- Async `POST /v1/search` with categorized tables (summary, intent, SQL, rows, raw JSON)
- Multi-turn: responses include `session_id` for follow-up queries

### Example request

```bash
curl -s -X POST http://localhost:8080/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Tender-stage hospital projects in Stockholm over 100 million", "execute": false}' | jq
```

### Multi-turn

```bash
# Turn 1
SID=$(curl -s -X POST http://localhost:8080/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Tender projects in Stockholm", "execute": false}' | jq -r .session_id)

# Turn 2 — additive filter
curl -s -X POST http://localhost:8080/v1/search \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"just the ones over 100M\", \"session_id\": \"$SID\", \"execute\": false}"
```

## LLM intent and refinement (optional)

Install LLM extras: `pip install -e ".[llm]"`.

Set `NLSEARCH_LLM_PROVIDER=databricks` (AI gateway) or `openai` / `anthropic`, plus credentials in `.env`.

| `NLSEARCH_LLM_INTENT_MODE` | Behaviour |
|---------------------------|-----------|
| `rules` (default) | Rule-based Rune-style intent; optional LLM polish when `NLSEARCH_LLM_REFINE_INTENT=true` |
| `refine` | Same as rules with refinement enabled |
| `primary` | **Rune LLM** builds canonical intent JSON from schema + vocabulary + geo + session; falls back to rules on error |

Primary mode uses the Rune Query Understanding prompt (`src/nlsearch/llm/rune_intent.py`):

- Schema catalog, sector/stage synonyms, business vocabulary, geo sample, temporal rules, conversation state
- Outputs JSON only — **no SQL** from the LLM
- Parsed by `src/nlsearch/llm/intent_parse.py` (strips FQN field paths to logical names)
- Existing SQL generator, validator, licence governance, and Databricks executor run afterward

### Databricks auth for execute + primary LLM

| Approach | Setup |
|----------|--------|
| Token in `.env` | `NLSEARCH_DATABRICKS_TOKEN=…` |
| CLI profile | `databricks auth login` + `NLSEARCH_DATABRICKS_PROFILE=…`; leave token empty — `get_settings()` resolves OAuth via SDK |
| AI gateway | When SQL credentials are set, host/token are mirrored to `NLSEARCH_DATABRICKS_AI_GATEWAY_*` automatically |

Model default: `NLSEARCH_DATABRICKS_AI_GATEWAY_MODEL=databricks-gpt-5-4-nano` (override in `.env`).

```bash
curl -s -X POST http://localhost:8080/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "tender projects in Uppsala over 50 mkr", "use_llm": true, "intent_mode": "primary", "execute": true}'
```

Request fields: `use_llm`, `intent_mode` (`rules` | `refine` | `primary`), `context` (`user_region`, `licensed_regions`, `eval_now`, …).

Response includes `intent_source` (`llm`, `rules`, `rules+llm_refine`, `rules_fallback`), `intent_mode`, and `intent_warnings` when falling back.

## ERD diagram from Databricks

Generate a Mermaid + Graphviz ERD from your Unity Catalog gold schema:

```bash
# Live: Unity Catalog API + optional FK query via SQL warehouse
python scripts/build_erd.py --sync-first -o docs/erd

# Offline: from synced schema_metadata.json
python scripts/build_erd.py --from-json src/nlsearch/semantic/data/schema_metadata.json -o docs/erd

# Subset
python scripts/build_erd.py --tables projects,companies,people,workplaces -o docs/erd
```

Outputs:

| File | Use |
|------|-----|
| `docs/erd/schema.mmd` | Mermaid — preview in VS Code or [mermaid.live](https://mermaid.live) |
| `docs/erd/schema.dot` | Graphviz — `dot -Tsvg docs/erd/schema.dot -o docs/erd/schema.svg` |

Relationships come from `information_schema` (when the warehouse is configured) and from `*_id` column naming heuristics.

Requires `NLSEARCH_DATABRICKS_HOST`, `NLSEARCH_DATABRICKS_HTTP_PATH`, `NLSEARCH_DATABRICKS_TOKEN`, `NLSEARCH_UNITY_CATALOG_NAME`, `NLSEARCH_UNITY_SCHEMA_NAME`.

## Unity Catalog schema sync

Sync gold-layer metadata from Databricks into `src/nlsearch/semantic/data/schema_metadata.json`:

```bash
# Configure NLSEARCH_DATABRICKS_HOST, TOKEN, UNITY_CATALOG_NAME, UNITY_SCHEMA_NAME
curl -X POST http://localhost:8080/v1/admin/schema/sync
curl http://localhost:8080/v1/admin/schema/tables
```

Or from Python: `await SchemaStore().sync_from_unity_catalog()`.

## Client query catalog & MF-28

| Suite | Files |
|-------|--------|
| ODT client queries | `tests/data/client_query_catalog.json` → `tests/test_query_catalog.py` (25 NL + 4 multi-turn) |
| MF-28 acceptance | `tests/data/mf28_test_cases.json` → `tests/test_mf28_cases.py` (~60 intent/SQL scenarios) |

## Configuration

Copy `.env.example` to `.env`:

| Variable | Purpose |
|----------|---------|
| `NLSEARCH_REDIS_URL` | Session memory (optional; in-process if empty) |
| `NLSEARCH_LICENSED_REGIONS` | Default comma-separated licence / patch regions |
| `NLSEARCH_DATABRICKS_HOST` | Workspace host for SQL warehouse |
| `NLSEARCH_DATABRICKS_HTTP_PATH` | SQL warehouse HTTP path |
| `NLSEARCH_DATABRICKS_TOKEN` | PAT or OAuth token; leave empty to use CLI profile |
| `NLSEARCH_DATABRICKS_PROFILE` | Databricks CLI profile when token unset |
| `NLSEARCH_SKIP_DATABRICKS_CLI` | `true` in CI/tests to skip CLI token resolution |
| `NLSEARCH_LLM_PROVIDER` | `databricks`, `openai`, `anthropic`, or empty |
| `NLSEARCH_LLM_INTENT_MODE` | `rules` \| `refine` \| `primary` |
| `NLSEARCH_LLM_REFINE_INTENT` | LLM polish after rule-based intent |
| `NLSEARCH_DATABRICKS_AI_GATEWAY_MODEL` | Model for Databricks primary intent |
| `NLSEARCH_UNITY_CATALOG_NAME` | Default `europe_prod_catalog` |
| `NLSEARCH_UNITY_SCHEMA_NAME` | Default `mimir_model_gold` |
| `NLSEARCH_OPENAI_*` / `NLSEARCH_ANTHROPIC_*` | Optional non-Databricks LLM providers |

## Project layout

```
src/nlsearch/
  api/           FastAPI gateway + static web UI
  intent/        Analyzer + mode router
  llm/           Rune intent, intent_parse, refiner, Databricks provider
  semantic/      Glossary, gold_layer mappings, schema metadata, RAG
  normalizers/   Currency, dates, places
  memory/        Conversation session state
  governance/    Licence + default exclusions
  sql/           Generator + validator
  execution/     Databricks adapter + formatter
  orchestrator.py
tests/           AC fixtures, client catalog, MF-28 cases
scripts/         sync_ontology.py, build_erd.py
```

## Acceptance criteria mapping

- **AC-1** — `/v1/search` and `/v1/intent` always return `intent` or `no_coverage`
- **AC-2** — `intent.mode` + `intent.result_type` on every successful parse
- **AC-3** — `dropped_constraints` and `explanation` fields
- **AC-4** — `tests/test_normalizers.py`
- **AC-5** — `default_exclusions_applied` in intent
- **AC-6** — `license_notice` when region out of scope
- **AC-7** — `tests/test_client_queries.py` multi-turn tests
- **AC-8** — `AMBIGUOUS_PLACE` no-coverage path
