"use client";

import Link from "next/link";
import { ArrowRight, BookOpenCheck, CircleHelp, Code2, LockKeyhole, Sparkles } from "lucide-react";

export default function SkillReviewPage({ skillId }: { skillId: string }) {
  return (
    <main className="skill-review-page" dir="rtl">
      <header className="skill-review-topbar">
        <Link className="skill-review-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="skill-review-brand-mark">
            <Sparkles size={18} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
        <Link className="skill-review-back" href="/skills/new">
          <ArrowRight size={17} /> العودة
        </Link>
      </header>

      <section className="skill-review-main" aria-labelledby="review-title">
        <div className="skill-review-eyebrow">
          <BookOpenCheck size={15} /> مراجعة المهارة
        </div>
        <h1 id="review-title">راجع مواصفات المهارة</h1>
        <p className="skill-review-intro">
          هتقدر تعدّل الأقسام حسب مخطط AI-01، وتراجع أخطاء التحقق قبل حفظ المسودة أو تجهيز الحزم.
        </p>

        <section className="skill-review-unavailable" aria-labelledby="review-unavailable-title">
          <div className="skill-review-unavailable-icon">
            <CircleHelp size={22} />
          </div>
          <div className="skill-review-unavailable-copy">
            <h2 id="review-unavailable-title">مخطط المهارة مش متوفر لسه</h2>
            <p>
              محرر الحقول هيتولد من <code>schema.json</code> اللي بيقدمه AI-01. الملف مش موجود في
              المشروع الحالي، فمش هنعرض حقول أو أقسام افتراضية ممكن تختلف عن العقد الحقيقي.
            </p>
          </div>
        </section>

        <div className="skill-review-panels">
          <article className="skill-review-panel">
            <span className="skill-review-panel-icon">
              <Code2 size={18} />
            </span>
            <div>
              <h3>توليد الحقول من المخطط</h3>
              <p>المكوّن العام جاهز لعرض الحقول بناءً على نوعها وقيودها في JSON Schema.</p>
            </div>
            <span className="skill-review-state">بانتظار AI-01</span>
          </article>
          <article className="skill-review-panel">
            <span className="skill-review-panel-icon">
              <LockKeyhole size={18} />
            </span>
            <div>
              <h3>الحفظ والتحقق والتجميع</h3>
              <p>حفظ المسودة، أخطاء التحقق بجانب الحقول، وتجهيز الحزم محتاجين عمليات BE-09.</p>
            </div>
            <span className="skill-review-state">بانتظار BE-09</span>
          </article>
        </div>

        <div className="skill-review-actions">
          <button type="button" className="skill-review-button" disabled>
            حفظ المسودة
          </button>
          <button
            type="button"
            className="skill-review-button skill-review-button-primary"
            disabled
          >
            تجهيز الحزم
          </button>
        </div>
        <p className="skill-review-id">
          معرّف المهارة: <span dir="ltr">{skillId}</span>
        </p>
      </section>
    </main>
  );
}
