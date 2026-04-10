import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  DndContext,
  DragOverlay,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { LogOut, Settings, GripVertical, RefreshCw } from "lucide-react";
import { loadGrades, clearGrades, getSessionCredentials } from "@/services/api";
import { useSyncContext } from "@/contexts/SyncContext";
import { getLetterGrade, getGradeColor, computeSimplePercent, computeWeightedPercent } from "@/lib/grades";
import { SortableClassCard } from "@/components/SortableClassCard";
import type { ApiClass } from "@/types";
import { projectedSemesterGrade } from "@/lib/semesterProjection";

const ORDER_KEY = "grades-class-order";

function mergeOrderWithClasses(currentIds: string[], savedOrder: string[]): string[] {
  const out: string[] = [];
  const pool = new Set(currentIds);
  for (const id of savedOrder) {
    if (pool.has(id)) {
      out.push(id);
      pool.delete(id);
    }
  }
  for (const id of currentIds) {
    if (pool.has(id)) out.push(id);
  }
  return out;
}

function loadSavedOrder(): string[] {
  try {
    const raw = localStorage.getItem(ORDER_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as string[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

const GradesHome = () => {
  const navigate = useNavigate();
  const { syncing, triggerSync, onSyncComplete } = useSyncContext();
  const [syncVersion, setSyncVersion] = useState(0);
  const data = useMemo(() => loadGrades(), [syncVersion]);
  const [order, setOrder] = useState<string[]>([]);
  const [activeDragId, setActiveDragId] = useState<string | null>(null);
  const [activeSemesterIdx, setActiveSemesterIdx] = useState<number | null>(null);
  /** Suppress card click right after a drag so reorder doesn't navigate */
  const navSuppressUntil = useRef(0);

  useEffect(() => {
    if (!data) navigate("/");
  }, [data, navigate]);

  // Re-read localStorage whenever a background sync completes
  useEffect(() => {
    return onSyncComplete(() => setSyncVersion((v) => v + 1));
  }, [onSyncComplete]);

  useEffect(() => {
    if (!data?.classes.length) return;
    const ids = data.classes.map((c) => c.id);
    setOrder(mergeOrderWithClasses(ids, loadSavedOrder()));
  }, [data?.classes]);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      /** No long-press: drag starts after a tiny move; tap still opens the class */
      activationConstraint: { distance: 2 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const effectiveOrder = useMemo(() => {
    if (!data?.classes.length) return [];
    const ids = data.classes.map((c) => c.id);
    return mergeOrderWithClasses(ids, order.length ? order : loadSavedOrder());
  }, [data?.classes, order]);

  const orderedClasses: ApiClass[] = useMemo(() => {
    if (!data?.classes.length) return [];
    const byId = new Map(data.classes.map((c) => [c.id, c]));
    const out: ApiClass[] = [];
    for (const id of effectiveOrder) {
      const c = byId.get(id);
      if (c) out.push(c);
    }
    return out;
  }, [data, effectiveOrder]);

  const handleDragEnd = (event: DragEndEvent) => {
    navSuppressUntil.current = Date.now() + 220;
    setActiveDragId(null);
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = effectiveOrder.indexOf(active.id as string);
    const newIndex = effectiveOrder.indexOf(over.id as string);
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(effectiveOrder, oldIndex, newIndex);
    setOrder(next);
    localStorage.setItem(ORDER_KEY, JSON.stringify(next));
  };

  const handleRefresh = () => {
    if (!getSessionCredentials()) return;
    triggerSync();
  };

  const handleLogout = () => {
    clearGrades();
    navigate("/");
  };

  if (!data) return null;

  const activeDragClass = activeDragId ? orderedClasses.find((c) => c.id === activeDragId) : undefined;
  let dragOverlayPreview: {
    cls: ApiClass;
    percent: number;
    letter: string;
    colorClass: string;
  } | null = null;
  if (activeDragClass) {
    const cls = activeDragClass;
    const sem = data ? projectedSemesterGrade(cls, cls.currentPeriod, data.semesterGroups, data.periods) : null;
    const percent = sem?.percentage ?? null;
    const letter = getLetterGrade(percent);
    dragOverlayPreview = { cls, percent: percent as any, letter, colorClass: getGradeColor(letter) };
  }

  return (
    <div className="min-h-screen bg-background px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-1">
          <h1 className="font-display text-3xl text-foreground">My Grades</h1>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={syncing}
              className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors text-sm px-3 py-1.5 rounded-lg border border-border hover:bg-accent disabled:opacity-50"
            >
              <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
              {syncing ? "Syncing..." : "Sync"}
            </button>
            <button
              type="button"
              onClick={() => navigate("/config")}
              className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors text-sm px-3 py-1.5 rounded-lg border border-border hover:bg-accent"
            >
              <Settings size={14} />
              Settings
            </button>
            <button
              type="button"
              onClick={handleLogout}
              className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors text-sm px-3 py-1.5 rounded-lg border border-border hover:bg-accent"
            >
              <LogOut size={14} />
              Logout
            </button>
          </div>
        </div>
        {data.student.name && (
          <p className="text-muted-foreground text-sm mb-1">{data.student.name}</p>
        )}
        <p className="text-muted-foreground text-sm mb-2">{data.periods.join(" · ")}</p>

        {/* Semester selector */}
        {data.semesterGroups && data.semesterGroups.length > 1 && (
          <div className="flex items-center gap-2 mb-5">
            {data.semesterGroups.map((group, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setActiveSemesterIdx(activeSemesterIdx === idx ? null : idx)}
                className={`text-xs font-semibold px-3 py-1 rounded-full border transition-colors ${
                  activeSemesterIdx === idx
                    ? "bg-foreground text-background border-foreground"
                    : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/40"
                }`}
              >
                S{idx + 1}
              </button>
            ))}
          </div>
        )}

        <p className="text-muted-foreground text-xs mb-8 flex items-center gap-1.5">
          <GripVertical size={12} className="shrink-0 opacity-70" />
          Drag to reorder · Tap to open a class
        </p>

        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={({ active }) => setActiveDragId(String(active.id))}
          onDragCancel={() => {
            navSuppressUntil.current = Date.now() + 220;
            setActiveDragId(null);
          }}
          onDragEnd={handleDragEnd}
        >
          <SortableContext items={effectiveOrder}>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {orderedClasses.map((cls) => {
                const semPeriod = activeSemesterIdx != null && data?.semesterGroups?.[activeSemesterIdx]?.[0]
                  ? data.semesterGroups[activeSemesterIdx][0]
                  : cls.currentPeriod;
                const sem = data ? projectedSemesterGrade(cls, semPeriod, data.semesterGroups, data.periods) : null;
                const percent = sem?.percentage ?? null;
                const letter = getLetterGrade(percent);
                const colorClass = getGradeColor(letter);

                return (
                  <SortableClassCard
                    key={cls.id}
                    id={cls.id}
                    onNavigate={() => {
                      if (Date.now() < navSuppressUntil.current) return;
                      navigate(`/class/${cls.id}`);
                    }}
                  >
                    <p className="text-muted-foreground text-xs font-medium uppercase tracking-wider mb-3 text-center line-clamp-3">
                      {cls.name}
                    </p>
                    {cls.error ? (
                      <p className="text-destructive text-xs text-center">No data</p>
                    ) : (
                      <>
                        <p className={`font-display text-5xl ${colorClass}`}>{letter}</p>
                        <p className="text-foreground text-lg font-medium mt-2">
                          {percent != null ? `${percent.toFixed(2)}%` : "—"}
                        </p>
                        {sem && (
                          <div className="flex flex-wrap justify-center gap-x-2 gap-y-1 mt-3">
                            {sem.periodBreakdown.map((bp) => (
                              <span key={bp.label} className="text-[10px] font-medium text-muted-foreground bg-accent/30 px-1.5 py-0.5 rounded border border-border/40">
                                {bp.displayLabel}: <span className={getGradeColor(bp.letter)}>{bp.percentage.toFixed(1)}%</span>
                              </span>
                            ))}
                          </div>
                        )}
                        <p className="text-muted-foreground text-[10px] mt-2 uppercase tracking-wider">
                          {sem?.label ?? cls.currentPeriod}
                        </p>
                      </>
                    )}
                  </SortableClassCard>
                );
              })}
            </div>
          </SortableContext>
          <DragOverlay dropAnimation={{ duration: 220, easing: "cubic-bezier(0.32, 0.72, 0, 1)" }}>
            {dragOverlayPreview ? (
              <div className="rounded-2xl border border-border bg-card p-6 flex flex-col items-center justify-center min-h-[140px] min-w-[200px] max-w-[280px] cursor-grabbing select-none shadow-[0_25px_50px_-12px_rgba(0,0,0,0.35)] scale-[1.06] rotate-[2deg] ring-2 ring-primary/25 transition-transform duration-200 ease-out">
                <p className="text-muted-foreground text-xs font-medium uppercase tracking-wider mb-3 text-center line-clamp-3">
                  {dragOverlayPreview.cls.name}
                </p>
                {dragOverlayPreview.cls.error ? (
                  <p className="text-destructive text-xs text-center">No data</p>
                ) : (
                  <>
                    <p className={`font-display text-5xl ${dragOverlayPreview.colorClass}`}>{dragOverlayPreview.letter}</p>
                    <p className="text-foreground text-lg font-medium mt-2">
                      {dragOverlayPreview.percent != null ? `${dragOverlayPreview.percent.toFixed(2)}%` : "—"}
                    </p>
                    <p className="text-muted-foreground text-[10px] mt-1 uppercase tracking-wider">
                      {dragOverlayPreview.cls.currentPeriod}
                    </p>
                  </>
                )}
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>
    </div>
  );
};

export default GradesHome;
