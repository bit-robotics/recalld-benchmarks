# Contributing

This repository exists so that our published memory-benchmark numbers can be
checked by people who have no reason to trust us. Corrections are the most
valuable contribution you can make.

## Disclosure

Recalld publishes this repository and Recalld is one of the systems measured in
it. If you find a way in which the setup flatters Recalld, that is a bug and we
want the issue.

## Especially welcome

- **A misconfigured competitor.** If you work on Mem0 or any other compared
  system and a setting here misrepresents it, open an issue with the correct
  configuration. We will re-run and publish the new numbers alongside the old
  ones rather than replacing them.
- **A biased patch.** Every patch in [`patches/`](patches/) is described in the
  README, including whether it can affect scoring. If one of them shifts results
  in Recalld's favour, show it and we will drop or fix it.
- **A run we have not done.** `mem0-oss` has an adapter but no published run.

## Before opening a pull request

```bash
uv run python scripts/setup.py
cd amb && uv run --with pytest pytest tests -q
```

If you change anything under `results/`:

```bash
uv run python scripts/summarize_results.py
```

## Changing the AMB patches

Do not edit files under `amb/` and commit the result: that directory is a
gitignored clone and its contents are never published. Instead:

1. Make the change in a clean clone at the pinned commit.
2. Regenerate the patch with `git diff` and save it into `patches/` with the next
   numeric prefix, keeping one concern per patch.
3. Verify the whole stack still applies to a pristine clone:

```bash
git clone https://github.com/vectorize-io/agent-memory-benchmark /tmp/amb-check
git -C /tmp/amb-check checkout aa9273ab9e34bbeaff3c6ef2f694142a552d5b22
cp -r overlay/src/. /tmp/amb-check/src/
for p in patches/*.patch; do git -C /tmp/amb-check apply "$p" || echo "FAILED: $p"; done
```

4. Update the patch table in the README, including the "Affects scoring?" column.

Patches are applied in filename order and the stack is sequential, so a patch
whose context depends on an earlier one must sort after it.

## Adding a benchmark run

Runs are only published with a `notes.md` recording the configuration. See
[results/README.md](results/README.md) for the required fields. A run with no
notes cannot be interpreted later and will not be merged.

Always run the validation gate described in the README before a full run. A run
whose retrieval silently returned nothing still produces a plausible score.

## Secrets

Never commit `amb/.env`, a service-account key file, or any real API key. The
`.gitignore` covers the usual filenames, but check `git diff --cached` before
pushing. If a key is exposed, rotate it first and rewrite history second.

## Reporting a security issue

See [SECURITY.md](SECURITY.md).
