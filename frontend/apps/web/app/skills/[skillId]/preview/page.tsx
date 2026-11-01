import { Suspense } from "react";
import SkillPackagePreview from "./preview-page";

type PreviewRouteProps = {
  params: Promise<{ skillId: string }>;
};

export default function PreviewRoute(props: PreviewRouteProps) {
  return (
    <Suspense fallback={<PreviewFallback />}>
      <ResolvedPreviewRoute {...props} />
    </Suspense>
  );
}

async function ResolvedPreviewRoute({ params }: PreviewRouteProps) {
  const { skillId } = await params;
  return <SkillPackagePreview skillId={skillId} />;
}

function PreviewFallback() {
  return (
    <main className="package-preview-page" dir="rtl">
      <div className="package-preview-loading" role="status" aria-live="polite">
        بنحمّل ملفات المهارة...
      </div>
    </main>
  );
}
