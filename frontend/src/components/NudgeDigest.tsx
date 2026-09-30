import { Link } from 'react-router-dom'
import { useNudges } from '@/api/hooks'
import { Skeleton } from '@/components/ui/skeleton'

const TONE: Record<string, string> = {
  overdue_commitment: 'border-alert-critical/25 bg-alert-critical-soft text-alert-critical-text',
  they_owe_overdue: 'border-alert-warning/40 bg-alert-warning-soft text-alert-warning-text',
  no_history: 'border-primary/25 bg-primary-soft text-primary-soft-foreground',
  silent_contact: 'border-alert-warning/40 bg-alert-warning-soft text-alert-warning-text',
  brief_ready: 'border-primary/25 bg-primary-soft text-primary-soft-foreground',
}

export function NudgeDigest() {
  const nudges = useNudges()
  if (nudges.isLoading) {
    return <section aria-label="Loading nudges" className="space-y-2 rounded-xl border bg-card p-4">
      <Skeleton className="h-5 w-48" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
    </section>
  }
  if (nudges.isError) return <section aria-label="Nudge digest" role="alert" className="rounded-[10px] border bg-card p-4 text-sm text-muted-foreground">Needs your attention could not be loaded.</section>
  if (!nudges.data?.length) return <section aria-label="Nudge digest" className="rounded-[10px] border bg-card p-4 shadow-card"><h2 className="text-sm font-semibold">Needs your attention</h2><p className="mt-2 text-sm text-muted-foreground">You’re all caught up.</p></section>
  return <section aria-label="Nudge digest" className="rounded-xl border bg-card p-4 shadow-card">
    <h2 className="mb-3 text-sm font-semibold">Needs your attention</h2>
    <ul className="space-y-2">{nudges.data.map((nudge, index) => <li key={`${nudge.kind}-${nudge.link}-${index}`}>
      <Link to={nudge.link} className={`block rounded-lg border px-3 py-2.5 text-sm transition-colors hover:brightness-[0.98] ${nudge.kind === 'overdue_commitment' && !nudge.critical ? TONE.they_owe_overdue : TONE[nudge.kind]}`}>
        {nudge.text}
      </Link>
    </li>)}</ul>
  </section>
}
