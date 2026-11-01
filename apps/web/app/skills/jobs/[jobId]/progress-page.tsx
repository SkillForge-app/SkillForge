"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  CircleAlert,
  CircleCheck,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  Sparkles,
} from "lucide-react";

type JobState = "running" | "failed" | "ready";

const stages = [
  "فهم الطلب",
  "مراجعة المهارات الموجودة",
  "جمع المعرفة والمصادر",
  "تصميم مواصفات المهارة",
  "التحقق من المهارة",
  "تجهيز الحزم",
];

// Preview fixtures only: BE-08 owns the real job status, event stages, and sources.
const previewSources = [
  { title: "إرشادات توثيق React", domain: "react.dev" },
  { title: "دليل إتاحة الويب", domain: "web.dev" },
];

const previewStates: { id: JobState; label: string }[] = [
  { id: "running", label: "جاري التنفيذ" },
  { id: "failed", label: "تعذر التنفيذ" },
  { id: "ready", label: "اكتملت المهارة" },
];

export default function JobProgressPage({ jobId }: { jobId: string }) {
  const [jobState, setJobState] = useState<JobState>("running");
  const [activeStage, setActiveStage] = useState(2);
  const [notice, setNotice] = useState("");

  function chooseState(state: JobState) {
    setJobState(state);
    setNotice("");
  }

  function retryPreview() {
    setJobState("running");
    setActiveStage(0);
    setNotice("دي معاينة محلية؛ إعادة المحاولة مش بتبعت طلب للسيرفر.");
  }

  const title =
    jobState === "failed"
      ? "مقدرناش نكمل إنشاء المهارة"
      : jobState === "ready"
        ? "المهارة بقت جاهزة للمراجعة"
        : "بنجهز مهارتك";

  return (
    <main className="job-progress-page" dir="rtl">
      <header className="job-progress-topbar">
        <Link className="job-progress-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="job-progress-brand-mark">
            <Sparkles size={18} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
        <Link className="job-progress-exit" href="/skills/new">
          <ArrowRight size={17} />
          <span>العودة لإنشاء مهارة</span>
        </Link>
      </header>

      <section className="job-progress-main" aria-labelledby="job-progress-title">
        <div className={`job-progress-status job-progress-status-${jobState}`}>
          {jobState === "running" ? (
            <LoaderCircle size={16} className="job-progress-spinner" />
          ) : jobState === "failed" ? (
            <CircleAlert size={16} />
          ) : (
            <CircleCheck size={16} />
          )}
          <span>
            {jobState === "running"
              ? "قيد الإنشاء"
              : jobState === "failed"
                ? "توقف الإنشاء"
                : "اكتمل الإنشاء"}
          </span>
        </div>
        <h1 id="job-progress-title">{title}</h1>
        <p className="job-progress-intro">
          {jobState === "failed"
            ? "حصلت مشكلة أثناء تجهيز المهارة. تقدر تعيد المحاولة أو ترجع لطلبك."
            : jobState === "ready"
              ? "تقدر تراجع مواصفات المهارة قبل ما تجهز ملفاتها."
              : "بنمشي في خطوات تجهيز المهارة. تقدر تسيب الصفحة وترجع لها بعدين."}
        </p>

        <fieldset className="job-preview-picker">
          <legend>حالات المعاينة فقط</legend>
          <div className="job-preview-state-list">
            {previewStates.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                className={`job-preview-state ${jobState === id ? "job-preview-state-active" : ""}`}
                aria-pressed={jobState === id}
                onClick={() => chooseState(id)}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>

        {jobState === "failed" ? (
          <section className="job-failure-card" aria-live="polite">
            <span className="job-failure-icon">
              <CircleAlert size={21} />
            </span>
            <div>
              <h2>تعذر تجهيز المهارة</h2>
              <p>تفاصيل الخطأ وخيارات استكمال الطلب هتظهر هنا بعد تحديد عقد الـ API.</p>
              <div className="job-progress-actions">
                <button type="button" className="job-primary-action" onClick={retryPreview}>
                  <RefreshCw size={16} /> إعادة المحاولة
                </button>
                <button
                  type="button"
                  className="job-secondary-action"
                  onClick={() => setNotice("الرجوع للطلب محتاج ربط معرّف الطلب بعقد BE-08.")}
                >
                  <ArrowRight size={16} /> الرجوع للطلب
                </button>
              </div>
            </div>
          </section>
        ) : (
          <>
            <section className="job-stage-card" aria-labelledby="job-stages-title">
              <div className="job-stage-heading">
                <h2 id="job-stages-title">مراحل تجهيز المهارة</h2>
                {jobState === "running" && <span>المرحلة الحالية: {stages[activeStage]}</span>}
              </div>
              <ol
                className={`job-stage-list ${jobState === "ready" ? "job-stage-list-ready" : ""}`}
              >
                {stages.map((stage, index) => {
                  const complete = jobState === "ready" || index < activeStage;
                  const current = jobState === "running" && index === activeStage;
                  return (
                    <li
                      className={`job-stage ${complete ? "job-stage-complete" : ""} ${current ? "job-stage-current" : ""}`}
                      key={stage}
                    >
                      <span className="job-stage-icon" aria-hidden="true">
                        {complete ? (
                          <Check size={15} />
                        ) : current ? (
                          <LoaderCircle size={15} className="job-progress-spinner" />
                        ) : (
                          <span>{index + 1}</span>
                        )}
                      </span>
                      <span>{stage}</span>
                      {current && <span className="job-stage-current-label">دلوقتي</span>}
                    </li>
                  );
                })}
              </ol>
            </section>

            <section className="job-sources-card" aria-labelledby="job-sources-title">
              <div className="job-sources-heading">
                <span className="job-sources-icon">
                  <BookOpen size={18} />
                </span>
                <div>
                  <h2 id="job-sources-title">المصادر اللي بنراجعها</h2>
                  <p>روابط المصادر الفعلية هتظهر مع بيانات المهمة.</p>
                </div>
              </div>
              <ul className="job-source-list">
                {previewSources.map((source) => (
                  <li className="job-source-item" key={source.domain}>
                    <div>
                      <strong>{source.title}</strong>
                      <span>{source.domain}</span>
                    </div>
                    <button
                      type="button"
                      disabled
                      aria-label={`رابط معاينة غير متاح: ${source.title}`}
                    >
                      <ExternalLink size={15} /> فتح المصدر
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}

        {jobState === "ready" && (
          <Link
            className="job-primary-action job-result-link"
            href={`/skills/jobs/${encodeURIComponent(jobId)}/result`}
          >
            <span>عرض النتيجة</span>
            <ArrowRight size={16} />
          </Link>
        )}
        {notice && (
          <p className="job-preview-notice" role="status">
            {notice}
          </p>
        )}
        <p className="job-preview-note">
          معاينة ببيانات محلية. التقدم الفعلي والاستعادة بعد تحديث الصفحة محتاجين BE-08.
        </p>
        <p className="job-id-label">
          معرّف المهمة: <span dir="ltr">{jobId}</span>
        </p>
      </section>
    </main>
  );
}
