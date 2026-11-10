import Link from "next/link";
import { BookOpen, Clock3, FileText, Layers3, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ThemeToggle } from "@/components/theme-toggle";
import { projects } from "@/lib/demo-data";
import { cn } from "@/lib/utils";

export default function Home() {
  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-neutral-100 via-background to-background dark:from-neutral-900">
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
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Link href="/project/new" className={cn(buttonVariants())}>
            <Plus className="size-4" />
            New project
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-6 pb-16">
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Your projects</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Pick a library to ask questions, review sources, and manage papers.
            </p>
          </div>
          <Badge variant="secondary">{projects.length} projects</Badge>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Link href="/project/new" className="group">
            <Card className="flex h-full min-h-[220px] flex-col items-center justify-center border-dashed bg-transparent text-muted-foreground transition-colors hover:border-foreground/30 hover:bg-card hover:text-foreground">
              <div className="flex size-11 items-center justify-center rounded-full border bg-background shadow-sm transition-transform group-hover:scale-105">
                <Plus className="size-5" />
              </div>
              <p className="mt-3 font-medium text-foreground">Create new project</p>
              <p className="mt-1 max-w-[220px] text-center text-sm">
                Start a new library for a topic, paper set, or research question.
              </p>
            </Card>
          </Link>

          {projects.map((project) => (
            <Link key={project.id} href={`/project/${project.id}`} className="group">
              <Card className="flex h-full min-h-[220px] flex-col transition-all hover:-translate-y-0.5 hover:shadow-md hover:border-foreground/20">
                <CardHeader>
                  <div className="mb-1 flex items-center justify-between">
                    <div className="flex size-8 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <Layers3 className="size-4" />
                    </div>
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Clock3 className="size-3" />
                      {project.updatedAt}
                    </span>
                  </div>
                  <CardTitle className="text-lg">{project.name}</CardTitle>
                  <CardDescription className="line-clamp-2">{project.description}</CardDescription>
                </CardHeader>
                <CardContent className="mt-auto">
                  <div className="flex items-center gap-4 text-sm text-muted-foreground">
                    <span className="flex items-center gap-1.5">
                      <FileText className="size-4" />
                      {project.papers} papers
                    </span>
                    <span>{project.chunks.toLocaleString()} chunks</span>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      </main>
    </div>
  );
}
