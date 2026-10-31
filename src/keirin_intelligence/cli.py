"""`keirin` command: predict / note / freeze / evaluate on hand-entered race cards.

Nothing here downloads data, places bets or posts to note.com.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from keirin_intelligence import ledger
from keirin_intelligence.evaluation import walk_forward
from keirin_intelligence.model import LineAwareModel
from keirin_intelligence.note import render_note
from keirin_intelligence.racecard import default_velodromes, load_cards, load_results


def _model(data_dir: Path, weights_path: Path | None) -> LineAwareModel:
    path = weights_path or data_dir / "weights.json"
    if path.exists():
        return LineAwareModel(json.loads(path.read_text(encoding="utf-8")), default_velodromes())
    return LineAwareModel(venues=default_velodromes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="keirin")
    parser.add_argument("--data", type=Path, default=Path("data/real"),
                        help="folder with races.csv / entries.csv / results.csv")
    parser.add_argument("--weights", type=Path, help="weights.json (default: <data>/weights.json)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("predict", "note", "freeze"):
        p = sub.add_parser(name)
        p.add_argument("race_id")
    sub.choices["note"].add_argument("--out", type=Path)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--min-train", type=int, default=100)
    fit = sub.add_parser("fit")
    fit.add_argument("--before", help="only use races dated before YYYY-MM-DD")
    args = parser.parse_args(argv)

    cards = load_cards(args.data)
    results = load_results(args.data)
    ledger_path = args.data / "ledger.jsonl"
    model = _model(args.data, args.weights)

    if args.command in ("predict", "note", "freeze"):
        card = cards[args.race_id]
        pred = model.predict(card)
        if args.command == "predict":
            for car in pred.ranked():
                print(f"{car}: win {pred.win[car]:.3f}  top3 {pred.top3[car]:.3f}")
        elif args.command == "note":
            text = render_note(
                card, pred, track_record=ledger.track_record(ledger_path, results),
                venue=default_velodromes().get(card.venue),
            )
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(text, encoding="utf-8")
                print(f"draft written: {args.out}")
            else:
                print(text)
        else:
            row = ledger.freeze(ledger_path, card, pred, model.weights, datetime.now(UTC))
            print(f"frozen {args.race_id} sha256={row['sha256']}")
    elif args.command == "evaluate":
        for board in walk_forward(
            cards, results, min_train_races=args.min_train, venues=default_velodromes()
        ):
            print(json.dumps(board.summary(), ensure_ascii=False))
    elif args.command == "fit":
        data = [(cards[r], res) for r, res in results.items() if r in cards and res.order
                and (args.before is None or cards[r].race_date.isoformat() < args.before)]
        fitted = LineAwareModel(venues=default_velodromes()).fit(data)
        out = args.weights or args.data / "weights.json"
        out.write_text(json.dumps(fitted.weights, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"fitted on {len(data)} races -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
