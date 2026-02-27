"use client";

import { PendingEmail } from "@/lib/imapClient";

interface EmailDetailProps {
  email: PendingEmail;
  onClose: () => void;
}

export default function EmailDetail({ email, onClose }: EmailDetailProps) {
  return (
    <div
      className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50 p-4 z-50"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl rounded-lg bg-white shadow-xl max-h-96 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 border-b border-gray-200 bg-gray-50 px-6 py-4 flex items-start justify-between">
          <div className="flex-1">
            <h2 className="text-xl font-bold text-gray-900">{email.subject}</h2>
            <p className="mt-1 text-sm text-gray-600">From: {email.from}</p>
            <p className="mt-1 text-xs text-gray-500">
              {new Date(email.date).toLocaleDateString()} at{" "}
              {new Date(email.date).toLocaleTimeString()}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Title */}
          {email.title && (
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-2">Title</h3>
              <p className="text-gray-700 bg-gray-50 rounded-lg p-3">{email.title}</p>
            </div>
          )}

          {/* Idea */}
          {email.idea && (
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-2">Idea</h3>
              <p className="text-gray-700 bg-gray-50 rounded-lg p-3 whitespace-pre-wrap">
                {email.idea}
              </p>
            </div>
          )}

          {/* Environment Variables */}
          {email.envs && Object.keys(email.envs).length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-2">
                Environment Variables
              </h3>
              <div className="bg-gray-50 rounded-lg p-3 space-y-2">
                {Object.entries(email.envs).map(([key, value]) => (
                  <div key={key} className="border-b border-gray-200 pb-2 last:pb-0 last:border-0">
                    <p className="font-semibold text-gray-800">{key}</p>
                    <p className="text-sm text-gray-600">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Directives */}
          {email.directives && email.directives.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-900 mb-2">
                Directives
              </h3>
              <ul className="bg-gray-50 rounded-lg p-3 space-y-2">
                {email.directives.map((directive, idx) => (
                  <li key={idx} className="flex gap-2 text-gray-700">
                    <span className="text-blue-600 flex-shrink-0">•</span>
                    <span>{directive}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!email.title && !email.idea && !email.envs && !email.directives && (
            <p className="text-gray-500 italic">No detailed information available</p>
          )}
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 border-t border-gray-200 bg-gray-50 px-6 py-4">
          <button
            onClick={onClose}
            className="rounded-lg bg-gray-200 px-4 py-2 font-semibold text-gray-800 hover:bg-gray-300"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
