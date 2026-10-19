import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Command } from 'cmdk'
import { AnimatePresence, motion } from 'motion/react'
import {
  ArrowLeft, AudioLines, BookCopy, BookOpenText, BookSearch, Bot, Check, ChevronRight, CircleHelp, Clock3,
  Download, FileText, FolderKanban, Gauge, HeartPulse, Library, ListTodo, LoaderCircle,
  Mic2, Moon, MoreHorizontal, PanelLeftClose, Pause, Play, Plus, Search, Settings2,
  SkipBack, SkipForward, Sparkles, Square, Sun, Upload, Volume2, WandSparkles, X,
} from 'lucide-react'
import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { createBrowserRouter, NavLink, Navigate, Outlet, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'
import { api } from './api'
import { DiscoverPage } from './DiscoverPage'
import { createProject, loadProjects, persistProjects, readActiveProjectId, writeActiveProjectId } from './storage'
import type { AppSettings, AppStage, GenerationJob, ImportedPublicBook, LibraryChapter, LibraryItem, ProjectDraft, VoicePreset } from './types'

const SiteAssistant = lazy(() => import('./SiteAssistant'))

const stages: Array<{ id: AppStage; label: string; description: string }> = [
  { id: 'text', label: '正文与章节', description: '导入、编辑并检查小说正文' },
  { id: 'casting', label: '角色与配音', description: '确认角色，安排每个人的声音' },
  { id: 'generate', label: '生成与试听', description: '选择引擎并开始制作有声书' },
]

type ProjectContextValue = {
  projects: ProjectDraft[]
  activeProjectId: string | null
  create: () => ProjectDraft
  update: (project: ProjectDraft) => void
  remove: (projectId: string) => void
  activate: (projectId: string) => void
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

function ProjectProvider({ children }: { children: React.ReactNode }) {
  const [projects, setProjects] = useState<ProjectDraft[]>(() => loadProjects())
  const [activeProjectId, setActiveProjectId] = useState<string | null>(() => readActiveProjectId())

  useEffect(() => persistProjects(projects), [projects])
  useEffect(() => {
    if (activeProjectId) writeActiveProjectId(activeProjectId)
  }, [activeProjectId])

  const create = useCallback(() => {
    const project = createProject()
    setProjects((items) => [project, ...items])
    setActiveProjectId(project.id)
    return project
  }, [])
  const update = useCallback((project: ProjectDraft) => {
    const next = { ...project, updatedAt: new Date().toISOString() }
    setProjects((items) => [next, ...items.filter((item) => item.id !== next.id)])
  }, [])
  const remove = useCallback((projectId: string) => {
    setProjects((items) => items.filter((item) => item.id !== projectId))
    setActiveProjectId((current) => current === projectId ? null : current)
  }, [])
  const activate = useCallback((projectId: string) => setActiveProjectId(projectId), [])

  return <ProjectContext.Provider value={{ projects, activeProjectId, create, update, remove, activate }}>{children}</ProjectContext.Provider>
}

function useProjects() {
  const context = useContext(ProjectContext)
  if (!context) throw new Error('Project context is unavailable')
  return context
}

function formatDate(value?: string) {
  if (!value) return '刚刚'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function formatBytes(value?: number) {
  if (!value) return '—'
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / 1024 / 1024).toFixed(value > 1024 * 1024 * 100 ? 0 : 1)} MB`
}

function titleFromPreview(preview?: string) {
  return preview?.match(/《([^》]+)》/)?.[1]?.trim()
}

function libraryTitle(item: LibraryItem, job?: GenerationJob) {
  return item.collection_title || item.audiobook_title || item.title || titleFromPreview(job?.text_preview) || '未命名有声书'
}

function groupLibraryItems(items: LibraryItem[], jobs: GenerationJob[] = []) {
  const grouped = new Map<string, LibraryItem>()
  const score = (item: LibraryItem) => {
    const job = jobs.find((entry) => entry.job_id === item.job_id)
    const active = ['processing', 'queued', 'pausing'].includes(job?.status ?? '') ? 1_000_000 : 0
    return active + (item.chapters?.filter((chapter) => !chapter.missing_file).length ?? 0)
  }
  for (const item of items) {
    const job = jobs.find((entry) => entry.job_id === item.job_id)
    const title = libraryTitle(item, job)
    const key = title === '未命名有声书' ? item.job_id : title.replace(/\s+/g, '').toLocaleLowerCase('zh-CN')
    const current = grouped.get(key)
    if (!current || score(item) > score(current)) grouped.set(key, item)
  }
  return [...grouped.values()]
}

function chapterAudioUrl(chapter?: LibraryChapter) {
  return chapter?.file_url || chapter?.output_file || ''
}

function formatDuration(value?: number) {
  if (!value || !Number.isFinite(value)) return '—'
  const total = Math.max(0, Math.round(value))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}` : `${minutes}:${String(seconds).padStart(2, '0')}`
}

function jobProgress(job: GenerationJob) {
  if (job.total_chunks && job.total_chunks > 0) return Math.min(100, Math.round(((job.processed_chunks ?? 0) / job.total_chunks) * 100))
  return Math.max(0, Math.min(100, Math.round(job.progress || 0)))
}

function currentChapterProgress(job: GenerationJob) {
  const value = job.streaming_summary?.active_chapter_progress
  return typeof value === 'number' ? Math.max(0, Math.min(100, Math.round(value))) : jobProgress(job)
}

function statusLabel(status: string) {
  const labels: Record<string, string> = { processing: '制作中', queued: '等待制作', paused: '已暂停', pausing: '正在暂停', completed: '已完成', failed: '失败', interrupted: '已中断' }
  return labels[status] ?? status
}

function castPhaseLabel(job: GenerationJob) {
  if (job.streaming_phase === 'cast_review') return '人物声线需要修正'
  if (job.streaming_phase === 'cast_ready') return `人物与场景已锁定 · 待重做 ${job.recast?.pending_segments?.toLocaleString() ?? 0} 段`
  if (job.streaming_phase === 'analyzing') return '正在分析全书人物'
  if (job.streaming_phase === 'synthesizing' && job.recast) return `正在修复 ${job.active_chapter_title || '当前章节'}`
  if (job.recast) return `V3 修复 · 已复用 ${job.recast.reused_segments?.toLocaleString() ?? 0} 段`
  return null
}

const VOICE_AUDITION_TEXT_KEY = 'shengyue-voice-audition-text'
const DEFAULT_AUDITION_TEXT = '雨停以后，长街上的灯一盏接一盏亮了起来。'

function useVoiceAuditionText() {
  const [text, setText] = useState(() => localStorage.getItem(VOICE_AUDITION_TEXT_KEY) || DEFAULT_AUDITION_TEXT)
  useEffect(() => { localStorage.setItem(VOICE_AUDITION_TEXT_KEY, text) }, [text])
  return [text, setText] as const
}

type VoiceAuditionController = {
  pendingId: string | null
  playingId: string | null
  play: (preset: VoicePreset, text: string) => Promise<void>
  stop: () => void
}

function useVoiceAudition(): VoiceAuditionController {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)

  const stop = useCallback(() => {
    const audio = audioRef.current
    if (audio) {
      audio.pause()
      audio.currentTime = 0
      audioRef.current = null
    }
    setPlayingId(null)
  }, [])

  const play = useCallback(async (preset: VoicePreset, text: string) => {
    const presetId = preset.id ?? preset.code
    if (!presetId || !text.trim()) return
    stop()
    setPendingId(presetId)
    try {
      const result = await api.auditionVoicePreset({ text: text.trim(), presetId, actingState: preset.default_state })
      if (!result.audio_base64) throw new Error('没有返回可播放的试音音频。')
      const audio = new Audio(`data:${result.mime_type || 'audio/wav'};base64,${result.audio_base64}`)
      audioRef.current = audio
      audio.addEventListener('ended', () => { if (audioRef.current === audio) { audioRef.current = null; setPlayingId(null) } })
      audio.addEventListener('error', () => { if (audioRef.current === audio) { audioRef.current = null; setPlayingId(null); toast.error('试音音频无法播放，请再试一次。') } })
      await audio.play()
      setPlayingId(presetId)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '试音失败，请稍后再试。')
    } finally {
      setPendingId(null)
    }
  }, [stop])

  useEffect(() => () => stop(), [stop])
  return { pendingId, playingId, play, stop }
}

function VoiceAuditionText({ text, onChange }: { text: string; onChange: (text: string) => void }) {
  return <section className="voice-audition"><div className="voice-audition-heading"><Volume2 size={19} /><div><h2>试音台词</h2><p>输入一句你想听的台词，再点击下方任意声线试听。</p></div></div><label className="field"><span>本次试音文本</span><textarea value={text} onChange={(event) => onChange(event.target.value)} maxLength={300} rows={3} placeholder="例如：别急，我已经想到办法了。" /><small>{text.length} / 300 字 · 文本会在声线选择和总览之间保留。</small></label></section>
}

