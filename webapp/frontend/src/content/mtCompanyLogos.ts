export interface MTCompanyLogo {
  /** Locally optimised colour mark for fast, stable rendering. */
  src?: string
  /** Used only if the local asset cannot load. */
  wordmark: string
}

const COMPANY_LOGO_FILES: Readonly<Record<string, string>> = {
  'Bank of America (BofA)': '/company-logos/bank-of-america.webp',
  'BOC International (BOCI)': '/company-logos/boci.webp',
  'Goldman Sachs': '/company-logos/goldman-sachs.webp',
  'Huatai International': '/company-logos/huatai-international.webp',
  Jefferies: '/company-logos/jefferies.webp',
  'Morgan Stanley': '/company-logos/morgan-stanley.webp',
  'Société Générale': '/company-logos/societe-generale.webp',
  UBS: '/company-logos/ubs.webp',
  'Bank of China (Hong Kong) [BOCHK]': '/company-logos/bochk.webp',
  'China Construction Bank (Asia)': '/company-logos/china-construction-bank.webp',
  'CMB Wing Lung Bank': '/company-logos/cmb-wing-lung.webp',
  'Hang Seng Bank': '/company-logos/hang-seng.webp',
  HSBC: '/company-logos/hsbc.webp',
  'MUFG (Mitsubishi UFJ Financial Group)': '/company-logos/mufg.webp',
  'Standard Chartered': '/company-logos/standard-chartered.png',
  'The Bank of East Asia (BEA)': '/company-logos/bea.webp',
  'CSOP Asset Management': '/company-logos/csop.webp',
  'Fidelity International': '/company-logos/fidelity.webp',
  'HKEX (Hong Kong Exchanges and Clearing)': '/company-logos/hkex.webp',
  'Invesco Asia': '/company-logos/invesco.webp',
  'ION Group': '/company-logos/ion.webp',
  RedotPay: '/company-logos/redotpay.webp',
  Aon: '/company-logos/aon.webp',
  Deloitte: '/company-logos/deloitte.webp',
  Ekimetrics: '/company-logos/ekimetrics.webp',
  'EY (Ernst & Young)': '/company-logos/ey.webp',
  'Gain Miles': '/company-logos/gain-miles.webp',
  KPMG: '/company-logos/kpmg.webp',
  'Marsh McLennan': '/company-logos/marsh-mclennan.webp',
  'PwC (PricewaterhouseCoopers)': '/company-logos/pwc.webp',
  'China Merchants Group': '/company-logos/china-merchants.webp',
  'China Overseas Land & Investment': '/company-logos/china-overseas.webp',
  'China Resources': '/company-logos/china-resources.webp',
  'CK Hutchison': '/company-logos/ck-hutchison.webp',
  Colliers: '/company-logos/colliers.webp',
  'Hang Lung Properties': '/company-logos/hang-lung.webp',
  'Jardine Matheson': '/company-logos/jardine-matheson.webp',
  'Sino Group': '/company-logos/sino.webp',
  'Sun Hung Kai Properties (SHKP)': '/company-logos/shkp.webp',
  Swire: '/company-logos/swire.webp',
  'DFI Retail Group': '/company-logos/dfi.webp',
  DKSH: '/company-logos/dksh.webp',
  'Li & Fung': '/company-logos/li-fung.webp',
  "Maxim's Group": '/company-logos/maxims.webp',
  Edelman: '/company-logos/edelman.webp',
  'FDM Group': '/company-logos/fdm.webp',
  'HKT (Hong Kong Telecom)': '/company-logos/hkt.webp',
  PCCW: '/company-logos/pccw.webp',
  'Cathay Pacific': '/company-logos/cathay.webp',
  'MTR Corporation': '/company-logos/mtr.webp',
}

export function mtCompanyLogo(company: string): MTCompanyLogo {
  const src = COMPANY_LOGO_FILES[company]
  return src ? { src, wordmark: company } : { wordmark: company }
}
