import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('voice audition API', () => {
  it('sends the selected preset and entered text to the immediate audition endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      success: true,
      audio_base64: 'dGVzdA==',
      mime_type: 'audio/wav',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.auditionVoicePreset({ text: '请听这一句。', presetId: 'frost_master', actingState: 'cold' })).resolves.toMatchObject({
      audio_base64: 'dGVzdA==',
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/qwen3/voice-design/audition', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ text: '请听这一句。', preset_id: 'frost_master', acting_state: 'cold' }),
    }))
  })
})

describe('audiobook playback API', () => {
  it('loads a whole-book chapter index and persists the listening position', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        job_id: 'book-1',
        chapters: [{ index: 0, title: '第1章 登仙门', state: 'ready', can_play: true, file_url: '/chapter-1.mp3' }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.streamingBook('book-1')).resolves.toMatchObject({
      job_id: 'book-1',
      chapters: [{ title: '第1章 登仙门' }],
    })
    await api.reportPlayback('book-1', {
      chapter_index: 0,
      current_time: 48.4,
      duration: 51.3,
      playback_rate: 1.25,
      state: 'paused',
    })

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/jobs/book-1/chapters', expect.any(Object))
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/jobs/book-1/playback', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ chapter_index: 0, current_time: 48.4, duration: 51.3, playback_rate: 1.25, state: 'paused' }),
    }))
  })
})

describe('book discovery API', () => {
  it('starts a local search job and polls its merged source snapshot', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        job_id: 'search-1',
        job: { id: 'search-1', query: '三体', status: 'queued', sources: [], results: [], result_count: 0 },
      }), { status: 202, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        job: {
          id: 'search-1', query: '三体', status: 'completed', result_count: 1,
          sources: [{ id: 'open-library', name: 'Open Library', status: 'success', result_count: 1 }],
          results: [{ id: 'book-1', title: '三体', offers: [{ source_id: 'open-library', url: 'https://openlibrary.org/' }] }],
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await api.createBookSearch({ query: '三体', source_ids: ['open-library'], include_mature: true })
    await expect(api.bookSearchJob('search-1')).resolves.toMatchObject({ status: 'completed', result_count: 1 })

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/book-search/jobs', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ query: '三体', source_ids: ['open-library'], include_mature: true }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/book-search/jobs/search-1', expect.any(Object))
  })

  it('writes source credentials without exposing a read-password request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      success: true,
      credential_configured: true,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await api.saveBookSourceCredentials('qidian', 'reader', 'local-secret')

    expect(fetchMock).toHaveBeenCalledWith('/api/book-search/sources/qidian/credentials', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ username: 'reader', password: 'local-secret' }),
    }))
  })

  it('imports text only by referencing a result from the current search job', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      success: true,
      book: {
        group_id: 'public-book-1',
        title: 'Alice in Wonderland',
        authors: ['Lewis Carroll'],
        text: 'Public-domain text',
        char_count: 18,
        source_id: 'project-gutenberg',
        source_name: 'Project Gutenberg',
        source_url: 'https://www.gutenberg.org/ebooks/11',
        download_url: 'https://www.gutenberg.org/ebooks/11.txt.utf-8',
        license: 'Public domain',
      },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(api.importPublicBook('search-1', 'public-book-1')).resolves.toMatchObject({
      source_id: 'project-gutenberg',
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/book-search/jobs/search-1/import', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ group_id: 'public-book-1' }),
    }))
  })
})
