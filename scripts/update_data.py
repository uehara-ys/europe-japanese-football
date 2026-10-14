#!/usr/bin/env python3
"""欧州サッカー日本人：試合結果・今後の日程・今シーズン通算成績を自動で更新する。

情報源「サッカー海外組ナビ」の公開ページ（/matches と /players）に埋め込まれた
データを読み取り、index.html の <script type="application/json" id="data"> を書き換える。
現地メディアの評価（"ratings"）は別の仕組み（Claude の定期タスク）が担当するので触らない。

使い方:
  python scripts/update_data.py            # サイトから取得して index.html を更新
  python scripts/update_data.py --offline DIR  # DIR/matches.html と DIR/players.html を使う（動作確認用）

変更がなければ index.html は書き換えない。変更があれば、追加した試合などを標準出力に出す。
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
ALIASES = ROOT / "data" / "aliases.json"
BASE = "https://soccer-kaigaigumi-navi.com"
UA = ("Mozilla/5.0 (compatible; europe-japanese-football-bot/1.0; "
      "+https://uehara-ys.github.io/europe-japanese-football/)")
JST = dt.timezone(dt.timedelta(hours=9))
DATA_RE = re.compile(r'(<script type="application/json" id="data">)(.*?)(</script>)', re.S)

FLAG_COUNTRY = {"gb-eng": "ENG", "es": "ESP", "de": "GER", "fr": "FRA", "it": "ITA",
                "nl": "NED", "be": "BEL", "pt": "POR"}
EURO_CUP_WORDS = ("チャンピオンズリーグ", "ヨーロッパリーグ", "カンファレンスリーグ")


# ---------- 取得と解析 ----------

def fetch(path: str) -> str:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept-Language": "ja"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # 一時的な失敗は少し待ってやり直す
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{path} を取得できませんでした: {last}")


def flight_text(html: str) -> str:
    """Next.js のページに埋め込まれたデータ（self.__next_f.push）をつなげて1つの文字列にする。"""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    return "".join(json.loads('"' + c + '"') for c in chunks)


def extract_array(text: str, key: str):
    i = text.find(f'"{key}":[')
    if i < 0:
        raise RuntimeError(f'ページの中に "{key}" のデータが見つかりません。情報源サイトの作りが変わった可能性があります。')
    arr, _ = json.JSONDecoder().raw_decode(text, i + len(key) + 3)
    return arr


# ---------- 表記の読み替え ----------

class Names:
    def __init__(self, aliases: dict, comps: dict):
        self.team = aliases.get("team", {})
        self.comp = aliases.get("competition", {})
        self.comp_flag = aliases.get("competition_by_flag", {})
        self.player_alias = aliases.get("player", {})
        self.ex_comp = set(aliases.get("exclude_competitions", []))
        self.ex_words = aliases.get("exclude_competition_keywords", [])
        self.ex_flags = set(aliases.get("exclude_flags", []))
        self.comps = comps  # index.html の "comps"（必要に応じて追加する）
        for code, val in aliases.get("new_competitions", {}).items():
            self.comps.setdefault(code, val)
        self.added_comps = []

    def t(self, name: str) -> str:
        return self.team.get(name, name)

    def p(self, name: str) -> str:
        n = name.replace(" ", "").replace("　", "")
        return self.player_alias.get(n, n)

    def excluded(self, row) -> bool:
        c = row.get("competition") or ""
        if c in self.ex_comp or any(w in c for w in self.ex_words):
            return True
        if (row.get("competitionFlag") or "") in self.ex_flags:
            return True
        if row.get("chip") == "日本代表":
            return True
        return False

    def code(self, row) -> str:
        c = row.get("competition") or "不明"
        flag = row.get("competitionFlag") or ""
        if f"{c}|{flag}" in self.comp_flag:
            return self.comp_flag[f"{c}|{flag}"]
        if c in self.comp:
            return self.comp[c]
        # 新しい大会：情報源の名前をそのままコードにし、"comps" に登録する
        if c not in self.comps:
            country = "EUR" if any(w in c for w in EURO_CUP_WORDS) else FLAG_COUNTRY.get(flag, "OTH")
            self.comps[c] = [c, country]
            self.added_comps.append(c)
        return c


# ---------- 出場状況 ----------

def parse_note(note: str):
    """'スタメン・71分まで ・ 1アシスト' などを (状態, 分, ゴール, アシスト) に変換する。読めなければ None。"""
    if not note:
        return None
    goals = sum(int(x) for x in re.findall(r"(\d+)ゴール", note))
    assists = sum(int(x) for x in re.findall(r"(\d+)アシスト", note))
    head = note.split(" ・ ")[0].strip()
    if head == "スタメン・フル出場":
        return ("F", None, goals, assists)
    m = re.fullmatch(r"スタメン・(\d+)分まで", head)
    if m:
        return ("S", int(m.group(1)), goals, assists)
    m = re.fullmatch(r"(\d+)分から出場", head)
    if m:
        return ("U", int(m.group(1)), goals, assists)
    if head == "ベンチ入り・出場なし":
        return ("B", None, 0, 0)
    if head == "メンバー外":
        return ("X", None, 0, 0)
    return None


def player_entry(name, club, parsed, note=""):
    st, mins, g, a = parsed
    e = [name, club, st]
    if st in ("S", "U") or g or a or note:
        e.append(mins)
    if g or a or note:
        e += [g, a]
    if note:
        e.append(note)
    return e


def parse_score(score: str):
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", score or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


# ---------- 更新本体 ----------

def update(data: dict, rows: list, groups: list, names: Names, today: str):
    log = []
    from_date = data.get("from", "0000-00-00")
    matches = data["matches"]
    index = {(m[0], m[3], m[4]): m for m in matches}

    # 1) 終わった試合の結果
    for r in rows:
        if not r.get("finished") or names.excluded(r):
            continue
        date = r.get("dateKey")
        if not date or date < from_date or date > today:
            continue
        sc = parse_score(r.get("score"))
        if not sc:
            continue
        home, away = names.t(r["home"]), names.t(r["away"])
        jp_entries = []
        for chip in r.get("chips", []):
            parsed = parse_note(chip.get("note"))
            if not parsed:
                continue  # 出場状況がまだ確認できない選手は入れない
            club = home if chip.get("side") == "home" else away
            jp_entries.append(player_entry(names.p(chip["name"]), club, parsed))
        if not jp_entries:
            continue
        key = (date, home, away)
        if key in index:
            # 既にある試合：まだ入っていない選手だけ足す（手で直した退場などは上書きしない）
            m = index[key]
            have = {p[0] for p in m[7]}
            new = [e for e in jp_entries if e[0] not in have]
            if new:
                m[7].extend(new)
                log.append(f"選手追加 {date} {home} {sc[0]}-{sc[1]} {away}: " + "、".join(e[0] for e in new))
            continue
        m = [date, names.code(r), r.get("round") or "", home, away, sc[0], sc[1], jp_entries]
        matches.append(m)
        index[key] = m
        ga = []
        for e in jp_entries:
            if e[2] not in ("F", "S", "U"):
                continue
            g = e[4] if len(e) > 4 else 0
            a = e[5] if len(e) > 5 else 0
            extra = " ".join(x for x in (f"{g}G" if g else "", f"{a}A" if a else "") if x)
            ga.append(e[0] + (f"（{extra}）" if extra else ""))
        log.append(f"結果追加 {date} {home} {sc[0]}-{sc[1]} {away}" + (f"（出場: {'、'.join(ga)}）" if ga else ""))
    matches.sort(key=lambda m: (m[0], m[3]))

    # 2) 今後の日程（情報源にある分で毎回作り直す）
    played = {(m[0], m[3], m[4]) for m in matches}
    fixtures = []
    for r in rows:
        if r.get("finished") or names.excluded(r):
            continue
        date = r.get("dateKey")
        if not date or date < today:
            continue
        if not (r.get("homeJp") or r.get("awayJp")):
            continue
        home, away = names.t(r["home"]), names.t(r["away"])
        if (date, home, away) in played:
            continue
        fixtures.append([date, r.get("timeLabel") or "未定", names.code(r), r.get("round") or "", home, away])
    fixtures.sort(key=lambda f: (f[0], f[1].zfill(5) if f[1][:1].isdigit() else "99:99", f[4]))
    if fixtures != data.get("fixtures"):
        log.append(f"日程 {len(fixtures)}試合（{fixtures[0][0] if fixtures else '-'}〜{fixtures[-1][0] if fixtures else '-'}）")
    data["fixtures"] = fixtures
    if fixtures:
        data["fixturesTo"] = fixtures[-1][0]

    # 3) 今シーズン通算成績（リーグ戦）
    rows_season = {}
    for g in groups:
        if (g.get("league") or "") == "MLS":
            continue
        for c in g.get("clubs", []):
            for pl in c.get("players", []):
                stat = pl.get("stat") or ""
                apps = re.search(r"(\d+)試合", stat)
                goals = re.search(r"(\d+)ゴール", stat)
                assists = re.search(r"(\d+)アシスト", stat)
                rows_season[names.p(pl["name"])] = [int(apps.group(1)) if apps else None,
                                                     int(goals.group(1)) if goals else 0,
                                                     int(assists.group(1)) if assists else 0]
    if rows_season:
        season = data.setdefault("season", {})
        if season.get("rows") != rows_season:
            log.append(f"通算成績 {len(rows_season)}人")
        season["rows"] = rows_season
        season["basis"] = "リーグ戦のみ"
        season["source"] = {"name": "サッカー海外組ナビ（選手一覧）", "url": BASE + "/players"}

    if names.added_comps:
        log.append("新しい大会: " + "、".join(names.added_comps))
    return log


def dump(d: dict) -> str:
    out = ["{"]
    keys = list(d.keys())
    for i, k in enumerate(keys):
        comma = "," if i < len(keys) - 1 else ""
        v = d[k]
        if k in ("matches", "fixtures", "ratings"):
            body = ",\n".join(json.dumps(x, ensure_ascii=False) for x in v)
            out.append(f'"{k}":[\n{body}\n]{comma}')
        else:
            out.append(f'"{k}":' + json.dumps(v, ensure_ascii=False) + comma)
    out.append("}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", help="matches.html と players.html があるフォルダ（動作確認用）")
    ap.add_argument("--today", help="今日の日付 YYYY-MM-DD（動作確認用。省略時は日本時間の今日）")
    args = ap.parse_args()

    if args.offline:
        d = pathlib.Path(args.offline)
        m_html = (d / "matches.html").read_text(encoding="utf-8")
        p_html = (d / "players.html").read_text(encoding="utf-8")
    else:
        m_html = fetch("/matches")
        time.sleep(3)
        p_html = fetch("/players")

    rows = [r for r in extract_array(flight_text(m_html), "rows") if isinstance(r, dict) and "dateKey" in r]
    groups = extract_array(flight_text(p_html), "groups")
    if len(rows) < 20:
        sys.exit(f"試合データが少なすぎます（{len(rows)}件）。情報源サイトの作りが変わった可能性があるため更新を中止します。")

    html = INDEX.read_text(encoding="utf-8")
    m = DATA_RE.search(html)
    data = json.loads(m.group(2))
    before = json.dumps({k: v for k, v in data.items() if k != "updated"}, ensure_ascii=False, sort_keys=True)

    aliases = json.loads(ALIASES.read_text(encoding="utf-8"))
    names = Names(aliases, data["comps"])
    today = args.today or dt.datetime.now(JST).strftime("%Y-%m-%d")
    log = update(data, rows, groups, names, today)

    after = json.dumps({k: v for k, v in data.items() if k != "updated"}, ensure_ascii=False, sort_keys=True)
    if after == before:
        print("変更なし")
        return
    if data["matches"]:
        data["to"] = max(data.get("to", ""), data["matches"][-1][0])
    data["updated"] = today
    if "season" in data:
        data["season"]["asOf"] = today
    new_html = html[:m.start(2)] + "\n" + dump(data) + "\n" + html[m.end(2):]
    json.loads(DATA_RE.search(new_html).group(2))  # 壊れていないか確認
    INDEX.write_text(new_html, encoding="utf-8")
    print("\n".join(log))


if __name__ == "__main__":
    main()
