import { useI18n, type TranslationKey } from "../i18n";
import { useInstallerStore, type HookComponent, type ComponentCategory } from "../store";

const CATEGORY_ORDER: ComponentCategory[] = ["required", "optional", "advanced"];

const CATEGORY_STYLES: Record<ComponentCategory, { borderColor: string; textColor: string; bgColor: string; labelKey: string; descKey: string }> = {
  required: { borderColor: "border-mocha-green/30", textColor: "text-mocha-green", bgColor: "bg-mocha-green/10", labelKey: "comp.required", descKey: "comp.requiredDesc" },
  optional: { borderColor: "border-mocha-blue/30", textColor: "text-mocha-blue", bgColor: "bg-mocha-blue/10", labelKey: "comp.optional", descKey: "comp.optionalDesc" },
  advanced: { borderColor: "border-mocha-mauve/30", textColor: "text-mocha-mauve", bgColor: "bg-mocha-mauve/10", labelKey: "comp.advanced", descKey: "comp.advancedDesc" },
};

function ComponentCard({
  comp,
  onToggle,
}: {
  comp: HookComponent;
  onToggle: (id: string) => void;
}) {
  const { t } = useI18n();
  const nameKey = `comp.${comp.id}` as TranslationKey;
  const descKey = `comp.${comp.id}.desc` as TranslationKey;

  return (
    <label
      className={`relative flex items-center p-3 sm:p-4 rounded-xl border transition-all duration-300 cursor-pointer group ${
        comp.enabled 
          ? "bg-surface border-mocha-blue/40 shadow-lg shadow-mocha-blue/5" 
          : "bg-mocha-overlay/10 border-white/5 hover:border-white/20"
      } ${comp.locked ? "opacity-70 cursor-not-allowed" : ""}`}
    >
      <div className="relative flex items-center justify-center w-6 h-6 mr-4">
        <input
          type="checkbox"
          className="peer absolute opacity-0 w-full h-full cursor-pointer disabled:cursor-not-allowed"
          checked={comp.enabled}
          disabled={comp.locked}
          onChange={() => onToggle(comp.id)}
        />
        <div className={`w-6 h-6 rounded-md border-2 transition-all duration-200 flex items-center justify-center ${
          comp.enabled 
            ? "bg-mocha-blue border-mocha-blue shadow-[0_0_10px_rgba(137,180,250,0.4)]" 
            : "border-mocha-overlay group-hover:border-mocha-subtext/40"
        }`}>
          {comp.enabled && (
            <svg width="14" height="10" viewBox="0 0 14 10" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M1 5L5 9L13 1" stroke="#11111b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          )}
        </div>
      </div>

      <span className="text-2xl mr-4 grayscale-[0.5] group-hover:grayscale-0 transition-all">
        {comp.icon}
      </span>
      
      <div className="flex flex-col">
        <div className={`text-sm font-bold transition-colors ${comp.enabled ? "text-white" : "text-mocha-subtext"}`}>
          {t(nameKey)}
        </div>
        <div className="text-[11px] text-mocha-subtext/60 leading-tight">
          {t(descKey)}
        </div>
      </div>

      {comp.locked && (
        <div className="absolute top-2 right-2 text-[10px] uppercase font-bold text-mocha-green/40 tracking-widest">
          Locked
        </div>
      )}
    </label>
  );
}

export default function ComponentSelect() {
  const { t } = useI18n();
  const { components, toggleComponent, nextStep, prevStep } = useInstallerStore();

  const grouped = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    style: CATEGORY_STYLES[cat],
    items: components.filter((c) => c.category === cat),
  }));

  return (
    <div className="flex w-full flex-1 flex-col px-4 py-6 sm:px-6 sm:py-8 md:px-10 md:py-10 bg-dark font-inter">
      <div className="max-w-4xl w-full mx-auto flex min-h-0 flex-1 flex-col">
        <header className="mb-6 sm:mb-10 text-center">
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-2">{t("comp.title")}</h2>
          <p className="text-mocha-subtext">{t("comp.subtitle")}</p>
        </header>

        <div className="space-y-6 sm:space-y-8 mb-8 sm:mb-12 flex-1">
          {grouped.map(({ category, style, items }) => (
            <div
              key={category}
              className={`rounded-2xl border p-4 sm:p-6 bg-surface/30 ${style.borderColor}`}
            >
              <div className="flex flex-wrap items-center gap-2 mb-4 sm:mb-6">
                <span className={`px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest ${style.bgColor} ${style.textColor}`}>
                  {t(style.labelKey as TranslationKey)}
                </span>
                <span className="text-xs text-mocha-subtext/80 italic font-medium">
                  {t(style.descKey as TranslationKey)}
                </span>
              </div>
              
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
                {items.map((comp) => (
                  <ComponentCard key={comp.id} comp={comp} onToggle={toggleComponent} />
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="shrink-0 flex items-center justify-between mt-auto pt-6 border-t border-white/5">
          <button 
            className="px-6 py-2 rounded-xl text-mocha-subtext hover:text-white hover:bg-white/5 transition-all" 
            onClick={prevStep}
          >
            {t("nav.back")}
          </button>
          
          <button 
            className="btn-gradient px-12 py-3 rounded-xl font-bold text-dark"
            onClick={nextStep}
          >
            {t("nav.next")}
          </button>
        </div>
      </div>
    </div>
  );
}
