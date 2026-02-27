"use client";

import { useState } from "react";
import EmailForm from "@/components/EmailForm";
import PendingEmails from "@/components/PendingEmails";
import PasswordGate from "@/components/PasswordGate";

export default function Home() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  return (
    <main className="min-h-screen bg-gray-100">
      <div className="mx-auto max-w-6xl px-4 py-8">
        {/* Header */}
        <div className="mb-12">
          <h1 className="text-4xl font-bold text-gray-900">Agent Triage Frontend</h1>
          <p className="mt-2 text-lg text-gray-600">
            Create new email requirements and view pending emails for triage
          </p>
        </div>

        {/* Two-column layout */}
        <div className="grid gap-8 lg:grid-cols-2">
          {/* Email Form - Always visible */}
          <div>
            <EmailForm />
          </div>

          {/* Pending Emails - Protected by password */}
          <div>
            {!isAuthenticated ? (
              <PasswordGate onAuthenticated={() => setIsAuthenticated(true)} />
            ) : (
              <PendingEmails />
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
