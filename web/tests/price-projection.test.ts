import { test } from 'node:test'
import assert from 'node:assert/strict'
import { seedCompanies } from '../src/data.ts'
import { historicalPriceVerdict, nvidiaArticleScenario, projectRevenuePrice, revenueProjectionBaseline } from '../src/priceProjection.ts'

const base = { annualRevenue: 100e9, currency: 'USD', netMargin: 20, targetPe: 20, dilutedShares: 10e9, firstGrowth: 10, secondGrowth: 20, annualShareChange: 0, years: 2 as const }
const now = Date.parse('2026-09-09T00:00:00Z')
const company = { ...seedCompanies[0], financials: { schemaVersion: 3, periodType: 'quarter' as const, periodEnd: '2026-06-30', revenue: 100, netIncome: 20, operatingIncome: 25, freeCashFlow: 10 }, valuation: { algorithmVersion: 4, currentPeQualified: true, status: 'qualified' as const, pe: 20, forwardPe: null, percentile10y: 10, percentile: 10, horizonYears: 10, asOf: '2026-09-08', frequency: 'daily' as const } }

test('revenue becomes profit before PE and is divided by shares for price', () => {
  const value = projectRevenuePrice(base)!
  assert.ok(Math.abs(value.projectedRevenue - 132e9) < 0.001)
  assert.ok(Math.abs(value.projectedProfit - 26.4e9) < 0.001)
  assert.ok(Math.abs(value.targetPrice - 52.8) < 1e-10)
})

test('net margin and dilution affect price; one-year model ignores second-year growth', () => {
  const full = projectRevenuePrice(base)!
  assert.ok(Math.abs(projectRevenuePrice({ ...base, netMargin: 10 })!.targetPrice - full.targetPrice / 2) < 1e-10)
  assert.ok(Math.abs(projectRevenuePrice({ ...base, annualShareChange: 10 })!.targetPrice - full.targetPrice / 1.21) < 1e-10)
  assert.ok(Math.abs(projectRevenuePrice({ ...base, years: 1 })!.targetPrice - 44) < 1e-10)
  assert.equal(projectRevenuePrice({ ...base, years: 1, secondGrowth: NaN })!.targetPrice, projectRevenuePrice({ ...base, years: 1 })!.targetPrice)
})

test('incomplete inputs, loss margins and unconverted TWD cannot produce dollar prices', () => {
  for (const change of [{ currency: 'TWD' }, { dilutedShares: 0 }, { netMargin: 0 }, { netMargin: -20 }, { netMargin: 101 }, { targetPe: NaN }, { annualShareChange: -100 }, { firstGrowth: -100 }]) assert.equal(projectRevenuePrice({ ...base, ...change }), null)
})

test('article scenario reproduces the constant-margin method without hidden intermediate rounding', () => {
  const article = nvidiaArticleScenario
  const value = projectRevenuePrice({ ...base, annualRevenue: article.quarterRevenue * 4, netMargin: article.quarterProfit / article.quarterRevenue * 100, firstGrowth: article.firstGrowth, secondGrowth: article.secondGrowth, targetPe: article.targetPe, dilutedShares: 24.285e9 })!
  assert.ok(Math.abs(value.projectedMarketCap / 1e12 - 10.553192) < 1e-9)
  assert.ok(Math.abs(value.targetPrice - value.projectedMarketCap / 24.285e9) < 1e-10)
})

test('simple historical verdict retains real window and withdraws when offline or stale', () => {
  assert.equal(historicalPriceVerdict(company, true, now).label, '偏便宜')
  assert.equal(historicalPriceVerdict({ ...company, valuation: { ...company.valuation, percentile: 90 } }, true, now).label, '偏贵')
  assert.equal(historicalPriceVerdict({ ...company, valuation: { ...company.valuation, percentile: 50 } }, true, now).label, '中间价位')
  assert.equal(historicalPriceVerdict(company, false, now).label, '暂不能判断')
  assert.equal(historicalPriceVerdict({ ...company, financials: { ...company.financials, periodEnd: '2024-06-30' } }, true, now).label, '暂不能判断')
  assert.match(historicalPriceVerdict({ ...company, valuation: { ...company.valuation, horizonYears: 3, percentile10y: null, status: 'limited' } }, true, now).basis, /3 年/)
})

test('exceptional profit blocks an unqualified cheap label', () => {
  const value = historicalPriceVerdict({ ...company, financials: { ...company.financials, netIncome: 80 } }, true, now)
  assert.equal(value.label, '低 PE 需核查')
  assert.equal(value.tone, 'watch')
})

test('latest quarter is explicitly annualized, annual revenue is never multiplied again', () => {
  const usd = { ...company, financials: { ...company.financials, currency: 'USD' } }
  const quarter = revenueProjectionBaseline(usd, 'latest', now)
  assert.equal(quarter.annualRevenue, 400)
  assert.equal(quarter.netMargin, 20)
  assert.match(quarter.basisLabel, /年化/)
  assert.equal(revenueProjectionBaseline({ ...usd, financials: { ...usd.financials, periodType: 'annual' } }, 'latest', now).annualRevenue, 100)
})

test('exceptional margins, stale facts and TWD are not silently used in USD forecasts', () => {
  const usd = { ...company, financials: { ...company.financials, currency: 'USD' } }
  assert.equal(revenueProjectionBaseline({ ...usd, financials: { ...usd.financials, netIncome: 80 } }, 'latest', now).netMargin, null)
  assert.equal(revenueProjectionBaseline({ ...usd, financials: { ...usd.financials, currency: 'TWD' } }, 'latest', now).annualRevenue, null)
  assert.equal(revenueProjectionBaseline({ ...usd, financials: { ...usd.financials, periodEnd: '2024-06-30' } }, 'latest', now).annualRevenue, null)
  assert.equal(revenueProjectionBaseline(usd, 'latest', now).dilutedShares, null)
})

test('article base is a separate frozen scenario and never applied to another company', () => {
  assert.equal(revenueProjectionBaseline(company, 'article', now).annualRevenue, nvidiaArticleScenario.quarterRevenue * 4)
  assert.equal(revenueProjectionBaseline({ ...company, symbol: 'TSM', financials: { ...company.financials, currency: 'TWD' } }, 'article', now).annualRevenue, null)
})