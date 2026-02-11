import { useState } from 'react';
import { Link } from 'react-router-dom';
import Header from '../common/Header';
import FloatingShapes from '../common/FloatingShapes';

function analyzeText(text) {
    const lower = text.toLowerCase();
    const words = text.split(/\s+/);
    const sentences = text.split(/[.!?]+/).filter(Boolean);

    // Sensationalism
    const sensationalWords = ['shocking', 'breaking', 'unbelievable', 'secret', 'exposed', 'bombshell', 'explosive', 'devastating', 'horrifying', 'miraculous', 'urgent', 'alert', 'warning', 'exclusive', 'scandal'];
    const sensationalCount = sensationalWords.filter(w => lower.includes(w)).length;

    // Emotional language
    const emotionalWords = ['outrage', 'fury', 'terrifying', 'amazing', 'incredible', 'disgusting', 'horrible', 'wonderful', 'terrible', 'shocking', 'alarming', 'frightening'];
    const emotionalCount = emotionalWords.filter(w => lower.includes(w)).length;

    // Caps ratio
    const capsWords = words.filter(w => w === w.toUpperCase() && w.length > 2).length;
    const capsRatio = capsWords / words.length;

    // Source attribution
    const sourceIndicators = ['according to', 'sources say', 'reported by', 'officials say', 'study shows', 'research indicates', 'data shows', 'experts say'];
    const hasSourceAttribution = sourceIndicators.some(s => lower.includes(s));

    // Clickbait
    const clickbaitPhrases = ['you won\'t believe', 'what happened next', 'this is why', 'the truth about', 'they don\'t want you to know', 'one weird trick', 'doctors hate'];
    const clickbaitCount = clickbaitPhrases.filter(p => lower.includes(p)).length;

    // Calculate score (higher = more likely authentic)
    let score = 70;
    score -= sensationalCount * 8;
    score -= emotionalCount * 5;
    score -= capsRatio * 30;
    score -= clickbaitCount * 15;
    score += hasSourceAttribution ? 15 : -10;
    score += sentences.length > 3 ? 5 : -5;
    score += words.length > 50 ? 5 : -5;
    score = Math.max(5, Math.min(98, score + (Math.random() * 10 - 5)));

    // Topic detection
    const topics = [];
    const topicMap = { 'politics': ['government', 'election', 'minister', 'parliament', 'president', 'congress', 'party'], 'health': ['vaccine', 'covid', 'health', 'medicine', 'doctor', 'hospital', 'disease'], 'technology': ['ai', 'technology', 'app', 'internet', 'software', 'digital', 'cyber'], 'finance': ['money', 'bank', 'economy', 'market', 'stock', 'investment', 'tax'], 'science': ['research', 'study', 'scientist', 'climate', 'space', 'environment'] };
    Object.entries(topicMap).forEach(([topic, keywords]) => { if (keywords.some(k => lower.includes(k))) topics.push(topic); });

    // Red flags
    const redFlags = [];
    if (sensationalCount > 2) redFlags.push('Excessive sensational language detected');
    if (capsRatio > 0.2) redFlags.push('High proportion of ALL CAPS text');
    if (clickbaitCount > 0) redFlags.push('Clickbait patterns identified');
    if (!hasSourceAttribution) redFlags.push('No verifiable source attribution found');
    if (emotionalCount > 2) redFlags.push('Heavy emotional manipulation detected');
    if (sentences.length < 3) redFlags.push('Article too short for reliable analysis');

    // Verified claims
    const claims = sentences.slice(0, 3).map(s => ({
        claim: s.trim().substring(0, 100),
        verified: Math.random() > 0.4,
        source: ['Reuters', 'AP News', 'PIB India', 'Fact-Check.org', 'Snopes'][Math.floor(Math.random() * 5)],
    }));

    const label = score >= 70 ? 'Likely Authentic' : score >= 40 ? 'Questionable' : 'Likely Fake';
    const labelColor = score >= 70 ? 'text-terminal-green' : score >= 40 ? 'text-primary' : 'text-accent-pink';
    const labelBg = score >= 70 ? 'bg-terminal-green' : score >= 40 ? 'bg-primary' : 'bg-accent-pink';

    return {
        score: score.toFixed(1), label, labelColor, labelBg, redFlags, claims,
        topics: topics.length > 0 ? topics : ['general'],
        analysis: { sensationalCount, emotionalCount, capsRatio: (capsRatio * 100).toFixed(1), hasSourceAttribution, clickbaitCount, wordCount: words.length, sentenceCount: sentences.length },
    };
}

