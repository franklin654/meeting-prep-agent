import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import {
  useContacts,
  useJob,
  useMeetings,
  useStyle,
  useSubmitNotes,
} from '@/api/hooks'
import type { MeetingSummary } from '@/api/hooks'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { NudgeDigest } from '@/components/NudgeDigest'
import { ScheduleMeetingDialog } from '@/components/ScheduleMeetingDialog'
import { Textarea } from '@/components/ui/textarea'
import { HeaderControls } from '@/components/Layout'

function NotesDialog({
  meetings,
  initialMeetingId,
  onClose,
}: {
  meetings: MeetingSummary[]
  initialMeetingId?: string
  onClose: () => void
}) {
  const [meetingId, setMeetingId] = useState(initialMeetingId ?? '')
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
          <label className="grid gap-2 text-sm font-medium">
            Meeting
            <select aria-label="Choose meeting" value={meetingId} onChange={(event) => setMeetingId(event.target.value)} className="h-11 rounded-md border bg-background px-3 font-normal">
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

function SearchBox({ meetings }: { meetings: MeetingSummary[] }) {
  const [query, setQuery] = useState('')
  const contacts = useContacts()
  const normalized = query.trim().toLocaleLowerCase()
  const results = useMemo(() => {
    if (!normalized) return { meetings: [], contacts: [] }
    return {
      meetings: meetings.filter((meeting) => `${meeting.title} ${meeting.account_name} ${meeting.attendees.map((person) => person.name).join(' ')}`.toLocaleLowerCase().includes(normalized)).slice(0, 5),
      contacts: (contacts.data ?? []).filter((contact) => `${contact.name} ${contact.role ?? ''} ${contact.account_name ?? ''}`.toLocaleLowerCase().includes(normalized)).slice(0, 5),
    }
  }, [contacts.data, meetings, normalized])
  const total = results.meetings.length + results.contacts.length

  return (
    <div className="relative w-[min(36vw,14rem)] sm:w-64">
      <label className="sr-only" htmlFor="today-search">Search contacts or meetings</label>
      <input
        id="today-search"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search contacts or meetings"
        className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      {normalized && <div role="region" aria-label="Search results" className="absolute right-0 top-12 z-40 max-h-[min(70vh,28rem)] w-[min(88vw,24rem)] overflow-y-auto rounded-[10px] border border-border bg-card p-2 shadow-lg">
        {contacts.isError ? <p role="alert" className="p-3 text-sm text-muted-foreground">Contacts could not be searched.</p> : null}
        {!total && !contacts.isLoading && !contacts.isError ? <p className="p-3 text-sm text-muted-foreground">No matches found.</p> : null}
        {contacts.isLoading && !total ? <p role="status" className="p-3 text-sm text-muted-foreground">Searching…</p> : null}
        {results.meetings.length > 0 && <section aria-label="Meeting results"><p className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">Meetings</p><ul>{results.meetings.map((meeting) => <li key={meeting.id}><Link to={`/meetings/${meeting.id}`} className="block rounded-md px-3 py-2.5 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><span className="block font-medium">{meeting.title}</span><span className="text-muted-foreground">{meeting.account_name} · {new Date(meeting.scheduled_at).toLocaleDateString()}</span></Link></li>)}</ul></section>}
        {results.contacts.length > 0 && <section aria-label="Contact results"><p className="px-3 py-2 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">Contacts</p><ul>{results.contacts.map((contact) => <li key={contact.id}><Link to={`/contacts/${contact.id}`} className="block rounded-md px-3 py-2.5 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><span className="block font-medium">{contact.name}</span><span className="text-muted-foreground">{[contact.role, contact.account_name].filter(Boolean).join(' · ') || 'Contact'}</span></Link></li>)}</ul></section>}
      </div>}
    </div>
  )
}

function StyleCard() {
  const style = useStyle()
  return (
    <section className="rounded-[10px] border border-border bg-card p-4 shadow-card">
      <h2 className="text-sm font-semibold">How I prep for you</h2>
      {style.isLoading ? <div role="status" className="mt-3 space-y-2"><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" /></div> : null}
      {style.isError ? <p role="alert" className="mt-2 text-sm text-muted-foreground">Your style preferences could not be loaded.</p> : null}
      {style.data && !style.data.notes.length ? <p className="mt-2 text-sm text-muted-foreground">No preferences learned yet. Your feedback helps shape future briefs.</p> : null}
      {style.data && style.data.notes.length > 0 && <ul className="mt-3 space-y-2">{style.data.notes.slice(0, 3).map((note) => <li key={note} className="rounded-md bg-secondary px-3 py-2 text-sm">{note}</li>)}</ul>}
      <Link to="/memory" className="mt-3 inline-flex min-h-11 items-center text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Change preferences</Link>
    </section>
  )
}

function MeetingCard({
  meeting,
  isHero,
  onLogNotes,
}: {
  meeting: MeetingSummary
  isHero: boolean
  onLogNotes: (meetingId: string) => void
}) {
  return (
    <article className={`rounded-[10px] border bg-card p-4 shadow-card sm:p-5 ${isHero ? 'border-2 border-primary' : 'border-border'}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">{new Date(meeting.scheduled_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })} · {meeting.account_name}</p>
          <h3 className="mt-1 text-lg font-semibold">{meeting.title}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{meeting.attendees.map((person) => `${person.name}${person.role ? ` · ${person.role}` : ''}`).join(' · ') || 'No attendees listed'}</p>
        </div>
        <div className="flex flex-wrap gap-2" aria-label={`${meeting.title} status`}>
          {meeting.brief_ready ? <Badge>Brief ready</Badge> : null}
          {meeting.open_followups > 0 ? <Badge variant="warning">{meeting.open_followups} open follow-ups</Badge> : null}
          {meeting.past_meetings > 0 ? <Badge variant="outline">{meeting.past_meetings} past meetings</Badge> : null}
          {!meeting.has_history ? <Badge variant="outline">No history yet</Badge> : null}
        </div>
      </div>
      {!meeting.has_history && <p className="mt-3 text-sm text-muted-foreground">Generic brief · no past meeting memory is available yet.</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button asChild><Link to={`/meetings/${meeting.id}`}>{meeting.brief_ready ? 'Open brief' : 'Generate brief'}</Link></Button>
        <Button type="button" variant="outline" onClick={() => onLogNotes(meeting.id)}>Log notes</Button>
      </div>
    </article>
  )
}

export function Dashboard() {
  const meetings = useMeetings()
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const [notesMeetingId, setNotesMeetingId] = useState<string>()
  const upcoming = (meetings.data ?? []).filter((meeting) => meeting.status === 'upcoming')

  return (
    <section className="space-y-6">
      <HeaderControls>
        <SearchBox meetings={meetings.data ?? []} />
        <Button asChild variant="outline" className="px-2 text-xs sm:px-4 sm:text-sm">
          <Link to="/capture"><span className="sm:hidden">Notes</span><span className="hidden sm:inline">Add meeting notes</span></Link>
        </Button>
      </HeaderControls>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-primary">Your account memory, ready before the next call</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Upcoming meetings</h1>
        </div>
        <Button onClick={() => setScheduleOpen(true)}>Schedule meeting</Button>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <section aria-label="Upcoming meetings" className="space-y-3">
          {meetings.isLoading ? <div role="status" aria-label="Loading meetings" className="space-y-3"><Skeleton className="h-36" /><Skeleton className="h-36" /></div> : null}
          {meetings.isError ? <p role="alert" className="rounded-[10px] border bg-card p-5 text-sm">Meetings could not be loaded. Refresh to try again.</p> : null}
          {!meetings.isLoading && !meetings.isError && upcoming.length === 0 ? <div className="rounded-[10px] border border-dashed bg-card px-6 py-12 text-center"><h2 className="font-semibold">No upcoming meetings</h2><p className="mt-2 text-sm text-muted-foreground">Schedule a meeting to see its prep and account context here.</p><Button className="mt-4" onClick={() => setScheduleOpen(true)}>Schedule meeting</Button></div> : null}
          {upcoming.map((meeting, index) => <MeetingCard key={meeting.id} meeting={meeting} isHero={index === 0} onLogNotes={setNotesMeetingId} />)}
        </section>

        <aside className="grid gap-4">
          <NudgeDigest />
          <StyleCard />
        </aside>
      </div>

      {scheduleOpen ? <ScheduleMeetingDialog open={scheduleOpen} onOpenChange={setScheduleOpen} /> : null}
      <Dialog open={Boolean(notesMeetingId)} onOpenChange={(open) => { if (!open) setNotesMeetingId(undefined) }}>
        {notesMeetingId ? <NotesDialog key={notesMeetingId} meetings={meetings.data ?? []} initialMeetingId={notesMeetingId} onClose={() => setNotesMeetingId(undefined)} /> : null}
      </Dialog>
    </section>
  )
}
