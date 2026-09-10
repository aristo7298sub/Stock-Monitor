import type { CompanySnapshot } from './data'
import type { Financials } from './liveData'

export type EvidenceState = 'support' | 'caution' | 'unknown'

export interface InvestmentMetric {
  key: string
  label: string
  value: number | null
  unit: '%' | 'x' | 'years'
  period: string
  state: EvidenceState
  explanation: string
  formula: string
  sourceUrl?: string
}

export interface InvestmentCase {
  state: 'research' | 'caution' | 'incomplete'
  label: string
  metrics: InvestmentMetric[]
  supports: InvestmentMetric[]
  concerns: InvestmentMetric[]
  missing: string[]
  fresh: boolean
}

function finite(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function ratio(numerator: number | null | undefined, denominator: number | null | undefined, scale = 100) {
  return finite(numerator) && finite(denominator) && denominator > 0 ? numerator / denominator * scale : null
}

export function assessInvestment(financials: Financials | null | undefined, valuation: CompanySnapshot['valuation'], pending = false, now = Date.now()): InvestmentCase {
  const end = financials?.periodEnd ? Date.parse(financials.periodEnd) : NaN
  const fresh = financials?.schemaVersion === 3 && Number.isFinite(end) && now >= end && now - end <= 160 * 86400000 && !pending
  const sourceUrl = financials?.sourceUrl
  const period = financials?.periodEnd ? `${financials.periodType === 'quarter' ? '单季' : financials.periodType === 'annual' ? '年度' : '累计'} · ${financials.periodEnd}` : '期间未确认'
  const metrics: InvestmentMetric[] = []
  const add = (key: string, label: string, value: number | null | undefined, unit: InvestmentMetric['unit'], support: boolean, explanation: string, formula: string, metricPeriod = period) => {
    const usable = fresh && finite(value)
    metrics.push({ key, label, value: finite(value) ? value : null, unit, period: metricPeriod, state: !usable ? 'unknown' : support ? 'support' : 'caution', explanation: !usable ? '缺少有效的同期数据，暂不判断。' : explanation, formula, sourceUrl })
  }
  const growth = financials?.revenueYoY
  add('growth', '营收增长', growth, '%', finite(growth) && growth > 0, finite(growth) && growth > 0 ? '业务收入同比增长，是继续研究需求的理由。' : '营收未增长，需要核查需求、竞争或周期。', '本期营收 / 上年同期间营收 - 1')
  const margin = ratio(financials?.operatingIncome, financials?.revenue)
  add('margin', '营业利润率', margin, '%', margin !== null && margin >= 15, margin !== null && margin >= 15 ? '每百元收入保留较多经营利润；是否持久还需跨年核查。' : '经营利润缓冲较薄，需要结合行业和商业模式判断。', '同期营业利润 / 营收；15% 为本项目研究阈值，不适用所有行业')
  const conversion = ratio(financials?.operatingCashFlow, financials?.netIncome)
  add('conversion', '利润现金兑现', conversion, '%', conversion !== null && conversion >= 100, conversion !== null && conversion >= 100 ? '经营现金覆盖账面利润，但仍需检查营运资金和股份薪酬。' : '经营现金尚未覆盖账面利润，需核查一次性收益与营运资金。', '同期经营现金 / 净利润；净利润非正时不计算')
  const cashMargin = ratio(financials?.freeCashFlow, financials?.revenue)
  add('cash', '自由现金率', cashMargin, '%', cashMargin !== null && cashMargin > 0, cashMargin !== null && cashMargin > 0 ? '支付现金资本开支后仍有现金剩余。' : '现金资本开支后未留有正现金，不应只凭低 PE 选择。', '(经营现金 - 现金资本开支) / 同期营收；不等于已核验的所有者盈余')
  const capexCoverage = ratio(financials?.capex, financials?.operatingCashFlow)
  add('reinvestment', '现金再投入占比', capexCoverage, '%', capexCoverage !== null && capexCoverage <= 100, capexCoverage !== null && capexCoverage <= 100 ? '现金资本开支未超过当期经营现金。' : '现金支出超过经营现金，需核查融资依赖与项目回报。', '现金资本开支 / 同期经营现金；未区分维持性与增长性投资')
  const peValid = valuation.algorithmVersion === 4 && valuation.currentPeQualified === true && finite(valuation.pe) && valuation.pe > 0
  const yieldValue = peValid ? 100 / valuation.pe! : null
  metrics.push({ key: 'yield', label: '盈利收益率', value: yieldValue, unit: '%', period: `四季盈利 · 收盘 ${valuation.asOf}`, state: 'unknown', explanation: peValid ? '对应过去四季会计盈利，不是未来收益承诺；价格判断还需估值假设。' : '当前价格或盈利尚不具备估值资格。', formula: '100 / 已验证的四季稀释 PE', sourceUrl: valuation.sourceUrl })
  const abnormalProfit = finite(financials?.netIncome) && finite(financials?.operatingIncome) && (financials.operatingIncome <= 0 ? financials.netIncome > 0 : financials.netIncome > financials.operatingIncome * 1.5)
  if (fresh && abnormalProfit) metrics.push({ key: 'profitQuality', label: '非经营利润核查', value: ratio(financials?.netIncome, financials?.operatingIncome, 1), unit: 'x', period, state: 'caution', explanation: '净利润明显高于营业利润，低 PE 可能受投资收益或税项影响。', formula: '净利润 > 正营业利润的 1.5 倍，或营业亏损但净利润为正；仅为筛查，不是逐项调整', sourceUrl })
  const quality = financials?.quality?.version === 1 && financials.quality.periodEnd === financials.periodEnd ? financials.quality : undefined
  const cagr = quality?.revenueCagr5y
  add('cagr', '五年营收复合增长', cagr, '%', finite(cagr) && cagr > 0, finite(cagr) && cagr > 0 ? '跨五年的收入规模扩大；未来不能机械沿用历史增速。' : '长期收入未扩张，需要解释业务与需求的变化。', '(最近年度营收 / 五年前年度营收) ^ (1 / 实际间隔年数) - 1；需六个连续年度端点', quality?.history.length ? `${quality.history[0].periodEnd} 至 ${quality.history[quality.history.length - 1].periodEnd}` : '五年数据待补齐')
  const cashYears = quality?.cashYearsKnown === 5 && quality.historyContiguous ? quality.cashYearsPositive : null
  add('consistency', '正自由现金年份', cashYears, 'years', cashYears === 5, cashYears === 5 ? '最近五个完整财年均有正自由现金，现金创造不是单季现象。' : '五年中出现自由现金为负，需要解释扩张与经营波动。', '最近五个完整财年中，经营现金减现金资本开支 > 0 的年份数', '最近五个完整财年')
  const roe = quality?.roeTtm
  add('roe', '权益回报 ROE', roe, '%', finite(roe) && roe >= 15 && roe <= 80 && !abnormalProfit, finite(roe) && roe > 80 ? 'ROE 异常高，回购、轻资产与低权益基数可能放大结果。' : abnormalProfit ? '会计利润受非经营因素影响，ROE 也不能直接视为经营回报。' : finite(roe) && roe >= 15 ? '平均权益上的账面回报较高，仍需核查杠杆与资本配置。' : '权益回报尚未达到本项目 15% 研究参考线。', 'TTM 净利润 / 本期与上年同期平均正权益；15% 和 80% 是研究提示线，不是巴菲特公式', `TTM · ${financials?.periodEnd || '待确认'}`)
  const debt = quality?.longDebtToOcf
  add('debt', '长期债务 / 经营现金', debt, 'x', false, finite(debt) && debt > 3 ? '仅已知长期债务已超过三年经营现金规模，需审查偿付安排。' : '已知长期债务相对经营现金较低，但短债与租赁仍需单独核查。', '流动部分长期债务 + 非流动长期债务，除以 TTM 经营现金；不是完整总债务', `期末债务 / TTM 现金 · ${financials?.periodEnd || '待确认'}`)
  const debtMetric = metrics[metrics.length - 1]
  if (fresh && finite(debt) && debt <= 3) debtMetric.state = 'unknown'
  const supports = metrics.filter(metric => metric.state === 'support')
  const concerns = metrics.filter(metric => metric.state === 'caution')
  const missing = []
  if (!fresh) missing.push(pending ? '新财报尚未完成解析' : '最新且期间对齐的财报')
  if (!peValid) missing.push('有效的当前价格与盈利')
  for (const metric of metrics.filter(metric => metric.value === null && metric.key !== 'yield')) missing.push(metric.label)
  missing.push('完整债务、租赁与管理层资本配置', '竞争优势的原始证据', '可持续现金与安全边际假设')
  const incompleteRecord = ['cagr', 'consistency', 'roe', 'debt'].some(key => metrics.find(metric => metric.key === key)?.value == null)
  return { state: !fresh || !peValid ? 'incomplete' : concerns.length ? 'caution' : incompleteRecord ? 'incomplete' : 'research', label: !fresh || !peValid ? '等待有效证据' : concerns.length ? '先核查风险' : incompleteRecord ? '长期证据待补' : '值得继续研究', metrics, supports, concerns, missing, fresh }
}

export interface ValueAssumptions {
  cashPerShare: number
  growth: number
  requiredReturn: number
  terminalGrowth: number
  safetyMargin: number
  years: number
}

export function discountedCashValue(assumptions: ValueAssumptions, price: number | null) {
  const { cashPerShare, growth, requiredReturn, terminalGrowth, safetyMargin, years } = assumptions
  if (!Object.values(assumptions).every(Number.isFinite) || cashPerShare <= 0 || growth <= -100 || requiredReturn <= 0 || terminalGrowth <= -100 || requiredReturn <= terminalGrowth || safetyMargin < 0 || safetyMargin >= 100 || !Number.isInteger(years) || years < 1 || years > 20) return null
  const growthRate = growth / 100
  const discount = requiredReturn / 100
  const terminalRate = terminalGrowth / 100
  let presentCash = 0
  const flows = []
  for (let year = 1; year <= years; year++) {
    const cash = cashPerShare * (1 + growthRate) ** year
    const present = cash / (1 + discount) ** year
    presentCash += present
    flows.push({ year, cash, present })
  }
  const terminal = flows[flows.length - 1].cash * (1 + terminalRate) / (discount - terminalRate) / (1 + discount) ** years
  const value = presentCash + terminal
  if (!Number.isFinite(value) || value <= 0) return null
  return { value, entryPrice: value * (1 - safetyMargin / 100), marginAtPrice: finite(price) && price > 0 ? (1 - price / value) * 100 : null, terminalWeight: terminal / value * 100, presentCash, presentTerminal: terminal, flows }
}

export function cashBaseline(company: CompanySnapshot, now = Date.now()): number | null {
  const financials = company.financials
  const quality = financials?.quality
  if (!quality || financials?.schemaVersion !== 3 || financials.currency !== 'USD' || quality.version !== 1 || quality.currency !== 'USD' || quality.periodEnd !== financials.periodEnd || company.earnings?.pendingStructuredData || company.valuation.algorithmVersion !== 4 || !company.valuation.currentPeQualified || company.valuation.epsPeriodEnd !== financials.periodEnd) return null
  const age = now - Date.parse(quality.periodEnd)
  return age >= 0 && age <= 160 * 86400000 && finite(quality.cashPerShareProxy) && quality.cashPerShareProxy > 0 ? quality.cashPerShareProxy : null
}

export function valuationReviewKey(company: CompanySnapshot, assumptions: ValueAssumptions) {
  const financials = company.financials
  const quality = financials?.quality
  return JSON.stringify([company.symbol, financials?.schemaVersion, financials?.currency, financials?.periodEnd, financials?.filedAt, financials?.netIncomeTtm, financials?.operatingCashFlowTtm, financials?.freeCashFlowTtm, quality?.version, quality?.cashPerShareProxy, quality?.shareCompensationTtm, quality?.sharesPeriod, quality?.dilutedShares, assumptions.cashPerShare, assumptions.growth, assumptions.requiredReturn, assumptions.terminalGrowth, assumptions.safetyMargin, assumptions.years])
}

export interface BusinessProfile {
  business: string
  advantage: string
  thesis: string
  falsifiers: string[]
  capitalQuestion: string
  sourceUrl: string
}

export const businessProfiles: Record<string, BusinessProfile> = {
  MSFT: { business: '向企业销售办公软件、云计算与开发工具，靠订阅和使用量收费。', advantage: '工作流、身份系统与数据嵌入企业，迁移往往牵涉整个组织。', thesis: '若客户续费与云端使用持续，现有分发渠道可能承接 AI 收入；关键是新增算力能否变成自由现金。', falsifiers: ['云与订阅增长长期放缓，营业利润率同时下行', '数据中心投资持续加速，但多期自由现金没有兑现'], capitalQuestion: 'AI 资本投入的使用率与回报，是否高于资金成本？', sourceUrl: 'https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q4/press-release-webcast' },
  NVDA: { business: '出售 GPU、网络与计算系统，并围绕软件生态组织算力平台。', advantage: '软件工具、开发者习惯和系统协同可能形成转换成本；不能只看芯片性能。', thesis: '若 AI 计算需求与平台优势持续，高经营利润率有价值；采购承诺、客户集中和现金回款必须跟上。', falsifiers: ['客户转向自研或替代方案，定价和毛利持续走弱', '库存、应收或采购承诺增长超过实际现金回收'], capitalQuestion: '现金生成能否支撑供应承诺与研发，而不依赖过度乐观的需求？', sourceUrl: 'https://investor.nvidia.com/financial-info/financial-reports-and-sec-filings/default.aspx' },
  AMZN: { business: '电商、商家服务、广告和 AWS 云计算共同构成收入来源。', advantage: '物流规模、商家与消费者网络，以及云服务切换成本是待验证的优势。', thesis: '零售效率与 AWS 的现金创造值得研究；投资收益不是云业务利润，投入后的现金剩余比表面 PE 更关键。', falsifiers: ['AWS 增长放缓且利润率下降，无法支撑持续投入', '零售效率改善未转化为跨周期正自由现金'], capitalQuestion: '云基础设施与物流的再投资，是扩大经济价值还是只扩大资产规模？', sourceUrl: 'https://ir.aboutamazon.com/quarterly-results/default.aspx' },
  GOOGL: { business: '搜索与视频广告是核心，云与订阅业务提供其他收入。', advantage: '分发、用户习惯和广告系统形成规模优势，但 AI 入口与监管会改变竞争条件。', thesis: '核心业务的盈利能力值得关注；先剔清投资重估影响，再判断 AI 投入后可持续现金和搜索优势。', falsifiers: ['新搜索方式使广告变现持续下降而非仅短期波动', '资本开支长期超过现金增长，或监管实质削弱分发优势'], capitalQuestion: 'AI 投入是在保护搜索现金来源，还是侵蚀可分配现金？', sourceUrl: 'https://abc.xyz/investor/' },
  AAPL: { business: '硬件、操作系统与服务结合，向消费者销售设备和生态内服务。', advantage: '品牌、软硬件协同与用户迁移成本，可能帮助维持溢价和复购。', thesis: '跨年现金创造与生态黏性是研究理由；回购可提高每股指标，也会推高 ROE，价格仍需单独检验。', falsifiers: ['核心设备需求和服务增长同时走弱，定价优势下降', '大额回购发生在高估值区间，却未改善长期每股价值'], capitalQuestion: '回购是否以低于内在价值的价格进行，而非只提高每股盈利？', sourceUrl: 'https://investor.apple.com/financials/default.aspx' },
  TSM: { business: '为芯片设计公司代工制造，收入来自工艺、产能与交付能力。', advantage: '先进工艺、良率、客户信任和长期产能协作构成待验证的竞争壁垒。', thesis: '先进工艺需求与执行能力有价值；资本密集、客户集中和地缘风险要求更谨慎的现金假设。', falsifiers: ['先进工艺竞争力、良率或主要客户需求持续恶化', '扩产兑现延迟，自由现金与资本回报长期承压'], capitalQuestion: '跨周期的扩产回报是否足够补偿巨额投入与地缘风险？', sourceUrl: 'https://investor.tsmc.com/english/quarterly-results/2026/q2' },
}