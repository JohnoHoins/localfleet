import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/global.css'
import MonitorApp from './MonitorApp'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <MonitorApp />
  </StrictMode>,
)
