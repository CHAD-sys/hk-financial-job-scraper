import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AuthProvider from './auth/AuthProvider'
import EmployerAuthProvider from './auth/EmployerAuthProvider'
import SavedRolesProvider from './savedRoles/SavedRolesProvider'
import LandingPage from './pages/LandingPage'
import JobBoardPage from './pages/JobBoardPage'
import SavedJobsPage from './pages/SavedJobsPage'
import AboutPage from './pages/AboutPage'
import PostRolePage from './pages/PostRolePage'
import LearningPage from './pages/LearningPage'
import SignInChooserPage from './pages/SignInChooserPage'
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
 * AuthProvider and EmployerAuthProvider both sit inside the router (Nav reads
 * both) and outside Routes (who is signed in does not change between routes).
 * Siblings, not nested — the two identities are independent (docs/adr/0001)
 * and neither is a special case of the other. SavedRolesProvider sits inside
 * AuthProvider only, because which store Saved Roles come from is a function
 * of the Seeker, not the Employer.
 *
 * Almost every route below is unprotected: the board is public and accounts
 * gate nothing for a Seeker (docs/adr/0002). /account (Seeker) and
 * /post-a-role (Employer, as of the Employer sign-in surfacing this file's
 * own history records) are the two pages that need someone signed in, and
 * each redirects itself rather than being wrapped in a guard component — see
 * AccountPage.tsx and PostRolePage.tsx.
 *
 * Nav's "Sign in" points at /get-started, not directly at /signin — see
 * SignInChooserPage.tsx for why a chooser sits in front of both sign-in
 * forms now that there are two account kinds to choose between.
 */
export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <EmployerAuthProvider>
          <SavedRolesProvider>
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/about" element={<AboutPage />} />
              <Route path="/jobs" element={<JobBoardPage />} />
              <Route path="/learning" element={<LearningPage />} />
              <Route path="/saved" element={<SavedJobsPage />} />
              <Route path="/post-a-role" element={<PostRolePage />} />
              <Route path="/get-started" element={<SignInChooserPage />} />
              <Route path="/signin" element={<SignInPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />
              <Route path="/verify" element={<VerifyEmailPage />} />
              <Route path="/account" element={<AccountPage />} />
              <Route path="/employer/register" element={<EmployerRegisterPage />} />
              <Route path="/employer/signin" element={<EmployerSignInPage />} />
              <Route path="/employer/forgot-password" element={<EmployerForgotPasswordPage />} />
              <Route path="/employer/reset-password" element={<EmployerResetPasswordPage />} />
              <Route path="/employer/verify" element={<EmployerVerifyEmailPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </SavedRolesProvider>
        </EmployerAuthProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
