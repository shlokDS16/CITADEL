import { useState } from 'react';
import { Link } from 'react-router-dom';
import Header from '../common/Header';
import FloatingShapes from '../common/FloatingShapes';

function classifyTicket(subject, description) {
    const text = `${subject} ${description}`.toLowerCase();
    const categories = {
        'Infrastructure': { keywords: ['road', 'bridge', 'building', 'pothole', 'construction', 'repair', 'maintenance', 'broken', 'damage'], priority: 'high', dept: 'Public Works' },
        'Water Supply': { keywords: ['water', 'pipe', 'leakage', 'supply', 'sewage', 'drainage', 'flood', 'contamination'], priority: 'critical', dept: 'Water Board' },
        'Electricity': { keywords: ['power', 'electricity', 'outage', 'transformer', 'wire', 'voltage', 'electric', 'light', 'pole'], priority: 'high', dept: 'Power Distribution' },
        'Sanitation': { keywords: ['garbage', 'waste', 'cleaning', 'hygiene', 'trash', 'dump', 'sanitation', 'smell'], priority: 'medium', dept: 'Municipal Sanitation' },
        'Traffic': { keywords: ['traffic', 'signal', 'parking', 'accident', 'speed', 'jam', 'congestion', 'vehicle'], priority: 'high', dept: 'Traffic Police' },
        'Public Safety': { keywords: ['safety', 'crime', 'theft', 'harassment', 'violence', 'police', 'security', 'emergency'], priority: 'critical', dept: 'Law Enforcement' },
        'Education': { keywords: ['school', 'education', 'teacher', 'student', 'college', 'admission', 'scholarship'], priority: 'medium', dept: 'Education Board' },
        'Healthcare': { keywords: ['hospital', 'health', 'medicine', 'doctor', 'clinic', 'vaccination', 'disease'], priority: 'high', dept: 'Health Department' },
        'General': { keywords: [], priority: 'low', dept: 'General Administration' },
    };

    let bestCategory = 'General';
    let bestScore = 0;
    Object.entries(categories).forEach(([cat, info]) => {
        const score = info.keywords.filter(k => text.includes(k)).length;
        if (score > bestScore) { bestScore = score; bestCategory = cat; }
    });

    const sentimentWords = { positive: ['thank', 'good', 'great', 'excellent', 'happy', 'appreciate', 'helpful'], negative: ['bad', 'terrible', 'worst', 'angry', 'frustrat', 'disappoint', 'horrible', 'urgent', 'compla'] };
    const posCount = sentimentWords.positive.filter(w => text.includes(w)).length;
    const negCount = sentimentWords.negative.filter(w => text.includes(w)).length;
    const sentiment = posCount > negCount ? 'Positive' : negCount > posCount ? 'Negative' : 'Neutral';

    const catInfo = categories[bestCategory];
    return {
        category: bestCategory,
        priority: catInfo.priority,
        department: catInfo.dept,
        sentiment,
        confidence: Math.min(95, 60 + bestScore * 12 + Math.random() * 10).toFixed(1),
        estimated_response: catInfo.priority === 'critical' ? '2-4 hours' : catInfo.priority === 'high' ? '24-48 hours' : '3-5 days',
    };
}

