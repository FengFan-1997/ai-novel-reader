import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight, BookOpenText, BookSearch, Check, CircleAlert, CircleCheck, Clock3, Download, ExternalLink,
  Globe2, Heart, History, KeyRound, LoaderCircle, LockKeyhole, Plus, Radar,
  Search, Settings2, ShieldAlert, SlidersHorizontal, Trash2, X,
} from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { api } from './api'
import type { BookAccess, BookSearchGroup, BookSearchSource, SourceSearchState } from './types'

const accessLabels: Record<BookAccess | 'all', string> = {
  all: '全部访问状态',
  public: '公开可读',
  login_required: '需要登录',
  paid: '付费',
  unknown: '状态未知',
}

const sourceStatusLabels: Record<SourceSearchState['status'], string> = {
  queued: '等待中',
  running: '搜索中',
  success: '已完成',
  login_required: '需要登录',
  failed: '暂时失效',
  timeout: '已超时',
}

function SourceRadar({ sources, states }: { sources: BookSearchSource[]; states?: SourceSearchState[] }) {
  const stateMap = new Map(states?.map((state) => [state.id, state]))
  const visibleSources = states ? sources.filter((source) => stateMap.has(source.id)) : sources.filter((source) => source.enabled)
  return <section className="source-radar" aria-labelledby="source-radar-title">
    <div className="source-radar-heading">
      <span><Radar size={18} /></span>
      <div><h2 id="source-radar-title">来源雷达</h2><p aria-live="polite">{states ? `${states.filter((item) => ['success', 'failed', 'timeout', 'login_required'].includes(item.status)).length} / ${states.length} 个来源已返回` : '搜索后会逐站显示实时状态'}</p></div>
    </div>
    <div className="radar-track" role="list">
      {visibleSources.map((source) => {
        const state = stateMap.get(source.id)
        const status = state?.status ?? (source.health === 'ready' ? 'success' : 'failed')
        const message = state?.message ?? source.health_message
        return <div className={`radar-source radar-${status}`} role="listitem" key={source.id} title={message}>
          <span className="radar-dot">{status === 'running' || status === 'queued' ? <LoaderCircle className="spin" size={13} /> : status === 'success' ? <Check size={13} /> : <CircleAlert size={13} />}</span>
          <span><strong>{source.name}</strong><small>{state ? (state.status === 'success' ? state.message : sourceStatusLabels[state.status]) : message}</small></span>
          {source.mature && <b>成人</b>}
        </div>
      })}
    </div>
  </section>
}

function BookCover({ book }: { book: BookSearchGroup }) {
  const [failed, setFailed] = useState(false)
  if (book.cover_url && !failed) return <img className="discovery-cover" src={book.cover_url} alt={`${book.title}封面`} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
  return <div className="discovery-cover cover-fallback" aria-hidden="true"><BookOpenText size={24} /><span>{book.title.slice(0, 6)}</span></div>
}

