export type Role = "patient" | "examiner" | "admin";
export type Stage = "in_progress" | "awaiting_review" | "released";

export interface PatientProfile {
  id: number;
  name: string;
  date_of_birth: string | null;
  sex: string | null;
  education_years: number | null;
}

export interface ExaminerProfile {
  id: number;
  name: string;
  title: string | null;
  organization: string | null;
}

export interface Me {
  id: string;
  email: string;
  role: Role | null;
  deactivated: boolean;
  profile?: PatientProfile | ExaminerProfile;
}

export interface TestSettings {
  voice_speed: "normal" | "slow";
  extra_answer_seconds: number;
  allow_skip: boolean;
  intro: string;
}

export interface Template {
  id: number;
  examiner_id: number;
  name: string;
  description: string | null;
  tasks: number[];
  settings: TestSettings;
  published: boolean;
  max_points: number;
  standard: boolean;
  updated_at: string;
}

export interface ExaminerChoice extends ExaminerProfile {
  tests: Template[];
}

export interface TaskInfo {
  number: number;
  id: string;
  title: string;
  description: string;
  camera: boolean;
  section: string;
  max: number;
}

export interface SheetSection {
  title: string;
  key: string;
  max: number;
  score: number;
  rows: { label: string; score: number; max: number }[];
}

export interface PatientSession {
  id: number;
  template_name: string;
  tasks: number[];
  settings: TestSettings;
  stage: Stage;
  started_at: string;
  finished_at: string | null;
  examiner: ExaminerProfile;
  done_tasks: number[];
  result?: {
    total: number;
    education_bonus: number;
    adjusted_total: number;
    max_total: number;
    released_at: string;
    note: string | null;
    sections: Record<string, { score: number; max: number }>;
    sheet_sections: SheetSection[];
  };
}

export interface TaskResult {
  task: string;
  score: number;
  max_score: number;
  criteria: Record<string, number> | null;
  completed: boolean;
  reason: string;
  details: any;
  evidence_urls: string[];
  auto_score: number | null;
  auto_criteria: Record<string, number> | null;
  corrected_at: string | null;
  correction_note: string | null;
}

export interface ExaminerSession {
  id: number;
  patient_id: number;
  template_name: string;
  tasks: number[];
  stage: Stage;
  started_at: string;
  finished_at: string | null;
  released_at: string | null;
  review_note: string | null;
  total: number | null;
  max_total: number | null;
  education_bonus: number | null;
  adjusted_total: number | null;
  done_tasks: number[];
  patient: PatientProfile;
  report?: {
    total: number;
    max_total: number;
    tasks: Record<string, TaskResult>;
    sections: Record<string, { score: number; max: number }>;
  };
  sheet?: {
    sections: SheetSection[];
    education_bonus: number;
    memory_recall: Record<string, string[]>;
  };
}

export interface AdminUser {
  id: string;
  email: string;
  role: Role;
  name: string;
  active: boolean;
  added_by_admin: boolean;
  details: string | null;
  tests: number;
  awaiting_review?: number;
}

export interface Invite {
  id: number;
  name: string;
  email: string;
  date_of_birth: string;
  token: string;
  patient_id: number | null;
  joined_at: string | null;
  created_at: string;
}

export interface Stats {
  patients: number;
  awaiting_review: number;
  released: number;
  in_progress: number;
  average_full: number | null;
}
