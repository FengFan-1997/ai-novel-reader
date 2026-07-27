import crypto from "node:crypto";
import http from "node:http";
import express from "express";
import { WebSocketServer, WebSocket } from "ws";

const port = Number.parseInt(process.env.PORT || "8787", 10);
const accessPassword = process.env.CLOUD_ACCESS_PASSWORD || "";
const bridgeSecret = process.env.BRIDGE_SHARED_SECRET || "";
const sessionSecret = process.env.SESSION_SECRET || "";
const publicOrigin = process.env.PUBLIC_ORIGIN || "";
const maxRequestBytes = Number.parseInt(process.env.MAX_REQUEST_BYTES || String(64 * 1024 * 1024), 10);
const sessionMaxAgeSeconds = 30 * 24 * 60 * 60;
const allowedPathPrefixes = ["/api/", "/files/", "/static/audio/", "/healthz", "/readyz"];

if (!accessPassword || !bridgeSecret || !sessionSecret) {
  throw new Error("CLOUD_ACCESS_PASSWORD, BRIDGE_SHARED_SECRET and SESSION_SECRET are required.");
}

const app = express();
app.disable("x-powered-by");
app.set("trust proxy", 1);

let activeBridge = null;
let bridgeMetadata = null;
let lastBridgeSeenAt = null;
const pendingRequests = new Map();
const loginAttempts = new Map();

function fixedEqual(left, right) {
  const leftBuffer = Buffer.from(String(left));
  const rightBuffer = Buffer.from(String(right));
  if (leftBuffer.length !== rightBuffer.length) return false;
  return crypto.timingSafeEqual(leftBuffer, rightBuffer);
}

function parseCookies(header = "") {
  return Object.fromEntries(
    header
      .split(";")
      .map(value => value.trim())
      .filter(Boolean)
      .map(value => {
        const separator = value.indexOf("=");
        if (separator < 0) return [value, ""];
        return [value.slice(0, separator), decodeURIComponent(value.slice(separator + 1))];
      }),
  );
}

function signSession(issuedAt) {
  const payload = String(issuedAt);
  const signature = crypto.createHmac("sha256", sessionSecret).update(payload).digest("base64url");
  return `${payload}.${signature}`;
}

function validSession(req) {
  const token = parseCookies(req.headers.cookie).shengyue_cloud_session;
  if (!token) return false;
  const [issuedAtRaw, signature] = token.split(".");
  const issuedAt = Number.parseInt(issuedAtRaw, 10);
  if (!Number.isFinite(issuedAt) || !signature) return false;
  if (Date.now() - issuedAt > sessionMaxAgeSeconds * 1000 || issuedAt > Date.now() + 60_000) return false;
  return fixedEqual(signSession(issuedAt), token);
}

function isBridgeOnline() {
  return Boolean(activeBridge && activeBridge.readyState === WebSocket.OPEN && bridgeMetadata);
}

function maintenancePayload() {
  return {
    success: false,
    online: false,
    code: "LOCAL_ENGINE_OFFLINE",
    error: "本地声阅引擎当前未连接，云端已进入维护模式。",
  };
}

app.get("/healthz", (_req, res) => {
  res.json({ ok: true, service: "shengyue-cloud-relay" });
});

app.get("/readyz", (_req, res) => {
  res.json({
    ok: true,
    bridgeOnline: isBridgeOnline(),
    lastBridgeSeenAt,
  });
});

app.get("/bridge/status", (req, res) => {
  res.set("Cache-Control", "no-store");
  res.json({
    success: true,
    authenticated: validSession(req),
    online: isBridgeOnline(),
    state: isBridgeOnline() ? "online" : "maintenance",
    lastSeenAt: lastBridgeSeenAt,
    instance: validSession(req) && isBridgeOnline()
      ? {
          name: bridgeMetadata.name,
          version: bridgeMetadata.version,
        }
      : null,
  });
});

app.post("/bridge/login", express.json({ limit: "32kb" }), (req, res) => {
  const address = req.ip || "unknown";
  const now = Date.now();
  const recent = (loginAttempts.get(address) || []).filter(timestamp => now - timestamp < 10 * 60_000);
  if (recent.length >= 8) {
    return res.status(429).json({ success: false, error: "尝试次数过多，请稍后再试。" });
  }
  recent.push(now);
  loginAttempts.set(address, recent);

  if (!fixedEqual(req.body?.password || "", accessPassword)) {
    return res.status(401).json({ success: false, error: "访问密码不正确。" });
  }

  loginAttempts.delete(address);
  const token = signSession(Date.now());
  res.setHeader(
    "Set-Cookie",
    `shengyue_cloud_session=${encodeURIComponent(token)}; Path=/; Max-Age=${sessionMaxAgeSeconds}; HttpOnly; Secure; SameSite=Lax`,
  );
  return res.json({ success: true, online: isBridgeOnline() });
});

app.post("/bridge/logout", (_req, res) => {
  res.setHeader("Set-Cookie", "shengyue_cloud_session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax");
  res.json({ success: true });
});

function requireSession(req, res, next) {
  if (!validSession(req)) {
    return res.status(401).json({ success: false, code: "AUTH_REQUIRED", error: "需要云端访问密码。" });
  }
  return next();
}

function pathAllowed(pathname) {
  return allowedPathPrefixes.some(prefix => pathname === prefix || pathname.startsWith(prefix));
}

function proxyHeaders(headers) {
  const blocked = new Set([
    "authorization",
    "connection",
    "content-length",
    "cookie",
    "host",
    "proxy-authorization",
    "transfer-encoding",
    "upgrade",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
  ]);
  return Object.fromEntries(
    Object.entries(headers)
      .filter(([name]) => !blocked.has(name.toLowerCase()))
      .map(([name, value]) => [name, Array.isArray(value) ? value.join(", ") : String(value)]),
  );
}

