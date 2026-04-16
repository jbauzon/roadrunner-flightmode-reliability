import { Search, Plus, Trash2, Upload, Download, Edit3 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { UUT, ClientMessage } from '@/lib/types'

interface DAQSetupProps {
  daq: {
    initialized: boolean
    device: string | null
    num_lines: number
    sitl_active: boolean
    devices: string[]
  }
  send: (msg: ClientMessage) => void
}

export function DAQSetup({ daq, send }: DAQSetupProps) {
  return (
    <div className="card space-y-3">
      <h3 className="section-title">DAQ Setup</h3>

      {/* Device selector */}
      <div className="flex items-center gap-2">
        <span className="text-text-secondary text-sm">Device:</span>
        <select
          className="flex-1 bg-bg-elevated border border-border rounded px-2 py-1.5
                     text-sm text-text-primary focus:border-border-focus outline-none"
          value={daq.device ?? ''}
          disabled={daq.sitl_active}
        >
          {daq.devices.length === 0 && !daq.device && (
            <option value="">No devices</option>
          )}
          {daq.device && !daq.devices.includes(daq.device) && (
            <option value={daq.device}>{daq.device}</option>
          )}
          {daq.devices.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </div>

      {/* Buttons */}
      <div className="flex gap-2">
        <button
          className="btn-neutral text-xs flex-1"
          onClick={() => send({ type: 'cmd.detect_daq' })}
          disabled={daq.sitl_active}
        >
          <Search className="w-3.5 h-3.5" />
          Detect
        </button>
        <button
          className="btn-neutral text-xs flex-1"
          onClick={() => {
            if (daq.devices[0]) {
              send({ type: 'cmd.init_daq', data: { device: daq.devices[0] } })
            }
          }}
          disabled={daq.sitl_active || daq.devices.length === 0}
        >
          Initialize
        </button>
      </div>

      {/* SITL — small, subtle, developer/test use only */}
      <button
        className="text-[10px] text-text-disabled hover:text-text-secondary
                   transition-colors border-none bg-transparent cursor-pointer
                   disabled:opacity-30 disabled:cursor-not-allowed w-full text-left px-1"
        onClick={() => send({ type: 'cmd.launch_sitl' })}
        disabled={daq.sitl_active}
      >
        {daq.sitl_active ? '● Simulation active' : '○ Simulate (no hardware)'}
      </button>

      {/* Status */}
      <div className="flex items-center gap-2">
        <span
          className={cn(
            'led',
            daq.initialized ? 'led-green' :
            daq.sitl_active ? 'led-green' :
            'led-off'
          )}
        />
        <span
          className={cn(
            'text-xs font-mono',
            daq.initialized ? 'text-green' :
            daq.sitl_active ? 'text-green' :
            'text-amber'
          )}
        >
          {daq.sitl_active
            ? `Ready (simulated)`
            : daq.initialized
              ? `Ready (${daq.num_lines} lines)`
              : 'Not Initialized'}
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// UUT Table
// ---------------------------------------------------------------------------

interface UUTTableProps {
  uuts: UUT[]
  send: (msg: ClientMessage) => void
  selectedIndex: number
  onSelect: (index: number) => void
  onAdd: () => void
  onEdit: () => void
  onRemove: () => void
}

const STATUS_STYLES: Record<string, string> = {
  READY:           'bg-bg-elevated text-text-secondary',
  TESTING:         'bg-blue-dim text-blue',
  PASSED:          'bg-green-dim text-green',
  FAILED:          'bg-red-dim text-red',
  RETRY:           'bg-amber-dim text-amber',
  FAILED_PERMANENT:'bg-red-dim text-red',
  SKIPPED:         'bg-bg-elevated text-text-disabled',
}

export function UUTTable({ uuts, selectedIndex, onSelect, onAdd, onEdit, onRemove }: UUTTableProps) {
  return (
    <div className="card flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <h3 className="section-title">Unit Under Test</h3>
        <div className="flex gap-1.5">
          <button
            className="btn-neutral text-xs py-1 px-2.5"
            onClick={onAdd}
          >
            <Plus className="w-3 h-3" />
            Add
          </button>
          <button className="btn-neutral text-xs py-1 px-2.5" onClick={onEdit}>
            <Edit3 className="w-3 h-3" />
            Edit
          </button>
          <button className="btn-neutral text-xs py-1 px-2.5 text-red hover:border-red" onClick={onRemove}>
            <Trash2 className="w-3 h-3" />
          </button>
          <div className="w-px bg-border mx-1" />
          <button className="btn-neutral text-xs py-1 px-2.5">
            <Download className="w-3 h-3" />
            Save
          </button>
          <button className="btn-neutral text-xs py-1 px-2.5">
            <Upload className="w-3 h-3" />
            Load
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 min-h-0 overflow-auto rounded border border-border">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10">
            <tr className="bg-bg-elevated text-text-secondary text-xs uppercase tracking-wider">
              <th className="py-2 px-3 text-left font-semibold">#</th>
              <th className="py-2 px-3 text-left font-semibold">Serial</th>
              <th className="py-2 px-3 text-left font-semibold">IP Address</th>
              <th className="py-2 px-3 text-center font-semibold">Port</th>
              <th className="py-2 px-3 text-center font-semibold">Relay</th>
              <th className="py-2 px-3 text-center font-semibold">Iterations</th>
              <th className="py-2 px-3 text-center font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {uuts.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-8 text-center text-text-disabled">
                  No UUTs configured. Click + Add to get started.
                </td>
              </tr>
            ) : (
              uuts.map((uut, i) => (
                <tr
                  key={uut.serial_number}
                  onClick={() => onSelect(i)}
                  className={cn(
                    'cursor-pointer transition-colors duration-150',
                    selectedIndex === i
                      ? 'bg-blue-dim/40'
                      : 'hover:bg-bg-hover'
                  )}
                >
                  <td className="py-2 px-3 text-text-disabled font-mono">{i + 1}</td>
                  <td className="py-2 px-3 font-mono font-medium">{uut.serial_number}</td>
                  <td className="py-2 px-3 font-mono text-text-secondary">{uut.ip_address}</td>
                  <td className="py-2 px-3 text-center font-mono text-text-secondary">{uut.port}</td>
                  <td className="py-2 px-3 text-center font-mono text-text-secondary">D{uut.relay_line}</td>
                  <td className="py-2 px-3 text-center font-mono">{uut.iterations_completed}</td>
                  <td className="py-2 px-3 text-center">
                    <span className={cn('badge', STATUS_STYLES[uut.status] ?? '')}>
                      {uut.status}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
