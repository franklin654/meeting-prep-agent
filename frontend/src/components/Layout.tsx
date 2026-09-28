import { NavLink, Outlet } from 'react-router-dom'
import { cn } from 'cn'

const NAV_LINKS = [{ to: '/', label: 'Dashboard' }] as const

/**
 * Shared shell for all three screens (Dashboard, Brief, Contact timeline).
 * Per docs/technical-design.md this is the only place that renders app-wide
 * chrome; pages render only their own content via <Outlet />.
 */
export function Layout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <NavLink to="/" className="text-sm font-semibold tracking-tight">
            Meeting Prep Agent
          </NavLink>
          <nav className="flex gap-4">
            {NAV_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end
                className={({ isActive }) =>
                  cn(
                    'text-sm text-muted-foreground transition-colors hover:text-foreground',
                    isActive && 'font-medium text-foreground',
                  )
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
