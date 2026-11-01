"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import {
  ArrowUp,
  BookOpen,
  ChevronLeft,
  FilePlus2,
  FolderOpen,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Sparkles,
  Sun,
  WandSparkles,
  X,
} from "lucide-react";

type Message = { role: "user" | "assistant"; text: string };
type Theme = "light" | "dark";

const themeSubscribers = new Set<() => void>();

function subscribeToTheme(subscriber: () => void) {
  themeSubscribers.add(subscriber);
  return () => {
    themeSubscribers.delete(subscriber);
  };
}

function getThemeSnapshot(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function getServerThemeSnapshot(): Theme {
  return "light";
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.classList.toggle("dark", theme === "dark");
  themeSubscribers.forEach((subscriber) => subscriber());
}

const suggestions = [
  { icon: WandSparkles, title: "إنشاء مهارة جديدة", detail: "ابدأ من فكرتك" },
  { icon: Search, title: "اكتشاف مهارة", detail: "تصفّح المكتبة" },
  { icon: FilePlus2, title: "تحسين مهارة", detail: "طوّر ما لديك" },
];

const recent = [
  "مهارة مراجعة الكود",
  "وكيل دعم العملاء",
  "مساعد كتابة المحتوى",
  "أتمتة تقارير أسبوعية",
];

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const theme = useSyncExternalStore(subscribeToTheme, getThemeSnapshot, getServerThemeSnapshot);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let initialTheme: Theme = window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";

    try {
      const savedTheme = window.localStorage.getItem("skillforge-theme");
      if (savedTheme === "light" || savedTheme === "dark") initialTheme = savedTheme;
    } catch {
      // Keep the system preference when browser storage is unavailable.
    }

    applyTheme(initialTheme);
  }, []);

  function toggleTheme() {
    const nextTheme: Theme = theme === "light" ? "dark" : "light";
    applyTheme(nextTheme);

    try {
      window.localStorage.setItem("skillforge-theme", nextTheme);
    } catch {
      // The selected theme remains active for the current page session.
    }
  }

  function startNewChat() {
    setMessages([]);
    setDraft("");
    setSidebarOpen(false);
    inputRef.current?.focus();
  }

  function sendMessage(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setMessages((current) => [
      ...current,
      { role: "user", text },
      {
        role: "assistant",
        text: "جميل، خلّينا نحوّل فكرتك إلى مهارة واضحة وسهلة الاستخدام. ما النتيجة التي تريد أن يحصل عليها المستخدم في نهاية هذه المهارة؟",
      },
    ]);
    setDraft("");
  }

  return (
    <main className="app-shell" dir="rtl">
      <aside
        id="app-sidebar"
        className={`sidebar ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${sidebarOpen ? "sidebar-mobile-open" : ""}`}
        aria-label="القائمة الرئيسية"
      >
        <div className="sidebar-top">
          <a
            className="brand"
            href="#home"
            onClick={startNewChat}
            aria-label="SkillForge — الرئيسية"
          >
            <span className="brand-mark">
              <Sparkles size={18} strokeWidth={1.8} />
            </span>
            <span className="brand-name">
              skillforge<span className="brand-period">.</span>
            </span>
          </a>
          <button
            className="icon-button sidebar-toggle"
            onClick={() => setSidebarCollapsed((value) => !value)}
            aria-label={sidebarCollapsed ? "توسيع القائمة" : "طي القائمة"}
            aria-expanded={!sidebarCollapsed}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
          <button
            className="icon-button mobile-close"
            onClick={() => setSidebarOpen(false)}
            aria-label="إغلاق القائمة"
          >
            <X size={19} />
          </button>
        </div>

        <Link className="new-skill-button" href="/skills/new">
          <Plus size={17} strokeWidth={1.8} />
          <span>إنشاء مهارة</span>
        </Link>

        <nav className="primary-nav" id="primary-navigation" aria-label="التنقل">
          <Link className="nav-item" href="/skills/new">
            <WandSparkles size={17} />
            <span>إنشاء مهارة</span>
          </Link>
          <a className="nav-item" href="/my/skills">
            <FolderOpen size={17} />
            <span>مهاراتي</span>
          </a>
          <a className="nav-item" href="/library">
            <BookOpen size={17} />
            <span>مكتبة المهارات</span>
          </a>
        </nav>

        <div className="history-section">
          <div className="section-label">
            <span>أحدث المهارات</span>
          </div>
          {recent.map((item, index) => (
            <div className={`history-item ${index === 0 ? "history-current" : ""}`} key={item}>
              <span className="history-dot" />
              <span>{item}</span>
            </div>
          ))}
        </div>

        <div className="sidebar-bottom">
          <Link className="profile-button" href="/auth/sign-in">
            <span className="avatar">د</span>
            <span className="profile-copy">
              <strong>تسجيل الدخول</strong>
              <small>حسابك الشخصي</small>
            </span>
          </Link>
        </div>
      </aside>

      {sidebarOpen && (
        <button
          className="mobile-scrim"
          onClick={() => setSidebarOpen(false)}
          aria-label="إغلاق القائمة"
        />
      )}

      <section className="workspace" id="home">
        <header className="topbar">
          <div className="topbar-start">
            <button
              className="icon-button mobile-menu"
              onClick={() => setSidebarOpen(true)}
              aria-label="فتح القائمة"
              aria-controls="app-sidebar"
              aria-expanded={sidebarOpen}
            >
              <Menu size={20} />
            </button>
            <span className="workspace-label">مساحة المهارات</span>
          </div>
          <div className="topbar-end">
            <button
              className="icon-button theme-toggle"
              onClick={toggleTheme}
              aria-label={theme === "light" ? "تفعيل الوضع الداكن" : "تفعيل الوضع الفاتح"}
              aria-pressed={theme === "dark"}
              title={theme === "light" ? "الوضع الداكن" : "الوضع الفاتح"}
            >
              {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
            </button>
          </div>
        </header>

        {messages.length === 0 ? (
          <div className="welcome-view">
            <div className="welcome-content">
              <div className="welcome-symbol">
                <Sparkles size={23} strokeWidth={1.5} />
              </div>
              <h1>
                أهلًا محمد،
                <br />
                <span>ما الذي تريد أن تصنعه؟</span>
              </h1>
              <p className="welcome-description">حوّل أفكارك إلى مهارات ذكية، خطوة بخطوة.</p>

              <form className="composer" onSubmit={sendMessage}>
                <label className="sr-only" htmlFor="prompt">
                  اكتب فكرتك
                </label>
                <textarea
                  id="prompt"
                  ref={inputRef}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      sendMessage();
                    }
                  }}
                  placeholder="صف المهارة التي تريد إنشاءها..."
                  rows={2}
                />
                <div className="composer-footer">
                  <div className="composer-tools">
                    <button type="button" className="composer-tool" aria-label="إضافة سياق">
                      <Plus size={17} />
                    </button>
                    <span className="composer-hint">اكتب فكرتك بطريقتك</span>
                  </div>
                  <button
                    className={`send-button ${draft.trim() ? "send-ready" : ""}`}
                    type="submit"
                    disabled={!draft.trim()}
                    aria-label="إرسال الرسالة"
                  >
                    <ArrowUp size={19} />
                  </button>
                </div>
              </form>
              <div className="suggestion-grid">
                {suggestions.map(({ icon: Icon, title, detail }) => (
                  <button
                    className="suggestion"
                    key={title}
                    onClick={() => {
                      setDraft(
                        title === "إنشاء مهارة جديدة"
                          ? "أريد إنشاء مهارة جديدة تساعدني على "
                          : title === "اكتشاف مهارة"
                            ? "أبحث عن مهارة تساعدني على "
                            : "أريد تحسين مهارتي في ",
                      );
                      inputRef.current?.focus();
                    }}
                  >
                    <span className="suggestion-icon">
                      <Icon size={17} strokeWidth={1.7} />
                    </span>
                    <span className="suggestion-copy">
                      <strong>{title}</strong>
                      <small>{detail}</small>
                    </span>
                    <ChevronLeft className="suggestion-arrow" size={15} />
                  </button>
                ))}
              </div>
              <p className="privacy-note">
                <span className="privacy-dot" /> مساحتك خاصة. مهاراتك تبقى ملكك.
              </p>
            </div>
            <div className="welcome-footer">
              <span>SkillForge يساعدك على بناء مهاراتك الذكية</span>
              <button aria-label="المزيد من المعلومات">حول SkillForge</button>
            </div>
          </div>
        ) : (
          <div className="conversation-view">
            <div className="conversation-messages" aria-live="polite">
              {messages.map((message, index) => (
                <article
                  className={`message message-${message.role}`}
                  key={`${index}-${message.role}`}
                >
                  {message.role === "assistant" && (
                    <span className="message-mark">
                      <Sparkles size={15} />
                    </span>
                  )}
                  <p>{message.text}</p>
                </article>
              ))}
            </div>
            <form className="composer conversation-composer" onSubmit={sendMessage}>
              <label className="sr-only" htmlFor="reply">
                اكتب ردك
              </label>
              <textarea
                id="reply"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    sendMessage();
                  }
                }}
                placeholder="اكتب ردك..."
                rows={2}
              />
              <div className="composer-footer">
                <div className="composer-tools">
                  <button type="button" className="composer-tool" aria-label="إضافة سياق">
                    <Plus size={17} />
                  </button>
                </div>
                <button
                  className={`send-button ${draft.trim() ? "send-ready" : ""}`}
                  type="submit"
                  disabled={!draft.trim()}
                  aria-label="إرسال الرسالة"
                >
                  <ArrowUp size={19} />
                </button>
              </div>
            </form>
            <p className="conversation-note">قد تحتاج المهارات المنشأة إلى مراجعة قبل استخدامها.</p>
          </div>
        )}
      </section>
    </main>
  );
}
