import crypto from "node:crypto";
import http from "node:http";
import express from "express";
import { WebSocketServer, WebSocket } from "ws";
import { CommunityStore, tokenFromRequest } from "./community-store.js";
import { createObjectStore } from "./object-store.js";

const port = Number.parseInt(process.env.PORT || "8787", 10);
const accessPassword = process.env.CLOUD_ACCESS_PASSWORD || "";
const bridgeSecret = process.env.BRIDGE_SHARED_SECRET || "";
const sessionSecret = process.env.SESSION_SECRET || "";
const publicOrigin = process.env.PUBLIC_ORIGIN || "";
const maxRequestBytes = Number.parseInt(process.env.MAX_REQUEST_BYTES || String(64 * 1024 * 1024), 10);
const sessionMaxAgeSeconds = 30 * 24 * 60 * 60;
const allowedPathPrefixes = ["/api/", "/files/", "/static/audio/", "/healthz", "/readyz"];
const legacyBridgeEnabled = process.env.ENABLE_LEGACY_BRIDGE !== "false";
const communityStore = new CommunityStore(process.env.DATABASE_URL || "");
const objectStore = createObjectStore();
const communityPeers = new Map();
const peerTickets = new Map();

if (legacyBridgeEnabled && (!accessPassword || !bridgeSecret || !sessionSecret)) {
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
  if (!sessionSecret) return false;
  const token = parseCookies(req.headers.cookie).shengyue_cloud_session;
  if (!token) return false;
  const [issuedAtRaw, signature] = token.split(".");
  const issuedAt = Number.parseInt(issuedAtRaw, 10);
  if (!Number.isFinite(issuedAt) || !signature) return false;
  if (Date.now() - issuedAt > sessionMaxAgeSeconds * 1000 || issuedAt > Date.now() + 60_000) return false;
  return fixedEqual(signSession(issuedAt), token);
}

function communityUnavailable(res) {
  return res.status(503).json({ success: false, code: "COMMUNITY_NOT_CONFIGURED", error: "公共书库正在配置数据库，请稍后再试。" });
}

function validHash(value) {
  return /^[a-f0-9]{64}$/i.test(String(value || ""));
}

function normalizeChapter(value) {
  const index = Number.parseInt(value?.index, 10);
  const title = String(value?.title || "").trim().slice(0, 300);
  const textHash = String(value?.textHash || "").toLowerCase();
  if (!Number.isInteger(index) || index < 0 || !title || !validHash(textHash)) return null;
  return { index, title, textHash };
}

async function deviceFromRequest(req) {
  if (!communityStore.configured) return null;
  return communityStore.deviceFromToken(tokenFromRequest(req));
}

async function requireCommunityDevice(req, res, next) {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    const device = await deviceFromRequest(req);
    if (!device) return res.status(401).json({ success: false, code: "DEVICE_AUTH_REQUIRED", error: "请先在本地客户端启用共享书库。" });
    req.communityDevice = device;
    return next();
  } catch (error) {
    console.error("Community device authentication failed", error);
    return res.status(503).json({ success: false, error: "公共书库暂时不可用。" });
  }
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

// Public community catalogue.  These routes intentionally sit before the
// legacy bridge middleware: listening to a shared book must not wake, expose,
// or depend on the maintainer's local Mac.
app.use("/v1", (req, res, next) => {
  const allowedOrigin = process.env.COMMUNITY_ALLOWED_ORIGIN || "*";
  res.setHeader("Access-Control-Allow-Origin", allowedOrigin);
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  if (req.method === "OPTIONS") return res.status(204).end();
  return next();
});

app.get("/v1/health", (_req, res) => {
  res.json({ success: true, configured: communityStore.configured, objectStore: objectStore.enabled, hotCacheLimitBytes: Number(process.env.R2_HOT_MAX_BYTES || 8 * 1024 ** 3) });
});

app.post("/v1/auth/devices", express.json({ limit: "64kb" }), async (req, res) => {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    if (req.body?.accepted !== true) return res.status(400).json({ success: false, error: "需要确认共享书库告知后才能自动贡献。" });
    const device = await communityStore.createDevice({
      displayName: req.body?.displayName,
      publicKey: req.body?.publicKey,
      consentVersion: req.body?.consentVersion,
    });
    return res.status(201).json({ success: true, ...device });
  } catch (error) {
    console.error("Community device registration failed", error);
    return res.status(500).json({ success: false, error: "无法创建共享设备身份。" });
  }
});

