# Results

Raw benchmark reports are committed here, unedited except for gzip compression.
AMB ships its own baselines as `.json.gz` for the same reason: an uncompressed
LoCoMo report runs to several MB because it stores every question's full context.

## What is here

| Run | Provider | Result |
|---|---|---|
| [2026-08-06_locomo_recalld-recall-sources](2026-08-06_locomo_recalld-recall-sources/) | `recalld-recall`, sources mode | 88.7% (1366/1540), 242.9 mean context tokens |
| [2026-09-01_locomo_recalld-search-sources](2026-09-01_locomo_recalld-search-sources/) | `recalld` (`/memory/search`), sources mode | 88.2% (1359/1540), 1627.4 mean context tokens |

The second run is the control for the first: same harness, models, context mode
and stores, different endpoint. See either `notes.md` for the comparison, and
read [the caveats in the README](../README.md#read-this-before-quoting-a-number)
first: the judge accepts "I don't know" answers, three recall rows retrieved
nothing, and three category labels in the JSON are swapped.

Recompute the headline figures straight from the committed files:

```bash
uv run python scripts/summarize_results.py
```

The summarizer recomputes accuracy and mean context tokens from the per-question
rows rather than trusting the report's own summary fields, and lists any
question that retrieved nothing.

## Dataset content in these files

Every row holds the LoCoMo question, its gold answer, and the conversation
excerpts retrieved as context. That text is from the LoCoMo dataset (Maharana et
al., ACL 2024), licensed
[CC BY-NC 4.0](https://github.com/snap-research/locomo/blob/main/LICENSE.txt),
and is reproduced here only so the published numbers can be checked. The same
licence terms apply if you reuse it.

## Where reports come from

After a run finishes, AMB writes its report to:

```
amb/outputs/locomo/<provider>/<mode>/locomo10.json
```

For sweep runs with custom `--name` values:

```
amb/outputs/locomo/<run-name>/<mode>/locomo10.json
```

Example sweep paths:

- `amb/outputs/locomo/recalld-search-k25-<sweep-id>/rag/locomo10.json`

For `recalld-recall`, the mode is `rag` (not `agent`):

```
amb/outputs/locomo/recalld-recall/rag/locomo10.json
```

## Adding a run

One directory per run, named `<YYYY-MM-DD>_<dataset>_<provider><-variant>`:

```
results/2026-08-06_locomo_recalld-recall-sources/
  conv-26.json.gz     one report per conversation unit
  ...
  notes.md
```

Compress each report as you copy it in:

```bash
gzip -9 -c amb/outputs/locomo/<run-name>/rag/locomo10.json \
  > results/<run-dir>/<unit>.json.gz
```

Single-unit runs may use `report.json.gz` instead of a per-unit name.

## What to record in notes.md

- Date of the run
- AMB pinned commit, and confirmation that the `patches/` stack was applied
- Provider settings (Recalld base URL type; embedding model; Mem0 OSS server
  version/commit and extraction model)
- Answer and judge models (`answer_llm` and `judge_llm` fields in the JSON)
- Dataset split (`locomo10`) and conversation units covered
- **Recalld endpoint** (`search` or `recall`) when applicable
- **`RECALLD_ANSWER_CONTEXT`** (`facts` or `sources`)
- **Top-k** (`RECALLD_TOP_K` or sweep k value) when not the default 10
- **Average context tokens** (`avg_context_tokens` field in the JSON)
- **Sweep ID** when the report comes from `scripts/run_recalld_sweep.py`
- Whether the run used `--skip-ingestion` against a store built by an earlier run
  (if so, `ingested_docs` will be `0` and ingestion is not being measured)
- SHA-256 of the dataset file if recorded locally
