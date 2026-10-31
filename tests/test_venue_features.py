from dataclasses import replace
from pathlib import Path

from keirin_intelligence.model import PRIOR_WEIGHTS, LineAwareModel, race_features
from keirin_intelligence.note import render_note
from keirin_intelligence.racecard import default_velodromes, load_cards, load_velodromes

ROOT = Path(__file__).resolve().parents[1]
CARD = load_cards(ROOT / "data" / "templates")["EXAMPLE-0001"]
VENUES = default_velodromes()


def at(venue: str, **kw):
    return replace(CARD, venue=venue, **kw)


def nige_win(card, venues=VENUES):
    pred = LineAwareModel(venues=venues).predict(card)
    return pred.win[4]  # car 4 is the 逃 leader of the strongest line


def test_velodrome_table_is_complete():
    assert len(VENUES) == 43
    assert VENUES["小田原"].straight_m == 36.1 and VENUES["大宮"].straight_m == 66.7
    assert VENUES["千葉"].straight_m is None and VENUES["前橋"].indoor
    assert load_velodromes(ROOT / "data" / "reference" / "velodromes.csv") == VENUES


def test_short_straight_favours_front_runner_over_long_straight():
    assert nige_win(at("小田原")) > nige_win(at("大宮"))


def test_unknown_venue_has_no_bank_effect():
    assert nige_win(CARD) == nige_win(at("架空バンク"))
    assert all(f["bank_nige"] == 0.0 for f in race_features(CARD, VENUES).values())


def test_back_headwind_hurts_front_runner_and_tailwind_helps():
    calm = nige_win(at("立川"))
    assert nige_win(at("立川", back_wind_mps=8.0)) < calm < nige_win(at("立川", back_wind_mps=-8.0))


def test_home_prefecture_rider_gets_local_flag():
    feats = race_features(at("京王閣"), VENUES)  # 東京都; cars 1 and 6 are 東京 in the template
    assert feats[1]["local"] == 1.0 and feats[6]["local"] == 1.0 and feats[2]["local"] == 0.0


def test_old_weights_without_new_keys_still_load():
    legacy = {k: v for k, v in PRIOR_WEIGHTS.items() if k in ("score_z", "follow")}
    model = LineAwareModel(legacy, VENUES)
    assert model.weights["bank_nige"] == 0.0 and model.weights["follow"] == legacy["follow"]


def test_note_mentions_bank_and_wind():
    card = at("小田原", back_wind_mps=7.0, wet=True)
    pred = LineAwareModel(venues=VENUES).predict(card)
    text = render_note(card, pred, venue=VENUES["小田原"])
    assert "みなし直線 36.1m" in text and "バック向かい風" in text and "濡れています" in text
