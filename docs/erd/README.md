# Schema ERD

- **Catalog:** `europe_prod_catalog`
- **Schema:** `mimir_model_gold`
- **Tables:** 32
- **Relationships:** 22

## View the diagram

1. Open [schema.mmd](./schema.mmd) in VS Code (Mermaid preview) or paste into https://mermaid.live

2. Render Graphviz:
   ```bash
   dot -Tsvg schema.dot -o schema.svg
   dot -Tpng schema.dot -o schema.png
   ```

## Regenerate

```bash
cd /path/to/nlsearchv2
python scripts/build_erd.py --sync-first -o docs/erd
# or offline from synced metadata:
python scripts/build_erd.py --from-json src/nlsearch/semantic/data/schema_metadata.json -o docs/erd
```
