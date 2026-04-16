/**
 * use-telemetry.ts — Ring-buffer telemetry history for charts.
 *
 * Accumulates actuator positions, battery, and engine data over time
 * in fixed-size ring buffers for Recharts sparklines.
 */

import { useRef, useCallback, useMemo } from 'react'
import type { ActuatorFeedback } from '@/lib/types'

const MAX_SAMPLES = 120  // 60 seconds at ~2Hz

export interface TelemetrySample {
  t: number  // relative seconds
  [key: string]: number
}

export interface BatterySample {
  t: number
  voltage: number
  current: number
  soc: number
}

export interface EngineSample {
  t: number
  rpm: number
  egt: number
  fuelPump: number
}

/**
 * Ring buffer that keeps the last MAX_SAMPLES entries.
 * Returns a new array reference on each push (for React re-render).
 */
class RingBuffer<T> {
  private _data: T[] = []
  private _max: number

  constructor(max: number = MAX_SAMPLES) {
    this._max = max
  }

  push(item: T): T[] {
    this._data.push(item)
    if (this._data.length > this._max) {
      this._data = this._data.slice(-this._max)
    }
    return [...this._data]
  }

  get data(): T[] {
    return this._data
  }

  clear(): void {
    this._data = []
  }
}

export function useTelemetryHistory() {
  const startRef = useRef(Date.now())
  const actuatorBuf = useRef(new RingBuffer<TelemetrySample>())
  const batteryBuf = useRef(new RingBuffer<BatterySample>())
  const engineBuf = useRef(new RingBuffer<EngineSample>())

  // Latest snapshot arrays (new refs on each push)
  const actuatorRef = useRef<TelemetrySample[]>([])
  const batteryRef = useRef<BatterySample[]>([])
  const engineRef = useRef<EngineSample[]>([])

  const relativeTime = useCallback(() => {
    return (Date.now() - startRef.current) / 1000
  }, [])

  const pushActuator = useCallback((data: ActuatorFeedback) => {
    const t = relativeTime()
    const sample: TelemetrySample = { t }

    const keys = [
      'left_elevon', 'right_elevon',
      'dorsal_rudder', 'ventral_rudder',
      'left_tvc_upper', 'left_tvc_lower',
      'right_tvc_upper', 'right_tvc_lower',
    ] as const

    for (const key of keys) {
      const raw = data[`${key}_feedback_cdeg` as keyof ActuatorFeedback]
      if (typeof raw === 'number') {
        sample[key] = raw / 100
      }
    }

    actuatorRef.current = actuatorBuf.current.push(sample)
  }, [relativeTime])

  const pushBattery = useCallback((voltage_mV: number, current_cA: number, soc: number) => {
    batteryRef.current = batteryBuf.current.push({
      t: relativeTime(),
      voltage: voltage_mV / 1000,
      current: current_cA / 100,
      soc: Math.max(0, Math.min(100, soc)),
    })
  }, [relativeTime])

  const pushEngine = useCallback((rpm: number, egt: number, fuelPump: number) => {
    engineRef.current = engineBuf.current.push({
      t: relativeTime(),
      rpm,
      egt,
      fuelPump,
    })
  }, [relativeTime])

  const reset = useCallback(() => {
    startRef.current = Date.now()
    actuatorBuf.current.clear()
    batteryBuf.current.clear()
    engineBuf.current.clear()
    actuatorRef.current = []
    batteryRef.current = []
    engineRef.current = []
  }, [])

  return useMemo(() => ({
    actuatorHistory: actuatorRef,
    batteryHistory: batteryRef,
    engineHistory: engineRef,
    pushActuator,
    pushBattery,
    pushEngine,
    reset,
  }), [pushActuator, pushBattery, pushEngine, reset])
}
