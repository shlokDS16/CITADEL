import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';

// Pages
import PortalSelection from './pages/PortalSelection';
import Login from './pages/Login';
import GovernmentDashboard from './pages/GovernmentDashboard';
import CitizenDashboard from './pages/CitizenDashboard';

// Government Components
import DocumentIntelligence from './components/government/DocumentIntelligence';
import ResumeScreening from './components/government/ResumeScreening';
import TrafficViolations from './components/government/TrafficViolations';
import AnomalyMonitoring from './components/government/AnomalyMonitoring';

// Citizen Components
import RAGChatbot from './components/citizen/RAGChatbot';
import FakeNewsDetector from './components/citizen/FakeNewsDetector';
import SupportTickets from './components/citizen/SupportTickets';
import ExpenseCategorizer from './components/citizen/ExpenseCategorizer';

// Protected Route Component
function ProtectedRoute({ children, requireRole }) {
  const { isAuthenticated, user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-background-light dark:bg-background-dark flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block w-16 h-16 border-4 border-primary border-t-transparent rounded-full animate-spin mb-4" />
          <p className="text-sm font-black tight-caps">LOADING...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (requireRole && user?.role !== requireRole) {
    // Redirect to appropriate dashboard if wrong role
    const dashboardPath = user?.role === 'government' ? '/government/dashboard' : '/citizen/dashboard';
    return <Navigate to={dashboardPath} replace />;
  }

  return children;
}

function AppRoutes() {
  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/" element={<PortalSelection />} />
      <Route path="/login" element={<Login />} />

      {/* Government Routes */}
      <Route
        path="/government/dashboard"
        element={
          <ProtectedRoute requireRole="government">
            <GovernmentDashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/government/document-intelligence"
        element={
          <ProtectedRoute requireRole="government">
            <DocumentIntelligence />
          </ProtectedRoute>
        }
      />
      <Route
        path="/government/resume-screening"
        element={
          <ProtectedRoute requireRole="government">
            <ResumeScreening />
          </ProtectedRoute>
        }
      />
      <Route
        path="/government/traffic-violations"
        element={
          <ProtectedRoute requireRole="government">
            <TrafficViolations />
          </ProtectedRoute>
        }
      />
      <Route
        path="/government/anomaly-monitoring"
        element={
          <ProtectedRoute requireRole="government">
            <AnomalyMonitoring />
          </ProtectedRoute>
        }
      />

      {/* Citizen Routes */}
      <Route
        path="/citizen/dashboard"
        element={
          <ProtectedRoute requireRole="citizen">
            <CitizenDashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/citizen/chatbot"
        element={
          <ProtectedRoute requireRole="citizen">
            <RAGChatbot />
          </ProtectedRoute>
        }
      />
      <Route
        path="/citizen/fake-news"
        element={
          <ProtectedRoute requireRole="citizen">
            <FakeNewsDetector />
          </ProtectedRoute>
        }
      />
      <Route
        path="/citizen/support-tickets"
        element={
          <ProtectedRoute requireRole="citizen">
            <SupportTickets />
          </ProtectedRoute>
        }
      />
      <Route
        path="/citizen/expense-categorizer"
        element={
          <ProtectedRoute requireRole="citizen">
            <ExpenseCategorizer />
          </ProtectedRoute>
        }
      />

      {/* Catch all - redirect to home */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <Router>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </Router>
  );
}

export default App;
