import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

import ErrorBoundary from './components/ErrorBoundary.tsx'
import { Auth0ProviderWithHistory } from './components/Auth/Auth0ProviderWithHistory'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <Auth0ProviderWithHistory>
        <App />
      </Auth0ProviderWithHistory>
    </ErrorBoundary>
  </StrictMode>,
)
