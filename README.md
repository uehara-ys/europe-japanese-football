# 欧州サッカー日本人

欧州のクラブでプレーする日本人サッカー選手の試合結果・日程・成績をまとめたサイトです。

公開URL: https://uehara-ys.github.io/europe-japanese-football/

- データは `index.html` 内の `<script type="application/json" id="data">` にあります。
- 試合結果・今後の日程・今シーズン通算成績は、GitHub Actions（`.github/workflows/update-data.yml`）が1時間ごとに `scripts/update_data.py` を動かして更新しています。情報源サイトの表記とこのサイトの表記の対応は `data/aliases.json` にあります。
- 「現地の評価」（海外メディアの採点・試合レポート・記事）は、Claude の定期タスクが探して追加しています。
- 試合結果・成績の出典: [サッカー海外組ナビ](https://soccer-kaigaigumi-navi.com/)
- 現地メディアの採点を探す媒体リスト: [media.md](media.md)
- LINEグループへの配信（返信Botと週1回のまとめ）: [line/README.md](line/README.md)
