/**
 * Source of truth: `MT List - updated.xlsx`, provided by the FinEx team on
 * 29 September 2026. Every workbook hyperlink is a distinct destination;
 * the directory groups those destinations beneath their employer card. Its
 * status and deadline are preserved per row.
 * Do not reconcile this list with the jobs-board feed here.
 */
export type MTWorkbookStatus = 'Active' | 'Closed' | 'N/A'

export interface MTWorkbookProgramme {
  id: string
  company: string
  status: MTWorkbookStatus
  deadline: string | null
  applicationUrl: string
  employerLinkNumber: number
}

export interface MTWorkbookEmployer {
  company: string
  programmes: readonly MTWorkbookProgramme[]
}

export function mtEmployerSlug(company: string) {
  return company.toLocaleLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
}

const NON_ROLE_URL_SEGMENTS = new Set([
  'about', 'career', 'careers', 'content', 'details', 'en', 'en-us', 'home', 'job', 'jobs',
  'programmes', 'programme', 'search', 'students', 'zh-cn', 'zh-hk',
])

const GENERIC_URL_LABELS = new Set([
  'about us', 'asia pacific', 'campus recruitment', 'career opportunities', 'careers', 'detail',
  'early career detail', 'employer careers', 'home with preload', 'hkt', 'job detail', 'jobs',
  'kpmg', 'list', 'mufg careers', 'practice', 'recruit detail', 'roles', 'search jobs', 'sol',
  'students graduates', 'sxs', 'xiaoyuan',
])

const ROLE_LABEL_OVERRIDES: Readonly<Record<string, string>> = {
  'mt-workbook-row-12': 'Career opportunities',
  'mt-workbook-row-13': 'Internship Programme',
  'mt-workbook-row-14': 'Career opportunities',
  'mt-workbook-row-15': 'Campus opportunities',
  'mt-workbook-row-16': 'Project Intern — IBD',
  'mt-workbook-row-17': 'Debt Capital Markets Intern',
  'mt-workbook-row-20': 'Career opportunities',
  'mt-workbook-row-21': 'Asia 2026–27 Recruiting News',
  'mt-workbook-row-22': 'Trainee — Securities Financing Tech',
  'mt-workbook-row-23': 'Student opportunities',
  'mt-workbook-row-24': 'Student opportunities',
  'mt-workbook-row-25': 'Student opportunities',
  'mt-workbook-row-26': 'Management Trainee Programme',
  'mt-workbook-row-28': 'Career opportunities',
  'mt-workbook-row-29': 'Career opportunities',
  'mt-workbook-row-30': 'Career opportunities',
  'mt-workbook-row-31': 'Career opportunities',
  'mt-workbook-row-32': 'Career opportunities',
  'mt-workbook-row-33': 'Career opportunities',
  'mt-workbook-row-34': 'Career opportunities',
  'mt-workbook-row-35': 'Career opportunities',
  'mt-workbook-row-36': 'Career opportunities',
  'mt-workbook-row-37': 'Career opportunities',
  'mt-workbook-row-49': 'Students and graduates',
  'mt-workbook-row-63': 'Student opportunities',
  'mt-workbook-row-64': 'Student opportunities',
  'mt-workbook-row-66': 'Early-career opportunities',
  'mt-workbook-row-67': 'Early-career opportunities',
  'mt-workbook-row-68': 'BEA Career MT Programme',
  'mt-workbook-row-69': 'Retail Banking Professional Programme',
  'mt-workbook-row-70': 'WBD Functional Trainee',
  'mt-workbook-row-72': 'Elite Programme',
  'mt-workbook-row-73': 'Early-career opportunities',
  'mt-workbook-row-76': 'Rotational Analyst 2027 Leadership Development Program',
  'mt-workbook-row-77': 'Career opportunities',
  'mt-workbook-row-78': 'Early-career opportunities',
  'mt-workbook-row-79': 'Internship Programme',
  'mt-workbook-row-80': 'Early-career opportunities',
  'mt-workbook-row-84': 'Career opportunities',
  'mt-workbook-row-85': 'Campus recruitment',
  'mt-workbook-row-86': 'Campus recruitment',
  'mt-workbook-row-87': 'Campus recruitment',
  'mt-workbook-row-88': 'Career opportunities',
  'mt-workbook-row-89': 'Career opportunities',
  'mt-workbook-row-90': 'Campus recruitment',
  'mt-workbook-row-91': 'Campus recruitment',
  'mt-workbook-row-92': 'Campus recruitment',
  'mt-workbook-row-93': 'Campus recruitment',
  'mt-workbook-row-94': 'Campus recruitment',
  'mt-workbook-row-95': 'Campus recruitment',
  'mt-workbook-row-96': 'Campus recruitment',
  'mt-workbook-row-97': 'Early-career opportunities',
  'mt-workbook-row-99': 'Graduate opportunities',
  'mt-workbook-row-102': 'Campus recruitment',
  'mt-workbook-row-103': 'Campus recruitment',
  'mt-workbook-row-104': 'Career opportunities',
  'mt-workbook-row-105': 'Career opportunities',
  'mt-workbook-row-106': 'Career opportunities',
  'mt-workbook-row-107': 'Career opportunities',
  'mt-workbook-row-108': 'Career opportunities',
  'mt-workbook-row-109': 'Career opportunities',
  'mt-workbook-row-116': 'JETS Programme',
  'mt-workbook-row-118': 'Early-career opportunities',
  'mt-workbook-row-125': 'Swire Summer Internship Programme',
  'mt-workbook-row-127': 'SCSI 2026 Programme',
  'mt-workbook-row-128': 'Career opportunities',
  'mt-workbook-row-130': 'Store Trainee Manager',
  'mt-workbook-row-133': 'Part-time Fashion Design Intern',
  'mt-workbook-row-134': 'Career opportunities',
  'mt-workbook-row-135': 'Students and graduates',
  'mt-workbook-row-136': 'Career opportunities',
  'mt-workbook-row-139': 'Graduates & Interns',
  'mt-workbook-row-140': 'Design Intern',
  'mt-workbook-row-141': 'Brand Intern',
  'mt-workbook-row-142': 'Corporate Brand Intern',
  'mt-workbook-row-145': 'Career opportunities',
  'mt-workbook-row-148': 'Payroll Intern',
  'mt-workbook-row-149': 'Data Analyst',
  'mt-workbook-row-150': 'Hong Kong internships',
  'mt-workbook-row-161': 'Career opportunities',
  'mt-workbook-row-162': 'Graduate Management Trainee Programme',
  'mt-workbook-row-163': 'Graduate Management Trainee Programme',
  'mt-workbook-row-164': 'Graduate Management Trainee Programme',
  'mt-workbook-row-165': 'Career programmes',
  'mt-workbook-row-166': 'Summer Internship Programme A',
  'mt-workbook-row-167': 'Internship Programme',
  'mt-workbook-row-168': 'Career opportunities',
  'mt-workbook-row-169': 'Career opportunities',
  'mt-workbook-row-170': 'Career opportunities',
}

