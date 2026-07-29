import crypto from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

const { Pool } = pg;
const here = path.dirname(fileURLToPath(import.meta.url));
const migrationPath = path.join(here, "migrations", "001_community_library.sql");
const HOT_CACHE_LIMIT_BYTES = Number.parseInt(process.env.R2_HOT_MAX_BYTES || String(8 * 1024 ** 3), 10);

const id = () => crypto.randomUUID();
const hash = value => crypto.createHash("sha256").update(String(value)).digest("hex");

function cleanText(value, max = 400) {
  return String(value || "").trim().slice(0, max);
}

function parseJson(value, fallback = {}) {
  if (!value) return fallback;
  if (typeof value === "object") return value;
  try { return JSON.parse(value); } catch { return fallback; }
}

function publicArtifact(row) {
  return {
    id: row.artifact_id || row.id,
    artifactKey: row.artifact_key,
    chapterIndex: Number(row.chapter_index),
    chapterTitle: row.chapter_title,
    recipeHash: row.recipe_hash,
    durationSeconds: Number(row.duration_seconds || 0),
    byteSize: Number(row.byte_size || 0),
    codec: row.codec || "opus",
    sampleRate: Number(row.sample_rate || 24000),
    state: row.state,
    cached: Boolean(row.r2_key),
  };
}

export class CommunityStore {
  constructor(databaseUrl) {
    this.pool = databaseUrl ? new Pool({ connectionString: databaseUrl, ssl: databaseUrl.includes("localhost") ? false : { rejectUnauthorized: false } }) : null;
  }

  get configured() { return Boolean(this.pool); }

  async init() {
    if (!this.pool) return false;
    const sql = await readFile(migrationPath, "utf8");
    await this.pool.query(sql);
    return true;
  }

  async close() { await this.pool?.end(); }

  async createDevice({ displayName, publicKey, consentVersion }) {
    const deviceId = id();
    const token = crypto.randomBytes(32).toString("base64url");
    await this.pool.query(
      `INSERT INTO community_devices (id, token_hash, display_name, public_key, consent_at)
       VALUES ($1, $2, $3, $4, NOW())`,
      [deviceId, hash(token), cleanText(displayName || "声阅设备", 80), cleanText(publicKey, 4096) || null],
    );
    return { deviceId, token, consentVersion: cleanText(consentVersion, 50) || "community-v1" };
  }

  async deviceFromToken(token) {
    if (!token) return null;
    const result = await this.pool.query(
      `UPDATE community_devices SET last_seen_at=NOW()
       WHERE token_hash=$1 AND revoked_at IS NULL
       RETURNING id, display_name, public_key`, [hash(token)],
    );
    return result.rows[0] || null;
  }

  async resolveEdition({ manifestHash, recipeHash }) {
    const edition = await this.pool.query(
      `SELECT e.id, e.manifest_hash, e.chapter_count, w.id AS work_id, w.title, w.author, w.description, w.cover_url
       FROM community_editions e JOIN community_works w ON w.id=e.work_id WHERE e.manifest_hash=$1`, [manifestHash],
    );
    if (!edition.rowCount) return null;
    const artifacts = await this.pool.query(
      `SELECT a.id AS artifact_id, a.artifact_key, a.recipe_hash, a.duration_seconds, a.byte_size, a.codec, a.sample_rate,
              a.state, a.r2_key, c.chapter_index, c.title AS chapter_title
       FROM community_chapters c
       LEFT JOIN community_artifacts a ON a.chapter_id=c.id AND a.recipe_hash=$2
           AND a.state IN ('seeded', 'provisional', 'verified')
       WHERE c.edition_id=$1 ORDER BY c.chapter_index ASC, a.created_at ASC`,
      [edition.rows[0].id, recipeHash],
    );
    return {
      edition: {
        id: edition.rows[0].id,
        manifestHash: edition.rows[0].manifest_hash,
        chapterCount: edition.rows[0].chapter_count,
        work: { id: edition.rows[0].work_id, title: edition.rows[0].title, author: edition.rows[0].author, description: edition.rows[0].description, coverUrl: edition.rows[0].cover_url },
      },
      artifacts: artifacts.rows.map(publicArtifact),
    };
  }

