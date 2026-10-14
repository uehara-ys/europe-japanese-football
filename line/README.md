# LINEグループへの配信（設定手順）

グループで「結果」「日程」などと送ると、Botが最新の情報を返信します（返信は無料メッセージ通数に数えられません）。
あわせて、毎週月曜9時に先週のまとめを1回だけ自動で送ります（14人のグループで月4〜5回×14通＝最大70通。無料枠200通に収まります）。

## しくみ

- `scripts/line_summary.py build` … 毎時の自動更新（GitHub Actions）で `data/summary.json` を作る
- `line/worker.js` … Cloudflare Workers で動く返信Bot。`data/summary.json` を読んで返信する
- `.github/workflows/line-weekly.yml` … 毎週月曜9時に先週のまとめをグループへ送る

## Botに話しかける言葉

| 送る言葉 | 返ってくるもの |
|---|---|
| 結果 | 最新の試合日の日本人選手の結果 |
| 日程 / 今日 | 今日の試合予定（日本時間） |
| 明日 | 明日の試合予定 |
| ゴール | 今週のゴール・アシスト |
| 使い方 | 話しかけ方の説明 |

「@Bot名 結果」のようにメンションを付けても反応します。普段の会話には反応しません。

## 設定手順

### 1. LINE公式アカウントを作る

1. https://www.linebiz.com/jp/entry/ から LINE公式アカウントを作成する（無料のコミュニケーションプランのまま）。アカウント名の例：「欧州サッカー日本人」
2. LINE Official Account Manager の「設定」→「Messaging API」で「Messaging APIを利用する」を押し、プロバイダーを作る（名前は自由）。
3. 「設定」→「アカウント設定」で「グループ・複数人トークへの参加を許可する」をオンにする。
4. 「設定」→「応答設定」で、「Webhook」をオン、「応答メッセージ」をオフにする（オンのままだと自動の定型文が毎回返ってしまう）。

### 2. 鍵を2つ控える

LINE Developers（https://developers.line.biz/console/ ）で、作ったチャネルを開く。

- 「チャネル基本設定」タブの **チャネルシークレット**
- 「Messaging API設定」タブの一番下、**チャネルアクセストークン（長期）**（「発行」を押す）

この2つは他人に見せないこと。

### 3. 返信Botを Cloudflare Workers に置く

1. https://dash.cloudflare.com/ で無料アカウントを作る。
2. 「Workers & Pages」→「作成」→「Worker を作成」。名前は例えば `europe-jp-line-bot`。「デプロイ」を押す。
3. 「コードを編集」を開き、中身をすべて消して、このリポジトリの `line/worker.js` の内容を貼り付け、「デプロイ」を押す。
4. Worker の「設定」→「変数とシークレット」で、次の2つを**シークレット**として追加し、デプロイする。
   - `LINE_CHANNEL_SECRET` … 手順2のチャネルシークレット
   - `LINE_CHANNEL_ACCESS_TOKEN` … 手順2のチャネルアクセストークン
5. Worker のURL（`https://europe-jp-line-bot.○○.workers.dev`）を控える。ブラウザで開いて「動いています」と出ればOK。

### 4. LINEとつなぐ

1. LINE Developers の「Messaging API設定」タブで、「Webhook URL」に手順3のURLを入れて「更新」→「検証」（「成功」と出ればOK）。
2. 「Webhookの利用」をオンにする。

### 5. グループに招待する

1. 「Messaging API設定」タブのQRコードからBotを友だち追加する。
2. LINEグループのメンバー招待からBotを招待する。
3. Botが「このグループのID」を送ってくるので控える（`C` で始まる長い文字列）。
4. グループで「結果」と送って、返信が来れば完了。

### 6. 週1回のまとめを有効にする（GitHub）

1. GitHub のこのリポジトリで「Settings」→「Secrets and variables」→「Actions」→「New repository secret」。
2. 次の2つを登録する。
   - `LINE_CHANNEL_ACCESS_TOKEN` … 手順2のチャネルアクセストークン
   - `LINE_GROUP_ID` … 手順5で控えたグループID
3. 試しに送る場合は「Actions」タブ →「LINE 週1回のまとめ」→「Run workflow」。（1回で14通ぶん使う）

## 困ったとき

- 返信が来ない：LINE Developers の Webhook の「検証」が成功するか、応答設定で「Webhook」がオンか確認する。Cloudflare の Worker の「ログ」にエラーが出ていないか見る。
- 定型文が返ってくる：LINE Official Account Manager の応答設定で「応答メッセージ」をオフにする。
- 週1回のまとめが届かない：GitHub の Secrets の名前と値を確認する。無料枠（月200通）を使い切ると、その月は届かない。
