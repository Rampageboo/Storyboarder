import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { applyStoredUiTheme } from './theme'
import './index.css'
import App from './App.tsx'
import { initApiBase } from './api/base'

applyStoredUiTheme()

initApiBase().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
