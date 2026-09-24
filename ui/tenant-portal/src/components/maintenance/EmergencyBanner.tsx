"use client";

import React from "react";

export function EmergencyBanner() {
  return (
    <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 bg-red-100 text-red-600 rounded-lg flex items-center justify-center shrink-0 font-bold">
          🚨
        </div>
        <div>
          <h4 className="text-sm font-bold text-red-900">Life-Safety or Active Emergency?</h4>
          <p className="text-xs text-red-700 mt-1 leading-relaxed">
            For active water leaks, fire, gas smells, or structural damage, do not rely on app ticketing. Please contact emergency services (911) or call our 24/7 maintenance hotline directly at:
          </p>
          <div className="mt-2 flex items-center gap-4">
            <a
              href="tel:18005550199"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-bold transition-colors shadow-sm"
            >
              📞 Call Hotline: 1-800-555-0199
            </a>
            <span className="text-xs text-red-600 font-medium">Available 24/7/365</span>
          </div>
        </div>
      </div>
    </div>
  );
}
