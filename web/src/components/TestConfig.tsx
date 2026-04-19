/**
 * TestConfig — Test configuration panel (mode, duration, options).
 */
import { useState, useEffect, useRef } from 'react'
import { Settings, FolderOpen, ChevronDown, ChevronRight } from 'lucide-react'
import type { ClientMessage, DAQStatus } from '@/lib/types'

interface TestConfigProps {
  send?: (msg: ClientMessage) => void
  daq?: DAQStatus
  onConfigChange?: (config: {
    mode: string
    durationSeconds: number
    playbackCsv: string
    playbackType: string
    config: object
  }) => void
  playbackCsvInfo?: { path: string; filename: string; frames: number } | null
}

export function TestConfig({
  onConfigChange, send, daq, playbackCsvInfo,
}: TestConfigProps) {
  const [mode, setMode] = useState<'ibit' | 'playback'>('ibit')
  const [durationValue, setDurationValue] = useState(14)
  const [durationUnit, setDurationUnit] = useState('Days')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [skipStateManagement, setSkipStateManagement] = useState(false)
  // playbackCsvPath is the SERVER-side path the backend will read from.
  // Populated by the file picker after uploading the file (or typed
  // manually into the text input for servers with the file already on disk).
  const [playbackCsvPath, setPlaybackCsvPath] = useState('')
  const [playbackType, setPlaybackType] = useState('Both')
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Advanced config
  const [ibitTimeout, setIbitTimeout] = useState(300)
  const [phaseTimeout, setPhaseTimeout] = useState(90)
  const [armTimeout, setArmTimeout] = useState(60)
  const [maxArmIterations, setMaxArmIterations] = useState(20)
  const [stabilizationDelay, setStabilizationDelay] = useState(2)
  const [connectionTimeout, setConnectionTimeout] = useState(10)

  // When the backend confirms a file upload, adopt its server-side path.
  useEffect(() => {
    if (playbackCsvInfo?.path && playbackCsvInfo.path !== playbackCsvPath) {
      setPlaybackCsvPath(playbackCsvInfo.path)
      setUploading(false)
    }
  }, [playbackCsvInfo, playbackCsvPath])

  useEffect(() => {
    const durationSeconds = durationValue * ({
      Seconds: 1, Minutes: 60, Hours: 3600, Days: 86400,
    } as Record<string, number>)[durationUnit]!
    onConfigChange?.({
      mode,
      durationSeconds,
      playbackCsv: playbackCsvPath,
      playbackType,
      config: {
        ibit_timeout: ibitTimeout,
        phase_timeout: phaseTimeout,
        arm_timeout: armTimeout,
        max_arm_iterations: maxArmIterations,
        skip_arm_for_ibit: skipStateManagement,
      },
    })
  }, [
    mode, durationValue, durationUnit,
    playbackCsvPath, playbackType,
    ibitTimeout, phaseTimeout, armTimeout, maxArmIterations,
    skipStateManagement, onConfigChange,
  ])

  // ── File picker handler ─────────────────────────────────────────────
  // Opens a native file dialog, reads the selected CSV contents, and
  // uploads them to the backend which writes to a temp path under
  // logs/uploaded_*.csv. The server broadcasts playback.csv_uploaded
  // which updates playbackCsvInfo above, which sets playbackCsvPath.
  const handleFilePick = () => {
    fileInputRef.current?.click()
  }

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !send) return

    if (!file.name.toLowerCase().endsWith('.csv')) {
      alert('Please select a .csv file')
      return
    }

    // Reasonable size cap to avoid blocking the UI on multi-MB files.
    // Real Roadrunner flight profiles are 2-5 MB; cap at 50 MB.
    if (file.size > 50 * 1024 * 1024) {
      alert(`File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Max 50 MB.`)
      return
    }

    setUploading(true)
    try {
      const contents = await file.text()
      send({
        type: 'cmd.upload_playback_csv',
        data: { filename: file.name, contents },
      })
      // Show the filename immediately so the user sees it was accepted.
      // The real server-side path will replace this when the backend
      // confirms via playback.csv_uploaded.
      setPlaybackCsvPath(file.name)
    } catch (err) {
      setUploading(false)
      alert(`Failed to read file: ${err}`)
    }
    // Reset the input so selecting the same file again fires onChange.
    e.target.value = ''
  }

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

          {/* Hidden native file input — triggered by the folder button */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            onChange={handleFileSelected}
            style={{ display: 'none' }}
          />

          <div className="flex items-center gap-2">
            <span className="text-text-secondary text-xs">CSV:</span>
            <input
              type="text"
              value={playbackCsvPath}
              onChange={(e) => setPlaybackCsvPath(e.target.value)}
              placeholder="Select flight profile..."
              className="flex-1 bg-bg-elevated border border-border rounded px-2 py-1
                         text-xs font-mono text-text-primary placeholder:text-text-disabled
                         focus:border-border-focus outline-none"
            />
            <button
              onClick={handleFilePick}
              disabled={uploading}
              title="Browse for flight profile CSV"
              className="btn-neutral text-xs py-1 px-2 disabled:opacity-50
                         disabled:cursor-not-allowed"
            >
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

          {/* Status line: upload progress / loaded info / empty */}
          {uploading ? (
            <p className="text-amber text-[10px] italic">
              Uploading to backend...
            </p>
          ) : playbackCsvInfo && playbackCsvInfo.path === playbackCsvPath ? (
            <p className="text-green text-[10px]">
              ✓ Loaded {playbackCsvInfo.frames.toLocaleString()} frames from{' '}
              <span className="font-mono">{playbackCsvInfo.filename}</span>
            </p>
          ) : !playbackCsvPath ? (
            <p className="text-text-disabled text-[10px] italic">
              Click the folder icon to browse, or paste an absolute server-side path
            </p>
          ) : (
            <p className="text-text-disabled text-[10px] italic">
              Path: <span className="font-mono">{playbackCsvPath}</span>
            </p>
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

          {/* Simulation — hidden in Advanced for dev/test use only */}
          {send && (
            <div className="pt-2 mt-2 border-t border-border">
              <button
                className="text-[10px] text-text-disabled hover:text-text-secondary
                           transition-colors bg-transparent cursor-pointer
                           disabled:opacity-30 disabled:cursor-not-allowed w-full text-left"
                onClick={() => send({ type: 'cmd.launch_sitl' })}
                disabled={daq?.sitl_active}
              >
                {daq?.sitl_active ? '● Simulation active' : '○ Launch simulation (no hardware needed)'}
              </button>
            </div>
          )}
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
