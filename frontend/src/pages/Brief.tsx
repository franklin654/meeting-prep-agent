import { useState } from 'react'
import { MoreHorizontal, ThumbsDown, ThumbsUp } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useBrief, useGenerateBrief, useMarkPrepared, useMeetings, useSubmitFeedback, useStyle, useDemoDate, type Brief as BriefData } from '@/api/hooks'
import type { components } from '@/api/schema'
import { HeaderControls } from '@/components/Layout'
import { AskPanel } from '@/components/AskPanel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'

type BriefMode = components['schemas']['Brief']['mode']
type BriefItem = components['schemas']['BriefItem']
type BriefSection = components['schemas']['BriefSection']
type SectionKey = components['schemas']['SectionKey']

const INTERNAL_CONTACT_IDS = new Set(['c_priya', 'c_arjun'])
const INTERNAL_CONTACT_NAMES = new Set(['priya nair', 'arjun menon'])

function isInternalPerson(person: { id: string; name: string }) {
  return INTERNAL_CONTACT_IDS.has(person.id) || INTERNAL_CONTACT_NAMES.has(person.name.trim().toLocaleLowerCase())
}

function appDate(value: string) {
  return new Date(`${value.slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function overdueDays(text: string, demoDate?: string) {
  const match = text.match(/due\s+([A-Za-z]+\s+\d{1,2})/i)
  if (!match || !demoDate) return null
  const dueParsed = new Date(`${match[1]}, 2000`)
  if (Number.isNaN(dueParsed.getTime())) return null
  const year = Number(demoDate.slice(0, 4))
  const due = Date.UTC(year, dueParsed.getMonth(), dueParsed.getDate())
  const today = Date.parse(`${demoDate}T00:00:00Z`)
  return Math.max(0, Math.floor((today - due) / 86400000))
}

const SECTION_TITLES: Record<SectionKey, string> = {
  attendees: 'Attendees', where_left_off: 'Where we left off', open_commitments: 'Open commitments',
  unresolved_objections: 'Unresolved objections', personal_touchpoints: 'Personal touchpoints',
  agenda: 'Suggested agenda', watch_outs: 'Watch-outs', alerts: 'Alerts', your_questions: 'Your questions',
}

function CitationChip({ citation }: { citation: components['schemas']['Citation'] }) {
  return <Popover><PopoverTrigger asChild><button type="button" className="rounded-full border px-2.5 py-1 text-xs text-primary hover:bg-primary/5">{citation.label}</button></PopoverTrigger><PopoverContent side="bottom" sideOffset={8} collisionPadding={12}><p className="font-medium">{citation.label}</p>{citation.quote ? <blockquote className="mt-2 border-l-2 pl-3 text-muted-foreground">“{citation.quote}”</blockquote> : <p className="mt-2 text-muted-foreground">Source meeting {citation.meeting_date ?? 'date unavailable'}.</p>}</PopoverContent></Popover>
}

function Severity({ value }: { value: BriefItem['severity'] }) {
  if (value === 'info') return null
  const cls = value === 'critical' ? 'border-alert-critical/30 bg-alert-critical-soft text-alert-critical-text' : 'border-alert-warning/40 bg-alert-warning-soft text-alert-warning-text'
  return <Badge className={cls}>{value === 'critical' ? 'Critical' : 'Watch'}</Badge>
}

const FEEDBACK_ACTIONS = [
  ['up', 'Useful'], ['down', 'Not useful'], ['more', 'More'], ['less', 'Less'], ['collapsed', 'Hide next time'],
] as const
const UNDO_ACTION: Record<(typeof FEEDBACK_ACTIONS)[number][0], (typeof FEEDBACK_ACTIONS)[number][0]> = {
  up: 'down', down: 'up', more: 'less', less: 'more', collapsed: 'up',
}

function FeedbackControls({ meetingId, briefId, section }: { meetingId: string; briefId: string; section: BriefSection }) {
  const feedback = useSubmitFeedback(meetingId, briefId)
  async function submit(action: (typeof FEEDBACK_ACTIONS)[number][0], undo = false) {
    try {
      const profile = await feedback.mutateAsync({ section: section.key, action })
      if (undo) toast.success('Feedback undone', { description: profile.notes[0] ?? 'Your style preference was updated.' })
      else toast.success('Preference learned', {
        description: profile.notes[0] ?? 'The next brief will reflect this feedback.',
        action: { label: 'Undo', onClick: () => void submit(UNDO_ACTION[action], true) },
      })
    } catch {
      toast.error('Feedback was not saved', { description: 'Please try again.' })
    }
  }
  return <div className="flex items-center gap-1" aria-label={`Feedback for ${section.title}`}>
    <Button aria-label="Thumbs up: useful" title="Useful" type="button" variant="ghost" size="icon" disabled={feedback.isPending} onClick={() => void submit('up')}><ThumbsUp aria-hidden="true" className="size-4" /></Button>
    <Button aria-label="Thumbs down: not useful" title="Not useful" type="button" variant="ghost" size="icon" disabled={feedback.isPending} onClick={() => void submit('down')}><ThumbsDown aria-hidden="true" className="size-4" /></Button>
    <details className="relative"><summary aria-label="More feedback options" className="grid size-9 cursor-pointer list-none place-items-center rounded-md text-muted-foreground hover:bg-muted"><MoreHorizontal aria-hidden="true" className="size-4" /></summary><div className="absolute right-0 z-10 mt-1 grid min-w-36 rounded-md border bg-popover p-1 shadow-lg">{FEEDBACK_ACTIONS.slice(2).map(([action, label]) => <button key={action} type="button" className="rounded px-3 py-2 text-left text-xs hover:bg-muted" disabled={feedback.isPending} onClick={() => void submit(action)}>{label}</button>)}</div></details>
  </div>
}

function HiddenSectionControls({ meetingId, briefId, section }: { meetingId: string; briefId: string; section: SectionKey }) {
  const feedback = useSubmitFeedback(meetingId, briefId)
  const title = SECTION_TITLES[section]
  async function submit(action: 'up' | 'down') {
    try {
      await feedback.mutateAsync({ section, action })
      toast.success(action === 'up' ? 'Section restored' : 'Feedback saved', {
        description: action === 'up' ? `${title} will appear again in cached briefs.` : `The ${title} preference was updated.`,
      })
    } catch {
      toast.error('Feedback was not saved', { description: 'Please try again.' })
    }
  }
  return <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed px-3 py-2">
    <span className="mr-auto text-sm text-muted-foreground">{title} is hidden by your learned preferences.</span>
    <Button type="button" variant="outline" size="sm" disabled={feedback.isPending} onClick={() => void submit('down')}>Not useful · {title}</Button>
    <Button type="button" size="sm" disabled={feedback.isPending} onClick={() => void submit('up')}>Restore section</Button>
  </div>
}

function BriefSectionCard({ meetingId, briefId, section, mode }: { meetingId: string; briefId: string; section: BriefSection; mode: BriefMode }) {
  const [expanded, setExpanded] = useState(!section.collapsed)
  const [showAll, setShowAll] = useState(false)
  const collapsed = section.collapsed && !expanded
  if (!section.items.length) return null
  if (!section.items.length) return null
  const visibleItems = collapsed ? section.items.filter((item) => item.severity === 'critical') : showAll ? section.items : section.items.slice(0, 3)
  return <section className="rounded-xl border bg-card p-5 shadow-card">
    <div className="flex items-center justify-between gap-3"><div><h2 className="text-base font-semibold">{section.title}</h2>{collapsed && <p className="text-xs text-muted-foreground">Collapsed by your preferences</p>}</div><div className="flex items-center gap-1">{mode === 'memory' && <FeedbackControls meetingId={meetingId} briefId={briefId} section={section} />}{section.collapsed && <div className="flex gap-1"><Button variant="ghost" size="sm" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Collapse' : 'Expand'}</Button>{collapsed && <Button variant="outline" size="sm" onClick={() => setExpanded(true)}>Restore</Button>}</div>}</div></div>
    <ul className="mt-3 space-y-4">{visibleItems.map((item, index) => <li key={`${item.id}-${index}`} className={`border-t pt-3 first:border-0 first:pt-0 ${item.severity === 'critical' ? 'rounded-lg border-alert-critical/30 bg-alert-critical-soft p-3' : ''}`}>
      <div className="flex flex-wrap items-start gap-2">{section.key !== 'agenda' && <Severity value={item.severity} />}<p className={`min-w-0 flex-1 text-sm leading-6 ${item.severity === 'critical' ? 'font-semibold text-alert-critical-text' : ''}`}>{item.text}</p></div>
      {!!item.citations.length && <div className="mt-2 flex flex-wrap gap-2">{item.citations.map((citation, i) => <CitationChip key={`${citation.label}-${i}`} citation={citation} />)}</div>}
    </li>)}</ul>
    {!collapsed && section.items.length > 3 && <button type="button" className="mt-3 text-sm text-primary hover:underline" onClick={() => setShowAll((value) => !value)}>{showAll ? 'Show fewer' : `Show ${section.items.length - 3} more`}</button>}
  </section>
}

function BriefCard({ brief, mode, meetingId, hiddenSections, demoDate }: { brief: BriefData | null | undefined; mode: BriefMode; meetingId: string; hiddenSections: SectionKey[]; demoDate?: string }) {
  const [showMoreLists, setShowMoreLists] = useState<Record<string, boolean>>({})
  if (!brief) return <div className="rounded-xl border border-dashed px-6 py-12 text-center"><h2 className="font-semibold">No brief yet</h2><p className="mt-2 text-sm text-muted-foreground">Generate a brief when you’re ready to prepare for this meeting.</p></div>
  const youOwe = brief.you_owe ?? []
  const theyOwe = brief.they_owe ?? []
  const objections = brief.objections ?? []
  if (!brief.sections.some((section) => section.items.length) && !youOwe.length && !theyOwe.length && !objections.length && !brief.first_meeting) return <div className="rounded-xl border border-dashed px-6 py-12 text-center"><h2 className="font-semibold">This brief has no items yet</h2><p className="mt-2 text-sm text-muted-foreground">There is no relevant meeting context to show in {mode === 'memory' ? 'memory' : 'no-memory'} mode.</p></div>
  const isAttentionAlert = (item: BriefItem) => /contradiction|conflict|was not on that call|raised a .* concern/i.test(item.text)
  const attention = mode === 'memory' ? brief.sections.flatMap((section) => section.items.filter((item) => item.severity === 'critical' || isAttentionAlert(item))).sort((a, b) => Number(b.severity === 'critical') - Number(a.severity === 'critical')) : []
  const criticalOwed = mode === 'memory' ? youOwe.filter((item) => item.severity === 'critical') : []
  const hasEnrichedOwed = youOwe.length > 0 || theyOwe.length > 0
  const hasEnrichedObjections = objections.length > 0
  const sections = brief.sections.filter((section) =>
    section.key !== 'where_left_off'
    && section.key !== 'agenda'
    && section.key !== 'attendees'
    && !(hasEnrichedOwed && section.key === 'open_commitments')
    && !(hasEnrichedObjections && section.key === 'unresolved_objections'),
  )
  const where = brief.sections.find((section) => section.key === 'where_left_off')
  const agenda = brief.sections.find((section) => section.key === 'agenda')
  const displaySection = (section: BriefSection, title?: string) => {
    let items = attention.length && mode === 'memory' && !section.collapsed ? section.items.filter((item) => !attention.some((top) => top.id === item.id)) : section.items
    if (section.key === 'attendees') items = items.filter((item) => !item.contact_ids.some((contactId) => INTERNAL_CONTACT_IDS.has(contactId)) && ![...INTERNAL_CONTACT_NAMES].some((name) => item.text.toLocaleLowerCase().includes(name)))
    return <BriefSectionCard key={section.key} meetingId={meetingId} briefId={brief.id} section={{...section, title: title ?? section.title, items}} mode={mode} />
  }
  return <div className="space-y-4">
    {brief.first_meeting && <section className="rounded-xl border border-dashed p-4"><h2 className="font-semibold">No history yet</h2><p className="mt-1 text-sm text-muted-foreground">This is the first meeting we have on record for this account.</p></section>}
    {(attention.length > 0 || criticalOwed.length > 0) && <section aria-label="Needs attention" className="space-y-3 rounded-xl border bg-card p-5"><h2 className="font-semibold">Needs attention</h2>{criticalOwed.map((item, index) => <article key={`owed-critical-${index}`} className="rounded-lg border border-alert-critical/20 bg-alert-critical-soft p-3"><p className="font-semibold text-alert-critical-text">{item.text} · {item.days_overdue} days overdue</p><div className="mt-2 flex flex-wrap gap-2">{item.citations.map((citation, i) => <CitationChip key={`${citation.label}-${i}`} citation={citation} />)}</div></article>)}{attention.map((item, index) => { const critical = item.severity === 'critical'; return <article key={`${item.id}-${index}`} className={`rounded-lg border p-3 ${critical ? 'border-alert-critical/20 bg-alert-critical-soft' : 'border-alert-warning/30 bg-alert-warning-soft/50'}`}><p className={critical ? 'font-semibold text-alert-critical-text' : 'font-medium text-alert-warning-text'}>{item.text}{critical && overdueDays(item.text, demoDate) !== null && overdueDays(item.text, demoDate)! > 0 && <span className="ml-2 text-xs font-normal">{overdueDays(item.text, demoDate)} days overdue</span>}</p>{!!item.citations.length && <div className="mt-2 flex flex-wrap gap-2">{item.citations.map((citation, i) => <CitationChip key={`${citation.label}-${i}`} citation={citation} />)}</div>}</article>})}</section>}
    {where?.items.length ? displaySection(where, 'Where we left off') : null}
    {(youOwe.length > 0 || theyOwe.length > 0) && <div className="grid gap-4 md:grid-cols-2">{([["You owe them", youOwe], ["They owe you", theyOwe]] as const).map(([title, sourceRows]) => { const rows = [...sourceRows].sort((a, b) => Number(b.severity === 'critical') - Number(a.severity === 'critical') || (b.days_overdue ?? 0) - (a.days_overdue ?? 0) || (a.due_date ? new Date(`${a.due_date}T00:00:00`).getTime() : Number.MAX_SAFE_INTEGER) - (b.due_date ? new Date(`${b.due_date}T00:00:00`).getTime() : Number.MAX_SAFE_INTEGER)); const visibleRows = showMoreLists[title] ? rows : rows.slice(0, 3); return <section key={title} className="rounded-xl border bg-card p-5"><h2 className="text-base font-semibold">{title}</h2><ul className="mt-3 space-y-3">{visibleRows.map((row, index) => { const overdue = (row.days_overdue ?? 0) > 0; return <li key={`${row.text}-${index}`} className={`border-t pt-3 first:border-0 first:pt-0 ${row.severity === 'critical' ? 'rounded-md border-alert-critical/20 bg-alert-critical-soft p-3' : ''}`}><div className="flex flex-wrap items-center gap-2"><p className="flex-1 text-sm">{row.text}</p>{overdue && <Badge className="border-alert-warning/40 bg-alert-warning-soft text-alert-warning-text">Watch</Badge>}</div><p className="mt-1 text-xs text-muted-foreground">{row.owner_name}{row.due_date ? ` · due ${appDate(row.due_date)}` : ''}{overdue ? ` · ${row.days_overdue} days overdue` : ''}</p><div className="mt-2 flex flex-wrap gap-2">{row.citations.map((citation, i) => <CitationChip key={`${citation.label}-${i}`} citation={citation} />)}</div></li>})}</ul>{rows.length > 3 && <button type="button" className="mt-3 text-sm text-primary hover:underline" onClick={() => setShowMoreLists((current) => ({ ...current, [title]: !current[title] }))}>{showMoreLists[title] ? 'Show fewer' : `Show ${rows.length - 3} more`}</button>}</section>})}</div>}
    {objections.length > 0 && <section className="rounded-xl border bg-card p-5"><h2 className="text-base font-semibold">Objections to expect</h2><ol className="mt-3 space-y-3">{(showMoreLists.objections ? objections : objections.slice(0, 3)).map((objection, index) => <li key={`${objection.topic}-${index}`} className="border-t pt-3 first:border-0 first:pt-0"><p className="text-sm font-medium">{objection.topic}</p><p className="mt-1 text-xs text-muted-foreground">Raised {objection.count === 1 ? 'once' : `${objection.count} times`} · {objection.dates.map((date) => new Date(`${date}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })).join(', ')}</p><div className="mt-2 flex flex-wrap gap-2">{objection.citations.map((citation, i) => <CitationChip key={`${citation.label}-${i}`} citation={citation} />)}</div></li>)}</ol>{objections.length > 3 && <button type="button" className="mt-3 text-sm text-primary hover:underline" onClick={() => setShowMoreLists((current) => ({ ...current, objections: !current.objections }))}>{showMoreLists.objections ? 'Show fewer' : `Show ${objections.length - 3} more`}</button>}</section>}
    {agenda?.items.length ? displaySection(agenda, 'Suggested plan for the call') : null}
    {sections.map((section) => displaySection(section))}
    {hiddenSections.length > 0 && <section aria-label="Hidden sections" className="rounded-xl border bg-card p-5"><h2 className="font-semibold">Hidden sections</h2><div className="mt-3 space-y-2">{hiddenSections.map((key) => <HiddenSectionControls key={key} meetingId={meetingId} briefId={brief.id} section={key} />)}</div></section>}
  </div>
}

