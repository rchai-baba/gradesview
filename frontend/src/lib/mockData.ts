export interface Assignment {
  id: string;
  title: string;
  pointsEarned: number;
  pointsTotal: number;
}

export interface MarkingPeriod {
  label: string;
  assignments: Assignment[];
}

export interface ClassData {
  id: string;
  name: string;
  gradingType: "cumulative" | "noncumulative";
  assignments: Assignment[]; // used for cumulative
  markingPeriods?: MarkingPeriod[]; // used for noncumulative (2 periods)
}

export const mockClasses: ClassData[] = [
  {
    id: "calc",
    name: "Calculus II",
    gradingType: "cumulative",
    assignments: [
      { id: "1", title: "Homework 1 — Integration by Parts", pointsEarned: 47, pointsTotal: 50 },
      { id: "2", title: "Quiz 1 — Sequences & Series", pointsEarned: 18, pointsTotal: 20 },
      { id: "3", title: "Homework 2 — Taylor Series", pointsEarned: 42, pointsTotal: 50 },
      { id: "4", title: "Midterm Exam", pointsEarned: 88, pointsTotal: 100 },
      { id: "5", title: "Homework 3 — Polar Coordinates", pointsEarned: 49, pointsTotal: 50 },
      { id: "6", title: "Quiz 2 — Convergence Tests", pointsEarned: 16, pointsTotal: 20 },
      { id: "7", title: "Homework 4 — Parametric Equations", pointsEarned: 44, pointsTotal: 50 },
      { id: "8", title: "Homework 5 — Vector Fields", pointsEarned: 46, pointsTotal: 50 },
      { id: "9", title: "Quiz 3 — Arc Length", pointsEarned: 19, pointsTotal: 20 },
      { id: "10", title: "Homework 6 — Surface Area", pointsEarned: 41, pointsTotal: 50 },
    ],
  },
  {
    id: "physics",
    name: "Physics I",
    gradingType: "noncumulative",
    assignments: [],
    markingPeriods: [
      {
        label: "Marking Period 1",
        assignments: [
          { id: "1", title: "Lab 1 — Kinematics", pointsEarned: 24, pointsTotal: 25 },
          { id: "2", title: "Problem Set 1", pointsEarned: 85, pointsTotal: 100 },
          { id: "3", title: "Lab 2 — Newton's Laws", pointsEarned: 23, pointsTotal: 25 },
          { id: "4", title: "Midterm Exam", pointsEarned: 76, pointsTotal: 100 },
          { id: "5", title: "Problem Set 2", pointsEarned: 90, pointsTotal: 100 },
          { id: "6", title: "Lab 3 — Friction", pointsEarned: 22, pointsTotal: 25 },
          { id: "7", title: "Quiz 1 — Free Body Diagrams", pointsEarned: 17, pointsTotal: 20 },
        ],
      },
      {
        label: "Marking Period 2",
        assignments: [
          { id: "8", title: "Lab 4 — Conservation of Energy", pointsEarned: 24, pointsTotal: 25 },
          { id: "9", title: "Problem Set 3", pointsEarned: 82, pointsTotal: 100 },
          { id: "10", title: "Lab 5 — Momentum", pointsEarned: 21, pointsTotal: 25 },
          { id: "11", title: "Quiz 2 — Work & Energy", pointsEarned: 18, pointsTotal: 20 },
          { id: "12", title: "Problem Set 4", pointsEarned: 88, pointsTotal: 100 },
          { id: "13", title: "Lab 6 — Rotational Motion", pointsEarned: 23, pointsTotal: 25 },
          { id: "14", title: "Midterm Exam 2", pointsEarned: 81, pointsTotal: 100 },
        ],
      },
    ],
  },
  {
    id: "english",
    name: "English Composition",
    gradingType: "cumulative",
    assignments: [
      { id: "1", title: "Essay 1 — Narrative", pointsEarned: 88, pointsTotal: 100 },
      { id: "2", title: "Peer Review Workshop", pointsEarned: 10, pointsTotal: 10 },
      { id: "3", title: "Essay 2 — Argumentative", pointsEarned: 91, pointsTotal: 100 },
      { id: "4", title: "Reading Response Journal", pointsEarned: 45, pointsTotal: 50 },
      { id: "5", title: "Essay 3 — Expository", pointsEarned: 85, pointsTotal: 100 },
      { id: "6", title: "Grammar Quiz 1", pointsEarned: 18, pointsTotal: 20 },
      { id: "7", title: "Essay 4 — Research Paper Draft", pointsEarned: 78, pointsTotal: 100 },
      { id: "8", title: "Vocabulary Test 1", pointsEarned: 43, pointsTotal: 50 },
      { id: "9", title: "Grammar Quiz 2", pointsEarned: 19, pointsTotal: 20 },
    ],
  },
  {
    id: "cs",
    name: "Intro to Computer Science",
    gradingType: "noncumulative",
    assignments: [],
    markingPeriods: [
      {
        label: "Marking Period 1",
        assignments: [
          { id: "1", title: "Project 1 — Hello World", pointsEarned: 100, pointsTotal: 100 },
          { id: "2", title: "Homework 1 — Variables & Loops", pointsEarned: 48, pointsTotal: 50 },
          { id: "3", title: "Project 2 — Calculator App", pointsEarned: 92, pointsTotal: 100 },
          { id: "4", title: "Quiz 1 — Data Structures", pointsEarned: 17, pointsTotal: 20 },
          { id: "5", title: "Midterm Exam", pointsEarned: 82, pointsTotal: 100 },
          { id: "6", title: "Homework 2 — Functions", pointsEarned: 46, pointsTotal: 50 },
        ],
      },
      {
        label: "Marking Period 2",
        assignments: [
          { id: "7", title: "Project 3 — Todo App", pointsEarned: 95, pointsTotal: 100 },
          { id: "8", title: "Homework 3 — OOP Basics", pointsEarned: 44, pointsTotal: 50 },
          { id: "9", title: "Quiz 2 — Algorithms", pointsEarned: 16, pointsTotal: 20 },
          { id: "10", title: "Project 4 — API Integration", pointsEarned: 88, pointsTotal: 100 },
          { id: "11", title: "Homework 4 — Recursion", pointsEarned: 42, pointsTotal: 50 },
          { id: "12", title: "Final Exam", pointsEarned: 85, pointsTotal: 100 },
        ],
      },
    ],
  },
  {
    id: "history",
    name: "World History",
    gradingType: "cumulative",
    assignments: [
      { id: "1", title: "Chapter 1 Reading Quiz", pointsEarned: 9, pointsTotal: 10 },
      { id: "2", title: "Research Paper Outline", pointsEarned: 23, pointsTotal: 25 },
      { id: "3", title: "Midterm Essay Exam", pointsEarned: 78, pointsTotal: 100 },
      { id: "4", title: "Chapter 2 Reading Quiz", pointsEarned: 8, pointsTotal: 10 },
      { id: "5", title: "Group Presentation", pointsEarned: 43, pointsTotal: 50 },
      { id: "6", title: "Chapter 3 Reading Quiz", pointsEarned: 9, pointsTotal: 10 },
      { id: "7", title: "Document Analysis Essay", pointsEarned: 82, pointsTotal: 100 },
      { id: "8", title: "Map Quiz — Ancient Civilizations", pointsEarned: 18, pointsTotal: 20 },
      { id: "9", title: "Chapter 4 Reading Quiz", pointsEarned: 7, pointsTotal: 10 },
      { id: "10", title: "Timeline Project", pointsEarned: 46, pointsTotal: 50 },
    ],
  },
  {
    id: "chem",
    name: "Chemistry I",
    gradingType: "noncumulative",
    assignments: [],
    markingPeriods: [
      {
        label: "Marking Period 1",
        assignments: [
          { id: "1", title: "Lab 1 — Density Measurements", pointsEarned: 22, pointsTotal: 25 },
          { id: "2", title: "Problem Set 1 — Stoichiometry", pointsEarned: 43, pointsTotal: 50 },
          { id: "3", title: "Lab 2 — Chemical Reactions", pointsEarned: 21, pointsTotal: 25 },
          { id: "4", title: "Midterm Exam", pointsEarned: 71, pointsTotal: 100 },
          { id: "5", title: "Problem Set 2 — Moles", pointsEarned: 40, pointsTotal: 50 },
          { id: "6", title: "Lab 3 — Titration", pointsEarned: 23, pointsTotal: 25 },
        ],
      },
      {
        label: "Marking Period 2",
        assignments: [
          { id: "7", title: "Lab 4 — Gas Laws", pointsEarned: 24, pointsTotal: 25 },
          { id: "8", title: "Problem Set 3 — Equilibrium", pointsEarned: 44, pointsTotal: 50 },
          { id: "9", title: "Quiz 1 — Thermodynamics", pointsEarned: 15, pointsTotal: 20 },
          { id: "10", title: "Lab 5 — Electrochemistry", pointsEarned: 20, pointsTotal: 25 },
          { id: "11", title: "Midterm Exam 2", pointsEarned: 78, pointsTotal: 100 },
        ],
      },
    ],
  },
  {
    id: "art",
    name: "Art History",
    gradingType: "cumulative",
    assignments: [
      { id: "1", title: "Museum Visit Report", pointsEarned: 46, pointsTotal: 50 },
      { id: "2", title: "Slide Identification Quiz", pointsEarned: 36, pointsTotal: 40 },
      { id: "3", title: "Essay — Renaissance Art", pointsEarned: 87, pointsTotal: 100 },
      { id: "4", title: "Midterm Exam", pointsEarned: 82, pointsTotal: 100 },
      { id: "5", title: "Baroque Period Analysis", pointsEarned: 44, pointsTotal: 50 },
      { id: "6", title: "Slide Quiz 2 — Impressionism", pointsEarned: 34, pointsTotal: 40 },
      { id: "7", title: "Essay — Modern Art Movements", pointsEarned: 90, pointsTotal: 100 },
      { id: "8", title: "Gallery Critique Paper", pointsEarned: 42, pointsTotal: 50 },
      { id: "9", title: "Slide Quiz 3 — Contemporary", pointsEarned: 35, pointsTotal: 40 },
    ],
  },
];

