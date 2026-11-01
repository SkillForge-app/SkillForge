"use client";

import Link from "next/link";
import { useState } from "react";
import type { FormEvent } from "react";
import { GitBranch, LockKeyhole, Mail, Sparkles } from "lucide-react";

type AuthMode = "sign-in" | "sign-up";

export default function AuthForm({ mode }: { mode: AuthMode }) {
  const [showPassword, setShowPassword] = useState(false);
  const [notice, setNotice] = useState("");
  const isSignUp = mode === "sign-up";

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("التحقق من الحقول اكتمل. إرسال بيانات الحساب هيتفعّل بعد ربط خدمة BE-04.");
  }

  return (
    <div className="auth-page" dir="rtl">
      <header className="auth-topbar">
        <Link className="auth-brand" href="/" aria-label="SkillForge — الرئيسية">
          <span className="auth-brand-mark">
            <Sparkles size={18} strokeWidth={1.8} />
          </span>
          <span>
            skillforge<span className="brand-period">.</span>
          </span>
        </Link>
        <Link className="auth-home-link" href="/">
          العودة للرئيسية
        </Link>
      </header>

      <main className="auth-layout">
        <section className="auth-panel" aria-labelledby="auth-title">
          <div className="auth-mobile-symbol" aria-hidden="true">
            <Sparkles size={20} />
          </div>
          <span className="auth-eyebrow">مساحة عملك في SkillForge</span>
          <h1 id="auth-title">{isSignUp ? "أنشئ حسابك" : "أهلًا بعودتك"}</h1>
          <p className="auth-intro">
            {isSignUp
              ? "أنشئ حسابًا عشان تحفظ مهاراتك وتتابع شغلك."
              : "سجّل دخولك عشان تكمل بناء مهاراتك."}
          </p>

          <div className="auth-oauth-list" aria-label="خيارات تسجيل الدخول الاجتماعي">
            <button className="auth-oauth-button" type="button" disabled>
              <GitBranch size={18} />
              <span>{isSignUp ? "المتابعة" : "تسجيل الدخول"} باستخدام GitHub</span>
            </button>
            <button className="auth-oauth-button" type="button" disabled>
              <span className="auth-google-mark" aria-hidden="true">
                G
              </span>
              <span>{isSignUp ? "المتابعة" : "تسجيل الدخول"} باستخدام Google</span>
            </button>
          </div>

          <p className="auth-provider-note">
            تسجيل الدخول عبر GitHub وGoogle هيتفعّل بعد ربط خدمة الحسابات.
          </p>

          <div className="auth-divider">
            <span>أو باستخدام البريد الإلكتروني</span>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="auth-label" htmlFor="auth-email">
              البريد الإلكتروني
            </label>
            <span className="auth-input-wrap">
              <Mail size={17} aria-hidden="true" />
              <input
                id="auth-email"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="name@example.com"
                required
              />
            </span>

            <div className="auth-password-heading">
              <label className="auth-label" htmlFor="auth-password">
                كلمة المرور
              </label>
              {isSignUp && <span>استخدم كلمة مرور يسهل عليك تذكرها</span>}
            </div>
            <span className="auth-input-wrap">
              <LockKeyhole size={17} aria-hidden="true" />
              <input
                id="auth-password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete={isSignUp ? "new-password" : "current-password"}
                placeholder="••••••••"
                required
              />
              <button
                className="auth-password-toggle"
                type="button"
                aria-label={showPassword ? "إخفاء كلمة المرور" : "إظهار كلمة المرور"}
                aria-pressed={showPassword}
                onClick={() => setShowPassword((value) => !value)}
              >
                {showPassword ? "إخفاء" : "إظهار"}
              </button>
            </span>

            <button className="auth-submit" type="submit">
              {isSignUp ? "إنشاء حساب" : "تسجيل الدخول"}
            </button>
          </form>

          {notice && (
            <p className="auth-status" role="status" aria-live="polite">
              {notice}
            </p>
          )}

          <p className="auth-switch">
            {isSignUp ? "عندك حساب بالفعل؟" : "لسه ماعندكش حساب؟"}{" "}
            <Link href={isSignUp ? "/auth/sign-in" : "/auth/sign-up"}>
              {isSignUp ? "سجّل دخولك" : "أنشئ حسابًا"}
            </Link>
          </p>
          <p className="auth-terms">بالمتابعة، أنت توافق على شروط الاستخدام وسياسة الخصوصية.</p>
        </section>

        <aside className="auth-aside">
          <div className="auth-aside-symbol">
            <Sparkles size={24} strokeWidth={1.7} />
          </div>
          <p className="auth-aside-kicker">SkillForge</p>
          <h2>خبرتك تتحول لمهارات تساعدك كل يوم.</h2>
          <p>ابنِ مهارات قابلة لإعادة الاستخدام، وراجعها قبل ما تستخدمها مع أدواتك المفضلة.</p>
          <div className="auth-aside-rule" />
          <span>مساحة واحدة لمهارات Claude Code وCodex.</span>
        </aside>
      </main>

      <footer className="auth-footer">
        <span>SkillForge</span>
        <span>مهارات واضحة. استخدام أسهل.</span>
      </footer>
    </div>
  );
}
