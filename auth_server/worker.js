// 深大抢课助手 · 授权校验（Cloudflare Worker）
//
// 只做一件事：exe 启动时问一句「这个版本、这个口令，还能用吗」。
// 所有的"开关"都存在 KV 里，你在本机用 wrangler 命令（或双击 auth_server 里的
// 那两个 .bat）改一下即可生效，不用重新打包 exe。
//
// KV 里的键（都存在绑定名 szu_grab_auth 下）：
//   password     当前口令（你要发给用户的那个）
//   min_version  最低可用版本；用户版本低于它就拒绝（用来强制升级）
//   enabled      "0" 表示紧急全停（不填或其它值＝正常）
//   deny         拉黑名单，JSON 数组，元素是 install（每个安装自己的随机号）
//                或版本号；命中就拒绝
//
// 边界声明：这里只返回"允许/拒绝"，**不做任何破坏性的事**。
// 拒绝时 exe 只是自己提示一句然后不启动，不碰用户电脑上的任何东西。

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...CORS },
  });
}

function versionParts(text) {
  return String(text || "0").split(".").map(function (part) {
    return parseInt(part.replace(/[^0-9]/g, ""), 10) || 0;
  });
}

function compareVersion(a, b) {
  const left = versionParts(a);
  const right = versionParts(b);
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const x = left[i] || 0;
    const y = right[i] || 0;
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    // 一个不带敏感信息的探活页（有人拿浏览器点开时能看到服务在不在）
    if (url.pathname === "/" || url.pathname === "/ping") {
      return json({ service: "szu-grab-auth", ok: true });
    }

    if (url.pathname !== "/check") {
      return json({ ok: false, reason: "notfound" }, 404);
    }
    if (request.method !== "POST") {
      return json({ ok: false, reason: "method" }, 405);
    }

    let body;
    try {
      body = await request.json();
    } catch (error) {
      return json({ ok: false, reason: "badjson" }, 400);
    }

    const kv = env.szu_grab_auth;
    const version = String((body && body.version) || "");
    const password = String((body && body.password) || "");
    const install = String((body && body.install) || "");

    // 防暴力猜口令：同一个 IP 一小时内失败太多次就先挡住
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const tryKey = "try:" + ip;
    const tries = parseInt((await kv.get(tryKey)) || "0", 10) || 0;
    if (tries >= 30) {
      return json({ ok: false, reason: "toomany",
                    msg: "尝试次数太多了，过一会儿再试" });
    }

    const settings = await Promise.all([
      kv.get("enabled"),
      kv.get("password"),
      kv.get("min_version"),
      kv.get("deny"),
    ]);
    const enabled = settings[0];
    const currentPassword = settings[1];
    const minVersion = settings[2];
    let deny = [];
    try {
      deny = JSON.parse(settings[3] || "[]");
    } catch (error) {
      deny = [];
    }

    const fail = async function (reason, msg) {
      await kv.put(tryKey, String(tries + 1), { expirationTtl: 3600 });
      return json({ ok: false, reason: reason, msg: msg });
    };

    if (enabled === "0") {
      return fail("disabled", "这个工具被作者暂时停用了");
    }
    if (!currentPassword) {
      // 服务器还没设口令＝还没配置好，不放行（避免误以为谁都能用）
      return json({ ok: false, reason: "noconfig",
                    msg: "授权服务还没配置好，找作者" });
    }
    if (minVersion && compareVersion(version, minVersion) < 0) {
      return json({ ok: false, reason: "version", min_version: minVersion,
                    msg: "这一版已停用，找作者要新版（最低可用版本 " +
                         minVersion + "）" });
    }
    if (install && deny.indexOf(install) >= 0) {
      return json({ ok: false, reason: "denied",
                    msg: "这份副本已被停用，找作者" });
    }
    if (version && deny.indexOf(version) >= 0) {
      return json({ ok: false, reason: "denied",
                    msg: "这一版已被停用，找作者要新版" });
    }
    if (password !== currentPassword) {
      return fail("password", "口令不对");
    }

    await kv.delete(tryKey);
    return json({ ok: true, msg: "ok", server_time: Date.now() });
  },
};
