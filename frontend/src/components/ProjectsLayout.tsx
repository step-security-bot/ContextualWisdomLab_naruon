"use client";

import { useEffect, useMemo, useState } from 'react';
import { CalendarDays, CheckCircle2, Clock, FolderOpen, ListChecks, Search, User } from 'lucide-react';

import { apiClient } from '@/lib/api-client';
import { toSafeReactText } from '@/lib/safe-text';

type ProjectViewMode = '프로젝트 상세' | '마일스톤' | '의사결정 로그';
type TaskStatus = 'open' | 'in_progress' | 'blocked' | 'done';
type TaskPriority = 'low' | 'normal' | 'high' | 'urgent';

interface ProjectFolder {
  folder_uid: string;
  project_name: string;
  webdav_path: string;
  owner_user_id: string;
  organization_id: string | null;
}

interface TicketTask {
  id: string;
  title: string;
  status: TaskStatus;
  priority: TaskPriority;
  source_type: string;
  source_email_id: string | null;
  related_thread_id: string | null;
  created_at: string;
  updated_at: string;
}

interface ProjectSummary {
  id: string;
  title: string;
  status: '진행 중' | '대기 중' | '완료' | '검토 중';
  progress: number;
  category: string;
  evidence: string;
  sourcePath: string | null;
}

interface ProjectAccessScope {
  userId: string | null;
  organizationId: string | null;
}

const projectStatusClass = {
  '완료': 'bg-emerald-100 text-emerald-700',
  '진행 중': 'bg-blue-100 text-blue-700',
  '검토 중': 'bg-violet-100 text-violet-700',
  '대기 중': 'bg-slate-100 text-slate-700',
} satisfies Record<ProjectSummary['status'], string>;

const taskStatusLabel: Record<TaskStatus, string> = {
  open: '실행 항목',
  in_progress: '진행 중',
  blocked: '검토 필요',
  done: '완료',
};

const taskStatusClass: Record<TaskStatus, string> = {
  open: 'bg-slate-100 text-slate-700',
  in_progress: 'bg-blue-100 text-blue-700',
  blocked: 'bg-amber-100 text-amber-800',
  done: 'bg-emerald-100 text-emerald-700',
};

const priorityLabel: Record<TaskPriority, string> = {
  urgent: '긴급',
  high: '높음',
  normal: '보통',
  low: '낮음',
};

function safeText(value: string | null | undefined, fallback = '') {
  return toSafeReactText(value, fallback).trim() || fallback;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '날짜 미정';
  return new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric' }).format(date);
}

function buildProgress(tasks: TicketTask[]) {
  if (tasks.length === 0) return 0;
  return Math.round((tasks.filter((task) => task.status === 'done').length / tasks.length) * 100);
}

function buildProjectStatus(tasks: TicketTask[]): ProjectSummary['status'] {
  if (tasks.some((task) => task.status === 'blocked')) return '검토 중';
  if (tasks.some((task) => task.status === 'in_progress')) return '진행 중';
  if (tasks.length > 0 && tasks.every((task) => task.status === 'done')) return '완료';
  return '대기 중';
}

function getProjectEvidenceLabel(evidence: string) {
  if (evidence === 'project_folders') return 'WebDAV 폴더 근거';
  if (evidence === 'ticket_tasks') return '작업 근거';
  return '원본 근거';
}

function getProjectBoundaryLabel(project: ProjectSummary) {
  return project.sourcePath ? '저장소 경계 확인됨' : '작업 대기열 기준';
}

function getTaskSourceLabel(sourceType: string) {
  switch (sourceType) {
    case 'email':
      return '메일 근거';
    case 'webdav':
      return '문서 근거';
    case 'reply_sla':
      return '답장 대기';
    case 'self_sent_knowledge':
      return '자기참조 메일';
    default:
      return '원본 근거';
  }
}

function getTaskEvidenceLabel(task: TicketTask) {
  if (task.related_thread_id) return '스레드 근거 연결됨';
  if (task.source_email_id) return '메일 근거 연결됨';
  return '원본 연결 대기';
}

function getWorkspaceScopeLabel(scope: ProjectAccessScope) {
  return scope.organizationId ? '서명된 조직 워크스페이스' : '서명된 개인 워크스페이스';
}

