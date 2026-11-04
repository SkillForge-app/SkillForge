import Link from "next/link";
import { ArrowRight, Search } from "lucide-react";

export default function NotFound() {
  return (
    <main className="route-state-page" dir="rtl">
      <section className="route-state-card">
        <span className="route-state-icon" aria-hidden="true">
          <Search size={20} />
        </span>
        <p className="route-state-eyebrow">404</p>
        <h1>الصفحة مش موجودة</h1>
        <p className="route-state-description">
          الرابط ده مش موجود أو الصفحة اتحركت. تقدر ترجع للرئيسية وتكمل من هناك.
        </p>
        <div className="route-state-actions">
          <Link href="/" className="route-state-primary">
            <ArrowRight size={16} /> العودة للرئيسية
          </Link>
          <Link href="/library">استكشف مكتبة المهارات</Link>
        </div>
      </section>
    </main>
  );
}
