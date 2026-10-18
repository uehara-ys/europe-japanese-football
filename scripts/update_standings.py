#!/usr/bin/env python3
"""欧州サッカー日本人：5大リーグの順位表を自動で更新する。

ESPN の公開データ（site.api.espn.com の standings）から、プレミアリーグ・ブンデスリーガ・
リーグ・アン・セリエA・ラ・リーガの順位表を取得し、index.html の
<script type="application/json" id="data"> の "standings" を書き換える。
"matches"・"fixtures"・"ratings" などほかのデータには触らない。

クラブ名は data/standings_names.json の対応表で日本語にする（ない場合は英語表記のまま）。
取得に失敗したリーグは、前回の順位表をそのまま残す。
順位表の中身が変わったときだけ index.html を書き換え、変わったリーグを標準出力に出す。

使い方:
  python scripts/update_standings.py
  python scripts/update_standings.py --offline DIR   # DIR/PL.json などを使う（動作確認用）
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.request

sys.dont_write_bytecode = True  # scripts/__pycache__ を書き換えない（自動更新の差分判定に影響するため）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from update_data import DATA_RE, dump  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
NAMES = ROOT / "data" / "standings_names.json"
JST = dt.timezone(dt.timedelta(hours=9))
UA = ("Mozilla/5.0 (compatible; europe-japanese-football-bot/1.0; "
      "+https://uehara-ys.github.io/europe-japanese-football/)")
API = "https://site.api.espn.com/apis/v2/sports/soccer/{}/standings"

# (サイト内の大会コード, ESPN のリーグコード, 表示名)
LEAGUES = [
    ("PL", "eng.1", "プレミアリーグ"),
    ("BL", "ger.1", "ブンデスリーガ"),
    ("L1", "fra.1", "リーグ・アン"),
    ("SA", "ita.1", "セリエA"),
    ("LL", "esp.1", "ラ・リーガ"),
]


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # 一時的な失敗は少し待ってやり直す
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url} を取得できませんでした: {last}")


def stat_map(entry: dict) -> dict:
    out = {}
    for s in entry.get("stats", []):
        key = (s.get("name") or s.get("type") or "").lower()
        if key:
            out[key] = s.get("value")
    return out


def num(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def parse(raw: dict, names: dict, notes: dict):
    """ESPN の standings から [順位, クラブ, 試合, 勝, 分, 敗, 得点, 失点, 得失点差, 勝点, 備考] の行を作る。"""
    groups = raw.get("children") or [raw]
    g = groups[0]
    entries = (g.get("standings") or {}).get("entries") or []
    if not entries:
        raise RuntimeError("順位表のデータが空です")
    season = (g.get("standings") or {}).get("seasonDisplayName") or g.get("name") or ""
    ms = re.search(r"\d{4}[-/]\d{2,4}", season)
    season = ms.group(0).replace("/", "-") if ms else ""
    rows = []
    for e in entries:
        st = stat_map(e)
        team = e.get("team") or {}
        en = team.get("displayName") or team.get("name") or "?"
        note = (e.get("note") or {}).get("description") or ""
        gf, ga = num(st.get("pointsfor")), num(st.get("pointsagainst"))
        rows.append([
            num(st.get("rank")), names.get(en, en),
            num(st.get("gamesplayed")), num(st.get("wins")), num(st.get("ties")), num(st.get("losses")),
            gf, ga, gf - ga, num(st.get("points")), notes.get(note, note),
        ])
    # 順位が入っていない場合は勝点・得失点差・得点の順で並べて振り直す
    if not all(r[0] for r in rows):
        rows.sort(key=lambda r: (-r[9], -r[8], -r[6]))
        for i, r in enumerate(rows, 1):
            r[0] = i
    rows.sort(key=lambda r: r[0])
    return season, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", help="PL.json などがあるフォルダ（動作確認用）")
    args = ap.parse_args()

    cfg = json.loads(NAMES.read_text(encoding="utf-8"))
    names, notes = cfg.get("team", {}), cfg.get("note", {})

    html = INDEX.read_text(encoding="utf-8")
    m = DATA_RE.search(html)
    data = json.loads(m.group(2))
    old = data.get("standings") or {}
    old_by_code = {lg["code"]: lg for lg in old.get("leagues", [])}

    leagues, changed, failed = [], [], []
    for code, espn, label in LEAGUES:
        try:
            if args.offline:
                raw = json.loads((pathlib.Path(args.offline) / f"{code}.json").read_text(encoding="utf-8"))
            else:
                raw = fetch_json(API.format(espn))
            season, rows = parse(raw, names, notes)
            lg = {"code": code, "name": label, "season": season, "rows": rows}
        except Exception as e:
            failed.append(f"{label}: {e}")
            if code in old_by_code:
                leagues.append(old_by_code[code])
            continue
        if old_by_code.get(code, {}).get("rows") != rows:
            changed.append(label)
        leagues.append(lg)

    for f in failed:
        print("取得失敗（前回の順位表を残す）", f, file=sys.stderr)
    if not changed:
        return
    now = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    standings = {"asOf": now, "source": {"name": "ESPN", "url": "https://www.espn.com/soccer/standings"},
                 "leagues": leagues}

    # "standings" は "fixtures" のすぐ後ろに置く（ほかのキーの順番はそのまま）
    new = {}
    for k, v in data.items():
        if k == "standings":
            continue
        new[k] = v
        if k == "fixtures":
            new["standings"] = standings
    if "standings" not in new:
        new["standings"] = standings
    new_html = html[:m.start(2)] + "\n" + dump(new) + "\n" + html[m.end(2):]
    json.loads(DATA_RE.search(new_html).group(2))  # 壊れていないか確認
    INDEX.write_text(new_html, encoding="utf-8")
    print("順位表更新:", "、".join(changed))


if __name__ == "__main__":
    main()
