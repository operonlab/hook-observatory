import I18nProvider from "./i18n/I18nProvider";
import StepIndicator from "./components/StepIndicator";
import LanguageSwitch from "./components/LanguageSwitch";
import Welcome from "./pages/Welcome";
import DependencyCheck from "./pages/DependencyCheck";
import ComponentSelect from "./pages/ComponentSelect";
import ToolConfig from "./pages/ToolConfig";
import Installing from "./pages/Installing";
import Complete from "./pages/Complete";
import { useInstallerStore } from "./store";

const PAGES = [Welcome, DependencyCheck, ComponentSelect, ToolConfig, Installing, Complete];

function InstallerApp() {
  const currentStep = useInstallerStore((s) => s.currentStep);
  const Page = PAGES[currentStep - 1];

  return (
    <div className="relative flex h-screen min-h-0 flex-col overflow-hidden bg-dark font-inter">
      {/* 全域背景光 */}
      <div className="absolute top-[-100px] left-[-100px] w-[500px] h-[500px] bg-mocha-blue/5 rounded-full blur-[150px] pointer-events-none" />
      <div className="absolute bottom-[-100px] right-[-100px] w-[500px] h-[500px] bg-mocha-mauve/5 rounded-full blur-[150px] pointer-events-none" />

      <header className="relative z-50 shrink-0 flex flex-wrap items-center justify-between px-4 sm:px-8 py-3 sm:py-6 gap-y-3 border-b border-white/5 bg-dark/30 backdrop-blur-md">
        <div className="flex items-center space-x-3">
          <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-lg bg-mocha-blue flex items-center justify-center shadow-lg shadow-mocha-blue/20">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#11111b" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" className="sm:w-4 sm:h-4">
              <path d="M 6 3 V 21 M 6 12 H 18 M 18 3 V 15 A 6 6 0 0 1 12 21" />
            </svg>
          </div>
          <span className="text-xs sm:text-sm font-black tracking-widest text-white uppercase opacity-80">Hook Observatory</span>
        </div>

        <div className="order-last sm:order-none flex w-full min-w-0 justify-center sm:w-auto">
          <StepIndicator />
        </div>
        <LanguageSwitch />
      </header>

      <main className="relative z-10 flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto">
        <Page />
      </main>

      <footer className="relative z-10 shrink-0 px-4 sm:px-8 py-4 border-t border-white/5 text-center">
        <p className="text-[10px] text-mocha-subtext/40 uppercase tracking-[0.3em] font-bold">
          © 2026 Hook Observatory — Modular Monolith Integration
        </p>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <InstallerApp />
    </I18nProvider>
  );
}
