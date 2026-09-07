import type { Job, WeeklyHighlightRole } from '../../api/client'

/** Static editorial material and adapters for the server-locked weekly Roles. */

/** Every card is one of these four. The shell is shared; the body is not. */
export type HighlightKind = 'role' | 'coach' | 'video' | 'course'

interface HighlightBase {
  id: string
  kind: HighlightKind
  /** Where the whole card goes when clicked. Never a dead card. */
  href: string
}

export interface RoleHighlight extends HighlightBase {
  kind: 'role'
  /** The exact granted Role travels through React Router state on normal taps. */
  job: Job
  company: string
  title: string
  /** Editorial desk label. Deliberately NOT `job_category`, whose vocabulary
   *  ("Finance", "Other") is too coarse to be worth a chip on a hero card. */
  desk: string
  seniority: string
  location: string
}

export interface CoachHighlight extends HighlightBase {
  kind: 'coach'
  name: string
  role: string
  focus: string
  image: string
}

export interface VideoHighlight extends HighlightBase {
  kind: 'video'
  title: string
  topic: string
  thumbnail: string
}

export interface CourseHighlight extends HighlightBase {
  kind: 'course'
  title: string
  venue: string
  date: string
  image: string
}

export type Highlight = RoleHighlight | CoachHighlight | VideoHighlight | CourseHighlight

/** Wix serves responsive transforms from the original asset. Keeping the
 * source URL here lets the coach rail show the official portrait at a sharp,
 * appropriately small size without copying 32 third-party image files into
 * this app. */
const coachImage = (asset: string, name: string) => {
  const extension = asset.endsWith('.jpg') ? '.jpg' : '.png'
  return `https://static.wixstatic.com/media/${asset}/v1/fill/w_280,h_280,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/${encodeURIComponent(name)}${extension}`
}

const roleHref = (source: string, sourceId: string, relatedSearch: string) => {
  const params = new URLSearchParams({
    q: relatedSearch,
    role_source: source,
    role_id: sourceId,
  })
  return `/jobs?${params.toString()}`
}

export function roleHighlightFromApi(entry: WeeklyHighlightRole): RoleHighlight {
  const { role } = entry
  return {
    id: `role-${role.source}-${role.source_id}`,
    kind: 'role',
    href: roleHref(role.source, role.source_id, entry.related_search),
    job: role,
    company: role.company,
    title: role.title_en || role.title,
    desk: entry.related_search,
    seniority: role.seniority || 'Experienced',
    location: role.locations[0] || 'Hong Kong',
  }
}

/** The Role rail mirrors the server's immutable editorial order exactly. */
export function mergeWeeklyHighlights(entries: WeeklyHighlightRole[]): Highlight[] {
  return entries.map(roleHighlightFromApi)
}

export const YOUTUBE_CHANNEL_URL = 'https://www.youtube.com/@finexclubhq'
export const COMMITTEE_PLAYLIST_URL = 'https://www.youtube.com/playlist?list=PLr56SwqMOvcsbMULkrC2ArgIB4MeCjV70'

