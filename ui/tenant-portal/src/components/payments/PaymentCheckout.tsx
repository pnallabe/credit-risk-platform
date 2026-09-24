"use client";

import React, { useState, useEffect } from "react";
import { validateABARouting } from "@/lib/validation/ach";

export interface PaymentCheckoutProps {
  amount: number;
  onSuccess?: (transactionId: string) => void;
  onClose?: () => void;
}

export function PaymentCheckout({ amount, onSuccess, onClose }: PaymentCheckoutProps) {
  const [paymentMethod, setPaymentMethod] = useState<"card" | "ach">("card");
  const [cardNumber, setCardNumber] = useState("");
  const [expiry, setExpiry] = useState("");
  const [cvv, setCvv] = useState("");

  const [accountNumber, setAccountNumber] = useState("");
  const [routingNumber, setRoutingNumber] = useState("");
  const [routingError, setRoutingError] = useState<string | null>(null);

  const [idempotencyKey, setIdempotencyKey] = useState<string>("");
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successTxId, setSuccessTxId] = useState<string | null>(null);

  // Initialize UUID v4 idempotency key on component mount
  useEffect(() => {
    setIdempotencyKey(crypto.randomUUID());
  }, []);

  const handleRoutingBlur = () => {
    if (paymentMethod === "ach" && routingNumber) {
      if (!validateABARouting(routingNumber)) {
        setRoutingError("Please enter a valid 9-digit routing number.");
      } else {
        setRoutingError(null);
      }
    }
  };

  const handlePaymentSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isProcessing) return; // Client-side lock guard

    setErrorMsg(null);

    if (paymentMethod === "ach") {
      if (!validateABARouting(routingNumber)) {
        setRoutingError("Please enter a valid 9-digit routing number.");
        return;
      }
    }

    setIsProcessing(true);

    try {
      const response = await fetch("/api/payments/charge", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify({
          amount,
          paymentMethod,
          details: paymentMethod === "card"
            ? { cardNumber: cardNumber.replace(/\s/g, ""), expiry, cvv }
            : { accountNumber, routingNumber },
        }),
      });

      if (response.status === 409) {
        throw new Error("This transaction is already being processed. Please wait.");
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || "Payment processing failed. Please try again.");
      }

      const data = await response.json();
      setSuccessTxId(data.transactionId || `TX-${Date.now()}`);
      if (onSuccess) onSuccess(data.transactionId);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "An unexpected error occurred.";
      setErrorMsg(message);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-lg border border-gray-100 p-6 max-w-md w-full mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-bold text-gray-900">Rent Payment Checkout</h2>
        {onClose && (
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg font-bold p-1"
            aria-label="Close modal"
          >
            ✕
          </button>
        )}
      </div>

      {successTxId ? (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
          <div className="w-12 h-12 bg-green-100 text-green-600 rounded-full flex items-center justify-center mx-auto mb-3 text-xl font-bold">
            ✓
          </div>
          <h3 className="text-lg font-semibold text-green-900">Payment Successful</h3>
          <p className="text-sm text-green-700 mt-1">
            Amount paid: <span className="font-bold">${amount.toFixed(2)}</span>
          </p>
          <p className="text-xs text-green-600 mt-2 font-mono">
            Transaction ID: {successTxId}
          </p>
        </div>
      ) : (
        <form onSubmit={handlePaymentSubmit} className="space-y-4">
          <div className="bg-gray-50 p-4 rounded-lg flex justify-between items-center">
            <span className="text-sm font-medium text-gray-600">Total Due</span>
            <span className="text-2xl font-bold text-gray-900">${amount.toFixed(2)}</span>
          </div>

          {/* Payment Method Selector */}
          <div className="grid grid-cols-2 gap-2 p-1 bg-gray-100 rounded-lg">
            <button
              type="button"
              className={`py-2 text-sm font-medium rounded-md transition-all ${
                paymentMethod === "card" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-900"
              }`}
              onClick={() => { setPaymentMethod("card"); setErrorMsg(null); }}
            >
              Credit / Debit Card
            </button>
            <button
              type="button"
              className={`py-2 text-sm font-medium rounded-md transition-all ${
                paymentMethod === "ach" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-900"
              }`}
              onClick={() => { setPaymentMethod("ach"); setErrorMsg(null); }}
            >
              Bank Account (ACH)
            </button>
          </div>

          {errorMsg && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {errorMsg}
            </div>
          )}

          {paymentMethod === "card" ? (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-gray-700 uppercase mb-1">Card Number</label>
                <input
                  type="text"
                  placeholder="4532 •••• •••• 8921"
                  required
                  value={cardNumber}
                  onChange={(e) => setCardNumber(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 uppercase mb-1">Expiry Date</label>
                  <input
                    type="text"
                    placeholder="MM/YY"
                    required
                    value={expiry}
                    onChange={(e) => setExpiry(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 uppercase mb-1">CVC / CVV</label>
                  <input
                    type="password"
                    maxLength={4}
                    placeholder="•••"
                    required
                    value={cvv}
                    onChange={(e) => setCvv(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-gray-700 uppercase mb-1">Routing Number (9 digits)</label>
                <input
                  type="text"
                  maxLength={9}
                  placeholder="021000021"
                  required
                  value={routingNumber}
                  onChange={(e) => {
                    setRoutingNumber(e.target.value);
                    if (routingError) setRoutingError(null);
                  }}
                  onBlur={handleRoutingBlur}
                  className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 ${
                    routingError ? "border-red-500 focus:ring-red-500" : "border-gray-300 focus:ring-blue-500"
                  }`}
                />
                {routingError && (
                  <p className="text-xs text-red-600 mt-1">{routingError}</p>
                )}
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-700 uppercase mb-1">Account Number</label>
                <input
                  type="text"
                  placeholder="1234567890"
                  required
                  value={accountNumber}
                  onChange={(e) => setAccountNumber(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          )}

          <button
            type="submit"
            disabled={isProcessing}
            className={`w-full py-3.5 px-4 rounded-lg font-semibold text-white transition-all flex items-center justify-center gap-2 ${
              isProcessing
                ? "bg-gray-400 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-700 active:scale-[0.99] shadow-md"
            }`}
          >
            {isProcessing ? (
              <>
                <svg className="animate-spin h-5 w-5 text-white" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                <span>Processing Payment...</span>
              </>
            ) : (
              <span>Confirm & Pay ${amount.toFixed(2)}</span>
            )}
          </button>
        </form>
      )}
    </div>
  );
}
