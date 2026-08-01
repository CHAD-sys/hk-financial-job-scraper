import { ShieldCheck } from 'lucide-react'

/**
 * Privacy notice, written against Hong Kong's Personal Data (Privacy) Ordinance
 * (Cap. 486) — the PDPO — since the platform, the Club and the audience are all
 * Hong Kong based.
 *
 * ⚠️ Two things the reader of this file must know:
 *
 * 1. This is NOT legal advice and has not been reviewed by a lawyer. It is a
 *    good-faith, accurate description of what the software actually does, which
 *    is the hard part — but a solicitor should read it before launch.
 *
 * 2. ACCOUNTS_LIVE below controls whether this notice describes the account
 *    system. Accounts do NOT exist yet (they are a separate ~5-day item). The
 *    owner asked for the notice to be written as though they do, so it defaults
 *    to true. Be aware that DPP1 requires a data user to state the purposes for
 *    which data is ACTUALLY collected: a notice describing account processing
 *    that does not happen is itself inaccurate. Flip this to false to publish a
 *    notice matching today's reality, and back to true the day accounts ship.
 */
const ACCOUNTS_LIVE = true

const LAST_UPDATED = '27 July 2026'
const CONTACT_EMAIL = 'mohamedaminechahid@gmail.com'

interface Clause {
  n: string
  title: string
  body: React.ReactNode
}

const CLAUSES: Clause[] = [
  {
    n: '1',
    title: 'Who we are',
    body: (
      <>
        FinEx Careers is operated by the Financial Executive Club, Unit 16–17, 6/F,
        Chevalier Commercial Centre, 8 Wang Hoi Road, Kowloon Bay, Hong Kong. For the
        purposes of the Personal Data (Privacy) Ordinance (Cap. 486) we are the{' '}
        <em className="not-italic font-semibold">data user</em> for the personal data
        described below.
      </>
    ),
  },
  {
    n: '2',
    title: 'What we collect, and only when you give it',
    body: (
      <>
        <ul className="mt-2 flex flex-col gap-2">
          {[
            ACCOUNTS_LIVE &&
              'Account details — your name, email address and a password, which is stored only as a cryptographic hash. We never see or store your password in readable form.',
            'Consultation enquiries — the name, email address, career stage and message you type into the enquiry form.',
            'Role submissions — if you post a role, your name and email address alongside the role details you supply.',
            ACCOUNTS_LIVE
              ? 'Saved roles and application status — held against your account so they follow you between devices. Without an account they stay in your own browser and never reach us.'
              : 'Saved roles — held in your own browser only. They never reach our servers.',
            'Technical data — your IP address and request details, recorded briefly by the server to rate-limit abuse of the public forms.',
          ]
            .filter(Boolean)
            .map(t => (
              <li key={t as string} className="flex gap-2.5">
                <span
                  className="mt-2 h-1 w-1 shrink-0 rounded-full"
                  style={{ backgroundColor: 'var(--color-gold)' }}
                />
                <span>{t}</span>
              </li>
            ))}
        </ul>
        <p className="mt-3">
          Browsing the job index requires none of this. You can read every listing without
          giving us anything.
        </p>
      </>
    ),
  },
  {
    n: '3',
    title: 'What we use it for',
    body: (
      <>
        Strictly the purpose you gave it for: answering your enquiry, reviewing a role you
        submitted{ACCOUNTS_LIVE ? ', operating your account and keeping your saved roles in sync' : ''},
        and keeping the forms free of abuse. We do not use your data to make automated
        decisions about you.
      </>
    ),
  },
  {
    n: '4',
    title: 'What we never do',
    body: (
      <>
        We do not sell your personal data, rent it, or pass it to advertisers or data
        brokers. We run no third-party advertising or analytics trackers on this site. We
        do not store CVs — the CV-matching feature discussed elsewhere is not built, and if
        it ever is, it will be covered by its own notice and its own consent before a single
        document is accepted.
      </>
    ),
  },
  {
    n: '5',
    title: 'Direct marketing',
    body: (
      <>
        Under Part 6A of the Ordinance we may not use your personal data in direct marketing
        without your consent. We do not add enquirers to any mailing list. If we ever want
        to, we will ask you first, separately and in plain terms, and you may withdraw that
        consent at any time at no cost by writing to the address in clause 10.
      </>
    ),
  },
  {
    n: '6',
    title: 'Who else sees it',
    body: (
      <>
        Only the service providers needed to run the platform: our email provider, which
        delivers your enquiry to us, and our hosting provider. They act on our instructions
        and for no other purpose. Job listings themselves come from employers' own public
        postings and are not personal data about you.
      </>
    ),
  },
  {
    n: '7',
    title: 'Where it is held, and for how long',
    body: (
      <>
        Our servers may be located outside Hong Kong, so your data may be transferred and
        stored elsewhere; we take reasonably practicable steps to ensure it is protected to
        a comparable standard. We keep enquiries and role submissions only as long as needed
        to deal with them and to keep a record of what was published
        {ACCOUNTS_LIVE ? ', and account data for as long as your account is open' : ''}. Data
        that is no longer needed for the purpose it was collected for is erased.
      </>
    ),
  },
  {
    n: '8',
    title: 'Keeping it safe',
    body: (
      <>
        Traffic to this site is encrypted in transit. Access to submitted data is limited to
        the people who need it to run the service{ACCOUNTS_LIVE ? ', and passwords are stored only as hashes' : ''}.
        No system is perfectly secure, and we will not pretend otherwise — but we take
        reasonably practicable steps as the Ordinance requires.
      </>
    ),
  },
  {
    n: '9',
    title: 'Your rights',
    body: (
      <>
        You may ask us whether we hold personal data about you, ask for a copy of it, and
        ask us to correct it if it is wrong — a{' '}
        <em className="not-italic font-semibold">data access request</em> and a{' '}
        <em className="not-italic font-semibold">data correction request</em> under sections
        18 and 22 of the Ordinance. Write to us at the address in clause 10 and we will
        respond within 40 days. We may charge a fee for a copy, but not more than is directly
        related to and necessary for complying. You may also complain to the Office of the
        Privacy Commissioner for Personal Data, Hong Kong.
      </>
    ),
  },
  {
    n: '10',
    title: 'Cookies, and contacting us',
    body: (
      <>
        We set no advertising or tracking cookies. Your saved roles are kept in your own
        browser's local storage, which you can clear at any time from your browser settings.
        <br />
        <br />
        For anything in this notice — including a data access or correction request — write
        to{' '}
        <a
          href={`mailto:${CONTACT_EMAIL}?subject=Privacy%20enquiry`}
          style={{ color: 'var(--color-blue)', fontWeight: 600 }}
        >
          {CONTACT_EMAIL}
        </a>
        .
      </>
    ),
  },
]

