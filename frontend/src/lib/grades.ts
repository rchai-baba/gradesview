import type { ApiAssignment, ApiCategory, ApiClass, ApiMarkingPeriod } from "@/types";

/** Prefer Exam/Final category for what-if; otherwise first category. */
export function pickExamCategory(categories: ApiCategory[]): string {
  if (!categories.length) return "";
  const hit = categories.find((c) => /exam|final|semester|midterm/i.test(c.name));
  return hit?.name ?? categories[0].name;
}

export function getLetterGrade(percent: number | null | undefined): string {
  if (percent == null) return "N/A";
  if (percent >= 93) return "A";
  if (percent >= 90) return "A-";
  if (percent >= 87) return "B+";
  if (percent >= 83) return "B";
  if (percent >= 80) return "B-";
  if (percent >= 77) return "C+";
  if (percent >= 73) return "C";
  if (percent >= 70) return "C-";
  if (percent >= 67) return "D+";
  if (percent >= 63) return "D";
  if (percent >= 60) return "D-";
  return "E";
}

export function getGradeColor(letter: string | null | undefined): string {
  if (!letter || letter === "N/A") return "text-muted-foreground";
  if (letter.startsWith("A")) return "text-grade-a";
  if (letter.startsWith("B")) return "text-grade-b";
  if (letter.startsWith("C")) return "text-grade-c";
  if (letter.startsWith("D")) return "text-grade-d";
  return "text-grade-f";
}

/** Per-category earned / total; extra credit adds to earned only (no denominator). */
export function categoryTotals(
  assignments: ApiAssignment[],
): Map<string, { earned: number; total: number }> {
  const m = new Map<string, { earned: number; total: number }>();
  for (const a of assignments) {
    if (a.excused) continue;
    const cat = a.category || "Other";
    const cur = m.get(cat) ?? { earned: 0, total: 0 };
    cur.earned += a.pointsEarned;
    if (a.pointsTotal > 0) cur.total += a.pointsTotal;
    m.set(cat, cur);
  }
  return m;
}

/** Category percent 0–100; if only EC in category, treat as 100 when earned > 0. */
export function categoryPercent(earned: number, total: number): number {
  if (total > 0) return (earned / total) * 100;
  if (earned > 0) return 100;
  return 0;
}

/**
 * Weighted overall 0–100. Weights should sum to ~100; names match assignment categories.
 */
export function computeWeightedPercent(
  assignments: ApiAssignment[],
  categories: ApiCategory[],
): number | null {
  if (!categories.length) return computeSimplePercent(assignments);
  const totals = categoryTotals(assignments);
  const weightSum = categories.reduce((s, c) => s + c.weight, 0);
  if (weightSum <= 0) return computeSimplePercent(assignments);

  let acc = 0;
  let anyData = false;
  for (const c of categories) {
    const t = totals.get(c.name);
    if (!t || (t.earned === 0 && t.total === 0)) continue;
    anyData = true;
    const pct = categoryPercent(t.earned, t.total);
    acc += (c.weight / weightSum) * pct;
  }
  return anyData ? acc : null;
}

export function computeSimplePercent(assignments: ApiAssignment[]): number | null {
  let earned = 0;
  let total = 0;
  for (const a of assignments) {
    if (a.excused) continue;
    earned += a.pointsEarned;
    if (a.pointsTotal > 0) total += a.pointsTotal;
  }
  return total === 0 ? null : (earned / total) * 100;
}

/** Unweighted: points needed on next assignment of fixed size to reach target % overall. */
export function getRequiredScoreForGrade(
  currentEarned: number,
  currentTotal: number,
  nextAssignmentTotal: number,
  targetPercent: number,
): number {
  const needed = (targetPercent / 100) * (currentTotal + nextAssignmentTotal) - currentEarned;
  return Math.max(0, needed);
}

/**
 * Weighted: minimum score x on a final worth `finalPoints` in category `examCategoryName`
 * to reach at least `targetPercent` overall. Category grade after final: 100*(E+x)/(T+F).
 */
