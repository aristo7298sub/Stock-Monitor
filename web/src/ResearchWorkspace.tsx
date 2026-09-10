import { useEffect, useState } from 'react'
import { ArrowDown, ArrowRight, ArrowUp, Bookmark, Calculator, Check, CircleAlert, ExternalLink, FileText, Info, RotateCcw, ShieldCheck, SlidersHorizontal, X } from 'lucide-react'
import type { CompanySnapshot } from './data'
import { eligiblePercentile, formatMoney } from './liveData'
import { assessInvestment, businessProfiles, cashBaseline, discountedCashValue, valuationReviewKey, type InvestmentMetric, type ValueAssumptions } from './investment'

export type ResearchView = 'overview' | 'research' | 'compare' | 'monitor'

const iconSymbols = new Set(['MSFT', 'NVDA', 'AMZN', 'AAPL', 'TSM'])

export function CompanyIcon({ symbol }: { symbol: string }) {
  const [failed, setFailed] = useState(false)
  return <span className={`company-icon logo-${symbol.toLowerCase()}`} aria-hidden="true">{iconSymbols.has(symbol) && !failed ? <img src={`/${symbol.toLowerCase()}.ico`} alt="" width="24" height="24" onError={() => setFailed(true)} /> : symbol === 'GOOGL' ? <b className="google-letter">G</b> : <b>{symbol.slice(0, 2)}</b>}</span>
}

function metricText(metric?: InvestmentMetric) {
  if (metric?.value == null) return '--'
  return metric.unit === 'years' ? `${metric.value} / 5 年` : `${metric.value.toLocaleString('en-US', { maximumFractionDigits: 1 })}${metric.unit === 'x' ? '×' : '%'}`
}

