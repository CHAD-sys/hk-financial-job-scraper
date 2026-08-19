import Nav from '../components/Nav'
import PrivacyNotice from '../components/PrivacyNotice'

/**
 * The privacy notice at its own address.
 *
 * It has always existed and been accurate — it is written against Hong Kong's
 * PDPO and names the Club, its registered address and a contact — but it lived
 * only at /about#privacy, where neither a person nor a reviewer would look for
 * it. "/privacy" returned 200 like every unknown path, and React quietly
 * redirected it to the homepage.
 *
 * That mattered on 2026-08-19, when Google Safe Browsing flagged the site
 * "Deceptive pages". A site that creates accounts and accepts CVs, with no
 * privacy policy at the address everyone checks first, reads as one more
 * anonymous credential collector. The notice is the evidence against that
 * reading, so it needs an address it can be linked from and cited by.
 */
export default function PrivacyPage() {
  return (
    <div style={{ backgroundColor: 'var(--color-bg)', minHeight: '100dvh' }}>
      <title>Privacy Notice — FinEx Careers</title>
      <meta
        name="description"
        content="How FinEx Careers, published by the Financial Executive Club in Hong Kong, collects, uses and deletes personal data, written against the Personal Data (Privacy) Ordinance (Cap. 486)."
      />
      <Nav />
      <main id="main-content">
        <PrivacyNotice />
      </main>
    </div>
  )
}
