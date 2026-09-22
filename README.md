# recalld-benchmarks

[![CI](https://github.com/bit-robotics/recalld-benchmarks/actions/workflows/ci.yml/badge.svg)](https://github.com/bit-robotics/recalld-benchmarks/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Public, reproducible memory benchmarks for [Recalld](https://recalld.ai), run on
the [Agent Memory Benchmark (AMB)](https://github.com/vectorize-io/agent-memory-benchmark),
Vectorize's open-source harness. We did not build our own harness. The harness
is pinned to one commit and every change we made to it is a patch in this
repository, each marked with whether it can affect scoring. Answer and judge
prompts are defined by the dataset (not per-provider adapters), so scores
reflect memory quality rather than custom answerer tuning.

Raw reports are committed unedited in [results/](results/), gzipped.

> Recalld is a product of Bit Robotics Ltd, which publishes this repository, and
> Recalld is one of the systems measured in it. Read
> [What we changed in AMB](#what-we-changed-in-amb) before quoting any number:
> three of the seven patches touch code that affects scoring, and one of them
> changes ingestion order for every provider.

## Published results

Both runs cover all ten `locomo10` conversations and their 1540 non-adversarial
questions. LoCoMo has 1986 questions in total; AMB excludes the 446 adversarial
ones, and so do we.

| Run | Configuration | Accuracy | Mean context tokens |
|---|---|---|---|
| [2026-08-06](results/2026-08-06_locomo_recalld-recall-sources/) | `recalld-recall`, sources mode | **88.7%** (1366/1540) | **242.9** |
| [2026-09-01](results/2026-09-01_locomo_recalld-search-sources/) | `recalld` (`/memory/search`), sources mode | 88.2% (1359/1540) | 1627.4 |

Each result is for the engine as it was on the run date. The engine is updated
regularly, so current results may differ slightly; we re-run after changes that
affect recall.

Same harness, dataset, answer model, judge model, retrieval limit, context mode
and memory stores. `/memory/recall` runs an LLM selection pass server-side and
returns only the excerpts it picked; `/memory/search` returns the top-k excerpts
by vector similarity with no LLM. The runs are four weeks apart and we did not
record the Recalld server revision for either, so the endpoint is the intended
difference, not a proven sole one. Recall's retrieved context is 6.7x smaller.
We make no claim about which endpoint is more accurate: see the next section.

### Read this before quoting a number

**The judge accepts "I don't know".** AMB's LoCoMo judge prompt has a clause for
questions whose gold answer says the information is missing. None of these 1540
questions is of that kind, but the default judge model applies the clause
anyway: an answer such as "The context lacks the information" is often marked
correct although the gold answer is a concrete fact. A rough text search of the
committed reports finds about 90 such rows in the recall run and about 30 in the
search run. We kept AMB's judge prompt and default judge model unchanged so that
our numbers stay comparable with other AMB results, which are judged the same
way. The consequence is that the headline accuracies are upper bounds, and that
the leniency helps recall more than search. Every row's answer, gold answer and
judge reasoning is in the reports, so this can be checked.

**Three recall rows retrieved nothing.** `conv-41_q69`, `conv-42_q92` and
`conv-44_q43` have the context `{"sources": []}`. The answer model said it could
not answer and the judge marked all three correct, for the reason above. When
these runs were made our validation only caught blank strings, so they passed.
The rows are left in and the denominator is unchanged. `verify_retrievals.py`
now rejects an empty source list, and `summarize_results.py` lists these rows.

**Category labels in the reports are AMB's, and three of them are swapped.**
Checked against the [LoCoMo evaluation code](https://github.com/snap-research/locomo/blob/main/task_eval/evaluation.py)
and the question counts in the paper, AMB's `single-hop` is LoCoMo's multi-hop,
its `multi-hop` is open-domain, and its `open-domain` is single-hop. The raw
reports keep AMB's labels. Read them as follows:

| LoCoMo category | Label in the reports | Questions | Recall | Search |
|---|---|---|---|---|
| Single-hop | `open-domain` | 841 | 91.7% | 92.2% |
| Multi-hop | `single-hop` | 282 | 80.5% | 78.0% |
| Temporal | `temporal` | 321 | 89.7% | 90.0% |
| Open-domain | `multi-hop` | 96 | 83.3% | 78.1% |

[07-locomo-category-labels](patches/07-locomo-category-labels.patch) corrects the
labels for future runs. It does not change any score.

Recompute both from the committed reports, without an API key:

```bash
uv run python scripts/summarize_results.py
```

`avg_context_tokens` is what the answer model is given per question. It is not
the memory system's total compute. See
[the run notes](results/2026-08-06_locomo_recalld-recall-sources/notes.md#read-the-context-token-figure-carefully)
for Recalld's own server-side token spend on the same run.

### Comparing against other systems

AMB ships its authors' own LoCoMo runs on these same 1540 questions, in
`results-manifest.json`. Those are the fairest external reference points, since
we did not run them:

| System | Accuracy | Mean context tokens | Run by |
|---|---|---|---|
| Hindsight | 92.0% | 36235.4 | AMB authors |
| Recalld (`recalld-recall`, sources) | 88.7% | 242.9 | us |
| hybrid-search (Qdrant RRF) | 79.1% | 22156.5 | AMB authors |

One caveat before using that table. Our runs apply
[03-locomo-session-order](patches/03-locomo-session-order.patch), which loads a
conversation's sessions in chronological rather than alphabetical order. The AMB
runs above predate that patch and do not have it. We have not measured what
difference it makes to a score, so treat the accuracy column as indicative rather
than a like-for-like ranking.

The LoCoMo entries in AMB's `external_results.json`, including its Mem0 figures,
are third-party blog claims rather than runs on this harness. They are not
comparable with anything above.

## What is measured

The [LoCoMo](https://github.com/snap-research/locomo) benchmark: long
conversations between two people, spread over many sessions. After conversations
are stored in a memory system, the harness asks questions about them. A memory
system scores well if retrieved context leads to correct answers.

For each conversation unit, AMB:

1. **Ingests** all session documents into the memory provider
2. **Retrieves** relevant memories for each question (top-k)
3. **Generates** an answer using the dataset's published RAG prompt (same for all providers)
4. **Judges** the answer against ground truth using the dataset's published judge prompt

## Providers in this repo

| Provider name | What it is | Published numbers? |
|---|---|---|
| `recalld` | Recalld REST API, plain retrieval (`POST /memory/search`). Run with `--mode rag`. | Yes, see above |
| `recalld-recall` | Recalld REST API, server-side LLM fact selection (`POST /memory/recall`). Run with `--mode rag`: it returns selected facts, not a final answer. | Yes, see above |
| `mem0-oss` | Mem0 OSS self-hosted server ([mem0 repository](https://github.com/mem0ai/mem0)), default configuration. Adapter targets server API v2.0.11. | No |

Only the two Recalld adapters have published numbers so far. The Mem0 OSS
adapter is included so the comparison can be run, by us or by anyone else, not
because we are quoting results from it. We have not published a Mem0 OSS run; do
not read this repository as a Recalld-vs-Mem0 claim.

For third-party baselines on the same harness, use AMB's own published results
rather than anything in this repository.

## Fixed configuration

| Setting | Value |
|---|---|
| Harness | AMB, commit `aa9273ab9e34bbeaff3c6ef2f694142a552d5b22` (pinned by `scripts/setup.py`) |
| Benchmark | LoCoMo (`locomo10` split; adversarial category excluded by AMB) |
| Answer model | `gemini-3.1-pro-preview`, via Vertex AI (`OMB_ANSWER_LLM=gemini`). AMB's own default answerer is Groq; we changed it, and the report files record which model answered. |
| Judge model | `gemini-2.5-flash-lite`, via Vertex AI (AMB's default judge provider) |
| Retrieval limit | 10 (AMB default k); Recalld sweeps override via `RECALLD_TOP_K` |
| Recalld endpoint | `https://eu.recalld.ai`, embedding model `gemini-embedding-002-vertex` |

## What we changed in AMB

The harness is not vendored. `scripts/setup.py` clones it at the pinned commit,
copies in files that do not exist upstream, then applies every patch in
[patches/](patches/) in filename order. Nothing else is modified.

**Added files** ([overlay/](overlay/)), no upstream file is touched:

- `src/memory_bench/memory/`: `recalld.py`, `mem0_oss.py`, `locomo_parse.py`
- `tests/`: unit tests for the Recalld adapter

**Patches**. The stack is sequential; 01 and 02 both edit
`src/memory_bench/memory/__init__.py`:

| Patch | Files | What it does | Affects scoring? |
|---|---|---|---|
| [01-register-providers](patches/01-register-providers.patch) | `catalog.json`, `memory/__init__.py` | Registers the three adapters above in `REGISTRY` and `catalog.json`. | No |
| [02-optional-hindsight](patches/02-optional-hindsight.patch) | `pyproject.toml`, `memory/__init__.py` | Drops the `hindsight-all` dependency and makes its import optional. `hindsight-all` has no Windows wheel, and we develop on Windows. | **Yes, indirectly**: it removes the `hindsight`, `hindsight-cloud` and `hindsight-http` providers from the registry, so this repo cannot reproduce Hindsight numbers. Use upstream AMB on Linux for those. |
| [03-locomo-session-order](patches/03-locomo-session-order.patch) | `dataset/locomo.py` | Sorts session keys numerically rather than lexicographically, so `session_2` is ingested before `session_10`. Also adds the `user_ids` parameter that `Dataset.load_documents` declares but LoCoMo did not implement. | **Yes**: it changes the order sessions are ingested in, for every provider. Results from this repo are not directly comparable with AMB runs that lack it. |
| [04-rag-context-tokens](patches/04-rag-context-tokens.patch) | `modes/rag.py` | When a provider supplies a custom answer prompt, stores that provider's structured payload as `context` instead of the rendered string. | **Yes**: `context_tokens`, and therefore the published `avg_context_tokens`, is derived from this field. |
| [05-provider-usage](patches/05-provider-usage.patch) | `runner.py` | Writes a provider's self-reported token usage into the report as `provider_usage`. | No, additive output only. |
| [06-vertex-gemini](patches/06-vertex-gemini.patch) | `llm/gemini.py` | Adds `GEMINI_BACKEND=vertex` to route Gemini through Vertex AI. AI Studio's per-tier daily request cap blocks a full run. | No, same models, different endpoint and quota. |
| [07-locomo-category-labels](patches/07-locomo-category-labels.patch) | `dataset/locomo.py` | Corrects the question-category names (see [above](#read-this-before-quoting-a-number)). Added after the published runs, which carry AMB's original labels. | No, labels only. Per-category figures from new runs will not line up with AMB reports that lack it. |

Patches 03, 04 and 07 look like upstream bugs to us rather than
benchmark-specific tweaks; we would rather they land in AMB than live here.

## Reproduce it

You need: Python >= 3.11, [uv](https://docs.astral.sh/uv/), git, Docker (only for
Mem0 OSS), a Recalld API key, and a Gemini API key (for answer + judge).

```bash
git clone https://github.com/bit-robotics/recalld-benchmarks
cd recalld-benchmarks
uv run python scripts/setup.py
```

Fill in your keys in `amb/.env` (created from [.env.example](.env.example)).
To reproduce the published configuration, also uncomment the block marked
"Published-run configuration" in that file: it sets the answer model, the judge
model and `RECALLD_ANSWER_CONTEXT=sources`. Without it AMB uses its own default
answerer and the adapter uses `facts` mode, which is a different experiment.
The published runs routed Gemini through Vertex AI because AI Studio's daily
request cap stops a full run partway; the `GEMINI_BACKEND=vertex` block in
`.env.example` shows how. An AI Studio key is enough for the validation gate and
single-conversation runs.

Check the adapters before spending any API budget:

```bash
cd amb
uv run --with pytest pytest tests -q
cd ..
```

Every command block in this README starts from the repo root.

### Running Mem0 OSS

Start the open-source Mem0 server following the [mem0 repository](https://github.com/mem0ai/mem0)
so it listens on `http://localhost:8888` (or set `MEM0_OSS_BASE_URL`). The adapter
targets server API v2.0.11.

- Set `AUTH_DISABLED=true` on the Mem0 server. The adapter sends no
  authentication header, so a server with auth enabled rejects its requests.
- Record server version/commit and extraction model in the run's `notes.md`.

### Validation gate: always run this first

Before any full run, test retrieval on a small slice:

```bash
cd amb
uv run omb run --dataset locomo --split locomo10 --memory recalld --mode rag --unit conv-30 --query-limit 5
cd ..
uv run python scripts/verify_retrievals.py recalld
```

For `recalld-recall`:

```bash
cd amb
uv run omb run --dataset locomo --split locomo10 --memory recalld-recall --mode rag --unit conv-30 --query-limit 5
cd ..
uv run python scripts/verify_retrievals.py recalld-recall --mode rag
```

Run the gate for each provider you intend to benchmark (`mem0-oss` works the same
way as `recalld`), and only continue when it passes.

A run whose retrieval silently returns nothing still produces a plausible-looking
score, because the answer model guesses or the judge accepts "I don't know".
`verify_retrievals.py` exits non-zero if any question got empty context,
including an empty source list; `summarize_results.py` lists such rows under the
totals.

### Evaluate custom context for one question

To score arbitrary plaintext (e.g. output from any memory tool) against a gold answer
without running ingestion or retrieval:

```bash
uv run python scripts/eval_context_file.py \
  --dataset locomo --split locomo10 --mode rag \
  --unit conv-30 --query-id conv-30_q0 \
  path/to/context.txt
```

### Recalld retrieval sweeps (ingest once, score all k/endpoint combos)

To compare `/memory/search` and `/memory/recall` at multiple
top-k values without re-ingesting the same conversation, use the sweep runner. It
ingests once on the first matrix entry, preserves Recalld agents, then runs fully
scored AMB experiments (answer + judge) for every combination.

```bash
# One conversation: ingest once, then run 8 fully scored AMB experiments
uv run python scripts/run_recalld_sweep.py --unit conv-30 --k 10 25 50 100

# Search endpoint only (smoke test)
uv run python scripts/run_recalld_sweep.py --unit conv-30 --k 10 --endpoints search --query-limit 5

# Resume unfinished combinations without re-ingesting
uv run python scripts/run_recalld_sweep.py --unit conv-30 --k 10 25 50 100 --resume --sweep-id <id>

# Explicitly remove only this sweep's preserved Recalld agents
uv run python scripts/run_recalld_sweep.py --sweep-id <id> --cleanup
```

Defaults: endpoints `search,recall`; k values `10,25,50,100`; dataset `locomo`;
split `locomo10`; mode `rag`. Each combination gets a unique AMB `--name` such as
`recalld-search-k25-<sweep-id>` and writes to
`amb/outputs/locomo/<name>/rag/locomo10.json`.

Sweep state (commands, accuracy, answer/judge models) is stored under
`experiments/sweeps/<sweep-id>/state.json`. Agent IDs are shared via
`experiments/sweeps/<sweep-id>/recalld-agents.json`.

Verify each sweep output independently:

```bash
uv run python scripts/verify_retrievals.py --name recalld-search-k25-<sweep-id> --mode rag
uv run python scripts/verify_retrievals.py --name recalld-recall-k50-<sweep-id> --mode rag
```

**Note:** AMB's published leaderboard numbers use each provider's default context
size (Recalld defaults to k=10). Sweep k values are an explicit ablation: record
endpoint, k, and `avg_context_tokens` from the output JSON when publishing.

### Full comparison runs

The published runs are one AMB run per conversation, ten per provider. Give each
its own `--name` so the reports do not overwrite each other:

```bash
cd amb
for unit in conv-26 conv-30 conv-41 conv-42 conv-43 conv-44 conv-47 conv-48 conv-49 conv-50; do
  uv run omb run --dataset locomo --split locomo10 --memory recalld-recall --mode rag \
    --unit "$unit" --name "recalld-recall-$unit"
done
cd ..
```

Swap `--memory recalld-recall` for `recalld` (search) or `mem0-oss`, and change
the `--name` prefix to match. Each report lands in
`amb/outputs/locomo/<name>/rag/locomo10.json`. Verify every one:

```bash
uv run python scripts/verify_retrievals.py --name recalld-recall-conv-26 --mode rag
```

Then copy the ten reports into one directory under [results/](results/) (see
[results/README.md](results/README.md)) and aggregate them:

```bash
uv run python scripts/summarize_results.py results/<run-dir>
```

This re-ingests every conversation. The published reports did not: they scored
stores built by earlier runs with `--skip-ingestion`, and we did not record the
Recalld server revision or prompt versions in use when those stores were built.
A fresh reproduction measures today's Recalld, not the August build, and will
not match question for question.

## Repository layout

```
overlay/    Files added to the AMB clone: provider adapters and their tests
patches/    Sequential patches applied to AMB, in filename order
scripts/    Setup, verification, sweeps and result aggregation
results/    Committed raw reports (gzipped) with per-run notes
amb/        The AMB clone itself: created by setup.py, never committed
```

## Corrections welcome

If you work on Mem0 or any compared system and believe a setting here
misrepresents your product, please open an issue or pull request. We will
re-run with corrected settings and publish new numbers alongside the old ones.
The same applies to our own numbers: if you can show a patch in `patches/`
biases a result, we want to know. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licences and attribution

**This repository** (adapters, patches, scripts, notes) is released under the
[MIT License](LICENSE), copyright Bit Robotics Ltd.

**LoCoMo** is by Adyasha Maharana, Dong-Ho Lee, Sergey Tulyakov, Mohit Bansal,
Francesco Barbieri and Yuwei Fang ([ACL 2024](https://arxiv.org/abs/2402.17753)),
and is licensed [CC BY-NC 4.0](https://github.com/snap-research/locomo/blob/main/LICENSE.txt).
This repository does not ship the dataset; AMB downloads it. The committed
reports do, however, reproduce parts of it: each question, its gold answer, and
the conversation excerpts the memory system retrieved for it. They are included
so that the published numbers can be verified, and are unmodified apart from
gzip compression. If you reuse the reports, the CC BY-NC 4.0 terms apply to that
content.

**AMB** is not vendored here and had no licence file at the pinned commit. The
files in `patches/` contain the minimal upstream context needed for `git apply`;
everything else in the harness is fetched from Vectorize's repository at setup
time. See [CITATION.cff](CITATION.cff) for how to cite all three.