function ResultCard({ book, favorite, onFavorite }: { book: BookSearchGroup; favorite: boolean; onFavorite: () => void }) {
  const firstOffer = book.offers[0]
  const directDownload = book.offers.find((offer) => Boolean(offer.download_url))
  const primaryOffer = directDownload ?? firstOffer
  return <article className={`discovery-result ${book.mature ? 'is-mature' : ''}`}>
    <BookCover book={book} />
    <div className="result-copy">
      <div className="result-badges">
        <span>{book.book_type || '图书'}</span>
        <span>{accessLabels[book.access]}</span>
        {book.importable && <span title="来源提供开放授权或明确公版的纯文本格式">提供公版文本</span>}
        {book.mature && <strong><ShieldAlert size={12} />成人内容</strong>}
      </div>
      <h2>{book.title}</h2>
      <p className="result-authors">{book.authors.length ? book.authors.join('、') : '作者未知'} · {book.source_count} 个来源</p>
      {book.description && <p className="result-description">{book.description}</p>}
      <div className="offer-list" aria-label={`${book.title}的全部来源`}>
        {book.offers.map((offer) => <div className={offer.mature ? 'offer-row mature-offer' : 'offer-row'} key={`${offer.source_id}-${offer.url}`}>
          <span>{offer.source_name}{offer.mature ? ' · 成人' : ''}</span>
          <a href={offer.download_url || offer.url} target="_blank" rel="noreferrer" title={offer.license || `${offer.download_url ? '下载' : '打开'}${offer.source_name}`}>
            {offer.download_url ? <><Download size={13} />下载 {offer.download_format || '文件'}</> : <>{offer.access === 'public' ? '去原站阅读' : '去原站获取'}<ExternalLink size={13} /></>}
          </a>
        </div>)}
      </div>
    </div>
    <div className="result-actions">
      <button className={`icon-button ${favorite ? 'is-favorite' : ''}`} type="button" onClick={onFavorite} aria-label={favorite ? `取消收藏${book.title}` : `收藏${book.title}`}><Heart size={18} fill={favorite ? 'currentColor' : 'none'} /></button>
      {primaryOffer && <a className="button primary" href={primaryOffer.download_url || primaryOffer.url} target="_blank" rel="noreferrer">{primaryOffer.download_url ? <><Download size={15} />下载 {primaryOffer.download_format || '文件'}</> : <>去原站获取<ExternalLink size={15} /></>}</a>}
    </div>
  </article>
}

function CredentialEditor({ source, onChanged }: { source: BookSearchSource; onChanged: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const save = useMutation({
    mutationFn: () => api.saveBookSourceCredentials(source.id, username, password),
    onSuccess: () => { setUsername(''); setPassword(''); onChanged(); toast.success(`${source.name}账号已写入本机钥匙串。`) },
    onError: (error) => toast.error(error.message),
  })
  const clear = useMutation({
    mutationFn: () => api.deleteBookSourceCredentials(source.id),
    onSuccess: () => { onChanged(); toast.success(`${source.name}账号已清除。`) },
    onError: (error) => toast.error(error.message),
  })
  return <details className="credential-editor">
    <summary><KeyRound size={14} />{source.credential_configured ? '账号已配置' : '配置本机账号'}</summary>
    <div>
      <p><LockKeyhole size={14} />只存入这台 Mac 的钥匙串。验证码、二次验证和站点登录挑战仍需在原站完成。</p>
      <label><span>用户名</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
      <label><span>密码</span><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <div className="inline-actions"><button className="button secondary" type="button" disabled={save.isPending || !username.trim() || !password} onClick={() => save.mutate()}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <KeyRound size={15} />}保存到钥匙串</button>{source.credential_configured && <button className="button ghost" type="button" disabled={clear.isPending} onClick={() => clear.mutate()}><Trash2 size={15} />清除</button>}</div>
    </div>
  </details>
}

type SoushubaCandidate = {
  origin: string
  verified: boolean
  title: string
  discovered_via: 'release_page' | 'searxng'
}

