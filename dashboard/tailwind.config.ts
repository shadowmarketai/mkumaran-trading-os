import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        trading: {
          bg: '#060A14',
          'bg-secondary': '#0A1020',
          card: '#0F1729',
          'card-hover': '#162036',
          'card-active': '#1A2842',
          border: '#1B2845',
          'border-light': '#243352',
          bull: '#00E676',
          'bull-light': '#69F0AE',
          'bull-dim': '#00E676',
          bear: '#FF1744',
          'bear-light': '#FF5252',
          'bear-dark': '#D50000',
          info: '#00E5FF',
          'info-light': '#18FFFF',
          'info-dim': '#006064',
          alert: '#FFAB00',
          gold: '#FFD600',
          ai: '#7C4DFF',
          'ai-light': '#B388FF',
          'ai-dim': '#311B92',
          accent: '#448AFF',
          'accent-light': '#82B1FF',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'SF Mono', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'glow-bull': 'radial-gradient(ellipse at center, rgba(0,230,118,0.15) 0%, transparent 70%)',
        'glow-bear': 'radial-gradient(ellipse at center, rgba(255,23,68,0.15) 0%, transparent 70%)',
        'glow-ai': 'radial-gradient(ellipse at center, rgba(124,77,255,0.15) 0%, transparent 70%)',
        'mesh-gradient': 'radial-gradient(at 0% 0%, rgba(124,77,255,0.08) 0%, transparent 50%), radial-gradient(at 100% 100%, rgba(0,230,118,0.05) 0%, transparent 50%)',
        'card-gradient': 'linear-gradient(135deg, rgba(15,23,41,0.95) 0%, rgba(10,16,32,0.98) 100%)',
        'sidebar-gradient': 'linear-gradient(180deg, rgba(10,16,32,1) 0%, rgba(6,10,20,1) 100%)',
      },
      boxShadow: {
        'glow-bull': '0 0 20px rgba(0,230,118,0.15), 0 0 60px rgba(0,230,118,0.05)',
        'glow-bear': '0 0 20px rgba(255,23,68,0.15), 0 0 60px rgba(255,23,68,0.05)',
        'glow-ai': '0 0 20px rgba(124,77,255,0.2), 0 0 60px rgba(124,77,255,0.08)',
        'glow-info': '0 0 20px rgba(0,229,255,0.15), 0 0 60px rgba(0,229,255,0.05)',
        'card': '0 4px 24px -4px rgba(0,0,0,0.4), 0 0 0 1px rgba(27,40,69,0.5)',
        'card-hover': '0 8px 32px -4px rgba(0,0,0,0.5), 0 0 0 1px rgba(36,51,82,0.6)',
        'elevated': '0 16px 48px -8px rgba(0,0,0,0.6)',
        'inner-glow': 'inset 0 1px 0 0 rgba(255,255,255,0.05)',
      },
      animation: {
        'pulse-bull': 'pulseBull 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-bear': 'pulseBear 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-live': 'pulseLive 2s ease-in-out infinite',
        'slide-up': 'slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-down': 'slideDown 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'fade-in': 'fadeIn 0.5s ease-out',
        'shimmer': 'shimmer 2s linear infinite',
        'glow-pulse': 'glowPulse 3s ease-in-out infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        pulseBull: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(0,230,118,0.4)' },
          '50%': { boxShadow: '0 0 0 8px rgba(0,230,118,0)' },
        },
        pulseBear: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(255,23,68,0.4)' },
          '50%': { boxShadow: '0 0 0 8px rgba(255,23,68,0)' },
        },
        pulseLive: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        slideUp: {
          '0%': { transform: 'translateY(12px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideDown: {
          '0%': { transform: 'translateY(-8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        glowPulse: {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-4px)' },
        },
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
    },
  },
  plugins: [],
} satisfies Config;
