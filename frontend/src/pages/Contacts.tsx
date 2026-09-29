import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/http'
import { useAccounts, useContacts } from '@/api/hooks'
import { AskPanel } from '@/components/AskPanel'
import { Button } from '@/components/ui/button'

async function loadProfile(id: string) {
  const { data, error } = await api.GET('/api/contacts/{contact_id}/profile', { params: { path: { contact_id: id } } })
  if (error || !data) throw new Error('Contact profile unavailable')
  return data
}

export function Contacts() {
  const { id } = useParams()
  return id ? <ContactDetail id={id} /> : <ContactList />
}

function ContactList() {
  const [search, setSearch] = useState('')
  const [accountId, setAccountId] = useState('')
  const contacts = useContacts(accountId || undefined)
  const accounts = useAccounts()
  const visible = (contacts.data ?? []).filter((contact) => `${contact.name} ${contact.role ?? ''} ${contact.account_name ?? ''}`.toLowerCase().includes(search.toLowerCase()))
  return <section className="space-y-6">
    <header><p className="text-sm text-primary">Workspace</p><h1 className="text-3xl font-semibold">Contacts</h1><p className="mt-1 text-sm text-muted-foreground">People and context learned across your meetings.</p></header>
    <div className="flex flex-wrap gap-3"><label className="sr-only" htmlFor="contact-search">Search contacts</label><input id="contact-search" className="min-w-56 rounded-md border bg-background px-3 py-2" placeholder="Search contacts" value={search} onChange={(event) => setSearch(event.target.value)} /><label className="sr-only" htmlFor="account-filter">Filter by account</label><select id="account-filter" className="rounded-md border bg-background px-3 py-2" value={accountId} onChange={(event) => setAccountId(event.target.value)}><option value="">All accounts</option>{(accounts.data ?? []).map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></div>
    {contacts.isLoading ? <p role="status">Loading contacts…</p> : contacts.isError ? <p role="alert">Contacts could not be loaded.</p> : visible.length === 0 ? <p className="rounded-lg border border-dashed p-8 text-sm text-muted-foreground">No contacts match this search.</p> : <ul className="grid gap-3 sm:grid-cols-2">{visible.map((contact) => <li key={contact.id}><Link className="block rounded-xl border bg-card p-5 hover:border-primary" to={`/contacts/${contact.id}`}><span className="font-medium">{contact.name}</span><span className="mt-1 block text-sm text-muted-foreground">{contact.role ?? 'Contact'} · {contact.account_name ?? 'Internal'}</span><span className="mt-3 block text-xs text-muted-foreground">{contact.meetings_count} meetings · {contact.open_followups} open follow-ups</span></Link></li>)}</ul>}
  </section>
}

function ContactDetail({ id }: { id: string }) {
  const [tab, setTab] = useState('Timeline')
  const profile = useQuery({ queryKey: ['contact-profile', id], queryFn: () => loadProfile(id) })
  const client = useQueryClient()
  if (profile.isLoading) return <p role="status">Loading contact…</p>
  if (profile.isError || !profile.data) return <p role="alert">Contact profile could not be loaded.</p>
  const data = profile.data
  const refresh = async () => { await api.POST('/api/contacts/{contact_id}/patterns/refresh', { params: { path: { contact_id: id } } }); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const hide = async (factId: string) => { if (!window.confirm('Hide this memory from this app? It remains in Hindsight.')) return; await api.POST('/api/memories/{memory_id}/hide', { params: { path: { memory_id: factId } } }); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const correct = async (factId: string) => { const text = window.prompt('Enter the corrected memory'); if (!text) return; await api.POST('/api/memories/{memory_id}/correct', { params: { path: { memory_id: factId } }, body: { corrected_text: text, scope_type: 'contact', scope_id: id } }); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const patchFollowup = async (followupId: string, body: { status?: 'open' | 'done'; due_date?: string }) => { await api.PATCH('/api/commitments/{commitment_id}', { params: { path: { commitment_id: followupId } }, body }); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const deleteFollowup = async (followupId: string) => { if (!window.confirm('Delete this follow-up?')) return; await api.DELETE('/api/commitments/{commitment_id}', { params: { path: { commitment_id: followupId } } }); await client.invalidateQueries({ queryKey: ['contact-profile', id] }) }
  const tabs = ['Timeline', 'Facts', 'Follow-ups', 'Preferences']
  return <section className="space-y-7">
    <header><Link to="/contacts" className="text-sm text-primary hover:underline">← Contacts</Link><div className="mt-4 flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm text-primary">{data.account.name} · {data.contact.role ?? 'Contact'}</p><h1 className="mt-1 text-3xl font-semibold">{data.contact.name}</h1><p className="mt-2 text-sm text-muted-foreground">{data.stats.meetings} meetings · {data.stats.facts} facts · {data.stats.open_follow_ups} open follow-ups</p></div>{data.timeline[0] && <Link className="rounded-full border px-3 py-1 text-sm" to={`/meetings/${data.timeline[0].meeting_id}`}>Open latest meeting</Link>}</div></header>
    <nav aria-label="Contact profile sections" className="flex flex-wrap gap-2">{tabs.map((name) => <button key={name} type="button" aria-pressed={tab === name} onClick={() => setTab(name)} className={`rounded-full border px-3 py-1.5 text-sm ${tab === name ? 'bg-primary text-primary-foreground' : ''}`}>{name}</button>)}</nav>
    {tab === 'Timeline' && <div className="space-y-4">{data.timeline.length ? data.timeline.map((meeting) => <article key={meeting.meeting_id} className="rounded-xl border bg-card p-5"><Link className="font-medium text-primary hover:underline" to={`/meetings/${meeting.meeting_id}`}>{meeting.title} · {meeting.meeting_date}</Link><ul className="mt-3 space-y-3">{meeting.items.map((item, index) => <li key={`${item.kind}-${index}`} className="text-sm"><span className="font-medium">{item.kind.replace('_', ' ')}:</span> {item.text}<p className="mt-1 text-xs text-muted-foreground">{item.citation.label}</p></li>)}</ul></article>) : <p className="rounded-lg border border-dashed p-6 text-sm">No timeline items yet.</p>}</div>}
    {tab === 'Facts' && <div className="space-y-3">{data.facts.length ? data.facts.map((fact) => <article key={fact.id} className="rounded-lg border p-4"><p className="text-sm">{fact.text}</p><p className="mt-2 text-xs text-muted-foreground">{fact.kind} · {fact.citation.label}</p><div className="mt-3 flex gap-2"><Button variant="outline" size="sm" onClick={() => void correct(fact.id)}>Correct</Button><Button variant="outline" size="sm" onClick={() => void hide(fact.id)}>Hide</Button></div></article>) : <p className="rounded-lg border border-dashed p-6 text-sm">No visible facts yet.</p>}</div>}
    {tab === 'Follow-ups' && <div className="space-y-3">{data.follow_ups.length ? data.follow_ups.map((item) => <article key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4"><div><p className="text-sm">{item.text}</p><p className="mt-1 text-xs text-muted-foreground">{item.citation.label} · {item.due_date ?? 'No due date'} · {item.status}</p></div><div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => void patchFollowup(item.id, { status: item.status === 'open' ? 'done' : 'open' })}>{item.status === 'open' ? 'Mark done' : 'Reopen'}</Button><Button variant="outline" size="sm" onClick={() => { const due_date = window.prompt('Due date (YYYY-MM-DD)', item.due_date ?? ''); if (due_date) void patchFollowup(item.id, { due_date }) }}>Edit due date</Button><Button variant="outline" size="sm" onClick={() => void deleteFollowup(item.id)}>Delete</Button></div></article>) : <p className="rounded-lg border border-dashed p-6 text-sm">No follow-ups.</p>}</div>}
    {tab === 'Preferences' && <div className="space-y-3">{data.preferences.length ? data.preferences.map((fact) => <p key={fact.id} className="rounded-lg border p-4 text-sm">{fact.text} <span className="mt-2 block text-xs text-muted-foreground">{fact.citation.label}</span></p>) : <p className="rounded-lg border border-dashed p-6 text-sm">No preferences recorded.</p>}</div>}
    <aside className="grid gap-4 lg:grid-cols-2"><article className="rounded-xl border bg-card p-5"><h2 className="font-semibold">What I have learned</h2>{data.patterns.length ? <ul className="mt-3 space-y-3">{data.patterns.map((pattern, index) => <li key={`${pattern.text}-${index}`} className="text-sm">{pattern.text}<p className="mt-1 text-xs text-muted-foreground">{pattern.citations.map((citation) => citation.label).join(' · ')}</p></li>)}</ul> : <p className="mt-2 text-sm text-muted-foreground">No recurring patterns cached.</p>}{data.facts.length >= 3 && <Button className="mt-4" variant="outline" onClick={() => void refresh()}>Refresh</Button>}</article><article className="rounded-xl border bg-card p-5"><h2 className="font-semibold">You stay in control</h2><p className="mt-2 text-sm text-muted-foreground">Edit memory hides the original from this app’s briefs, timeline, and answers. It is not deleted from Hindsight.</p><p className="mt-2 text-sm">{data.hidden_count} hidden items</p><Button className="mt-3" variant="outline" onClick={() => { const text = window.prompt('Add a note about this contact'); if (text) void api.POST('/api/memories/notes', { body: { text, scope_type: 'contact', scope_id: id } }) }}>Add note</Button></article></aside>
    <AskPanel scopeType="contact" scopeId={id} meetingId={data.timeline[0]?.meeting_id} />
  </section>
}
