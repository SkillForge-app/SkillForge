import { Suspense } from "react";
import SkillReviewPage from "./review-page";

type ReviewRouteProps = {
  params: Promise<{ skillId: string }>;
};

export default function ReviewRoute(props: ReviewRouteProps) {
  return (
    <Suspense fallback={<ReviewFallback />}>
      <ResolvedReviewRoute {...props} />
    </Suspense>
  );
}

async function ResolvedReviewRoute({ params }: ReviewRouteProps) {
  const { skillId } = await params;
  return <SkillReviewPage skillId={skillId} />;
}

function ReviewFallback() {
  return (
    <main className="skill-review-page" dir="rtl">
      <div className="skill-review-loading" role="status" aria-live="polite">
        بنحمّل بيانات المهارة...
      </div>
    </main>
  );
}
