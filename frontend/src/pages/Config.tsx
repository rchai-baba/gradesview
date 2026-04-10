import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { FETCH_MODE_STORAGE_KEY, type LoginFetchMode } from "@/services/api";

const MODES: { value: LoginFetchMode; title: string; body: string }[] = [
  {
    value: "cards_only",
    title: "Cards only (default)",
    body:
      "Fastest: loads the grade grid only. Full assignment lists load when you open a class for a marking period — closest to the official site.",
  },
  {
    value: "current_period_only",
    title: "Current marking period",
    body: "Loads every class but only the current marking period’s assignments at login. Slower than cards-only.",
  },
  {
    value: "full",
    title: "All periods",
    body: "Loads every marking period for every class at login. Slowest; use if you need everything offline immediately.",
  },
];

const Config = () => {
  const [mode, setMode] = useState<LoginFetchMode>("cards_only");

  useEffect(() => {
    try {
      const raw = localStorage.getItem(FETCH_MODE_STORAGE_KEY);
      if (raw === "current_period_only" || raw === "full") setMode(raw);
      else if (raw === "fast") setMode("current_period_only");
      else setMode("cards_only");
    } catch {
      setMode("cards_only");
    }
  }, []);

  const selectMode = (next: LoginFetchMode) => {
    setMode(next);
    localStorage.setItem(FETCH_MODE_STORAGE_KEY, next);
  };

  return (
    <div className="min-h-screen bg-background px-6 py-10">
      <div className="max-w-lg mx-auto">
        <Link
          to="/grades"
          className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground text-sm mb-6"
        >
          <ArrowLeft size={16} />
          Back to grades
        </Link>
        <h1 className="font-display text-3xl text-foreground mb-2">Settings</h1>
        <p className="text-muted-foreground text-sm mb-8">
          Login fetch mode applies on your device only. Course pairing and semester buckets are configured on the server in{" "}
          <code className="text-xs bg-muted px-1 py-0.5 rounded">backend/course_merge_config.json</code>{" "}
          (mergeNameGroups + semesterGroups).
        </p>

        <div className="rounded-xl border border-border bg-card p-5 space-y-4">
          <p className="text-sm font-medium text-foreground">Login fetch</p>
          <fieldset className="space-y-3">
            {MODES.map((m) => (
              <label
                key={m.value}
                className={`flex gap-3 cursor-pointer rounded-lg border p-3 transition-colors ${
                  mode === m.value ? "border-primary bg-primary/5 ring-1 ring-primary/25" : "border-border hover:bg-accent/50"
                }`}
              >
                <input
                  type="radio"
                  name="fetch-mode"
                  value={m.value}
                  checked={mode === m.value}
                  onChange={() => selectMode(m.value)}
                  className="mt-1 shrink-0"
                />
                <span>
                  <span className="text-sm font-semibold text-foreground block">{m.title}</span>
                  <span className="text-xs text-muted-foreground mt-0.5 block">{m.body}</span>
                </span>
              </label>
            ))}
          </fieldset>
        </div>

        <p className="text-muted-foreground text-xs mt-8">
          This page is intentionally minimal — extend it as you add more options.
        </p>
      </div>
    </div>
  );
};

export default Config;
