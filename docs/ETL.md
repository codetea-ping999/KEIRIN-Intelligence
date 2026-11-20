# 許諾済みデータの取り込み（Issue #5）

`keirin_intelligence.etl` が、提供元のファイルを再実行しても重複しない形で取り込みます。

```bash
keirin ingest races.csv entries.csv results.csv \
  --source licensed.example --contract AGR-001 \
  --observed-at 2026-12-01T18:00:00+09:00 --store data/store
```

## 1ファイルごとの流れ

1. **権利検査**（`RightsGate`、#3）。用途は既定で `ingest`。未登録・未許諾・失効・撤回・契約番号の不一致・架空データは、何も保存せずに拒否し、判断を監査ログに残します。研究用途は `--research` を明示したときだけです。
2. **原本ハッシュ**（SHA-256）。同じ提供元から同じ原本が来たら `duplicate_object` として何もしません。
3. **原本の保存**: `data/store/raw/<source>/<sha256>` に元のバイト列をそのまま保存します。
4. **行の検証**: 型・範囲・必須項目・同じファイル内のキー重複。だめな行は `quarantine` テーブルに理由つきで隔離し、ほかの行は取り込みます。
5. **変更履歴**: レコードは自然キー（レースID、レースID#車番）ごとに版を持ちます。内容が同じなら `unchanged`、違えば新しい版（`changed`）を追加し、古い版は消しません。各版に提供元・契約番号・observed_at・ingested_at・バッチを記録します。

## 監視

`keirin ingest` は1ファイルごとに件数（`inserted` / `changed` / `unchanged` / `quarantined`）と隔離理由を JSON で出力します。`batches` テーブルにも同じ件数が残るので、隔離件数が増えたら提供元のフォーマット変更を疑います。

## 提供元アダプタ

`SourceAdapter`（`fetch()` で `RawObject` を返す）を提供元ごとに実装します。今あるのは、届いたファイルを読む `FileDropAdapter` だけです。ネットワークから取得するアダプタは、許諾（#2）と取得可否の確認（`sources.require_automation_allowed`）が済むまで追加しません。追加するときは `RateLimiter` で間隔を空けます。
