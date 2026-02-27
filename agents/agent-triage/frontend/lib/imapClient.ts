/**
 * IMAP client for fetching pending emails.
 * This is a server-side utility that connects to the IMAP server.
 */

import Imap from "imap";
import { simpleParser } from "mailparser";

export interface PendingEmail {
  uid: string;
  subject: string;
  from: string;
  date: Date;
  title?: string;
  idea?: string;
  directives?: string[];
  envs?: Record<string, string>;
}

/**
 * Body tag pattern: [tag]content[/tag]
 * Extracts content between tags like [title], [idea], [envs], [directives]
 */
function parseBodyTags(
  body: string
): Record<string, string> {
  const tags: Record<string, string> = {};
  const tagPattern = /\[(title|idea|envs|directives)\]([\s\S]*?)(?=\[|$)/gi;

  let match;
  while ((match = tagPattern.exec(body)) !== null) {
    const tagName = match[1].toLowerCase();
    const tagContent = match[2].trim();
    tags[tagName] = tagContent;
  }

  return tags;
}

/**
 * Parses directives from text (one per line, prefixed with -)
 */
function parseDirectives(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.replace(/^[\s-]+/, "").trim())
    .filter((line) => line.length > 0);
}

/**
 * Parses environment variables from text (format: KEY: value)
 */
function parseEnvs(text: string): Record<string, string> {
  const envs: Record<string, string> = {};
  text.split("\n").forEach((line) => {
    const [key, ...valueParts] = line.split(":");
    if (key && valueParts.length > 0) {
      envs[key.trim()] = valueParts.join(":").trim();
    }
  });
  return envs;
}

/**
 * Connects to IMAP server and fetches all JARVIS emails.
 * Note: IMAP_PASSWORD must be set in environment variables.
 */
export async function fetchPendingEmails(): Promise<PendingEmail[]> {
  return new Promise((resolve, reject) => {
    const password = process.env.IMAP_PASSWORD;
    if (!password) {
      reject(new Error("IMAP_PASSWORD environment variable is not set"));
      return;
    }

    console.log("Connecting to IMAP server...", {
      host: process.env.NEXT_PUBLIC_IMAP_HOST,
      port: process.env.NEXT_PUBLIC_IMAP_PORT,
      user: process.env.NEXT_PUBLIC_IMAP_USERNAME,
    });

    const imap = new Imap({
      user: process.env.NEXT_PUBLIC_IMAP_USERNAME!,
      password,
      host: process.env.NEXT_PUBLIC_IMAP_HOST!,
      port: parseInt(process.env.NEXT_PUBLIC_IMAP_PORT || "993"),
      tls: process.env.NEXT_PUBLIC_IMAP_USE_SSL === "true",
      tlsOptions: { rejectUnauthorized: false },
      authTimeout: 10000,
    });

    const emails: PendingEmail[] = [];
    let emailsProcessed = 0;
    let totalEmails = 0;
    let processingComplete = false;

    function parseEmail(msg: any, seqno: number): Promise<PendingEmail | null> {
      return new Promise((resolveEmail) => {
        let emailContent = "";

        msg.on("body", (stream: any) => {
          stream.on("data", (chunk: Buffer) => {
            emailContent += chunk.toString();
          });

          stream.once("end", async () => {
            try {
              const parsed = await simpleParser(emailContent);
              const subject = parsed.subject || "";
              const from = parsed.from?.text || "";
              const date = parsed.date || new Date();
              const textBody = parsed.text || "";

              // Filter emails by JARVIS prefix
              const prefix =
                process.env.NEXT_PUBLIC_EMAIL_SUBJECT_PREFIX || "[JARVIS]-";
              if (!subject.includes(prefix)) {
                resolveEmail(null);
                return;
              }

              const tags = parseBodyTags(textBody);
              const email: PendingEmail = {
                uid: seqno.toString(),
                subject,
                from,
                date,
                title: tags.title,
                idea: tags.idea,
                directives: tags.directives
                  ? parseDirectives(tags.directives)
                  : undefined,
                envs: tags.envs ? parseEnvs(tags.envs) : undefined,
              };

              resolveEmail(email);
            } catch (err) {
              console.error("Error parsing email:", err);
              resolveEmail(null);
            }
          });
        });

        msg.once("attributes", () => {
          // Email attributes available
        });
      });
    }

    function openInboxAndSearch() {
      imap.openBox(
        process.env.NEXT_PUBLIC_IMAP_MAILBOX || "INBOX",
        false,
        (err) => {
          if (err) {
            imap.end();
            reject(err);
            return;
          }

          imap.search(["ALL"], async (err, results) => {
            if (err) {
              imap.end();
              reject(err);
              return;
            }

            if (!results || results.length === 0) {
              imap.end();
              resolve([]);
              return;
            }

            totalEmails = results.length;
            const f = imap.fetch(results, { bodies: "HEADER,TEXT" });

            f.on("message", (msg: any, seqno: number) => {
              parseEmail(msg, seqno).then((email) => {
                emailsProcessed++;
                if (email) {
                  emails.push(email);
                }

                if (emailsProcessed === totalEmails && !processingComplete) {
                  processingComplete = true;
                  imap.end();
                  resolve(emails);
                }
              });
            });

            f.on("error", (err: Error) => {
              imap.end();
              reject(err);
            });
          });
        }
      );
    }

    imap.on("ready", openInboxAndSearch);

    imap.on("error", (err: Error) => {
      console.error("IMAP connection error:", err);
      reject(err);
    });

    imap.on("end", () => {
      console.log("IMAP connection closed");
    });

    imap.connect();
  });
}
