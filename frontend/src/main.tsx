import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { applyStoredUiTheme } from './theme'
import './index.css'
import App from './App.tsx'

applyStoredUiTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
