import { useState, useEffect } from 'react'
import { Activity, Wifi, WifiOff, Radio } from 'lucide-react'
import type { TestMode } from '@/lib/types'
import type { ConnectionStatus } from '@/lib/ws-client'

interface HeaderProps {
  testMode: TestMode
  connectionStatus: ConnectionStatus
  batchActive: boolean
}

export function Header({ testMode, connectionStatus, batchActive }: HeaderProps) {
  const [clock, setClock] = useState(formatClock())

  useEffect(() => {
    const timer = setInterval(() => setClock(formatClock()), 1000)
    return () => clearInterval(timer)
  }, [])

  const modeLabel = testMode === 'playback' ? 'PLAYBACK MODE' : 'IBIT MODE'
  const isPlayback = testMode === 'playback'

  return (
    <header className="relative flex items-center h-14 px-6 shrink-0 overflow-hidden">
      {/* Gradient background */}
      <div className="absolute inset-0 bg-gradient-to-r from-bg-elevated via-bg-surface to-bg-elevated" />
      <div className="absolute inset-0 bg-gradient-to-b from-transparent to-black/20" />

      {/* Accent line at top */}
      <div
        className={`absolute top-0 left-0 right-0 h-[2px] transition-all duration-1000 ${
          batchActive
            ? 'bg-gradient-to-r from-transparent via-green to-transparent opacity-100'
            : isPlayback
              ? 'bg-gradient-to-r from-transparent via-purple to-transparent opacity-60'
              : 'bg-gradient-to-r from-transparent via-blue to-transparent opacity-40'
        }`}
      />

      {/* Bottom border */}
      <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent" />

      {/* Content */}
      <div className="relative flex items-center gap-3 z-10">
        <div className="relative">
          <Activity className="w-5 h-5 text-green" />
          {batchActive && (
            <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green rounded-full animate-ping" />
          )}
        </div>
        <h1 className="text-base font-bold tracking-[3px] gradient-text">
          ROADRUNNER  FLIGHT TEST
        </h1>
      </div>

      <div className="flex-1" />

      {/* Batch active indicator */}
      {batchActive && (
        <div className="relative flex items-center gap-2 mr-5 z-10">
          <Radio className="w-3.5 h-3.5 text-green animate-pulse" />
          <span className="text-green text-[11px] font-mono font-bold tracking-widest">
            TESTING
          </span>
        </div>
      )}

      {/* Mode badge */}
      <div className="relative z-10">
        <div
          className={`
            px-5 py-1.5 rounded-full font-mono text-[11px] font-bold tracking-[0.15em]
            transition-all duration-700 border
            ${isPlayback
              ? 'bg-purple/10 text-purple border-purple/30 shadow-[0_0_15px_rgba(188,140,255,0.15)]'
              : 'bg-blue/10 text-blue border-blue/30 shadow-[0_0_15px_rgba(88,166,255,0.15)]'
            }
          `}
        >
          {modeLabel}
        </div>
      </div>

      <div className="w-5" />

      {/* Connection indicator */}
      <div className="relative flex items-center gap-2 z-10">
        {connectionStatus === 'connected' ? (
          <Wifi className="w-3.5 h-3.5 text-green/70" />
        ) : (
          <WifiOff className="w-3.5 h-3.5 text-text-disabled" />
        )}
      </div>

      <div className="w-4" />

      {/* Clock */}
      <span className="relative z-10 text-text-secondary/60 font-mono text-[11px] tracking-wider">
        {clock}
      </span>
    </header>
  )
}

function formatClock(): string {
  const now = new Date()
  const y = now.getFullYear()
  const mo = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  const h = String(now.getHours()).padStart(2, '0')
  const mi = String(now.getMinutes()).padStart(2, '0')
  const s = String(now.getSeconds()).padStart(2, '0')
  return `${y}-${mo}-${d}  ${h}:${mi}:${s}`
}
