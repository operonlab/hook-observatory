import { useState, useMemo, type ReactNode } from "react";
import {
  I18nContext,
  detectLocale,
  createTranslator,
  type Locale,
} from "./index";

export default function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(detectLocale);

  const value = useMemo(
    () => ({
      locale,
      setLocale: (newLocale: Locale) => {
        localStorage.setItem("hook-obs-installer-locale", newLocale);
        setLocaleState(newLocale);
      },
      t: createTranslator(locale),
    }),
    [locale],
  );

  return (
    <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
  );
}
