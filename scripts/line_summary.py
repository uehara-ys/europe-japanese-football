#!/usr/bin/env python3
"""LINEグループ向けの文章を作る・送る。

  python scripts/line_summary.py build         # data/summary.json を作る（返信Botが読む）
  python scripts/line_summary.py push-weekly   # 先週のまとめをLINEグループに送る
  python scripts/line_summary.py print-weekly  # 送らずに先週のまとめを表示（確認用）

push-weekly には環境変数 LINE_CHANNEL_ACCESS_TOKEN と LINE_GROUP_ID が必要。
どちらかが無いときは何も送らずに終わる。
"""
import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
SUMMARY = ROOT / "data" / "summary.json"
SITE = "https://uehara-ys.github.io/europe-japanese-football/"
JST = dt.timezone(dt.timedelta(hours=9))
WD = "月火水木金土日"
MAX_LEN = 4800  # LINEのテキストは1通5000文字まで


def load():
    html = INDEX.read_text(encoding="utf-8")
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))


def d(iso):
    return dt.date.fromisoformat(iso)


def md(iso):
    x = d(iso)
    return f"{x.month}/{x.day}（{WD[x.weekday()]}）"


def comp_name(data, code):
    return (data["comps"].get(code) or [code])[0]


def played(p):
    return p[2] in ("F", "S", "U")


def player_line(p):
    st, mins = p[2], (p[3] if len(p) > 3 else None)
    g = p[4] if len(p) > 4 else 0
    a = p[5] if len(p) > 5 else 0
    note = p[6] if len(p) > 6 else ""
    s = {"F": "フル出場", "S": f"先発{mins}分まで", "U": f"{mins}分から出場",
         "B": "ベンチ", "X": "メンバー外"}[st]
    extra = " ".join(x for x in (f"⚽{g}" if g else "", f"🅰️{a}" if a else "") if x)
    return f"・{p[0]} {s}" + (f" {extra}" if extra else "") + (f"（{note}）" if note else "")


def result_mark(m, club):
    if club not in (m[3], m[4]):
        return ""
    f, a = (m[5], m[6]) if club == m[3] else (m[6], m[5])
    return "○" if f > a else "●" if f < a else "△"


def clip(text):
    if len(text) <= MAX_LEN:
        return text
    cut = text[:MAX_LEN].rsplit("\n", 1)[0]
    return cut + f"\n…（続きはサイトで）\n{SITE}"


# ---------- 文章 ----------

def results_text(data, date=None):
    ms = [m for m in data["matches"] if any(played(p) for p in m[7])]
    if not ms:
        return "まだ試合結果がありません。"
    date = date or max(m[0] for m in ms)
    day = [m for m in ms if m[0] == date]
    lines = [f"⚽ {md(date)}の日本人選手の結果", ""]
    for m in day:
        clubs = sorted({p[1] for p in m[7] if played(p)})
        mark = result_mark(m, clubs[0]) if len(clubs) == 1 else ""
        lines.append(f"{m[3]} {m[5]}-{m[6]} {m[4]} {mark}".rstrip())
        lines.append(f"  {comp_name(data, m[1])} {m[2]}".rstrip())
        for p in m[7]:
            if played(p):
                lines.append("  " + player_line(p))
        lines.append("")
    idle = [p[0] for m in day for p in m[7] if not played(p)]
    if idle:
        lines.append(f"出場なし：{'、'.join(idle)}")
        lines.append("")
    rated = sum(1 for r in data.get("ratings", []) if r[0] == date)
    if rated:
        lines.append(f"現地メディアの評価 {rated}件はサイトの「現地の評価」で")
    lines.append(SITE)
    return clip("\n".join(lines).strip())


def rosters(data):
    club_of = {}
    for m in sorted(data["matches"], key=lambda m: m[0]):
        for p in m[7]:
            club_of[p[0]] = p[1]
    r = {}
    for n, c in club_of.items():
        r.setdefault(c, []).append(n)
    return r


def schedule_text(data, date):
    ros = rosters(data)
    fx = [f for f in data.get("fixtures", []) if f[0] == date]
    if not fx:
        return f"📅 {md(date)}は日本人選手の試合予定がありません。\n{SITE}"
    key = lambda f: f[1].zfill(5) if f[1][:1].isdigit() else "99:99"
    lines = [f"📅 {md(date)}の試合（日本時間）", ""]
    for f in sorted(fx, key=key):
        names = ros.get(f[4], []) + ros.get(f[5], [])
        lines.append(f"{f[1]} {f[4]} vs {f[5]}")
        lines.append(f"  {comp_name(data, f[2])}" + (f"｜{'・'.join(names)}" if names else ""))
    lines += ["", "※深夜は24時以降で表記（27:45＝翌3:45）", SITE]
    return clip("\n".join(lines))


