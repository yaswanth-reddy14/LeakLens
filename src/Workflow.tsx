import { useEffect, useState } from 'react'
import type { Building, Incident, Workspace } from './types'
import { date, number, time } from './format'
import { isHosted } from './api'

export type RequestWorkspace = (url: string, body?: object) => Promise<boolean>
const stamp = (value: string) => `${date(value)} at ${time(value)} IST`
const isoInput = (value: string) => `${value}:00+05:30`

export function WorkflowControls({
  workspace,
  busy,
  request,
}: {
  workspace: Workspace | null
  busy: boolean
  request: RequestWorkspace
}) {
  const [cutoff, setCutoff] = useState('')
  useEffect(() => {
    setCutoff(workspace?.cutoff.slice(0, 16) ?? '')
  }, [workspace?.cutoff])
  const replay = workspace?.replay
  return (
    <section className="workflow-controls panel" aria-labelledby="workflow-heading">
      <div className="workflow-heading">
        <div>
          <h2 id="workflow-heading">Investigation workspace</h2>
          <p>
            {workspace?.scope === 'replay'
              ? 'Guided replay · simulated, isolated from uploads'
              : workspace?.scope === 'demo'
                ? 'Quick sample · simulated, isolated from uploads'
                : isHosted
                  ? 'Uploaded readings · private temporary session'
                  : 'Uploaded readings · saved on this computer'}
          </p>
        </div>
        <div className="workflow-actions">
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => void request('/api/workspace?scope=uploads')}
          >
            View saved uploads
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => void request('/api/replay/start', {})}
          >
            Start / resume guided replay
          </button>
        </div>
      </div>
      {workspace && (
        <form
          className="cutoff-form"
          onSubmit={(e) => {
            e.preventDefault()
            void request(
              `/api/workspace?scope=${workspace.scope}&cutoff=${encodeURIComponent(isoInput(cutoff))}`,
            )
          }}
        >
          <label htmlFor="evaluation-cutoff">Evaluate as of (Asia/Kolkata)</label>
          <input
            id="evaluation-cutoff"
            type="datetime-local"
            required
            value={cutoff}
            onChange={(e) => setCutoff(e.target.value)}
          />
          <button className="button secondary" disabled={busy}>
            Apply cutoff
          </button>
          <button
            className="text-button"
            type="button"
            disabled={busy}
            onClick={() => void request(`/api/workspace?scope=${workspace.scope}`)}
          >
            Latest available
          </button>
          <p>
            Only completed hourly intervals are available. This is a historical overnight check, not
            intrahour or real-time detection.
          </p>
        </form>
      )}
      {replay && (
        <div className="replay-stage">
          <div>
            <strong>
              Stage {replay.stage + 1} of {replay.stage_count}: {replay.label}
            </strong>
            <p>
              Simulation cutoff: {stamp(workspace!.cutoff)}. Advancing runs the real detector and
              incident workflow.
            </p>
          </div>
          <div className="workflow-actions">
            <button
              className="button primary"
              disabled={busy || replay.stage === 4}
              onClick={() => void request('/api/replay/advance', { expected_stage: replay.stage })}
            >
              Advance replay
            </button>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => void request('/api/replay/reset', {})}
            >
              Reset replay only
            </button>
          </div>
        </div>
      )}
      {workspace && workspace.analysis.reading_count === 0 && (
        <p className="quality-note">
          No completed readings are available in this workspace at the selected cutoff. Upload a
          CSV, choose a later cutoff, or start the simulated replay.
        </p>
      )}
    </section>
  )
}

