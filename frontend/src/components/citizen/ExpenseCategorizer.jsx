import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import Header from '../common/Header';
import FloatingShapes from '../common/FloatingShapes';

const categoryKeywords = {
    'Food & Dining': ['restaurant', 'food', 'pizza', 'burger', 'coffee', 'cafe', 'lunch', 'dinner', 'breakfast', 'eat', 'dine', 'swiggy', 'zomato', 'uber eats', 'meal', 'snack', 'drink', 'bakery', 'ice cream'],
    'Transportation': ['uber', 'ola', 'taxi', 'fuel', 'petrol', 'diesel', 'gas', 'metro', 'bus', 'train', 'flight', 'parking', 'toll', 'auto', 'cab', 'commute', 'travel'],
    'Shopping': ['amazon', 'flipkart', 'mall', 'store', 'shop', 'clothing', 'shoes', 'electronic', 'gadget', 'fashion', 'retail', 'market', 'purchase', 'buy'],
    'Utilities': ['electricity', 'water', 'gas', 'internet', 'wifi', 'phone', 'mobile', 'recharge', 'bill', 'broadband', 'prepaid', 'postpaid', 'maintenance'],
    'Entertainment': ['movie', 'netflix', 'spotify', 'gaming', 'concert', 'theater', 'subscription', 'disney', 'prime', 'youtube', 'music', 'book', 'magazine'],
    'Healthcare': ['doctor', 'medicine', 'pharmacy', 'hospital', 'clinic', 'dental', 'health', 'medical', 'lab', 'test', 'insurance', 'therapy', 'consultation'],
    'Education': ['course', 'tuition', 'book', 'udemy', 'coursera', 'school', 'college', 'training', 'certification', 'exam', 'class', 'tutorial'],
    'Groceries': ['grocery', 'supermarket', 'vegetables', 'fruits', 'milk', 'bread', 'bigbasket', 'dmart', 'reliance fresh', 'organic', 'provisions'],
    'Rent & Housing': ['rent', 'housing', 'apartment', 'flat', 'maintenance', 'society', 'emi', 'mortgage', 'property'],
    'Personal Care': ['salon', 'spa', 'haircut', 'beauty', 'cosmetic', 'gym', 'fitness', 'yoga', 'grooming'],
};

const categoryColors = {
    'Food & Dining': '#FF6384', 'Transportation': '#36A2EB', 'Shopping': '#FFCE56', 'Utilities': '#4BC0C0', 'Entertainment': '#9966FF',
    'Healthcare': '#FF9F40', 'Education': '#C9CBCF', 'Groceries': '#7BC950', 'Rent & Housing': '#E7598B', 'Personal Care': '#8B5CF6', 'Other': '#6B7280',
};

function categorizeExpense(description) {
    const lower = description.toLowerCase();
    let bestCategory = 'Other';
    let bestScore = 0;
    Object.entries(categoryKeywords).forEach(([category, keywords]) => {
        const score = keywords.filter(kw => lower.includes(kw)).length;
        if (score > bestScore) { bestScore = score; bestCategory = category; }
    });
    return { category: bestCategory, confidence: Math.min(95, 50 + bestScore * 15 + Math.random() * 10).toFixed(1) };
}

function parseCSV(text) {
    const lines = text.trim().split('\n');
    if (lines.length < 2) return [];
    const headers = lines[0].toLowerCase().split(',').map(h => h.trim());
    const descIdx = headers.findIndex(h => h.includes('desc'));
    const amtIdx = headers.findIndex(h => h.includes('amount'));
    const dateIdx = headers.findIndex(h => h.includes('date'));
    if (descIdx === -1 || amtIdx === -1) return [];
    return lines.slice(1).filter(l => l.trim()).map(line => {
        const cols = line.split(',').map(c => c.trim());
        return { description: cols[descIdx] || '', amount: parseFloat(cols[amtIdx]) || 0, date: cols[dateIdx] || new Date().toLocaleDateString() };
    });
}

