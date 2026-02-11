import { useState, useEffect } from 'react';
import Header from '../components/common/Header';
import FloatingShapes from '../components/common/FloatingShapes';
import ModuleCard from '../components/common/ModuleCard';
import StatusWidget from '../components/common/StatusWidget';
import TerminalDisplay from '../components/common/TerminalDisplay';

const terminalLines = [
    'CITADEL_CIV v3.7.1 :: User session active',
    'Citizen services gateway: ONLINE',
    'Knowledge base sync: COMPLETE',
    'News verification DB: UPDATED',
    'Support AI classifier: READY',
    'Expense analytics engine: LOADED',
    'All citizen gateways: OPERATIONAL',
];

export default function CitizenDashboard() {
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
                        <h1 className="text-5xl font-black tight-caps">CITIZEN</h1>
                        <div className="px-4 py-2 bg-accent-pink border-4 border-black neo-shadow-sm">
                            <span className="text-sm font-black tight-caps text-black">SERVICE PORTAL</span>
                        </div>
                    </div>
                    <p className="text-sm font-mono text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                        C.I.T.A.D.E.L. Citizen Access Layer • AI-Powered Government Services
                    </p>
                </div>

                {/* Module Grid */}
                <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-8 mb-12">
                    <ModuleCard
                        title="RAG Chatbot"
                        gateway="GATEWAY_01"
                        icon="smart_toy"
                        color="primary"
                        status="OPERATIONAL"
                        subtitle="Ollama Llama-3.2 • FAISS Retrieval"
                        path="/citizen/chatbot"
                        tiltDirection="left"
                    />
                    <ModuleCard
                        title="Fake News Detector"
                        gateway="GATEWAY_02"
                        icon="fact_check"
                        color="pink"
                        status="OPERATIONAL"
                        subtitle="BERT • Ensemble Classifier"
                        path="/citizen/fake-news"
                        tiltDirection="right"
                    />
                    <ModuleCard
                        title="Support Tickets"
                        gateway="GATEWAY_03"
                        icon="confirmation_number"
                        color="cyan"
                        status="OPERATIONAL"
                        subtitle="BERT • VADER • Auto-Route"
                        path="/citizen/support-tickets"
                        tiltDirection="left"
                    />
                    <ModuleCard
                        title="Expense Categorizer"
                        gateway="GATEWAY_04"
                        icon="receipt_long"
                        color="primary"
                        status="OPERATIONAL"
                        subtitle="TF-IDF • Isolation Forest"
                        path="/citizen/expense-categorizer"
                        tiltDirection="right"
                    />
                </div>

                {/* Status & Terminal Row */}
                <div className="grid md:grid-cols-2 gap-8 mb-8">
                    <StatusWidget />
                    <TerminalDisplay lines={activeLogs} title="SESSION_LOG" />
                </div>

                {/* Stats Strip */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-white dark:bg-black border-4 border-black neo-shadow-pink p-4 text-center">
                        <div className="text-3xl font-roboto tight-caps text-accent-pink">4</div>
                        <p className="text-xs font-black tight-caps mt-1">ACTIVE SERVICES</p>
                    </div>
                    <div className="bg-white dark:bg-black border-4 border-black neo-shadow-pink p-4 text-center">
                        <div className="text-3xl font-roboto tight-caps text-terminal-green">10</div>
                        <p className="text-xs font-black tight-caps mt-1">KB DOCUMENTS</p>
                    </div>
                    <div className="bg-white dark:bg-black border-4 border-black neo-shadow-pink p-4 text-center">
                        <div className="text-3xl font-roboto tight-caps text-accent-cyan">92%</div>
                        <p className="text-xs font-black tight-caps mt-1">AI ACCURACY</p>
                    </div>
                    <div className="bg-white dark:bg-black border-4 border-black neo-shadow-pink p-4 text-center">
                        <div className="text-3xl font-roboto tight-caps text-primary">24/7</div>
                        <p className="text-xs font-black tight-caps mt-1">AVAILABILITY</p>
                    </div>
                </div>
            </div>
        </div>
    );
}
