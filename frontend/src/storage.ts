import type { ProjectDraft } from './types'

const PROJECT_KEY = 'shengyue-projects-v2'
const ACTIVE_KEY = 'shengyue-active-project-v2'
const LEGACY_PROJECT_KEY = 'tts-story-projects'

const now = () => new Date().toISOString()

export function createProject(name = '未命名小说'): ProjectDraft {
  const timestamp = now()
  return {
    id: crypto.randomUUID(),
    name,
    text: '',
    createdAt: timestamp,
    updatedAt: timestamp,
    engine: 'qwen3_custom',
    outputFormat: 'mp3',
    outputBitrate: 128,
    streamingMode: true,
    splitByChapter: true,
    fullStory: false,
    voiceAssignments: {},
  }
}

function safeParse(value: string | null): unknown {
  if (!value) return []
  try {
    return JSON.parse(value)
  } catch {
    return []
  }
}

function normalizeProject(value: unknown): ProjectDraft | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Record<string, unknown>
  const id = typeof raw.id === 'string' ? raw.id : crypto.randomUUID()
  const savedAt = typeof raw.saved_at === 'string' ? raw.saved_at : now()
  return {
    ...createProject(typeof raw.name === 'string' ? raw.name : '未命名小说'),
    id,
    name: typeof raw.name === 'string' && raw.name.trim() ? raw.name : '未命名小说',
    text: typeof raw.text === 'string' ? raw.text : '',
    createdAt: typeof raw.createdAt === 'string' ? raw.createdAt : savedAt,
    updatedAt: typeof raw.updatedAt === 'string' ? raw.updatedAt : savedAt,
    engine: typeof raw.engine === 'string' ? raw.engine : 'qwen3_custom',
    outputFormat: raw.output_format === 'wav' || raw.outputFormat === 'wav' ? 'wav' : 'mp3',
    outputBitrate: Number(raw.output_bitrate ?? raw.outputBitrate ?? 128),
    streamingMode: typeof raw.streamingMode === 'boolean' ? raw.streamingMode : true,
    splitByChapter: raw.split_chapters !== false && raw.splitByChapter !== false,
    fullStory: Boolean(raw.full_story ?? raw.fullStory),
    voiceAssignments: (raw.assignments ?? raw.voiceAssignments ?? {}) as Record<string, string>,
  }
}

export function loadProjects(): ProjectDraft[] {
  const current = safeParse(localStorage.getItem(PROJECT_KEY))
  const source = Array.isArray(current) && current.length ? current : safeParse(localStorage.getItem(LEGACY_PROJECT_KEY))
  const projects = Array.isArray(source) ? source.map(normalizeProject).filter((project): project is ProjectDraft => Boolean(project)) : []
  if (!localStorage.getItem(PROJECT_KEY) && projects.length) persistProjects(projects)
  return projects.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
}

export function persistProjects(projects: ProjectDraft[]): void {
  localStorage.setItem(PROJECT_KEY, JSON.stringify(projects))
}

export function readActiveProjectId(): string | null {
  return localStorage.getItem(ACTIVE_KEY)
}

export function writeActiveProjectId(projectId: string): void {
  localStorage.setItem(ACTIVE_KEY, projectId)
}
