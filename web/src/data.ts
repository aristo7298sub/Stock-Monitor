import type { Financials } from './liveData'

export type SignalTone = 'positive' | 'watch' | 'neutral'

export interface FinancialQuality {
  version: number
  currency: string
  periodEnd: string
  revenueCagr5y: number | null
  cashYearsKnown: number
  cashYearsPositive: number
  profitYearsKnown: number
  profitYearsPositive: number
  historyContiguous: boolean
  roeTtm: number | null
  longDebtToOcf: number | null
  longDebt?: number | null
  cash?: number | null
  equity?: number | null
  shortBorrowings?: number | null
  commercialPaper?: number | null
  shareCompensationTtm?: number | null
  cashPerShareProxy: number | null
  dilutedShares?: number | null
  sharesPeriod?: string | null
  roeBasis?: string
  debtBasis?: string
  cashProxyBasis?: string
  history: { periodStart: string; periodEnd: string; revenue: number | null; netIncome: number | null; freeCashFlow: number | null; operatingCashFlow?: number | null; capex?: number | null; sourceUrls?: string[] }[]
}

export interface QuoteSnapshot {
  price: number | null
  changePercent: number | null
  asOf: string
  source: string
  receivedAt?: string
}

export interface CoreMetric {
  label: string
  value: string
  change: string
  hint: string
}

export interface CompanySnapshot {
  symbol: string
  name: string
  shortName: string
  aliases: string[]
  category: string
  exchange: string
  evidenceCount: number
  stance: string
  tone: SignalTone
  headline: string
  summary: string
  quote: QuoteSnapshot
  valuation: {
    pe: number | null
    forwardPe: number | null
    percentile10y: number | null
    asOf: string
    frequency?: 'daily' | 'annual'
    sampleCount?: number
    historyStart?: string
    historyEnd?: string
    calculatedAt?: string
    source?: string
    sourceUrl?: string
    dailyUnavailableReason?: string
    algorithmVersion?: number
    status?: 'qualified' | 'limited' | 'current_only' | 'incomplete' | 'stale' | 'withdrawn'
    reason?: string | null
    currentPeQualified?: boolean
    percentile?: number | null
    horizonYears?: number | null
    price?: number
    epsTtm?: number
    epsPeriodEnd?: string
    epsFiledAt?: string
    earningsYieldPercent?: number
    priceLagSessions?: number
    basis?: string
    warnings?: string[]
    referencePrices?: { percentile: number; pe: number; price: number }[]
    coverage?: { years: number; qualified: boolean; expectedSessions: number; validSamples: number; missingEarningsSessions: number; nonpositiveEarningsSessions: number; coveragePercent: number; maxMissingRun: number }[]
    earningsComponents?: { start: string; end: string; filedAt: string; eps: number; reportedEps: number; splitAdjustment: number; accession: string; sourceUrl?: string; sourceHash?: string; extraction: string }[]
  }
  earnings?: {
    lastCheckedAt?: string | null
    latestFiling?: { form: string; filedAt: string; reportDate: string; url: string } | null
    pendingStructuredData?: boolean
  }
  dataErrors?: Record<string, string>
  financialPeriod?: string
  financialSourceUrl?: string
  cashFlowSourceUrl?: string
  capexConcept?: string
  qualityWarning?: string
  financialCurrency?: string
  financials?: Financials | null
  metrics: CoreMetric[]
  proof: {
    title: string
    status: string
    tone: SignalTone
    marginalCoverage: number | null
    explanation: string
    facts: string[]
  }
  outlook: {
    baseQuarterProfitB: number | null
    firstYear: number
    secondYear: number
    firstGrowth: number
    secondGrowth: number
    terminalPe: number
    sourceLabel: string
    baseLabel?: string
    blockedReason?: string
  }
  moat: string
  risks: string[]
  sourceNote: string
}

const pendingQuote: QuoteSnapshot = {
  price: null,
  changePercent: null,
  asOf: '等待本地服务刷新',
  source: 'CNBC Quick Quote',
}

