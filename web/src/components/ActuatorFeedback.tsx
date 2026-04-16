import { cn } from '@/lib/utils'
import { SURFACES, type ActuatorFeedback as ActuatorData } from '@/lib/types'

interface ActuatorFeedbackProps {
  data: ActuatorData
  mistrackingFlags: number
}

export function ActuatorFeedback({ data, mistrackingFlags }: ActuatorFeedbackProps) {
  return (
    <div className="card space-y-3">
      <h3 className="section-title flex items-center gap-2">
        <div className="w-1 h-3.5 rounded-full bg-blue" />
        Actuator Feedback
      </h3>

      {/* Header */}
      <div className="grid grid-cols-4 gap-1 text-text-disabled/50 text-[9px] font-bold uppercase tracking-[0.12em] pb-1">
        <span>Surface</span>
        <span className="text-center">Pos (&deg;)</span>
        <span className="text-center">Current</span>
        <span className="text-center">Temp</span>
      </div>

      <div className="separator" />

      {/* Rows */}
      <div className="space-y-0.5">
        {SURFACES.map(({ key, display, bit }) => {
          const fb = data[`${key}_feedback_cdeg` as keyof ActuatorData] as number | undefined
          const curr = data[`${key}_current_mA` as keyof ActuatorData] as number | undefined
          const temp = data[`${key}_motor_temp_degC` as keyof ActuatorData] as number | undefined
          const mistracking = (mistrackingFlags & bit) !== 0
          const fbDeg = fb != null ? (fb / 100).toFixed(1) : '---'
          const hasData = fb != null

          return (
            <div
              key={key}
              className={cn(
                'grid grid-cols-4 gap-1 py-1 px-1 rounded-md transition-all duration-300',
                mistracking && 'bg-red/10 border border-red/20',
                !mistracking && hasData && 'hover:bg-white/[0.02]',
              )}
            >
              <span className="text-text-secondary text-[11px] font-medium">{display}</span>
              <span
                className={cn(
                  'font-mono text-[11px] text-center transition-colors duration-300',
                  mistracking ? 'text-red font-bold' :
                  hasData ? 'text-text-primary' : 'text-text-disabled/40'
                )}
              >
                {fbDeg}
              </span>
              <span className={cn(
                'font-mono text-[11px] text-center',
                hasData ? 'text-text-primary/70' : 'text-text-disabled/40'
              )}>
                {curr != null ? String(curr) : '---'}
              </span>
              <span className={cn(
                'font-mono text-[11px] text-center',
                hasData ? 'text-text-primary/70' : 'text-text-disabled/40'
              )}>
                {temp != null ? String(temp) : '---'}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