export default function PrivacyNotice() {
  return (
    <section
      id="privacy"
      aria-labelledby="privacy-heading"
      className="scroll-mt-20 lg:scroll-mt-26"
      style={{
        backgroundColor: 'var(--color-surface-2)',
        borderTop: '1px solid var(--color-border)',
      }}
    >
      <div className="mx-auto max-w-7xl px-6 lg:px-8 py-16">
        <div className="max-w-3xl">
          <div className="mb-2 flex items-center gap-2">
            <ShieldCheck size={16} style={{ color: 'var(--color-gold)' }} />
            <p
              className="text-xs font-semibold uppercase"
              style={{ color: 'var(--color-gold)', letterSpacing: '0.12em' }}
            >
              Privacy
            </p>
          </div>

          <h2
            id="privacy-heading"
            className="text-2xl lg:text-3xl font-bold tracking-tight"
            style={{
              fontFamily: 'var(--font-display)',
              color: 'var(--color-ink)',
              letterSpacing: '-0.02em',
            }}
          >
            What we do with your data
          </h2>

          <p className="mt-4 text-base leading-relaxed" style={{ color: 'var(--color-ink-muted)' }}>
            The short version: you can read every job on this site without telling us
            anything. We only hold personal data you deliberately hand over — an enquiry, a
            role submission{ACCOUNTS_LIVE ? ', or an account' : ''} — and we use it for that
            and nothing else.
          </p>

          <dl className="mt-8 flex flex-col gap-6">
            {CLAUSES.map(({ n, title, body }) => (
              <div key={n}>
                <dt
                  className="mb-1 text-sm font-semibold"
                  style={{ color: 'var(--color-ink)' }}
                >
                  <span
                    className="mr-2 tabular-nums"
                    style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-faint)' }}
                  >
                    {n}
                  </span>
                  {title}
                </dt>
                <dd
                  className="text-sm leading-relaxed"
                  style={{ color: 'var(--color-ink-muted)', marginInlineStart: 0 }}
                >
                  {body}
                </dd>
              </div>
            ))}
          </dl>

          <p
            className="mt-8 pt-5 text-xs"
            style={{ color: 'var(--color-ink-faint)', borderTop: '1px solid var(--color-border)' }}
          >
            Last updated {LAST_UPDATED}. If we change how we use personal data we will update
            this notice and change that date. This is a plain-language summary of our
            practice, not legal advice.
          </p>
        </div>
      </div>
    </section>
  )
}
