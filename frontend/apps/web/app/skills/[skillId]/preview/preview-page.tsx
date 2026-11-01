"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  Braces,
  Check,
  ChevronDown,
  Download,
  FileCode2,
  FileText,
  Folder,
  FolderOpen,
  Sparkles,
} from "lucide-react";

type Platform = "claude" | "codex";
type PreviewMode = "rendered" | "raw";
type PackageFile = {
  id: string;
  name: string;
  folder: "" | "references" | "templates";
  raw: string;
  rendered: { kind: "heading" | "paragraph" | "list"; text: string | string[] }[];
};

// UI fixtures only. BE-09/BE-10 must supply the real compiler output and archive files.
const files: PackageFile[] = [
  {
    id: "skill",
    name: "SKILL.md",
    folder: "",
    raw: `# React Code Reviewer\n\nReview React changes for correctness, accessibility, and maintainability.\n\n## Workflow\n\n1. Understand the change and its intended behavior.\n2. Check component state, effects, and accessible interactions.\n3. Report actionable findings with file and line references.\n\n## Guardrails\n\n- Explain the impact before suggesting a fix.\n- Do not modify files unless the user asks.\n`,
    rendered: [
      { kind: "heading", text: "React Code Reviewer" },
      {
        kind: "paragraph",
        text: "Review React changes for correctness, accessibility, and maintainability.",
      },
      { kind: "heading", text: "Workflow" },
      {
        kind: "list",
        text: [
          "Understand the change and its intended behavior.",
          "Check component state, effects, and accessible interactions.",
          "Report actionable findings with file and line references.",
        ],
      },
      { kind: "heading", text: "Guardrails" },
      {
        kind: "list",
        text: [
          "Explain the impact before suggesting a fix.",
          "Do not modify files unless the user asks.",
        ],
      },
    ],
  },
  {
    id: "reference",
    name: "review-checklist.md",
    folder: "references",
    raw: `# Review checklist\n\n- Verify behavior at empty, loading, and error states.\n- Check keyboard access and visible focus.\n- Prefer specific, testable findings.\n`,
    rendered: [
      { kind: "heading", text: "Review checklist" },
      {
        kind: "list",
        text: [
          "Verify behavior at empty, loading, and error states.",
          "Check keyboard access and visible focus.",
          "Prefer specific, testable findings.",
        ],
      },
    ],
  },
  {
    id: "template",
    name: "review-summary.md",
    folder: "templates",
    raw: `# Review summary\n\n## Findings\n\n- [Severity] [File:line] — [Actionable description]\n\n## Notes\n\n- [Questions or follow-up context]\n`,
    rendered: [
      { kind: "heading", text: "Review summary" },
      { kind: "heading", text: "Findings" },
      { kind: "list", text: ["[Severity] [File:line] — [Actionable description]"] },
      { kind: "heading", text: "Notes" },
      { kind: "list", text: ["[Questions or follow-up context]"] },
    ],
  },
];

const platformLabels: Record<Platform, string> = { claude: "Claude Code", codex: "Codex" };

