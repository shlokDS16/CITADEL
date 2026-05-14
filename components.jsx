// ==================== CITADEL COMPONENTS ====================
// Shared primitives for the CITADEL_OS enterprise UI.
// Loaded into window for cross-file access (CITADEL.html uses no bundler).

// ---- Decorative Background ----
const CitadelBackground = () => (
  <div style={{ position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none', overflow: 'hidden' }}>
    <div style={{ position: 'absolute', inset: 0, background: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px)', zIndex: 10 }}></div>
    <div style={{ position: 'absolute', inset: 0, opacity: 0.04, backgroundImage: 'linear-gradient(rgba(0,0,0,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.3) 1px, transparent 1px)', backgroundSize: '60px 60px' }}></div>
    <div className="float-shape shape-diamond" style={{ top: '12%', right: '3%' }}></div>
    <div className="float-shape shape-ellipse" style={{ top: '8%', left: '25%' }}></div>
    <div className="float-shape shape-circle" style={{ bottom: '8%', right: '12%' }}></div>
    <div className="float-shape shape-square" style={{ bottom: '20%', left: '2%' }}></div>
  </div>
);

// ====================================================================
// LIVE BACKEND HELPERS
// Frontend stays mock-driven by default. Pass `?live=1` in the URL
// (or set localStorage 'citadel_live'='1') to opt in to real API calls.
// ====================================================================

const API_BASE = 'http://127.0.0.1:8000';

const isLiveMode = () => {
  try {
    const url = new URLSearchParams(window.location.search);
    if (url.get('live') === '1') return true;
    return window.localStorage.getItem('citadel_live') === '1';
  } catch (e) { return false; }
};

const useLive = () => {
  const [live] = React.useState(isLiveMode());
  return live;
};

/**
 * apiFetch(path, options?)
 *   - options.json   → POST/PUT body (auto stringified, sets content-type)
 *   - options.form   → multipart FormData (do NOT set content-type)
 *   - options.method → defaults to GET (or POST if json/form provided)
 *   - options.params → object → ?key=val querystring
 * Returns parsed JSON, throws Error on non-2xx with .status set.
 */
const apiFetch = async (path, options = {}) => {
  const { json, form, params, method, ...rest } = options;
  let url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  if (params) {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') q.set(k, v);
    });
    const qs = q.toString();
    if (qs) url += (url.includes('?') ? '&' : '?') + qs;
  }
  const init = {
    method: method || (json || form ? 'POST' : 'GET'),
    headers: {},
    ...rest,
  };
  if (json !== undefined) {
    init.body = JSON.stringify(json);
    init.headers['Content-Type'] = 'application/json';
  } else if (form !== undefined) {
    init.body = form;
    // do NOT set content-type — browser adds the multipart boundary
  }
  const r = await fetch(url, init);
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    // FastAPI puts validation errors in body.detail as an array of objects.
    // Flatten them so the user sees a real message rather than "[object Object]".
    let msg = body?.error?.message;
    if (!msg && Array.isArray(body?.detail)) {
      msg = body.detail.map(d => `${(d.loc || []).join('.')}: ${d.msg}`).join('; ');
    } else if (!msg && typeof body?.detail === 'string') {
      msg = body.detail;
    } else if (!msg && typeof body === 'string') {
      msg = body;
    }
    const e = new Error(msg || `HTTP ${r.status}`);
    e.status = r.status;
    e.body = body;
    throw e;
  }
  return body;
};

// Live-mode badge — drop into any header to show "LIVE" status
const LiveBadge = () => {
  if (!isLiveMode()) return null;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 8px', background: 'var(--green)', color: '#000',
      border: '2px solid #000', fontFamily: 'var(--font-mono)',
      fontSize: 10, fontWeight: 700, letterSpacing: 1, marginLeft: 8,
    }} title={`Connected to ${API_BASE}`}>
      <span style={{ width: 6, height: 6, background: '#000', borderRadius: '50%' }}></span>
      LIVE BACKEND
    </span>
  );
};


