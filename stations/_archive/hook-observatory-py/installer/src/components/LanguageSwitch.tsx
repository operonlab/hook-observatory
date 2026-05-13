import { useI18n } from "../i18n";

export default function LanguageSwitch() {
  const { locale, setLocale } = useI18n();

  return (
    <div className="flex bg-surface/50 border border-white/5 p-1 rounded-xl">
      <button
        className={`px-3 py-1 text-[10px] font-black rounded-lg transition-all duration-300 ${
          locale === "en" ? "bg-mocha-blue text-dark shadow-lg shadow-mocha-blue/20" : "text-mocha-subtext/40 hover:text-mocha-subtext/80"
        }`}
        onClick={() => setLocale("en")}
      >
        EN
      </button>
      <button
        className={`px-3 py-1 text-[10px] font-black rounded-lg transition-all duration-300 ${
          locale === "zh-TW" ? "bg-mocha-blue text-dark shadow-lg shadow-mocha-blue/20" : "text-mocha-subtext/40 hover:text-mocha-subtext/80"
        }`}
        onClick={() => setLocale("zh-TW")}
      >
        中文
      </button>
    </div>
  );
}