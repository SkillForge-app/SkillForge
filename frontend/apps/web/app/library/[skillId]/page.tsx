import { notFound } from "next/navigation";
import SkillDetailPage from "./skill-detail-page";

const previewSkills = [
  {
    id: "code-review",
    title: "مراجع الشيفرة",
    category: "برمجة",
    summary: "راجع التغييرات واكتشف المشكلات المحتملة مع توضيح أثرها واقتراح تحسينات.",
    platforms: ["Claude Code", "Codex"],
    version: "1.2.0",
    sources: 4,
    updatedAt: "28 أكتوبر 2026",
  },
  {
    id: "meeting-notes",
    title: "ملخص الاجتماعات",
    category: "إنتاجية",
    summary: "حوّل ملاحظات الاجتماع إلى ملخص واضح وقرارات ومهام متابعة.",
    platforms: ["Claude Code"],
    version: "1.0.3",
    sources: 3,
    updatedAt: "25 أكتوبر 2026",
  },
  {
    id: "content-editor",
    title: "محرر المحتوى",
    category: "كتابة",
    summary: "حسّن النصوص مع الحفاظ على نبرة الكاتب والجمهور المستهدف.",
    platforms: ["Codex"],
    version: "2.1.0",
    sources: 5,
    updatedAt: "22 أكتوبر 2026",
  },
  {
    id: "api-documentation",
    title: "موثق واجهات API",
    category: "برمجة",
    summary: "أنشئ توثيقًا عمليًا لنقاط النهاية والطلبات والاستجابات والأخطاء.",
    platforms: ["Claude Code", "Codex"],
    version: "1.1.0",
    sources: 2,
    updatedAt: "19 أكتوبر 2026",
  },
  {
    id: "research-brief",
    title: "موجز البحث",
    category: "بحث",
    summary: "نظّم المصادر والنتائج في موجز مختصر يوضح ما نعرفه وما يحتاج تحققًا.",
    platforms: ["Claude Code"],
    version: "1.0.1",
    sources: 6,
    updatedAt: "15 أكتوبر 2026",
  },
  {
    id: "requirements-helper",
    title: "مساعد المتطلبات",
    category: "إنتاجية",
    summary: "حوّل وصف الفكرة إلى متطلبات واضحة وأسئلة مفتوحة ومعايير قبول.",
    platforms: ["Codex"],
    version: "1.0.0",
    sources: 3,
    updatedAt: "10 أكتوبر 2026",
  },
  {
    id: "test-case-writer",
    title: "كاتب حالات الاختبار",
    category: "برمجة",
    summary: "استخرج سيناريوهات الاختبار من المتطلبات والحالات الحدّية.",
    platforms: ["Claude Code", "Codex"],
    version: "1.3.0",
    sources: 4,
    updatedAt: "6 أكتوبر 2026",
  },
  {
    id: "weekly-report",
    title: "معدّ التقرير الأسبوعي",
    category: "إنتاجية",
    summary: "اجمع تحديثات الأسبوع في تقرير منظم للإنجازات والعوائق والخطوات التالية.",
    platforms: ["Claude Code"],
    version: "1.0.2",
    sources: 2,
    updatedAt: "1 أكتوبر 2026",
  },
];

export function generateStaticParams() {
  return previewSkills.map(({ id }) => ({ skillId: id }));
}

export default async function Page({ params }: { params: Promise<{ skillId: string }> }) {
  const { skillId } = await params;
  const skill = previewSkills.find((item) => item.id === skillId);

  if (!skill) notFound();

  return <SkillDetailPage skill={skill} />;
}
