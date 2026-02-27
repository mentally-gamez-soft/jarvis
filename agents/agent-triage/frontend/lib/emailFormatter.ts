/**
 * Email formatting utility for generating email body in the format
 * expected by the agent-triage backend.
 */

export interface EmailFormData {
  projectName: string;
  title: string;
  idea: string;
  directives?: string[];
  envs?: Record<string, string>;
}

/**
 * Formats email data into the standard email body format.
 * Follows the format defined in rules/email-format.md
 */
export function formatEmailBody(data: EmailFormData): string {
  let body = "";

  // Add title section (mandatory)
  body += "[title]\n";
  body += data.title.trim() + "\n\n";

  // Add idea section (mandatory)
  body += "[idea]\n";
  body += data.idea.trim() + "\n\n";

  // Add environment variables section (optional)
  if (data.envs && Object.keys(data.envs).length > 0) {
    body += "[envs]\n";
    Object.entries(data.envs).forEach(([key, value]) => {
      body += `${key}: ${value}\n`;
    });
    body += "\n";
  }

  // Add directives section (optional)
  if (data.directives && data.directives.length > 0) {
    body += "[directives]\n";
    data.directives.forEach((directive) => {
      body += `- ${directive.trim()}\n`;
    });
  }

  return body.trim();
}

/**
 * Generates the complete email subject line.
 */
export function formatEmailSubject(projectName: string): string {
  return `${process.env.NEXT_PUBLIC_EMAIL_SUBJECT_PREFIX}[${projectName.trim()}]`;
}

/**
 * Generates the complete formatted email (subject + body).
 */
export function generateCompleteEmail(data: EmailFormData): string {
  const subject = formatEmailSubject(data.projectName);
  const body = formatEmailBody(data);

  return `Subject: ${subject}\n\n${body}`;
}

/**
 * Downloads the email as a .txt file.
 */
export function downloadEmail(
  data: EmailFormData,
  filename: string = "email-requirement.txt"
): void {
  const emailContent = generateCompleteEmail(data);
  const element = document.createElement("a");
  element.setAttribute(
    "href",
    "data:text/plain;charset=utf-8," + encodeURIComponent(emailContent)
  );
  element.setAttribute("download", filename);
  element.style.display = "none";
  document.body.appendChild(element);
  element.click();
  document.body.removeChild(element);
}