function VoiceAuditionButton({ preset, text, audition }: { preset?: VoicePreset; text: string; audition: VoiceAuditionController }) {
  const presetId = preset?.id ?? preset?.code
  const isPending = Boolean(presetId && audition.pendingId === presetId)
  const isPlaying = Boolean(presetId && audition.playingId === presetId)
  const label = preset ? `试听${preset.name}` : '请先选择声线'
  return <button className="button audition-button" type="button" disabled={!presetId || !text.trim() || Boolean(audition.pendingId)} aria-label={label} onClick={() => { if (!preset) return; if (isPlaying) audition.stop(); else void audition.play(preset, text) }}>{isPending ? <LoaderCircle className="spin" size={16} /> : isPlaying ? <Square size={15} /> : <Play size={16} />}{isPending ? '正在合成…' : isPlaying ? '停止试听' : '试听'}</button>
}

function findVoicePreset(presets: VoicePreset[], selection?: string) {
  return presets.find((preset) => [preset.id, preset.code, preset.name].includes(selection))
}

function EmptyState({ icon: Icon, title, description, action }: { icon: typeof Sparkles; title: string; description: string; action?: React.ReactNode }) {
  return <div className="empty-state"><span className="empty-state-icon"><Icon size={22} /></span><h3>{title}</h3><p>{description}</p>{action}</div>
}

function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: React.ReactNode }) {
  return <header className="page-header"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1><p>{description}</p></div>{action && <div className="page-header-action">{action}</div>}</header>
}

const navigation = [
  { to: '/', label: '总览', icon: Sparkles },
  { to: '/discover', label: '找书', icon: BookSearch },
  { to: '/projects', label: '作品', icon: FolderKanban },
  { to: '/tasks', label: '制作任务', icon: ListTodo },
  { to: '/library', label: '我的有声书', icon: Library },
  { to: '/voices', label: '声线工作室', icon: Mic2 },
]

const mobileNavigation = navigation.filter((item) => item.to !== '/voices')

function AppShell() {
  const [commandOpen, setCommandOpen] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [dark, setDark] = useState(() => localStorage.getItem('reader-theme') === 'dark')
  const navigate = useNavigate()
  const { activeProjectId, projects, create, update } = useProjects()
  const activeProject = projects.find((project) => project.id === activeProjectId)
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 60_000 })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('reader-theme', dark ? 'dark' : 'light')
  }, [dark])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setCommandOpen(true) }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const navigateTo = (to: string) => { setCommandOpen(false); navigate(to) }
  const startPublicBook = useCallback(async (book: ImportedPublicBook) => {
    const draft = create()
    const project: ProjectDraft = { ...draft, name: book.title, text: book.text, streamingMode: true, splitByChapter: true }
    update(project)
    const generated = await api.generate({
      text: book.text,
      tts_engine: project.engine,
      output_format: project.outputFormat,
      output_bitrate_kbps: project.outputBitrate,
      split_by_chapter: true,
      generate_full_story: false,
      voice_assignments: {},
      streaming_mode: true,
      review_mode: false,
      buffer_chapters: 1,
      batch_strategy: 'adaptive_window',
      batch_window_segments: 12,
      max_batch_size: 4,
    })
    localStorage.setItem('reader-streaming-job', generated.job_id)
    try { await api.updateLibraryTitle(generated.job_id, book.title) } catch { /* The project title still remains local. */ }
    return { projectId: project.id, jobId: generated.job_id }
  }, [create, update])
  const engineName = typeof health?.tts_engine === 'string' ? health.tts_engine : '本地引擎'
  return <div className="app-frame">
    <aside className="sidebar">
      <NavLink to="/" className="brand" aria-label="声阅总览"><span className="brand-mark">声</span><span><strong>声阅</strong><small>AI 小说有声书</small></span></NavLink>
      <nav className="nav-list" aria-label="主导航">{navigation.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} className="nav-item"><Icon size={19} /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom">
        <NavLink to="/settings" className="nav-item"><Settings2 size={19} /><span>设置</span></NavLink>
        <NavLink to="/help" className="nav-item"><CircleHelp size={19} /><span>使用帮助</span></NavLink>
        <a className="legacy-link" href="/legacy"><PanelLeftClose size={16} />旧版回退</a>
      </div>
    </aside>
    <div className="app-body">
      <header className="topbar">
        <div className="topbar-context"><span className="health-dot" aria-hidden="true" /><span>{activeProjectId ? '正在编辑作品' : '尚未选择作品'}</span><span className="topbar-separator">/</span><span>{engineName}</span></div>
        <div className="topbar-actions">
          <button className="command-trigger" onClick={() => setCommandOpen(true)}><Search size={16} /><span>查找功能</span><kbd>⌘K</kbd></button>
          <NavLink to="/help" className="icon-button mobile-help" aria-label="打开使用帮助"><CircleHelp size={18} /></NavLink>
          <button className="icon-button" onClick={() => setDark((value) => !value)} aria-label={dark ? '切换为日间模式' : '切换为夜间模式'}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button>
        </div>
      </header>
      <motion.main className="page-content" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24 }}><Outlet /></motion.main>
    </div>
    <nav className="mobile-nav" aria-label="移动端主导航">{mobileNavigation.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} className="mobile-nav-item"><Icon size={18} /><span>{label === '我的有声书' ? '书库' : label}</span></NavLink>)}</nav>
    <Command.Dialog label="查找声阅功能" open={commandOpen} onOpenChange={setCommandOpen}>
      <div className="command-modal"><div className="command-title"><Sparkles size={18} />快速打开</div><Command.Input placeholder="搜索作品、任务或功能…" /><Command.List>{navigation.map(({ to, label, icon: Icon }) => <Command.Item key={to} value={label} onSelect={() => navigateTo(to)}><Icon size={17} />{label}</Command.Item>)}<Command.Item value="问声阅 AI 助手" onSelect={() => { setCommandOpen(false); setAssistantOpen(true) }}><Bot size={17} />问声阅助手</Command.Item><Command.Item value="设置" onSelect={() => navigateTo('/settings')}><Settings2 size={17} />设置</Command.Item><Command.Item value="使用帮助" onSelect={() => navigateTo('/help')}><CircleHelp size={17} />使用帮助</Command.Item>{activeProjectId && <Command.Item value="继续编辑" onSelect={() => navigateTo(`/projects/${activeProjectId}/text`)}><BookOpenText size={17} />继续编辑当前作品</Command.Item>}</Command.List></div>
    </Command.Dialog>
    <Suspense fallback={null}><SiteAssistant open={assistantOpen} onOpenChange={setAssistantOpen} activeProject={activeProject ? { name: activeProject.name, textLength: activeProject.text.length } : undefined} onPublicBookReady={startPublicBook} /></Suspense>
  </div>
}

