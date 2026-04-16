import { Play, Square, Zap } from 'lucide-react'
import type { TestMode, ClientMessage, TestConfig } from '@/lib/types'

interface ControlBarProps {
  batchActive: boolean
  testMode: TestMode
  send: (msg: ClientMessage) => void
  testPayload?: { mode: string; durationSeconds: number; config: object } | null
}

export function ControlBar({ batchActive, testMode, send, testPayload }: ControlBarProps) {
  const startLabel =
    testMode === 'playback' ? 'Start Playback Test' : 'Start IBIT Test'

  return (
    <div className="relative flex items-center gap-3 h-20 px-5 shrink-0">
      {/* Background */}
      <div className="absolute inset-0 bg-gradient-to-t from-bg-base via-bg-elevated to-bg-surface border-t border-white/5" />

      {/* Start */}
      <button
        disabled={batchActive}
        onClick={() =>
          send({
            type: 'cmd.start_test',
            data: {
              mode: (testPayload?.mode ?? testMode) as TestMode,
              duration_seconds: testPayload?.durationSeconds ?? 86400 * 14,
              config: testPayload?.config as Partial<TestConfig> | undefined,
            },
          })
        }
        className="btn-primary relative z-10 flex-[2] h-12 text-base tracking-wider"
      >
        <Play className="w-4 h-4" />
        {startLabel}
      </button>

      {/* Stop */}
      <button
        disabled={!batchActive}
        onClick={() => send({ type: 'cmd.stop_test' })}
        className="btn-danger relative z-10 flex-1 h-12 text-base tracking-wide"
      >
        <Square className="w-4 h-4" />
        Stop
      </button>

      {/* Emergency Stop */}
      <button
        onClick={() => send({ type: 'cmd.emergency_stop' })}
        className="btn-emergency relative z-10 flex-1 h-14"
      >
        <Zap className="w-5 h-5" />
        EMERGENCY STOP
      </button>
    </div>
  )
}
