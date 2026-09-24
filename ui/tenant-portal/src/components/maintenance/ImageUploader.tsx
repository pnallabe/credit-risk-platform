"use client";

import React, { useState } from "react";

export interface AttachedImage {
  id: string;
  url: string;
  name: string;
}

export function ImageUploader() {
  const [images, setImages] = useState<AttachedImage[]>([
    { id: "img-1", name: "water_leak_1.jpg", url: "https://images.unsplash.com/photo-1585704032915-c3400ca199e7?w=300" },
    { id: "img-2", name: "sink_damage.jpg", url: "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=300" },
  ]);

  const handleRemoveImage = (id: string, e: React.MouseEvent | React.TouchEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setImages((prev) => prev.filter((img) => img.id !== id));
  };

  return (
    <div className="space-y-3">
      <label className="block text-sm font-semibold text-gray-700">Attach Photos of Issue</label>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {images.map((img) => (
          <div
            key={img.id}
            className="relative group rounded-xl overflow-hidden border border-gray-200 aspect-square bg-gray-100"
          >
            {/* Thumbnail Image */}
            <img
              src={img.url}
              alt={img.name}
              className="w-full h-full object-cover"
            />

            {/* Top-Right Remove Button with enlarged 44x44px touch target */}
            <div className="absolute top-1 right-1 z-20">
              <button
                type="button"
                onClick={(e) => handleRemoveImage(img.id, e)}
                onTouchEnd={(e) => handleRemoveImage(img.id, e)}
                className="w-11 h-11 min-w-[44px] min-h-[44px] flex items-center justify-center bg-black/60 hover:bg-red-600 text-white rounded-full transition-colors pointer-events-auto shadow-md"
                aria-label={`Remove photo ${img.name}`}
                title="Remove photo"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="absolute bottom-0 inset-x-0 bg-black/50 text-white text-[10px] p-1 truncate">
              {img.name}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
