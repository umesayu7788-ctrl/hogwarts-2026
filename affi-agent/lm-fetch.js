#!/usr/bin/env node
/*
 * lm-fetch.js — 会員キット同梱（本文もKVキーも持たない）。
 *   在籍時だけ Worker(KV) から資料を取得して標準出力に出す。退会すると取得不可。
 *   node lm-fetch.js --check        … 在籍確認だけ（OK / NG、exit 0 / 1）
 *   node lm-fetch.js <KVキー>       … 例 node lm-fetch.js affiliate_persuasion_psychology.md
 * 必要: auth_config.json（endpoint_url・kit）／ auth_member.txt（DiscordユーザーID）
 *   ※GitHub Actions では auth_member.txt を repo Secret(DISCORD_USER_ID) から展開して使う。
 */
const fs = require("fs");

function fail(m) { console.error("[lm-fetch] " + m); process.exit(1); }

let cfg = {};
try { cfg = JSON.parse(fs.readFileSync("auth_config.json", "utf8")); } catch (e) {}
const endpoint = (cfg.endpoint_url || "").trim();
const kit = (cfg.kit || "").trim();
if (!endpoint) fail("接続先が未設定です（auth_config.json）。配布元の設定をご確認ください。");

let id = "";
try { id = fs.readFileSync("auth_member.txt", "utf8").trim(); } catch (e) {}
if (!id) fail("DiscordユーザーIDが未登録です（auth_member.txt）。");

const arg = process.argv[2];
const base = endpoint + (endpoint.includes("?") ? "&" : "?") +
  "id=" + encodeURIComponent(id) + (kit ? "&kit=" + encodeURIComponent(kit) : "");

(async () => {
  try {
    if (arg === "--check") {
      const r = await fetch(base);
      const j = await r.json();
      console.log(j && j.active ? "OK" : "NG");
      process.exit(j && j.active ? 0 : 1);
    }
    if (!arg) fail("使い方: node lm-fetch.js <KVキー>");
    const r = await fetch(base + "&doc=" + encodeURIComponent(arg.replace(/\\/g, "/")));
    const j = await r.json();
    if (!j || !j.ok || typeof j.text !== "string") {
      fail("資料を取得できませんでした（コミュニティ在籍が確認できない可能性）。");
    }
    process.stdout.write(j.text);
    process.exit(0); // keep-alive接続で終了が遅れるのを防ぐ
  } catch (e) {
    fail("接続に失敗しました: " + e.message);
  }
})();
