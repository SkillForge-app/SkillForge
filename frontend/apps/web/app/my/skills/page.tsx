"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight, CirclePlus, Code2, Search, Sparkles } from "lucide-react";

type Platform = "Claude Code" | "Codex";
type SkillStatus = "جاهزة" | "مسودة";

type Skill = {
  id: string;
  title: string;
  summary: string;
  status: SkillStatus;
  version: string;
  platform: Platform;
  updatedAt: string;
};

const previewSkills: Skill[] = [
  {
    id: "code-review",
    title: "مراجع الشيفرة",
    summary: "راجع التغييرات واكتشف المشكلات المحتملة مع اقتراح تحسينات.",
    status: "جاهزة",
    version: "1.2.0",
    platform: "Claude Code",
    updatedAt: "28 أكتوبر 2026",
  },
  {
    id: "meeting-notes",
    title: "ملخص الاجتماعات",
    summary: "حوّل ملاحظات الاجتماع إلى ملخص واضح وقرارات ومهام متابعة.",
    status: "مسودة",
    version: "مسودة",
    platform: "Claude Code",
    updatedAt: "25 أكتوبر 2026",
  },
  {
    id: "api-documentation",
    title: "موثق واجهات API",
    summary: "أنشئ توثيقًا عمليًا لنقاط النهاية والطلبات والاستجابات.",
    status: "جاهزة",
    version: "1.1.0",
    platform: "Codex",
    updatedAt: "19 أكتوبر 2026",
  },
  {
    id: "requirements-helper",
    title: "مساعد المتطلبات",
    summary: "حوّل وصف الفكرة إلى متطلبات واضحة ومعايير قبول.",
    status: "مسودة",
    version: "مسودة",
    platform: "Codex",
    updatedAt: "10 أكتوبر 2026",
  },
];

export default function MySkillsPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("الكل");
  const [platform, setPlatform] = useState("الكل");

  const filteredSkills = useMemo(() => {
    const searchTerm = query.trim().toLocaleLowerCase("ar");
    return previewSkills.filter((skill) => {
      const matchesQuery =
        !searchTerm ||
        `${skill.title} ${skill.summary}`.toLocaleLowerCase("ar").includes(searchTerm);
      const matchesStatus = status === "الكل" || skill.status === status;
      const matchesPlatform = platform === "الكل" || skill.platform === platform;
      return matchesQuery && matchesStatus && matchesPlatform;
    });
  }, [platform, query, status]);

  return (
    <main className="my-skills-page" dir="rtl">
      <header className="my-skills-topbar">
        <Link className="my-skills-back" href="/">
          <ArrowRight size={17} /> الرئيسية
        </Link>
        <Link className="my-skills-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="my-skills-brand-mark">
            <Sparkles size={17} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
      </header>

      <section className="my-skills-content" aria-labelledby="my-skills-title">
        <div className="my-skills-preview-note" role="status">
          <Sparkles size={16} />
          <span>
            دي معاينة ببيانات محلية. مهاراتك الحقيقية وحالاتها هتظهر بعد ما الـ Backend يوفّر API
            القائمة والحسابات.
          </span>
        </div>

        <div className="my-skills-heading">
          <div>
            <span className="my-skills-eyebrow">
              <Code2 size={15} /> مساحة العمل
            </span>
            <h1 id="my-skills-title">مهاراتي</h1>
            <p>تابع المهارات اللي أنشأتها وافتحها أو كمّل تعديل المسودات.</p>
          </div>
          <Link className="my-skills-create" href="/skills/new">
            <CirclePlus size={17} /> أنشئ مهارة
          </Link>
        </div>

        <div className="my-skills-toolbar">
          <label className="my-skills-search">
            <Search size={17} aria-hidden="true" />
            <span className="sr-only">ابحث في مهاراتي</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="ابحث باسم المهارة..."
              type="search"
            />
          </label>
          <label className="my-skills-filter">
            <span>الحالة</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option>الكل</option>
              <option>جاهزة</option>
              <option>مسودة</option>
            </select>
          </label>
          <label className="my-skills-filter">
            <span>المنصة</span>
            <select value={platform} onChange={(event) => setPlatform(event.target.value)}>
              <option>الكل</option>
              <option>Claude Code</option>
              <option>Codex</option>
            </select>
          </label>
        </div>

        <div className="my-skills-results-heading" aria-live="polite">
          <h2>كل المهارات</h2>
          <span>{filteredSkills.length} مهارات</span>
        </div>

        {filteredSkills.length ? (
          <div className="my-skills-list">
            {filteredSkills.map((skill) => (
              <article className="my-skills-card" key={skill.id}>
                <div className="my-skills-card-icon">
                  <Sparkles size={18} />
                </div>
                <div className="my-skills-card-main">
                  <div className="my-skills-card-title">
                    <h3>{skill.title}</h3>
                    <span
                      className={`my-skills-status ${skill.status === "جاهزة" ? "is-ready" : "is-draft"}`}
                    >
                      {skill.status}
                    </span>
                  </div>
                  <p>{skill.summary}</p>
                  <div className="my-skills-card-meta">
                    <span>الإصدار: {skill.version}</span>
                    <span>{skill.platform}</span>
                    <span>آخر تحديث: {skill.updatedAt}</span>
                  </div>
                </div>
                <div className="my-skills-card-actions">
                  <Link href={`/library/${skill.id}`}>فتح</Link>
                  <button type="button" disabled title="التقييم يحتاج API من الـ Backend">
                    تقييم
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="my-skills-empty" role="status">
            <span>
              <Search size={21} />
            </span>
            <h3>مفيش مهارات مطابقة</h3>
            <p>جرّب تغيّر البحث أو الفلاتر، أو ابدأ بإنشاء مهارة جديدة.</p>
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setStatus("الكل");
                setPlatform("الكل");
              }}
            >
              مسح البحث والفلاتر
            </button>
            <Link href="/library">استكشف مكتبة المهارات</Link>
          </div>
        )}
      </section>
    </main>
  );
}
