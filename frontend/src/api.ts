import { z } from 'zod'
import type { AnalysisStats, AppSettings, BookSearchGroup, BookSearchHistoryEntry, BookSearchJob, BookSearchSource, CastAudit, CastCharacter, CommunityStatus, GenerationJob, ImportedPublicBook, LibraryItem, SiteAssistantMessage, SiteAssistantReply, SiteAssistantStatus, StreamingBook, VoicePreset } from './types'

const responseSchema = z.object({ success: z.boolean().optional(), error: z.string().optional() }).passthrough()

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
  })
  const data: unknown = await response.json().catch(() => ({}))
  const parsed = responseSchema.safeParse(data)
  if (!response.ok || (parsed.success && parsed.data.success === false)) {
    throw new Error(parsed.success ? parsed.data.error || '请求失败，请稍后重试。' : `请求失败（${response.status}）`)
  }
  return data as T
}

export const api = {
  health: () => request<Record<string, unknown>>('/api/health'),
  queue: async () => {
    const data = await request<{ jobs?: GenerationJob[]; current_job?: string; queue_size?: number }>('/api/queue')
    return { jobs: data.jobs ?? [], currentJob: data.current_job, queueSize: data.queue_size ?? 0 }
  },
  library: async () => {
    const data = await request<{ library?: LibraryItem[]; items?: LibraryItem[] }>('/api/library')
    return data.library ?? data.items ?? []
  },
  streamingBook: (jobId: string, chapterIndex?: number) => request<StreamingBook>(`/api/jobs/${encodeURIComponent(jobId)}/chapters${chapterIndex === undefined ? '' : `?chapter=${chapterIndex}`}`),
  reportPlayback: (jobId: string, payload: { chapter_index: number; current_time: number; duration: number; playback_rate: number; state: string }) => request(`/api/jobs/${encodeURIComponent(jobId)}/playback`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  prioritizeChapter: (jobId: string, chapterIndex: number) => request(`/api/jobs/${encodeURIComponent(jobId)}/chapters/${chapterIndex}/priority`, { method: 'POST' }),
  castAudit: (jobId: string) => request<CastAudit & { success?: boolean; job_id?: string }>(`/api/jobs/${encodeURIComponent(jobId)}/cast-audit`),
  characters: async (jobId: string) => {
    const data = await request<{ characters?: CastCharacter[] }>(`/api/jobs/${encodeURIComponent(jobId)}/characters`)
    return data.characters ?? []
  },
  recast: (jobId: string) => request<{ audit: CastAudit; reused_segments: number; pending_segments: number }>(`/api/jobs/${encodeURIComponent(jobId)}/recast`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'reuse_verified' }),
  }),
  updateLibraryTitle: (jobId: string, title: string) => request<{ title: string }>(`/api/library/${encodeURIComponent(jobId)}/title`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  }),
  settings: async () => {
    const data = await request<{ settings: AppSettings }>('/api/settings')
    return data.settings
  },
  saveSettings: (settings: AppSettings) => request<AppSettings>('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settings) }),
  voices: async () => {
    const data = await request<{ presets?: VoicePreset[]; voices?: VoicePreset[] }>('/api/qwen3/voice-design/presets')
    return data.presets ?? data.voices ?? []
  },
  auditionVoicePreset: (payload: { text: string; presetId: string; actingState?: string }) => request<{ audio_base64: string; mime_type?: string }>('/api/qwen3/voice-design/audition', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: payload.text, preset_id: payload.presetId, acting_state: payload.actingState }),
  }),
  voicePrompts: async () => {
    const data = await request<{ voices?: VoicePreset[]; prompts?: VoicePreset[] }>('/api/voice-prompts')
    return data.voices ?? data.prompts ?? []
  },
  analyze: (text: string, ttsEngine: string) => request<{ statistics: AnalysisStats }>('/api/analyze', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, tts_engine: ttsEngine }),
  }),
  extractDocument: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<{ text: string; filename: string; char_count: number }>('/api/extract-document', { method: 'POST', body })
  },
  generate: (payload: Record<string, unknown>) => request<{ job_id: string; queue_position?: number }>('/api/generate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  jobAction: (jobId: string, action: 'pause' | 'resume' | 'cancel') => request(`/api/${action === 'cancel' ? 'cancel' : `jobs/${jobId}/${action}`}${action === 'cancel' ? `/${jobId}` : ''}`, { method: 'POST' }),
  help: async () => {
    const data = await request<{ articles?: Array<{ id: string; title: string; summary?: string }> }>('/api/help/catalog')
    return data.articles ?? []
  },
  communityStatus: () => request<CommunityStatus>('/api/community/status'),
  enableCommunity: (apiUrl: string) => request<{ enabled: boolean; device_id?: string }>('/api/community/enable', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accepted: true, api_url: apiUrl }) }),
  disableCommunity: () => request<{ enabled: boolean }>('/api/community/disable', { method: 'POST' }),
  backfillCommunity: (jobId: string) => request<{ queued: number; message?: string }>(`/api/community/jobs/${encodeURIComponent(jobId)}/backfill`, { method: 'POST' }),
  bookSearchSources: async () => {
    const data = await request<{ sources: BookSearchSource[]; searxng_url: string }>('/api/book-search/sources')
    return data
  },
  createBookSearch: (payload: { query: string; page?: number; source_ids?: string[]; include_mature?: boolean }) => request<{ job: BookSearchJob; job_id: string }>('/api/book-search/jobs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  bookSearchJob: async (jobId: string) => {
    const data = await request<{ job: BookSearchJob }>(`/api/book-search/jobs/${encodeURIComponent(jobId)}`)
    return data.job
  },
  importPublicBook: async (jobId: string, groupId: string) => {
    const data = await request<{ book: ImportedPublicBook }>(`/api/book-search/jobs/${encodeURIComponent(jobId)}/import`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ group_id: groupId }),
    })
    return data.book
  },
  bookSearchHistory: async () => {
    const data = await request<{ history: BookSearchHistoryEntry[] }>('/api/book-search/history')
    return data.history
  },
  deleteBookSearchHistory: (id?: string) => request<{ deleted: number }>('/api/book-search/history', {
    method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(id ? { id } : {}),
  }),
  bookSearchFavorites: async () => {
    const data = await request<{ favorites: BookSearchGroup[] }>('/api/book-search/favorites')
    return data.favorites
  },
  saveBookSearchFavorite: (favorite: BookSearchGroup) => request<{ favorite: BookSearchGroup }>('/api/book-search/favorites', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(favorite),
  }),
  deleteBookSearchFavorite: (id: string) => request<{ deleted: boolean }>('/api/book-search/favorites', {
    method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }),
  }),
  createBookSearchSource: (source: { name: string; domain: string; search_url_template: string; book_type?: string; mature?: boolean }) => request<{ source: BookSearchSource }>('/api/book-search/sources', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(source),
  }),
  updateBookSearchSource: (id: string, update: { enabled?: boolean; confirmed_origin?: string; release_url?: string; name?: string; mature?: boolean }) => request<{ source: BookSearchSource }>('/api/book-search/sources', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, ...update }),
  }),
  deleteBookSearchSource: (id: string) => request<{ deleted: boolean }>('/api/book-search/sources', {
    method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }),
  }),
  discoverSoushuba: () => request<{ candidates: Array<{ origin: string; verified: boolean; title: string; discovered_via: 'release_page' | 'searxng' }> }>('/api/book-search/sources/soushuba/discover', { method: 'POST' }),
  saveBookSourceCredentials: (sourceId: string, username: string, password: string) => request<{ credential_configured: boolean }>(`/api/book-search/sources/${encodeURIComponent(sourceId)}/credentials`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }),
  }),
  deleteBookSourceCredentials: (sourceId: string) => request<{ credential_configured: boolean }>(`/api/book-search/sources/${encodeURIComponent(sourceId)}/credentials`, { method: 'DELETE' }),
  siteAssistantStatus: () => request<SiteAssistantStatus>('/api/site-assistant/status'),
  siteAssistantChat: (payload: { messages: SiteAssistantMessage[]; context: Record<string, string> }) => request<SiteAssistantReply>('/api/site-assistant/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
}
