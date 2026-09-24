"use client";

import React, { useState, useEffect } from "react";

export interface ToastMessage {
  id: string;
  type: "success" | "error" | "info";
  message: string;
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastMessage[]>([
    { id: "1", type: "success", message: "Profile settings saved successfully." },
    { id: "2", type: "info", message: "Auto-pay enabled for the 1st of next month." },
  ]);

  // Auto dismiss toasts after 4000ms
  useEffect(() => {
    if (toasts.length === 0) return;

    const timer = setTimeout(() => {
      setToasts((prev) => prev.slice(1));
    }, 4000);

    return () => clearTimeout(timer);
  }, [toasts]);

  // Cap mobile toasts to max 2 items to prevent viewport occlusion
  const visibleToasts = toasts.slice(-2);

  return (
    <div className="fixed bottom-20 sm:bottom-6 inset-x-0 sm:inset-x-auto sm:right-6 z-50 flex flex-col items-center sm:items-end gap-2 px-4 pointer-events-none">
      {visibleToasts.map((toast) => (
        <div
          key={toast.id}
          className={`pointer-events-auto w-full max-w-sm p-4 rounded-xl shadow-lg border flex items-center justify-between transition-all transform translate-y-0 animate-fade-in ${
            toast.type === "success"
              ? "bg-white border-green-200 text-green-900"
              : toast.type === "error"
              ? "bg-white border-red-200 text-red-900"
              : "bg-white border-blue-200 text-blue-900"
          }`}
        >
          <div className="flex items-center gap-3">
            <span className="text-lg">
              {toast.type === "success" ? "✓" : toast.type === "error" ? "⚠️" : "ℹ️"}
            </span>
            <p className="text-sm font-medium">{toast.message}</p>
          </div>
          <button
            onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
            className="text-gray-400 hover:text-gray-600 text-xs font-bold p-1 ml-2"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
