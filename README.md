# Discord Message Purger

自分が Discord のサーバーや DM（ダイレクトメッセージ）に投稿したメッセージを一括で消すためのツールです。気軽に使えるように GUI を付けてあります。

Discord の利用規約ではユーザートークンを使った自動化は禁止されているので、最悪アカウントが BAN される可能性があります。自己責任でどうぞ。アプリ起動時に確認ダイアログが出ます。

## 必要なもの

Windows と Python 3.10 以降。ソースから動かす場合は以下で依存関係を入れます。

```
pip install -e .[dev]
```

## 動かし方

```
python -m discord_message_purger
```

トークンを入れると、「Servers」と「Direct messages」の 2 つのタブが表示されます。

### サーバー

サーバーを選んで、確認ダイアログにサーバー名を入力すれば削除が始まります。

### DM

1. 「Direct messages」タブを開きます。開いている DM・グループ DM が新しい順に並びます。
2. 消したい会話にチェックを入れます（行のどこをクリックしても切り替わります）。検索欄で絞り込み、「Select all」で表示中の会話をまとめて選択できます。
3. DM 一覧から閉じてしまった会話は、Discord で開き直して「Refresh」を押すか、チャンネル ID または `https://discord.com/channels/@me/...` のリンクを貼って「Add」を押してください。
4. 削除ボタンを押し、確認ダイアログに `DELETE` と入力すると開始します。

消えるのは自分のメッセージだけで、相手のメッセージには触りません。通話履歴やメンバー追加などのシステムメッセージは Discord 側で削除できないので、自動的にスキップします。

### その他

- 一時停止・再開・キャンセルができます。ネットワークエラーで一時停止した場合も「Resume」で続きから再開します。
- 終わったら「New cleanup」でアプリを再起動せずに別のサーバーや DM を選べます。
- 「Save log to file」で作業ログを保存できます。

## ビルド

実行ファイルを作りたい場合は PyInstaller を使います。

```
pip install pyinstaller
pyinstaller packaging/discord_message_purger.spec
```

`dist/DiscordMessagePurger.exe` ができます。

## テスト

```
pytest
```
