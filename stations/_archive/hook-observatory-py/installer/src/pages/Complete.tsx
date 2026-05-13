import { useI18n } from "../i18n";
import { useInstallerStore } from "../store";
import { closeWindow } from "../tauri";

export default function Complete() {
  const { t } = useI18n();
  const components = useInstallerStore((s) => s.components);

  const enabled = components.filter((c) => c.enabled);

  return (
    <div className="flex w-full flex-1 flex-col px-4 py-6 sm:px-6 sm:py-8 md:px-10 md:py-10 bg-dark font-inter relative overflow-x-hidden text-center">
      {/* Celebration Glows */}
      <div className="absolute top-1/3 left-1/4 w-[400px] h-[400px] bg-mocha-green/5 rounded-full blur-[100px] pointer-events-none animate-pulse" />
      <div className="absolute bottom-1/3 right-1/4 w-[400px] h-[400px] bg-mocha-mauve/5 rounded-full blur-[100px] pointer-events-none animate-pulse" style={{ animationDelay: '1s' }} />

      <div className="glass-card my-auto max-w-lg w-full mx-auto p-6 sm:p-12 relative z-10 flex flex-col items-center">
        <div className="mb-6 sm:mb-10 relative">
          <div className="absolute inset-0 bg-mocha-green/20 rounded-full blur-2xl animate-glow-pulse" />
          <div className="relative w-24 h-24 rounded-full bg-mocha-green flex items-center justify-center shadow-[0_0_40px_rgba(166,227,161,0.4)]">
            <svg
              width="50"
              height="38"
              viewBox="0 0 32 24"
              fill="none"
              className="animate-[bounce_0.8s_ease-in-out]"
            >
              <path
                d="M2 12L11 21L30 2"
                stroke="#11111b"
                strokeWidth="5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
        </div>

        <h2 className="text-2xl sm:text-3xl font-bold text-white mb-3">
          {t("complete.title")}
        </h2>
        <p className="text-mocha-blue font-medium mb-6 uppercase tracking-[0.2em] text-xs">
          {t("complete.subtitle")}
        </p>
        
        <div className="bg-mocha-overlay/10 rounded-2xl p-4 sm:p-6 mb-6 sm:mb-10 w-full border border-white/5">
          <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-mocha-subtext/60 mb-4">
            {t("complete.enabled")}
          </h3>
          <div className="flex flex-wrap justify-center gap-2">
            {enabled.map((comp) => (
              <span 
                key={comp.id} 
                className="bg-surface border border-mocha-blue/20 text-white text-[10px] font-bold px-3 py-1.5 rounded-lg flex items-center shadow-sm"
              >
                <span className="mr-2 opacity-80">{comp.icon}</span>
                {comp.id.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </div>

        <p className="text-mocha-subtext text-sm mb-6 sm:mb-10 italic leading-relaxed">
          {t("complete.enjoy")}
          <br />
          <span className="text-[11px] opacity-60 not-italic mt-2 block">
            {t("complete.restart")}
          </span>
        </p>

        <button 
          className="btn-gradient w-full py-4 rounded-xl text-dark font-black text-sm uppercase tracking-widest shadow-lg shadow-mocha-blue/10 active:scale-95 transition-all"
          onClick={closeWindow}
        >
          {t("nav.close")}
        </button>
      </div>
    </div>
  );
}
