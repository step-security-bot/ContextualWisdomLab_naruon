/* @vitest-environment jsdom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui/separator", () => ({
  Separator: () => <hr />,
}));

vi.mock("@/components/ui/avatar", () => ({
  Avatar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AvatarFallback: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("@/components/ui/checkbox", () => ({
  Checkbox: (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input type="checkbox" {...props} />
  ),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
}));

vi.mock("@/components/ui/textarea", () => ({
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea {...props} />
  ),
}));

vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}));

vi.mock("lucide-react", () => ({
  MessagesSquare: () => <svg aria-hidden="true" />,
  AlertCircle: () => <svg aria-hidden="true" />,
  RefreshCw: () => <svg aria-hidden="true" />,
  Info: () => <svg aria-hidden="true" />,
  Loader2: () => <svg aria-hidden="true" />,
}));

import { EmailDetail } from "./EmailDetail";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

type TestEmail = {
  id: number;
  message_id: string;
  thread_id: string | null;
  sender: string;
  recipients: string;
  subject: string;
  date: string;
  body: string;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((innerResolve) => {
    resolve = innerResolve;
  });
  return { promise, resolve };
}

function jsonResponse(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  };
}

async function flushAsyncWork() {
  for (let index = 0; index < 5; index += 1) {
    await act(async () => {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

async function waitForCondition(condition: () => boolean) {
  for (let index = 0; index < 20; index += 1) {
    if (condition()) return;
    await flushAsyncWork();
  }
}

describe("EmailDetail", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    root = null;
    container?.remove();
    container = null;
    vi.unstubAllGlobals();
  });

  it("renders untrusted detail fields as plain display text without markup", async () => {
    const email = {
      id: 15,
      message_id: "<markup-detail@example.com>",
      thread_id: null,
      sender: "<img src=x onerror=alert(1)>",
      recipients: "user@example.com",
      reply_to: "<script>alert(3)</script>",
      subject: "<script>alert(1)</script>",
      date: "2026-05-17T09:00:00Z",
      body: "hello\u0000<script>alert(2)</script >",
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/emails/15")) return Promise.resolve(jsonResponse(email));
      if (url.endsWith("/api/llm/summarize")) return Promise.resolve(jsonResponse({ summary: "정상 맥락 종합", todos: [] }));
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={15} />);
    });
    await flushAsyncWork();

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("(제목 없음)");
    expect(container.textContent).toContain("보낸 사람");
    expect(container.textContent).toContain("hello�");
    expect(container.textContent).not.toContain("<img");
    expect(container.textContent).not.toContain("<script>");
    expect(container.textContent).not.toContain("alert(1)");
    expect(container.textContent).not.toContain("alert(2)");
    expect(container.textContent).not.toContain("alert(3)");
  });

  it("keeps the latest conversation when an older thread request resolves late", async () => {
    const emailA: TestEmail = {
      id: 1,
      message_id: "<a@example.com>",
      thread_id: "thread-a",
      sender: "a@example.com",
      recipients: "user@example.com",
      subject: "Thread A",
      date: "2026-04-27T10:00:00Z",
      body: "Selected A body",
    };
    const emailB: TestEmail = {
      id: 2,
      message_id: "<b@example.com>",
      thread_id: "thread-b",
      sender: "b@example.com",
      recipients: "user@example.com",
      subject: "Thread B",
      date: "2026-04-27T11:00:00Z",
      body: "Selected B body",
    };
    const siblingB: TestEmail = {
      ...emailB,
      id: 3,
      message_id: "<b-sibling@example.com>",
      body: "Thread B sibling body",
    };
    const siblingA: TestEmail = {
      ...emailA,
      id: 4,
      message_id: "<a-sibling@example.com>",
      body: "Thread A stale sibling body",
    };

    const emailAResponse = deferred<ReturnType<typeof jsonResponse>>();
    const threadAResponse = deferred<ReturnType<typeof jsonResponse>>();
    const emailBResponse = deferred<ReturnType<typeof jsonResponse>>();
    const threadBResponse = deferred<ReturnType<typeof jsonResponse>>();

    const fetchMock = vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/emails/1")) return emailAResponse.promise;
        if (url.endsWith("/api/emails/2")) return emailBResponse.promise;
        if (url.endsWith("/api/emails/thread/thread-a")) return threadAResponse.promise;
        if (url.endsWith("/api/emails/thread/thread-b")) return threadBResponse.promise;
        if (url.endsWith("/api/llm/summarize")) {
          return Promise.resolve(jsonResponse({ summary: "Summary", todos: [] }));
        }
        throw new Error(`Unexpected fetch: ${url}`);
      });
    vi.stubGlobal("fetch", fetchMock);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={1} />);
    });

    await act(async () => {
      emailAResponse.resolve(jsonResponse(emailA));
      await emailAResponse.promise;
    });

    await act(async () => {
      root?.render(<EmailDetail emailId={2} />);
    });

    await act(async () => {
      emailBResponse.resolve(jsonResponse(emailB));
      await emailBResponse.promise;
      await Promise.resolve();
    });

    await waitForCondition(() =>
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith("/api/emails/thread/thread-b"),
      ),
    );

    await act(async () => {
      threadBResponse.resolve(jsonResponse({ thread: [emailB, siblingB] }));
      await threadBResponse.promise;
    });

    await waitForCondition(() =>
      container?.textContent?.includes("Thread B sibling body") ?? false,
    );

    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain(
      "/api/emails/thread/thread-b",
    );
    expect(container.textContent).toContain("Thread B sibling body");
    expect(container.textContent).toContain("2개 메시지");

    await act(async () => {
      threadAResponse.resolve(jsonResponse({ thread: [emailA, siblingA] }));
      await threadAResponse.promise;
    });
    await flushAsyncWork();

    expect(container.textContent).toContain("Thread B sibling body");
    expect(container.textContent).toContain("2개 메시지");
    expect(container.textContent).not.toContain("Thread A stale sibling body");
  });

  it("renders 맥락 종합, action items, and reply drafting in reusable 판단 포인트 cards", async () => {
    const email: TestEmail = {
      id: 7,
      message_id: "<insight@example.com>",
      thread_id: null,
      sender: "insight@example.com",
      recipients: "user@example.com",
      subject: "판단 포인트 카드 adoption",
      date: "2026-05-17T10:00:00Z",
      body: "Please summarize this launch message and prepare actions.",
    };

    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/emails/7")) return Promise.resolve(jsonResponse(email));
      if (url.endsWith("/api/llm/summarize")) {
        return Promise.resolve(jsonResponse({
          summary: "출시 메시지의 핵심 맥락입니다.",
          todos: ["캘린더에 출시 리뷰 일정을 반영", "답장 초안 준비"],
          confidence: 0.82,
        }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }));

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={7} />);
    });
    await waitForCondition(() => container?.textContent?.includes("출시 메시지의 핵심 맥락입니다.") ?? false);

    const cards = Array.from(container.querySelectorAll<HTMLElement>('article[data-decision-point-card="true"]'));
    expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual(
      expect.arrayContaining(["맥락 종합", "실행 항목", "답장 초안"]),
    );
    expect(cards.find((card) => card.getAttribute("aria-label") === "답장 초안")?.querySelector('[role="heading"][aria-level="3"]')?.textContent).toContain("답장 초안");
    expect(cards.find((card) => card.getAttribute("aria-label") === "맥락 종합")?.textContent).toContain("출시 메시지의 핵심 맥락입니다.");
    expect(cards.find((card) => card.getAttribute("aria-label") === "맥락 종합")?.textContent).toContain("82%");
    expect(cards.find((card) => card.getAttribute("aria-label") === "실행 항목")?.textContent).toContain("캘린더에 출시 리뷰 일정을 반영");
    expect(cards.find((card) => card.getAttribute("aria-label") === "실행 항목")?.textContent).toContain("82%");
    expect(cards.find((card) => card.getAttribute("aria-label") === "답장 초안")?.querySelector('textarea[aria-label="답장 초안"]')).not.toBeNull();
  });

  it("lets users create tasks from visible execution items in the email detail", async () => {
    const email: TestEmail = {
      id: 14,
      message_id: "<tasks@example.com>",
      thread_id: null,
      sender: "tasks@example.com",
      recipients: "user@example.com",
      subject: "Visible task action",
      date: "2026-05-18T09:00:00Z",
      body: "Please convert these follow-ups into tasks.",
    };

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/emails/14")) return Promise.resolve(jsonResponse(email));
      if (url.endsWith("/api/llm/summarize")) {
        return Promise.resolve(jsonResponse({
          summary: "후속 실행 항목을 정리해야 합니다.",
          todos: ["담당자 확인", "일정 공유"],
        }));
      }
      if (url.endsWith("/api/tasks/from-email")) {
        expect(init?.method).toBe("POST");
        expect(init?.credentials).toBe("same-origin");
        expect(init?.headers).toMatchObject({
          "Content-Type": "application/json",
        });
        expect(init?.headers).not.toHaveProperty("Authorization");
        expect(JSON.parse(String(init?.body))).toEqual({
          source_email_id: "<tasks@example.com>",
          thread_id: "<tasks@example.com>",
          items: ["담당자 확인", "일정 공유"],
        });
        return Promise.resolve(jsonResponse({
          created: 2,
          tasks: [
            { id: "task_01HZXOPAQUE001", title: "담당자 확인", status: "open", priority: "normal", source_type: "email", source_email_id: "<tasks@example.com>", related_thread_id: "<tasks@example.com>", created_at: "2026-05-19T00:00:00Z", updated_at: "2026-05-19T00:00:00Z" },
            { id: "task_01HZXOPAQUE002", title: "일정 공유", status: "open", priority: "normal", source_type: "email", source_email_id: "<tasks@example.com>", related_thread_id: "<tasks@example.com>", created_at: "2026-05-19T00:00:00Z", updated_at: "2026-05-19T00:00:00Z" },
          ],
        }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={14} />);
    });
    await waitForCondition(() => container?.textContent?.includes("후속 실행 항목을 정리해야 합니다.") ?? false);

    const actionCard = Array.from(container.querySelectorAll<HTMLElement>('article[data-decision-point-card="true"]')).find(
      (card) => card.getAttribute("aria-label") === "실행 항목",
    );
    const createTaskButton = Array.from(actionCard?.querySelectorAll<HTMLButtonElement>("button") ?? []).find(
      (button) => button.textContent?.includes("실행 항목 생성"),
    );

    expect(createTaskButton).not.toBeUndefined();

    await act(async () => {
      createTaskButton?.click();
    });

    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain("/api/tasks/from-email");
    expect(actionCard?.textContent).toContain("2개 실행 항목을 티켓형 실행 항목으로 추적합니다.");
  });

  it("clears conversation loading when the latest email has no thread", async () => {
    const threadedEmail: TestEmail = {
      id: 1,
      message_id: "<threaded@example.com>",
      thread_id: "thread-a",
      sender: "threaded@example.com",
      recipients: "user@example.com",
      subject: "Threaded",
      date: "2026-04-27T10:00:00Z",
      body: "Threaded body",
    };
    const standaloneEmail: TestEmail = {
      id: 3,
      message_id: "<standalone@example.com>",
      thread_id: null,
      sender: "standalone@example.com",
      recipients: "user@example.com",
      subject: "Standalone",
      date: "2026-04-27T12:00:00Z",
      body: "Standalone body",
    };

    const threadedEmailResponse = deferred<ReturnType<typeof jsonResponse>>();
    const threadResponse = deferred<ReturnType<typeof jsonResponse>>();
    const standaloneEmailResponse = deferred<ReturnType<typeof jsonResponse>>();

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.endsWith("/api/emails/1")) return threadedEmailResponse.promise;
      if (url.endsWith("/api/emails/3")) return standaloneEmailResponse.promise;
      if (url.endsWith("/api/emails/thread/thread-a")) return threadResponse.promise;
      if (url.endsWith("/api/llm/summarize")) {
        return Promise.resolve(jsonResponse({ summary: "Summary", todos: [] }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={1} />);
    });

    await act(async () => {
      threadedEmailResponse.resolve(jsonResponse(threadedEmail));
      await threadedEmailResponse.promise;
      await Promise.resolve();
    });

    await waitForCondition(() =>
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith("/api/emails/thread/thread-a"),
      ),
    );

    await act(async () => {
      root?.render(<EmailDetail emailId={3} />);
    });

    await act(async () => {
      standaloneEmailResponse.resolve(jsonResponse(standaloneEmail));
      await standaloneEmailResponse.promise;
      await Promise.resolve();
    });

    await waitForCondition(() =>
      container?.textContent?.includes("Standalone body") ?? false,
    );

    expect(container.textContent).toContain("Standalone body");
    expect(container.textContent).toContain("1개 메시지");
    expect(container.textContent).not.toContain("대화 흐름을 불러오는 중입니다...");
  });

  it("uses Korean-first labels for 맥락 종합 and execution actions", async () => {
    const email: TestEmail = {
      id: 5,
      message_id: "<label@example.com>",
      thread_id: null,
      sender: "label@example.com",
      recipients: "user@example.com",
      subject: "Label check",
      date: "2026-05-11T09:00:00Z",
      body: "Please review the launch plan.",
    };

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.endsWith("/api/emails/5")) return Promise.resolve(jsonResponse(email));
      if (url.endsWith("/api/llm/summarize")) {
        return Promise.resolve(
          jsonResponse({
            summary: "출시 계획 검토",
            todos: ["일정 확인"],
            confidence: 0.91,
          }),
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={5} />);
    });
    await flushAsyncWork();

    expect(container.textContent).toContain("맥락 종합");
    expect(container.textContent).toContain("판단 보조 생성");
    expect(container.textContent).toContain("실행 항목");
    expect(container.textContent).toContain("신뢰도 91%");
    expect(container.textContent).not.toContain("AI Generated");
    expect(container.textContent).not.toContain("Tasks");
  });

  it("runs a requested reply draft command for the selected email", async () => {
    const email: TestEmail = {
      id: 7,
      message_id: "<command@example.com>",
      thread_id: null,
      sender: "command@example.com",
      recipients: "user@example.com",
      subject: "Command check",
      date: "2026-05-17T09:00:00Z",
      body: "Please draft a launch update.",
    };
    const nextEmail: TestEmail = {
      ...email,
      id: 8,
      message_id: "<next-command@example.com>",
      subject: "Next command check",
      body: "Please draft a follow-up update.",
    };

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.endsWith("/api/emails/7")) return Promise.resolve(jsonResponse(email));
      if (url.endsWith("/api/emails/8")) return Promise.resolve(jsonResponse(nextEmail));
      if (url.endsWith("/api/llm/summarize")) {
        return Promise.resolve(jsonResponse({ summary: "출시 업데이트", todos: ["일정 확인"] }));
      }
      if (url.endsWith("/api/llm/draft")) {
        return Promise.resolve(jsonResponse({ draft: "초안 답장입니다." }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={7} actionCommand={{ id: 1, action: "reply-draft" }} />);
    });
    await flushAsyncWork();

    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain("/api/llm/draft");
    expect(container.querySelector<HTMLTextAreaElement>('#reply-draft')?.value).toBe("초안 답장입니다.");

    await act(async () => {
      root?.render(<EmailDetail emailId={7} actionCommand={{ id: 1, action: "reply-draft" }} />);
    });
    await flushAsyncWork();

    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/llm/draft"))).toHaveLength(1);

    await act(async () => {
      root?.render(<EmailDetail emailId={7} actionCommand={null} />);
    });
    await flushAsyncWork();
    await act(async () => {
      root?.render(<EmailDetail emailId={7} actionCommand={{ id: 1, action: "reply-draft" }} />);
    });
    await flushAsyncWork();

    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/llm/draft"))).toHaveLength(2);

    await act(async () => {
      root?.render(<EmailDetail emailId={8} actionCommand={{ id: 1, action: "reply-draft" }} />);
    });
    await flushAsyncWork();

    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/llm/draft"))).toHaveLength(3);
    const draftRequests = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/llm/draft"));
    expect(JSON.parse(String(draftRequests[2][1]?.body))).toMatchObject({
      email_body: "Please draft a follow-up update.",
    });
  });

  it("shows shell command feedback when an email has no todos", async () => {
    const email: TestEmail = {
      id: 12,
      message_id: "<empty-todos@example.com>",
      thread_id: null,
      sender: "empty@example.com",
      recipients: "user@example.com",
      subject: "No todos",
      date: "2026-05-17T12:00:00Z",
      body: "No follow-up needed.",
    };

    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/emails/12")) return Promise.resolve(jsonResponse(email));
      if (url.endsWith("/api/llm/summarize")) return Promise.resolve(jsonResponse({ summary: "후속 조치 없음", todos: [] }));
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={12} actionCommand={{ id: 3, action: "calendar-sync" }} />);
    });
    await flushAsyncWork();

    expect(container.textContent).toContain("캘린더에 반영할 실행 항목이 없습니다.");
  });

  it("waits for summary todos before requesting a server-authoritative calendar writeback intent", async () => {
    const email: TestEmail = {
      id: 9,
      message_id: "<calendar-command@example.com>",
      thread_id: null,
      sender: "calendar@example.com",
      recipients: "user@example.com",
      subject: "Calendar command",
      date: "2026-05-17T10:00:00Z",
      body: "Please sync the launch meeting.",
    };
    const summaryResponse = deferred<ReturnType<typeof jsonResponse>>();

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/emails/9")) return Promise.resolve(jsonResponse(email));
      if (url.endsWith("/api/llm/summarize")) return summaryResponse.promise;
      if (url.endsWith("/api/calendar/writeback-intent")) {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({ action: "create", summary: "출시 회의 일정 잡기" });
        return Promise.resolve(jsonResponse({
          workspace_id: "default",
          target_source_id: "caldav-primary",
          protocol: "caldav",
          writeback_mode: "customer_owned",
          requires_if_match: false,
          if_match: null,
          provenance: {
            created_by: "default",
            source_provider: "Customer CalDAV",
            source_protocol: "caldav",
          },
          audit_event: "calendar.writeback_intent.created",
        }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={9} actionCommand={{ id: 2, action: "calendar-sync" }} />);
    });
    await flushAsyncWork();

    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/calendar/writeback-intent"))).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/calendar/sync"))).toHaveLength(0);

    await act(async () => {
      summaryResponse.resolve(jsonResponse({ summary: "회의 일정", todos: ["출시 회의 일정 잡기"] }));
      await summaryResponse.promise;
    });
    await flushAsyncWork();

    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/calendar/writeback-intent"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/calendar/sync"))).toHaveLength(0);
    expect(container.textContent).toContain("1개 일정 반영 의도를 선택한 원본 계정에 요청했습니다.");
    expect(container.textContent).not.toContain("Customer CalDAV");
    expect(container.textContent).not.toContain("caldav-primary");
    expect(container.textContent).not.toContain("calendar.writeback_intent.created");
  });

  it("ignores a late draft response after the selected email changes", async () => {
    const emailA: TestEmail = {
      id: 10,
      message_id: "<late-a@example.com>",
      thread_id: null,
      sender: "late-a@example.com",
      recipients: "user@example.com",
      subject: "Late A",
      date: "2026-05-17T11:00:00Z",
      body: "Draft for A.",
    };
    const emailB: TestEmail = {
      ...emailA,
      id: 11,
      message_id: "<late-b@example.com>",
      subject: "Late B",
      body: "Draft for B.",
    };
    const draftResponse = deferred<ReturnType<typeof jsonResponse>>();

    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/emails/10")) return Promise.resolve(jsonResponse(emailA));
      if (url.endsWith("/api/emails/11")) return Promise.resolve(jsonResponse(emailB));
      if (url.endsWith("/api/llm/summarize")) {
        return Promise.resolve(jsonResponse({ summary: "맥락 종합", todos: ["일정 확인"] }));
      }
      if (url.endsWith("/api/llm/draft")) return draftResponse.promise;
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<EmailDetail emailId={10} actionCommand={{ id: 1, action: "reply-draft" }} />);
    });
    await flushAsyncWork();

    await act(async () => {
      root?.render(<EmailDetail emailId={11} actionCommand={null} />);
    });
    await flushAsyncWork();

    await act(async () => {
      draftResponse.resolve(jsonResponse({ draft: "A의 늦은 초안입니다." }));
      await draftResponse.promise;
    });
    await flushAsyncWork();

    expect(container.textContent).toContain("Late B");
    expect(container.querySelector<HTMLTextAreaElement>('#reply-draft')?.value).toBe("");
  });
});
