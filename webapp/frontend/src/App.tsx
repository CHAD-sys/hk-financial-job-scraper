import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import JobBoardPage from './pages/JobBoardPage'
import SavedJobsPage from './pages/SavedJobsPage'
import AboutPage from './pages/AboutPage'
import PostRolePage from './pages/PostRolePage'
import LearningPage from './pages/LearningPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/jobs" element={<JobBoardPage />} />
        <Route path="/learning" element={<LearningPage />} />
        <Route path="/saved" element={<SavedJobsPage />} />
        <Route path="/post-a-role" element={<PostRolePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