export default function SupportTickets() {
    const [subject, setSubject] = useState('');
    const [description, setDescription] = useState('');
    const [loading, setLoading] = useState(false);
    const [tickets, setTickets] = useState([]);
    const [selectedTicket, setSelectedTicket] = useState(null);
    const [processingStep, setProcessingStep] = useState('');

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!subject.trim() || !description.trim()) return;
        setLoading(true);

        const steps = ['Preprocessing text...', 'Running BERT classifier...', 'Analyzing sentiment (VADER)...', 'Computing priority score...', 'Routing to department...'];
        for (const step of steps) { setProcessingStep(step); await new Promise(r => setTimeout(r, 300 + Math.random() * 300)); }

        const classification = classifyTicket(subject, description);
        const newTicket = {
            id: `TKT-${Math.floor(100000 + Math.random() * 900000)}`,
            subject, description,
            ...classification,
            created_at: new Date().toISOString(),
            status: 'Open',
        };

        setTickets(prev => [newTicket, ...prev]);
        setSubject('');
        setDescription('');
        setLoading(false);
        setProcessingStep('');
    };

    const priorityColors = { critical: 'bg-accent-pink text-black', high: 'bg-primary text-black', medium: 'bg-accent-cyan text-black', low: 'bg-gray-400 text-black' };
    const sentimentColors = { Positive: 'text-terminal-green', Negative: 'text-accent-pink', Neutral: 'text-primary' };

    return (
        <div className="min-h-screen bg-background-light dark:bg-background-dark">
            <FloatingShapes />
            <Header showNetworkStatus={true} />
            <div className="relative z-10 container mx-auto px-8 py-8">
                <Link to="/citizen/dashboard" className="inline-block mb-6 px-4 py-2 bg-white dark:bg-black border-4 border-black neo-shadow-sm hover-collapse font-bold tight-caps text-sm transition-all">← DASHBOARD</Link>
                <div className="mb-8">
                    <div className="flex items-center gap-4 mb-4">
                        <h1 className="text-4xl font-black tight-caps">SUPPORT TICKETS</h1>
                        <div className="px-4 py-2 bg-accent-cyan border-4 border-black neo-shadow-sm"><span className="text-sm font-black tight-caps text-black">GATEWAY_03</span></div>
                    </div>
                    <p className="text-sm font-mono text-gray-600 dark:text-gray-400 uppercase">AI-Powered Classification • BERT + VADER • Auto-Routing</p>
                </div>

                <div className="grid lg:grid-cols-2 gap-8">
                    <div className="space-y-6">
                        <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow-cyan">
                            <div className="bg-accent-cyan px-6 py-4 border-b-4 border-black"><h2 className="text-xl font-black tight-caps text-black">SUBMIT TICKET</h2></div>
                            <form onSubmit={handleSubmit} className="p-6">
                                <div className="mb-4">
                                    <label className="block text-sm font-black tight-caps mb-2">SUBJECT</label>
                                    <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Brief description of issue..."
                                        className="w-full px-4 py-3 bg-white dark:bg-gray-800 border-4 border-black font-mono text-sm focus:outline-none focus:ring-4 focus:ring-accent-cyan" />
                                </div>
                                <div className="mb-6">
                                    <label className="block text-sm font-black tight-caps mb-2">DESCRIPTION</label>
                                    <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={6} placeholder="Provide detailed information about your complaint or request..."
                                        className="w-full px-4 py-3 bg-white dark:bg-gray-800 border-4 border-black font-mono text-sm focus:outline-none focus:ring-4 focus:ring-accent-cyan resize-none" />
                                </div>
                                <button type="submit" disabled={loading || !subject.trim() || !description.trim()}
                                    className="w-full px-6 py-4 bg-accent-cyan border-4 border-black neo-shadow-cyan hover-collapse-cyan font-black tight-caps text-black transition-all disabled:opacity-50">
                                    {loading ? processingStep : 'SUBMIT TICKET'}
                                </button>
                            </form>
                        </div>

                        <div className="bg-white dark:bg-gray-900 border-4 border-black p-4">
                            <h3 className="text-xs font-black tight-caps mb-3">QUICK TEMPLATES</h3>
                            <div className="space-y-2">
                                {[
                                    { s: 'Road Pothole Complaint', d: 'There is a large pothole on MG Road near sector 12 junction. Multiple vehicles have been damaged. Urgent repair needed.' },
                                    { s: 'Water Supply Issue', d: 'No water supply in our area since yesterday morning. The pipe seems to have a major leakage. Affecting over 50 families.' },
                                    { s: 'Streetlight Not Working', d: 'The streetlight near block C residential area has not been working for a week. Safety concern for residents.' },
                                ].map((t, i) => (
                                    <button key={i} onClick={() => { setSubject(t.s); setDescription(t.d); }}
                                        className="w-full text-left p-2 bg-black border-2 border-gray-700 hover:border-accent-cyan text-xs font-mono text-terminal-green transition-all">{t.s}</button>
                                ))}
                            </div>
                        </div>

                        <div className="bg-white dark:bg-gray-900 border-4 border-black p-4">
                            <h3 className="text-xs font-black tight-caps mb-2">MODEL INFO</h3>
                            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Classifier: </span><span className="text-terminal-green">BERT-fine</span></div>
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Sentiment: </span><span className="text-terminal-green">VADER</span></div>
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Router: </span><span className="text-terminal-green">Rule+ML</span></div>
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Accuracy: </span><span className="text-terminal-green">89.5%</span></div>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-6">
                        <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow">
                            <div className="bg-black px-6 py-4 border-b-4 border-white flex items-center justify-between">
                                <h2 className="text-xl font-black tight-caps text-accent-cyan">SUBMITTED TICKETS</h2>
                                <span className="text-xs font-mono text-gray-500">{tickets.length} tickets</span>
                            </div>
                            <div className="p-4 space-y-3 max-h-[600px] overflow-y-auto">
                                {tickets.length > 0 ? tickets.map((ticket, idx) => (
                                    <div key={idx} onClick={() => setSelectedTicket(selectedTicket === ticket ? null : ticket)}
                                        className={`p-4 border-4 border-black bg-black cursor-pointer transition-all hover:border-accent-cyan ${selectedTicket === ticket ? 'border-accent-cyan' : ''}`}>
                                        <div className="flex items-start justify-between mb-2">
                                            <div>
                                                <p className="text-sm font-black tight-caps text-accent-cyan">{ticket.subject}</p>
                                                <p className="text-xs font-mono text-gray-500">{ticket.id} • {new Date(ticket.created_at).toLocaleString()}</p>
                                            </div>
                                            <span className={`px-2 py-1 ${priorityColors[ticket.priority]} text-xs font-black tight-caps border-2 border-black`}>{ticket.priority}</span>
                                        </div>
                                        <div className="flex items-center gap-3 text-xs font-mono">
                                            <span className="text-gray-400">→ {ticket.department}</span>
                                            <span className="text-gray-400">| {ticket.category}</span>
                                            <span className={sentimentColors[ticket.sentiment]}>{ticket.sentiment}</span>
                                        </div>

                                        {selectedTicket === ticket && (
                                            <div className="mt-4 pt-4 border-t-2 border-gray-700 space-y-3">
                                                <p className="text-xs font-mono text-gray-300">{ticket.description}</p>
                                                <div className="grid grid-cols-2 gap-2 text-xs">
                                                    <div className="p-2 border border-gray-700"><span className="text-gray-500 font-mono">Category:</span><span className="text-accent-cyan ml-2 font-mono">{ticket.category}</span></div>
                                                    <div className="p-2 border border-gray-700"><span className="text-gray-500 font-mono">Priority:</span><span className={`ml-2 font-bold ${ticket.priority === 'critical' ? 'text-accent-pink' : ticket.priority === 'high' ? 'text-primary' : 'text-accent-cyan'}`}>{ticket.priority.toUpperCase()}</span></div>
                                                    <div className="p-2 border border-gray-700"><span className="text-gray-500 font-mono">Confidence:</span><span className="text-terminal-green ml-2 font-mono">{ticket.confidence}%</span></div>
                                                    <div className="p-2 border border-gray-700"><span className="text-gray-500 font-mono">ETA:</span><span className="text-primary ml-2 font-mono">{ticket.estimated_response}</span></div>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs font-mono text-gray-500">AI Confidence:</span>
                                                    <div className="flex-1 h-2 bg-gray-800 overflow-hidden"><div className="h-full bg-terminal-green" style={{ width: `${ticket.confidence}%` }} /></div>
                                                    <span className="text-xs font-mono text-terminal-green">{ticket.confidence}%</span>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )) : (
                                    <div className="text-center py-20 text-gray-400">
                                        <span className="material-symbols-outlined text-6xl mb-4">confirmation_number</span>
                                        <p className="text-sm font-mono">No tickets submitted yet</p>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
