"use client";

import React, { useState } from "react";

export interface DocumentViewerProps {
  documentTitle?: string;
  documentType?: string;
  downloadUrl?: string;
}

export function DocumentViewer({
  documentTitle = "Residential Lease Agreement (2026-2027)",
  documentType = "Lease Agreement",
  downloadUrl = "/api/documents/lease/download",
}: DocumentViewerProps) {
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const handleDownload = async () => {
    setIsDownloading(true);
    setDownloadError(null);

    try {
      const response = await fetch(downloadUrl);

      if (!response.ok) {
        throw new Error(`Failed to download file (Status ${response.status})`);
      }

      // Convert response to Blob
      const blob = await response.blob();

      if (blob.size === 0) {
        throw new Error("Downloaded document is empty (0 bytes).");
      }

      // Create object URL and trigger browser download
      const blobUrl = window.URL.createObjectURL(blob);
      const tempLink = document.createElement("a");
      tempLink.href = blobUrl;
      tempLink.setAttribute("download", "Signed_Lease_Agreement.pdf");
      document.body.appendChild(tempLink);
      tempLink.click();

      // Cleanup DOM and revoke Object URL
      document.body.removeChild(tempLink);
      window.URL.revokeObjectURL(blobUrl);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Download failed. Please try again.";
      setDownloadError(message);
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 max-w-2xl w-full">
      <div className="flex items-start justify-between border-b border-gray-100 pb-4 mb-4">
        <div>
          <span className="inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 mb-2">
            {documentType}
          </span>
          <h3 className="text-lg font-bold text-gray-900">{documentTitle}</h3>
          <p className="text-sm text-gray-500 mt-1">Status: Fully Executed & Signed</p>
        </div>
        <button
          onClick={handleDownload}
          disabled={isDownloading}
          className={`px-4 py-2.5 rounded-lg text-sm font-semibold text-white transition-all flex items-center gap-2 ${
            isDownloading
              ? "bg-gray-400 cursor-not-allowed"
              : "bg-blue-600 hover:bg-blue-700 active:scale-[0.98] shadow-sm"
          }`}
        >
          {isDownloading ? (
            <>
              <svg className="animate-spin h-4 w-4 text-white" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <span>Downloading...</span>
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              <span>Download Signed Copy</span>
            </>
          )}
        </button>
      </div>

      {downloadError && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 mb-4">
          {downloadError}
        </div>
      )}

      {/* PDF Document Preview Mock */}
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 min-h-[300px] flex flex-col items-center justify-center text-center">
        <svg className="w-16 h-16 text-gray-400 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <p className="text-sm font-medium text-gray-700">Residential Lease Agreement (PDF)</p>
        <p className="text-xs text-gray-400 mt-1">Click "Download Signed Copy" above to download the verified PDF document.</p>
      </div>
    </div>
  );
}
