import { useState, useEffect } from 'react'
import type { useWebSocket } from '@/hooks/use-websocket'
import { cn } from '@/lib/utils'
import { ACTUATION_MODE_NAMES, SURFACES } from '@/lib/types'
import { ActuatorPositionChart, BatteryChart, EngineChart } from '@/components/TelemetryCharts'

interface DebugModeProps {
  ws: ReturnType<typeof useWebSocket>
  onAlert: (message: string, severity: string) => void
}

const MODE_BUTTONS = [
  { id: 0, name: 'OFF',       color: 'text-text-disabled', border: 'border-text-disabled', hoverBg: 'hover:bg-text-disabled' },
  { id: 2, name: 'OPERATE',   color: 'text-green',   border: 'border-green',   hoverBg: 'hover:bg-green' },
  { id: 4, name: 'PLAYBACK',  color: 'text-blue',    border: 'border-blue',    hoverBg: 'hover:bg-blue' },
  { id: 1, name: 'IBIT',      color: 'text-amber',   border: 'border-amber',   hoverBg: 'hover:bg-amber' },
  { id: 3, name: 'MANUAL',    color: 'text-purple',  border: 'border-purple',  hoverBg: 'hover:bg-purple' },
  { id: 5, name: 'TRIM',      color: 'text-text-secondary', border: 'border-text-secondary', hoverBg: 'hover:bg-text-secondary' },
  { id: 6, name: 'POS CHECK', color: 'text-blue',    border: 'border-blue',    hoverBg: 'hover:bg-blue' },
  { id: 7, name: 'TERMINAL',  color: 'text-red',     border: 'border-red',     hoverBg: 'hover:bg-red' },
] as const

