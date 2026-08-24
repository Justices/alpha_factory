# Recovery Runbook

All commands load the single `storage` section from `configs/alpha-factory.yaml` (or the file passed with `--config`). Do not pass database paths on the command line.

## Before an upgrade (SQLite)

Stop workers, then create a consistent backup before applying a code upgrade:

```powershell
& 'D:\quant-venv\Scripts\python.exe' alpha_machine.py storage-backup --destination D:\backups\alpha-research-before-upgrade.db --config configs/alpha-factory.yaml
```

The command rejects non-SQLite storage and an existing destination. Keep the backup outside the live database directory.

## Upgrade and rollback

Start any research command with the new release. It applies ordered migrations recorded in `schema_migrations`; a checksum mismatch stops the process before research work begins.

If the upgrade must be rolled back, stop all workers and run `alpha_machine.py storage-restore --backup D:\backups\alpha-research-before-upgrade.db --config configs/alpha-factory.yaml`. Restart with the previous release and verify with `alpha_machine.py init-db --verify --config configs/alpha-factory.yaml`.

## Incident drills

```powershell
# Rebuild projections only; no platform call
& 'D:\quant-venv\Scripts\python.exe' alpha_machine.py research-rebuild --round-id <round-id> --config configs/alpha-factory.yaml

# Process currently due batches once
& 'D:\quant-venv\Scripts\python.exe' alpha_machine.py research-worker --watch --poll-seconds 30 --config configs/alpha-factory.yaml

# Dispatch only previously approved submissions
& 'D:\quant-venv\Scripts\python.exe' alpha_machine.py submission-dispatch --config configs/alpha-factory.yaml
```

For a platform 429 or timeout, leave the worker running: task retry state is durable and uses bounded backoff. For a submission failure, inspect the outbox and evidence record; do not resubmit manually without a valid, unexpired receipt-backed evidence record.
