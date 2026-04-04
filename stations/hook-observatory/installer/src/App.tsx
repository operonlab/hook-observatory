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
    <div className="relative min-h-screen bg-dark overflow-hidden flex flex-col font-inter">
      {/* 全域背景光 */}
      <div className="absolute top-[-100px] left-[-100px] w-[500px] h-[500px] bg-mocha-blue/5 rounded-full blur-[150px] pointer-events-none" />
      <div className="absolute bottom-[-100px] right-[-100px] w-[500px] h-[500px] bg-mocha-mauve/5 rounded-full blur-[150px] pointer-events-none" />

      <header className="relative z-50 flex items-center justify-between px-8 py-6 border-b border-white/5 bg-dark/30 backdrop-blur-md">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-lg bg-mocha-blue flex items-center justify-center shadow-lg shadow-mocha-blue/20">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#11111b" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M 6 3 V 21 M 6 12 H 18 M 18 3 V 15 A 6 6 0 0 1 12 21" />
            </svg>
          </div>
          <span className="text-sm font-black tracking-widest text-white uppercase opacity-80">Hook Observatory</span>
        </div>
        
        <StepIndicator />
        <LanguageSwitch />
      </header>

      <main className="relative z-10 flex-grow flex flex-col items-center justify-center">
        <Page />
      </main>

      <footer className="relative z-10 px-8 py-4 border-t border-white/5 text-center">
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