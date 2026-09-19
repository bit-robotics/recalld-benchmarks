# LoCoMo, `recalld` (`/memory/search`) in sources mode, 2026-08-31 to 2026-09-01

All ten `locomo10` conversations, 1540 non-adversarial questions.

| | |
|---|---|
| Date of run | 2026-08-31 to 2026-09-01 |
| Harness | AMB @ `aa9273ab9e34bbeaff3c6ef2f694142a552d5b22`, plus patches 01 to 06 in [`patches/`](../../patches/) (07 was added later and only renames categories) |
| Dataset | LoCoMo, `locomo10` split (adversarial category excluded by AMB) |
| Provider | `recalld` (`POST /memory/search`, vector similarity, no LLM), `--mode rag` |
| `RECALLD_ANSWER_CONTEXT` | `sources` |
| Retrieval limit | 10 (AMB default k; `RECALLD_TOP_K` unset) |
| Embedding model | `gemini-embedding-002-vertex` |
| Recalld base URL | `https://eu.recalld.ai` (the EU region; at run time this host was still addressed as `api.recalld.ai`) |
| Answer model | `gemini:gemini-3.1-pro-preview` (via Vertex, `GEMINI_BACKEND=vertex`) |
| Judge model | `gemini:gemini-2.5-flash-lite` (via Vertex) |

## Result

**1359 / 1540 correct = 88.2%**, at a mean of **1627.4 context tokens per question**.

Recompute both figures from the committed reports:

```bash
uv run python scripts/summarize_results.py results/2026-09-01_locomo_recalld-search-sources
```

Per-unit accuracy ranges from 83.2% (conv-48) to 94.7% (conv-47).

Per category, using LoCoMo's own category names: single-hop 92.2% (775/841),
temporal 90.0% (289/321), open-domain 78.1% (75/96), multi-hop 78.0% (220/282).
The reports carry AMB's labels, three of which are swapped: `open-domain` in the
JSON is LoCoMo's single-hop, `multi-hop` is open-domain, `single-hop` is
multi-hop. See [the README](../../README.md#read-this-before-quoting-a-number).

## Why this run is published

It is the control for the
[recall run](../2026-08-06_locomo_recalld-recall-sources/). Same harness, same
dataset, same answer and judge models, same retrieval limit, same `sources`
context mode, same memory stores. The intended variable is the endpoint:
`/memory/search` returns the top-k source excerpts by vector similarity with no
LLM call; `/memory/recall` runs an LLM selection pass server-side and returns
only the excerpts it picked. The two runs are four weeks apart and we did not
record the Recalld server revision for either, so we cannot prove the endpoint
is the only thing that differed.

| | Accuracy | Mean context tokens | Mean retrieval time |
|---|---|---|---|
| search (this run) | 88.2% (1359/1540) | 1627.4 | 0.56 s |
| recall | 88.7% (1366/1540) | 242.9 | 6.65 s |

The context reduction is 6.7x and is the point of the comparison. Search is
about twelve times faster per question, because it makes no LLM call.

Do not read the accuracy column as "recall is as accurate as search". AMB's
judge often marks an answer of "the context lacks the information" as correct,
and that happens about 90 times in the recall run against about 30 here (rough
text search of the reports). We kept AMB's judge unchanged for comparability
with other AMB results. Details in
[the README](../../README.md#read-this-before-quoting-a-number) and the
[recall run notes](../2026-08-06_locomo_recalld-recall-sources/notes.md#known-problems-with-this-run).

## How these runs were produced

Each unit was ingested once by an earlier `recalld-bench-conv-NN` run with
`RECALLD_KEEP_BENCHMARK_AGENTS=true`. The `-search-sources` runs then scored
the same stores with `--skip-ingestion`, so `ingested_docs` and
`ingestion_time_ms` read `0` in these reports. Ingestion is not re-measured
here; only retrieval and answering are. The
[recall run](../2026-08-06_locomo_recalld-recall-sources/) scored the same
stores the same way.

## Server-side cost

`/memory/search` makes no LLM call. `provider_usage` in these reports records
zero tokens: the adapter version used here did not record the single query
embedding that search performs per question.

## Not comparable with

- AMB leaderboard entries produced without the patches in `patches/`, in
  particular [`03-locomo-session-order.patch`](../../patches/03-locomo-session-order.patch),
  which changes the order sessions are ingested in for every provider.
