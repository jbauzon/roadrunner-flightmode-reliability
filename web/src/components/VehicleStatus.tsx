import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/lib/utils'
import { ACTUATION_MODE_NAMES } from '@/lib/types'
import { Link2, Shield, Cpu, ToggleRight } from 'lucide-react'

interface VehicleStatusProps {
  mode: number
  regime: number
  armed: boolean
  relayOn: boolean
  connectionHealthy: boolean
}

const MODE_STYLES: Record<number, { bg: string; text: string; glow: string }> = {
  0: { bg: 'bg-white/5',    text: 'text-text-disabled', glow: '' },
  1: { bg: 'bg-amber/10',   text: 'text-amber',         glow: 'shadow-[0_0_12px_rgba(210,153,34,0.15)]' },
  2: { bg: 'bg-green/10',   text: 'text-green',          glow: 'shadow-[0_0_12px_rgba(63,185,80,0.15)]' },
  3: { bg: 'bg-blue/10',    text: 'text-blue',           glow: 'shadow-[0_0_12px_rgba(88,166,255,0.15)]' },
  4: { bg: 'bg-purple/10',  text: 'text-purple',         glow: 'shadow-[0_0_12px_rgba(188,140,255,0.15)]' },
  5: { bg: 'bg-white/5',    text: 'text-text-secondary', glow: '' },
}

export function VehicleStatus({
  mode,
  regime,
  armed,
  relayOn,
  connectionHealthy,
}: VehicleStatusProps) {
  const modeStyle = MODE_STYLES[mode] ?? MODE_STYLES[0]
  const modeName = ACTUATION_MODE_NAMES[mode] ?? 'UNKNOWN'

  return (
    <div className="card space-y-4">
      <h3 className="section-title flex items-center gap-2">
        <div className="w-1 h-3.5 rounded-full bg-green" />
        Vehicle Status
      </h3>

      {/* Connection */}
      <StatusRow
        icon={<Link2 className="w-3.5 h-3.5" />}
        label="Link"
        ledState={connectionHealthy ? 'green' : 'off'}
        animate={connectionHealthy}
      >
        <AnimatePresence mode="wait">
          <motion.span
            key={connectionHealthy ? 'on' : 'off'}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className={cn(
              'badge',
              connectionHealthy
                ? 'bg-green/15 text-green border border-green/20'
                : 'bg-white/5 text-text-disabled border border-white/5'
            )}
          >
            {connectionHealthy ? 'CONNECTED' : 'OFFLINE'}
          </motion.span>
        </AnimatePresence>
      </StatusRow>

      {/* Armed */}
      <StatusRow
        icon={<Shield className="w-3.5 h-3.5" />}
        label="Armed"
        ledState={armed ? 'amber' : 'green'}
        animate={armed}
      >
        <AnimatePresence mode="wait">
          <motion.span
            key={armed ? 'armed' : 'safe'}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className={cn(
              'badge border',
              armed
                ? 'bg-amber/15 text-amber border-amber/20'
                : 'bg-green/15 text-green border-green/20'
            )}
          >
            {armed ? 'ARMED' : 'SAFE'}
            {regime > 0 && (
              <span className="ml-1.5 opacity-60 text-[9px]">R{regime}</span>
            )}
          </motion.span>
        </AnimatePresence>
      </StatusRow>

      {/* Mode */}
      <StatusRow
        icon={<Cpu className="w-3.5 h-3.5" />}
        label="Mode"
      >
        <AnimatePresence mode="wait">
          <motion.span
            key={mode}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.3 }}
            className={cn(
              'badge border border-white/10 transition-all duration-500',
              modeStyle.bg, modeStyle.text, modeStyle.glow
            )}
          >
            {modeName}
          </motion.span>
        </AnimatePresence>
      </StatusRow>

      {/* Relay */}
      <StatusRow
        icon={<ToggleRight className="w-3.5 h-3.5" />}
        label="Relay"
        ledState={relayOn ? 'red' : 'green'}
      >
        <span
          className={cn(
            'badge border',
            relayOn
              ? 'bg-red/15 text-red border-red/20'
              : 'bg-green/15 text-green border-green/20'
          )}
        >
          {relayOn ? 'ON' : 'OFF'}
        </span>
      </StatusRow>
    </div>
  )
}

function StatusRow({
  icon,
  label,
  ledState,
  animate,
  children,
}: {
  icon: React.ReactNode
  label: string
  ledState?: 'green' | 'red' | 'amber' | 'blue' | 'off'
  animate?: boolean
  children: React.ReactNode
}) {
  const ledClass = ledState ? `led-${ledState}` : undefined
  return (
    <div className="flex items-center gap-3">
      <span className="text-text-disabled">{icon}</span>
      <span className="text-text-secondary text-xs w-12 font-medium">{label}</span>
      {ledClass && (
        <span className={cn('led', ledClass, animate && 'animate-led-pulse')} />
      )}
      <div className="flex-1">{children}</div>
    </div>
  )
}
