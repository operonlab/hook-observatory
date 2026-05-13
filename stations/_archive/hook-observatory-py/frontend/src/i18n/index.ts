import { createContext, useContext } from "react";
import en from "./en";
import zhTW from "./zh-TW";

export type Locale = "en" | "zh-TW";
export type TranslationKey = keyof typeof en;

const translations: Record<Locale, Record<TranslationKey, string>> = {
  en,
  "zh-TW": zhTW,
};

export function detectLocale(): Locale {
  const saved = localStorage.getItem("hook-obs-locale");
  if (saved === "en" || saved === "zh-TW") return saved;
  const browserLang = navigator.language;
  if (browserLang.startsWith("zh")) return "zh-TW";
  return "en";
}

export interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey) => string;
}

export const I18nContext = createContext<I18nContextValue>({
  locale: "en",
  setLocale: () => {},
  t: (key) => key,
});

export function useI18n() {
  return useContext(I18nContext);
}

export function createTranslator(locale: Locale) {
  const dict = translations[locale] || translations.en;
  return (key: TranslationKey): string => dict[key] ?? key;
}

export { translations };
