# C.I.T.A.D.E.L. Frontend - Quick Start Guide

## ✅ Build Status: SUCCESS

The production build has been successfully tested and generated in the `dist/` folder.

## 🚀 Running the Application

### 1. Start the Development Server

```bash
cd citadel-frontend
npm run dev
```

The app will be available at: **http://localhost:5173**

### 2. Configure Backend Connection

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and set your backend URL:
```
VITE_API_URL=http://localhost:8000
```

### 3. Access the Application

Open your browser and navigate to `http://localhost:5173`

You'll see the **Portal Selection** screen with two options:
- **Government Portal** (Yellow) - For government officials
- **Citizen Portal** (Pink) - For citizens

## 🎯 Testing the Application

### Government Portal Flow:
1. Click "Government" card
2. Sign up with any username/password
3. Access the dashboard with 4 modules:
   - Document Intelligence
   - Resume Screening
   - Traffic Violations
   - Infrastructure Anomaly Monitoring
4. Click any module to test its functionality

### Citizen Portal Flow:
1. Click "Citizen" card
2. Sign up with any username/password
3. Access the dashboard with 4 modules:
   - RAG Chatbot
   - Fake News Detector
   - Support Tickets
   - Expense Categorizer
4. Click any module to test its functionality

## 📦 What's Built

### Core Files:
- ✅ **13 Pages & Components**
  - Portal Selection
  - Login/Signup
  - Government Dashboard
  - Citizen Dashboard
  - 4 Government modules
  - 4 Citizen modules

- ✅ **6 Reusable Components**
  - Header with authentication
  - FloatingShapes (animated background)
  - ModuleCard (3D-tilted cards)
  - ProgressBar (animated)
  - TerminalDisplay
  - StatusWidget

- ✅ **Complete API Integration**
  - Authentication (login/signup)
  - 8 module endpoints
  - File upload support
  - Error handling
  - Loading states

- ✅ **Routing & Security**
  - Protected routes
  - Role-based access control
  - Session persistence
  - Automatic redirects

### Design Features:
- ✨ Neo-brutalist aesthetic (bold borders, heavy shadows)
- ✨ 3D transform effects on cards
- ✨ Animated floating shapes in background
- ✨ Color-coded modules (yellow, pink, cyan, purple)
- ✨ Terminal-style displays with green text
- ✨ Responsive layout
- ✨ Dark mode support

## 🎨 Visual Highlights

### Color System:
- **Yellow (#e9b50b)** - Government primary
- **Pink (#ff184c)** - Citizen primary
- **Cyan (#00d9ff)** - Traffic/Support modules
- **Purple (#d946ef)** - Anomaly/Expense modules
- **Green (#00ff00)** - Terminal displays

### Typography:
- **Space Grotesk** - Primary UI font
- **Roboto Black (900)** - Large numbers/headings
- **JetBrains Mono** - Terminal/code displays

## 🧪 Production Build

To create a production build:

```bash
npm run build
```

Output will be in `dist/` folder:
- `index.html` - 0.46 KB
- `assets/index-[hash].css` - 19.65 KB (4.56 KB gzipped)
- `assets/index-[hash].js` - 344.34 KB (100.73 KB gzipped)

To preview the production build locally:

```bash
npm run preview
```

## 📝 Notes

1. **Backend Required**: The frontend expects a backend API at the URL specified in `.env`
   - Default: `http://localhost:8000`
   - Ensure CORS is configured on the backend to allow frontend origin

2. **Authentication**:
   - Uses localStorage for session persistence
   - No actual email verification (for demo purposes)
   - Any username/password works for signup

3. **File Uploads**:
   - Document Intelligence: PDF, JPG, PNG
   - Resume Screening: PDF, DOC, DOCX
   - Traffic Violations: MP4, AVI, MOV
   - Expense Categorizer: JPG, PNG

4. **Browser Support**:
   - Chrome/Edge (latest)
   - Firefox (latest)
   - Safari (latest)

## 🐛 Common Issues

**Port 5173 already in use:**
```bash
npx kill-port 5173
npm run dev
```

**API connection errors:**
- Verify backend is running at the URL in `.env`
- Check browser console for CORS errors
- Ensure backend has proper CORS configuration

**Build errors:**
```bash
rm -rf node_modules package-lock.json
npm install
npm run build
```

## 🎯 Next Steps

1. Start the backend server (see backend README)
2. Run `npm run dev` in this directory
3. Open `http://localhost:5173` in your browser
4. Test both Government and Citizen portals
5. Upload sample files to test each module

---

**Ready to launch! 🚀**
