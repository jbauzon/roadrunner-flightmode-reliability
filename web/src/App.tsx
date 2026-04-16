import { useState, useCallback, useEffect } from 'react'
import { useWebSocket } from '@/hooks/use-websocket'
import { Header } from '@/components/Header'
import { ControlBar } from '@/components/ControlBar'
import { TestMode } from '@/pages/TestMode'
import { DebugMode } from '@/pages/DebugMode'
import { AlertBanner } from '@/components/AlertBanner'

type TabId = 'test' | 'debug'

export default function App() {
  const ws = useWebSocket()
  const [activeTab, setActiveTab] = useState<TabId>('test')
  const [alert, setAlert] = useState<{ message: string; severity: string } | null>(null)
  const [testPayload, setTestPayload] = useState<{
    mode: string
    durationSeconds: number
    config: object
  } | null>(null)

  // Show alerts from the backend
  const handleAlert = useCallback((message: string, severity: string) => {
    setAlert({ message, severity })
    setTimeout(() => setAlert(null), 10000)
  }, [])

  // Forward backend alerts to the banner
  useEffect(() => {
    // Check last log for alert-level messages
    const lastLog = ws.logs[ws.logs.length - 1]
    if (lastLog && (lastLog.level === 'critical' || lastLog.level === 'error')) {
      if (lastLog.message.includes('EMERGENCY')) {
        handleAlert(lastLog.message, 'critical')
      }
    }
  }, [ws.logs, handleAlert])

  // ── Keyboard shortcuts ─────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ignore if typing in an input
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if (e.ctrlKey && e.key === 's') {
        e.preventDefault()
        if (!ws.batch.active) {
          ws.send({
            type: 'cmd.start_test',
            data: {
              mode: (testPayload?.mode ?? ws.test_mode) as 'ibit' | 'playback',
              duration_seconds: testPayload?.durationSeconds ?? 86400 * 14,
              config: testPayload?.config as Partial<import('@/lib/types').TestConfig> | undefined,
            },
          })
        }
      }
      if (e.ctrlKey && e.key === 'q') {
        e.preventDefault()
        ws.send({ type: 'cmd.stop_test' })
      }
      if (e.ctrlKey && e.key === 'e') {
        e.preventDefault()
        ws.send({ type: 'cmd.emergency_stop' })
      }
      if (e.key === 'F5') {
        e.preventDefault()
        ws.send({ type: 'cmd.detect_daq' })
      }
      if (e.ctrlKey && e.key === 'd') {
        e.preventDefault()
        setActiveTab('debug')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [ws])

  return (
    <div className="flex flex-col h-screen bg-bg-base bg-grid overflow-hidden select-none">
      {/* Header */}
      <Header
        testMode={ws.test_mode}
        connectionStatus={ws.connectionStatus}
        batchActive={ws.batch.active}
      />

      {/* Alert banner */}
      <AlertBanner alert={alert} onDismiss={() => setAlert(null)} />

      {/* Tab bar */}
      <div className="flex items-center h-10 px-5 gap-1 shrink-0 border-b border-white/5 bg-gradient-to-r from-bg-surface/50 via-transparent to-bg-surface/50">
        <TabButton
          label="TEST MODE"
          active={activeTab === 'test'}
          onClick={() => setActiveTab('test')}
        />
        <TabButton
          label="DEBUG MODE"
          active={activeTab === 'debug'}
          onClick={() => setActiveTab('debug')}
        />
        <div className="flex-1" />
        <span className="text-text-disabled text-[10px] font-mono">
          Ctrl+S Start &middot; Ctrl+Q Stop &middot; Ctrl+E E-Stop &middot; F5 Detect &middot; Ctrl+D Debug
        </span>
      </div>

      {/* Main content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'test' ? (
          <TestMode ws={ws} onAlert={handleAlert} onConfigChange={setTestPayload} />
        ) : (
          <DebugMode ws={ws} onAlert={handleAlert} />
        )}
      </div>

      {/* Bottom control bar */}
      <ControlBar
        batchActive={ws.batch.active}
        testMode={ws.test_mode}
        send={ws.send}
        testPayload={testPayload}
      />

      {/* Status bar */}
      <div className="relative flex items-center h-6 px-5 text-text-disabled text-[10px] font-mono tracking-wider shrink-0">
        <div className="absolute inset-0 bg-gradient-to-r from-bg-elevated via-bg-surface to-bg-elevated border-t border-white/5" />
        <span className="relative z-10">Mode: {ws.test_mode.toUpperCase()}</span>
        <span className="relative z-10 mx-2 opacity-30">|</span>
        <span className="relative z-10">
          Backend:{' '}
          <span className={ws.connectionStatus === 'connected' ? 'text-green/80' : 'text-red/80'}>
            {ws.connectionStatus}
          </span>
        </span>
        <span className="relative z-10 mx-2 opacity-30">|</span>
        <span className="relative z-10">
          DAQ:{' '}
          <span className={ws.daq.initialized ? 'text-green/80' : 'text-amber/80'}>
            {ws.daq.initialized ? ws.daq.device ?? 'Ready' : 'Not initialized'}
          </span>
        </span>
        <span className="relative z-10 mx-2 opacity-30">|</span>
        <span className="relative z-10">UUTs: {ws.uuts.length}</span>
        <span className="flex-1" />
        <span className="relative z-10 text-text-disabled/50">v5.0.0</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab button
// ---------------------------------------------------------------------------

function TabButton({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`
        relative h-8 px-5 text-[10px] font-bold tracking-[0.15em] rounded-md
        transition-all duration-300
        ${
          active
            ? 'bg-white/[0.06] text-text-primary shadow-[0_0_12px_rgba(255,255,255,0.03)]'
            : 'bg-transparent text-text-disabled hover:text-text-secondary hover:bg-white/[0.03]'
        }
      `}
    >
      {label}
      {active && (
        <span className="absolute bottom-0 left-2 right-2 h-[2px] rounded-full bg-gradient-to-r from-green/80 via-green to-green/80" />
      )}
    </button>
  )
}