app.get("/v1/library", async (req, res) => {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    const limit = Math.max(1, Math.min(50, Number.parseInt(req.query.limit || "20", 10) || 20));
    const offset = Math.max(0, Number.parseInt(req.query.offset || "0", 10) || 0);
    const items = await communityStore.listLibrary({ query: req.query.q, limit, offset });
    return res.json({ success: true, items, nextOffset: items.length === limit ? offset + limit : null });
  } catch (error) {
    console.error("Community library listing failed", error);
    return res.status(500).json({ success: false, error: "书库暂时无法读取。" });
  }
});

app.get("/v1/works/:workId", async (req, res) => {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    const work = await communityStore.workDetail(req.params.workId);
    if (!work) return res.status(404).json({ success: false, error: "未找到这部作品。" });
    return res.json({ success: true, work });
  } catch (error) {
    console.error("Community work lookup failed", error);
    return res.status(500).json({ success: false, error: "作品详情暂时无法读取。" });
  }
});

app.post("/v1/editions/resolve", express.json({ limit: "256kb" }), async (req, res) => {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    const manifestHash = String(req.body?.manifestHash || "").toLowerCase();
    const recipeHash = String(req.body?.recipeHash || "").toLowerCase();
    if (!validHash(manifestHash) || !validHash(recipeHash)) return res.status(400).json({ success: false, error: "作品或声线配方指纹不正确。" });
    const result = await communityStore.resolveEdition({ manifestHash, recipeHash });
    return res.json({ success: true, match: result });
  } catch (error) {
    console.error("Community edition resolve failed", error);
    return res.status(500).json({ success: false, error: "无法检查公共缓存。" });
  }
});

app.post("/v1/artifacts/resolve", express.json({ limit: "256kb" }), async (req, res) => {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    const manifestHash = String(req.body?.manifestHash || "").toLowerCase();
    const recipeHash = String(req.body?.recipeHash || "").toLowerCase();
    if (!validHash(manifestHash) || !validHash(recipeHash)) return res.status(400).json({ success: false, error: "作品或声线配方指纹不正确。" });
    const result = await communityStore.resolveEdition({ manifestHash, recipeHash });
    return res.json({ success: true, match: result });
  } catch (error) {
    console.error("Community artifact resolve failed", error);
    return res.status(500).json({ success: false, error: "无法检查公共缓存。" });
  }
});

