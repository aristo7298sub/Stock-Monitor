import { test } from 'node:test'
import assert from 'node:assert/strict'
import { seedCompanies } from '../src/data.ts'
import { mergeApiCompanies, formatMoney, eligiblePercentile, suspendJudgments } from '../src/liveData.ts'

const valuation = { algorithmVersion: 4, currentPeQualified: true, status: 'qualified' as const, pe: 16.81, forwardPe: null, percentile10y: 0, percentile: 0, horizonYears: 10, earningsYieldPercent: 5.95, asOf: '2026-09-04', frequency: 'daily' as const, sampleCount: 2514 }
const financials = { schemaVersion: 3, currency: 'USD', revenue: 120e9, netIncome: 30e9, operatingCashFlow: 45e9, capex: 20e9, freeCashFlow: 25e9, periodStart: '2026-04-01', periodEnd: '2026-06-30', periodType: 'quarter' as const }

test('pre-seeded companies receive real valuation and financials including zero percentile', () => {
  const companies = mergeApiCompanies(seedCompanies, [{ symbol: 'GOOGL', name: 'Alphabet', valuation, financials }])
  const google = companies.find((company) => company.symbol === 'GOOGL')!
  assert.equal(google.valuation.percentile10y, 0)
  assert.equal(google.valuation.sampleCount, 2514)
  assert.equal(google.metrics[0].value, '$1,200 亿')
  assert.equal(google.outlook.baseQuarterProfitB, 30)
  assert.match(google.headline, /近10年/)
})

test('missing update never clears last good price or valuation', () => {
  const initial = mergeApiCompanies(seedCompanies, [{ symbol: 'AAPL', name: 'Apple', valuation, quote: { price: 320, changePercent: 0, asOf: '2026-09-04', source: 'test' }, financials }])
  const updated = mergeApiCompanies(initial, [{ symbol: 'AAPL', name: 'Apple', errors: { valuation: 'offline' }, financials }])
  const apple = updated.find((company) => company.symbol === 'AAPL')!
  assert.equal(apple.quote.price, 320)
  assert.equal(apple.valuation.pe, 16.81)
  assert.equal(apple.dataErrors?.valuation, 'offline')
})

test('annual profit never becomes a quarter profit times four', () => {
  const updated = mergeApiCompanies(seedCompanies, [{ symbol: 'TSM', name: 'TSMC', valuation, financials: { ...financials, periodType: 'annual' } }])
  const tsm = updated.find((company) => company.symbol === 'TSM')!
  assert.equal(tsm.outlook.baseQuarterProfitB, null)
  assert.match(tsm.metrics[1].label, /年度/)
})

test('NVDA author scenario is retained separately from live financials', () => {
  const updated = mergeApiCompanies(seedCompanies, [{ symbol: 'NVDA', name: 'NVIDIA', valuation, financials }])
  const nvidia = updated.find((company) => company.symbol === 'NVDA')!
  assert.equal(nvidia.outlook.baseQuarterProfitB, 59.69)
  assert.equal(nvidia.metrics[1].value, '$300 亿')
})

test('zero financial amount is not missing', () => {
  assert.equal(formatMoney(0), '$0 亿')
  assert.equal(formatMoney(null), '未取得')
})

test('large non-operating profit is not automatically projected as recurring earnings', () => {
  const updated = mergeApiCompanies(seedCompanies, [{ symbol: 'GOOGL', name: 'Alphabet', valuation, financials: { ...financials, netIncome: 110e9, operatingIncome: 40e9 } }])
  const google = updated.find((company) => company.symbol === 'GOOGL')!
  assert.equal(google.outlook.baseQuarterProfitB, null)
  assert.match(google.outlook.blockedReason!, /可持续利润/)
  assert.equal(google.valuation.percentile10y, 0)
  assert.equal(google.stance, '需核查盈利')
})

test('annual or obsolete algorithm results cannot drive a price judgment', () => {
  assert.equal(eligiblePercentile({ ...valuation, frequency: 'annual' }), null)
  assert.equal(eligiblePercentile({ ...valuation, algorithmVersion: 3 }), null)
  assert.equal(eligiblePercentile({ ...valuation, status: 'stale' }), null)
  assert.equal(eligiblePercentile(valuation), 0)
})

test('short qualified window is not called ten years', () => {
  const updated = mergeApiCompanies(seedCompanies, [{ symbol: 'GOOGL', name: 'Alphabet', valuation: { ...valuation, status: 'limited', horizonYears: 3, percentile10y: null, percentile: 1.19 }, financials }])
  const google = updated.find((company) => company.symbol === 'GOOGL')!
  assert.match(google.headline, /近3年/)
  assert.doesNotMatch(google.headline, /近10年/)
})

test('TWD financials cannot be labeled dollars or projected as USD market cap', () => {
  const updated = mergeApiCompanies(seedCompanies, [{ symbol: 'TSM', name: 'TSMC', valuation, financials: { ...financials, currency: 'TWD' } }])
  const tsm = updated.find((company) => company.symbol === 'TSM')!
  assert.match(tsm.metrics[0].value, /^NT\$/)
  assert.equal(tsm.outlook.baseQuarterProfitB, null)
  assert.match(tsm.outlook.blockedReason!, /新台币/)
})

test('explicitly missing valuation replaces an old low signal', () => {
  const initial = mergeApiCompanies(seedCompanies, [{ symbol: 'MSFT', name: 'Microsoft', valuation, financials }])
  const updated = mergeApiCompanies(initial, [{ symbol: 'MSFT', name: 'Microsoft', valuation: null, financials }])
  const microsoft = updated.find((company) => company.symbol === 'MSFT')!
  assert.equal(eligiblePercentile(microsoft.valuation), null)
  assert.equal(microsoft.stance, '无法判断')
})

test('disconnection retains dated values but withdraws price judgments', () => {
  const initial = mergeApiCompanies(seedCompanies, [{ symbol: 'MSFT', name: 'Microsoft', valuation, financials }])
  const microsoft = suspendJudgments(initial).find((company) => company.symbol === 'MSFT')!
  assert.equal(microsoft.valuation.pe, valuation.pe)
  assert.equal(eligiblePercentile(microsoft.valuation), null)
  assert.equal(microsoft.stance, '连接中断')
})

test('improving cash flow is still flagged when it remains negative', () => {
  const updated = mergeApiCompanies(seedCompanies, [{ symbol: 'AMZN', name: 'Amazon', valuation, financials: { ...financials, freeCashFlow: -8e9, fcfDelta: 9e9 } }])
  const amazon = updated.find((company) => company.symbol === 'AMZN')!
  assert.equal(amazon.proof.tone, 'watch')
  assert.equal(amazon.proof.status, '自由现金仍为负')
})