"use client";

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="ar" dir="rtl">
      <body>
        <main
          style={{
            minHeight: "100vh",
            display: "grid",
            placeItems: "center",
            padding: 24,
            background: "#faf9f6",
            color: "#252521",
            fontFamily: "Arial, sans-serif",
          }}
        >
          <section
            role="alert"
            style={{
              maxWidth: 480,
              padding: 32,
              border: "1px solid #e8e6df",
              borderRadius: 16,
              background: "#fff",
              textAlign: "center",
            }}
          >
            <span
              aria-hidden="true"
              style={{
                display: "grid",
                width: 44,
                height: 44,
                margin: "0 auto 18px",
                placeItems: "center",
                borderRadius: 14,
                background: "#f8e9e5",
                color: "#9c463d",
                fontSize: 22,
                fontWeight: 700,
              }}
            >
              !
            </span>
            <h1 style={{ margin: "0 0 10px", fontSize: 22 }}>حصلت مشكلة في تحميل SkillForge</h1>
            <p style={{ margin: "0 0 22px", color: "#77756c", lineHeight: 1.8 }}>
              حاول تحميل التطبيق مرة تانية. لو المشكلة مستمرة، ارجع بعد شوية.
            </p>
            <button
              type="button"
              onClick={reset}
              style={{
                minHeight: 42,
                padding: "0 18px",
                border: 0,
                borderRadius: 9,
                background: "#575a45",
                color: "white",
                font: "inherit",
                cursor: "pointer",
              }}
            >
              إعادة المحاولة
            </button>
          </section>
        </main>
      </body>
    </html>
  );
}