  async ensureEdition(client, contribution) {
    const { work, edition, chapters } = contribution;
    const existing = await client.query(`SELECT id, work_id FROM community_editions WHERE manifest_hash=$1`, [edition.manifestHash]);
    if (existing.rowCount) return existing.rows[0];
    const workId = id();
    const editionId = id();
    await client.query(
      `INSERT INTO community_works (id, title, author, description, cover_url) VALUES ($1, $2, $3, $4, $5)`,
      [workId, work.title, work.author || null, work.description || null, work.coverUrl || null],
    );
    await client.query(
      `INSERT INTO community_editions (id, work_id, manifest_hash, chapter_count) VALUES ($1, $2, $3, $4)`,
      [editionId, workId, edition.manifestHash, chapters.length],
    );
    for (const chapter of chapters) {
      await client.query(
        `INSERT INTO community_chapters (id, edition_id, chapter_index, title, text_hash) VALUES ($1, $2, $3, $4, $5)`,
        [id(), editionId, chapter.index, chapter.title, chapter.textHash],
      );
    }
    return { id: editionId, work_id: workId };
  }

  async initiateContribution({ deviceId, contribution, preferHotCache }) {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const edition = await this.ensureEdition(client, contribution);
      const chapterResult = await client.query(
        `SELECT id, chapter_index, title FROM community_chapters WHERE edition_id=$1 AND text_hash=$2`,
        [edition.id, contribution.chapter.textHash],
      );
      if (!chapterResult.rowCount) throw new Error("章节正文与作品版本不一致。");
      const chapter = chapterResult.rows[0];
      await client.query(
        `INSERT INTO community_recipes (recipe_hash, model_version, voice_manifest, settings)
         VALUES ($1, $2, $3::jsonb, $4::jsonb)
         ON CONFLICT(recipe_hash) DO NOTHING`,
        [contribution.recipe.recipeHash, contribution.recipe.modelVersion, JSON.stringify(contribution.recipe.voiceManifest || {}), JSON.stringify(contribution.recipe.settings || {})],
      );
      const found = await client.query(
        `SELECT id, state, r2_key FROM community_artifacts
         WHERE chapter_id=$1 AND recipe_hash=$2 AND audio_sha256=$3`,
        [chapter.id, contribution.recipe.recipeHash, contribution.audio.sha256],
      );
      let artifact;
      if (found.rowCount) artifact = found.rows[0];
      else {
        const artifactId = id();
        const artifactKey = hash(`${contribution.chapter.textHash}:${contribution.recipe.recipeHash}`);
        const inserted = await client.query(
          `INSERT INTO community_artifacts
             (id, chapter_id, recipe_hash, artifact_key, audio_sha256, duration_seconds, byte_size, codec, sample_rate, state)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'seeded') RETURNING id, state, r2_key`,
          [artifactId, chapter.id, contribution.recipe.recipeHash, artifactKey, contribution.audio.sha256,
            contribution.audio.durationSeconds, contribution.audio.byteSize, contribution.audio.codec, contribution.audio.sampleRate],
        );
        artifact = inserted.rows[0];
      }
      const contributionId = id();
      await client.query(
        `INSERT INTO community_contributions (id, artifact_id, device_id, status, validation)
         VALUES ($1, $2, $3, 'registered', $4::jsonb)`,
        [contributionId, artifact.id, deviceId, JSON.stringify(contribution.validation || {})],
      );
      const usage = await client.query(`SELECT COALESCE(SUM(byte_size), 0)::bigint AS bytes FROM community_artifacts WHERE r2_key IS NOT NULL`);
      const hotCacheAvailable = preferHotCache && !artifact.r2_key && (Number(usage.rows[0].bytes) + contribution.audio.byteSize <= HOT_CACHE_LIMIT_BYTES);
      await client.query("COMMIT");
      return {
        contributionId,
        artifactId: artifact.id,
        chapterIndex: Number(chapter.chapter_index),
        hotCacheAvailable,
        objectKey: hotCacheAvailable ? `artifacts/${artifact.id}/${contribution.audio.sha256}.opus` : null,
        duplicate: Boolean(found.rowCount),
      };
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally { client.release(); }
  }