/** Get all active assignments for a class (current marking period for noncumulative) */
export function getCurrentAssignments(cls: ClassData): Assignment[] {
  if (cls.gradingType === "cumulative") return cls.assignments;
  if (cls.markingPeriods && cls.markingPeriods.length >= 2) {
    return cls.markingPeriods[1].assignments; // current = second marking period
  }
  return cls.assignments;
}

/** Get previous marking period assignments */
export function getPreviousAssignments(cls: ClassData): Assignment[] | null {
  if (cls.gradingType === "noncumulative" && cls.markingPeriods && cls.markingPeriods.length >= 2) {
    return cls.markingPeriods[0].assignments;
  }
  return null;
}

/** Calculate percent from assignments */
export function calcPercent(assignments: Assignment[]): number {
  const earned = assignments.reduce((s, a) => s + a.pointsEarned, 0);
  const total = assignments.reduce((s, a) => s + a.pointsTotal, 0);
  return total === 0 ? 0 : (earned / total) * 100;
}

/** Get overall class percent (accounts for marking period averaging) */
export function getClassPercent(cls: ClassData): number {
  if (cls.gradingType === "cumulative") {
    return calcPercent(cls.assignments);
  }
  if (cls.markingPeriods && cls.markingPeriods.length >= 2) {
    const mp1 = calcPercent(cls.markingPeriods[0].assignments);
    const mp2 = calcPercent(cls.markingPeriods[1].assignments);
    return (mp1 + mp2) / 2;
  }
  return calcPercent(cls.assignments);
}

