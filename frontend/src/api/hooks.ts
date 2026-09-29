import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from './errors'
import { api } from './http'
import { queryKeys, type BriefMode, type MeetingStatus } from './keys'
import type { components } from './schema'

export type Brief = components['schemas']['Brief']
export type MeetingSummary = components['schemas']['MeetingSummary']
export type JobStatus = components['schemas']['JobStatus']
export type ContactTimelineData = components['schemas']['ContactTimeline']
export type StyleProfile = components['schemas']['StyleProfile']
export type Nudge = components['schemas']['Nudge']

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/health')
      if (error || !data) throw new Error('Workspace identity unavailable')
      return data
    },
    staleTime: 60 * 60 * 1000,
  })
}

export function useNudges() {
  return useQuery({
    queryKey: queryKeys.nudges(),
    queryFn: async (): Promise<Nudge[]> => {
      const { data, error } = await api.GET('/api/nudges')
      if (error || !data) throw new Error('Nudges unavailable')
      return data as Nudge[]
    },
    staleTime: 60_000,
  })
}

export function useDemoDate() {
  return useQuery({
    queryKey: ['demo-date'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/health')
      if (error || !data) throw new Error('Demo date unavailable')
      return data.demo_today
    },
    staleTime: 60 * 60 * 1000,
  })
}

export const JOB_POLL_MS = 2500
/** ~150 s of polling, then stop. */
const JOB_MAX_POLLS = 60
const BRIEF_STALE_MS = 30 * 60 * 1000

export function useMeetings(status?: MeetingStatus) {
  return useQuery({
    queryKey: queryKeys.meetings(status),
    queryFn: async () => {
      const { data } = await api.GET('/api/meetings', {
        params: { query: status ? { status } : {} },
      })
      return data as MeetingSummary[]
    },
  })
}

export function useContactTimeline(contactId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.contactTimeline(contactId ?? ''),
    enabled: !!contactId,
    queryFn: async () => {
      const { data } = await api.GET('/api/contacts/{contact_id}/timeline', {
        params: { path: { contact_id: contactId! } },
      })
      return data as ContactTimelineData
    },
  })
}

export function useSuggestedQuestions(meetingId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['suggested-questions', meetingId ?? ''],
    enabled: !!meetingId && enabled,
    staleTime: 30 * 60 * 1000,
    queryFn: async (): Promise<string[]> => {
      const { data, error } = await api.GET('/api/meetings/{meeting_id}/suggested-questions', { params: { path: { meeting_id: meetingId! } } })
      if (error || !data) throw new Error('Suggested questions unavailable')
      return data.questions
    },
  })
}

export function useAskQuestion() {
  return useMutation({
    mutationFn: async (body: { question: string; scope_type: 'meeting' | 'contact' | 'account'; scope_id: string; history?: { question: string; answer: string }[] }) => {
      const { data, error } = await api.POST('/api/ask', { body })
      if (error || !data) throw new Error('Answer unavailable')
      return data
    },
  })
}

export function usePinAnswer() {
  return useMutation({
    mutationFn: async ({ answerId, meetingId }: { answerId: string; meetingId: string }) => {
      const { data, error } = await api.POST('/api/ask/{ask_answer_id}/pin', { params: { path: { ask_answer_id: answerId } }, body: { meeting_id: meetingId } })
      if (error || !data) throw new Error('Answer could not be pinned')
      return data
    },
  })
}

export function useRememberNote() {
  return useMutation({
    mutationFn: async (body: { text: string; scope_type: 'meeting' | 'contact' | 'account'; scope_id: string }) => {
      const { data, error } = await api.POST('/api/memories/notes', { body })
      if (error || !data) throw new Error('Note could not be saved')
      return data
    },
  })
}

/**
 * The stored brief for a meeting and mode. A 404 means "no cached brief" and
 * resolves to `null`. This hook only ever GETs; generation is an explicit
 * mutation (useGenerateBrief).
 */
export function useBrief(meetingId: string | undefined, mode: BriefMode, enabled = true) {
  return useQuery({
    queryKey: queryKeys.brief(meetingId ?? '', mode),
    enabled: !!meetingId && enabled,
    staleTime: BRIEF_STALE_MS,
    refetchOnWindowFocus: false,
    queryFn: async (): Promise<Brief | null> => {
      try {
        const { data } = await api.GET('/api/meetings/{meeting_id}/brief', {
          params: { path: { meeting_id: meetingId! }, query: { mode } },
        })
        return data as Brief
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null
        throw err
      }
    },
  })
}

/** POST /brief?mode= (36-54 s). On success the brief is written into the useBrief cache. */
export function useGenerateBrief(meetingId: string, mode: BriefMode) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (): Promise<Brief> => {
      const { data } = await api.POST('/api/meetings/{meeting_id}/brief', {
        params: { path: { meeting_id: meetingId }, query: { mode } },
      })
      return data as Brief
    },
    onSuccess: (brief) => {
      queryClient.setQueryData(queryKeys.brief(meetingId, mode), brief)
      void queryClient.invalidateQueries({ queryKey: queryKeys.meetingsAll() })
    },
  })
}

export function useStyle(enabled = true) {
  return useQuery({
    queryKey: queryKeys.style(),
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/api/style')
      return data as StyleProfile
    },
  })
}

export function useSubmitFeedback(meetingId: string, briefId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (feedback: components['schemas']['FeedbackRequest']) => {
      const { data } = await api.POST('/api/briefs/{brief_id}/feedback', {
        params: { path: { brief_id: briefId } }, body: feedback,
      })
      return data as StyleProfile
    },
    onSuccess: (profile) => {
      queryClient.setQueryData(queryKeys.style(), profile)
      void queryClient.invalidateQueries({ queryKey: ['brief', meetingId] })
    },
  })
}

/** Polls an ingest job every 2.5 s until done or failed, giving up after ~150 s. */
export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.job(jobId ?? ''),
    enabled: !!jobId,
    refetchOnWindowFocus: false,
    queryFn: async (): Promise<JobStatus> => {
      const { data } = await api.GET('/api/jobs/{job_id}', {
        params: { path: { job_id: jobId! } },
      })
      return data as JobStatus
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'done' || status === 'failed') return false
      if (query.state.dataUpdateCount >= JOB_MAX_POLLS) return false
      return JOB_POLL_MS
    },
  })
}

/** POST notes; resolves with the accepted job id. */
export function useSubmitNotes(meetingId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (transcript: string) => {
      const { data } = await api.POST('/api/meetings/{meeting_id}/notes', {
        params: { path: { meeting_id: meetingId } },
        body: { transcript },
      })
      return data as components['schemas']['JobAccepted']
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.meetingsAll() })
    },
  })
}
