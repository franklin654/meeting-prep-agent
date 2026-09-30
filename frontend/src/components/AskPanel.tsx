import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAskQuestion, useMeetings, usePinAnswer, useRememberNote } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

type Scope = 'meeting' | 'contact' | 'account'
type Citation = { meeting_id: string | null; label: string; quote: string | null }
type Turn = { question: string; answer: string; ask_answer_id: string; grounded: boolean; citations: Citation[] }
const SUGGESTIONS: Record<Scope, string[]> = {
  meeting: ['What did we agree?', 'What should I follow up on?', 'What was their main concern?'],
  contact: ['What have they said about priorities?', 'What objections have come up?', 'What do we owe them?'],
  account: ['What changed recently?', 'What follow-ups are open?', 'What risks should I prepare for?'],
}

export function AskPanel({ scopeType, scopeId, meetingId, open: externalOpen, onOpenChange }: { scopeType: Scope; scopeId: string; meetingId?: string; open?: boolean; onOpenChange?: (open: boolean) => void }) {
  const [internalOpen, setInternalOpen] = useState(false)
  const open = externalOpen ?? internalOpen
  const setOpen = (value: boolean) => { setInternalOpen(value); onOpenChange?.(value) }
  const [question, setQuestion] = useState('')
  const [note, setNote] = useState('')
  const [history, setHistory] = useState<Turn[]>([])
  const meetings = useMeetings()
  const ask = useAskQuestion()
  const pin = usePinAnswer()
  const remember = useRememberNote()

  async function submit(value = question) {
    const trimmed = value.trim()
    if (!trimmed) return
    try {
      const response = await ask.mutateAsync({ question: trimmed, scope_type: scopeType, scope_id: scopeId, history: history.slice(-3).map(({ question: q, answer }) => ({ question: q, answer })) })
      setHistory((items) => [...items, { ...response, question: trimmed }])
      setQuestion('')
    } catch { toast.error('Could not answer from memory') }
  }

  return <section className="rounded-xl border bg-card p-4 shadow-card" aria-label="Ask your memory">
    <div className="flex items-center justify-between"><div><h2 className="font-semibold">Ask your memory</h2><p className="text-xs text-muted-foreground">Answers use cited meeting memories.</p></div><Button variant="outline" size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Close' : 'Open Ask'}</Button></div>
    {open && <div className="mt-4 space-y-4">
      <div aria-label="Suggested questions" className="flex flex-wrap gap-2">{SUGGESTIONS[scopeType].map((item) => <Button key={item} type="button" variant="outline" size="sm" onClick={() => void submit(item)}>{item}</Button>)}</div>
      <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void submit() }}><input aria-label="Question" className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm" minLength={3} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask what you remember…"/><Button type="submit" disabled={ask.isPending || question.trim().length < 3}>{ask.isPending ? 'Thinking…' : 'Ask'}</Button></form>
      {history.map((turn) => <article key={turn.ask_answer_id} className="space-y-2 rounded-lg border p-3"><p className="text-xs font-medium text-muted-foreground">{turn.question}</p><p className="text-sm leading-6">{turn.answer}</p>{turn.citations.length > 0 && <ul className="flex flex-wrap gap-2">{turn.citations.map((citation, index) => { const meeting = meetings.data?.find((item) => item.id === citation.meeting_id); const label = meeting ? `${meeting.title} · ${new Date(meeting.scheduled_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}` : 'Meeting source'; return <li key={`${citation.label}-${index}`}>{citation.meeting_id ? <Link className="text-xs text-primary underline" to={`/meetings/${citation.meeting_id}`} title={citation.quote ?? undefined}>{label}</Link> : <span className="text-xs">{label}</span>}</li>})}</ul>}{turn.grounded && meetingId && <Button size="sm" variant="outline" disabled={pin.isPending} onClick={() => pin.mutateAsync({ answerId: turn.ask_answer_id, meetingId }).then(() => toast.success('Pinned to brief')).catch(() => toast.error('Could not pin answer'))}>Pin to brief</Button>}</article>)}
      <form className="flex gap-2 border-t pt-3" onSubmit={(event) => { event.preventDefault(); if (note.trim().length >= 3) remember.mutate({ text: note.trim(), scope_type: scopeType, scope_id: scopeId }, { onSuccess: () => { setNote(''); toast.success('Note remembered') }, onError: () => toast.error('Note could not be remembered') }) }}><input aria-label="Remember this note" className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm" minLength={3} maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Remember this…"/><Button type="submit" variant="outline" disabled={remember.isPending || note.trim().length < 3}>{remember.isPending ? 'Saving…' : 'Remember this'}</Button></form>
    </div>}
  </section>
}
