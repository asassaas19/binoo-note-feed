#!/usr/bin/env python3
"""note のマガジンRSSから NEWS / STORIES の JSON を生成する。

これまで public/data/*.json は手置きの静的ファイルで、最終更新は 2026-06-19 で
止まっていた（note に 2026-09-09 の記事があるのに LP に出ていなかった）。
自動取得の仕組みがそもそも無かったため、このスクリプトで生成する。

マガジン単位の RSS が使えるので、NEWS と STORIES をタイトルの命名規則などに
頼らず確実に振り分けられる。

注意:
- RSS にハッシュタグは含まれないので、news の tags は記事ごとに note API
  （/api/v3/notes/<key> の hashtag_notes）から取る。API が失敗したときだけ
  既存ファイルの同一URLのタグで補う。LP 側は先頭3件だけ表示する。
- 依存パッケージなし（標準ライブラリのみ）。
"""

from __future__ import annotations

import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

NOTE_USER = "inoue_kikaku"

# script.js の NEWS_VIEWALL_URL / STORIES_VIEWALL_URL と同じマガジン
MAGAZINES = {
    "news": "m36b1cda71c32",
    "stories": "mab1daeb6720d",
}

# LP の NEWS は一覧表示なので、増え続けないよう最新のみ出す（全件は View All で note へ）
MAX_ITEMS = {"news": 5, "stories": 6}

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

USER_AGENT = "binoo-note-feed-bot/1.0 (+https://binoo.jp)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def local_name(tag: str) -> str:
    """'{ns}thumbnail' -> 'thumbnail'"""
    return tag.rsplit("}", 1)[-1]


def thumbnail_of(item: ET.Element) -> str:
    """media:thumbnail は名前空間付き。url 属性・テキストのどちらでも拾えるようにする。"""
    for child in item:
        if local_name(child.tag) != "thumbnail":
            continue
        return (child.get("url") or (child.text or "")).strip()
    return ""


def parse_magazine(magazine_id: str) -> list[dict]:
    url = f"https://note.com/{NOTE_USER}/m/{magazine_id}/rss"
    root = ET.fromstring(fetch(url))

    entries = []
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if not link or not title or not pub:
            continue

        published = parsedate_to_datetime(pub)
        entries.append(
            {
                "_sort": published.timestamp(),
                "date": published.strftime("%Y/%m/%d"),
                "title": title,
                "url": link,
                "imgSrc": thumbnail_of(item),
            }
        )

    entries.sort(key=lambda e: e["_sort"], reverse=True)
    return entries


def load_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def fetch_hashtags(note_url: str) -> list[str] | None:
    """記事のハッシュタグを note API から取る。取れなければ None。

    RSS にはタグが無い。API のフィールドは `hashtags` ではなく
    `data.hashtag_notes[].hashtag.name`（先頭に # が付く）。
    """
    key = note_url.rstrip("/").rsplit("/", 1)[-1]
    try:
        data = json.loads(fetch(f"https://note.com/api/v3/notes/{key}"))["data"]
        names = [h["hashtag"]["name"] for h in data.get("hashtag_notes") or []]
    except Exception as err:  # noqa: BLE001 - タグは付加情報なので記事の反映は止めない
        print(f"[news] タグ取得失敗 {key}: {err}", file=sys.stderr)
        return None
    return [n.lstrip("#") for n in names if n.strip("#")]


def build_news(entries: list[dict], existing: list[dict]) -> list[dict]:
    # タグは note API から取る。API が落ちたときだけ既存ファイルのタグで補う
    tags_by_url = {e.get("url"): e.get("tags", []) for e in existing}
    news = []
    for e in entries[: MAX_ITEMS["news"]]:
        tags = fetch_hashtags(e["url"])
        news.append(
            {
                "date": e["date"],
                "tags": tags if tags is not None else tags_by_url.get(e["url"], []),
                "title": e["title"],
                "url": e["url"],
            }
        )
    return news


def build_stories(entries: list[dict], existing: list[dict]) -> list[dict]:
    # サムネイルが取れなかった場合は既存の imgSrc を温存する
    img_by_url = {e.get("url"): e.get("imgSrc", "") for e in existing}
    return [
        {
            "date": e["date"],
            "title": e["title"],
            "imgSrc": e["imgSrc"] or img_by_url.get(e["url"], ""),
            "url": e["url"],
        }
        for e in entries[: MAX_ITEMS["stories"]]
    ]


BUILDERS = {"news": build_news, "stories": build_stories}


def write_if_changed(path: Path, data: list[dict]) -> bool:
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return True


def main() -> int:
    changed = False
    for kind, magazine_id in MAGAZINES.items():
        path = DATA_DIR / f"{kind}.json"
        try:
            entries = parse_magazine(magazine_id)
        except Exception as err:  # noqa: BLE001 - 1本落ちても他を止めない
            print(f"[{kind}] 取得失敗: {err}", file=sys.stderr)
            return 1

        if not entries:
            # 空で上書きすると LP から記事が消えるので、異常として扱い既存を残す
            print(f"[{kind}] RSS が0件。既存ファイルを維持して終了", file=sys.stderr)
            return 1

        data = BUILDERS[kind](entries, load_existing(path))
        if write_if_changed(path, data):
            changed = True
            print(f"[{kind}] 更新: {len(data)}件 -> {path.relative_to(REPO_ROOT)}")
        else:
            print(f"[{kind}] 変更なし: {len(data)}件")

    print(f"changed={'true' if changed else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
