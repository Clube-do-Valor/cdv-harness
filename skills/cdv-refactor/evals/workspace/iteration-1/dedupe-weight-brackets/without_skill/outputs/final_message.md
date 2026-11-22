Both files now use one shared function, `bracket_price`, in `shipping/brackets.py`, and no price changed. It is one commit on `main`, `84a0141`.

**The two copies were not identical.** `quote.py` priced exactly 10 kg in the 20.0 bracket (`weight_kg < 10`). `label.py` priced it in the 14.0 bracket (`weight_kg <= 10`). So `quote(10, "domestic")` is 27.5 and `label_cost(10)` is 15.25. One plain shared function would have changed one of them.

I kept both behaviours. `bracket_price(weight_kg, *, ten_kg_in_heavy_bracket=False)` has a flag, and `quote` passes `True`.

**Checking.** I compared 13 weights, including the bracket edges and 10 kg, across 5 zones with express on and off, plus label costs. The outputs were byte-identical before and after. The 7 existing tests pass. I added `tests/test_brackets.py`, which pins the bracket edges and the 10 kg difference. All 9 tests pass.

**Questions for you:**
1. **Is the 10 kg difference intended?** Customers pay 27.5 for a 10 kg parcel while we pay the carrier 15.25 for its label, which looks like a bug in one of the two. Once you confirm which copy is right, the flag can be deleted and both callers share one rule. That would change prices, so I left it.
2. **`quote.py` has a bug I did not touch.** `if zone == "intl" or "INTL":` is always true, so the 7.5 international surcharge is added in every zone, including `domestic` and `eu`. Fixing it changes quoted prices, so it needs your decision and probably a QA pass. It almost certainly should be `zone == "intl"`.

The `README.md` says to run tests with `python3 -m unittest discover -s tests`, and that is what I used. I did not add the new module to the README.
