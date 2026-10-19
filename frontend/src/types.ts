export type AppStage = 'text' | 'casting' | 'generate'

export interface Speaker {
  name: string
  voice?: string
  gender?: string
  mentions?: number
  dialogue_count?: number
  confidence?: number
}

export interface AnalysisStats {
  speakers: Speaker[]
  word_count?: number
  total_chunks?: number
  estimated_duration?: string
  section_count?: number
}

export interface ProjectDraft {
  id: string
  name: string
  text: string
  createdAt: string
  updatedAt: string
  engine: string
  outputFormat: 'mp3' | 'wav'
  outputBitrate: number
  streamingMode: boolean
  splitByChapter: boolean
  fullStory: boolean
  voiceAssignments: Record<string, string>
  analysis?: AnalysisStats
}

export interface GenerationJob {
  job_id: string
  status: string
  progress: number
  created_at?: string
  text_preview?: string
  error?: string
  total_chunks?: number
  processed_chunks?: number
  eta_seconds?: number
  chapter_count?: number
  active_chapter_title?: string
  streaming_mode?: boolean
  streaming_warning?: string
  streaming_phase?: string
  streaming_pipeline_version?: number
  cast_audit?: CastAudit
  recast?: {
    mode?: string
    reused_segments?: number
    pending_segments?: number
    manifest?: string
  }
  streaming_summary?: {
    ready_chapters?: number
    streamable_chapters?: number
    playable_chapters?: number
    legacy_playable_chapters?: number
    chapter_count?: number
    active_chapter_progress?: number
    current_chapter_index?: number
    highest_ready_chapter?: number
    highest_playable_chapter?: number
    playback?: PlaybackState
  }
}

export interface PlaybackState {
  job_id?: string
  chapter_index: number
  current_time: number
  duration: number
  playback_rate: number
  state: string
  updated_at?: string
}

export interface LibraryChapter {
  index: number
  title?: string
  output_file?: string
  file_url?: string
  relative_path?: string
  file_size?: number
  format?: string
  missing_file?: boolean
  state?: string
  can_play?: boolean
  progress?: number
  duration_seconds?: number
  playable_seconds?: number
  playback_version?: 'legacy-v2' | 'speaker-pipeline-v3' | null
  generation_version?: number
  recast_state?: string | null
}

export interface CastCharacter {
  character_id: string
  name: string
  aliases: string[]
  gender: 'male' | 'female' | 'neutral'
  voice?: string
  role_tier: 'lead' | 'recurring' | 'extra'
  voice_locked: boolean
  appearance_chapter_count: number
  speech_count: number
  gender_confidence?: number
}

export interface CastAudit {
  ready: boolean
  status: 'ready' | 'review_required' | 'not_analyzed' | string
  pipeline_version: number
  counts?: {
    characters?: number
    segments?: number
    low_confidence_segments?: number
    blocking_issues?: number
  }
  gender_conflicts?: Array<Record<string, unknown>>
  scene_voice_conflicts?: Array<Record<string, unknown>>
  important_missing_voices?: Array<Record<string, unknown>>
  low_confidence_segments?: Array<Record<string, unknown>>
}

export interface LibraryItem {
  job_id: string
  title?: string
  collection_title?: string
  audiobook_title?: string
  audiobook_author?: string
  audiobook_description?: string
  created_at?: string
  engine?: string
  format?: string
  file_size?: number
  size?: number
  total_size?: number
  duration?: number
  output_file?: string
  chapter_count?: number
  chapter_mode?: boolean
  streaming_mode?: boolean
  chapters?: LibraryChapter[]
  full_story?: {
    title?: string
    output_file?: string
    relative_path?: string
    file_size?: number
    format?: string
  } | null
}

export interface StreamingBook {
  job_id: string
  status?: string
  phase?: string
  warning?: string
  playback?: PlaybackState
  summary?: GenerationJob['streaming_summary']
  chapters: LibraryChapter[]
}

export interface VoicePreset {
  id?: string
  code?: string
  name: string
  label?: string
  description?: string
  gender?: string
  language?: string
  category?: string
  default_state?: string
}

export interface AppSettings {
  tts_engine?: string
  output_format?: string
  output_bitrate?: number
  [key: string]: unknown
}

export interface SiteAssistantMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface SiteAssistantAction {
  path: string
  label: string
}

export interface SiteAssistantStatus {
  connected: boolean
  provider: 'ollama' | 'lmstudio'
  provider_label: string
  model: string
  available_models: string[]
  prompt_version: string
  error?: string
}

export interface SiteAssistantReply {
  message: SiteAssistantMessage
  provider: string
  model: string
  prompt_version: string
  suggested_actions: SiteAssistantAction[]
}

export interface CommunityContribution {
  job_id: string
  chapter_index: number
  state: 'uploading' | 'complete' | 'failed' | 'seeded' | 'registered'
  artifact_id?: string
  error?: string
  updated_at: number
}

export interface CommunityStatus {
  enabled: boolean
  shared_enabled: boolean
  auto_contribute: boolean
  api_url: string
  device_id: string
  contributions: CommunityContribution[]
}

export type BookAccess = 'public' | 'login_required' | 'paid' | 'unknown'

export type SourceSearchStatus = 'queued' | 'running' | 'success' | 'login_required' | 'failed' | 'timeout'

export interface BookSearchOffer {
  title: string
  authors: string[]
  cover_url?: string
  description?: string
  source_id: string
  source_name: string
  url: string
  download_url?: string
  download_format?: 'TXT' | 'EPUB' | 'PDF' | ''
  updated_at?: string
  book_type?: string
  mature: boolean
  access: BookAccess
  importable: boolean
  license?: string
  isbns?: string[]
  rank?: number
  score?: number
}

export interface BookSearchGroup {
  id: string
  title: string
  authors: string[]
  cover_url?: string
  description?: string
  book_type: string
  mature: boolean
  access: BookAccess
  importable: boolean
  source_count: number
  offers: BookSearchOffer[]
  saved_at?: string
}

export interface SourceSearchState {
  id: string
  name: string
  mature: boolean
  status: SourceSearchStatus
  result_count: number
  available_count: number
  message: string
}

export interface BookSearchJob {
  id: string
  query: string
  page: number
  include_mature: boolean
  created_at: string
  completed_at?: string | null
  status: 'queued' | 'running' | 'completed' | 'failed'
  sources: SourceSearchState[]
  results: BookSearchGroup[]
  result_count: number
  has_next_page: boolean
}

export interface BookSearchSource {
  id: string
  name: string
  kind: string
  domain: string
  homepage_url: string
  release_url: string
  search_url_template: string
  confirmed_origin: string
  book_type: string
  mature: boolean
  enabled: boolean
  builtin: boolean
  credential_supported: boolean
  credential_configured: boolean
  health: 'ready' | 'degraded' | 'needs_origin'
  health_message: string
}

export interface BookSearchHistoryEntry {
  id: string
  query: string
  filters: {
    page?: number
    source_ids?: string[]
    include_mature?: boolean
  }
  created_at: string
}

export interface ImportedPublicBook {
  group_id: string
  title: string
  authors: string[]
  text: string
  char_count: number
  source_id: string
  source_name: string
  source_url: string
  download_url: string
  license: string
}
