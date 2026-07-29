-- ShengYue community library.  Audio remains in R2 or on contributor devices;
-- Postgres stores only the public catalogue, fingerprints, and availability.
CREATE TABLE IF NOT EXISTS community_devices (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    public_key TEXT,
    consent_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS community_works (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    description TEXT,
    cover_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS community_editions (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES community_works(id) ON DELETE CASCADE,
    manifest_hash TEXT NOT NULL UNIQUE,
    chapter_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS community_chapters (
    id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES community_editions(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    UNIQUE(edition_id, chapter_index),
    UNIQUE(edition_id, text_hash)
);

CREATE TABLE IF NOT EXISTS community_recipes (
    recipe_hash TEXT PRIMARY KEY,
    model_version TEXT NOT NULL,
    voice_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS community_artifacts (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES community_chapters(id) ON DELETE CASCADE,
    recipe_hash TEXT NOT NULL REFERENCES community_recipes(recipe_hash) ON DELETE RESTRICT,
    artifact_key TEXT NOT NULL,
    audio_sha256 TEXT NOT NULL,
    duration_seconds REAL NOT NULL DEFAULT 0,
    byte_size BIGINT NOT NULL DEFAULT 0,
    codec TEXT NOT NULL DEFAULT 'opus',
    sample_rate INTEGER NOT NULL DEFAULT 24000,
    state TEXT NOT NULL DEFAULT 'seeded' CHECK(state IN ('seeded', 'provisional', 'verified', 'quarantined', 'disabled')),
    r2_key TEXT,
    r2_cached_at TIMESTAMPTZ,
    heat_score REAL NOT NULL DEFAULT 0,
    last_played_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(chapter_id, recipe_hash, audio_sha256)
);

CREATE INDEX IF NOT EXISTS community_artifacts_lookup_idx
    ON community_artifacts(chapter_id, recipe_hash, state);
CREATE INDEX IF NOT EXISTS community_artifacts_cache_idx
    ON community_artifacts(r2_key, heat_score, last_played_at);

CREATE TABLE IF NOT EXISTS community_contributions (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES community_artifacts(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES community_devices(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('registered', 'uploading', 'seeded', 'complete', 'rejected')),
    validation JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS community_peers (
    artifact_id TEXT NOT NULL REFERENCES community_artifacts(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES community_devices(id) ON DELETE CASCADE,
    endpoint TEXT,
    available BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(artifact_id, device_id)
);
CREATE INDEX IF NOT EXISTS community_peers_live_idx
    ON community_peers(artifact_id, available, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS community_playback_events (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES community_artifacts(id) ON DELETE CASCADE,
    device_id TEXT REFERENCES community_devices(id) ON DELETE SET NULL,
    seconds_played REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS community_reports (
    id TEXT PRIMARY KEY,
    artifact_id TEXT REFERENCES community_artifacts(id) ON DELETE SET NULL,
    work_id TEXT REFERENCES community_works(id) ON DELETE SET NULL,
    reporter_device_id TEXT REFERENCES community_devices(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    detail TEXT,
    state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open', 'resolved', 'dismissed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
