import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AuthProvider from './auth/AuthProvider'
import SavedRolesProvider from './savedRoles/SavedRolesProvider'
import LandingPage from './pages/LandingPage'
import JobBoardPage from './pages/JobBoardPage'
import SavedJobsPage from './pages/SavedJobsPage'
import AboutPage from './pages/AboutPage'
import PostRolePage from './pages/PostRolePage'
import LearningPage from './pages/LearningPage'
import SignInPage from './pages/SignInPage'
import RegisterPage from './pages/RegisterPage'
import AccountPage from './pages/AccountPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'

/**
 * AuthProvider sits inside the router because Nav — which every page renders —
 * reads it, and outside Routes because who is signed in does not change between
 * routes. SavedRolesProvider sits inside it, because which store the Saved Roles
 * come from is a function of who is signed in, and outside Routes for the same
 * reason: Nav shows the count on every page.
 *
 * No route below is protected: the board is public and accounts gate nothing
 * (docs/adr/0002). /account is the single page that needs a Seeker, and it
 * redirects itself rather than being wrapped in a guard.
 */
export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <SavedRolesProvider>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="/jobs" element={<JobBoardPage />} />
            <Route path="/learning" element={<LearningPage />} />
            <Route path="/saved" element={<SavedJobsPage />} />
            <Route path="/post-a-role" element={<PostRolePage />} />
            <Route path="/signin" element={<SignInPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/account" element={<AccountPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </SavedRolesProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
