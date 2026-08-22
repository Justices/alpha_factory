"""Field Research Bounded Context - Domain Models & Aggregate Root."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class FieldSnapshot:
    """Immutable snapshot of a raw data field from the market platform catalog."""
    field_id: str
    dataset_id: str
    data_type: str = "MATRIX"  # MATRIX | VECTOR
    description: str = ""
    category: str = ""
    coverage: float = 1.0
    user_count: int = 0
    alpha_count: int = 0
    region: str = "GBR"
    delay: int = 1


@dataclass
class FieldProfile:
    """Enriched research profile of a field tracking quality, novelty, and sampling weight."""
    field_id: str
    dataset_id: str
    is_eligible: bool = True
    eligibility_reason: str = "PASS"
    coverage: float = 1.0
    crowding_score: float = 0.0  # High user_count / alpha_count -> crowded
    novelty_score: float = 1.0   # Low test count in local system -> novel
    historical_tests: int = 0
    historical_avg_sharpe: float = 0.0
    sampling_weight: float = 1.0
    tier: str = "Neutral"  # Alpha | Neutral | Noise | Crowded
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class FieldUniverse:
    """Aggregate Root: Owns the immutable snapshot and dynamic profiles of fields in a market."""
    region: str
    universe: str
    snapshots: Dict[str, FieldSnapshot] = field(default_factory=dict)
    profiles: Dict[str, FieldProfile] = field(default_factory=dict)
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def register_snapshot(self, snapshot: FieldSnapshot) -> None:
        self.snapshots[snapshot.field_id] = snapshot
        if snapshot.field_id not in self.profiles:
            self.profiles[snapshot.field_id] = FieldProfile(
                field_id=snapshot.field_id,
                dataset_id=snapshot.dataset_id,
                coverage=snapshot.coverage,
            )

    def get_eligible_fields(self) -> List[FieldProfile]:
        return [p for p in self.profiles.values() if p.is_eligible]

    def update_profile(self, profile: FieldProfile) -> None:
        self.profiles[profile.field_id] = profile
        self.version += 1
