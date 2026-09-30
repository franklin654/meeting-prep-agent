import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from './errors'
import { api } from './http'
import { queryKeys, type BriefMode, type MeetingStatus } from './keys'
import type { components } from './schema'

export type Brief = components['schemas']['Brief']
export type MeetingSummary = components['schemas']['MeetingSummary']
export type JobStatus = components['schemas']['JobStatus']
export type CaptureDraft = components['schemas']['CaptureDraftResponse']
export type CaptureItem = components['schemas']['CaptureItem']
export type ContactTimelineData = components['schemas']['ContactTimeline']
export type StyleProfile = components['schemas']['StyleProfile']
export type Nudge = components['schemas']['Nudge']
export type Account = components['schemas']['AccountResponse']
export type ContactSummary = components['schemas']['ContactSummary']

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

export function useAccounts() {
  return useQuery({
    queryKey: queryKeys.accounts(),
    queryFn: async (): Promise<Account[]> => {
      const { data } = await api.GET('/api/accounts')
      return data as Account[]
    },
  })
}

export function useContacts(accountId?: string, enabled = true, includeUnconfirmed = false) {
  return useQuery({
    queryKey: queryKeys.contacts(accountId),
    enabled,
    queryFn: async (): Promise<ContactSummary[]> => {
      const { data } = await api.GET('/api/contacts', {
        params: { query: { ...(accountId ? { account_id: accountId } : {}), ...(includeUnconfirmed ? { include_unconfirmed: true } : {}) } },
      })
      return data as ContactSummary[]
    },
  })
}

export function useCreateAccount() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: { name: string; industry?: string; stage: Account['stage'] }) => {
      const { data } = await api.POST('/api/accounts', { body })
      return data as Account
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.accounts() }),
  })
}

export function useCreateContact() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: { account_id: string; name: string; role?: string; aliases?: string[] }) => {
      const { data } = await api.POST('/api/contacts', { body })
      return data as ContactSummary
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: ['contacts'] }),
  })
}

export function useScheduleMeeting() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (body: components['schemas']['MeetingCreate']) => {
      const { data } = await api.POST('/api/meetings', { body })
      return data as MeetingSummary
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.meetingsAll() }),
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

export function useMarkPrepared(meetingId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (prepared: boolean = true) => {
      if (prepared) {
        await api.POST('/api/meetings/{meeting_id}/prepared', {
          params: { path: { meeting_id: meetingId } },
        })
      } else {
        await api.DELETE('/api/meetings/{meeting_id}/prepared', {
          params: { path: { meeting_id: meetingId } },
        })
      }
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.meetingsAll() }),
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

export function usePreviewCapture(meetingId: string) {
  return useMutation({
    mutationFn: async (transcript: string) => {
      const { data } = await api.POST('/api/meetings/{meeting_id}/capture/preview', {
        params: { path: { meeting_id: meetingId } },
        body: { transcript },
      })
      return data as components['schemas']['JobAccepted']
    },
  })
}

export function useSaveCapture(draftId: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (uncheckedItemIds: string[]) => {
      const { data } = await api.POST('/api/capture/{draft_id}/save', {
        params: { path: { draft_id: draftId } },
        body: { unchecked_item_ids: uncheckedItemIds },
      })
      return data as components['schemas']['JobAccepted']
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.meetingsAll() }),
  })
}

export function useDiscardCapture(draftId: string) {
  return useMutation({
    mutationFn: async () => {
      await api.DELETE('/api/capture/{draft_id}', { params: { path: { draft_id: draftId } } })
    },
  })
}
