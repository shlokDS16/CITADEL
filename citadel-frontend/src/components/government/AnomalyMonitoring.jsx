import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Header from '../common/Header';
import FloatingShapes from '../common/FloatingShapes';

function generateAnomalyData() {
    const anomalyTypes = [
        { type: 'Structural Degradation', category: 'Bridge', severity: 'critical', icon: '🏗️' },
        { type: 'Power Grid Fluctuation', category: 'Electrical', severity: 'high', icon: '⚡' },
        { type: 'Water Pressure Drop', category: 'Water System', severity: 'medium', icon: '💧' },
        { type: 'Traffic Signal Malfunction', category: 'Traffic', severity: 'high', icon: '🚦' },
        { type: 'Pipeline Corrosion', category: 'Water System', severity: 'critical', icon: '🔧' },
        { type: 'Transformer Overload', category: 'Electrical', severity: 'critical', icon: '🔥' },
        { type: 'Road Surface Damage', category: 'Road', severity: 'medium', icon: '🛣️' },
        { type: 'Sewage System Blockage', category: 'Drainage', severity: 'high', icon: '🚿' },
        { type: 'Building Vibration Anomaly', category: 'Structure', severity: 'high', icon: '🏢' },
        { type: 'Air Quality Index Spike', category: 'Environment', severity: 'medium', icon: '🌫️' },
    ];
    const locations = ['Sector 12 - MG Road Junction', 'Sector 5 - Industrial Area', 'Sector 8 - Residential Block C', 'Highway NH-48 - Km 34', 'Sector 17 - Commercial Complex', 'Sector 3 - Water Treatment Plant', 'Sector 21 - Power Substation', 'Sector 9 - School Zone'];
    const actions = ['Deploy maintenance crew within 4 hours', 'Schedule emergency inspection', 'Initiate automated shutoff protocol', 'Reroute traffic to alternate path', 'Replace degraded component immediately', 'Monitor for 24 hours before intervention', 'Escalate to engineering division', 'Issue public safety advisory'];

    const anomalies = [];
    const numAnomalies = 5 + Math.floor(Math.random() * 4);
    for (let i = 0; i < numAnomalies; i++) {
        const template = anomalyTypes[Math.floor(Math.random() * anomalyTypes.length)];
        const hoursAgo = Math.floor(Math.random() * 48);
        anomalies.push({
            id: `ANM-${Math.floor(100000 + Math.random() * 900000)}`, ...template,
            location: locations[Math.floor(Math.random() * locations.length)],
            detected_at: new Date(Date.now() - hoursAgo * 3600000).toISOString(),
            confidence: (72 + Math.random() * 26).toFixed(1),
            recommended_action: actions[Math.floor(Math.random() * actions.length)],
            sensor_readings: { temperature: (20 + Math.random() * 30).toFixed(1), vibration: (Math.random() * 15).toFixed(2), pressure: (Math.random() * 100 + 50).toFixed(1) },
            status: Math.random() > 0.3 ? 'active' : 'investigating',
        });
    }
    const severityOrder = { critical: 0, high: 1, medium: 2 };
    anomalies.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]);
    return anomalies;
}

function generateTimeSeriesData() {
    const hours = [];
    for (let i = 23; i >= 0; i--) {
        const hour = new Date(Date.now() - i * 3600000);
        hours.push({ label: hour.getHours().toString().padStart(2, '0') + ':00', anomalies: Math.floor(Math.random() * 5), resolved: Math.floor(Math.random() * 3), critical: Math.floor(Math.random() * 2) });
    }
    return hours;
}

