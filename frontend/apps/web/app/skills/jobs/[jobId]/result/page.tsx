import { Suspense } from "react";
import { LoaderCircle } from "lucide-react";
import SkillResultView from "./result-view";

type ResultPageProps = {
  params: Promise<{ jobId: string }>;
  searchParams: Promise<{ preview?: string | string[] }>;
};

type PreviewState = "pending" | "failed" | "ready";

function resolvePreviewState(value: string | string[] | undefined): PreviewState {
  const requestedState = Array.isArray(value) ? value[0] : value;
  if (requestedState === "failed" || requestedState === "ready") return requestedState;
  return "pending";
}

export default function ResultPage(props: ResultPageProps) {
  return (
    <Suspense fallback={<ResultPageFallback />}>
      <ResolvedResultPage {...props} />
    </Suspense>
  );
}

async function ResolvedResultPage({ params, searchParams }: ResultPageProps) {
  const [{ jobId }, { preview }] = await Promise.all([params, searchParams]);

  return <SkillResultView jobId={jobId} state={resolvePreviewState(preview)} />;
}

function ResultPageFallback() {
  return (
    <main className="skill-result-page" dir="rtl">
      <div className="skill-result-main" role="status" aria-live="polite">
        <span className="skill-result-status-icon skill-result-status-pending">
          <LoaderCircle size={23} aria-hidden="true" />
        </span>
        <p className="skill-result-description">بنحمّل تفاصيل الطلب...</p>
      </div>
    </main>
  );
}
