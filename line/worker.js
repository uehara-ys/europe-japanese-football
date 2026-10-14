// 欧州サッカー日本人 LINE返信Bot（Cloudflare Workers 用）
//
// グループで「結果」「日程」「明日」「ゴール」「使い方」と送られたら、
// GitHub Pages に置いた data/summary.json の文章を返信する。
// LINE の「応答メッセージ」は無料メッセージ通数に数えられない。
//
// Cloudflare 側で設定するもの（設定 → 変数とシークレット）:
//   LINE_CHANNEL_SECRET        … LINE Developers の「チャネルシークレット」（シークレットとして登録）
//   LINE_CHANNEL_ACCESS_TOKEN  … LINE Developers の「チャネルアクセストークン（長期）」（シークレットとして登録）
//   SUMMARY_URL（省略可）       … 既定は下の DEFAULT_SUMMARY_URL

const DEFAULT_SUMMARY_URL = "https://uehara-ys.github.io/europe-japanese-football/data/summary.json";

const COMMANDS = {
  "結果": "results", "けっか": "results", "昨日": "results",
  "日程": "today", "にってい": "today", "今日": "today", "きょう": "today",
  "明日": "tomorrow", "あした": "tomorrow",
  "ゴール": "goals", "ごーる": "goals",
  "使い方": "help", "つかいかた": "help", "ヘルプ": "help",
};

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("欧州サッカー日本人 LINE Bot は動いています。", { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    const body = await request.text();
    if (!(await validSignature(body, request.headers.get("x-line-signature"), env.LINE_CHANNEL_SECRET))) {
      return new Response("bad signature", { status: 401 });
    }
    let payload;
    try { payload = JSON.parse(body); } catch { return new Response("bad json", { status: 400 }); }
    // LINE には先に 200 を返し、返信は裏で行う
    ctx.waitUntil(Promise.all((payload.events || []).map(ev => handle(ev, env).catch(e => console.log("error", e)))));
    return new Response("ok");
  },
};

async function handle(ev, env) {
  if (!ev.replyToken) return;

  // グループに招待されたとき：グループIDを知らせる（週1回のまとめの送り先に使う）
  if (ev.type === "join") {
    const id = ev.source.groupId || ev.source.roomId || "";
    return reply(env, ev.replyToken,
      "招待ありがとうございます！欧州でプレーする日本人選手の試合結果をお届けします。\n\n" +
      "このグループのID（週1回のまとめの送り先として、管理者がGitHubに登録します）：\n" + id + "\n\n" +
      "「使い方」と送ると、話しかけ方を表示します。");
  }

  if (ev.type !== "message" || ev.message.type !== "text") return;
  const word = normalize(ev.message.text);
  const kind = COMMANDS[word];
  if (!kind) return; // 普段の会話には反応しない

  const s = await summary(env);
  if (!s) return reply(env, ev.replyToken, "いまデータを読み込めませんでした。少し時間をおいてもう一度送ってください。");

  const today = jstDate(0), tomorrow = jstDate(1);
  const text =
    kind === "results" ? s.results :
    kind === "today" ? (s.schedule?.[today] || "今日の予定はまだ作られていません。") :
    kind === "tomorrow" ? (s.schedule?.[tomorrow] || "明日の予定はまだ作られていません。") :
    kind === "goals" ? s.goals : s.help;
  return reply(env, ev.replyToken, text);
}

// 「@Bot名 結果」「結果！」なども受け付ける
function normalize(t) {
  return (t || "").replace(/@\S+/g, "").replace(/[\s　!！?？。、]/g, "").trim();
}

function jstDate(offsetDays) {
  const x = new Date(Date.now() + 9 * 3600 * 1000 + offsetDays * 86400 * 1000);
  return x.toISOString().slice(0, 10);
}

async function summary(env) {
  try {
    const r = await fetch(env.SUMMARY_URL || DEFAULT_SUMMARY_URL, { cf: { cacheTtl: 60, cacheEverything: true } });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

async function reply(env, replyToken, text) {
  const r = await fetch("https://api.line.me/v2/bot/message/reply", {
    method: "POST",
    headers: { "content-type": "application/json", "authorization": `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}` },
    body: JSON.stringify({ replyToken, messages: [{ type: "text", text: String(text).slice(0, 5000) }] }),
  });
  if (!r.ok) console.log("reply failed", r.status, await r.text());
}

async function validSignature(body, signature, secret) {
  if (!signature || !secret) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  const expected = btoa(String.fromCharCode(...new Uint8Array(mac)));
  if (expected.length !== signature.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ signature.charCodeAt(i);
  return diff === 0;
}
