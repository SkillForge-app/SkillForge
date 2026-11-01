"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Check, ChevronLeft, CircleHelp, Sparkles } from "lucide-react";

type SingleQuestion = {
  id: string;
  kind: "single";
  title: string;
  detail: string;
  options: string[];
};

type MultipleQuestion = {
  id: string;
  kind: "multiple";
  title: string;
  detail: string;
  options: string[];
};

type TextQuestion = {
  id: string;
  kind: "text";
  title: string;
  detail: string;
  placeholder: string;
};

type PreviewQuestion = SingleQuestion | MultipleQuestion | TextQuestion;
type Answer = string | string[];

// UI preview data only. AI-05 defines the response contract and real question types.
const previewQuestions: PreviewQuestion[] = [
  {
    id: "preferred-output",
    kind: "single",
    title: "شكل المساعدة اللي تفضّله إيه؟",
    detail: "اختار أكتر شكل مناسب لطريقة شغلك.",
    options: ["شرح مختصر وواضح", "خطوات مرتبة واحدة واحدة", "حل جاهز أقدر أبدأ منه"],
  },
  {
    id: "working-context",
    kind: "multiple",
    title: "هتستخدم المهارة فين غالبًا؟",
    detail: "ممكن تختار أكتر من اختيار.",
    options: ["داخل محرر الكود", "في سطر الأوامر", "أثناء مراجعة التغييرات"],
  },
  {
    id: "guardrails",
    kind: "text",
    title: "في قواعد لازم المهارة تلتزم بيها؟",
    detail: "اكتب أي تفضيلات أو حدود مهمة، أو تخطَّ السؤال لو مش متأكد.",
    placeholder: "مثال: ما تغيّرش ملفات قبل ما تشرحلي السبب...",
  },
];

export default function QuestionsWizard({ requestId }: { requestId: string }) {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [skipped, setSkipped] = useState<string[]>([]);
  const [attempted, setAttempted] = useState(false);
  const [submittedPreview, setSubmittedPreview] = useState(false);

  const question = previewQuestions[step];
  const currentAnswer = answers[question.id];
  const hasAnswer = Array.isArray(currentAnswer)
    ? currentAnswer.length > 0
    : typeof currentAnswer === "string" && currentAnswer.trim().length > 0;
  const isLastStep = step === previewQuestions.length - 1;

  function saveAnswer(value: Answer) {
    setAnswers((current) => ({ ...current, [question.id]: value }));
    setSkipped((current) => current.filter((id) => id !== question.id));
    setAttempted(false);
    setSubmittedPreview(false);
  }

  function moveToNext(skip: boolean) {
    if (!skip && !hasAnswer) {
      setAttempted(true);
      return;
    }

    if (skip) {
      setSkipped((current) =>
        current.includes(question.id) ? current : [...current, question.id],
      );
    }
    setAttempted(false);

    if (isLastStep) {
      setSubmittedPreview(true);
      return;
    }

    setStep((current) => current + 1);
  }

  function moveBack() {
    setAttempted(false);
    setSubmittedPreview(false);
    setStep((current) => Math.max(0, current - 1));
  }

  function toggleMultipleOption(option: string) {
    const current = Array.isArray(currentAnswer) ? currentAnswer : [];
    saveAnswer(
      current.includes(option) ? current.filter((item) => item !== option) : [...current, option],
    );
  }

  return (
    <main className="questions-page" dir="rtl">
      <header className="questions-topbar">
        <Link className="questions-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="questions-brand-mark">
            <Sparkles size={18} strokeWidth={1.8} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
        <Link className="questions-exit" href="/skills/new">
          <ArrowRight size={17} />
          <span>الرجوع لوصف المهارة</span>
        </Link>
      </header>

      <section className="questions-main" aria-labelledby="questions-title">
        <div className="questions-preview-label">
          <CircleHelp size={15} />
          معاينة واجهة الأسئلة
        </div>
        <p className="questions-step-count">
          السؤال {new Intl.NumberFormat("ar-EG").format(step + 1)} من{" "}
          {new Intl.NumberFormat("ar-EG").format(previewQuestions.length)}
        </p>
        <div
          className="questions-progress-track"
          role="progressbar"
          aria-label="التقدم في أسئلة التوضيح"
          aria-valuemin={1}
          aria-valuemax={previewQuestions.length}
          aria-valuenow={step + 1}
        >
          <span style={{ width: `${((step + 1) / previewQuestions.length) * 100}%` }} />
        </div>

        <div className="questions-heading">
          <h1 id="questions-title">خلينا نوضح شوية تفاصيل</h1>
          <p>إجاباتك تساعد في تشكيل المهارة. تقدر ترجع للسؤال السابق أو تتخطى أي سؤال.</p>
        </div>

        <article className="question-card" aria-live="polite">
          <span className="question-card-number">
            {new Intl.NumberFormat("ar-EG").format(step + 1)}
          </span>
          <div className="question-card-copy">
            <h2>{question.title}</h2>
            <p>{question.detail}</p>
          </div>

          {question.kind === "single" && (
            <div className="question-options" role="group" aria-label={question.title}>
              {question.options.map((option) => {
                const selected = currentAnswer === option;
                return (
                  <button
                    className={`question-option ${selected ? "question-option-selected" : ""}`}
                    key={option}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => saveAnswer(option)}
                  >
                    <span>{option}</span>
                    <span className="question-option-check" aria-hidden="true">
                      {selected && <Check size={14} />}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {question.kind === "multiple" && (
            <div className="question-options" role="group" aria-label={question.title}>
              {question.options.map((option) => {
                const selected = Array.isArray(currentAnswer) && currentAnswer.includes(option);
                return (
                  <button
                    className={`question-option ${selected ? "question-option-selected" : ""}`}
                    key={option}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => toggleMultipleOption(option)}
                  >
                    <span>{option}</span>
                    <span className="question-option-check" aria-hidden="true">
                      {selected && <Check size={14} />}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {question.kind === "text" && (
            <textarea
              className="question-textarea"
              value={typeof currentAnswer === "string" ? currentAnswer : ""}
              onChange={(event) => saveAnswer(event.target.value)}
              placeholder={question.placeholder}
              rows={4}
              aria-label={question.title}
            />
          )}

          {attempted && !hasAnswer && (
            <p className="question-validation" role="alert">
              جاوب على السؤال أو اختار «تخطي السؤال».
            </p>
          )}
        </article>

        <div className="questions-actions">
          {step === 0 ? (
            <Link className="questions-back" href="/skills/new">
              <ArrowRight size={16} />
              تعديل الوصف
            </Link>
          ) : (
            <button className="questions-back" type="button" onClick={moveBack}>
              <ArrowRight size={16} />
              السابق
            </button>
          )}

          <div className="questions-next-actions">
            <button className="questions-skip" type="button" onClick={() => moveToNext(true)}>
              تخطي السؤال
            </button>
            <button className="questions-continue" type="button" onClick={() => moveToNext(false)}>
              <span>{isLastStep ? "إرسال الإجابات" : "حفظ ومتابعة"}</span>
              <ChevronLeft size={17} />
            </button>
          </div>
        </div>

        {submittedPreview && (
          <p className="questions-preview-note" role="status">
            دي معاينة محلية. حفظ الإجابات في الطلب هيشتغل لما يتوصل BE-05.
          </p>
        )}
        <p className="questions-request-id">
          معرّف الطلب: <span dir="ltr">{requestId}</span>
        </p>
      </section>
    </main>
  );
}
