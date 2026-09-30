import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { recordVisit } from './api/client'
import AuthProvider from './auth/AuthProvider'
import EmployerAuthProvider from './auth/EmployerAuthProvider'
import SavedRolesProvider from './savedRoles/SavedRolesProvider'
import AdminModeProvider from './adminMode/AdminModeProvider'
import EmployerViewProvider from './employerView/EmployerViewProvider'
import DeviceModeProvider from './deviceMode/DeviceModeProvider'
import { useDeviceMode } from './deviceMode/useDeviceMode'

// Device detection guarantees that only one of these two home experiences can
// render. Split both so a phone never downloads the editorial desktop landing
// page, and a desktop never pays for the phone-first board during startup.
const LandingPage = lazy(() => import('./pages/LandingPage'))
const JobBoardPage = lazy(() => import('./pages/JobBoardPage'))
const PrivacyPage = lazy(() => import('./pages/PrivacyPage'))
const SavedJobsPage = lazy(() => import('./pages/SavedJobsPage'))
const AboutPage = lazy(() => import('./pages/AboutPage'))
const PostRolePage = lazy(() => import('./pages/PostRolePage'))
const LearningPage = lazy(() => import('./pages/LearningPage'))
const ManagementTraineePage = lazy(() => import('./pages/ManagementTraineePage'))
const MTEmployerPage = lazy(() => import('./pages/MTEmployerPage'))
const RoleDetailPage = lazy(() => import('./pages/RoleDetailPage'))
const CareerCoachesPage = lazy(() => import('./pages/CareerCoachesPage'))
const SignInChooserPage = lazy(() => import('./pages/SignInChooserPage'))
const SignInPage = lazy(() => import('./pages/SignInPage'))
const RegisterPage = lazy(() => import('./pages/RegisterPage'))
const AccountPage = lazy(() => import('./pages/AccountPage'))
const AdminPage = lazy(() => import('./pages/AdminPage'))
const AsfPage = lazy(() => import('./pages/AsfPage'))
const RecruiterDeskPage = lazy(() => import('./pages/RecruiterDeskPage'))
const ForgotPasswordPage = lazy(() => import('./pages/ForgotPasswordPage'))
const ResetPasswordPage = lazy(() => import('./pages/ResetPasswordPage'))
const VerifyEmailPage = lazy(() => import('./pages/VerifyEmailPage'))
const EmployerRegisterPage = lazy(() => import('./pages/EmployerRegisterPage'))
const EmployerSignInPage = lazy(() => import('./pages/EmployerSignInPage'))
const EmployerForgotPasswordPage = lazy(() => import('./pages/EmployerForgotPasswordPage'))
const EmployerResetPasswordPage = lazy(() => import('./pages/EmployerResetPasswordPage'))
const EmployerVerifyEmailPage = lazy(() => import('./pages/EmployerVerifyEmailPage'))

/**
 * AuthProvider and EmployerAuthProvider both sit inside the router (Nav reads
 * both) and outside Routes (who is signed in does not change between routes).
 * Siblings, not nested — the two identities are independent (docs/adr/0001)
 * and neither is a special case of the other. SavedRolesProvider sits inside
 * AuthProvider only, because which store Saved Roles come from is a function
 * of the Seeker, not the Employer.
 *
 * Almost every route below is unprotected: the board is public and accounts
 * gate nothing for a Seeker (docs/adr/0002). /account (Seeker), /post-a-role
 * (Employer), and /admin (a Seeker with is_admin set) are the
 * pages that need someone signed in — with the right privilege, in the admin
 * pages' case — and each redirects itself rather than being wrapped in a
 * guard component. See AccountPage.tsx, PostRolePage.tsx, AdminPage.tsx and
 * AdminPage.tsx.
 *
 * Nav's "Sign in" points at /get-started, not directly at /signin — see
 * SignInChooserPage.tsx for why a chooser sits in front of both sign-in
 * forms now that there are two account kinds to choose between.
 */

/**
 * A shared fallback <title> for every route that has no reason to set its
 * own — account, sign-in, admin, employer flows — none meant to be indexed
 * (see robots.txt). A layout route rather than an always-mounted App-level
 * tag: React has no documented tie-break for two simultaneously-mounted
 * <title>s, so the only way to guarantee exactly one in the document is to
 * never mount two at once. LandingPage, AboutPage, JobBoardPage and
 * LearningPage sit outside this layout and set their own instead.
 */
/**
 * Head tags for the routes that do not carry their own.
 *
 * Two of these routes are indexable and want real copy — "/get-started" is the
 * page LinkedIn unfurls when someone shares a sign-in link, and "/post-a-role"
 * is how an employer finds us. The rest are account pages that must never be
 * indexed at all.
 *
 * Kept in step with `_ROUTE_META` and `_NOINDEX_PREFIXES` in
 * webapp/backend/main.py, which serves the same values to clients that never
 * run JS. tests/test_route_meta_in_step.py fails if the two drift apart.
 */
