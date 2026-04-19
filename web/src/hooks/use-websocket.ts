/**
 * use-websocket.ts — React hook for WebSocket communication.
 *
 * Provides the full application state (synced from Python backend),
 * connection status, and a send() function for dispatching commands.
 *
 * State updates are handled via a reducer that processes ServerMessage events.
 */

import { useEffect, useReducer, useRef, useState, useCallback } from 'react'
import { WSClient, type ConnectionStatus } from '@/lib/ws-client'
import type { ServerMessage, ClientMessage, AppState } from '@/lib/types'
import { DEFAULT_APP_STATE } from '@/lib/types'

// ---------------------------------------------------------------------------
// Log entry model (kept locally in the frontend, not part of AppState)
// ---------------------------------------------------------------------------

export interface LogEntry {
  id: number
  message: string
  level: string
  timestamp: string
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

interface ReducerState {
  app: AppState
  logs: LogEntry[]
  debugMessages: Array<{ msg_type: string; summary: string; timestamp: string }>
  actuatorHistory: Array<Record<string, number>>
  batteryHistory: Array<{ t: number; voltage: number; current: number; soc: number }>
  engineHistory: Array<{ t: number; rpm: number; egt: number; fuelPump: number }>
  // Playback CSV metadata after the user uploads a file via the folder picker
  playbackCsvInfo: { path: string; filename: string; frames: number } | null
}

type Action =
  | { type: 'SYNC'; state: AppState }
  | { type: 'MSG'; msg: ServerMessage }
  | { type: 'CLEAR_LOGS' }

let logIdCounter = 0

function reducer(state: ReducerState, action: Action): ReducerState {
  switch (action.type) {
    case 'SYNC':
      return { ...state, app: action.state }

    case 'MSG': {
      const msg = action.msg
      switch (msg.type) {
        case 'state.sync':
          return { ...state, app: msg.data }

        case 'telemetry.actuator': {
          const sample: Record<string, number> = { t: Date.now() / 1000 }
          const surfKeys = [
            'left_elevon', 'right_elevon', 'dorsal_rudder', 'ventral_rudder',
            'left_tvc_upper', 'left_tvc_lower', 'right_tvc_upper', 'right_tvc_lower',
          ] as const
          for (const k of surfKeys) {
            const raw = (msg.data as Record<string, number | undefined>)[`${k}_feedback_cdeg`]
            if (typeof raw === 'number') sample[k] = raw / 100
          }
          return {
            ...state,
            app: { ...state.app, actuator: msg.data },
            actuatorHistory: [...state.actuatorHistory.slice(-119), sample],
          }
        }

        case 'telemetry.vehicle_status':
          return {
            ...state,
            app: {
              ...state.app,
              vehicle: { ...state.app.vehicle, ...msg.data },
            },
          }

        case 'telemetry.battery': {
          const d = msg.data
          return {
            ...state,
            batteryHistory: [...state.batteryHistory.slice(-119), {
              t: Date.now() / 1000,
              voltage: d.voltage_mV / 1000,
              current: d.current_cA / 100,
              soc: Math.max(0, Math.min(100, d.soc)),
            }],
          }
        }

        case 'telemetry.engine': {
          const d = msg.data
          return {
            ...state,
            engineHistory: [...state.engineHistory.slice(-119), {
              t: Date.now() / 1000,
              rpm: d.rpm,
              egt: d.egt_C,
              fuelPump: d.fuel_pump_mA,
            }],
          }
        }

        case 'ibit.state':
          return {
            ...state,
            app: {
              ...state.app,
              ibit: { ...state.app.ibit, substate: msg.data.substate },
            },
          }

        case 'ibit.mistracking':
          return {
            ...state,
            app: {
              ...state.app,
              ibit: { ...state.app.ibit, mistracking_flags: msg.data.flags },
            },
          }

        case 'test.log':
          return {
            ...state,
            logs: [
              ...state.logs.slice(-499),
              {
                id: ++logIdCounter,
                message: msg.data.message,
                level: msg.data.level,
                timestamp: msg.data.timestamp,
              },
            ],
          }

        case 'test.complete':
          return {
            ...state,
            app: {
              ...state.app,
              batch: { ...state.app.batch, active: false },
            },
          }

        case 'test.statistics':
          return {
            ...state,
            app: { ...state.app, statistics: msg.data },
          }

        case 'test.duration':
          return {
            ...state,
            app: {
              ...state.app,
              ibit: { ...state.app.ibit, duration_seconds: msg.data.seconds },
            },
          }

        case 'test.iteration':
          return state // handled via statistics

        case 'test.progress':
          return state // playback progress (store separately if needed)

        case 'test.status':
          return state // preparation status text

        case 'uut.update':
          return {
            ...state,
            app: { ...state.app, uuts: msg.data.uuts },
          }

        case 'daq.status':
          return {
            ...state,
            app: { ...state.app, daq: msg.data },
          }

        case 'daq.relay':
          return {
            ...state,
            app: {
              ...state.app,
              vehicle: { ...state.app.vehicle, relay_on: msg.data.on },
            },
          }

        case 'batch.status':
          return {
            ...state,
            app: { ...state.app, batch: msg.data },
          }

        case 'connection.health':
          return {
            ...state,
            app: {
              ...state.app,
              vehicle: {
                ...state.app.vehicle,
                connection_healthy: msg.data.healthy,
              },
            },
          }

        case 'alert':
          // Alerts shown via the AlertBanner component — add as a log too
          return {
            ...state,
            logs: [
              ...state.logs.slice(-499),
              {
                id: ++logIdCounter,
                message: `[${msg.data.severity.toUpperCase()}] ${msg.data.message}`,
                level: msg.data.severity,
                timestamp: new Date().toISOString(),
              },
            ],
          }

        case 'debug.message':
          return {
            ...state,
            debugMessages: [
              ...state.debugMessages.slice(-19),
              {
                msg_type: msg.data.msg_type,
                summary: msg.data.summary,
                timestamp: new Date().toLocaleTimeString('en-US', { hour12: false }),
              },
            ],
          }

        case 'error':
          return {
            ...state,
            logs: [
              ...state.logs.slice(-499),
              {
                id: ++logIdCounter,
                message: msg.data.message,
                level: 'error',
                timestamp: new Date().toISOString(),
              },
            ],
          }

        case 'playback.csv_uploaded':
          return {
            ...state,
            playbackCsvInfo: {
              path: msg.data.path,
              filename: msg.data.filename,
              frames: msg.data.frames,
            },
            logs: [
              ...state.logs.slice(-499),
              {
                id: ++logIdCounter,
                message: `Flight profile loaded: ${msg.data.filename} (${msg.data.frames} frames)`,
                level: 'info',
                timestamp: new Date().toISOString(),
              },
            ],
          }

        default:
          return state
      }
    }

    case 'CLEAR_LOGS':
      return { ...state, logs: [] }

    default:
      return state
  }
}

const INITIAL_STATE: ReducerState = {
  app: DEFAULT_APP_STATE,
  logs: [],
  debugMessages: [],
  actuatorHistory: [],
  batteryHistory: [],
  engineHistory: [],
  playbackCsvInfo: null,
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

const WS_URL = 'ws://localhost:18889'

export function useWebSocket() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE)
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected')
  const clientRef = useRef<WSClient | null>(null)

  useEffect(() => {
    const client = new WSClient({
      url: WS_URL,
      onMessage: (msg) => dispatch({ type: 'MSG', msg }),
      onStatusChange: setConnectionStatus,
      reconnectInterval: 1000,
      maxReconnectInterval: 10000,
    })

    clientRef.current = client
    client.connect()

    return () => {
      client.disconnect()
      clientRef.current = null
    }
  }, [])

  const send = useCallback((msg: ClientMessage) => {
    clientRef.current?.send(msg)
  }, [])

  const clearLogs = useCallback(() => {
    dispatch({ type: 'CLEAR_LOGS' })
  }, [])

  return {
    ...state.app,
    logs: state.logs,
    debugMessages: state.debugMessages,
    actuatorHistory: state.actuatorHistory,
    batteryHistory: state.batteryHistory,
    engineHistory: state.engineHistory,
    playbackCsvInfo: state.playbackCsvInfo,
    connectionStatus,
    send,
    clearLogs,
  }
}
