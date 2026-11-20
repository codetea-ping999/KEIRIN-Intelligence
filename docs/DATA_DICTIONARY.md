# データ辞書（PostgreSQL、Issue #4）

スキーマは `db/migrations/` の番号付き SQL（up / down の対）で管理します。

```bash
pip install -e '.[db]'
export KEIRIN_DATABASE_URL=postgresql://user:pass@localhost:5432/keirin
keirin-db upgrade            # 空の DB から最新まで
keirin-db downgrade --to 1   # 0002 だけ戻す（--to 0 で全部消す）
keirin-db status
```

適用済みの up スクリプトを後から書き換えると、チェックサムの不一致で `upgrade` が止まります。変更は必ず新しい番号で追加します。

このデータベースは**商用データの保管庫**です。`accepted` のバッチは、許諾済み（`approved`・保存可・有効期限内・未撤回・契約番号一致）の提供元からしか入れられません（トリガーで強制）。許諾が出るまでの研究用の手入力データは、これまでどおり CSV（`data/real/`）で扱います。

時刻はすべて `TIMESTAMPTZ`（絶対時刻）で保存し、表示時に JST に変換します。金額は円、オッズは払戻倍率（例 6.00）です。

## 共通ルール

- `observed_at` = 提供元で公表・観測された時刻、`ingested_at` = 当方に取り込んだ時刻。スナップショット系はすべて `ingested_at >= observed_at`。
- 予想に使えるのは、両方の時刻が予想時刻（`prediction_asof_at`）以前の行だけです。
- スナップショットは上書きせず、新しい行を追加します（車番変更・欠場・並びの変更を履歴として残す）。

## テーブル

| テーブル | 1行の意味 | 主な制約 |
|---|---|---|
| `data_sources` | 提供元と許諾の内容 | `approved` には契約番号が必須。`revoked_at` で撤回を記録 |
| `ingestion_batches` | 取り込み1回分（原本のパス・SHA-256・件数・検証結果） | `(source_id, sha256)` 一意で同じ原本の二重取り込みを防止。`accepted` は許諾トリガーを通過したものだけ |
| `velodromes` | 競輪場（周長・みなし直線） | 公式コード一意 |
| `riders` | 選手 | 公式登録番号一意 |
| `races` | レース | `(競輪場, 日付, R)` 一意。締切は発走以前 |
| `race_entries` | 出走（レースと選手と車番） | `(race, rider)` と `(race, car)` がそれぞれ一意 |
| `entry_snapshots` | 出走情報のある時点の状態（得点・級班・脚質・欠場） | バッチ参照必須、時刻の前後関係 |
| `line_snapshots` / `line_members` | ある時点の並び予想・確定並び | 予想に使う並びは同じレースで予想時刻以前のもの（トリガー） |
| `weather_snapshots` | 天候（風速・風向・気温・降水） | 値の範囲、時刻の前後関係 |
| `odds_snapshots` | ある時点のオッズ | 組番の書式 `1-5` / `1-5-3` |
| `race_results` | 着順 | 出走していない選手の結果は入れられない（複合外部キー）。`finished` のときだけ着順あり |
| `race_payouts` | 払戻 | 返還・不成立を区別 |
| `model_versions` | 学習済みモデルの版 | 成果物ハッシュ必須、学習期間の前後関係 |
| `prediction_runs` | 予想1回分 | 予想時刻は締切より前（トリガー）。`blocked` のときは理由必須 |
| `rider_predictions` | 選手ごとの確率 | 0〜1 |
| `ticket_predictions` | 買い目候補 | 参照するオッズは同じレース・券種・組番で、予想時刻以前（トリガー） |
| `publications` | note 記事 | 公開後は変更・削除不可。訂正は `correction_of` で新しい行を追加 |
| `prediction_evaluations` | 予想の精算結果 | バックテスト / シャドー / 実運用を区別 |
| `rights_decisions` | 利用権限の判断ログ（#3 の監査ログの DB 版） | 追記のみ（更新・削除はトリガーで拒否） |
| `schema_migrations` | 適用済みマイグレーション | `keirin-db` が管理 |

## 保管期間とアクセス権限の方針

| データ | 保管期間 | 根拠 |
|---|---|---|
| 原本（`ingestion_batches.raw_object_path` の先） | 契約で定められた期間。定めがなければ取得から1年、契約終了時は契約の定めに従い削除 | 提供元の許諾範囲 |
| スナップショット・結果・払戻 | 契約の範囲内で保持。撤回・終了時は該当 `source_id` の行を削除し、削除記録を残す | 同上 |
| 予想・評価・公開記録・判断ログ | 無期限（実績の検証と訂正の追跡に必要。第三者データ本体は含まない） | 景品表示法上の根拠資料、改ざん検知 |

ロールは3つに分けます（クラスタ単位の設定なのでマイグレーションには含めず、本番構築時に作成します）。

- `keirin_ingest`: `data_sources` 以外のスナップショット系・バッチに INSERT のみ
- `keirin_model`: 参照系を SELECT、予想系に INSERT
- `keirin_editor`: `publications` に INSERT と未公開行の UPDATE
- `data_sources` の変更は所有者ロールだけ（許諾台帳の変更は PR レビューを通す）

## CI

GitHub Actions の `postgres` ジョブが PostgreSQL 16 を起動し、空の DB から構築 → 全ロールバック → 再構築を実行したうえで、参照整合性・締切後予想の拒否・未許諾バッチの拒否・追記専用のテスト（`tests/test_migrations.py`）を流します。