function BriefRail({ brief, onAskContact, meetingDate }: { brief: BriefData | null | undefined; onAskContact: (contactId: string) => void; meetingDate?: string }) {
  const contacts = brief?.contact_cards ?? []
  return <aside className="space-y-4" aria-label="Brief context">
    {contacts.filter((contact) => !INTERNAL_CONTACT_IDS.has(contact.contact_id) && !INTERNAL_CONTACT_NAMES.has(contact.name.trim().toLocaleLowerCase())).length > 0 && <section className="space-y-3 rounded-xl border bg-card p-4"><h2 className="font-semibold">Contacts</h2>{contacts.filter((contact) => !INTERNAL_CONTACT_IDS.has(contact.contact_id) && !INTERNAL_CONTACT_NAMES.has(contact.name.trim().toLocaleLowerCase())).map((contact) => <article key={contact.contact_id} className="rounded-lg border p-3"><h3 className="font-medium">{contact.name}</h3><p className="text-sm text-muted-foreground">{contact.role ?? 'Contact'} · {contact.account}</p>{contact.style && <><p className="mt-2 text-sm"><span className="font-medium">Style:</span> {contact.style}</p><div className="mt-1 flex flex-wrap gap-2">{contact.style_citations.map((citation, i) => <CitationChip key={`style-${citation.label}-${i}`} citation={citation} />)}</div></>}<p className="mt-2 text-xs text-muted-foreground">{contact.open_follow_ups} open follow-ups</p><div className="mt-2 space-y-1">{contact.recent_meetings.filter((citation) => !meetingDate || (citation.meeting_date && citation.meeting_date < meetingDate.slice(0, 10))).sort((a, b) => (b.meeting_date ?? '').localeCompare(a.meeting_date ?? '')).slice(0, 3).map((citation, i) => <div key={`${citation.label}-${i}`}><CitationChip citation={citation} /></div>)}</div><div className="mt-3 flex flex-wrap gap-2"><Button type="button" variant="outline" size="sm" onClick={() => onAskContact(contact.contact_id)}>Ask about {contact.name.split(' ')[0]}</Button><Button asChild type="button" variant="ghost" size="sm"><Link to={`/contacts/${contact.contact_id}`}>Full history</Link></Button></div></article>)}</section>}
  </aside>
}

