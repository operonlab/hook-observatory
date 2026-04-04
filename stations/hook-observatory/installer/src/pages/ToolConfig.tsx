import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import { useInstallerStore } from "../store";
import { detectTools } from "../tauri";

export default function ToolConfig() {
  const { t } = useI18n();
  const { toolPaths, setToolPaths, nextStep, prevStep } = useInstallerStore();
  const [expanded, setExpanded] = useState(false);
  const [detecting, setDetecting] = useState(false);

  useEffect(() => {
    if (!toolPaths.python) {
      setDetecting(true);
      detectTools()
        .then((paths) => setToolPaths(paths))
        .catch(console.error)
        .finally(() => setDetecting(false));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const InputField = ({ label, value, onChange, placeholder, detected }: any) => (
    <div className="mb-6">
      <label className="block text-xs font-bold text-mocha-subtext uppercase tracking-widest mb-2 ml-1">
        {label}
      </label>
      <div className="relative group">
        <input
          type="text"
          className="w-full bg-dark/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-mocha-blue/30 focus:border-mocha-blue/50 transition-all placeholder:text-mocha-overlay"
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
        />
        {detected && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2 bg-mocha-green/20 text-mocha-green text-[9px] font-black px-2 py-1 rounded-md uppercase tracking-tighter">
            {t("config.detected")}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col min-h-screen p-10 bg-dark font-inter">
      <div className="max-w-2xl w-full mx-auto flex flex-col min-h-full">
        <header className="mb-10 text-center">
          <h2 className="text-3xl font-bold text-white mb-2">{t("config.title")}</h2>
          <p className="text-mocha-subtext">{t("config.subtitle")}</p>
        </header>

        <div className="glass-card p-8 mb-12 flex-grow">
          {detecting ? (
            <div className="flex flex-col items-center justify-center py-20">
              <div className="w-12 h-12 border-4 border-mocha-blue border-t-transparent rounded-full animate-spin mb-6" />
              <span className="text-mocha-subtext font-medium animate-pulse">{t("deps.checking")}</span>
            </div>
          ) : (
            <div className="space-y-4">
              <InputField 
                label={t("config.python")}
                value={toolPaths.python}
                onChange={(val: string) => setToolPaths({ python: val })}
                detected={!!toolPaths.python}
              />

              <div className="pt-4 border-t border-white/5">
                <button
                  className="flex items-center text-xs font-bold text-mocha-mauve hover:text-mocha-mauve/80 transition-colors uppercase tracking-widest group"
                  onClick={() => setExpanded(!expanded)}
                >
                  <span className={`mr-2 transition-transform duration-300 ${expanded ? "rotate-90" : ""}`}>
                    ▶
                  </span>
                  {t("config.advanced")}
                </button>

                <div className={`mt-6 overflow-hidden transition-all duration-500 ease-in-out ${expanded ? "max-h-[500px] opacity-100" : "max-h-0 opacity-0"}`}>
                  <div className="bg-mocha-overlay/5 p-6 rounded-2xl border border-white/5 space-y-2">
                    <InputField 
                      label={t("config.ruff")}
                      value={toolPaths.ruff}
                      onChange={(val: string) => setToolPaths({ ruff: val })}
                      placeholder={t("config.ruffPlaceholder")}
                    />
                    <InputField 
                      label={t("config.biome")}
                      value={toolPaths.biome}
                      onChange={(val: string) => setToolPaths({ biome: val })}
                      placeholder={t("config.biomePlaceholder")}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between mt-auto pt-6 border-t border-white/5">
          <button 
            className="px-6 py-2 rounded-xl text-mocha-subtext hover:text-white hover:bg-white/5 transition-all" 
            onClick={prevStep}
          >
            {t("nav.back")}
          </button>
          
          <button 
            className={`px-12 py-3 rounded-xl font-bold transition-all ${
              toolPaths.python 
                ? "btn-gradient text-dark shadow-lg shadow-mocha-blue/10" 
                : "bg-mocha-overlay text-mocha-subtext opacity-50 cursor-not-allowed"
            }`}
            onClick={nextStep} 
            disabled={!toolPaths.python}
          >
            {t("nav.next")}
          </button>
        </div>
      </div>
    </div>
  );
}