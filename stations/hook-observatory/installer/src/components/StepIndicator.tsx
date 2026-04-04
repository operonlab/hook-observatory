import { useI18n, type TranslationKey } from "../i18n";
import { useInstallerStore } from "../store";

const STEP_KEYS: TranslationKey[] = [
  "step.welcome",
  "step.dependencies",
  "step.components",
  "step.config",
  "step.install",
  "step.complete",
];

export default function StepIndicator() {
  const { t } = useI18n();
  const currentStep = useInstallerStore((s) => s.currentStep);

  return (
    <div className="flex items-center space-x-1 sm:space-x-2">
      {STEP_KEYS.map((key, i) => {
        const stepNum = i + 1;
        const isActive = stepNum === currentStep;
        const isDone = stepNum < currentStep;

        return (
          <div key={key} className="flex items-center">
            {/* Step Node */}
            <div className="relative group cursor-default">
              <div
                className={`w-5 h-5 sm:w-7 sm:h-7 rounded-full sm:rounded-lg border flex items-center justify-center text-[10px] font-black transition-all duration-500 ${
                  isActive
                    ? "bg-mocha-blue border-mocha-blue text-dark shadow-[0_0_15px_rgba(137,180,250,0.5)] scale-110"
                    : isDone
                      ? "bg-mocha-green/20 border-mocha-green/40 text-mocha-green"
                      : "bg-surface border-white/5 text-mocha-subtext/40"
                }`}
              >
                {isDone ? (
                  <svg
                    width="10"
                    height="8"
                    viewBox="0 0 14 10"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    className="sm:w-3 sm:h-[10px]"
                  >
                    <path
                      d="M1 5L5 9L13 1"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                ) : (
                  <span className="hidden sm:inline">{stepNum}</span>
                )}
              </div>

              {/* Tooltip Label — hidden on small screens */}
              <div
                className={`hidden sm:block absolute top-10 left-1/2 -translate-x-1/2 whitespace-nowrap text-[9px] font-black uppercase tracking-widest transition-all duration-300 pointer-events-none ${
                  isActive
                    ? "opacity-100 translate-y-0 text-mocha-blue"
                    : "opacity-0 -translate-y-2 text-mocha-subtext/40"
                }`}
              >
                {t(key)}
              </div>
            </div>

            {/* Connector */}
            {i < STEP_KEYS.length - 1 && (
              <div className="w-3 sm:w-6 h-[2px] mx-0.5 sm:mx-1 bg-white/5 overflow-hidden">
                <div
                  className={`h-full bg-gradient-to-r from-mocha-blue to-mocha-mauve transition-all duration-1000 ease-in-out ${
                    isDone ? "w-full" : "w-0"
                  }`}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
