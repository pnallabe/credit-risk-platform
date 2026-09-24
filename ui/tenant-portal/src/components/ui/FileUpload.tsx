"use client";

import React, { useState, useRef } from "react";

export interface FileValidationRules {
  maxSizeBytes?: number; // Default 10MB
  allowedMimeTypes?: string[];
  allowedExtensions?: string[];
}

export interface FileUploadProps {
  onFileSelect?: (file: File) => void;
  rules?: FileValidationRules;
  label?: string;
  acceptText?: string;
}

const DEFAULT_RULES: FileValidationRules = {
  maxSizeBytes: 10 * 1024 * 1024, // 10 MB
  allowedMimeTypes: ["application/pdf", "image/png", "image/jpeg"],
  allowedExtensions: [".pdf", ".png", ".jpg", ".jpeg"],
};

export function FileUpload({
  onFileSelect,
  rules = DEFAULT_RULES,
  label = "Upload Document",
  acceptText = "PDF, PNG, or JPEG (Max 10MB)",
}: FileUploadProps) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const maxBytes = rules.maxSizeBytes ?? DEFAULT_RULES.maxSizeBytes!;
  const allowedExts = rules.allowedExtensions ?? DEFAULT_RULES.allowedExtensions!;

  const validateFile = (file: File): boolean => {
    setErrorMessage(null);

    // 1. Check file size
    if (file.size > maxBytes) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
      const limitMB = (maxBytes / (1024 * 1024)).toFixed(0);
      setErrorMessage(`File size exceeds the ${limitMB}MB limit (Uploaded file size: ${sizeMB}MB).`);
      return false;
    }

    // 2. Check file extension / mime type
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    const isValidExt = allowedExts.includes(ext);
    const isValidMime = rules.allowedMimeTypes
      ? rules.allowedMimeTypes.includes(file.type)
      : true;

    if (!isValidExt || !isValidMime) {
      setErrorMessage(
        `File type "${ext}" is not supported. Please upload ${allowedExts.join(", ")} files.`
      );
      return false;
    }

    return true;
  };

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const file = files[0];

    if (validateFile(file)) {
      setSelectedFile(file);
      if (onFileSelect) onFileSelect(file);
    } else {
      setSelectedFile(null);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFiles(e.target.files);
    }
  };

  const handleRemove = () => {
    setSelectedFile(null);
    setErrorMessage(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className="w-full max-w-lg">
      <label className="block text-sm font-semibold text-gray-700 mb-2">{label}</label>

      {errorMessage && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center justify-between text-sm text-red-700">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-red-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>{errorMessage}</span>
          </div>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="text-red-500 hover:text-red-700 text-xs font-bold"
          >
            ✕
          </button>
        </div>
      )}

      {!selectedFile ? (
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
            dragActive
              ? "border-blue-500 bg-blue-50"
              : "border-gray-300 hover:border-gray-400 bg-gray-50/50"
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            accept={allowedExts.join(",")}
            onChange={handleChange}
          />

          <div className="w-12 h-12 bg-blue-50 text-blue-600 rounded-full flex items-center justify-center mx-auto mb-3">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
          </div>

          <p className="text-sm font-semibold text-gray-800">
            Click to upload or drag & drop file
          </p>
          <p className="text-xs text-gray-500 mt-1">{acceptText}</p>
        </div>
      ) : (
        <div className="p-4 bg-blue-50/50 border border-blue-200 rounded-xl flex items-center justify-between">
          <div className="flex items-center gap-3 overflow-hidden">
            <div className="w-10 h-10 bg-blue-100 text-blue-700 rounded-lg flex items-center justify-center shrink-0">
              📄
            </div>
            <div className="truncate">
              <p className="text-sm font-semibold text-gray-900 truncate">{selectedFile.name}</p>
              <p className="text-xs text-gray-500">{(selectedFile.size / (1024 * 1024)).toFixed(2)} MB</p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleRemove}
            className="p-1.5 text-gray-400 hover:text-red-600 rounded-lg hover:bg-gray-100 transition-colors"
            title="Remove file"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
