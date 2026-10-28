"""Small, dependency-free domain types for an auditable research baseline."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


def require_aware(value: datetime, name: str) -> None:
    """Reject naive datetimes; store absolute times, display in JST at presentation time."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class DataLicense:
    name: str
    permission_status: Literal["unverified", "approved", "expired", "revoked"]
    allowed_training: bool = False
    allowed_derived_sales: bool = False
    allowed_storage: bool = False
    expires_at: datetime | None = None
    agreement_reference: str | None = None

    def __post_init__(self) -> None:
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")


@dataclass(frozen=True)
class FeatureObservation:
    name: str
    observed_at: datetime
    ingested_at: datetime
    license: DataLicense
    synthetic: bool = False

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        require_aware(self.ingested_at, "ingested_at")


@dataclass(frozen=True)
class Race:
    race_id: str
    label: str
    betting_cutoff_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.betting_cutoff_at, "betting_cutoff_at")


@dataclass(frozen=True)
class RiderEntry:
    car_number: int
    label: str
    rating: float

    def __post_init__(self) -> None:
        if not 1 <= self.car_number <= 9:
            raise ValueError("car_number must be between 1 and 9")
