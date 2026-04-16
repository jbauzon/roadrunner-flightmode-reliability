import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Merge Tailwind classes with clsx for conditional class composition. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format a duration in seconds as MM:SS. */
export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** Format a duration in seconds as a human-readable string. */
export function formatDurationLong(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}m ${s}s`
  }
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

/** Format a timestamp as HH:MM:SS. */
export function formatTime(date: Date = new Date()): string {
  return date.toLocaleTimeString('en-US', { hour12: false })
}

/** Format a timestamp as YYYY-MM-DD HH:MM:SS. */
export function formatDateTime(date: Date = new Date()): string {
  return date.toISOString().replace('T', '  ').slice(0, 21)
}
