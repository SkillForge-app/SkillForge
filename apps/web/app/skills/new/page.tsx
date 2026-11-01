"use client";

import Link from "next/link";
import { useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowRight,
  BookOpenCheck,
  Boxes,
  Check,
  Code2,
  Sparkles,
  UserRound,
  Workflow,
} from "lucide-react";

type SkillKind = "role" | "task" | "workflow";
type Platform = "claude_code" | "codex";

const skillKinds: { id: SkillKind; title: string; detail: string; icon: typeof UserRound }[] = [
  { id: "role", title: "دور وظيفي", detail: "زي مهندس بيانات أو كاتب محتوى", icon: UserRound },
  { id: "task", title: "مهمة", detail: "شغل متكرر عايز تنفذه بسهولة", icon: Code2 },
  { id: "workflow", title: "سير عمل", detail: "مجموعة خطوات مترابطة", icon: Workflow },
];

const platforms: { id: Platform; title: string; detail: string }[] = [
  { id: "claude_code", title: "Claude Code", detail: "تتثبت كمهارة داخل Claude Code" },
  { id: "codex", title: "Codex", detail: "تتثبت كمهارة داخل Codex" },
];

export default function NewSkillPage() {
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<SkillKind | null>(null);
  const [selectedPlatforms, setSelectedPlatforms] = useState<Platform[]>([]);
  const [attempted, setAttempted] = useState(false);
  const [ready, setReady] = useState(false);

  const hasDescription = description.trim().length > 0;
  const hasPlatform = selectedPlatforms.length > 0;
  const isValid = hasDescription && kind !== null && hasPlatform;

  function togglePlatform(platform: Platform) {
    setReady(false);
    setSelectedPlatforms((current) =>
      current.includes(platform)
        ? current.filter((item) => item !== platform)
        : [...current, platform],
    );
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAttempted(true);
    setReady(false);

    if (!isValid) return;

    // BE-05 will connect this UI state to its generated request operation.
    setReady(true);
  }

  return (
    <main className="skill-create-page" dir="rtl">
      <header className="skill-create-topbar">
        <Link className="skill-create-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="skill-create-brand-mark">
            <Sparkles size={18} strokeWidth={1.8} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
        <Link className="skill-create-back" href="/">
          <ArrowRight size={17} />
          <span>العودة للرئيسية</span>
        </Link>
      </header>

      <div className="skill-create-main">
        <div className="skill-create-step">
          <span className="skill-create-step-number">١</span>
          <span>وصف المهارة</span>
        </div>

        <div className="skill-create-heading">
          <div className="skill-create-symbol">
            <Sparkles size={21} strokeWidth={1.7} />
          </div>
          <h1>إيه المهارة اللي محتاجها؟</h1>
          <p>ابدأ بوصف النتيجة اللي عايز الوكيل يساعدك توصل لها.</p>
        </div>

        <form className="skill-create-form" onSubmit={handleSubmit} noValidate>
          <section className="skill-create-section">
            <label className="skill-create-label" htmlFor="skill-description">
              احكي لنا عن الدور أو المهمة
              <span className="skill-create-required">مطلوب</span>
            </label>
            <textarea
              id="skill-description"
              className="skill-create-textarea"
              value={description}
              onChange={(event) => {
                setDescription(event.target.value);
                setReady(false);
              }}
              placeholder="مثال: عايز مساعد يراجع كود React، يكتشف المشاكل، ويشرحلي اقتراحات الإصلاح خطوة بخطوة."
              rows={5}
              aria-invalid={attempted && !hasDescription}
              aria-describedby="skill-description-hint"
            />
            <div className="skill-create-field-footer">
              <span id="skill-description-hint">اكتب بطريقتك، ومش لازم تستخدم مصطلحات تقنية.</span>
              <span aria-live="polite">{description.length} حرف</span>
            </div>
            {attempted && !hasDescription && (
              <p className="skill-create-field-error" role="alert">
                اكتب وصفًا بسيطًا للمهارة عشان نكمل.
              </p>
            )}
          </section>

          <fieldset className="skill-create-section skill-create-fieldset">
            <legend className="skill-create-label">نوع المهارة</legend>
            <div className="skill-kind-grid">
              {skillKinds.map(({ id, title, detail, icon: Icon }) => (
                <button
                  className={`skill-choice ${kind === id ? "skill-choice-selected" : ""}`}
                  key={id}
                  type="button"
                  aria-pressed={kind === id}
                  onClick={() => {
                    setKind(id);
                    setReady(false);
                  }}
                >
                  <span className="skill-choice-icon">
                    <Icon size={19} strokeWidth={1.8} />
                  </span>
                  <span className="skill-choice-copy">
                    <strong>{title}</strong>
                    <small>{detail}</small>
                  </span>
                  <span className="skill-choice-check" aria-hidden="true">
                    {kind === id && <Check size={14} />}
                  </span>
                </button>
              ))}
            </div>
            {attempted && !kind && (
              <p className="skill-create-field-error" role="alert">
                اختار النوع الأقرب لفكرتك.
              </p>
            )}
          </fieldset>

          <fieldset className="skill-create-section skill-create-fieldset">
            <legend className="skill-create-label">هتستخدم المهارة فين؟</legend>
            <p className="skill-create-section-hint">تقدر تختار منصة واحدة أو الاتنين.</p>
            <div className="platform-choice-grid">
              {platforms.map(({ id, title, detail }) => {
                const selected = selectedPlatforms.includes(id);
                return (
                  <button
                    className={`platform-choice ${selected ? "platform-choice-selected" : ""}`}
                    key={id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => togglePlatform(id)}
                  >
                    <span className="platform-choice-logo" aria-hidden="true">
                      {id === "claude_code" ? <Sparkles size={19} /> : <Boxes size={19} />}
                    </span>
                    <span className="platform-choice-copy">
                      <strong>{title}</strong>
                      <small>{detail}</small>
                    </span>
                    <span className="platform-choice-check" aria-hidden="true">
                      {selected && <Check size={14} />}
                    </span>
                  </button>
                );
              })}
            </div>
            {attempted && !hasPlatform && (
              <p className="skill-create-field-error" role="alert">
                اختار منصة واحدة على الأقل.
              </p>
            )}
          </fieldset>

          <div className="skill-create-submit-row">
            <p className="skill-create-privacy">
              <BookOpenCheck size={16} />
              هتراجع المهارة قبل ما تستخدمها.
            </p>
            <button className="skill-create-submit" type="submit">
              <span>متابعة</span>
              <ArrowRight size={17} />
            </button>
          </div>
          {ready && (
            <p className="skill-create-api-note" role="status">
              البيانات مكتملة. هيتوصل الإرسال بالخدمة لما يجهز مسار إنشاء المهارة.
            </p>
          )}
        </form>
      </div>
    </main>
  );
}