export function getLetterGrade(percent: number): string {
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
  return "F";
}

export function getGradeColor(letter: string): string {
  if (letter.startsWith("A")) return "text-grade-a";
  if (letter.startsWith("B")) return "text-grade-b";
  if (letter.startsWith("C")) return "text-grade-c";
  if (letter.startsWith("D")) return "text-grade-d";
  return "text-grade-f";
}

export function getRequiredScoreForGrade(
  currentEarned: number,
  currentTotal: number,
  nextAssignmentTotal: number,
  targetPercent: number
): number {
  const needed = (targetPercent / 100) * (currentTotal + nextAssignmentTotal) - currentEarned;
  return Math.max(0, needed);
}

/**
 * For noncumulative: calculate what score is needed on the next assignment
 * in the current marking period so the overall average (50% MP1 + 50% MP2) >= targetPercent.
 * MP1 percent is fixed; we solve for x in:
 * (mp1Pct + (currentEarned + x) / (currentTotal + nextTotal) * 100) / 2 >= targetPercent
 * => (currentEarned + x) / (currentTotal + nextTotal) >= (2 * targetPercent - mp1Pct) / 100
 */
export function getRequiredScoreForGradeNoncumulative(
  mp1Percent: number,
  currentEarned: number,
  currentTotal: number,
  nextAssignmentTotal: number,
  targetPercent: number
): number {
  const requiredCurrentPct = 2 * targetPercent - mp1Percent;
  const needed = (requiredCurrentPct / 100) * (currentTotal + nextAssignmentTotal) - currentEarned;
  return Math.max(0, needed);
}
