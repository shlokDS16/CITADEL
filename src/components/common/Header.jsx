import { useAuth } from '../../context/AuthContext';
import { useNavigate } from 'react-router-dom';

export default function Header({ showNetworkStatus = false }) {
  const { user, logout, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  return (
    <header className="relative z-10 bg-white dark:bg-black border-b-4 border-black px-8 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-6">
          <h1 className="text-3xl font-roboto tight-caps">
            <span className="text-primary">CITADEL</span>
            <span className="text-black dark:text-white">_OS</span>
          </h1>

          {showNetworkStatus && (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 px-3 py-1 bg-terminal-green border-2 border-black">
                <div className="w-2 h-2 bg-black rounded-full animate-pulse-slow" />
                <span className="text-xs font-mono font-bold text-black">NETWORK: ACTIVE</span>
              </div>
              <div className="flex items-center gap-2 px-3 py-1 bg-accent-cyan border-2 border-black">
                <div className="w-2 h-2 bg-black rounded-full" />
                <span className="text-xs font-mono font-bold text-black">SECURE</span>
              </div>
            </div>
          )}
        </div>

        {isAuthenticated && (
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-sm font-bold tight-caps">{user?.username}</div>
              <div className="text-xs text-gray-600 dark:text-gray-400 uppercase">
                {user?.role === 'government' ? 'OFFICIAL' : 'CITIZEN'}
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="px-4 py-2 bg-accent-pink border-4 border-black neo-shadow-sm hover-collapse-pink font-bold tight-caps text-sm transition-all"
            >
              LOGOUT
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
