/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // ── Base backgrounds ─────────────────────────────────
        'bg-base':     '#0D1117',
        'bg-surface':  '#161B22',
        'bg-elevated': '#21262D',
        'bg-hover':    '#30363D',

        // ── Borders ──────────────────────────────────────────
        border:        '#30363D',
        'border-focus':'#58A6FF',

        // ── Text ─────────────────────────────────────────────
        'text-primary':   '#E6EDF3',
        'text-secondary': '#8B949E',
        'text-disabled':  '#484F58',

        // ── Semantic / status ────────────────────────────────
        green:      '#3FB950',
        'green-dim':'#1A3D22',
        amber:      '#D29922',
        'amber-dim':'#3D2F0A',
        red:        '#F85149',
        'red-dim':  '#3D1212',
        blue:       '#58A6FF',
        'blue-dim': '#0C2A4A',
        purple:     '#BC8CFF',
        'purple-dim':'#2A1A3D',
        teal:       '#39D353',
        orange:     '#E3B341',

        // ── Button accents ───────────────────────────────────
        'btn-primary':      '#238636',
        'btn-primary-hover':'#2EA043',
        'btn-danger':       '#DA3633',
        'btn-danger-hover': '#F85149',
        'btn-emrg':         '#B91C1C',
        'btn-emrg-hover':   '#DC2626',
        'btn-neutral':      '#21262D',
        'btn-neutral-hover':'#30363D',
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'Courier New', 'monospace'],
      },
      fontSize: {
        'xs':  ['0.75rem',  { lineHeight: '1rem'   }],
        'sm':  ['0.8125rem',{ lineHeight: '1.25rem' }],
        'base':['0.875rem', { lineHeight: '1.375rem'}],
        'lg':  ['1rem',     { lineHeight: '1.5rem'  }],
        'xl':  ['1.125rem', { lineHeight: '1.75rem' }],
        '2xl': ['1.25rem',  { lineHeight: '1.75rem' }],
        '3xl': ['1.5rem',   { lineHeight: '2rem'    }],
      },
      borderRadius: {
        DEFAULT: '6px',
        'sm': '4px',
        'md': '6px',
        'lg': '8px',
        'xl': '12px',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'led-pulse':  'led-pulse 2s ease-in-out infinite',
        'slide-down': 'slide-down 0.3s ease-out',
        'slide-up':   'slide-up 0.3s ease-out',
        'fade-in':    'fade-in 0.2s ease-out',
        'glow-red':   'glow-red 2s ease-in-out infinite',
      },
      keyframes: {
        'led-pulse': {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.5' },
        },
        'slide-down': {
          '0%':   { transform: 'translateY(-100%)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'slide-up': {
          '0%':   { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'glow-red': {
          '0%, 100%': { boxShadow: '0 0 8px rgba(248, 81, 73, 0.4)' },
          '50%':      { boxShadow: '0 0 20px rgba(248, 81, 73, 0.8)' },
        },
      },
    },
  },
  plugins: [],
}
