// Бот @funko22ua_bot на Cloudflare Workers.
//  • відповідає на /start, /stop, /subs;
//  • зберігає підписки на новинки (їх надсилає каталог);
//  • кожні 5 хвилин перевіряє каталог і пише підписникам про нові фігурки.
// Секрети (wrangler secret put): BOT_TOKEN, WEBHOOK_SECRET.

const CATALOG = "https://nefanchik.github.io/funko-catalog/";
const ALLOWED_ORIGIN = "https://nefanchik.github.io";
const CHANNEL = "funko22ua";
const SEND_PER_RUN = 35; // безкоштовний Cloudflare дозволяє ~50 запитів назовні за раз

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return cors(new Response(null, { status: 204 }));
    try {
      if (url.pathname === "/tg" && req.method === "POST") {
        if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
        await onUpdate(await req.json(), env);
        return new Response("ok");
      }
      if (url.pathname === "/api/subs" && req.method === "POST") {
        const body = await req.json();
        const user = await checkInitData(body.initData || "", env.BOT_TOKEN);
        if (!user) return json({ error: "auth" }, 401);
        if (body.subs) await saveSubs(env, user, body.subs);
        return json({ subs: await getSubs(env, user.id) });
      }
      if (url.pathname === "/setup" && env.WEBHOOK_SECRET && url.searchParams.get("key") === env.WEBHOOK_SECRET) {
        const a = await tg(env, "setWebhook", {
          url: url.origin + "/tg", secret_token: env.WEBHOOK_SECRET, allowed_updates: ["message"], drop_pending_updates: true,
        });
        const b = await tg(env, "setMyCommands", { commands: [
          { command: "start", description: "Відкрити каталог" },
          { command: "subs", description: "Мої підписки на новинки" },
          { command: "stop", description: "Відписатися від сповіщень" },
        ] });
        return json({ webhook: await a.json(), commands: await b.json() });
      }
      if (url.pathname === "/run" && env.WEBHOOK_SECRET && url.searchParams.get("key") === env.WEBHOOK_SECRET) {
        return json(await tick(env));
      }
      return new Response("22FunkoShop bot", { status: 200 });
    } catch (e) {
      return json({ error: String(e) }, 500);
    }
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(tick(env));
  },
};

// ---------- допоміжне ----------
const json = (data, status = 200) => cors(new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } }));
function cors(res) {
  res.headers.set("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
  res.headers.set("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.headers.set("Access-Control-Allow-Headers", "content-type");
  return res;
}
const tg = (env, method, payload) => fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
});
const escHtml = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const openBtn = (text, url) => ({ inline_keyboard: [[{ text, web_app: { url } }]] });

// Перевірка, що дані справді прийшли з Telegram (initData Mini App)
async function hmac(key, data) {
  const k = await crypto.subtle.importKey("raw", typeof key === "string" ? new TextEncoder().encode(key) : key,
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(data)));
}
async function checkInitData(initData, token) {
  const p = new URLSearchParams(initData);
  const hash = p.get("hash");
  if (!hash || !token) return null;
  p.delete("hash");
  const check = [...p.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, v]) => `${k}=${v}`).join("\n");
  const secret = await hmac("WebAppData", token);
  const sig = [...(await hmac(secret, check))].map((b) => b.toString(16).padStart(2, "0")).join("");
  if (sig !== hash) return null;
  if (Date.now() / 1000 - Number(p.get("auth_date") || 0) > 7 * 86400) return null;
  try { return JSON.parse(p.get("user")); } catch { return null; }
}

// ---------- підписки ----------
const strList = (a, max) => (Array.isArray(a) ? a : [])
  .filter((x) => typeof x === "string").map((x) => x.trim().slice(0, 40)).filter(Boolean).slice(0, max);

