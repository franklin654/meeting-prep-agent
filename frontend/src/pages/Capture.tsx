import { useMemo, useState, type ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import {
  useDiscardCapture,
  useJob,
  useMeetings,
  usePreviewCapture,
  useSaveCapture,
} from '@/api/hooks'
import type { CaptureItem } from '@/api/hooks'
import { describeError } from '@/api/errors'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'

const MAX_TRANSCRIPT_CHARS = 200_000
const KIND_LABEL: Record<string, string> = {
  commitment: 'Commitment',
  closes: 'Closes follow-up',
  objection: 'Objection',
  personal: 'Personal',
  deal_fact: 'Deal fact',
  competitor: 'Competitor',
}
const BADGE_LABEL: Record<string, string> = {
  new: 'New',
  closes: 'Closes a follow-up',
  duplicate: 'Merged into existing',
  updates_due_date: 'Updates due date',
}
const JOB_ERROR: Record<string, string> = {
  not_found: 'The meeting or capture draft could not be found.',
  validation_error: 'The transcript or selected items are invalid. Review them and try again.',
  memory_unavailable: 'Memory temporarily unavailable.',
  llm_timeout: 'The model took too long to respond. Try again.',
  llm_invalid_output: 'The model returned an unusable result. Try again.',
  rate_limited: 'The model is busy. Wait a few seconds and try again.',
  internal_error: 'Something went wrong while saving. Try again.',
}

function itemKind(item: CaptureItem) {
  if (item.kind === 'fact' && item.fact_kind) return KIND_LABEL[item.fact_kind] ?? 'Fact'
  return KIND_LABEL[item.kind] ?? 'Fact'
}

function jobError(code: string | null | undefined) {
  return code ? JOB_ERROR[code] ?? describeError(new Error(code)) : 'Something went wrong. Try again.'
}

function Stepper({ active }: { active: 1 | 2 | 3 }) {
  const steps = ['Paste', 'Review', 'Saved']
  return (
    <ol aria-label="Capture steps" className="grid grid-cols-3 gap-2">
      {steps.map((label, index) => {
        const step = index + 1
        const current = active === step
        const complete = active > step
        return (
          <li key={label} aria-current={current ? 'step' : undefined} className={`flex min-h-11 items-center justify-center gap-2 rounded-md border px-2 text-sm ${current ? 'border-primary bg-primary-soft font-semibold text-primary-soft-foreground' : complete ? 'border-primary/30 bg-card text-foreground' : 'border-border bg-card text-muted-foreground'}`}>
            <span className="grid size-6 place-items-center rounded-full border text-xs">{complete ? '✓' : step}</span>
            {label}
          </li>
        )
      })}
    </ol>
  )
}

function ReviewItem({
  item,
  checked,
  onChange,
}: {
  item: CaptureItem
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  const badgeTone = item.badge === 'duplicate'
    ? 'border-border bg-secondary text-secondary-foreground'
    : item.badge === 'updates_due_date'
      ? 'border-alert-warning/40 bg-alert-warning-soft text-alert-warning-text'
      : item.badge === 'closes'
        ? 'border-primary/25 bg-primary-soft text-primary-soft-foreground'
        : 'border-border bg-card text-muted-foreground'
  return (
    <li className="grid gap-3 rounded-[10px] border border-border bg-card p-4 sm:grid-cols-[auto_minmax(0,1fr)]">
      <label className="flex min-h-11 items-center gap-3 sm:items-start">
        <input
          type="checkbox"
          aria-label={`Include ${item.text}`}
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          className="mt-1 size-4 accent-primary"
        />
        <span className="sr-only">Include this memory</span>
      </label>
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{itemKind(item)}</Badge>
          <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${badgeTone}`}>{BADGE_LABEL[item.badge]}</span>
        </div>
        <p className="text-sm leading-6">{item.text}</p>
        {item.owner ? <p className="text-xs text-muted-foreground">Owner: {item.owner}{item.contact ? ` · ${item.contact}` : ''}</p> : null}
        {item.due_date ? <p className="text-xs text-muted-foreground">Due {new Date(`${item.due_date}T00:00:00`).toLocaleDateString()}</p> : null}
        {item.target_commitment_id ? <p className="text-xs text-muted-foreground">Matched follow-up</p> : null}
        <blockquote className="border-l-2 border-primary/40 pl-3 text-xs leading-5 text-muted-foreground">“{item.quote}”</blockquote>
      </div>
    </li>
  )
}

export function Capture() {
  const meetings = useMeetings()
  const [meetingId, setMeetingId] = useState('')
  const [transcript, setTranscript] = useState('')
  const [fileError, setFileError] = useState<string>()
  const [formError, setFormError] = useState<string>()
  const [previewJobId, setPreviewJobId] = useState<string>()
  const [saveJobId, setSaveJobId] = useState<string>()
  const [uncheckedOverrides, setUncheckedOverrides] = useState<Record<string, boolean>>({})
  const availableMeetings = useMemo(
    () => [...(meetings.data ?? [])]
      .filter((meeting) => meeting.status === 'upcoming' || meeting.status === 'done')
      .sort((a, b) => b.scheduled_at.localeCompare(a.scheduled_at)),
    [meetings.data],
  )
  const meeting = availableMeetings.find((item) => item.id === meetingId)
  const preview = usePreviewCapture(meetingId)
  const previewJob = useJob(previewJobId)
  const draft = previewJob.data?.draft
  const save = useSaveCapture(draft?.draft_id ?? '')
  const discard = useDiscardCapture(draft?.draft_id ?? '')
  const saveJob = useJob(saveJobId)
  const saved = Boolean(saveJobId && saveJob.data?.status === 'done' && saveJob.data.learned)
  const saveFailed = saveJob.data?.status === 'failed'
  const memoryUnavailable = saveFailed && saveJob.data?.error === 'memory_unavailable'
  const reviewing = Boolean(draft && !saved)
  const activeStep: 1 | 2 | 3 = saved ? 3 : reviewing ? 2 : 1
  const previewPending = Boolean(previewJobId && !draft && previewJob.data?.status !== 'failed')
  const savePending = Boolean(saveJobId && saveJob.data?.status !== 'done' && saveJob.data?.status !== 'failed')

  const isChecked = (item: CaptureItem) => uncheckedOverrides[item.id] ?? item.checked
  const checkedItems = draft?.items.filter(isChecked) ?? []
  const newCount = checkedItems.filter((item) => item.badge === 'new').length
  const closeCount = checkedItems.filter((item) => item.badge === 'closes').length
  const mergedCount = (draft?.items ?? []).filter((item) => item.badge === 'duplicate').length

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    setFileError(undefined)
    if (!file) return
    if (!/\.(txt|md)$/i.test(file.name)) {
      setFileError('Choose a .txt or .md file. Voice notes are not supported.')
      event.target.value = ''
      return
    }
    if (file.size > MAX_TRANSCRIPT_CHARS) {
      setFileError('Files must be 200 KB or smaller.')
      event.target.value = ''
      return
    }
    setTranscript(await file.text())
  }

  async function handlePreview() {
    setFormError(undefined)
    if (!meetingId || transcript.trim().length < 50) return
    try {
      const accepted = await preview.mutateAsync(transcript.trim())
      setPreviewJobId(accepted.job_id)
      setSaveJobId(undefined)
      setUncheckedOverrides({})
    } catch (error) {
      setFormError(describeError(error))
    }
  }

  async function handleSave() {
    if (!draft) return
    setFormError(undefined)
    const uncheckedItemIds = draft.items.filter((item) => !isChecked(item)).map((item) => item.id)
    try {
      const accepted = await save.mutateAsync(uncheckedItemIds)
      setSaveJobId(accepted.job_id)
    } catch (error) {
      setFormError(describeError(error))
    }
  }

  async function handleDiscard() {
    if (!draft) return
    try {
      await discard.mutateAsync()
      setPreviewJobId(undefined)
      setSaveJobId(undefined)
      setUncheckedOverrides({})
      setFormError(undefined)
      toast.success('Capture discarded')
    } catch (error) {
      setFormError(describeError(error))
    }
  }

  function changeMeeting(value: string) {
    setMeetingId(value)
    setTranscript('')
    setFileError(undefined)
    setFormError(undefined)
    setPreviewJobId(undefined)
    setSaveJobId(undefined)
    setUncheckedOverrides({})
  }

  return (
    <section className="mx-auto max-w-4xl space-y-6">
      <header>
        <p className="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-primary">Post-meeting workflow</p>
        <h1 className="mt-1 text-2xl font-semibold">Capture notes</h1>
        <p className="mt-1 text-sm text-muted-foreground">Review what was learned before it updates your account ledger.</p>
      </header>

      <Stepper active={activeStep} />

      {activeStep === 1 && <section aria-label="Paste meeting notes" className="space-y-5 rounded-[10px] border border-border bg-card p-4 shadow-card sm:p-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-1.5 text-sm font-medium">
            Meeting
            <select aria-label="Choose meeting" value={meetingId} onChange={(event) => changeMeeting(event.target.value)} disabled={meetings.isLoading || meetings.isError} className="h-11 rounded-md border border-input bg-background px-3 font-normal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <option value="">Choose an upcoming or recent meeting</option>
              {availableMeetings.filter((item) => item.status === 'upcoming').length ? <optgroup label="Upcoming meetings">{availableMeetings.filter((item) => item.status === 'upcoming').map((item) => <option key={item.id} value={item.id}>{item.account_name} · {item.title} · {new Date(item.scheduled_at).toLocaleDateString()}</option>)}</optgroup> : null}
              {availableMeetings.filter((item) => item.status === 'done').length ? <optgroup label="Recent meetings">{availableMeetings.filter((item) => item.status === 'done').map((item) => <option key={item.id} value={item.id}>{item.account_name} · {item.title} · {new Date(item.scheduled_at).toLocaleDateString()}</option>)}</optgroup> : null}
            </select>
            {meetings.isLoading ? <span role="status" className="text-xs text-muted-foreground">Loading meetings…</span> : null}
            {meetings.isError ? <span role="alert" className="text-xs">Meetings could not be loaded.</span> : null}
            {!meetings.isLoading && !meetings.isError && !availableMeetings.length ? <span className="text-xs text-muted-foreground">No upcoming or recent meetings yet.</span> : null}
          </label>
          <label className="grid gap-1.5 text-sm font-medium">
            Upload a .txt or .md file
            <input aria-label="Upload transcript file" type="file" accept=".txt,.md,text/plain,text/markdown" onChange={(event) => void handleFile(event)} className="min-h-11 rounded-md border border-input bg-background px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-secondary file:px-2 file:py-1" />
          </label>
        </div>

        <label htmlFor="capture-transcript" className="grid gap-2 text-sm font-medium">
          Meeting transcript or notes
          <Textarea id="capture-transcript" maxLength={MAX_TRANSCRIPT_CHARS} rows={12} value={transcript} onChange={(event) => { setTranscript(event.target.value); setFileError(undefined) }} placeholder="Paste the meeting transcript…" aria-describedby="capture-length capture-file-hint" />
        </label>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <p id="capture-length">{transcript.length.toLocaleString()} / 200,000 characters · 50 minimum</p>
          <p id="capture-file-hint">Plain text only; voice notes are not supported.</p>
        </div>
        {fileError ? <p role="alert" className="text-sm text-alert-warning-text">{fileError}</p> : null}
        {formError ? <p role="alert" className="text-sm text-destructive">{formError}</p> : null}

        {previewPending && <div role="status" className="space-y-3 rounded-md border border-border bg-secondary/60 p-4"><p className="text-sm font-medium">Extracting memories — this can take about a minute.</p><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-1/2" /></div>}
        {previewJob.data?.status === 'failed' ? <p role="alert" className="rounded-md border border-destructive/30 p-3 text-sm">{jobError(previewJob.data.error)}</p> : null}
        {previewJob.isError ? <p role="alert" className="rounded-md border border-destructive/30 p-3 text-sm">{describeError(previewJob.error)}</p> : null}

        <div className="flex justify-end">
          <Button disabled={!meetingId || transcript.trim().length < 50 || transcript.length > MAX_TRANSCRIPT_CHARS || preview.isPending || previewPending} onClick={() => void handlePreview()}>
            {preview.isPending || previewPending ? 'Extracting…' : 'Extract memories'}
          </Button>
        </div>
      </section>}

      {reviewing && draft && <section aria-label="Review extracted memories" className="space-y-5">
        <div className="rounded-[10px] border border-border bg-card p-4 shadow-card sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><p className="text-sm text-muted-foreground">{meeting?.account_name ?? 'Meeting'} · {meeting?.title ?? ''}</p><h2 className="mt-1 text-lg font-semibold">Review what the agent found</h2></div>
            <Badge variant="outline">{draft.items.length} items</Badge>
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            {newCount} new{closeCount ? `, ${closeCount} closes a follow-up` : ''}{mergedCount ? `, ${mergedCount} merged into existing` : ''}.
          </p>
          <ul className="mt-4 space-y-3">
            {draft.items.map((item) => <ReviewItem key={item.id} item={item} checked={isChecked(item)} onChange={(checked) => setUncheckedOverrides((current) => ({ ...current, [item.id]: checked }))} />)}
          </ul>
          {!draft.items.length ? <p className="mt-4 rounded-md bg-secondary p-4 text-sm text-muted-foreground">No quote-verified memories were found in this transcript.</p> : null}
        </div>

        <p className="rounded-[10px] border border-alert-warning/40 bg-alert-warning-soft p-4 text-sm leading-6 text-alert-warning-text">
          Unchecking removes an item from the ledger and fact list only. The transcript is still remembered; edit the notes to leave something out.
        </p>
        {formError ? <p role="alert" className="text-sm text-destructive">{formError}</p> : null}
        {savePending && <div role="status" className="rounded-md border p-4 text-sm text-muted-foreground">Saving the selected items and remembering the transcript… <Skeleton className="mt-3 h-2 w-full" /></div>}
        {saveFailed && memoryUnavailable ? <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-alert-warning/40 bg-alert-warning-soft p-3 text-sm text-alert-warning-text"><p>Memory temporarily unavailable. Your review is safe; retrying will not re-extract it.</p><Button variant="outline" disabled={save.isPending} onClick={() => void handleSave()}>Retry</Button></div> : null}
        {saveFailed && !memoryUnavailable ? <p role="alert" className="rounded-md border border-destructive/30 p-3 text-sm">{jobError(saveJob.data?.error)}</p> : null}
        {saveJob.isError ? <p role="alert" className="rounded-md border border-destructive/30 p-3 text-sm">{describeError(saveJob.error)}</p> : null}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="outline" disabled={discard.isPending || savePending} onClick={() => void handleDiscard()}>{discard.isPending ? 'Discarding…' : 'Discard'}</Button>
          <Button disabled={save.isPending || savePending || saveJob.data?.status === 'failed'} onClick={() => void handleSave()}>{save.isPending || savePending ? 'Saving…' : 'Save to memory'}</Button>
        </div>
      </section>}

      {saved && saveJob.data?.learned && <section aria-label="Saved capture summary" className="rounded-[10px] border-2 border-primary bg-card p-5 shadow-card sm:p-7">
        <div className="flex items-center gap-3"><span aria-hidden className="grid size-10 place-items-center rounded-full bg-primary-soft font-semibold text-primary-soft-foreground">✓</span><div><p className="font-mono text-[11px] uppercase tracking-[0.08em] text-primary">Saved</p><h2 className="text-xl font-semibold">Memory updated</h2></div></div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <div className="rounded-md bg-secondary p-3 text-sm"><span className="font-semibold">{saveJob.data.learned.facts.length}</span> facts learned</div>
          <div className="rounded-md bg-secondary p-3 text-sm"><span className="font-semibold">{saveJob.data.learned.new_commitments}</span> new follow-ups</div>
          <div className="rounded-md bg-secondary p-3 text-sm"><span className="font-semibold">{saveJob.data.learned.closed_commitments}</span> follow-ups closed</div>
        </div>
        {saveJob.data.learned.facts.length ? <ul className="mt-4 list-inside list-disc space-y-1 text-sm">{saveJob.data.learned.facts.map((fact, index) => <li key={`${index}-${fact}`}>{fact}</li>)}</ul> : null}
        {saveJob.data.learned.alerts.length ? <p className="mt-3 text-sm text-alert-warning-text">{saveJob.data.learned.alerts.join(' · ')}</p> : null}
        <div className="mt-5 flex flex-wrap gap-2">
          {meeting ? <Button asChild><Link to={`/meetings/${meeting.id}`}>Open the brief</Link></Button> : null}
          {meeting?.attendees[0] ? <Button asChild variant="outline"><Link to={`/contacts/${meeting.attendees[0].id}`}>Open contact</Link></Button> : null}
          <Button variant="outline" onClick={() => changeMeeting('')}>Capture another meeting</Button>
        </div>
      </section>}
    </section>
  )
}
