import { createContext, useContext, useEffect, useState } from "react";
import { translate, translateError } from "./translations.js";

const LanguageContext = createContext("en");
const STORAGE_KEY = "paperlense-interface";
const languages = ["en", "si", "ta"];
const sizes = ["small", "medium", "large"];

function initialPreferences() {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    // The interface still works when storage is blocked or contains invalid JSON.
  }
  const systemTheme = window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark" : "light";
  return {
    theme: ["light", "dark"].includes(saved?.theme) ? saved.theme : systemTheme,
    language: languages.includes(saved?.language) ? saved.language : "en",
    size: sizes.includes(saved?.size) ? saved.size : "medium",
  };
}

export function useTranslation() {
  const language = useContext(LanguageContext);
  return (message, values) => typeof message === "string"
    ? translate(language, message, values)
    : translateError(language, message);
}

export function InterfacePreferences({ children }) {
  const [preferences, setPreferences] = useState(initialPreferences);
  const { theme, language, size } = preferences;

  useEffect(() => {
    const root = document.documentElement;
    root.lang = language;
    root.dataset.theme = theme;
    root.dataset.textSize = size;
    document.title = translate(language, "PaperLense — Your research, in focus");
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
    } catch {
      // Preferences remain usable for the current visit.
    }
  }, [preferences, theme, language, size]);

  function change(name, value) {
    setPreferences((previous) => ({ ...previous, [name]: value }));
  }

  return (
    <LanguageContext.Provider value={language}>
      {children({ theme, language, size, change })}
    </LanguageContext.Provider>
  );
}

export function PreferenceControls({ theme, language, size, change }) {
  const t = useTranslation();
  const dark = theme === "dark";
  const mode = t(dark ? "Dark mode" : "Light mode");
  const action = t(dark ? "Switch to light mode" : "Switch to dark mode");
  return (
    <div className="interface-preferences" role="group" aria-label={t("Interface settings")}>
      <button
        type="button"
        className="theme-toggle"
        aria-label={`${mode}. ${action}`}
        title={action}
        onClick={() => change("theme", dark ? "light" : "dark")}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.75" strokeLinecap="round" aria-hidden="true">
          {dark
            ? <path d="M21 14a9 9 0 0 1-11-11A9 9 0 1 0 21 14Z" />
            : <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>}
        </svg>
        <span>{mode}</span>
      </button>
      <label>
        <span>{t("Language")}</span>
        <select value={language} onChange={(event) => change("language", event.target.value)}>
          <option value="en" lang="en">English</option>
          <option value="si" lang="si">සිංහල</option>
          <option value="ta" lang="ta">தமிழ்</option>
        </select>
      </label>
      <label>
        <span>{t("Text size")}</span>
        <select value={size} onChange={(event) => change("size", event.target.value)}>
          <option value="small">{t("Small")}</option>
          <option value="medium">{t("Medium")}</option>
          <option value="large">{t("Large")}</option>
        </select>
      </label>
    </div>
  );
}