async function saveSubs(env, user, s) {
  const all = !!s.all, updates = !!s.updates, cats = strList(s.cats, 60), tags = strList(s.tags, 120).map((t) => t.toLowerCase());
  const words = [...new Set(strList(s.words, 30).map((w) => w.toLowerCase()))];
  if (!all && !updates && !cats.length && !words.length) {
    await env.DB.prepare("DELETE FROM subs WHERE user_id = ?").bind(user.id).run();
    return;
  }
  await env.DB.prepare(`INSERT INTO subs (user_id, name, all_new, upd, cats, tags, words, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, all_new = excluded.all_new, upd = excluded.upd, cats = excluded.cats,
    tags = excluded.tags, words = excluded.words, updated = excluded.updated`)
    .bind(user.id, [user.first_name, user.username && "@" + user.username].filter(Boolean).join(" "),
      all ? 1 : 0, updates ? 1 : 0, JSON.stringify(cats), JSON.stringify(tags), JSON.stringify(words), Date.now()).run();
}
async function getSubs(env, userId) {
  const r = await env.DB.prepare("SELECT * FROM subs WHERE user_id = ?").bind(userId).first();
  return r ? { all: !!r.all_new, updates: !!r.upd, cats: JSON.parse(r.cats), tags: JSON.parse(r.tags), words: JSON.parse(r.words) }
    : { all: false, updates: false, cats: [], tags: [], words: [] };
}
function describe(s) {
  const parts = [];
  if (s.updates) parts.push("• нові поставки (пости «ОНОВЛЕННЯ»)");
  if (s.all) parts.push("• усі новинки");
  if (s.cats.length) parts.push("• категорії: " + s.cats.join(", "));
  if (s.words.length) parts.push("• слова: " + s.words.join(", "));
  return parts.join("\n");
}

// ---------- повідомлення боту ----------
async function onUpdate(u, env) {
  const m = u.message;
  if (!m || !m.chat || m.chat.type !== "private") return;
  const text = (m.text || "").trim();
  const chat_id = m.chat.id;
  if (/^\/stop\b/.test(text)) {
    await env.DB.prepare("DELETE FROM subs WHERE user_id = ?").bind(m.from.id).run();
    return tg(env, "sendMessage", { chat_id, text: "🔕 Ви відписались від сповіщень про новинки.\n\nПідписатися знову можна в каталозі — кнопка 🔔." });
  }
  if (/^\/subs\b/.test(text)) {
    const s = await getSubs(env, m.from.id), d = describe(s);
    return tg(env, "sendMessage", {
      chat_id, text: d ? `🔔 Ви підписані на:\n${d}\n\nЗмінити — у каталозі (кнопка 🔔), відписатися — /stop` :
        "У вас поки немає підписок.\nВідкрийте каталог і натисніть 🔔, щоб бот писав вам про нові фігурки.",
      reply_markup: openBtn("🛍 Відкрити каталог", CATALOG),
    });
  }
  return tg(env, "sendMessage", {
    chat_id, parse_mode: "HTML",
    text: "Привіт! 👋 Це <b>22FunkoShop</b> — каталог фігурок Funko Pop.\n\n" +
      "🛍 Шукайте за назвою чи номером, додавайте в кошик і оформлюйте одним повідомленням.\n" +
      "🔔 Натисніть дзвіночок у каталозі — і я напишу, щойно з'явиться фігурка, яка вас цікавить.",
    reply_markup: openBtn("🛍 Відкрити каталог", CATALOG),
  });
}

