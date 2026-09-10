import type { CompanySnapshot, FinancialQuality } from './data'

export interface Financials {
  schemaVersion?: number
  currency?: string
  source?: string
  sourceUrl?: string
  cashFlowSourceUrl?: string
  capexConcept?: string
  operatingCashFlowTtm?: number | null
  operatingIncomeTtm?: number | null
  revenueTtm?: number | null
  freeCashFlowTtm?: number | null
  quality?: FinancialQuality
  revenue?: number | null
  netIncome?: number | null
  operatingIncome?: number | null
  operatingCashFlow?: number | null
  capex?: number | null
  freeCashFlow?: number | null
  netIncomeTtm?: number | null
  revenueYoY?: number | null
  netIncomeYoY?: number | null
  marginalCoverage?: number | null
  fcfDelta?: number | null
  periodStart?: string
  periodEnd?: string
  periodType?: 'quarter' | 'annual' | 'ytd'
  form?: string
  filedAt?: string
}

export interface ApiCompany {
  symbol: string
  name: string
  cik?: string | null
  exchange?: string | null
  quote?: CompanySnapshot['quote'] | null
  valuation?: CompanySnapshot['valuation'] | null
  financials?: Financials | null
  earnings?: CompanySnapshot['earnings']
  errors?: Record<string, string>
}

export function formatMoney(value: number | null | undefined, currency = 'USD') {
  if (value === null || value === undefined || !Number.isFinite(value)) return '未取得'
  const scale = Math.abs(value) >= 1e12 ? 1e12 : 1e8
  const prefix = currency === 'TWD' ? 'NT$' : currency === 'USD' ? '$' : `${currency} `
  return `${value < 0 ? '-' : ''}${prefix}${(Math.abs(value) / scale).toLocaleString('en-US', { maximumFractionDigits: 2 })} ${scale === 1e12 ? '万亿' : '亿'}`
}

export function eligiblePercentile(value: CompanySnapshot['valuation']) {
  return value.algorithmVersion === 4 && value.currentPeQualified === true && ['qualified', 'limited'].includes(value.status || '') && value.frequency === 'daily' && Number.isFinite(value.percentile)
    ? value.percentile! : null
}

export function suspendJudgments(companies: CompanySnapshot[]): CompanySnapshot[] {
  return companies.map((company) => ({
    ...company, tone: 'neutral', stance: '连接中断',
    headline: '连接中断，暂停价格高低判断。',
    summary: '下方保留上次数据及其日期；恢复连接并通过新鲜度检查后才恢复估值判断。',
    valuation: { ...company.valuation, status: 'stale', currentPeQualified: false, percentile: null, percentile10y: null, referencePrices: [], reason: '连接中断，尚未确认数据是否仍然有效。' },
  }))
}

