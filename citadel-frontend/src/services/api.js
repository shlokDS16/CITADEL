import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Auto-inject auth headers
apiClient.interceptors.request.use(
  (config) => {
    const userId = localStorage.getItem('user_id');
    const userRole = localStorage.getItem('user_role');
    const sessionId = localStorage.getItem('session_id');

    if (userId) config.headers['x-user-id'] = userId;
    if (userRole) config.headers['x-user-role'] = userRole;
    if (sessionId) config.headers['x-session-id'] = sessionId;

    return config;
  },
  (error) => Promise.reject(error)
);

// Auth endpoints - works client-side for demo
export const auth = {
  login: async (username, password) => {
    // Smart demo login - accept any credentials
    const role = localStorage.getItem('login_role') || 'citizen';
    const data = {
      user_id: `user_${Date.now()}`,
      role: role,
      session_id: `session_${Date.now()}`,
      username: username,
    };
    return data;
  },

  signup: async (username, password, role) => {
    const data = {
      user_id: `user_${Date.now()}`,
      role: role,
      session_id: `session_${Date.now()}`,
      username: username,
    };
    return data;
  },

  logout: () => {
    localStorage.removeItem('user_id');
    localStorage.removeItem('user_role');
    localStorage.removeItem('session_id');
    localStorage.removeItem('username');
    localStorage.removeItem('login_role');
  },
};

// Government Official endpoints
export const government = {
  processDocument: async (file, docType) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('doc_type', docType);

    try {
      const response = await apiClient.post('/api/documents/process', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return response.data;
    } catch {
      return null; // fallback handled in component
    }
  },

  screenResume: async (file, jobDescription) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('job_description', jobDescription);

    try {
      const response = await apiClient.post('/api/resumes/analyze', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return response.data;
    } catch {
      return null;
    }
  },

  analyzeTrafficFootage: async (videoFile, violationTypes) => {
    const formData = new FormData();
    formData.append('video', videoFile);
    violationTypes.forEach(type => formData.append('violation_types', type));

    try {
      const response = await apiClient.post('/api/traffic-violations/analyze', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return response.data;
    } catch {
      return null;
    }
  },

  getAnomalyStats: async () => {
    try {
      const response = await apiClient.get('/api/anomaly/stats');
      return response.data;
    } catch {
      return null;
    }
  },

  triggerAnomalyCheck: async () => {
    try {
      const response = await apiClient.post('/api/anomaly/check');
      return response.data;
    } catch {
      return null;
    }
  },
};

// Citizen endpoints
export const citizen = {
  sendChatMessage: async (message) => {
    try {
      const response = await apiClient.post('/api/chat/query', { query: message });
      return response.data;
    } catch {
      return null;
    }
  },

  getChatHistory: async (limit = 20) => {
    try {
      const response = await apiClient.get(`/api/chat/history?limit=${limit}`);
      return response.data;
    } catch {
      return { history: [] };
    }
  },

  analyzeFakeNews: async (text) => {
    try {
      const response = await apiClient.post('/api/news/analyze', { text });
      return response.data;
    } catch {
      return null;
    }
  },

  getRecentFakeNewsChecks: async () => {
    try {
      const response = await apiClient.get('/api/news/');
      return response.data;
    } catch {
      return { checks: [] };
    }
  },

  submitTicket: async (title, description, contactEmail) => {
    try {
      const response = await apiClient.post('/api/support-tickets/submit', {
        title,
        description,
        contact_email: contactEmail,
      });
      return response.data;
    } catch {
      return null;
    }
  },

  getMyTickets: async () => {
    try {
      const response = await apiClient.get('/api/support-tickets/my-tickets');
      return response.data;
    } catch {
      return { tickets: [] };
    }
  },

  categorizeExpense: async (file) => {
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await apiClient.post('/api/expenses/categorize', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return response.data;
    } catch {
      return null;
    }
  },

  getExpenseHistory: async () => {
    try {
      const response = await apiClient.get('/api/expenses/history');
      return response.data;
    } catch {
      return { expenses: [] };
    }
  },
};

// Dashboard
export const dashboard = {
  getData: async () => {
    try {
      const response = await apiClient.get('/api/dashboard');
      return response.data;
    } catch {
      return null;
    }
  },
};

export default apiClient;
