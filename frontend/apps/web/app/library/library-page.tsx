"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight, BookOpen, ChevronLeft, ChevronRight, Search, Sparkles } from "lucide-react";

type Platform = "Claude Code" | "Codex";
type Skill = {
  id: string;
  title: string;
  category: string;
  summary: string;
  platforms: Platform[];
  version: string;
  sources: number;
  updatedAt: string;
};

// Temporary preview data. Replace this list with the BE-11 registry response.
const previewSkills: Skill[] = [
  {
    id: "code-review",
    title: "مراجع الشيفرة",
    category: "برمجة",
    summary: "راجع التغييرات واكتشف المشكلات المحتملة مع توضيح أثرها واقتراح تحسينات.",
    platforms: ["Claude Code", "Codex"],
    version: "1.2.0",
    sources: 4,
    updatedAt: "2026-10-28",
  },
  {
    id: "meeting-notes",
    title: "ملخص الاجتماعات",
    category: "إنتاجية",
    summary: "حوّل ملاحظات الاجتماع إلى ملخص واضح وقرارات ومهام متابعة.",
    platforms: ["Claude Code"],
    version: "1.0.3",
    sources: 3,
    updatedAt: "2026-10-25",
  },
  {
    id: "content-editor",
    title: "محرر المحتوى",
    category: "كتابة",
    summary: "حسّن النصوص مع الحفاظ على نبرة الكاتب والجمهور المستهدف.",
    platforms: ["Codex"],
    version: "2.1.0",
    sources: 5,
    updatedAt: "2026-10-22",
  },
  {
    id: "api-documentation",
    title: "موثق واجهات API",
    category: "برمجة",
    summary: "أنشئ توثيقًا عمليًا لنقاط النهاية والطلبات والاستجابات والأخطاء.",
    platforms: ["Claude Code", "Codex"],
    version: "1.1.0",
    sources: 2,
    updatedAt: "2026-10-19",
  },
  {
    id: "research-brief",
    title: "موجز البحث",
    category: "بحث",
    summary: "نظّم المصادر والنتائج في موجز مختصر يوضح ما نعرفه وما يحتاج تحققًا.",
    platforms: ["Claude Code"],
    version: "1.0.1",
    sources: 6,
    updatedAt: "2026-10-15",
  },
  {
    id: "requirements-helper",
    title: "مساعد المتطلبات",
    category: "إنتاجية",
    summary: "حوّل وصف الفكرة إلى متطلبات واضحة وأسئلة مفتوحة ومعايير قبول.",
    platforms: ["Codex"],
    version: "1.0.0",
    sources: 3,
    updatedAt: "2026-10-10",
  },
  {
    id: "test-case-writer",
    title: "كاتب حالات الاختبار",
    category: "برمجة",
    summary: "استخرج سيناريوهات الاختبار من المتطلبات والحالات الحدّية.",
    platforms: ["Claude Code", "Codex"],
    version: "1.3.0",
    sources: 4,
    updatedAt: "2026-10-06",
  },
  {
    id: "weekly-report",
    title: "معدّ التقرير الأسبوعي",
    category: "إنتاجية",
    summary: "اجمع تحديثات الأسبوع في تقرير منظم للإنجازات والعوائق والخطوات التالية.",
    platforms: ["Claude Code"],
    version: "1.0.2",
    sources: 2,
    updatedAt: "2026-10-01",
  },
];

const categories = ["الكل", ...new Set(previewSkills.map((skill) => skill.category))];
const platforms: Array<"الكل" | Platform> = ["الكل", "Claude Code", "Codex"];

