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
import ResetPasswordPage from './pages/ResetPasswordPage'
import VerifyEmailPage from './pages/VerifyEmailPage'
import EmployerRegisterPage from './pages/EmployerRegisterPage'
import EmployerSignInPage from './pages/EmployerSignInPage'
import EmployerForgotPasswordPage from './pages/EmployerForgotPasswordPage'
import EmployerResetPasswordPage from './pages/EmployerResetPasswordPage'
import EmployerVerifyEmailPage from './pages/EmployerVerifyEmailPage'

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
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/verify" element={<VerifyEmailPage />} />
            <Route path="/account" element={<AccountPage />} />
            {/* Employer accounts (ADR 0001's gate, reopened 2026-08-05): live but
                not linked from anywhere above — see EmployerRegisterPage.tsx. */}
            <Route path="/employer/register" element={<EmployerRegisterPage />} />
            <Route path="/employer/signin" element={<EmployerSignInPage />} />
            <Route path="/employer/forgot-password" element={<EmployerForgotPasswordPage />} />
            <Route path="/employer/reset-password" element={<EmployerResetPasswordPage />} />
            <Route path="/employer/verify" element={<EmployerVerifyEmailPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </SavedRolesProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
