// Dates, ages, score bands and the task-order rules shown on screen.

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? iso + "T00:00:00" : iso);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function fmtDateTime(iso: string | null | undefined) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function age(dob: string | null | undefined) {
  if (!dob) return null;
  const d = new Date(dob + "T00:00:00"), n = new Date();
  let a = n.getFullYear() - d.getFullYear();
  if (n.getMonth() < d.getMonth() || (n.getMonth() === d.getMonth() && n.getDate() < d.getDate())) a--;
  return a;
}

/** MoCA: 26 or more out of 30 is in the normal range. */
export function band(score: number | null | undefined, max: number | null | undefined) {
  if (score == null || max !== 30) return null;
  return score >= 26 ? { cls: "good", label: "Normal range (26+)" } : { cls: "warn", label: "Below 26" };
}

export function patientLine(p: { date_of_birth: string | null; sex: string | null; education_years: number | null }) {
  const a = age(p.date_of_birth);
  return [a != null ? `${a} yrs` : null, p.sex, p.education_years != null ? `${p.education_years} yrs education` : null]
    .filter(Boolean).join(" · ");
}

export function greeting(now = new Date()) {
  const h = now.getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

const MEMORY_TASK = 5, RECALL_TASK = 12;

/** Same rule as the server: delayed recall needs the words to have been learned first. */
export function orderProblem(tasks: number[]) {
  if (!tasks.length) return "Choose at least one task.";
  const recall = tasks.indexOf(RECALL_TASK);
  if (recall >= 0 && !tasks.slice(0, recall).includes(MEMORY_TASK)) {
    return "Delayed recall needs Memory (learning) earlier in the test.";
  }
  return null;
}

export function isStandardOrder(tasks: number[]) {
  return tasks.length === 13 && tasks.every((t, i) => t === i + 1);
}
