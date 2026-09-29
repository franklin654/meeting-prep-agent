import { useState, createContext, useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import {
  BrainCircuit,
  CalendarDays,
  ClipboardPlus,
  Menu,
  MessageCircleQuestion,
  Users,
  X,
} from 'lucide-react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useHealth } from '@/api/hooks'
import { cn } from '@/lib/utils'

const NAV_LINKS = [
  { to: '/', label: 'Today', icon: CalendarDays },
  { to: '/contacts', label: 'Contacts', icon: Users },
  { to: '/ask', label: 'Ask', icon: MessageCircleQuestion },
  { to: '/capture', label: 'Capture', icon: ClipboardPlus },
  { to: '/memory', label: 'Memory', icon: BrainCircuit },
] as const

const SlotContext = createContext<HTMLElement | null>(null)

export function HeaderControls({ children }: { children: ReactNode }) {
  const slot = useContext(SlotContext)
  return slot ? createPortal(children, slot) : null
}

function pageTitle(pathname: string) {
  if (pathname.startsWith('/meetings/')) return 'Meeting brief'
  if (pathname.startsWith('/contacts/')) return 'Contacts'
  if (pathname === '/contacts') return 'Contacts'
  if (pathname === '/ask') return 'Ask'
  if (pathname === '/capture') return 'Capture notes'
  if (pathname === '/memory') return 'Memory'
  return 'Today'
}

function WorkspaceIdentity() {
  const health = useHealth()
  if (health.isLoading) {
    return <p className="text-xs text-muted-foreground" role="status">Loading workspace…</p>
  }
  if (health.isError || !health.data) {
    return <p className="text-xs text-muted-foreground" role="status">Workspace identity unavailable</p>
  }
  return (
    <p className="text-xs leading-5 text-muted-foreground">
      Signed in as {health.data.ae_name} · {health.data.company_name}
    </p>
  )
}

function Brand() {
  return (
    <Link to="/" className="flex min-w-0 items-center gap-2 text-sm font-semibold tracking-tight">
      <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
        P
      </span>
      <span>Prep Agent</span>
    </Link>
  )
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation()
  return (
    <nav aria-label="Main navigation" className="grid gap-1">
      {NAV_LINKS.map(({ to, label, icon: Icon }) => {
        const active = to === '/' ? pathname === '/' : pathname === to || pathname.startsWith(`${to}/`)
        return (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={onNavigate}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex min-h-11 items-center gap-3 rounded-md border border-transparent px-3 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              active && 'border-border bg-card font-semibold text-foreground shadow-sm',
            )}
          >
            <Icon aria-hidden size={17} strokeWidth={1.8} />
            {label}
          </NavLink>
        )
      })}
    </nav>
  )
}

export function Layout() {
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const { pathname } = useLocation()
  const title = pageTitle(pathname)

  return (
    <SlotContext.Provider value={slot}>
      <div className="min-h-screen bg-background text-foreground lg:flex">
        <aside className="hidden w-[216px] shrink-0 flex-col border-r border-border bg-secondary px-4 py-5 lg:flex">
          <Brand />
          <div className="mt-8 flex-1">
            <Navigation />
          </div>
          <div className="border-t border-border pt-4">
            <WorkspaceIdentity />
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-card/95 px-4 backdrop-blur sm:px-6 lg:px-7">
            <button
              type="button"
              className="grid size-11 shrink-0 place-items-center rounded-md border border-border hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
              aria-label={mobileNavOpen ? 'Close navigation' : 'Open navigation'}
              aria-expanded={mobileNavOpen}
              aria-controls="mobile-navigation"
              onClick={() => setMobileNavOpen((open) => !open)}
            >
              {mobileNavOpen ? <X aria-hidden size={18} /> : <Menu aria-hidden size={18} />}
            </button>
            <div className="min-w-0 flex-1">
              <p className="truncate text-base font-semibold">{title}</p>
            </div>
            <div ref={setSlot} data-testid="header-controls" className="ml-auto flex shrink-0 items-center gap-2" />
          </header>

          {mobileNavOpen && (
            <div id="mobile-navigation" className="border-b border-border bg-secondary px-4 py-3 lg:hidden">
              <Navigation onNavigate={() => setMobileNavOpen(false)} />
              <div className="mt-3 border-t border-border pt-3">
                <WorkspaceIdentity />
              </div>
            </div>
          )}

          <main className="px-4 py-6 sm:px-6 lg:px-7 lg:py-[22px]">
            <Outlet />
          </main>
        </div>
      </div>
    </SlotContext.Provider>
  )
}
