import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useContacts,
  useDemoDate,
  useMeetings,
  useStyle,
} from '@/api/hooks'
import type { MeetingSummary } from '@/api/hooks'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { NudgeDigest } from '@/components/NudgeDigest'
import { ScheduleMeetingDialog } from '@/components/ScheduleMeetingDialog'
import { HeaderControls } from '@/components/Layout'

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
}: {
  meeting: MeetingSummary
  isHero: boolean
}) {
  const customerAttendees = meeting.attendees.filter((person) => !['c_priya', 'c_arjun'].includes(person.id) && !['Priya Nair', 'Arjun Menon'].includes(person.name))
  return (
    <article className={`rounded-[10px] border bg-card p-4 shadow-card sm:p-5 ${isHero ? 'border-2 border-primary' : 'border-border'}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">{new Date(meeting.scheduled_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })} · {meeting.account_name}</p>
          <h3 className="mt-1 text-lg font-semibold">{meeting.title}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{customerAttendees.map((person) => `${person.name}${person.role ? ` (${person.role})` : ''}`).join(' · ') || 'No attendees listed'}</p>
        </div>
        <div className="flex flex-wrap gap-2" aria-label={`${meeting.title} status`}>
          {meeting.brief_ready ? <Badge>Brief ready</Badge> : null}
          {meeting.overdue_followups > 0 ? <Badge variant="warning">{meeting.overdue_followups} overdue</Badge> : null}
          {meeting.open_followups - meeting.overdue_followups > 0 ? <Badge variant="outline">{meeting.open_followups - meeting.overdue_followups} other open</Badge> : null}
          {meeting.past_meetings > 0 ? <Badge variant="outline">{meeting.past_meetings} past meetings</Badge> : null}
          {!meeting.has_history ? <Badge variant="outline">No history yet</Badge> : null}
        </div>
      </div>
      {!meeting.has_history && <p className="mt-3 text-sm text-muted-foreground">Generic brief · no past meeting memory is available yet.</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button asChild><Link to={`/meetings/${meeting.id}`}>{meeting.brief_ready ? 'Open brief' : 'Generate brief'}</Link></Button>
        <Button asChild variant="outline"><Link to={`/capture?meeting=${meeting.id}`}>Log notes</Link></Button>
      </div>
    </article>
  )
}

export function Dashboard() {
  const meetings = useMeetings()
  const demoDate = useDemoDate()
  const [scheduleOpen, setScheduleOpen] = useState(false)
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
          <p className="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-primary">TODAY</p>
          <div className="mt-1 flex flex-wrap items-center gap-2"><p className="text-sm text-muted-foreground">Your account memory, ready before the next call</p><Badge variant="outline">{demoDate.data ? new Date(`${demoDate.data}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'Demo date'}</Badge></div>
        </div>
        <Button onClick={() => setScheduleOpen(true)}>Schedule meeting</Button>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <section aria-label="Upcoming meetings" className="space-y-3">
          {meetings.isLoading ? <div role="status" aria-label="Loading meetings" className="space-y-3"><Skeleton className="h-36" /><Skeleton className="h-36" /></div> : null}
          {meetings.isError ? <p role="alert" className="rounded-[10px] border bg-card p-5 text-sm">Meetings could not be loaded. Refresh to try again.</p> : null}
          {!meetings.isLoading && !meetings.isError && upcoming.length === 0 ? <div className="rounded-[10px] border border-dashed bg-card px-6 py-12 text-center"><h2 className="font-semibold">No upcoming meetings</h2><p className="mt-2 text-sm text-muted-foreground">Schedule a meeting to see its prep and account context here.</p><Button className="mt-4" onClick={() => setScheduleOpen(true)}>Schedule meeting</Button></div> : null}
          {upcoming.map((meeting, index) => <MeetingCard key={meeting.id} meeting={meeting} isHero={index === 0} />)}
        </section>

        <aside className="grid gap-4">
          <NudgeDigest />
          <StyleCard />
        </aside>
      </div>

      {scheduleOpen ? <ScheduleMeetingDialog open={scheduleOpen} onOpenChange={setScheduleOpen} /> : null}
    </section>
  )
}
