import { createContext, useContext, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, Outlet } from 'react-router-dom'
import { cn } from '@/lib/utils'

const NAV_LINKS = [{ to: '/', label: 'Meetings' }] as const

/**
 * Global controls slot. Pages (e.g. the brief's memory toggle and
 * personalization meter) render into the top bar with <HeaderControls>.
 */
const SlotContext = createContext<HTMLElement | null>(null)

export function HeaderControls({ children }: { children: ReactNode }) {
  const slot = useContext(SlotContext)
  return slot ? createPortal(children, slot) : null
}

/**
 * Shared shell for all screens. The only place that renders app-wide chrome;
 * pages render their own content via <Outlet />.
 */
export function Layout() {
  const [slot, setSlot] = useState<HTMLElement | null>(null)

  return (
    <SlotContext.Provider value={slot}>
      <div className="min-h-screen bg-background text-foreground">
        <header className="sticky top-0 z-30 border-b border-border bg-card/90 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-6xl items-center gap-8 px-4 sm:px-6">
            <NavLink
              to="/"
              className="flex items-center gap-2 text-sm font-semibold tracking-tight"
            >
              <span
                aria-hidden
                className="grid size-6 place-items-center rounded-md bg-primary text-xs font-bold text-primary-foreground"
              >
                M
              </span>
              Meeting Prep Agent
            </NavLink>
            <nav aria-label="Main" className="flex gap-1">
              {NAV_LINKS.map((link) => (
                <NavLink
                  key={link.to}
                  to={link.to}
                  end
                  className={({ isActive }) =>
                    cn(
                      'rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
                      isActive && 'bg-accent font-medium text-foreground',
                    )
                  }
                >
                  {link.label}
                </NavLink>
              ))}
            </nav>
            <div
              ref={setSlot}
              data-testid="header-controls"
              className="ml-auto flex items-center gap-4"
            />
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
          <Outlet />
        </main>
      </div>
    </SlotContext.Provider>
  )
}
