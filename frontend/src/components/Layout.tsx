// Page frame: header with navigation and the language switch (NFR-26), content below.
// Works from 320 px wide (NFR-21): on narrow screens the menu folds into a button.
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { setLanguage } from "../i18n";

function LanguageSwitch() {
  const { i18n } = useTranslation();
  return (
    <div className="flex overflow-hidden rounded-md border border-slate-300 text-xs font-medium" role="group">
      {(["ru", "en"] as const).map((lang) => (
        <button
          key={lang}
          type="button"
          onClick={() => setLanguage(lang)}
          aria-pressed={i18n.language === lang}
          className={`px-2 py-1 uppercase ${i18n.language === lang ? "bg-brand text-white" : "bg-white text-slate-700"}`}
        >
          {lang}
        </button>
      ))}
    </div>
  );
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded-md px-3 py-2 text-sm ${isActive ? "bg-brand-light text-brand-dark" : "text-slate-700 hover:bg-slate-100"}`;

export function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, hasRole, signOut } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const close = () => setOpen(false);
  const logout = async () => {
    close();
    await signOut();
    navigate("/");
  };

  const links = user ? (
    <>
      <NavLink to="/profile" className={navClass} onClick={close}>
        {t("nav.profile")}
      </NavLink>
      <NavLink to="/billing" className={navClass} onClick={close}>
        {t("nav.billing")}
      </NavLink>
      {!hasRole("producer") && (
        <NavLink to="/producer/connect" className={navClass} onClick={close}>
          {t("nav.becomeProducer")}
        </NavLink>
      )}
      <button type="button" onClick={logout} className="block w-full rounded-md px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100">
        {t("nav.logout")}
      </button>
    </>
  ) : (
    <>
      <NavLink to="/login" className={navClass} onClick={close}>
        {t("nav.login")}
      </NavLink>
      <NavLink to="/register" className={navClass} onClick={close}>
        {t("nav.register")}
      </NavLink>
    </>
  );

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3">
          <Link to="/" className="text-lg font-bold text-brand" onClick={close}>
            OhBeat
          </Link>
          <NavLink to="/" end className={navClass}>
            {t("nav.catalog")}
          </NavLink>
          <div className="ml-auto flex items-center gap-2">
            <LanguageSwitch />
            {user && <span className="hidden max-w-[10rem] truncate text-sm text-slate-600 sm:inline">{user.display_name}</span>}
            <button
              type="button"
              className="btn-secondary px-3 md:hidden"
              aria-expanded={open}
              aria-label={t("nav.menu")}
              onClick={() => setOpen((v) => !v)}
            >
              ☰
            </button>
            <nav className="hidden items-center gap-1 md:flex">{links}</nav>
          </div>
        </div>
        {open && <nav className="mx-auto max-w-5xl space-y-1 px-4 pb-3 md:hidden">{links}</nav>}
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
