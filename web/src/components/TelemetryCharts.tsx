/**
 * TelemetryCharts — Real-time sparkline charts for actuator positions,
 * battery, and engine telemetry.
 */

import { useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, ResponsiveContainer,
  Tooltip, CartesianGrid, AreaChart, Area,
} from 'recharts'

// ── Color palette for 8 surfaces ────────────────────────────────────────────
const SURFACE_COLORS: Record<string, string> = {
  left_elevon:     '#58A6FF',
  right_elevon:    '#3FB950',
  dorsal_rudder:   '#D29922',
  ventral_rudder:  '#BC8CFF',
  left_tvc_upper:  '#F85149',
  left_tvc_lower:  '#E3B341',
  right_tvc_upper: '#39D353',
  right_tvc_lower: '#8B949E',
}

const SURFACE_LABELS: Record<string, string> = {
  left_elevon:     'L Elev',
  right_elevon:    'R Elev',
  dorsal_rudder:   'Dors',
  ventral_rudder:  'Vent',
  left_tvc_upper:  'LTU',
  left_tvc_lower:  'LTL',
  right_tvc_upper: 'RTU',
  right_tvc_lower: 'RTL',
}

// ---------------------------------------------------------------------------
// Actuator Position Chart
// ---------------------------------------------------------------------------

interface ActuatorChartProps {
  data: Array<Record<string, number>>
}

export function ActuatorPositionChart({ data }: ActuatorChartProps) {
  const surfaces = useMemo(() => Object.keys(SURFACE_COLORS), [])

  if (data.length < 2) {
    return (
      <div className="card">
        <h3 className="section-title mb-2">Actuator Positions</h3>
        <div className="h-32 flex items-center justify-center text-text-disabled text-xs">
          Waiting for telemetry data...
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <h3 className="section-title mb-2">Actuator Positions (&deg;)</h3>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#21262D"
              vertical={false}
            />
            <XAxis
              dataKey="t"
              tick={{ fontSize: 9, fill: '#484F58' }}
              tickFormatter={(v: number) => `${Math.floor(v)}s`}
              stroke="#30363D"
            />
            <YAxis
              tick={{ fontSize: 9, fill: '#484F58' }}
              stroke="#30363D"
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#161B22',
                border: '1px solid #30363D',
                borderRadius: 6,
                fontSize: 11,
                fontFamily: 'JetBrains Mono, monospace',
              }}
              labelFormatter={(v: number) => `${v.toFixed(1)}s`}
              formatter={(value: number, name: string) => [
                `${value.toFixed(1)}°`,
                SURFACE_LABELS[name] ?? name,
              ]}
            />
            {surfaces.map((key) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={SURFACE_COLORS[key]}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {/* Legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1">
        {surfaces.map((key) => (
          <span key={key} className="flex items-center gap-1 text-[9px]">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ backgroundColor: SURFACE_COLORS[key] }}
            />
            <span className="text-text-secondary">{SURFACE_LABELS[key]}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Battery Chart
// ---------------------------------------------------------------------------

interface BatteryChartProps {
  data: Array<{ t: number; voltage: number; current: number; soc: number }>
}

export function BatteryChart({ data }: BatteryChartProps) {
  if (data.length < 2) {
    return (
      <div className="card">
        <h3 className="section-title mb-2">Battery</h3>
        <div className="h-24 flex items-center justify-center text-text-disabled text-xs">
          Waiting for battery data...
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <h3 className="section-title">Battery</h3>
        {data.length > 0 && (
          <div className="flex gap-3 text-xs font-mono">
            <span className="text-green">{data[data.length - 1].voltage.toFixed(1)}V</span>
            <span className="text-amber">{data[data.length - 1].current.toFixed(1)}A</span>
            <span className="text-blue">{data[data.length - 1].soc}%</span>
          </div>
        )}
      </div>
      <div className="h-24">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#21262D" vertical={false} />
            <XAxis
              dataKey="t"
              tick={{ fontSize: 9, fill: '#484F58' }}
              tickFormatter={(v: number) => `${Math.floor(v)}s`}
              stroke="#30363D"
            />
            <YAxis tick={{ fontSize: 9, fill: '#484F58' }} stroke="#30363D" />
            <Tooltip
              contentStyle={{
                backgroundColor: '#161B22',
                border: '1px solid #30363D',
                borderRadius: 6,
                fontSize: 11,
                fontFamily: 'JetBrains Mono, monospace',
              }}
            />
            <Area
              type="monotone"
              dataKey="voltage"
              stroke="#3FB950"
              fill="#1A3D22"
              strokeWidth={1.5}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="current"
              stroke="#D29922"
              fill="#3D2F0A"
              strokeWidth={1.5}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Engine Chart
// ---------------------------------------------------------------------------

interface EngineChartProps {
  data: Array<{ t: number; rpm: number; egt: number; fuelPump: number }>
}

export function EngineChart({ data }: EngineChartProps) {
  if (data.length < 2) {
    return (
      <div className="card">
        <h3 className="section-title mb-2">Engine</h3>
        <div className="h-24 flex items-center justify-center text-text-disabled text-xs">
          Waiting for engine data...
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <h3 className="section-title">Engine</h3>
        {data.length > 0 && (
          <div className="flex gap-3 text-xs font-mono">
            <span className="text-orange">{data[data.length - 1].rpm.toLocaleString()} RPM</span>
            <span className="text-red">{data[data.length - 1].egt}&deg;C</span>
          </div>
        )}
      </div>
      <div className="h-24">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#21262D" vertical={false} />
            <XAxis
              dataKey="t"
              tick={{ fontSize: 9, fill: '#484F58' }}
              tickFormatter={(v: number) => `${Math.floor(v)}s`}
              stroke="#30363D"
            />
            <YAxis tick={{ fontSize: 9, fill: '#484F58' }} stroke="#30363D" />
            <Tooltip
              contentStyle={{
                backgroundColor: '#161B22',
                border: '1px solid #30363D',
                borderRadius: 6,
                fontSize: 11,
                fontFamily: 'JetBrains Mono, monospace',
              }}
            />
            <Line
              type="monotone"
              dataKey="rpm"
              stroke="#E3B341"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="egt"
              stroke="#F85149"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