app.post("/v1/contributions/initiate", express.json({ limit: "512kb" }), requireCommunityDevice, async (req, res) => {
  try {
    const body = req.body || {};
    const chapters = Array.isArray(body.chapters) ? body.chapters.map(normalizeChapter).filter(Boolean) : [];
    const chapter = normalizeChapter(body.chapter);
    const manifestHash = String(body.edition?.manifestHash || "").toLowerCase();
    const recipeHash = String(body.recipe?.recipeHash || "").toLowerCase();
    const audioSha = String(body.audio?.sha256 || "").toLowerCase();
    const byteSize = Number(body.audio?.byteSize || 0);
    const durationSeconds = Number(body.audio?.durationSeconds || 0);
    if (!chapters.length || !chapter || !chapters.some(item => item.index === chapter.index && item.textHash === chapter.textHash) || !validHash(manifestHash) || !validHash(recipeHash) || !validHash(audioSha) || !Number.isFinite(byteSize) || byteSize < 1024 || byteSize > 512 * 1024 ** 2 || !Number.isFinite(durationSeconds) || durationSeconds <= 0) {
      return res.status(400).json({ success: false, error: "贡献资料不完整或音频参数不安全。" });
    }
    const work = {
      title: String(body.work?.title || "未命名作品").trim().slice(0, 300),
      author: String(body.work?.author || "").trim().slice(0, 160),
      description: String(body.work?.description || "").trim().slice(0, 2000),
      coverUrl: String(body.work?.coverUrl || "").trim().slice(0, 2000),
    };
    if (!work.title) return res.status(400).json({ success: false, error: "请提供作品标题。" });
    const contribution = {
      work,
      edition: { manifestHash },
      chapters,
      chapter,
      recipe: {
        recipeHash,
        modelVersion: String(body.recipe?.modelVersion || "qwen3-tts").slice(0, 200),
        voiceManifest: body.recipe?.voiceManifest && typeof body.recipe.voiceManifest === "object" ? body.recipe.voiceManifest : {},
        settings: body.recipe?.settings && typeof body.recipe.settings === "object" ? body.recipe.settings : {},
      },
      audio: { sha256: audioSha, byteSize: Math.floor(byteSize), durationSeconds, codec: "opus", sampleRate: 24000 },
      validation: body.validation && typeof body.validation === "object" ? body.validation : {},
    };
    if (objectStore.enabled) {
      await communityStore.evictHotCache({
        reserveBytes: contribution.audio.byteSize,
        deleteObject: key => objectStore.deleteObject(key),
      });
    }
    const result = await communityStore.initiateContribution({ deviceId: req.communityDevice.id, contribution, preferHotCache: objectStore.enabled });
    const uploadUrl = result.hotCacheAvailable && !result.duplicate ? await objectStore.uploadUrl(result.objectKey) : null;
    return res.status(201).json({ success: true, ...result, upload: uploadUrl ? { url: uploadUrl, method: "PUT", contentType: "audio/ogg" } : null, seedRequired: true });
  } catch (error) {
    console.error("Community contribution initiate failed", error);
    return res.status(500).json({ success: false, error: "无法登记自动贡献。" });
  }
});

app.post("/v1/contributions/:contributionId/complete", express.json({ limit: "128kb" }), requireCommunityDevice, async (req, res) => {
  try {
    const artifactId = String(req.body?.artifactId || "");
    const cached = Boolean(req.body?.cached && objectStore.enabled);
    const objectKey = cached ? String(req.body?.objectKey || "") : null;
    const byteSize = Number(req.body?.byteSize || 0);
    const durationSeconds = Number(req.body?.durationSeconds || 0);
    if (!artifactId || !Number.isFinite(byteSize) || byteSize < 1024 || !Number.isFinite(durationSeconds) || durationSeconds <= 0 || (cached && !objectKey.startsWith(`artifacts/${artifactId}/`))) {
      return res.status(400).json({ success: false, error: "贡献完成信息不正确。" });
    }
    if (cached) {
      const objectInfo = await objectStore.inspectObject(objectKey);
      if (!objectInfo || objectInfo.byteSize !== Math.floor(byteSize) || !String(objectInfo.contentType || "").startsWith("audio/")) {
        return res.status(400).json({ success: false, error: "云端未验证到完整的 Opus 音频。" });
      }
    }
    const completed = await communityStore.completeContribution({
      deviceId: req.communityDevice.id,
      contributionId: req.params.contributionId,
      artifactId,
      result: { cached, objectKey, byteSize: Math.floor(byteSize), durationSeconds, validation: req.body?.validation && typeof req.body.validation === "object" ? req.body.validation : {} },
    });
    if (!completed) return res.status(404).json({ success: false, error: "未找到该贡献记录。" });
    return res.json({ success: true, ...completed });
  } catch (error) {
    console.error("Community contribution complete failed", error);
    return res.status(500).json({ success: false, error: "无法确认贡献完成。" });
  }
});

app.post("/v1/peers/announce", express.json({ limit: "256kb" }), requireCommunityDevice, async (req, res) => {
  try {
    const artifacts = Array.isArray(req.body?.artifacts) ? [...new Set(req.body.artifacts.map(String).filter(value => /^[a-f0-9-]{36}$/i.test(value)))].slice(0, 500) : [];
    if (!artifacts.length) return res.status(400).json({ success: false, error: "没有可做种的章节。" });
    await communityStore.announcePeers(req.communityDevice.id, artifacts, String(req.body?.endpoint || "").slice(0, 1000));
    return res.json({ success: true, announced: artifacts.length, ttlSeconds: 90 });
  } catch (error) {
    console.error("Community peer announce failed", error);
    return res.status(500).json({ success: false, error: "无法更新在线贡献状态。" });
  }
});

