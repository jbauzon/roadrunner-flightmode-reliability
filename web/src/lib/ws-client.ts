/**
 * ws-client.ts — WebSocket client singleton with auto-reconnect.
 *
 * Manages the connection lifecycle to the Python backend.
 * All React state updates flow through the message callback.
 */

import type { ClientMessage, ServerMessage } from './types'

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

export interface WSClientOptions {
  url: string
  onMessage: (msg: ServerMessage) => void
  onStatusChange: (status: ConnectionStatus) => void
  reconnectInterval?: number
  maxReconnectInterval?: number
}

export class WSClient {
  private ws: WebSocket | null = null
  private options: WSClientOptions
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private currentInterval: number
  private intentionalClose = false

  constructor(options: WSClientOptions) {
    this.options = options
    this.currentInterval = options.reconnectInterval ?? 1000
  }

  connect(): void {
    this.intentionalClose = false
    this.options.onStatusChange('connecting')

    try {
      this.ws = new WebSocket(this.options.url)
    } catch {
      this.options.onStatusChange('error')
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.options.onStatusChange('connected')
      this.currentInterval = this.options.reconnectInterval ?? 1000

      // Request full state sync on connect
      this.send({ type: 'cmd.sync_state' })
    }

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as ServerMessage
        this.options.onMessage(msg)
      } catch {
        // Ignore malformed messages
      }
    }

    this.ws.onclose = () => {
      this.options.onStatusChange('disconnected')
      if (!this.intentionalClose) {
        this.scheduleReconnect()
      }
    }

    this.ws.onerror = () => {
      this.options.onStatusChange('error')
    }
  }

  send(msg: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  disconnect(): void {
    this.intentionalClose = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.options.onStatusChange('disconnected')
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  private scheduleReconnect(): void {
    if (this.intentionalClose) return
    if (this.reconnectTimer) return

    const maxInterval = this.options.maxReconnectInterval ?? 10000
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, this.currentInterval)

    // Exponential backoff capped at maxInterval
    this.currentInterval = Math.min(this.currentInterval * 1.5, maxInterval)
  }
}