function DashboardPage() {
  const navigate = useNavigate()
  const { projects, activeProjectId, create, activate } = useProjects()
  const { data: queue } = useQuery({ queryKey: ['queue'], queryFn: api.queue, refetchInterval: (query) => query.state.data?.jobs.some((job) => ['processing', 'queued', 'pausing'].includes(job.status)) ? 6000 : false })
  const { data: library = [] } = useQuery({ queryKey: ['library'], queryFn: api.library })
  const activeProject = projects.find((project) => project.id === activeProjectId) ?? projects[0]
  const activeJob = queue?.jobs.find((job) => job.status === 'processing' || job.status === 'queued')
  const newProject = () => { const project = create(); navigate(`/projects/${project.id}/text`) }
  const continueProject = () => {
    if (!activeProject) return newProject()
    activate(activeProject.id); navigate(`/projects/${activeProject.id}/text`)
  }

  return <><PageHeader eyebrow="声阅工作台" title="今天想把哪段故事变成声音？" description="从正文、角色到第一章试听，每一步都有明确出口。" action={<button className="button primary" onClick={newProject}><Plus size={17} />新建作品</button>} />
    <section className="dashboard-grid">
      <article className="feature-card current-project"><div className="card-kicker"><BookOpenText size={16} />当前编辑</div>{activeProject ? <><h2>{activeProject.name}</h2><p>{activeProject.text ? `${activeProject.text.length.toLocaleString()} 字 · ${activeProject.analysis?.speakers.length ?? 0} 位已识别角色` : '还没有导入正文，从第一步开始即可。'}</p><button className="button primary" onClick={continueProject}>{activeProject.text ? '继续创作' : '导入小说'}<ChevronRight size={17} /></button></> : <><h2>开始第一本有声书</h2><p>导入 TXT、PDF、Word、EPUB 或 Markdown，声阅会帮助你拆章节、识别角色并安排配音。</p><button className="button primary" onClick={newProject}>导入小说<Upload size={17} /></button></>}</article>
      <article className="feature-card task-spotlight"><div className="card-kicker"><Gauge size={16} />后台制作</div>{activeJob ? <><h2>{statusLabel(activeJob.status)}</h2><div className="metric-row"><strong>{jobProgress(activeJob)}%</strong><span>{activeJob.processed_chunks?.toLocaleString() ?? 0} / {activeJob.total_chunks?.toLocaleString() ?? '—'} 段</span></div><div className="progress-track"><span style={{ width: `${jobProgress(activeJob)}%` }} /></div><p>{activeJob.active_chapter_title || '正在准备下一段语音，不会影响你的继续编辑。'}</p><button className="button secondary" onClick={() => navigate('/tasks')}>查看制作进度<ChevronRight size={17} /></button></> : <><h2>没有正在制作的任务</h2><p>完成角色配音后，点击“生成并试听”即可在后台开始制作。</p><button className="button secondary" onClick={continueProject}>前往创作<ChevronRight size={17} /></button></>}</article>
    </section>
    <section className="section-block"><div className="section-heading"><div><p className="eyebrow">快速指引</p><h2>三步完成第一本有声书</h2></div><NavLink to="/help" className="text-link">查看完整帮助<ChevronRight size={16} /></NavLink></div><div className="guide-grid">{stages.map((stage, index) => <article className="guide-card" key={stage.id}><span>{index + 1}</span><div><h3>{stage.label}</h3><p>{stage.description}</p></div></article>)}</div></section>
    <section className="section-block"><div className="section-heading"><div><p className="eyebrow">最近可听</p><h2>我的有声书</h2></div><NavLink to="/library" className="text-link">打开书库<ChevronRight size={16} /></NavLink></div>{library.length ? <div className="recent-list">{groupLibraryItems(library, queue?.jobs).slice(0, 3).map((item) => { const job = queue?.jobs.find((entry) => entry.job_id === item.job_id); const title = libraryTitle(item, job); const ready = item.chapters?.length ?? 0; const total = job?.chapter_count ?? item.chapter_count; return <article className="recent-item" key={item.job_id}><span className="media-icon"><AudioLines size={18} /></span><div><h3>{title}</h3><p>{job && ['processing', 'queued', 'pausing'].includes(job.status) ? `制作中 · 已可听 ${ready}${total ? ` / ${total}` : ''} 章` : `${ready || 1} 章可听 · ${formatDate(item.created_at)}`}</p></div><NavLink className="icon-button" to={`/library/${item.job_id}`} aria-label={`打开${title}`}><Play size={17} /></NavLink></article> })}</div> : <EmptyState icon={Library} title="书库还没有作品" description="第一章生成完成后，整本书就会自动出现在这里。" action={<button className="button secondary" onClick={continueProject}>开始创作</button>} />}</section>
  </>
}

function ProjectsPage() {
  const navigate = useNavigate()
  const { projects, activeProjectId, create, activate, remove } = useProjects()
  const newProject = () => { const project = create(); navigate(`/projects/${project.id}/text`) }
  return <><PageHeader eyebrow="作品" title="你的小说工作区" description="每部作品独立保存正文、角色配置和生成偏好。" action={<button className="button primary" onClick={newProject}><Plus size={17} />新建作品</button>} />
    {projects.length ? <div className="project-grid">{projects.map((project) => <article className={`project-card ${project.id === activeProjectId ? 'is-active' : ''}`} key={project.id}><div className="project-card-top"><span className="media-icon"><BookCopy size={18} /></span><button className="icon-button" aria-label={`删除${project.name}`} onClick={() => { if (window.confirm(`删除本地草稿“${project.name}”？已生成的有声书不会删除。`)) remove(project.id) }}><X size={16} /></button></div><h2>{project.name}</h2><p>{project.text ? `${project.text.length.toLocaleString()} 字 · ${project.analysis?.speakers.length ?? 0} 位角色` : '空白草稿'}</p><span className="project-time">上次编辑：{formatDate(project.updatedAt)}</span><button className="button secondary wide" onClick={() => { activate(project.id); navigate(`/projects/${project.id}/text`) }}>打开工作区<ChevronRight size={17} /></button></article>)}</div> : <EmptyState icon={FolderKanban} title="还没有作品" description="先导入一部小说；之后可以随时回到这里继续编辑。" action={<button className="button primary" onClick={newProject}>新建作品</button>} />}
  </>
}

function WorkspacePage() {
  const { projectId, stage = 'text' } = useParams()
  const navigate = useNavigate()
  const { projects, update, activate } = useProjects()
  const project = projects.find((item) => item.id === projectId)
  const activeStage = stages.some((item) => item.id === stage) ? stage as AppStage : 'text'
  useEffect(() => { if (project) activate(project.id) }, [activate, project])
  if (!project) return <Navigate to="/projects" replace />
  const stepIndex = stages.findIndex((item) => item.id === activeStage)
  const jump = (target: AppStage) => navigate(`/projects/${project.id}/${target}`)
  return <><div className="workspace-heading"><div><NavLink to="/projects" className="breadcrumb"><FolderKanban size={15} />作品<ChevronRight size={14} />{project.name}</NavLink><input className="project-title-input" aria-label="作品名称" value={project.name} onChange={(event) => update({ ...project, name: event.target.value })} /></div><span className="save-state"><Check size={15} />本地草稿已保存</span></div>
    <nav className="stage-nav" aria-label="创作流程">{stages.map((item, index) => <button key={item.id} className={item.id === activeStage ? 'is-active' : index < stepIndex ? 'is-complete' : ''} onClick={() => jump(item.id)}><span>{index < stepIndex ? <Check size={15} /> : index + 1}</span><div><strong>{item.label}</strong><small>{item.description}</small></div></button>)}</nav>
    <AnimatePresence mode="wait">{activeStage === 'text' && <TextStage key="text" project={project} update={update} next={() => jump('casting')} />}{activeStage === 'casting' && <CastingStage key="casting" project={project} update={update} previous={() => jump('text')} next={() => jump('generate')} />}{activeStage === 'generate' && <GenerateStage key="generate" project={project} update={update} previous={() => jump('casting')} />}</AnimatePresence>
  </>
}

function TextStage({ project, update, next }: { project: ProjectDraft; update: (project: ProjectDraft) => void; next: () => void }) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [text, setText] = useState(project.text)
  const extract = useMutation({ mutationFn: api.extractDocument, onSuccess: (data) => { setText(data.text); update({ ...project, text: data.text }); toast.success(`已导入 ${data.filename}`) }, onError: (error) => toast.error(error.message) })
  const analyze = useMutation({ mutationFn: () => api.analyze(text, project.engine), onSuccess: (data) => { update({ ...project, text, analysis: data.statistics }); toast.success('角色与章节分析完成，可以进入下一步。') }, onError: (error) => toast.error(error.message) })
  const save = () => { update({ ...project, text }); toast.success('正文已保存') }
  const continueNext = () => { update({ ...project, text }); next() }
  return <motion.section className="workspace-panel text-stage" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="panel-title"><div><p className="eyebrow">第一步</p><h1>导入并整理正文</h1><p>先把小说放进来。章节、角色和配音都可以下一步再处理。</p></div><div className="panel-actions"><button className="button ghost" onClick={() => fileInput.current?.click()} disabled={extract.isPending}><Upload size={17} />{extract.isPending ? '正在读取…' : '导入文件'}</button><button className="button secondary" onClick={save}>保存草稿</button></div></div><input ref={fileInput} className="sr-only" type="file" accept=".txt,.pdf,.doc,.docx,.epub,.md" onChange={(event) => { const file = event.target.files?.[0]; if (file) extract.mutate(file); event.target.value = '' }} />
    <div className="editor-shell"><div className="editor-toolbar"><span><FileText size={16} />小说正文</span><span>{text.length.toLocaleString()} 字</span></div><textarea value={text} onChange={(event) => setText(event.target.value)} onBlur={save} placeholder="粘贴小说正文，或导入 TXT、PDF、Word、EPUB、Markdown 文件。" /></div>
    <div className="analysis-strip"><div><Bot size={19} /><span><strong>{project.analysis ? `已识别 ${project.analysis.speakers.length} 位角色` : '准备好后进行智能分析'}</strong><small>{project.analysis ? `${project.analysis.total_chunks ?? '—'} 段 · 预计 ${project.analysis.estimated_duration ?? '—'}` : '分析不会开始生成音频。'}</small></span></div><button className="button secondary" onClick={() => analyze.mutate()} disabled={!text.trim() || analyze.isPending}>{analyze.isPending ? <LoaderCircle className="spin" size={17} /> : <WandSparkles size={17} />}{project.analysis ? '重新分析' : '智能分角色'}</button></div>
    <div className="workspace-footer"><span>下一步：确认角色并选择声线</span><button className="button primary" onClick={continueNext} disabled={!text.trim()}>进入角色与配音<ChevronRight size={17} /></button></div></motion.section>
}

