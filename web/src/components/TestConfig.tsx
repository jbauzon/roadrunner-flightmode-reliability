/**
 * TestConfig — Test configuration panel (mode, duration, options).
 */
import { useState, useEffect } from 'react'
import { Settings, FolderOpen, ChevronDown, ChevronRight } from 'lucide-react'
import type { ClientMessage } from '@/lib/types'

interface TestConfigProps {
  send?: (msg: ClientMessage) => void
  onConfigChange?: (config: { mode: string; durationSeconds: number; config: object }) => void
}

export function TestConfig({ onConfigChange }: TestConfigProps) {
  const [mode, setMode] = useState<'ibit' | 'playback'>('ibit')
  const [durationValue, setDurationValue] = useState(14)
  const [durationUnit, setDurationUnit] = useState('Days')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [skipStateManagement, setSkipStateManagement] = useState(false)
  const [playbackCsv, setPlaybackCsv] = useState('')
  const [playbackType, setPlaybackType] = useState('Both')

  // Advanced config
  const [ibitTimeout, setIbitTimeout] = useState(300)
  const [phaseTimeout, setPhaseTimeout] = useState(90)
  const [armTimeout, setArmTimeout] = useState(60)
  const [maxArmIterations, setMaxArmIterations] = useState(20)
  const [stabilizationDelay, setStabilizationDelay] = useState(2)
  const [connectionTimeout, setConnectionTimeout] = useState(10)

  useEffect(() => {
    const durationSeconds = durationValue * ({
      Seconds: 1, Minutes: 60, Hours: 3600, Days: 86400,
    } as Record<string, number>)[durationUnit]!
    onConfigChange?.({
      mode,
      durationSeconds,
      config: {
        ibit_timeout: ibitTimeout,
        phase_timeout: phaseTimeout,
        arm_timeout: armTimeout,
        max_arm_iterations: maxArmIterations,
        skip_arm_for_ibit: skipStateManagement,
      },
    })
  }, [mode, durationValue, durationUnit, ibitTimeout, phaseTimeout, armTimeout, maxArmIterations, skipStateManagement, onConfigChange])

  return (
    <div className="card space-y-3">
      <h3 className="section-title flex items-center gap-2">
        <Settings className="w-3.5 h-3.5" />
        Test Configuration
      </h3>

      {/* Mode toggle */}
      <div>
        <span className="text-text-secondary text-[10px] font-semibold uppercase tracking-wider">
          Test Mode
        </span>
        <div className="flex mt-1.5 bg-bg-base rounded-lg p-0.5 border border-border">
          <button
            onClick={() => setMode('ibit')}
            className={`flex-1 py-1.5 text-xs font-bold tracking-wider rounded transition-all
              ${mode === 'ibit'
                ? 'bg-bg-elevated text-text-primary shadow-sm'
                : 'text-text-disabled hover:text-text-secondary'}`}
          >
            IBIT
          </button>
          <button
            onClick={() => setMode('playback')}
            className={`flex-1 py-1.5 text-xs font-bold tracking-wider rounded transition-all
              ${mode === 'playback'
                ? 'bg-bg-elevated text-text-primary shadow-sm'
                : 'text-text-disabled hover:text-text-secondary'}`}
          >
            Playback
          </button>
        </div>
      </div>

      {/* Playback options (visible when playback mode) */}
      {mode === 'playback' && (
        <div className="space-y-2 p-2.5 bg-bg-base rounded border border-border animate-fade-in">
          <span className="text-text-secondary text-[10px] font-semibold uppercase tracking-wider">
            Playback Options
          </span>

          <div className="flex items-center gap-2">
            <span className="text-text-secondary text-xs">CSV:</span>
            <input
              type="text"
              value={playbackCsv}
              onChange={(e) => setPlaybackCsv(e.target.value)}
              placeholder="Select flight profile..."
              className="flex-1 bg-bg-elevated border border-border rounded px-2 py-1
                         text-xs font-mono text-text-primary placeholder:text-text-disabled
                         focus:border-border-focus outline-none"
            />
            <button className="btn-neutral text-xs py-1 px-2">
              <FolderOpen className="w-3 h-3" />
            </button>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-text-secondary text-xs">Type:</span>
            <select
              value={playbackType}
              onChange={(e) => setPlaybackType(e.target.value)}
              className="flex-1 bg-bg-elevated border border-border rounded px-2 py-1
                         text-xs text-text-primary focus:border-border-focus outline-none"
            >
              <option>Actuation</option>
              <option>TVC</option>
              <option>Both</option>
            </select>
          </div>

          {!playbackCsv && (
            <p className="text-text-disabled text-[10px] italic">No profile loaded</p>
          )}
        </div>
      )}

      {/* Duration */}
      <div>
        <span className="text-text-secondary text-[10px] font-semibold uppercase tracking-wider">
          Duration
        </span>
        <div className="flex gap-2 mt-1.5">
          <input
            type="number"
            value={durationValue}
            onChange={(e) => setDurationValue(Number(e.target.value))}
            min={1}
            className="w-20 bg-bg-elevated border border-border rounded px-2 py-1.5
                       text-sm font-mono text-text-primary focus:border-border-focus outline-none"
          />
          <select
            value={durationUnit}
            onChange={(e) => setDurationUnit(e.target.value)}
            className="flex-1 min-w-0 bg-bg-elevated border border-border rounded px-2 py-1.5
                       text-sm text-text-primary focus:border-border-focus outline-none"
          >
            <option>Seconds</option>
            <option>Minutes</option>
            <option>Hours</option>
            <option>Days</option>
          </select>
        </div>
      </div>

      {/* Options */}
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={skipStateManagement}
          onChange={(e) => setSkipStateManagement(e.target.checked)}
          className="w-3.5 h-3.5 rounded border-border bg-bg-elevated
                     checked:bg-blue checked:border-blue accent-blue"
        />
        <span className="text-xs text-text-secondary">
          Skip State Management (faster, less safe)
        </span>
      </label>

      {/* Advanced settings (collapsible) */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="flex items-center gap-1 text-text-disabled text-[10px] font-semibold
                   uppercase tracking-wider hover:text-text-secondary transition-colors w-full"
      >
        {showAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        Advanced
      </button>

      {showAdvanced && (
        <div className="space-y-2 p-2.5 bg-bg-base rounded border border-border animate-fade-in">
          <ConfigRow label="IBIT Timeout" value={ibitTimeout} onChange={setIbitTimeout} suffix="s" />
          <ConfigRow label="Phase Timeout" value={phaseTimeout} onChange={setPhaseTimeout} suffix="s" />
          <ConfigRow label="ARM Timeout" value={armTimeout} onChange={setArmTimeout} suffix="s" />
          <ConfigRow label="Max ARM Iterations" value={maxArmIterations} onChange={setMaxArmIterations} />
          <ConfigRow label="Stabilization Delay" value={stabilizationDelay} onChange={setStabilizationDelay} suffix="s" />
          <ConfigRow label="Connection Timeout" value={connectionTimeout} onChange={setConnectionTimeout} suffix="s" />
        </div>
      )}
    </div>
  )
}

function ConfigRow({
  label,
  value,
  onChange,
  suffix,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  suffix?: string
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-text-secondary text-[10px]">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-16 bg-bg-elevated border border-border rounded px-1.5 py-0.5
                     text-xs font-mono text-text-primary text-right
                     focus:border-border-focus outline-none"
        />
        {suffix && <span className="text-text-disabled text-[10px]">{suffix}</span>}
      </div>
    </div>
  )
}