function ModePanel({ meetingId, mode, onGenerate, disabled, active, hiddenSections, generating, demoDate }: { meetingId: string; mode: BriefMode; onGenerate: (mode: BriefMode) => void; disabled: boolean; active: boolean; hiddenSections: SectionKey[]; generating: boolean; demoDate?: string }) {
  const brief = useBrief(meetingId, mode, active)
  if (!active) return null
  return <div className="min-w-0 space-y-3">
    <div className="flex items-center justify-between"><h2 className="font-semibold">{mode === 'memory' ? 'With memory' : 'Without memory'}</h2><Badge variant="outline">{mode === 'memory' ? 'Cited context' : 'Meeting only'}</Badge></div>
    {brief.isLoading || generating ? <div className="space-y-3" aria-label={generating ? `Generating ${mode} brief` : `Loading ${mode} brief`}>{generating && <p className="text-sm text-muted-foreground">This can take about a minute.</p>}<Skeleton className="h-32"/><Skeleton className="h-24"/></div> : brief.isError ? <p role="alert" className="rounded-xl border p-5 text-sm">Brief could not be loaded. Refresh to try again.</p> : <BriefCard brief={brief.data} mode={mode} meetingId={meetingId} hiddenSections={hiddenSections} demoDate={demoDate} />}
    <Button variant="outline" size="sm" disabled={disabled || brief.isLoading || generating} onClick={() => onGenerate(mode)}>{generating ? 'Generating…' : brief.isLoading ? 'Loading brief…' : `${brief.data ? 'Regenerate' : 'Generate'} ${mode === 'memory' ? 'with' : 'without'} memory`}</Button>
  </div>
}

