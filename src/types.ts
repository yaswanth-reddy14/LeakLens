export type Point = {
  timestamp: string
  hour: number
  liters: number | null
  baseline: number | null
  threshold: number | null
  history_count: number
  unusual: boolean
}
export type Alert = {
  title: string
  start: string
  end: string
  duration_hours: number
  observed_liters: number
  baseline_liters: number
  threshold_liters: number
  hours: Point[]
}
export type Building = {
  building_id: string
  reading_count: number
  status: 'possible_loss' | 'no_pattern' | 'insufficient_history' | 'incomplete_data'
  evaluation_start: string
  evaluation_end: string
  missing_hours: number
  insufficient_history_hours: number
  overnight_liters: number
  baseline_liters: number | null
  points: Point[]
  alerts: Alert[]
}
export type Analysis = {
  source: 'simulated' | 'upload'
  timezone: string
  reading_count: number
  building_count: number
  period_start: string | null
  period_end: string | null
  buildings: Building[]
}

export type Scope = 'uploads' | 'demo' | 'replay'
export type Verification = {
  status: 'Compared' | 'Awaiting data'
  window_start: string
  window_end: string
  reference_start: string
  reference_end: string
  target_hours: number
  elapsed_hours: number
  observed_hours: number
  matched_hours: number
  missing_hours: number
  pending_hours: number
  incident_excluded_hours: number
  unsupported_history_hours: number
  coverage_percent: number
  baseline_samples: Record<string, number>
  excluded_reference_hours: number
  observed_liters: number | null
  expected_liters: number | null
  difference_liters: number | null
  percentage_difference: number | null
  method: string
}
export type Incident = {
  id: string
  building_id: string
  status: 'Open' | 'Investigating' | 'Repaired'
  start: string
  created_at: string
  repair_time: string | null
  notes: string[]
  events: {
    id: string
    kind: string
    status: string
    effective_at: string
    recorded_at: string
    note: string
  }[]
  verification: Verification | null
}
export type Workspace = {
  scope: Scope
  cutoff: string
  analysis: Analysis
  incidents: Incident[]
  message?: string
  replay?: { stage: number; label: string; stage_count: number }
}
