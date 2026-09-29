import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from './errors'
import { api } from './http'
import { queryKeys, type BriefMode, type MeetingStatus } from './keys'
import type { components } from './schema'

export type Brief = components['schemas']['Brief']
export type MeetingSummary = components['schemas']['MeetingSummary']
export type JobStatus = components['schemas']['JobStatus']

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

/**
 * The stored brief for a meeting and mode. A 404 means "no cached brief" and
 * resolves to `null`. This hook only ever GETs; generation is an explicit
 * mutation (useGenerateBrief).
 */
export function useBrief(meetingId: string | undefined, mode: BriefMode) {
  return useQuery({
    queryKey: queryKeys.brief(meetingId ?? '', mode),
    enabled: !!meetingId,
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
