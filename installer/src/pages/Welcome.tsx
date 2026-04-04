import { useI18n } from "../i18n";
import { useInstallerStore } from "../store";

export default function Welcome() {
  const { t } = useI18n();
  const nextStep = useInstallerStore((s) => s.nextStep);

  return (
    <div className="flex items-center justify-center min-h-screen p-6 bg-dark font-inter">
      <div className="glass-card max-w-lg w-full p-10 flex flex-col items-center text-center">
        <div className="mb-8 p-6 bg-mocha-overlay/20 rounded-2xl animate-glow-pulse">
          <svg width="100" height="100" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
            {/* Outer Observatory Ring - Minimalist & Tech */}
            <circle cx="50" cy="50" r="45" stroke="#313244" strokeWidth="1" strokeDasharray="6 6" />
            <circle cx="50" cy="50" r="35" stroke="#89b4fa" strokeWidth="2" strokeOpacity="0.1" />
            
            {/* The Hook / H-Core */}
            <path 
              d="M35 25 V75 M35 50 H65 M65 25 V60 C65 70 55 75 45 75" 
              stroke="#89b4fa" 
              strokeWidth="6" 
              strokeLinecap="round" 
              strokeLinejoin="round" 
              className="drop-shadow-[0_0_8px_rgba(137,180,250,0.4)]"
            />

            {/* Accent Hook Tip */}
            <path 
              d="M65 45 V60 C65 70 55 75 45 75" 
              stroke="#cba6f7" 
              strokeWidth="6" 
              strokeLinecap="round" 
              strokeLinejoin="round" 
            />

            {/* The "Captured" Node */}
            <circle cx="45" cy="75" r="5" fill="#a6e3a1" className="animate-pulse" />
            <circle cx="45" cy="75" r="2" fill="#11111b" />
          </svg>
        </div>

        <h1 className="text-3xl font-bold text-white mb-2 tracking-tight">
          {t("welcome.title")}
        </h1>
        <p className="text-mocha-blue font-medium mb-6 uppercase tracking-[0.2em] text-xs">
          {t("welcome.subtitle")}
        </p>
        <p className="text-mocha-subtext mb-10 text-sm leading-relaxed max-w-sm">
          {t("welcome.description")}
        </p>

        <button 
          className="btn-gradient w-full py-4 rounded-xl text-dark font-bold flex items-center justify-center group"
          onClick={nextStep}
        >
          <span className="mr-2">{t("nav.getStarted")}</span>
          <span className="transition-transform duration-300 group-hover:translate-x-1">→</span>
        </button>

        <div className="mt-8 flex items-center space-x-2 opacity-40">
           <span className="w-1.5 h-1.5 rounded-full bg-mocha-blue shadow-[0_0_8px_#89b4fa]"></span>
           <span className="text-[10px] uppercase font-bold tracking-widest text-mocha-subtext">
             {t("welcome.version")}
           </span>
        </div>
      </div>
    </div>
  );
}