def week_bounds(day):
    start = day - dt.timedelta(days=day.weekday())
    return start, start + dt.timedelta(days=6)


def goals_text(data, start, end, title):
    ms = [m for m in data["matches"] if start <= d(m[0]) <= end]
    tally = {}
    for m in ms:
        for p in m[7]:
            g = p[4] if len(p) > 4 else 0
            a = p[5] if len(p) > 5 else 0
            if g or a:
                t = tally.setdefault(p[0], {"club": p[1], "g": 0, "a": 0})
                t["g"] += g
                t["a"] += a
    lines = [title, ""]
    if not tally:
        lines.append("ゴール・アシストはまだありません。")
    for n, t in sorted(tally.items(), key=lambda kv: (-(kv[1]["g"] * 2 + kv[1]["a"]), -kv[1]["g"])):
        extra = " ".join(x for x in (f"⚽{t['g']}" if t["g"] else "", f"🅰️{t['a']}" if t["a"] else "") if x)
        lines.append(f"・{n}（{t['club']}）{extra}")
    return lines, ms


def weekly_text(data, today):
    last_mon = week_bounds(today)[0] - dt.timedelta(days=7)
    start, end = last_mon, last_mon + dt.timedelta(days=6)
    lines, ms = goals_text(data, start, end,
                           f"📰 先週（{start.month}/{start.day}〜{end.month}/{end.day}）の日本人選手まとめ")
    apps = sum(1 for m in ms for p in m[7] if played(p))
    lines += ["", f"出場のべ{apps}人・{len(ms)}試合"]
    # 現地メディアの採点（10点満点）で高かったもの
    top = [r for r in data.get("ratings", [])
           if start <= d(r[0]) <= end and r[4] is not None and r[5] == "10点満点"]
    top.sort(key=lambda r: -r[4])
    if top:
        lines += ["", "現地メディアの高評価"]
        seen = set()
        for r in top:
            if r[1] in seen:
                continue
            seen.add(r[1])
            lines.append(f"・{r[1]} {r[4]}点（{r[2]}）")
            if len(seen) >= 5:
                break
    lines += ["", "グループで「結果」「日程」「ゴール」と送ると、Botが最新の情報を返します。", SITE]
    return clip("\n".join(lines))


HELP = ("このBotに話しかける言葉\n"
        "・結果 … 最新の試合日の結果\n"
        "・日程 … 今日の試合予定（「明日」で明日の予定）\n"
        "・ゴール … 今週のゴール・アシスト\n"
        "・使い方 … この説明\n"
        f"サイト：{SITE}")


def build(today=None):
    data = load()
    today = today or dt.datetime.now(JST).date()
    start, end = week_bounds(today)
    g_lines, _ = goals_text(data, start, end, f"🔥 今週（{start.month}/{start.day}〜）のゴール・アシスト")
    out = {
        "updated": dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "results": results_text(data),
        "schedule": {(today + dt.timedelta(days=i)).isoformat():
                     schedule_text(data, (today + dt.timedelta(days=i)).isoformat()) for i in range(-1, 8)},
        "goals": clip("\n".join(g_lines + ["", SITE])),
        "help": HELP,
    }
    old = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.exists() else {}
    if {k: v for k, v in old.items() if k != "updated"} == {k: v for k, v in out.items() if k != "updated"}:
        print("要約に変更なし")
        return
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("要約を更新しました")


def push(text):
    token, group = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"), os.environ.get("LINE_GROUP_ID")
    if not token or not group:
        print("LINE_CHANNEL_ACCESS_TOKEN か LINE_GROUP_ID が未設定のため送信しませんでした。")
        return
    body = json.dumps({"to": group, "messages": [{"type": "text", "text": text}]}).encode()
    req = urllib.request.Request("https://api.line.me/v2/bot/message/push", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("送信しました", r.status)
    except urllib.error.HTTPError as e:
        sys.exit(f"送信に失敗しました: {e.code} {e.read().decode(errors='replace')}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    today = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else dt.datetime.now(JST).date()
    if cmd == "build":
        build(today)
    elif cmd == "print-weekly":
        print(weekly_text(load(), today))
    elif cmd == "push-weekly":
        push(weekly_text(load(), today))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
