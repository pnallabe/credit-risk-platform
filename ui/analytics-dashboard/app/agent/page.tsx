"use client";

export const dynamic = "force-dynamic";

import { useState, useRef, useEffect, useCallback } from "react";
import { DashboardShell } from "@/components/DashboardShell";
import ReactMarkdown from "react-markdown";

type Persona = "data_analyst" | "business_analyst";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: string[];
  isStreaming?: boolean;
}

const PERSONA_CONFIG: Record<Persona, { label: string; icon: string; color: string }> = {
  data_analyst: { label: "Data Analyst", icon: "🔬", color: "bg-blue-600 text-white" },
  business_analyst: { label: "Business Analyst", icon: "📊", color: "bg-purple-600 text-white" },
};

const AGENT_API = process.env.NEXT_PUBLIC_AGENT_API_URL ?? "http://localhost:8082";

function SqlBlock({ code }: { code: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="my-2 border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((p) => !p)}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-900 text-gray-300 text-xs font-mono hover:bg-gray-800"
      >
        <span>📄 Show SQL</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <pre className="px-3 py-3 bg-gray-950 text-green-400 text-xs overflow-x-auto">{code}</pre>
      )}
    </div>
  );
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-sm mr-2 flex-shrink-0">🤖</div>
      )}
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm ${
          isUser ? "bg-blue-600 text-white rounded-br-sm" : "bg-white border border-gray-200 text-gray-800 rounded-bl-sm shadow-sm"
        }`}
      >
        {msg.toolCalls && msg.toolCalls.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {msg.toolCalls.map((t, i) => (
              <span key={i} className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full font-medium">
                🔧 {t}
              </span>
            ))}
          </div>
        )}
        {isUser ? (
          <p>{msg.content}</p>
        ) : (
          <ReactMarkdown
            components={{
              // Render SQL code blocks as collapsible
              code({ className, children, ...props }) {
                const isSQL = className?.includes("sql");
                if (isSQL) {
                  return <SqlBlock code={String(children).trim()} />;
                }
                return <code className="bg-gray-100 text-gray-800 px-1 rounded text-xs font-mono" {...props}>{children}</code>;
              },
              pre({ children }) {
                return <>{children}</>;
              },
            }}
          >
            {msg.isStreaming ? msg.content + "▌" : msg.content}
          </ReactMarkdown>
        )}
      </div>
      {isUser && (
        <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-sm ml-2 flex-shrink-0">👤</div>
      )}
    </div>
  );
}

export default function AgentChatPage() {
  const [persona, setPersona] = useState<Persona>("data_analyst");
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content: `Hi there! I'm your **Credit Risk AI Assistant**. Ask me about portfolio metrics, model performance, fair lending compliance, or data quality. I can run SQL queries on your behalf.`,
    },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [showReport, setShowReport] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const createSession = useCallback(async (p: Persona) => {
    const res = await fetch(`${AGENT_API}/agent/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona: p }),
    });
    const data = await res.json();
    setSessionId(data.session_id);
    return data.session_id;
  }, []);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");

    const userMsg: Message = { id: `u-${Date.now()}`, role: "user", content: text };
    const assistantMsgId = `a-${Date.now()}`;
    const assistantMsg: Message = { id: assistantMsgId, role: "assistant", content: "", isStreaming: true, toolCalls: [] };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setStreaming(true);

    let sid = sessionId;
    if (!sid) {
      sid = await createSession(persona);
    }

    esRef.current?.close();

    // Use POST + SSE via fetch streaming
    const res = await fetch(`${AGENT_API}/agent/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sid, message: text, persona }),
    });

    const reader = res.body?.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const processLine = (line: string) => {
      if (!line.startsWith("data: ")) return;
      const payload = line.slice(6);
      if (payload === "[DONE]") {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantMsgId ? { ...m, isStreaming: false } : m))
        );
        setStreaming(false);
        return;
      }
      try {
        const d = JSON.parse(payload);
        if (d.token) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId ? { ...m, content: m.content + d.token } : m
            )
          );
        }
        if (d.tool_call) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, toolCalls: [...(m.toolCalls ?? []), d.tool_call] }
                : m
            )
          );
        }
      } catch {}
    };

    if (reader) {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) processLine(line);
      }
    }
    setStreaming(false);
    setMessages((prev) =>
      prev.map((m) => (m.id === assistantMsgId ? { ...m, isStreaming: false } : m))
    );
  }, [input, streaming, sessionId, persona, createSession]);

  const newChat = () => {
    esRef.current?.close();
    setSessionId(null);
    setMessages([
      {
        id: "welcome-new",
        role: "assistant",
        content: "New conversation started! How can I help you?",
      },
    ]);
    setStreaming(false);
  };

  const switchPersona = (p: Persona) => {
    setPersona(p);
    setSessionId(null); // New session for new persona
  };

  return (
    <DashboardShell role="data_scientist" userName="User">
      <div className="flex flex-col h-[calc(100vh-140px)] max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-bold text-gray-900">AI Risk Assistant</h2>
            <p className="text-xs text-gray-500">Powered by GPT-4o · ReAct Agent · SSE Streaming</p>
          </div>
          <div className="flex items-center gap-2">
            {/* Persona toggle */}
            <div className="flex bg-gray-100 rounded-lg p-1 gap-1">
              {(Object.keys(PERSONA_CONFIG) as Persona[]).map((p) => (
                <button
                  key={p}
                  onClick={() => switchPersona(p)}
                  className={`text-xs px-3 py-1.5 rounded-md font-medium transition-all ${
                    persona === p ? PERSONA_CONFIG[p].color : "text-gray-600 hover:bg-gray-200"
                  }`}
                >
                  {PERSONA_CONFIG[p].icon} {PERSONA_CONFIG[p].label}
                </button>
              ))}
            </div>
            <button
              onClick={() => setShowReport(true)}
              className="text-xs bg-gray-900 text-white px-3 py-1.5 rounded-lg hover:bg-gray-800"
            >
              📋 Report
            </button>
            <button
              onClick={newChat}
              className="text-xs border border-gray-300 text-gray-600 px-3 py-1.5 rounded-lg hover:bg-gray-50"
            >
              + New Chat
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto bg-gray-50 rounded-xl p-4 border border-gray-200">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="mt-3 flex gap-2">
          <div className="flex-1 relative">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
              placeholder={`Ask ${PERSONA_CONFIG[persona].label.toLowerCase()}… (Enter to send)`}
              disabled={streaming}
              className="w-full border border-gray-300 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none pr-12 disabled:opacity-50 disabled:bg-gray-50"
            />
            {streaming && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-blue-500 animate-spin text-lg">⟳</span>
            )}
          </div>
          <button
            onClick={sendMessage}
            disabled={streaming || !input.trim()}
            className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-3 rounded-xl font-medium text-sm disabled:opacity-40 transition-colors"
          >
            Send
          </button>
        </div>

        {/* Suggestions */}
        <div className="mt-2 flex flex-wrap gap-2">
          {[
            "What's the current approval rate?",
            "Show me model performance metrics",
            "Any data drift detected?",
            "Is fair lending compliant?",
          ].map((s) => (
            <button
              key={s}
              onClick={() => { setInput(s); }}
              className="text-xs bg-white border border-gray-200 hover:border-blue-300 text-gray-600 px-3 py-1.5 rounded-full transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Report slide-over */}
      {showReport && (
        <div className="fixed inset-0 bg-black/40 z-50 flex justify-end">
          <div className="w-full max-w-lg bg-white h-full shadow-2xl flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h3 className="font-bold text-gray-900">Generate Report</h3>
              <button onClick={() => setShowReport(false)} className="text-gray-400 hover:text-gray-700">✕</button>
            </div>
            <div className="p-6 flex-1">
              <p className="text-sm text-gray-600 mb-4">Select a report type to generate automatically.</p>
              <div className="space-y-3">
                {["portfolio", "model_health", "fair_lending", "drift"].map((rt) => (
                  <button
                    key={rt}
                    onClick={() => {
                      setShowReport(false);
                      setInput(`Generate a ${rt.replace("_", " ")} report and summarize key findings.`);
                    }}
                    className="w-full text-left border border-gray-200 hover:border-blue-300 rounded-lg p-3 text-sm text-gray-700 capitalize transition-colors"
                  >
                    <span className="font-semibold">{rt.replace("_", " ")} Report</span>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {{ portfolio: "Portfolio health, volumes, and trends", model_health: "AUC, KS, F1 metrics and SLOs", fair_lending: "DIR score and ECOA compliance", drift: "PSI per feature and retraining recommendations" }[rt]}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </DashboardShell>
  );
}
