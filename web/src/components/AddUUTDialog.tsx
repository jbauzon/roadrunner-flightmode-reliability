/**
 * AddUUTDialog — Modal dialog for adding or editing a UUT.
 */
import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X } from 'lucide-react'
import type { UUT, ClientMessage } from '@/lib/types'

interface AddUUTDialogProps {
  open: boolean
  editingUUT?: UUT & { index: number }
  existingUUTs: UUT[]
  onClose: () => void
  send: (msg: ClientMessage) => void
}

interface FormErrors {
  serial?: string
  ip?: string
  port?: string
  relay?: string
}

export function AddUUTDialog({ open, editingUUT, existingUUTs, onClose, send }: AddUUTDialogProps) {
  const [serial, setSerial] = useState('')
  const [ip, setIp] = useState('10.10.10.1')
  const [port, setPort] = useState('13002')
  const [relay, setRelay] = useState('0')
  const [errors, setErrors] = useState<FormErrors>({})

  const isEditing = !!editingUUT

  // Populate form when editing
  useEffect(() => {
    if (editingUUT) {
      setSerial(editingUUT.serial_number)
      setIp(editingUUT.ip_address)
      setPort(String(editingUUT.port))
      setRelay(String(editingUUT.relay_line))
    } else {
      setSerial('')
      setIp('10.10.10.1')
      setPort('13002')
      setRelay(String(existingUUTs.length))
    }
    setErrors({})
  }, [editingUUT, open, existingUUTs.length])

  const validate = useCallback((): boolean => {
    const errs: FormErrors = {}
    if (!serial.trim()) errs.serial = 'Serial number is required'

    if (!ip.trim()) {
      errs.ip = 'IP address is required'
    } else if (!/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(ip)) {
      errs.ip = 'Invalid IP format'
    }

    const portNum = parseInt(port, 10)
    if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
      errs.port = 'Port must be 1-65535'
    }

    const relayNum = parseInt(relay, 10)
    if (isNaN(relayNum) || relayNum < 0 || relayNum > 7) {
      errs.relay = 'Relay must be 0-7'
    }

    // Check for duplicate relay (excluding current if editing)
    const relayConflict = existingUUTs.some((u, i) =>
      u.relay_line === relayNum && (!isEditing || i !== editingUUT?.index)
    )
    if (relayConflict) {
      errs.relay = `Relay D${relayNum} is already assigned`
    }

    // Check for duplicate endpoint
    const endpointConflict = existingUUTs.some((u, i) =>
      u.ip_address === ip && u.port === portNum && (!isEditing || i !== editingUUT?.index)
    )
    if (endpointConflict) {
      errs.ip = `${ip}:${portNum} is already in use`
    }

    setErrors(errs)
    return Object.keys(errs).length === 0
  }, [serial, ip, port, relay, existingUUTs, isEditing, editingUUT])

  const handleSubmit = useCallback(() => {
    if (!validate()) return

    const uutData = {
      serial_number: serial.trim(),
      ip_address: ip.trim(),
      port: parseInt(port, 10),
      relay_line: parseInt(relay, 10),
    }

    if (isEditing && editingUUT) {
      send({ type: 'cmd.edit_uut', data: { index: editingUUT.index, ...uutData } })
    } else {
      send({ type: 'cmd.add_uut', data: uutData })
    }

    onClose()
  }, [validate, serial, ip, port, relay, isEditing, editingUUT, send, onClose])

  // Handle Escape key
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Enter') handleSubmit()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose, handleSubmit])

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
            onClick={onClose}
          />

          {/* Dialog */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                       w-[440px] bg-bg-surface border border-border rounded-xl
                       shadow-2xl z-50 overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-border">
              <h2 className="text-base font-semibold">
                {isEditing ? 'Edit UUT' : 'Add UUT'}
              </h2>
              <button
                onClick={onClose}
                className="p-1 rounded hover:bg-bg-hover transition-colors"
              >
                <X className="w-4 h-4 text-text-secondary" />
              </button>
            </div>

            {/* Form */}
            <div className="p-5 space-y-4">
              <Field
                label="Serial Number"
                value={serial}
                onChange={setSerial}
                placeholder="RR-001"
                error={errors.serial}
                autoFocus
              />
              <div className="grid grid-cols-2 gap-3">
                <Field
                  label="IP Address"
                  value={ip}
                  onChange={setIp}
                  placeholder="10.10.10.1"
                  error={errors.ip}
                />
                <Field
                  label="Port"
                  value={port}
                  onChange={setPort}
                  placeholder="13002"
                  type="number"
                  error={errors.port}
                />
              </div>
              <Field
                label="Relay Line"
                value={relay}
                onChange={setRelay}
                placeholder="0"
                type="number"
                error={errors.relay}
                hint="Digital output line (0-7) on the NI-DAQmx device"
              />
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border bg-bg-elevated/50">
              <button onClick={onClose} className="btn-neutral">
                Cancel
              </button>
              <button onClick={handleSubmit} className="btn-primary">
                {isEditing ? 'Save Changes' : 'Add UUT'}
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

// ---------------------------------------------------------------------------
// Field helper
// ---------------------------------------------------------------------------

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
  error,
  hint,
  autoFocus,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  error?: string
  hint?: string
  autoFocus?: boolean
}) {
  return (
    <div>
      <label className="block text-xs text-text-secondary font-semibold uppercase tracking-wider mb-1.5">
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className={`
          w-full bg-bg-elevated border rounded px-3 py-2
          text-sm font-mono text-text-primary
          placeholder:text-text-disabled
          focus:outline-none focus:border-border-focus
          transition-colors
          ${error ? 'border-red' : 'border-border'}
        `}
      />
      {error && <p className="text-red text-xs mt-1">{error}</p>}
      {hint && !error && <p className="text-text-disabled text-xs mt-1">{hint}</p>}
    </div>
  )
}