function growthLabel(value: number | null | undefined) {
  return value === null || value === undefined ? '同比待确认' : `同比 ${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

export function genericCompany(api: ApiCompany): CompanySnapshot {
  return {
    symbol: api.symbol, name: api.name,
    shortName: api.name.replace(/,?\s+(Inc\.?|Corp\.?|Corporation|Ltd\.?).*$/i, '').slice(0, 24),
    aliases: [api.name, api.symbol], category: '美股标的 · 持续监控', exchange: api.exchange || 'US',
    evidenceCount: 0, stance: '等待数据', tone: 'neutral',
    headline: '等待足够的财报与估值证据。', summary: '缺失数据不作买入依据，研究判断需要持续验证。',
    quote: api.quote || { price: null, changePercent: null, asOf: '等待刷新', source: 'CNBC Quick Quote' },
    valuation: api.valuation || { pe: null, forwardPe: null, percentile10y: null, asOf: '等待估值计算' },
    metrics: [], proof: { title: '投入是否值得', status: '等待财报', tone: 'neutral', marginalCoverage: null, explanation: '需要可比期间的现金流与资本开支。', facts: [] },
    outlook: { baseQuarterProfitB: null, firstYear: 2027, secondYear: 2028, firstGrowth: 10, secondGrowth: 8, terminalPe: 18, sourceLabel: '自定义研究情景，非公司指引' },
    moat: '尚未完成业务研究。', risks: ['财务数据不能替代业务与竞争研究'], sourceNote: '以注明日期的财报和数据来源为准。',
  }
}

export function mergeCompany(existing: CompanySnapshot, api: ApiCompany): CompanySnapshot {
  const company: CompanySnapshot = {
    ...existing, quote: api.quote || existing.quote,
    financials: api.financials,
    valuation: api.valuation === undefined ? existing.valuation : api.valuation || { pe: null, forwardPe: null, percentile10y: null, asOf: '', status: 'incomplete', reason: '尚无可验证的估值数据。' },
    earnings: api.earnings, dataErrors: api.errors || {},
  }
  const financials = api.financials
  const percentile = eligiblePercentile(company.valuation)
  const horizon = company.valuation.horizonYears
  const hasPe = company.valuation.algorithmVersion === 4 && company.valuation.currentPeQualified === true && company.valuation.pe !== null
  company.stance = percentile === null ? '无法判断' : percentile <= 20 ? `${horizon}年低位` : percentile >= 80 ? `${horizon}年高位` : `${horizon}年中段`
  company.tone = percentile !== null && percentile <= 20 ? 'positive' : percentile !== null && percentile >= 80 ? 'watch' : 'neutral'
  company.headline = percentile === null
    ? hasPe ? '当前 PE 可核验，历史覆盖尚不足以判断高低。' : '估值暂不具备判断条件，不能据此买入。'
    : percentile <= 20 ? `估值处于近${horizon}年低位，仍需验证利润能否持续。`
      : percentile >= 80 ? `估值处于近${horizon}年高位，需要更多增长兑现。`
        : `估值处于近${horizon}年中段，重点看现金回报。`
  company.summary = percentile === null
    ? company.valuation.reason || '数据尚不完整或已过期，暂不对价格高低作结论。'
    : `每 $100 股价对应过去四季约 $${company.valuation.earningsYieldPercent?.toFixed(2)} 盈利，并非分红或保证回报。${horizon !== 10 ? '十年数据尚未齐全，仅采用已通过覆盖校验的短窗口。' : '历史分位只衡量相对估值，不代表公司内在价值。'}`
  if (financials?.schemaVersion !== 3 || !financials.periodEnd) {
    company.metrics = [
      { label: '营收', value: '等待同步', change: '尚无可比期间', hint: '等待已对齐期间的财报数据' },
      { label: '净利润', value: '等待同步', change: '尚无可比期间', hint: '不使用过期文章数字冒充当前财报' },
    ]
    company.proof = { title: '投入是否值得', status: '无法判断', tone: 'neutral', marginalCoverage: null, explanation: '缺少已对齐期间的财报数据，不使用文章旧值代替。', facts: [] }
    company.qualityWarning = '财务尚未通过当前口径验证。'
    company.tone = 'neutral'
    company.stance = '财务待核查'
    company.headline = '财务证据尚未齐全，暂停综合价格判断。'
    company.financialPeriod = undefined
    company.financialSourceUrl = undefined
    company.cashFlowSourceUrl = undefined
    company.capexConcept = undefined
    if (existing.symbol !== 'NVDA') company.outlook = { ...existing.outlook, baseQuarterProfitB: null, blockedReason: '财务尚未通过当前口径验证，暂停使用旧利润基线。' }
    return company
  }
  const currency = financials.currency || 'USD'
  const money = (value: number | null | undefined) => formatMoney(value, currency)
  company.financialCurrency = currency
  const period = financials.periodType === 'quarter' ? '单季' : financials.periodType === 'annual' ? '年度' : '年初至今'
  company.financialPeriod = `${financials.periodEnd} · ${period} · ${currency === 'TWD' ? '新台币' : '美元'}`
  company.financialSourceUrl = financials.sourceUrl || api.earnings?.latestFiling?.url
  company.cashFlowSourceUrl = financials.cashFlowSourceUrl || company.financialSourceUrl
  company.capexConcept = financials.capexConcept
  company.metrics = [
    { label: `${period}营收`, value: money(financials.revenue), change: growthLabel(financials.revenueYoY), hint: `${financials.periodStart} 至 ${financials.periodEnd} · ${financials.form}` },
    { label: `${period}净利润`, value: money(financials.netIncome), change: growthLabel(financials.netIncomeYoY), hint: '财报净利润，可能包含投资收益与一次性税项' },
    { label: `${period}经营现金`, value: money(financials.operatingCashFlow), change: '业务实际产生的现金', hint: '年初累计现金流已拆分为同期间数值' },
    { label: `${period}自由现金`, value: money(financials.freeCashFlow), change: `现金资本开支 ${money(financials.capex)}`, hint: '同期间经营现金减去现金资本开支；未付融资租赁和资产处置回款不在此口径内' },
  ]
  const delta = financials.fcfDelta
  const negativeCash = financials.freeCashFlow != null && financials.freeCashFlow < 0
  company.proof = {
    title: '投入是否值得',
    status: negativeCash ? '自由现金仍为负' : delta == null ? `${period}现金流` : delta > 0 ? '自由现金改善' : delta < 0 ? '自由现金承压' : '自由现金持平',
    tone: negativeCash ? 'watch' : delta == null || delta === 0 ? 'neutral' : delta > 0 ? 'positive' : 'watch',
    marginalCoverage: financials.marginalCoverage != null && Number.isFinite(financials.marginalCoverage) ? financials.marginalCoverage : null,
    explanation: delta === null || delta === undefined
      ? '暂缺两个可比季度，不把当期现金流正负当成投资回报结论。'
      : `相比上季，自由现金流变化 ${money(delta)}；边际比率是同期现金增量／投入增量，不是项目收益率。`,
    facts: [`经营现金 ${money(financials.operatingCashFlow)}`, `资本开支 ${money(financials.capex)}`, `${period}截至 ${financials.periodEnd}`],
  }
  const investmentEffect = financials.netIncome != null && financials.operatingIncome != null && financials.operatingIncome > 0 && financials.netIncome > financials.operatingIncome * 1.5
  const staleFinancials = Date.now() - new Date(financials.periodEnd).getTime() > 160 * 86400000
  company.qualityWarning = investmentEffect ? '净利润明显高于营业利润：投资／税项可能拉低表面 PE，不能据此判便宜。'
    : api.earnings?.pendingStructuredData || staleFinancials ? '财务期间已滞后，暂停把旧盈利视为当前经营状态。'
      : negativeCash ? '经营现金不足以覆盖现金资本开支，不能只凭低 PE 判断便宜。'
        : delta != null && delta < 0 ? '自由现金流环比减少，低 PE 需要结合现金兑现继续核查。'
        : '仍须持续核对增长、现金回报与竞争变化，不能只看 PE。'
  if (investmentEffect || staleFinancials || api.earnings?.pendingStructuredData) {
    company.stance = '需核查盈利'
    company.tone = 'watch'
    company.headline = investmentEffect ? '表面 PE 受非经营因素影响，低分位不等于便宜。' : '财务信息滞后，暂停价格高低结论。'
  }
  company.sourceNote = `财务：${financials.source || 'SEC Company Facts'}，${company.financialPeriod}。估值：${company.valuation.source || '尚未取得'}，${company.valuation.asOf}。`
  if (api.earnings?.pendingStructuredData) company.sourceNote += '已发现更晚申报，结构化财务尚未追上；旧期数据不冒充最新季度。'
  if (existing.symbol !== 'NVDA') {
    const hasQuarter = currency === 'USD' && financials.periodType === 'quarter' && financials.netIncome != null && financials.netIncome > 0 && !investmentEffect && !staleFinancials && !api.earnings?.pendingStructuredData
    company.outlook = {
      ...existing.outlook,
      baseQuarterProfitB: hasQuarter ? financials.netIncome! / 1e9 : null,
      baseLabel: `${financials.periodEnd} 单季`,
      sourceLabel: `以 ${financials.periodEnd} 财报净利润为基线；增长与 PE 为研究假设，非公司指引。`,
      blockedReason: currency !== 'USD' ? '财务以新台币披露，不能直接乘美元 PE 推导美元市值；美元 ADR 估值已在左侧独立计算。' : investmentEffect ? '净利润明显高于营业利润，可能受投资或税项影响。先核对可持续利润，不直接把这一季外推。' : !hasQuarter ? '尚无最新匹配期间的正单季净利润；年度利润不能当成单季利润再乘四。' : undefined,
    }
  }
  return company
}

export function mergeApiCompanies(current: CompanySnapshot[], incoming: ApiCompany[]) {
  const incomingBySymbol = new Map(incoming.map((item) => [item.symbol, item]))
  const merged = current.map((existing) => {
    const api = incomingBySymbol.get(existing.symbol)
    return api ? mergeCompany(existing, api) : existing
  })
  for (const api of incoming) {
    if (!merged.some((item) => item.symbol === api.symbol)) merged.push(mergeCompany(genericCompany(api), api))
  }
  return merged
}