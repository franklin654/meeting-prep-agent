export function ComingSoon({ title }: { title: string }) {
  return (
    <section className="rounded-[10px] border border-dashed border-border bg-card px-6 py-12 text-center">
      <p className="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-primary">
        In progress
      </p>
      <h1 className="mt-2 text-2xl font-semibold">{title}</h1>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
        This workspace is being built. Your saved meeting memory remains available from Today.
      </p>
    </section>
  )
}
