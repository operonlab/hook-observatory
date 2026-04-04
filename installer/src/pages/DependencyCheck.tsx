import { useEffect, useState } from "react";
import { useI18n, type TranslationKey } from "../i18n";
import { useInstallerStore } from "../store";
import { checkDependencies } from "../tauri";

const DEP_LINKS: Record<string, string> = {
  python: "https://www.python.org/downloads/",
  claude_code: "https://claude.ai/code",
  git: "https://git-scm.com/downloads",
};

const DEP_ICONS: Record<string, string> = {
  python: "🐍",
  claude_code: "🤖",
  git: "📂",
};

export default function DependencyCheck() {
  const { t } = useI18n();
  const { dependencies, setDependencies, nextStep, prevStep } = useInstallerStore();
  const [checking, setChecking] = useState(false);

  const runCheck = async () => {
    setChecking(true);
    try {
      const results = await checkDependencies();
      setDependencies(results);
    } catch (err) {
      console.error("Dependency check failed:", err);
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    if (dependencies.length === 0) {
      runCheck();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const allFound = dependencies.length > 0 && dependencies.every((d) => d.found);

  const depNameKey = (name: string) => {
    const map: Record<string, string> = {
      python: "deps.python",
      claude_code: "deps.claudeCode",
      git: "deps.git",
    };
    return map[name] || name;
  };

  const depDescKey = (name: string) => {
    const map: Record<string, string> = {
      python: "deps.pythonDesc",
      claude_code: "deps.claudeCodeDesc",
      git: "deps.gitDesc",
    };
    return map[name] || "";
  };

  return (
    <div className="flex w-full flex-1 flex-col px-4 py-6 sm:px-6 sm:py-8 md:px-10 md:py-10 bg-dark font-inter">
      <div className="max-w-4xl w-full mx-auto flex min-h-0 flex-1 flex-col">
        <header className="mb-6 sm:mb-10 text-center">
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-2">{t("deps.title")}</h2>
          <p className="text-mocha-subtext">{t("deps.subtitle")}</p>
        </header>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 sm:gap-6 mb-8 sm:mb-12 flex-1 content-start">
          {checking && dependencies.length === 0 ? (
            <div className="col-span-1 sm:col-span-2 md:col-span-3 flex flex-col items-center py-20 bg-surface/50 rounded-xl border border-white/5 animate-pulse">
              <div className="w-10 h-10 border-2 border-mocha-blue border-t-transparent rounded-full animate-spin mb-4" />
              <span className="text-mocha-subtext font-medium">{t("deps.checking")}</span>
            </div>
          ) : (
            dependencies.map((dep) => (
              <div
                key={dep.name}
                className={`glass-card p-4 sm:p-6 flex flex-col items-center text-center transition-all duration-300 ${
                  dep.found ? "border-mocha-green/20" : "border-mocha-red/20"
                }`}
              >
                <div className="relative mb-6">
                  <div className="text-4xl bg-mocha-overlay/20 p-4 rounded-2xl">
                    {DEP_ICONS[dep.name] || "📦"}
                  </div>
                  <div 
                    className={`absolute -bottom-1 -right-1 w-4 h-4 rounded-full border-2 border-dark ${
                      dep.found ? "bg-mocha-green" : "bg-mocha-red"
                    } ${!checking && "animate-indicator-pulse"}`}
                  />
                </div>

                <h3 className="text-lg font-bold text-white mb-1">
                  {t(depNameKey(dep.name) as TranslationKey)}
                </h3>
                <p className="text-xs text-mocha-subtext mb-6 line-clamp-2 min-h-[32px]">
                  {t(depDescKey(dep.name) as TranslationKey)}
                </p>

                {dep.found ? (
                  <div className="w-full pt-4 border-t border-white/5 flex flex-col items-center">
                    <span className="text-[10px] uppercase tracking-widest font-bold text-mocha-green mb-1">
                      {t("deps.found")}
                    </span>
                    <code className="text-[10px] bg-dark px-2 py-1 rounded text-mocha-subtext truncate max-w-full">
                      {dep.path}
                    </code>
                    {dep.version && (
                       <span className="mt-2 text-[10px] font-mono text-mocha-subtext/60">
                         v{dep.version}
                       </span>
                    )}
                  </div>
                ) : (
                  <a
                    className="mt-auto w-full py-2 bg-mocha-red/10 hover:bg-mocha-red/20 text-mocha-red text-xs font-bold rounded-lg transition-colors"
                    href={DEP_LINKS[dep.name]}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t("deps.install")}
                  </a>
                )}
              </div>
            ))
          )}
        </div>

        <div className="flex flex-col items-center mb-6 sm:mb-10">
          {dependencies.length > 0 && !allFound && (
            <div className="bg-mocha-red/10 text-mocha-red px-4 py-2 rounded-lg text-sm font-medium mb-4 flex items-center">
              <span className="mr-2">⚠️</span> {t("deps.missing")}
            </div>
          )}
          {allFound && (
            <div className="bg-mocha-green/10 text-mocha-green px-4 py-2 rounded-lg text-sm font-medium mb-4 flex items-center">
              <span className="mr-2">✓</span> {t("deps.allGood")}
            </div>
          )}
        </div>

        <div className="shrink-0 flex items-center justify-between mt-auto pt-6 border-t border-white/5">
          <button 
            className="px-6 py-2 rounded-xl text-mocha-subtext hover:text-white hover:bg-white/5 transition-all" 
            onClick={prevStep}
          >
            {t("nav.back")}
          </button>
          
          <div className="flex space-x-4">
            {!allFound && dependencies.length > 0 && (
              <button 
                className="px-6 py-2 rounded-xl border border-mocha-blue/30 text-mocha-blue hover:bg-mocha-blue/10 transition-all disabled:opacity-50" 
                onClick={runCheck} 
                disabled={checking}
              >
                {t("deps.retry")}
              </button>
            )}
            <button 
              className={`px-10 py-2 rounded-xl font-bold transition-all ${
                allFound 
                  ? "btn-gradient text-dark" 
                  : "bg-mocha-overlay text-mocha-subtext opacity-50 cursor-not-allowed"
              }`}
              onClick={nextStep} 
              disabled={!allFound}
            >
              {t("nav.next")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
