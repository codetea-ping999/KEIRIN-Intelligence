"""Run a reproducible fake-race demonstration with no network dependencies."""

from datetime import UTC, datetime, timedelta

from keirin_intelligence.baseline import ordered_pair_probability, rating_softmax
from keirin_intelligence.domain import DataLicense, FeatureObservation, Race, RiderEntry
from keirin_intelligence.governance import validate_prediction_inputs
from keirin_intelligence.reporting import render_synthetic_draft


def main() -> None:
    asof = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
    race = Race("SYNTHETIC-R001", "架空バンク 7R", asof + timedelta(minutes=50))
    dummy_license = DataLicense("SYNTHETIC_FIXTURES", permission_status="unverified")
    observations = [
        FeatureObservation(
            "fixture-rating", asof - timedelta(hours=2),
            asof - timedelta(hours=1), dummy_license, synthetic=True,
        )
    ]
    validate_prediction_inputs(race, asof, observations, commercial=False)
    entries = [
        RiderEntry(1, "架空選手A", 95.0),
        RiderEntry(2, "架空選手B", 92.0),
        RiderEntry(3, "架空選手C", 87.0),
        RiderEntry(4, "架空選手D", 83.0),
        RiderEntry(5, "架空選手E", 91.0),
        RiderEntry(6, "架空選手F", 84.0),
        RiderEntry(7, "架空選手G", 89.0),
    ]
    scores = rating_softmax(entries)
    print(render_synthetic_draft(race, entries, scores, asof))
    example = ordered_pair_probability(scores, 1, 5)
    print(f"\n検算用（合成データのみ）：1→5 の順序付き確率スコア = {example:.5f}")


if __name__ == "__main__":
    main()
