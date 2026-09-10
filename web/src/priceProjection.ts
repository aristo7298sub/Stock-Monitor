import type { CompanySnapshot } from './data'
import { assessInvestment } from './investment.ts'
import { eligiblePercentile } from './liveData.ts'

export interface RevenueProjectionInput {
  annualRevenue: number
  currency: string
  netMargin: number
  targetPe: number
  dilutedShares: number
  firstGrowth: number
  secondGrowth: number
  annualShareChange: number
  years: 1 | 2
}

export function projectRevenuePrice(input: RevenueProjectionInput) {
  const { annualRevenue, currency, netMargin, targetPe, dilutedShares, firstGrowth, secondGrowth, annualShareChange, years } = input
  if (currency !== 'USD' || ![annualRevenue, netMargin, targetPe, dilutedShares, firstGrowth, annualShareChange, years].every(Number.isFinite) || years === 2 && !Number.isFinite(secondGrowth)) return null
  if (annualRevenue <= 0 || netMargin <= 0 || netMargin > 100 || targetPe <= 0 || dilutedShares <= 0 || firstGrowth <= -100 || years === 2 && secondGrowth <= -100 || annualShareChange <= -100 || ![1, 2].includes(years)) return null
  const revenueFactor = (1 + firstGrowth / 100) * (years === 2 ? 1 + secondGrowth / 100 : 1)
  const projectedRevenue = annualRevenue * revenueFactor
  const projectedProfit = projectedRevenue * netMargin / 100
  const projectedShares = dilutedShares * (1 + annualShareChange / 100) ** years
  const projectedEps = projectedProfit / projectedShares
  const projectedMarketCap = projectedProfit * targetPe
  const targetPrice = projectedMarketCap / projectedShares
  return [projectedRevenue, projectedProfit, projectedShares, projectedEps, projectedMarketCap, targetPrice].every(Number.isFinite)
    ? { projectedRevenue, projectedProfit, projectedShares, projectedEps, projectedMarketCap, targetPrice } : null
}

export function historicalPriceVerdict(company: CompanySnapshot, connected: boolean, now = Date.now()) {
  const percentile = eligiblePercentile(company.valuation)
  const assessment = assessInvestment(company.financials, company.valuation, company.earnings?.pendingStructuredData || !connected, now)
  const horizon = company.valuation.horizonYears
  if (!connected || !assessment.fresh || percentile === null || percentile < 0 || percentile > 100 || !horizon) {
    return { tone: 'neutral' as const, label: '暂不能判断', percentile: null, basis: '等待有效价格与财报', reason: !connected ? '连接中断，旧数据不用于判断。' : company.valuation.reason || '历史窗口或最新财报尚未通过校验。' }
  }
  const profitConcern = assessment.concerns.some(metric => metric.key === 'profitQuality')
  if (profitConcern) return { tone: 'watch' as const, label: percentile <= 20 ? '低 PE 需核查' : '盈利需核查', percentile, basis: `相对自身近 ${horizon} 年历史`, reason: '净利润包含明显非经营影响，不能把表面 PE 直接当作贵便宜的依据。' }
  const label = percentile <= 20 ? '偏便宜' : percentile >= 80 ? '偏贵' : '中间价位'
  return { tone: percentile <= 20 ? 'positive' as const : percentile >= 80 ? 'watch' as const : 'neutral' as const, label, percentile, basis: `相对自身近 ${horizon} 年历史`, reason: company.financials?.freeCashFlow != null && company.financials.freeCashFlow < 0 ? '自由现金仍为负，历史低估值不等于值得买入。' : company.financials?.fcfDelta != null && company.financials.fcfDelta < 0 ? '自由现金环比减少，仍需观察盈利能否兑现为现金。' : '这是自身历史估值的位置，不是对未来涨跌的保证。' }
}

export const nvidiaArticleScenario = {
  sourceUrl: 'https://mp.weixin.qq.com/s/o4UlHPBFUFh_gaPatoAmKA',
  publishedAt: '2026-08-31',
  quarterRevenue: 96.22e9,
  quarterProfit: 59.69e9,
  firstGrowth: 70,
  secondGrowth: 30,
  targetPe: 20,
  targetLabel: '2028 年中',
}

export function revenueProjectionBaseline(company: CompanySnapshot, basis: 'latest' | 'article', now = Date.now()) {
  const financials = company.financials
  const quality = financials?.quality
  const fresh = assessInvestment(financials, company.valuation, company.earnings?.pendingStructuredData, now).fresh
  const positive = (value: number | null | undefined): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0
  const article = basis === 'article' && company.symbol === 'NVDA'
  const shares = fresh && quality?.version === 1 && quality.currency === 'USD' && quality.periodEnd === financials?.periodEnd && positive(quality.dilutedShares) ? quality.dilutedShares : null
  if (article) return {
    annualRevenue: nvidiaArticleScenario.quarterRevenue * 4,
    netMargin: nvidiaArticleScenario.quarterProfit / nvidiaArticleScenario.quarterRevenue * 100,
    dilutedShares: shares, basisLabel: '文章基期：2026 年二季度 × 4',
    sharesLabel: quality?.sharesPeriod || '尚未取得', warning: '70% / 30% 增长与利润率稳定来自文章情景，不是本平台核验的未来指引。',
  }
  const period = financials?.periodType
  const annualRevenue = fresh && financials?.currency === 'USD'
    ? period === 'quarter' && positive(financials.revenue) ? financials.revenue * 4
      : period === 'annual' && positive(financials.revenue) ? financials.revenue
        : positive(financials.revenueTtm) ? financials.revenueTtm : null
    : null
  const income = period === 'quarter' || period === 'annual' ? financials?.netIncome : financials?.netIncomeTtm
  const operating = period === 'quarter' || period === 'annual' ? financials?.operatingIncome : financials?.operatingIncomeTtm
  const revenue = period === 'quarter' || period === 'annual' ? financials?.revenue : financials?.revenueTtm
  const marginUsable = annualRevenue !== null && positive(income) && positive(operating) && positive(revenue) && income <= operating * 1.5 && income <= revenue
  return {
    annualRevenue, netMargin: marginUsable ? income / revenue * 100 : null, dilutedShares: shares,
    basisLabel: `${financials?.periodEnd || '待取得'} · ${period === 'quarter' ? '单季营收 × 4（年化）' : period === 'annual' ? '全年营收' : '过去四季营收'}`,
    sharesLabel: quality?.sharesPeriod || '尚未取得',
    warning: financials?.currency === 'TWD' ? '台积电财务为新台币；未核验美元营收与 ADR 等价股数，不自动推演美元股价。'
      : !fresh ? '最新财务尚未通过校验，不自动填入旧基期。'
        : !marginUsable ? '净利率含非经营影响或证据不全，请自行核验可持续净利率。'
          : shares === null ? '尚未取得同期间股数，不能将市值换算成每股价格。' : null,
  }
}