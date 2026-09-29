import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { useJob, useMeetings, useSubmitNotes } from '@/api/hooks'
import type { MeetingSummary } from '@/api/hooks'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'

function NotesDialog({ meetings, onClose }: { meetings: MeetingSummary[]; onClose: () => void }) {
  const [meetingId, setMeetingId] = useState('')
  const [transcript, setTranscript] = useState('')
  const [jobId, setJobId] = useState<string>()
  const completedJobId = useRef<string | undefined>(undefined)
  const submit = useSubmitNotes(meetingId)
  const job = useJob(jobId)

  useEffect(() => {
    if (job.data?.status !== 'done' || !job.data.learned || !jobId || completedJobId.current === jobId) return
    completedJobId.current = jobId
    const learned = job.data.learned
    toast.success('Memory updated', {
      description: [learned.facts.length ? learned.facts.join(' · ') : `${learned.new_commitments} new commitments learned`, learned.alerts.length ? `Alerts: ${learned.alerts.join(' · ')}` : ''].filter(Boolean).join(' · '),
    })
    onClose()
  }, [job.data, jobId, onClose])

  const ready = transcript.trim().length >= 50 && meetingId.length > 0
  async function handleSubmit() {
    if (!ready) return
    try {
      const accepted = await submit.mutateAsync(transcript.trim())
      setJobId(accepted.job_id)
    } catch {
      toast.error('Could not submit notes', { description: 'Check the connection and try again.' })
    }
  }

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Log meeting notes</DialogTitle>
        <DialogDescription>Save the transcript so the agent can update its account memory.</DialogDescription>
      </DialogHeader>
      {jobId ? (
        <div role="status" className="space-y-3 rounded-lg border p-4 text-sm">
          <p className="font-medium">{job.data?.status === 'failed' ? 'Learning failed' : 'Updating account memory…'}</p>
          <p className="text-muted-foreground">{job.data?.status === 'failed' ? job.data.error ?? 'Please try again.' : 'You can keep this window open while the meeting is processed.'}</p>
          {job.isLoading && <Skeleton className="h-2 w-full" />}
        </div>
      ) : (
        <div className="space-y-4">
          <label className="grid gap-2 text-sm font-medium">Meeting
          <select aria-label="Choose meeting" value={meetingId} onChange={(event) => setMeetingId(event.target.value)} className="h-10 rounded-md border bg-background px-3 font-normal">
              <option value="">Choose a meeting</option>
              {meetings.map((meeting) => <option key={meeting.id} value={meeting.id}>{meeting.account_name} · {meeting.title}</option>)}
            </select>
          </label>
          <label htmlFor="transcript" className="grid gap-2 text-sm font-medium">Meeting transcript
            <Textarea id="transcript" value={transcript} onChange={(event) => setTranscript(event.target.value)} rows={8} placeholder="Paste the meeting transcript…" />
          </label>
          <p className="text-xs text-muted-foreground">{transcript.trim().length}/50 characters minimum</p>
        </div>
      )}
      <DialogFooter>
        {jobId ? <Button variant="outline" onClick={onClose}>Close</Button> : <>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!ready || submit.isPending} onClick={() => void handleSubmit()}>{submit.isPending ? 'Submitting…' : 'Start learning'}</Button>
        </>}
      </DialogFooter>
    </DialogContent>
  )
}

export function Dashboard() {
  const meetings = useMeetings('upcoming')
  const [dialogOpen, setDialogOpen] = useState(false)
  return (
    <section className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-sm font-medium text-primary">Your account memory, ready before the next call</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Meetings</h1></div>
        <Button onClick={() => setDialogOpen(true)}>Log notes</Button>
      </div>
      {meetings.isLoading ? <div className="grid gap-3" aria-label="Loading meetings"><Skeleton className="h-28" /><Skeleton className="h-28" /></div> : meetings.isError ? <p role="alert" className="rounded-lg border p-5 text-sm">Meetings could not be loaded. Refresh to try again.</p> : meetings.data?.length ? (
        <div className="grid gap-3">
          {meetings.data.map((meeting) => <article key={meeting.id} className="rounded-xl border bg-card p-5 shadow-card sm:flex sm:items-center sm:justify-between">
            <div><p className="text-sm text-muted-foreground">{meeting.account_name} <span aria-hidden>·</span> {new Date(meeting.scheduled_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</p><h2 className="mt-1 text-lg font-semibold">{meeting.title}</h2><p className="mt-2 text-sm text-muted-foreground">{meeting.attendees.map((contact) => contact.name).join(' · ') || 'No attendees listed'}</p></div>
            <div className="mt-4 flex items-center gap-2 sm:mt-0">{meeting.brief_ready && <Badge>Brief ready</Badge>}<Button variant="outline" onClick={() => setDialogOpen(true)}>Log notes</Button><Button asChild><Link to={`/meetings/${meeting.id}`}>Open brief</Link></Button></div>
          </article>)}
        </div>
      ) : <div className="rounded-xl border border-dashed bg-card px-6 py-14 text-center"><h2 className="font-semibold">No upcoming meetings</h2><p className="mt-2 text-sm text-muted-foreground">Your next meeting will appear here with its account context.</p></div>}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}><NotesDialog key={dialogOpen ? 'open' : 'closed'} meetings={meetings.data ?? []} onClose={() => setDialogOpen(false)} /></Dialog>
    </section>
  )
}
