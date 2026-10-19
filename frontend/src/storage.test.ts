import { beforeEach, describe, expect, it, vi } from 'vitest'
import { loadProjects, readActiveProjectId, writeActiveProjectId } from './storage'

const entries = new Map<string, string>()

beforeEach(() => {
  entries.clear()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => entries.set(key, value),
    removeItem: (key: string) => entries.delete(key),
    clear: () => entries.clear(),
  })
})

describe('project storage migration', () => {
  it('normalizes an existing legacy draft without discarding its content', () => {
    entries.set('tts-story-projects', JSON.stringify([{
      id: 'legacy-1',
      name: '长夜行',
      text: '第一章：雨夜',
      saved_at: '2026-07-01T12:00:00.000Z',
      output_format: 'wav',
      output_bitrate: 192,
      assignments: { 旁白: '温柔女声' },
    }]))

    const projects = loadProjects()

    expect(projects).toHaveLength(1)
    expect(projects[0]).toMatchObject({
      id: 'legacy-1', name: '长夜行', text: '第一章：雨夜', outputFormat: 'wav', outputBitrate: 192,
      voiceAssignments: { 旁白: '温柔女声' },
    })
    expect(entries.get('shengyue-projects-v2')).toContain('长夜行')
  })

  it('remembers the active project separately from the draft list', () => {
    writeActiveProjectId('project-current')
    expect(readActiveProjectId()).toBe('project-current')
  })
})
