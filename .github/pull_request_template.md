**What this changes**

**Checklist**

- [ ] `uv run python scripts/setup.py` succeeds from a clean checkout
- [ ] `cd amb && uv run --with pytest pytest tests -q` passes
- [ ] If `patches/` changed: the whole stack applies to a pristine clone, and the
      README patch table (including "Affects scoring?") is updated
- [ ] If `results/` changed: `uv run python scripts/summarize_results.py` passes
      and the run has a `notes.md`
- [ ] No API keys, `.env` files or service-account keys in the diff
