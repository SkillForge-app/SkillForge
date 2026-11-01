import { Suspense } from "react";
import InstallPage from "./install-page";

type InstallRouteProps = {
  params: Promise<{ skillId: string }>;
};

export default function InstallRoute(props: InstallRouteProps) {
  return (
    <Suspense fallback={<InstallFallback />}>
      <ResolvedInstallRoute {...props} />
    </Suspense>
  );
}

async function ResolvedInstallRoute({ params }: InstallRouteProps) {
  const { skillId } = await params;
  return <InstallPage skillId={skillId} />;
}

function InstallFallback() {
  return (
    <main className="skill-install-page" dir="rtl">
      <div className="skill-install-loading" role="status" aria-live="polite">
        بنحمّل تعليمات التثبيت...
      </div>
    </main>
  );
}
