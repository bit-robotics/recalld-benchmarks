# LoCoMo, `recalld-recall` in sources mode, 2026-08-06

All ten `locomo10` conversations, 1540 non-adversarial questions.

| | |
|---|---|
| Date of run | 2026-08-06 |
| Harness | AMB @ `aa9273ab9e34bbeaff3c6ef2f694142a552d5b22`, plus patches 01 to 06 in [`patches/`](../../patches/) (07 was added later and only renames categories) |
| Dataset | LoCoMo, `locomo10` split (adversarial category excluded by AMB) |
| Provider | `recalld-recall` (`POST /memory/recall`), `--mode rag` |
| `RECALLD_ANSWER_CONTEXT` | `sources` |
| Retrieval limit | 10 (AMB default k; `RECALLD_TOP_K` unset) |
| Embedding model | `gemini-embedding-002-vertex` |
| Recalld base URL | `https://eu.recalld.ai` (the EU region; at run time this host was still addressed as `api.recalld.ai`) |
| Answer model | `gemini:gemini-3.1-pro-preview` (via Vertex, `GEMINI_BACKEND=vertex`) |
| Judge model | `gemini:gemini-2.5-flash-lite` (via Vertex) |

## Result

**1366 / 1540 correct = 88.7%**, at a mean of **242.9 context tokens per question**.

Recompute both figures from the committed reports:

```bash
uv run python scripts/summarize_results.py results/2026-08-06_locomo_recalld-recall-sources
```

Per-unit accuracy ranges from 84.0% (conv-49) to 93.5% (conv-44).

Per category, using LoCoMo's own category names: single-hop 91.7% (771/841),
temporal 89.7% (288/321), open-domain 83.3% (80/96), multi-hop 80.5% (227/282).
The reports carry AMB's labels, three of which are swapped: `open-domain` in the
JSON is LoCoMo's single-hop, `multi-hop` is open-domain, `single-hop` is
multi-hop. See [the README](../../README.md#read-this-before-quoting-a-number).

The control for this run is the
[search run](../2026-09-01_locomo_recalld-search-sources/): same stores, same
context mode, `/memory/search` instead of `/memory/recall`. It scores 88.2%
(1359/1540) at 1627.4 mean context tokens. See its notes for the comparison.

## Known problems with this run

**Three questions retrieved nothing.** `conv-41_q69`, `conv-42_q92` and
`conv-44_q43` have the context `{"sources": []}`. When this run was made,
`verify_retrievals.py` only caught blank strings, so the run passed the gate. It
would not pass today. The answer model said it could not answer all three, and
the judge marked all three correct. The rows are left in and still counted.

**The judge accepts "I don't know".** Those three are not special. AMB's judge
prompt has a clause for questions whose gold answer says the information is
missing, and the judge model applies it to questions that do have a concrete
gold answer. A rough text search finds 113 answers in this run that say the
context lacks the information, about 90 of them judged correct. The search run
has 51 such answers, about 30 judged correct. We kept AMB's judge prompt and
default judge model so the score stays comparable with other AMB results, which
are judged the same way. Read 88.7% as an upper bound, and do not read the gap
to the search run as evidence that recall is more accurate.

## How these runs were produced

Each unit was ingested once by an earlier `recalld-bench-conv-NN` run with
`RECALLD_KEEP_BENCHMARK_AGENTS=true`. The
`-recall-sources` runs then scored the same stores with `--skip-ingestion`, so
`ingested_docs` and `ingestion_time_ms` read `0` in these reports. Ingestion is
not re-measured here; only retrieval and answering are.

## Read the context-token figure carefully

`avg_context_tokens` measures the context handed to the **answer model**: that
is what a RAG application pays for on every question. It is not the total
compute the memory system used.

`provider_usage` in each report records Recalld's own server-side spend for these
runs: 18.76M input tokens and 353.6K output tokens across 4254
`gemini-3.1-flash-lite-vertex` calls and 561 `gemini-embedding-002-vertex` calls,
for the retrieval half of the workload. `recalld-recall` does LLM fact selection
server-side, so it moves work off the answer prompt rather than eliminating it.
Any cost comparison should say which of the two it is measuring.

`per_operation` is `null` in these reports: the adapter version used here
recorded only run totals.

## Not comparable with

- AMB leaderboard entries produced without the patches in `patches/`, in
  particular [`03-locomo-session-order.patch`](../../patches/03-locomo-session-order.patch),
  which changes the order sessions are ingested in for every provider.
