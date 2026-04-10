import { useState } from "react";
import { flushSync } from "react-dom";
import { useNavigate } from "react-router-dom";
import { loginAndFetchGrades, saveGrades, saveSessionCredentials } from "@/services/api";
import { useSyncContext } from "@/contexts/SyncContext";

const Login = () => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { triggerSync } = useSyncContext();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError("Please enter both fields.");
      return;
    }

    flushSync(() => {
      setError("");
      setLoading(true);
    });
    try {
      const data = await loginAndFetchGrades(username, password);
      saveSessionCredentials(username, password);
      saveGrades(data);
      navigate("/grades");
      // Kick off a background sync immediately after cards load
      triggerSync();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm px-6">
        <h1 className="font-display text-4xl text-foreground text-center mb-2">
          Student Grades
        </h1>
        <p className="text-muted-foreground text-center mb-8 text-sm">
          Sign in with your StudentVue credentials
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loading}
              className="w-full rounded-lg border border-border bg-card px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
              placeholder="Enter username"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1.5">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
              className="w-full rounded-lg border border-border bg-card px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
              placeholder="Enter password"
            />
          </div>

          {error && (
            <p className="text-destructive text-sm">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-primary py-3 text-sm font-semibold text-primary-foreground hover:opacity-90 transition-all active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed shadow-md"
          >
            {loading ? (
              <div className="flex items-center justify-center gap-2">
                <div className="w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
                Updating grades…
              </div>
            ) : "Sign In"}
          </button>

          {loading && (
            <div className="fixed inset-0 bg-background/60 backdrop-blur-sm z-50 flex items-center justify-center p-6 animate-in fade-in duration-300">
               <div className="bg-card border border-border rounded-2xl p-8 shadow-2xl max-w-xs w-full text-center space-y-4">
                  <div className="relative mx-auto w-16 h-16">
                    <div className="absolute inset-0 border-4 border-primary/20 rounded-full" />
                    <div className="absolute inset-0 border-4 border-primary border-t-transparent rounded-full animate-spin" />
                  </div>
                  <div>
                    <h3 className="font-display text-xl text-foreground">Syncing Grades</h3>
                    <p className="text-muted-foreground text-xs mt-1 leading-relaxed">
                      Securely connecting to StudentVue. This might take a few seconds…
                    </p>
                  </div>
               </div>
            </div>
          )}
        </form>
      </div>
    </div>
  );
};

export default Login;
