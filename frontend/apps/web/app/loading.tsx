export default function Loading() {
  return (
    <main className="route-loading" aria-busy="true" aria-live="polite">
      <span className="route-loading-mark" aria-hidden="true" />
      <span className="sr-only">جاري تحميل الصفحة</span>
      <div className="route-loading-lines" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </main>
  );
}