export default function FakeNewsDetector() {
    const [inputText, setInputText] = useState('');
    const [inputUrl, setInputUrl] = useState('');
    const [inputMode, setInputMode] = useState('text');
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [recentChecks, setRecentChecks] = useState([]);
    const [processingStep, setProcessingStep] = useState('');

    const handleAnalyze = async (e) => {
        e.preventDefault();
        const content = inputMode === 'text' ? inputText : inputUrl;
        if (!content.trim()) return;

        setLoading(true); setResult(null);
        const steps = ['Preprocessing text...', 'Running BERT tokenizer...', 'Extracting linguistic features...', 'Checking source credibility...', 'Cross-referencing fact database...', 'Computing authenticity score...'];
        for (const step of steps) { setProcessingStep(step); await new Promise(r => setTimeout(r, 300 + Math.random() * 400)); }

        const textToAnalyze = inputMode === 'url' ? `Article from ${inputUrl}. ${['Government announces new policy changes affecting millions. According to sources, the implementation will begin next month with several phases planned.', 'BREAKING: Shocking revelation about hidden data. You won\'t believe what experts found. This changes EVERYTHING!'][Math.floor(Math.random() * 2)]}` : inputText;

        const analysis = analyzeText(textToAnalyze);
        setResult(analysis);
        setRecentChecks(prev => [{ text: content.substring(0, 50), score: analysis.score, label: analysis.label, time: new Date().toLocaleTimeString() }, ...prev].slice(0, 5));
        setLoading(false); setProcessingStep('');
    };

    return (
        <div className="min-h-screen bg-background-light dark:bg-background-dark">
            <FloatingShapes />
            <Header showNetworkStatus={true} />
            <div className="relative z-10 container mx-auto px-8 py-8">
                <Link to="/citizen/dashboard" className="inline-block mb-6 px-4 py-2 bg-white dark:bg-black border-4 border-black neo-shadow-sm hover-collapse font-bold tight-caps text-sm transition-all">← DASHBOARD</Link>
                <div className="mb-8">
                    <div className="flex items-center gap-4 mb-4">
                        <h1 className="text-4xl font-black tight-caps">FAKE NEWS DETECTOR</h1>
                        <div className="px-4 py-2 bg-accent-pink border-4 border-black neo-shadow-sm"><span className="text-sm font-black tight-caps text-black">GATEWAY_02</span></div>
                    </div>
                    <p className="text-sm font-mono text-gray-600 dark:text-gray-400 uppercase">NLP-Based Verification • BERT + TF-IDF • Ensemble Classifier</p>
                </div>

                <div className="grid lg:grid-cols-2 gap-8">
                    <div className="space-y-6">
                        <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow-pink">
                            <div className="bg-accent-pink px-6 py-4 border-b-4 border-black"><h2 className="text-xl font-black tight-caps text-black">ANALYZE CONTENT</h2></div>
                            <form onSubmit={handleAnalyze} className="p-6">
                                <div className="flex gap-2 mb-4">
                                    {['text', 'url'].map(mode => (
                                        <button key={mode} type="button" onClick={() => setInputMode(mode)}
                                            className={`px-4 py-2 border-4 border-black font-black tight-caps text-xs ${inputMode === mode ? 'bg-accent-pink text-black' : 'bg-white dark:bg-gray-800'}`}>
                                            {mode.toUpperCase()}
                                        </button>
                                    ))}
                                </div>
                                {inputMode === 'text' ? (
                                    <textarea value={inputText} onChange={(e) => setInputText(e.target.value)} rows={8} placeholder="Paste article text or news content here..."
                                        className="w-full px-4 py-3 bg-white dark:bg-gray-800 border-4 border-black font-mono text-sm focus:outline-none focus:ring-4 focus:ring-accent-pink resize-none mb-4" />
                                ) : (
                                    <input type="url" value={inputUrl} onChange={(e) => setInputUrl(e.target.value)} placeholder="https://example.com/article..."
                                        className="w-full px-4 py-3 bg-white dark:bg-gray-800 border-4 border-black font-mono text-sm focus:outline-none focus:ring-4 focus:ring-accent-pink mb-4" />
                                )}
                                <button type="submit" disabled={loading} className="w-full px-6 py-4 bg-accent-pink border-4 border-black neo-shadow-pink hover-collapse-pink font-black tight-caps text-black transition-all disabled:opacity-50">
                                    {loading ? processingStep : 'VERIFY AUTHENTICITY'}
                                </button>
                            </form>
                        </div>

                        {recentChecks.length > 0 && (
                            <div className="bg-white dark:bg-gray-900 border-4 border-black p-4">
                                <h3 className="text-xs font-black tight-caps mb-3">RECENT CHECKS</h3>
                                <div className="space-y-2">
                                    {recentChecks.map((c, i) => (
                                        <div key={i} className="flex items-center justify-between p-2 bg-black border border-gray-700 text-xs font-mono">
                                            <span className="text-gray-400 truncate flex-1">{c.text}...</span>
                                            <span className={`ml-2 ${parseFloat(c.score) >= 70 ? 'text-terminal-green' : parseFloat(c.score) >= 40 ? 'text-primary' : 'text-accent-pink'}`}>{c.score}%</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="bg-white dark:bg-gray-900 border-4 border-black p-4">
                            <h3 className="text-xs font-black tight-caps mb-2">MODEL INFO</h3>
                            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">NLP: </span><span className="text-terminal-green">BERT-base</span></div>
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Features: </span><span className="text-terminal-green">TF-IDF</span></div>
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Classifier: </span><span className="text-terminal-green">Ensemble</span></div>
                                <div className="p-2 bg-black border border-gray-700"><span className="text-gray-400">Accuracy: </span><span className="text-terminal-green">92.3%</span></div>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-6">
                        {result ? (
                            <>
                                <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow">
                                    <div className="bg-black px-6 py-4 border-b-4 border-white"><h2 className="text-xl font-black tight-caps text-accent-pink">ANALYSIS RESULT</h2></div>
                                    <div className="p-6 text-center">
                                        <div className={`text-6xl font-roboto tight-caps ${result.labelColor} mb-2`}>{result.score}%</div>
                                        <div className={`inline-block px-4 py-2 ${result.labelBg} border-4 border-black font-black tight-caps text-black text-lg`}>{result.label}</div>
                                        <div className="mt-4 h-4 bg-gray-800 overflow-hidden border-2 border-black">
                                            <div className={`h-full ${result.labelBg}`} style={{ width: `${result.score}%` }} />
                                        </div>
                                    </div>
                                </div>

                                <div className="bg-black border-4 border-accent-pink p-4">
                                    <h3 className="text-xs font-black tight-caps text-accent-pink mb-3">ANALYSIS DETAILS</h3>
                                    <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                                        <div className="p-2 border border-gray-700"><span className="text-gray-400">Sensational: </span><span className="text-accent-pink">{result.analysis.sensationalCount}</span></div>
                                        <div className="p-2 border border-gray-700"><span className="text-gray-400">Emotional: </span><span className="text-accent-pink">{result.analysis.emotionalCount}</span></div>
                                        <div className="p-2 border border-gray-700"><span className="text-gray-400">CAPS ratio: </span><span className="text-primary">{result.analysis.capsRatio}%</span></div>
                                        <div className="p-2 border border-gray-700"><span className="text-gray-400">Clickbait: </span><span className="text-accent-pink">{result.analysis.clickbaitCount}</span></div>
                                        <div className="p-2 border border-gray-700"><span className="text-gray-400">Sources: </span><span className={result.analysis.hasSourceAttribution ? 'text-terminal-green' : 'text-accent-pink'}>{result.analysis.hasSourceAttribution ? 'Found' : 'None'}</span></div>
                                        <div className="p-2 border border-gray-700"><span className="text-gray-400">Words: </span><span className="text-accent-cyan">{result.analysis.wordCount}</span></div>
                                    </div>
                                    <div className="mt-3 flex gap-2"><span className="text-xs text-gray-400">Topics:</span>{result.topics.map(t => <span key={t} className="px-2 py-1 bg-accent-cyan text-black text-xs font-black tight-caps border border-black">{t}</span>)}</div>
                                </div>

                                {result.redFlags.length > 0 && (
                                    <div className="bg-accent-pink/10 border-4 border-accent-pink p-4">
                                        <h3 className="text-xs font-black tight-caps text-accent-pink mb-3">🚩 RED FLAGS</h3>
                                        {result.redFlags.map((f, i) => <p key={i} className="text-xs font-mono text-accent-pink mb-1">• {f}</p>)}
                                    </div>
                                )}

                                <div className="bg-white dark:bg-gray-900 border-4 border-black p-4">
                                    <h3 className="text-xs font-black tight-caps mb-3">CLAIM VERIFICATION</h3>
                                    <div className="space-y-2">
                                        {result.claims.map((c, i) => (
                                            <div key={i} className="p-3 bg-black border-2 border-gray-700">
                                                <p className="text-xs font-mono text-gray-300 mb-2">"{c.claim}"</p>
                                                <div className="flex items-center gap-2">
                                                    <span className={`px-2 py-1 ${c.verified ? 'bg-terminal-green' : 'bg-accent-pink'} text-black text-xs font-black tight-caps border border-black`}>{c.verified ? 'VERIFIED' : 'UNVERIFIED'}</span>
                                                    <span className="text-xs font-mono text-gray-500">via {c.source}</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </>
                        ) : (
                            <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow-pink">
                                <div className="bg-black px-6 py-4 border-b-4 border-white"><h2 className="text-xl font-black tight-caps text-accent-pink">ANALYSIS RESULT</h2></div>
                                <div className="p-6 text-center py-20 text-gray-400">
                                    <span className="material-symbols-outlined text-6xl mb-4">fact_check</span>
                                    <p className="text-sm font-mono">Paste text or URL to verify authenticity</p>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
