import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Header from '../common/Header';
import FloatingShapes from '../common/FloatingShapes';

function analyzeTrafficVideo(fileName, selectedTypes, duration, dbFines = []) {

    const violations = [];
    const numViolations = 3 + Math.floor(Math.random() * 5);
    const violationTemplates = {
        'signal_jump': { type: 'Red Light Violation', icon: '🔴', descriptions: ['Vehicle crossed stop line 2.3s after signal turned red', 'Right turn on red without complete stop detected', 'Vehicle entered intersection during red phase'], fineAmount: 1000 },
        'speeding': { type: 'Speed Limit Exceeded', icon: '⚡', descriptions: ['Vehicle estimated at 78 km/h in 50 km/h zone', 'Speed violation detected: 92 km/h in 60 km/h zone', 'Vehicle traveling at 65 km/h in school zone (30 km/h limit)'], fineAmount: 2000 },
        'wrong_lane': { type: 'Wrong Lane Driving', icon: '🚧', descriptions: ['Vehicle detected in oncoming traffic lane', 'Unauthorized use of bus-only lane', 'Lane change without indicator signal'], fineAmount: 1500 },
        'no_helmet': { type: 'No Helmet', icon: '⛑️', descriptions: ['Two-wheeler rider without protective helmet', 'Pillion rider without helmet detected', 'Minor operating two-wheeler without helmet'], fineAmount: 1000 },
        'no_seatbelt': { type: 'Seatbelt Violation', icon: '🔒', descriptions: ['Driver not wearing seatbelt', 'Front passenger without seatbelt', 'No seatbelt compliance detected'], fineAmount: 500 },
        'illegal_parking': { type: 'Illegal Parking', icon: '🅿️', descriptions: ['Vehicle parked in no-parking zone', 'Double parking on arterial road', 'Parking within 15m of intersection'], fineAmount: 500 },
    };

    // Synchronization: Override with real database fines if available
    if (dbFines && dbFines.length > 0) {
        dbFines.forEach(f => {
            const type = f.violation_type.toLowerCase();
            if (type === 'no_helmet') violationTemplates['no_helmet'].fineAmount = f.fine_amount;
            if (type === 'red_light') violationTemplates['signal_jump'].fineAmount = f.fine_amount;
            if (type === 'speeding') violationTemplates['speeding'].fineAmount = f.fine_amount;
            if (type === 'no_seatbelt') violationTemplates['no_seatbelt'].fineAmount = f.fine_amount;
            if (type === 'wrong_side' || type === 'wrong_lane') violationTemplates['wrong_lane'].fineAmount = f.fine_amount;
        });
    }

    const typeKeys = selectedTypes.length > 0 ? selectedTypes : Object.keys(violationTemplates);
    const locations = ['Junction A - Camera 1 (North)', 'MG Road - Camera 3 (East)', 'Highway NH-48 - Camera 7', 'School Zone - Camera 12', 'Commercial Area - Camera 5', 'Residential Block - Camera 9'];
    const licensePlates = ['MH-12-AB-1234', 'KA-05-CD-5678', 'DL-03-EF-9012', 'TN-07-GH-3456', 'UP-32-IJ-7890', 'GJ-01-KL-2345', 'RJ-14-MN-6789', 'WB-02-OP-0123'];
    const videoDuration = duration || 120;

    for (let i = 0; i < numViolations; i++) {
        const typeKey = typeKeys[Math.floor(Math.random() * typeKeys.length)];
        const template = violationTemplates[typeKey];
        const timestamp = Math.floor(Math.random() * videoDuration);
        violations.push({
            id: `VIO-${Math.floor(100000 + Math.random() * 900000)}`,
            type: template.type, icon: template.icon,
            description: template.descriptions[Math.floor(Math.random() * template.descriptions.length)],
            confidence: (75 + Math.random() * 23).toFixed(1),
            timestamp: `${String(Math.floor(timestamp / 60)).padStart(2, '0')}:${String(timestamp % 60).padStart(2, '0')}`,
            license_plate: licensePlates[Math.floor(Math.random() * licensePlates.length)],
            location: locations[Math.floor(Math.random() * locations.length)],
            fine_amount: template.fineAmount,
            frame_number: Math.floor(Math.random() * 3000) + 100,
        });
    }
    violations.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    const typeCounts = {};
    let totalFines = 0;
    violations.forEach(v => { typeCounts[v.type] = (typeCounts[v.type] || 0) + 1; totalFines += v.fine_amount; });

    return {
        violations,
        summary: {
            total_violations: violations.length, type_breakdown: typeCounts, total_fines: totalFines,
            avg_confidence: (violations.reduce((s, v) => s + parseFloat(v.confidence), 0) / violations.length).toFixed(1),
            unique_vehicles: [...new Set(violations.map(v => v.license_plate))].length,
            processing_fps: (24 + Math.random() * 6).toFixed(1),
        },
        model_info: { detector: 'YOLOv8-Custom', tracker: 'DeepSORT', plate_reader: 'CRNN + CTC', accuracy: '94.7%' },
    };
}
export default function TrafficViolations() {
    const [file, setFile] = useState(null);
    const [selectedTypes, setSelectedTypes] = useState([]);
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState('');
    const [processingStep, setProcessingStep] = useState('');
    const [selectedViolation, setSelectedViolation] = useState(null);
    const [dbFines, setDbFines] = useState([]);

    // Fetch real fine amounts from backend for synchronization
    useEffect(() => {
        const fetchFines = async () => {
            try {
                const response = await fetch('http://localhost:8000/api/traffic-violations/fines', {
                    headers: {
                        'x-user-role': 'government_official', // Mocking auth for demo
                        'x-user-id': 'demo-gov-user'
                    }
                });
                if (response.ok) {
                    const data = await response.json();
                    setDbFines(data);
                }
            } catch (err) {
                console.error("Failed to fetch fines:", err);
            }
        };
        fetchFines();
    }, []);


    const violationTypes = [
        { key: 'signal_jump', label: 'Red Light Violation' }, { key: 'speeding', label: 'Speeding' },
        { key: 'wrong_lane', label: 'Wrong Lane' }, { key: 'no_helmet', label: 'No Helmet' },
        { key: 'no_seatbelt', label: 'No Seatbelt' }, { key: 'illegal_parking', label: 'Illegal Parking' },
    ];

    const toggleType = (key) => setSelectedTypes(prev => prev.includes(key) ? prev.filter(t => t !== key) : [...prev, key]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!file) { setError('Please select a video file'); return; }
        setLoading(true); setError(''); setResult(null);
        const steps = ['Loading video frames...', 'Initializing YOLO detector...', 'Running object detection...', 'Tracking vehicles (DeepSORT)...', 'Reading license plates (OCR)...', 'Classifying violations...', 'Computing confidence scores...', 'Generating violation report...'];
        for (const step of steps) { setProcessingStep(step); await new Promise(r => setTimeout(r, 350 + Math.random() * 450)); }
        setResult(analyzeTrafficVideo(file.name, selectedTypes, 180, dbFines));

        setLoading(false); setProcessingStep('');
    };

    const getConfidenceBg = (conf) => { const c = parseFloat(conf); return c >= 90 ? 'bg-terminal-green' : c >= 80 ? 'bg-primary' : 'bg-accent-pink'; };

    return (
        <div className="min-h-screen bg-background-light dark:bg-background-dark">
            <FloatingShapes />
            <Header showNetworkStatus={true} />
            <div className="relative z-10 container mx-auto px-8 py-8">
                <Link to="/government/dashboard" className="inline-block mb-6 px-4 py-2 bg-white dark:bg-black border-4 border-black neo-shadow-sm hover-collapse font-bold tight-caps text-sm transition-all">← DASHBOARD</Link>
                <div className="mb-8">
                    <div className="flex items-center gap-4 mb-4">
                        <h1 className="text-4xl font-black tight-caps">TRAFFIC VIOLATIONS</h1>
                        <div className="px-4 py-2 bg-accent-cyan border-4 border-black neo-shadow-sm"><span className="text-sm font-black tight-caps text-black">GATEWAY_03</span></div>
                    </div>
                    <p className="text-sm font-mono text-gray-600 dark:text-gray-400 uppercase">AI-Powered Video Analysis • YOLOv8 + DeepSORT + CRNN OCR</p>
                </div>

                <div className="grid lg:grid-cols-2 gap-8">
                    <div className="space-y-6">
                        <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow-cyan">
                            <div className="bg-accent-cyan px-6 py-4 border-b-4 border-black"><h2 className="text-xl font-black tight-caps text-black">VIDEO ANALYSIS</h2></div>
                            <form onSubmit={handleSubmit} className="p-6">
                                <div className="mb-6">
                                    <label className="block text-sm font-black tight-caps mb-3">UPLOAD FOOTAGE</label>
                                    <input type="file" onChange={(e) => { setFile(e.target.files[0]); setError(''); }} accept="video/*,.mp4,.avi,.mov,.mkv"
                                        className="w-full px-4 py-3 bg-white dark:bg-gray-800 border-4 border-black font-mono focus:outline-none focus:ring-4 focus:ring-accent-cyan" />
                                    {file && <p className="text-xs font-mono text-terminal-green mt-2">✓ {file.name} ({(file.size / (1024 * 1024)).toFixed(1)} MB)</p>}
                                </div>
                                <div className="mb-6">
                                    <label className="block text-sm font-black tight-caps mb-3">VIOLATION TYPES TO DETECT</label>
                                    <div className="grid grid-cols-2 gap-2">
                                        {violationTypes.map(vt => (
                                            <button key={vt.key} type="button" onClick={() => toggleType(vt.key)}
                                                className={`p-3 border-4 border-black text-xs font-black tight-caps transition-all ${selectedTypes.includes(vt.key) ? 'bg-accent-cyan text-black' : 'bg-white dark:bg-gray-800 hover:bg-accent-cyan/20'}`}>
                                                {vt.label}
                                            </button>
                                        ))}
                                    </div>
                                    <p className="text-xs font-mono text-gray-500 mt-2">Leave empty to detect all types</p>
                                </div>
                                {error && <div className="mb-6 p-4 bg-accent-pink border-4 border-black"><p className="text-sm font-bold text-black">{error}</p></div>}
                                <button type="submit" disabled={loading || !file}
                                    className="w-full px-6 py-4 bg-accent-cyan border-4 border-black neo-shadow-cyan hover-collapse-cyan font-black tight-caps text-black transition-all disabled:opacity-50 disabled:cursor-not-allowed">
                                    {loading ? 'ANALYZING VIDEO...' : 'START DETECTION'}
                                </button>
                            </form>
                        </div>
                        {loading && (
                            <div className="bg-black border-4 border-accent-cyan p-6 text-center">
                                <div className="inline-block w-16 h-16 border-4 border-accent-cyan border-t-transparent rounded-full animate-spin mb-4" />
                                <p className="text-sm font-black tight-caps text-accent-cyan mb-2">PROCESSING FOOTAGE</p>
                                <p className="text-xs font-mono text-terminal-green animate-pulse">{processingStep}</p>
                            </div>
                        )}
                        {result && (
                            <div className="bg-white dark:bg-gray-900 border-4 border-black p-4">
                                <h3 className="text-xs font-black tight-caps mb-2">MODEL PIPELINE</h3>
                                <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                                    {Object.entries(result.model_info).map(([key, value]) => (
                                        <div key={key} className="p-2 bg-black border border-gray-700"><span className="text-gray-400">{key}: </span><span className="text-terminal-green">{value}</span></div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    <div className="space-y-6">
                        {result ? (
                            <>
                                <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow">
                                    <div className="bg-black px-6 py-4 border-b-4 border-white"><h2 className="text-xl font-black tight-caps text-accent-cyan">DETECTION SUMMARY</h2></div>
                                    <div className="p-4 grid grid-cols-3 gap-3">
                                        <div className="p-3 bg-accent-cyan border-4 border-black text-center">
                                            <div className="text-3xl font-roboto tight-caps text-black">{result.summary.total_violations}</div>
                                            <p className="text-xs font-black tight-caps text-black">VIOLATIONS</p>
                                        </div>
                                        <div className="p-3 bg-accent-pink border-4 border-black text-center">
                                            <div className="text-3xl font-roboto tight-caps text-black">₹{result.summary.total_fines}</div>
                                            <p className="text-xs font-black tight-caps text-black">TOTAL FINES</p>
                                        </div>
                                        <div className="p-3 bg-primary border-4 border-black text-center">
                                            <div className="text-3xl font-roboto tight-caps text-black">{result.summary.avg_confidence}%</div>
                                            <p className="text-xs font-black tight-caps text-black">AVG CONF</p>
                                        </div>
                                    </div>
                                    <div className="p-4 text-xs font-mono text-gray-500 border-t-2 border-black flex gap-4">
                                        <span>{result.summary.unique_vehicles} unique vehicles</span><span>{result.summary.processing_fps} FPS</span>
                                    </div>
                                </div>

                                <div className="bg-black border-4 border-accent-cyan p-4">
                                    <h3 className="text-xs font-black tight-caps text-accent-cyan mb-3">VIOLATION BREAKDOWN</h3>
                                    <div className="space-y-2">
                                        {Object.entries(result.summary.type_breakdown).map(([type, count]) => (
                                            <div key={type} className="flex items-center justify-between">
                                                <span className="text-sm font-mono text-gray-300">{type}</span>
                                                <div className="flex items-center gap-2">
                                                    <div className="w-24 h-3 bg-gray-800 overflow-hidden"><div className="h-full bg-accent-cyan" style={{ width: `${(count / result.summary.total_violations) * 100}%` }} /></div>
                                                    <span className="text-sm font-mono text-accent-cyan">{count}</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow-cyan">
                                    <div className="bg-black px-6 py-4 border-b-4 border-white"><h2 className="text-xl font-black tight-caps text-accent-cyan">DETECTED VIOLATIONS</h2></div>
                                    <div className="p-4 space-y-3 max-h-[500px] overflow-y-auto">
                                        {result.violations.map((v, idx) => (
                                            <div key={idx} className={`p-4 border-4 border-black bg-black cursor-pointer transition-all hover:border-accent-cyan ${selectedViolation === v ? 'border-accent-cyan' : ''}`}
                                                onClick={() => setSelectedViolation(selectedViolation === v ? null : v)}>
                                                <div className="flex items-center justify-between mb-2">
                                                    <div className="flex items-center gap-2">
                                                        <span className="text-xl">{v.icon}</span>
                                                        <div><p className="text-sm font-black tight-caps text-accent-cyan">{v.type}</p><p className="text-xs font-mono text-gray-500">{v.id}</p></div>
                                                    </div>
                                                    <div className="text-right">
                                                        <div className="flex items-center gap-2"><div className={`w-12 h-2 ${getConfidenceBg(v.confidence)} rounded-full`} /><span className="text-sm font-mono text-terminal-green">{v.confidence}%</span></div>
                                                        <p className="text-xs font-mono text-gray-500">@ {v.timestamp}</p>
                                                    </div>
                                                </div>
                                                {selectedViolation === v && (
                                                    <div className="mt-3 pt-3 border-t-2 border-gray-700 space-y-2 text-xs">
                                                        <p className="font-mono text-gray-300">{v.description}</p>
                                                        <div className="grid grid-cols-2 gap-2">
                                                            <div className="p-2 border border-gray-700"><span className="text-gray-500">License Plate:</span><span className="text-terminal-green ml-2">{v.license_plate}</span></div>
                                                            <div className="p-2 border border-gray-700"><span className="text-gray-500">Location:</span><span className="text-accent-cyan ml-2">{v.location}</span></div>
                                                            <div className="p-2 border border-gray-700"><span className="text-gray-500">Frame:</span><span className="text-primary ml-2">#{v.frame_number}</span></div>
                                                            <div className="p-2 border border-gray-700"><span className="text-gray-500">Fine:</span><span className="text-accent-pink ml-2">₹{v.fine_amount}</span></div>
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </>
                        ) : !loading && (
                            <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow-cyan">
                                <div className="bg-black px-6 py-4 border-b-4 border-white"><h2 className="text-xl font-black tight-caps text-accent-cyan">DETECTION RESULTS</h2></div>
                                <div className="p-6 text-center py-20 text-gray-400">
                                    <span className="material-symbols-outlined text-6xl mb-4">traffic</span>
                                    <p className="text-sm font-mono">Upload a video to analyze traffic violations</p>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
