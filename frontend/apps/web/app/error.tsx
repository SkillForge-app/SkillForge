"use client";

import Link from "next/link";

export default function Error({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="route-state-page" dir="rtl">
      <section className="route-state-card" role="alert">
        <span className="route-state-icon route-state-icon-error" aria-hidden="true">
          !
        </span>
        <p className="route-state-eyebrow">حصلت مشكلة</p>
        <h1>الصفحة ماقدرتش تكمل التحميل</h1>
        <p className="route-state-description">
          جرّب تاني. لو المشكلة مستمرة، ارجع للرئيسية وحاول تفتح الصفحة من جديد.
        </p>
        <div className="route-state-actions">
          <button type="button" onClick={reset}>
            حاول مرة تانية
          </button>
          <Link href="/">العودة للرئيسية</Link>
        </div>
      </section>
    </main>
  );
}
