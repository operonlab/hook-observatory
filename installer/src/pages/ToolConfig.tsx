import { useEffect, useState } from "react";
import { useI18n, type TranslationKey } from "../i18n";
import { useInstallerStore, type ToolDetailInfo } from "../store";
import { detectTools } from "../tauri";

const TOOL_ICONS: Record<string, string> = {
  git: "\u{1F4C2}",
  ruff: "\u{1F40D}",
  biome: "\u{1F310}",
  gh: "\u{1F419}",
};

function ToolCard({ tool }: { tool: ToolDetailInfo }) {
  const { t } = useI18n();
  const [showCmd, setShowCmd] = useState(false);
  const [copied, setCopied] = useState(false);

  const nameKey = `tool.${tool.name}` as TranslationKey;
  const descKey = `tool.${tool.name}.desc` as TranslationKey;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(tool.install_command);
    } catch {
      // Fallback for non-secure contexts
      const ta = document.createElement("textarea");
      ta.value = tool.install_command;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className={`glass-card p-4 sm:p-6 flex flex-col items-center text-center transition-all duration-300 ${
        tool.installed ? "border-mocha-green/20" : "border-white/5"
      }`}
    >
      <div className="relative mb-4">
        <div className="text-3xl bg-mocha-overlay/20 p-3 rounded-2xl">
          {TOOL_ICONS[tool.name] || "\u{1F4E6}"}
        </div>
        <div
          className={`absolute -bottom-1 -right-1 w-4 h-4 rounded-full border-2 border-dark ${
            tool.installed ? "bg-mocha-green" : "bg-mocha-overlay"
          }`}
        />
      </div>

      <div className="flex flex-wrap items-center justify-center gap-1.5 mb-1">
        <h3 className="text-sm sm:text-base font-bold text-white">
          {t(nameKey)}
        </h3>
        <span
          className={`text-[9px] font-black px-1.5 py-0.5 rounded uppercase tracking-wider ${
            tool.required
              ? "bg-mocha-yellow/15 text-mocha-yellow"
              : "bg-mocha-blue/15 text-mocha-blue"
          }`}
        >
          {tool.required
            ? t("config.requiredLabel")
            : t("config.optionalLabel")}
        </span>
      </div>

      <p className="text-[11px] text-mocha-subtext/60 mb-4 line-clamp-2 min-h-[30px] leading-tight">
        {t(descKey)}
      </p>

      {tool.installed ? (
        <div className="w-full pt-3 border-t border-white/5 flex flex-col items-center">
          <span className="text-[10px] uppercase tracking-widest font-bold text-mocha-green mb-1">
            {t("config.installed")}
          </span>
          {tool.version && (
            <span className="text-[10px] font-mono text-mocha-subtext/60 mb-1">
              v{tool.version}
            </span>
          )}
          <code className="text-[10px] bg-dark px-2 py-1 rounded text-mocha-subtext truncate max-w-full">
            {tool.path}
          </code>
          {tool.required && (
            <span className="mt-2 text-[9px] text-mocha-green/60 italic">
              {t("config.checkedInStep2")}
            </span>
          )}
        </div>
      ) : (
        <div className="w-full pt-3 border-t border-white/5 flex flex-col items-center">
          <span className="text-[10px] uppercase tracking-widest font-bold text-mocha-overlay mb-3">
            {t("config.notInstalled")}
          </span>
          {!showCmd ? (
            <button
              className="w-full py-2 bg-mocha-blue/10 hover:bg-mocha-blue/20 text-mocha-blue text-xs font-bold rounded-lg transition-colors"
              onClick={() => setShowCmd(true)}
            >
              {t("deps.install")}
            </button>
          ) : (
            <div className="w-full space-y-2">
              <p className="text-[10px] text-mocha-subtext">
                {t("config.installCmd")}
              </p>
              <div className="flex items-center bg-dark rounded-lg overflow-hidden border border-white/5">
                <code className="flex-1 px-3 py-2 text-[11px] text-mocha-blue font-mono truncate min-w-0">
                  {tool.install_command}
                </code>
                <button
                  className="px-3 py-2 text-[10px] font-bold text-mocha-subtext hover:text-white transition-colors border-l border-white/5 shrink-0"
                  onClick={handleCopy}
                >
                  {copied ? t("config.copied") : t("config.copy")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ToolConfig() {
  const { t } = useI18n();
  const { toolPaths, toolDetails, setToolPaths, setToolDetails, nextStep, prevStep } =
    useInstallerStore();
  const [detecting, setDetecting] = useState(false);

  useEffect(() => {
    if (toolDetails.length === 0) {
      setDetecting(true);
      detectTools()
        .then((details) => setToolDetails(details))
        .catch(console.error)
        .finally(() => setDetecting(false));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const displayTools = toolDetails.filter((d) => d.name !== "python");

  return (
    <div className="flex w-full flex-1 flex-col px-4 py-6 sm:px-6 sm:py-8 md:px-10 md:py-10 bg-dark font-inter">
      <div className="max-w-4xl w-full mx-auto flex min-h-0 flex-1 flex-col">
        <header className="mb-6 sm:mb-10 text-center">
          <h2 className="text-2xl sm:text-3xl font-bold text-white mb-2">
            {t("config.title")}
          </h2>
          <p className="text-sm text-mocha-subtext">{t("config.subtitle")}</p>
        </header>

        <div className="flex-1 space-y-6 sm:space-y-8 mb-8 sm:mb-12">
          {detecting ? (
            <div className="flex flex-col items-center justify-center py-20">
              <div className="w-12 h-12 border-4 border-mocha-blue border-t-transparent rounded-full animate-spin mb-6" />
              <span className="text-mocha-subtext font-medium animate-pulse">
                {t("deps.checking")}
              </span>
            </div>
          ) : (
            <>
              {/* Python Path Input */}
              <div className="glass-card p-4 sm:p-6">
                <label className="block text-xs font-bold text-mocha-subtext uppercase tracking-widest mb-2 ml-1">
                  {t("config.python")}
                </label>
                <div className="relative group">
                  <input
                    type="text"
                    className="w-full bg-dark/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-mocha-blue/30 focus:border-mocha-blue/50 transition-all placeholder:text-mocha-overlay"
                    value={toolPaths.python}
                    onChange={(e) => setToolPaths({ python: e.target.value })}
                  />
                  {toolPaths.python && (
                    <div className="absolute right-3 top-1/2 -translate-y-1/2 bg-mocha-green/20 text-mocha-green text-[9px] font-black px-2 py-1 rounded-md uppercase tracking-tighter">
                      {t("config.detected")}
                    </div>
                  )}
                </div>
              </div>

              {/* Tool Cards Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
                {displayTools.map((tool) => (
                  <ToolCard key={tool.name} tool={tool} />
                ))}
              </div>
            </>
          )}
        </div>

        <div className="shrink-0 flex items-center justify-between mt-auto pt-6 border-t border-white/5">
          <button
            className="px-4 sm:px-6 py-2 rounded-xl text-mocha-subtext hover:text-white hover:bg-white/5 transition-all text-sm"
            onClick={prevStep}
          >
            {t("nav.back")}
          </button>

          <button
            className={`px-8 sm:px-12 py-3 rounded-xl font-bold transition-all text-sm ${
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
