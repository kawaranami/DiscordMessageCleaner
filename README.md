# Discord Message Purger

選択した Discord サーバー内に投稿した自分自身のメッセージを一括削除するデスクトップアプリケーションです。GUI には PySide6 を使用しています。

## 注意事項

Discord 利用規約およびコミュニティガイドラインは、ユーザートークンを用いた自動化（いわゆるセルフボット）を明確に禁止しています。本ツールの使用によりアカウントが永久停止される可能性があります。リスクを理解した上で自己責任にて使用してください。起動時に同意ダイアログで確認を求めます。

## 動作環境

- Windows 10 / 11
- Python 3.11 以上（ソースから実行する場合）

## 開発環境のセットアップ

```bash
pip install -e .[dev]
```

## 起動

```bash
python -m discord_message_purger
```

## テスト

```bash
pytest
```

## ビルド

PyInstaller を使用して単一の実行ファイルを作成します。

```bash
pip install pyinstaller
pyinstaller packaging/discord_message_purger.spec
```

成果物は `dist/DiscordMessagePurger.exe` に出力されます。

## ライセンス

未定。