function TimelineChart({ data }) {
    const maxVal = Math.max(...data.map(d => Math.max(d.anomalies, d.resolved, d.critical)), 1);
    return (
        <div className="p-4 bg-black border-2 border-primary">
            <h3 className="text-xs font-black tight-caps text-primary mb-4">24-HOUR ANOMALY TIMELINE</h3>
            <div className="flex items-end gap-[2px] h-32">
                {data.map((d, i) => (
                    <div key={i} className="flex-1 flex flex-col items-center gap-[1px] h-full justify-end" title={`${d.label}: ${d.anomalies} detected`}>
                        <div className="w-full bg-accent-pink opacity-80" style={{ height: `${(d.critical / maxVal) * 100}%`, minHeight: d.critical > 0 ? '2px' : '0' }} />
                        <div className="w-full bg-primary opacity-80" style={{ height: `${(d.anomalies / maxVal) * 100}%`, minHeight: d.anomalies > 0 ? '2px' : '0' }} />
                        <div className="w-full bg-terminal-green opacity-60" style={{ height: `${(d.resolved / maxVal) * 100}%`, minHeight: d.resolved > 0 ? '2px' : '0' }} />
                    </div>
                ))}
            </div>
            <div className="flex justify-between mt-2 text-xs font-mono text-gray-500"><span>{data[0]?.label}</span><span>{data[Math.floor(data.length / 2)]?.label}</span><span>{data[data.length - 1]?.label}</span></div>
            <div className="flex gap-4 mt-3 text-xs font-mono">
                <span className="flex items-center gap-1"><div className="w-3 h-3 bg-accent-pink" /> Critical</span>
                <span className="flex items-center gap-1"><div className="w-3 h-3 bg-primary" /> Detected</span>
                <span className="flex items-center gap-1"><div className="w-3 h-3 bg-terminal-green" /> Resolved</span>
            </div>
        </div>
    );
}

function SeverityChart({ anomalies }) {
    const counts = { critical: 0, high: 0, medium: 0 };
    anomalies.forEach(a => { counts[a.severity] = (counts[a.severity] || 0) + 1; });
    const total = anomalies.length || 1;
    return (
        <div className="p-4 bg-black border-2 border-accent-pink">
            <h3 className="text-xs font-black tight-caps text-accent-pink mb-3">SEVERITY DISTRIBUTION</h3>
            <div className="space-y-3">
                {[['critical', 'CRITICAL', 'text-accent-pink', 'bg-accent-pink'], ['high', 'HIGH', 'text-primary', 'bg-primary'], ['medium', 'MEDIUM', 'text-accent-cyan', 'bg-accent-cyan']].map(([key, label, textColor, bgColor]) => (
                    <div key={key}>
                        <div className="flex items-center justify-between text-xs font-mono mb-1"><span className={textColor}>{label}</span><span className={textColor}>{counts[key]}</span></div>
                        <div className="h-4 bg-gray-800 overflow-hidden"><div className={`h-full ${bgColor}`} style={{ width: `${(counts[key] / total) * 100}%` }} /></div>
                    </div>
                ))}
            </div>
        </div>
    );
}