export default function LibraryPage() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("الكل");
  const [platform, setPlatform] = useState<(typeof platforms)[number]>("الكل");
  const [sort, setSort] = useState<"relevant" | "newest">("relevant");
  const [page, setPage] = useState(1);

  const filteredSkills = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("ar");
    const matches = previewSkills.filter((skill) => {
      const matchesQuery =
        !normalizedQuery ||
        `${skill.title} ${skill.summary} ${skill.category}`
          .toLocaleLowerCase("ar")
          .includes(normalizedQuery);
      const matchesCategory = category === "الكل" || skill.category === category;
      const matchesPlatform = platform === "الكل" || skill.platforms.includes(platform);
      return matchesQuery && matchesCategory && matchesPlatform;
    });

    if (sort === "newest") {
      return [...matches].sort((first, second) => second.updatedAt.localeCompare(first.updatedAt));
    }
    return matches;
  }, [category, platform, query, sort]);
  const pageSize = 6;
  const pageCount = Math.ceil(filteredSkills.length / pageSize);
  const visibleSkills = filteredSkills.slice((page - 1) * pageSize, page * pageSize);

  return (
    <main className="skill-library-page" dir="rtl">
      <header className="skill-library-topbar">
        <Link className="skill-library-back" href="/">
          <ArrowRight size={17} /> الرجوع للرئيسية
        </Link>
        <Link className="skill-library-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="skill-library-brand-mark">
            <Sparkles size={17} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
      </header>

      <section className="skill-library-content" aria-labelledby="library-title">
        <div className="skill-library-heading">
          <span className="skill-library-eyebrow">
            <BookOpen size={15} /> مكتبة SkillForge
          </span>
          <h1 id="library-title">اكتشف مهارات تناسب شغلك</h1>
          <p>ابحث في المهارات المنشورة واعرف المنصات والمصادر والإصدار قبل ما تفتح التفاصيل.</p>
        </div>

        <div className="skill-library-preview-note" role="status">
          <Sparkles size={16} />
          <span>
            المعروض هنا بيانات تجريبية. هنربط البحث بكتالوج المهارات لما BE-11 يوفّر العقد.
          </span>
        </div>

        <div className="skill-library-toolbar">
          <label className="skill-library-search">
            <Search size={18} aria-hidden="true" />
            <span className="sr-only">ابحث عن مهارة</span>
            <input
              type="search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(1);
              }}
              placeholder="ابحث بالاسم أو الوصف..."
            />
          </label>

          <label className="skill-library-filter">
            <span>التصنيف</span>
            <select
              value={category}
              onChange={(event) => {
                setCategory(event.target.value);
                setPage(1);
              }}
            >
              {categories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <label className="skill-library-filter">
            <span>المنصة</span>
            <select
              value={platform}
              onChange={(event) => {
                setPlatform(event.target.value as (typeof platforms)[number]);
                setPage(1);
              }}
            >
              {platforms.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <label className="skill-library-filter">
            <span>الترتيب</span>
            <select
              value={sort}
              onChange={(event) => {
                setSort(event.target.value as typeof sort);
                setPage(1);
              }}
            >
              <option value="relevant">الأكثر صلة</option>
              <option value="newest">الأحدث</option>
            </select>
          </label>
        </div>

        <div className="skill-library-results-heading" aria-live="polite">
          <h2>المهارات</h2>
          <span>{filteredSkills.length} مهارات</span>
        </div>

        {filteredSkills.length ? (
          <div className="skill-library-grid">
            {visibleSkills.map((skill) => (
              <article className="skill-library-card" key={skill.id}>
                <div className="skill-library-card-topline">
                  <span className="skill-library-category">{skill.category}</span>
                  <span className="skill-library-version">v{skill.version}</span>
                </div>
                <h3>{skill.title}</h3>
                <p className="skill-library-summary">{skill.summary}</p>
                <div className="skill-library-platforms" aria-label="المنصات المتاحة">
                  {skill.platforms.map((item) => (
                    <span key={item}>{item}</span>
                  ))}
                </div>
                <div className="skill-library-card-footer">
                  <span>{skill.sources} مصادر</span>
                  <Link href={`/library/${skill.id}`}>التفاصيل</Link>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="skill-library-empty" role="status">
            <Search size={22} />
            <h3>مفيش مهارات مطابقة</h3>
            <p>جرّب كلمة بحث أو اختيارات مختلفة.</p>
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setCategory("الكل");
                setPlatform("الكل");
                setPage(1);
              }}
            >
              مسح البحث والفلاتر
            </button>
          </div>
        )}
        {pageCount > 1 && (
          <nav className="skill-library-pagination" aria-label="صفحات مكتبة المهارات">
            <span>
              عرض {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, filteredSkills.length)} من{" "}
              {filteredSkills.length}
            </span>
            <div>
              <button
                type="button"
                aria-label="الصفحة السابقة"
                disabled={page === 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                <ChevronRight size={16} />
              </button>
              <span aria-current="page">
                {page} / {pageCount}
              </span>
              <button
                type="button"
                aria-label="الصفحة التالية"
                disabled={page === pageCount}
                onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
              >
                <ChevronLeft size={16} />
              </button>
            </div>
          </nav>
        )}
      </section>
    </main>
  );
}
