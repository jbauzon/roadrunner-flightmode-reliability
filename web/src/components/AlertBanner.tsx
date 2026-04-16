import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle, X } from 'lucide-react'

interface AlertBannerProps {
  alert: { message: string; severity: string } | null
  onDismiss: () => void
}

const severityStyles: Record<string, string> = {
  info:     'bg-blue-dim border-blue text-blue',
  warning:  'bg-amber-dim border-amber text-amber',
  error:    'bg-red-dim border-red text-red',
  critical: 'bg-red-dim border-red text-red',
}

export function AlertBanner({ alert, onDismiss }: AlertBannerProps) {
  return (
    <AnimatePresence>
      {alert && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.3 }}
          className="overflow-hidden shrink-0"
        >
          <div
            className={`
              flex items-center gap-3 px-4 py-2.5 border-b
              ${severityStyles[alert.severity] ?? severityStyles.warning}
            `}
          >
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span className="text-sm font-medium flex-1">{alert.message}</span>
            <button
              onClick={onDismiss}
              className="p-1 rounded hover:bg-white/10 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
