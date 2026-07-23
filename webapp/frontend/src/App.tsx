import { Suspense, lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'

// Route-level code splitting: each page ships as its own chunk instead of
// one bundle for the whole app, so a landing-page visitor never downloads
// the job board's filter UI, and vice versa.
const LandingPage = lazy(() => import('./pages/LandingPage'))
const JobBoardPage = lazy(() => import('./pages/JobBoardPage'))
const SavedJobsPage = lazy(() => import('./pages/SavedJobsPage'))
const AboutPage = lazy(() => import('./pages/AboutPage'))

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={null}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/jobs" element={<JobBoardPage />} />
          <Route path="/saved" element={<SavedJobsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
