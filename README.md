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

## Architecture

```
User → API Gateway → Query Orchestrator
                         ├─ Intent Analyzer (entities, mode)
                         ├─ Semantic Layer (glossary + schema RAG)
                         ├─ Session Memory
                         ├─ SQL Generator
                         ├─ SQL Validator
                         ├─ License + Default governance
                         └─ Databricks SQL Warehouse → Result Formatter
```

## Gold-layer schema (Mimir)

NL search targets `europe_prod_catalog.mimir_model_gold` with **`project_fields`** as the hub table. Related tables include `site_address` (geo), `project_roles` / `project_role_contacts` (companies/people), `contract_stages` / `planning_stages` / `project_statuses` (three-dimension stage model), and `project_green_building` (semantic sustainability).

Field mapping lives in `src/nlsearch/semantic/gold_layer.py`. Intent filters use logical names (`project_value`, `contract_stage`, `building_use_group`, `postal_town`, …) and `SQLGenerator` emits joined SQL with fully qualified table names.

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
cd /home/sudeep/ubuntu-p16/hubexo/nlsearchv2
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
uvicorn nlsearch.api.main:app --reload --port 8080
```

Open **http://localhost:8080/** for the web UI (query textarea, async `/v1/search`, results as categorized tables).

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

Set `NLSEARCH_LLM_PROVIDER=openai` (or `databricks`) and API credentials. Install extras: `pip install 'nlsearch[llm]'`.

| `NLSEARCH_LLM_INTENT_MODE` | Behaviour |
|---------------------------|-----------|
| `rules` (default) | Rule-based Rune-style intent; optional LLM polish when `NLSEARCH_LLM_REFINE_INTENT=true` |
| `refine` | Same as rules with refinement enabled |
| `primary` | **Rune LLM** builds the canonical intent JSON from schema + vocabulary + geo + session; falls back to rules on error |

Primary mode uses the Rune Query Understanding prompt (schema catalog, sector/stage synonyms, business vocabulary, geo sample, temporal rules, conversation state). It does **not** generate SQL — the existing SQL generator and Databricks executor run after governance.

```bash
curl -s -X POST http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "tender projects in Uppsala over 50 mkr", "use_llm": true, "intent_mode": "primary", "execute": true}'
```

Response includes `intent_source` (`llm`, `rules`, `rules+llm_refine`, `rules_fallback`) and `intent_mode`.

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

## Client query catalog

All example queries from `nl2sql-hubexo.odt` are in `tests/data/client_query_catalog.json` and exercised by `tests/test_query_catalog.py` (25 NL queries + 4 multi-turn flows).

## Configuration

Copy `.env.example` to `.env`:

| Variable | Purpose |
|----------|---------|
| `NLSEARCH_REDIS_URL` | Session memory (optional) |
| `NLSEARCH_LICENSED_REGIONS` | Comma-separated licence scope |
| `NLSEARCH_DATABRICKS_*` | SQL warehouse execution |
| `NLSEARCH_OPENAI_API_KEY` | Optional LLM refinement |

## Project layout

```
src/nlsearch/
  api/           FastAPI gateway
  intent/        Analyzer + mode router
  semantic/      Glossary, schema metadata, RAG retrieval
  normalizers/   Currency, dates, places
  memory/        Conversation session stateN
  governance/    Licence + default exclusions
  sql/           Generator + validator
  execution/     Databricks adapter + formatter
  orchestrator.py
tests/           AC-4 fixtures + client query catalog
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
