import { fetchPendingEmails } from "@/lib/imapClient";
import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  try {
    const emails = await fetchPendingEmails();
    return NextResponse.json({ emails });
  } catch (error) {
    let errorMsg = error instanceof Error ? error.message : "Unknown error";
    console.error("Error fetching emails:", errorMsg);

    // Handle specific IMAP errors with user-friendly messages
    if (errorMsg.includes("Invalid BODY")) {
      errorMsg = "No pending emails with JARVIS format found in your inbox.";
    } else if (errorMsg.includes("IMAP_PASSWORD")) {
      errorMsg = "IMAP password not configured. Please set IMAP_PASSWORD in environment variables.";
    } else if (errorMsg.includes("authenticate") || errorMsg.includes("authentication")) {
      errorMsg = "Failed to authenticate with IMAP server. Please check your credentials.";
    }

    return NextResponse.json(
      { error: errorMsg },
      { status: 500 }
    );
  }
}
