import { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check for existing session
    const userId = localStorage.getItem('user_id');
    const userRole = localStorage.getItem('user_role');
    const username = localStorage.getItem('username');

    if (userId && userRole) {
      setUser({
        id: userId,
        role: userRole,
        username: username || 'User',
      });
    }
    setLoading(false);
  }, []);

  const login = async (username, password, role) => {
    try {
      // Client-side login for demo - accept any credentials
      const loginRole = role || localStorage.getItem('login_role') || 'citizen';
      const data = {
        user_id: `user_${Date.now()}`,
        role: loginRole,
        session_id: `session_${Date.now()}`,
      };

      localStorage.setItem('user_id', data.user_id);
      localStorage.setItem('user_role', data.role);
      localStorage.setItem('session_id', data.session_id);
      localStorage.setItem('username', username);

      setUser({
        id: data.user_id,
        role: data.role,
        username: username,
      });

      return { success: true };
    } catch (error) {
      console.error('Login error:', error);
      return {
        success: false,
        error: 'Login failed',
      };
    }
  };

  const signup = async (username, password, role) => {
    try {
      const data = {
        user_id: `user_${Date.now()}`,
        role: role,
        session_id: `session_${Date.now()}`,
      };

      localStorage.setItem('user_id', data.user_id);
      localStorage.setItem('user_role', data.role);
      localStorage.setItem('session_id', data.session_id);
      localStorage.setItem('username', username);

      setUser({
        id: data.user_id,
        role: data.role,
        username: username,
      });

      return { success: true };
    } catch (error) {
      console.error('Signup error:', error);
      return {
        success: false,
        error: 'Signup failed',
      };
    }
  };

  const logout = () => {
    localStorage.removeItem('user_id');
    localStorage.removeItem('user_role');
    localStorage.removeItem('session_id');
    localStorage.removeItem('username');
    localStorage.removeItem('login_role');
    setUser(null);
  };

  const value = {
    user,
    login,
    signup,
    logout,
    loading,
    isAuthenticated: !!user,
    isGovernment: user?.role === 'government',
    isCitizen: user?.role === 'citizen',
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