function CastingStage({ project, update, previous, next }: { project: ProjectDraft; update: (project: ProjectDraft) => void; previous: () => void; next: () => void }) {
  const { data: presets = [], isLoading } = useQuery({ queryKey: ['voice-presets'], queryFn: api.voices })
  const [auditionText, setAuditionText] = useVoiceAuditionText()
  const audition = useVoiceAudition()
  const speakers = project.analysis?.speakers ?? []
  const updateAssignment = (speaker: string, voice: string) => update({ ...project, voiceAssignments: { ...project.voiceAssignments, [speaker]: voice } })
  const autoAssign = () => { const nextAssignments = Object.fromEntries(speakers.map((speaker, index) => [speaker.name, presets[index % Math.max(presets.length, 1)]?.id ?? presets[index % Math.max(presets.length, 1)]?.name ?? ''])); update({ ...project, voiceAssignments: nextAssignments }); toast.success('已填入推荐声线，请逐个确认。') }
  return <motion.section className="workspace-panel" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="panel-title"><div><p className="eyebrow">第二步</p><h1>角色与配音</h1><p>先确认会说话的人物，再为每个人挑选合适的声音。没有把握的角色可以保持待确认。</p></div><div className="panel-actions"><button className="button ghost" onClick={previous}>返回正文</button><button className="button secondary" onClick={autoAssign} disabled={!speakers.length || isLoading}><Sparkles size={17} />智能配音</button></div></div>
    <VoiceAuditionText text={auditionText} onChange={setAuditionText} />
    {speakers.length ? <div className="casting-list">{speakers.map((speaker) => { const selectedPreset = findVoicePreset(presets, project.voiceAssignments[speaker.name]); return <article className="speaker-card" key={speaker.name}><div className="speaker-avatar">{speaker.name.slice(0, 1)}</div><div className="speaker-meta"><h2>{speaker.name}</h2><p>{speaker.gender || '待确认'} · 提及 {speaker.mentions ?? 0} 次 · 置信度 {speaker.confidence ? `${Math.round(speaker.confidence * 100)}%` : '—'}</p></div><div className="voice-select"><label><span className="sr-only">{speaker.name}的声线</span><select value={project.voiceAssignments[speaker.name] ?? ''} onChange={(event) => updateAssignment(speaker.name, event.target.value)}><option value="">稍后决定</option>{presets.map((preset) => <option key={preset.id ?? preset.code ?? preset.name} value={preset.id ?? preset.code ?? preset.name}>{preset.name}{preset.description ? ` · ${preset.description}` : ''}</option>)}</select></label><VoiceAuditionButton preset={selectedPreset} text={auditionText} audition={audition} /></div></article>})}</div> : <EmptyState icon={Bot} title="还没有可确认的角色" description="回到正文页点击“智能分角色”，或直接继续生成，系统会使用默认旁白。" action={<button className="button secondary" onClick={previous}>回到正文</button>} />}
    <div className="workspace-footer"><span>{speakers.length ? `${Object.values(project.voiceAssignments).filter(Boolean).length} / ${speakers.length} 位角色已选择声线` : '你可以随时跳过这一步。'}</span><button className="button primary" onClick={next}>进入生成与试听<ChevronRight size={17} /></button></div></motion.section>
}

function GenerateStage({ project, update, previous }: { project: ProjectDraft; update: (project: ProjectDraft) => void; previous: () => void }) {
  const navigate = useNavigate()
  const generate = useMutation({ mutationFn: () => api.generate({ text: project.text, tts_engine: project.engine, output_format: project.outputFormat, output_bitrate_kbps: project.outputBitrate, split_by_chapter: project.splitByChapter, generate_full_story: project.fullStory, voice_assignments: Object.fromEntries(Object.entries(project.voiceAssignments).map(([speaker, voice]) => [speaker, { voice }])), streaming_mode: project.streamingMode, review_mode: !project.streamingMode, buffer_chapters: 1, batch_strategy: 'adaptive_window', batch_window_segments: 12, max_batch_size: 4 }), onSuccess: (data) => { if (project.streamingMode) localStorage.setItem('reader-streaming-job', data.job_id); toast.success('任务已创建，正在准备第一章。'); navigate('/tasks') }, onError: (error) => toast.error(error.message) })
  const set = <Key extends keyof ProjectDraft>(key: Key, value: ProjectDraft[Key]) => update({ ...project, [key]: value })
  return <motion.section className="workspace-panel" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="panel-title"><div><p className="eyebrow">第三步</p><h1>生成与试听</h1><p>确认这次任务的引擎与输出格式。任务会在后台继续，不会丢失正在编辑的作品。</p></div><button className="button ghost" onClick={previous}>返回角色与配音</button></div>
    <div className="settings-grid"><label className="field"><span>朗读引擎</span><select value={project.engine} onChange={(event) => set('engine', event.target.value)}><option value="qwen3_custom">Qwen3-TTS · 中文角色声线</option><option value="index_tts">IndexTTS2 · 中文情绪阅读</option><option value="kokoro">Kokoro · 本地</option></select><small>常用引擎在这里；更多引擎参数在设置页。</small></label><label className="field"><span>音频格式</span><select value={project.outputFormat} onChange={(event) => set('outputFormat', event.target.value as 'mp3' | 'wav')}><option value="mp3">MP3</option><option value="wav">WAV</option></select><small>MP3 适合日常播放和下载。</small></label><label className="field"><span>MP3 音质</span><select value={project.outputBitrate} onChange={(event) => set('outputBitrate', Number(event.target.value))} disabled={project.outputFormat !== 'mp3'}><option value={96}>96 kbps</option><option value={128}>128 kbps</option><option value={192}>192 kbps</option></select><small>更高码率会增加体积。</small></label></div>
    <div className="toggle-list"><label><input type="checkbox" checked={project.streamingMode} onChange={(event) => set('streamingMode', event.target.checked)} /><span><strong>边生成边播放</strong><small>第一章准备好后即可开始听，后续章节在后台继续制作。</small></span></label><label><input type="checkbox" checked={project.splitByChapter} onChange={(event) => set('splitByChapter', event.target.checked)} /><span><strong>按章节归档</strong><small>长篇小说会保留每章独立音频，便于继续收听。</small></span></label><label><input type="checkbox" checked={project.fullStory} onChange={(event) => set('fullStory', event.target.checked)} /><span><strong>同时合并整本</strong><small>完成后额外导出整本音频，耗时更长。</small></span></label></div>
    <div className="generation-summary"><div><span>本次作品</span><strong>{project.name}</strong></div><div><span>角色配音</span><strong>{Object.values(project.voiceAssignments).filter(Boolean).length} 位已分配</strong></div><div><span>处理方式</span><strong>{project.streamingMode ? '流式制作' : '任务完成后试听'}</strong></div></div><div className="workspace-footer"><span>提交后可在“制作任务”查看进度、暂停或继续。</span><button className="button primary" onClick={() => generate.mutate()} disabled={generate.isPending || !project.text.trim()}>{generate.isPending ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}{generate.isPending ? '正在创建任务…' : '生成并试听'}</button></div></motion.section>
}