function isAuthorizedToViewProject(folder: ProjectFolder, scope: ProjectAccessScope) {
  const ownerUserId = safeText(folder.owner_user_id);
  if (!ownerUserId || !scope.userId || ownerUserId !== scope.userId) return false;
  return (folder.organization_id ?? null) === scope.organizationId;
}

function buildProjects(folders: ProjectFolder[], tasks: TicketTask[]): ProjectSummary[] {
  const progress = buildProgress(tasks);
  const status = buildProjectStatus(tasks);
  const folderProjects = folders.map((folder) => ({
    id: folder.folder_uid,
    title: safeText(folder.project_name, '이름 없는 프로젝트'),
    status,
    progress,
    category: 'WebDAV 프로젝트',
    evidence: 'project_folders',
    sourcePath: safeText(folder.webdav_path, ''),
  }));

  if (folderProjects.length > 0) return folderProjects;

  return [
    {
      id: 'workspace_task_backlog',
      title: '원본 연결 작업 대기열',
      status,
      progress,
      category: '작업 대기열',
      evidence: 'ticket_tasks',
      sourcePath: null,
    },
  ];
}

function countByStatus(tasks: TicketTask[], status: TaskStatus) {
  return tasks.filter((task) => task.status === status).length;
}

export function ProjectsLayout() {
  const [folders, setFolders] = useState<ProjectFolder[]>([]);
  const [tasks, setTasks] = useState<TicketTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ProjectViewMode>('프로젝트 상세');
  const [projectScope, setProjectScope] = useState<ProjectAccessScope>({
    userId: null,
    organizationId: null,
  });

  useEffect(() => {
    let cancelled = false;

    void Promise.all([
      apiClient.get<ProjectFolder[]>('/api/webdav/folders'),
      apiClient.get<TicketTask[]>('/api/tasks'),
      apiClient.getServerSessionClaims(),
    ])
      .then(([folderRows, taskRows, claims]) => {
        if (cancelled) return;
        setFolders(Array.isArray(folderRows) ? folderRows : []);
        setTasks(Array.isArray(taskRows) ? taskRows : []);
        setProjectScope({
          userId: claims.userId,
          organizationId: claims.organizationId,
        });
        setError(null);
      })
      .catch((fetchError: Error) => {
        if (cancelled) return;
        setFolders([]);
        setTasks([]);
        setError(fetchError.message ? '프로젝트 근거를 불러오지 못했습니다. 데이터 연결 상태를 확인해 주세요.' : '프로젝트 근거를 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const authorizedFolders = useMemo(
    () => folders.filter((folder) => isAuthorizedToViewProject(folder, projectScope)),
    [folders, projectScope],
  );
  const projects = useMemo(() => buildProjects(authorizedFolders, tasks), [authorizedFolders, tasks]);
  const activeProject = projects.find((project) => project.id === selectedProjectId) ?? projects[0];
  const projectTasks = tasks;
  const openCount = countByStatus(projectTasks, 'open');
  const inProgressCount = countByStatus(projectTasks, 'in_progress');
  const blockedCount = countByStatus(projectTasks, 'blocked');
  const doneCount = countByStatus(projectTasks, 'done');
  const sourceTypeCount = new Set(projectTasks.map((task) => task.source_type)).size;
  const projectEvidenceLabel = getProjectEvidenceLabel(activeProject.evidence);
  const projectBoundaryLabel = getProjectBoundaryLabel(activeProject);
  const workspaceScopeLabel = getWorkspaceScopeLabel(projectScope);

  return (
    <div className="flex h-full min-h-0 min-w-0 overflow-x-hidden bg-background text-foreground">
      <aside className="hidden w-72 shrink-0 flex-col overflow-y-auto border-r border-border bg-card lg:flex">
        <div className="border-b border-border p-4">
          <a href="/data" className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary py-2.5 text-sm font-bold text-primary-foreground shadow-sm hover:bg-primary/90">
            <FolderOpen className="size-4" /> 새 프로젝트
          </a>
          <div className="relative mt-4">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <a href="/search" aria-label="프로젝트 관련 문서와 메일 연결" className="flex h-9 w-full items-center rounded-md border border-border bg-background pl-9 pr-4 text-sm font-semibold text-muted-foreground hover:bg-secondary">
              관련 문서/메일 연결
            </a>
          </div>
        </div>

        <div className="flex-1 space-y-1 p-3">
          {loading ? (
            <div role="status" className="rounded-lg border border-border bg-background p-3 text-sm font-semibold text-muted-foreground">프로젝트 근거를 불러오는 중입니다.</div>
          ) : null}
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              onClick={() => setSelectedProjectId(project.id)}
              className={`w-full rounded-lg border px-3 py-3 text-left transition-colors ${activeProject.id === project.id ? 'border-primary/30 bg-secondary' : 'border-transparent hover:bg-secondary/50'}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs font-bold text-muted-foreground">{project.category}</span>
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold ${projectStatusClass[project.status]}`}>{project.status}</span>
              </div>
              <h3 className="mt-1 line-clamp-2 font-bold text-sm text-foreground">{project.title}</h3>
              <div className="mt-3 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-border">
                  <div className={`h-full ${project.progress === 100 ? 'bg-emerald-500' : 'bg-primary'}`} style={{ width: `${project.progress}%` }} />
                </div>
                <span className="text-xs font-semibold text-muted-foreground">{project.progress}%</span>
              </div>
            </button>
          ))}
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col bg-background">
        <header className="flex shrink-0 flex-col gap-3 border-b border-border bg-card px-4 py-4 lg:h-24 lg:flex-row lg:items-center lg:justify-between lg:px-6">
          <div className="min-w-0">
            <h1 className="break-keep text-sm font-black text-foreground lg:text-base">프로젝트 워크스페이스</h1>
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-bold text-muted-foreground">
              <span>{activeProject.category}</span>
              <span>/</span>
              <span>{projectEvidenceLabel}</span>
            </div>
            <h2 className="break-keep text-xl font-bold leading-tight lg:text-2xl">{activeProject.title}</h2>
          </div>
          <div className="flex min-w-0 flex-col gap-3 lg:items-end">
            <div className="flex gap-2 overflow-x-auto pb-1 lg:hidden">
              {projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  onClick={() => setSelectedProjectId(project.id)}
                  className={`min-h-10 shrink-0 rounded-xl px-3 text-xs font-bold ${activeProject.id === project.id ? 'bg-primary text-primary-foreground' : 'bg-background text-muted-foreground'}`}
                >
                  {project.title}
                </button>
              ))}
            </div>
            <div className="flex overflow-x-auto rounded-md border border-border">
              {(['프로젝트 상세', '마일스톤', '의사결정 로그'] as ProjectViewMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setViewMode(mode)}
                  className={`min-h-9 shrink-0 px-3 text-xs font-semibold transition-colors sm:px-4 sm:text-sm ${viewMode === mode ? 'bg-primary text-primary-foreground' : 'bg-background hover:bg-secondary'}`}
                >
                  {mode}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <a href="/tasks" className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-semibold hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40">작업 보드</a>
              <a href="/data" className="rounded-md bg-primary px-4 py-1.5 text-sm font-bold text-primary-foreground hover:bg-primary/90">원본 연결</a>
            </div>
          </div>
        </header>

        <div role="region" aria-label="프로젝트 내용" className="grid flex-1 gap-6 overflow-y-auto p-4 md:p-6 lg:grid-cols-3">
          <div className="min-w-0 space-y-6 lg:col-span-2">
            {error ? (
              <div role="alert" className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm font-semibold text-amber-900">
                {error}
              </div>
            ) : null}

            {(viewMode === '프로젝트 상세' || viewMode === '마일스톤') && (
              <section aria-label="프로젝트 마일스톤" className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
                <div className="flex items-center justify-between border-b border-border p-5">
                  <h2 className="font-bold text-lg">마일스톤</h2>
                  <a href="/tasks" className="rounded-md bg-primary px-3 py-1.5 text-xs font-bold text-primary-foreground hover:bg-primary/90">마일스톤 추가</a>
                </div>
                <div className="grid gap-4 p-5 md:grid-cols-4">
                  {[
                    { label: '실행 항목', count: openCount, status: 'open' as const },
                    { label: '진행 중', count: inProgressCount, status: 'in_progress' as const },
                    { label: '검토 필요', count: blockedCount, status: 'blocked' as const },
                    { label: '완료', count: doneCount, status: 'done' as const },
                  ].map((milestone) => (
                    <article key={milestone.status} className="rounded-xl border border-border bg-background p-4">
                      <div className={`inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${taskStatusClass[milestone.status]}`}>{milestone.label}</div>
                      <p className="mt-4 text-2xl font-black">{milestone.count}</p>
                      <p className="mt-1 text-sm text-muted-foreground">원본 연결 작업</p>
                    </article>
                  ))}
                </div>
              </section>
            )}

            {(viewMode === '프로젝트 상세' || viewMode === '의사결정 로그') && (
              <section aria-label="프로젝트 의사결정 로그" className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
                <div className="flex items-center justify-between border-b border-border bg-primary/5 p-5">
                  <h2 className="font-bold text-lg text-primary">의사결정 로그</h2>
                  <button type="button" aria-label="프로젝트 의사결정 추가" onClick={() => setViewMode('의사결정 로그')} className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 rounded-md bg-primary px-3 py-1.5 text-xs font-bold text-primary-foreground hover:bg-primary/90">의사결정 추가</button>
                </div>
                <div className="divide-y divide-border">
                  <article className="p-5">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="flex items-center gap-2 font-bold text-base"><CheckCircle2 className="size-4 text-emerald-500" /> 원본 저장소 연결</h3>
                      <span className="text-xs text-muted-foreground">{authorizedFolders.length}개 폴더</span>
                    </div>
                    <p className="mt-2 rounded-lg border border-border bg-background p-3 text-sm leading-6 text-foreground">
                      WebDAV 프로젝트 폴더를 작업 경계로 사용합니다. 외부 저장소 쓰기는 별도 승인 전까지 실행하지 않습니다.
                    </p>
                    <p className="mt-3 flex items-center gap-2 text-xs font-semibold text-muted-foreground"><User className="size-3.5" /> 근거: WebDAV 폴더</p>
                  </article>
                  <article className="p-5">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="flex items-center gap-2 font-bold text-base"><ListChecks className="size-4 text-primary" /> 작업 흐름 반영</h3>
                      <span className="text-xs text-muted-foreground">{projectTasks.length}개 작업</span>
                    </div>
                    <p className="mt-2 rounded-lg border border-border bg-background p-3 text-sm leading-6 text-foreground">
                      메일과 스레드 근거가 연결된 실행 항목을 기준으로 상태와 완료 흐름을 집계합니다.
                    </p>
                    <p className="mt-3 flex items-center gap-2 text-xs font-semibold text-muted-foreground"><User className="size-3.5" /> 근거: 실행 항목</p>
                  </article>
                  <article className="p-5">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="flex items-center gap-2 font-bold text-base"><Search className="size-4 text-primary" /> 관련 문서/메일 연결</h3>
                      <a href="/search" className="rounded-md border border-border bg-background px-2.5 py-1 text-xs font-bold hover:bg-secondary">맥락 검색</a>
                    </div>
                    <p className="mt-2 rounded-lg border border-border bg-background p-3 text-sm leading-6 text-foreground">
                      프로젝트 판단 근거는 맥락 검색에서 메일, 스레드, 문서 근거를 확인한 뒤 연결합니다.
                    </p>
                    <p className="mt-3 flex items-center gap-2 text-xs font-semibold text-muted-foreground"><User className="size-3.5" /> 상태: 연결 준비</p>
                  </article>
                </div>
              </section>
            )}

            <section aria-label="프로젝트 작업 목록" className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
              <div className="flex items-center justify-between border-b border-border p-5">
                <h2 className="font-bold text-lg">연결 작업</h2>
                <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-bold text-muted-foreground">{projectTasks.length}건</span>
              </div>
              {projectTasks.length > 0 ? (
                <ol className="divide-y divide-border">
                  {projectTasks.slice(0, 8).map((task) => (
                    <li key={task.id} className="grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_auto]">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${taskStatusClass[task.status]}`}>{taskStatusLabel[task.status]}</span>
                          <span className="rounded-full bg-secondary px-2.5 py-1 text-xs font-bold text-muted-foreground">{priorityLabel[task.priority]}</span>
                          <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-bold text-primary">{getTaskSourceLabel(task.source_type)}</span>
                        </div>
                        <h3 className="mt-2 break-keep font-bold text-sm">{safeText(task.title, '제목 없는 작업')}</h3>
                        <p className="mt-1 text-xs font-semibold text-muted-foreground">{getTaskEvidenceLabel(task)}</p>
                      </div>
                      <time className="flex items-center gap-1 text-xs text-muted-foreground sm:justify-end"><Clock className="size-3" />{formatDate(task.updated_at)}</time>
                    </li>
                  ))}
                </ol>
              ) : (
                <div className="p-5">
                  <p className="rounded-xl border border-dashed border-border p-4 text-sm font-semibold text-muted-foreground">연결된 실행 항목이 아직 없습니다.</p>
                </div>
              )}
            </section>
          </div>

          <aside className="space-y-6">
            <section aria-label="프로젝트 액션" className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <h2 className="mb-4 font-bold text-base">프로젝트 액션</h2>
              <div className="grid gap-2 text-sm">
                <a href="/data" className="flex min-h-10 items-center gap-2 rounded-md bg-primary px-3 font-bold text-primary-foreground hover:bg-primary/90"><FolderOpen className="size-4" /> 새 프로젝트</a>
                <button type="button" aria-label="프로젝트 상세 열기" onClick={() => setViewMode('프로젝트 상세')} className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 flex min-h-10 items-center gap-2 rounded-md border border-border bg-background px-3 font-bold hover:bg-secondary"><CheckCircle2 className="size-4 text-primary" /> 프로젝트 열기</button>
                <a href="/tasks" className="flex min-h-10 items-center gap-2 rounded-md border border-border bg-background px-3 font-bold hover:bg-secondary"><ListChecks className="size-4 text-primary" /> 마일스톤 추가</a>
                <button type="button" aria-label="프로젝트 의사결정 추가" onClick={() => setViewMode('의사결정 로그')} className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 flex min-h-10 items-center gap-2 rounded-md border border-border bg-background px-3 font-bold hover:bg-secondary"><CheckCircle2 className="size-4 text-primary" /> 의사결정 추가</button>
                <a href="/search" className="flex min-h-10 items-center gap-2 rounded-md border border-border bg-background px-3 font-bold hover:bg-secondary"><Search className="size-4 text-primary" /> 관련 문서/메일 연결</a>
              </div>
            </section>

            <section aria-label="프로젝트 개요" className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <h2 className="mb-4 font-bold text-base">프로젝트 개요</h2>
              <dl className="space-y-4 text-sm">
                <div>
                  <dt className="mb-1 font-semibold text-muted-foreground">책임 경계</dt>
                  <dd className="flex items-center gap-2 font-bold"><User className="size-4 text-primary" /> {workspaceScopeLabel}</dd>
                </div>
                <div>
                  <dt className="mb-1 font-semibold text-muted-foreground">상태</dt>
                  <dd><span className={`rounded px-2 py-1 text-xs font-bold ${projectStatusClass[activeProject.status]}`}>{activeProject.status}</span></dd>
                </div>
                <div>
                  <dt className="mb-1 font-semibold text-muted-foreground">진행률</dt>
                  <dd className="flex items-center gap-3">
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-border">
                      <div className="h-full bg-primary" style={{ width: `${activeProject.progress}%` }} />
                    </div>
                    <span className="font-mono text-xs font-bold">{activeProject.progress}%</span>
                  </dd>
                </div>
                <div>
                  <dt className="mb-1 font-semibold text-muted-foreground">원본 근거</dt>
                  <dd className="text-sm font-bold">{projectEvidenceLabel}</dd>
                  <dd className="mt-1 text-xs font-semibold text-muted-foreground">{projectBoundaryLabel}</dd>
                </div>
              </dl>
            </section>

            <section aria-label="연결된 자원" className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <h2 className="mb-4 font-bold text-base">연결된 자원</h2>
              <ul className="space-y-3 text-sm">
                <li className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 font-semibold"><FolderOpen className="size-4 text-primary" /> WebDAV 폴더</span>
                  <span className="font-mono text-xs text-muted-foreground">{authorizedFolders.length}</span>
                </li>
                <li className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 font-semibold"><ListChecks className="size-4 text-primary" /> 실행 항목</span>
                  <span className="font-mono text-xs text-muted-foreground">{projectTasks.length}</span>
                </li>
                <li className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 font-semibold"><CalendarDays className="size-4 text-primary" /> 원본 종류</span>
                  <span className="font-mono text-xs text-muted-foreground">{sourceTypeCount}</span>
                </li>
              </ul>
            </section>
          </aside>
        </div>
      </main>
    </div>
  );
}
