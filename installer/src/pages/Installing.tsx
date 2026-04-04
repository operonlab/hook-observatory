import { useEffect, useRef } from "react";
import { useI18n, type TranslationKey } from "../i18n";
import { useInstallerStore } from "../store";
import { installHooks } from "../tauri";

const STEP_LABELS: TranslationKey[] = [
  "install.step1",
  "install.step2",
  "install.step3",
  "install.step4",
];

export default function Installing() {
  const { t } = useI18n();
  const {
    components,
    toolPaths,
    installSteps,
    installError,
    setInstallSteps,
    updateInstallStep,
    setInstallError,
    nextStep,
    prevStep,
  } = useInstallerStore();
  const startedRef = useRef(false);

  const runInstall = async () => {
    const steps = STEP_LABELS.map((label) => ({
      label: t(label),
      status: "pending" as const,
    }));
    setInstallSteps(steps);
    setInstallError(null);

    const enabledIds = components.filter((c) => c.enabled).map((c) => c.id);

    try {
      await installHooks(
        { components: enabledIds, toolPaths },
        (progress) => {
          updateInstallStep(progress.step, {
            status: progress.status,
            error: progress.error,
          });
        },
      );
      setTimeout(nextStep, 1500);
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    if (!startedRef.current) {
      startedRef.current = true;
      runInstall();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const completedCount = installSteps.filter((s) => s.status === "done").length;
  const progressPercent = (completedCount / Math.max(installSteps.length, 1)) * 100;
  const allDone = installSteps.length > 0 && installSteps.every((s) => s.status === "done");
  const hasError = installSteps.some((s) => s.status === "error") || installError;

  return (
    <div className="flex flex-col items-center justify-center min-h-screen p-10 bg-dark font-inter relative overflow-hidden">
      {/* Background Glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-mocha-blue/5 rounded-full blur-[120px] pointer-events-none" />
      
      <div className="glass-card max-w-xl w-full p-10 relative z-10">
        <header className="mb-10 text-center">
          <h2 className="text-3xl font-bold text-white mb-2">
            {hasError ? t("install.failed") : allDone ? "Installation Complete" : t("install.title")}
          </h2>
          <p className="text-mocha-subtext">{t("install.subtitle")}</p>
        </header>

        <div className="space-y-4 mb-10">
          {installSteps.map((step, i) => (
            <div 
              key={i} 
              className={`flex items-center p-4 rounded-xl border transition-all duration-500 ${
                step.status === "running" ? "bg-mocha-blue/5 border-mocha-blue/20" : 
                step.status === "done" ? "bg-mocha-green/5 border-mocha-green/20" : 
                step.status === "error" ? "bg-mocha-red/5 border-mocha-red/20" : "bg-transparent border-transparent"
              }`}
            >
              <div className="flex items-center justify-center w-8 h-8 mr-4">
                {step.status === "pending" && <div className="w-2 h-2 rounded-full bg-mocha-overlay" />}
                {step.status === "running" && <div className="w-5 h-5 border-2 border-mocha-blue border-t-transparent rounded-full animate-spin" />}
                {step.status === "done" && (
                  <div className="w-6 h-6 rounded-full bg-mocha-green flex items-center justify-center animate-[bounce_0.5s_ease-in-out]">
                    <svg width="12" height="9" viewBox="0 0 12 9" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M1 4.5L4 7.5L11 0.5" stroke="#11111b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </div>
                )}
                {step.status === "error" && (
                  <div className="w-6 h-6 rounded-full bg-mocha-red flex items-center justify-center">
                    <span className="text-dark font-black text-xs">✕</span>
                  </div>
                )}
              </div>
              
              <div className="flex-grow">
                <span className={`text-sm font-bold transition-colors ${
                  step.status === "running" || step.status === "done" ? "text-white" : "text-mocha-subtext"
                }`}>
                  {step.label}
                </span>
                {step.error && (
                  <p className="text-[10px] text-mocha-red mt-1 leading-tight">{step.error}</p>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Progress Section */}
        <div className="space-y-4">
          <div className="flex justify-between text-[10px] font-black uppercase tracking-widest text-mocha-subtext/60 px-1">
            <span>Progress</span>
            <span>{Math.round(progressPercent)}%</span>
          </div>
          <div className="h-2 w-full bg-mocha-overlay/20 rounded-full overflow-hidden relative">
            <div
              className="h-full btn-gradient transition-all duration-700 ease-out relative"
              style={{ width: `${progressPercent}%` }}
            >
              <div className="absolute top-0 left-0 w-full h-full bg-white/20 animate-[pulse_2s_infinite]" />
            </div>
          </div>
        </div>

        {allDone && (
          <div className="mt-10 flex flex-col items-center animate-[fadeIn_0.5s_ease-out]">
            <div className="w-16 h-16 rounded-full bg-mocha-green flex items-center justify-center shadow-[0_0_30px_rgba(166,227,161,0.3)] mb-4">
               <svg width="32" height="24" viewBox="0 0 32 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M2 12L11 21L30 2" stroke="#11111b" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <p className="text-mocha-green font-bold animate-pulse uppercase tracking-[0.2em] text-xs">Finalizing Assets...</p>
          </div>
        )}

        {hasError && (
          <div className="mt-10 p-6 bg-mocha-red/10 rounded-2xl border border-mocha-red/20 animate-[shake_0.5s_ease-in-out]">
            <h3 className="text-mocha-red font-bold text-sm mb-2 flex items-center">
              <span className="mr-2">🚨</span> {t("install.failed")}
            </h3>
            <p className="text-xs text-mocha-subtext mb-6">{installError || t("install.failedDesc")}</p>
            
            <div className="flex space-x-4">
              <button 
                className="flex-1 py-3 rounded-xl bg-mocha-overlay/20 text-mocha-subtext text-xs font-bold hover:bg-mocha-overlay/40 transition-all" 
                onClick={prevStep}
              >
                {t("nav.back")}
              </button>
              <button
                className="flex-[2] py-3 rounded-xl bg-mocha-red text-dark text-xs font-bold hover:brightness-110 transition-all"
                onClick={() => {
                  startedRef.current = false;
                  runInstall();
                }}
              >
                {t("install.retry")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}