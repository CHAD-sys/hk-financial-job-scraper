export interface MTCompanyLogo {
  /** A high-resolution official or established brand asset. */
  src?: string
  /** A crisp text fallback beats a low-resolution favicon. */
  wordmark: string
}

const COMPANY_LOGOS: readonly [RegExp, MTCompanyLogo][] = [
  [/hong kong monetary authority|\bhkma\b/i, { src: 'https://www.hkma.gov.hk/statics/assets/img/logo.jpg', wordmark: 'HKMA' }],
  [/bank of china \(hong kong\)|\bbochk\b/i, { src: 'https://beltandroad.hktdc.com/sites/default/files/bloggers/2019-10/BOCHK_Horizontal_Revised.jpg', wordmark: 'BOCHK' }],
  [/bank of east asia|\bbea\b/i, { wordmark: 'BEA 東亞銀行' }],
  [/hong kong jockey club|\bhkjc\b/i, { src: 'https://www.theofficialboard.com/img/twitterCompanyBigImages/36713.jpg', wordmark: 'HKJC' }],
  [/hang seng indexes/i, { wordmark: 'HANG SENG INDEXES' }],
  [/hang seng/i, { src: 'https://images.seeklogo.com/logo-png/6/1/hang-seng-bank-logo-png_seeklogo-65039.png', wordmark: 'HANG SENG' }],
  [/smartone/i, { wordmark: 'SmarTone' }],
  [/hang lung/i, { src: 'https://www.hanglung.com/getmedia/cfd2433a-11a3-46d2-b0a8-260b77554946/20200909_Hang-Lung-Logo.jpg', wordmark: 'HANG LUNG' }],
  [/\bboci\b/i, { wordmark: 'BOCI' }],
  [/\baia\b/i, { src: 'https://www.aia.com.hk/content/dam/group-wise/images/system/icons/aia-logo-red.svg', wordmark: 'AIA' }],
  [/hyatt/i, { wordmark: 'HYATT' }],
  [/standard chartered|\bscb\b/i, { wordmark: 'STANDARD CHARTERED' }],
  [/\bhsbc\b/i, { src: 'https://cdn.jsdelivr.net/npm/simple-icons@v14/icons/hsbc.svg', wordmark: 'HSBC' }],
]

export function mtCompanyLogo(company: string): MTCompanyLogo {
  return COMPANY_LOGOS.find(([pattern]) => pattern.test(company))?.[1] ?? { wordmark: company }
}
