import { startTransition, useDeferredValue, useEffect, useState } from 'react'
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleAlert,
  Columns3,
  Database,
  Info,
  LineChart,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  X,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import './App.css'
import './Research.css'
import { seedCompanies, type CompanySnapshot } from './data'
import { eligiblePercentile, genericCompany, mergeApiCompanies, suspendJudgments, type ApiCompany } from './liveData'
import { historicalPriceVerdict } from './priceProjection'
import { CompanyIcon, CompareWorkspace, ResearchWorkspace, type ResearchView } from './ResearchWorkspace'
import { PriceOverview } from './PriceOverview'

const DEFAULT_WATCHLIST = ['NVDA', 'MSFT', 'AMZN', 'GOOGL', 'AAPL', 'TSM']

interface SearchResult {
  symbol: string
  name: string
  cik?: string
  exchange?: string
}

function readWatchlist() {
  try {
    const stored = JSON.parse(localStorage.getItem('stock-monitor-watchlist') || '[]')
    return Array.isArray(stored) && stored.length ? stored as string[] : DEFAULT_WATCHLIST
  } catch {
    return DEFAULT_WATCHLIST
  }
}

function scenarioValues(company: CompanySnapshot, scenario: string) {
  const base = company.outlook
  if (scenario === '保守') {
    return {
      firstGrowth: Math.max(0, Math.round(base.firstGrowth * 0.72)),
      secondGrowth: Math.max(0, Math.round(base.secondGrowth * 0.68)),
      terminalPe: Math.max(8, Math.round(base.terminalPe * 0.85)),
    }
  }
  if (scenario === '乐观') {
    return {
      firstGrowth: Math.round(base.firstGrowth * 1.18),
      secondGrowth: Math.round(base.secondGrowth * 1.25),
      terminalPe: Math.round(base.terminalPe * 1.18),
    }
  }
  return {
    firstGrowth: base.firstGrowth,
    secondGrowth: base.secondGrowth,
    terminalPe: base.terminalPe,
  }
}

