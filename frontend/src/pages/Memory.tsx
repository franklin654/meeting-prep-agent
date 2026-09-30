import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { useBrief, useMeetings, useMemoryOverview, useResetStyle, useUnhideMemory } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

function GrowthChart({ name, points }: { name: string; points: { meeting_id: string; meeting_title: string; meeting_date: string; fact_count: number }[] }) {
  const max = Math.max(1, ...points.map((point) => point.fact_count))
  const coords = points.map((point, index) => ({
    ...point,
    x: points.length < 2 ? 240 : 24 + (index * 432) / (points.length - 1),
    y: 148 - (point.fact_count / max) * 120,
  }))
  return <section className="rounded-[10px] border bg-card p-4">
    <h3 className="text-sm font-semibold">{name}</h3>
    <svg role="img" aria-label={`Facts known after each meeting for ${name}`} viewBox="0 0 480 180" className="mt-3 h-44 w-full overflow-visible">
      <line x1="20" y1="150" x2="460" y2="150" stroke="currentColor" className="text-border" />
      {coords.length > 1 && <polyline fill="none" stroke="currentColor" strokeWidth="3" className="text-primary" points={coords.map((point) => `${point.x},${point.y}`).join(' ')} />}
      {coords.map((point) => <g key={point.meeting_id}><circle cx={point.x} cy={point.y} r="5" fill="currentColor" className="text-primary"><title>{point.meeting_title} · {point.meeting_date}: {point.fact_count} facts</title></circle><text x={point.x} y="172" textAnchor="middle" fontSize="10" fill="currentColor" className="text-muted-foreground">{new Date(`${point.meeting_date}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</text></g>)}
    </svg>
  </section>
}

export function Memory() {
  const overview = useMemoryOverview()
  const meetings = useMeetings()
  const unhide = useUnhideMemory()
  const reset = useResetStyle()
  const [meetingId, setMeetingId] = useState('')
  const [memoryEnabled, setMemoryEnabled] = useState(true)
  const [confirmReset, setConfirmReset] = useState(false)
  const chosenMeetingId = meetings.data?.some((meeting) => meeting.id === meetingId)
    ? meetingId
    : meetings.data?.find((meeting) => meeting.brief_ready)?.id ?? meetings.data?.[0]?.id ?? ''
  const brief = useBrief(chosenMeetingId || undefined, memoryEnabled ? 'memory' : 'no_memory', Boolean(chosenMeetingId))

  if (overview.isLoading) return <section className="space-y-4" aria-label="Loading memory overview" role="status"><Skeleton className="h-20" /><Skeleton className="h-40" /><Skeleton className="h-40" /></section>
  if (overview.isError || !overview.data) return <section className="rounded-[10px] border bg-card p-5"><p role="alert" className="text-sm">Memory overview could not be loaded. Refresh to try again.</p></section>
  const data = overview.data
  const kindLabels: Record<string, string> = { deal_fact: 'Deal fact', objection: 'Objection', personal: 'Personal', competitor: 'Competitor', commitment: 'Commitment' }

  return <section className="space-y-6">
    <header><p className="font-mono text-[11px] uppercase tracking-[0.08em] text-primary">MEMORY INSPECTOR</p><p className="mt-1 text-sm text-muted-foreground">A transparent view of what this workspace has learned.</p></header>

    <section className="rounded-[10px] border bg-card p-5" aria-labelledby="brief-memory-title">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 id="brief-memory-title" className="font-semibold">Memory on / off</h2><p className="mt-1 text-sm text-muted-foreground">Compare cached briefs for a meeting. This view never generates a brief.</p></div><div className="flex gap-2" role="group" aria-label="Memory mode"><Button aria-pressed={memoryEnabled} variant={memoryEnabled ? 'default' : 'outline'} onClick={() => setMemoryEnabled(true)}>Memory on</Button><Button aria-pressed={!memoryEnabled} variant={!memoryEnabled ? 'default' : 'outline'} onClick={() => setMemoryEnabled(false)}>Memory off</Button></div></div>
      <label className="mt-4 grid max-w-xl gap-1.5 text-sm font-medium">Choose a meeting<select aria-label="Choose a meeting for cached brief" className="h-11 rounded-md border bg-background px-3" value={chosenMeetingId} onChange={(event) => setMeetingId(event.target.value)}>{(meetings.data ?? []).map((meeting) => <option key={meeting.id} value={meeting.id}>{meeting.account_name} · {meeting.title} · {new Date(meeting.scheduled_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</option>)}</select></label>
      {!meetings.isLoading && !meetings.data?.length && <p className="mt-3 text-sm text-muted-foreground">No meetings are available yet.</p>}
      {brief.isLoading && <div role="status" className="mt-4 space-y-2"><Skeleton className="h-20" /><Skeleton className="h-12" /></div>}
      {brief.isError && <p role="alert" className="mt-4 text-sm">Cached brief could not be loaded.</p>}
      {!brief.isLoading && !brief.isError && chosenMeetingId && !brief.data && <p className="mt-4 rounded-md border border-dashed p-4 text-sm text-muted-foreground">No cached brief for this meeting in {memoryEnabled ? 'with memory' : 'without memory'} mode. Open a brief to generate it if needed.</p>}
      {brief.data && <div className="mt-4 space-y-3"><ul className="space-y-3">{brief.data.sections.filter((section) => section.items.length).map((section) => <li key={section.key} className="rounded-md border p-3"><h3 className="text-sm font-semibold">{section.title}</h3><ul className="mt-2 space-y-2">{section.items.map((item) => <li key={item.id} className="text-sm"><p>{item.text}</p>{item.citations.length > 0 && <p className="mt-1 text-xs text-muted-foreground">{item.citations.map((citation) => citation.label).join(' · ')}</p>}</li>)}</ul></li>)}</ul><Button asChild variant="outline"><Link to={`/meetings/${chosenMeetingId}`}>Open a brief</Link></Button></div>}
    </section>

    <section className="rounded-[10px] border bg-card p-5"><h2 className="font-semibold">Memory bank by kind</h2><p className="mt-1 text-xs text-muted-foreground">Visible extracted facts from SQLite</p><dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">{Object.entries(kindLabels).map(([kind, label]) => <div key={kind} className="rounded-md bg-secondary p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 text-xl font-semibold">{data.facts_by_kind[kind as keyof typeof data.facts_by_kind] ?? 0}</dd></div>)}</dl>{data.hindsight_stats ? <p className="mt-3 text-xs text-muted-foreground">Hindsight bank: {data.hindsight_stats.total_nodes} nodes · {data.hindsight_stats.total_documents} documents{data.hindsight_stats.total_observations !== null ? ` · ${data.hindsight_stats.total_observations} observations` : ''}</p> : <p className="mt-3 text-xs text-muted-foreground">Hindsight bank statistics are temporarily unavailable.</p>}</section>

    <section className="space-y-3"><div><h2 className="font-semibold">Facts known after each meeting</h2><p className="mt-1 text-sm text-muted-foreground">Cumulative visible facts in completed meetings.</p></div>{data.growth.length ? data.growth.map((series) => <GrowthChart key={series.account_id} name={series.account_name} points={series.points} />) : <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">No completed meetings with account history yet.</p>}</section>

    <section className="rounded-[10px] border bg-card p-5"><h2 className="font-semibold">Hidden items <span className="text-sm font-normal text-muted-foreground">({data.hidden_item_count})</span></h2>{data.hidden_items.length ? <ul className="mt-3 space-y-2">{data.hidden_items.map((item) => <li key={`${item.target_type}-${item.target_id}`} className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"><div><p className="text-sm">{item.text}</p>{item.meeting_title && item.meeting_date && <p className="mt-1 text-xs text-muted-foreground">{item.meeting_title} · {new Date(`${item.meeting_date}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</p>}</div><Button variant="outline" size="sm" disabled={unhide.isPending} aria-label={`Unhide ${item.text}`} onClick={() => unhide.mutateAsync(item.target_id).then(() => toast.success('Item unhidden')).catch(() => toast.error('Item could not be unhidden'))}>Unhide</Button></li>)}</ul> : <p className="mt-3 text-sm text-muted-foreground">No hidden items.</p>}</section>

    <section className="rounded-[10px] border bg-card p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">Style rules</h2><p className="mt-1 text-sm text-muted-foreground">Learned from your brief feedback.</p></div><Button variant="outline" onClick={() => setConfirmReset(true)}>Reset style rules</Button></div>{data.style_rules.notes.length ? <ul className="mt-3 space-y-2">{data.style_rules.notes.map((rule) => <li key={rule} className="rounded-md bg-secondary px-3 py-2 text-sm">{rule}</li>)}</ul> : <p className="mt-3 text-sm text-muted-foreground">No style rules learned yet.</p>}</section>
    {confirmReset && <div role="alertdialog" aria-labelledby="reset-style-title" aria-describedby="reset-style-description" className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"><div className="w-full max-w-sm rounded-xl border bg-card p-6 shadow-lg"><h2 id="reset-style-title" className="font-semibold">Reset style rules?</h2><p id="reset-style-description" className="mt-2 text-sm text-muted-foreground">This clears the SQLite feedback used for your style profile.</p><div className="mt-5 flex justify-end gap-2"><Button variant="outline" onClick={() => setConfirmReset(false)}>Cancel</Button><Button disabled={reset.isPending} onClick={() => reset.mutateAsync().then(() => { setConfirmReset(false); toast.success('Style rules reset') }).catch(() => toast.error('Style rules could not be reset'))}>{reset.isPending ? 'Resetting…' : 'Confirm reset'}</Button></div></div></div>}
  </section>
}
