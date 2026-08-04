# -*- coding: utf-8 -*-
"""textfile.py — 「元ファイルの改行コードを壊さずに書き戻す」ための共通部品

## なぜ要るか

Python のテキストモードは**ユニバーサル改行**です。
`open(path, "r", encoding="utf-8")` で読むと `\r\n` は `\n` に化け、
`open(path, "w", encoding="utf-8")` で書き戻すと今度は環境ごとの改行に変換されます。

その結果、buzz_posts.md に**1行足すだけのつもりが、ファイル全体が書き換わります**。
git の autocrlf が差分を吸収してしまうため、壊れていることに気づけません。

改行の判断はこのファイル1つに集約しています。以後
`read_keep_eol()` / `write_keep_eol()` 以外で buzz_posts.md 等を書かないでください。

## 使い方

    from utils.textfile import read_keep_eol, write_keep_eol

    text, eol = read_keep_eol(path)      # text は必ず \n 区切り（加工しやすい形）
    ...text を編集...
    write_keep_eol(path, text, eol)      # 元の改行コードに戻して書く

BOM は読み書きとも素通しします。
"""

import io


def read_keep_eol(path):
    """(本文, 元の改行コード) を返す。本文は `\n` 区切りに正規化してある。

    改行コードは**多数決**で決める。混在ファイルでも「支配的な方」に寄せる＝
    1行足すたびに全体が揺れるのを防ぐ。
    """
    with io.open(path, 'r', encoding='utf-8', newline='') as f:
        raw = f.read()
    crlf = raw.count('\r\n')
    lf = raw.count('\n') - crlf
    eol = '\r\n' if crlf > lf else '\n'
    return raw.replace('\r\n', '\n'), eol


def write_keep_eol(path, text, eol):
    """`\n` 区切りの本文を、元の改行コードに戻して書く。

    ⚠️ `newline=''` を必ず付ける。付けないと Windows のテキストモードが
    `\n` を `\r\n` に自動変換し、`eol` が `\r\n` のときに `\r\r\n` になる。
    """
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text.replace('\n', eol))