export function DebugMode({ ws }: DebugModeProps) {
  const [selectedUUT, setSelectedUUT] = useState(() =>
    ws.uuts.length > 0
      ? JSON.stringify({ serial: ws.uuts[0].serial_number, ip: ws.uuts[0].ip_address, port: ws.uuts[0].port })
      : ''
  )
  const [monitorId, setMonitorId] = useState(0)

  useEffect(() => {
    if (ws.uuts.length > 0 && !selectedUUT) {
      setSelectedUUT(JSON.stringify({
        serial: ws.uuts[0].serial_number,
        ip: ws.uuts[0].ip_address,
        port: ws.uuts[0].port,
      }))
    }
  }, [ws.uuts, selectedUUT])

  return (
    <div className="flex h-full">
      {/* Left — Command console */}
      <div className="w-[460px] shrink-0 overflow-y-auto border-r border-border flex flex-col">
        {/* Title bar */}
        <div className="flex items-center justify-between h-9 bg-bg-elevated border-b border-border px-3">
          <span className="text-amber text-xs font-bold tracking-widest">
            MANUAL COMMANDS
          </span>
          <span className="text-text-disabled text-xs">
            {ws.vehicle.connection_healthy ? (
              <span className="text-green">Connected</span>
            ) : (
              'Not connected'
            )}
          </span>
        </div>

        {/* Warning */}
        {ws.batch.active && (
          <div className="bg-red-dim/50 border-b border-red px-3 py-2 text-red text-xs font-bold">
            TEST IS RUNNING — commands will interrupt the sequence
          </div>
        )}

        {/* Connection bar */}
        <div className="flex items-center gap-2 px-3 py-2 bg-bg-base border-b border-border">
          <span className="text-text-secondary text-xs shrink-0">UUT:</span>
          <select
            className="flex-1 bg-bg-elevated border border-border rounded px-2 py-1 text-xs
                       text-text-primary focus:border-border-focus outline-none font-mono"
            value={selectedUUT}
            onChange={(e) => setSelectedUUT(e.target.value)}
            disabled={ws.vehicle.connection_healthy}
          >
            {ws.uuts.length === 0 ? (
              <option value="">No UUTs — click Simulate first</option>
            ) : (
              ws.uuts.map((u) => (
                <option key={u.serial_number} value={JSON.stringify({ serial: u.serial_number, ip: u.ip_address, port: u.port })}>
                  {u.serial_number} ({u.ip_address}:{u.port})
                </option>
              ))
            )}
          </select>
          {!ws.vehicle.connection_healthy ? (
            <button
              className="btn-neutral text-xs px-3 text-green border-green hover:bg-green hover:text-bg-base
                         disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
              disabled={ws.uuts.length === 0 || !selectedUUT}
              onClick={() => {
                try {
                  const parsed = JSON.parse(selectedUUT)
                  ws.send({ type: 'cmd.debug.connect', data: { serial: parsed.serial, ip: parsed.ip, port: parsed.port } })
                } catch {}
              }}
            >
              Connect
            </button>
          ) : (
            <button
              className="btn-neutral text-xs px-3 text-red border-red hover:bg-red hover:text-bg-base shrink-0"
              onClick={() => ws.send({ type: 'cmd.debug.disconnect' })}
            >
              Disconnect
            </button>
          )}
        </div>

        <div className="p-3 space-y-4 overflow-y-auto flex-1">
          {/* Mode request */}
          <Section title="Actuation Mode Request">
            <div className="grid grid-cols-4 gap-1.5">
              {MODE_BUTTONS.map((m) => (
                <button
                  key={m.id}
                  onClick={() =>
                    ws.send({ type: 'cmd.debug.mode_request', data: { mode_id: m.id } })
                  }
                  disabled={!ws.vehicle.connection_healthy}
                  className={cn(
                    'py-1.5 text-xs font-bold rounded border transition-all',
                    m.color, m.border,
                    `${m.hoverBg} hover:text-bg-base`,
                    'disabled:opacity-30 disabled:cursor-not-allowed'
                  )}
                >
                  {m.name}
                </button>
              ))}
            </div>
          </Section>

          {/* ARM / DISARM */}
          <Section title="ARM / DISARM">
            <div className="flex gap-2">
              <button
                onClick={() => ws.send({ type: 'cmd.debug.arm', data: { arm: true } })}
                disabled={!ws.vehicle.connection_healthy}
                className="btn-neutral flex-1 text-green border-green hover:bg-green hover:text-bg-base disabled:opacity-30"
              >
                ARM
              </button>
              <button
                onClick={() => ws.send({ type: 'cmd.debug.arm', data: { arm: true, force: true } })}
                disabled={!ws.vehicle.connection_healthy}
                className="btn-neutral flex-1 text-amber border-amber hover:bg-amber hover:text-bg-base disabled:opacity-30"
              >
                Force ARM
              </button>
              <button
                onClick={() => ws.send({ type: 'cmd.debug.arm', data: { arm: false } })}
                disabled={!ws.vehicle.connection_healthy}
                className="btn-neutral flex-1 text-red border-red hover:bg-red hover:text-bg-base disabled:opacity-30"
              >
                DISARM
              </button>
            </div>
          </Section>

          {/* Parameter set */}
          <Section title="Parameter Set">
            <div className="grid grid-cols-2 gap-1.5">
              {[
                { label: 'USE_NEST = 0', name: 'USE_NEST', val: 0 },
                { label: 'USE_NEST = 1', name: 'USE_NEST', val: 1 },
                { label: 'CLASSIC_MODE = 0', name: 'CLASSIC_MODE_EN', val: 0 },
                { label: 'CLASSIC_MODE = 1', name: 'CLASSIC_MODE_EN', val: 1 },
              ].map((p) => (
                <button
                  key={p.label}
                  onClick={() =>
                    ws.send({ type: 'cmd.debug.param_set', data: { name: p.name, value: p.val } })
                  }
                  disabled={!ws.vehicle.connection_healthy}
                  className="btn-neutral text-xs disabled:opacity-30"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </Section>

          {/* Monitor override */}
          <Section title="Monitor Override">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-text-secondary text-xs shrink-0">Monitor ID:</span>
              <input
                type="number"
                value={monitorId}
                onChange={(e) => setMonitorId(Number(e.target.value))}
                min={0}
                max={300}
                className="w-20 bg-bg-elevated border border-border rounded px-2 py-1
                           text-xs font-mono text-text-primary focus:border-border-focus outline-none"
              />
              <div className="flex gap-1 flex-1">
                {[
                  { label: 'M6', id: 6, title: 'Temp Warning' },
                  { label: 'M7', id: 7, title: 'Temp Critical' },
                  { label: 'M9', id: 9, title: 'Thermal Limit' },
                ].map((m) => (
                  <button
                    key={m.id}
                    title={m.title}
                    onClick={() => setMonitorId(m.id)}
                    className="btn-neutral text-[10px] px-1.5 py-0.5 shrink-0"
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => ws.send({ type: 'cmd.debug.monitor_override', data: { cmd: 1, monitor_id: monitorId } })}
                disabled={!ws.vehicle.connection_healthy}
                className="btn-neutral flex-1 text-xs text-green disabled:opacity-30"
              >
                Suppress (1)
              </button>
              <button
                onClick={() => ws.send({ type: 'cmd.debug.monitor_override', data: { cmd: 0, monitor_id: monitorId } })}
                disabled={!ws.vehicle.connection_healthy}
                className="btn-neutral flex-1 text-xs disabled:opacity-30"
              >
                Cancel (0)
              </button>
              <button
                onClick={() => ws.send({ type: 'cmd.debug.monitor_override', data: { cmd: 2, monitor_id: monitorId } })}
                disabled={!ws.vehicle.connection_healthy}
                className="btn-neutral flex-1 text-xs text-red disabled:opacity-30"
              >
                Force Fault (2)
              </button>
            </div>
          </Section>
        </div>
      </div>

      {/* Right — Live telemetry panel */}
      <div className="flex-1 min-w-0 overflow-y-auto p-3 space-y-3">
        {!ws.vehicle.connection_healthy ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-text-disabled">
            <span className="text-lg">No vehicle connected</span>
            <span className="text-sm text-center max-w-xs">
              Select a UUT from the dropdown and click <span className="text-green">Connect</span> to see live telemetry
            </span>
          </div>
        ) : (
          <>
            {/* Vehicle status section */}
            <TelemetrySection title="Vehicle Status" accent="border-l-green">
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                <TelemetryRow label="Mode">
                  <span className="font-mono font-bold">
                    {ACTUATION_MODE_NAMES[ws.vehicle.mode] ?? 'UNKNOWN'}
                  </span>
                </TelemetryRow>
                <TelemetryRow label="Regime">
                  <span className="font-mono">R{ws.vehicle.regime}</span>
                </TelemetryRow>
                <TelemetryRow label="Armed">
                  <span className={ws.vehicle.armed ? 'text-amber font-bold' : 'text-green'}>
                    {ws.vehicle.armed ? 'ARMED' : 'SAFE'}
                  </span>
                </TelemetryRow>
                <TelemetryRow label="Relay">
                  <span className={ws.vehicle.relay_on ? 'text-red' : 'text-green'}>
                    {ws.vehicle.relay_on ? 'ON' : 'OFF'}
                  </span>
                </TelemetryRow>
              </div>
            </TelemetrySection>

            {/* IBIT status */}
            <TelemetrySection title="IBIT Status" accent="border-l-amber">
              <div className="flex items-center gap-3 text-sm">
                <span className="text-text-secondary">Substate:</span>
                <span className="font-mono font-bold">{ws.ibit.substate}</span>
              </div>
              <div className="flex gap-1 mt-2">
                {SURFACES.map(({ display, bit }) => {
                  const mistracking = (ws.ibit.mistracking_flags & bit) !== 0
                  return (
                    <span
                      key={display}
                      className={cn(
                        'text-[8px] px-1.5 py-0.5 rounded border text-center flex-1 transition-colors',
                        mistracking
                          ? 'bg-red-dim border-red text-red font-bold'
                          : 'bg-green-dim border-green text-green'
                      )}
                    >
                      {display}
                    </span>
                  )
                })}
              </div>
            </TelemetrySection>

            {/* Actuator surfaces */}
            <TelemetrySection title="Actuator Surfaces" accent="border-l-blue">
              <div className="grid grid-cols-4 gap-1 text-[10px] text-text-disabled font-semibold uppercase mb-1">
                <span>Surface</span>
                <span className="text-center">Pos (&deg;)</span>
                <span className="text-center">Current</span>
                <span className="text-center">Temp</span>
              </div>
              {SURFACES.map(({ key, display, bit }) => {
                const fb = ws.actuator[`${key}_feedback_cdeg` as keyof typeof ws.actuator] as number | undefined
                const curr = ws.actuator[`${key}_current_mA` as keyof typeof ws.actuator] as number | undefined
                const temp = ws.actuator[`${key}_motor_temp_degC` as keyof typeof ws.actuator] as number | undefined
                const mistracking = (ws.ibit.mistracking_flags & bit) !== 0

                return (
                  <div key={key} className="grid grid-cols-4 gap-1 text-xs py-0.5">
                    <span className="text-text-secondary">{display}</span>
                    <span className={cn(
                      'font-mono text-center',
                      mistracking ? 'text-red font-bold' : 'text-text-primary'
                    )}>
                      {fb != null ? (fb / 100).toFixed(1) : '---'}
                    </span>
                    <span className="font-mono text-center text-text-primary">
                      {curr != null ? String(curr) : '---'}
                    </span>
                    <span className="font-mono text-center text-text-primary">
                      {temp != null ? String(temp) : '---'}
                    </span>
                  </div>
                )
              })}
            </TelemetrySection>

            {/* Message stream */}
            <TelemetrySection title="Message Stream (last 20)" accent="border-l-purple">
              <div className="bg-bg-base border border-border rounded p-2 font-mono text-[10px] max-h-40 overflow-y-auto">
                {ws.debugMessages.length === 0 ? (
                  <span className="text-text-disabled">Waiting for messages...</span>
                ) : (
                  ws.debugMessages.map((m, i) => (
                    <div key={i} className="flex gap-2 text-text-secondary">
                      <span className="text-text-disabled shrink-0">[{m.timestamp}]</span>
                      <span className="text-green">{m.msg_type}</span>
                      <span className="truncate">{m.summary}</span>
                    </div>
                  ))
                )}
              </div>
            </TelemetrySection>

            {/* Real-time charts */}
            <ActuatorPositionChart data={ws.actuatorHistory} />
            <BatteryChart data={ws.batteryHistory} />
            <EngineChart data={ws.engineHistory} />
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-border rounded-md overflow-hidden">
      <div className="bg-bg-elevated px-3 py-1.5 border-b border-border">
        <span className="text-text-secondary text-xs font-bold uppercase tracking-wider">
          {title}
        </span>
      </div>
      <div className="p-3">{children}</div>
    </div>
  )
}

function TelemetrySection({
  title,
  accent,
  children,
}: {
  title: string
  accent: string
  children: React.ReactNode
}) {
  return (
    <div className={cn('bg-bg-elevated rounded-md border-l-[3px] overflow-hidden', accent)}>
      <div className="px-3 py-1.5 border-b border-border">
        <span className="text-text-secondary text-xs font-bold uppercase tracking-wider">
          {title}
        </span>
      </div>
      <div className="p-3">{children}</div>
    </div>
  )
}

function TelemetryRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-text-secondary">{label}:</span>
      {children}
    </div>
  )
}