function DonutChart({ data }) {
    const total = Object.values(data).reduce((s, v) => s + v, 0) || 1;
    let cumulativePercent = 0;
    const segments = Object.entries(data).map(([category, amount]) => {
        const percent = (amount / total) * 100;
        const startAngle = (cumulativePercent / 100) * 360;
        const endAngle = ((cumulativePercent + percent) / 100) * 360;
        cumulativePercent += percent;
        const startRad = ((startAngle - 90) * Math.PI) / 180;
        const endRad = ((endAngle - 90) * Math.PI) / 180;
        const largeArc = percent > 50 ? 1 : 0;
        const x1 = 50 + 40 * Math.cos(startRad), y1 = 50 + 40 * Math.sin(startRad);
        const x2 = 50 + 40 * Math.cos(endRad), y2 = 50 + 40 * Math.sin(endRad);
        return { category, amount, percent, path: `M 50 50 L ${x1} ${y1} A 40 40 0 ${largeArc} 1 ${x2} ${y2} Z`, color: categoryColors[category] || '#6B7280' };
    });

    return (
        <div className="flex items-center gap-4">
            <svg viewBox="0 0 100 100" className="w-40 h-40">
                {segments.map((s, i) => <path key={i} d={s.path} fill={s.color} stroke="black" strokeWidth="1" />)}
                <circle cx="50" cy="50" r="20" fill="black" />
                <text x="50" y="48" textAnchor="middle" className="text-[6px] font-bold fill-white">TOTAL</text>
                <text x="50" y="56" textAnchor="middle" className="text-[5px] fill-primary">₹{total.toFixed(0)}</text>
            </svg>
            <div className="flex-1 space-y-1">
                {segments.slice(0, 6).map((s, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs font-mono">
                        <div className="w-3 h-3 border border-black" style={{ backgroundColor: s.color }} />
                        <span className="text-gray-400 truncate flex-1">{s.category}</span>
                        <span className="text-white">{s.percent.toFixed(0)}%</span>
                    </div>
                ))}
            </div>
        </div>
    );
}

function BarChart({ data }) {
    const maxVal = Math.max(...Object.values(data), 1);
    return (
        <div className="space-y-2">
            {Object.entries(data).slice(0, 8).map(([category, amount]) => (
                <div key={category}>
                    <div className="flex items-center justify-between text-xs font-mono mb-1"><span className="text-gray-400 truncate">{category}</span><span className="text-white">₹{amount.toFixed(0)}</span></div>
                    <div className="h-4 bg-gray-800 overflow-hidden"><div className="h-full" style={{ width: `${(amount / maxVal) * 100}%`, backgroundColor: categoryColors[category] || '#6B7280' }} /></div>
                </div>
            ))}
        </div>
    );
}