function SoushubaOriginReview({ source, onChanged }: { source: BookSearchSource; onChanged: () => void }) {
  const [releaseUrl, setReleaseUrl] = useState(source.release_url)
  const [candidates, setCandidates] = useState<SoushubaCandidate[]>([])

  useEffect(() => setReleaseUrl(source.release_url), [source.release_url])

  const saveAndDiscover = useMutation({
    mutationFn: async () => {
      await api.updateBookSearchSource(source.id, { release_url: releaseUrl.trim() })
      return api.discoverSoushuba()
    },
    onSuccess: (data) => {
      setCandidates(data.candidates)
      onChanged()
      toast.success(data.candidates.some((candidate) => candidate.verified) ? '已从发布页找到可确认的 HTTPS 搜索站。' : '发布页已保存，暂未验证到可用搜索站。')
    },
    onError: (error) => toast.error(error.message),
  })
  const confirm = useMutation({
    mutationFn: (origin: string) => api.updateBookSearchSource(source.id, { confirmed_origin: origin }),
    onSuccess: () => { onChanged(); toast.success('当前搜索站已确认；账号只会发送到这个 HTTPS 域名。') },
    onError: (error) => toast.error(error.message),
  })

  return <div className="origin-review">
    <div className="source-route" aria-label="搜书吧地址链路">
      <div><span>发布页 · 只读</span>{source.release_url ? <a href={source.release_url} target="_blank" rel="noreferrer">{source.release_url}<ExternalLink size={12} /></a> : <strong>尚未设置</strong>}<small>允许 HTTP，只读取最新地址，绝不发送账号</small></div>
      <ArrowRight aria-hidden="true" size={16} />
      <div><span>当前搜索站 · 登录</span>{source.confirmed_origin ? <a href={source.confirmed_origin} target="_blank" rel="noreferrer">{source.confirmed_origin}<ExternalLink size={12} /></a> : <strong>尚未确认</strong>}<small>必须是已验证的 HTTPS 域名，账号仅绑定于此</small></div>
    </div>
    <label className="release-url-field"><span>搜书吧发布页地址</span><input type="url" value={releaseUrl} onChange={(event) => setReleaseUrl(event.target.value)} placeholder="http://发布页域名:端口/o/?sigin=..." /></label>
    <button className="button secondary" type="button" disabled={saveAndDiscover.isPending || !releaseUrl.trim()} onClick={() => saveAndDiscover.mutate()}>{saveAndDiscover.isPending ? <LoaderCircle className="spin" size={15} /> : <Globe2 size={15} />}保存并读取最新地址</button>
    {candidates.map((candidate) => <div className="origin-candidate" key={candidate.origin}><span><strong>{candidate.origin}</strong><small>{candidate.verified ? `${candidate.discovered_via === 'release_page' ? '发布页直达' : '全网线索'} · HTTPS、品牌和搜索入口已验证` : '未通过自动验证，请勿确认'}</small></span><button className="button ghost" type="button" disabled={!candidate.verified || confirm.isPending || candidate.origin === source.confirmed_origin} onClick={() => confirm.mutate(candidate.origin)}>{candidate.origin === source.confirmed_origin ? '当前使用' : '确认使用'}</button></div>)}
  </div>
}