function failPending(reason) {
  for (const [id, pending] of pendingRequests.entries()) {
    clearTimeout(pending.timer);
    if (!pending.res.headersSent) pending.res.status(503).json(maintenancePayload());
    else pending.res.end();
    pendingRequests.delete(id);
  }
  if (reason) console.warn(reason);
}

app.use(requireSession);
app.use((req, res, next) => {
  if (req.path.startsWith("/bridge/")) return next();
  if (!pathAllowed(req.path)) {
    return res.status(404).json({ success: false, error: "云端未开放这个本地路径。" });
  }
  if (!isBridgeOnline()) return res.status(503).json(maintenancePayload());

  const chunks = [];
  let total = 0;
  req.on("data", chunk => {
    total += chunk.length;
    if (total > maxRequestBytes) {
      req.destroy(new Error("request-too-large"));
      return;
    }
    chunks.push(chunk);
  });
  req.on("error", error => {
    if (!res.headersSent) {
      const status = error.message === "request-too-large" ? 413 : 400;
      res.status(status).json({ success: false, error: status === 413 ? "上传内容过大。" : "请求读取失败。" });
    }
  });
  req.on("end", () => {
    if (!isBridgeOnline() || res.headersSent) return;
    const id = crypto.randomUUID();
    const timer = setTimeout(() => {
      const pending = pendingRequests.get(id);
      if (!pending) return;
      pendingRequests.delete(id);
      if (!res.headersSent) res.status(504).json({ success: false, error: "本地处理超时，请稍后重试。" });
      else res.end();
    }, 30 * 60_000);
    pendingRequests.set(id, { res, timer, started: false });
    activeBridge.send(JSON.stringify({
      type: "request",
      id,
      method: req.method,
      path: req.originalUrl,
      headers: proxyHeaders(req.headers),
      body: Buffer.concat(chunks).toString("base64"),
    }));
  });
});

app.use((_req, res) => {
  res.status(404).json({ success: false, error: "Not found." });
});

const server = http.createServer(app);
const websocketServer = new WebSocketServer({ noServer: true, maxPayload: 80 * 1024 * 1024 });

server.on("upgrade", (req, socket, head) => {
  const requestUrl = new URL(req.url || "/", "http://localhost");
  if (requestUrl.pathname !== "/bridge/connect") {
    socket.destroy();
    return;
  }
  websocketServer.handleUpgrade(req, socket, head, ws => websocketServer.emit("connection", ws));
});

websocketServer.on("connection", ws => {
  let authenticated = false;
  const authTimer = setTimeout(() => ws.close(4401, "authentication timeout"), 10_000);

  ws.on("message", raw => {
    let message;
    try {
      message = JSON.parse(raw.toString());
    } catch {
      ws.close(4400, "invalid message");
      return;
    }

    if (!authenticated) {
      if (message.type !== "auth" || !fixedEqual(message.secret || "", bridgeSecret)) {
        ws.close(4403, "forbidden");
        return;
      }
      clearTimeout(authTimer);
      authenticated = true;
      if (activeBridge && activeBridge !== ws) activeBridge.close(4410, "replaced by a newer local bridge");
      activeBridge = ws;
      bridgeMetadata = {
        name: String(message.name || "本地声阅"),
        version: String(message.version || "unknown"),
      };
      lastBridgeSeenAt = new Date().toISOString();
      ws.send(JSON.stringify({ type: "auth_ok" }));
      return;
    }

    lastBridgeSeenAt = new Date().toISOString();
    if (message.type === "heartbeat") {
      ws.send(JSON.stringify({ type: "heartbeat_ack", at: lastBridgeSeenAt }));
      return;
    }

    const pending = pendingRequests.get(message.id);
    if (!pending) return;
    if (message.type === "response_start") {
      pending.started = true;
      pending.res.status(Number.parseInt(message.status || 200, 10));
      const safeHeaders = ["content-type", "content-disposition", "cache-control", "content-range", "accept-ranges"];
      for (const [name, value] of Object.entries(message.headers || {})) {
        if (safeHeaders.includes(name.toLowerCase())) pending.res.setHeader(name, value);
      }
      return;
    }
    if (message.type === "response_chunk") {
      pending.res.write(Buffer.from(message.data || "", "base64"));
      return;
    }
    if (message.type === "response_end") {
      clearTimeout(pending.timer);
      pending.res.end();
      pendingRequests.delete(message.id);
      return;
    }
    if (message.type === "response_error") {
      clearTimeout(pending.timer);
      if (!pending.res.headersSent) {
        pending.res.status(502).json({ success: false, error: message.error || "本地请求失败。" });
      } else {
        pending.res.end();
      }
      pendingRequests.delete(message.id);
    }
  });

  ws.on("close", () => {
    clearTimeout(authTimer);
    if (activeBridge !== ws) return;
    activeBridge = null;
    bridgeMetadata = null;
    failPending("Local bridge disconnected.");
  });
  ws.on("error", error => {
    console.warn(`Bridge websocket error: ${error.message}`);
  });
});

setInterval(() => {
  if (!activeBridge || activeBridge.readyState !== WebSocket.OPEN) return;
  activeBridge.ping();
}, 25_000).unref();

server.listen(port, "0.0.0.0", () => {
  console.log(`ShengYue cloud relay listening on ${port}`);
  if (publicOrigin) console.log(`Public origin: ${publicOrigin}`);
});
