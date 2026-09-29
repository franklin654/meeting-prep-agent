import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { routes } from './routes'
import { renderRoutes } from '@/test/renderWithProviders'

describe('routing', () => {
  it('renders the dashboard at /', () => {
    renderRoutes(routes, { route: '/' })
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
  })

  it('renders the brief route at /meetings/:id', () => {
    renderRoutes(routes, { route: '/meetings/mtg-123' })
    expect(screen.getByRole('heading', { name: 'Brief' })).toBeInTheDocument()
    expect(screen.getByText('mtg-123')).toBeInTheDocument()
  })

  it('renders the contact timeline route at /contacts/:id', () => {
    renderRoutes(routes, { route: '/contacts/con-456' })
    expect(screen.getByRole('heading', { name: 'Contact timeline' })).toBeInTheDocument()
    expect(screen.getByText('con-456')).toBeInTheDocument()
  })

  it('renders shared layout nav on every route', () => {
    renderRoutes(routes, { route: '/meetings/mtg-123' })
    expect(screen.getByRole('link', { name: 'Meeting Prep Agent' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Meetings' })).toBeInTheDocument()
  })
})
