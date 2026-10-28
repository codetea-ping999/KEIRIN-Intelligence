"""Fail-closed data provenance and timing checks (research scaffold, not legal advice)."""

from datetime import datetime

from keirin_intelligence.domain import DataLicense, FeatureObservation, Race, require_aware


class GateRejected(ValueError):
    """Safety or provenance gate refused the requested operation."""


def require_commercial_rights(license: DataLicense, when: datetime) -> None:
    """No production sale/training/storage unless the supplier is explicitly approved."""
    require_aware(when, "when")
    if license.permission_status != "approved":
        raise GateRejected("commercial data permission is not approved")
    if not all((license.allowed_training, license.allowed_derived_sales, license.allowed_storage)):
        raise GateRejected("commercial training / derivative sale / storage permission missing")
    if license.expires_at is not None and when >= license.expires_at:
        raise GateRejected("commercial data license expired")
    if not license.agreement_reference:
        raise GateRejected("written agreement reference missing")


def validate_prediction_inputs(
    race: Race,
    prediction_asof_at: datetime,
    observations: list[FeatureObservation],
    *,
    commercial: bool = False,
) -> None:
    """Research may process synthetic fixtures; commercial use must never do so."""
    require_aware(prediction_asof_at, "prediction_asof_at")
    if prediction_asof_at >= race.betting_cutoff_at:
        raise GateRejected("prediction must precede betting cutoff")
    if not observations:
        raise GateRejected("cannot predict without provenance-bearing observations")
    for obs in observations:
        if obs.observed_at > prediction_asof_at or obs.ingested_at > prediction_asof_at:
            raise GateRejected(f"future or late-arriving observation: {obs.name}")
        if commercial:
            if obs.synthetic:
                raise GateRejected("synthetic observations cannot be used commercially")
            require_commercial_rights(obs.license, prediction_asof_at)
