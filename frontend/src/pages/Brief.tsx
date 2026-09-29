import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useBrief, useGenerateBrief, useSubmitFeedback, useStyle, type Brief as BriefData } from '@/api/hooks'
import type { components } from '@/api/schema'
import { HeaderControls } from '@/components/Layout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from 'sonner'

type BriefMode = components['schemas']['Brief']['mode']
type BriefItem = components['schemas']['BriefItem']
type BriefSection = components['schemas']['BriefSection']
type SectionKey = components['schemas']['SectionKey']

const SECTION_TITLES: Record<SectionKey, string> = {
  attendees: 'Attendees', where_left_off: 'Where we left off', open_commitments: 'Open commitments',
  unresolved_objections: 'Unresolved objections', personal_touchpoints: 'Personal touchpoints',
  agenda: 'Suggested agenda', watch_outs: 'Watch-outs', alerts: 'Alerts', your_questions: 'Your questions',
}

function CitationChip({ citation }: { citation: components['schemas']['Citation'] }) {
  return <Popover><PopoverTrigger asChild><button type="button" className="rounded-full border px-2.5 py-1 text-xs text-primary hover:bg-primary/5">{citation.label}</button></PopoverTrigger><PopoverContent><p className="font-medium">{citation.label}</p>{citation.quote ? <blockquote className="mt-2 border-l-2 pl-3 text-muted-foreground">“{citation.quote}”</blockquote> : <p className="mt-2 text-muted-foreground">Source meeting {citation.meeting_date ?? 'date unavailable'}.</p>}</PopoverContent></Popover>
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
  return <div className="flex flex-wrap items-center gap-1" aria-label={`Feedback for ${section.title}`}>
    <span className="mr-1 text-xs text-muted-foreground">Was this section useful?</span>
    {FEEDBACK_ACTIONS.map(([action, label]) => <Button key={action} type="button" variant="ghost" size="sm" disabled={feedback.isPending} onClick={() => void submit(action)}>{label}</Button>)}
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

function BriefSectionCard({ meetingId, briefId, section }: { meetingId: string; briefId: string; section: BriefSection }) {
  const [expanded, setExpanded] = useState(!section.collapsed)
  const collapsed = section.collapsed && !expanded
  const visibleItems = collapsed ? section.items.filter((item) => item.severity === 'critical') : section.items
  return <section className="rounded-xl border bg-card p-5 shadow-card">
    <div className="flex items-center justify-between gap-3"><h2 className="text-base font-semibold">{section.title}</h2>{section.collapsed && <Button variant="ghost" size="sm" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Collapse section' : 'Expand section'}</Button>}</div>
    {collapsed && <p className="mt-2 text-xs font-medium text-alert-critical-text">Critical items remain visible.</p>}
    <ul className="mt-3 space-y-4">{visibleItems.map((item) => <li key={item.id} className="border-t pt-3 first:border-0 first:pt-0">
      <div className="flex flex-wrap items-start gap-2"><Severity value={item.severity} /><p className="min-w-0 flex-1 text-sm leading-6">{item.text}</p></div>
      {!!item.citations.length && <div className="mt-2 flex flex-wrap gap-2">{item.citations.map((citation, i) => <CitationChip key={`${citation.label}-${i}`} citation={citation} />)}</div>}
    </li>)}</ul>
    <div data-testid={`feedback-slot-${section.key}`} className="mt-4 border-t pt-3"><FeedbackControls meetingId={meetingId} briefId={briefId} section={section} /></div>
  </section>
}

function BriefCard({ brief, mode, meetingId, hiddenSections }: { brief: BriefData | null | undefined; mode: BriefMode; meetingId: string; hiddenSections: SectionKey[] }) {
  if (!brief) return <div className="rounded-xl border border-dashed px-6 py-12 text-center"><h2 className="font-semibold">No brief yet</h2><p className="mt-2 text-sm text-muted-foreground">Generate a brief when you’re ready to prepare for this meeting.</p></div>
  if (!brief.sections.some((section) => section.items.length)) return <div className="rounded-xl border border-dashed px-6 py-12 text-center"><h2 className="font-semibold">This brief has no items yet</h2><p className="mt-2 text-sm text-muted-foreground">There is no relevant meeting context to show in {mode === 'memory' ? 'memory' : 'no-memory'} mode.</p></div>
  return <div className="space-y-4">{brief.sections.map((section) => <BriefSectionCard key={section.key} meetingId={meetingId} briefId={brief.id} section={section} />)}
    {hiddenSections.length > 0 && <section aria-label="Hidden sections" className="rounded-xl border bg-card p-5"><h2 className="font-semibold">Hidden sections</h2><div className="mt-3 space-y-2">{hiddenSections.map((key) => <HiddenSectionControls key={key} meetingId={meetingId} briefId={brief.id} section={key} />)}</div></section>}
  </div>
}

function ModePanel({ meetingId, mode, onGenerate, disabled, active, hiddenSections }: { meetingId: string; mode: BriefMode; onGenerate: (mode: BriefMode) => void; disabled: boolean; active: boolean; hiddenSections: SectionKey[] }) {
  const brief = useBrief(meetingId, mode, active)
  if (!active) return null
  return <div className="min-w-0 space-y-3">
    <div className="flex items-center justify-between"><h2 className="font-semibold">{mode === 'memory' ? 'With memory' : 'Without memory'}</h2><Badge variant="outline">{mode === 'memory' ? 'Cited context' : 'Meeting only'}</Badge></div>
    {brief.isLoading ? <div className="space-y-3" aria-label={`Loading ${mode} brief`}><Skeleton className="h-32"/><Skeleton className="h-24"/></div> : brief.isError ? <p role="alert" className="rounded-xl border p-5 text-sm">Brief could not be loaded. Refresh to try again.</p> : <BriefCard brief={brief.data} mode={mode} meetingId={meetingId} hiddenSections={hiddenSections} />}
    {brief.data && <p className="text-right text-xs text-muted-foreground">{brief.data.facts_used} facts used · {brief.data.preferences_applied.length} preferences applied</p>}
    <Button variant="outline" size="sm" disabled={disabled || brief.isLoading} onClick={() => onGenerate(mode)}>{brief.isLoading ? 'Loading brief…' : `${brief.data ? 'Regenerate' : 'Generate'} ${mode === 'memory' ? 'with' : 'without'} memory`}</Button>
  </div>
}

export function Brief() {
  const { id } = useParams<{ id: string }>()
  const [viewMode, setViewMode] = useState<'memory' | 'no_memory' | 'side_by_side'>('memory')
  const [pendingMode, setPendingMode] = useState<BriefMode>()
  const [confirmMode, setConfirmMode] = useState<BriefMode>()
  const generateMemory = useGenerateBrief(id ?? '', 'memory')
  const generateNoMemory = useGenerateBrief(id ?? '', 'no_memory')
  const memory = useBrief(id, 'memory')
  const style = useStyle(Boolean(memory.data?.preferences_applied.length))
  const hiddenSections = style.data?.hidden_sections ?? []

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

  return <section className="space-y-6">
    <HeaderControls>
      <div className="flex items-center gap-2"><span className="hidden text-xs font-medium sm:inline">Personalization</span><div aria-label="Personalization meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, ((memory.data?.facts_used ?? 0) + (memory.data?.preferences_applied.length ?? 0) * 4) * 3)} className="h-2 w-12 overflow-hidden rounded-full bg-muted sm:w-20"><div className="h-full bg-primary" style={{ width: `${Math.min(100, ((memory.data?.facts_used ?? 0) + (memory.data?.preferences_applied.length ?? 0) * 4) * 3)}%` }} /></div><span className="text-[10px] text-muted-foreground sm:text-xs">{memory.data ? `${memory.data.facts_used} facts · ${memory.data.preferences_applied.length} prefs` : 'Loading'}</span></div>
      <div role="group" aria-label="Brief mode" className="flex rounded-lg border bg-background p-0.5 text-xs">{([['memory', 'With memory'], ['no_memory', 'Without'], ['side_by_side', 'Side by side']] as const).map(([mode, label]) => <button key={mode} type="button" aria-pressed={viewMode === mode} onClick={() => setViewMode(mode)} className={`rounded-md px-2 py-1 ${viewMode === mode ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{label}</button>)}</div>
    </HeaderControls>
    <div><p className="text-sm font-medium text-primary">Preparation brief</p><h1 className="mt-1 text-2xl font-semibold">Meeting {id ?? ''}</h1><p className="mt-1 text-sm text-muted-foreground">Every memory item links back to the meeting where it was learned.</p></div>
    <div id="side-by-side" className={`grid gap-8 ${viewMode === 'side_by_side' ? 'xl:grid-cols-2' : 'grid-cols-1'}`}>
      <div id="with-memory"><ModePanel meetingId={id ?? ''} mode="memory" onGenerate={setConfirmMode} disabled={loading || !!pendingMode} active={viewMode !== 'no_memory'} hiddenSections={hiddenSections} /></div>
      <div id="without-memory"><ModePanel meetingId={id ?? ''} mode="no_memory" onGenerate={setConfirmMode} disabled={loading || !!pendingMode} active={viewMode !== 'memory'} hiddenSections={[]} /></div>
    </div>
    {confirmMode && <div role="alertdialog" aria-labelledby="regenerate-title" className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"><div className="w-full max-w-sm rounded-xl border bg-card p-6 shadow-lg"><h2 id="regenerate-title" className="font-semibold">Regenerate this brief?</h2><p className="mt-2 text-sm text-muted-foreground">This can take up to a minute. The cached {confirmMode === 'memory' ? 'memory' : 'no-memory'} brief will be replaced.</p><div className="mt-5 flex justify-end gap-2"><Button variant="outline" disabled={!!pendingMode} onClick={() => setConfirmMode(undefined)}>Cancel</Button><Button disabled={!!pendingMode || loading} onClick={() => void confirmGenerate()}>{pendingMode ? 'Generating…' : 'Confirm regenerate'}</Button></div></div></div>}
  </section>
}