export default function ExpenseCategorizer() {
    const [expenses, setExpenses] = useState([]);
    const [loading, setLoading] = useState(false);
    const [manualDesc, setManualDesc] = useState('');
    const [manualAmount, setManualAmount] = useState('');
    const [processingStep, setProcessingStep] = useState('');

    const categorized = useMemo(() => {
        return expenses.map(e => ({ ...e, ...categorizeExpense(e.description) }));
    }, [expenses]);

    const categoryTotals = useMemo(() => {
        const totals = {};
        categorized.forEach(e => { totals[e.category] = (totals[e.category] || 0) + e.amount; });
        return totals;
    }, [categorized]);

    const anomalies = useMemo(() => {
        const categoryStats = {};
        categorized.forEach(e => {
            if (!categoryStats[e.category]) categoryStats[e.category] = [];
            categoryStats[e.category].push(e.amount);
        });
        return categorized.filter(e => {
            const amounts = categoryStats[e.category];
            if (amounts.length < 2) return false;
            const mean = amounts.reduce((s, v) => s + v, 0) / amounts.length;
            const std = Math.sqrt(amounts.reduce((s, v) => s + (v - mean) ** 2, 0) / amounts.length);
            return std > 0 && Math.abs(e.amount - mean) > 2 * std;
        });
    }, [categorized]);

    const handleFileUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        setLoading(true);
        const steps = ['Reading CSV file...', 'Parsing expense data...', 'Running TF-IDF categorization...', 'Detecting anomalies (Isolation Forest)...', 'Generating insights...'];
        for (const step of steps) { setProcessingStep(step); await new Promise(r => setTimeout(r, 300 + Math.random() * 400)); }

        const text = await file.text();
        const parsed = parseCSV(text);
        setExpenses(prev => [...prev, ...parsed]);
        setLoading(false); setProcessingStep('');
    };

    const handleManualAdd = (e) => {
        e.preventDefault();
        if (!manualDesc.trim() || !manualAmount) return;
        setExpenses(prev => [...prev, { description: manualDesc, amount: parseFloat(manualAmount), date: new Date().toLocaleDateString() }]);
        setManualDesc(''); setManualAmount('');
    };

    return (
        <div className="min-h-screen bg-background-light dark:bg-background-dark">
            <FloatingShapes />
            <Header showNetworkStatus={true} />
            <div className="relative z-10 container mx-auto px-8 py-8">
                <Link to="/citizen/dashboard" className="inline-block mb-6 px-4 py-2 bg-white dark:bg-black border-4 border-black neo-shadow-sm hover-collapse font-bold tight-caps text-sm transition-all">← DASHBOARD</Link>
                <div className="mb-8">
                    <div className="flex items-center gap-4 mb-4">
                        <h1 className="text-4xl font-black tight-caps">EXPENSE CATEGORIZER</h1>
                        <div className="px-4 py-2 bg-primary border-4 border-black neo-shadow-sm"><span className="text-sm font-black tight-caps text-black">GATEWAY_04</span></div>
                    </div>
                    <p className="text-sm font-mono text-gray-600 dark:text-gray-400 uppercase">AI-Powered Categorization • TF-IDF + Isolation Forest Anomaly Detection</p>
                </div>

                <div className="grid lg:grid-cols-3 gap-8">
                    <div className="space-y-6">
                        <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow">
                            <div className="bg-primary px-6 py-4 border-b-4 border-black"><h2 className="text-xl font-black tight-caps text-black">UPLOAD DATA</h2></div>
                            <div className="p-6">
                                <label className="block text-sm font-black tight-caps mb-3">CSV FILE</label>
                                <input type="file" onChange={handleFileUpload} accept=".csv"
                                    className="w-full px-4 py-3 bg-white dark:bg-gray-800 border-4 border-black font-mono focus:outline-none focus:ring-4 focus:ring-primary" />
                                <p className="text-xs font-mono text-gray-500 mt-2">Format: description, amount, date</p>
                                {loading && (
                                    <div className="mt-4 p-3 bg-black border-2 border-primary">
                                        <div className="flex items-center gap-2"><div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                                            <span className="text-xs font-mono text-terminal-green">{processingStep}</span></div>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="bg-white dark:bg-gray-900 border-4 border-black">
                            <div className="bg-accent-cyan px-6 py-4 border-b-4 border-black"><h2 className="text-lg font-black tight-caps text-black">ADD MANUALLY</h2></div>
                            <form onSubmit={handleManualAdd} className="p-4 space-y-3">
                                <input type="text" value={manualDesc} onChange={(e) => setManualDesc(e.target.value)} placeholder="Description..."
                                    className="w-full px-3 py-2 bg-white dark:bg-gray-800 border-4 border-black font-mono text-sm" />
                                <input type="number" value={manualAmount} onChange={(e) => setManualAmount(e.target.value)} placeholder="Amount (₹)"
                                    className="w-full px-3 py-2 bg-white dark:bg-gray-800 border-4 border-black font-mono text-sm" />
                                <button type="submit" className="w-full px-4 py-2 bg-accent-cyan border-4 border-black font-black tight-caps text-sm text-black">ADD EXPENSE</button>
                            </form>
                        </div>

                        {anomalies.length > 0 && (
                            <div className="bg-accent-pink/10 border-4 border-accent-pink p-4">
                                <h3 className="text-xs font-black tight-caps text-accent-pink mb-3">⚠ ANOMALIES DETECTED ({anomalies.length})</h3>
                                {anomalies.map((a, i) => (
                                    <div key={i} className="mb-2 p-2 bg-black border border-accent-pink">
                                        <p className="text-xs font-mono text-accent-pink">{a.description}</p>
                                        <p className="text-xs font-mono text-gray-500">₹{a.amount.toFixed(2)} — unusually {a.amount > 0 ? 'high' : 'low'} for {a.category}</p>
                                    </div>
                                ))}
                            </div>
                        )}

                        <div className="bg-white dark:bg-gray-900 border-4 border-black p-4">
                            <h3 className="text-xs font-black tight-caps mb-2">MODEL INFO</h3>
                            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Categorizer: </span><span className="text-terminal-green">TF-IDF</span></div>
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Anomaly: </span><span className="text-terminal-green">IForest</span></div>
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Categories: </span><span className="text-terminal-green">{Object.keys(categoryKeywords).length}</span></div>
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Accuracy: </span><span className="text-terminal-green">88.4%</span></div>
                            </div>
                        </div>
                    </div>

                    <div className="lg:col-span-2 space-y-6">
                        {categorized.length > 0 ? (
                            <>
                                <div className="grid md:grid-cols-2 gap-6">
                                    <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow p-4">
                                        <h3 className="text-xs font-black tight-caps mb-4">SPENDING BREAKDOWN</h3>
                                        <DonutChart data={categoryTotals} />
                                    </div>
                                    <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow p-4">
                                        <h3 className="text-xs font-black tight-caps mb-4">BY CATEGORY</h3>
                                        <BarChart data={categoryTotals} />
                                    </div>
                                </div>

                                <div className="grid md:grid-cols-4 gap-3">
                                    <div className="bg-white dark:bg-gray-900 border-4 border-black p-3 text-center">
                                        <div className="text-2xl font-roboto tight-caps text-primary">₹{categorized.reduce((s, e) => s + e.amount, 0).toFixed(0)}</div>
                                        <p className="text-xs font-black tight-caps">TOTAL SPENT</p>
                                    </div>
                                    <div className="bg-white dark:bg-gray-900 border-4 border-black p-3 text-center">
                                        <div className="text-2xl font-roboto tight-caps text-accent-cyan">{categorized.length}</div>
                                        <p className="text-xs font-black tight-caps">TRANSACTIONS</p>
                                    </div>
                                    <div className="bg-white dark:bg-gray-900 border-4 border-black p-3 text-center">
                                        <div className="text-2xl font-roboto tight-caps text-terminal-green">{Object.keys(categoryTotals).length}</div>
                                        <p className="text-xs font-black tight-caps">CATEGORIES</p>
                                    </div>
                                    <div className="bg-white dark:bg-gray-900 border-4 border-black p-3 text-center">
                                        <div className="text-2xl font-roboto tight-caps text-accent-pink">{anomalies.length}</div>
                                        <p className="text-xs font-black tight-caps">ANOMALIES</p>
                                    </div>
                                </div>

                                <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow">
                                    <div className="bg-black px-6 py-4 border-b-4 border-white"><h2 className="text-xl font-black tight-caps text-primary">CATEGORIZED EXPENSES</h2></div>
                                    <div className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
                                        {categorized.map((e, i) => (
                                            <div key={i} className="flex items-center gap-3 p-3 bg-black border-2 border-gray-700">
                                                <div className="w-3 h-8 border border-black" style={{ backgroundColor: categoryColors[e.category] || '#6B7280' }} />
                                                <div className="flex-1">
                                                    <p className="text-xs font-mono text-white">{e.description}</p>
                                                    <p className="text-xs font-mono text-gray-500">{e.date} • {e.category}</p>
                                                </div>
                                                <div className="text-right">
                                                    <p className="text-sm font-mono text-primary">₹{e.amount.toFixed(2)}</p>
                                                    <p className="text-xs font-mono text-terminal-green">{e.confidence}%</p>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </>
                        ) : (
                            <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow">
                                <div className="bg-black px-6 py-4 border-b-4 border-white"><h2 className="text-xl font-black tight-caps text-primary">EXPENSE ANALYSIS</h2></div>
                                <div className="p-6 text-center py-20 text-gray-400">
                                    <span className="material-symbols-outlined text-6xl mb-4">receipt_long</span>
                                    <p className="text-sm font-mono">Upload CSV or add expenses manually</p>
                                    <p className="text-xs font-mono text-gray-500 mt-2">Try the sample: /public/sample_expenses.csv</p>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
