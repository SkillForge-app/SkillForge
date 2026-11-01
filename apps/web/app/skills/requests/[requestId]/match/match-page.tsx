"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  CircleAlert,
  Code2,
  FilePlus2,
  Layers3,
  RefreshCw,
  Sparkles,
  WandSparkles,
} from "lucide-react";

type PreviewState = "match" | "multiple" | "none" | "error";

type Skill = {
  id: string;
  name: string;
  summary: string;
  platform: string;
  version: string;
  tags: string[];
};

const skills: Skill[] = [
  {
    id: "react-reviewer",
    name: "مراجع كود React",
    summary: "يراجع مكونات React، يحدد المشكلات، ويقترح إصلاحات عملية مع شرحها.",
    platform: "Claude Code",
    version: "1.4.0",
    tags: ["React", "Code review", "Frontend"],
  },
  {
    id: "frontend-accessibility",
    name: "مراجع إتاحة الواجهات",
    summary: "يفحص الواجهات الأمامية ويقترح تحسينات في الوصول وتجربة الاستخدام.",
    platform: "Codex",
    version: "1.1.0",
    tags: ["Accessibility", "Frontend", "Review"],
  },
];

const previewStates: { id: PreviewState; label: string }[] = [
  { id: "match", label: "نتيجة واحدة" },
  { id: "multiple", label: "أكثر من نتيجة" },
  { id: "none", label: "مفيش نتيجة" },
  { id: "error", label: "خطأ" },
];

export default function MatchPage({ requestId }: { requestId: string }) {
  const [previewState, setPreviewState] = useState<PreviewState>("match");
  const [notice, setNotice] = useState("");

  function choosePreviewState(state: PreviewState) {
    setPreviewState(state);
    setNotice("");
  }

  function describePendingAction(action: string) {
    setNotice(`معاينة فقط: إجراء «${action}» هيتوصل بالـ API لما عقد AI-08 وBE-11 يجهز.`);
  }

  const displayedSkills = previewState === "multiple" ? skills : [skills[0]];

  return (
    <main className="match-page" dir="rtl">
      <header className="match-topbar">
        <Link className="match-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="match-brand-mark">
            <Sparkles size={18} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
        <Link
          className="match-exit"
          href={`/skills/requests/${encodeURIComponent(requestId)}/questions`}
        >
          <ArrowRight size={17} />
          <span>الرجوع للأسئلة</span>
        </Link>
      </header>

      <section className="match-main" aria-labelledby="match-title">
        <div className="match-eyebrow">
          <Layers3 size={15} /> معاينة نتيجة البحث
        </div>
        <h1 id="match-title">
          {previewState === "error" ? "حصلت مشكلة وإحنا بندور" : "هل فيه مهارة مناسبة لفكرتك؟"}
        </h1>
        <p className="match-intro">
          {previewState === "error"
            ? "البحث مش متاح دلوقتي. تقدر تعيد المحاولة أو تكمل بإنشاء مهارة جديدة."
            : "راجع الاقتراحات واختار إذا كانت مهارة موجودة مناسبة، أو كمّل بإنشاء مهارة جديدة."}
        </p>

        <fieldset className="match-state-picker">
          <legend>حالات المعاينة فقط</legend>
          <div className="match-state-list">
            {previewStates.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                className={`match-state-button ${previewState === id ? "match-state-button-active" : ""}`}
                aria-pressed={previewState === id}
                onClick={() => choosePreviewState(id)}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>

        {previewState === "error" ? (
          <section className="match-empty-card" aria-live="polite">
            <span className="match-empty-icon match-error-icon">
              <CircleAlert size={22} />
            </span>
            <h2>تعذر إكمال البحث</h2>
            <p>
              مفيش اتصال بخدمة البحث في المعاينة دي. تفاصيل الخطأ هتظهر هنا بعد تحديد شكل أخطاء الـ
              API.
            </p>
            <div className="match-empty-actions">
              <button
                className="match-secondary-action"
                type="button"
                onClick={() => describePendingAction("إعادة البحث")}
              >
                <RefreshCw size={16} /> إعادة المحاولة
              </button>
              <button
                className="match-primary-action"
                type="button"
                onClick={() => describePendingAction("إنشاء مهارة جديدة")}
              >
                <WandSparkles size={16} /> إنشاء مهارة جديدة
              </button>
            </div>
          </section>
        ) : previewState === "none" ? (
          <section className="match-empty-card" aria-live="polite">
            <span className="match-empty-icon">
              <BookOpen size={22} />
            </span>
            <h2>ملقيناش مهارة مناسبة</h2>
            <p>تقدر تكمّل فكرتك ونبدأ إنشاء مهارة جديدة مناسبة لاحتياجك.</p>
            <button
              className="match-primary-action"
              type="button"
              onClick={() => describePendingAction("إنشاء مهارة جديدة")}
            >
              <WandSparkles size={16} /> إنشاء مهارة جديدة
            </button>
          </section>
        ) : (
          <section className="match-results" aria-live="polite">
            <div className="match-results-heading">
              <h2>
                {previewState === "multiple"
                  ? "لقينا كذا مهارة ممكن تناسبك"
                  : "لقينا مهارة ممكن تناسبك"}
              </h2>
              <p>
                {previewState === "multiple"
                  ? "اختار المهارة الأقرب لاحتياجك."
                  : "راجع وصف المهارة قبل ما تختار."}
              </p>
            </div>
            <div className="match-skill-list">
              {displayedSkills.map((skill) => (
                <article className="match-skill-card" key={skill.id}>
                  <div className="match-skill-icon">
                    <Code2 size={20} />
                  </div>
                  <div className="match-skill-content">
                    <div className="match-skill-title-row">
                      <h3>{skill.name}</h3>
                      <span className="match-version">v{skill.version}</span>
                    </div>
                    <p>{skill.summary}</p>
                    <div className="match-skill-meta">
                      <span>{skill.platform}</span>
                      {skill.tags.map((tag) => (
                        <span className="match-tag" key={tag}>
                          {tag}
                        </span>
                      ))}
                    </div>
                    <div className="match-card-actions">
                      <button
                        className="match-primary-action"
                        type="button"
                        onClick={() => describePendingAction(`استخدام ${skill.name}`)}
                      >
                        <Check size={16} /> استخدام المهارة
                      </button>
                      <button
                        className="match-secondary-action"
                        type="button"
                        onClick={() => describePendingAction(`تخصيص ${skill.name}`)}
                      >
                        <FilePlus2 size={16} /> تخصيصها
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
            <div className="match-new-skill">
              <div>
                <strong>عايز تبدأ من الصفر؟</strong>
                <p>كمّل بإنشاء مهارة جديدة من وصفك.</p>
              </div>
              <button
                className="match-secondary-action"
                type="button"
                onClick={() => describePendingAction("إنشاء مهارة جديدة")}
              >
                <WandSparkles size={16} /> إنشاء مهارة جديدة
              </button>
            </div>
          </section>
        )}

        {notice && (
          <p className="match-preview-notice" role="status">
            {notice}
          </p>
        )}
        <p className="match-request-id">
          معرّف الطلب: <span dir="ltr">{requestId}</span>
        </p>
      </section>
    </main>
  );
}