const video = (id: string, title: string, topic: string): VideoHighlight => ({
  id: `video-${id}`,
  kind: 'video',
  href: `https://www.youtube.com/watch?v=${id}`,
  title,
  topic,
  thumbnail: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`,
})

/** FinEx Club's requested video collection. The repeated SEVKQL6Ag8I URL in
 * the source list is represented once, so the rail never shows a duplicate. */
export const VIDEO_HIGHLIGHTS: VideoHighlight[] = [
  video('alQ0eelrn1E', 'Part 2: Fed Rate Policy 2026 | Gold Sensitivity and Allocation', 'Macro & markets'),
  video('qUuzybEQdlE', '【CEO Podcast】Eleanor Wan’s extraordinary career and the evolution of global asset management', 'CEO podcast'),
  video('6g0FAqKApMM', '【Part 2】Leadership and career progression: from entry-level to board executive', 'Leadership'),
  video('m5Bntb8ZMWY', '與CUHK商學院助理院長對話：當代商業教育與高管教育如何擴展全球視野', 'Executive education'),
  video('B72UtQTBX3M', '哈佛金融高管人生逆轉的真實故事：毫無背景卻闖進 Harvard 與 UC Berkeley', 'Career stories'),
  video('x1q7-q1Ebnc', 'Banking models, fintech, supply chains and advice to young bankers', 'Banking & fintech'),
  video('lmePYW_eBjs', 'CEO Talk：數字資產與傳統金融如何交滙融合', 'Digital assets'),
  video('ZJp5UK1wog0', 'APAC CEO Talk: the evolution and defining moments of asset servicing', 'Securities services'),
  video('MCicagWuFGI', 'Part 2：私募世界創新型基金、投資分紅、透明度與風險管理', 'Private markets'),
  video('SWVGD9z4iAI', 'Part 1：Private Equity and Private Credit in portfolio allocation', 'Private markets'),
  video('K4aZUhRrYO8', 'Trustee CEO 解讀 2025 強積金資金流向、最佳基金與 2026 大事件', 'Pensions'),
  video('1Q9Dzs3Ysv4', '直擊 Saudi FII 2025：第一視角分析中東市場與嶄新投資機遇', 'Global markets'),
  video('TfmOMTNadeY', 'Treasurers’ Insight: navigating the work dynamics of finance executives', 'Treasury'),
  video('yLVerwMgUb4', 'Accountant and Lawyer unlock the skills that make a great leader', 'Leadership'),
  video('BcsaChO2z9A', '保險公司的精算部、投資部與風控部到底如何運作？', 'Insurance'),
  video('Mc6Pc0GlpMI', 'Cambridge Professor on climate change and sustainability strategies', 'Sustainability'),
  video('6hQHzK5Jd6A', '信託與法務：Unit Trust、Declaration of Trust 與 Private Trust 精解', 'Trust & legal'),
  video('DrLhZQj2UGQ', 'Citi MD unpacks stablecoin’s impact on global banking and finance', 'Stablecoins'),
  video('SEVKQL6Ag8I', 'Web3.0 大時代：銀行戰略佈署對抗鏈上交易衝擊', 'Web3'),
  video('iZ1EyIODvaA', 'Web3.0：正確認識穩定幣、央行數字貨幣與代幣化存款', 'FinEx Research'),
]

/** The full public FinEx Club coach roster. Each card keeps its official
 * destination, so a visitor can go straight to that coach's profile rather
 * than landing on a generic enquiry page. */
export const COACH_HIGHLIGHTS: CoachHighlight[] = [
  { id: 'coach-01', kind: 'coach', name: 'Andrew Chan', role: 'Governor, HK Institute of Internal Auditors; Head of Internal Audit & Risk Management (former)', focus: 'Internal Audit · Risk & Governance', image: coachImage('e83ee7_402d698ee3f84fc1805d7624937cf316~mv2.jpg', 'Andrew Chan'), href: 'https://www.finexclub.org/andrew-chan' },
  { id: 'coach-02', kind: 'coach', name: 'Apple Lo', role: 'Group Director, Financial and Credit Risk', focus: 'Credit Risk & Ratings · ESG · Investment Banking', image: coachImage('e83ee7_d7ba510d91174c1cbee1fb9db27fc2b4~mv2.png', 'Apple Lo'), href: 'https://www.finexclub.org/career-coach/apple-lo' },
  { id: 'coach-03', kind: 'coach', name: 'Arthur Tan', role: 'Executive Director (former)', focus: 'Institutional Banking · Sales & Client Coverage', image: coachImage('e83ee7_271a7e3db31e4dee84d76d9b48d5e0ac~mv2.jpg', 'Arthur Tan'), href: 'https://www.finexclub.org/career-coach/arthur-tan' },
  { id: 'coach-04', kind: 'coach', name: 'Benjamin Chung', role: 'Chief Risk Officer', focus: 'Enterprise Risk Management · Insurance · Asset Management', image: coachImage('e83ee7_37367b82a568428ba68e3d789dd2b6f2~mv2.png', 'Benjamin Chung'), href: 'https://www.finexclub.org/career-coach/benjamin-chung' },
  { id: 'coach-05', kind: 'coach', name: 'Biswajyoti (BJ) Upadhyay', role: 'Managing Director & Regional Head (former)', focus: 'Institutional Banking · Regional Sales & Transformation', image: coachImage('e83ee7_85cb41a419934d75a6e8ac59a5832425~mv2.png', 'Biswajyoti (BJ) Upadhyay (based in Dubai)'), href: 'https://www.finexclub.org/bj-upadhyay' },
  { id: 'coach-06', kind: 'coach', name: 'Byron Gardiner', role: 'Executive Director / Global Head (former)', focus: 'Treasury & Banking · Corporate Treasury Advisory', image: coachImage('e83ee7_d0535f305b53452eb02240ed956f3ecd~mv2.png', 'Byron Gardiner (based in Singapore)'), href: 'https://www.finexclub.org/byron-gardiner' },
  { id: 'coach-07', kind: 'coach', name: 'Calvin Lee', role: 'Financial Controller & Head of Finance (former)', focus: 'Finance & Accounting · Strategic Planning', image: coachImage('e83ee7_8292059406c449f4a956a5d64ce22dfc~mv2.png', 'Calvin Lee'), href: 'https://www.finexclub.org/calvin-lee' },
  { id: 'coach-08', kind: 'coach', name: 'Cammy Tong', role: 'Senior Regional Director & Head of Life Insurance', focus: 'Insurance & Operations · Customer Experience', image: coachImage('e83ee7_b0c20b5acf154325a22aa6d5fa9673a5~mv2.png', 'Cammy Tong'), href: 'https://www.finexclub.org/career-coach/cammy-tong' },
  { id: 'coach-09', kind: 'coach', name: 'Connie Mak', role: 'Head of Relationship Management (former)', focus: 'Securities Services · Client Relationship Management', image: coachImage('e83ee7_62a368184e3e4ecf98adce7044452d7e~mv2.png', 'Connie Mak'), href: 'https://www.finexclub.org/connie-mak' },
  { id: 'coach-10', kind: 'coach', name: 'Dennis Luk', role: 'Chief Investment Officer', focus: 'Life Insurance · Investment Management', image: coachImage('e83ee7_6bd302864ab343e5a3bb0bca6fa475b6~mv2.png', 'Dennis Luk'), href: 'https://www.finexclub.org/dennis-luk' },
  { id: 'coach-11', kind: 'coach', name: 'Dicky Lee', role: 'CFO & Head of Operations', focus: 'Finance & Operations Leadership', image: coachImage('e83ee7_1261dbda39d74d64bd8d75ce8ffb112b~mv2.png', 'Dicky Lee'), href: 'https://www.finexclub.org/dicky-lee' },
  { id: 'coach-12', kind: 'coach', name: 'Doris Kuo', role: 'Business Consultant & Finance Leader (former)', focus: 'Business Consulting · Accounting · Securities Services', image: coachImage('e83ee7_db32d539531e4c7c96feab7b99f4037a~mv2.png', 'Doris Kuo'), href: 'https://www.finexclub.org/career-coach/doris-kuo' },
  { id: 'coach-13', kind: 'coach', name: 'Edward Lee', role: 'Chief Investment Officer', focus: 'Family Office · Investment · Wealth Management', image: coachImage('e83ee7_49427045c28c4696b2816b14a630e688~mv2.png', 'Edward Lee'), href: 'https://www.finexclub.org/edward-lee' },
  { id: 'coach-14', kind: 'coach', name: 'Hannah Hui', role: 'CEO / Managing Director', focus: 'Fintech & Digital Assets · Virtual Banking', image: coachImage('e83ee7_7b953fdad53f433f9d12174a315abb7c~mv2.png', 'Hannah Hui'), href: 'https://www.finexclub.org/hannah-hui' },
  { id: 'coach-15', kind: 'coach', name: 'Jame DiBiasio', role: 'Founder, Editor & Board Director', focus: 'Fintech Media & Entrepreneurship', image: coachImage('e83ee7_97007c12a5ce4098aaba3014928ed6dc~mv2.png', 'Jame DiBiasio'), href: 'https://www.finexclub.org/jame-dibiasio' },
  { id: 'coach-16', kind: 'coach', name: 'Jeremy Wong', role: 'Founder & CEO; Hedge Fund Manager (former)', focus: 'Fintech · Equity Long/Short · Equity Research', image: coachImage('fe3fd5_becd89718b3348619b18bca182f2b15a~mv2.png', 'Jeremy Wong'), href: 'https://www.finexclub.org/career-coach' },
  { id: 'coach-17', kind: 'coach', name: 'John Wong', role: 'Managing Director', focus: 'Transaction Banking & Fintech · Web3', image: coachImage('e83ee7_a8339fae8bdd48429b037288a7b286cc~mv2.png', 'John Wong'), href: 'https://www.finexclub.org/career-coach/john-wong' },
  { id: 'coach-18', kind: 'coach', name: 'Katherine Lee', role: 'Executive Director, Product Management', focus: 'Product & Relationship Management · Program Leadership', image: coachImage('e83ee7_0e1fe10bc0ed47fda64da46d852135e9~mv2.png', 'Katherine Lee'), href: 'https://www.finexclub.org/katherine-lee' },
  { id: 'coach-19', kind: 'coach', name: 'Ken Cheung', role: 'Chief Asian FX Strategist (former)', focus: 'Global Markets · FX Strategy', image: coachImage('e83ee7_80543a22c5a047288a62f0143cac51e2~mv2.png', 'Ken Cheung'), href: 'https://www.finexclub.org/ken-cheung' },
  { id: 'coach-20', kind: 'coach', name: 'Lawrence Au', role: 'Asia-Pacific CEO, Securities Services (former)', focus: 'Securities Services · Regional Leadership', image: coachImage('e83ee7_bf0cfd6e857f45fa8e41bf7aa98064f7~mv2.png', 'Lawrence Au'), href: 'https://www.finexclub.org/career-coach/lawrence-au' },
  { id: 'coach-21', kind: 'coach', name: 'Margaret Chan', role: 'Executive Director', focus: 'Securities Services · Pricing & Risk Management', image: coachImage('e83ee7_d1a6ad4e9c674b08959cbe8d5b62f61e~mv2.png', 'Margaret Chan'), href: 'https://www.finexclub.org/margaret-chan' },
  { id: 'coach-22', kind: 'coach', name: 'Morris Hui, CFA', role: 'Founder / Group Treasurer / Portfolio Manager', focus: 'Entrepreneurship · Finance · Investment Banking', image: coachImage('e83ee7_c4ed07bf2bea4023ab947d15860b95b8~mv2.png', 'Morris Hui, CFA'), href: 'https://www.finexclub.org/morris-hui' },
  { id: 'coach-23', kind: 'coach', name: 'Nelson Chau', role: 'Chief Operating Officer (former)', focus: 'Investment Operations · Fund Accounting', image: coachImage('e83ee7_6837d6f800154701918282892a67b071~mv2.png', 'Nelson Chau (based in Australia)'), href: 'https://www.finexclub.org/career-coach/nelson-chau' },
  { id: 'coach-24', kind: 'coach', name: 'Nicholas Yip', role: 'Corporate Treasurer & Director, Digital Assets', focus: 'Corporate Treasury · Fintech & Digital Assets', image: coachImage('e83ee7_cf268e15f7c14bd2a1817f01d6cc9586~mv2.png', 'Nicholas Yip'), href: 'https://www.finexclub.org/nicholas-yip' },
  { id: 'coach-25', kind: 'coach', name: 'Patrick Leung', role: 'Wealth Management Advisor', focus: 'Finance & Wealth Management', image: coachImage('e83ee7_085bf1f5c45e47e9b95e148970cf74d2~mv2.png', 'Patrick Leung'), href: 'https://www.finexclub.org/patrick-leung' },
  { id: 'coach-26', kind: 'coach', name: 'Raymong Chung', role: 'General Manager', focus: 'Securities Services · Digital Assets · Tokenization', image: coachImage('e83ee7_ef2da9f15b724535a280b605fa5b5749~mv2.png', 'Raymong Chung'), href: 'https://www.finexclub.org/raymond-chung' },
  { id: 'coach-27', kind: 'coach', name: 'Shannon Chow', role: 'Managing Director', focus: 'Private Markets · Investment Solutions', image: coachImage('e83ee7_350ec338396e48f9803ec04b635061c1~mv2.png', 'Shannon Chow'), href: 'https://www.finexclub.org/shannon-chow' },
  { id: 'coach-28', kind: 'coach', name: 'Simon Cheung', role: 'Head of Risk Management', focus: 'Insurance Risk · Enterprise Risk & Actuarial', image: coachImage('e83ee7_029f3022df224e3eb5e64a9ae81bd60b~mv2.png', 'Simon Cheung'), href: 'https://www.finexclub.org/simon-cheung' },
  { id: 'coach-29', kind: 'coach', name: 'Simon Tung', role: 'Audit Partner', focus: 'Audit & Assurance · Capital Markets & IPO', image: coachImage('e83ee7_80928bc0c7e2430f8de14bb70d7ab4ee~mv2.png', 'Simon Tung'), href: 'https://www.finexclub.org/simon-tung' },
  { id: 'coach-30', kind: 'coach', name: 'Timothy Chan', role: 'Head of Global Markets Sales', focus: 'Global Markets (FICC) · Sales & Green Finance', image: coachImage('e83ee7_b6e1e929af2f4bbfb021f4dc79feb5e1~mv2.png', 'Timothy Chan'), href: 'https://www.finexclub.org/timothy-chan' },
  { id: 'coach-31', kind: 'coach', name: 'Vera Lau', role: 'Head of Sales', focus: 'Sales & Relationship Management', image: coachImage('e83ee7_c3284de5a3c94c5cb0d3c9867b77598c~mv2.png', 'Vera Lau'), href: 'https://www.finexclub.org/vera-lau' },
  { id: 'coach-32', kind: 'coach', name: 'Vincent Huen', role: 'Consulting Partner (former)', focus: 'Management Consulting (TMT) · Transformation & Strategy', image: coachImage('e83ee7_4403b66d2f8a4f78954d6a80bcc23cbb~mv2.png', 'Vincent Huen'), href: 'https://www.finexclub.org/vincent-huen' },
]
