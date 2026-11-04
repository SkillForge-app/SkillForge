"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Download,
  ExternalLink,
  FileText,
  History,
  MessageSquare,
  Sparkles,
  Star,
} from "lucide-react";

type Skill = {
  id: string;
  title: string;
  category: string;
  summary: string;
  platforms: string[];
  version: string;
  sources: number;
  updatedAt: string;
};

type Tab = "overview" | "versions" | "sources" | "files" | "ratings";

const tabs: Array<{ id: Tab; label: string; icon: typeof BookOpen }> = [
  { id: "overview", label: "نظرة عامة", icon: BookOpen },
  { id: "versions", label: "الإصدارات", icon: History },
  { id: "sources", label: "المصادر", icon: ExternalLink },
  { id: "files", label: "الملفات", icon: FileText },
  { id: "ratings", label: "التقييمات", icon: Star },
];

export default function SkillDetailPage({ skill }: { skill: Skill }) {
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  return (
    <main className="skill-detail-page" dir="rtl">
      <header className="skill-detail-topbar">
        <Link className="skill-detail-back" href="/library">
          <ArrowRight size={17} /> العودة للمكتبة
        </Link>
        <Link className="skill-detail-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="skill-detail-brand-mark">
            <Sparkles size={17} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
      </header>

      <section className="skill-detail-content" aria-labelledby="skill-detail-title">
        <div className="skill-detail-preview-note" role="status">
          <Sparkles size={16} />
          <span>
            دي معاينة ببيانات محلية؛ تفاصيل الإصدارات والمصادر والملفات والتقييمات هتظهر لما يتوفر
            عقد مكتبة المهارات من الـ Backend.
          </span>
        </div>

        <div className="skill-detail-hero">
          <div className="skill-detail-copy">
            <div className="skill-detail-badges">
              <span className="skill-detail-category">{skill.category}</span>
              <span className="skill-detail-version">الإصدار الحالي · v{skill.version}</span>
            </div>
            <h1 id="skill-detail-title">{skill.title}</h1>
            <p>{skill.summary}</p>
            <div className="skill-detail-platforms" aria-label="المنصات المتاحة">
              {skill.platforms.map((platform) => (
                <span key={platform}>{platform}</span>
              ))}
            </div>
            <div className="skill-detail-meta">
              <span>
                <BookOpen size={15} /> {skill.sources} مصادر مذكورة
              </span>
              <span>آخر تحديث: {skill.updatedAt}</span>
            </div>
          </div>
          <div className="skill-detail-actions">
            <button type="button" disabled title="يتطلب ربط مكتبة المهارات بالـ Backend">
              استخدم المهارة
            </button>
            <button type="button" disabled title="يتطلب ربط مكتبة المهارات بالـ Backend">
              تخصيص
            </button>
            <button
              className="skill-detail-download"
              type="button"
              disabled
              title="يتطلب API تنزيل الحزمة"
            >
              <Download size={16} /> تنزيل الحزمة
            </button>
            <span>الإجراءات هتتفعّل بعد ربط الـ APIs.</span>
          </div>
        </div>

        <nav className="skill-detail-tabs" aria-label="تفاصيل المهارة" role="tablist">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              id={`skill-tab-${id}`}
              type="button"
              role="tab"
              aria-selected={activeTab === id}
              aria-controls="skill-detail-panel"
              className={activeTab === id ? "is-active" : ""}
              onClick={() => setActiveTab(id)}
            >
              <Icon size={16} /> {label}
              {id === "sources" && <span className="skill-detail-tab-count">{skill.sources}</span>}
            </button>
          ))}
        </nav>

        <section
          className="skill-detail-panel"
          id="skill-detail-panel"
          role="tabpanel"
          aria-labelledby={`skill-tab-${activeTab}`}
          tabIndex={0}
        >
          {activeTab === "overview" && (
            <div className="skill-detail-overview">
              <div>
                <span className="skill-detail-eyebrow">عن المهارة</span>
                <h2>إيه اللي بتعمله المهارة دي؟</h2>
                <p>{skill.summary}</p>
              </div>
              <div className="skill-detail-facts">
                <div>
                  <span>التصنيف</span>
                  <strong>{skill.category}</strong>
                </div>
                <div>
                  <span>الإصدار الحالي</span>
                  <strong>v{skill.version}</strong>
                </div>
                <div>
                  <span>المنصات</span>
                  <strong>{skill.platforms.join("، ")}</strong>
                </div>
                <div>
                  <span>عدد المصادر</span>
                  <strong>{skill.sources}</strong>
                </div>
              </div>
            </div>
          )}
          {activeTab === "versions" && (
            <EmptyDetail
              icon={History}
              title="سجل الإصدارات غير متاح"
              description={`المتاح في بيانات المعاينة هو الإصدار الحالي v${skill.version} فقط. سجل الإصدارات محتاج endpoint من الـ Backend.`}
            />
          )}
          {activeTab === "sources" && (
            <EmptyDetail
              icon={ExternalLink}
              title="تفاصيل المصادر غير متاحة"
              description={`المعاينة بتشير إلى ${skill.sources} مصادر، لكن بياناتها وروابطها الأصلية مش موجودة في الـ API الحالي.`}
            />
          )}
          {activeTab === "files" && (
            <EmptyDetail
              icon={FileText}
              title="ملفات المهارة غير متاحة"
              description="قائمة الملفات ومحتواها هتظهر هنا لما يتوفر عقد تفاصيل المهارة من الـ Backend."
            />
          )}
          {activeTab === "ratings" && (
            <EmptyDetail
              icon={MessageSquare}
              title="مفيش تقييمات في المعاينة"
              description="بيانات التقييمات وعددها محتاجة endpoint من الـ Backend."
            />
          )}
        </section>
      </section>
    </main>
  );
}

function EmptyDetail({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof BookOpen;
  title: string;
  description: string;
}) {
  return (
    <div className="skill-detail-empty" role="status">
      <span>
        <Icon size={21} />
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  );
}