export default function AnomalyMonitoring() {
    const [anomalies, setAnomalies] = useState([]);
    const [timelineData, setTimelineData] = useState([]);
    const [scanning, setScanning] = useState(false);
    const [selectedAnomaly, setSelectedAnomaly] = useState(null);
    const [lastScan, setLastScan] = useState(null);
    const [autoRefresh, setAutoRefresh] = useState(false);

    useEffect(() => { setAnomalies(generateAnomalyData()); setTimelineData(generateTimeSeriesData()); setLastScan(new Date().toISOString()); }, []);

    useEffect(() => {
        if (!autoRefresh) return;
        const interval = setInterval(() => { setAnomalies(generateAnomalyData()); setTimelineData(generateTimeSeriesData()); setLastScan(new Date().toISOString()); }, 10000);
        return () => clearInterval(interval);
    }, [autoRefresh]);

    const runScan = async () => { setScanning(true); await new Promise(r => setTimeout(r, 2000 + Math.random() * 1500)); setAnomalies(generateAnomalyData()); setTimelineData(generateTimeSeriesData()); setLastScan(new Date().toISOString()); setScanning(false); };

    const criticalCount = anomalies.filter(a => a.severity === 'critical').length;
    const highCount = anomalies.filter(a => a.severity === 'high').length;
    const activeCount = anomalies.filter(a => a.status === 'active').length;

    const getSeverityColor = (severity) => ({ critical: 'border-accent-pink bg-accent-pink/10 text-accent-pink', high: 'border-primary bg-primary/10 text-primary', medium: 'border-accent-cyan bg-accent-cyan/10 text-accent-cyan' }[severity]);
    const getSeverityBadge = (severity) => ({ critical: 'bg-accent-pink text-black', high: 'bg-primary text-black', medium: 'bg-accent-cyan text-black' }[severity]);

    return (
        <div className="min-h-screen bg-background-light dark:bg-background-dark">
            <FloatingShapes />
            <Header showNetworkStatus={true} />
            <div className="relative z-10 container mx-auto px-8 py-8">
                <Link to="/government/dashboard" className="inline-block mb-6 px-4 py-2 bg-white dark:bg-black border-4 border-black neo-shadow-sm hover-collapse font-bold tight-caps text-sm transition-all">← DASHBOARD</Link>
                <div className="mb-8 flex items-start justify-between">
                    <div>
                        <div className="flex items-center gap-4 mb-4">
                            <h1 className="text-4xl font-black tight-caps">ANOMALY MONITORING</h1>
                            <div className="px-4 py-2 bg-accent-pink border-4 border-black neo-shadow-sm"><span className="text-sm font-black tight-caps text-black">GATEWAY_04</span></div>
                        </div>
                        <p className="text-sm font-mono text-gray-600 dark:text-gray-400 uppercase">Predictive Maintenance • IoT Sensor Fusion • Isolation Forest</p>
                    </div>
                    <div className="flex gap-3">
                        <button onClick={() => setAutoRefresh(!autoRefresh)} className={`px-4 py-2 border-4 border-black font-black tight-caps text-xs transition-all ${autoRefresh ? 'bg-terminal-green text-black' : 'bg-white dark:bg-black'}`}>{autoRefresh ? '● LIVE' : '○ AUTO'}</button>
                        <button onClick={runScan} disabled={scanning} className="px-6 py-2 bg-accent-pink border-4 border-black neo-shadow-pink hover-collapse-pink font-black tight-caps text-xs text-black transition-all disabled:opacity-50">{scanning ? 'SCANNING...' : 'RUN SCAN'}</button>
                    </div>
                </div>

                <div className="grid md:grid-cols-5 gap-4 mb-8">
                    <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow p-4 text-center"><div className="text-3xl font-roboto tight-caps text-accent-pink">{anomalies.length}</div><p className="text-xs font-black tight-caps">TOTAL</p></div>
                    <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow p-4 text-center"><div className="text-3xl font-roboto tight-caps text-accent-pink animate-pulse">{criticalCount}</div><p className="text-xs font-black tight-caps">CRITICAL</p></div>
                    <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow p-4 text-center"><div className="text-3xl font-roboto tight-caps text-primary">{highCount}</div><p className="text-xs font-black tight-caps">HIGH</p></div>
                    <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow p-4 text-center"><div className="text-3xl font-roboto tight-caps text-terminal-green">{activeCount}</div><p className="text-xs font-black tight-caps">ACTIVE</p></div>
                    <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow p-4 text-center"><div className="text-xs font-mono text-terminal-green">{lastScan ? new Date(lastScan).toLocaleTimeString() : '--'}</div><p className="text-xs font-black tight-caps mt-1">LAST SCAN</p></div>
                </div>

                <div className="grid lg:grid-cols-3 gap-8">
                    <div className="space-y-6">
                        <TimelineChart data={timelineData} />
                        <SeverityChart anomalies={anomalies} />
                        <div className="p-4 bg-black border-2 border-accent-cyan">
                            <h3 className="text-xs font-black tight-caps text-accent-cyan mb-3">BY CATEGORY</h3>
                            <div className="space-y-2">
                                {Object.entries(anomalies.reduce((acc, a) => { acc[a.category] = (acc[a.category] || 0) + 1; return acc; }, {})).map(([cat, count]) => (
                                    <div key={cat} className="flex items-center justify-between text-xs font-mono"><span className="text-gray-400">{cat}</span><span className="text-accent-cyan">{count}</span></div>
                                ))}
                            </div>
                        </div>
                        <div className="bg-white dark:bg-gray-900 border-4 border-black p-4">
                            <h3 className="text-xs font-black tight-caps mb-2">SYSTEM INFO</h3>
                            <div className="space-y-1 text-xs font-mono text-gray-500">
                                <div className="flex justify-between"><span>Model:</span><span className="text-terminal-green">Isolation Forest</span></div>
                                <div className="flex justify-between"><span>Sensors:</span><span className="text-terminal-green">847 Active</span></div>
                                <div className="flex justify-between"><span>Pipeline:</span><span className="text-terminal-green">Streaming</span></div>
                                <div className="flex justify-between"><span>Latency:</span><span className="text-terminal-green">{(50 + Math.random() * 100).toFixed(0)}ms</span></div>
                            </div>
                        </div>
                    </div>

                    <div className="lg:col-span-2">
                        <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow">
                            <div className="bg-black px-6 py-4 border-b-4 border-white flex items-center justify-between">
                                <h2 className="text-xl font-black tight-caps text-accent-pink">ACTIVE ALERTS</h2>
                                {scanning && <div className="flex items-center gap-2"><div className="w-3 h-3 border-2 border-accent-pink border-t-transparent rounded-full animate-spin" /><span className="text-xs font-mono text-accent-pink">Scanning...</span></div>}
                            </div>
                            <div className="p-4 space-y-3 max-h-[700px] overflow-y-auto">
                                {anomalies.map((anomaly, idx) => (
                                    <div key={idx} onClick={() => setSelectedAnomaly(selectedAnomaly === anomaly ? null : anomaly)}
                                        className={`p-4 border-4 border-black cursor-pointer transition-all ${getSeverityColor(anomaly.severity)} ${selectedAnomaly === anomaly ? 'ring-2 ring-white' : ''}`}>
                                        <div className="flex items-start justify-between mb-2">
                                            <div className="flex items-center gap-3">
                                                <span className="text-2xl">{anomaly.icon}</span>
                                                <div><p className="text-sm font-black tight-caps">{anomaly.type}</p><p className="text-xs font-mono opacity-70">{anomaly.id} • {anomaly.category}</p></div>
                                            </div>
                                            <span className={`px-2 py-1 ${getSeverityBadge(anomaly.severity)} text-xs font-black tight-caps border-2 border-black`}>{anomaly.severity.toUpperCase()}</span>
                                        </div>
                                        <div className="flex items-center justify-between text-xs font-mono opacity-70"><span>📍 {anomaly.location}</span><span>{new Date(anomaly.detected_at).toLocaleString()}</span></div>
                                        <div className="flex items-center gap-2 mt-2">
                                            <span className="text-xs font-mono opacity-70">Confidence:</span>
                                            <div className="flex-1 h-2 bg-black/30 overflow-hidden"><div className="h-full bg-terminal-green" style={{ width: `${anomaly.confidence}%` }} /></div>
                                            <span className="text-xs font-mono text-terminal-green">{anomaly.confidence}%</span>
                                        </div>
                                        {selectedAnomaly === anomaly && (
                                            <div className="mt-4 pt-4 border-t-2 border-current/30 space-y-3">
                                                <div className="grid grid-cols-3 gap-2">
                                                    <div className="p-2 bg-black/30 border border-current/30 text-center"><p className="text-xs opacity-60">Temperature</p><p className="text-sm font-mono">{anomaly.sensor_readings.temperature}°C</p></div>
                                                    <div className="p-2 bg-black/30 border border-current/30 text-center"><p className="text-xs opacity-60">Vibration</p><p className="text-sm font-mono">{anomaly.sensor_readings.vibration} Hz</p></div>
                                                    <div className="p-2 bg-black/30 border border-current/30 text-center"><p className="text-xs opacity-60">Pressure</p><p className="text-sm font-mono">{anomaly.sensor_readings.pressure} kPa</p></div>
                                                </div>
                                                <div className="p-3 bg-black/30 border border-current/30"><p className="text-xs font-black tight-caps mb-1">🤖 AI RECOMMENDED ACTION</p><p className="text-sm font-mono">{anomaly.recommended_action}</p></div>
                                                <div className="flex items-center gap-2 text-xs font-mono opacity-70">
                                                    <span>Status: </span><span className={`px-2 py-1 ${anomaly.status === 'active' ? 'bg-accent-pink text-black' : 'bg-primary text-black'} font-black tight-caps`}>{anomaly.status.toUpperCase()}</span>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
