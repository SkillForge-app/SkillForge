"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  Clipboard,
  Download,
  ExternalLink,
  Folder,
  Info,
  Sparkles,
  Terminal,
} from "lucide-react";

type Platform = "claude" | "codex";

/** UI view model populated from compiler/install guidance when its contract is available. */
export type InstallGuidance = {
  destination: string;
  steps: string[];
  command?: string;
  downloadUrl?: string;
};

type InstallPageProps = {
  skillId: string;
  guidance?: Partial<Record<Platform, InstallGuidance>>;
};

const platforms: { id: Platform; title: string }[] = [
  { id: "claude", title: "Claude Code" },
  { id: "codex", title: "Codex" },
];

export default function InstallPage({ skillId, guidance }: InstallPageProps) {
  const [platform, setPlatform] = useState<Platform>("claude");
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
  const guide = guidance?.[platform];

  async function copyDestination() {
    if (!guide?.destination) return;
    try {
      await navigator.clipboard.writeText(guide.destination);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  }

  return (
    <main className="skill-install-page" dir="rtl">
      <header className="skill-install-topbar">
        <Link className="skill-install-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="skill-install-brand-mark">
            <Sparkles size={18} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
        <Link
          className="skill-install-back"
          href={`/skills/${encodeURIComponent(skillId)}/preview`}
        >
          <ArrowRight size={17} /> معاينة الحزمة
        </Link>
      </header>

      <section className="skill-install-main" aria-labelledby="install-title">
        <div className="skill-install-eyebrow">
          <BookOpen size={15} /> تثبيت المهارة
        </div>
        <div className="skill-install-heading-row">
          <div>
            <h1 id="install-title">ثبّت المهارة في مشروعك</h1>
            <p>اختار المنصة عشان تظهر تعليمات التثبيت المناسبة.</p>
          </div>
          <div className="skill-install-platform-picker" role="group" aria-label="اختيار المنصة">
            {platforms.map(({ id, title }) => (
              <button
                key={id}
                type="button"
                className={platform === id ? "skill-install-platform-active" : ""}
                aria-pressed={platform === id}
                onClick={() => {
                  setPlatform(id);
                  setCopyStatus("idle");
                }}
              >
                {title}
              </button>
            ))}
          </div>
        </div>

        {guide ? (
          <>
            <section
              className="skill-install-destination"
              aria-labelledby="install-destination-title"
            >
              <div className="skill-install-section-heading">
                <span className="skill-install-section-icon">
                  <Folder size={18} />
                </span>
                <div>
                  <h2 id="install-destination-title">مجلد التثبيت</h2>
                  <p>المسار جاي من تعليمات المنصة المعتمدة.</p>
                </div>
              </div>
              <div className="skill-install-path-row">
                <code dir="ltr">{guide.destination}</code>
                <button type="button" onClick={copyDestination} aria-live="polite">
                  {copyStatus === "copied" ? <Check size={16} /> : <Clipboard size={16} />}
                  {copyStatus === "copied" ? "اتنسخ" : "نسخ المسار"}
                </button>
              </div>
              {copyStatus === "failed" && (
                <p className="skill-install-copy-error" role="alert">
                  المتصفح مقدرش ينسخ المسار. حدده وانسخه يدويًا.
                </p>
              )}
              {guide.command && (
                <div className="skill-install-command">
                  <span>
                    <Terminal size={15} /> أمر التثبيت
                  </span>
                  <code dir="ltr">{guide.command}</code>
                </div>
              )}
            </section>

            <section className="skill-install-steps" aria-labelledby="install-steps-title">
              <h2 id="install-steps-title">الخطوات</h2>
              <ol>
                {guide.steps.map((step, index) => (
                  <li key={`${index}-${step}`}>
                    <span>{index + 1}</span>
                    <p>{step}</p>
                  </li>
                ))}
              </ol>
            </section>

            <div className="skill-install-actions">
              <Link
                className="skill-install-secondary-action"
                href={`/skills/${encodeURIComponent(skillId)}/preview`}
              >
                <ExternalLink size={16} /> معاينة الملفات
              </Link>
              {guide.downloadUrl ? (
                <a className="skill-install-primary-action" href={guide.downloadUrl}>
                  <Download size={16} /> تنزيل الحزمة
                </a>
              ) : (
                <button className="skill-install-primary-action" type="button" disabled>
                  <Download size={16} /> تنزيل الحزمة
                </button>
              )}
            </div>
          </>
        ) : (
          <section className="skill-install-unavailable" aria-live="polite">
            <span className="skill-install-unavailable-icon">
              <Info size={20} />
            </span>
            <div>
              <h2>تعليمات التثبيت لسه مش متاحة</h2>
              <p>
                مسار التثبيت والأوامر لازم ييجوا من تعليمات الـcompiler للمنصة المختارة، ولسه
                البيانات دي مش متوفرة. هنعرضها هنا أول ما BE-09 يوفّرها.
              </p>
            </div>
          </section>
        )}

        <p className="skill-install-id">
          معرّف المهارة: <span dir="ltr">{skillId}</span>
        </p>
      </section>
    </main>
  );
}
