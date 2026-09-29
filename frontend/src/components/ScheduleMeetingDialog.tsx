import { useState } from 'react'
import { toast } from 'sonner'
import {
  useAccounts,
  useContacts,
  useCreateAccount,
  useCreateContact,
  useHealth,
  useScheduleMeeting,
} from '@/api/hooks'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const NEW_ACCOUNT = '__new_account__'

function Field({
  label,
  value,
  onChange,
  type = 'text',
  min,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  min?: string
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium">
      {label}
      <input
        aria-label={label}
        type={type}
        min={min}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 rounded-md border border-input bg-background px-3 font-normal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
    </label>
  )
}

export function ScheduleMeetingDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const health = useHealth()
  const accounts = useAccounts()
  const [accountId, setAccountId] = useState('')
  const isNewAccount = accountId === NEW_ACCOUNT
  const contacts = useContacts(isNewAccount || !accountId ? undefined : accountId, Boolean(accountId && !isNewAccount))
  const createAccount = useCreateAccount()
  const createContact = useCreateContact()
  const scheduleMeeting = useScheduleMeeting()
  const [accountName, setAccountName] = useState('')
  const [industry, setIndustry] = useState('')
  const [title, setTitle] = useState('')
  const [scheduledAt, setScheduledAt] = useState('')
  const [selectedContactIds, setSelectedContactIds] = useState<string[]>([])
  const [addContact, setAddContact] = useState(false)
  const [contactName, setContactName] = useState('')
  const [contactRole, setContactRole] = useState('')
  const demoDate = health.data?.demo_today

  const scheduledValue = scheduledAt || (demoDate ? `${demoDate}T10:00` : '')

  const validAccount = isNewAccount ? accountName.trim().length > 0 : accountId.length > 0
  const dateIsValid = Boolean(demoDate && scheduledValue && scheduledValue.slice(0, 10) >= demoDate)
  const validContact = !addContact || contactName.trim().length > 0
  const canSubmit = Boolean(title.trim() && validAccount && dateIsValid && validContact && !scheduleMeeting.isPending)

  function toggleContact(id: string) {
    setSelectedContactIds((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id])
  }

  async function handleSubmit() {
    if (!canSubmit) return
    try {
      const account = isNewAccount
        ? await createAccount.mutateAsync({ name: accountName.trim(), industry: industry.trim() || undefined, stage: 'discovery' })
        : accounts.data?.find((row) => row.id === accountId)
      if (!account) throw new Error('Choose an account before scheduling.')
      const attendeeIds = [...selectedContactIds]
      if (addContact) {
        const contact = await createContact.mutateAsync({
          account_id: account.id,
          name: contactName.trim(),
          role: contactRole.trim() || undefined,
        })
        attendeeIds.push(contact.id)
      }
      await scheduleMeeting.mutateAsync({
        account_id: account.id,
        title: title.trim(),
        // Keep the user's demo-local calendar date; the API treats naive values as UTC.
        scheduled_at: `${scheduledValue}:00`,
        attendee_ids: attendeeIds,
      })
      toast.success('Meeting scheduled')
      onOpenChange(false)
    } catch (error) {
      toast.error('Meeting could not be scheduled', {
        description: error instanceof Error ? error.message : 'Check the account, attendees, and date.',
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Schedule a meeting</DialogTitle>
          <DialogDescription>Choose an account and a date on or after {demoDate ?? 'the demo date'}.</DialogDescription>
        </DialogHeader>

        {accounts.isLoading ? (
          <p role="status" className="rounded-md border p-4 text-sm text-muted-foreground">Loading accounts…</p>
        ) : accounts.isError ? (
          <p role="alert" className="rounded-md border p-4 text-sm">Accounts could not be loaded. Close and try again.</p>
        ) : (
          <div className="grid gap-4">
            <label className="grid gap-1.5 text-sm font-medium">
              Account
              <select
                aria-label="Account"
                value={accountId}
                onChange={(event) => { setAccountId(event.target.value); setSelectedContactIds([]) }}
                className="h-11 rounded-md border border-input bg-background px-3 font-normal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="">Choose an account</option>
                {(accounts.data ?? []).map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
                <option value={NEW_ACCOUNT}>+ Create a new account</option>
              </select>
            </label>

            {isNewAccount && <div className="grid gap-4 sm:grid-cols-2">
              <Field label="New account name" value={accountName} onChange={setAccountName} />
              <Field label="Industry (optional)" value={industry} onChange={setIndustry} />
            </div>}

            <Field label="Meeting title" value={title} onChange={setTitle} />
            <Field label="Date and time" type="datetime-local" min={demoDate ? `${demoDate}T00:00` : undefined} value={scheduledValue} onChange={setScheduledAt} />

            {accountId && !isNewAccount && (
              <fieldset className="grid gap-2">
                <legend className="text-sm font-medium">Attendees</legend>
                {contacts.isLoading ? <p role="status" className="text-sm text-muted-foreground">Loading contacts…</p> : null}
                {contacts.isError ? <p role="alert" className="text-sm">Contacts could not be loaded.</p> : null}
                {!contacts.isLoading && !contacts.isError && !contacts.data?.length ? <p className="text-sm text-muted-foreground">No contacts for this account yet. Add one below.</p> : null}
                {(contacts.data ?? []).map((contact) => (
                  <label key={contact.id} className="flex min-h-11 items-center gap-3 rounded-md border bg-card px-3 text-sm">
                    <input type="checkbox" checked={selectedContactIds.includes(contact.id)} onChange={() => toggleContact(contact.id)} className="size-4 accent-primary" />
                    <span>{contact.name}{contact.role ? <span className="text-muted-foreground"> · {contact.role}</span> : null}</span>
                  </label>
                ))}
              </fieldset>
            )}

            {isNewAccount && <p className="rounded-md bg-secondary px-3 py-2 text-sm text-muted-foreground">This first meeting will show “No history yet”. Add its attendee below.</p>}

            {accountId && <div className="space-y-3 border-t border-border pt-3">
              <label className="flex min-h-11 items-center gap-2 text-sm font-medium">
                <input type="checkbox" checked={addContact} onChange={(event) => setAddContact(event.target.checked)} className="size-4 accent-primary" />
                Add a contact to this account
              </label>
              {addContact && <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Contact name" value={contactName} onChange={setContactName} />
                <Field label="Contact role (optional)" value={contactRole} onChange={setContactRole} />
              </div>}
            </div>}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!canSubmit || accounts.isError || health.isError} onClick={() => void handleSubmit()}>
            {createAccount.isPending || createContact.isPending || scheduleMeeting.isPending ? 'Scheduling…' : 'Schedule meeting'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
