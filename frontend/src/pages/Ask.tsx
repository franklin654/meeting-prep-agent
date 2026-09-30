import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { useAccounts, useAskQuestion, useContacts, useMeetings, usePinAnswer, useRememberNote } from '@/api/hooks'
import type { Account, ContactSummary, MeetingSummary } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

type ScopeType = 'account' | 'contact' | 'meeting'
type Citation = { meeting_id: string | null; meeting_date: string | null; label: string; quote: string | null }
type Turn = { id: string; question: string; answer: string; grounded: boolean; citations: Citation[] }
type Scope = { type: ScopeType; id: string; name: string }
const SUGGESTIONS: Record<ScopeType, string[]> = {
  account: ['What changed recently?', 'What follow-ups are open?', 'What risks should I prepare for?'],
  contact: ['What have they said about priorities?', 'What objections have come up?', 'What do we owe them?'],
  meeting: ['What did we agree?', 'What should I follow up on?', 'What was their main concern?'],
}

export function Ask() {
  const accounts = useAccounts()
  const contacts = useContacts()
  const meetings = useMeetings()
  const ask = useAskQuestion()
  const pin = usePinAnswer()
  const remember = useRememberNote()
  const [scope, setScope] = useState<Scope>()
  const [scopeType, setScopeType] = useState<ScopeType>('account')
  const [scopeOpen, setScopeOpen] = useState(false)
  const [question, setQuestion] = useState('')
  const [note, setNote] = useState('')
  const [history, setHistory] = useState<Turn[]>([])
  const selected = useMemo(() => {
    if (scope) return scope
    const account = accounts.data?.[0]
    return account ? { type: 'account' as const, id: account.id, name: account.name } : undefined
  }, [accounts.data, scope])
  const selectedAnswer = history.at(-1)
  const meetingsById = new Map((meetings.data ?? []).map((meeting) => [meeting.id, meeting]))

  function options(type: ScopeType): Scope[] {
    if (type === 'account') return (accounts.data ?? []).map((item: Account) => ({ type, id: item.id, name: item.name }))
    if (type === 'contact') return (contacts.data ?? []).filter((item: ContactSummary) => item.account_id).map((item) => ({ type, id: item.id, name: `${item.name} · ${item.account_name}` }))
    return (meetings.data ?? []).map((item: MeetingSummary) => ({ type, id: item.id, name: `${item.title} · ${item.account_name} · ${new Date(item.scheduled_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}` }))
  }

  async function submit(value = question) {
    const trimmed = value.trim()
    if (!selected || trimmed.length < 3) return
    try {
      const response = await ask.mutateAsync({ question: trimmed, scope_type: selected.type, scope_id: selected.id, history: history.slice(-3).map(({ question: q, answer }) => ({ question: q, answer })) })
      setHistory((current) => [...current, { id: response.ask_answer_id, question: trimmed, answer: response.answer, grounded: response.grounded, citations: response.citations }])
      setQuestion('')
    } catch { toast.error('Could not answer from memory') }
  }

  function choose(item: Scope) {
    setScope(item)
    setHistory([])
    setScopeOpen(false)
  }

  return <section className="space-y-6">
    <header><p className="font-mono text-[11px] uppercase tracking-[0.08em] text-primary">MEMORY Q&A</p><p className="mt-1 text-sm text-muted-foreground">Ask a question against your meeting memory.</p></header>
    <div className="flex flex-wrap items-center gap-3"><span className="text-sm text-muted-foreground">Scope</span><Button variant="outline" aria-label={`Change scope${selected ? `: ${selected.name}` : ''}`} onClick={() => setScopeOpen(true)}>{selected ? `${selected.name} · ${selected.type}` : 'Choose a scope'}</Button></div>
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_19rem]">
      <section aria-label="Ask your memory" className="space-y-4 rounded-[10px] border bg-card p-5">
        <h2 className="font-semibold">Ask your memory</h2>
        <div aria-label="Suggested questions" className="flex flex-wrap gap-2">{SUGGESTIONS[selected?.type ?? scopeType].map((item) => <Button key={item} type="button" variant="outline" size="sm" onClick={() => void submit(item)} disabled={!selected || ask.isPending}>{item}</Button>)}</div>
        <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void submit() }}><input aria-label="Question" className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm" minLength={3} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask what you remember…"/><Button type="submit" disabled={!selected || ask.isPending || question.trim().length < 3}>{ask.isPending ? 'Thinking…' : 'Ask'}</Button></form>
        {!selected && <p className="text-sm text-muted-foreground">No scope is available yet. Add an account, contact, or meeting first.</p>}
        {ask.isError && <p role="alert" className="text-sm text-destructive">The answer could not be loaded. Please try again.</p>}
        <ol className="space-y-3">{history.map((turn) => <li key={turn.id} className="rounded-lg border p-3"><p className="text-xs font-medium text-muted-foreground">{turn.question}</p><p className="mt-2 text-sm leading-6">{turn.answer}</p>{turn.grounded && selected?.type === 'meeting' && <Button className="mt-3" size="sm" variant="outline" disabled={pin.isPending} onClick={() => pin.mutateAsync({ answerId: turn.id, meetingId: selected.id }).then(() => toast.success('Pinned to brief')).catch(() => toast.error('Could not pin answer'))}>Pin to brief</Button>}</li>)}</ol>
        <form className="flex gap-2 border-t pt-4" onSubmit={(event) => { event.preventDefault(); if (selected && note.trim().length >= 3) remember.mutate({ text: note.trim(), scope_type: selected.type, scope_id: selected.id }, { onSuccess: () => { setNote(''); toast.success('Note remembered') }, onError: () => toast.error('Note could not be remembered') }) }}><input aria-label="Remember this note" className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm" minLength={3} maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Remember this…"/><Button type="submit" variant="outline" disabled={!selected || remember.isPending || note.trim().length < 3}>{remember.isPending ? 'Saving…' : 'Remember this'}</Button></form>
      </section>
      <aside aria-label="Sources for this answer" className="rounded-[10px] border bg-card p-4"><h2 className="text-sm font-semibold">Sources for this answer</h2>{selectedAnswer && !selectedAnswer.grounded ? <p role="note" className="mt-3 rounded-md bg-secondary p-3 text-sm">Not found in memory. {selectedAnswer.answer}</p> : null}{selectedAnswer?.grounded && selectedAnswer.citations.length > 0 ? <ul className="mt-3 space-y-3">{selectedAnswer.citations.map((citation, index) => { const meeting = citation.meeting_id ? meetingsById.get(citation.meeting_id) : undefined; const label = meeting ? `${meeting.title} · ${new Date(citation.meeting_date ?? meeting.scheduled_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}` : citation.meeting_date ? `Meeting · ${new Date(citation.meeting_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}` : 'Meeting source'; return <li key={`${citation.meeting_id}-${index}`} className="rounded-md border p-3"><p className="text-xs font-medium">{citation.meeting_id ? <Link className="text-primary underline" to={`/meetings/${citation.meeting_id}`}>{label}</Link> : label}</p>{citation.quote && <blockquote className="mt-2 border-l-2 pl-3 text-sm leading-5 text-muted-foreground">“{citation.quote}”</blockquote>}</li> })}</ul> : null}{!selectedAnswer && <p className="mt-3 text-sm text-muted-foreground">Citations for the selected answer will appear here.</p>}</aside>
    </div>
    <Dialog open={scopeOpen} onOpenChange={setScopeOpen}><DialogContent><DialogHeader><DialogTitle>Change scope</DialogTitle><DialogDescription>Choose which account, contact, or meeting to ask about.</DialogDescription></DialogHeader><div role="tablist" aria-label="Scope type" className="flex gap-2">{(['account', 'contact', 'meeting'] as const).map((type) => <Button key={type} role="tab" aria-selected={scopeType === type} variant={scopeType === type ? 'default' : 'outline'} onClick={() => setScopeType(type)}>{type}</Button>)}</div><div role="listbox" aria-label={`${scopeType} scopes`} className="max-h-72 space-y-1 overflow-auto">{options(scopeType).map((item) => <button key={item.id} type="button" role="option" aria-selected={selected?.id === item.id && selected.type === item.type} className="block min-h-11 w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => choose(item)}>{item.name}</button>)}{!options(scopeType).length && <p className="p-3 text-sm text-muted-foreground">No {scopeType}s available.</p>}</div></DialogContent></Dialog>
  </section>
}
