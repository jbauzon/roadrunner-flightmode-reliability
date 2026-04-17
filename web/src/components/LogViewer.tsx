import { useRef, useEffect, useState, useCallback } from 'react'
import { cn } from '@/lib/utils'
import type { LogEntry } from '@/hooks/use-websocket'

interface LogViewerProps {
  logs: LogEntry[]
  onClear: () => void
}

type LogLevel = 'ALL' | 'INFO' | 'WARN' | 'ERROR' | 'PASS' | 'FAIL'

const LEVEL_COLORS: Record<string, string> = {
  info:    'text-text-secondary',
  warn:    'text-amber',
  warning: 'text-amber',
  error:   'text-red',
  critical:'text-red',
  pass:    'text-green',
  fail:    'text-red',
}

export function LogViewer({ logs, onClear }: LogViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [filter, setFilter] = useState<LogLevel>('ALL')
  const [search, setSearch] = useState('')

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const handleScroll = useCallback(() => {
    if (!containerRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40)
  }, [])

  // Filter logs
  const filteredLogs = logs.filter((log) => {
    if (filter !== 'ALL') {
      const level = log.level?.toLowerCase() ?? 'info'
      if (filter === 'WARN' && level !== 'warn' && level !== 'warning') return false
      if (filter === 'ERROR' && level !== 'error' && level !== 'critical') return false
      if (filter === 'PASS' && !log.message.toLowerCase().includes('pass')) return false
      if (filter === 'FAIL' && !log.message.toLowerCase().includes('fail')) return false
      if (filter === 'INFO' && level !== 'info') return false
    }
    if (search && !log.message.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="card flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <h3 className="section-title">Test Log</h3>
        <div className="flex-1" />

        {/* Level filter pills */}
        {(['ALL', 'INFO', 'WARN', 'ERROR', 'PASS', 'FAIL'] as LogLevel[]).map((level) => (
          <button
            key={level}
            onClick={() => setFilter(level)}
            className={cn(
              'px-2 py-0.5 text-[10px] font-bold tracking-wider rounded transition-colors',
              filter === level
                ? 'bg-bg-hover text-text-primary'
                : 'text-text-disabled hover:text-text-secondary'
            )}
          >
            {level}
          </button>
        ))}

        {/* Search */}
        <input
          type="text"
          placeholder="Search log..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-bg-elevated border border-border rounded px-2 py-0.5
                     text-xs text-text-primary placeholder:text-text-disabled
                     focus:border-border-focus outline-none w-32"
        />

        {/* Clear */}
        <button
          onClick={onClear}
          className="text-text-disabled text-xs hover:text-text-secondary transition-colors"
        >
          Clear
        </button>
      </div>

      {/* Log content */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 min-h-0 overflow-y-auto bg-bg-base border border-border
                   rounded p-2 font-mono text-xs leading-5"
      >
        {filteredLogs.map((log) => {
          const ts = log.timestamp
            ? new Date(log.timestamp).toLocaleTimeString('en-US', { hour12: false })
            : ''
          const levelColor = LEVEL_COLORS[log.level?.toLowerCase() ?? 'info'] ?? 'text-text-secondary'

          return (
            <div key={log.id} className="flex gap-2 hover:bg-bg-hover/30 rounded px-1">
              <span className="text-text-disabled shrink-0">[{ts}]</span>
              <span className={cn(levelColor)}>{log.message}</span>
            </div>
          )
        })}
        {filteredLogs.length === 0 && (
          <div className="text-text-disabled text-center py-8 space-y-2">
            {logs.length === 0 ? (
              <>
                <div className="text-sm font-medium">Ready to test</div>
                <div className="text-xs leading-relaxed max-w-xs mx-auto">
                  1. Set up DAQ hardware or launch SITL<br />
                  2. Add UUTs to the table above<br />
                  3. Click <span className="text-green font-medium">Start</span> to begin IBIT testing
                </div>
              </>
            ) : (
              'No matching entries'
            )}
          </div>
        )}
      </div>
    </div>
  )
}
