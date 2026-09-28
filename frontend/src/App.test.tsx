import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { routes } from './routes'

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  return render(<RouterProvider router={router} />)
}

describe('routing', () => {
  it('renders the dashboard at /', () => {
    renderAt('/')
    expect(
      screen.getByRole('heading', { name: 'Dashboard' }),
    ).toBeInTheDocument()
  })

  it('renders the brief route at /meetings/:id', () => {
    renderAt('/meetings/mtg-123')
    expect(screen.getByRole('heading', { name: 'Brief' })).toBeInTheDocument()
    expect(screen.getByText('mtg-123')).toBeInTheDocument()
  })

  it('renders the contact timeline route at /contacts/:id', () => {
    renderAt('/contacts/con-456')
    expect(
      screen.getByRole('heading', { name: 'Contact timeline' }),
    ).toBeInTheDocument()
    expect(screen.getByText('con-456')).toBeInTheDocument()
  })

  it('renders shared layout nav on every route', () => {
    renderAt('/meetings/mtg-123')
    expect(
      screen.getByRole('link', { name: 'Meeting Prep Agent' }),
    ).toBeInTheDocument()
  })
})
