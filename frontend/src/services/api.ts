import type { ApiClass, ApiMarkingPeriod, ApiResponse } from "@/types";

const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

/** localStorage: cards_only | current_period_only | full */
export const FETCH_MODE_STORAGE_KEY = "grades-fetch-mode";

/** Tab-only credentials; cleared on logout */
export const SESSION_CREDENTIALS_KEY = "gradesview-session-creds";

export type LoginFetchMode = "cards_only" | "current_period_only" | "full";

export function getLoginFetchMode(): LoginFetchMode {
  try {
    const v = localStorage.getItem(FETCH_MODE_STORAGE_KEY);
    if (v === "current_period_only" || v === "full") return v;
    if (v === "fast") return "current_period_only"; // legacy
    return "cards_only";
  } catch {
    return "cards_only";
  }
}

export function saveSessionCredentials(username: string, password: string): void {
  try {
    sessionStorage.setItem(SESSION_CREDENTIALS_KEY, JSON.stringify({ username, password }));
  } catch {
    /* ignore */
  }
}

export function getSessionCredentials(): { username: string; password: string } | null {
  try {
    const raw = sessionStorage.getItem(SESSION_CREDENTIALS_KEY);
    if (!raw) return null;
    const o = JSON.parse(raw) as { username?: string; password?: string };
    if (o.username && o.password) return { username: o.username, password: o.password };
    return null;
  } catch {
    return null;
  }
}

export function clearSessionCredentials(): void {
  try {
    sessionStorage.removeItem(SESSION_CREDENTIALS_KEY);
  } catch {
    /* ignore */
  }
}

export async function loginAndFetchGrades(username: string, password: string): Promise<ApiResponse> {
  const fetch_mode = getLoginFetchMode();
  const res = await fetch(`${API_URL}/api/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, fetch_mode }),
  });

  if (res.status === 401) throw new Error("Invalid credentials");
  if (res.status === 502) throw new Error("StudentVue is not responding. Try again in a moment.");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { error?: string }).error ?? "Failed to load grades");
  }

  return res.json() as Promise<ApiResponse>;
}

export interface ClassDetailResponse {
  markingPeriod: ApiMarkingPeriod;
  synergyClassIdUsed: number;
  fetchMode: string;
}

export async function fetchClassDetail(params: {
  username: string;
  password: string;
  markingPeriod: string;
  synergyClassIds: number[];
}): Promise<ClassDetailResponse> {
  const res = await fetch(`${API_URL}/api/class-detail`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: params.username,
      password: params.password,
      markingPeriod: params.markingPeriod,
      synergyClassIds: params.synergyClassIds,
    }),
  });
  if (res.status === 401) throw new Error("Invalid credentials");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { error?: string }).error ?? "Failed to load class");
  }
  return res.json() as Promise<ClassDetailResponse>;
}

const STORAGE_KEY = "grades-data";

export function saveGrades(data: ApiResponse): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

export function loadGrades(): ApiResponse | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as ApiResponse;
  } catch {
    return null;
  }
}

/** Merge one marking period into cached grades and persist. */
export function patchClassMarkingPeriod(classId: string, periodLabel: string, mp: ApiMarkingPeriod): void {
  const data = loadGrades();
  if (!data) return;
  const c = data.classes.find((x) => x.id === classId);
  if (!c) return;
  const idx = c.markingPeriods.findIndex((m) => m.label === periodLabel);
  if (idx >= 0) {
    c.markingPeriods[idx] = { ...mp, assignmentsLoaded: true };
  }
  if (c.currentPeriod === periodLabel) {
    c.assignments = mp.assignments;
    c.isAssignmentWeightingOn = mp.isAssignmentWeightingOn ?? false;
    c.assignmentCategories = mp.assignmentCategories ?? [];
    const st = mp.percentage != null ? { percentage: mp.percentage, calculatedMark: mp.calculatedMark } : null;
    if (st) {
      c.percentage = st.percentage ?? c.percentage;
      c.calculatedMark = st.calculatedMark ?? c.calculatedMark;
    }
    c.assignmentsLoaded = true;
  }
  saveGrades(data);
}

export function clearGrades(): void {
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem("grades-auth");
  clearSessionCredentials();
}