app.get("/v1/artifacts/:artifactId/sources", async (req, res) => {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    const sources = await communityStore.artifactSources(req.params.artifactId);
    if (!sources) return res.status(404).json({ success: false, error: "音频尚未可用。" });
    const cachedUrl = sources.artifact.r2_key ? await objectStore.downloadUrl(sources.artifact.r2_key) : null;
    return res.json({ success: true, state: cachedUrl ? "cached" : sources.peers.length ? "peer" : "waiting", audioUrl: cachedUrl, peers: sources.peers.map(peer => ({ deviceId: peer.device_id, lastSeenAt: peer.last_seen_at })), codec: sources.artifact.codec, durationSeconds: Number(sources.artifact.duration_seconds || 0) });
  } catch (error) {
    console.error("Community artifact source lookup failed", error);
    return res.status(500).json({ success: false, error: "无法查询音频来源。" });
  }
});

// A listener receives a short-lived opaque ticket rather than a contributor's
// device credential.  The ticket is only used to exchange WebRTC SDP/ICE
// messages through /v1/peers/connect; no audio bytes ever traverse Render.
app.post("/v1/artifacts/:artifactId/peer-ticket", express.json({ limit: "8kb" }), async (req, res) => {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    const sources = await communityStore.artifactSources(req.params.artifactId);
    if (!sources?.peers?.length) return res.status(409).json({ success: false, error: "暂无在线贡献节点。" });
    const ticket = crypto.randomBytes(24).toString("base64url");
    const expiresAt = Date.now() + 2 * 60_000;
    peerTickets.set(ticket, { artifactId: req.params.artifactId, expiresAt, listener: null });
    return res.status(201).json({ success: true, ticket, expiresAt, peerCount: sources.peers.length, websocketPath: "/v1/peers/connect" });
  } catch (error) {
    console.error("Community peer ticket failed", error);
    return res.status(500).json({ success: false, error: "无法建立社区直连。" });
  }
});

app.post("/v1/artifacts/:artifactId/playback", express.json({ limit: "32kb" }), async (req, res) => {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    const device = await deviceFromRequest(req);
    const secondsPlayed = Math.max(0, Math.min(3600, Number(req.body?.secondsPlayed || 0)));
    await communityStore.playback(req.params.artifactId, device?.id || null, secondsPlayed);
    return res.status(204).end();
  } catch (error) {
    console.error("Community playback update failed", error);
    return res.status(500).json({ success: false, error: "无法记录播放状态。" });
  }
});

