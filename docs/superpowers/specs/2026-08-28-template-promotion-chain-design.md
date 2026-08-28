# Template Promotion Chain Design

## Goal

Complete the template-promotion feedback loop with `template_library` as the only source of truth:

1. qualified backtest results are distilled into structural templates;
2. repeated promotions merge evidence idempotently;
3. promoted templates survive restart;
4. the explicit `database_template` construction strategy consumes them;
5. the obsolete `template_promotions` repository and its test are removed.

## Architecture

The worker continues to call `distill_templates()` after evaluation. Instead of writing to a second SQLAlchemy projection, it writes each `DistilledTemplate` through `AlphaDatabase.save_abstracted_template()`. The method stores the deterministic `evolved_<hash>` row in `template_library` and merges promotion evidence into `source_json`.

`template_library` remains the single catalog read by `ResearchLoopCoordinator.prepare()`. Its active rows are passed into `ConstructionContext`; `DatabaseTemplateStrategy` selects and renders the promoted template through the same AST validation, structural measurement, deduplication, provenance, and quota pipeline as static templates.

## Evidence Semantics

For one deterministic template identity:

- `source.type` remains `autonomous_distillation`;
- `source.support` is the size of the union of known source task IDs, not a sum of repeated writes;
- `source.source_task_ids` is a sorted unique list;
- repeated promotion of the same task IDs is a no-op;
- new task IDs extend the evidence and update support;
- the first non-empty example expression is preserved unless an explicit overwrite is requested.

Legacy evolved rows that contain only a numeric support value remain readable. A new promotion upgrades them to the structured evidence shape without deleting their prior support claim; because legacy rows lack identities for that prior evidence, their support is retained as a lower bound.

## Error Handling

- Empty expression templates are rejected without writing.
- Invalid or missing source task IDs are ignored after normalization.
- Promotion persistence failure is not silently replaced by an in-memory repository.
- The worker emits `TEMPLATE_PROMOTED` only after the catalog write succeeds.
- No second `template_promotions` table or compatibility repository is restored.

## Verification

Tests will prove:

- repeated promotion is idempotent;
- distinct source tasks merge and survive a database reopen;
- the worker passes complete promotion evidence to the catalog;
- `database_template` generates a candidate from a promoted row;
- schema migration does not recreate `template_promotions`;
- full test collection no longer imports `SqlAlchemyTemplatePromotionRepository`.

Production code will be completed before tests are added or run, followed by one final commit.