function titleFromUrlText(value: string) {
  const decoded = decodeURIComponent(value)
    .replace(/---split---/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!decoded) return null

  // URL providers frequently end an otherwise useful path with a locale such
  // as `en-GB`; that is routing metadata, never a job title.
  if (/^[a-z]{2}(?:[-_\s][a-z]{2})?$/i.test(decoded)) return null
  if (/^\d+\s+[a-z]{2}\s+[a-z]{2}$/i.test(decoded)) return null

  // Provider URLs usually append location information after the role. It is
  // useful for routing but noisy in a compact role tile.
  const withoutLocation = decoded
    .replace(/^(?!20\d{2}\b)\d{4,}\s+/, '')
    .replace(/^Central\s+/i, '')
    .replace(/^Hong Kong\s+/i, '')
    .replace(/(?:\s+Hong\s+Kong(?:\s+SAR)?)+$/i, '')
    .replace(/\s+Hong$/i, '')
    .replace(/\s+HK$/i, '')
    .replace(/\s+\d{6,}$/i, '')
    .trim()
  if (!withoutLocation || /^\d+$/.test(withoutLocation)) return null

  return withoutLocation.replace(/\b\w+/g, word => {
    if (/^(ai|apac|asia|bo|cn|gb|hk|hsbc|ibd|it|mt|uk|us)$/i.test(word)) return word.toUpperCase()
    if (/^(and|at|for|in|of|on|the|to|with)$/i.test(word)) return word.toLowerCase()
    return `${word.charAt(0).toUpperCase()}${word.slice(1).toLowerCase()}`
  })
}

/**
 * The supplied workbook has a destination URL per route but no standalone
 * title column. Job boards encode the role in `jobTitle` or their final
 * meaningful URL path segment, so derive the label from that factual source.
 */
