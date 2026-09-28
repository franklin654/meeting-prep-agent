import { useParams } from 'react-router-dom'

/**
 * Brief view ("/meetings/:id"): memory toggle, brief sections, citations,
 * feedback controls, Ask panel. Implemented in T17 — this is an
 * intentionally empty placeholder so routing and layout can be verified
 * before the real data lands.
 */
export function Brief() {
  const { id } = useParams<{ id: string }>()

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Brief</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Brief for meeting <span className="font-mono">{id}</span> will render
        here (T17).
      </p>
    </section>
  )
}
