import { Suspense } from "react";
import JobProgressPage from "./progress-page";

type JobRouteProps = {
  params: Promise<{ jobId: string }>;
};

export default function JobRoute(props: JobRouteProps) {
  return (
    <Suspense fallback={<ProgressFallback />}>
      <ResolvedJobRoute {...props} />
    </Suspense>
  );
}

async function ResolvedJobRoute({ params }: JobRouteProps) {
  const { jobId } = await params;
  return <JobProgressPage jobId={jobId} />;
}

function ProgressFallback() {
  return (
    <main className="job-progress-page" dir="rtl">
      <div className="job-progress-loading" role="status" aria-live="polite">
        بنحمّل حالة المهمة...
      </div>
    </main>
  );
}
