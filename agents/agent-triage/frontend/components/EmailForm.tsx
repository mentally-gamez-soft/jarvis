"use client";

import { useState } from "react";
import { EmailFormData, downloadEmail } from "@/lib/emailFormatter";

interface EnvVar {
  key: string;
  value: string;
}

export default function EmailForm() {
  const [projectName, setProjectName] = useState("");
  const [title, setTitle] = useState("");
  const [idea, setIdea] = useState("");
  const [directiveText, setDirectiveText] = useState("");
  const [envVars, setEnvVars] = useState<EnvVar[]>([{ key: "", value: "" }]);
  const [preview, setPreview] = useState<string>("");
  const [showPreview, setShowPreview] = useState(false);

  const addEnvVar = () => {
    setEnvVars([...envVars, { key: "", value: "" }]);
  };

  const removeEnvVar = (index: number) => {
    setEnvVars(envVars.filter((_, i) => i !== index));
  };

  const updateEnvVar = (
    index: number,
    field: "key" | "value",
    value: string
  ) => {
    const newVars = [...envVars];
    newVars[index][field] = value;
    setEnvVars(newVars);
  };

  const parseDirectives = (): string[] => {
    return directiveText
      .split("\n")
      .map((d) => d.trim())
      .filter((d) => d.length > 0);
  };

  const parseEnvs = (): Record<string, string> => {
    const result: Record<string, string> = {};
    envVars.forEach(({ key, value }) => {
      if (key.trim()) {
        result[key.trim()] = value.trim();
      }
    });
    return result;
  };

  const handlePreview = () => {
    const formData: EmailFormData = {
      projectName,
      title,
      idea,
      directives: parseDirectives(),
      envs: Object.keys(parseEnvs()).length > 0 ? parseEnvs() : undefined,
    };

    // Generate preview (same as download would show)
    const emailContent = `Subject: [JARVIS]-[${projectName.trim()}]\n\n`;
    const body = `[title]\n${title.trim()}\n\n[idea]\n${idea.trim()}`;

    const directives = parseDirectives();
    const envs = parseEnvs();

    let fullBody = body;
    if (Object.keys(envs).length > 0) {
      fullBody += "\n\n[envs]\n";
      Object.entries(envs).forEach(([k, v]) => {
        fullBody += `${k}: ${v}\n`;
      });
    }

    if (directives.length > 0) {
      fullBody += "\n[directives]\n";
      directives.forEach((d) => {
        fullBody += `- ${d}\n`;
      });
    }

    setPreview(emailContent + fullBody);
    setShowPreview(true);
  };

  const handleDownload = () => {
    if (!projectName || !title || !idea) {
      alert("Please fill in Project Name, Title, and Idea fields");
      return;
    }

    const formData: EmailFormData = {
      projectName,
      title,
      idea,
      directives: parseDirectives(),
      envs: Object.keys(parseEnvs()).length > 0 ? parseEnvs() : undefined,
    };

    const filename = `${projectName.toLowerCase().replace(/\s+/g, "-")}-requirement.txt`;
    downloadEmail(formData, filename);
  };

  const isFormValid = projectName.trim() && title.trim() && idea.trim();

  return (
    <div className="w-full">
      <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-6 text-2xl font-bold text-gray-900">
          Create New Email Requirement
        </h2>

        {/* Project Name */}
        <div className="mb-6">
          <label htmlFor="projectName" className="block mb-2 font-semibold text-gray-700">
            Project Name <span className="text-red-600">*</span>
          </label>
          <input
            id="projectName"
            type="text"
            placeholder="e.g., Project Phoenix"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <p className="mt-1 text-sm text-gray-500">
            Will be used in the email subject as [JARVIS]-[Project Name]
          </p>
        </div>

        {/* Title */}
        <div className="mb-6">
          <label htmlFor="title" className="block mb-2 font-semibold text-gray-700">
            Title <span className="text-red-600">*</span>
          </label>
          <input
            id="title"
            type="text"
            placeholder="e.g., Project Phoenix"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <p className="mt-1 text-sm text-gray-500">
            A concise and descriptive project title
          </p>
        </div>

        {/* Idea */}
        <div className="mb-6">
          <label htmlFor="idea" className="block mb-2 font-semibold text-gray-700">
            Idea <span className="text-red-600">*</span>
          </label>
          <textarea
            id="idea"
            placeholder="Detailed description of the requirement..."
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            rows={6}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <p className="mt-1 text-sm text-gray-500">
            Comprehensive overview of concept, features, and functionalities
          </p>
        </div>

        {/* Directives */}
        <div className="mb-6">
          <label
            htmlFor="directives"
            className="block mb-2 font-semibold text-gray-700"
          >
            Directives <span className="text-gray-400">(Optional)</span>
          </label>
          <textarea
            id="directives"
            placeholder="One directive per line&#10;- Framework to use&#10;- Coding standards&#10;- Architecture pattern"
            value={directiveText}
            onChange={(e) => setDirectiveText(e.target.value)}
            rows={4}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <p className="mt-1 text-sm text-gray-500">
            Technical instructions and guidelines (one per line)
          </p>
          {parseDirectives().length > 0 && (
            <div className="mt-3 border-t pt-3">
              <p className="mb-2 text-sm font-semibold text-gray-600">
                Parsed Directives:
              </p>
              <ul className="space-y-1">
                {parseDirectives().map((directive, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-2 text-sm text-gray-700"
                  >
                    <span className="text-blue-600">•</span>
                    <span>{directive}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Environment Variables */}
        <div className="mb-6">
          <label className="block mb-2 font-semibold text-gray-700">
            Environment Variables <span className="text-gray-400">(Optional)</span>
          </label>
          <div className="space-y-3">
            {envVars.map((envVar, index) => (
              <div key={index} className="flex gap-2">
                <input
                  type="text"
                  placeholder="Variable name"
                  value={envVar.key}
                  onChange={(e) => updateEnvVar(index, "key", e.target.value)}
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
                <input
                  type="text"
                  placeholder="Description"
                  value={envVar.value}
                  onChange={(e) => updateEnvVar(index, "value", e.target.value)}
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
                {envVars.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeEnvVar(index)}
                    className="rounded-lg bg-red-100 px-3 py-2 text-red-700 hover:bg-red-200"
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={addEnvVar}
            className="mt-3 rounded-lg bg-blue-100 px-4 py-2 text-blue-700 hover:bg-blue-200"
          >
            + Add Environment Variable
          </button>

          {Object.keys(parseEnvs()).length > 0 && (
            <div className="mt-3 border-t pt-3">
              <p className="mb-2 text-sm font-semibold text-gray-600">
                Parsed Variables:
              </p>
              <ul className="space-y-1">
                {Object.entries(parseEnvs()).map(([key, value]) => (
                  <li key={key} className="text-sm text-gray-700">
                    <span className="font-semibold text-gray-800">{key}:</span>{" "}
                    {value}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button
            type="button"
            onClick={handlePreview}
            disabled={!isFormValid}
            className="rounded-lg border border-gray-300 px-6 py-2 font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Preview
          </button>
          <button
            type="button"
            onClick={handleDownload}
            disabled={!isFormValid}
            className="rounded-lg bg-blue-600 px-6 py-2 font-semibold text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Download Email
          </button>
        </div>

        {!isFormValid && (
          <p className="mt-3 text-sm text-red-600">
            Please fill in all required fields (Project Name, Title, Idea)
          </p>
        )}
      </div>

      {/* Preview Modal */}
      {showPreview && (
        <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50 p-4 z-50">
          <div className="w-full max-w-2xl rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-xl font-bold text-gray-900">Email Preview</h3>
            <pre className="mb-4 max-h-96 overflow-auto rounded-lg bg-gray-50 p-4 text-sm text-gray-700 border border-gray-200">
              {preview}
            </pre>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setShowPreview(false)}
                className="rounded-lg border border-gray-300 px-4 py-2 font-semibold text-gray-700 hover:bg-gray-50"
              >
                Close
              </button>
              <button
                type="button"
                onClick={handleDownload}
                className="rounded-lg bg-blue-600 px-4 py-2 font-semibold text-white hover:bg-blue-700"
              >
                Download This Email
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
