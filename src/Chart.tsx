import { useState } from 'react'
import type { Point } from './types'
import { number, time } from './format'

export default function Chart({ points }: { points: Point[] }) {
  const [active, setActive] = useState<number | null>(null)
  const width = 900,
    height = 280,
    left = 58,
    right = 20,
    top = 25,
    bottom = 40
  const peak = Math.max(
    100,
    ...points.flatMap((p) => [p.liters ?? 0, p.baseline ?? 0, p.threshold ?? 0]),
  )
  const max = Math.ceil(peak / 100) * 100
  const x = (hour: number) => left + (hour / 24) * (width - left - right)
  const y = (value: number) => height - bottom - (value / max) * (height - top - bottom)
  const path = (field: 'liters' | 'baseline' | 'threshold') => {
    let previous = false
    return points
      .map((p) => {
        const value = p[field]
        if (value === null) {
          previous = false
          return ''
        }
        const command = previous ? 'L' : 'M'
        previous = true
        return `${command}${x(p.hour + 0.5)},${y(value)}`
      })
      .join(' ')
  }
  const selected = active === null ? null : points[active]
  return (
    <>
      <div className="chart-wrap" tabIndex={0} role="region" aria-label="Hourly consumption chart">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="chart-title chart-desc">
          <title id="chart-title">Hourly water consumption in liters</title>
          <desc id="chart-desc">
            Solid green is observed consumption, dashed grey is the historical median, and dotted
            orange is the overnight threshold. Missing readings have gaps. Exact values are
            available in the table below.
          </desc>
          <rect
            x={x(0)}
            y={top}
            width={x(6) - x(0)}
            height={height - bottom - top}
            fill="#f6eddc"
            rx="6"
          />
          <text x={x(0) + 10} y={top + 17} className="night-label">
            OVERNIGHT CHECK
          </text>
          {[0, 1, 2, 3, 4].map((i) => (
            <g key={i}>
              <line
                x1={left}
                x2={width - right}
                y1={y((max * i) / 4)}
                y2={y((max * i) / 4)}
                stroke="#e4e9e5"
              />
              <text x={left - 12} y={y((max * i) / 4) + 4} textAnchor="end">
                {number((max * i) / 4)}
              </text>
            </g>
          ))}
          <text x="12" y="14">
            Liters
          </text>
          {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
            <text key={h} x={x(h)} y={height - 14} textAnchor="middle">
              {String(h).padStart(2, '0')}:00
            </text>
          ))}
          <path
            d={path('baseline')}
            fill="none"
            stroke="#8c9693"
            strokeWidth="2"
            strokeDasharray="6 5"
          />
          <path
            d={path('threshold')}
            fill="none"
            stroke="#a45a16"
            strokeWidth="2"
            strokeDasharray="2 5"
          />
          <path
            d={path('liters')}
            fill="none"
            stroke="#237560"
            strokeWidth="3"
            strokeLinejoin="round"
          />
          {points.map(
            (p, i) =>
              p.liters !== null && (
                <circle
                  key={p.hour}
                  cx={x(p.hour + 0.5)}
                  cy={y(p.liters)}
                  r={p.unusual ? 5 : 3.5}
                  fill={p.unusual ? '#b96723' : '#237560'}
                  stroke="white"
                  strokeWidth="1.5"
                  onMouseEnter={() => setActive(i)}
                  onMouseLeave={() => setActive(null)}
                >
                  <title>
                    {time(p.timestamp)}: {number(p.liters)} L
                  </title>
                </circle>
              ),
          )}
        </svg>
      </div>
      <div className="chart-caption">
        {selected
          ? `${time(selected.timestamp)}–${String(selected.hour + 1).padStart(2, '0')}:00 · ${number(selected.liters!)} L observed · ${selected.baseline === null ? 'Baseline unavailable' : `${number(selected.baseline)} L baseline`}`
          : 'Each point represents one hour of consumption. Gaps mean missing readings.'}
      </div>
      <details className="data-table">
        <summary>View hourly readings and baseline</summary>
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Hourly readings table">
          <table>
            <caption>Hour beginning in Asia/Kolkata · all consumption values in liters</caption>
            <thead>
              <tr>
                <th scope="col">Hour</th>
                <th scope="col">Observed (L)</th>
                <th scope="col">Baseline (L)</th>
                <th scope="col">Threshold (L)</th>
                <th scope="col">Prior samples</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.hour}>
                  <th scope="row">{time(p.timestamp)}</th>
                  <td>{p.liters === null ? 'Missing' : number(p.liters)}</td>
                  <td>{p.baseline === null ? 'Insufficient history' : number(p.baseline)}</td>
                  <td>
                    {p.hour >= 6
                      ? 'Not evaluated'
                      : p.threshold === null
                        ? 'Unavailable'
                        : number(p.threshold)}
                  </td>
                  <td>{p.history_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  )
}
