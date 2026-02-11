# C.I.T.A.D.E.L. Frontend

> **Centralized Intelligence & Technology Administration Dashboard for Enhanced Living**

A sophisticated React-based frontend for the C.I.T.A.D.E.L. municipal platform, featuring neo-brutalist design, 3D card effects, and comprehensive AI-powered modules for both government officials and citizens.

## 🎨 Design Features

- **Neo-Brutalist Aesthetic**: Bold black borders, heavy shadows, and striking color contrasts
- **3D Transform Effects**: Tilted cards with perspective transforms and smooth hover interactions
- **Animated Elements**: Floating geometric shapes, loading animations, and smooth transitions
- **Responsive Layout**: Optimized for desktop and mobile viewing
- **Dark Mode Ready**: Full dark mode support with seamless transitions

## 🏗️ Architecture

### Pages
- **Portal Selection**: Landing page with government/citizen portal choice
- **Login/Signup**: Authentication with role-based access
- **Government Dashboard**: 4-module grid with system monitoring
- **Citizen Dashboard**: User-friendly service access portal

### Government Modules
1. **Document Intelligence** (GATEWAY_01) - AI document analysis and data extraction
2. **Resume Screening** (GATEWAY_02) - Automated candidate evaluation
3. **Traffic Violations** (GATEWAY_03) - Video-based violation detection
4. **Anomaly Monitoring** (GATEWAY_04) - Infrastructure anomaly detection

### Citizen Modules
1. **RAG Chatbot** (GATEWAY_01) - AI assistant with government knowledge base
2. **Fake News Detector** (GATEWAY_02) - News authenticity verification
3. **Support Tickets** (GATEWAY_03) - AI-powered ticket routing
4. **Expense Categorizer** (GATEWAY_04) - Receipt analysis and tracking

## 🚀 Quick Start

### Prerequisites
- Node.js 18+
- npm or yarn
- Backend API running (see backend README)

### Installation

1. **Clone and navigate to the frontend directory:**
   ```bash
   cd citadel-frontend
   ```

2. **Install dependencies:**
   ```bash
   npm install
   ```

3. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```

   Edit `.env` to point to your backend:
   ```env
   VITE_API_URL=http://localhost:8000
   ```

4. **Start the development server:**
   ```bash
   npm run dev
   ```

5. **Open your browser:**
   - Navigate to `http://localhost:5173`
   - Select Government or Citizen portal
   - Sign up or log in to access modules

## 🛠️ Available Scripts

- `npm run dev` - Start development server with hot reload
- `npm run build` - Build production-ready bundle
- `npm run preview` - Preview production build locally
- `npm run lint` - Run ESLint for code quality

## 📦 Tech Stack

- **React 18** - UI library
- **Vite** - Build tool and dev server
- **React Router** - Client-side routing
- **Tailwind CSS** - Utility-first styling
- **Axios** - HTTP client for API calls

## 🎯 Key Features

### Authentication & Authorization
- Role-based access control (Government/Citizen)
- Protected routes with automatic redirects
- Session persistence via localStorage
- Secure token-based authentication

### UI Components
- **ModuleCard** - Reusable 3D-tilted module cards
- **FloatingShapes** - Animated background elements
- **ProgressBar** - Animated progress indicators
- **TerminalDisplay** - Monospace terminal-style displays
- **StatusWidget** - Real-time system status monitoring

### API Integration
- Automatic auth header injection
- File upload support (documents, videos, images)
- Error handling with user-friendly messages
- Loading states for all async operations

## 🎨 Color Palette

```css
--primary: #e9b50b        /* Yellow - Government primary */
--accent-pink: #ff184c     /* Pink - Citizen primary */
--accent-cyan: #00d9ff     /* Cyan - Traffic/Support */
--accent-purple: #d946ef   /* Purple - Anomaly/Expense */
--terminal-green: #00ff00  /* Green - Success/Terminal */
--background-light: #f0f0f0
--background-dark: #1a1814
```

## 📐 Project Structure

```
citadel-frontend/
├── public/              # Static assets
├── src/
│   ├── components/
│   │   ├── common/      # Reusable components
│   │   ├── government/  # Government module components
│   │   └── citizen/     # Citizen module components
│   ├── pages/           # Top-level page components
│   ├── context/         # React context providers
│   ├── services/        # API service layer
│   ├── App.jsx          # Root component with routing
│   ├── main.jsx         # Application entry point
│   └── index.css        # Global styles & utilities
├── tailwind.config.js   # Tailwind configuration
├── vite.config.js       # Vite configuration
└── package.json         # Dependencies and scripts
```

## 🔒 Security Features

- Role-based route protection
- XSS protection via React's built-in escaping
- Secure authentication token handling
- Input validation on all forms
- CORS-compliant API requests

## 🌐 Browser Support

- Chrome/Edge (latest 2 versions)
- Firefox (latest 2 versions)
- Safari (latest 2 versions)

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Kill process on port 5173
npx kill-port 5173
```

### API Connection Issues
1. Verify backend is running: `http://localhost:8000/docs`
2. Check `.env` file has correct `VITE_API_URL`
3. Ensure no CORS issues (backend should allow your origin)

### Build Errors
```bash
# Clear node modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

## 📝 Development Guidelines

### Adding New Modules
1. Create component in `src/components/government/` or `src/components/citizen/`
2. Add route in `src/App.jsx`
3. Add ModuleCard to dashboard
4. Implement API endpoints in `src/services/api.js`

### Styling Conventions
- Use Tailwind utility classes
- Apply neo-brutalist shadows: `neo-shadow`, `neo-shadow-pink`, etc.
- Use 3D tilts: `tilted-card-left`, `tilted-card-right`
- Follow tight-caps typography: `tight-caps` class

## 🎓 Learning Resources

- [React Documentation](https://react.dev)
- [Tailwind CSS Docs](https://tailwindcss.com/docs)
- [Vite Guide](https://vitejs.dev/guide/)
- [React Router](https://reactrouter.com)

## 📄 License

Part of the C.I.T.A.D.E.L. municipal platform project.

## 🤝 Contributing

1. Create feature branch
2. Follow existing code style
3. Test all modules thoroughly
4. Submit pull request with description

---

**Built with React + Vite + Tailwind CSS**
