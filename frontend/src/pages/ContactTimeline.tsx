import { Link, useParams } from 'react-router-dom'
import { useContactTimeline } from '@/api/hooks'
import { Badge } from '@/components/ui/badge'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'

const KIND_LABELS: Record<string, string> = {
  commitment: 'Commitment', objection: 'Objection', personal: 'Personal', deal_fact: 'Deal fact', competitor: 'Competitor',
}

function LearnedDate({ date }: { date: string }) {
  const [year, month, day] = date.split('-').map(Number)
  return <time dateTime={date}>{new Date(year, month - 1, day).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</time>
}

export function ContactTimeline() {
  const { id } = useParams<{ id: string }>()
  const timeline = useContactTimeline(id)

  if (timeline.isLoading) return <section className="space-y-5"><Skeleton className="h-10 w-64"/><Skeleton className="h-24"/><Skeleton className="h-24"/><Skeleton className="h-24"/></section>
  if (timeline.isError) return <section><h1 className="text-2xl font-semibold">Contact timeline</h1><p role="alert" className="mt-5 rounded-lg border p-5 text-sm">This contact’s memory could not be loaded.</p></section>
  if (!timeline.data) return null

  const { contact, entries } = timeline.data
  return <section className="space-y-8">
    <header><Link to="/" className="text-sm text-primary hover:underline">← Meetings</Link><p className="mt-5 text-sm font-medium text-primary">Memory inspector</p><h1 className="mt-1 text-2xl font-semibold">{contact.name}</h1><p className="mt-1 text-sm text-muted-foreground">{contact.role ?? 'Contact'} · {entries.length} remembered {entries.length === 1 ? 'fact' : 'facts'}</p></header>
    {entries.length === 0 ? <div className="rounded-xl border border-dashed px-6 py-14 text-center"><h2 className="font-semibold">No memories for this contact yet</h2><p className="mt-2 text-sm text-muted-foreground">Facts learned from future meetings will appear here.</p></div> : <ol className="relative ml-2 space-y-0 border-l pl-6">
      {entries.map((entry, index) => <li key={`${entry.citation.memory_id ?? entry.citation.meeting_id ?? 'entry'}-${index}`} className="relative pb-7 last:pb-0">
        <span aria-hidden className="absolute -left-[1.9rem] top-1.5 size-3 rounded-full border-2 border-primary bg-background" />
        <article className="rounded-xl border bg-card p-5 shadow-card">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><LearnedDate date={entry.learned_on} />{entry.fact_kind && <Badge variant="outline">{KIND_LABELS[entry.fact_kind]}</Badge>}</div>
          <p className="mt-3 text-sm leading-6">{entry.text}</p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {entry.citation.meeting_id ? <Link to={`/meetings/${entry.citation.meeting_id}`} className="rounded-full border px-2.5 py-1 text-xs text-primary hover:bg-primary/5">{entry.citation.label}</Link> : <span className="rounded-full border px-2.5 py-1 text-xs">{entry.citation.label}</span>}
            {entry.citation.quote && <Popover><PopoverTrigger asChild><button type="button" className="text-xs text-muted-foreground underline underline-offset-2">Source quote</button></PopoverTrigger><PopoverContent><p className="font-medium">{entry.citation.label}</p><blockquote className="mt-2 border-l-2 pl-3 text-muted-foreground">“{entry.citation.quote}”</blockquote></PopoverContent></Popover>}
          </div>
        </article>
      </li>)}
    </ol>}
  </section>
}
