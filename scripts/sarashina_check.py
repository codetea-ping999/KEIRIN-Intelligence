"""Connectivity + quality check for Sarashina (SB Intuitions) as a commentary writer.

Usage (key comes from the environment only; never put it in code, files or commits):

    export SARASHINA_API_KEY=...            # from https://chat.sarashina.ai/dashboard/api-keys
    python scripts/sarashina_check.py [--model sarashina3-nano] [--data data/templates]

It sends ONLY the fictional template race (or a card you pass) and asks for a short
展開解説. The free beta terms say inputs may be used for training and that personal
information must not be sent, so keep real names of private persons out of prompts.
The reply is checked for guarantee wording and for numbers not present in the input.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from keirin_intelligence.model import LineAwareModel
from keirin_intelligence.note import BANNED_PHRASES
from keirin_intelligence.racecard import default_velodromes, load_cards

BASE_URL = "https://api.sarashina.ai/v1/chat/completions"
SYSTEM = (
    "あなたは競輪のデータ分析記事の解説担当です。与えられた数値だけを根拠に、"
    "3〜4文の日本語で展開を説明してください。的中や利益を保証する表現、"
    "買い目の断定、数値の創作は禁止です。『〜と推定されます』のように控えめに書いてください。"
)


def build_prompt(card, pred, venue) -> str:
    by_car = {e.car_number: e for e in card.entries}
    rows = [
        f"{c}番 {by_car[c].name}（{by_car[c].rider_class}・得点{by_car[c].score:.2f}・{by_car[c].style}）"
        f" 1着率{pred.win[c]:.1%} 3着内率{pred.top3[c]:.1%}"
        for c in pred.ranked()
    ]
    bank = f"{venue.name} みなし直線{venue.straight_m}m" if venue and venue.straight_m else "バンク情報なし"
    return "\n".join([f"並び: {card.formation()}", f"バンク: {bank}", "出走と推定確率:", *rows,
                      "", "この情報だけで展開を解説してください。"])


def check_reply(prompt: str, reply: str) -> list[str]:
    """Problems found in the model's reply (empty list = passes our guards)."""
    problems = [f"保証・断定表現: {p}" for p in BANNED_PHRASES if p in reply]
    allowed = set(re.findall(r"\d+(?:\.\d+)?", prompt))
    invented = [n for n in re.findall(r"\d+(?:\.\d+)?", reply) if n not in allowed]
    if invented:
        problems.append(f"入力にない数値: {sorted(set(invented))}")
    if not reply.strip():
        problems.append("空の応答")
    return problems


def call(api_key: str, model: str, prompt: str, retries: int = 4) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "max_completion_tokens": 400,
    }).encode()
    delay = 10.0  # free tier: 6 req/min on mini, no Retry-After header
    for attempt in range(retries + 1):
        req = urllib.request.Request(BASE_URL, data=body, headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            detail = err.read().decode(errors="replace")[:300]
            raise SystemExit(f"HTTP {err.code}: {detail}") from None
    raise SystemExit("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sarashina3-nano")
    parser.add_argument("--data", type=Path, default=Path("data/templates"))
    parser.add_argument("--race-id", default="EXAMPLE-0001")
    args = parser.parse_args()
    api_key = os.environ.get("SARASHINA_API_KEY")
    if not api_key:
        print("SARASHINA_API_KEY is not set", file=sys.stderr)
        return 2
    venues = default_velodromes()
    card = load_cards(args.data)[args.race_id]
    pred = LineAwareModel(venues=venues).predict(card)
    prompt = build_prompt(card, pred, venues.get(card.venue))
    started = time.time()
    data = call(api_key, args.model, prompt)
    reply = data["choices"][0]["message"]["content"]
    print(f"model={data.get('model', args.model)} latency={time.time() - started:.1f}s")
    print(reply)
    problems = check_reply(prompt, reply)
    print("guards:", "PASS" if not problems else problems)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
