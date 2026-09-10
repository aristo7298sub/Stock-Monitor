import { useEffect, useState } from 'react'
import { ArrowRight, BookOpen, ChevronDown, CircleAlert, ExternalLink, Info, RotateCcw, SlidersHorizontal } from 'lucide-react'
import type { CompanySnapshot } from './data'
import { formatMoney } from './liveData'
import { assessInvestment } from './investment'
import { historicalPriceVerdict, nvidiaArticleScenario, projectRevenuePrice, revenueProjectionBaseline } from './priceProjection'
import './PriceOverview.css'

interface ProjectionDraft {
  version: 1
  basis: 'latest' | 'article'
  years: 1 | 2
  firstGrowth: string
  secondGrowth: string
  netMargin: string | null
  targetPe: string
  annualRevenue: string | null
  dilutedShares: string | null
  annualShareChange: string
}

const defaults: ProjectionDraft = { version: 1, basis: 'latest', years: 2, firstGrowth: '10', secondGrowth: '10', netMargin: null, targetPe: '20', annualRevenue: null, dilutedShares: null, annualShareChange: '0' }

function readProjection(symbol: string): ProjectionDraft {
  try {
    const stored = JSON.parse(localStorage.getItem(`stock-monitor-revenue-${symbol}`) || 'null') as Partial<ProjectionDraft> | null
    if (!stored || stored.version !== 1) return { ...defaults }
    const result = { ...defaults }
    for (const key of ['firstGrowth', 'secondGrowth', 'targetPe', 'annualShareChange'] as const) if (typeof stored[key] === 'string') result[key] = stored[key]
    for (const key of ['netMargin', 'annualRevenue', 'dilutedShares'] as const) if (typeof stored[key] === 'string') result[key] = stored[key]
    result.basis = stored.basis === 'article' && symbol === 'NVDA' ? 'article' : 'latest'
    result.years = stored.years === 1 ? 1 : 2
    return result
  } catch { return { ...defaults } }
}

function numberValue(override: string | null, automatic: number | null) {
  return override === null ? automatic ?? NaN : override.trim() === '' ? NaN : Number(override)
}

function inputValue(override: string | null, automatic: number | null) {
  return override === null ? automatic === null ? '' : String(Number(automatic.toFixed(2))) : override
}

