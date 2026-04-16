/**
 * Electron main process.
 *
 * - Spawns the Python WebSocket backend (ws_server.py) as a child process
 * - Waits for the WebSocket to become available
 * - Creates a BrowserWindow loading the Vite dev server (dev) or bundled HTML (prod)
 * - Kills the Python process on window close
 */

import { app, BrowserWindow, shell } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import net from 'net'

const WS_PORT = 18889
const DEV_SERVER_URL = 'http://localhost:5173'
let pythonProcess: ChildProcess | null = null
let mainWindow: BrowserWindow | null = null

// ---------------------------------------------------------------------------
// Python backend lifecycle
// ---------------------------------------------------------------------------

function startPythonBackend(): void {
  const projectRoot = path.resolve(__dirname, '..', '..')
  const wsServer = path.join(projectRoot, 'ws_server.py')

  console.log(`Starting Python backend: ${wsServer}`)
  pythonProcess = spawn('python', [wsServer], {
    cwd: projectRoot,
    stdio: ['pipe', 'pipe', 'pipe'],
  })

  pythonProcess.stdout?.on('data', (data: Buffer) => {
    console.log(`[python] ${data.toString().trim()}`)
  })

  pythonProcess.stderr?.on('data', (data: Buffer) => {
    console.error(`[python] ${data.toString().trim()}`)
  })

  pythonProcess.on('close', (code: number | null) => {
    console.log(`Python backend exited with code ${code}`)
    pythonProcess = null
  })
}

function stopPythonBackend(): void {
  if (pythonProcess) {
    console.log('Stopping Python backend...')
    pythonProcess.kill('SIGTERM')
    // Force kill after 3 seconds if still alive
    setTimeout(() => {
      if (pythonProcess && !pythonProcess.killed) {
        pythonProcess.kill('SIGKILL')
      }
    }, 3000)
  }
}

// ---------------------------------------------------------------------------
// Wait for WebSocket port to become available
// ---------------------------------------------------------------------------

function waitForPort(port: number, timeout: number = 15000): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now()

    function tryConnect() {
      const socket = new net.Socket()
      socket.setTimeout(1000)

      socket.on('connect', () => {
        socket.destroy()
        resolve()
      })

      socket.on('error', () => {
        socket.destroy()
        if (Date.now() - start > timeout) {
          reject(new Error(`Timeout waiting for port ${port}`))
        } else {
          setTimeout(tryConnect, 500)
        }
      })

      socket.on('timeout', () => {
        socket.destroy()
        if (Date.now() - start > timeout) {
          reject(new Error(`Timeout waiting for port ${port}`))
        } else {
          setTimeout(tryConnect, 500)
        }
      })

      socket.connect(port, '127.0.0.1')
    }

    tryConnect()
  })
}

// ---------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1800,
    height: 1000,
    minWidth: 1400,
    minHeight: 820,
    title: 'Roadrunner Flight Test v5.0.0',
    backgroundColor: '#0D1117',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
    autoHideMenuBar: true,
  })

  // In development, load the Vite dev server
  // In production, load the built index.html
  const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged

  if (isDev) {
    mainWindow.loadURL(DEV_SERVER_URL)
    // mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }

  // Open external links in the system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  startPythonBackend()

  try {
    console.log(`Waiting for WebSocket server on port ${WS_PORT}...`)
    await waitForPort(WS_PORT)
    console.log('WebSocket server ready')
  } catch (err) {
    console.error('Failed to start Python backend:', err)
    // Create the window anyway — it will show the "disconnected" state
  }

  createWindow()
})

app.on('window-all-closed', () => {
  stopPythonBackend()
  app.quit()
})

app.on('before-quit', () => {
  stopPythonBackend()
})
