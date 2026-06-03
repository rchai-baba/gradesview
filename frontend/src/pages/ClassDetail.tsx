import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  loadGrades,
  fetchClassDetail,
  getSessionCredentials,
  patchClassMarkingPeriod,
} from "@/services/api";
import {
  getLetterGrade,
  getGradeColor,
  getRequiredScoreForGrade,
  getRequiredScoreWeighted,
  computeSimplePercent,
  computeWeightedPercent,
  computeEffectiveMPGrade,
  pickExamCategory,
  type ClassEdits,
  loadEdits,
  saveEdits,
} from "@/lib/grades";
import type { ApiAssignment, ApiCategory, ApiClass } from "@/types";
import { projectedSemesterGrade } from "@/lib/semesterProjection";
import { ArrowLeft, Plus, Pencil, Check, X, Trash2, RotateCcw } from "lucide-react";

const gradeThresholds = [
  { label: "A", percent: 93 },
  { label: "A-", percent: 90 },
  { label: "B+", percent: 87 },
  { label: "B", percent: 83 },
  { label: "B-", percent: 80 },
];

function synergyClassIdsFromClass(cls: ApiClass): number[] {
  if (cls.mergedFromIds?.length) {
    return cls.mergedFromIds.map((id) => parseInt(id, 10)).filter((n) => !Number.isNaN(n));
  }
  const n = parseInt(cls.id, 10);
  return Number.isNaN(n) ? [] : [n];
}

function formatPeriodShort(label: string) {
  return label.replace(/marking period/i, "MP").replace(/quarter/i, "Q");
}