// ---------- перевірка новинок і розсилка ----------
async function tick(env) {
  const report = { fresh: 0, queued: 0, sent: 0 };
  let items = null;
  try {
    const r = await fetch(CATALOG + "data.js?t=" + Date.now(), { cf: { cacheTtl: 0 } });
    if (r.ok) items = JSON.parse((await r.text()).trim().replace(/^window\.CATALOG=/, "").replace(/;$/, ""));
  } catch (e) { report.error = String(e); }

  if (items && items.length) {
    const seen = new Set((await env.DB.prepare("SELECT id FROM seen").all()).results.map((r) => r.id));
    const fresh = items.filter((it) => !seen.has(it.id));
    const insertSeen = fresh.map((it) => env.DB.prepare("INSERT OR IGNORE INTO seen (id) VALUES (?)").bind(it.id));
    // Перший запуск — лише запам'ятовуємо, що вже є. Якщо «нового» підозріло багато — теж нікому не пишемо.
    if (seen.size && fresh.length && fresh.length <= Math.max(60, seen.size * 0.5)) {
      report.fresh = fresh.length;
      const subs = (await env.DB.prepare("SELECT * FROM subs").all()).results;
      const queue = [];
      for (const s of subs) {
        const tags = JSON.parse(s.tags), words = JSON.parse(s.words);
        const hit = fresh.filter((it) => {
          if (s.all_new) return true;
          if (it.tags.some((t) => tags.includes(t))) return true;
          const hay = [it.name, it.series, it.num, ...it.tags].join(" ").toLowerCase();
          return words.some((w) => hay.includes(w));
        });
        if (hit.length) queue.push(env.DB.prepare("INSERT INTO outbox (user_id, body) VALUES (?, ?)")
          .bind(s.user_id, JSON.stringify(hit.map((it) => ({ id: it.id, name: it.name, num: it.num, series: it.series, price: it.price, photo: it.photos[0] && it.photos[0].full })))));
      }
      report.queued = queue.length;
      for (let i = 0; i < queue.length; i += 50) await env.DB.batch(queue.slice(i, i + 50));
    }
    for (let i = 0; i < insertSeen.length; i += 50) await env.DB.batch(insertSeen.slice(i, i + 50));
  }

  // Пости «ОНОВЛЕННЯ» (нова поставка)
  let ups = null;
  try {
    const r = await fetch(CATALOG + "updates.js?t=" + Date.now(), { cf: { cacheTtl: 0 } });
    if (r.ok) ups = JSON.parse((await r.text()).trim().replace(/^window\.UPDATES=/, "").replace(/;$/, ""));
  } catch (e) { report.updError = String(e); }
  if (ups && ups.length) {
    const seenU = new Set((await env.DB.prepare("SELECT id FROM seen_upd").all()).results.map((r) => r.id));
    const freshU = ups.filter((u) => !seenU.has(u.id));
    if (freshU.length) {
      report.freshUpdates = freshU.length;
      const subs = (await env.DB.prepare("SELECT user_id FROM subs WHERE upd = 1").all()).results;
      const stmts = [];
      for (const u of freshU.slice(0, 3)) for (const s of subs)
        stmts.push(env.DB.prepare("INSERT INTO outbox (user_id, body) VALUES (?, ?)").bind(s.user_id, JSON.stringify({ upd: u })));
      for (const u of freshU) stmts.push(env.DB.prepare("INSERT OR IGNORE INTO seen_upd (id) VALUES (?)").bind(u.id));
      for (let i = 0; i < stmts.length; i += 50) await env.DB.batch(stmts.slice(i, i + 50));
    }
  }

  const rows = (await env.DB.prepare("SELECT n, user_id, body FROM outbox ORDER BY n LIMIT ?").bind(SEND_PER_RUN).all()).results;
  for (const row of rows) {
    const status = await sendNotice(env, row.user_id, JSON.parse(row.body));
    await env.DB.prepare("DELETE FROM outbox WHERE n = ?").bind(row.n).run();
    if (status === 403) await env.DB.prepare("DELETE FROM subs WHERE user_id = ?").bind(row.user_id).run(); // заблокував бота
    else report.sent++;
  }
  return report;
}

async function sendUpdate(env, chat_id, u) {
  let text = u.text.length > 700 ? u.text.slice(0, 700).trimEnd() + "…" : u.text;
  const caption = `📦 <b>Нова поставка фігурок!</b>\n\n${escHtml(text)}\n\n<i>Встигніть першими 👇\nВідписатися: /stop</i>`;
  const reply_markup = { inline_keyboard: [[{ text: "👀 Дивитись пост", url: `https://t.me/${CHANNEL}/${u.id}` }]] };
  let r = u.photo ? await tg(env, "sendPhoto", { chat_id, photo: CATALOG + u.photo, caption, parse_mode: "HTML", reply_markup }) : null;
  if (!r || (!r.ok && r.status !== 403)) r = await tg(env, "sendMessage", { chat_id, text: caption, parse_mode: "HTML", reply_markup });
  return r.status;
}

async function sendNotice(env, chat_id, list) {
  if (list.upd) return sendUpdate(env, chat_id, list.upd);
  const line = (it) => `<b>${escHtml(it.name)}</b>${it.num ? " #" + escHtml(it.num) : ""} — ${it.price} грн`;
  let caption, button;
  if (list.length === 1) {
    const it = list[0];
    caption = `🔔 Нова фігурка за вашою підпискою!\n\n${line(it)}${it.series ? "\n<i>" + escHtml(it.series) + "</i>" : ""}`;
    button = openBtn("🛍 Відкрити в каталозі", `${CATALOG}?item=${it.id}`);
  } else {
    caption = `🔔 Нові фігурки за вашою підпискою (${list.length}):\n`;
    let shown = 0;
    for (const it of list) {
      const l = "\n• " + line(it);
      if (caption.length + l.length > 900) break;
      caption += l; shown++;
    }
    if (shown < list.length) caption += `\n…і ще ${list.length - shown}`;
    button = openBtn("🆕 Переглянути новинки", `${CATALOG}?view=new`);
  }
  caption += "\n\n<i>Відписатися: /stop</i>";
  const photo = list[0].photo ? CATALOG + list[0].photo : null;
  let r = photo ? await tg(env, "sendPhoto", { chat_id, photo, caption, parse_mode: "HTML", reply_markup: button }) : null;
  if (!r || (!r.ok && r.status !== 403)) r = await tg(env, "sendMessage", { chat_id, text: caption, parse_mode: "HTML", reply_markup: button });
  return r.status;
}
