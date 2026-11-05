/** Illustrative review content, adapted from the user's three layout references. */
export interface Trainer {
  id: string;
  name: string;
  initials: string;
  role: string;
  credentials: string;
  bio: string;
  tone: string;
}
export interface PreviewCourse {
  id: string;
  category: string;
  title: string;
  description: string;
  duration: string;
  hours: number;
  level: "Advanced" | "Intermediate";
  price: number;
  fullPrice: number;
  rating: string;
  reviews: number;
  trainerId: string;
  modules: string[];
  outcomes: string[];
}
export const TRAINERS: Trainer[] = [
  {
    id: "marcus",
    name: "Dr. Marcus Vance",
    initials: "MV",
    role: "Former Chief Investment Officer",
    credentials: "CFA · Quantitative investing",
    bio: "An illustrative faculty profile focused on translating investment research into practical portfolio decisions, with hands-on modelling and real-world case discussions.",
    tone: "blue",
  },
  {
    id: "elena",
    name: "Elena Rostova",
    initials: "ER",
    role: "Sustainable Capital Strategist",
    credentials: "Sustainability · Investment research",
    bio: "An illustrative faculty profile bringing an investment perspective to sustainable capital, climate risk and the integration of ESG factors into decision-making.",
    tone: "sand",
  },
  {
    id: "harrison",
    name: "Harrison Sterling",
    initials: "HS",
    role: "Managing Director, Private Equity",
    credentials: "Private markets · Deal execution",
    bio: "An illustrative faculty profile specialising in private equity deal structuring, financial modelling and the commercial decisions behind value creation.",
    tone: "sage",
  },
];
export const COURSES: PreviewCourse[] = [
  {
    id: "quant",
    category: "Quantitative finance",
    title: "Advanced Quantitative Portfolio Management",
    description:
      "Build multi-factor strategies, model portfolio risk, and turn investment research into decisions with Python.",
    duration: "6 weeks",
    hours: 36,
    level: "Advanced",
    price: 2240,
    fullPrice: 2800,
    rating: "4.9",
    reviews: 38,
    trainerId: "marcus",
    modules: [
      "Portfolio foundations & factor investing",
      "Building a research workflow in Python",
      "Risk models and portfolio construction",
      "Backtesting and execution strategies",
      "Performance attribution",
      "Final portfolio case study",
    ],
    outcomes: [
      "Construct and evaluate multi-factor portfolios.",
      "Apply Python to repeatable investment research.",
      "Understand model risk and execution trade-offs.",
    ],
  },
  {
    id: "esg",
    category: "ESG investing",
    title: "ESG Integration & Sustainable Investing",
    description:
      "Bring climate risk and sustainability data into your investment process, from analysis to portfolio construction.",
    duration: "4 weeks",
    hours: 24,
    level: "Intermediate",
    price: 1560,
    fullPrice: 1950,
    rating: "4.8",
    reviews: 52,
    trainerId: "elena",
    modules: [
      "The sustainable investment landscape",
      "Evaluating ESG data and materiality",
      "Climate risk in portfolio decisions",
      "Applied investment case study",
    ],
    outcomes: [
      "Assess the materiality of sustainability factors.",
      "Interpret climate risk and ESG disclosures.",
      "Build an investment thesis with clear ESG reasoning.",
    ],
  },
  {
    id: "private-equity",
    category: "Private markets",
    title: "Private Equity Deal Structuring & LBO Valuation",
    description:
      "Work through LBO modelling, debt waterfalls, value creation and exit strategies for private capital.",
    duration: "5 weeks",
    hours: 30,
    level: "Advanced",
    price: 2560,
    fullPrice: 3200,
    rating: "4.95",
    reviews: 29,
    trainerId: "harrison",
    modules: [
      "Private equity transaction fundamentals",
      "Building the LBO model",
      "Capital structure and debt waterfalls",
      "Value creation planning",
      "Investment committee presentation",
    ],
    outcomes: [
      "Build an integrated LBO model.",
      "Evaluate financing and exit scenarios.",
      "Present an investment case with conviction.",
    ],
  },
  {
    id: "macro",
    category: "Quantitative finance",
    title: "Global Macro & Investment Strategy",
    description:
      "Connect monetary policy, market cycles and cross-asset signals to a disciplined allocation framework.",
    duration: "4 weeks",
    hours: 24,
    level: "Advanced",
    price: 1920,
    fullPrice: 2400,
    rating: "4.9",
    reviews: 24,
    trainerId: "marcus",
    modules: [
      "Monetary policy and market cycles",
      "Cross-asset research",
      "Building an allocation framework",
      "Scenario analysis workshop",
    ],
    outcomes: [
      "Interpret cross-asset macro signals.",
      "Build scenarios for changing rate environments.",
      "Translate a macro view into portfolio positions.",
    ],
  },
  {
    id: "leadership",
    category: "Leadership",
    title: "Leading the Modern Finance Function",
    description:
      "Build the strategic judgement, communication and leadership skills to move your team forward.",
    duration: "3 weeks",
    hours: 18,
    level: "Intermediate",
    price: 1280,
    fullPrice: 1600,
    rating: "4.8",
    reviews: 31,
    trainerId: "harrison",
    modules: [
      "Finance as a strategic partner",
      "Communicating decisions and trade-offs",
      "Leading change in your team",
    ],
    outcomes: [
      "Frame financial decisions for diverse stakeholders.",
      "Lead a team through uncertainty.",
      "Create an actionable leadership development plan.",
    ],
  },
];
export const WORKSHOPS = [
  {
    id: "macro-workshop",
    kind: "Live workshop",
    day: "12",
    month: "NOV",
    date: "12 November 2026",
    time: "6:00–7:30 pm HKT",
    title: "The next rate cycle: a global macro workshop",
    trainer: "Dr. Marcus Vance",
    duration: "90 min",
    credits: 2,
  },
  {
    id: "tokenisation",
    kind: "Member roundtable",
    day: "19",
    month: "NOV",
    date: "19 November 2026",
    time: "6:30–8:00 pm HKT",
    title: "Tokenised assets: from theory to practice",
    trainer: "Elena Rostova",
    duration: "90 min",
    credits: 2,
  },
];
export const money = (amount: number) =>
  new Intl.NumberFormat("en-HK", {
    style: "currency",
    currency: "HKD",
    maximumFractionDigits: 0,
  }).format(amount);
export const trainerFor = (course: PreviewCourse) =>
  TRAINERS.find((trainer) => trainer.id === course.trainerId)!;
export const brochureFor = (course: PreviewCourse) =>
  `/learning-assets/brochures/${course.id}.pdf`;
export const summaryFor = (courseId: string) =>
  `/learning-assets/brochures/${courseId}-summary.pdf`;