export const seedCompanies: CompanySnapshot[] = [
  {
    symbol: 'NVDA',
    name: 'NVIDIA Corporation',
    shortName: '英伟达',
    aliases: ['NVIDIA', '英伟达', 'NVDA'],
    category: 'AI 上游 · 算力平台',
    exchange: 'NASDAQ',
    evidenceCount: 4,
    stance: '值得研究',
    tone: 'positive',
    headline: '利润跑得比估值快，市场可能仍低估长期增长。',
    summary: '动态 PE 约 22 倍，而最近季度净利润同比增长 126%。真正要验证的不是 AI 有没有需求，而是这种增长能维持多久。',
    quote: pendingQuote,
    valuation: { pe: null, forwardPe: null, percentile10y: null, asOf: '等待后端计算' },
    metrics: [
      { label: '季度营收', value: '$962.2 亿', change: '+106%', hint: '公司卖出的产品和服务总额' },
      { label: '季度净利润', value: '$596.9 亿', change: '+126%', hint: '扣除成本后真正赚到的钱' },
      { label: '下一季指引', value: '$1,080 亿', change: '超预期', hint: '管理层对下一季度的收入预告' },
      { label: '2027 收入展望', value: '+70%', change: '供给受限', hint: '文章引用的公司长期增长判断' },
    ],
    proof: {
      title: '需求是否真实',
      status: '订单在加速',
      tone: 'positive',
      marginalCoverage: null,
      explanation: '英伟达提前锁定上游产能，说明管理层愿意用真金白银押注未来需求。',
      facts: ['供应采购承诺 $2,790 亿', '企业与主权 AI 客户增长更快', 'AWS 计划继续部署 200 万颗 GPU'],
    },
    outlook: {
      baseQuarterProfitB: 59.69,
      firstYear: 2027,
      secondYear: 2028,
      firstGrowth: 70,
      secondGrowth: 30,
      terminalPe: 20,
      sourceLabel: '《十万亿不是梦？》作者基准情景',
    },
    moat: 'CUDA、完整软硬件生态与稀缺产能，让客户不仅“想买”，而且很难绕开。',
    risks: ['毛利率指引由 75% 降至 74%', '头部云客户占比仍高', '先进制程与封装产能限制交付'],
    sourceNote: '财务与情景来自 2026-08-31 研究文章；行情由本地服务刷新。',
  },
  {
    symbol: 'MSFT',
    name: 'Microsoft Corporation',
    shortName: '微软',
    aliases: ['Microsoft', '微软', 'MSFT'],
    category: 'AI 中游 · 云与软件',
    exchange: 'NASDAQ',
    evidenceCount: 4,
    stance: '值得研究',
    tone: 'positive',
    headline: '估值曾落入十年极低位，AI 投入已经开始带来更多现金。',
    summary: 'Azure 增长加速，Copilot 付费席位快速增加；经营现金流增量超过 Capex 增量，是市场态度反转的核心。',
    quote: pendingQuote,
    valuation: { pe: null, forwardPe: null, percentile10y: null, asOf: '等待后端计算' },
    metrics: [
      { label: '季度营收', value: '$900 亿', change: '+18%', hint: '公司卖出的产品和服务总额' },
      { label: '季度净利润', value: '$358 亿', change: '+31%', hint: '扣除成本后真正赚到的钱' },
      { label: 'Azure 增速', value: '+43%', change: '下季 45%', hint: '微软云业务的同比增速' },
      { label: 'Copilot 席位', value: '3,000 万', change: '单季 +1,000 万', hint: '已经付费使用 Copilot 的企业席位' },
    ],
    proof: {
      title: '投入是否值得',
      status: '回报已超过新增投入',
      tone: 'positive',
      marginalCoverage: 1.78,
      explanation: '每新增投入 1 美元 Capex，经营现金流增加约 1.78 美元，且无需发债或增发。',
      facts: ['经营现金流 $554.4 亿', '现金 Capex $358 亿', '自由现金流 $196 亿'],
    },
    outlook: {
      baseQuarterProfitB: 35.8,
      firstYear: 2027,
      secondYear: 2028,
      firstGrowth: 22,
      secondGrowth: 18,
      terminalPe: 25,
      sourceLabel: '可调整研究情景，非分析师共识',
    },
    moat: 'Office 工作流、Azure 分发和企业权限体系互相加强，AI 更可能嵌入生态而非绕过生态。',
    risks: ['AI 原生办公入口可能削弱 Office', '高 Capex 持续压制短期现金流', '云业务受产能约束'],
    sourceNote: '财务与估值来自 2026 年研究文章；情景参数可自行调整。',
  },
  {
    symbol: 'AMZN',
    name: 'Amazon.com, Inc.',
    shortName: '亚马逊',
    aliases: ['Amazon', '亚马逊', 'AMZN', 'AWS'],
    category: 'AI 中游 · AWS 云服务',
    exchange: 'NASDAQ',
    evidenceCount: 4,
    stance: '拐点出现',
    tone: 'positive',
    headline: '自由现金流仍为负，但改善速度比绝对值更重要。',
    summary: '市场不怕 Capex 高，而是怕它没有回报。AWS 增长超预期、自由现金流单季改善，说明投入开始兑现。',
    quote: pendingQuote,
    valuation: { pe: null, forwardPe: null, percentile10y: null, asOf: '等待后端计算' },
    metrics: [
      { label: '季度营收', value: '$2,006 亿', change: '+20%', hint: '公司所有业务的季度收入' },
      { label: '调整后营业利润', value: '$275 亿', change: '+43%', hint: '剔除 Anthropic 投资收益后更可比的利润' },
      { label: 'AWS 增速', value: '+37%', change: '预期 31%', hint: '亚马逊云业务的同比增速' },
      { label: '自由现金流', value: '-$76.95 亿', change: '单季改善 $95.13 亿', hint: '经营现金减去资本开支后剩下的钱' },
    ],
    proof: {
      title: '投入是否值得',
      status: '现金流快速修复',
      tone: 'positive',
      marginalCoverage: null,
      explanation: '自由现金流仍是负数，但比上季度改善 $95.13 亿；方向比当期正负更重要。',
      facts: ['季度 Capex $542.08 亿', '2026 Capex 指引 $2,200 亿', 'AWS 增速超预期 6 个百分点'],
    },
    outlook: {
      baseQuarterProfitB: 27.5,
      firstYear: 2027,
      secondYear: 2028,
      firstGrowth: 25,
      secondGrowth: 20,
      terminalPe: 24,
      sourceLabel: '基于调整后营业利润的可调整情景',
    },
    moat: 'AWS 把昂贵且迭代迅速的 GPU 变成随用随付的算力，承担了 AI 产业链最关键的分发环节。',
    risks: ['Capex 规模为科技巨头之最', '自由现金流尚未转正', '零售与云业务混合使估值更复杂'],
    sourceNote: 'AWS 不是独立股票，本平台将其作为 AMZN 的核心业务分部跟踪。',
  },
  {
    symbol: 'GOOGL',
    name: 'Alphabet Inc.',
    shortName: '谷歌',
    aliases: ['Alphabet', 'Google', '谷歌', 'GOOGL'],
    category: 'AI 中游 · 云与模型',
    exchange: 'NASDAQ',
    evidenceCount: 2,
    stance: '等待验证',
    tone: 'watch',
    headline: '关键不在 Capex 是否下降，而在云收入增量何时超过新增投入。',
    summary: '搜索现金牛提供投资能力，Google Cloud 与模型业务需要证明投入能持续转成收入和自由现金流。',
    quote: pendingQuote,
    valuation: { pe: null, forwardPe: null, percentile10y: null, asOf: '等待历史估值同步' },
    metrics: [
      { label: '核心观察', value: '云收入增量', change: '对比 Capex 增量', hint: '新增云收入能否覆盖新增投资' },
      { label: '利润来源', value: '搜索广告', change: '现金牛', hint: '支撑 AI 投资的成熟业务' },
      { label: '增长引擎', value: 'Google Cloud', change: '等待财报', hint: '最直接承接 AI 需求的业务' },
      { label: '估值位置', value: '同步中', change: '需十年历史', hint: '当前 PE 在自身十年历史中的位置' },
    ],
    proof: {
      title: '投入是否值得', status: '等待交叉点', tone: 'watch', marginalCoverage: null,
      explanation: '当云收入增量稳定超过 Capex 增量，市场对高投入的担忧才会真正逆转。',
      facts: ['跟踪 Google Cloud 增速', '跟踪经营现金流增量', '排除会计口径变化'],
    },
    outlook: { baseQuarterProfitB: null, firstYear: 2027, secondYear: 2028, firstGrowth: 18, secondGrowth: 15, terminalPe: 22, sourceLabel: '等待 SEC 最新财报后建立基线' },
    moat: '搜索入口、全球分发和自研 TPU 形成数据、模型与算力的闭环。',
    risks: ['搜索入口可能被 AI 重构', '高投入回报仍需验证', '监管与反垄断压力'],
    sourceNote: '本地服务将从 SEC 更新通用财务数据；业务分部需财报补充。',
  },
  {
    symbol: 'AAPL',
    name: 'Apple Inc.',
    shortName: '苹果',
    aliases: ['Apple', '苹果', 'AAPL'],
    category: '平台下游 · 终端生态',
    exchange: 'NASDAQ',
    evidenceCount: 2,
    stance: '等待增长',
    tone: 'neutral',
    headline: '成熟现金牛是否值得买，取决于估值是否给增长留出余地。',
    summary: '苹果的优势是生态与现金流，弱点是增长基数高。需要同时看利润趋势、回购后的每股收益和历史估值位置。',
    quote: pendingQuote,
    valuation: { pe: null, forwardPe: null, percentile10y: null, asOf: '等待历史估值同步' },
    metrics: [
      { label: '核心观察', value: '每股收益', change: '含回购贡献', hint: '公司每一股对应的利润' },
      { label: '现金能力', value: '自由现金流', change: '稳定性优先', hint: '可用于回购、分红和投资的钱' },
      { label: '增长引擎', value: '服务业务', change: '等待财报', hint: '硬件之外的高毛利收入' },
      { label: '估值位置', value: '同步中', change: '需十年历史', hint: '当前 PE 在自身十年历史中的位置' },
    ],
    proof: {
      title: '利润是否增长', status: '等待新催化', tone: 'neutral', marginalCoverage: null,
      explanation: '成熟公司的关键不是故事有多大，而是利润与每股收益能否继续支撑当前价格。',
      facts: ['跟踪服务收入占比', '拆分利润增长与回购贡献', '对比自身历史 PE'],
    },
    outlook: { baseQuarterProfitB: null, firstYear: 2027, secondYear: 2028, firstGrowth: 8, secondGrowth: 7, terminalPe: 24, sourceLabel: '等待 SEC 最新财报后建立基线' },
    moat: '硬件、操作系统、服务和开发者形成高转换成本的消费生态。',
    risks: ['硬件换机周期放缓', '高估值需要持续回购和增长支撑', '供应链与监管风险'],
    sourceNote: '本地服务将从 SEC 更新通用财务数据。',
  },
  {
    symbol: 'TSM',
    name: 'Taiwan Semiconductor Manufacturing Company',
    shortName: '台积电',
    aliases: ['TSMC', '台积电', 'TSM'],
    category: 'AI 上游 · 先进制程',
    exchange: 'NYSE',
    evidenceCount: 3,
    stance: '值得跟踪',
    tone: 'positive',
    headline: '产能瓶颈不是缺点，而是定价权与客户依赖性的证据。',
    summary: '几乎所有先进 AI 芯片都依赖其制程与封装能力。真正要监控的是产能、利用率、先进节点占比和地缘风险。',
    quote: pendingQuote,
    valuation: { pe: null, forwardPe: null, percentile10y: null, asOf: '等待历史估值同步' },
    metrics: [
      { label: '核心观察', value: '先进制程产能', change: '供不应求', hint: '能够生产顶级 AI 芯片的稀缺能力' },
      { label: '需求证明', value: '客户长期下单', change: '依赖加深', hint: '客户是否持续提前锁定产能' },
      { label: '增长引擎', value: 'AI / HPC', change: '等待财报', hint: '高性能计算业务的收入贡献' },
      { label: '估值位置', value: '同步中', change: '需十年历史', hint: '当前 PE 在自身十年历史中的位置' },
    ],
    proof: {
      title: '护城河是否加深', status: '客户更难绕开', tone: 'positive', marginalCoverage: null,
      explanation: '英伟达等客户越成功，对先进制程和封装的依赖越深，台积电的稀缺性越强。',
      facts: ['跟踪先进节点收入占比', '跟踪产能利用率与扩产', '跟踪客户长期承诺'],
    },
    outlook: { baseQuarterProfitB: null, firstYear: 2027, secondYear: 2028, firstGrowth: 25, secondGrowth: 20, terminalPe: 22, sourceLabel: '等待公司财报建立利润基线' },
    moat: '先进制程、良率、封装和客户信任需要多年积累，无法靠一次资本投入复制。',
    risks: ['台海地缘风险', '扩产周期与资本密集度高', '大客户集中与半导体周期'],
    sourceNote: 'TSM 为 ADR，采用 IFRS；业务数据需从公司财报更新。',
  },
]