import React, { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom/client'
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Building2,
  Check,
  CircleHelp,
  Droplets,
  FileSpreadsheet,
  FlaskConical,
  LayoutDashboard,
  LoaderCircle,
  Moon,
  ShieldCheck,
  TriangleAlert,
  Upload,
  Waves,
  X,
} from 'lucide-react'
import type { Building, Workspace } from './types'
import { date, number, time } from './format'
import Chart from './Chart'
import { IncidentPanel, WorkflowControls } from './Workflow'
import './styles.css'
import { apiFetch, apiUrl, isHosted, restartHostedSession, viewStorage } from './api'

const labels: Record<Building['status'], string> = {
  possible_loss: 'Possible water loss',
  no_pattern: 'No sustained pattern',
  insufficient_history: 'Insufficient history',
  incomplete_data: 'Incomplete readings',
}

function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const data = workspace?.analysis.building_count ? workspace.analysis : null
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [filename, setFilename] = useState('')
  const [notice, setNotice] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const building = data?.buildings.find((b) => b.building_id === selected) ?? data?.buildings[0]
  const alertCount = data?.buildings.filter((b) => b.alerts.length > 0).length ?? 0

  function applyWorkspace(result: Workspace, preserveSelection = true) {
    setWorkspace(result)
    setSelected((current) =>
      preserveSelection && result.analysis.buildings.some((b) => b.building_id === current)
        ? current
        : (result.analysis.buildings.find((b) => b.alerts.length)?.building_id ??
          result.incidents[0]?.building_id ??
          result.analysis.buildings[0]?.building_id ??
          ''),
    )
    try {
      viewStorage().setItem(
        'leaklens-view',
        JSON.stringify({ scope: result.scope, cutoff: result.cutoff }),
      )
    } catch {
      /* Database persistence is independent of browser preferences. */
    }
    setNotice(result.message ?? '')
  }

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      controller.abort()
      setBusy(false)
      setError(
        'Workspace restore timed out. Check the backend and use View saved uploads to retry.',
      )
    }, 30_000)
    let view = { scope: 'uploads', cutoff: '' }
    try {
      view = JSON.parse(viewStorage().getItem('leaklens-view') ?? 'null') ?? view
    } catch {
      /* Use saved uploads if preferences are invalid. */
    }
    setBusy(true)
    apiFetch(
      `/api/workspace?scope=${encodeURIComponent(view.scope)}${view.cutoff ? `&cutoff=${encodeURIComponent(view.cutoff)}` : ''}`,
      { signal: controller.signal },
    )
      .then(async (response) => {
        if (!response.ok)
          throw new Error(
            'Could not restore the saved workspace. Check the backend, then choose View saved uploads or Load demo data.',
          )
        return response.json() as Promise<Workspace>
      })
      .then((result) => {
        if (!controller.signal.aborted) applyWorkspace(result, false)
      })
      .catch((err) => {
        if (!controller.signal.aborted)
          setError(err instanceof Error ? err.message : 'Could not restore workspace.')
      })
      .finally(() => {
        window.clearTimeout(timeout)
        if (!controller.signal.aborted) setBusy(false)
      })
    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [])

  async function requestWorkspace(url: string, body?: object): Promise<boolean> {
    if (busy) return false
    setBusy(true)
    setError('')
    setNotice('')
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 30_000)
    try {
      const response = await apiFetch(url, {
        method: body ? 'POST' : 'GET',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      })
      const result = await response.json().catch(() => null)
      if (!response.ok || !result?.analysis)
        throw new Error(
          typeof result?.detail === 'string'
            ? result.detail
            : 'The server could not complete this action. Check the backend and try again.',
        )
      if (result.scope === 'replay' && !result.replay && workspace?.replay)
        result.replay = workspace.replay
      applyWorkspace(result)
      if (url.startsWith('/api/replay')) setSelected('Hostel B')
      return true
    } catch (err) {
      setError(
        err instanceof Error && err.name === 'AbortError'
          ? 'The request timed out. Refresh the workspace before retrying; the action may have been saved.'
          : err instanceof Error
            ? err.message
            : 'Could not reach the server.',
      )
      return false
    } finally {
      window.clearTimeout(timeout)
      setBusy(false)
    }
  }

  async function load(file?: File) {
    if (busy) return
    setError('')
    if (file && file.size > (isHosted ? 512 * 1024 : 8 * 1024 * 1024)) {
      setError(
        isHosted
          ? 'Hosted uploads allow up to 512 KiB and 3,000 rows. Choose a smaller CSV.'
          : 'This file is larger than 8 MB. Choose a smaller CSV.',
      )
      return
    }
    setBusy(true)
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 30_000)
    try {
      const body = new FormData()
      if (file) body.append('file', file)
      const response = await apiFetch(file ? '/api/analyze' : '/api/demo', {
        method: file ? 'POST' : 'GET',
        body: file ? body : undefined,
        signal: controller.signal,
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(
          [409, 413, 422].includes(response.status) && typeof payload?.detail === 'string'
            ? payload.detail
            : isHosted
              ? 'The hosted API could not complete this request. Please try again shortly.'
              : 'The analysis server could not complete this request. Check that the FastAPI backend is running on port 8000, then try again.',
        )
      }
      const saved = await apiFetch(`/api/workspace?scope=${file ? 'uploads' : 'demo'}`, {
        signal: controller.signal,
      })
      if (!saved.ok)
        throw new Error(
          'Readings were processed, but the saved workspace could not be loaded. Choose View saved uploads to retry.',
        )
      applyWorkspace(await saved.json(), false)
      if (file)
        setNotice(
          'Readings saved. Identical repeats were ignored; existing readings were preserved.',
        )
      setFilename(file?.name ?? 'Built-in simulated dataset')
    } catch (err) {
      setError(
        err instanceof TypeError
          ? isHosted
            ? 'Cannot reach the hosted API. Check your connection and try again.'
            : 'Cannot reach the analysis server. Start the FastAPI backend on port 8000, then try again.'
          : err instanceof Error && err.name === 'AbortError'
            ? 'The request took too long. Check the backend and try again.'
            : err instanceof Error
              ? err.message
              : 'Something went wrong. Please try again.',
      )
    } finally {
      window.clearTimeout(timeout)
      setBusy(false)
    }
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <aside className="sidebar">
        <a className="brand" href="#main" aria-label="LeakLens home">
          <span className="brand-icon">
            <Droplets size={24} />
          </span>
          <span>
            LeakLens<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="workspace-label">HOSTEL WATER MONITORING</div>
        <nav aria-label="Main navigation">
          <a className="nav-link active" href="#overview">
            <LayoutDashboard size={18} /> Overview <span className="nav-dot" />
          </a>
          <a className="nav-link" href="#data">
            <FileSpreadsheet size={18} /> Data & examples
          </a>
          <a className="nav-link" href="#method">
            <CircleHelp size={18} /> How it works
          </a>
        </nav>
        <div className="sidebar-note">
          <span className="note-icon">
            <Waves size={24} />
          </span>
          <h3>A clearer view of water use.</h3>
          <p>Spot unusual overnight patterns. Know where to look next.</p>
          <div className="local-tag">
            <span /> {isHosted ? 'Private demo session' : 'Local workspace'}
          </div>
        </div>
        <div className="sidebar-footer">
          <div className="avatar">MS</div>
          <div>
            <strong>Maintenance supervisor</strong>
            <span>Campus operations</span>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span> <strong>Overview</strong>
          </span>
          <span className="timezone">
            <span className="live-dot" /> Asia/Kolkata <span className="muted">· UTC+05:30</span>
          </span>
        </header>
        <main id="main">
          <section id="overview" className="page-heading">
            <div>
              <div className="eyebrow">EVERY DROP, BETTER UNDERSTOOD</div>
              <h1>Water consumption overview</h1>
              <p>
                For hostel maintenance supervisors: spot possible overnight water loss, record an
                inspection, and check consumption after a repair.
              </p>
            </div>
            <button
              className="button primary"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
            >
              <Upload size={17} /> Upload readings
            </button>
          </section>

          <section id="data" className="upload-panel" aria-label="Upload readings">
            <div className="upload-icon">
              <FileSpreadsheet size={26} />
            </div>
            <div className="upload-copy">
              <h2>
                {data
                  ? 'Your next check starts with fresh readings'
                  : 'Start with your hourly water readings'}
              </h2>
              <p>Try the five-stage simulation, or upload hourly readings from your hostel.</p>
              <div className="example-links">
                <span>Download simulated CSVs:</span>
                <a href={apiUrl('/api/examples/possible-water-loss')} download>
                  <ArrowDownToLine size={13} /> Download sample CSV
                </a>
                <a href={apiUrl('/api/examples/normal')} download>
                  <ArrowDownToLine size={13} /> Normal use
                </a>
              </div>
            </div>
            <button
              className="button primary"
              onClick={() => void requestWorkspace('/api/replay/start', {})}
              disabled={busy}
            >
              <FlaskConical size={17} /> Try simulated demo
            </button>
            <button className="button secondary" onClick={() => void load()} disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : <FlaskConical size={17} />}{' '}
              {busy ? 'Analyzing readings…' : 'Load demo data'}
            </button>
            <input
              ref={fileInput}
              className="visually-hidden"
              tabIndex={-1}
              type="file"
              accept=".csv,text/csv"
              aria-label="Choose water readings CSV"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) void load(file)
                e.target.value = ''
              }}
            />
          </section>
          <details className="format-help">
            <summary>CSV format and upload requirements</summary>
            <p>
              Required header: <code>building_id,timestamp,consumption_liters</code>
            </p>
            <p>
              Example row: <code>Hostel A,2026-09-29T01:00:00+05:30,48.5</code>
            </p>
            <p>
              Each value is liters consumed during the hour beginning at that timestamp, not a
              cumulative meter reading. Use explicit timezone offsets and hour starts aligned to
              Asia/Kolkata. Include at least 7 previous days for each overnight hour (28
              recommended).{' '}
              {isHosted
                ? 'Hosted limit: 512 KiB and 3,000 rows per upload; 12,000 readings and 12 buildings per session, with a bounded session storage size.'
                : 'Maximum 8 MB and 100,000 rows.'}{' '}
              Uploads merge with saved readings: identical repeats are ignored, but a different
              value for an existing building/hour rejects the whole upload. Existing readings are
              never silently overwritten.
            </p>
          </details>
          {isHosted && (
            <div className="replay-stage">
              <div>
                <strong>Temporary private demo session</strong>
                <p>
                  This browser session expires after 24 hours. Closing the tab may lose access.
                  Starting a new session leaves the current workspace behind.
                </p>
              </div>
              <button className="button secondary" disabled={busy} onClick={restartHostedSession}>
                Start new hosted session
              </button>
            </div>
          )}
          <WorkflowControls workspace={workspace} busy={busy} request={requestWorkspace} />
          {error && (
            <div className="error-banner" role="alert">
              <TriangleAlert size={20} />
              <div>
                <strong>We couldn’t analyze these readings</strong>
                <p>{error}</p>
                {data && <p>The previous successful analysis is still displayed below.</p>}
              </div>
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => setError('')}
              >
                <X size={18} />
              </button>
            </div>
          )}
          <div role="status" aria-live="polite" className="visually-hidden">
            {busy
              ? 'Analyzing readings. Please wait.'
              : data
                ? `Analysis loaded: ${data.building_count} buildings, ${alertCount} with possible water loss.`
                : ''}
            {notice ? ` ${notice}` : ''}
          </div>
          {notice && <p className="workflow-notice">{notice}</p>}
          {data && (
            <div className={`source-banner ${data.source === 'simulated' ? 'simulated' : ''}`}>
              <span>
                {data.source === 'simulated' ? <FlaskConical size={16} /> : <Check size={16} />}
                <strong>
                  {data.source === 'simulated' ? 'Simulated data' : 'Uploaded readings'}
                </strong>
                <span>
                  {data.source === 'simulated'
                    ? 'For demonstration only · not real meter readings'
                    : filename || 'Saved local readings'}
                </span>
              </span>
              <span>
                {date(data.period_start!)} –{' '}
                {date(new Date(new Date(data.period_end!).getTime() - 1).toISOString())}
              </span>
            </div>
          )}

          <section className="stats" aria-label="Dataset overview">
            <div className="stat-card">
              <div className="stat-label">
                Buildings in dataset <Building2 size={18} />
              </div>
              <div className="stat-value">
                {data ? data.building_count : '—'}
                <span>hostels</span>
              </div>
              <p>
                {data
                  ? `${number(data.reading_count)} hourly readings uploaded`
                  : 'Upload readings to get started'}
              </p>
            </div>
            <div className={`stat-card ${alertCount ? 'stat-alert' : ''}`}>
              <div className="stat-label">
                Possible water loss <TriangleAlert size={18} />
              </div>
              <div className="stat-value">
                {data ? alertCount : '—'}
                <span>{alertCount === 1 ? 'building to review' : 'buildings to review'}</span>
              </div>
              <p>Latest eligible overnight period per building</p>
            </div>
            <div className="stat-card">
              <div className="stat-label">
                Overnight check <Moon size={18} />
              </div>
              <div className="stat-value time-value">
                00:00 <span>–</span> 06:00
              </div>
              <p>Asia/Kolkata · 3+ consecutive high hours</p>
            </div>
          </section>

          {!building ? (
            <section className="empty-state">
              <div className="empty-art">
                <Activity size={44} strokeWidth={1.4} />
              </div>
              <span className="eyebrow">READY WHEN YOU ARE</span>
              <h2>See what happens after lights out.</h2>
              <p>
                Your chart and overnight assessment will appear here.
                <br />
                Try the simulated demo to see an explainable alert in action.
              </p>
              <button className="text-button" disabled={busy} onClick={() => void load()}>
                Explore demo data <ArrowRight size={16} />
              </button>
            </section>
          ) : (
            <div aria-busy={busy} className={busy ? 'results loading-results' : 'results'}>
              <section className="building-bar">
                <div>
                  <h2>Building detail</h2>
                  <p>Review one hostel at a time.</p>
                </div>
                <div className="select-wrap">
                  <label htmlFor="building">Select building</label>
                  <select
                    id="building"
                    value={building.building_id}
                    onChange={(e) => setSelected(e.target.value)}
                  >
                    {data!.buildings.map((b) => (
                      <option key={b.building_id}>{b.building_id}</option>
                    ))}
                  </select>
                </div>
              </section>
              <section className="chart-panel panel">
                <div className="panel-header">
                  <div>
                    <h2>
                      Daily consumption{' '}
                      <span className="subtle-pill">Liters per hourly reading</span>
                    </h2>
                    <p>{date(building.evaluation_start)} · Asia/Kolkata (UTC+05:30)</p>
                  </div>
                  <span className={`status-pill ${building.status}`}>
                    {building.status === 'possible_loss' ? (
                      <TriangleAlert size={14} />
                    ) : building.status === 'no_pattern' ? (
                      <Check size={14} />
                    ) : (
                      <CircleHelp size={14} />
                    )}
                    {labels[building.status]}
                  </span>
                </div>
                <div className="legend">
                  <span>
                    <i className="legend-observed" /> Observed
                  </span>
                  <span>
                    <i className="legend-baseline" /> Historical baseline
                  </span>
                  <span>
                    <i className="legend-threshold" /> Overnight threshold
                  </span>
                </div>
                <Chart key={building.building_id} points={building.points} />
              </section>
              <section className="assessment-grid">
                <div className={`assessment panel ${building.alerts.length ? 'attention' : ''}`}>
                  <div className="assessment-title">
                    <span className="assessment-icon">
                      {building.alerts.length ? (
                        <TriangleAlert size={22} />
                      ) : (
                        <ShieldCheck size={22} />
                      )}
                    </span>
                    <div>
                      <div className="eyebrow">OVERNIGHT ASSESSMENT</div>
                      <h2>{labels[building.status]}</h2>
                    </div>
                  </div>
                  <p className="assessment-period">
                    {date(building.evaluation_start)} · 00:00–06:00 IST · {building.building_id}
                  </p>
                  {building.alerts.map((alert) => (
                    <div key={alert.start}>
                      <p>
                        Consumption stayed above its hourly threshold for{' '}
                        <strong>{alert.duration_hours} consecutive hours</strong>, from{' '}
                        {time(alert.start)} to {time(alert.end)} IST.
                      </p>
                      <div className="alert-metrics">
                        <div>
                          <span>Observed in this period</span>
                          <strong>
                            {number(alert.observed_liters)} <small>L</small>
                          </strong>
                        </div>
                        <div>
                          <span>Historical baseline</span>
                          <strong>
                            {number(alert.baseline_liters)} <small>L</small>
                          </strong>
                        </div>
                        <div>
                          <span>Sum of hourly thresholds</span>
                          <strong>
                            {number(alert.threshold_liters)} <small>L</small>
                          </strong>
                        </div>
                      </div>
                      <p className="explanation">
                        Each flagged hour exceeded the greater of <strong>2 × its baseline</strong>{' '}
                        or <strong>baseline + 50 L</strong>. Baselines use the median for the same
                        hour from the previous 28 days, with at least 7 readings per hour.
                      </p>
                      <div className="next-step">
                        <strong>Suggested next step</strong>
                        <p>
                          Check for running taps, tank overflow, or scheduled overnight use in{' '}
                          {building.building_id}. This pattern indicates possible water loss; it
                          does not confirm the cause.
                        </p>
                      </div>
                    </div>
                  ))}
                  {building.status === 'no_pattern' && (
                    <>
                      <p>
                        No three consecutive overnight hours exceeded the threshold. This check does
                        not rule out smaller or intermittent water loss.
                      </p>
                      <div className="alert-metrics">
                        <div>
                          <span>Observed overnight</span>
                          <strong>
                            {number(building.overnight_liters)} <small>L</small>
                          </strong>
                        </div>
                        <div>
                          <span>Historical baseline</span>
                          <strong>
                            {number(building.baseline_liters!)} <small>L</small>
                          </strong>
                        </div>
                      </div>
                    </>
                  )}
                  {building.insufficient_history_hours > 0 && (
                    <p className="quality-note">
                      <strong>
                        Insufficient history for {building.insufficient_history_hours} of 6
                        overnight hours.
                      </strong>{' '}
                      Supply at least 7 prior readings for each hour within the preceding 28 days. A
                      complete overnight assessment is unavailable.
                    </p>
                  )}
                  {building.missing_hours > 0 && (
                    <p className="quality-note">
                      <strong>{building.missing_hours} of 6 overnight readings are missing.</strong>{' '}
                      Gaps break the sustained-consumption check and are never counted as zero. Any
                      alert above covers only the observed consecutive hours.
                    </p>
                  )}
                </div>
                <aside className="context-panel panel">
                  <Moon size={23} />
                  <h2>Why look overnight?</h2>
                  <p>When routine activity is lower, sustained changes can be easier to spot.</p>
                  <hr />
                  <h3>A comparison, not a diagnosis</h3>
                  <p>
                    Every hostel is compared with its own history. Occupancy changes, cleaning, and
                    tank filling can also explain higher use.
                  </p>
                  <a href="#method">
                    Understand the method <ArrowRight size={15} />
                  </a>
                </aside>
              </section>
            </div>
          )}
          {workspace && building && (
            <IncidentPanel
              workspace={workspace}
              building={building}
              busy={busy}
              request={requestWorkspace}
            />
          )}
          <section className="method panel" id="method">
            <div className="method-heading">
              <span className="eyebrow">SIMPLE BY DESIGN</span>
              <h2>Every alert has a reason.</h2>
              <p>No black box. Just your readings and a transparent comparison.</p>
            </div>
            <div className="method-steps">
              <div>
                <span>01</span>
                <h3>Learn the usual pattern</h3>
                <p>
                  Take the median for the same building and hour over the prior 28 days. Require at
                  least 7 earlier readings per hour.
                </p>
              </div>
              <div>
                <span>02</span>
                <h3>Look for a sustained change</h3>
                <p>
                  Between midnight and 6 a.m., look for 3 consecutive hours above both twice the
                  baseline and baseline plus 50 liters.
                </p>
              </div>
              <div>
                <span>03</span>
                <h3>Give you a place to start</h3>
                <p>
                  Show the observed liters, baseline, duration, and threshold so you can decide what
                  to inspect.
                </p>
              </div>
            </div>
            <p className="method-footnote">
              The latest eligible night is chosen separately for each building using its last
              reading, not today’s date. Earlier nights are history only. Weekdays and weekends are
              pooled; thresholds are a screening heuristic, not a calibrated guarantee.
            </p>
          </section>
          <footer className="footer">
            <span>
              <Droplets size={15} /> LeakLens{' '}
              <span className="muted">· A little clarity for every drop.</span>
            </span>
            <span>
              {isHosted
                ? 'Temporary hosted demo · Session expires after 24 hours'
                : 'Local workspace · Readings and maintenance history saved on this computer'}
            </span>
          </footer>
        </main>
      </div>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
