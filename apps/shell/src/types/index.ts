export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  status: string;
  created_at: string;
}

export interface AppInfo {
  id: string;
  name: string;
  description: string;
  icon: string;
  path: string;
  color: string;
  status: "available" | "coming-soon";
}