function SourceSettings({ sources }: { sources: BookSearchSource[] }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [template, setTemplate] = useState('')
  const [mature, setMature] = useState(false)
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['book-search-sources'] })
  const update = useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled?: boolean }) => api.updateBookSearchSource(id, { enabled }), onSuccess: refresh, onError: (error) => toast.error(error.message) })
  const remove = useMutation({ mutationFn: api.deleteBookSearchSource, onSuccess: () => { refresh(); toast.success('自定义来源已删除。') }, onError: (error) => toast.error(error.message) })
  const add = useMutation({
    mutationFn: () => api.createBookSearchSource({ name, domain, search_url_template: template, mature }),
    onSuccess: () => { setName(''); setDomain(''); setTemplate(''); setMature(false); refresh(); toast.success('自定义来源已加入来源雷达。') },
    onError: (error) => toast.error(error.message),
  })
  return <details className="source-settings">
    <summary><Settings2 size={16} /><span><strong>来源与本机账号</strong><small>启停来源、确认搜书吧地址或加入自定义网站</small></span></summary>
    <div className="source-settings-body">
      <div className="source-admin-list">
        {sources.map((source) => <article key={source.id}>
          <div className="source-admin-heading"><span className={`source-health health-${source.health}`}>{source.health === 'ready' ? <CircleCheck size={15} /> : <CircleAlert size={15} />}</span><div><strong>{source.name}{source.mature ? ' · 成人来源' : ''}</strong><small>{source.health_message}</small></div><label className="switch-label"><input type="checkbox" checked={source.enabled} onChange={(event) => update.mutate({ id: source.id, enabled: event.target.checked })} /><span>{source.enabled ? '启用' : '停用'}</span></label></div>
          <div className="source-admin-actions">{source.id !== 'soushuba' && source.homepage_url && <a href={source.homepage_url} target="_blank" rel="noreferrer">打开原站<ExternalLink size={13} /></a>}{!source.builtin && <button type="button" onClick={() => remove.mutate(source.id)}>删除</button>}</div>
          {source.id === 'soushuba' && <SoushubaOriginReview source={source} onChanged={refresh} />}
          {source.credential_supported && <CredentialEditor source={source} onChanged={refresh} />}
        </article>)}
      </div>
      <form className="custom-source-form" onSubmit={(event) => { event.preventDefault(); add.mutate() }}>
        <div><p className="eyebrow">自定义来源</p><h3>加入一个公开网站</h3><p>仅填写域名和搜索 URL 模板，不执行脚本或 XPath。后端会阻止内网、回环和危险协议。</p></div>
        <label><span>名称</span><input required value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：豆瓣读书" /></label>
        <label><span>域名</span><input required value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="book.example.com" /></label>
        <label><span>搜索 URL 模板</span><input required value={template} onChange={(event) => setTemplate(event.target.value)} placeholder="https://book.example.com/search?q={query}" /></label>
        <label className="check-label"><input type="checkbox" checked={mature} onChange={(event) => setMature(event.target.checked)} />将此来源标记为成人内容</label>
        <button className="button primary" type="submit" disabled={add.isPending}>{add.isPending ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}加入来源</button>
      </form>
    </div>
  </details>
}

