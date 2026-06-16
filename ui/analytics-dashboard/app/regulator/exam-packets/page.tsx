"use client";

import { useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExamPacket {
  packet_id: string;
  tenant_id: string;
  template: string;
  from_date: string;
  to_date: string;
  generated_at: string;
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_URL = process.env.NEXT_PUBLIC_DECISION_API_URL ?? "http://localhost:8000";

function getToken() {
  return typeof window !== "undefined" ? (localStorage.getItem("decision_api_token") ?? "") : "";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function RegulatorExamPacketsPage() {
  const [packets, setPackets] = useState<ExamPacket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/v1/audit/packets`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then((data) => setPackets(data.packets ?? []))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, []);

  const downloadPacket = async (packet: ExamPacket) => {
    setDownloading(packet.packet_id);
    try {
      const res = await fetch(`${API_URL}/v1/audit/generate-package`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({
          from_date: packet.from_date,
          to_date: packet.to_date,
          format: "pdf_zip",
          template: packet.template,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `exam_packet_${packet.packet_id.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`Download failed: ${err}`);
    } finally {
      setDownloading(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm animate-pulse">
        Loading exam packets…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load exam packets: {error}
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Exam Packets</h1>
        <p className="text-sm text-gray-500 mt-1">
          Download generated regulatory exam packages. Read-only access.
        </p>
      </div>

      {packets.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 p-8 text-center">
          <p className="text-gray-400 text-sm">No exam packets have been generated yet.</p>
          <p className="text-xs text-gray-300 mt-1">
            Ask a compliance user to generate a package from the compliance portal.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {packets.map((p) => (
            <div
              key={p.packet_id}
              className="bg-white rounded-xl border border-gray-100 shadow-sm p-5"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-200 rounded-full px-2.5 py-0.5">
                      {p.template}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-gray-900">
                    Period: {p.from_date} → {p.to_date}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">
                    Generated: {new Date(p.generated_at).toLocaleString()}
                    {" · "}
                    ID: <span className="font-mono">{p.packet_id.slice(0, 8)}…</span>
                  </p>
                </div>

                <button
                  onClick={() => downloadPacket(p)}
                  disabled={downloading === p.packet_id}
                  className="flex-shrink-0 rounded-lg border border-gray-200 bg-white px-4 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
                >
                  {downloading === p.packet_id ? "Downloading…" : "⬇ Download PDF"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
