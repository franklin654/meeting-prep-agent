import type { components } from './schema'

export type BriefMode = components['schemas']['Brief']['mode']
export type MeetingStatus = 'upcoming' | 'done'

/** All TanStack Query keys, in one place. */
export const queryKeys = {
  meetings: (status?: MeetingStatus) => ['meetings', status ?? 'all'] as const,
  meetingsAll: () => ['meetings'] as const,
  brief: (meetingId: string, mode: BriefMode) => ['brief', meetingId, mode] as const,
  job: (jobId: string) => ['job', jobId] as const,
}
