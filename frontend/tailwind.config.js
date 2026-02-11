/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'primary': '#e9b50b',
        'accent-pink': '#ff184c',
        'accent-cyan': '#00d9ff',
        'accent-purple': '#d946ef',
        'background-light': '#f0f0f0',
        'background-dark': '#1a1814',
        'terminal-green': '#00ff00',
      },
      fontFamily: {
        'display': ['Space Grotesk', 'sans-serif'],
        'roboto': ['Roboto', 'sans-serif'],
        'mono': ['JetBrains Mono', 'Courier New', 'monospace'],
      },
      borderWidth: {
        '4': '4px',
        '6': '6px',
      },
      animation: {
        'float': 'float 6s ease-in-out infinite',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'loading': 'loading-sweep 2s ease-in-out infinite',
      },
      keyframes: {
        float: {
          '0%': { transform: 'translateY(0px) rotate(0deg)' },
          '50%': { transform: 'translateY(-20px) rotate(5deg)' },
          '100%': { transform: 'translateY(0px) rotate(0deg)' },
        },
        'loading-sweep': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(400%)' },
        },
      },
    },
  },
  plugins: [],
}
