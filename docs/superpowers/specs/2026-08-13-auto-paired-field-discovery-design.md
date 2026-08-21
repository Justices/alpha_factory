# Automatic Paired Field Discovery Design

## Goal

After field retrieval, discover high-confidence economic field groups that are
suitable for binary base signals.  Discovered pairs are added to Survey without
requiring a user-supplied `--pair`; explicit pairs remain supported as additions.

## Scope

The discovery rule is deliberately strict.  It only groups fields in the same
dataset and only when the field IDs share an exact normalized key.

1. Revision trio: `<key>_raisednum_<window>`, `<key>_lowerednum_<window>`, and
   `<key>_num` become `net_revision:left:right:normalizer`.
2. Dispersion trio: `<key>_high`, `<key>_low`, `<key>_mean` become
   `spread:left:right:normalizer`.
3. No fuzzy cross-dataset matching, cross-window matching, or automatic generic
   ratios are allowed.

The generated base expression is preprocessed and submitted to Survey directly.
Grouped fields do **not** enter the generic first-order path or fixed unary
template path: their economic relationship is already represented by the
binary base expression.  Ordinary ungrouped fields retain the existing unary
and first-order exploration workflow.

## Interfaces and Metadata

`discover_pair_specs(fields) -> list[PairSpec]` returns deterministic,
deduplicated pair specifications.  `PairSpec` gains `source` with values
`"auto"` or `"explicit"`.

All paired tasks use `expression_origin="paired_base"` and retain
`pair_kind`, `pair_stage="base"`, and `base_fields` metadata, with an
additional `pair_source`.  Explicit
`--pair` values are appended after auto-discovered pairs; duplicate logical
specifications are emitted once.

## Error Handling

Automatic discovery simply returns no pair when a complete exact trio is not
present.  Explicit pair validation remains strict and reports missing fields,
incompatible types, and mixed datasets.

## Verification

Unit tests cover discovery of a revision trio and a high/low/mean trio,
rejecting cross-dataset and incomplete groups, metadata propagation,
deduplication with explicit input, and the absence of paired first-order or
paired unary tasks.  A local dry-run against GBR/TOP700 analyst7 must produce
automatic paired base tasks without platform access.