function TaskPage() {
  const [filter, setFilter] = useState<'active' | 'paused' | 'done' | 'all'>('active')
  const client = useQueryClient()
  const { data: queue, isLoading, error } = useQuery({ queryKey: ['queue'], queryFn: api.queue, refetchInterval: (query) => query.state.data?.jobs.some((job) => ['processing', 'queued', 'pausing'].includes(job.status)) ? 6000 : false })
  const action = useMutation({ mutationFn: ({ jobId, type }: { jobId: string; type: 'pause' | 'resume' | 'cancel' }) => api.jobAction(jobId, type), onSuccess: () => { client.invalidateQueries({ queryKey: ['queue'] }); toast.success('任务状态已更新') }, onError: (mutationError) => toast.error(mutationError.message) })
  const recast = useMutation({ mutationFn: api.recast, onSuccess: (data) => { client.invalidateQueries({ queryKey: ['queue'] }); toast.success(`人物与场景已重新分析，复用 ${data.reused_segments.toLocaleString()} 段`) }, onError: (mutationError) => toast.error(mutationError.message) })
  const allJobs = queue?.jobs ?? []
  const jobs = allJobs.filter((job) => filter === 'all' || (filter === 'active' && ['processing', 'queued', 'pausing'].includes(job.status)) || (filter === 'paused' && ['paused', 'interrupted', 'failed'].includes(job.status)) || (filter === 'done' && job.status === 'completed'))
  const active = allJobs.find((job) => ['processing', 'queued', 'pausing'].includes(job.status))
  const activeChapterPercent = active ? currentChapterProgress(active) : 0
  const activePlayable = active?.streaming_summary?.playable_chapters ?? active?.streaming_summary?.ready_chapters ?? 0
  return <><PageHeader eyebrow="制作任务" title="有声书正在怎样制作？" description="任务与当前编辑作品分开显示；关闭页面不会停止后台制作。" action={<button className="button secondary" onClick={() => client.invalidateQueries({ queryKey: ['queue'] })}><Clock3 size={17} />刷新状态</button>} />
    {active && <section className="active-job"><div><p className="eyebrow">正在制作</p><h2>{active.active_chapter_title || '正在合成语音'}</h2><p>当前章 {activeChapterPercent}% · {activePlayable} 章可听 · 全书已核验 {active.processed_chunks?.toLocaleString() ?? 0} / {active.total_chunks?.toLocaleString() ?? '—'} 段</p></div><div className="active-job-meter"><strong>{activeChapterPercent}%</strong><div className="progress-track"><span style={{ width: `${activeChapterPercent}%` }} /></div><small>{active.eta_seconds ? `预计还需约 ${Math.ceil(active.eta_seconds / 60)} 分钟` : '完成当前章后会自动继续下一章'}</small></div></section>}
    <div className="filter-tabs" role="tablist">{([['active', '进行中'], ['paused', '已暂停 / 失败'], ['done', '已完成'], ['all', '全部']] as const).map(([value, label]) => <button role="tab" aria-selected={filter === value} className={filter === value ? 'is-active' : ''} key={value} onClick={() => setFilter(value)}>{label}</button>)}</div>
    {isLoading ? <div className="loading-block"><LoaderCircle className="spin" />正在读取任务…</div> : error ? <EmptyState icon={HeartPulse} title="任务状态暂时不可用" description={error.message} /> : <VirtualJobList jobs={jobs} onAction={(jobId, type) => action.mutate({ jobId, type })} onRecast={(jobId) => recast.mutate(jobId)} recasting={recast.isPending} />}
  </>
}

function VirtualJobList({ jobs, onAction, onRecast, recasting }: { jobs: GenerationJob[]; onAction: (jobId: string, type: 'pause' | 'resume' | 'cancel') => void; onRecast: (jobId: string) => void; recasting: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({ count: jobs.length, getScrollElement: () => ref.current, estimateSize: () => 184, overscan: 5 })
  if (!jobs.length) return <EmptyState icon={ListTodo} title="这里没有对应任务" description="新的生成任务会自动出现在“进行中”，暂停和失败任务可以随时继续处理。" />
  return <div ref={ref} className="virtual-list"><div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>{virtualizer.getVirtualItems().map((row) => {
    const job = jobs[row.index]
    const castPhase = castPhaseLabel(job)
    const paused = ['paused', 'failed', 'interrupted'].includes(job.status)
    const auditBlocksResume = Boolean(job.cast_audit && !job.cast_audit.ready)
    const chapterPercent = currentChapterProgress(job)
    const playable = job.streaming_summary?.playable_chapters ?? job.streaming_summary?.ready_chapters ?? 0
    return <div key={job.job_id} className="virtual-row" style={{ transform: `translateY(${row.start}px)` }}><article className="job-card"><div className="job-card-main"><div className="status-line"><span className={`status-pill status-${job.status}`}>{statusLabel(job.status)}</span><code>{job.job_id.slice(0, 8)}</code><span>{formatDate(job.created_at)}</span></div><h2>{job.active_chapter_title || job.text_preview?.replace(/\[[^\]]+\]/g, '').slice(0, 56) || '正在准备小说内容'}</h2>{castPhase && <div className={`cast-status ${auditBlocksResume ? 'needs-review' : ''}`}><span />{castPhase}{job.cast_audit?.counts?.blocking_issues ? ` · ${job.cast_audit.counts.blocking_issues} 项待处理` : ''}</div>}<div className="job-progress"><div className="progress-track"><span style={{ width: `${chapterPercent}%` }} /></div><strong>当前章 {chapterPercent}% · {playable} 章可听</strong></div>{job.error && <p className="error-note">{job.error}</p>}{job.streaming_warning && <p className="warning-note">{job.streaming_warning}</p>}</div><div className="job-actions">{['processing', 'queued'].includes(job.status) && <button className="button secondary" onClick={() => onAction(job.job_id, 'pause')}>暂停</button>}{paused && job.streaming_mode && <button className="button secondary" disabled={recasting} onClick={() => onRecast(job.job_id)}>{recasting ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}{job.recast ? '重新分析角色' : '修复人物声线'}</button>}{paused && !auditBlocksResume && <button className="button primary" onClick={() => onAction(job.job_id, 'resume')}>继续</button>}{job.status === 'completed' ? <a className="button primary" href={`/api/download/${job.job_id}`}><Download size={16} />下载</a> : <button className="button ghost danger" onClick={() => { if (window.confirm('取消这个制作任务？已生成的音频会保留。')) onAction(job.job_id, 'cancel') }}>取消</button>}</div></article></div>
  })}</div></div>
}

