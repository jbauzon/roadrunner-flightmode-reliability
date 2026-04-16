import { formatDuration, formatDurationLong } from '@/lib/utils'
import type { BatchStatus, TestStatistics } from '@/lib/types'

interface BatchProgressProps {
  batch: BatchStatus
  statistics: TestStatistics | null
}

export function BatchProgress({ batch, statistics }: BatchProgressProps) {
  const progressPct = batch.remaining_seconds > 0
    ? Math.min(100, (batch.elapsed_seconds / (batch.elapsed_seconds + batch.remaining_seconds)) * 100)
    : 0

  return (
    <div className="card space-y-3">
      <h3 className="section-title">Batch Progress</h3>

      {/* Current UUT */}
      <div className="flex items-center justify-between text-sm">
        <span className="text-text-secondary">Testing:</span>
        <span className="font-mono">
          {batch.current_uut_serial
            ? `UUT ${batch.current_uut_index + 1}/${batch.total_uuts} — ${batch.current_uut_serial}`
            : '---'}
        </span>
      </div>

      {/* Progress bar */}
      {batch.active && (
        <div className="space-y-1">
          <div className="h-1.5 bg-bg-elevated rounded-full overflow-hidden">
            <div
              className="h-full bg-blue rounded-full transition-all duration-1000 ease-linear"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-text-disabled font-mono">
            <span>{progressPct.toFixed(0)}%</span>
            <span>{formatDurationLong(batch.remaining_seconds)} remaining</span>
          </div>
        </div>
      )}

      {/* Timers */}
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-text-secondary">Elapsed:</span>
          <span className="font-mono">{formatDuration(batch.elapsed_seconds)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-text-secondary">Remaining:</span>
          <span className="font-mono">{formatDuration(batch.remaining_seconds)}</span>
        </div>
      </div>

      {/* Statistics */}
      {statistics && (
        <div className="grid grid-cols-4 gap-2 pt-2 border-t border-border">
          <StatBox label="Iterations" value={statistics.total_iterations} />
          <StatBox label="Passes" value={statistics.total_passes} color="text-green" />
          <StatBox label="Fails" value={statistics.total_fails} color="text-red" />
          <StatBox
            label="Pass Rate"
            value={`${(statistics.pass_rate * 100).toFixed(0)}%`}
            color={statistics.pass_rate >= 0.9 ? 'text-green' : 'text-amber'}
          />
        </div>
      )}
    </div>
  )
}

function StatBox({
  label,
  value,
  color,
}: {
  label: string
  value: number | string
  color?: string
}) {
  return (
    <div className="text-center">
      <div className={`font-mono text-lg font-bold ${color ?? 'text-text-primary'}`}>
        {value}
      </div>
      <div className="text-[10px] text-text-disabled uppercase tracking-wider">{label}</div>
    </div>
  )
}