  async evictHotCache({ reserveBytes, deleteObject }) {
    if (!Number.isFinite(reserveBytes) || reserveBytes <= 0) return { evicted: 0, bytes: 0 };
    const usageResult = await this.pool.query(
      `SELECT COALESCE(SUM(byte_size), 0)::bigint AS bytes FROM community_artifacts WHERE r2_key IS NOT NULL`,
    );
    let usage = Number(usageResult.rows[0]?.bytes || 0);
    let evicted = 0;
    let reclaimed = 0;
    if (usage + reserveBytes <= HOT_CACHE_LIMIT_BYTES) return { evicted, bytes: reclaimed };

    // Keep recently played chapters and the only currently-online copies out
    // of the eviction pool.  This intentionally leaves a small safety margin
    // rather than turning a popular or sole live source into an interruption.
    const candidates = await this.pool.query(
      `SELECT a.id, a.r2_key, a.byte_size
       FROM community_artifacts a
       WHERE a.r2_key IS NOT NULL
         AND COALESCE(a.last_played_at, a.created_at) < NOW() - INTERVAL '10 minutes'
         AND NOT EXISTS (
           SELECT 1 FROM community_peers p
           WHERE p.artifact_id=a.id AND p.available=TRUE
             AND p.last_seen_at > NOW() - INTERVAL '90 seconds'
         )
       ORDER BY a.heat_score ASC, COALESCE(a.last_played_at, a.created_at) ASC
       LIMIT 500`,
    );
    for (const candidate of candidates.rows) {
      if (usage + reserveBytes <= HOT_CACHE_LIMIT_BYTES) break;
      try {
        await deleteObject(candidate.r2_key);
        const result = await this.pool.query(
          `UPDATE community_artifacts SET r2_key=NULL, r2_cached_at=NULL,
             state=CASE WHEN state='provisional' THEN 'seeded' ELSE state END,
             updated_at=NOW() WHERE id=$1 AND r2_key=$2`,
          [candidate.id, candidate.r2_key],
        );
        if (result.rowCount) {
          const size = Number(candidate.byte_size || 0);
          usage -= size;
          reclaimed += size;
          evicted += 1;
        }
      } catch (error) {
        console.warn(`Could not evict hot-cache object ${candidate.id}: ${error.message}`);
      }
    }
    return { evicted, bytes: reclaimed };
  }

  async completeContribution({ deviceId, contributionId, artifactId, result }) {
    const contribution = await this.pool.query(
      `SELECT id FROM community_contributions WHERE id=$1 AND artifact_id=$2 AND device_id=$3`, [contributionId, artifactId, deviceId],
    );
    if (!contribution.rowCount) return null;
    const state = result.cached ? "provisional" : "seeded";
    await this.pool.query(
      `UPDATE community_artifacts SET state=$2, r2_key=$3, r2_cached_at=CASE WHEN $3 IS NULL THEN r2_cached_at ELSE NOW() END,
          byte_size=$4, duration_seconds=$5, updated_at=NOW() WHERE id=$1`,
      [artifactId, state, result.objectKey || null, result.byteSize, result.durationSeconds],
    );
    await this.pool.query(
      `UPDATE community_contributions SET status=$2, validation=$3::jsonb, completed_at=NOW() WHERE id=$1`,
      [contributionId, result.cached ? "complete" : "seeded", JSON.stringify(result.validation || {})],
    );
    return { state, cached: Boolean(result.cached) };
  }

  async listLibrary({ query, limit, offset }) {
    const q = cleanText(query, 120);
    const params = [];
    let where = "WHERE EXISTS (SELECT 1 FROM community_artifacts a JOIN community_chapters c ON c.id=a.chapter_id WHERE c.edition_id=e.id AND a.state IN ('provisional','verified','seeded'))";
    if (q) { params.push(`%${q}%`); where += ` AND (w.title ILIKE $${params.length} OR COALESCE(w.author, '') ILIKE $${params.length})`; }
    params.push(limit, offset);
    const result = await this.pool.query(
      `SELECT w.id AS work_id, w.title, w.author, w.description, w.cover_url, e.id AS edition_id, e.chapter_count,
        COUNT(a.id) FILTER (WHERE a.state IN ('provisional','verified','seeded')) AS available_chapters,
        COUNT(a.id) FILTER (WHERE a.r2_key IS NOT NULL) AS cached_chapters,
        COALESCE(SUM(a.heat_score), 0) AS heat, MAX(a.created_at) AS updated_at
       FROM community_works w JOIN community_editions e ON e.work_id=w.id
       LEFT JOIN community_chapters c ON c.edition_id=e.id LEFT JOIN community_artifacts a ON a.chapter_id=c.id
       ${where}
       GROUP BY w.id, e.id ORDER BY heat DESC, updated_at DESC LIMIT $${params.length - 1} OFFSET $${params.length}`,
      params,
    );
    return result.rows.map(row => ({
      id: row.work_id, editionId: row.edition_id, title: row.title, author: row.author, description: row.description,
      coverUrl: row.cover_url, chapterCount: Number(row.chapter_count), availableChapters: Number(row.available_chapters),
      cachedChapters: Number(row.cached_chapters), heat: Number(row.heat), updatedAt: row.updated_at,
    }));
  }

