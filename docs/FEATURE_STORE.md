# as-of 特徴量ストア（Issue #6）

`keirin_intelligence.features.AsOfStore` は、予想時刻 t に**公表済みかつ取り込み済み**だったデータだけで特徴量を作ります。

- 各レコードの版は `observed_at`（提供元での公表）と `ingested_at`（当方への取り込み）を持ち、**両方が t 以前**の版のうち最新のものだけを使います。公表は前でも取り込みが後なら使いません（遅延到着）。
- 車番変更・欠場・並びの変更は ETL（#5）で新しい版として入るので、t 時点の出走表がそのまま再現されます。欠場した選手は除き、同じラインの後ろの選手を繰り上げます。
- t が締切以後なら拒否します（`GateRejected`）。出走表がまだ知られていない時刻も拒否します。
- 選手の過去成績（出走数・1着率・3着内率）は、締切が t より前で、着順が t までに取り込まれたレースだけで数えます。
- 特徴量は `model.race_features`（得点・ライン・バンク・風・地元など）＋過去成績です。

## 対象の特徴量

| 区分 | 特徴量 | 出どころ |
|---|---|---|
| 過去成績 | `hist_starts` / `hist_win_rate` / `hist_top3_rate` | 結果（t までに確定・取り込み済み） |
| 級班・得点 | `score_z`, `nige_lowclass` | 出走表の最新版 |
| ライン | `line_strength_z`, `leader`, `bante`, `third`, `solo` | 出走表の並び（版管理） |
| 競輪場 | `bank_nige`, `bank_chaser`, `local` | `data/reference/velodromes.csv` |
| 天候 | `wind_nige`, `wind_chaser`, `wet_nige` | レース情報の最新版 |

## リーク対策のテスト

`tests/test_features.py` は、対象レースの着順、締切後に公表された得点変更、t 以前に公表されたが t 以後に取り込まれた変更、t 以後に結果が届いた過去レースを**わざと混ぜて**も、特徴量が混ぜる前とまったく同じになることを確かめます。
