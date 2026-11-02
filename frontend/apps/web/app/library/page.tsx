import type { Metadata } from "next";
import LibraryPage from "./library-page";

export const metadata: Metadata = {
  title: "مكتبة المهارات | SkillForge",
  description: "اكتشف المهارات المنشورة في مكتبة SkillForge.",
};

export default function Page() {
  return <LibraryPage />;
}
