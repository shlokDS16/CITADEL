import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useEffect } from 'react';
import FloatingShapes from '../components/common/FloatingShapes';

export default function PortalSelection() {
  const navigate = useNavigate();
  const { isAuthenticated, isGovernment, isCitizen } = useAuth();

  useEffect(() => {
    if (isAuthenticated) {
      if (isGovernment) {
        navigate('/government/dashboard');
      } else if (isCitizen) {
        navigate('/citizen/dashboard');
      }
    }
  }, [isAuthenticated, isGovernment, isCitizen, navigate]);

  return (
    <div className="min-h-screen bg-background-light dark:bg-background-dark relative overflow-hidden">
      <FloatingShapes />

      <div className="relative z-10 container mx-auto px-8 py-16 min-h-screen flex flex-col">
        {/* Header */}
        <div className="text-center mb-16">
          <h1 className="text-6xl md:text-8xl font-roboto tight-caps mb-4">
            <span className="text-primary">C.I.T.A.D.E.L.</span>
          </h1>
          <p className="text-xl font-bold uppercase tracking-wide">
            Centralized Intelligence & Technology
          </p>
          <p className="text-lg font-bold uppercase tracking-wide text-gray-600 dark:text-gray-400">
            Administration Dashboard for Enhanced Living
          </p>
        </div>

        {/* Portal Cards */}
        <div className="flex-1 flex items-center justify-center">
          <div className="grid md:grid-cols-2 gap-16 md:gap-24 max-w-5xl w-full">
            {/* Government Portal */}
            <div
              onClick={() => navigate('/login?role=government')}
              className="tilted-card-left hover-tilt-reduce bg-white dark:bg-gray-900 border-4 border-black neo-shadow hover-collapse cursor-pointer transition-all duration-300 group"
            >
              <div className="bg-primary px-8 py-6 border-b-4 border-black skewed-header">
                <h2 className="text-3xl font-black tight-caps text-black">GOVERNMENT</h2>
              </div>

              <div className="p-12">
                <div className="text-center mb-8">
                  <span className="material-symbols-outlined text-primary" style={{ fontSize: '6rem' }}>
                    shield
                  </span>
                </div>

                <div className="space-y-4 mb-8">
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 bg-primary" />
                    <span className="text-sm font-bold uppercase">Document Intelligence</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 bg-primary" />
                    <span className="text-sm font-bold uppercase">Resume Screening</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 bg-primary" />
                    <span className="text-sm font-bold uppercase">Traffic Violations</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 bg-primary" />
                    <span className="text-sm font-bold uppercase">Infrastructure Monitoring</span>
                  </div>
                </div>

                <div className="text-center">
                  <div className="inline-block px-6 py-3 bg-primary border-4 border-black font-black tight-caps text-black group-hover:bg-black group-hover:text-primary transition-colors">
                    ACCESS PORTAL
                  </div>
                </div>
              </div>

              <div className="h-2 bg-primary" />
            </div>

            {/* Citizen Portal */}
            <div
              onClick={() => navigate('/login?role=citizen')}
              className="tilted-card-right hover-tilt-reduce bg-white dark:bg-gray-900 border-4 border-black neo-shadow-pink hover-collapse-pink cursor-pointer transition-all duration-300 group"
            >
              <div className="bg-accent-pink px-8 py-6 border-b-4 border-black skewed-header">
                <h2 className="text-3xl font-black tight-caps text-black">CITIZEN</h2>
              </div>

              <div className="p-12">
                <div className="text-center mb-8">
                  <span className="material-symbols-outlined text-accent-pink" style={{ fontSize: '6rem' }}>
                    groups
                  </span>
                </div>

                <div className="space-y-4 mb-8">
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 bg-accent-pink" />
                    <span className="text-sm font-bold uppercase">AI Chatbot Assistant</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 bg-accent-pink" />
                    <span className="text-sm font-bold uppercase">Fake News Detection</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 bg-accent-pink" />
                    <span className="text-sm font-bold uppercase">Support Tickets</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 bg-accent-pink" />
                    <span className="text-sm font-bold uppercase">Expense Management</span>
                  </div>
                </div>

                <div className="text-center">
                  <div className="inline-block px-6 py-3 bg-accent-pink border-4 border-black font-black tight-caps text-black group-hover:bg-black group-hover:text-accent-pink transition-colors">
                    ACCESS PORTAL
                  </div>
                </div>
              </div>

              <div className="h-2 bg-accent-pink" />
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="text-center mt-16 text-sm font-mono text-gray-600 dark:text-gray-400">
          <p>SECURE AUTHENTICATION REQUIRED • AUTHORIZED PERSONNEL ONLY</p>
        </div>
      </div>
    </div>
  );
}