  async workDetail(workId) {
    const work = await this.pool.query(`SELECT id, title, author, description, cover_url FROM community_works WHERE id=$1`, [workId]);
    if (!work.rowCount) return null;
    const editions = await this.pool.query(
      `SELECT id, manifest_hash, chapter_count FROM community_editions WHERE work_id=$1 ORDER BY created_at ASC`, [workId],
    );
    const detail = [];
    for (const edition of editions.rows) {
      const chapters = await this.pool.query(
        `SELECT c.chapter_index, c.title, c.text_hash,
          (SELECT a.id FROM community_artifacts a WHERE a.chapter_id=c.id AND a.state IN ('verified','provisional','seeded') ORDER BY CASE a.state WHEN 'verified' THEN 0 WHEN 'provisional' THEN 1 ELSE 2 END, a.heat_score DESC LIMIT 1) AS artifact_id,
          (SELECT a.state FROM community_artifacts a WHERE a.chapter_id=c.id AND a.state IN ('verified','provisional','seeded') ORDER BY CASE a.state WHEN 'verified' THEN 0 WHEN 'provisional' THEN 1 ELSE 2 END, a.heat_score DESC LIMIT 1) AS artifact_state,
          (SELECT a.r2_key IS NOT NULL FROM community_artifacts a WHERE a.chapter_id=c.id AND a.state IN ('verified','provisional','seeded') ORDER BY CASE a.state WHEN 'verified' THEN 0 WHEN 'provisional' THEN 1 ELSE 2 END, a.heat_score DESC LIMIT 1) AS cached,
          (SELECT COUNT(*) FROM community_peers p WHERE p.artifact_id=(SELECT a.id FROM community_artifacts a WHERE a.chapter_id=c.id AND a.state IN ('verified','provisional','seeded') ORDER BY CASE a.state WHEN 'verified' THEN 0 WHEN 'provisional' THEN 1 ELSE 2 END, a.heat_score DESC LIMIT 1) AND p.available=TRUE AND p.last_seen_at > NOW() - INTERVAL '90 seconds') AS peer_count
         FROM community_chapters c WHERE c.edition_id=$1 ORDER BY c.chapter_index`, [edition.id],
      );
      detail.push({ id: edition.id, manifestHash: edition.manifest_hash, chapterCount: Number(edition.chapter_count), chapters: chapters.rows.map(row => ({ index: Number(row.chapter_index), title: row.title, artifactId: row.artifact_id, availability: row.cached ? "cached" : Number(row.peer_count || 0) ? "peer" : "waiting", peerCount: Number(row.peer_count || 0) })) });
    }
    return { id: work.rows[0].id, title: work.rows[0].title, author: work.rows[0].author, description: work.rows[0].description, coverUrl: work.rows[0].cover_url, editions: detail };
  }

  async artifactSources(artifactId) {
    const artifact = await this.pool.query(
      `SELECT id, r2_key, state, codec, duration_seconds FROM community_artifacts WHERE id=$1 AND state IN ('seeded','provisional','verified')`, [artifactId],
    );
    if (!artifact.rowCount) return null;
    const peers = await this.pool.query(
      `SELECT p.device_id, p.endpoint, p.last_seen_at FROM community_peers p
       WHERE p.artifact_id=$1 AND p.available=TRUE AND p.last_seen_at > NOW() - INTERVAL '90 seconds'
       ORDER BY p.last_seen_at DESC LIMIT 12`, [artifactId],
    );
    return { artifact: artifact.rows[0], peers: peers.rows };
  }

  async announcePeers(deviceId, artifacts, endpoint) {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      for (const artifactId of artifacts) {
        await client.query(
          `INSERT INTO community_peers (artifact_id, device_id, endpoint, available, last_seen_at)
           VALUES ($1, $2, $3, TRUE, NOW())
           ON CONFLICT(artifact_id, device_id) DO UPDATE SET endpoint=excluded.endpoint, available=TRUE, last_seen_at=NOW()`,
          [artifactId, deviceId, endpoint || null],
        );
      }
      await client.query("COMMIT");
    } catch (error) { await client.query("ROLLBACK"); throw error; } finally { client.release(); }
  }

  async playback(artifactId, deviceId, secondsPlayed) {
    await this.pool.query(`UPDATE community_artifacts SET heat_score=heat_score+1, last_played_at=NOW(), updated_at=NOW() WHERE id=$1`, [artifactId]);
    await this.pool.query(`INSERT INTO community_playback_events (id, artifact_id, device_id, seconds_played) VALUES ($1, $2, $3, $4)`, [id(), artifactId, deviceId || null, secondsPlayed]);
  }

  async report({ artifactId, workId, deviceId, category, detail }) {
    const reportId = id();
    await this.pool.query(`INSERT INTO community_reports (id, artifact_id, work_id, reporter_device_id, category, detail) VALUES ($1,$2,$3,$4,$5,$6)`, [reportId, artifactId || null, workId || null, deviceId || null, category, detail || null]);
    return reportId;
  }
}

export function tokenFromRequest(req) {
  const raw = String(req.headers.authorization || "");
  return raw.startsWith("Bearer ") ? raw.slice(7).trim() : "";
}
