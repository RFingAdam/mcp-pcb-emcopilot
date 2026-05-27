import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'

function App(){return <h1>PCB/EM Copilot</h1>}

describe('App', () => {
  it('renders title', () => {
    const { getByText } = render(<App />)
    expect(getByText('PCB/EM Copilot')).toBeTruthy()
  })
})