function LibraryPage() {
  const [search, setSearch] = useState('')
  const { data: items = [], isLoading, error } = useQuery({ queryKey: ['library'], queryFn: api.library })
  const { data: queue } = useQuery({ queryKey: ['queue'], queryFn: api.queue, refetchInterval: (query) => query.state.data?.jobs.some((job) => ['processing', 'queued', 'pausing'].includes(job.status)) ? 8000 : false })
  const { data: community } = useQuery({ queryKey: ['community-status'], queryFn: api.communityStatus, refetchInterval: 15_000 })
  const backfill = useMutation({ mutationFn: api.backfillCommunity, onSuccess: (data) => toast.success(data.message || `已排队贡献 ${data.queued} 章`), onError: (error) => toast.error(error.message) })
  const jobFor = (item: LibraryItem) => queue?.jobs.find((job) => job.job_id === item.job_id)
  const filtered = groupLibraryItems(items, queue?.jobs)
    .filter((item) => libraryTitle(item, jobFor(item)).includes(search.trim()))
    .sort((left, right) => {
      const leftActive = ['processing', 'queued', 'pausing'].includes(jobFor(left)?.status ?? '') ? 1 : 0
      const rightActive = ['processing', 'queued', 'pausing'].includes(jobFor(right)?.status ?? '') ? 1 : 0
      return rightActive - leftActive
    })
  return <><PageHeader eyebrow="我的有声书" title="一本书，一个入口" description="正在制作的书也会留在这里。打开一本书，再从目录选择第几章开始听。" action={<label className="search-field"><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索书名" /></label>} />
    {isLoading ? <div className="loading-block"><LoaderCircle className="spin" />正在整理书库…</div> : error ? <EmptyState icon={HeartPulse} title="书库暂时无法读取" description={error.message} /> : filtered.length ? <div className="library-grid">{filtered.map((item) => {
      const job = jobFor(item)
      const title = libraryTitle(item, job)
      const ready = item.chapters?.filter((chapter) => !chapter.missing_file).length ?? 0
      const total = job?.chapter_count ?? item.chapter_count ?? ready
      const active = Boolean(job && ['processing', 'queued', 'pausing'].includes(job.status))
      return <article className={`audiobook-card ${active ? 'is-producing' : ''}`} key={item.job_id}><div className="audiobook-art"><BookOpenText size={26} /></div><div className="audiobook-info"><span>{active ? '正在制作' : '可以收听'} · 已可听 {ready || 1}{total ? ` / ${total}` : ''} 章</span><h2>{title}</h2><p>{active && job?.active_chapter_title ? `正在处理：${job.active_chapter_title}` : `${formatDate(item.created_at)} · ${formatBytes(item.file_size ?? item.total_size ?? item.size)}`}</p></div><div className="audiobook-actions"><NavLink className="button primary" to={`/library/${item.job_id}`}><Play size={16} />{active ? '继续听' : '打开目录'}</NavLink><details><summary aria-label={`${title}的更多操作`}><MoreHorizontal size={20} /></summary><div className="details-menu"><a href={`/api/download/${item.job_id}/zip`}>下载章节压缩包</a>{community?.enabled && <button type="button" onClick={() => backfill.mutate(item.job_id)} disabled={backfill.isPending}>贡献已完成章节</button>}<a href="/legacy">高级编辑与重建</a></div></details></div></article>
    })}</div> : <EmptyState icon={Library} title={search ? '没有匹配的有声书' : '书库还没有可播放的作品'} description={search ? '换个关键词试试。' : '第一章生成完成后，整本书会自动出现在这里，不必等全部完成。'} />}
  </>
}

function playableChapter(chapter: LibraryChapter) {
  return Boolean(chapterAudioUrl(chapter)) && chapter.missing_file !== true && chapter.state !== 'failed'
}

function displayChapterTitle(chapter: LibraryChapter, position: number) {
  const title = chapter.title?.trim()
  if (!title || title.toLowerCase() === 'chapter') return `第 ${position + 1} 章`
  if (title.toLowerCase() === 'title') return '片头 · 作品信息'
  return title
}

function ChapterDirectory({ chapters, selectedPosition, search, onSelect }: { chapters: LibraryChapter[]; selectedPosition: number; search: string; onSelect: (position: number) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const rows = chapters.map((chapter, position) => ({ chapter, position })).filter(({ chapter, position }) => displayChapterTitle(chapter, position).includes(search.trim()))
  const virtualizer = useVirtualizer({ count: rows.length, getScrollElement: () => ref.current, estimateSize: () => 66, overscan: 8 })
  return <div ref={ref} className="chapter-directory" aria-label="章节目录"><div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>{virtualizer.getVirtualItems().map((row) => {
    const entry = rows[row.index]
    const isSelected = entry.position === selectedPosition
    const canPlay = playableChapter(entry.chapter)
    return <div className="chapter-directory-row" key={`${entry.chapter.index}-${entry.position}`} style={{ transform: `translateY(${row.start}px)` }}><button className={`chapter-row ${isSelected ? 'is-selected' : ''}`} type="button" onClick={() => onSelect(entry.position)} disabled={!canPlay} aria-current={isSelected ? 'true' : undefined}><span className="chapter-number">{String(entry.position + 1).padStart(3, '0')}</span><span className="chapter-name"><strong>{displayChapterTitle(entry.chapter, entry.position)}</strong><small>{canPlay ? `${formatDuration(entry.chapter.duration_seconds)} · 点击播放` : entry.chapter.state === 'processing' ? `制作中 ${Math.round(entry.chapter.progress ?? 0)}%` : '等待制作'}</small></span><span className={`chapter-state ${canPlay ? 'is-ready' : ''}`}>{isSelected ? <Volume2 size={17} /> : canPlay ? <Play size={16} /> : <Clock3 size={16} />}</span></button></div>
  })}</div></div>
}

function BookDetailPage() {
  const { jobId = '' } = useParams()
  const [directorySearch, setDirectorySearch] = useState('')
  const [jumpChapter, setJumpChapter] = useState('1')
  const [selectedPosition, setSelectedPosition] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1)
  const audioRef = useRef<HTMLAudioElement>(null)
  const pendingPlayRef = useRef(false)
  const restoredRef = useRef(false)
  const lastReportedSecondRef = useRef(0)
  const { data: items = [], isLoading: libraryLoading } = useQuery({ queryKey: ['library'], queryFn: api.library })
  const { data: queue } = useQuery({ queryKey: ['queue'], queryFn: api.queue, refetchInterval: 8000, refetchIntervalInBackground: false })
  const item = items.find((entry) => entry.job_id === jobId)
  const job = queue?.jobs.find((entry) => entry.job_id === jobId)
  const isStreaming = Boolean(job?.streaming_mode)
  const active = Boolean(job && ['processing', 'queued', 'pausing'].includes(job.status))
  const { data: streaming, error: streamingError } = useQuery({
    queryKey: ['streaming-book', jobId],
    queryFn: () => api.streamingBook(jobId),
    enabled: Boolean(jobId && isStreaming),
    refetchInterval: active ? 8000 : false,
    refetchIntervalInBackground: false,
  })
  const chapters = streaming?.chapters?.length ? streaming.chapters : item?.chapters ?? []
  const title = item ? libraryTitle(item, job) : titleFromPreview(job?.text_preview) || '有声书'
  const readyCount = chapters.filter(playableChapter).length
  const totalCount = job?.chapter_count ?? streaming?.summary?.chapter_count ?? item?.chapter_count ?? chapters.length
  const selected = chapters[selectedPosition]
  const reportPlayback = useCallback((state: string) => {
    const audio = audioRef.current
    if (!audio || !isStreaming) return
    void api.reportPlayback(jobId, { chapter_index: selectedPosition, current_time: audio.currentTime || 0, duration: audio.duration || 0, playback_rate: audio.playbackRate || 1, state }).catch(() => undefined)
  }, [isStreaming, jobId, selectedPosition])

  useEffect(() => {
    if (restoredRef.current || !chapters.length) return
    const stored = streaming?.playback ?? job?.streaming_summary?.playback
    const target = Math.min(Math.max(stored?.chapter_index ?? 0, 0), chapters.length - 1)
    setSelectedPosition(target)
    setPlaybackRate(stored?.playback_rate ?? 1)
    restoredRef.current = true
  }, [chapters.length, job?.streaming_summary?.playback, streaming?.playback])

  const selectChapter = (position: number, autoplay = true) => {
    const chapter = chapters[position]
    if (!chapter || !playableChapter(chapter)) return
    pendingPlayRef.current = autoplay
    setSelectedPosition(position)
    setCurrentTime(0)
    if (position === selectedPosition && audioRef.current) {
      audioRef.current.currentTime = 0
      if (autoplay) void audioRef.current.play()
    }
  }

  const nextPlayable = (direction: 1 | -1) => {
    let position = selectedPosition + direction
    while (position >= 0 && position < chapters.length) {
      if (playableChapter(chapters[position])) return position
      position += direction
    }
    return -1
  }

  const playFirstChapter = () => {
    const firstStory = chapters.findIndex((chapter) => /第\s*0*1\s*章/i.test(chapter.title ?? ''))
    const firstPlayable = chapters.findIndex(playableChapter)
    selectChapter(firstStory >= 0 ? firstStory : firstPlayable, true)
  }

  const jumpToChapter = () => {
    const target = Math.max(1, Number.parseInt(jumpChapter, 10) || 1)
    const exact = chapters.findIndex((chapter) => new RegExp(`第\\s*0*${target}\\s*章`, 'i').test(chapter.title ?? ''))
    const fallback = Math.min(target - 1, chapters.length - 1)
    const position = exact >= 0 ? exact : fallback
    if (!playableChapter(chapters[position])) {
      toast.info(`第 ${target} 章还在制作，请先选择“已可听”的章节。`)
      return
    }
    selectChapter(position, true)
  }

  if (libraryLoading) return <div className="loading-block"><LoaderCircle className="spin" />正在打开有声书…</div>
  if (!item && !job) return <EmptyState icon={BookOpenText} title="没有找到这本有声书" description="它可能已被删除，或第一章还没有生成完成。" action={<NavLink className="button secondary" to="/library">返回书库</NavLink>} />

  return <div className="book-detail">
    <NavLink className="breadcrumb" to="/library"><ArrowLeft size={15} />我的有声书</NavLink>
    <header className="book-hero"><div className="book-cover"><BookOpenText size={34} /><span>声阅</span></div><div className="book-identity"><p className="eyebrow">{active ? '边制作边收听' : '有声书'}</p><h1>{title}</h1><p>{active ? `已可听 ${readyCount} / ${totalCount} 章 · ${job?.active_chapter_title ? `正在制作 ${job.active_chapter_title}` : '后台仍在继续制作'}` : `${readyCount || chapters.length} 章可听 · ${formatDate(item?.created_at)}`}</p><div className="book-hero-actions"><button className="button primary" onClick={playFirstChapter} disabled={!readyCount}><Play size={17} />从第一章播放</button><a className="button secondary" href={`/api/download/${jobId}/zip`}><Download size={17} />下载已完成章节</a></div></div></header>

    <section className="book-player" aria-label="有声书播放器"><div className="now-playing"><span className="playing-mark">{isPlaying ? <Volume2 size={19} /> : <AudioLines size={19} />}</span><div><p>正在收听</p><h2>{selected ? displayChapterTitle(selected, selectedPosition) : '选择一章开始播放'}</h2><small>{formatDuration(currentTime)} / {formatDuration(duration || selected?.duration_seconds)}</small></div></div><label className="player-timeline"><span className="sr-only">播放进度</span><input type="range" min={0} max={duration || selected?.duration_seconds || 0} step={0.1} value={Math.min(currentTime, duration || selected?.duration_seconds || 0)} disabled={!playableChapter(selected)} onChange={(event) => { const time = Number(event.target.value); setCurrentTime(time); if (audioRef.current) audioRef.current.currentTime = time }} /></label><div className="player-controls"><button className="icon-button" type="button" aria-label="上一章" disabled={nextPlayable(-1) < 0} onClick={() => selectChapter(nextPlayable(-1), true)}><SkipBack size={19} /></button><button className="player-main-button" type="button" aria-label={isPlaying ? '暂停' : '播放'} disabled={!playableChapter(selected)} onClick={() => { const audio = audioRef.current; if (!audio) return; if (audio.paused) void audio.play(); else audio.pause() }}>{isPlaying ? <Pause size={22} /> : <Play size={22} />}</button><button className="icon-button" type="button" aria-label="下一章" disabled={nextPlayable(1) < 0} onClick={() => selectChapter(nextPlayable(1), true)}><SkipForward size={19} /></button><label className="rate-control"><span>倍速</span><select value={playbackRate} onChange={(event) => { const rate = Number(event.target.value); setPlaybackRate(rate); if (audioRef.current) audioRef.current.playbackRate = rate; reportPlayback(isPlaying ? 'playing' : 'paused') }}><option value={0.75}>0.75×</option><option value={1}>1×</option><option value={1.25}>1.25×</option><option value={1.5}>1.5×</option><option value={2}>2×</option></select></label></div><audio ref={audioRef} src={chapterAudioUrl(selected)} preload="metadata" onLoadedMetadata={(event) => { const audio = event.currentTarget; audio.playbackRate = playbackRate; const saved = streaming?.playback ?? job?.streaming_summary?.playback; if (saved?.chapter_index === selectedPosition && saved.current_time > 0 && saved.current_time < audio.duration - 2) audio.currentTime = saved.current_time; setDuration(audio.duration || selected?.duration_seconds || 0) }} onCanPlay={(event) => { if (pendingPlayRef.current) { pendingPlayRef.current = false; void event.currentTarget.play() } }} onPlay={() => { setIsPlaying(true); reportPlayback('playing') }} onPause={() => { setIsPlaying(false); reportPlayback('paused') }} onTimeUpdate={(event) => { const second = Math.floor(event.currentTarget.currentTime); setCurrentTime(event.currentTarget.currentTime); if (second > 0 && second - lastReportedSecondRef.current >= 10) { lastReportedSecondRef.current = second; reportPlayback('playing') } }} onEnded={() => { reportPlayback('ended'); const next = nextPlayable(1); if (next >= 0) selectChapter(next, true) }} />
    </section>

    <section className="chapter-section"><div className="chapter-section-heading"><div><p className="eyebrow">章节目录</p><h2>选择从哪里开始听</h2><p>{readyCount} 章已可播放，未完成章节会保留在目录中并显示制作状态。</p></div><div className="chapter-tools"><label className="search-field"><Search size={16} /><input value={directorySearch} onChange={(event) => setDirectorySearch(event.target.value)} placeholder="搜索章节" /></label><div className="chapter-jump"><label htmlFor="chapter-jump-input">从第</label><input id="chapter-jump-input" type="number" min={1} max={totalCount || chapters.length} value={jumpChapter} onChange={(event) => setJumpChapter(event.target.value)} /><span>章</span><button className="button secondary" type="button" onClick={jumpToChapter}>开始听</button></div></div></div>
      {streamingError && !chapters.length ? <EmptyState icon={HeartPulse} title="章节目录暂时无法读取" description={streamingError.message} /> : chapters.length ? <ChapterDirectory chapters={chapters} selectedPosition={selectedPosition} search={directorySearch} onSelect={(position) => selectChapter(position, true)} /> : <div className="loading-block"><LoaderCircle className="spin" />正在读取章节目录…</div>}
    </section>
  </div>
}

const voiceFormSchema = z.object({ name: z.string().trim().min(2, '请给声线起一个至少两个字的名称'), description: z.string().trim().min(4, '请简短描述这条声线'), sample_text: z.string().trim().min(8, '试听文本至少需要 8 个字') })
type VoiceForm = z.infer<typeof voiceFormSchema>

function VoicesPage() {
  const [tab, setTab] = useState<'presets' | 'mine' | 'create'>('presets')
  const [auditionText, setAuditionText] = useVoiceAuditionText()
  const audition = useVoiceAudition()
  const { data: presets = [], isLoading } = useQuery({ queryKey: ['voice-presets'], queryFn: api.voices })
  const { data: prompts = [] } = useQuery({ queryKey: ['voice-prompts'], queryFn: api.voicePrompts })
  const form = useForm<VoiceForm>({ resolver: zodResolver(voiceFormSchema), defaultValues: { name: '', description: '', sample_text: '雨停以后，长街上的灯一盏接一盏亮了起来。' } })
  const preview = useMutation({ mutationFn: async (value: VoiceForm) => {
    const response = await fetch('/api/qwen3/voice-design/preview', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify({ ...value, language: 'Chinese', gender: '', instruct: value.description }) })
    const data = await response.json() as { success?: boolean; error?: string }
    if (!response.ok || !data.success) throw new Error(data.error || '无法创建试听任务')
    return data
  }, onSuccess: () => toast.success('试听任务已创建，可在制作任务查看。'), onError: (error) => toast.error(error.message) })
  return <><PageHeader eyebrow="声线工作室" title="给故事找到合适的声音" description="预设、已保存声线和新建试听分开管理，避免把不相关的引擎堆在同一页。" />
    <div className="filter-tabs">{([['presets', '推荐预设'], ['mine', '我的声线'], ['create', '创建声线']] as const).map(([value, label]) => <button className={tab === value ? 'is-active' : ''} key={value} onClick={() => setTab(value)}>{label}</button>)}</div>
    {tab === 'presets' && <><VoiceAuditionText text={auditionText} onChange={setAuditionText} /><div className="voice-grid">{isLoading ? <div className="loading-block"><LoaderCircle className="spin" />正在读取声线…</div> : presets.map((preset) => <article className="voice-card" key={preset.id ?? preset.code ?? preset.name}><span className="voice-avatar">{preset.name.slice(0, 1)}</span><h2>{preset.name}</h2><p>{preset.description || '中文角色声线'}</p><span className="voice-meta">{preset.gender || '通用'} · {preset.category || '预设'}</span><VoiceAuditionButton preset={preset} text={auditionText} audition={audition} /></article>)}</div></>}
    {tab === 'mine' && (prompts.length ? <div className="voice-grid">{prompts.map((voice) => <article className="voice-card" key={voice.id ?? voice.code ?? voice.name}><span className="voice-avatar"><Mic2 size={18} /></span><h2>{voice.name}</h2><p>{voice.description || '已保存的声线样本'}</p><span className="voice-meta">{voice.language || '中文'} · 我的声线</span></article>)}</div> : <EmptyState icon={Mic2} title="还没有保存的声线" description="在“创建声线”生成试听并确认后，或从旧版导入已有样本。" action={<a className="button secondary" href="/legacy">打开导入与归档</a>} />)}
    {tab === 'create' && <form className="voice-form" onSubmit={form.handleSubmit((value) => preview.mutate(value))}><div className="form-heading"><WandSparkles size={20} /><div><h2>创建一条中文角色声线</h2><p>从人设和试听文本开始；生成后可回到任务列表等待结果。</p></div></div><label className="field"><span>声线名称</span><input {...form.register('name')} placeholder="例如：清冷师尊" />{form.formState.errors.name && <small className="field-error">{form.formState.errors.name.message}</small>}</label><label className="field"><span>音色与表演描述</span><input {...form.register('description')} placeholder="例如：清冷、克制，亲密时会变柔" />{form.formState.errors.description && <small className="field-error">{form.formState.errors.description.message}</small>}</label><label className="field"><span>试听文本</span><textarea {...form.register('sample_text')} rows={4} />{form.formState.errors.sample_text && <small className="field-error">{form.formState.errors.sample_text.message}</small>}</label><button className="button primary" disabled={preview.isPending}>{preview.isPending ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}{preview.isPending ? '正在创建试听…' : '生成试听'}</button></form>}
  </>
}

