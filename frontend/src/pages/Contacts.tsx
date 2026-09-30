import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/http'
import { useAccounts, useContacts } from '@/api/hooks'
import { AskPanel } from '@/components/AskPanel'
import { Button } from '@/components/ui/button'
import { MoreHorizontal } from 'lucide-react'

async function loadProfile(id: string) {
  const { data, error } = await api.GET('/api/contacts/{contact_id}/profile', { params: { path: { contact_id: id } } })
  if (error || !data) throw new Error('Contact profile unavailable')
  return data
}

function displayDate(value: string) {
  return new Date(`${value.slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function factKindLabel(kind: string) {
  const labels: Record<string, string> = { personal: 'Personal', objection: 'Objection', deal_fact: 'Deal fact', competitor: 'Competitor', commitment: 'Commitment' }
  return labels[kind] ?? kind.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
}

function SourceChip({ meetingId, label }: { meetingId: string | null; label: string }) {
  const className = 'inline-flex rounded-md border border-teal-700/30 bg-teal-50 px-2 py-1 font-mono text-xs text-teal-800 hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
  return meetingId ? <Link className={className} to={`/meetings/${meetingId}`}>{label}</Link> : <span className={className}>{label}</span>
}

function ItemActions({ name, children }: { name: string; children: ReactNode }) {
  return <details className="relative"><summary aria-label={`Actions for ${name}`} className="grid size-10 cursor-pointer list-none place-items-center rounded-md text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><MoreHorizontal aria-hidden="true" className="size-5" /></summary><div className="absolute right-0 z-10 mt-1 grid min-w-40 rounded-md border bg-popover p-1 shadow-lg">{children}</div></details>
}

export function Contacts() {
  const { id } = useParams()
  return id ? <ContactDetail id={id} /> : <ContactList />
}

function ContactList() {
  const [search, setSearch] = useState('')
  const [accountId, setAccountId] = useState('')
  const [showUnconfirmed, setShowUnconfirmed] = useState(false)
  const contacts = useContacts(accountId || undefined, true, true)
  const accounts = useAccounts()
  const unconfirmedCount = (contacts.data ?? []).filter((contact) => contact.needs_review).length
  const visible = (contacts.data ?? []).filter((contact) => (showUnconfirmed || !contact.needs_review) && `${contact.name} ${contact.role ?? ''} ${contact.account_name ?? ''}`.toLowerCase().includes(search.toLowerCase()))
  return <section className="space-y-6">
    <header><p className="font-mono text-[11px] uppercase tracking-[0.08em] text-primary">CONTACTS</p><p className="mt-1 text-sm text-muted-foreground">People and context learned across your meetings.</p></header>
    <div className="flex flex-wrap gap-3"><label className="sr-only" htmlFor="contact-search">Search contacts</label><input id="contact-search" className="min-w-56 rounded-md border bg-background px-3 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" placeholder="Search contacts" value={search} onChange={(event) => setSearch(event.target.value)} /><label className="sr-only" htmlFor="account-filter">Filter by account</label><select id="account-filter" className="rounded-md border bg-background px-3 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={accountId} onChange={(event) => setAccountId(event.target.value)}><option value="">All accounts</option>{(accounts.data ?? []).map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select><Button type="button" variant="outline" aria-pressed={showUnconfirmed} onClick={() => setShowUnconfirmed((value) => !value)}>{showUnconfirmed ? 'Hide unconfirmed' : `Show unconfirmed (${unconfirmedCount})`}</Button></div>
    {contacts.isLoading ? <p role="status">Loading contacts…</p> : contacts.isError ? <p role="alert">Contacts could not be loaded.</p> : visible.length === 0 ? <p className="rounded-lg border border-dashed p-8 text-sm text-muted-foreground">No contacts match this search.</p> : <ul className="grid gap-3 sm:grid-cols-2">{visible.map((contact) => <li key={contact.id}><Link className="block rounded-xl border bg-card p-5 hover:border-primary" to={`/contacts/${contact.id}`}><span className="font-medium">{contact.name}</span>{contact.needs_review && <span className="ml-2 rounded-full border px-2 py-0.5 text-xs text-muted-foreground">Unconfirmed</span>}<span className="mt-1 block text-sm text-muted-foreground">{contact.role ?? 'Contact'} · {contact.account_name}</span><span className="mt-3 block text-xs text-muted-foreground">{contact.meetings_count} meetings · {contact.open_followups} open follow-ups</span></Link></li>)}</ul>}
  </section>
}

function ContactDetail({ id }: { id: string }) {
  const [tab, setTab] = useState('Timeline')
  const [patternMessage, setPatternMessage] = useState('')
  const profile = useQuery({ queryKey: ['contact-profile', id], queryFn: () => loadProfile(id) })
  const client = useQueryClient()
  if (profile.isLoading) return <p role="status">Loading contact…</p>
  if (profile.isError || !profile.data) return <p role="alert">Contact profile could not be loaded.</p>
  const data = profile.data
  const distinctFactMeetings = new Set(data.facts.map((fact) => fact.citation.meeting_id).filter(Boolean)).size
  const refresh = async () => { const { data: result, error } = await api.POST('/api/contacts/{contact_id}/patterns/refresh', { params: { path: { contact_id: id } } }); if (error) { setPatternMessage('Patterns could not be refreshed.'); return } setPatternMessage(result?.reason ?? ''); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const confirmContact = async () => {
    const name = window.prompt('Confirm contact name', data.contact.name)
    if (!name?.trim()) return
    const role = window.prompt('Confirm contact role', data.contact.role ?? '')
    if (role === null) return
    const { error } = await api.PATCH('/api/contacts/{contact_id}', {
      params: { path: { contact_id: id } },
      body: { name: name.trim(), role: role.trim() || null },
    })
    if (error) return
    await client.invalidateQueries({ queryKey: ['contact-profile', id] })
    await client.invalidateQueries({ queryKey: ['contacts'] })
  }
  const hide = async (factId: string) => { if (!window.confirm('Hide this memory from this app? It remains in Hindsight.')) return; await api.POST('/api/memories/{memory_id}/hide', { params: { path: { memory_id: factId } } }); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const correct = async (factId: string) => { const text = window.prompt('Enter the corrected memory'); if (!text) return; await api.POST('/api/memories/{memory_id}/correct', { params: { path: { memory_id: factId } }, body: { corrected_text: text, scope_type: 'contact', scope_id: id } }); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const patchFollowup = async (followupId: string, body: { status?: 'open' | 'done'; due_date?: string }) => { await api.PATCH('/api/commitments/{commitment_id}', { params: { path: { commitment_id: followupId } }, body }); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const deleteFollowup = async (followupId: string) => { if (!window.confirm('Delete this follow-up?')) return; await api.DELETE('/api/commitments/{commitment_id}', { params: { path: { commitment_id: followupId } } }); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const tabs = ['Timeline', 'Facts', 'Follow-ups', 'Preferences']
  return <section className="space-y-7">
    <header><Link to="/contacts" className="text-sm text-primary hover:underline">← Contacts</Link><div className="mt-4 flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm text-primary">{data.account.name} · {data.contact.role ?? 'Contact'}</p><h1 className="mt-1 text-3xl font-semibold">{data.contact.name}{data.contact.needs_review && <span className="ml-2 rounded-full border px-2 py-1 align-middle text-xs text-muted-foreground">Unconfirmed</span>}</h1><p className="mt-2 text-sm text-muted-foreground">{data.stats.meetings} meetings · {data.stats.facts} facts · {data.stats.open_follow_ups} open follow-ups</p>{data.contact.needs_review && <Button className="mt-3" variant="outline" onClick={() => void confirmContact()}>Confirm contact</Button>}</div>{data.timeline[0] && <Link className="rounded-full border px-3 py-1 text-sm" to={`/meetings/${data.timeline[0].meeting_id}`}>Open latest meeting</Link>}</div></header>
    <nav aria-label="Contact profile sections" className="flex flex-wrap gap-2">{tabs.map((name) => <button key={name} type="button" aria-pressed={tab === name} onClick={() => setTab(name)} className={`min-h-11 rounded-full border px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${tab === name ? 'bg-primary text-primary-foreground' : ''}`}>{name}</button>)}</nav>
    {tab === 'Timeline' && <div className="space-y-4">{data.timeline.length ? data.timeline.map((meeting) => <article key={meeting.meeting_id} className="rounded-xl border bg-card p-5"><h2 className="font-medium"><Link className="text-primary hover:underline" to={`/meetings/${meeting.meeting_id}`}>{meeting.title} · {displayDate(meeting.meeting_date)}</Link></h2><ul className="mt-3 space-y-3">{meeting.items.map((item, index) => <li key={`${item.kind}-${index}`} className="text-sm"><span className="mr-2 inline-flex rounded-full border px-2 py-0.5 text-xs">{factKindLabel(item.kind)}</span>{item.text}<div className="mt-2"><SourceChip meetingId={item.citation.meeting_id} label={item.citation.label} /></div></li>)}</ul></article>) : <p className="rounded-lg border border-dashed p-6 text-sm">No timeline items yet.</p>}</div>}
    {tab === 'Facts' && <div className="space-y-3">{data.facts.length ? data.facts.map((fact) => <article key={fact.id} className="flex items-start justify-between gap-3 rounded-lg border p-4"><div><p className="text-sm">{fact.text}</p><p className="mt-2 text-xs text-muted-foreground"><span className="mr-2 rounded-full border px-2 py-0.5">{factKindLabel(fact.kind)}</span>{fact.learned_on && displayDate(fact.learned_on)}</p><div className="mt-2"><SourceChip meetingId={fact.citation.meeting_id} label={fact.citation.label} /></div></div><ItemActions name={fact.text}><button type="button" className="rounded px-3 py-2 text-left text-sm hover:bg-muted" onClick={() => void correct(fact.id)}>Correct</button><button type="button" className="rounded px-3 py-2 text-left text-sm hover:bg-muted" onClick={() => void hide(fact.id)}>Hide</button></ItemActions></article>) : <p className="rounded-lg border border-dashed p-6 text-sm">No visible facts yet.</p>}</div>}
    {tab === 'Follow-ups' && <div className="space-y-3">{data.follow_ups.length ? data.follow_ups.map((item) => <article key={item.id} className="flex items-start justify-between gap-3 rounded-lg border p-4"><div><p className="text-sm">{item.text}</p><p className="mt-1 text-xs text-muted-foreground">{item.due_date ? displayDate(item.due_date) : 'No due date'} · {item.status}</p><div className="mt-2"><SourceChip meetingId={item.citation.meeting_id} label={item.citation.label} /></div></div><ItemActions name={item.text}><button type="button" className="rounded px-3 py-2 text-left text-sm hover:bg-muted" onClick={() => void patchFollowup(item.id, { status: item.status === 'open' ? 'done' : 'open' })}>{item.status === 'open' ? 'Mark done' : 'Reopen'}</button><button type="button" className="rounded px-3 py-2 text-left text-sm hover:bg-muted" onClick={() => { const due_date = window.prompt('Due date (YYYY-MM-DD)', item.due_date ?? ''); if (due_date) void patchFollowup(item.id, { due_date }) }}>Edit due date</button><button type="button" className="rounded px-3 py-2 text-left text-sm text-destructive hover:bg-muted" onClick={() => void deleteFollowup(item.id)}>Delete</button></ItemActions></article>) : <p className="rounded-lg border border-dashed p-6 text-sm">No follow-ups.</p>}</div>}
    {tab === 'Preferences' && <div className="space-y-3">{data.preferences.length ? data.preferences.map((fact) => <article key={fact.id} className="rounded-lg border p-4 text-sm"><p>{fact.text}</p><div className="mt-2"><SourceChip meetingId={fact.citation.meeting_id} label={fact.citation.label} /></div></article>) : <p className="rounded-lg border border-dashed p-6 text-sm">No preferences recorded.</p>}</div>}
    <aside className={`grid gap-4 ${data.patterns.length ? 'lg:grid-cols-2' : ''}`}>
      {data.patterns.length > 0 && <article className="rounded-xl border bg-card p-5"><h2 className="font-semibold">What I have learned</h2><ul className="mt-3 space-y-3">{data.patterns.map((pattern, index) => <li key={`${pattern.text}-${index}`} className="text-sm">{pattern.text}<div className="mt-2 flex flex-wrap gap-2">{pattern.citations.map((citation, citationIndex) => <SourceChip key={`${citation.label}-${citationIndex}`} meetingId={citation.meeting_id} label={citation.label} />)}</div></li>)}</ul></article>}
      <article className="rounded-xl border bg-card p-5"><h2 className="font-semibold">You stay in control</h2><p className="mt-2 text-sm text-muted-foreground">Edit memory hides the original from this app’s briefs, timeline, and answers. It is not deleted from Hindsight.</p><p className="mt-2 text-sm">{data.hidden_count} hidden items</p><div className="mt-3 flex items-center gap-3"><Button variant="ghost" size="sm" className="h-auto px-0 py-1 text-primary underline underline-offset-4" aria-label="Refresh patterns" disabled={distinctFactMeetings < 2} title={distinctFactMeetings < 2 ? 'Needs facts from at least 2 meetings' : undefined} onClick={() => void refresh()}>Refresh</Button><Button variant="outline" onClick={() => { const text = window.prompt('Add a note about this contact'); if (text) void api.POST('/api/memories/notes', { body: { text, scope_type: 'contact', scope_id: id } }) }}>Add note</Button></div>{patternMessage && <p role="status" className="mt-2 text-sm text-muted-foreground">{patternMessage}</p>}</article>
    </aside>
    <AskPanel scopeType="contact" scopeId={id} meetingId={data.timeline[0]?.meeting_id} />
  </section>
}
