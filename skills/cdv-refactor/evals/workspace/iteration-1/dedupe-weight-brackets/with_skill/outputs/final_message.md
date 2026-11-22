Nothing about prices changed. Both commits are on `main`.

**Commits**
- `57126aa` adds `tests/test_bracket_characterization.py`. It pins `quote` and `label_cost` at every bracket edge, across all zones and express on/off. It passed on the old code.
- `d8e7b6c` adds `shipping/brackets.py` with `bracket_price(weight_kg, *, ten_kg_is_mid)`, and both files now call it.

**Checks**
- The record passed unchanged after the move, and the full suite is green.
- I flipped the flag in `quote.py` as a test. Exactly the 11 subtests at 10 kg went red. I reverted it before committing.

**The tables were not identical, so I kept the difference.** At exactly 10 kg:
- `quote` priced it at 20.0, because it uses `< 10`.
- `label_cost` priced it at 14.0, because it uses `<= 10`.

A single plain function would have changed one of the two prices at 10 kg. The shared function takes the 10 kg edge as an argument (`quote` passes `False`, `label` passes `True`) so both behave exactly as before. I did not pick which one is correct.

**Existing bug, not fixed:** in `shipping/quote.py`, `if zone == "intl" or "INTL":` is always true. The 7.5 international surcharge is therefore added to every zone, including `domestic` and `eu`. The characterization test pins this as it is. Both findings are in `docs/research/2026-11-22-shared-brackets/bugs.md`.

**Questions for you**
1. What should 10 kg cost? If the two should agree, say which one wins. Then the `ten_kg_is_mid` argument can go. That is a price change, so it needs its own change and QA.
2. Do you want the intl surcharge bug fixed? It would lower the price for every domestic and EU quote. It also needs its own change and QA, not a no-op merge.

**Skipped:** the skill's full state folder, ratchets and verifier. This repo has no extension, no verifier role and no counters. The slice is tiny, so I used only the record-first, then move, then prove steps. The profile sets `role_builder` and `role_verifier` to `none`, so no independent verifier ran either.

Since 10 kg prices differ today, treat this as no-op only for behaviour. If the business intent was a single table, the two questions above come first.