function dollars(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '--' : `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function MetricDetail({ metric, onClose }: { metric: InvestmentMetric; onClose: () => void }) {
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [onClose])
  return <div className="modal-backdrop metric-backdrop" onMouseDown={onClose}><section className="metric-dialog" role="dialog" aria-modal="true" aria-label={metric.label} onMouseDown={event => event.stopPropagation()}><header><div><span className="eyebrow">指标证据</span><h2>{metric.label}</h2></div><button className="icon-button" title="关闭指标详情" onClick={onClose}><X size={17} /></button></header><strong className="metric-detail-value">{metricText(metric)}</strong><p>{metric.period}</p><p>{metric.explanation}</p><div className="formula-block"><span>计算与边界</span><p>{metric.formula}</p></div>{metric.sourceUrl && <a href={metric.sourceUrl} target="_blank" rel="noreferrer">原始数据 <ExternalLink size={13} /></a>}</section></div>
}

export function ResearchWorkspace({ company, connected, onSources }: { company: CompanySnapshot; connected: boolean; onSources: () => void }) {
  const [tab, setTab] = useState<'case' | 'metrics' | 'history' | 'business'>('case')
  const [detail, setDetail] = useState<InvestmentMetric | null>(null)
  const assessment = assessInvestment(company.financials, company.valuation, company.earnings?.pendingStructuredData || !connected)
  const profile = businessProfiles[company.symbol]
  const summaryMetrics = ['cagr', 'margin', 'consistency', 'roe'].map(key => assessment.metrics.find(metric => metric.key === key)!)
  const quality = company.financials?.quality
  const percentile = eligiblePercentile(company.valuation)
  return <main className="research-workspace">
    <section className="research-main">
      <header className="research-intro"><div><span className="eyebrow">企业所有者视角 <span className="intro-dot" /> 长期研究</span><h2>{company.shortName}，值得成为股东吗？</h2><p>{profile?.business || '盈利来源与商业模式尚未完成研究。'}</p></div><span className={`research-status ${assessment.state}`}>{assessment.state === 'research' ? <ShieldCheck size={14} /> : <CircleAlert size={14} />}{assessment.label}</span></header>
      <div className="research-metrics">{summaryMetrics.map(metric => <button className={`research-metric ${metric.state}`} key={metric.key} onClick={() => setDetail(metric)} title={`查看${metric.label}的公式和证据`}><span>{metric.label}<Info size={12} /></span><strong>{metricText(metric)}</strong><small>{metric.key === 'margin' ? '最新单季' : metric.key === 'roe' ? 'TTM · 平均权益' : metric.key === 'consistency' ? '完整财年 · 非单季' : '历史记录 · 非预测'}</small></button>)}</div>
      <nav className="research-tabs" role="tablist" aria-label="公司研究视图">{([{ id: 'case', label: '投资论点' }, { id: 'metrics', label: '指标明细' }, { id: 'history', label: '经营记录' }, { id: 'business', label: '生意与反证' }] as const).map(item => <button role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'active' : ''} key={item.id} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav>
      <div className="research-content">
        {tab === 'case' && <>
          <div className="thesis-statement"><span className="mini-heading">研究假设 · 非事实结论</span><p>{profile?.thesis || '先理解公司如何赚钱，再形成可以验证的持有理由。'}</p></div>
          <div className="evidence-columns"><section><h3><Check size={15} /> 值得研究的理由 <span>{assessment.supports.length}</span></h3><ul className="evidence-list">{assessment.supports.map(metric => <li key={metric.key}><button onClick={() => setDetail(metric)}><span>{metric.label}</span><b>{metricText(metric)}</b><ExternalLink size={12} /></button><p>{metric.explanation}</p></li>)}{!assessment.supports.length && <li className="evidence-empty">有效证据尚不足，不自动生成正面理由。</li>}</ul></section><section><h3><CircleAlert size={15} /> 不宜忽略的代价 <span>{assessment.concerns.length}</span></h3><ul className="evidence-list concerns">{assessment.concerns.map(metric => <li key={metric.key}><button onClick={() => setDetail(metric)}><span>{metric.label}</span><b>{metricText(metric)}</b><ExternalLink size={12} /></button><p>{metric.explanation}</p></li>)}{!assessment.concerns.length && <li className="evidence-empty">当前规则未触发风险，不等于不存在风险。</li>}</ul></section></div>
          <div className="open-questions"><span className="mini-heading">决定之前，仍需回答</span><p>{profile?.capitalQuestion || '业务的竞争优势与资本配置是否经得起验证？'}</p><div>{assessment.missing.map(item => <span key={item}>{item}</span>)}</div></div>
        </>}
        {tab === 'metrics' && <div className="metric-ledger">{assessment.metrics.map(metric => <button className={`ledger-row ${metric.state}`} key={metric.key} onClick={() => setDetail(metric)}><span><strong>{metric.label}</strong><small>{metric.period}</small></span><b>{metricText(metric)}</b><em>{metric.state === 'support' ? '支持研究' : metric.state === 'caution' ? '需要核查' : metric.value === null ? '证据不足' : '仅供参考'}</em><Info size={13} /></button>)}</div>}
        {tab === 'history' && <><div className="history-heading"><h3>穿过一个周期，生意留下了什么</h3><span>{company.financialCurrency === 'TWD' ? '新台币' : '美元'} · 最新披露口径</span></div>{quality?.history.length ? <><div className="annual-chart" aria-label="最近年度营收柱状图">{quality.history.map(row => { const maximum = Math.max(...quality.history.map(item => item.revenue || 0), 1); return <div key={row.periodEnd}><span>{formatMoney(row.revenue, company.financialCurrency)}</span><div><i style={{ height: `${row.revenue == null ? 0 : row.revenue / maximum * 100}%` }} /></div><b>{row.periodEnd.slice(0, 4)}</b></div> })}</div><div className="history-table-wrap"><table className="history-table"><thead><tr><th>财年结束</th><th>营收</th><th>净利润</th><th>自由现金</th></tr></thead><tbody>{quality.history.map(row => <tr key={row.periodEnd}><td>{row.periodEnd}</td><td>{formatMoney(row.revenue, company.financialCurrency)}</td><td>{formatMoney(row.netIncome, company.financialCurrency)}</td><td className={row.freeCashFlow != null && row.freeCashFlow < 0 ? 'negative-text' : ''}>{formatMoney(row.freeCashFlow, company.financialCurrency)}</td></tr>)}</tbody></table></div><p className="research-footnote">各公司财年不同；金额按最新披露重述，不用于历史时点回测。台积电年度营收、净利润由四个原币种季度相加，未核验的历史现金留空。</p></> : <div className="research-empty"><FileText size={25} /><strong>跨年记录尚未齐全</strong><p>不会把缺失的年份当成稳定盈利记录。</p></div>}</>}
        {tab === 'business' && <div className="business-case"><section><span className="mini-heading">如何赚钱</span><h3>{profile?.business || '商业模式待研究'}</h3></section><section><span className="mini-heading">竞争优势假设</span><p>{profile?.advantage || company.moat}</p><small>研究判断，不是已核验的市场份额或护城河评分。</small></section><section><span className="mini-heading">什么会推翻持有理由</span><ol>{(profile?.falsifiers || company.risks).map(item => <li key={item}>{item}</li>)}</ol></section><section><span className="mini-heading">管理层与资本配置</span><p>{profile?.capitalQuestion || '管理层如何将保留利润转化为长期每股价值？'}</p><small>高 ROE 不代表管理层诚实或回购价格合理，这些需要阅读年报与资本配置记录。</small></section>{profile && <a className="text-link" href={profile.sourceUrl} target="_blank" rel="noreferrer">公司披露入口 <ExternalLink size={13} /></a>}<p className="research-footnote">方法参考伯克希尔 1986、1992 年股东信中的所有者盈余、资本回报和安全边际原则，不代表巴菲特本人观点或投资建议。</p></div>}
      </div>
      <footer className="research-provenance"><span><span className={`connection-dot ${connected ? 'online' : ''}`} />财务 {company.financials?.periodEnd || '待取得'} <span className="separator">/</span> {percentile === null ? '历史分位暂停' : `${company.valuation.horizonYears}年 PE 分位 ${percentile.toFixed(1)}%`}</span><button onClick={onSources}>证据与方法 <ArrowRight size={13} /></button></footer>
    </section>
    <ValueWorkbench key={company.symbol} company={company} connected={connected} />
    {detail && <MetricDetail metric={detail} onClose={() => setDetail(null)} />}
  </main>
}

interface ResearchDraft {
  cash: string | null
  growth: number
  requiredReturn: number
  terminalGrowth: number
  safetyMargin: number
  thesis: string
  falsifier: string
  reviewedKey: string | null
  candidate: boolean
}

const defaultDraft: ResearchDraft = { cash: null, growth: 5, requiredReturn: 10, terminalGrowth: 2, safetyMargin: 25, thesis: '', falsifier: '', reviewedKey: null, candidate: false }

function loadDraft(symbol: string): ResearchDraft {
  try {
    const saved = JSON.parse(localStorage.getItem(`stock-monitor-research-${symbol}`) || 'null') as Partial<ResearchDraft> | null
    if (!saved || typeof saved !== 'object') return { ...defaultDraft }
    const result = { ...defaultDraft }
    for (const key of ['growth', 'requiredReturn', 'terminalGrowth', 'safetyMargin'] as const) if (typeof saved[key] === 'number' && Number.isFinite(saved[key])) result[key] = saved[key]
    if (typeof saved.cash === 'string') result.cash = saved.cash
    for (const key of ['thesis', 'falsifier'] as const) if (typeof saved[key] === 'string') result[key] = saved[key].slice(0, 3000)
    result.reviewedKey = typeof saved.reviewedKey === 'string' ? saved.reviewedKey : null
    result.candidate = saved.candidate === true
    return result
  } catch { return { ...defaultDraft } }
}

function ValueWorkbench({ company, connected }: { company: CompanySnapshot; connected: boolean }) {
  const [draft, setDraft] = useState(() => loadDraft(company.symbol))
  const [tab, setTab] = useState<'value' | 'sensitivity' | 'memo'>('value')
  const [storageError, setStorageError] = useState(false)
  useEffect(() => {
    try { localStorage.setItem(`stock-monitor-research-${company.symbol}`, JSON.stringify(draft)); setStorageError(false) }
    catch { setStorageError(true) }
  }, [company.symbol, draft])
  const baseline = cashBaseline(company)
  const cash = draft.cash === null ? baseline : draft.cash.trim() ? Number(draft.cash) : null
  const priceReady = connected && company.valuation.algorithmVersion === 4 && company.valuation.currentPeQualified === true
  const price = priceReady ? company.valuation.price ?? null : null
  const assumptions: ValueAssumptions = { cashPerShare: cash ?? 0, growth: draft.growth, requiredReturn: draft.requiredReturn, terminalGrowth: draft.terminalGrowth, safetyMargin: draft.safetyMargin, years: 10 }
  const result = discountedCashValue(assumptions, price)
  const reviewKey = valuationReviewKey(company, assumptions)
  const reviewed = Boolean(result && draft.reviewedKey === reviewKey)
  const canReview = Boolean(result && priceReady && assessInvestment(company.financials, company.valuation, company.earnings?.pendingStructuredData).fresh)
  const hasMargin = result?.marginAtPrice != null && result.marginAtPrice >= draft.safetyMargin
  const update = (patch: Partial<ResearchDraft>) => setDraft(current => ({ ...current, ...patch, reviewedKey: patch.reviewedKey ?? null }))
  const condition = !priceReady ? '价格或盈利未确认有效，暂停安全边际判断。' : !result ? cash != null && cash > 0 ? '参数无效：回报要求须高于长期增长，数值需完整。' : '缺少正的美元每股可持续现金，暂不生成估值。' : !reviewed ? '当前财报与假设尚未复核，结果仅为试算。' : hasMargin ? '在你的假设下留有折价，仍需核查生意与风险。' : '当前价格尚未达到你设定的折价要求。'
  return <aside className="value-workbench"><header className="value-heading"><div><span className="eyebrow"><Calculator size={14} /> 价格纪律</span><h2>留出安全边际</h2></div><button className="icon-button" title="重置估值参数，保留研究备忘" onClick={() => setDraft(current => ({ ...defaultDraft, thesis: current.thesis, falsifier: current.falsifier, candidate: current.candidate }))}><RotateCcw size={15} /></button></header><nav className="value-tabs" role="tablist" aria-label="估值工具">{([{ id: 'value', label: '估值假设' }, { id: 'sensitivity', label: '敏感性' }, { id: 'memo', label: '我的论点' }] as const).map(item => <button role="tab" aria-selected={tab === item.id} key={item.id} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav><div className="value-body">
      {tab === 'value' && <>
        <div className="margin-result">
          <span>含 {Number.isFinite(draft.safetyMargin) ? draft.safetyMargin : '--'}% 折价的观察价 <small>{reviewed ? '你的假设' : '未复核试算'}</small></span>
          <strong>{result ? dollars(result.entryPrice) : '--'}</strong>
          <div><span>模型参考值 <b>{dollars(result?.value)}</b></span><span>有效收盘价 <b>{dollars(price)}</b><small>{priceReady ? company.valuation.asOf : '等待有效数据'}</small></span></div>
        </div>
        <label className="cash-input">
          <span>每股可持续现金 <small>USD / 年</small></span>
          <div><b>$</b><input aria-label="每股可持续现金" type="number" min="0.01" step="0.1" placeholder="待核验" value={draft.cash ?? (baseline === null ? '' : baseline.toFixed(4))} onChange={event => update({ cash: event.target.value })} /></div>
        </label>
        <p className="baseline-note">{draft.cash !== null ? '手动假设，不代表已披露的每股现金。' : baseline !== null ? '起点为 TTM 自由现金扣股份薪酬 / 披露加权股数，不等于所有者盈余。' : company.financialCurrency === 'TWD' ? '新台币现金不能自动换成美元 ADR 盈余。' : '现金代理缺失、非正或失效，不自动填值。'}</p>
        <div className="valuation-inputs">
          {([{ key: 'growth', label: '前十年增长', min: -20, max: 50, step: 1 }, { key: 'requiredReturn', label: '要求年回报', min: 3, max: 30, step: 0.5 }, { key: 'terminalGrowth', label: '长期增长', min: -5, max: 5, step: 0.5 }, { key: 'safetyMargin', label: '安全折价', min: 0, max: 80, step: 5 }] as const).map(field => (
            <label key={field.key}><span>{field.label}</span><div><input type="number" aria-label={field.label} min={field.min} max={field.max} step={field.step} value={Number.isFinite(draft[field.key]) ? draft[field.key] : ''} onChange={event => update({ [field.key]: event.target.value === '' ? NaN : Number(event.target.value) })} /><b>%</b></div></label>
          ))}
        </div>
        <label className="review-check"><input type="checkbox" checked={reviewed && canReview} disabled={!canReview} onChange={event => update({ reviewedKey: event.target.checked ? reviewKey : null })} />现金基线、增长与回报假设已复核</label>
        <p className={`margin-condition ${reviewed && canReview && hasMargin ? 'support' : ''}`}><CircleAlert size={14} />{condition}</p>
        {result && <p className="terminal-warning">终值占估值 {result.terminalWeight.toFixed(0)}%。{result.terminalWeight > 70 ? '结果高度依赖远期假设。' : '未来现金与稀释仍可能偏离假设。'}</p>}
        <p className="research-footnote">十年现金逐年折现，加长期终值；回报要求须高于长期增长。示例参数不是公司指引。</p>
      </>}
      {tab === 'sensitivity' && <><h3 className="subsection-title">假设变一点，价格差多少</h3><p className="research-footnote">下表为含 {draft.safetyMargin}% 折价的观察价，其他假设不变。</p><div className="sensitivity-wrap"><table className="sensitivity-table"><thead><tr><th>增长 / 回报</th>{[-1, 0, 1].map(offset => <th key={offset}>{draft.requiredReturn + offset}%</th>)}</tr></thead><tbody>{[-3, 0, 3].map(growthOffset => <tr key={growthOffset}><th>{draft.growth + growthOffset}%</th>{[-1, 0, 1].map(returnOffset => { const cell = discountedCashValue({ ...assumptions, growth: draft.growth + growthOffset, requiredReturn: draft.requiredReturn + returnOffset }, price); return <td className={growthOffset === 0 && returnOffset === 0 ? 'selected-assumption' : ''} key={returnOffset}>{dollars(cell?.entryPrice)}</td> })}</tr>)}</tbody></table></div><div className="discount-breakdown"><h3>模型价值从哪里来</h3><dl><div><dt>前十年现金现值</dt><dd>{dollars(result?.presentCash)}</dd></div><div><dt>终值现值</dt><dd>{dollars(result?.presentTerminal)}</dd></div><div><dt>当前价格的模型折价</dt><dd>{result?.marginAtPrice == null ? '--' : `${result.marginAtPrice.toFixed(1)}%`}</dd></div></dl></div><p className="research-footnote">没有独立验证的现金预测，就没有确定的内在价值。该模型不另加现金、不减债务；输入应代表可持续、偿付义务之后的每股现金假设，不能把企业自由现金直接套入。</p><p className="margin-condition"><Info size={14} />{condition}</p></>}
      {tab === 'memo' && <><h3 className="subsection-title">写给未来的自己</h3><label className="memo-field"><span>我愿意持有的理由</span><textarea maxLength={3000} value={draft.thesis} onChange={event => setDraft(current => ({ ...current, thesis: event.target.value }))} placeholder="一条能用事实验证的理由" /></label><label className="memo-field"><span>什么事实会让我改判</span><textarea maxLength={3000} value={draft.falsifier} onChange={event => setDraft(current => ({ ...current, falsifier: event.target.value }))} placeholder="写下条件，而不只是股价涨跌" /></label><label className="candidate-check"><input type="checkbox" checked={draft.candidate} onChange={event => setDraft(current => ({ ...current, candidate: event.target.checked }))} /><Bookmark size={14} />列入我的候选研究</label><p className="research-footnote">这是个人研究记录，不会触发交易。</p></>}
    </div><footer className="value-footer"><span className={`connection-dot ${storageError ? '' : 'online'}`} />{storageError ? '本地保存失败，请检查浏览器存储' : '参数与论点保存在本机浏览器'}<ShieldCheck size={13} /></footer></aside>
}

export function CompareWorkspace({ companies, connected, onSelect }: { companies: CompanySnapshot[]; connected: boolean; onSelect: (symbol: string) => void }) {
  const [filter, setFilter] = useState<'all' | 'cash' | 'history'>('all')
  const [onlyCandidates, setOnlyCandidates] = useState(false)
  const [sort, setSort] = useState<'symbol' | 'cagr' | 'margin' | 'cash' | 'roe'>('symbol')
  const [ascending, setAscending] = useState(true)
  const rows = companies.map(company => ({ company, assessment: assessInvestment(company.financials, company.valuation, company.earnings?.pendingStructuredData || !connected) }))
  const metric = (row: typeof rows[number], key: string) => row.assessment.metrics.find(item => item.key === key)
  const filtered = rows.filter(row => (!onlyCandidates || loadDraft(row.company.symbol).candidate) && (filter === 'all' || row.assessment.fresh && (filter === 'cash' ? (metric(row, 'cash')?.value ?? -1) > 0 : metric(row, 'consistency')?.value === 5))).sort((first, second) => {
    if (sort === 'symbol') return first.company.symbol.localeCompare(second.company.symbol) * (ascending ? 1 : -1)
    const firstValue = metric(first, sort)?.value
    const secondValue = metric(second, sort)?.value
    if (firstValue == null) return secondValue == null ? 0 : 1
    if (secondValue == null) return -1
    return (firstValue - secondValue) * (ascending ? 1 : -1)
  })
  return <main className="compare-workspace">
    <header className="compare-heading"><div><span className="eyebrow">我的观察池</span><h2>好生意，也需要好价格。</h2><p>同看经营质量与风险，不把不同历史窗口排成一个选股分数。</p></div><div className="compare-count"><strong>{filtered.length}</strong><span>/ {companies.length} 家公司</span></div></header>
    <div className="compare-tools">
      <nav className="filter-tabs" aria-label="财务筛选">{([{ id: 'all', label: '全部公司' }, { id: 'cash', label: '当期正自由现金' }, { id: 'history', label: '五年现金均为正' }] as const).map(item => <button className={filter === item.id ? 'active' : ''} aria-pressed={filter === item.id} key={item.id} onClick={() => setFilter(item.id)}>{item.label}</button>)}</nav>
      <label className="candidate-filter"><input type="checkbox" checked={onlyCandidates} onChange={event => setOnlyCandidates(event.target.checked)} /><Bookmark size={12} />我的候选</label>
      <label className="sort-control"><SlidersHorizontal size={14} /><select aria-label="比较排序指标" value={sort} onChange={event => setSort(event.target.value as typeof sort)}><option value="symbol">公司代码</option><option value="cagr">五年营收增长</option><option value="margin">营业利润率</option><option value="cash">自由现金率</option><option value="roe">权益回报</option></select></label>
      <button className="icon-button" title={ascending ? '改为降序' : '改为升序'} onClick={() => setAscending(value => !value)}>{ascending ? <ArrowUp size={14} /> : <ArrowDown size={14} />}</button>
    </div>
    <div className="compare-scroll"><table className="comparison-table"><thead><tr><th>公司 / 研究状态</th><th>TTM PE</th><th>历史分位</th><th>五年营收增长</th><th>营业利润率</th><th>自由现金率</th><th>ROE</th><th>优先核查</th></tr></thead><tbody>
      {filtered.map(row => {
        const percentile = eligiblePercentile(row.company.valuation)
        return <tr key={row.company.symbol}>
          <td><button className="compare-company" onClick={() => onSelect(row.company.symbol)}><CompanyIcon symbol={row.company.symbol} /><span><strong>{row.company.shortName}<small>{row.company.symbol}</small></strong><em className={row.assessment.state}>{row.assessment.label}</em></span>{loadDraft(row.company.symbol).candidate ? <Bookmark size={13} aria-label="我的候选" /> : <ArrowRight size={13} />}</button></td>
          <td>{row.company.valuation.currentPeQualified ? row.company.valuation.pe?.toFixed(2) : '--'}<small>收盘 {row.company.valuation.asOf}</small></td>
          <td>{percentile === null ? '--' : `${percentile.toFixed(1)}%`}<small>{percentile === null ? '暂无有效窗口' : `${row.company.valuation.horizonYears} 年日频`}</small></td>
          {['cagr', 'margin', 'cash', 'roe'].map(key => <td className={metric(row, key)?.state === 'caution' ? 'negative-text' : ''} title={metric(row, key)?.explanation} key={key}>{metricText(metric(row, key))}</td>)}
          <td className="compare-risk">{row.assessment.concerns.find(item => item.key === 'profitQuality')?.label || row.assessment.concerns[0]?.label || row.assessment.missing[0]}<small>财务 {row.company.financials?.periodEnd || '待取得'}</small></td>
        </tr>
      })}
    </tbody></table>{!filtered.length && <div className="research-empty"><CircleAlert size={25} /><strong>当前没有符合条件的公司</strong><button className="text-link" onClick={() => { setFilter('all'); setOnlyCandidates(false) }}>查看全部公司</button></div>}</div>
    <footer className="compare-footer"><Info size={15} /><p>增长和利润率不是越高越好；高 ROE 可能来自低权益或非经营收益。不同公司的财年、资本密集度与货币口径不同，筛选结果仅确定研究顺序。</p></footer>
  </main>
}