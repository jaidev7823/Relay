"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BookOpen, LoaderCircle, LogIn, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ThemeToggle } from "@/components/theme-toggle";
import { api } from "@/lib/api";

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";

  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") await api.register(username.trim(), password);
      else await api.login(username.trim(), password);
      router.replace(next);
    } catch (e: any) {
      setError(e?.message || "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-neutral-100 via-background to-background dark:from-neutral-900">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-8">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg border bg-card shadow-sm">
            <BookOpen className="size-4" />
          </div>
          <div>
            <p className="text-sm font-semibold tracking-tight">Relevantr</p>
            <p className="text-xs text-muted-foreground">Scientific PDF workspace</p>
          </div>
        </div>
        <ThemeToggle />
      </header>

      <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-6 pb-24">
        <Tabs value={mode} onValueChange={(v) => { setMode(v as "login" | "register"); setError(null); }}>
          <TabsList className="w-full">
            <TabsTrigger value="login" className="flex-1">Log in</TabsTrigger>
            <TabsTrigger value="register" className="flex-1">Register</TabsTrigger>
          </TabsList>

          <div className="mt-4 space-y-3 rounded-xl border bg-card p-4 shadow-sm">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Username</label>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
                placeholder="username"
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Password</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
                placeholder={mode === "register" ? "At least 6 characters" : "password"}
              />
            </div>
            {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
            <Button className="w-full" onClick={submit} disabled={busy || !username.trim() || !password}>
              {busy
                ? <LoaderCircle className="size-4 animate-spin" />
                : mode === "register" ? <UserPlus className="size-4" /> : <LogIn className="size-4" />}
              {mode === "register" ? "Create account" : "Log in"}
            </Button>
            <p className="text-center text-[11px] text-muted-foreground">
              Sessions are stored server-side in the app database.
            </p>
          </div>
        </Tabs>
      </main>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}