// ---- Top Navigation Bar ----
const NavBar = ({ role, user, onLogout, onDashboard, onOpenCmd, notifCount = 3 }) => {
  const isGov = role === 'government';
  const accent = isGov ? 'var(--gold)' : 'var(--red)';
  const [notifOpen, setNotifOpen] = React.useState(false);
  const now = new Date();
  const [clock, setClock] = React.useState(now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
  React.useEffect(() => {
    const t = setInterval(() => setClock(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <nav className="navbar">
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <span className="nav-logo" onClick={onDashboard} style={{ cursor: onDashboard ? 'pointer' : 'default' }}>CITADEL_OS</span>
        <span className="status-badge green">● NETWORK: ACTIVE</span>
        <span className="status-badge green hide-sm">● SECURE CONNECTION</span>
        <span className="status-badge hide-sm" style={{ background: 'rgba(255,255,255,0.05)', color: '#888', border: '1px solid #333' }}>◷ {clock}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button className="nav-icon-btn hide-sm" onClick={onOpenCmd} title="Command Palette (⌘K)">
          <span style={{ fontSize: 13, letterSpacing: 1 }}>⌘K</span>
        </button>
        <button className="nav-icon-btn" onClick={() => setNotifOpen(o => !o)} title="Notifications" style={{ position: 'relative' }}>
          <span style={{ fontSize: 15 }}>◉</span>
          {notifCount > 0 && <span className="nav-badge">{notifCount}</span>}
        </button>
        <div className="nav-user">
          <div className="nav-user-name">{user}</div>
          <div className="nav-user-role">{isGov ? 'OFFICIAL' : 'CITIZEN'}</div>
        </div>
        <button className="btn-brutal" onClick={onLogout} style={{ background: accent, color: isGov ? '#000' : '#fff', borderColor: '#000', fontSize: 12, padding: '6px 14px' }}>LOGOUT</button>
      </div>
      {notifOpen && <NotificationDrawer onClose={() => setNotifOpen(false)} role={role} />}
    </nav>
  );
};

// ---- Notification Drawer ----
const NotificationDrawer = ({ onClose, role }) => {
  const items = role === 'government' ? [
    { t: 'Document batch processed', d: '47 files complete', time: '2 min', type: 'success' },
    { t: 'Anomaly alert: Bridge sensor', d: 'Sector 12 • Confidence 89%', time: '8 min', type: 'alert' },
    { t: 'Resume screening batch done', d: '12 candidates shortlisted', time: '22 min', type: 'info' },
    { t: 'Challan issued', d: '₹2,500 • Plate MH-02-CD-5678', time: '1 hr', type: 'info' },
    { t: 'System backup completed', d: 'All replicas in sync', time: '2 hr', type: 'success' },
  ] : [
    { t: 'Ticket TKT-1024 resolved', d: 'Water supply restored', time: '10 min', type: 'success' },
    { t: 'Expense anomaly flagged', d: '₹8,500 — unusual pattern', time: '1 hr', type: 'alert' },
    { t: 'KB article updated', d: 'Passport renewal steps', time: '3 hr', type: 'info' },
  ];
  return (
    <>
      <div className="drawer-scrim" onClick={onClose}></div>
      <div className="notif-drawer slide-in-right">
        <div className="drawer-header">
          <span>NOTIFICATIONS</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div className="drawer-body">
          {items.map((n, i) => (
            <div key={i} className={`notif-item notif-${n.type}`}>
              <div className={`notif-dot notif-${n.type}`}></div>
              <div style={{ flex: 1 }}>
                <div className="notif-title">{n.t}</div>
                <div className="notif-desc">{n.d}</div>
              </div>
              <div className="notif-time">{n.time}</div>
            </div>
          ))}
        </div>
        <div className="drawer-footer">
          <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }}>MARK ALL READ</button>
        </div>
      </div>
    </>
  );
};

// ---- Command Palette (⌘K) ----
const CommandPalette = ({ open, onClose, onJump, role }) => {
  const [q, setQ] = React.useState('');
  const inputRef = React.useRef(null);
  React.useEffect(() => { if (open && inputRef.current) inputRef.current.focus(); }, [open]);
  React.useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    if (open) window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  const gov = [
    { label: 'Document Intelligence', page: 'doc-intel', icon: '📋', cat: 'Gateway' },
    { label: 'Resume Screening', page: 'resume', icon: '👥', cat: 'Gateway' },
    { label: 'Traffic Violations', page: 'traffic', icon: '🚦', cat: 'Gateway' },
    { label: 'Anomaly Monitoring', page: 'anomaly', icon: '📡', cat: 'Gateway' },
    { label: 'Dashboard', page: 'dashboard', icon: '⊞', cat: 'Navigation' },
  ];
  const cit = [
    { label: 'RAG Chatbot', page: 'chatbot', icon: '🤖', cat: 'Gateway' },
    { label: 'Fake News Detector', page: 'fake-news', icon: '📰', cat: 'Gateway' },
    { label: 'Support Tickets', page: 'tickets', icon: '🎫', cat: 'Gateway' },
    { label: 'Expense Categorizer', page: 'expenses', icon: '💰', cat: 'Gateway' },
    { label: 'Dashboard', page: 'dashboard', icon: '⊞', cat: 'Navigation' },
  ];
  const all = role === 'government' ? gov : cit;
  const filtered = all.filter(c => !q || c.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="cmd-scrim" onClick={onClose}></div>
      <div className="cmd-palette fade-in">
        <div className="cmd-input-wrap">
          <span style={{ opacity: 0.5 }}>⌕</span>
          <input ref={inputRef} className="cmd-input" value={q} onChange={e => setQ(e.target.value)} placeholder="Search gateways, actions, tickets..." />
          <span className="cmd-kbd">ESC</span>
        </div>
        <div className="cmd-results">
          {filtered.length === 0 ? (
            <div style={{ padding: 20, opacity: 0.5, fontFamily: 'var(--font-mono)', fontSize: 12 }}>No results found</div>
          ) : filtered.map((c, i) => (
            <button key={i} className="cmd-item" onClick={() => { onJump(c.page); onClose(); }}>
              <span style={{ fontSize: 18 }}>{c.icon}</span>
              <div style={{ flex: 1, textAlign: 'left' }}>
                <div className="cmd-item-label">{c.label}</div>
                <div className="cmd-item-cat">{c.cat}</div>
              </div>
              <span style={{ opacity: 0.4, fontSize: 12 }}>↵</span>
            </button>
          ))}
        </div>
        <div className="cmd-footer">
          <span>↑↓ navigate</span>
          <span>↵ select</span>
          <span>ESC close</span>
        </div>
      </div>
    </>
  );
};

// ---- Gateway Card (for dashboard) ----
const GatewayCard = ({ title, gatewayId, icon, status, description, accentColor, onClick, index, metric }) => {
  const [hovered, setHovered] = React.useState(false);
  return (
    <div className={`gateway-card ${hovered ? 'hovered' : ''}`} style={{ '--accent': accentColor, animationDelay: `${index * 0.1}s` }} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} onClick={onClick} role="button" tabIndex={0} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && onClick()}>
      <div className="gateway-header" style={{ background: accentColor }}>
        <span className="gateway-title">{title}</span>
        <span className="gateway-id">{gatewayId}</span>
      </div>
      <div className="gateway-body">
        <div className="gateway-icon">{icon}</div>
        <div className="gateway-status"><span className="status-dot green"></span> {status}</div>
        <div className="gateway-desc">{description}</div>
        {metric && <div className="gateway-metric"><strong>{metric.value}</strong> <span>{metric.label}</span></div>}
      </div>
      <div className="gateway-footer">
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.5 }}>CLICK TO ACCESS →</span>
      </div>
    </div>
  );
};