export function Brief() {
  const { id } = useParams<{ id: string }>()
  const [viewMode, setViewMode] = useState<'memory' | 'no_memory' | 'side_by_side'>('memory')
  const [pendingMode, setPendingMode] = useState<BriefMode>()
  const [confirmMode, setConfirmMode] = useState<BriefMode>()
  const [askOpen, setAskOpen] = useState(false)
  const [askScope, setAskScope] = useState<{ type: 'meeting' | 'contact'; id: string }>({ type: 'meeting', id: id ?? '' })
  const [preparedOverride, setPreparedOverride] = useState<boolean>()
  const generateMemory = useGenerateBrief(id ?? '', 'memory')
  const generateNoMemory = useGenerateBrief(id ?? '', 'no_memory')
  const markPrepared = useMarkPrepared(id ?? '')
  const memory = useBrief(id, 'memory')
  const noMemory = useBrief(id, 'no_memory')
  const demoDate = useDemoDate()
  const meetings = useMeetings()
  const meeting = meetings.data?.find((item) => item.id === id)
  const style = useStyle(Boolean(memory.data?.preferences_applied.length))
  const hiddenSections = style.data?.hidden_sections ?? []
  const shownBrief = viewMode === 'no_memory' ? noMemory.data : memory.data
  const memoryUsage = memory.data?.memory_used
  const isPrepared = preparedOverride ?? Boolean(meeting?.prepared)

  async function confirmGenerate() {
    if (!confirmMode || !id) return
    setPendingMode(confirmMode)
    const mode = confirmMode
    try {
      await (mode === 'memory' ? generateMemory.mutateAsync() : generateNoMemory.mutateAsync())
    } catch {
      toast.error('Brief could not be generated', { description: 'Please try again when the service is available.' })
    } finally { setPendingMode(undefined); setConfirmMode(undefined) }
  }
  const loading = memory.isLoading

  function askAboutContact(contactId: string) {
    setAskScope({ type: 'contact', id: contactId })
    setAskOpen(true)
  }

  return <section className="space-y-6">
    <HeaderControls>
      <div className="flex items-center gap-1.5"><Badge variant="outline">{memoryUsage?.facts ?? 0} facts from {memoryUsage?.meetings ?? 0} meetings</Badge><Badge variant="outline">{shownBrief?.preferences_applied.length ?? 0} preferences applied</Badge><Button type="button" size="sm" variant="outline" onClick={() => setAskOpen(true)}>Ask</Button></div>
      <div role="group" aria-label="Brief mode" className="flex flex-wrap rounded-lg border bg-background p-0.5 text-xs">{([['memory', 'With memory'], ['no_memory', 'Without'], ['side_by_side', 'Side by side']] as const).map(([mode, label]) => <button key={mode} type="button" aria-pressed={viewMode === mode} onClick={() => setViewMode(mode)} className={`min-h-11 rounded-md px-2 py-1 ${viewMode === mode ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{label}</button>)}</div>
    </HeaderControls>
    <div className="flex flex-wrap items-end justify-between gap-4"><div><nav aria-label="Breadcrumb" className="text-sm text-muted-foreground"><Link to="/" className="hover:text-foreground">Today</Link>{meeting && <> / <span>{meeting.account_name}</span></>}</nav><p className="mt-3 text-xs font-semibold uppercase tracking-wider text-primary">Preparation brief</p><h1 className="mt-1 text-2xl font-semibold">{meeting?.title ?? 'Meeting brief'}</h1>{meeting && <p className="mt-1 text-sm text-muted-foreground">{meeting.account_name} · {new Date(meeting.scheduled_at).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</p>}</div><div className="flex flex-wrap gap-2"><Button type="button" variant="outline" onClick={() => setConfirmMode(viewMode === 'no_memory' ? 'no_memory' : 'memory')}>{(viewMode === 'no_memory' ? noMemory.data : memory.data) ? 'Regenerate' : 'Generate brief'}</Button><Button type="button" variant={isPrepared ? 'outline' : 'default'} className={isPrepared ? 'border-teal-600 text-teal-700 hover:bg-teal-50' : ''} disabled={markPrepared.isPending} onClick={() => markPrepared.mutateAsync(!isPrepared).then(() => setPreparedOverride(!isPrepared)).catch(() => toast.error('Meeting preparation state could not be updated'))}>{markPrepared.isPending ? 'Saving…' : isPrepared ? 'Prepared ✓' : 'Mark as prepared'}</Button></div></div>
    {meeting?.attendees.filter((person) => !isInternalPerson(person)).length ? <div className="flex flex-wrap gap-2" aria-label="Meeting attendees">{meeting.attendees.filter((person) => !isInternalPerson(person)).map((person) => <Badge key={person.id} variant="outline">{person.name}{person.role ? ` (${person.role})` : ''}</Badge>)}</div> : null}
    <div id="brief-layout" className={`grid items-start gap-8 ${viewMode === 'side_by_side' ? 'xl:grid-cols-2' : viewMode === 'memory' ? 'xl:grid-cols-[minmax(0,1fr)_340px]' : 'grid-cols-1'}`}>
      <div id="with-memory"><ModePanel meetingId={id ?? ''} mode="memory" onGenerate={setConfirmMode} disabled={loading || !!pendingMode} active={viewMode !== 'no_memory'} hiddenSections={hiddenSections} generating={pendingMode === 'memory'} demoDate={demoDate.data} /></div>
      {viewMode === 'side_by_side' ? <div id="without-memory"><ModePanel meetingId={id ?? ''} mode="no_memory" onGenerate={setConfirmMode} disabled={loading || !!pendingMode} active hiddenSections={[]} generating={pendingMode === 'no_memory'} demoDate={demoDate.data} /></div> : viewMode === 'memory' ? <BriefRail brief={memory.data} onAskContact={askAboutContact} meetingDate={meeting?.scheduled_at} /> : <div id="without-memory"><ModePanel meetingId={id ?? ''} mode="no_memory" onGenerate={setConfirmMode} disabled={loading || !!pendingMode} active hiddenSections={[]} generating={pendingMode === 'no_memory'} demoDate={demoDate.data} /></div>}
    </div>
    {id && <AskPanel scopeType={askScope.type} scopeId={askScope.id} meetingId={id} open={askOpen} onOpenChange={setAskOpen} />}
    {confirmMode && <div role="alertdialog" aria-labelledby="regenerate-title" className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"><div className="w-full max-w-sm rounded-xl border bg-card p-6 shadow-lg"><h2 id="regenerate-title" className="font-semibold">{(confirmMode === 'memory' ? memory.data : noMemory.data) ? 'Regenerate this brief?' : 'Generate this brief?'}</h2><p className="mt-2 text-sm text-muted-foreground">This can take up to a minute. {(confirmMode === 'memory' ? memory.data : noMemory.data) ? `The cached ${confirmMode === 'memory' ? 'memory' : 'no-memory'} brief will be replaced.` : `Generate a ${confirmMode === 'memory' ? 'memory' : 'no-memory'} brief for this meeting?`}</p><div className="mt-5 flex justify-end gap-2"><Button variant="outline" disabled={!!pendingMode} onClick={() => setConfirmMode(undefined)}>Cancel</Button><Button disabled={!!pendingMode || loading} onClick={() => void confirmGenerate()}>{pendingMode ? 'Generating…' : 'Confirm regenerate'}</Button></div></div></div>}
  </section>
}
