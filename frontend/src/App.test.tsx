import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { routes } from './routes'
import { renderRoutes } from '@/test/renderWithProviders'
import { mockFetch } from '@/test/mockFetch'

describe('routing', () => {
  it('renders the dashboard at /', () => {
    renderRoutes(routes, { route: '/' })
    expect(screen.getByRole('heading', { name: 'Meetings' })).toBeInTheDocument()
  })

  it('renders the brief route at /meetings/:id', () => {
    renderRoutes(routes, { route: '/meetings/mtg-123' })
    expect(screen.getByRole('heading', { name: 'Meeting mtg-123' })).toBeInTheDocument()
  })

  it('renders the contact timeline route at /contacts/:id', async () => {
    mockFetch({ 'GET /api/contacts/con-456/timeline': { body: { contact: { id: 'con-456', name: 'Anita Rao', role: 'CFO' }, entries: [] } } })
    renderRoutes(routes, { route: '/contacts/con-456' })
    expect(await screen.findByRole('heading', { name: 'Anita Rao' })).toBeInTheDocument()
  })

  it('renders shared layout nav on every route', () => {
    renderRoutes(routes, { route: '/meetings/mtg-123' })
    expect(screen.getByRole('link', { name: 'Meeting Prep Agent' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Meetings' })).toBeInTheDocument()
  })
})
