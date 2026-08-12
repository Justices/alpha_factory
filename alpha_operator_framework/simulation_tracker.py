"""Durable submission and polling for BRAIN multi-simulation batches."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from .database import AlphaDatabase, persist_workflow_row


Submit = Callable[[list[dict[str, Any]]], str]
Fetch = Callable[[str], tuple[dict[str, Any], float]]
Detail = Callable[[str], dict[str, Any]]


class SimulationTracker:
    """Submit once, persist platform identity, then poll an existing batch."""

    def __init__(self, database: AlphaDatabase, *, submit: Submit, fetch: Fetch, detail: Detail) -> None:
        self.database = database
        self.submit_request = submit
        self.fetch_progress = fetch
        self.fetch_detail = detail

    def submit(self, tasks: Sequence[dict[str, Any]], settings: dict[str, Any]) -> int:
        """Create a local batch, submit it once, and save its platform Location."""
        batch_id = self.database.create_simulation_batch(list(tasks), settings)
        try:
            location = self.submit_request(list(tasks))
            platform_batch_id = location.rstrip("/").split("/")[-1]
            self.database.attach_platform_batch(batch_id, platform_batch_id, location)
            return batch_id
        except Exception as error:
            self.database.record_simulation_progress(batch_id, {}, status="failed", error_message=str(error))
            raise

    def submit_existing(self, batch_id: int) -> int:
        """Submit a created batch exactly once; an existing Location is never reposted."""
        batch = self.database.get_simulation_batch(batch_id)
        if not batch:
            raise ValueError(f"simulation batch does not exist: {batch_id}")
        if batch.get("platform_location"):
            return batch_id
        tasks = [
            {"expression": row["expression"], "decay": row["decay"]}
            for row in self.database.get_simulation_results(batch_id)
        ]
        location = self.submit_request(tasks)
        self.database.attach_platform_batch(batch_id, location.rstrip("/").split("/")[-1], location)
        return batch_id

    def poll(self, batch_id: int) -> dict[str, Any]:
        """Poll a persisted platform batch once and store every completed child."""
        batch = self.database.get_simulation_batch(batch_id)
        if not batch:
            raise ValueError(f"simulation batch does not exist: {batch_id}")
        if batch["status"] == "completed":
            return batch
        location = batch.get("platform_location")
        if not location:
            raise ValueError(f"simulation batch {batch_id} has not been submitted")
        progress, _retry_after = self.fetch_progress(location)
        self.database.record_simulation_progress(batch_id, progress)
        children = progress.get("children") if isinstance(progress, dict) else []
        if not isinstance(children, list):
            children = []
        results = self.database.get_simulation_results(batch_id)
        for sequence_no, child_url in enumerate(children[:len(results)]):
            child, _ = self.fetch_progress(child_url)
            alpha_id = child.get("alpha") if isinstance(child, dict) else None
            if not alpha_id:
                self.database.record_simulation_result(batch_id, sequence_no, status="running", child_url=child_url)
                continue
            details = self.fetch_detail(str(alpha_id))
            self.database.record_simulation_result(
                batch_id, sequence_no, status="completed", alpha_id=str(alpha_id), child_url=child_url, result=details,
            )
            settings = _decode_settings(batch.get("settings_json"))
            persist_workflow_row(self.database, {**details, "alpha_id": str(alpha_id)}, settings, stage="simulation")
        return self.database.get_simulation_batch(batch_id) or batch


def _decode_settings(raw: str | None) -> dict[str, Any]:
    import json
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


__all__ = ["SimulationTracker"]
