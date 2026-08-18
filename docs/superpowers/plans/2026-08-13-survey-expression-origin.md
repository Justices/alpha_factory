# Survey Expression Origins Implementation Plan

**Goal:** Run both fixed unary templates and generic first-order operators during Survey, and persist their origin in `alpha_expressions`.

**Architecture:** Give every generated `Task` an `expression_origin` (`unary_template`, `first_order`, or `semantic_pair`). Survey concatenates the two single-field task families before cataloging and sampling. SQLite stores the origin in a dedicated migration-safe column while retaining existing JSON metadata.

### Task 1: Add regression tests

- [ ] Assert fixed unary and generic first-order factories assign distinct origins.
- [ ] Assert `alpha_expressions.expression_origin` is created for a new database and populated by cataloging.
- [ ] Assert existing databases without the column are migrated safely.

### Task 2: Propagate expression origin

- [ ] Add `expression_origin` to `Task` and set it in all relevant factories.
- [ ] Include origin in task JSON and simulated-result metadata.
- [ ] Update `alpha_expressions` schema, migration guard, insert/upsert handling, and catalog APIs.

### Task 3: Make Survey exhaustive across first-level families

- [ ] Generate both `unary_factory(scalars)` and `first_order_task_factory(scalars)` whenever `--unary` is enabled.
- [ ] Catalog both with their supplied origins, then apply `--backtest-sample` only as an explicit budget cap.
- [ ] Run the framework test suite and a local dry-run using the fields fixture.
