import type { ApiClass } from "@/types";
import { getLetterGrade, computeEffectiveMPGrade } from "@/lib/grades";

function inferSemesterBuckets(periodLabels: string[]): string[][] {
  if (periodLabels.length <= 1) return [periodLabels];
  const mid = Math.ceil(periodLabels.length / 2);
  return [periodLabels.slice(0, mid), periodLabels.slice(mid)];
}

/** Short label for totals line, e.g. "Marking Period 3" → "mp3" */
export function formatPeriodShort(label: string): string {
  const m = label.match(/marking\s*period\s*(\d+)/i);
  if (m) return `mp${m[1]}`;
  const q = label.match(/\bQ\s*(\d)\b/i);
  if (q) return `q${q[1]}`;
  return label.length <= 10 ? label : `${label.slice(0, 9)}…`;
}

export interface SemesterProjection {
  semesterIndex: number;
  label: string;
  percentage: number;
  letter: string;
  /** Marking periods in this semester with a reported %, in school-year order */
  periodBreakdown: { label: string; displayLabel: string; percentage: number; letter: string }[];
}

/**
 * Average of reported % for marking periods in the same semester bucket as `selectedPeriod`.
 */
export function projectedSemesterGrade(
  cls: ApiClass,
  selectedPeriod: string,
  semesterGroups: string[][] | undefined,
  allPeriodLabels: string[],
): SemesterProjection | null {
  const buckets = semesterGroups?.length ? semesterGroups : inferSemesterBuckets(allPeriodLabels);
  const idx = buckets.findIndex((b) => b.includes(selectedPeriod));
  if (idx < 0) return null;
  const bucketLabels = buckets[idx];

  const periodBreakdown: SemesterProjection["periodBreakdown"] = [];
  for (const pl of bucketLabels) {
    const m = cls.markingPeriods.find((x) => x.label === pl);
    if (!m) continue;
    const p = computeEffectiveMPGrade(cls.id, m);
    if (p == null) continue;
    periodBreakdown.push({
      label: pl,
      displayLabel: formatPeriodShort(pl),
      percentage: p,
      letter: getLetterGrade(p),
    });
  }
  if (!periodBreakdown.length) return null;

  const pct = periodBreakdown.reduce((s, x) => s + x.percentage, 0) / periodBreakdown.length;
  return {
    semesterIndex: idx,
    label: `Semester ${idx + 1}`,
    percentage: pct,
    letter: getLetterGrade(pct),
    periodBreakdown,
  };
}
