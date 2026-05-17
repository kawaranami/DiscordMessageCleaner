# Discord Message Purger

自分が Discord サーバーに投稿したメッセージを一括で消すためのツールです。気軽に使えるように GUI を付けてあります。

Discord の利用規約ではユーザートークンを使った自動化は禁止されているので、最悪アカウントが BAN される可能性があります。自己責任でどうぞ。アプリ起動時に確認ダイアログが出ます。

## 必要なもの

Windows と Python 3.11 以降。ソースから動かす場合は以下で依存関係を入れます。

```
pip install -e .[dev]
```

## 動かし方

```
python -m discord_message_purger
```

トークンを入れて、サーバーを選んで、サーバー名を入力すれば削除が始まります。

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