function IncidentCard({
  incident,
  workspace,
  busy,
  request,
}: {
  incident: Incident
  workspace: Workspace
  busy: boolean
  request: RequestWorkspace
}) {
  const [note, setNote] = useState('')
  const [repair, setRepair] = useState(workspace.cutoff.slice(0, 16))
  useEffect(() => setRepair(workspace.cutoff.slice(0, 16)), [workspace.cutoff])
  const verification = incident.verification
  async function record(status?: 'Investigating' | 'Repaired') {
    const success = await request(`/api/incidents/${incident.id}/events`, {
      scope: workspace.scope,
      cutoff: workspace.cutoff,
      note,
      status,
      repair_time: status === 'Repaired' ? isoInput(repair) : undefined,
    })
    if (success) setNote('')
  }
  return (
    <article className="incident-card" aria-label={`Incident ${incident.id.slice(0, 8)}`}>
      <div className="workflow-heading">
        <h3>
          Incident {incident.id.slice(0, 8)} · {incident.building_id}
        </h3>
        <strong className="status-pill">{incident.status}</strong>
      </div>
      <p>
        Created at evaluation time: {stamp(incident.created_at)}
        <br />
        First observed anomaly: {stamp(incident.start)}
      </p>
      {incident.repair_time && (
        <p>
          <strong>Repair recorded: {stamp(incident.repair_time)}</strong>. Repaired is a
          user-recorded status, not evidence of reduced consumption.
        </p>
      )}
      <label htmlFor={`note-${incident.id}`}>Maintenance note</label>
      <textarea
        id={`note-${incident.id}`}
        maxLength={2000}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="What did you check or change?"
        rows={2}
      />
      {incident.status === 'Investigating' && (
        <div className="repair-input">
          <label htmlFor={`repair-${incident.id}`}>Repair time (Asia/Kolkata)</label>
          <input
            id={`repair-${incident.id}`}
            type="datetime-local"
            value={repair}
            max={workspace.cutoff.slice(0, 16)}
            onChange={(e) => setRepair(e.target.value)}
          />
        </div>
      )}
      <div className="workflow-actions">
        <button
          className="button secondary"
          disabled={busy || !note.trim()}
          onClick={() => void record()}
        >
          Save note
        </button>
        {incident.status === 'Open' && (
          <button
            className="button primary"
            disabled={busy}
            onClick={() => void record('Investigating')}
          >
            Start investigation
          </button>
        )}
        {incident.status === 'Investigating' && (
          <button
            className="button primary"
            disabled={busy || !repair}
            onClick={() => void record('Repaired')}
          >
            Record repair
          </button>
        )}
      </div>
      {verification && (
        <section className="verification" aria-label="Repair verification">
          <h3>Estimated consumption reduction against baseline</h3>
          <p>
            <strong>{verification.status}</strong>
            {verification.status === 'Awaiting data'
              ? ' — need 18 matched hours across 3 complete post-repair nights and at least 7 clean historical samples per hour.'
              : ' — measured comparison, not proven water savings.'}
          </p>
          <div className="alert-metrics">
            <div>
              <span>Observed in matched hours</span>
              <strong>
                {verification.observed_liters === null ? '—' : number(verification.observed_liters)}{' '}
                <small>L</small>
              </strong>
            </div>
            <div>
              <span>Expected baseline in matched hours</span>
              <strong>
                {verification.expected_liters === null ? '—' : number(verification.expected_liters)}{' '}
                <small>L</small>
              </strong>
            </div>
            <div>
              <span>Baseline minus observed</span>
              <strong>
                {verification.difference_liters === null
                  ? 'Awaiting data'
                  : `${number(verification.difference_liters)} L`}
              </strong>
            </div>
          </div>
          {verification.status === 'Compared' && (
            <p>
              {verification.difference_liters! > 0
                ? 'Consumption was lower than baseline.'
                : verification.difference_liters! < 0
                  ? 'Consumption increased; the data does not support a reduction.'
                  : 'No change against baseline.'}{' '}
              Percentage difference:{' '}
              {verification.percentage_difference === null
                ? 'not defined because baseline is zero'
                : `${number(verification.percentage_difference)}%`}
              . Positive values mean a reduction; negative values mean an increase.
            </p>
          )}
          <p>
            <strong>
              Coverage: {verification.matched_hours}/{verification.target_hours} matched hours (
              {number(verification.coverage_percent)}%).
            </strong>{' '}
            {verification.observed_hours} readings available; {verification.missing_hours} elapsed
            hours missing; {verification.pending_hours} hours not yet elapsed.{' '}
            {verification.incident_excluded_hours} observed hours excluded by known incidents;{' '}
            {verification.unsupported_history_hours} other observed hours lack a supported baseline.
          </p>
          <p>
            Comparison window: {stamp(verification.window_start)} to{' '}
            {stamp(verification.window_end)} (end exclusive), overnight hours 00:00–06:00 only.
            <br />
            Reference window: {stamp(verification.reference_start)} to{' '}
            {stamp(verification.reference_end)} (end exclusive).
          </p>
          <details>
            <summary>Baseline method and coverage details</summary>
            <p>{verification.method}</p>
            <p>
              {verification.excluded_reference_hours} known incident hours excluded from reference
              data. Clean prior samples by hour:{' '}
              {Object.entries(verification.baseline_samples)
                .map(([hour, count]) => `${hour.padStart(2, '0')}:00 — ${count}`)
                .join('; ')}
              .
            </p>
          </details>
        </section>
      )}
      <details className="event-history" open>
        <summary>Event history ({incident.events.length})</summary>
        <ol>
          {incident.events.map((event) => (
            <li key={event.id}>
              <strong>{event.kind}</strong> · {stamp(event.effective_at)}
              {event.note && <p>{event.note}</p>}
              <small>Recorded in app: {stamp(event.recorded_at)}</small>
            </li>
          ))}
        </ol>
      </details>
    </article>
  )
}

export function IncidentPanel({
  workspace,
  building,
  busy,
  request,
}: {
  workspace: Workspace
  building: Building
  busy: boolean
  request: RequestWorkspace
}) {
  const incidents = workspace.incidents.filter((i) => i.building_id === building.building_id)
  return (
    <section className="incident-panel panel" aria-labelledby="incidents-heading">
      <h2 id="incidents-heading">Investigation & repair</h2>
      <p>Track what was checked, record a repair, and compare the outcome separately.</p>
      {building.alerts.map((alert) => (
        <div className="incident-alert-action" key={alert.start}>
          <span>
            Possible water loss · {stamp(alert.start)}–{time(alert.end)} IST
          </span>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() =>
              void request('/api/incidents', {
                scope: workspace.scope,
                building_id: building.building_id,
                alert_start: alert.start,
                cutoff: workspace.cutoff,
              })
            }
          >
            Create incident from alert
          </button>
        </div>
      ))}
      {incidents.length === 0 && (
        <p className="quality-note">
          No incidents for this building at this cutoff. A qualifying alert can start an
          investigation.
        </p>
      )}
      {incidents.map((incident) => (
        <IncidentCard
          key={incident.id}
          incident={incident}
          workspace={workspace}
          busy={busy}
          request={request}
        />
      ))}
      <p className="workflow-footnote">
        Repeated alerts link to an ongoing episode. After repair, a new incident requires a later
        complete overnight check with no sustained pattern before the new alert.
      </p>
    </section>
  )
}
