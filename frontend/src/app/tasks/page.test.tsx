/* @vitest-environment jsdom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => <a href={href} {...props}>{children}</a>,
}));

vi.mock("lucide-react", () => ({
  AlertCircle: () => <svg aria-hidden="true" />,
  CalendarDays: () => <svg aria-hidden="true" />,
  CheckCircle2: () => <svg aria-hidden="true" />,
  Filter: () => <svg aria-hidden="true" />,
  Inbox: () => <svg aria-hidden="true" />,
  ListChecks: () => <svg aria-hidden="true" />,
  Search: () => <svg aria-hidden="true" />,
  ShieldCheck: () => <svg aria-hidden="true" />,
  User: () => <svg aria-hidden="true" />,
  UserRoundCheck: () => <svg aria-hidden="true" />,
  Plus: () => <svg aria-hidden="true" />,
  X: () => <svg aria-hidden="true" />,
}));

import TasksPage from "./page";

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 500) {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Server Error",
    json: async () => body,
  } as Response;
}

async function flushAsyncWork() {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("TasksPage", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(() => {
    if (root) act(() => root?.unmount());
    root = null;
    container?.remove();
    container = null;
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("renders ticket tracking screens with source-backed empty states", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<TasksPage />);
    });
    await flushAsyncWork();

    expect(container.querySelector("h1")?.textContent).toContain("실행 항목 추적");
    expect(container.textContent).toContain("실행 항목 추적");
    expect(container.textContent).toContain("위임한 작업");
    expect(container.textContent).toContain("실제 티켓 큐");
    expect(container.textContent).toContain("연결된 티켓 없음");
    expect(container.textContent).toContain("메일 상세에서 실행 항목을 만들면 원본 연결 티켓으로 표시됩니다.");
    expect(container.querySelector('a[href="/mail"]')?.textContent).toContain("메일에서 작업 생성");
  });

  it("loads source-linked tickets from the signed task API without exposing raw source ids", async () => {
    const publicIdentityHeaders = [
      "x-user-id",
      "x-organization-id",
      "x-group-id",
      "x-group-ids",
      "x-user-role",
      "x-dev-auth-token",
    ];
    const fetchMock = vi.fn(async () => jsonResponse([
      {
        id: "task_public_123",
        title: "보낸 메일 회신 추적",
        status: "in_progress",
        priority: "high",
        source_type: "email",
        source_email_id: "mail_public_456",
        related_thread_id: "thread_public_789",
        updated_at: "2026-05-26T09:00:00.000Z",
      },
      {
        id: "task-webdav-markup",
        title: "<script>문서 원본 검토</script>",
        status: "blocked",
        priority: "normal",
        source_type: "webdav",
        source_email_id: null,
        related_thread_id: null,
        updated_at: "2026-05-26T09:10:00.000Z",
      },
    ]));
    vi.stubGlobal("fetch", fetchMock);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<TasksPage />);
    });
    await flushAsyncWork();

    expect(fetchMock).toHaveBeenCalledWith("/api/tasks", expect.objectContaining({
      credentials: "same-origin",
      headers: expect.objectContaining({
        "Content-Type": "application/json",
      }),
    }));
    const firstFetchCall = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit?] | undefined;
    const firstCallHeaders = firstFetchCall?.[1]?.headers as Record<string, string> | undefined;
    expect(firstCallHeaders).not.toHaveProperty("Authorization");
    for (const headerName of publicIdentityHeaders) {
      expect(Object.keys(firstCallHeaders ?? {}).some((key) => key.toLowerCase() === headerName)).toBe(false);
    }
    expect(container.textContent).toContain("2개 티켓 연결");
    expect(container.textContent).toContain("보낸 메일 회신 추적");
    expect(container.textContent).toContain("문서 원본 검토");
    expect(container.textContent).toContain("메일 근거");
    expect(container.textContent).toContain("스레드 근거 연결됨");
    expect(container.textContent).not.toContain("<script>");
    expect(container.textContent).not.toContain("mail_public_456");
    expect(container.textContent).not.toContain("thread_public_789");

    const taskSearchInput = container.querySelector<HTMLInputElement>('input[aria-label="작업 맥락 검색"]');
    expect(taskSearchInput).not.toBeNull();
    expect(taskSearchInput?.type).toBe("search");
    expect(taskSearchInput?.inputMode).toBe("search");
    expect(taskSearchInput?.getAttribute("role")).toBe("searchbox");
    await act(async () => {
      if (!taskSearchInput) return;
      const setInputValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setInputValue?.call(taskSearchInput, "보낸");
      taskSearchInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await flushAsyncWork();
    expect(container.textContent).toContain("보낸 메일 회신 추적");
    expect(container.textContent).not.toContain("문서 원본 검토");

    const clearSearchButton = container.querySelector<HTMLButtonElement>('button[aria-label="맥락 검색어 지우기"]');
    expect(clearSearchButton).not.toBeNull();
    await act(async () => {
      clearSearchButton?.click();
    });
    await flushAsyncWork();
    expect(taskSearchInput?.value).toBe("");
    expect(document.activeElement).toBe(taskSearchInput);
    expect(container.textContent).toContain("문서 원본 검토");
  });

  it("updates ticket status through the signed task API", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/tasks/task_public_123" && init?.method === "PATCH") {
        expect(init.credentials).toBe("same-origin");
        expect(init.headers).toEqual(expect.objectContaining({
          "Content-Type": "application/json",
        }));
        expect(init.headers).not.toHaveProperty("Authorization");
        expect(JSON.parse(String(init.body))).toEqual({ status: "done" });
        return jsonResponse({
          id: "task_public_123",
          title: "보낸 메일 회신 추적",
          status: "done",
          priority: "high",
          source_type: "email",
          source_email_id: "mail_public_456",
          related_thread_id: "thread_public_789",
          updated_at: "2026-05-26T10:00:00.000Z",
        });
      }
      return jsonResponse([
        {
          id: "task_public_123",
          title: "보낸 메일 회신 추적",
          status: "in_progress",
          priority: "high",
          source_type: "email",
          source_email_id: "mail_public_456",
          related_thread_id: "thread_public_789",
          updated_at: "2026-05-26T09:00:00.000Z",
        },
      ]);
    });
    vi.stubGlobal("fetch", fetchMock);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<TasksPage />);
    });
    await flushAsyncWork();

    const doneButton = container.querySelector<HTMLButtonElement>('button[aria-label="보낸 메일 회신 추적 상태를 완료로 변경"]');
    expect(doneButton).not.toBeNull();
    await act(async () => {
      doneButton?.click();
    });
    await flushAsyncWork();

    expect(fetchMock).toHaveBeenCalledWith("/api/tasks/task_public_123", expect.objectContaining({
      method: "PATCH",
    }));
    expect(container.textContent).toContain("보낸 메일 회신 추적 상태를 완료로 변경했습니다.");
    expect(doneButton?.getAttribute("aria-pressed")).toBe("true");
  });

  it("creates overdue reply follow-up tasks with signed headers", async () => {
    const publicIdentityHeaders = [
      "x-user-id",
      "x-organization-id",
      "x-group-id",
      "x-group-ids",
      "x-user-role",
      "x-dev-auth-token",
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/tasks/reply-sla-escalations") {
        const headers = init?.headers as Record<string, string>;
        expect(init?.method).toBe("POST");
        expect(init?.credentials).toBe("same-origin");
        expect(headers.Authorization).toBeUndefined();
        expect(headers["Content-Type"]).toBe("application/json");
        for (const headerName of publicIdentityHeaders) {
          expect(Object.keys(headers).some((key) => key.toLowerCase() === headerName)).toBe(false);
        }
        expect(JSON.parse(String(init?.body))).toEqual({ overdue_hours: 48 });
        return jsonResponse({
          evaluated: 2,
          created: 1,
          policy: { overdue_hours: 48 },
          tasks: [
            {
              id: "task-reply-sla-urgent",
              title: "미답변 팔로업: 벤더 계약 답변 요청",
              status: "blocked",
              priority: "urgent",
              source_type: "reply_sla",
              source_email_id: "<sent-q2@example.com>",
              related_thread_id: "thread-sent-q2",
              updated_at: "2026-05-26T11:00:00.000Z",
            },
          ],
        });
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<TasksPage />);
    });
    await flushAsyncWork();

    const escalationButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="보낸 메일 미답변 팔로업 작업 생성"]',
    );
    expect(escalationButton).not.toBeNull();
    await act(async () => {
      escalationButton?.click();
    });
    await flushAsyncWork();

    expect(fetchMock).toHaveBeenCalledWith("/api/tasks/reply-sla-escalations", expect.objectContaining({
      method: "POST",
    }));
    expect(container.textContent).toContain("1개 미답변 팔로업 작업을 생성했습니다. 2개 대기 메일을 48시간 기준으로 확인했습니다.");
    expect(container.textContent).toContain("미답변 팔로업: 벤더 계약 답변 요청");
    expect(container.textContent).toContain("답장 대기 메일");
    expect(container.textContent).toContain("스레드 근거 연결됨");
    expect(container.textContent).not.toContain("<sent-q2@example.com>");
    expect(container.textContent).not.toContain("thread-sent-q2");
  });

  it("creates self-sent knowledge WebDAV materialization intent with signed headers", async () => {
    const publicIdentityHeaders = [
      "x-user-id",
      "x-organization-id",
      "x-group-id",
      "x-group-ids",
      "x-user-role",
      "x-dev-auth-token",
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/webdav/knowledge-materialization-intent") {
        const headers = init?.headers as Record<string, string>;
        expect(init?.method).toBe("POST");
        expect(init?.credentials).toBe("same-origin");
        expect(headers.Authorization).toBeUndefined();
        expect(headers["Content-Type"]).toBe("application/json");
        for (const headerName of publicIdentityHeaders) {
          expect(Object.keys(headers).some((key) => key.toLowerCase() === headerName)).toBe(false);
        }
        expect(JSON.parse(String(init?.body))).toEqual({ source_task_id: "task-self-knowledge" });
        return jsonResponse({
          intent: "knowledge_materialization",
          status: "intent_ready",
          task_id: "task-self-knowledge",
          source_type: "self_sent_knowledge",
          source_email_id: "<self-note@example.com>",
          source_thread_id: "thread-self-note",
          source_id: "webdav_src_primary",
          target_label: "WebDAV source webdav_src_primary",
          target_path: "/Naruon/Notes/task-self-knowledge.md",
          requires_if_match: true,
          provenance: "server-authoritative",
          provider_write_executed: false,
          audit_event: "webdav.self_sent_knowledge_intent.created",
        });
      }
      return jsonResponse([
        {
          id: "task-self-knowledge",
          title: "나에게 보낸 지식 메모 정리",
          status: "open",
          priority: "normal",
          source_type: "self_sent_knowledge",
          source_email_id: "<self-note@example.com>",
          related_thread_id: "thread-self-note",
          updated_at: "2026-05-26T09:00:00.000Z",
        },
      ]);
    });
    vi.stubGlobal("fetch", fetchMock);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<TasksPage />);
    });
    await flushAsyncWork();

    const intentButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="나에게 보낸 지식 메모 정리 WebDAV 지식 노트 의도 생성"]',
    );
    expect(intentButton).not.toBeNull();
    await act(async () => {
      intentButton?.click();
    });
    await flushAsyncWork();

    expect(fetchMock).toHaveBeenCalledWith("/api/webdav/knowledge-materialization-intent", expect.objectContaining({
      method: "POST",
    }));
    expect(container.textContent).toContain("WebDAV/Notes 의도 준비");
    expect(container.textContent).toContain("의도만 기록");
    expect(container.textContent).toContain("충돌 검사 필요");
    expect(container.textContent).toContain("감사 근거");
    expect(container.textContent).not.toContain("/Naruon/Notes/task-self-knowledge.md");
    expect(container.textContent).not.toContain("WebDAV source webdav_src_primary");
    expect(container.textContent).not.toContain("webdav_src_primary");
    expect(container.textContent).not.toContain("<self-note@example.com>");
    expect(container.textContent).not.toContain("thread-self-note");
    expect(container.textContent).not.toContain("https://webdav.naruon.net");
    expect(container.textContent).not.toContain("provider_write_executed=false");
    expect(container.textContent).not.toContain("webdav.self_sent_knowledge_intent.created");
  });

  it("explicitly requests self-sent knowledge WebDAV provider execution with signed headers", async () => {
    const publicIdentityHeaders = [
      "x-user-id",
      "x-organization-id",
      "x-group-id",
      "x-group-ids",
      "x-user-role",
      "x-dev-auth-token",
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/webdav/knowledge-materialization-intent") {
        const headers = init?.headers as Record<string, string>;
        expect(init?.method).toBe("POST");
        expect(init?.credentials).toBe("same-origin");
        expect(headers.Authorization).toBeUndefined();
        expect(headers["Content-Type"]).toBe("application/json");
        for (const headerName of publicIdentityHeaders) {
          expect(Object.keys(headers).some((key) => key.toLowerCase() === headerName)).toBe(false);
        }
        expect(JSON.parse(String(init?.body))).toEqual({
          source_task_id: "task-self-knowledge",
          execute_provider: true,
        });
        return jsonResponse({
          intent: "knowledge_materialization",
          status: "queued",
          task_id: "task-self-knowledge",
          source_type: "self_sent_knowledge",
          source_email_id: "<self-note@example.com>",
          source_thread_id: "thread-self-note",
          source_id: "webdav_src_primary",
          target_label: "WebDAV source webdav_src_primary",
          target_path: "/Naruon/Notes/task-self-knowledge.md",
          requires_if_match: true,
          provenance: "server-authoritative",
          provider_write_executed: false,
          audit_event: "webdav.self_sent_knowledge_write.dispatch_failed",
          runner_request_id: "runner-request-webdav-1",
          retry_item_uid: "provider-retry-webdav-1",
        });
      }
      return jsonResponse([
        {
          id: "task-self-knowledge",
          title: "나에게 보낸 지식 메모 정리",
          status: "open",
          priority: "normal",
          source_type: "self_sent_knowledge",
          source_email_id: "<self-note@example.com>",
          related_thread_id: "thread-self-note",
          updated_at: "2026-05-26T09:00:00.000Z",
        },
      ]);
    });
    vi.stubGlobal("fetch", fetchMock);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<TasksPage />);
    });
    await flushAsyncWork();

    const executeButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="나에게 보낸 지식 메모 정리 WebDAV 지식 노트 실행 요청"]',
    );
    expect(executeButton).not.toBeNull();
    await act(async () => {
      executeButton?.click();
    });
    await flushAsyncWork();

    expect(fetchMock).toHaveBeenCalledWith("/api/webdav/knowledge-materialization-intent", expect.objectContaining({
      method: "POST",
    }));
    expect(container.textContent).toContain("커넥터 실행 요청 접수");
    expect(container.textContent).toContain("재시도 대기");
    expect(container.textContent).toContain("충돌 검사 필요");
    expect(container.textContent).not.toContain("/Naruon/Notes/task-self-knowledge.md");
    expect(container.textContent).not.toContain("WebDAV source webdav_src_primary");
    expect(container.textContent).not.toContain("webdav_src_primary");
    expect(container.textContent).not.toContain("runner-request-webdav-1");
    expect(container.textContent).not.toContain("provider-retry-webdav-1");
    expect(container.textContent).not.toContain("webdav.self_sent_knowledge_write.dispatch_failed");
  });

  it("distinguishes signed-session authorization failures from generic task API errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "forbidden" }, false, 403)));
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<TasksPage />);
    });
    await flushAsyncWork();

    expect(container.textContent).toContain("인증된 세션 필요");
    expect(container.textContent).toContain("서명 세션");
    expect(container.textContent).not.toContain("작업 API 오류");
  });
});
