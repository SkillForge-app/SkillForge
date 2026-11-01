"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, BookOpenCheck, CircleHelp, LockKeyhole, Sparkles } from "lucide-react";
import {
  SchemaDrivenForm,
  createInitialValue,
  type JsonSchema,
} from "@/components/schema-driven-form";
import skillSpecSchemaFile from "@/lib/skillspec/schema.json";

const skillSpecSchema = skillSpecSchemaFile as JsonSchema;

export default function SkillReviewPage({ skillId }: { skillId: string }) {
  const [spec, setSpec] = useState(() => createInitialValue(skillSpecSchema));
  const [hasUnsavedEdits, setHasUnsavedEdits] = useState(false);

  function updateSpec(next: Record<string, unknown>) {
    setSpec(next);
    setHasUnsavedEdits(true);
  }

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
        <Link className="skill-review-back" href={`/skills/${encodeURIComponent(skillId)}/preview`}>
          <ArrowRight size={17} /> معاينة الحزمة
        </Link>
      </header>

      <section className="skill-review-main" aria-labelledby="review-title">
        <div className="skill-review-eyebrow">
          <BookOpenCheck size={15} /> مراجعة المهارة
        </div>
        <div className="skill-review-title-row">
          <div>
            <h1 id="review-title">راجع مواصفات المهارة</h1>
            <p>حقول الصفحة متولدة مباشرة من مخطط AI-01.</p>
          </div>
          <span className="skill-review-schema-version">SkillSpec v0.2</span>
        </div>

        <div className="skill-review-contract-note" role="note">
          <CircleHelp size={17} />
          <p>
            تغييراتك محفوظة في الصفحة الحالية فقط. الحفظ والتحقق عبر الخدمة وتجهيز الحزم محتاجين
            عمليات BE-09.
          </p>
        </div>
        {hasUnsavedEdits && (
          <p className="skill-review-dirty" role="status">
            فيه تغييرات محلية غير محفوظة.
          </p>
        )}

        <SchemaDrivenForm schema={skillSpecSchema} value={spec} issues={[]} onChange={updateSpec} />

        <div className="skill-review-actions">
          <button type="button" className="skill-review-button" disabled>
            <LockKeyhole size={15} /> حفظ المسودة
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