export function getRequiredScoreWeighted(
  assignments: ApiAssignment[],
  categories: ApiCategory[],
  examCategoryName: string,
  finalPoints: number,
  targetPercent: number,
): number | null {
  if (finalPoints <= 0 || !categories.length) return null;
  const examCat = categories.find(
    (c) => c.name.toLowerCase() === examCategoryName.toLowerCase(),
  );
  if (!examCat) return null;

  const weightSum = categories.reduce((s, c) => s + c.weight, 0);
  if (weightSum <= 0) return null;

  const w = examCat.weight / weightSum;
  if (w <= 0) return null;

  const totals = categoryTotals(assignments);
  let overall = 0;
  for (const c of categories) {
    const t = totals.get(c.name) ?? { earned: 0, total: 0 };
    const pct = categoryPercent(t.earned, t.total);
    overall += (c.weight / weightSum) * pct;
  }

  const tExam = totals.get(examCat.name) ?? { earned: 0, total: 0 };
  const P = categoryPercent(tExam.earned, tExam.total);
  const rhs = (targetPercent - overall + w * P) / w;
  const E = tExam.earned;
  const T = tExam.total;
  const F = finalPoints;
  const x = ((T + F) * rhs) / 100 - E;
  if (Number.isNaN(x)) return null;
  return Math.max(0, Math.min(F, x));
}

export interface ClassEdits {
  assignments: Record<string, { pointsEarned: number; pointsTotal: number }>;
  addedAssignments: ApiAssignment[];
  nextAssignmentTotal: number;
  examTotalPoints: number;
}

export function editsStorageKey(classId: string, period: string): string {
  return `class-edits-${classId}-${period}`;
}

export function loadEdits(classId: string, period: string): ClassEdits {
  const raw = localStorage.getItem(editsStorageKey(classId, period));
  if (raw) {
    try {
      const o = JSON.parse(raw) as Partial<ClassEdits>;
      return {
        assignments: o.assignments ?? {},
        addedAssignments: o.addedAssignments ?? [],
        nextAssignmentTotal: typeof o.nextAssignmentTotal === "number" ? o.nextAssignmentTotal : 100,
        examTotalPoints: typeof o.examTotalPoints === "number" ? o.examTotalPoints : 100,
      };
    } catch {
      /* fall through */
    }
  }
  return { assignments: {}, addedAssignments: [], nextAssignmentTotal: 100, examTotalPoints: 100 };
}

export function saveEdits(classId: string, period: string, edits: ClassEdits): void {
  localStorage.setItem(editsStorageKey(classId, period), JSON.stringify(edits));
}

export function getEffectiveAssignments(
  base: ApiAssignment[],
  edits: ClassEdits,
): ApiAssignment[] {
  const overrideMap = edits.assignments;
  const merged = base.map((a) => {
    const override = overrideMap[a.id];
    const differs = override && (override.pointsEarned !== a.pointsEarned || override.pointsTotal !== a.pointsTotal);
    if (differs) {
      return { ...a, pointsEarned: override.pointsEarned, pointsTotal: override.pointsTotal };
    }
    return a;
  });
  return [...merged, ...edits.addedAssignments];
}

export function computeEffectiveMPGrade(
  classId: string,
  mp: ApiMarkingPeriod,
): number | null {
  const edits = loadEdits(classId, mp.label);
  const eff = getEffectiveAssignments(mp.assignments, edits);
  const isWeighting = mp.isAssignmentWeightingOn ?? false;
  const cats = mp.assignmentCategories ?? [];

  const cal = isWeighting && cats.length
    ? computeWeightedPercent(eff, cats)
    : computeSimplePercent(eff);

  const hasEdits = Object.keys(edits.assignments).length > 0 || edits.addedAssignments.length > 0;
  const reported = mp.percentage;

  if (hasEdits || (reported === 0 && cal === null)) return cal;
  return reported ?? cal;
}