// ---- Stat Card ----
const StatCard = ({ value, label, accentColor, trend, trendDir }) => (
  <div className="stat-card" style={{ '--accent': accentColor || 'var(--gold)' }}>
    <div className="stat-value">{value}</div>
    <div className="stat-label">{label}</div>
    {trend !== undefined && (
      <div className={`stat-trend ${trendDir === 'up' ? 'up' : trendDir === 'down' ? 'down' : ''}`}>
        {trendDir === 'up' ? '▲' : trendDir === 'down' ? '▼' : '■'} {trend}
      </div>
    )}
    <div className="stat-accent-bar" style={{ background: accentColor }}></div>
  </div>
);

// ---- KPI Card (stat + sparkline) ----
const KPICard = ({ value, label, data = [], color = 'var(--gold)', delta, deltaDir }) => {
  const max = Math.max(...data, 1);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * 100},${100 - (v / max) * 100}`).join(' ');
  return (
    <div className="kpi-card" style={{ '--accent': color }}>
      <div className="kpi-top">
        <div>
          <div className="kpi-label">{label}</div>
          <div className="kpi-value">{value}</div>
        </div>
        {delta !== undefined && (
          <div className={`kpi-delta ${deltaDir === 'up' ? 'up' : 'down'}`}>
            {deltaDir === 'up' ? '▲' : '▼'} {delta}
          </div>
        )}
      </div>
      {data.length > 0 && (
        <svg className="kpi-sparkline" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
          <polyline points={`0,100 ${pts} 100,100`} fill={color} opacity="0.15" />
        </svg>
      )}
    </div>
  );
};

// ---- Core Dynamics Widget ----
const CoreDynamics = () => {
  const values = { neural: 94, quantum: 22, grid: 100 };
  return (
    <div className="widget-card">
      <div className="widget-title">CORE_DYNAMICS</div>
      <div className="progress-row">
        <span>NEURAL PROCESSING</span>
        <div className="progress-bar"><div className="progress-fill green" style={{ width: `${values.neural}%` }}></div></div>
        <span className="progress-val">{values.neural}%</span>
      </div>
      <div className="progress-row">
        <span>QUANTUM STORAGE</span>
        <div className="progress-bar"><div className="progress-fill blue" style={{ width: `${values.quantum}%` }}></div></div>
        <span className="progress-val">{values.quantum}%</span>
      </div>
      <div className="progress-row">
        <span>GRID STABILITY</span>
        <div className="progress-bar"><div className="progress-fill green" style={{ width: `${values.grid}%` }}></div></div>
        <span className="progress-val">{values.grid}%</span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12, fontFamily: 'var(--font-mono)', fontSize: 12 }}>
        <span>SYSTEM STATUS</span>
        <span style={{ color: 'var(--green)' }}>OPTIMAL</span>
      </div>
    </div>
  );
};

// ---- Session Log Widget ----
const SessionLog = ({ lines }) => {
  const [cursor, setCursor] = React.useState(true);
  React.useEffect(() => {
    const i = setInterval(() => setCursor(c => !c), 500);
    return () => clearInterval(i);
  }, []);
  return (
    <div className="widget-card terminal-widget">
      <div className="widget-title">SESSION_LOG</div>
      <div className="terminal-body">
        {lines.map((l, i) => (
          <div key={i} className="terminal-line">
            <span style={{ color: 'var(--green)' }}>&gt; </span>
            <span dangerouslySetInnerHTML={{ __html: l }}></span>
          </div>
        ))}
        <div className="terminal-line">
          <span style={{ color: 'var(--green)' }}>&gt; </span>
          <span className={`cursor-blink ${cursor ? 'on' : ''}`}>█</span>
        </div>
      </div>
    </div>
  );
};

// ---- Activity Timeline Widget ----
const ActivityTimeline = ({ events }) => (
  <div className="widget-card">
    <div className="widget-title">RECENT_ACTIVITY</div>
    <div className="timeline-list">
      {events.map((e, i) => (
        <div key={i} className="timeline-item" style={{ animationDelay: `${i * 0.08}s` }}>
          <div className="timeline-dot" style={{ background: e.color || 'var(--gold)' }}></div>
          <div className="timeline-content">
            <div className="timeline-action">{e.action}</div>
            <div className="timeline-time">{e.time}</div>
          </div>
        </div>
      ))}
    </div>
  </div>
);

// ---- Network Topology Widget ----
const NetworkTopology = ({ nodes }) => (
  <div className="widget-card">
    <div className="widget-title">NETWORK_TOPOLOGY</div>
    <div className="topology-grid">
      {nodes.map((n, i) => (
        <div key={i} className={`topology-node ${n.status}`} title={n.name}>
          <div className="node-pulse"></div>
          <span>{n.label}</span>
        </div>
      ))}
    </div>
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, marginTop: 8, display: 'flex', gap: 16, opacity: 0.6 }}>
      <span><span className="status-dot green"></span> Online</span>
      <span><span className="status-dot" style={{ background: 'var(--gold)' }}></span> Busy</span>
      <span><span className="status-dot red"></span> Alert</span>
    </div>
  </div>
);

// ---- Quick Actions Widget ----
const QuickActions = ({ actions, accent }) => (
  <div className="widget-card">
    <div className="widget-title">QUICK_ACTIONS</div>
    <div className="quick-actions-grid">
      {actions.map((a, i) => (
        <button key={i} className="quick-action-btn" style={{ '--accent': accent }} onClick={a.onClick}>
          <span className="qa-icon">{a.icon}</span>
          <span className="qa-label">{a.label}</span>
        </button>
      ))}
    </div>
  </div>
);

// ---- Mini Chart Widget ----
const MiniChart = ({ title, data, color, labels }) => {
  const max = Math.max(...data);
  return (
    <div className="widget-card">
      <div className="widget-title">{title}</div>
      <div className="mini-chart">
        {data.map((v, i) => (
          <div key={i} className="chart-bar-col">
            <div className="chart-bar" style={{ height: `${(v / max) * 100}%`, background: color || 'var(--gold)' }} title={`${v}`}></div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 9, opacity: 0.4, marginTop: 4 }}>
        <span>{labels ? labels[0] : '7D AGO'}</span>
        <span>{labels ? labels[labels.length - 1] : 'TODAY'}</span>
      </div>
    </div>
  );
};

// ---- Donut Chart ----
const Donut = ({ segments, size = 120, stroke = 20, centerLabel, centerValue }) => {
  const total = segments.reduce((s, x) => s + x.value, 0);
  const radius = (size - stroke) / 2;
  const circ = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="donut-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#e5e5e0" strokeWidth={stroke} />
        {segments.map((s, i) => {
          const len = (s.value / total) * circ;
          const el = <circle key={i} cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={s.color} strokeWidth={stroke} strokeDasharray={`${len} ${circ - len}`} strokeDashoffset={-offset} transform={`rotate(-90 ${size / 2} ${size / 2})`} />;
          offset += len;
          return el;
        })}
        {(centerValue || centerLabel) && (
          <g>
            <text x="50%" y="48%" textAnchor="middle" fontFamily="var(--font-display)" fontWeight="700" fontSize="18">{centerValue}</text>
            <text x="50%" y="62%" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" opacity="0.5" letterSpacing="1">{centerLabel}</text>
          </g>
        )}
      </svg>
      <div className="donut-legend">
        {segments.map((s, i) => (
          <div key={i} className="donut-legend-item">
            <span className="legend-dot" style={{ background: s.color }}></span>
            <span className="legend-label">{s.label}</span>
            <span className="legend-val">{Math.round((s.value / total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
};

// ---- Heatmap (7×24 time-of-day) ----
const Heatmap = ({ data, title }) => {
  const days = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
  const max = Math.max(...data.flat(), 1);
  return (
    <div className="widget-card">
      <div className="widget-title">{title}</div>
      <div className="heatmap-wrap">
        <div className="heatmap-y-axis">
          {days.map(d => <div key={d} className="heatmap-y-label">{d}</div>)}
        </div>
        <div className="heatmap-grid">
          {data.map((row, i) => (
            <div key={i} className="heatmap-row">
              {row.map((v, j) => {
                const intensity = v / max;
                return <div key={j} className="heatmap-cell" style={{ background: v === 0 ? '#f0efec' : `rgba(230,57,70,${0.1 + intensity * 0.85})` }} title={`${days[i]} ${j}:00 — ${v}`}></div>;
              })}
            </div>
          ))}
        </div>
      </div>
      <div className="heatmap-x-axis">
        <span>00</span><span>06</span><span>12</span><span>18</span><span>23</span>
      </div>
    </div>
  );
};

// ---- Section Header for sub-pages ----
const SubPageHeader = ({ title, gatewayId, subtitle, accentColor, onBack, actions }) => (
  <div className="subpage-header">
    <button className="btn-brutal back-btn" onClick={onBack} style={{ fontSize: 12, padding: '4px 14px' }}>← DASHBOARD</button>
    <div className="subpage-header-row">
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
          <h1 className="subpage-title">{title}</h1>
          <span className="gateway-badge" style={{ background: accentColor }}>{gatewayId}</span>
        </div>
        <p className="subpage-subtitle">{subtitle}</p>
      </div>
      {actions && <div className="subpage-actions">{actions}</div>}
    </div>
  </div>
);

// ---- Tabs ----
const Tabs = ({ tabs, active, onChange, accent = 'var(--gold)' }) => (
  <div className="tabs-bar">
    {tabs.map(t => (
      <button
        key={t.key}
        className={`tab-pill ${active === t.key ? 'active' : ''}`}
        style={{ '--accent': accent }}
        onClick={() => onChange(t.key)}
      >
        {t.icon && <span style={{ marginRight: 6 }}>{t.icon}</span>}
        {t.label}
        {t.badge !== undefined && <span className="tab-pill-badge">{t.badge}</span>}
      </button>
    ))}
  </div>
);

// ---- Segmented Control ----
const SegmentedControl = ({ options, value, onChange, accent = 'var(--gold)' }) => (
  <div className="segmented-control" style={{ '--accent': accent }}>
    {options.map(o => (
      <button key={o} className={`seg-btn ${value === o ? 'active' : ''}`} onClick={() => onChange(o)}>{o}</button>
    ))}
  </div>
);

// ---- Two Column Layout for sub-pages ----
const TwoColumnLayout = ({ left, right, leftTitle, rightTitle, accentColor }) => (
  <div className="two-col-layout">
    <div className="col-panel left-panel">
      <div className="panel-header" style={{ background: accentColor }}>{leftTitle}</div>
      <div className="panel-body">{left}</div>
    </div>
    <div className="col-panel right-panel">
      <div className="panel-header" style={{ background: '#111' }}><span style={{ color: '#fff' }}>{rightTitle}</span></div>
      <div className="panel-body">{right}</div>
    </div>
  </div>
);

// ---- Animated Number ----
const AnimNum = ({ value, suffix = '' }) => {
  const [display, setDisplay] = React.useState(0);
  React.useEffect(() => {
    let start = 0;
    const end = typeof value === 'number' ? value : parseFloat(value);
    if (isNaN(end)) { setDisplay(value); return; }
    const dur = 1200;
    const step = (ts) => {
      if (!step.s) step.s = ts;
      const p = Math.min((ts - step.s) / dur, 1);
      setDisplay(Math.round(start + (end - start) * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, [value]);
  return <>{display}{suffix}</>;
};

// ---- Badge ----
const Badge = ({ children, variant = 'default' }) => (
  <span className={`badge badge-${variant}`}>{children}</span>
);

// ---- Status Pill ----
const StatusPill = ({ status, label }) => (
  <span className={`status-pill status-${status}`}>
    <span className="pill-dot"></span>
    {label || status.toUpperCase()}
  </span>
);

// ---- Severity Badge ----
const SeverityBadge = ({ level }) => (
  <span className={`severity-badge ${level.toLowerCase()}`}>{level.toUpperCase()}</span>
);

// ---- Confidence Bar ----
const ConfidenceBar = ({ value, showLabel = true, compact = false }) => {
  const color = value >= 90 ? 'var(--green)' : value >= 70 ? 'var(--gold)' : value >= 50 ? 'var(--cyan)' : 'var(--red)';
  return (
    <div className={`confidence-wrap ${compact ? 'compact' : ''}`}>
      <div className="confidence-bar"><div style={{ width: `${value}%`, background: color }}></div></div>
      {showLabel && <span className="confidence-num">{value}%</span>}
    </div>
  );
};

// ---- Chip (removable tag) ----
const Chip = ({ label, onRemove, color, selected, onClick }) => (
  <span className={`chip ${selected ? 'selected' : ''}`} style={color ? { '--chip-color': color } : {}} onClick={onClick}>
    {label}
    {onRemove && <button className="chip-remove" onClick={(e) => { e.stopPropagation(); onRemove(); }}>✕</button>}
  </span>
);

// ---- Avatar (initials) ----
const Avatar = ({ name, color, size = 32 }) => {
  const initials = name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();
  const bgColors = ['var(--gold)', 'var(--red)', 'var(--cyan)', 'var(--green)'];
  const bg = color || bgColors[name.length % bgColors.length];
  return (
    <div className="avatar" style={{ width: size, height: size, background: bg, fontSize: size * 0.4 }}>
      {initials}
    </div>
  );
};

// ---- Data Table ----
const DataTable = ({ columns, rows, onRowClick, selectable, selected = [], onSelect, emptyMsg = 'No data' }) => {
  const [sort, setSort] = React.useState({ key: null, dir: 'asc' });
  const sorted = React.useMemo(() => {
    if (!sort.key) return rows;
    return [...rows].sort((a, b) => {
      const va = a[sort.key], vb = b[sort.key];
      if (va == null) return 1;
      if (vb == null) return -1;
      const cmp = typeof va === 'number' ? va - vb : String(va).localeCompare(String(vb));
      return sort.dir === 'asc' ? cmp : -cmp;
    });
  }, [rows, sort]);
  const toggleSort = (k) => setSort(s => s.key === k ? { key: k, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key: k, dir: 'asc' });
  if (rows.length === 0) return <div className="empty-state"><div className="empty-icon">∅</div><p>{emptyMsg}</p></div>;
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {selectable && <th style={{ width: 32 }}><input type="checkbox" onChange={e => onSelect(e.target.checked ? rows.map((_, i) => i) : [])} checked={selected.length === rows.length && rows.length > 0} /></th>}
            {columns.map(c => (
              <th key={c.key} style={{ width: c.width, textAlign: c.align || 'left', cursor: c.sortable !== false ? 'pointer' : 'default' }} onClick={() => c.sortable !== false && toggleSort(c.key)}>
                {c.label}
                {sort.key === c.key && <span style={{ marginLeft: 4 }}>{sort.dir === 'asc' ? '▲' : '▼'}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i} className={onRowClick ? 'clickable' : ''} onClick={() => onRowClick && onRowClick(r, i)}>
              {selectable && <td onClick={e => e.stopPropagation()}><input type="checkbox" checked={selected.includes(i)} onChange={e => onSelect(e.target.checked ? [...selected, i] : selected.filter(x => x !== i))} /></td>}
              {columns.map(c => (
                <td key={c.key} style={{ textAlign: c.align || 'left' }}>
                  {c.render ? c.render(r[c.key], r) : r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// ---- Search Bar ----
const SearchBar = ({ value, onChange, placeholder = 'Search...', onSubmit }) => (
  <div className="searchbar">
    <span className="search-icon">⌕</span>
    <input className="search-input" value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} onKeyDown={e => e.key === 'Enter' && onSubmit && onSubmit()} />
    {value && <button className="search-clear" onClick={() => onChange('')}>✕</button>}
  </div>
);

// ---- Filter Bar ----
const FilterBar = ({ filters, values, onChange, onClear }) => (
  <div className="filter-bar">
    {filters.map(f => (
      <div key={f.key} className="filter-group">
        <label className="filter-label">{f.label}</label>
        <select className="filter-select" value={values[f.key] || ''} onChange={e => onChange(f.key, e.target.value)}>
          <option value="">All</option>
          {f.options.map(o => <option key={o.value || o} value={o.value || o}>{o.label || o}</option>)}
        </select>
      </div>
    ))}
    {onClear && <button className="btn-brutal filter-clear" onClick={onClear} style={{ fontSize: 11, padding: '6px 14px' }}>CLEAR</button>}
  </div>
);

// ---- Toggle / Switch ----
const Toggle = ({ checked, onChange, label }) => (
  <label className="toggle-wrap">
    <span className="toggle-label">{label}</span>
    <button className={`toggle-switch ${checked ? 'on' : ''}`} onClick={() => onChange(!checked)} role="switch" aria-checked={checked}>
      <span className="toggle-knob"></span>
    </button>
  </label>
);

// ---- Modal ----
// Scrim is a full-viewport flex container. The modal-shell is a CHILD of the scrim
// so flex centers it. Click on scrim closes; click on modal-shell stops propagation
// so users can interact with the form without accidentally dismissing.
const Modal = ({ open, onClose, title, children, footer, size = 'md' }) => {
  React.useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    if (open) window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-scrim" onClick={onClose}>
      <div
        className={`modal-shell modal-${size} fade-in`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <span>{title}</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
};

// ---- Rich Text Editor (Quill) ----
// Word-like formal editor for document content. Lazy-mounts Quill (loaded
// via CDN in CITADEL.html). Falls back to plain textarea if Quill missing.
const RichEditor = ({ value, onChange, placeholder = 'Edit document content...', minHeight = 360 }) => {
  const containerRef = React.useRef(null);
  const quillRef = React.useRef(null);
  const lastSetValueRef = React.useRef(value);

  React.useEffect(() => {
    if (!containerRef.current) return;
    if (typeof window.Quill === 'undefined') {
      // Quill CDN not yet loaded — bail; we'll render a textarea fallback below
      return;
    }
    if (quillRef.current) return;   // already initialized

    const q = new window.Quill(containerRef.current, {
      theme: 'snow',
      placeholder,
      modules: {
        toolbar: [
          [{ header: [1, 2, 3, false] }],
          ['bold', 'italic', 'underline', 'strike'],
          [{ list: 'ordered' }, { list: 'bullet' }],
          [{ align: [] }],
          [{ color: [] }, { background: [] }],
          ['blockquote', 'code-block'],
          ['link'],
          ['clean'],
        ],
      },
    });

    // Seed initial content
    if (value) {
      try {
        // If it looks like HTML, paste as HTML; otherwise keep as plain text
        if (/<[a-z][\s\S]*>/i.test(value)) {
          q.clipboard.dangerouslyPasteHTML(value);
        } else {
          q.setText(value);
        }
      } catch (e) {
        q.setText(value);
      }
    }

    q.on('text-change', () => {
      const html = q.root.innerHTML;
      lastSetValueRef.current = html;
      onChange?.(html);
    });

    quillRef.current = q;
  }, []);    // run once

  // External value updates → only push into Quill if it diverges
  React.useEffect(() => {
    const q = quillRef.current;
    if (!q) return;
    if (value !== lastSetValueRef.current) {
      lastSetValueRef.current = value;
      const sel = q.getSelection();
      if (/<[a-z][\s\S]*>/i.test(value || '')) {
        q.clipboard.dangerouslyPasteHTML(value || '');
      } else {
        q.setText(value || '');
      }
      if (sel) q.setSelection(sel);
    }
  }, [value]);

  // Fallback path when Quill hasn't loaded
  if (typeof window.Quill === 'undefined') {
    return (
      <textarea
        className="brutal-select"
        value={value || ''}
        onChange={(e) => onChange?.(e.target.value)}
        rows={14}
        placeholder={placeholder}
        style={{ fontFamily: 'var(--font-mono)', fontSize: 11, width: '100%' }}
      />
    );
  }

  return (
    <div className="rich-editor-wrap" style={{ minHeight }}>
      <div ref={containerRef} style={{ minHeight: minHeight - 50 }} />
    </div>
  );
};

// ---- Empty State ----
const EmptyState = ({ icon = '∅', title, description, action }) => (
  <div className="empty-state enhanced">
    <div className="empty-icon">{icon}</div>
    {title && <h3 className="empty-title">{title}</h3>}
    {description && <p>{description}</p>}
    {action}
  </div>
);

// ---- Loading Skeleton ----
const Skeleton = ({ w = '100%', h = 16 }) => (
  <div className="skeleton" style={{ width: w, height: h }}></div>
);

// ---- Pagination ----
const Pagination = ({ page, total, onPage, perPage = 10 }) => {
  const pages = Math.ceil(total / perPage);
  if (pages <= 1) return null;
  const range = [];
  for (let i = Math.max(1, page - 2); i <= Math.min(pages, page + 2); i++) range.push(i);
  return (
    <div className="pagination">
      <button className="page-btn" disabled={page === 1} onClick={() => onPage(page - 1)}>← PREV</button>
      {range[0] > 1 && <><button className="page-btn" onClick={() => onPage(1)}>1</button><span className="page-ellipsis">…</span></>}
      {range.map(p => <button key={p} className={`page-btn ${p === page ? 'active' : ''}`} onClick={() => onPage(p)}>{p}</button>)}
      {range[range.length - 1] < pages && <><span className="page-ellipsis">…</span><button className="page-btn" onClick={() => onPage(pages)}>{pages}</button></>}
      <button className="page-btn" disabled={page === pages} onClick={() => onPage(page + 1)}>NEXT →</button>
    </div>
  );
};

// ---- Kanban Board ----
const KanbanBoard = ({ columns, cards, onMove, renderCard }) => (
  <div className="kanban-board">
    {columns.map(col => {
      const colCards = cards.filter(c => c.status === col.key);
      return (
        <div key={col.key} className="kanban-col" style={{ '--col-accent': col.color }}>
          <div className="kanban-col-header">
            <span className="kanban-col-title">{col.label}</span>
            <span className="kanban-col-count">{colCards.length}</span>
          </div>
          <div className="kanban-col-body">
            {colCards.length === 0 ? (
              <div className="kanban-empty">Drop here</div>
            ) : colCards.map((c, i) => (
              <div key={i} className="kanban-card" style={{ animationDelay: `${i * 0.04}s` }}>
                {renderCard(c, col.key, onMove)}
              </div>
            ))}
          </div>
        </div>
      );
    })}
  </div>
);

// ---- Funnel Chart ----
const FunnelChart = ({ stages, accent = 'var(--red)' }) => {
  const max = Math.max(...stages.map(s => s.value), 1);
  return (
    <div className="funnel-chart">
      {stages.map((s, i) => {
        const pct = (s.value / max) * 100;
        return (
          <div key={i} className="funnel-stage" style={{ animationDelay: `${i * 0.08}s` }}>
            <div className="funnel-bar-wrap">
              <div className="funnel-bar" style={{ width: `${pct}%`, background: accent, opacity: 1 - i * 0.15 }}></div>
              <span className="funnel-value">{s.value}</span>
            </div>
            <div className="funnel-label">{s.label}</div>
            {i < stages.length - 1 && s.dropRate !== undefined && (
              <div className="funnel-drop">▼ {s.dropRate}% drop</div>
            )}
          </div>
        );
      })}
    </div>
  );
};

// ---- Radar Chart (for skill/bias profiles) ----
const RadarChart = ({ axes, data, size = 220, color = 'var(--gold)' }) => {
  const cx = size / 2, cy = size / 2, r = size / 2 - 24;
  const step = (Math.PI * 2) / axes.length;
  const getPoint = (val, i) => {
    const angle = -Math.PI / 2 + step * i;
    const rad = (val / 100) * r;
    return [cx + Math.cos(angle) * rad, cy + Math.sin(angle) * rad];
  };
  const grid = [0.25, 0.5, 0.75, 1].map(f => axes.map((_, i) => getPoint(f * 100, i)));
  const dataPts = data.map((v, i) => getPoint(v, i));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="radar-chart">
      {grid.map((pts, gi) => (
        <polygon key={gi} points={pts.map(p => p.join(',')).join(' ')} fill="none" stroke="#d5d3cd" strokeWidth="1" />
      ))}
      {axes.map((_, i) => {
        const [px, py] = getPoint(100, i);
        return <line key={i} x1={cx} y1={cy} x2={px} y2={py} stroke="#d5d3cd" strokeWidth="1" />;
      })}
      <polygon points={dataPts.map(p => p.join(',')).join(' ')} fill={color} fillOpacity="0.25" stroke={color} strokeWidth="2" />
      {dataPts.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="3" fill={color} stroke="#000" strokeWidth="1" />)}
      {axes.map((axis, i) => {
        const [x, y] = getPoint(115, i);
        return <text key={i} x={x} y={y} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" fontWeight="700" dominantBaseline="middle">{axis}</text>;
      })}
    </svg>
  );
};

// ---- Map Mock (city grid with pins) ----
const MapMock = ({ pins = [], title = 'CITY MAP' }) => (
  <div className="map-mock">
    <div className="map-title">{title}</div>
    <div className="map-canvas">
      <svg viewBox="0 0 400 280" preserveAspectRatio="none" width="100%" height="100%">
        {/* grid roads */}
        {[0, 1, 2, 3, 4, 5].map(i => <line key={`h${i}`} x1="0" y1={i * 56} x2="400" y2={i * 56} stroke="#d5d3cd" strokeWidth="1.5" />)}
        {[0, 1, 2, 3, 4, 5, 6, 7].map(i => <line key={`v${i}`} x1={i * 57} y1="0" x2={i * 57} y2="280" stroke="#d5d3cd" strokeWidth="1.5" />)}
        {/* diagonal highway */}
        <line x1="0" y1="0" x2="400" y2="280" stroke="#c0beb8" strokeWidth="2.5" strokeDasharray="6,4" />
        {/* river */}
        <path d="M 0,200 Q 100,170 200,200 T 400,210 L 400,280 L 0,280 Z" fill="#b8d8e0" opacity="0.6" />
        {/* park */}
        <rect x="230" y="50" width="80" height="50" fill="#c3d9b8" opacity="0.6" />
        <text x="270" y="80" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="8" fill="#4a5c3c">PARK</text>
        {/* pins */}
        {pins.map((p, i) => (
          <g key={i} transform={`translate(${p.x},${p.y})`}>
            <circle r="10" fill={p.color || 'var(--red)'} opacity="0.3" className={p.pulse ? 'pin-pulse' : ''}></circle>
            <circle r="5" fill={p.color || 'var(--red)'} stroke="#000" strokeWidth="1.5"></circle>
            {p.label && <text x="8" y="3" fontFamily="var(--font-mono)" fontSize="8" fontWeight="700">{p.label}</text>}
          </g>
        ))}
      </svg>
    </div>
  </div>
);

// ---- Timeline (for status tracking) ----
const StatusTimeline = ({ steps, current }) => (
  <div className="status-timeline">
    {steps.map((s, i) => {
      const done = i < current;
      const active = i === current;
      return (
        <div key={i} className={`status-step ${done ? 'done' : ''} ${active ? 'active' : ''}`}>
          <div className="status-node">{done ? '✓' : i + 1}</div>
          <div className="status-label">
            <div className="status-title">{s.label}</div>
            {s.time && <div className="status-time">{s.time}</div>}
          </div>
          {i < steps.length - 1 && <div className="status-connector"></div>}
        </div>
      );
    })}
  </div>
);

// ---- Toast Host ----
const useToast = () => {
  const [toasts, setToasts] = React.useState([]);
  const show = React.useCallback((msg, type = 'info', dur = 3500) => {
    const id = Date.now() + Math.random();
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), dur);
  }, []);
  const host = (
    <div className="toast-host">
      {toasts.map(t => (
        <div key={t.id} className={`toast toast-${t.type} slide-in-right`} role="status" aria-live="polite">
          <span className="toast-icon">{t.type === 'success' ? '✓' : t.type === 'error' ? '✕' : t.type === 'warn' ? '⚠' : 'ℹ'}</span>
          <span>{t.msg}</span>
        </div>
      ))}
    </div>
  );
  return [show, host];
};

// ---- Progress Ring ----
const ProgressRing = ({ value, size = 80, stroke = 8, label, color = 'var(--gold)' }) => {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c - (value / 100) * c;
  return (
    <div className="progress-ring-wrap">
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e5e5e0" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeDasharray={c} strokeDashoffset={offset} transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: 'stroke-dashoffset 0.8s' }} />
        <text x="50%" y="52%" textAnchor="middle" fontFamily="var(--font-display)" fontWeight="700" fontSize="16" dominantBaseline="middle">{value}%</text>
      </svg>
      {label && <div className="ring-label">{label}</div>}
    </div>
  );
};

// ---- Alert Ticker (horizontal scrolling) ----
const AlertTicker = ({ items }) => (
  <div className="alert-ticker">
    <span className="ticker-label">● LIVE FEED</span>
    <div className="ticker-track">
      <div className="ticker-content">
        {items.map((item, i) => (
          <span key={i} className="ticker-item">
            <span className="ticker-tag" style={{ background: item.color }}>{item.tag}</span>
            {item.text}
          </span>
        ))}
        {items.map((item, i) => (
          <span key={`d${i}`} className="ticker-item">
            <span className="ticker-tag" style={{ background: item.color }}>{item.tag}</span>
            {item.text}
          </span>
        ))}
      </div>
    </div>
  </div>
);

// Export all to window so pages.jsx can reference them
Object.assign(window, {
  CitadelBackground, NavBar, NotificationDrawer, CommandPalette,
  GatewayCard, StatCard, KPICard, CoreDynamics, SessionLog,
  ActivityTimeline, NetworkTopology, QuickActions, MiniChart,
  Donut, Heatmap, SubPageHeader, Tabs, SegmentedControl,
  TwoColumnLayout, AnimNum, Badge, StatusPill, SeverityBadge,
  ConfidenceBar, Chip, Avatar, DataTable, SearchBar, FilterBar,
  Toggle, Modal, RichEditor, EmptyState, Skeleton, Pagination, KanbanBoard,
  FunnelChart, RadarChart, MapMock, StatusTimeline, useToast,
  ProgressRing, AlertTicker,
  // Live-backend wiring helpers
  API_BASE, isLiveMode, useLive, apiFetch, LiveBadge,
});
