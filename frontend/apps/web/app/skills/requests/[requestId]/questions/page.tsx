import { Suspense } from "react";
import QuestionsWizard from "./questions-wizard";

type QuestionsPageProps = {
  params: Promise<{ requestId: string }>;
};

export default function QuestionsPage(props: QuestionsPageProps) {
  return (
    <Suspense fallback={<QuestionsPageFallback />}>
      <ResolvedQuestionsPage {...props} />
    </Suspense>
  );
}

async function ResolvedQuestionsPage({ params }: QuestionsPageProps) {
  const { requestId } = await params;
  return <QuestionsWizard requestId={requestId} />;
}

function QuestionsPageFallback() {
  return (
    <main className="questions-page" dir="rtl">
      <div className="questions-loading" role="status" aria-live="polite">
        بنحمّل الأسئلة...
      </div>
    </main>
  );
}
