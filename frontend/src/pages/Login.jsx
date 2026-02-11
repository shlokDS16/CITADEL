import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import FloatingShapes from '../components/common/FloatingShapes';

export default function Login() {
  const [searchParams] = useSearchParams();
  const roleParam = searchParams.get('role') || 'government';
  const [isLogin, setIsLogin] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const { login, signup, isAuthenticated, isGovernment, isCitizen } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (isAuthenticated) {
      if (isGovernment) {
        navigate('/government/dashboard');
      } else if (isCitizen) {
        navigate('/citizen/dashboard');
      }
    }
  }, [isAuthenticated, isGovernment, isCitizen, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      // Store role before login
      localStorage.setItem('login_role', roleParam);

      const result = isLogin
        ? await login(username, password, roleParam)
        : await signup(username, password, roleParam);

      if (!result.success) {
        setError(result.error);
      }
    } catch (err) {
      setError('An unexpected error occurred');
    } finally {
      setLoading(false);
    }
  };

  const accentColor = roleParam === 'government' ? 'primary' : 'accent-pink';
  const shadowClass = roleParam === 'government' ? 'neo-shadow' : 'neo-shadow-pink';
  const hoverClass = roleParam === 'government' ? 'hover-collapse' : 'hover-collapse-pink';

  return (
    <div className="min-h-screen bg-background-light dark:bg-background-dark relative overflow-hidden">
      <FloatingShapes />

      <div className="relative z-10 container mx-auto px-8 py-16 min-h-screen flex flex-col items-center justify-center">
        {/* Back button */}
        <Link
          to="/"
          className="absolute top-8 left-8 px-4 py-2 bg-white dark:bg-black border-4 border-black neo-shadow-sm hover-collapse font-bold tight-caps text-sm transition-all"
        >
          ← BACK
        </Link>

        {/* Login Card */}
        <div className={`bg-white dark:bg-gray-900 border-4 border-black ${shadowClass} max-w-md w-full`}>
          <div className={`bg-${accentColor} px-8 py-6 border-b-4 border-black`}>
            <h2 className="text-3xl font-black tight-caps text-black">
              {roleParam === 'government' ? 'GOVERNMENT' : 'CITIZEN'} {isLogin ? 'LOGIN' : 'SIGNUP'}
            </h2>
          </div>

          <form onSubmit={handleSubmit} className="p-8">
            {error && (
              <div className="mb-6 p-4 bg-accent-pink border-4 border-black">
                <p className="text-sm font-bold text-black">{error}</p>
              </div>
            )}

            <div className="space-y-6">
              <div>
                <label className="block text-sm font-black tight-caps mb-2">USERNAME</label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  className="w-full px-4 py-3 bg-white dark:bg-gray-800 border-4 border-black font-mono focus:outline-none focus:ring-4 focus:ring-primary"
                  placeholder="Enter username"
                />
              </div>

              <div>
                <label className="block text-sm font-black tight-caps mb-2">PASSWORD</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="w-full px-4 py-3 bg-white dark:bg-gray-800 border-4 border-black font-mono focus:outline-none focus:ring-4 focus:ring-primary"
                  placeholder="Enter password"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className={`w-full px-6 py-4 bg-${accentColor} border-4 border-black ${shadowClass} ${hoverClass} font-black tight-caps text-black transition-all disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {loading ? 'PROCESSING...' : isLogin ? 'ACCESS SYSTEM' : 'CREATE ACCOUNT'}
              </button>
            </div>

            <div className="mt-6 text-center">
              <button
                type="button"
                onClick={() => {
                  setIsLogin(!isLogin);
                  setError('');
                }}
                className="text-sm font-bold uppercase text-gray-600 dark:text-gray-400 hover:text-black dark:hover:text-white transition-colors"
              >
                {isLogin ? 'Need an account? Sign up' : 'Already have an account? Login'}
              </button>
            </div>
          </form>

          <div className={`h-2 bg-${accentColor}`} />
        </div>

        <div className="mt-8 text-center text-xs font-mono text-gray-600 dark:text-gray-400">
          <p>SECURE CONNECTION • 256-BIT ENCRYPTION</p>
        </div>
      </div>
    </div>
  );
}
