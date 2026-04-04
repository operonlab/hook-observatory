import type en from "./en";

const zhTW: Record<keyof typeof en, string> = {
  // Step indicator
  "step.welcome": "歡迎",
  "step.dependencies": "環境檢查",
  "step.components": "選擇元件",
  "step.config": "工具設定",
  "step.install": "安裝中",
  "step.complete": "完成",

  // Navigation
  "nav.next": "下一步",
  "nav.back": "上一步",
  "nav.getStarted": "開始安裝",
  "nav.close": "關閉",
  "nav.skip": "略過",

  // Welcome
  "welcome.title": "hook-observatory",
  "welcome.subtitle": "你的 AI 寫程式助手的安全護欄",
  "welcome.description":
    "用智慧 hook 保護你的程式碼庫——阻擋危險指令、防止機密外洩，並保留完整操作紀錄。",
  "welcome.version": "v1.0.0",

  // Dependency Check
  "deps.title": "環境檢查",
  "deps.subtitle": "確認一切就緒",
  "deps.checking": "檢查中...",
  "deps.found": "找到於",
  "deps.notFound": "未找到",
  "deps.install": "安裝",
  "deps.allGood": "所有相依項目就緒！",
  "deps.missing": "部分相依項目缺失，請先安裝後再繼續。",
  "deps.python": "Python 3.12+",
  "deps.pythonDesc": "執行 hook 處理器所需",
  "deps.claudeCode": "Claude Code",
  "deps.claudeCodeDesc": "要保護的 AI 寫程式助手",
  "deps.git": "git",
  "deps.gitDesc": "版本控制系統",
  "deps.retry": "重新檢查",

  // Component Selection
  "comp.title": "選擇你的防護網",
  "comp.subtitle": "選擇要啟用的防護措施",
  "comp.required": "必要",
  "comp.requiredDesc": "核心安全 — 始終啟用",
  "comp.optional": "建議",
  "comp.optionalDesc": "額外防護 — 預設啟用",
  "comp.advanced": "整合",
  "comp.advancedDesc": "進階功能 — 需額外設定",

  // Component names & descriptions
  "comp.bash_safety": "指令防護",
  "comp.bash_safety.desc": "阻擋危險指令——防止 AI 意外刪除你的檔案",
  "comp.auto_format": "自動格式化",
  "comp.auto_format.desc": "編輯後自動格式化程式碼——就像程式碼的拼字檢查",
  "comp.secret_scan": "機密掃描",
  "comp.secret_scan.desc": "防止密碼或 API 金鑰被上傳到網路上",
  "comp.agent_naming": "代理命名",
  "comp.agent_naming.desc": "為每個 AI 任務清楚命名，方便追蹤它做了什麼",
  "comp.observability": "活動紀錄",
  "comp.observability.desc": "記錄 AI 做的每件事——就像程式碼的行車紀錄器",
  "comp.verify_commit": "提交前檢查",
  "comp.verify_commit.desc": "存檔前先跑測試——確保沒有東西壞掉",
  "comp.review_gate": "審閱提醒",
  "comp.review_gate.desc": "AI 完成時提醒你未儲存的變更",
  "comp.plan_impl_gate": "計畫守衛",
  "comp.plan_impl_gate.desc": "開始工作前提醒你先儲存計畫",
  "comp.skill_security": "外掛防護",
  "comp.skill_security.desc": "阻擋惡意外掛竊取你的資料",
  "comp.voice_notify": "語音通知",
  "comp.voice_notify.desc": "AI 完成時語音通知你（需要文字轉語音）",
  "comp.pm_autopilot": "專案自動追蹤",
  "comp.pm_autopilot.desc": "自動追蹤 GitHub 上的工作進度（需要 GitHub CLI）",

  // Tool Config
  "config.title": "工具路徑",
  "config.subtitle": "我們偵測到這些工具——只在需要時修改",
  "config.advanced": "進階設定",
  "config.python": "Python 路徑",
  "config.ruff": "ruff（Python 格式化工具）",
  "config.ruffPlaceholder": "留空則略過 Python 格式化",
  "config.biome": "biome（JS/TS 格式化工具）",
  "config.biomePlaceholder": "留空則略過 JS/TS 格式化",
  "config.detected": "自動偵測",
  "config.manual": "手動設定",

  // Installing
  "install.title": "正在安裝 Hook",
  "install.subtitle": "正在設定你的防護網...",
  "install.step1": "複製 dispatcher...",
  "install.step2": "註冊 hook 事件...",
  "install.step3": "產生設定檔...",
  "install.step4": "驗證安裝...",
  "install.success": "步驟完成",
  "install.error": "錯誤",
  "install.failed": "安裝失敗",
  "install.failedDesc": "發生錯誤，請檢查錯誤訊息後重試。",
  "install.retry": "重試",

  // Complete
  "complete.title": "安裝完成！",
  "complete.subtitle": "你的 AI 寫程式助手已受到保護",
  "complete.restart": "重新啟動 Claude Code 即可生效。",
  "complete.enabled": "已啟用的防護：",
  "complete.enjoy": "祝程式寫得愉快！",
};

export default zhTW;
