import { Suspense } from "react";
import MatchPage from "./match-page";

type MatchRouteProps = {
  params: Promise<{ requestId: string }>;
};

export default function MatchRoute(props: MatchRouteProps) {
  return (
    <Suspense fallback={<MatchPageFallback />}>
      <ResolvedMatchRoute {...props} />
    </Suspense>
  );
}

async function ResolvedMatchRoute({ params }: MatchRouteProps) {
  const { requestId } = await params;
  return <MatchPage requestId={requestId} />;
}

function MatchPageFallback() {
  return (
    <main className="match-page" dir="rtl">
      <div className="match-loading" role="status" aria-live="polite">
        بنحمّل نتيجة البحث...
      </div>
    </main>
  );
}