function formatPrice(price: number | null) {
  return price === null
    ? '待刷新'
    : `$${price.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

function formatTimestamp(value?: string | null) {
  if (!value) return '尚未完成'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false })
}

function App() {
  const [companies, setCompanies] = useState(() => mergeApiCompanies(seedCompanies, seedCompanies.map(({ symbol, name }) => ({ symbol, name }))))
  const [watchlist, setWatchlist] = useState(readWatchlist)
  const [selectedSymbol, setSelectedSymbol] = useState('NVDA')
  const [view, setView] = useState<ResearchView>('overview')
  const [showAdd, setShowAdd] = useState(false)
  const [showSources, setShowSources] = useState(false)
  const [query, setQuery] = useState('')
  const [remoteResults, setRemoteResults] = useState<SearchResult[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [dataMode, setDataMode] = useState<'live' | 'snapshot'>('snapshot')
  const [monitorRunning, setMonitorRunning] = useState(false)
  const [lastSyncAt, setLastSyncAt] = useState<string | null>(null)
  const [refreshError, setRefreshError] = useState('')
  const [trackError, setTrackError] = useState('')
  const [scenario, setScenario] = useState('作者基准')
  const [firstGrowth, setFirstGrowth] = useState(70)
  const [secondGrowth, setSecondGrowth] = useState(30)
  const [terminalPe, setTerminalPe] = useState(20)
  const deferredQuery = useDeferredValue(query)

  const company = companies.find((item) => item.symbol === selectedSymbol) || companies[0]
  const baselineFirstGrowth = company.outlook.firstGrowth
  const baselineSecondGrowth = company.outlook.secondGrowth
  const baselinePe = company.outlook.terminalPe
  const visibleCompanies = watchlist
    .map((symbol) => companies.find((item) => item.symbol === symbol))
    .filter((item): item is CompanySnapshot => Boolean(item))
  const localSearchResults = companies.filter((item) => {
    const needle = deferredQuery.trim().toLowerCase()
    return !needle || [item.symbol, item.name, item.shortName, ...item.aliases]
      .some((value) => value.toLowerCase().includes(needle))
  })
  const searchResults: SearchResult[] = [
    ...localSearchResults.map((item) => ({ symbol: item.symbol, name: item.name, exchange: item.exchange })),
    ...remoteResults.filter((remote) => !localSearchResults.some((local) => local.symbol === remote.symbol)),
  ].slice(0, 8)
  const hasExactLocalMatch = localSearchResults.some(
    (item) => item.symbol.toLowerCase() === deferredQuery.trim().toLowerCase(),
  )

  useEffect(() => {
    localStorage.setItem('stock-monitor-watchlist', JSON.stringify(watchlist))
  }, [watchlist])

  useEffect(() => {
    let stopped = false
    let active = false
    let controller: AbortController | null = null
    async function load() {
      if (active || stopped) return
      active = true
      controller = new AbortController()
      const timeout = window.setTimeout(() => controller?.abort(), 12000)
      try {
        const response = await fetch('/api/companies', { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('API unavailable')
        const payload = await response.json() as { companies: ApiCompany[]; generatedAt: string; monitor?: { running: boolean } }
        if (!stopped) {
          setCompanies((current) => mergeApiCompanies(current, payload.companies))
          setDataMode('live')
          setMonitorRunning(Boolean(payload.monitor?.running))
          setLastSyncAt(payload.generatedAt)
        }
      } catch {
        if (!stopped) { setDataMode('snapshot'); setMonitorRunning(false); setCompanies(suspendJudgments) }
      } finally {
        window.clearTimeout(timeout)
        active = false
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), 15000)
    const onVisibility = () => { if (document.visibilityState === 'visible') void load() }
    document.addEventListener('visibilitychange', onVisibility)
    return () => { stopped = true; window.clearInterval(timer); controller?.abort(); document.removeEventListener('visibilitychange', onVisibility) }
  }, [refreshKey])

  useEffect(() => {
    const needle = deferredQuery.trim()
    if (needle.length < 2 || hasExactLocalMatch) {
      setRemoteResults([])
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setIsSearching(true)
      fetch(`/api/search?q=${encodeURIComponent(needle)}`, { signal: controller.signal })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error('Search unavailable')))
        .then((payload: { results?: SearchResult[] }) => setRemoteResults(payload.results || []))
        .catch(() => setRemoteResults([]))
        .finally(() => setIsSearching(false))
    }, 280)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [deferredQuery, hasExactLocalMatch])

  useEffect(() => {
    setScenario('作者基准')
    setFirstGrowth(baselineFirstGrowth)
    setSecondGrowth(baselineSecondGrowth)
    setTerminalPe(baselinePe)
  }, [selectedSymbol, baselineFirstGrowth, baselineSecondGrowth, baselinePe])

  async function requestRefresh() {
    if (isRefreshing) return
    setIsRefreshing(true)
    setRefreshError('')
    try {
      const response = await fetch('/api/refresh', { method: 'POST' })
      if (!response.ok) throw new Error('refresh failed')
      setRefreshKey((value) => value + 1)
    } catch { setRefreshError('刷新请求失败，保留上次数据。') }
    finally { setIsRefreshing(false) }
  }

  function selectCompany(symbol: string) {
    startTransition(() => setSelectedSymbol(symbol))
  }

  function applyScenario(nextScenario: string) {
    const values = scenarioValues(company, nextScenario)
    setScenario(nextScenario)
    setFirstGrowth(values.firstGrowth)
    setSecondGrowth(values.secondGrowth)
    setTerminalPe(values.terminalPe)
  }

  function addCompany(result: SearchResult) {
    const symbol = result.symbol
    setTrackError('')
    setWatchlist((current) => current.includes(symbol) ? current : [...current, symbol])
    if (!companies.some((item) => item.symbol === symbol)) {
      const optimistic = genericCompany({ symbol, name: result.name, cik: result.cik, exchange: result.exchange })
      setCompanies((current) => [...current, optimistic])
      fetch('/api/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(result),
      })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error('Track unavailable')))
        .then((payload: { company: ApiCompany }) => setCompanies((current) => mergeApiCompanies(current, [payload.company])))
        .catch(() => setTrackError(`${symbol} 后台跟踪失败，请重新尝试；本地列表不代表已经开始监控。`))
    }
    selectCompany(symbol)
    setView('overview')
    setShowAdd(false)
    setQuery('')
  }

  const baseProfit = company.outlook.baseQuarterProfitB
  const firstProfit = baseProfit === null ? null : Math.round(baseProfit * (1 + firstGrowth / 100) * 10) / 10
  const secondProfit = firstProfit === null ? null : Math.round(firstProfit * (1 + secondGrowth / 100) * 10) / 10
  const annualProfit = secondProfit === null ? null : secondProfit * 4
  const targetMarketCap = annualProfit === null ? null : (annualProfit * terminalPe) / 1000
  const outlookData = baseProfit === null ? [] : [
    { year: company.symbol === 'NVDA' ? '文章基期' : '财报基期', profit: baseProfit },
    { year: String(company.outlook.firstYear), profit: firstProfit },
    { year: String(company.outlook.secondYear), profit: secondProfit },
  ]
  const valuation = company.valuation
  const percentile = eligiblePercentile(valuation)
  const valuationCurrent = valuation.algorithmVersion === 4 && valuation.currentPeQualified === true
  const windowLabel = `${valuation.horizonYears || ''}年日频`

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <img className="brand-mark" src="/stock-monitor-logo.png" alt="Stock Monitor" width="34" height="34" />
          <div><strong>Stock Monitor</strong><span>价格与业绩</span></div>
        </div>

        <nav className="primary-nav" aria-label="工作区导航">
          <button className={view === 'overview' || view === 'research' ? 'active' : ''} aria-current={view === 'overview' || view === 'research' ? 'page' : undefined} onClick={() => setView('overview')}><Target size={17} /><span>价格概览</span><ChevronRight size={13} /></button>
          <button className={view === 'compare' ? 'active' : ''} aria-current={view === 'compare' ? 'page' : undefined} onClick={() => setView('compare')}><Columns3 size={17} /><span>公司对比</span><small>{visibleCompanies.length}</small></button>
          <button className={view === 'monitor' ? 'active' : ''} aria-current={view === 'monitor' ? 'page' : undefined} onClick={() => setView('monitor')}><LineChart size={17} /><span>财报监控</span><ChevronRight size={13} /></button>
        </nav>
        <div className="watchlist-heading">
          <span>观察公司</span>
          <button className="icon-button on-dark" title="新增公司" onClick={() => setShowAdd(true)}>
            <Plus size={16} />
          </button>
        </div>
        <nav className="watchlist" aria-label="股票观察列表">
          {visibleCompanies.map((item) => {
            const verdict = historicalPriceVerdict(item, dataMode === 'live')
            return (
            <button
              className={`stock-nav-item ${item.symbol === selectedSymbol ? 'active' : ''}`}
              key={item.symbol}
              onClick={() => { selectCompany(item.symbol); if (view === 'compare') setView('overview') }}
            >
              <CompanyIcon key={item.symbol} symbol={item.symbol} />
              <span className="stock-nav-copy"><strong>{item.shortName}</strong><small>{item.symbol}<span className={`simple-stock-stance ${verdict.tone}`}>{verdict.label}</span></small></span>
              <span className={`mini-signal ${verdict.tone}`} title={`${verdict.label} · ${verdict.basis}`} />
            </button>
          )})}
        </nav>
        <button className="add-stock-button" onClick={() => setShowAdd(true)}>
          <Plus size={16} /> 输入名称或代码
        </button>
        <div className={`monitor-status ${monitorRunning ? 'connected' : ''}`} role="status">
          <span className="mini-signal" /><span>{monitorRunning ? '自动监控中' : '监控连接中断'}<small>财报检查 / 5 分钟</small></span>
        </div>
        <div className="sidebar-footnote"><ShieldCheck size={15} /><span>有依据地研究，独立地判断。</span></div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="company-identity">
            <CompanyIcon key={company.symbol} symbol={company.symbol} />
            <div>
              <div className="company-title-row">
                <h1>{company.shortName}</h1><span>{company.symbol}</span><span className="exchange-label">{company.exchange}</span>
              </div>
              <p>{view === 'compare' ? '观察池 / 公司对比' : `${company.category} / ${view === 'overview' ? '价格概览' : view === 'research' ? '详细研究' : '财报监控'}`}</p>
            </div>
          </div>
          <div className="quote-block">
            <div>
              <strong>{formatPrice(company.quote.price)}</strong>
              {company.quote.changePercent !== null && (
                <span className={company.quote.changePercent >= 0 ? 'up' : 'down'}>
                  {company.quote.changePercent >= 0 ? '+' : ''}{company.quote.changePercent.toFixed(2)}%
                </span>
              )}
            </div>
            <small>{company.quote.asOf} · {dataMode === 'live' ? '自动同步' : '连接中断，显示缓存'}</small>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" title="查看数据来源" onClick={() => setShowSources(true)}><Database size={17} /></button>
            <button className="icon-button" title="重新检查行情、财报和估值" aria-label="刷新数据" disabled={isRefreshing} onClick={() => void requestRefresh()}>
              <RefreshCw size={17} className={isRefreshing ? 'spinning' : ''} />
            </button>
          </div>
        </header>

        {(refreshError || trackError) && <div className="request-error" role="alert">{refreshError || trackError}</div>}
        {view === 'overview' && <PriceOverview key={company.symbol} company={company} connected={dataMode === 'live'} onResearch={() => setView('research')} onSources={() => setShowSources(true)} />}
        {view === 'research' && <button className="research-back" onClick={() => setView('overview')}><ChevronRight size={13} style={{ transform: 'rotate(180deg)' }} />返回价格概览</button>}
        {view === 'research' && <ResearchWorkspace key={company.symbol} company={company} connected={dataMode === 'live'} onSources={() => setShowSources(true)} />}
        {view === 'compare' && <CompareWorkspace companies={visibleCompanies} connected={dataMode === 'live'} onSelect={symbol => { selectCompany(symbol); setView('overview') }} />}
        {view === 'monitor' && <main className="dashboard-grid">
          <div className="analysis-column">
            <section className={`verdict-band ${company.tone}`}>
              <div className="score-ring" title="后台持续检查财报，页面自动读取最新结果">
                <span><RefreshCw size={22} /></span><small>自动监测</small>
              </div>
              <div className="verdict-copy">
                <div className="eyebrow"><Target size={14} /> 当前判断 · {company.stance}</div>
                <h2>{company.headline}</h2>
                <p>{company.summary}</p>
              </div>
              <button className="logic-button" onClick={() => setShowSources(true)}>判断依据 <ArrowRight size={15} /></button>
            </section>

            <div className="signal-grid">
              <section className="signal-panel valuation-panel">
                <PanelHeading step="01" title="价格贵不贵" subtitle="先和它自己的过去比" icon={<button className="info-button" title="查看百分位算法与来源" onClick={() => setShowSources(true)}><Info size={15} /></button>} />
                <div className={`valuation-multiples ${valuationCurrent ? '' : 'unavailable'}`}>
                  <span>TTM PE <b>{valuation.pe?.toFixed(2) ?? '--'}×</b></span>
                  <span>盈利收益率 <b>{valuation.earningsYieldPercent?.toFixed(2) ?? '--'}%</b></span>
                  {!valuationCurrent && <small>未确认有效</small>}
                </div>
                {percentile === null ? (
                  <div className="empty-state"><Database size={22} /><strong>{valuationCurrent ? '历史覆盖不足' : '暂停估值判断'}</strong><span>{valuation.reason || '等待可核验的盈利与历史价格。'}</span></div>
                ) : (
                  <>
                    <div className="percentile-summary">
                      <div><strong>{percentile.toFixed(2)}%</strong><span>{windowLabel} PE 百分位</span></div>
                      <p>不低于 <b>{percentile.toFixed(1)}%</b> 的历史正 PE 样本。{valuation.horizonYears !== 10 ? '十年覆盖不足。' : '不等于上涨概率。'}</p>
                    </div>
                    <div className="percentile-track">
                      <span className="track-cheap">历史低位</span><span className="track-fair">历史中段</span><span className="track-rich">历史高位</span>
                      <i style={{ left: `${Math.min(98, Math.max(2, percentile))}%` }} />
                    </div>
                    <div className="reference-prices" aria-label="历史倍数对应价格">
                      {valuation.referencePrices?.map((reference) => <div key={reference.percentile} title={`近${valuation.horizonYears}年 P${reference.percentile} 的 PE ${reference.pe.toFixed(2)} 倍 × 当前四季 EPS；不是目标价`}><span>P{reference.percentile}</span><b>{formatPrice(reference.price)}</b></div>)}
                    </div>
                    <p className="reference-caption">历史倍数 × 当前 EPS，不是合理价或目标价</p>
                  </>
                )}
                <div className="metric-footer"><span>{valuation.sampleCount ?? 0} 个正 PE 样本</span><small>收盘 {valuation.asOf || '未取得'}</small></div>
                {company.dataErrors?.valuation && <p className="sampling-note">估值更新失败，已记录错误和数据日期。</p>}
              </section>

              <section className="signal-panel fundamentals-panel">
                <PanelHeading step="02" title="增长与利润质量" subtitle={company.financialPeriod || '等待最新财报'} icon={<LineChart size={16} />} />
                <div className="fundamental-list">
                  {company.metrics.map((metric) => (
                    <div className="fundamental-row" key={metric.label} title={metric.hint}>
                      <span>{metric.label}</span><strong>{metric.value}</strong><em>{metric.change}</em>
                    </div>
                  ))}
                </div>
                <p className="plain-insight"><Check size={15} />
                  {company.qualityWarning}
                </p>
              </section>

              <section className={`signal-panel proof-panel ${company.proof.tone}`}>
                <PanelHeading
                  step="03"
                  title={company.proof.title}
                  subtitle="投入最终必须换回更多现金"
                  icon={<span className={`status-chip ${company.proof.tone}`}>{company.proof.status}</span>}
                />
                {company.proof.marginalCoverage !== null && (
                  <div className="coverage-visual">
                    <div className="coverage-value"><strong>{company.proof.marginalCoverage.toFixed(2)}×</strong><span>边际现金覆盖率</span></div>
                    {company.proof.marginalCoverage < 0 ? <p className="negative-coverage">投入增加，经营现金却减少</p> : <div className="coverage-bars">
                      <span style={{ width: '56%' }}>新增投入 1</span>
                      <b style={{ width: `${Math.max(0, Math.min(100, 56 * company.proof.marginalCoverage))}%` }}>现金增量 {company.proof.marginalCoverage.toFixed(2)}</b>
                    </div>}
                  </div>
                )}
                <p className="proof-explanation">{company.proof.explanation}</p>
                <ul className="fact-list">{company.proof.facts.map((fact) => <li key={fact}>{fact}</li>)}</ul>
              </section>

              <section className="signal-panel moat-panel">
                <PanelHeading step="04" title="什么可能看错" subtitle="业务研究笔记 · 非自动核验" icon={<CircleAlert size={16} />} />
                <div className="moat-line"><ShieldCheck size={17} /><p><span>护城河</span>{company.moat}</p></div>
                <div className="risk-list">
                  {company.risks.map((risk, index) => <span key={risk}><i>{index + 1}</i>{risk}</span>)}
                </div>
              </section>
            </div>
          </div>

          <aside className="outlook-panel">
            <header className="outlook-heading">
              <div><span className="eyebrow"><Sparkles size={14} /> 未来情景</span><h2>把增长翻译成市值</h2></div>
              <button className="icon-button subtle" title="恢复基准情景" onClick={() => applyScenario('作者基准')}><RotateCcw size={15} /></button>
            </header>
            <p className="outlook-intro">不是猜股价，而是先写下假设，再看这些假设值多少钱。</p>
            <div className="scenario-tabs" role="tablist">
              {['保守', '作者基准', '乐观'].map((item) => (
                <button className={scenario === item ? 'active' : ''} onClick={() => applyScenario(item)} key={item}>{item === '作者基准' && company.symbol !== 'NVDA' ? '研究基准' : item}</button>
              ))}
            </div>

            {baseProfit === null ? (
              <div className="outlook-empty"><BookOpen size={27} /><strong>等待建立利润基线</strong><p>{company.outlook.blockedReason || '同步最新财报后，才能把增长率转成未来利润和估值。'}</p></div>
            ) : (
              <>
                <div className="outlook-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={outlookData} margin={{ top: 12, right: 8, left: -18, bottom: 0 }}>
                      <defs><linearGradient id="profitFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#639AA7" stopOpacity={0.36} /><stop offset="100%" stopColor="#639AA7" stopOpacity={0.02} /></linearGradient></defs>
                      <CartesianGrid stroke="#dce8e8" strokeDasharray="3 4" vertical={false} />
                      <XAxis dataKey="year" axisLine={false} tickLine={false} tick={{ fill: '#71878c', fontSize: 11 }} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fill: '#91a4a9', fontSize: 10 }} tickFormatter={(value) => `$${value}B`} />
                      <Tooltip formatter={(value) => [`$${Number(value).toFixed(1)}B`, '季度利润']} contentStyle={{ border: '1px solid #dce8e8', borderRadius: 6, fontSize: 12 }} />
                      <Area type="monotone" dataKey="profit" stroke="#4f8996" strokeWidth={2.5} fill="url(#profitFill)" dot={{ fill: '#f2c48d', stroke: '#4f8996', strokeWidth: 2, r: 4 }} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <div className="assumption-list">
                  <RangeInput label={`${company.outlook.firstYear} 利润增长`} value={firstGrowth} max={120} onChange={(value) => { setScenario('自定义'); setFirstGrowth(value) }} />
                  <RangeInput label={`${company.outlook.secondYear} 利润增长`} value={secondGrowth} max={80} onChange={(value) => { setScenario('自定义'); setSecondGrowth(value) }} />
                  <RangeInput label="市场愿意给的 PE" value={terminalPe} min={8} max={40} suffix="×" onChange={(value) => { setScenario('自定义'); setTerminalPe(value) }} />
                </div>
                <div className="projection-result">
                  <span>{company.outlook.secondYear} 年中情景市值</span>
                  <strong>{targetMarketCap === null ? '—' : `$${targetMarketCap.toFixed(2)} 万亿`}</strong>
                  <p>季度利润 ${secondProfit?.toFixed(1)}B × 4 × {terminalPe} 倍 PE</p>
                </div>
                <p className="outlook-source"><Info size={13} /> {company.outlook.sourceLabel}</p>
              </>
            )}
          </aside>
        </main>}
      </section>

      {showAdd && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowAdd(false)}>
          <section className="add-modal" role="dialog" aria-modal="true" aria-labelledby="add-title" onMouseDown={(event) => event.stopPropagation()}>
            <header><div><span className="eyebrow">观察列表</span><h2 id="add-title">新增标的公司</h2></div><button className="icon-button" onClick={() => setShowAdd(false)}><X size={17} /></button></header>
            <label className="search-field"><Search size={18} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入公司名称、股票代码，或 AWS" /></label>
            <div className="search-results">
              {searchResults.map((item) => (
                <button key={item.symbol} onClick={() => addCompany(item)}>
                  <span className="ticker-avatar light">{item.symbol.slice(0, 2)}</span>
                  <span><strong>{companies.find((companyItem) => companyItem.symbol === item.symbol)?.shortName || item.symbol}</strong><small>{item.name} · {item.symbol}</small></span>
                  {watchlist.includes(item.symbol) ? <Check size={17} /> : <ChevronRight size={17} />}
                </button>
              ))}
            </div>
            {isSearching && <p className="searching-state"><RefreshCw size={13} className="spinning" /> 正在查询 SEC 公司目录</p>}
            <p className="modal-note"><Info size={14} /> AWS 属于亚马逊 AMZN，不是独立上市股票；分部指标需查阅公司披露。</p>
          </section>
        </div>
      )}

      {showSources && (
        <div className="modal-backdrop source-backdrop" role="presentation" onMouseDown={() => setShowSources(false)}>
          <aside className="source-drawer" role="dialog" aria-modal="true" aria-labelledby="source-title" onMouseDown={(event) => event.stopPropagation()}>
            <header><div><span className="eyebrow">可验证的判断</span><h2 id="source-title">数据与方法</h2></div><button className="icon-button" onClick={() => setShowSources(false)}><X size={17} /></button></header>
            <SourceSection title="一句话方法">寻找“基本面仍在增强，但估值仍停留在旧叙事里”的错配，而不是只找股价跌得多的公司。</SourceSection>
            <SourceSection title="长期投资研究框架"><p>先理解生意、验证多年盈利和资本回报，再用可持续现金与安全折价评估价格。指标阈值只作研究提示，不是巴菲特本人评分或买卖建议。</p><a href="https://www.berkshirehathaway.com/letters/1986.html" target="_blank" rel="noreferrer">1986 股东信：所有者盈余与资本开支</a><a href="https://www.berkshirehathaway.com/letters/1992.html" target="_blank" rel="noreferrer">1992 股东信：现金折现与安全边际</a></SourceSection>
            <SourceSection title="当前公司数据">{company.sourceNote}<ul><li>行情：{company.quote.source}</li><li>财务币种：{company.financialCurrency || '尚未核验'}</li><li>研究情景：归档文章或明确标注的假设，不是公司指引</li></ul>{company.financialSourceUrl && <a href={company.financialSourceUrl} target="_blank" rel="noreferrer">当前财务原始报告</a>}</SourceSection>
            <SourceSection title="自动监控状态">
              <ul><li>后台：{monitorRunning ? '运行中' : '连接中断'}</li><li>网页同步：{formatTimestamp(lastSyncAt)}</li><li>财报检查：{formatTimestamp(company.earnings?.lastCheckedAt)}</li><li>报价每 60 秒、财报每 5 分钟、估值每 6 小时检查；需本机和服务持续运行。</li></ul>
              {refreshError && <p role="alert">{refreshError}</p>}
              {Object.entries(company.dataErrors || {}).map(([source, error]) => <p className="source-error" key={source}>{source}: {error}</p>)}
              {company.earnings?.latestFiling && <a href={company.earnings.latestFiling.url} target="_blank" rel="noreferrer">最新申报：{company.earnings.latestFiling.form} · {company.earnings.latestFiling.filedAt}</a>}
            </SourceSection>
            <SourceSection title="百分位怎么算">
              <p>百分位 = 历史 PE 不高于当前 PE 的有效样本数 ÷ 总有效样本数 × 100。只统计正 PE，亏损与缺失数据不当作低估值。</p>
              <p>交易日拆股调整收盘价 ÷ 当时已披露的四个独立季度稀释 EPS 之和。披露次日起生效；不使用“年报 EPS + 本年累计 − 上年同期”。不以十个年末点替代日频。</p>
              <p>覆盖：{valuation.historyStart || '尚未取得'} 至 {valuation.historyEnd || '尚未取得'}；计算时间：{formatTimestamp(valuation.calculatedAt)}</p>
              {valuation.reason && <p className="source-error">{valuation.reason}</p>}
              <div className="source-table-wrap"><table className="source-table"><thead><tr><th>窗口</th><th>已知覆盖</th><th>正 PE / 亏损</th><th>可用</th></tr></thead><tbody>{valuation.coverage?.map((window) => <tr key={window.years}><td>{window.years} 年</td><td>{window.coveragePercent}%</td><td>{window.validSamples} / {window.nonpositiveEarningsSessions}</td><td>{window.qualified ? '是' : '否'}</td></tr>)}</tbody></table></div>
              <p>覆盖门槛：真实交易日已知盈利 ≥99.5%，缺价 ≤2 日，连续缺口 ≤3 日，并有足够正 PE 样本。超过一个完整交易日的价格延迟，或盈利期末超过 160 天，停止判断。</p>
              {valuation.sourceUrl && <a href={valuation.sourceUrl} target="_blank" rel="noreferrer">{valuation.source}</a>}
              <a href={`/api/valuation/${company.symbol}`} target="_blank" rel="noreferrer">查看完整计算样本 JSON</a>
            </SourceSection>
            <SourceSection title="四季盈利原始证据">
              <p>{formatPrice(valuation.price ?? null)} 收盘价 ÷ ${valuation.epsTtm?.toFixed(4) ?? '--'} 四季稀释 EPS = {valuation.pe?.toFixed(2) ?? '--'} 倍。价格日期 {valuation.asOf || '未取得'}，盈利截至 {valuation.epsPeriodEnd || '未取得'}。</p>
              <div className="source-table-wrap"><table className="source-table"><thead><tr><th>季度结束</th><th>原报 EPS</th><th>拆股后 EPS</th><th>原文</th></tr></thead><tbody>{valuation.earningsComponents?.map((component) => <tr key={component.end}><td>{component.end}<small>披露 {component.filedAt}</small></td><td>{component.reportedEps.toFixed(4)}</td><td>{component.eps.toFixed(4)}</td><td>{component.sourceUrl ? <a href={component.sourceUrl} target="_blank" rel="noreferrer">报告</a> : '未链接'}</td></tr>)}</tbody></table></div>
              {company.symbol === 'TSM' && <p>TSM 为美元 ADR，每 ADR 对应 5 股普通股。EPS 使用公司各季度披露的美元 ADR 数值及当季换算口径；财务卡保留新台币，不能与美元直接相除。</p>}
              <p>稀释 EPS 相加是一致的历史比较口径，不等于年度加权股数重算 EPS。拆股规则目前仅核验默认六家公司；新增标的不能自动继承这些规则。</p>
            </SourceSection>
            <SourceSection title="参考价格与盈利质量">
              <p>P20／P50／P80 价格是历史 PE 的相应分位值 × 当前 EPS，假设当前盈利不变。不是内在价值，也不包含未来增长、利率、业务结构变化或安全边际。</p>
              <p>{company.qualityWarning}</p><p>净利润明显高于营业利润仅触发风险提示，未自动剔除投资收益。未经逐项核验的“调整后 PE”不发布。</p>
              <p>自由现金 = 同期经营现金 − 现金购建资产支出；不含未付融资租赁新增额，也不抵减资产处置回款，可能与公司自定义 FCF 不同。{company.capexConcept && <>当前现金资本开支标签：{company.capexConcept}。</>}</p>
              {company.cashFlowSourceUrl && <a href={company.cashFlowSourceUrl} target="_blank" rel="noreferrer">现金流原始报告</a>}
            </SourceSection>
            <SourceSection title="四步判断"><ol><li>估值是否处于自身历史低位</li><li>营收与利润是否仍在增长</li><li>新增现金回报是否超过新增投入</li><li>护城河是否增强，退出信号是什么</li></ol></SourceSection>
            <div className="source-warning"><CircleAlert size={17} /><p>估值采用注明日期的价格与盈利口径，可能有数据源延迟；研究情景不是盈利承诺，也不是自动买入指令。</p></div>
          </aside>
        </div>
      )}
    </div>
  )
}

function PanelHeading({ step, title, subtitle, icon }: { step: string; title: string; subtitle: string; icon: React.ReactNode }) {
  return <header className="panel-heading"><div><span className="step-number">{step}</span><div><h3>{title}</h3><p>{subtitle}</p></div></div>{icon}</header>
}

function RangeInput({ label, value, onChange, min = 0, max, suffix = '%' }: { label: string; value: number; onChange: (value: number) => void; min?: number; max: number; suffix?: string }) {
  return <label><span>{label}<b>{value}{suffix}</b></span><input type="range" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>
}

function SourceSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="source-section"><h3>{title}</h3><div>{children}</div></div>
}

export default App
