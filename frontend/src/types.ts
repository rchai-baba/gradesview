export interface ApiAssignment {
  id: string;
  title: string;
  pointsEarned: number;
  pointsTotal: number;
  category: string;
  dueDate: string;
  excused: boolean;
  isForGrading: boolean;
  /** True when points are extra credit (e.g. 2/0). */
  isExtraCredit?: boolean;
  debugFields?: Record<string, any>;
}

export interface ApiCategory {
  name: string;
  weight: number;
}

export interface ApiMarkingPeriod {
  label: string;
  percentage: number | null;
  calculatedMark: string | null;
  assignments: ApiAssignment[];
  isAssignmentWeightingOn?: boolean;
  assignmentCategories?: ApiCategory[];
  /** Flag to prevent infinite loading of marking periods with 0 assignments. */
  assignmentsLoaded?: boolean;
}

export interface ApiClass {
  id: string;
  name: string;
  teacherName: string;
  gradingType: "cumulative" | "noncumulative";
  percentage: number | null;
  calculatedMark: string | null;
  currentPeriod: string;
  markingPeriods: ApiMarkingPeriod[];
  assignments: ApiAssignment[];
  isAssignmentWeightingOn?: boolean;
  assignmentCategories?: ApiCategory[];
  /** Present when S1+S2 Synergy rows were merged into one card */
  mergedFromIds?: string[];
  /** False after fast login until /api/class-detail fills assignments */
  assignmentsLoaded?: boolean;
  error?: string;
}

export interface ApiResponse {
  student: { name: string | null };
  periods: string[];
  classes: ApiClass[];
  /** Period labels per semester bucket (from backend course_merge_config.json). */
  semesterGroups?: string[][];
  fetchMode?: "full" | "current_period_only" | "cards_only";
}
