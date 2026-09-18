/**
 * Time-sensitive opportunities shown ahead of the evergreen MT directory.
 *
 * These are deliberately separate from `MT_PROGRAMMES`: a company can run
 * more than one live intake at once, while the directory remains one entry
 * per employer. The date is when this opportunity was last checked, not a
 * claim that every other programme has closed.
 */
export interface MTOpening {
  id: string
  company: string
  role: string
  location: string
  applicationUrl: string
  source: 'Official careers' | 'JobsDB' | 'Indeed' | 'LinkedIn'
  applicationDestination?: 'employer_role' | 'employer_vacancies' | 'intermediary'
  applicationLabel?: string
  verifiedAt: string
  deadline?: string
  note?: string
}

export const MT_OPENINGS: readonly MTOpening[] = [
  {
    id: 'hkjc-2027-management-trainee',
    company: 'The Hong Kong Jockey Club',
    role: '2027 Management Trainee Programme',
    location: 'Happy Valley, Hong Kong',
    deadline: '2026-10-31',
    applicationUrl: 'https://careers.hkjc.com/job/Happy-Valley-Management-Trainee-Hong/1366549566/',
    source: 'Official careers',
    applicationDestination: 'employer_role',
    applicationLabel: 'View HKJC programme',
    verifiedAt: '2026-09-14',
  },
  {
    id: 'hang-seng-indexes-management-trainee',
    company: 'Hang Seng Indexes',
    role: 'Management Trainee Programme',
    location: 'Central, Hong Kong',
    deadline: '2026-11-30',
    applicationUrl: 'https://apply.careers.hsbc.com/emergingtalent/job/Central-Hang-Seng-Management-Trainee-%28MT%29-Programme-Hang-Seng-Indexes-Company-Limited-Hong/1371340657/?feedId=434057',
    source: 'Official careers',
    applicationDestination: 'employer_role',
    applicationLabel: 'View Hang Seng programme',
    verifiedAt: '2026-09-14',
  },
  {
    id: 'hang-seng-commercial-banking-management-trainee',
    company: 'Hang Seng Bank',
    role: 'Commercial Banking Management Trainee Programme',
    location: 'Hong Kong',
    applicationUrl: 'https://www.hangseng.com/en-hk/about/careers/management-trainee-program/',
    source: 'Official careers',
    applicationDestination: 'employer_role',
    applicationLabel: 'View Hang Seng programme',
    verifiedAt: '2026-09-14',
  },
  {
    id: 'hang-seng-global-markets-management-trainee',
    company: 'Hang Seng Bank',
    role: 'Global Markets Management Trainee Programme',
    location: 'Hong Kong',
    applicationUrl: 'https://www.hangseng.com/en-hk/about/careers/management-trainee-program/',
    source: 'Official careers',
    applicationDestination: 'employer_role',
    applicationLabel: 'View Hang Seng programme',
    verifiedAt: '2026-09-14',
  },
  {
    id: 'smartone-management-trainee',
    company: 'SmarTone',
    role: 'Management Trainee Programme',
    location: 'Hong Kong',
    applicationUrl: 'https://www.smartoneholdings.com/jsp/site/careers/english/detail.jsp?id=636',
    source: 'Official careers',
    applicationDestination: 'employer_role',
    applicationLabel: 'View SmarTone programme',
    verifiedAt: '2026-09-14',
  },
  {
    id: 'hang-lung-management-trainee-2027',
    company: 'Hang Lung Properties',
    role: '2027 Management Trainee Programme',
    location: 'Hong Kong',
    applicationUrl: 'https://www.hanglung.com/en-us/careers/management-trainee-program',
    source: 'Official careers',
    applicationDestination: 'employer_role',
    applicationLabel: 'View Hang Lung programme',
    verifiedAt: '2026-09-14',
  },
  {
    id: 'boci-management-trainee-2027',
    company: 'BOCI',
    role: '2027 Management Trainee Programme',
    location: 'Hong Kong',
    applicationUrl: 'https://hk.indeed.com/viewjob?jk=3cb2b501b5212504',
    source: 'Indeed',
    verifiedAt: '2026-09-14',
  },
  {
    id: 'aia-business-consultant-trainee-2027',
    company: 'AIA Hong Kong and Macau',
    role: '2027 Business Consultant Trainee — Management Trainee Programme',
    location: 'Hong Kong',
    note: 'Financial-advisory and wealth-management track.',
    applicationUrl: 'https://www.aia.com.hk/en/about-aia/careers',
    source: 'Official careers',
    applicationDestination: 'employer_vacancies',
    applicationLabel: 'View AIA careers',
    verifiedAt: '2026-09-14',
  },
  {
    id: 'hyatt-regency-rooms-management-trainee',
    company: 'Hyatt Regency Hong Kong, Tsim Sha Tsui',
    role: 'Management Trainee — Rooms',
    location: 'Tsim Sha Tsui, Hong Kong',
    note: 'Hospitality and Rooms Division track.',
    applicationUrl: 'https://hk.linkedin.com/jobs/view/management-trainee-rooms-hyatt-regency-hong-kong-tsim-sha-tsui-at-hyatt-regency-4460371166',
    source: 'LinkedIn',
    verifiedAt: '2026-09-14',
  },
]
