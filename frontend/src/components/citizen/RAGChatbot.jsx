import { useState, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Header from '../common/Header';
import FloatingShapes from '../common/FloatingShapes';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function callBackend(message, sessionId = null) {
    const body = {
        message: message,
        session_id: sessionId
    };

    const res = await fetch(`${API_URL}/api/chat/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });

    if (!res.ok) {
        const errText = await res.text();
        throw new Error(`Backend error ${res.status}: ${errText}`);
    }

    return await res.json();
}

export default function RAGChatbot() {
    const [messages, setMessages] = useState([
        {
            role: 'assistant',
            text: 'Welcome to the C.I.T.A.D.E.L. AI Assistant! 🏛️\n\nI\'m powered by OLLAMA (Llama 3.2) and can help you with:\n• Government services & schemes\n• Document applications (Aadhaar, Passport, PAN, etc.)\n• Tax filing, property registration, education\n• Health, pension, business registration\n• ...and any other questions you have!\n\nAsk me anything — I\'m here to help.',
            sources: [],
            confidence: 1.0,
            aiPowered: true,
        }
    ]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [streamingText, setStreamingText] = useState('');
    const [aiStatus, setAiStatus] = useState('ONLINE');
    const [sessionId, setSessionId] = useState(null);
    const chatRef = useRef(null);

    useEffect(() => { chatRef.current?.scrollTo(0, chatRef.current.scrollHeight); }, [messages, streamingText]);

    const handleSend = async (text) => {
        const query = text || input.trim();
        if (!query || loading) return;
        setMessages(prev => [...prev, { role: 'user', text: query }]);
        setInput('');
        setLoading(true);
        setStreamingText('');

        try {
            setAiStatus('PROCESSING');
            setStreamingText('⚡ Connecting to Local Ollama...');

            const result = await callBackend(query, sessionId);

            if (result.session_id && !sessionId) {
                setSessionId(result.session_id);
            }

            const aiResponse = result.answer || "No response received";
            const sources = result.sources || [];
            const confidence = result.confidence || 0.8;

            setMessages(prev => [...prev, {
                role: 'assistant',
                text: aiResponse,
                sources: sources.map(s => ({ topic: `Doc Match`, sources: [s.source_id?.slice(0, 8) || 'doc'], relevanceScore: (s.relevance * 100).toFixed(0) })),
                confidence: confidence,
                aiPowered: true,
            }]);
            setAiStatus('ONLINE');
        } catch (err) {
            console.error('Backend API error:', err);
            setAiStatus('FALLBACK');

            const fallbackText = "I apologize, but the local AI service (Ollama) is temporarily unavailable. Please make sure the backend server is running.";

            setMessages(prev => [...prev, {
                role: 'assistant',
                text: fallbackText,
                sources: [],
                confidence: 0.1,
                aiPowered: false,
            }]);

            setTimeout(() => setAiStatus('ONLINE'), 5000);
        }

        setLoading(false);
        setStreamingText('');
    };

    const statusColors = {
        ONLINE: 'text-terminal-green',
        PROCESSING: 'text-primary animate-pulse',
        FALLBACK: 'text-accent-pink',
    };

    return (
        <div className="min-h-screen bg-background-light dark:bg-background-dark">
            <FloatingShapes />
            <Header showNetworkStatus={true} />
            <div className="relative z-10 container mx-auto px-8 py-8">
                <Link to="/citizen/dashboard" className="inline-block mb-6 px-4 py-2 bg-white dark:bg-black border-4 border-black neo-shadow-sm hover-collapse font-bold tight-caps text-sm transition-all">← DASHBOARD</Link>
                <div className="mb-8">
                    <div className="flex items-center gap-4 mb-4">
                        <h1 className="text-4xl font-black tight-caps">RAG CHATBOT</h1>
                        <div className="px-4 py-2 bg-primary border-4 border-black neo-shadow-sm"><span className="text-sm font-black tight-caps text-black">GATEWAY_01</span></div>
                        <div className={`px-3 py-1 border-2 border-black ${aiStatus === 'ONLINE' ? 'bg-terminal-green' : aiStatus === 'PROCESSING' ? 'bg-primary' : 'bg-accent-pink'}`}>
                            <span className="text-xs font-black tight-caps text-black">● OLLAMA {aiStatus}</span>
                        </div>
                    </div>
                    <p className="text-sm font-mono text-gray-600 dark:text-gray-400 uppercase">Local RAG • Ollama Llama 3.2</p>
                </div>

                <div className="grid lg:grid-cols-4 gap-8">
                    {/* Sidebar */}
                    <div className="space-y-6">
                        <div className="bg-white dark:bg-gray-900 border-4 border-black p-4">
                            <h3 className="text-xs font-black tight-caps mb-2">SYSTEM INFO</h3>
                            <div className="space-y-1 text-xs font-mono text-gray-500">
                                <div className="flex justify-between"><span>LLM:</span><span className="text-terminal-green">Ollama 3.2 (Local)</span></div>
                                <div className="flex justify-between"><span>RAG Mode:</span><span className="text-terminal-green">Hybrid</span></div>
                                <div className="flex justify-between"><span>KB Status:</span><span className="text-terminal-green">Supabase Sync</span></div>
                                <div className="flex justify-between"><span>AI Status:</span><span className={statusColors[aiStatus]}>{aiStatus}</span></div>
                                <div className="flex justify-between"><span>Port:</span><span className="text-terminal-green">8000</span></div>
                            </div>
                        </div>
                    </div>

                    {/* Chat */}
                    <div className="lg:col-span-3">
                        <div className="bg-white dark:bg-gray-900 border-4 border-black neo-shadow h-[650px] flex flex-col">
                            <div className="bg-primary px-6 py-4 border-b-4 border-black flex items-center justify-between">
                                <h2 className="text-xl font-black tight-caps text-black">OLLAMA ASSISTANT</h2>
                                <div className="flex items-center gap-2">
                                    <div className={`w-2 h-2 rounded-full ${aiStatus === 'ONLINE' ? 'bg-terminal-green' : aiStatus === 'PROCESSING' ? 'bg-black animate-pulse' : 'bg-accent-pink'}`} />
                                    <span className="text-xs font-black tight-caps text-black">LOCAL AI ACTIVE</span>
                                </div>
                            </div>
                            <div ref={chatRef} className="flex-1 p-4 overflow-y-auto space-y-4 font-mono">
                                {messages.map((msg, idx) => (
                                    <div key={idx} className={`${msg.role === 'user' ? 'ml-12' : msg.role === 'system' ? 'mx-4' : 'mr-12'}`}>
                                        <div className={`p-4 border-4 border-black ${msg.role === 'user' ? 'bg-primary text-black' : msg.role === 'system' ? 'bg-accent-cyan/10 border-accent-cyan' : 'bg-black text-white'}`}>
                                            {msg.role !== 'user' && msg.role !== 'system' && (
                                                <div className="flex items-center justify-between mb-2 border-b border-gray-800 pb-2">
                                                    <p className="text-xs font-black tight-caps text-primary">🦙 CITADEL OLLAMA</p>
                                                    {msg.aiPowered !== undefined && (
                                                        <span className={`text-xs font-mono px-2 py-0.5 border ${msg.aiPowered ? 'border-terminal-green text-terminal-green' : 'border-accent-pink text-accent-pink'}`}>
                                                            {msg.aiPowered ? '⚡ OLLAMA' : '📦 OFFLINE'}
                                                        </span>
                                                    )}
                                                </div>
                                            )}
                                            <p className="text-sm whitespace-pre-wrap">{msg.text}</p>

                                            {msg.sources && msg.sources.length > 0 && (
                                                <div className="mt-3 pt-3 border-t border-gray-700">
                                                    <p className="text-xs font-black tight-caps text-gray-400 mb-2 underline decoration-primary">DOC MATCHES</p>
                                                    {msg.sources.map((s, i) => (
                                                        <div key={i} className="mb-1 text-[10px] font-mono flex justify-between">
                                                            <span><span className="text-accent-cyan">ID_{s.sources[0]}</span><span className="text-gray-500 ml-2">SIMILARITY: {s.relevanceScore}%</span></span>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                                {loading && (
                                    <div className="mr-12">
                                        <div className="p-4 border-4 border-black bg-black">
                                            <div className="flex items-center gap-3 mb-2">
                                                <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                                                <span className="text-xs font-black tight-caps text-primary uppercase">LOCAL INFERENCE IN PROGRESS</span>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <span className="text-xs font-mono text-terminal-green animate-pulse">
                                                    {streamingText || 'Ollama is thinking...'}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                            <div className="p-4 border-t-4 border-black bg-gray-50 dark:bg-gray-800/50">
                                <form onSubmit={(e) => { e.preventDefault(); handleSend(); }} className="flex gap-3">
                                    <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
                                        placeholder="Type your message..."
                                        className="flex-1 px-4 py-3 bg-white dark:bg-gray-900 border-4 border-black font-mono text-sm focus:outline-none focus:ring-4 focus:ring-primary" disabled={loading} />
                                    <button type="submit" disabled={loading || !input.trim()}
                                        className="px-8 py-3 bg-primary border-4 border-black neo-shadow-sm hover-collapse font-black tight-caps text-black transition-all disabled:opacity-50">
                                        {loading ? '...' : 'SEND'}
                                    </button>
                                </form>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
