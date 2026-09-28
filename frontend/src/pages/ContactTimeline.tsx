import { useParams } from 'react-router-dom'

/**
 * Contact timeline ("/contacts/:id"): memory timeline, fact cards,
 * stakeholder map, Ask panel. Implemented in T18 — this is an
 * intentionally empty placeholder so routing and layout can be verified
 * before the real data lands.
 */
export function ContactTimeline() {
  const { id } = useParams<{ id: string }>()

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">
        Contact timeline
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Memory timeline for contact <span className="font-mono">{id}</span>{' '}
        will render here (T18).
      </p>
    </section>
  )
}
