import { motion, AnimatePresence } from 'framer-motion'
import { cn, formatDuration } from '@/lib/utils'
import { Timer, CheckCircle2 } from 'lucide-react'

interface IBITDisplayProps {
  substate: string
  mistrackingFlags: number
  durationSeconds: number
}

const IBIT_PHASES = ['BEGIN', 'WAIT_FOR_SETTLE', 'ELEVONS', 'RUDDERS', 'TVC'] as const
const PHASE_LABELS = ['BEGIN', 'SETTLE', 'ELEVONS', 'RUDDERS', 'TVC']

const STATE_STYLES: Record<string, { bg: string; text: string; border: string; glow: string }> = {
  'IDLE':             { bg: 'bg-white/5',    text: 'text-text-disabled', border: 'border-white/5',   glow: '' },
  'BEGIN':            { bg: 'bg-blue/10',    text: 'text-blue',          border: 'border-blue/30',   glow: 'shadow-[0_0_20px_rgba(88,166,255,0.15)]' },
  'WAIT_FOR_SETTLE':  { bg: 'bg-amber/10',   text: 'text-amber',         border: 'border-amber/30',  glow: 'shadow-[0_0_20px_rgba(210,153,34,0.15)]' },
  'ELEVONS':          { bg: 'bg-amber/10',   text: 'text-amber',         border: 'border-amber/30',  glow: 'shadow-[0_0_20px_rgba(210,153,34,0.15)]' },
  'RUDDERS':          { bg: 'bg-amber/10',   text: 'text-amber',         border: 'border-amber/30',  glow: 'shadow-[0_0_20px_rgba(210,153,34,0.15)]' },
  'TVC':              { bg: 'bg-amber/10',   text: 'text-amber',         border: 'border-amber/30',  glow: 'shadow-[0_0_20px_rgba(210,153,34,0.15)]' },
  '\u2713 COMPLETE':  { bg: 'bg-green/10',   text: 'text-green',          border: 'border-green/30',  glow: 'shadow-[0_0_30px_rgba(63,185,80,0.2)]' },
  '\u2713 PASS':      { bg: 'bg-green/10',   text: 'text-green',          border: 'border-green/30',  glow: 'shadow-[0_0_30px_rgba(63,185,80,0.2)]' },
  '\u2717 FAIL':      { bg: 'bg-red/10',     text: 'text-red',            border: 'border-red/30',    glow: 'shadow-[0_0_30px_rgba(248,81,73,0.2)]' },
  'CONNECTING':       { bg: 'bg-blue/10',    text: 'text-blue',          border: 'border-blue/30',   glow: 'shadow-[0_0_20px_rgba(88,166,255,0.15)]' },
  'ARMING':           { bg: 'bg-amber/10',   text: 'text-amber',         border: 'border-amber/30',  glow: 'shadow-[0_0_20px_rgba(210,153,34,0.15)]' },
  'ENTERING IBIT':    { bg: 'bg-amber/10',   text: 'text-amber',         border: 'border-amber/30',  glow: 'shadow-[0_0_20px_rgba(210,153,34,0.15)]' },
}

const PHASE_MAP: Record<string, number> = {
  'BEGIN': 0, 'WAIT_FOR_SETTLE': 1, 'ELEVONS': 2, 'RUDDERS': 3, 'TVC': 4,
}

export function IBITDisplay({ substate, mistrackingFlags: _mf, durationSeconds }: IBITDisplayProps) {
  const style = STATE_STYLES[substate] ?? STATE_STYLES['IDLE']
  const currentPhaseIdx = PHASE_MAP[substate] ?? -1
  const isComplete = substate.includes('COMPLETE') || substate.includes('PASS')

  return (
    <div className="card space-y-4">
      <h3 className="section-title flex items-center gap-2">
        <div className="w-1 h-3.5 rounded-full bg-amber" />
        Test Status
      </h3>

      {/* Primary state badge — the hero element */}
      <AnimatePresence mode="wait">
        <motion.div
          key={substate}
          initial={{ opacity: 0, scale: 0.92 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 1.05 }}
          transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
          className={cn(
            'flex items-center justify-center h-14 rounded-xl',
            'font-mono text-xl font-extrabold tracking-[3px]',
            'border transition-all duration-500',
            style.bg, style.text, style.border, style.glow
          )}
        >
          {isComplete && <CheckCircle2 className="w-5 h-5 mr-2" />}
          {substate}
        </motion.div>
      </AnimatePresence>

      {/* Phase stepper */}
      <div className="flex items-center gap-0 px-2">
        {IBIT_PHASES.map((phase, i) => {
          let dotState: 'done' | 'active' | 'pending' = 'pending'
          if (isComplete || i < currentPhaseIdx) dotState = 'done'
          else if (i === currentPhaseIdx) dotState = 'active'

          return (
            <div key={phase} className="flex items-center flex-1">
              <div className="flex flex-col items-center flex-1">
                <motion.div
                  animate={{
                    scale: dotState === 'active' ? [1, 1.3, 1] : 1,
                  }}
                  transition={{
                    duration: 1.5,
                    repeat: dotState === 'active' ? Infinity : 0,
                    ease: 'easeInOut',
                  }}
                  className={cn(
                    'w-3.5 h-3.5 rounded-full transition-all duration-500',
                    dotState === 'done' && 'led-green',
                    dotState === 'active' && 'led-amber',
                    dotState === 'pending' && 'bg-white/5 border border-white/10'
                  )}
                  title={phase}
                />
                <span className={cn(
                  'text-[8px] mt-1.5 font-medium tracking-wider',
                  dotState === 'done' ? 'text-green/60' :
                  dotState === 'active' ? 'text-amber' :
                  'text-text-disabled/50'
                )}>
                  {PHASE_LABELS[i]}
                </span>
              </div>
              {i < IBIT_PHASES.length - 1 && (
                <div
                  className={cn(
                    'h-px flex-1 mx-1 transition-all duration-500 rounded-full',
                    (isComplete || i < currentPhaseIdx)
                      ? 'bg-green/40 shadow-[0_0_4px_rgba(63,185,80,0.2)]'
                      : 'bg-white/5'
                  )}
                />
              )}
            </div>
          )
        })}
      </div>

      {/* Duration */}
      <div className="flex items-center gap-2 text-sm">
        <Timer className="w-3.5 h-3.5 text-text-disabled" />
        <span className="text-text-secondary text-xs">Duration:</span>
        <span className="mono-value text-xs">
          {formatDuration(durationSeconds)}
          <span className="text-text-disabled ml-1.5">({durationSeconds.toFixed(1)}s)</span>
        </span>
      </div>
    </div>
  )
}
