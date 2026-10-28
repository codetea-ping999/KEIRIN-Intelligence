from datetime import UTC, datetime, timedelta

import pytest

from keirin_intelligence.domain import DataLicense, FeatureObservation, Race
from keirin_intelligence.governance import GateRejected, validate_prediction_inputs

T = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
R = Race("test", "fake", T + timedelta(hours=1))
UNVERIFIED = DataLicense("unverified source", "unverified")
APPROVED = DataLicense(
    "approved licensed source", "approved",
    True, True, True, T + timedelta(days=30), "signed-001",
)


def observation(license=UNVERIFIED, observed=T, ingested=T, synthetic=False):
    return FeatureObservation("dummy", observed, ingested, license, synthetic)


def test_reject_future_observed_data():
    with pytest.raises(GateRejected, match="future"):
        validate_prediction_inputs(R, T, [observation(observed=T + timedelta(seconds=1))])


def test_reject_late_ingestion_even_if_observed_earlier():
    with pytest.raises(GateRejected, match="late-arriving"):
        validate_prediction_inputs(R, T, [observation(ingested=T + timedelta(seconds=1))])


def test_reject_prediction_after_cutoff():
    with pytest.raises(GateRejected, match="cutoff"):
        validate_prediction_inputs(R, T + timedelta(hours=1), [observation()])


def test_commercial_unverified_license_fails():
    with pytest.raises(GateRejected, match="not approved"):
        validate_prediction_inputs(R, T, [observation()], commercial=True)


def test_commercial_synthetic_fails_even_approved():
    with pytest.raises(GateRejected, match="synthetic"):
        validate_prediction_inputs(R, T, [observation(license=APPROVED, synthetic=True)], commercial=True)


def test_approved_non_synthetic_passes_commercial_guard():
    validate_prediction_inputs(R, T, [observation(license=APPROVED)], commercial=True)


def test_expired_license_rejected():
    expired = DataLicense("expired source", "approved", True, True, True, T, "contract-001")
    with pytest.raises(GateRejected, match="expired"):
        validate_prediction_inputs(R, T, [observation(license=expired)], commercial=True)


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        Race("bad", "bad", datetime(2026, 10, 28, 11, 0))


def test_missing_observations_rejected():
    with pytest.raises(GateRejected, match="without provenance"):
        validate_prediction_inputs(R, T, [])
