const en = {
  // Step indicator
  "step.welcome": "Welcome",
  "step.dependencies": "Dependencies",
  "step.components": "Components",
  "step.config": "Configuration",
  "step.install": "Installing",
  "step.complete": "Complete",

  // Navigation
  "nav.next": "Next",
  "nav.back": "Back",
  "nav.getStarted": "Get Started",
  "nav.close": "Close",
  "nav.skip": "Skip",

  // Welcome
  "welcome.title": "hook-observatory",
  "welcome.subtitle": "Safety rails for your AI coding assistant",
  "welcome.description":
    "Protect your codebase with smart hooks that watch what AI does — block dangerous commands, prevent secret leaks, and keep a full audit trail.",
  "welcome.version": "v1.0.0",

  // Dependency Check
  "deps.title": "Checking Dependencies",
  "deps.subtitle": "Let's make sure everything is ready",
  "deps.checking": "Checking...",
  "deps.found": "Found at",
  "deps.notFound": "Not found",
  "deps.install": "Install",
  "deps.allGood": "All dependencies found!",
  "deps.missing":
    "Some dependencies are missing. Please install them to continue.",
  "deps.python": "Python 3.12+",
  "deps.pythonDesc": "Required to run hook handlers",
  "deps.claudeCode": "Claude Code",
  "deps.claudeCodeDesc": "The AI coding assistant to protect",
  "deps.git": "git",
  "deps.gitDesc": "Version control system",
  "deps.retry": "Re-check",

  // Component Selection
  "comp.title": "Choose Your Safety Net",
  "comp.subtitle": "Select which protections to enable",
  "comp.required": "Essential",
  "comp.requiredDesc": "Core safety — always enabled",
  "comp.optional": "Recommended",
  "comp.optionalDesc": "Extra protection — enabled by default",
  "comp.advanced": "Integrations",
  "comp.advancedDesc": "Power-user features — needs extra setup",

  // Component names & descriptions
  "comp.bash_safety": "Command Guard",
  "comp.bash_safety.desc":
    "Blocks dangerous commands — prevents AI from accidentally deleting your files",
  "comp.auto_format": "Auto Format",
  "comp.auto_format.desc":
    "Auto-formats code after edits — like spell-check but for code",
  "comp.secret_scan": "Secret Scanner",
  "comp.secret_scan.desc":
    "Prevents uploading passwords or API keys to the internet",
  "comp.agent_naming": "Agent Naming",
  "comp.agent_naming.desc":
    "Names every AI task clearly so you can track what it did",
  "comp.observability": "Activity Log",
  "comp.observability.desc":
    "Records everything AI does — like a dashcam for your code",
  "comp.verify_commit": "Pre-Commit Check",
  "comp.verify_commit.desc":
    "Runs tests before saving — makes sure nothing is broken",
  "comp.review_gate": "Review Reminder",
  "comp.review_gate.desc":
    "Reminds you about unsaved changes when AI finishes",
  "comp.plan_impl_gate": "Plan Guard",
  "comp.plan_impl_gate.desc":
    "Reminds you to save your plan before starting work",
  "comp.skill_security": "Plugin Shield",
  "comp.skill_security.desc":
    "Blocks malicious plugins from stealing your data",
  "comp.voice_notify": "Voice Alerts",
  "comp.voice_notify.desc":
    "AI speaks to you when done (needs text-to-speech)",
  "comp.pm_autopilot": "PM Auto-Pilot",
  "comp.pm_autopilot.desc":
    "Auto-tracks work progress on GitHub (needs GitHub CLI)",

  // Tool Config
  "config.title": "Tool Paths",
  "config.subtitle": "We detected these tools — change only if needed",
  "config.advanced": "Advanced Settings",
  "config.python": "Python Path",
  "config.ruff": "ruff (Python formatter)",
  "config.ruffPlaceholder": "Leave empty to skip Python formatting",
  "config.biome": "biome (JS/TS formatter)",
  "config.biomePlaceholder": "Leave empty to skip JS/TS formatting",
  "config.detected": "Auto-detected",
  "config.manual": "Manual",
  "config.installed": "Installed",
  "config.notInstalled": "Not installed",
  "config.installCmd": "Install with:",
  "config.copy": "Copy",
  "config.copied": "Copied!",
  "config.requiredLabel": "Required",
  "config.optionalLabel": "Optional",
  "config.checkedInStep2": "Verified in Step 2",

  // Tool names & descriptions
  "tool.git": "git",
  "tool.git.desc":
    "Version control system. Essential for tracking code changes.",
  "tool.ruff": "ruff",
  "tool.ruff.desc":
    "Python code formatter and linter. Keeps your Python code clean and consistent.",
  "tool.biome": "biome",
  "tool.biome.desc":
    "JavaScript/TypeScript formatter and linter. Like spell-check for web code.",
  "tool.gh": "GitHub CLI",
  "tool.gh.desc":
    "GitHub command-line tool. Required only if you want automatic issue tracking.",

  // Installing
  "install.title": "Installing Hooks",
  "install.subtitle": "Setting up your safety net...",
  "install.step1": "Copying dispatcher...",
  "install.step2": "Registering hook events...",
  "install.step3": "Generating config...",
  "install.step4": "Verifying installation...",
  "install.success": "Step completed",
  "install.error": "Error",
  "install.failed": "Installation failed",
  "install.failedDesc": "Something went wrong. Check the error and try again.",
  "install.retry": "Retry",

  // Complete
  "complete.title": "Installation Complete!",
  "complete.subtitle": "Your AI coding assistant is now protected",
  "complete.restart": "Restart Claude Code to activate.",
  "complete.enabled": "Enabled protections:",
  "complete.enjoy": "Happy coding!",
} as const;

export default en;
