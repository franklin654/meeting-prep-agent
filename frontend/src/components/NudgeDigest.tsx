import { Link } from 'react-router-dom'
import { useNudges } from '@/api/hooks'
import { Skeleton } from '@/components/ui/skeleton'

const TONE: Record<string, string> = {
  overdue_commitment: 'border-red-200 bg-red-50 text-red-900',
  silent_contact: 'border-amber-200 bg-amber-50 text-amber-950',
  brief_ready: 'border-indigo-200 bg-indigo-50 text-indigo-950',
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
  if (nudges.isError || !nudges.data?.length) return null
  return <section aria-label="Nudge digest" className="rounded-xl border bg-card p-4 shadow-card">
    <h2 className="mb-3 text-sm font-semibold">Needs your attention</h2>
    <ul className="space-y-2">{nudges.data.map((nudge, index) => <li key={`${nudge.kind}-${nudge.link}-${index}`}>
      <Link to={nudge.link} className={`block rounded-lg border px-3 py-2.5 text-sm transition-colors hover:brightness-[0.98] ${TONE[nudge.kind]}`}>
        {nudge.text}
      </Link>
    </li>)}</ul>
  </section>
}
