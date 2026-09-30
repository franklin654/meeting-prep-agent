import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { routes } from './routes'
import { renderRoutes } from '@/test/renderWithProviders'
import { mockFetch } from '@/test/mockFetch'

describe('routing', () => {
  it('renders the dashboard at /', () => {
    renderRoutes(routes, { route: '/' })
    expect(screen.getByText('TODAY')).toBeInTheDocument()
  })

  it('renders the brief route at /meetings/:id', () => {
    renderRoutes(routes, { route: '/meetings/mtg-123' })
    expect(screen.getByRole('heading', { name: 'Meeting brief' })).toBeInTheDocument()
  })

  it('renders the contact profile route at /contacts/:id', async () => {
    mockFetch({ 'GET /api/contacts/con-456/profile': { body: { contact: { id: 'con-456', name: 'Anita Rao', role: 'CFO' }, account: { id: 'acc', name: 'FinEdge', industry: 'Finance', stage: 'evaluation' }, stats: { meetings: 0, facts: 0, open_follow_ups: 0 }, timeline: [], facts: [], follow_ups: [], preferences: [], patterns: [], hidden_count: 0 } } })
    renderRoutes(routes, { route: '/contacts/con-456' })
    expect(await screen.findByRole('heading', { name: 'Anita Rao' })).toBeInTheDocument()
  })

  it('renders shared layout nav on every route', () => {
    renderRoutes(routes, { route: '/meetings/mtg-123' })
    expect(screen.getByRole('link', { name: 'Prep Agent' })).toBeInTheDocument()
    const mainNav = within(screen.getByRole('navigation', { name: 'Main navigation' }))
    expect(mainNav.getByRole('link', { name: 'Today' })).toBeInTheDocument()
    expect(mainNav.getByRole('link', { name: 'Contacts' })).toBeInTheDocument()
    expect(mainNav.getByRole('link', { name: 'Ask' })).toBeInTheDocument()
    expect(mainNav.getByRole('link', { name: 'Capture' })).toBeInTheDocument()
    expect(mainNav.getByRole('link', { name: 'Memory' })).toBeInTheDocument()
  })

  it('registers the new shell routes', () => {
    renderRoutes(routes, { route: '/ask' })
    expect(screen.getByRole('heading', { name: 'Ask' })).toBeInTheDocument()
  })

  it('registers the Contacts list route', () => {
    renderRoutes(routes, { route: '/contacts' })
    expect(screen.getByRole('heading', { name: 'Contacts' })).toBeInTheDocument()
  })

  it('shows the signed-in identity and exposes collapsible navigation', async () => {
    mockFetch({ 'GET /api/health': { body: { status: 'ok', demo_today: '2026-09-30', ae_name: 'Priya Nair', company_name: 'Tracewise' } } })
    renderRoutes(routes, { route: '/ask' })
    await waitFor(() => expect(screen.getByText('Signed in as Priya Nair · Tracewise')).toBeInTheDocument())
    const toggle = screen.getByRole('button', { name: 'Open navigation' })
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const mobileNavigation = document.getElementById('mobile-navigation')
    expect(mobileNavigation).not.toBeNull()
    expect(within(mobileNavigation!).getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
  })
})