function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>({})
  const [communityUrl, setCommunityUrl] = useState('')
  const { data, isLoading } = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const { data: assistantStatus, isLoading: assistantLoading } = useQuery({ queryKey: ['site-assistant-status'], queryFn: api.siteAssistantStatus, retry: false })
  const { data: community, isLoading: communityLoading } = useQuery({ queryKey: ['community-status'], queryFn: api.communityStatus, refetchInterval: 15_000 })
  const client = useQueryClient()
  const save = useMutation({ mutationFn: () => api.saveSettings(settings), onSuccess: () => { client.invalidateQueries({ queryKey: ['site-assistant-status'] }); toast.success('设置已保存') }, onError: (error) => toast.error(error.message) })
  const enableCommunity = useMutation({ mutationFn: () => api.enableCommunity(communityUrl), onSuccess: () => { client.invalidateQueries({ queryKey: ['community-status'] }); toast.success('共享书库已启用，后续完成章节会自动贡献') }, onError: (error) => toast.error(error.message) })
  const disableCommunity = useMutation({ mutationFn: api.disableCommunity, onSuccess: () => { client.invalidateQueries({ queryKey: ['community-status'] }); toast.success('已切换为仅本地生成') }, onError: (error) => toast.error(error.message) })
  useEffect(() => { if (data) setSettings(data) }, [data])
  useEffect(() => { if (community?.api_url) setCommunityUrl(community.api_url) }, [community?.api_url])
  if (isLoading) return <div className="loading-block"><LoaderCircle className="spin" />正在读取设置…</div>
  return <><PageHeader eyebrow="设置" title="常用选项先放在眼前" description="引擎、音频和高级参数分组管理；不会再让你从一页折叠面板里猜入口。" />
    <div className="settings-layout"><section className="settings-card"><div className="form-heading"><Gauge size={20} /><div><h2>常用设置</h2><p>这些选项会成为新作品的默认值。</p></div></div><label className="field"><span>默认朗读引擎</span><select value={String(settings.tts_engine ?? 'qwen3_custom')} onChange={(event) => setSettings((current) => ({ ...current, tts_engine: event.target.value }))}><option value="qwen3_custom">Qwen3-TTS · 中文角色声线</option><option value="index_tts">IndexTTS2 · 中文情绪阅读</option><option value="kokoro">Kokoro · 本地</option></select></label><label className="field"><span>默认输出格式</span><select value={String(settings.output_format ?? 'mp3')} onChange={(event) => setSettings((current) => ({ ...current, output_format: event.target.value }))}><option value="mp3">MP3</option><option value="wav">WAV</option></select></label><button className="button primary" onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? '正在保存…' : '保存设置'}</button></section><section className="settings-card muted-card"><Settings2 size={22} /><h2>高级引擎与 API</h2><p>Ollama、云端服务、音色模型、内存管理和所有引擎专属参数暂时保留在兼容界面中；下一步会按引擎逐页迁入 React。</p><a className="button secondary" href="/legacy">打开高级设置</a></section></div>
    <section className="assistant-settings-card"><div className="assistant-settings-heading"><span><Bot size={20} /></span><div><p className="eyebrow">免费 AI 助手</p><h2>让本机模型读懂声阅怎么用</h2><p>复用 Ollama 或 LM Studio 中已经安装的模型；站内助手使用独立操作提示词，不会改动小说分角色提示词。</p></div><div className={`assistant-connection ${assistantStatus?.connected ? 'is-ready' : ''}`}><i />{assistantLoading ? '正在检测' : assistantStatus?.connected ? `已连接 ${assistantStatus.model}` : '尚未连接'}</div></div><div className="assistant-settings-fields"><label className="field"><span>免费模型服务</span><select value={String(settings.llm_local_provider ?? 'ollama')} onChange={(event) => { const provider = event.target.value; setSettings((current) => ({ ...current, llm_local_provider: provider, llm_local_base_url: provider === 'ollama' ? 'http://localhost:11434' : 'http://localhost:1234/v1' })) }}><option value="ollama">Ollama · 推荐</option><option value="lmstudio">LM Studio · OpenAI 兼容</option></select></label><label className="field"><span>本机服务地址</span><input value={String(settings.llm_local_base_url ?? 'http://localhost:11434')} onChange={(event) => setSettings((current) => ({ ...current, llm_local_base_url: event.target.value }))} placeholder="http://localhost:11434" /></label><label className="field"><span>助手模型</span>{assistantStatus?.available_models.length ? <select value={String(settings.llm_local_model ?? assistantStatus.model)} onChange={(event) => setSettings((current) => ({ ...current, llm_local_model: event.target.value }))}>{assistantStatus.available_models.map((model) => <option key={model} value={model}>{model}</option>)}</select> : <input value={String(settings.llm_local_model ?? 'qwen3:1.7b')} onChange={(event) => setSettings((current) => ({ ...current, llm_local_model: event.target.value }))} placeholder="qwen3:1.7b" />}</label></div>{assistantStatus?.connected ? <p className="assistant-settings-note"><Check size={15} />检测到 {assistantStatus.available_models.length} 个已安装模型。保存后，“问声阅”会立即使用所选模型。</p> : <p className="assistant-settings-note is-warning"><CircleHelp size={15} />声阅不会自动下载大型模型或启动服务。请先启动 Ollama/LM Studio，再保存并检测。</p>}<div className="assistant-settings-actions"><small>推荐先用 Qwen 1.5B～4B 级别中文模型；更大的模型回答更稳，但更慢、更占内存。</small><button className="button primary" onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}{save.isPending ? '正在保存…' : '保存并重新检测'}</button></div></section>
    <section className="community-card"><div className="form-heading"><Library size={20} /><div><p className="eyebrow">共享书库</p><h2>{community?.enabled ? '正在自动贡献' : '让已完成章节被更多人听见'}</h2><p>{community?.enabled ? `本机已贡献 ${community.contributions.filter((item) => item.state === 'complete').length} 章；上传失败不会影响本地生成。` : '确认一次后，每章完成会自动转为 Opus、校验并后台贡献；原始小说正文不会上传。'}</p></div></div>{community?.enabled ? <div className="community-actions"><span className="community-state"><Check size={16} />已连接设备 {community.device_id.slice(0, 8)}</span><button className="button ghost danger" onClick={() => disableCommunity.mutate()} disabled={disableCommunity.isPending}>仅保留本地</button></div> : <div className="community-enable"><label className="field"><span>公共书库地址</span><input value={communityUrl} onChange={(event) => setCommunityUrl(event.target.value)} placeholder="https://shengyue-relay.onrender.com" /></label><div className="community-actions"><small>启用即代表你同意以后完成的章节自动上传并做种；可随时切回仅本地。</small><button className="button primary" onClick={() => enableCommunity.mutate()} disabled={enableCommunity.isPending || communityLoading || !communityUrl}>{enableCommunity.isPending ? '正在连接…' : '启用自动贡献'}</button></div></div>}</section>
  </>
}