export function mtApplicationRoleLabel(programme: MTWorkbookProgramme) {
  const override = ROLE_LABEL_OVERRIDES[programme.id]
  if (override) return override

  try {
    const url = new URL(programme.applicationUrl)
    const queryTitle = [...url.searchParams.entries()].find(([key]) => /(?:job)?title/i.test(key))?.[1]
    const fromQuery = queryTitle && titleFromUrlText(queryTitle)
    if (fromQuery) return fromQuery

    const pathSegments = url.pathname
      .split('/')
      .filter(Boolean)
      .map(segment => segment.replace(/\.[a-z0-9]+$/i, ''))
      .filter(segment => !NON_ROLE_URL_SEGMENTS.has(segment.toLocaleLowerCase()))
    const fromPath = [...pathSegments].reverse()
      .map(titleFromUrlText)
      .find((label): label is string => Boolean(label))
    if (fromPath && !GENERIC_URL_LABELS.has(fromPath.toLocaleLowerCase())) return fromPath

    const fromFragment = url.hash.split(/[?#=&]+/).map(titleFromUrlText)
      .find((label): label is string => Boolean(label))
    if (fromFragment && !GENERIC_URL_LABELS.has(fromFragment.toLocaleLowerCase())) return fromFragment

    if (/intern/i.test(url.pathname)) return 'Internship opportunities'
    if (/graduate/i.test(url.pathname)) return 'Graduate opportunities'
    if (/early.?careers?/i.test(url.pathname)) return 'Early-career opportunities'
  } catch {
    // A malformed source URL should retain a useful, non-invented fallback.
  }
  return 'Employer careers'
}

const rows: readonly [string, string, MTWorkbookStatus, string | null, string, number][] = [
  ["mt-workbook-row-2", "Bank of America (BofA)", "Active", "30-Sep-2026", "https://careers.bankofamerica.com/en-us/students/job-detail/14366/global-markets-sales-trading-rotational-summer-analyst-2027-hong-kong-hong-kong-hong-kong", 1],
  ["mt-workbook-row-3", "Bank of America (BofA)", "Active", "30-Sep-2026", "https://careers.bankofamerica.com/en-us/students/job-detail/14372/chief-operating-officer-group-summer-analyst-2027-hong-kong-hong-kong-hong-kong", 2],
  ["mt-workbook-row-4", "Bank of America (BofA)", "Active", "30-Sep-2026", "https://careers.bankofamerica.com/en-us/students/job-detail/14375/global-capital-markets-summer-analyst-2027-hong-kong-hong-kong-hong-kong", 3],
  ["mt-workbook-row-5", "Bank of America (BofA)", "Active", "30-Sep-2026", "https://careers.bankofamerica.com/en-us/students/job-detail/14367/global-investment-banking-summer-analyst-2027-hong-kong-hong-kong-hong-kong", 4],
  ["mt-workbook-row-6", "Bank of America (BofA)", "Active", "30-Sep-2026", "https://careers.bankofamerica.com/en-us/students/job-detail/14384/global-corporate-banking-summer-analyst-2027-hong-kong-hong-kong-hong-kong", 5],
  ["mt-workbook-row-7", "Bank of America (BofA)", "Active", "30-Sep-2026", "https://careers.bankofamerica.com/en-us/students/job-detail/14359/global-quantitative-strategies-summer-associate-2027-hong-kong-hong-kong-hong-kong", 6],
  ["mt-workbook-row-8", "Bank of America (BofA)", "Active", "30-Sep-2026", "https://careers.bankofamerica.com/en-us/students/job-detail/14369/corporate-audit-summer-analyst-2027-hong-kong-hong-kong-hong-kong", 7],
  ["mt-workbook-row-9", "Bank of America (BofA)", "Active", "30-Sep-2026", "https://careers.bankofamerica.com/en-us/students/job-detail/14382/enterprise-credit-summer-analyst-2027-hong-kong-hong-kong-hong-kong", 8],
  ["mt-workbook-row-10", "BOC International (BOCI)", "Active", "09-Oct-2026", "https://boci.recruitmentplatform.com/details.html?jobId=6328&jobTitle=2027%20Management%20Trainee%20Programme", 1],
  ["mt-workbook-row-11", "BOC International (BOCI)", "Active", "09-Oct-2026", "https://boci.recruitmentplatform.com/details.html?jobId=6329&jobTitle=2027%20Management%20Trainee%20Programme%20(Information%20Technology%20Focused)", 2],
  ["mt-workbook-row-12", "BOCOM International", "N/A", null, "https://www.bocomgroup.com/BankCommSite/shtml/jygj/en/16634/16749/list.shtml", 1],
  ["mt-workbook-row-13", "CLSA", "Closed", null, "https://www.clsa.com/internship-programme-2/", 1],
  ["mt-workbook-row-14", "CMB International", "Closed", null, "https://www.cmbi.com.hk/en-US/practice", 1],
  ["mt-workbook-row-15", "Goldman Sachs", "Active", "Ongoing", "https://higher.gs.com/roles/183898", 1],
  ["mt-workbook-row-16", "Huatai International", "Active", "Ongoing", "https://htsc.wd102.myworkdayjobs.com/en-US/Huatai_Careers/details/Project-Intern--IBD_-3?q=intership", 1],
  ["mt-workbook-row-17", "Huatai International", "Active", "Ongoing", "https://htsc.wd102.myworkdayjobs.com/en-US/Huatai_Careers/details/Debt-Capital-Markets---Intern_-1?q=intership", 2],
  ["mt-workbook-row-18", "Jefferies", "Active", "Ongoing", "https://jefferies.tal.net/vx/lang-en-GB/mobile-0/appcentre-1/brand-4/xf-016c915b0a67/candidate/so/pm/1/pl/2/opp/1814-2027-Summer-Analyst-Program-Investment-Banking-Hong-Kong/en-GB", 1],
  ["mt-workbook-row-19", "Jefferies", "Active", "Ongoing", "https://jefferies.tal.net/vx/lang-en-GB/mobile-0/appcentre-1/brand-4/xf-016c915b0a67/candidate/so/pm/1/pl/2/opp/1984-2027-Equity-Research-Summer-Analyst-Program-Hong-Kong/en-GB", 2],
  ["mt-workbook-row-20", "Mizuho", "Closed", null, "https://www.mizuhogroup.com/asia-pacific/careers", 1],
  ["mt-workbook-row-21", "Morgan Stanley", "Active", "Ongoing", "https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/so/pm/1/pl/2/opp/20995-Morgan-Stanley-Asia-2026-27-Recruiting-News/en-GB", 1],
  ["mt-workbook-row-22", "Société Générale", "Active", "Ongoing", "https://careers.societegenerale.com/en/job-offers/trainee-securities-financing-tech-26000HKS-en", 1],
  ["mt-workbook-row-23", "UBS", "Active", "04-Nov-2026", "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid=25008&siteid=5131&PageType=searchResults&SearchType=linkquery&LinkID=15974#jobDetails=349902_5131", 1],
  ["mt-workbook-row-24", "UBS", "Active", "25-Sep-2026", "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid=25008&siteid=5131&PageType=searchResults&SearchType=linkquery&LinkID=15974#jobDetails=350169_5131", 2],
  ["mt-workbook-row-25", "UBS", "Active", "30-Oct-2026", "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid=25008&siteid=5131&PageType=searchResults&SearchType=linkquery&LinkID=15974#jobDetails=350660_5131", 3],
  ["mt-workbook-row-26", "Bank of China (Hong Kong) [BOCHK]", "Active", "09-Oct-2026", "https://www.bochk.com/en/career/ustudentprogramme/mgttrainee.html", 1],
  ["mt-workbook-row-27", "China Construction Bank (Asia)", "Active", "Ongoing", "https://www.asia.ccb.com/hongkong/aboutus/career_opportunities/graduate_opportunities/graduate_trainee_program.html", 1],
  ["mt-workbook-row-28", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=55386149-1350-46C6-9EED-11FB73653AC6&pageSource=homepage&fromType=Contract", 1],
  ["mt-workbook-row-29", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=1CFEDAB5-6DF3-4951-AC7C-64229338C79C&pageSource=jobList&fromType=Contract", 2],
  ["mt-workbook-row-30", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=D5D8F95C-2804-49E5-AF0E-0484E7E5E49F&pageSource=jobList&fromType=Contract", 3],
  ["mt-workbook-row-31", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=82B77D01-85EE-48F7-A4A7-E7832D7AD08A&pageSource=jobList&fromType=Contract", 4],
  ["mt-workbook-row-32", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=CB0F4D2A-3B6F-4356-9AFD-DC10C1D8E01A&pageSource=jobList&fromType=Contract", 5],
  ["mt-workbook-row-33", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=33F1AD46-7398-409E-982E-2BF278D406B5&pageSource=jobList&fromType=Contract", 6],
  ["mt-workbook-row-34", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=63A798A7-D108-4DFB-8EC5-EA7F649C751E&pageSource=jobList&fromType=Contract", 7],
  ["mt-workbook-row-35", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=A743418B-A8BF-4CE4-8349-195800319691&pageSource=jobList&fromType=Contract", 8],
  ["mt-workbook-row-36", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=8AE5F018-C1B3-490A-9EB5-D59A0C514D6E&pageSource=jobList&fromType=Contract", 9],
  ["mt-workbook-row-37", "CMB Wing Lung Bank", "Active", "Ongoing", "https://recruit.cmbwinglungbank.com/#/jobDetail?publishId=B5B6A9B4-706C-4981-A1B4-13D71BEA6E7A&pageSource=jobList&fromType=Contract", 10],
  ["mt-workbook-row-38", "Hang Seng Bank", "Active", "30-Nov-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Hang-Seng-Management-Trainee-%28MT%29-Programme-Global-Markets-Hong/1371336857/?feedId=434057&utm_source=CareerSite&utm_campaign=EmergingTalent", 1],
  ["mt-workbook-row-39", "Hang Seng Bank", "Active", "30-Nov-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Hang-Seng-Management-Trainee-%28MT%29-Programme-Commercial-Banking-Hong/1371337557/?feedId=434057&utm_source=CareerSite&utm_campaign=EmergingTalent", 2],
  ["mt-workbook-row-40", "Hang Seng Bank", "Active", "30-Nov-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Hang-Seng-Management-Trainee-%28MT%29-Programme-Retail-Banking-and-Wealth-Hong/1371337257/?feedId=434057&utm_source=CareerSite&utm_campaign=EmergingTalent", 3],
  ["mt-workbook-row-41", "Hang Seng Bank", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Relationship-Management-Commercial-Banking-Graduate-Hong/1371197557/?feedId=434057&utm_source=CareerSite&utm_campaign=EmergingTalent", 4],
  ["mt-workbook-row-42", "Hang Seng Bank", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Business-Analyst-Treasury-Graduate-Hong/1371080157", 5],
  ["mt-workbook-row-43", "Hang Seng Bank", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Relationship-Management-Private-Bank-Graduate-Hong/1371077157/", 6],
  ["mt-workbook-row-44", "Hang Seng Bank", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Business-Analyst-Finance-Graduate-Hong/1371080257/", 7],
  ["mt-workbook-row-45", "Hang Seng Bank", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Business-Analyst-Insurance-Graduate-Hong/1371078657/", 8],
  ["mt-workbook-row-46", "Hang Seng Bank", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Relationship-Management-Retail-Banking-and-Wealth-Graduate-Hong/1371076857", 9],
  ["mt-workbook-row-47", "Hang Seng Bank", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Investment-Banking-Graduate-Hong/1365764257", 10],
  ["mt-workbook-row-48", "Hang Seng Bank", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Markets-Sales-and-Trading-Graduate-Hong/1365763657/", 11],
  ["mt-workbook-row-49", "HSBC", "Active", "31-Oct-2026", "https://www.hsbc.com/careers/students-and-graduates", 1],
  ["mt-workbook-row-50", "HSBC", "Active", "30-Oct-2026", "https://hk.linkedin.com/jobs/view/2027-hsbc-hong-kong-corporate-and-institutional-banking-graduate-programmes-at-hsbc-4451119894", 2],
  ["mt-workbook-row-51", "HSBC", "Active", "30-Oct-2026", "https://hk.linkedin.com/jobs/view/2027-hsbc-hong-kong-corporate-and-institutional-banking-summer-internship-programmes-at-hsbc-4451113955", 3],
  ["mt-workbook-row-52", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Relationship-Management-Commercial-Banking-Graduate-Hong/1371197557/?feedId=434057&utm_source=CareerSite&utm_campaign=EmergingTalent", 4],
  ["mt-workbook-row-53", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Transaction-Banking-Securities-Services-Graduate-Hong/1371075957", 5],
  ["mt-workbook-row-54", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Business-Analyst-Treasury-Graduate-Hong/1371080157", 6],
  ["mt-workbook-row-55", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Investment-Specialist-Investments-Graduate-Hong/1371078957", 7],
  ["mt-workbook-row-56", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Engineering-Graduate-Hong/1371075057", 8],
  ["mt-workbook-row-57", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Relationship-Management-Private-Bank-Graduate-Hong/1371077157/", 9],
  ["mt-workbook-row-58", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Business-Analyst-Finance-Graduate-Hong/1371080257/", 10],
  ["mt-workbook-row-59", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Business-Analyst-Insurance-Graduate-Hong/1371078657/", 11],
  ["mt-workbook-row-60", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Relationship-Management-Retail-Banking-and-Wealth-Graduate-Hong/1371076857", 12],
  ["mt-workbook-row-61", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Investment-Banking-Graduate-Hong/1365764257", 13],
  ["mt-workbook-row-62", "HSBC", "Active", "31-Oct-2026", "https://apply.careers.hsbc.com/emergingtalent/job/Central-Markets-Sales-and-Trading-Graduate-Hong/1365763657/", 14],
  ["mt-workbook-row-63", "MUFG (Mitsubishi UFJ Financial Group)", "Active", "31-Oct-2026", "https://mufgub.wd3.myworkdayjobs.com/en-US/MUFG-Careers", 1],
  ["mt-workbook-row-64", "MUFG (Mitsubishi UFJ Financial Group)", "Active", "31-Dec-2026", "https://mufgub.wd3.myworkdayjobs.com/en-US/MUFG-Careers", 2],
  ["mt-workbook-row-65", "Standard Chartered", "Active", "31-Dec-2026", "https://jobs.standardchartered.com/job/Global-Banking-Intern-Hong-Kong-2027/59126-en_GB", 1],
  ["mt-workbook-row-66", "Standard Chartered", "Active", "31-Dec-2026", "https://jobs.standardchartered.com/search/?q=&skillsSearch=false&facetFilters=%7B%22cust_csb_careerType%22%3A%5B%22Early+Careers%22%5D%2C%22jobLocationCountry%22%3A%5B%22Hong+Kong%22%5D%7D&pageNumber=0", 2],
  ["mt-workbook-row-67", "Standard Chartered", "Active", "31-Dec-2026", "https://jobs.standardchartered.com/search/?q=&skillsSearch=false&facetFilters=%7B%22cust_csb_careerType%22%3A%5B%22Early+Careers%22%5D%2C%22jobLocationCountry%22%3A%5B%22Hong+Kong%22%5D%7D&pageNumber=0", 3],
  ["mt-workbook-row-68", "The Bank of East Asia (BEA)", "Active", "Ongoing", "https://www.hkbea.com/html/en/bea-career-mt-programme.html", 1],
  ["mt-workbook-row-69", "The Bank of East Asia (BEA)", "Active", "Ongoing", "https://www.hkbea.com/html/en/bea-career-Retail-Banking-Professional-Programme.html", 2],
  ["mt-workbook-row-70", "The Bank of East Asia (BEA)", "Active", "Ongoing", "https://www.hkbea.com/html/en/bea-wbd-functional-trainee.html", 3],
  ["mt-workbook-row-71", "CSOP Asset Management", "Active", "Ongoing", "https://www.csopasset.com/en/career/apprenticeshipProgram", 1],
  ["mt-workbook-row-72", "CSOP Asset Management", "Active", "31-Oct-2026", "https://www.csopasset.com/en/career/earlyCareerDeatil?jobId=4e9ddced996c44d5b0f09a03e4ef2ef5---split---EliteProgram", 2],
  ["mt-workbook-row-73", "Fidelity International", "Active", "31-Oct-2026", "https://careers.fidelityinternational.com", 1],
  ["mt-workbook-row-74", "HKEX (Hong Kong Exchanges and Clearing)", "Active", "25-Oct-2026", "https://www.hkexgroup.com/about-hkex/careers-at-hkex/early-careers?sc_lang=en", 1],
  ["mt-workbook-row-75", "Invesco Asia", "Active", "Ongoing", "https://careers.invesco.com/early-careers/", 1],
  ["mt-workbook-row-76", "ION Group", "Active", "Ongoing", "https://iongroup.com/jobs/rotational-analyst-2027-leadership-development-program-hong-kong-86ec0518-6757-4f06-bb27-c2fdc7e70621/", 1],
  ["mt-workbook-row-77", "RedotPay", "Active", "Ongoing", "https://hire-r1.mokahr.com/social-recruitment/redotpay/100008889?locale=en-US#/", 1],
  ["mt-workbook-row-78", "Aon", "Active", "Ongoing", "https://www.aon.com/careers/early-careers/asia", 1],
  ["mt-workbook-row-79", "Aon", "Active", "Ongoing", "https://www.aon.com/hongkong/zh/traditional-chinese/about-aon/careers/internship-programme-tc.jsp", 2],
  ["mt-workbook-row-80", "Computershare", "N/A", null, "https://www.computershare.com/corporate/careers/build-your-career/early-careers", 1],
  ["mt-workbook-row-81", "Deloitte", "Active", "31-Oct-2026", "https://www.deloitte.com/cn/en/careers/explore-your-fit/students/graduate-program.html", 1],
  ["mt-workbook-row-82", "Deloitte", "Active", "31-Oct-2026", "https://www.deloitte.com/cn/en/careers/explore-your-fit/students/internship-program.html", 2],
  ["mt-workbook-row-83", "Deloitte", "Active", "31-Oct-2026", "https://www.deloitte.com/cn/zh/careers/explore-your-fit/students/students-deloitte-club.html", 3],
  ["mt-workbook-row-84", "Ekimetrics", "Active", "Ongoing", "https://jobs.lever.co/ekimetrics/c7a0112a-4228-416f-8dd0-ff65fd0e87cc", 1],
  ["mt-workbook-row-85", "EY (Ernst & Young)", "Active", "Ongoing", "https://hkcareers.ey.com.cn/campus-recruitment/ey/168333?locale=en-US/#/", 1],
  ["mt-workbook-row-86", "EY (Ernst & Young)", "Active", "Ongoing", "https://hkcareers.ey.com.cn/campus-recruitment/ey/168333?locale=en-US/#/job/a4948ee2-4c2e-4d24-ace3-56b25b0d5093", 2],
  ["mt-workbook-row-87", "EY (Ernst & Young)", "Active", "Ongoing", "https://hkcareers.ey.com.cn/campus-recruitment/ey/168333?locale=en-US/#/job/b64fe85b-aaab-498d-b888-676e21c69f0d", 3],
  ["mt-workbook-row-88", "Gain Miles", "Active", "Ongoing", "https://hk.jobsdb.com/job/94765912?cid=company-profile&ref=company-profile#sol=5b7284de796258d0144879d41d1f708b5b2cb04c", 1],
  ["mt-workbook-row-89", "Gain Miles", "Active", "Ongoing", "https://hk.jobsdb.com/job/94313653?cid=company-profile&ref=company-profile#sol=ae374c8673ebff5506dc7ffb04f148b3151030d1", 2],
  ["mt-workbook-row-90", "KPMG", "Active", "31-Dec-2026", "https://app.mokahr.com/campus-recruitment/kpmg/70399#/job/24a15c47-501c-49a2-b66a-8da90db1c57f", 1],
  ["mt-workbook-row-91", "KPMG", "Active", "31-Dec-2026", "https://app.mokahr.com/campus-recruitment/kpmg/70399#/job/253072dc-6f51-4d66-9bdd-763d3373b34b", 2],
  ["mt-workbook-row-92", "KPMG", "Active", "31-Dec-2026", "https://app.mokahr.com/campus-recruitment/kpmg/70399#/job/837246df-a8fc-4ec6-99c7-e834f0ef58e8", 3],
  ["mt-workbook-row-93", "KPMG", "Active", "30-Jun-2027", "https://app.mokahr.com/campus-recruitment/kpmg/74217#/job/650addd8-6896-4067-bd67-71cc546cc0e3", 4],
  ["mt-workbook-row-94", "KPMG", "Active", "30-Jun-2027", "https://app.mokahr.com/campus-recruitment/kpmg/74217#/job/b10f4525-28ab-4a38-888c-470b43b70a11", 5],
  ["mt-workbook-row-95", "KPMG", "Active", "30-Jun-2027", "https://app.mokahr.com/campus-recruitment/kpmg/74217#/job/fe5860f6-1f38-42b7-9489-e3de838e7de3", 6],
  ["mt-workbook-row-96", "KPMG", "Active", "30-Jun-2027", "https://app.mokahr.com/campus-recruitment/kpmg/74217#/job/99891883-4830-4912-bf55-8dc880d7d914", 7],
  ["mt-workbook-row-97", "Lockton", "Closed", null, "https://careers.lockton.com/early-careers", 1],
  ["mt-workbook-row-98", "Marsh McLennan", "Active", "Ongoing", "https://careers.marsh.com/global/en/job/R_344279/Fiduciary-Account-Assistant-1-year-Contract-role-Open-to-Fresh-Graduates!", 1],
  ["mt-workbook-row-99", "PwC (PricewaterhouseCoopers)", "Active", "Ongoing", "https://www.pwccn.com/en/careers/students.html#graduate", 1],
  ["mt-workbook-row-100", "CBRE", "Closed", null, "https://www.cbre.com.hk/careers/graduate-trainee-programme", 1],
  ["mt-workbook-row-101", "CBRE", "Closed", null, "https://www.cbre.com.hk/careers/cbre-internship-programme", 2],
  ["mt-workbook-row-102", "China Merchants Group", "Active", "Ongoing", "https://cmhk.zhiye.com/custom/xiaoyuan?hideAll=true", 1],
  ["mt-workbook-row-103", "China Merchants Group", "Active", "Ongoing", "https://cmhk.zhiye.com/custom/sxs?hideAll=true", 2],
  ["mt-workbook-row-104", "China Overseas Land & Investment", "Active", "Ongoing", "https://coli688.zhiye.com/campus/detail?jobAdId=e97a2dac-368f-4476-8439-f74f6fa7fda1", 1],
  ["mt-workbook-row-105", "China Resources", "Active", "Ongoing", "https://runjob.crc.com.cn/#/complex/RecruitDetail?id=2097516880552214530&comId=1768465038664790017&typeId=A02", 1],
  ["mt-workbook-row-106", "China Resources", "Active", "Ongoing", "https://runjob.crc.com.cn/#/complex/RecruitDetail?id=2097514884046733315&comId=1768465038664790017&typeId=A02", 2],
  ["mt-workbook-row-107", "China Resources", "Active", "Ongoing", "https://runjob.crc.com.cn/#/complex/RecruitDetail?id=1940589609777709058&comId=1768465038664790017&typeId=A02", 3],
  ["mt-workbook-row-108", "China Resources", "Active", "Ongoing", "https://runjob.crc.com.cn/#/complex/RecruitDetail?id=1927553426336202754&comId=1768465038664790017&typeId=A02", 4],
  ["mt-workbook-row-109", "CK Hutchison", "Active", "Ongoing", "https://hk.jobsdb.com/ck-hutchison-jobs", 1],
  ["mt-workbook-row-110", "Colliers", "Active", "Ongoing", "https://careers.colliers.com/early-careers-students-and-graduates", 1],
  ["mt-workbook-row-111", "Colliers", "Active", "Ongoing", "https://www.colliers.com/en-hk/countries/hong-kong-sar-china/graduate-recruitment", 2],
  ["mt-workbook-row-112", "Cushman & Wakefield", "Closed", null, "https://careers.cushmanwakefield.com/en/life-at-cw/global-early-careers-programs/#APAC", 1],
  ["mt-workbook-row-113", "Hang Lung Properties", "Active", "Ongoing", "https://www.hanglung.com/en-us/careers/management-trainee-program", 1],
  ["mt-workbook-row-114", "Hang Lung Properties", "Closed", null, "https://www.hanglung.com/en-us/careers/internship-program", 2],
  ["mt-workbook-row-115", "Hang Lung Properties", "Active", "Ongoing", "https://careers.hanglung.com/job/Management-Trainee-2027-Hong-Kong-Stream/1430621233/", 3],
  ["mt-workbook-row-116", "Jardine Matheson", "Active", "Ongoing", "https://careers.jardines.com/jets", 1],
  ["mt-workbook-row-117", "JLL (Jones Lang LaSalle)", "Closed", null, "https://www.jll.com/en-hk/careers/early-careers", 1],
  ["mt-workbook-row-118", "Knight Frank", "Closed", null, "https://knightfrankearlycareers.com/", 1],
  ["mt-workbook-row-119", "Knight Frank", "Closed", null, "https://knightfrankearlycareers.com/graduate-schemes/", 2],
  ["mt-workbook-row-120", "Sino Group", "Active", "15-Nov-2026", "https://www.sino.com/en/careers/trainee-programmes/corporate-management-trainee-programme/", 1],
  ["mt-workbook-row-121", "Sino Group", "Active", "15-Nov-2026", "https://www.sino.com/en/careers/internship-programmes/sino-internship-programme/", 2],
  ["mt-workbook-row-122", "Sino Group", "Active", "15-Nov-2026", "https://www.sino.com/en/careers/trainee-programmes/engineer-trainee-programme/", 3],
  ["mt-workbook-row-123", "Sun Hung Kai Properties (SHKP)", "Active", "01-Nov-2026", "https://www.shkp.com/en-US/work-with-us/executive-trainee-programme", 1],
  ["mt-workbook-row-124", "Sun Hung Kai Properties (SHKP)", "Active", "Ongoing", "https://www.shkp.com/en-US/work-with-us/graduate-engineer-structural-hong-kong", 2],
  ["mt-workbook-row-125", "Swire", "Active", "31-Jan-2027", "https://careers.swire.com/zh-hk/careers/swire-summer-internship-programme", 1],
  ["mt-workbook-row-126", "Swire", "Active", "31-Oct-2026", "https://careers.swire.com/zh-hk/careers/swire-management-programme", 2],
  ["mt-workbook-row-127", "Swire", "Active", "Ongoing", "https://careers.swire.com/zh-hk/careers/scsi2026", 3],
  ["mt-workbook-row-128", "The Wharf Group", "N/A", null, "https://www.wharfreic.com/en/about_us/careers", 1],
  ["mt-workbook-row-129", "Bayer", "Closed", null, "https://talent.bayer.com/careers?location=Hong%20Kong%2CHong%20Kong%2CHong%20Kong%20%28China%29&job%20type=student&domain=bayer.com&sort_by=relevance&triggerGoButton=true", 1],
  ["mt-workbook-row-130", "DFI Retail Group", "Active", "Ongoing", "https://dfiretailgroup.avature.net/en_US/careers/JobDetail/Hong-Kong-Store-Trainee-Manager/15542", 1],
  ["mt-workbook-row-131", "DFI Retail Group", "Active", "Ongoing", "https://www.dfiretailgroup.com/en/careers-at-dfi/talent-programmes/", 2],
  ["mt-workbook-row-132", "DKSH", "Active", "Ongoing", "https://www.dksh.com/global-en/home/careers/early-careers", 1],
  ["mt-workbook-row-133", "Li & Fung", "Active", "Ongoing", "https://lifung.wd3.myworkdayjobs.com/zh-CN/FungGroup/jobs/details/Intern---Part-time---Fashion-Design_V98190?q=intern&locationCountry=d4afdeb461d446e4babd204bd102dba8", 1],
  ["mt-workbook-row-134", "L'Oréal", "Closed", null, "https://careers.loreal.com/en_US/jobs/SearchJobs?3_33_3=136&3_110_3=161554", 1],
  ["mt-workbook-row-135", "Maxim's Group", "Active", "Ongoing", "https://www.maxims.com.hk/en/careers#studentsgraduates", 1],
  ["mt-workbook-row-136", "Pfizer", "Closed", null, "https://pfizer.wd1.myworkdayjobs.com/zh-CN/PfizerCareers?q=hongkong", 1],
  ["mt-workbook-row-137", "Reckitt", "Closed", null, "https://www.reckitt.com/careers/students-and-graduates/internships/", 1],
  ["mt-workbook-row-138", "Reckitt", "Closed", null, "https://www.reckitt.com/careers/students-and-graduates/graduates/", 2],
  ["mt-workbook-row-139", "Reckitt", "Closed", null, "https://careers.reckitt.com/go/Graduates-&-Interns_gb/3895301/", 3],
  ["mt-workbook-row-140", "Edelman", "Active", "Ongoing", "https://djeholdings.wd5.myworkdayjobs.com/zh-CN/edelman-careers-E200/details/Design-Intern_JR103415?locations=9aea86bf32a11001b496ac3721f90000", 1],
  ["mt-workbook-row-141", "Edelman", "Active", "Ongoing", "https://djeholdings.wd5.myworkdayjobs.com/zh-CN/edelman-careers-E200/details/Brand-Intern_JR103424-1?locations=9aea86bf32a11001b496ac3721f90000", 2],
  ["mt-workbook-row-142", "Edelman", "Active", "Ongoing", "https://djeholdings.wd5.myworkdayjobs.com/zh-CN/edelman-careers-E200/details/Corporate-Brand-Intern_JR103422?locations=9aea86bf32a11001b496ac3721f90000", 3],
  ["mt-workbook-row-143", "FDM Group", "Active", "Ongoing", "https://www.fdmgroup.com/candidates/graduate-programme/", 1],
  ["mt-workbook-row-144", "FDM Group", "Active", "Ongoing", "https://www.fdmgroup.com/candidates/apprenticeship-programme/", 2],
  ["mt-workbook-row-145", "HKBN (Hong Kong Broadband Network)", "N/A", null, "https://hk.jobsdb.com/HKBN-Ltd-jobs", 1],
  ["mt-workbook-row-146", "HKT (Hong Kong Telecom)", "Active", "Ongoing", "https://job.pccw.com/hkt/content/Technology-Stream---Information-Technology/", 1],
  ["mt-workbook-row-147", "HKT (Hong Kong Telecom)", "Active", "Ongoing", "https://job.pccw.com/hkt/content/Business-Stream---Digital-Ventures/", 2],
  ["mt-workbook-row-148", "HKT (Hong Kong Telecom)", "Active", "Ongoing", "https://job.pccw.com/hkt/job/Hong-Kong-Payroll-Intern-HK/1367397066/", 3],
  ["mt-workbook-row-149", "HKT (Hong Kong Telecom)", "Active", "Ongoing", "https://job.pccw.com/hkt/job/Hong-Kong-Data-Analyst-HK/1361229966/", 4],
  ["mt-workbook-row-150", "PCCW", "Active", "Ongoing", "https://job.pccw.com/hkt/search/?q=Hong+Kong+internship", 1],
  ["mt-workbook-row-151", "Publicis Groupe", "Closed", null, "https://jobs.ctgoodjobs.hk/job/10098900/summer-internship-program-2026", 1],
  ["mt-workbook-row-152", "Cathay Pacific", "Active", "15-Nov-2026", "https://careers.cathaypacific.com/cn/careers/our-teams/early-careers-students-and-graduates/graduate-trainee#tabPageContent-tab-01-tabhttps://careers.cathaypacific.com/cn/careers/our-teams/early-careers-students-and-graduates#tabPageContent-tab-02-tab", 1],
  ["mt-workbook-row-153", "Cathay Pacific", "Active", "15-Nov-2026", "https://careers.cathaypacific.com/cn/careers/our-teams/early-careers-students-and-graduates/graduate-trainee#tabPageContent-tab-01-tab", 2],
  ["mt-workbook-row-154", "Cathay Pacific", "Active", "15-Nov-2026", "https://careers.cathaypacific.com/cn/careers/our-teams/early-careers-students-and-graduates/graduate-trainee#tabPageContent-tab-02-tab", 3],
  ["mt-workbook-row-155", "Cathay Pacific", "Active", "15-Nov-2026", "https://careers.cathaypacific.com/cn/careers/our-teams/early-careers-students-and-graduates/graduate-trainee#tabPageContent-tab-04-tab", 4],
  ["mt-workbook-row-156", "DSV", "Closed", null, "https://www.dsv.com/zh-cn/careers/job-areas/trainee-programmes", 1],
  ["mt-workbook-row-157", "HKIA (Hong Kong International Airport / Airport Authority)", "Closed", null, "https://www.hongkongairport.com/en/careers/programmes/management-trainee.page", 1],
  ["mt-workbook-row-158", "HKIA (Hong Kong International Airport / Airport Authority)", "Closed", null, "https://www.hongkongairport.com/en/careers/programmes/graduate-engineer.page", 2],
  ["mt-workbook-row-159", "HKIA (Hong Kong International Airport / Airport Authority)", "Closed", null, "https://www.hongkongairport.com/en/careers/programmes/it-trainee.page", 3],
  ["mt-workbook-row-160", "HKIA (Hong Kong International Airport / Airport Authority)", "Closed", null, "https://www.hongkongairport.com/en/careers/programmes/internship.page", 4],
  ["mt-workbook-row-161", "ISS Facility Services", "Closed", null, "https://www.hk.issworld.com/join-iss_career-at-iss", 1],
  ["mt-workbook-row-162", "ISS Facility Services", "Closed", null, "https://www.hk.issworld.com/join-iss-graduate-management-trainee-programme", 2],
  ["mt-workbook-row-163", "ISS Facility Services", "Closed", null, "https://www.hk.issworld.com/join-iss-graduate-management-trainee-programme", 3],
  ["mt-workbook-row-164", "ISS Facility Services", "Closed", null, "https://www.hk.issworld.com/join-iss-graduate-management-trainee-programme", 4],
  ["mt-workbook-row-165", "MTR Corporation", "Active", "27-Oct-2026", "https://mtr.com.hk/en/corporate/careers/programme_apply.html", 1],
  ["mt-workbook-row-166", "MTR Corporation", "Closed", null, "https://www.mtr.com.hk/summer-internship-programme/en/programA.html", 2],
  ["mt-workbook-row-167", "MTR Corporation", "Closed", null, "https://www.mtr.com.hk/en/corporate/careers/internship.html", 3],
  ["mt-workbook-row-168", "MTR Corporation", "Closed", null, "http://www.mtr.com.hk/mtr_job_en", 4],
  ["mt-workbook-row-169", "MTR Corporation", "Closed", null, "http://www.mtr.com.hk/mtr_job_en", 5],
  ["mt-workbook-row-170", "Pattern", "N/A", null, "https://au.pattern.com/about/careers/", 1],
]

export const MT_WORKBOOK_PROGRAMMES: readonly MTWorkbookProgramme[] = rows.map(
  ([id, company, status, deadline, applicationUrl, employerLinkNumber]) => ({
    id, company, status, deadline, applicationUrl, employerLinkNumber,
  }),
)

// This is an editorial ordering for candidates, not a claim of a formal league
// table. It prioritises the relative pull of each employer's Hong Kong early-
// career platform; status still determines which section a card belongs to.
const PRESTIGE_ORDER = [
  'Goldman Sachs',
  'Morgan Stanley',
  'UBS',
  'Bank of America (BofA)',
  'HSBC',
  'HKEX (Hong Kong Exchanges and Clearing)',
  'Standard Chartered',
  'Jardine Matheson',
  'Swire',
  'Cathay Pacific',
  'Jefferies',
  'Fidelity International',
  'Mizuho',
  'MUFG (Mitsubishi UFJ Financial Group)',
  'Société Générale',
  'CLSA',
  'BOC International (BOCI)',
  'CMB International',
  'Huatai International',
  'China Construction Bank (Asia)',
  'Bank of China (Hong Kong) [BOCHK]',
  'Hang Seng Bank',
  'The Bank of East Asia (BEA)',
  'CMB Wing Lung Bank',
  'Invesco Asia',
  'CSOP Asset Management',
  'Deloitte',
  'PwC (PricewaterhouseCoopers)',
  'EY (Ernst & Young)',
  'KPMG',
  'Marsh McLennan',
  'Aon',
  'CK Hutchison',
  'China Merchants Group',
  'China Resources',
  'China Overseas Land & Investment',
  'Sun Hung Kai Properties (SHKP)',
  'Hang Lung Properties',
  'Sino Group',
  'The Wharf Group',
  'CBRE',
  'JLL (Jones Lang LaSalle)',
  'Cushman & Wakefield',
  'Colliers',
  'Knight Frank',
  'MTR Corporation',
  'HKIA (Hong Kong International Airport / Airport Authority)',
  'Bayer',
  'Pfizer',
  "L'Oréal",
  'Reckitt',
  'DFI Retail Group',
  'Li & Fung',
  "Maxim's Group",
  'DKSH',
  'Edelman',
  'Publicis Groupe',
  'ION Group',
  'RedotPay',
  'FDM Group',
  'HKT (Hong Kong Telecom)',
  'PCCW',
  'HKBN (Hong Kong Broadband Network)',
  'Computershare',
  'BOCOM International',
  'Lockton',
  'ISS Facility Services',
  'DSV',
  'Gain Miles',
  'Pattern',
] as const

const PRESTIGE_RANK = new Map<string, number>(PRESTIGE_ORDER.map((company, index) => [company, index]))

export function compareMTProgrammePrestige(a: MTWorkbookProgramme, b: MTWorkbookProgramme) {
  const aRank = PRESTIGE_RANK.get(a.company) ?? Number.MAX_SAFE_INTEGER
  const bRank = PRESTIGE_RANK.get(b.company) ?? Number.MAX_SAFE_INTEGER
  return aRank - bRank || a.company.localeCompare(b.company)
}

export function groupMTWorkbookProgrammesByEmployer(
  programmes: readonly MTWorkbookProgramme[],
): MTWorkbookEmployer[] {
  const byEmployer = new Map<string, MTWorkbookProgramme[]>()

  for (const programme of programmes) {
    const employerProgrammes = byEmployer.get(programme.company) ?? []
    employerProgrammes.push(programme)
    byEmployer.set(programme.company, employerProgrammes)
  }

  return [...byEmployer.entries()].map(([company, employerProgrammes]) => ({
    company,
    programmes: employerProgrammes.sort((a, b) => a.employerLinkNumber - b.employerLinkNumber),
  }))
}

export function findMTWorkbookEmployerBySlug(slug: string): MTWorkbookEmployer | undefined {
  return groupMTWorkbookProgrammesByEmployer(MT_WORKBOOK_PROGRAMMES)
    .find(employer => mtEmployerSlug(employer.company) === slug)
}
