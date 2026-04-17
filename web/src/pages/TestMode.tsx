import { useState, useCallback } from 'react'
import { DAQSetup, UUTTable } from '@/components/DAQSetup'
import { VehicleStatus } from '@/components/VehicleStatus'
import { IBITDisplay } from '@/components/IBITDisplay'
import { ActuatorFeedback } from '@/components/ActuatorFeedback'
import { LogViewer } from '@/components/LogViewer'
import { BatchProgress } from '@/components/BatchProgress'
import { AddUUTDialog } from '@/components/AddUUTDialog'
import { TestConfig } from '@/components/TestConfig'
import type { useWebSocket } from '@/hooks/use-websocket'
import type { UUT } from '@/lib/types'

interface TestModeProps {
  ws: ReturnType<typeof useWebSocket>
  onAlert: (message: string, severity: string) => void
  onConfigChange?: (payload: { mode: string; durationSeconds: number; config: object }) => void
}

export function TestMode({ ws, onAlert, onConfigChange }: TestModeProps) {
  const [selectedUUT, setSelectedUUT] = useState(0)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingUUT, setEditingUUT] = useState<(UUT & { index: number }) | undefined>()
  const [_testPayload, setTestPayload] = useState<{
    mode: string
    durationSeconds: number
    config: object
  } | null>(null)

  const handleConfigChange = useCallback((payload: { mode: string; durationSeconds: number; config: object }) => {
    setTestPayload(payload)
    onConfigChange?.(payload)
  }, [onConfigChange])

  const handleAdd = useCallback(() => {
    setEditingUUT(undefined)
    setDialogOpen(true)
  }, [])

  const handleEdit = useCallback(() => {
    if (selectedUUT >= 0 && selectedUUT < ws.uuts.length) {
      setEditingUUT({ ...ws.uuts[selectedUUT], index: selectedUUT })
      setDialogOpen(true)
    }
  }, [selectedUUT, ws.uuts])

  const handleRemove = useCallback(() => {
    if (ws.batch.active) {
      onAlert('Cannot remove a UUT while a test is running.', 'warning')
      return
    }
    if (selectedUUT >= 0 && selectedUUT < ws.uuts.length) {
      ws.send({ type: 'cmd.remove_uut', data: { index: selectedUUT } })
      setSelectedUUT(Math.max(0, selectedUUT - 1))
    }
  }, [selectedUUT, ws, onAlert])

  return (
    <div className="flex h-full">
      {/* Left column — config */}
      <div className="w-[320px] shrink-0 overflow-y-auto p-3 space-y-3 border-r border-white/5 bg-gradient-to-b from-bg-surface/30 to-transparent">
        <DAQSetup daq={ws.daq} send={ws.send} />
        <TestConfig onConfigChange={handleConfigChange} send={ws.send} daq={ws.daq} />
      </div>

      {/* Center column — UUT table + progress + log */}
      <div className="flex-1 min-w-0 flex flex-col p-3 gap-3">
        <div className="flex-[3] min-h-0">
          <UUTTable
            uuts={ws.uuts}
            send={ws.send}
            selectedIndex={selectedUUT}
            onSelect={setSelectedUUT}
            onAdd={handleAdd}
            onEdit={handleEdit}
            onRemove={handleRemove}
          />
        </div>
        <BatchProgress batch={ws.batch} statistics={ws.statistics} />
        <div className="flex-[2] min-h-0">
          <LogViewer logs={ws.logs} onClear={ws.clearLogs} />
        </div>
      </div>

      {/* Right column — status + IBIT + actuators */}
      <div className="w-[360px] shrink-0 overflow-y-auto p-3 space-y-3 border-l border-white/5 bg-gradient-to-b from-bg-surface/30 to-transparent">
        <VehicleStatus
          mode={ws.vehicle.mode}
          regime={ws.vehicle.regime}
          armed={ws.vehicle.armed}
          relayOn={ws.vehicle.relay_on}
          connectionHealthy={ws.vehicle.connection_healthy}
        />
        <IBITDisplay
          substate={ws.ibit.substate}
          mistrackingFlags={ws.ibit.mistracking_flags}
          durationSeconds={ws.ibit.duration_seconds}
        />
        <ActuatorFeedback
          data={ws.actuator}
          mistrackingFlags={ws.ibit.mistracking_flags}
        />
      </div>

      {/* Add/Edit UUT dialog */}
      <AddUUTDialog
        open={dialogOpen}
        editingUUT={editingUUT}
        existingUUTs={ws.uuts}
        onClose={() => setDialogOpen(false)}
        send={ws.send}
      />
    </div>
  )
}
