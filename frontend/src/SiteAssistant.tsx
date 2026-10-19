import { useMutation, useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, BookOpenText, Bot, CircleAlert, Eraser, LoaderCircle, Send, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { api } from './api'
import type { BookSearchJob, ImportedPublicBook, SiteAssistantAction, SiteAssistantMessage } from './types'

type DisplayMessage = SiteAssistantMessage & {
  id: string
  actions?: SiteAssistantAction[]
}

type SiteAssistantProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  activeProject?: { name: string; textLength: number }
  onPublicBookReady: (book: ImportedPublicBook) => Promise<{ projectId: string; jobId: string }>
}

type AssistantMode = 'guide' | 'book'

type BookWorkflowResult =
  | { kind: 'started'; title: string; jobId: string; charCount: number; sourceName: string }
  | { kind: 'review'; title: string; searchJob: BookSearchJob; soushubaCount: number; reason: string }

const INTRO_MESSAGE: DisplayMessage = {
  id: 'assistant-intro',
  role: 'assistant',
  content: '我是声阅的页边助手。我熟悉找书、导入、分角色、生成和收听的完整流程；告诉我你想做到什么，我会直接说下一步点哪里。',
}

const PAGE_LABELS: Array<[RegExp, string]> = [
  [/^\/discover/, '找书'],
  [/^\/projects\/[^/]+\/casting/, '角色与配音'],
  [/^\/projects\/[^/]+\/generate/, '生成与试听'],
  [/^\/projects\/[^/]+/, '正文与章节'],
  [/^\/projects/, '作品'],
  [/^\/tasks/, '制作任务'],
  [/^\/library\/[^/]+/, '有声书详情'],
  [/^\/library/, '我的有声书'],
  [/^\/voices/, '声线工作室'],
  [/^\/settings/, '设置'],
  [/^\/help/, '使用帮助'],
  [/^\/$/, '总览'],
]

