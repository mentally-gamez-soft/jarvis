"use client";

import { useState, useEffect } from "react";
import { PendingEmail } from "@/lib/imapClient";
import EmailDetail from "./EmailDetail";

interface PendingEmailsProps {
  onFetchError?: (error: string) => void;
}

export default function PendingEmails({ onFetchError }: PendingEmailsProps) {
  const [emails, setEmails] = useState<PendingEmail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEmail, setSelectedEmail] = useState<PendingEmail | null>(null);

  useEffect(() => {
    fetchEmails();
  }, []);

  const fetchEmails = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/emails");
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Failed to fetch emails");
      }
      const data = await response.json();
      setEmails(data.emails || []);
    } catch (err) {
      const errorMsg =
        err instanceof Error ? err.message : "Unknown error occurred";
      setError(errorMsg);
      onFetchError?.(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">Pending Emails</h2>
        <div className="flex items-center justify-center py-12">
          <div className="text-center">
            <div className="mb-4 inline-block">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-300 border-t-blue-600"></div>
            </div>
            <p className="text-gray-600">Loading pending emails...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full">
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-gray-900">Pending Emails</h2>
          <button
            onClick={fetchEmails}
            className="rounded-lg bg-blue-100 px-4 py-2 text-blue-700 hover:bg-blue-200"
          >
            Refresh
          </button>
        </div>

        {error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
            <p className="font-semibold">Error fetching emails</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {emails.length === 0 && !error ? (
          <div className="py-12 text-center">
            <p className="text-gray-500">No pending emails found</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {emails.map((email) => (
              <button
                key={email.uid}
                onClick={() => setSelectedEmail(email)}
                className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-left hover:border-blue-400 hover:bg-blue-50 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <p className="font-semibold text-gray-900">{email.subject}</p>
                    <p className="mt-1 text-sm text-gray-600">From: {email.from}</p>
                    <p className="mt-1 text-xs text-gray-500">
                      {new Date(email.date).toLocaleDateString()} at{" "}
                      {new Date(email.date).toLocaleTimeString()}
                    </p>
                  </div>
                  <div className="ml-4">
                    <svg
                      className="h-5 w-5 text-gray-400"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 5l7 7-7 7"
                      />
                    </svg>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Email Detail Modal */}
      {selectedEmail && (
        <EmailDetail
          email={selectedEmail}
          onClose={() => setSelectedEmail(null)}
        />
      )}
    </div>
  );
}
