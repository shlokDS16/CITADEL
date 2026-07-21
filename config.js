// Deploy-time backend endpoint override (loaded before components.jsx).
//
// Local dev: leave this empty — the app defaults to http://127.0.0.1:8000.
// Hosted (e.g. Vercel frontend → ngrok/Render backend): the deploy bundle
// ships a config.js where this string is the public backend URL, e.g.
//   window.CITADEL_API_BASE = 'https://xxxx.ngrok-free.app';
window.CITADEL_API_BASE = window.CITADEL_API_BASE || '';
