# Research coverage and TS window implementation plan

Goal: execute the user's approved first revision of balanced exploration and evidence-driven TS windows, followed by at most 24 live simulations.

Architecture: preserve existing strategies and submission controls. Opt-in balanced scheduling uses task-local selected history, weighted exploration/optimization/validation shares, dataset/field/operator coverage and eight-result feedback. Raw first-order TS generation uses three coarse probes; adjacent successful probes unlock intermediate windows through the existing acceptance and provenance pipeline. No inferred field frequency or claimed OOS evidence.

Constraints: original database currently reports malformed; preserve it and use a new explicit experiment database for live evidence. No Alpha submission. Keep the prior assessment file. Use D:/quant-venv/Scripts/python.exe (system Python has an incomplete YAML module). User approval already covers the design and live testing; no additional design approval required.

- [ ] Add failing coverage tests: dense families must not hide other fields/datasets; selected history rotates to untested fields; validation gets reserved capacity; seed determinism; cohort <= 8.
- [ ] Add configurable coverage policy and a pure scheduler; integrate at the coordinator boundary; reserve budget using root catalog selections across restarts. Test with real temporary SQLite repository.
- [ ] Add failing TS tests: enabled strategy emits only probes; one isolated high metric does not trigger refinement; adjacent passes trigger only allowed untested intermediate windows; grouping isolates operators and scalarizations; disabled behavior unchanged.
- [ ] Add TS policy and feedback construction using existing candidate acceptance, canonical identity, and provenance. Persist refinements without overwriting initial strategy totals.
- [ ] Fix prerequisite bounded error-result/incomplete-result retries and validation queue evidence preservation, with regression tests.
- [ ] Check field loading cap: make limited scope selection represent datasets instead of stopping at the first large file, and preserve explicit frequency metadata only.
- [ ] Run targeted tests then full suite once, review diff, and record exact outcomes.
- [ ] Run production coordinator on a frozen exact-scope two-field/two-TS-operator probe cohort, at most three eight-expression rounds in an isolated experiment DB. Save raw results to disk, run brain_sim_summary.py summarize, report only decisions and coverage. If a real external blocker prevents execution, retain evidence and report the limitation rather than claiming production success.

Acceptance: deterministic coverage improves versus sorted-prefix baseline under equal budget; no restored task can reissue its full budget; refinements require adjacent evidence; errors terminate; existing evidence survives repeated enqueue; live evidence distinguishes actual completed simulations from local tests and pending runs. Timing metadata and cross-period stability remain future evidence, not synthesized by this revision.
