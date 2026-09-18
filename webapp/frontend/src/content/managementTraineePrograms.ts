import { MT_PROGRAMME_LINKS } from './managementTraineeLinks'
import { MT_APPLICATION_STATUS } from './mtApplicationStatus'
import type { MTApplicationSnapshot } from './mtApplicationStatus'

export type MTIndustry =
  | 'Investment Banking & Capital Markets'
  | 'Commercial & Retail Banking'
  | 'Asset Management, Financial Services & FinTech'
  | 'Accounting, Audit & Professional Consulting'
  | 'Conglomerates, Real Estate & Property Management'
  | 'Retail, FMCG, Healthcare & Consumer Goods'
  | 'Telecommunications, Technology & Media'
  | 'Aviation, Transportation, Logistics & Infrastructure'

export interface MTProgramme {
  id: string
  company: string
  companyChinese: string
  industry: MTIndustry
  featured?: boolean
  programmeName?: string
  applicationUrls: readonly string[]
  /** One best destination only: a directory should not make applicants choose
   * between multiple stale or generic workbook links. */
  masterApplicationUrl?: string
  linksVerified?: boolean
  application?: MTApplicationSnapshot
}

type MTProgrammeRow = Omit<MTProgramme, 'applicationUrls'>

export function selectMasterApplicationUrl(
  urls: readonly string[],
  application?: MTApplicationSnapshot,
): string | undefined {
  if (application?.sourceUrl && urls.includes(application.sourceUrl)) return application.sourceUrl
  return [...urls].sort((left, right) => score(right) - score(left))[0]
}

function score(url: string): number {
  const value = url.toLowerCase()
  let valueScore = 0
  if (/management[-_/ ]trainee|manager[-_/ ]trainee/.test(value)) valueScore += 100
  if (/details\.html|\/job\/|jobdetail|\/apply\b/.test(value)) valueScore += 60
  if (/graduate[-_/ ](?:programme|program|analyst|trainee)/.test(value)) valueScore -= 80
  if (/intern/.test(value)) valueScore -= 80
  if (/search|campus|career\/?$/.test(value)) valueScore -= 15
  return valueScore
}

const rows = (
  industry: MTIndustry,
  companies: Array<[string, string, boolean?]>,
): MTProgrammeRow[] => companies.map(([company, companyChinese, featured]) => ({
  id: company.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, ''),
  company,
  companyChinese,
  industry,
  featured,
}))

