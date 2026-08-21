# Super Alpha Design

## Goal

Create, persist, submit, and poll small Super Alpha research batches from the
project's existing SQLite ledger without adding credentials, MySQL, or automatic
submission.

## Scope

The component reads regular-alpha records from `alpha_details`, applies explicit
quality gates, and produces a bounded set of distinct `(selection, combo)`
templates.  A canonical hash covers the component pool, template text, and full
settings.  Each candidate is stored as a `super_alpha_candidates` row before
any platform request.  Super Alpha simulations use the existing durable
`simulation_batches` lifecycle, whose rows gain a `simulation_type` and a
structured task payload so that both REGULAR and SUPER requests are recoverable.

The initial template library contains an equal-weight baseline, a `combo_a`
variant, and internal-correlation penalty variants, together with quality,
turnover, and hard correlation selection families.  The generator prioritizes
structurally different combinations and limits a requested batch to 4--6
candidates by default.

## Non-goals

No account credentials are stored. No raw HTTP client is introduced. No Super
Alpha is submitted to production automatically. Pairwise PnL-correlation graph
selection is deferred until enough Super Alpha PnL records have been collected.

## Interfaces

`SuperAlphaConfig` contains source gates, template names, and the maximum batch
size. `build_super_candidates(database, config, settings)` returns durable,
deduplicated candidate dictionaries. `super_simulation_payload(candidate,
settings)` returns the BRAIN `type=SUPER` request object. `alpha_machine`
exposes `prepare-super`, `simulate-super --execute`, and `poll-super` using the
same managed BRAIN client and `data/alpha_research.db` default as regular
simulation.

## Verification

Tests prove candidate filtering, canonical deduplication, bounded diversity,
payload construction, and persistence of SUPER batch/result type.  A fresh
schema snapshot and migration are updated whenever tables or columns change.
