import { useState, useEffect } from 'react';
import Header from '../components/common/Header';
import FloatingShapes from '../components/common/FloatingShapes';
import ModuleCard from '../components/common/ModuleCard';
import StatusWidget from '../components/common/StatusWidget';
import TerminalDisplay from '../components/common/TerminalDisplay';

const terminalLines = [
    'CITADEL_GOV v3.7.1 :: Bootloader initialized',
    'Loading kernel modules... OK',
    'Mounting encrypted volumes... OK',
    'Neural processing grid: ONLINE',
    'Quantum coprocessor: STANDBY',
    'Biometric auth layer: ACTIVE',
    'Threat assessment: LOW',
    'All government gateways: OPERATIONAL',
];

export default function GovernmentDashboard() {
    const [activeLogs, setActiveLogs] = useState([]);

    useEffect(() => {
        let idx = 0;
        const interval = setInterval(() => {
            if (idx < terminalLines.length) {
                setActiveLogs(prev => [...prev, terminalLines[idx]]);
                idx++;
            } else {
                clearInterval(interval);
            }
        }, 400);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="min-h-screen bg-background-light dark:bg-background-dark">
            <FloatingShapes />
            <Header showNetworkStatus={true} />

            <div className="relative z-10 container mx-auto px-8 py-8">
                {/* Title */}
                <div className="mb-10">
                    <div className="flex items-center gap-4 mb-2">
                        <h1 className="text-5xl font-black tight-caps">GOVERNMENT</h1>
                        <div className="px-4 py-2 bg-primary border-4 border-black neo-shadow-sm">
                            <span className="text-sm font-black tight-caps text-black">COMMAND CENTER</span>
                        </div>
                    </div>
                    <p className="text-sm font-mono text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                        C.I.T.A.D.E.L. Administrative Control Panel • Clearance Level: ALPHA
                    </p>
                </div>

                {/* Module Grid */}
                <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-8 mb-12">
                    <ModuleCard
                        title="Document Intelligence"
                        gateway="GATEWAY_01"
                        icon="description"
                        color="primary"
                        status="OPERATIONAL"
                        subtitle="OCR • NER • Layout Analysis"
                        path="/government/document-intelligence"
                        tiltDirection="left"
                    />
                    <ModuleCard
                        title="Resume Screening"
                        gateway="GATEWAY_02"
                        icon="person_search"
                        color="pink"
                        status="OPERATIONAL"
                        subtitle="BERT • TF-IDF Matching"
                        path="/government/resume-screening"
                        tiltDirection="right"
                    />
                    <ModuleCard
                        title="Traffic Violations"
                        gateway="GATEWAY_03"
                        icon="traffic"
                        color="cyan"
                        status="OPERATIONAL"
                        subtitle="YOLOv8 • DeepSORT • OCR"
                        path="/government/traffic-violations"
                        tiltDirection="left"
                    />
                    <ModuleCard
                        title="Anomaly Monitoring"
                        gateway="GATEWAY_04"
                        icon="monitoring"
                        color="pink"
                        status="OPERATIONAL"
                        subtitle="IoT Fusion • Isolation Forest"
                        path="/government/anomaly-monitoring"
                        tiltDirection="right"
                    />
                </div>

                {/* Status & Terminal Row */}
                <div className="grid md:grid-cols-2 gap-8 mb-8">
                    <StatusWidget />
                    <TerminalDisplay lines={activeLogs} title="SYSTEM_LOG" />
                </div>

                {/* Stats Strip */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-white dark:bg-black border-4 border-black neo-shadow p-4 text-center">
                        <div className="text-3xl font-roboto tight-caps text-primary">4</div>
                        <p className="text-xs font-black tight-caps mt-1">ACTIVE GATEWAYS</p>
                    </div>
                    <div className="bg-white dark:bg-black border-4 border-black neo-shadow p-4 text-center">
                        <div className="text-3xl font-roboto tight-caps text-terminal-green">99.7%</div>
                        <p className="text-xs font-black tight-caps mt-1">UPTIME</p>
                    </div>
                    <div className="bg-white dark:bg-black border-4 border-black neo-shadow p-4 text-center">
                        <div className="text-3xl font-roboto tight-caps text-accent-cyan">847</div>
                        <p className="text-xs font-black tight-caps mt-1">SENSORS ONLINE</p>
                    </div>
                    <div className="bg-white dark:bg-black border-4 border-black neo-shadow p-4 text-center">
                        <div className="text-3xl font-roboto tight-caps text-accent-pink">12</div>
                        <p className="text-xs font-black tight-caps mt-1">ALERTS TODAY</p>
                    </div>
                </div>
            </div>
        </div>
    );
}