function makeMessage(role: SiteAssistantMessage['role'], content: string, actions?: SiteAssistantAction[]): DisplayMessage {
  return { id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2)}`, role, content, actions }
}

function pageLabel(pathname: string) {
  return PAGE_LABELS.find(([pattern]) => pattern.test(pathname))?.[1] ?? '声阅'
}

function projectStage(pathname: string) {
  if (pathname.endsWith('/casting')) return '角色与配音'
  if (pathname.endsWith('/generate')) return '生成与试听'
  if (/^\/projects\/[^/]+/.test(pathname)) return '正文与章节'
  return ''
}

function normalizeBookTitle(value: string) {
  return value.normalize('NFKC').toLocaleLowerCase('zh-CN').replace(/[《》「」『』【】()（）\s·:：,，.。!！?？'"“”‘’_-]/g, '')
}

function cleanBookQuery(value: string) {
  const wrapped = value.match(/《([^》]{2,160})》/)?.[1]
  if (wrapped) return wrapped.trim()
  return value
    .replace(/^(?:请|麻烦)?(?:帮我)?(?:去)?(?:搜书吧)?(?:搜索|搜|找|制作|处理)?(?:一下)?/u, '')
    .replace(/(?:这本书)?(?:并|然后)?(?:开始)?(?:有声|朗读|制作|处理).*$/u, '')
    .trim()
}

function waitForPolling(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

export default function SiteAssistant({ open, onOpenChange, activeProject, onPublicBookReady }: SiteAssistantProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const transcriptRef = useRef<HTMLDivElement | null>(null)
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<DisplayMessage[]>([INTRO_MESSAGE])
  const [mode, setMode] = useState<AssistantMode>('guide')
  const [workflowStage, setWorkflowStage] = useState('')
  const currentPage = pageLabel(location.pathname)
  const status = useQuery({
    queryKey: ['site-assistant-status'],
    queryFn: api.siteAssistantStatus,
    enabled: open,
    staleTime: 20_000,
    retry: false,
  })

  const context = useMemo(() => ({
    pathname: location.pathname,
    page_title: currentPage,
    active_project_name: activeProject?.name ?? '',
    active_project_text_length: activeProject ? String(activeProject.textLength) : '',
    active_project_stage: projectStage(location.pathname),
  }), [activeProject, currentPage, location.pathname])

  const chat = useMutation({
    mutationFn: api.siteAssistantChat,
    onSuccess: (reply) => {
      setMessages((items) => [...items, makeMessage('assistant', reply.message.content, reply.suggested_actions)])
    },
  })

  const bookWorkflow = useMutation({
    mutationFn: async (rawQuery: string): Promise<BookWorkflowResult> => {
      const title = cleanBookQuery(rawQuery)
      if (title.length < 2) throw new Error('请输入至少两个字的书名。')
      setWorkflowStage('正在同时搜索搜书吧与公开书库…')
      const created = await api.createBookSearch({
        query: title,
        source_ids: ['soushuba', 'project-gutenberg', 'google-books', 'open-library'],
        include_mature: true,
      })
      let searchJob = created.job
      for (let attempt = 0; attempt < 30 && ['queued', 'running'].includes(searchJob.status); attempt += 1) {
        await waitForPolling(650)
        searchJob = await api.bookSearchJob(created.job_id)
      }
      if (['queued', 'running'].includes(searchJob.status)) throw new Error('找书任务仍在运行，请到找书页继续查看。')

      const exactGroups = searchJob.results.filter((book) => normalizeBookTitle(book.title) === normalizeBookTitle(title))
      const importableGroups = exactGroups.filter((book) => book.importable && book.offers.some((offer) => offer.source_id === 'project-gutenberg' && offer.importable))
      const soushubaState = searchJob.sources.find((source) => source.id === 'soushuba')
      const soushubaCount = soushubaState ? Math.max(soushubaState.result_count, soushubaState.available_count) : 0
      if (importableGroups.length !== 1) {
        const reason = importableGroups.length > 1
          ? '找到了多个同名公版版本，需要你先确认作者或版本。'
          : soushubaCount > 0
            ? '搜书吧有匹配结果，但没有明确公版或开放授权，不能自动下载。'
            : '没有找到书名完全匹配、且明确允许自动导入的纯文本。'
        return { kind: 'review', title, searchJob, soushubaCount, reason }
      }

      setWorkflowStage('已确认公开授权，正在获取并检查纯文本…')
      const imported = await api.importPublicBook(searchJob.id, importableGroups[0].id)
      setWorkflowStage('正文已建立，正在创建首章有声任务…')
      const production = await onPublicBookReady(imported)
      return {
        kind: 'started',
        title: imported.title,
        jobId: production.jobId,
        charCount: imported.char_count,
        sourceName: imported.source_name,
      }
    },
    onSuccess: (result) => {
      setWorkflowStage('')
      if (result.kind === 'started') {
        setMessages((items) => [...items, makeMessage(
          'assistant',
          `《${result.title}》已从 ${result.sourceName} 获取并通过公开文本检查，共 ${result.charCount.toLocaleString()} 字。声阅作品已经建立，首章有声处理任务已开始。`,
          [{ path: '/tasks', label: '查看制作进度' }],
        )])
        navigate('/tasks')
        return
      }
      const path = `/discover?query=${encodeURIComponent(result.title)}&job_id=${encodeURIComponent(result.searchJob.id)}`
      setMessages((items) => [...items, makeMessage(
        'assistant',
        `${result.reason}${result.soushubaCount ? ` 搜书吧原站约有 ${result.soushubaCount} 条匹配。` : ''} 本次结果已经保留；确认版本和使用权后，可以从找书页打开原站或手动导入你有权使用的文件。`,
        [{ path, label: '查看本次候选' }],
      )])
    },
    onError: () => setWorkflowStage(''),
  })

  useEffect(() => {
    if (!open) return
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus())
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onOpenChange(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => { window.cancelAnimationFrame(frame); window.removeEventListener('keydown', onKeyDown) }
  }, [onOpenChange, open])

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: 'smooth' })
  }, [bookWorkflow.isPending, chat.isPending, messages])

  const starters = currentPage === '找书'
    ? ['为什么有些结果只能打开原站？', '怎么只看普通内容？']
    : currentPage === '制作任务'
      ? ['任务失败先检查什么？', '暂停和取消有什么区别？']
      : currentPage === '设置'
        ? ['怎么接入免费的本机模型？', 'Ollama 没连接怎么办？']
        : ['怎样从找书做到第一章可听？', '我现在这一步接下来做什么？']

  const send = (question = draft) => {
    const content = question.trim()
    if (!content || chat.isPending || bookWorkflow.isPending || (mode === 'guide' && status.data?.connected === false)) return
    const userMessage = makeMessage('user', content)
    const nextMessages = [...messages, userMessage]
    setMessages(nextMessages)
    setDraft('')
    if (mode === 'book') {
      bookWorkflow.reset()
      bookWorkflow.mutate(content)
      return
    }
    chat.reset()
    chat.mutate({
      messages: nextMessages.slice(-12).map(({ role, content: messageContent }) => ({ role, content: messageContent })),
      context,
    })
  }

  const followAction = (action: SiteAssistantAction) => {
    navigate(action.path)
    onOpenChange(false)
  }

  return <>
    <button className="assistant-bookmark" type="button" onClick={() => onOpenChange(true)} aria-label="打开声阅助手" aria-expanded={open}>
      <Bot size={18} /><span>问声阅</span>
    </button>
    <AnimatePresence>
      {open && <>
        <motion.button className="assistant-scrim" type="button" aria-label="关闭声阅助手" onClick={() => onOpenChange(false)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
        <motion.aside className="assistant-drawer" role="dialog" aria-modal="true" aria-labelledby="assistant-title" initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', stiffness: 380, damping: 38 }}>
          <header className="assistant-header">
            <div className="assistant-title-lockup"><span><Sparkles size={17} /></span><div><p>页边批注 · {currentPage}</p><h2 id="assistant-title">声阅助手</h2></div></div>
            <div className="assistant-header-actions"><button type="button" aria-label="清空对话" onClick={() => { setMessages([INTRO_MESSAGE]); chat.reset(); bookWorkflow.reset(); setWorkflowStage('') }}><Eraser size={17} /></button><button type="button" aria-label="关闭" onClick={() => onOpenChange(false)}><X size={19} /></button></div>
          </header>

          <div className={`assistant-model-strip ${status.data?.connected ? 'is-ready' : ''}`}>
            <span aria-hidden="true" />
            {status.isLoading ? '正在检查本机模型…' : status.data?.connected ? `${status.data.provider_label} · ${status.data.model}` : '本机模型未连接'}
            {status.data?.prompt_version && <small>提示词 {status.data.prompt_version}</small>}
          </div>

          <div className="assistant-transcript" ref={transcriptRef} aria-live="polite">
            {messages.map((message) => <article className={`assistant-message is-${message.role}`} key={message.id}>
              <p className="assistant-message-role">{message.role === 'assistant' ? '声阅批注' : '你'}</p>
              <div>{message.content}</div>
              {message.actions?.length ? <nav aria-label="建议入口">{message.actions.map((action) => <button key={action.path} type="button" onClick={() => followAction(action)}>{action.label}<ArrowRight size={14} /></button>)}</nav> : null}
            </article>)}
            {chat.isPending && <div className="assistant-thinking"><LoaderCircle className="spin" size={16} />正在查阅声阅操作手册…</div>}
            {bookWorkflow.isPending && <div className="assistant-workflow-progress"><span><LoaderCircle className="spin" size={17} /></span><div><strong>一句话制书进行中</strong><p>{workflowStage}</p></div></div>}
            {(bookWorkflow.error || chat.error || (mode === 'guide' && status.data?.connected === false)) && <div className="assistant-error" role="alert"><CircleAlert size={17} /><div><strong>{bookWorkflow.error ? '制书流程已停止' : chat.error ? '这次没有回答' : '免费模型还没接通'}</strong><p>{bookWorkflow.error instanceof Error ? bookWorkflow.error.message : chat.error instanceof Error ? chat.error.message : status.data?.error || '请到设置检查本机模型。'}</p>{!bookWorkflow.error && <button type="button" onClick={() => followAction({ path: '/settings', label: '检查 AI 设置' })}>打开设置<ArrowRight size={13} /></button>}</div></div>}
            {messages.length === 1 && status.data?.connected !== false && <div className="assistant-starters"><p>可以这样问</p>{starters.map((starter) => <button type="button" key={starter} onClick={() => send(starter)}>{starter}<ArrowRight size={14} /></button>)}</div>}
          </div>

          <form className="assistant-composer" onSubmit={(event) => { event.preventDefault(); send() }}>
            <div className="assistant-composer-modes" aria-label="助手模式"><button type="button" className={mode === 'guide' ? 'is-active' : ''} aria-pressed={mode === 'guide'} onClick={() => { setMode('guide'); setDraft('') }}><Sparkles size={13} />问操作</button><button type="button" className={mode === 'book' ? 'is-active' : ''} aria-pressed={mode === 'book'} onClick={() => { setMode('book'); setDraft('') }}><BookOpenText size={13} />找书并制作</button></div>
            <label htmlFor="assistant-question">{mode === 'book' ? '输入一本书的书名' : '问这一步怎么做'}</label>
            <div><textarea id="assistant-question" ref={inputRef} value={draft} rows={2} maxLength={4000} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send() } }} placeholder={mode === 'book' ? '例如：Alice’s Adventures in Wonderland' : `例如：我在“${currentPage}”页面，下一步做什么？`} disabled={chat.isPending || bookWorkflow.isPending || (mode === 'guide' && status.data?.connected === false)} /><button type="submit" aria-label={mode === 'book' ? '开始找书并制作' : '发送问题'} disabled={!draft.trim() || chat.isPending || bookWorkflow.isPending || (mode === 'guide' && status.data?.connected === false)}>{chat.isPending || bookWorkflow.isPending ? <LoaderCircle className="spin" size={18} /> : mode === 'book' ? <BookOpenText size={18} /> : <Send size={18} />}</button></div>
            <small>{mode === 'book' ? '会搜索搜书吧和公开书库；仅明确公版/开放授权的唯一匹配会自动导入并开始处理。' : '仅发送对话、页面名称和作品概况；不会发送小说正文或密码。'}</small>
          </form>
        </motion.aside>
      </>}
    </AnimatePresence>
  </>
}