const ClassDetail = () => {
  const { classId } = useParams();
  const navigate = useNavigate();

  const [cacheTick, setCacheTick] = useState(0);
  const data = useMemo(() => loadGrades(), [cacheTick]);
  const cls = data?.classes.find((c) => c.id === classId);

  const [selectedPeriod, setSelectedPeriod] = useState(cls?.currentPeriod ?? "");
  const [examCategoryName, setExamCategoryName] = useState("");

  useEffect(() => {
    if (cls) setSelectedPeriod(cls.currentPeriod);
  }, [cls?.id, cls?.currentPeriod]);

  const activeMp = useMemo(() => {
    if (!cls?.markingPeriods.length) return null;
    return cls.markingPeriods.find((m) => m.label === selectedPeriod) ?? cls.markingPeriods[0];
  }, [cls, selectedPeriod]);

  const categories: ApiCategory[] = useMemo(
    () => activeMp?.assignmentCategories ?? cls?.assignmentCategories ?? [],
    [activeMp, cls?.assignmentCategories],
  );

  const isWeighting = activeMp?.isAssignmentWeightingOn ?? cls?.isAssignmentWeightingOn ?? false;

  useEffect(() => {
    setExamCategoryName(pickExamCategory(categories));
  }, [activeMp?.label, categories]);

  const [edits, setEdits] = useState<ClassEdits>({
    assignments: {},
    addedAssignments: [],
    nextAssignmentTotal: 100,
    examTotalPoints: 100,
  });
  useEffect(() => {
    if (classId && selectedPeriod) setEdits(loadEdits(classId, selectedPeriod));
  }, [classId, selectedPeriod]);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editEarned, setEditEarned] = useState("");
  const [editTotal, setEditTotal] = useState("");
  const [addingNew, setAddingNew] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newEarned, setNewEarned] = useState("");
  const [newTotal, setNewTotal] = useState("");
  const [editingPointsTarget, setEditingPointsTarget] = useState<"next" | "exam" | null>(null);
  const [pointsInput, setPointsInput] = useState("");
  const [analysisMode, setAnalysisMode] = useState<"next" | "exam">("next");
  const [sortKey, setSortKey] = useState<"date" | "score-asc" | "score-desc" | "worth-asc" | "worth-desc" | "name">("date");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const detailFetchRef = useRef(false);
  const [expandedAssignmentId, setExpandedAssignmentId] = useState<string | null>(null);

  useEffect(() => {
    if (!cls || !classId || !selectedPeriod) return;
    const mp = cls.markingPeriods.find((m) => m.label === selectedPeriod);
    if (mp && (mp.assignments.length > 0 || mp.assignmentsLoaded)) {
      setDetailError(null);
      return;
    }
    const creds = getSessionCredentials();
    if (!creds) {
      setDetailError("Sign in again to load assignments (session missing).");
      return;
    }
    const synergyIds = synergyClassIdsFromClass(cls);
    if (!synergyIds.length) {
      setDetailError("Cannot load this class — re-sync with full login.");
      return;
    }
    let cancelled = false;
    (async () => {
      if (detailFetchRef.current) return;
      detailFetchRef.current = true;
      setDetailLoading(true);
      setDetailError(null);
      try {
        const res = await fetchClassDetail({
          username: creds.username,
          password: creds.password,
          markingPeriod: selectedPeriod,
          synergyClassIds: synergyIds,
        });
        if (cancelled) return;
        patchClassMarkingPeriod(classId, selectedPeriod, res.markingPeriod);
        setCacheTick((t) => t + 1);
      } catch (e) {
        if (!cancelled) setDetailError(e instanceof Error ? e.message : "Failed to load assignments");
      } finally {
        detailFetchRef.current = false;
        setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cls?.id, classId, selectedPeriod, cacheTick]);

  const persist = useCallback(
    (next: ClassEdits) => {
      setEdits(next);
      if (classId && selectedPeriod) saveEdits(classId, selectedPeriod, next);
    },
    [classId, selectedPeriod],
  );

  const effectiveAssignments: (ApiAssignment & { edited?: boolean; userAdded?: boolean })[] = useMemo(() => {
    if (!cls || !activeMp) return [];
    const baseAssignments = activeMp.assignments;
    return [
      ...baseAssignments.map((a) => {
        const override = edits.assignments[a.id];
        const differs = override && (
          override.pointsEarned !== a.pointsEarned ||
          override.pointsTotal !== a.pointsTotal
        );
        if (differs) {
          const ec = override.pointsTotal <= 0 && override.pointsEarned > 0;
          return {
            ...a,
            pointsEarned: override.pointsEarned,
            pointsTotal: override.pointsTotal,
            edited: true,
            isExtraCredit: ec,
          };
        }
        return a;
      }),
      ...edits.addedAssignments.map((a) => ({ ...a, userAdded: true })),
    ];
  }, [cls, activeMp, edits]);

  const totalPercent = useMemo(() => {
    if (!cls || !activeMp) return 0;
    if (isWeighting && categories.length) {
      return computeWeightedPercent(effectiveAssignments, categories);
    }
    return computeSimplePercent(effectiveAssignments);
  }, [effectiveAssignments, isWeighting, categories, cls, activeMp]);

  const semesterProj = useMemo(() => {
    if (!cls || !data?.periods?.length) return null;
    return projectedSemesterGrade(cls, selectedPeriod, data.semesterGroups, data.periods);
  }, [cls, selectedPeriod, data?.semesterGroups, data?.periods, edits, cacheTick]);

  const { totalEarned, totalPoints } = useMemo(() => {
    let e = 0;
    let t = 0;
    for (const a of effectiveAssignments) {
      if (a.excused) continue;
      e += a.pointsEarned;
      if (a.pointsTotal > 0) t += a.pointsTotal;
    }
    return { totalEarned: e, totalPoints: t };
  }, [effectiveAssignments]);

  const sortedAssignments = useMemo(() => {
    const arr = [...effectiveAssignments];
    const parseDate = (d: string) => {
      if (!d) return 0;
      const [m, day, y] = d.split("/").map(Number);
      return new Date(y, m - 1, day).getTime();
    };
    if (sortKey === "date") {
      arr.sort((a, b) => parseDate(b.dueDate) - parseDate(a.dueDate));
    } else if (sortKey === "name") {
      arr.sort((a, b) => a.title.localeCompare(b.title));
    } else if (sortKey === "score-asc") {
      arr.sort((a, b) => (a.pointsEarned / (a.pointsTotal || 1)) - (b.pointsEarned / (b.pointsTotal || 1)));
    } else if (sortKey === "score-desc") {
      arr.sort((a, b) => (b.pointsEarned / (b.pointsTotal || 1)) - (a.pointsEarned / (a.pointsTotal || 1)));
    } else if (sortKey === "worth-asc") {
      arr.sort((a, b) => a.pointsTotal - b.pointsTotal);
    } else if (sortKey === "worth-desc") {
      arr.sort((a, b) => b.pointsTotal - a.pointsTotal);
    }
    return arr;
  }, [effectiveAssignments, sortKey]);

  if (!cls || !activeMp) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <p className="text-muted-foreground">Class not found.</p>
      </div>
    );
  }

  function startEdit(a: ApiAssignment & { edited?: boolean }) {
    setEditingId(a.id);
    setEditEarned(String(a.pointsEarned));
    setEditTotal(String(a.pointsTotal));
  }

  function confirmEdit() {
    if (!editingId) return;
    const earned = parseFloat(editEarned);
    const total = parseFloat(editTotal);
    if (isNaN(earned) || isNaN(total) || total < 0) return;
    const base = activeMp.assignments.find((a) => a.id === editingId);
    if (base && earned === base.pointsEarned && total === base.pointsTotal) {
      const nextEdits = { ...edits };
      delete nextEdits.assignments[editingId];
      persist(nextEdits);
      setEditingId(null);
      return;
    }

    const isEc = total === 0 && earned > 0;
    const addedIdx = edits.addedAssignments.findIndex((a) => a.id === editingId);
    if (addedIdx >= 0) {
      const updated = [...edits.addedAssignments];
      updated[addedIdx] = {
        ...updated[addedIdx],
        pointsEarned: earned,
        pointsTotal: total,
        isExtraCredit: isEc,
      };
      persist({ ...edits, addedAssignments: updated });
    } else {
      persist({ ...edits, assignments: { ...edits.assignments, [editingId]: { pointsEarned: earned, pointsTotal: total } } });
    }
    setEditingId(null);
  }

  function addAssignment() {
    const earned = parseFloat(newEarned) || 0;
    const total = parseFloat(newTotal) || 0;
    if (!newTitle.trim() || isNaN(total) || total < 0) return;
    if (total === 0 && earned < 0) return;

    const isEc = total === 0 && earned > 0;
    const newA: ApiAssignment = {
      id: `user-${Date.now()}`,
      title: newTitle.trim(),
      pointsEarned: earned,
      pointsTotal: total,
      category: "Manual",
      dueDate: "",
      excused: false,
      isForGrading: true,
      isExtraCredit: isEc,
    };
    persist({ ...edits, addedAssignments: [...edits.addedAssignments, newA] });
    setAddingNew(false);
    setNewTitle("");
    setNewEarned("");
    setNewTotal("");
  }

  function savePointsValue() {
    const val = parseFloat(pointsInput);
    if (isNaN(val) || val <= 0 || !editingPointsTarget) return;
    if (editingPointsTarget === "next") {
      persist({ ...edits, nextAssignmentTotal: val });
    } else {
      persist({ ...edits, examTotalPoints: val });
    }
    setEditingPointsTarget(null);
  }

  function removeAdded(id: string) {
    persist({
      ...edits,
      addedAssignments: edits.addedAssignments.filter((a) => a.id !== id),
    });
    if (editingId === id) setEditingId(null);
  }

  const hasEdits = Object.keys(edits.assignments).length > 0 || edits.addedAssignments.length > 0;
  const reportedGrade = activeMp.percentage ?? cls.percentage;
  const displayGrade = hasEdits || (reportedGrade === 0 && totalPercent === null)
    ? totalPercent
    : (reportedGrade ?? totalPercent);
  const displayLetter = getLetterGrade(displayGrade);

  return (
    <div className="min-h-screen bg-background pb-32">
      <div className="px-6 py-8 max-w-4xl mx-auto">
        {detailLoading && (
          <div className="flex items-center gap-2 mb-4 bg-primary/5 border border-primary/20 rounded-full px-3 py-1.5 w-fit animate-pulse shadow-sm">
            <div className="w-2 h-2 rounded-full bg-primary animate-ping" />
            <span className="text-[10px] font-bold uppercase tracking-wider text-primary">Live syncing from StudentVue…</span>
          </div>
        )}
        {detailError && (
          <p className="text-sm text-destructive mb-2">{detailError}</p>
        )}

        <div className="flex flex-col lg:flex-row items-stretch lg:items-start justify-between gap-8 mb-8">
          <div className="flex-1 space-y-4">
            <button
              onClick={() => navigate("/grades")}
              className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors text-sm"
            >
              <ArrowLeft size={16} />
              Back to grades
            </button>
            <div className="flex flex-wrap items-baseline gap-3">
              <h1 className="font-display text-4xl text-foreground">{cls.name}</h1>
              <span className="text-sm font-bold text-muted-foreground">{selectedPeriod}</span>
            </div>
            {cls.teacherName && (
              <p className="text-muted-foreground text-sm mt-1">{cls.teacherName}</p>
            )}
            <div className="flex items-center gap-4 text-xs mt-2 text-muted-foreground">
              <span>{cls.gradingType === "cumulative" ? "Cumulative Grading" : "Independent Marking Periods"}</span>
              {(Object.keys(edits.assignments).length > 0 || edits.addedAssignments.length > 0) && (
                <button
                  onClick={() => {
                    if (window.confirm("Reset all manual overrides for this class?")) {
                      for (const mp of cls.markingPeriods) {
                        localStorage.removeItem(`class-edits-${cls.id}-${mp.label}`);
                      }
                      setEdits({ assignments: {}, addedAssignments: [], nextAssignmentTotal: 100, examTotalPoints: 100 });
                      setCacheTick((t) => t + 1);
                    }
                  }}
                  className="hover:text-foreground transition-colors flex items-center gap-1 bg-accent/30 px-2 py-0.5 rounded border border-border/40"
                >
                  <RotateCcw size={10} /> Reset Changes
                </button>
              )}
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-3 shrink-0">
            {/* Totals Section */}
            <div className="rounded-2xl border border-totals-border bg-totals px-3 py-2 shadow-sm min-w-[14rem]">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-totals-foreground/80">
                {selectedPeriod}
                {isWeighting && categories.length > 0 ? " · weighted" : ""}
              </p>
              <p className="font-display text-2xl font-bold text-totals-foreground tracking-tight mt-0.5 leading-none">
                {displayGrade != null ? `${Number(displayGrade).toFixed(2)}%` : "—"}
              </p>
              <p className="text-[11px] text-totals-foreground/55 mt-1 leading-snug">
                Reported · {displayGrade != null ? `${Number(displayGrade).toFixed(2)}%` : "—"} · {displayLetter}
              </p>
              <p className="text-[10px] text-totals-foreground/45 mt-1">
                {totalEarned.toFixed(1)}/{totalPoints.toFixed(1)} pts
              </p>

              {semesterProj && (
                <>
                  <div className="my-2 border-t border-totals-foreground/15" />
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-totals-foreground/80">
                    {semesterProj.label}
                  </p>
                  <p className="font-display text-2xl font-bold text-totals-foreground tracking-tight mt-0.5 leading-none">
                    {semesterProj.percentage.toFixed(2)}%
                  </p>
                  <p className="text-[10px] text-totals-foreground/55 mt-1 leading-relaxed">
                    {semesterProj.periodBreakdown
                      .map((p) => `${formatPeriodShort(p.displayLabel)}: ${p.percentage.toFixed(1)}%`)
                      .join(" · ")}
                  </p>
                </>
              )}
            </div>

            {/* Analysis Section */}
            <div className="rounded-2xl border border-analysis-border bg-analysis px-3 py-2 shadow-sm min-w-[14rem]">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-analysis-foreground">Analysis</p>
                <div className="flex rounded-lg border border-analysis-foreground/20 overflow-hidden text-[10px] shadow-sm">
                  <button
                    type="button"
                    onClick={() => { setAnalysisMode("next"); setEditingPointsTarget(null); }}
                    className={`px-2.5 py-1.5 font-medium transition-colors ${analysisMode === "next"
                      ? "bg-analysis-foreground/15 text-analysis-foreground"
                      : "text-analysis-foreground/60 hover:text-analysis-foreground"
                      }`}
                  >
                    Next assignment
                  </button>
                  <button
                    type="button"
                    onClick={() => { setAnalysisMode("exam"); setEditingPointsTarget(null); }}
                    className={`px-2.5 py-1.5 font-medium transition-colors border-l border-analysis-foreground/20 ${analysisMode === "exam"
                      ? "bg-analysis-foreground/15 text-analysis-foreground"
                      : "text-analysis-foreground/60 hover:text-analysis-foreground"
                      }`}
                  >
                    Exam
                  </button>
                </div>
              </div>

              {analysisMode === "next" && (() => {
                const activePtsValue = edits.nextAssignmentTotal;

                return (
                  <div className="flex items-center justify-between gap-1 rounded-md bg-analysis-foreground/5 px-2 py-1.5 mb-2 text-[10px]">
                    <span className="text-analysis-foreground/70">Next pts</span>
                    {editingPointsTarget === "next" ? (
                      <span className="flex items-center gap-0.5">
                        <input
                          className="w-12 rounded border border-analysis-foreground/25 bg-transparent px-1 py-0.5 text-[11px] text-analysis-foreground text-right"
                          value={pointsInput}
                          onChange={(e) => setPointsInput(e.target.value)}
                          autoFocus
                          onKeyDown={(e) => {
                            if (e.key === "Enter") savePointsValue();
                            if (e.key === "Escape") setEditingPointsTarget(null);
                          }}
                        />
                        <button type="button" onClick={savePointsValue} className="text-analysis-foreground">
                          <Check size={10} />
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => {
                          setEditingPointsTarget("next");
                          setPointsInput(String(activePtsValue));
                        }}
                        className="font-semibold text-analysis-foreground flex items-center gap-0.5"
                      >
                        {activePtsValue} <Pencil size={8} />
                      </button>
                    )}
                  </div>
                );
              })()}

              {analysisMode === "exam" && (() => {
                const mpAvg = semesterProj?.percentage ?? displayGrade ?? totalPercent ?? 0;
                return (
                  <div className="mb-2 rounded-md bg-analysis-foreground/5 px-2 py-1.5 text-[10px] text-analysis-foreground/70">
                    MP avg: <span className="font-semibold text-analysis-foreground">{mpAvg.toFixed(1)}%</span>
                    <span className="ml-1">(exam worth 10%)</span>
                  </div>
                );
              })()}

              <div className="space-y-0.5">
                {gradeThresholds.map((t) => {
                  if (analysisMode === "exam") {
                    const mpAvg = semesterProj?.percentage ?? displayGrade ?? totalPercent ?? 0;
                    const examNeeded = (t.percent - mpAvg * 0.9) / 0.1;
                    const possible = examNeeded <= 100 + 1e-6;
                    const alreadyAchieved = examNeeded <= 0;
                    return (
                      <div key={t.label} className="flex justify-between text-xs text-analysis-foreground">
                        <span>Required exam for {t.label}</span>
                        <span className={!possible ? "opacity-40 line-through" : alreadyAchieved ? "font-semibold text-grade-a" : "font-semibold"}>
                          {alreadyAchieved ? "✓ achieved" : `${examNeeded.toFixed(1)}%`}
                        </span>
                      </div>
                    );
                  }
                  const bucketPts = edits.nextAssignmentTotal;
                  const useWeighted = isWeighting && categories.length > 0 && examCategoryName;
                  let needed: number;
                  let possible: boolean;
                  if (useWeighted) {
                    const w = getRequiredScoreWeighted(effectiveAssignments, categories, examCategoryName, bucketPts, t.percent);
                    if (w != null) {
                      needed = w;
                      possible = w <= bucketPts + 1e-6;
                    } else {
                      needed = getRequiredScoreForGrade(totalEarned, totalPoints, bucketPts, t.percent);
                      possible = needed <= bucketPts + 1e-6;
                    }
                  } else {
                    needed = getRequiredScoreForGrade(totalEarned, totalPoints, bucketPts, t.percent);
                    possible = needed <= bucketPts + 1e-6;
                  }
                  return (
                    <div key={t.label} className="flex justify-between text-xs text-analysis-foreground">
                      <span>Required score for {t.label}</span>
                      <span className={!possible ? "opacity-40 line-through" : "font-semibold"}>
                        {needed.toFixed(2)}/{bucketPts}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        {/* Marking Period Tabs */}
        {cls.markingPeriods.length > 1 && (
          <div className="mb-10">
            <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/40 mb-3 ml-1">Marking period</p>
            <div className="flex flex-wrap gap-2.5">
              {cls.markingPeriods.map((mp) => {
                const active = mp.label === selectedPeriod;
                const pct = computeEffectiveMPGrade(cls.id, mp);
                const letter = getLetterGrade(pct);
                return (
                  <button
                    key={mp.label}
                    type="button"
                    onClick={() => setSelectedPeriod(mp.label)}
                    className={`rounded-2xl border px-4 py-2.5 text-center transition-all min-w-[5rem] ${active
                      ? "border-primary bg-primary text-primary-foreground shadow-lg scale-[1.02]"
                      : "border-border bg-card hover:border-primary/20 hover:bg-accent/30"
                      }`}
                  >
                    <div className={`text-xs font-bold ${active ? "text-primary-foreground" : "text-foreground"}`}>{formatPeriodShort(mp.label).toUpperCase()}</div>
                    {pct != null && (
                      <div className={`text-[10px] font-bold mt-1.5 opacity-80 ${active ? "text-primary-foreground" : getGradeColor(letter)}`}>
                        {pct.toFixed(1)}%
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-1.5 mb-4">
          <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/40 mr-1">Sort</span>
          {(["date", "name"] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setSortKey(key)}
              className={`px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors border ${sortKey === key ? "bg-primary border-primary text-primary-foreground" : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"}`}
            >
              {key === "date" ? "Date" : "Name"}
            </button>
          ))}
          {([ ["score", "Score"], ["worth", "Worth"] ] as const).map(([base, label]) => {
            const ascKey = `${base}-asc` as const;
            const descKey = `${base}-desc` as const;
            const active = sortKey === ascKey || sortKey === descKey;
            const isAsc = sortKey === ascKey;
            return (
              <button
                key={base}
                type="button"
                onClick={() => setSortKey(active && !isAsc ? ascKey : descKey)}
                className={`px-2.5 py-1 rounded-full text-[10px] font-medium transition-colors border flex items-center gap-1 ${active ? "bg-primary border-primary text-primary-foreground" : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"}`}
              >
                {label}
                <span className={active ? "opacity-100" : "opacity-40"}>{active && isAsc ? "↑" : "↓"}</span>
              </button>
            );
          })}
        </div>

        <div className="space-y-3">
          {detailLoading && effectiveAssignments.length === 0 && (
            <div className="space-y-3 animate-pulse">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div key={i} className="h-16 rounded-2xl bg-muted/20 border border-border/50" />
              ))}
            </div>
          )}

          {sortedAssignments.map((a) => {
            const isEditing = editingId === a.id;
            const ec = a.isExtraCredit || (a.pointsTotal <= 0 && a.pointsEarned > 0);
            const pct = ec ? null : a.pointsTotal === 0 ? 0 : (a.pointsEarned / a.pointsTotal) * 100;
            const letter = pct != null ? getLetterGrade(pct) : null;
            const colorClass = letter ? getGradeColor(letter) : "text-muted-foreground";
            const isModified = a.edited || a.userAdded;

            const isExpanded = expandedAssignmentId === a.id;
            const d = a.debugFields ?? {};
            const detailRows: { label: string; value: string }[] = [
              a.category ? { label: "Type", value: a.category } : null,
              d.week ? { label: "Week", value: d.week } : null,
              d.score !== undefined ? { label: "Score", value: `${d.score} / ${d.maxScore ?? d.pointsPossible ?? 0}` } : null,
              (d.originalScore !== undefined && String(d.originalScore) !== String(d.score)) ? { label: "Original score", value: String(d.originalScore) } : null,
              d.penaltyPct ? { label: "Penalty", value: `${d.penaltyPct}%` } : null,
              d.dropScoreText ? { label: "Drop score", value: d.dropScoreText } : null,
              d.publicNote ? { label: "Note", value: d.publicNote } : null,
              d.privateNote ? { label: "Private note", value: d.privateNote } : null,
              a.excused ? { label: "Status", value: "Excused" } : null,
              d.isGradeBookMissingMark ? { label: "Status", value: "Missing" } : null,
              d.gradeBookId ? { label: "ID", value: String(d.gradeBookId) } : null,
            ].filter(Boolean) as { label: string; value: string }[];

            return (
              <div
                key={a.id}
                className={`rounded-lg border transition-all overflow-hidden ${isExpanded
                  ? a.userAdded
                    ? "border-primary/50 bg-primary/10"
                    : a.edited
                      ? "border-primary/50 bg-primary/10"
                      : "border-border/80 bg-muted/30"
                  : a.userAdded
                    ? "border-dashed border-primary/40 bg-primary/5"
                    : a.edited
                      ? "border-primary/30 bg-primary/5"
                      : "border-border bg-card hover:border-primary/20"
                  }`}
              >
              <div
                onClick={() => { if (!isEditing) setExpandedAssignmentId(isExpanded ? null : a.id); }}
                className="flex items-center justify-between px-5 py-3.5 cursor-pointer"
              >
                <div className="flex items-center gap-4 min-w-0 flex-1">
                  {a.dueDate && (
                    <span className="text-xs font-medium text-muted-foreground/50 w-10 shrink-0 tabular-nums">
                      {a.dueDate.split("/").slice(0, 2).join("/")}
                    </span>
                  )}
                  <div className="flex items-center gap-2 min-w-0 overflow-hidden">
                    <span className="text-sm font-medium text-foreground truncate">{a.title}</span>
                    {ec && (
                      <span className="text-[10px] font-bold text-muted-foreground/60 bg-muted/50 px-2 py-0.5 rounded-md shrink-0 uppercase tracking-tight">
                        extra credit
                      </span>
                    )}
                    {isModified && (
                      <span className="text-[10px] text-primary/60 shrink-0">
                        {a.userAdded ? "added" : "edited"}
                      </span>
                    )}
                  </div>
                </div>

                {isEditing ? (
                  <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <input
                      className="w-16 rounded border border-border bg-background px-2 py-1 text-sm text-foreground text-right focus:outline-none focus:ring-1 focus:ring-ring"
                      value={editEarned}
                      onChange={(e) => setEditEarned(e.target.value)}
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === "Enter") confirmEdit();
                        if (e.key === "Escape") setEditingId(null);
                      }}
                    />
                    <span className="text-muted-foreground text-sm">/</span>
                    <input
                      className="w-16 rounded border border-border bg-background px-2 py-1 text-sm text-foreground text-right focus:outline-none focus:ring-1 focus:ring-ring"
                      value={editTotal}
                      onChange={(e) => setEditTotal(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") confirmEdit();
                        if (e.key === "Escape") setEditingId(null);
                      }}
                    />
                    <button onClick={confirmEdit} className="text-primary hover:text-primary/80 p-1"><Check size={14} /></button>
                    <button onClick={() => setEditingId(null)} className="text-muted-foreground hover:text-foreground p-1"><X size={14} /></button>
                  </div>
                ) : (
                  <div className="flex items-center gap-3 text-sm shrink-0">
                    <span className={`font-semibold ${colorClass}`}>
                      {ec ? "—" : pct != null ? `${pct.toFixed(2)}%` : "—"}
                    </span>
                    <span className="text-muted-foreground">
                      {a.pointsEarned}/{a.pointsTotal || 0}
                    </span>
                    <div className="flex items-center gap-0.5">
                      {a.userAdded && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); removeAdded(a.id); }}
                          className="text-destructive/70 hover:text-destructive p-1 transition-colors"
                          title="Remove"
                        >
                          <Trash2 size={12} />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); startEdit(a); }}
                        className="text-muted-foreground/50 hover:text-foreground p-1 transition-colors"
                      >
                        <Pencil size={12} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
              {isExpanded && detailRows.length > 0 && (
                <div className="px-5 pb-4 pt-1 border-t border-border/40 grid grid-cols-2 gap-x-6 gap-y-1.5">
                  {detailRows.map((r) => (
                    <div key={r.label} className="flex flex-col">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50">{r.label}</span>
                      <span className="text-xs text-foreground">{r.value}</span>
                    </div>
                  ))}
                </div>
              )}
              </div>
            );
          })}

          {addingNew ? (
            <div
              className="rounded-xl border border-dashed border-primary/40 bg-primary/5 p-4 space-y-3 animate-in zoom-in-95 duration-200"
              onKeyDown={(e) => {
                if (e.key === "Enter") addAssignment();
                if (e.key === "Escape") {
                  setAddingNew(false);
                  setNewTitle("");
                  setNewEarned("");
                  setNewTotal("");
                }
              }}
            >
              <input
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/20"
                placeholder="New assignment name..."
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                autoFocus
              />
              <div className="flex items-center gap-2">
                <input
                  className="w-20 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium text-foreground text-center focus:outline-none focus:ring-1 focus:ring-primary/20"
                  placeholder="Scored"
                  value={newEarned}
                  onChange={(e) => setNewEarned(e.target.value)}
                />
                <span className="text-muted-foreground/30 font-bold">/</span>
                <input
                  className="w-20 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium text-foreground text-center focus:outline-none focus:ring-1 focus:ring-primary/20"
                  placeholder="Total"
                  value={newTotal}
                  onChange={(e) => setNewTotal(e.target.value)}
                />
                <div className="flex-1" />
                <button
                  onClick={() => { setAddingNew(false); setNewTitle(""); setNewEarned(""); setNewTotal(""); }}
                  className="px-3 py-2 rounded-lg hover:bg-muted text-muted-foreground text-sm font-medium transition-colors"
                >Cancel</button>
                <button
                  onClick={addAssignment}
                  className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-bold shadow-sm hover:opacity-90 active:scale-95 transition-all"
                >Add</button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setAddingNew(true)}
              className="w-full flex items-center justify-center gap-2 rounded-lg border border-dashed border-border hover:border-primary/40 py-3 text-muted-foreground hover:text-primary transition-colors"
            >
              <Plus size={16} />
              <span className="text-sm font-medium">Simulate Assignment</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default ClassDetail;
