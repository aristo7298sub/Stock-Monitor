import { test } from 'node:test'
import assert from 'node:assert/strict'
import { assessInvestment, cashBaseline, discountedCashValue, valuationReviewKey } from '../src/investment.ts'
import { seedCompanies } from '../src/data.ts'

const now = Date.parse('2026-09-09T00:00:00Z')
const valuation = { algorithmVersion: 4, currentPeQualified: true, status: 'qualified' as const, pe: 10, forwardPe: null, percentile: 1, percentile10y: 1, asOf: '2026-09-08', epsPeriodEnd: '2026-06-30', horizonYears: 10, frequency: 'daily' as const }
const financials = { schemaVersion: 3, currency: 'USD', periodType: 'quarter' as const, periodEnd: '2026-06-30', revenue: 100, revenueYoY: 10, operatingIncome: 25, netIncome: 20, operatingCashFlow: 30, capex: 10, freeCashFlow: 20 }

test('low PE cannot cancel a cash deficit or non-operating profit warning', () => {
  const result = assessInvestment({ ...financials, netIncome: 80, freeCashFlow: -10, capex: 40 }, valuation, false, now)
  assert.equal(result.state, 'caution')
  assert.ok(result.concerns.some(metric => metric.key === 'cash'))
  assert.ok(result.concerns.some(metric => metric.key === 'profitQuality'))
})

test('missing, stale and pending evidence cannot create positive selection reasons', () => {
  for (const snapshot of [undefined, { ...financials, periodEnd: '2024-06-30' }]) {
    const result = assessInvestment(snapshot, valuation, false, now)
    assert.equal(result.state, 'incomplete')
    assert.equal(result.supports.length, 0)
  }
  assert.equal(assessInvestment(financials, valuation, true, now).supports.length, 0)
})

test('healthy metrics support further research, not an automatic buy decision', () => {
  const result = assessInvestment(financials, valuation, false, now)
  assert.equal(result.state, 'incomplete')
  assert.equal(result.label, '长期证据待补')
  assert.equal(result.supports.length, 5)
  assert.ok(result.missing.includes('可持续现金与安全边际假设'))
  assert.equal(result.metrics.find(metric => metric.key === 'yield')?.value, 10)
})

test('long-term evidence must be present and unusual ROE is not automatically quality', () => {
  const quality = { version: 1, currency: 'USD', periodEnd: '2026-06-30', revenueCagr5y: 10, cashYearsKnown: 5, cashYearsPositive: 5, profitYearsKnown: 5, profitYearsPositive: 5, historyContiguous: true, roeTtm: 20, longDebtToOcf: 0.5, cashPerShareProxy: 10, history: [] }
  assert.equal(assessInvestment({ ...financials, quality }, valuation, false, now).state, 'research')
  const unusual = assessInvestment({ ...financials, quality: { ...quality, roeTtm: 150 } }, valuation, false, now)
  assert.equal(unusual.state, 'caution')
  assert.ok(unusual.concerns.some(metric => metric.key === 'roe'))
  assert.equal(assessInvestment({ ...financials, quality: { ...quality, cashYearsKnown: 0 } }, valuation, false, now).state, 'incomplete')
})

test('currency-independent ratios stay comparable without converting TWD to USD', () => {
  const result = assessInvestment({ ...financials, currency: 'TWD' }, valuation, false, now)
  assert.equal(result.metrics.find(metric => metric.key === 'margin')?.value, 25)
  assert.equal(result.metrics.find(metric => metric.key === 'cash')?.value, 20)
})

test('cash-flow valuation matches a level perpetuity with explicit safety margin', () => {
  const result = discountedCashValue({ cashPerShare: 10, growth: 0, requiredReturn: 10, terminalGrowth: 0, safetyMargin: 25, years: 10 }, 80)!
  assert.ok(Math.abs(result.value - 100) < 1e-9)
  assert.ok(Math.abs(result.entryPrice - 75) < 1e-9)
  assert.ok(Math.abs(result.marginAtPrice! - 20) < 1e-9)
})

test('invalid terminal growth and nonpositive cash cannot manufacture valuation', () => {
  const base = { cashPerShare: 10, growth: 5, requiredReturn: 10, terminalGrowth: 2, safetyMargin: 25, years: 10 }
  assert.equal(discountedCashValue({ ...base, terminalGrowth: 10 }, 80), null)
  assert.equal(discountedCashValue({ ...base, cashPerShare: -1 }, 80), null)
  assert.equal(discountedCashValue({ ...base, growth: NaN }, 80), null)
  assert.equal(discountedCashValue(base, null)?.marginAtPrice, null)
  assert.ok(discountedCashValue({ ...base, requiredReturn: 12 }, 80)!.value < discountedCashValue(base, 80)!.value)
})

test('TWD or negative cash proxies never prefill USD valuation', () => {
  const quality = { version: 1, currency: 'TWD', periodEnd: '2026-06-30', revenueCagr5y: 10, cashYearsKnown: 0, cashYearsPositive: 0, profitYearsKnown: 5, profitYearsPositive: 5, historyContiguous: true, roeTtm: null, longDebtToOcf: null, cashPerShareProxy: 10, history: [] }
  const company = { ...seedCompanies[0], valuation, financials: { ...financials, quality } }
  assert.equal(cashBaseline(company, now), null)
  assert.equal(cashBaseline({ ...company, financials: { ...financials, quality: { ...quality, currency: 'USD', cashPerShareProxy: -2 } } }, now), null)
  assert.equal(cashBaseline({ ...company, financials: { ...financials, quality: { ...quality, currency: 'USD' } } }, now), 10)
  assert.equal(cashBaseline({ ...company, valuation: { ...valuation, epsPeriodEnd: '2026-03-31' }, financials: { ...financials, quality: { ...quality, currency: 'USD' } } }, now), null)
})

test('a reviewed valuation is invalidated by new financial evidence or changed assumptions, not quote polling', () => {
  const company = { ...seedCompanies[0], financials, valuation }
  const assumptions = { cashPerShare: 10, growth: 5, requiredReturn: 10, terminalGrowth: 2, safetyMargin: 25, years: 10 }
  const key = valuationReviewKey(company, assumptions)
  assert.equal(valuationReviewKey({ ...company, quote: { ...company.quote, price: 110 } }, assumptions), key)
  assert.notEqual(valuationReviewKey({ ...company, financials: { ...financials, periodEnd: '2026-09-30' } }, assumptions), key)
  assert.notEqual(valuationReviewKey({ ...company, financials: { ...financials, freeCashFlowTtm: 50 } }, assumptions), key)
  assert.notEqual(valuationReviewKey(company, { ...assumptions, growth: 7 }), key)
})