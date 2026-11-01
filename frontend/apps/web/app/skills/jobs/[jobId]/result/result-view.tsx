import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  ArrowUpLeft,
  Boxes,
  Check,
  Download,
  FileCode2,
  LoaderCircle,
  Sparkles,
} from "lucide-react";

type ResultState = "pending" | "failed" | "ready";

type SkillResultViewProps = {
  jobId: string;
  state: ResultState;
};

const packages = [
  { id: "claude", title: "Claude Code", icon: Sparkles },
  { id: "codex", title: "Codex", icon: Boxes },
];

export default function SkillResultView({ jobId, state }: SkillResultViewProps) {
  return (
    <main className="skill-result-page" dir="rtl">
      <header className="skill-result-topbar">
        <Link className="skill-result-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="skill-result-brand-mark">
            <Sparkles size={18} strokeWidth={1.8} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
        <Link className="skill-result-back" href="/">
          <ArrowRight size={17} />
          <span>العودة للرئيسية</span>
        </Link>
      </header>

      <section className="skill-result-main" aria-live="polite">
        {state === "pending" && (
          <div className="skill-result-state">
            <div className="skill-result-status-icon skill-result-status-pending">
              <LoaderCircle size={23} />
            </div>
            <span className="skill-result-eyebrow">طلب إنشاء المهارة</span>
            <h1>طلبك قيد التجهيز</h1>
            <p className="skill-result-description">
              هتظهر هنا الحزم وروابط التنزيل لما تكون جاهزة.
            </p>
            <div className="skill-result-job-card">
              <span className="skill-result-job-icon">
                <FileCode2 size={18} />
              </span>
              <span>
                <strong>جارٍ تجهيز الحزمة</strong>
                <small dir="ltr">{jobId}</small>
              </span>
            </div>
            <div className="skill-result-placeholder-packages" aria-hidden="true">
              {packages.map(({ id, title, icon: Icon }) => (
                <div className="skill-result-package-card skill-result-package-pending" key={id}>
                  <span className="skill-result-package-icon">
                    <Icon size={18} />
                  </span>
                  <span className="skill-result-package-copy">
                    <strong>{title}</strong>
                    <small>بانتظار تجهيز الملفات</small>
                  </span>
                  <span className="skill-result-download-disabled">
                    <Download size={16} />
                  </span>
                </div>
              ))}
            </div>
            <Link className="skill-result-text-link" href="/">
              <ArrowUpLeft size={16} />
              متابعة لاحقًا
            </Link>
          </div>
        )}

        {state === "failed" && (
          <div className="skill-result-state">
            <div className="skill-result-status-icon skill-result-status-failed">
              <AlertCircle size={23} />
            </div>
            <span className="skill-result-eyebrow">طلب إنشاء المهارة</span>
            <h1>ما قدرناش نجهز الحزمة</h1>
            <p className="skill-result-description">
              حصلت مشكلة أثناء تجهيز الملفات. تقدر تبدأ طلبًا جديدًا أو ترجع للرئيسية.
            </p>
            <div className="skill-result-job-card skill-result-job-error">
              <span className="skill-result-package-icon">
                <AlertCircle size={18} />
              </span>
              <span>
                <strong>تعذر تجهيز الملفات</strong>
                <small dir="ltr">{jobId}</small>
              </span>
            </div>
            <div className="skill-result-actions">
              <Link className="skill-result-primary-action" href="/skills/new">
                إنشاء طلب جديد
              </Link>
              <Link className="skill-result-secondary-action" href="/">
                الرئيسية
              </Link>
            </div>
          </div>
        )}

        {state === "ready" && (
          <div className="skill-result-state skill-result-state-ready">
            <div className="skill-result-status-icon skill-result-status-ready">
              <Check size={23} />
            </div>
            <span className="skill-result-eyebrow">معاينة حالة الاكتمال</span>
            <h1>الحزمة جاهزة</h1>
            <p className="skill-result-description">
              لما يرجع الـAPI روابط الحزم، هتقدر تنزّل النسخة المناسبة لمنصتك من هنا.
            </p>

            <div className="skill-result-package-list">
              {packages.map(({ id, title, icon: Icon }) => (
                <article className="skill-result-package-card" key={id}>
                  <span className="skill-result-package-icon">
                    <Icon size={19} />
                  </span>
                  <span className="skill-result-package-copy">
                    <strong>{title}</strong>
                    <small>حزمة المهارة</small>
                  </span>
                  <button
                    className="skill-result-download-disabled"
                    type="button"
                    disabled
                    aria-label={`تنزيل حزمة ${title} — يتطلب ربط API`}
                  >
                    <Download size={16} />
                    <span>تنزيل ZIP</span>
                  </button>
                </article>
              ))}
            </div>

            <p className="skill-result-preview-note" role="note">
              دي معاينة للواجهة؛ زر التنزيل هيتفعّل لما يتوفر رابط الحزمة الفعلي.
            </p>
            <div className="skill-result-actions">
              <button className="skill-result-secondary-action" type="button" disabled>
                معاينة الملفات
              </button>
              <button className="skill-result-secondary-action" type="button" disabled>
                تعليمات التثبيت
              </button>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