export default function SkillPackagePreview({ skillId }: { skillId: string }) {
  const [platform, setPlatform] = useState<Platform>("claude");
  const [selectedFileId, setSelectedFileId] = useState("skill");
  const [mode, setMode] = useState<PreviewMode>("rendered");
  const selectedFile = files.find((file) => file.id === selectedFileId) ?? files[0];

  function renderBlock(block: PackageFile["rendered"][number], index: number) {
    if (block.kind === "heading") {
      return index === 0 ? <h1 key={index}>{block.text}</h1> : <h2 key={index}>{block.text}</h2>;
    }
    if (block.kind === "paragraph") return <p key={index}>{block.text}</p>;
    return (
      <ul key={index}>
        {(block.text as string[]).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    );
  }

  return (
    <main className="package-preview-page" dir="rtl">
      <header className="package-preview-topbar">
        <Link className="package-preview-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="package-preview-brand-mark">
            <Sparkles size={18} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
        <Link
          className="package-preview-back"
          href={`/skills/${encodeURIComponent(skillId)}/review`}
        >
          <ArrowRight size={17} /> العودة للمراجعة
        </Link>
      </header>

      <section className="package-preview-main" aria-labelledby="package-preview-title">
        <div className="package-preview-heading">
          <div>
            <span className="package-preview-eyebrow">معاينة ملفات المهارة</span>
            <h1 id="package-preview-title">مراجع كود React</h1>
            <p>راجع محتويات الحزمة قبل تنزيلها.</p>
          </div>
          <div className="package-platform-picker" role="group" aria-label="اختيار المنصة">
            {(["claude", "codex"] as const).map((id) => (
              <button
                key={id}
                type="button"
                className={platform === id ? "package-platform-active" : ""}
                aria-pressed={platform === id}
                onClick={() => setPlatform(id)}
              >
                {id === "claude" ? <Sparkles size={15} /> : <Braces size={15} />}
                {platformLabels[id]}
              </button>
            ))}
          </div>
        </div>

        <div className="package-preview-layout">
          <aside className="package-file-sidebar" aria-label="ملفات الحزمة">
            <div className="package-file-sidebar-heading">
              <FolderOpen size={16} /> skill-folder <ChevronDown size={14} />
            </div>
            <nav className="package-file-tree">
              <button
                type="button"
                className={`package-file-item ${selectedFileId === "skill" ? "package-file-selected" : ""}`}
                aria-current={selectedFileId === "skill" ? "page" : undefined}
                onClick={() => setSelectedFileId("skill")}
              >
                <FileText size={15} /> SKILL.md
              </button>
              <div className="package-folder-label">
                <Folder size={15} /> references/
              </div>
              <button
                type="button"
                className={`package-file-item package-file-nested ${selectedFileId === "reference" ? "package-file-selected" : ""}`}
                aria-current={selectedFileId === "reference" ? "page" : undefined}
                onClick={() => setSelectedFileId("reference")}
              >
                <FileCode2 size={15} /> review-checklist.md
              </button>
              <div className="package-folder-label">
                <Folder size={15} /> templates/
              </div>
              <button
                type="button"
                className={`package-file-item package-file-nested ${selectedFileId === "template" ? "package-file-selected" : ""}`}
                aria-current={selectedFileId === "template" ? "page" : undefined}
                onClick={() => setSelectedFileId("template")}
              >
                <FileCode2 size={15} /> review-summary.md
              </button>
            </nav>
          </aside>

          <section className="package-file-viewer" aria-label="معاينة الملف المحدد">
            <div className="package-file-toolbar">
              <strong>{selectedFile.name}</strong>
              <div className="package-view-mode" role="group" aria-label="طريقة عرض الملف">
                <button
                  type="button"
                  aria-pressed={mode === "rendered"}
                  className={mode === "rendered" ? "package-view-active" : ""}
                  onClick={() => setMode("rendered")}
                >
                  منسق
                </button>
                <button
                  type="button"
                  aria-pressed={mode === "raw"}
                  className={mode === "raw" ? "package-view-active" : ""}
                  onClick={() => setMode("raw")}
                >
                  Markdown خام
                </button>
              </div>
            </div>
            <div
              className={`package-file-content ${mode === "raw" ? "package-file-content-raw" : ""}`}
            >
              {mode === "raw" ? (
                <pre dir="ltr">
                  <code>{selectedFile.raw}</code>
                </pre>
              ) : (
                selectedFile.rendered.map(renderBlock)
              )}
            </div>
            <p className="package-fixture-note">
              <Check size={14} /> دي بيانات معاينة محلية، مش ملفات مولّدة من المهارة.
            </p>
          </section>
        </div>

        <div className="package-preview-footer">
          <p>
            المنصة المحددة: <strong>{platformLabels[platform]}</strong>
          </p>
          <div>
            <Link
              className="package-install-button"
              href={`/skills/${encodeURIComponent(skillId)}/install`}
            >
              تعليمات التثبيت
            </Link>
            <button
              type="button"
              className="package-download-button"
              disabled
              aria-label="تنزيل ZIP غير متاح قبل ربط ملفات الحزمة"
            >
              <Download size={16} /> تنزيل ZIP
            </button>
          </div>
        </div>
        <p className="package-skill-id">
          معرّف المهارة: <span dir="ltr">{skillId}</span>
        </p>
      </section>
    </main>
  );
}