export function DiscoverPage() {
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [query, setQuery] = useState(() => searchParams.get('query')?.trim() ?? '')
  const [jobId, setJobId] = useState<string | null>(() => searchParams.get('job_id')?.trim() || null)
  const [selectedSources, setSelectedSources] = useState<string[] | null>(null)
  const [ordinaryOnly, setOrdinaryOnly] = useState(false)
  const [sourceFilter, setSourceFilter] = useState('all')
  const [accessFilter, setAccessFilter] = useState<BookAccess | 'all'>('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [lastRecordedJob, setLastRecordedJob] = useState<string | null>(null)

  const sourceQuery = useQuery({ queryKey: ['book-search-sources'], queryFn: api.bookSearchSources })
  const sources = useMemo(() => sourceQuery.data?.sources ?? [], [sourceQuery.data])
  useEffect(() => {
    if (selectedSources === null && sources.length) setSelectedSources(sources.filter((source) => source.enabled).map((source) => source.id))
  }, [selectedSources, sources])
  const historyQuery = useQuery({ queryKey: ['book-search-history'], queryFn: api.bookSearchHistory })
  const favoritesQuery = useQuery({ queryKey: ['book-search-favorites'], queryFn: api.bookSearchFavorites })
  const jobQuery = useQuery({
    queryKey: ['book-search-job', jobId],
    queryFn: () => api.bookSearchJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (current) => ['queued', 'running'].includes(current.state.data?.status ?? '') ? 700 : false,
  })
  const job = jobQuery.data
  useEffect(() => {
    if (job && ['completed', 'failed'].includes(job.status) && lastRecordedJob !== job.id) {
      setLastRecordedJob(job.id)
      void queryClient.invalidateQueries({ queryKey: ['book-search-history'] })
    }
  }, [job, lastRecordedJob, queryClient])

  const search = useMutation({
    mutationFn: ({ value, page }: { value: string; page: number }) => api.createBookSearch({ query: value, page, source_ids: selectedSources ?? undefined, include_mature: true }),
    onSuccess: (data) => { queryClient.setQueryData(['book-search-job', data.job_id], data.job); setJobId(data.job_id) },
    onError: (error) => toast.error(error.message),
  })
  const runSearch = (value = query, page = 1) => {
    const normalized = value.trim()
    if (normalized.length < 2) return toast.error('请输入至少两个字的书名、作者或 ISBN。')
    if (selectedSources?.length === 0) return toast.error('请至少选择一个搜索来源。')
    setQuery(normalized)
    search.mutate({ value: normalized, page })
  }
  const submit = (event: FormEvent) => { event.preventDefault(); runSearch() }

  const favoriteIds = new Set((favoritesQuery.data ?? []).map((item) => item.id))
  const favorite = useMutation({
    mutationFn: async (book: BookSearchGroup) => favoriteIds.has(book.id) ? api.deleteBookSearchFavorite(book.id) : api.saveBookSearchFavorite(book),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['book-search-favorites'] }),
    onError: (error) => toast.error(error.message),
  })
  const deleteHistory = useMutation({ mutationFn: api.deleteBookSearchHistory, onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['book-search-history'] }), onError: (error) => toast.error(error.message) })

  const types = useMemo(() => [...new Set((job?.results ?? []).map((item) => item.book_type).filter(Boolean))], [job?.results])
  const visibleResults = useMemo(() => (job?.results ?? []).filter((book) => {
    if (ordinaryOnly && book.mature) return false
    if (accessFilter !== 'all' && book.access !== accessFilter) return false
    if (typeFilter !== 'all' && book.book_type !== typeFilter) return false
    if (sourceFilter !== 'all' && !book.offers.some((offer) => offer.source_id === sourceFilter)) return false
    return true
  }), [accessFilter, job?.results, ordinaryOnly, sourceFilter, typeFilter])

  return <div className="discover-page">
    <header className="discover-hero">
      <div><p className="eyebrow">找书神器</p><h1>一处落笔，四方寻书</h1><p>输入书名、作者或 ISBN。公开授权文件可以直接下载，其余结果会带你到原站合法获取。</p></div>
      <div className="discover-seal" aria-hidden="true"><BookSearch size={25} /><span>寻书</span></div>
      <form className="discover-search" role="search" onSubmit={submit}>
        <Search size={20} aria-hidden="true" />
        <label className="sr-only" htmlFor="book-discovery-query">书名、作者或 ISBN</label>
        <input id="book-discovery-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：三体、刘慈欣、9787536692930" autoComplete="off" />
        {query && <button className="clear-query" type="button" onClick={() => setQuery('')} aria-label="清空搜索词"><X size={16} /></button>}
        <button className="button primary" type="submit" disabled={search.isPending}>{search.isPending ? <LoaderCircle className="spin" size={17} /> : <Search size={17} />}开始找书</button>
      </form>
      <div className="source-picker" aria-label="参与搜索的来源">
        <span><SlidersHorizontal size={14} />搜索范围</span>
        {sources.filter((source) => source.enabled).map((source) => <label key={source.id} className={source.mature ? 'mature-source' : ''}><input type="checkbox" checked={selectedSources?.includes(source.id) ?? false} onChange={(event) => setSelectedSources((current) => event.target.checked ? [...new Set([...(current ?? []), source.id])] : (current ?? []).filter((id) => id !== source.id))} />{source.name}{source.mature ? ' · 成人' : ''}</label>)}
      </div>
      {sourceQuery.data && sources.some((source) => source.health === 'degraded') && <p className="degraded-notice"><CircleAlert size={15} />SearXNG 未运行或部分来源不可用；Google Books、Open Library 等直连来源仍会继续搜索。</p>}
    </header>

    <SourceRadar sources={sources} states={job?.sources} />

    <div className="discovery-utility-grid">
      <section className="history-panel">
        <div className="mini-heading"><span><History size={16} />最近搜索</span>{Boolean(historyQuery.data?.length) && <button type="button" onClick={() => deleteHistory.mutate(undefined)}>全部清空</button>}</div>
        <div className="history-chips">{historyQuery.data?.length ? historyQuery.data.slice(0, 8).map((entry) => <span key={entry.id}><button type="button" onClick={() => runSearch(entry.query)}>{entry.query}</button><button type="button" onClick={() => deleteHistory.mutate(entry.id)} aria-label={`删除搜索记录${entry.query}`}><X size={12} /></button></span>) : <small>搜索记录只保存在这台电脑。</small>}</div>
      </section>
      <section className="favorites-panel">
        <div className="mini-heading"><span><Heart size={16} />本机收藏</span><small>{favoritesQuery.data?.length ?? 0} 本</small></div>
        <div className="favorite-strip">{favoritesQuery.data?.length ? favoritesQuery.data.slice(0, 4).map((book) => <a key={book.id} href={book.offers[0]?.url} target="_blank" rel="noreferrer"><strong>{book.title}</strong><small>{book.authors.join('、') || '作者未知'}</small></a>) : <small>点结果右侧的爱心，稍后从这里回来。</small>}</div>
      </section>
    </div>

    {job && <section className="results-section" aria-labelledby="results-title">
      <div className="results-heading"><div><p className="eyebrow">搜索结果</p><h2 id="results-title">“{job.query}”{job.status === 'running' || job.status === 'queued' ? ' 正在汇入…' : ` · ${job.result_count} 本`}</h2></div><button className={`button ${ordinaryOnly ? 'primary' : 'secondary'}`} type="button" onClick={() => setOrdinaryOnly((value) => !value)}><ShieldAlert size={16} />{ordinaryOnly ? '已只看普通内容' : '一键只看普通内容'}</button></div>
      <div className="result-filters">
        <label><span>来源</span><select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}><option value="all">全部来源</option>{sources.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}</select></label>
        <label><span>访问状态</span><select value={accessFilter} onChange={(event) => setAccessFilter(event.target.value as BookAccess | 'all')}>{Object.entries(accessLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label><span>书籍类型</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="all">全部类型</option>{types.map((type) => <option value={type} key={type}>{type}</option>)}</select></label>
        <span className="visible-count">当前显示 {visibleResults.length} 本</span>
      </div>
      <div className="results-list">{visibleResults.map((book) => <ResultCard book={book} key={book.id} favorite={favoriteIds.has(book.id)} onFavorite={() => favorite.mutate(book)} />)}</div>
      {!visibleResults.length && job.status === 'failed' && <div className="discovery-empty"><CircleAlert size={24} /><h3>这次没有来源返回结果</h3><p>请检查网络或 SearXNG 状态，也可以换一个更短的书名再试。</p></div>}
      {!visibleResults.length && job.status !== 'failed' && !['queued', 'running'].includes(job.status) && <div className="discovery-empty"><BookSearch size={24} /><h3>筛选后没有结果</h3><p>放宽来源、访问状态或成人内容筛选即可恢复。</p></div>}
      {(job.status === 'completed' || job.status === 'failed') && <div className="pagination"><button className="button secondary" type="button" disabled={job.page <= 1} onClick={() => runSearch(job.query, job.page - 1)}>上一页</button><span>第 {job.page} 页</span><button className="button secondary" type="button" disabled={!job.has_next_page} onClick={() => runSearch(job.query, job.page + 1)}>下一页</button></div>}
    </section>}

    {!job && <section className="discovery-empty welcome-empty"><Globe2 size={26} /><h2>先搜一本你想读的书</h2><p>默认会包含成人来源，但每条成人结果都会单独醒目标注；可随时一键只看普通内容。</p></section>}

    <SourceSettings sources={sources} />
    <aside className="discovery-policy"><Clock3 size={16} /><p>这里只保存最近 100 条搜索词和你主动收藏的书目。公版文件使用来源直链下载；登录、付费或银币附件会前往原站确认，不绕过权限，也不缓存受保护正文。</p></aside>
  </div>
}