function priceText(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '--' : `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function ScenarioInput({ label, value, suffix, onChange, min, max, step = 1 }: { label: string; value: string; suffix: string; onChange: (value: string) => void; min?: number; max?: number; step?: number }) {
  return <label className="scenario-field"><span>{label}</span><div><input aria-label={label} type="number" value={value} min={min} max={max} step={step} placeholder="待核验" onChange={event => onChange(event.target.value)} /><small>{suffix}</small></div></label>
}

export function PriceOverview({ company, connected, onResearch, onSources }: { company: CompanySnapshot; connected: boolean; onResearch: () => void; onSources: () => void }) {
  const [draft, setDraft] = useState(() => readProjection(company.symbol))
  const [storageError, setStorageError] = useState(false)
  useEffect(() => {
    try { localStorage.setItem(`stock-monitor-revenue-${company.symbol}`, JSON.stringify(draft)); setStorageError(false) }
    catch { setStorageError(true) }
  }, [company.symbol, draft])
  const verdict = historicalPriceVerdict(company, connected)
  const baseline = revenueProjectionBaseline(company, draft.basis)
  const current = company.valuation
  const priceValid = connected && current.algorithmVersion === 4 && current.currentPeQualified === true && typeof current.price === 'number' && Number.isFinite(current.price) && current.price > 0
  const price = priceValid ? current.price! : null
  const fresh = assessInvestment(company.financials, current, company.earnings?.pendingStructuredData || !connected).fresh
  const annualRevenue = numberValue(draft.annualRevenue, baseline.annualRevenue === null ? null : baseline.annualRevenue / 1e8) * 1e8
  const dilutedShares = numberValue(draft.dilutedShares, baseline.dilutedShares === null ? null : baseline.dilutedShares / 1e8) * 1e8
  const netMargin = numberValue(draft.netMargin, baseline.netMargin)
  const result = connected && fresh ? projectRevenuePrice({ annualRevenue, dilutedShares, currency: 'USD', netMargin, targetPe: numberValue(draft.targetPe, null), firstGrowth: numberValue(draft.firstGrowth, null), secondGrowth: numberValue(draft.secondGrowth, null), annualShareChange: numberValue(draft.annualShareChange, null), years: draft.years }) : null
  const relative = result && price !== null ? (result.targetPrice / price - 1) * 100 : null
  const endpoint = draft.basis === 'article' ? '2026-06-30' : company.financials?.periodEnd
  const endDate = endpoint ? new Date(`${endpoint}T00:00:00Z`) : null
  const targetLabel = endDate && Number.isFinite(endDate.getTime()) ? `${endDate.getUTCFullYear() + draft.years} 年 ${endDate.getUTCMonth() + 1} 月` : `${draft.years} 年后`
  const set = (patch: Partial<ProjectionDraft>) => setDraft(previous => ({ ...previous, ...patch }))
  const articleChanged = draft.basis === 'article' && (draft.firstGrowth !== String(nvidiaArticleScenario.firstGrowth) || draft.secondGrowth !== String(nvidiaArticleScenario.secondGrowth) || draft.targetPe !== String(nvidiaArticleScenario.targetPe) || draft.netMargin !== null || draft.annualRevenue !== null || draft.dilutedShares !== null || draft.annualShareChange !== '0')
  const useLatest = () => setDraft({ ...defaults, years: draft.years })
  const useArticle = () => setDraft({ ...defaults, basis: 'article', firstGrowth: String(nvidiaArticleScenario.firstGrowth), secondGrowth: String(nvidiaArticleScenario.secondGrowth), targetPe: String(nvidiaArticleScenario.targetPe) })
  const missing = !connected ? '连接中断，暂停股价推演与价格对比。'
    : !fresh ? '等待最新财报，旧基期不继续生成参考股价。'
      : !Number.isFinite(annualRevenue) || annualRevenue <= 0 ? '缺少美元年营收；原币种数据不会自动混入。'
        : !Number.isFinite(dilutedShares) || dilutedShares <= 0 ? '缺少股数，尚不能将未来市值换算为股价。'
          : !Number.isFinite(netMargin) || netMargin <= 0 || netMargin > 100 ? '需要核验正的可持续净利率，不能直接沿用异常利润。'
            : '参数不成立，请检查增长率、PE 或股数变化。'
  const rangeMaximum = Math.max(price || 0, result?.targetPrice || 0, 1) * 1.12
  return <main className="price-overview">
    <section className={`quick-verdict ${verdict.tone}`} aria-label="估值结论">
      <div className="quick-verdict-copy"><span className="overview-eyebrow">现在贵不贵 <span>· {verdict.basis}</span></span><h2>{verdict.label}</h2><p>{verdict.reason}</p></div>
      <div className="quick-price-metrics">
        <div><span>收盘 PE <button className="info-button" title="查看 PE 口径与数据来源" onClick={onSources}><Info size={13} /></button></span><strong>{priceValid && current.pe != null ? current.pe.toFixed(1) : '--'}<small>倍</small></strong><small>{priceValid ? current.asOf : '过去四季稀释盈利'}</small></div>
        <div><span>历史位置</span><strong>{verdict.percentile === null ? '--' : `${verdict.percentile.toFixed(1)}%`}</strong><small>{verdict.percentile === null ? '等待合格样本' : `近 ${current.horizonYears} 年 · 越低越便宜`}</small></div>
      </div>
      <div className="simple-pe-scale" aria-label="历史估值位置"><div><span>历史便宜区</span><span>中间区间</span><span>历史昂贵区</span></div>{verdict.percentile !== null && <i style={{ left: `${Math.max(1, Math.min(99, verdict.percentile))}%` }} />}</div>
    </section>

    <section className="revenue-scenario" aria-label="营收与 PE 股价推演">
      <header className="scenario-heading"><div><span className="overview-eyebrow">未来看业绩</span><h3>营收增长，能对应多少股价？</h3></div><div className="scenario-commands"><div className="scenario-basis" role="group" aria-label="推演基期"><button aria-pressed={draft.basis === 'latest'} onClick={useLatest}>最新财报</button>{company.symbol === 'NVDA' && <button aria-pressed={draft.basis === 'article'} onClick={useArticle}><BookOpen size={12} />文章情景</button>}</div><button className="icon-button" title="恢复最新财报与示例参数" onClick={() => setDraft({ ...defaults })}><RotateCcw size={15} /></button></div></header>
      <div className="scenario-main">
        <div className="scenario-controls">
          <div className="projection-horizon"><span>推演时点</span><div role="group" aria-label="推演年数"><button aria-pressed={draft.years === 1} onClick={() => set({ years: 1 })}>一年后</button><button aria-pressed={draft.years === 2} onClick={() => set({ years: 2 })}>两年后</button></div><small>{targetLabel} · 相对财报基期</small></div>
          <div className={`simple-scenario-inputs ${draft.years === 1 ? 'one-year' : ''}`}>
            <ScenarioInput label="第一年营收增长" value={draft.firstGrowth} suffix="%" min={-99} max={200} onChange={value => set({ firstGrowth: value })} />
            {draft.years === 2 && <ScenarioInput label="第二年营收增长" value={draft.secondGrowth} suffix="%" min={-99} max={200} onChange={value => set({ secondGrowth: value })} />}
            <ScenarioInput label="未来净利率" value={inputValue(draft.netMargin, baseline.netMargin)} suffix="%" min={0.01} max={100} step={0.5} onChange={value => set({ netMargin: value })} />
            <ScenarioInput label="未来给予 PE" value={draft.targetPe} suffix="倍" min={1} max={100} onChange={value => set({ targetPe: value })} />
          </div>
          <p className="scenario-assumption-note">{articleChanged ? '文章基期 · 参数已自定义，不再是原文情景。' : draft.basis === 'article' ? '文章基期与增长情景，非本平台确认的公司指引。' : '增长与 PE 为示例假设；净利率默认保持基期水平。'}</p>
          {(draft.annualRevenue !== null || draft.dilutedShares !== null) && <p className="scenario-assumption-note">基期营收或股数已手动覆盖，数值不是自动财报事实。</p>}
          {baseline.warning && <p className="scenario-source-warning"><CircleAlert size={13} />{baseline.warning}</p>}
        </div>
        <div className="scenario-answer">
          <div className="scenario-price-pair"><div><span>参考收盘价</span><strong>{priceText(price)}</strong><small>{price !== null ? current.asOf : '有效行情待取得'}</small></div><ArrowRight size={19} /><div><span>{targetLabel} 情景股价</span><strong>{priceText(result?.targetPrice)}</strong><small>假设兑现时 · 未折现</small></div></div>
          {result && price !== null ? <>
            <div className="price-comparison-bars" aria-label="收盘与未来情景股价对照"><span style={{ width: `${Math.max(1, price / rangeMaximum * 100)}%` }} /><b style={{ width: `${Math.max(1, result.targetPrice / rangeMaximum * 100)}%` }} /></div>
            <p className={`scenario-price-difference ${relative !== null && relative >= 0 ? 'positive' : 'negative'}`}>相对收盘 {relative !== null && relative > 0 ? '+' : ''}{relative?.toFixed(1)}%<span>仅股价差，不含股息</span></p>
            <p className="future-price-caveat">未来情景价不等于今天的合理价，也不是预期收益承诺。</p>
          </> : <p className="projection-unavailable"><CircleAlert size={15} />{result ? '情景可计算，但当前价格失效，暂停涨跌幅对比。' : missing}</p>}
        </div>
      </div>
      <div className="simple-formula" aria-label="股价推演公式"><span>年营收 <b>{result ? formatMoney(result.projectedRevenue) : '--'}</b></span><i>×</i><span>净利率 <b>{Number.isFinite(netMargin) ? `${netMargin.toFixed(1)}%` : '--'}</b></span><i>÷</i><span>股数 <b>{result ? `${(result.projectedShares / 1e8).toFixed(2)} 亿股` : '--'}</b></span><i>×</i><span>PE <b>{draft.targetPe || '--'} 倍</b></span><i>=</i><strong>{priceText(result?.targetPrice)}</strong></div>
      <p className="formula-explanation">注：情景股价 = 年营收 × 净利率 ÷ 股数 × PE。其中，年营收 × 净利率 = 年净利润；年净利润 ÷ 股数 = 每股收益（EPS）；PE 表示市场愿意为每股一年的利润支付多少倍价格。结果取决于这些假设，不代表股价一定会达到。</p>
      <details className="projection-details"><summary><SlidersHorizontal size={14} /><span>基期、股数与原文依据</span><ChevronDown size={14} /></summary><div className="projection-details-content"><p>{baseline.basisLabel}。单季年化不是实际全年业绩，净利率也不能替换成营业利润率。</p><div className="projection-base-inputs"><ScenarioInput label="基期年化营收" value={inputValue(draft.annualRevenue, baseline.annualRevenue === null ? null : baseline.annualRevenue / 1e8)} suffix="亿美元" min={0.01} step={10} onChange={value => set({ annualRevenue: value })} /><ScenarioInput label="基期股数" value={inputValue(draft.dilutedShares, baseline.dilutedShares === null ? null : baseline.dilutedShares / 1e8)} suffix="亿股" min={0.01} step={1} onChange={value => set({ dilutedShares: value })} /><ScenarioInput label="每年股数变化" value={draft.annualShareChange} suffix="%" min={-99} max={100} step={0.5} onChange={value => set({ annualShareChange: value })} /></div><p>股数采用披露稀释加权股数（{baseline.sharesLabel}），只是代理，不是未来实际股数。正变化代表稀释，负变化代表回购；ADR 必须用美元营收与等价 ADR 数量。手动输入需要自行确认币种与单位。</p>{result && <p>未来年化净利润 {formatMoney(result.projectedProfit)}，对应市值 {formatMoney(result.projectedMarketCap)}。计算使用原始精度，显示时取整。</p>}<p>《十万亿不是梦？》以英伟达单季营收 962.2 亿美元、净利润 596.9 亿美元为基期，假设营收先增 70%、再增 30%，净利率不变、PE 为 20 倍。连续计算约 10.55 万亿美元；文中逐步取整为 10.56 万亿。原文推的是市值，本页再除以股数推演每股价格。</p><div className="projection-source-links"><a href={nvidiaArticleScenario.sourceUrl} target="_blank" rel="noreferrer">2026-08-31 文章原文 <ExternalLink size={12} /></a>{company.financialSourceUrl && <a href={company.financialSourceUrl} target="_blank" rel="noreferrer">当前财务来源 <ExternalLink size={12} /></a>}</div></div></details>
    </section>
    <footer className="overview-footer"><span>{storageError ? '参数未能保存至本机浏览器' : '情景参数按公司保存在本机'} · 贵便宜相对历史，未来股价相对假设</span><div><button onClick={onSources}>数据依据 <Info size={13} /></button><button onClick={onResearch}>详细研究 <ArrowRight size={14} /></button></div></footer>
  </main>
}