app.post("/v1/reports", express.json({ limit: "64kb" }), async (req, res) => {
  try {
    if (!communityStore.configured) return communityUnavailable(res);
    const category = String(req.body?.category || "other").slice(0, 80);
    const device = await deviceFromRequest(req);
    const reportId = await communityStore.report({ artifactId: req.body?.artifactId, workId: req.body?.workId, deviceId: device?.id || null, category, detail: String(req.body?.detail || "").slice(0, 4000) });
    return res.status(201).json({ success: true, reportId });
  } catch (error) {
    console.error("Community report failed", error);
    return res.status(500).json({ success: false, error: "无法提交反馈。" });
  }
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
const peerWebsocketServer = new WebSocketServer({ noServer: true, maxPayload: 128 * 1024 });

server.on("upgrade", (req, socket, head) => {
  const requestUrl = new URL(req.url || "/", "http://localhost");
  if (requestUrl.pathname === "/bridge/connect") {
    websocketServer.handleUpgrade(req, socket, head, ws => websocketServer.emit("connection", ws));
    return;
  }
  if (requestUrl.pathname === "/v1/peers/connect" && communityStore.configured) {
    peerWebsocketServer.handleUpgrade(req, socket, head, ws => peerWebsocketServer.emit("connection", ws));
    return;
  }
  socket.destroy();
});

function sendPeer(ws, message) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
}

function cleanExpiredPeerTickets() {
  const now = Date.now();
  for (const [ticket, value] of peerTickets) {
    if (value.expiresAt < now) peerTickets.delete(ticket);
  }
}

peerWebsocketServer.on("connection", ws => {
  let device = null;
  let listenerTicket = null;
  let announcedArtifacts = new Set();
  const authTimer = setTimeout(() => ws.close(4401, "authentication timeout"), 15_000);

  ws.on("message", async raw => {
    let message;
    try { message = JSON.parse(raw.toString()); } catch { ws.close(4400, "invalid message"); return; }
    try {
      if (!device && !listenerTicket) {
        if (message.type === "auth") {
          device = await communityStore.deviceFromToken(String(message.token || ""));
          if (!device) { ws.close(4403, "forbidden"); return; }
          clearTimeout(authTimer);
          communityPeers.set(device.id, ws);
          sendPeer(ws, { type: "auth_ok", deviceId: device.id, protocol: "shengyue-webrtc-signal-v1" });
          return;
        }
        if (message.type === "listen") {
          cleanExpiredPeerTickets();
          const ticket = String(message.ticket || "");
          const entry = peerTickets.get(ticket);
          if (!entry || entry.listener) { ws.close(4404, "invalid ticket"); return; }
          entry.listener = ws;
          listenerTicket = ticket;
          clearTimeout(authTimer);
          sendPeer(ws, { type: "listen_ok", ticket, artifactId: entry.artifactId, protocol: "shengyue-webrtc-signal-v1" });
          return;
        }
        ws.close(4403, "authentication required");
        return;
      }

      if (message.type === "heartbeat") { sendPeer(ws, { type: "heartbeat_ack", at: new Date().toISOString() }); return; }
      if (device && message.type === "announce") {
        announcedArtifacts = new Set((Array.isArray(message.artifacts) ? message.artifacts : []).map(String).filter(value => /^[a-f0-9-]{36}$/i.test(value)).slice(0, 500));
        // Keep the active set on the socket as well: listeners are matched
        // only to currently connected contributors that explicitly announced
        // the requested artifact.
        ws._shengyueArtifacts = announcedArtifacts;
        await communityStore.announcePeers(device.id, [...announcedArtifacts], null);
        sendPeer(ws, { type: "announce_ok", count: announcedArtifacts.size });
        return;
      }

      const ticket = String(message.ticket || listenerTicket || "");
      const entry = peerTickets.get(ticket);
      if (message.type === "signal" && entry && entry.expiresAt >= Date.now()) {
        if (listenerTicket === ticket) {
          let delivered = 0;
          for (const peer of communityPeers.values()) {
            if (peer === ws || !peer._shengyueArtifacts?.has(entry.artifactId)) continue;
            sendPeer(peer, { type: "signal", ticket, artifactId: entry.artifactId, from: "listener", payload: message.payload || {} });
            delivered += 1;
          }
          sendPeer(ws, { type: "signal_sent", ticket, delivered });
          return;
        }
        if (device && announcedArtifacts.has(entry.artifactId) && entry.listener) {
          sendPeer(entry.listener, { type: "signal", ticket, artifactId: entry.artifactId, from: device.id, payload: message.payload || {} });
          return;
        }
      }
      sendPeer(ws, { type: "error", error: "无效的社区直连消息。" });
    } catch (error) {
      console.warn(`Community peer websocket error: ${error.message}`);
      sendPeer(ws, { type: "error", error: "社区直连暂时不可用。" });
    }
  });

  ws.on("close", () => {
    clearTimeout(authTimer);
    if (device && communityPeers.get(device.id) === ws) communityPeers.delete(device.id);
    if (listenerTicket) {
      const entry = peerTickets.get(listenerTicket);
      if (entry?.listener === ws) entry.listener = null;
    }
  });
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

async function startServer() {
  if (communityStore.configured) {
    await communityStore.init();
    console.log("ShengYue community catalogue database is ready.");
  } else {
    console.warn("Community catalogue disabled: DATABASE_URL is not configured.");
  }
  server.listen(port, "0.0.0.0", () => {
    console.log(`ShengYue cloud relay listening on ${port}`);
    if (publicOrigin) console.log(`Public origin: ${publicOrigin}`);
  });
}

startServer().catch(error => {
  console.error("Failed to start ShengYue relay", error);
  process.exitCode = 1;
});