const MT_PROGRAMME_ROWS: MTProgrammeRow[] = [
  ...rows('Investment Banking & Capital Markets', [
    ['Bank of America (BofA)', '美國銀行 / 美銀證券'], ['BOC International (BOCI)', '中銀國際'],
    ['BOCOM International', '交銀國際'], ['CLSA', '中信里昂證券'], ['CMB International', '招銀國際'],
    ['Goldman Sachs', '高盛'], ['Huatai International', '華泰國際'], ['Jefferies', '傑富瑞'],
    ['Mizuho', '瑞穗證券'], ['Morgan Stanley', '摩根士丹利', true], ['Société Générale', '法國興業銀行'], ['UBS', '瑞銀'],
  ]),
  ...rows('Commercial & Retail Banking', [
    ['Bank of China (Hong Kong) [BOCHK]', '中銀香港'], ['China Construction Bank (Asia)', '中國建設銀行（亞洲）'],
    ['CMB Wing Lung Bank', '招商永隆銀行'], ['Hang Seng Bank', '恒生銀行'], ['HSBC', '滙豐銀行', true],
    ['MUFG (Mitsubishi UFJ Financial Group)', '三菱 UFJ 銀行'], ['Standard Chartered', '渣打銀行'], ['The Bank of East Asia (BEA)', '東亞銀行'],
  ]),
  ...rows('Asset Management, Financial Services & FinTech', [
    ['CSOP Asset Management', '南方東英'], ['Fidelity International', '富達國際'],
    ['HKEX (Hong Kong Exchanges and Clearing)', '香港交易所', true], ['Invesco Asia', '景順亞洲'],
    ['ION Group', 'ION Group'], ['RedotPay', 'RedotPay'],
  ]),
  ...rows('Accounting, Audit & Professional Consulting', [
    ['Aon', '安昂'], ['Computershare', '香港中央證券（Computershare）'], ['Deloitte', '德勤'],
    ['Ekimetrics', 'Ekimetrics'], ['EY (Ernst & Young)', '安永'], ['Gain Miles', '駿隆'], ['KPMG', '畢馬威'],
    ['Lockton', '諾信'], ['Marsh McLennan', '達信麥克倫南'], ['PwC (PricewaterhouseCoopers)', '普華永道'],
  ]),
  ...rows('Conglomerates, Real Estate & Property Management', [
    ['CBRE', '世邦魏理仕'], ['China Merchants Group', '招商局集團'], ['China Overseas Land & Investment', '中海地產'],
    ['China Resources', '華潤集團'], ['CK Hutchison', '長江和記'], ['Colliers', '高力國際'],
    ['Cushman & Wakefield', '戴德梁行'], ['Hang Lung Properties', '恒隆地產'], ['Jardine Matheson', '怡和集團'],
    ['JLL (Jones Lang LaSalle)', '仲量聯行'], ['Knight Frank', '萊坊'], ['Sino Group', '信和集團'],
    ['Sun Hung Kai Properties (SHKP)', '新鴻基地產'], ['Swire', '太古集團'], ['The Wharf Group', '九龍倉集團'],
  ]),
  ...rows('Retail, FMCG, Healthcare & Consumer Goods', [
    ['Bayer', '拜耳'], ['DFI Retail Group', '牛奶公司集團（DFI 零售集團）'], ['DKSH', '大昌華嘉'],
    ['Li & Fung', '利豐集團'], ["L'Oréal", '歐萊雅'], ["Maxim's Group", '美心集團'], ['Pfizer', '輝瑞'], ['Reckitt', '利潔時'],
  ]),
  ...rows('Telecommunications, Technology & Media', [
    ['Edelman', '愛德曼'], ['FDM Group', 'FDM 集團'], ['HKBN (Hong Kong Broadband Network)', '香港寬頻'],
    ['HKT (Hong Kong Telecom)', '香港電訊'], ['PCCW', '電訊盈科'], ['Publicis Groupe', '陽獅集團'],
  ]),
  ...rows('Aviation, Transportation, Logistics & Infrastructure', [
    ['Cathay Pacific', '國泰航空', true], ['DSV', 'DSV 國際物流'],
    ['HKIA (Hong Kong International Airport / Airport Authority)', '香港國際機場 / 機場管理局'],
    ['ISS Facility Services', 'ISS 設施管理'], ['MTR Corporation', '港鐵公司'], ['Pattern', 'Pattern'],
  ]),
  {
    id: 'the-hong-kong-jockey-club-hkjc',
    company: 'The Hong Kong Jockey Club (HKJC)',
    companyChinese: '香港賽馬會',
    industry: 'Conglomerates, Real Estate & Property Management',
    featured: true,
    programmeName: 'Management Trainee',
    linksVerified: true,
  },
  {
    id: 'hong-kong-monetary-authority-hkma',
    company: 'Hong Kong Monetary Authority (HKMA)',
    companyChinese: '香港金融管理局',
    industry: 'Asset Management, Financial Services & FinTech',
    featured: true,
    programmeName: 'Manager Trainee Programme',
    linksVerified: true,
  },
]

const isDirectManagementTraineeProgramme = (urls: readonly string[]) => urls.some(url => {
  const value = url.toLowerCase()
  return /(management|manager)[-_/ ]trainee/.test(value)
    && !/graduate[-_/ ](?:management|manager)[-_/ ]trainee/.test(value)
})

export const MT_PROGRAMMES: MTProgramme[] = MT_PROGRAMME_ROWS.map(programme => ({
  ...programme,
  applicationUrls: MT_PROGRAMME_LINKS[programme.id] ?? [],
  application: MT_APPLICATION_STATUS[programme.id],
  masterApplicationUrl: selectMasterApplicationUrl(
    MT_PROGRAMME_LINKS[programme.id] ?? [], MT_APPLICATION_STATUS[programme.id],
  ),
})).filter(programme => isDirectManagementTraineeProgramme(programme.applicationUrls))

export const MT_INDUSTRIES = [...new Set(MT_PROGRAMMES.map(programme => programme.industry))]
export const FEATURED_MT_PROGRAMMES = MT_PROGRAMMES.filter(programme => programme.featured)
export const LINKED_MT_PROGRAMMES = MT_PROGRAMMES.filter(programme => programme.applicationUrls.length > 0)
export const VERIFIED_MT_PROGRAMMES = MT_PROGRAMMES.filter(programme => programme.linksVerified)