const ROUTE_META: Record<string, { title: string; description: string }> = {
  '/get-started': {
    title: 'Create Your Free FinEx Careers Account',
    description:
      'Create a free FinEx Careers account to see full role descriptions, save positions, upload a CV for matching, and get a weekly digest of new roles.',
  },
  '/post-a-role': {
    title: 'Post a Finance Role in Hong Kong | FinEx Careers',
    description:
      'Reach Hong Kong finance professionals directly. Submit an open role to the FinEx Careers board, reviewed before it is published.',
  },
}

function DefaultTitleLayout() {
  const { pathname } = useLocation()
  const meta = ROUTE_META[pathname.replace(/\/+$/, '') || '/']
  if (!meta) {
    return (
      <>
        <title>FinEx Careers</title>
        {/* An account page. Keeping it out of the index is the point: a sign-in
            form in search results is a reputation liability, not traffic. */}
        <meta name="robots" content="noindex,follow" />
        <Outlet />
      </>
    )
  }
  return (
    <>
      <title>{meta.title}</title>
      <meta name="description" content={meta.description} />
      <Outlet />
    </>
  )
}

/**
 * The root route is a product decision, not a responsive breakpoint. Phone
 * visitors enter the phone-first discovery home immediately; desktop visitors
 * retain the editorial landing page. The device decision comes from the
 * provider's stable identity signals, never the current browser-window size.
 */
export function HomeRoute() {
  const { uiMode } = useDeviceMode()
  return uiMode === 'mobile' ? <JobBoardPage /> : <LandingPage />
}

function RouteLoading() {
  return (
    <main className="route-loading" aria-live="polite" aria-busy="true">
      <span className="route-loading__mark" aria-hidden="true" />
      <p>Loading FinEx Careers…</p>
    </main>
  )
}

export default function App() {
  // Fired once per app load, not per route change — a "visit", not a
  // pageview. Best-effort and silent: see client.ts's recordVisit().
  useEffect(() => {
    void recordVisit()
  }, [])

  return (
    <DeviceModeProvider>
      <BrowserRouter>
        <AuthProvider>
          <EmployerAuthProvider>
            <SavedRolesProvider>
              {/* Inside AuthProvider: whether Admin Mode is even available is a
                  function of the signed-in Seeker's privilege bits. */}
              <AdminModeProvider>
                {/* Inside BOTH auth providers: availability is a function of the
                    Seeker's Ultimate-Admin bit AND of there being no real
                    Employer session to conflict with. */}
                <EmployerViewProvider>
                  <Suspense fallback={<RouteLoading />}>
                  <Routes>
                    <Route path="/" element={<HomeRoute />} />
                    <Route path="/about" element={<AboutPage />} />
                    <Route path="/privacy" element={<PrivacyPage />} />
                    <Route path="/jobs" element={<JobBoardPage />} />
                    <Route path="/roles/:source/:sourceId" element={<RoleDetailPage />} />
                    <Route path="/learning" element={<LearningPage />} />
                    <Route path="/management-trainee" element={<ManagementTraineePage />} />
                    <Route path="/management-trainee/:employerSlug" element={<MTEmployerPage />} />
                    <Route path="/career-coaches" element={<CareerCoachesPage />} />
                    <Route element={<DefaultTitleLayout />}>
                      <Route path="/saved" element={<SavedJobsPage />} />
                      <Route path="/post-a-role" element={<PostRolePage />} />
                      <Route path="/get-started" element={<SignInChooserPage />} />
                      <Route path="/signin" element={<SignInPage />} />
                      <Route path="/register" element={<RegisterPage />} />
                      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                      <Route path="/reset-password" element={<ResetPasswordPage />} />
                      <Route path="/verify" element={<VerifyEmailPage />} />
                      <Route path="/account" element={<AccountPage />} />
                      <Route path="/admin" element={<AdminPage />} />
                      <Route path="/validate" element={<AsfPage />} />
                      <Route path="/recruiter-desk" element={<RecruiterDeskPage />} />
                      <Route path="/asf" element={<Navigate to="/validate" replace />} />
                      <Route path="/employer/register" element={<EmployerRegisterPage />} />
                      <Route path="/employer/signin" element={<EmployerSignInPage />} />
                      <Route path="/employer/forgot-password" element={<EmployerForgotPasswordPage />} />
                      <Route path="/employer/reset-password" element={<EmployerResetPasswordPage />} />
                      <Route path="/employer/verify" element={<EmployerVerifyEmailPage />} />
                    </Route>
                    <Route path="/choose-view" element={<Navigate to="/admin" replace />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                  </Suspense>
                </EmployerViewProvider>
              </AdminModeProvider>
            </SavedRolesProvider>
          </EmployerAuthProvider>
        </AuthProvider>
      </BrowserRouter>
    </DeviceModeProvider>
  )
}