function HelpPage() {
  const { data: articles = [], isLoading } = useQuery({ queryKey: ['help'], queryFn: api.help })
  return <><PageHeader eyebrow="使用帮助" title="每一步都有可回看的说明" description="从导入小说到处理失败，先给你最短路径，再提供完整的本地帮助文档。" />
    <div className="help-hero"><div><span className="media-icon"><CircleHelp size={19} /></span><h2>第一次使用？先完成这三步</h2><ol><li>新建或导入一部作品</li><li>智能分角色并确认声线</li><li>生成第一章，在任务页查看进度</li></ol></div><NavLink className="button primary" to="/projects">开始创作<ChevronRight size={17} /></NavLink></div>
    <section className="section-block"><div className="section-heading"><div><p className="eyebrow">本地文档</p><h2>按主题查找</h2></div></div>{isLoading ? <div className="loading-block"><LoaderCircle className="spin" />正在读取帮助目录…</div> : articles.length ? <div className="help-grid">{articles.slice(0, 12).map((article) => <a className="help-card" key={article.id} href={`/legacy#help`}><CircleHelp size={18} /><div><h3>{article.title}</h3><p>{article.summary || '打开旧版帮助中心查看完整说明。'}</p></div><ChevronRight size={17} /></a>)}</div> : <EmptyState icon={CircleHelp} title="帮助目录暂时不可用" description="你仍可从旧版帮助中心阅读完整的本地文档。" action={<a className="button secondary" href="/legacy">打开旧版帮助</a>} />}</section>
  </>
}

function Root() { return <ProjectProvider><AppShell /></ProjectProvider> }

export const router = createBrowserRouter([
  { path: '/', Component: Root, children: [
    { index: true, Component: DashboardPage },
    { path: 'discover', Component: DiscoverPage },
    { path: 'projects', Component: ProjectsPage },
    { path: 'projects/:projectId', Component: WorkspacePage },
    { path: 'projects/:projectId/:stage', Component: WorkspacePage },
    { path: 'tasks', Component: TaskPage },
    { path: 'library', Component: LibraryPage },
    { path: 'library/:jobId', Component: BookDetailPage },
    { path: 'voices', Component: VoicesPage },
    { path: 'settings', Component: SettingsPage },
    { path: 'help', Component: HelpPage },
    { path: '*', element: <Navigate to="/" replace /> },
  ] },
])
