import React, { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '@/lib/api-client';
import { Separator } from "@/components/ui/separator";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Loader2, MessagesSquare } from "lucide-react";
import { DecisionPointCard } from "@/components/DecisionPointCard";
import {
  buildThreadUrl,
  buildReplyPayload,
  formatEmailDate,
  getConversationMessages,
  type ThreadEmailData,
} from "@/lib/email-threading";
import { toMailBodyText, toMailDisplayText } from "@/lib/mail-text";
import { toConfidencePercent } from "@/lib/confidence";

type EmailData = ThreadEmailData & {
  requires_reply?: boolean;
  schedule_conflict?: boolean;
};
interface LlmData {
  summary: string;
  todos: string[];
  provenance?: string;
  confidence?: number;
}

interface CreateTasksFromEmailResponse {
  created: number;
}

interface CalendarWritebackIntentResponse {
  target_source_id: string;
  protocol: string;
  provider_write_executed?: boolean;
  status?: string;
  runner_request_id?: string | null;
  provider_status?: number | null;
  error_code?: string | null;
  provenance: {
    source_provider?: string;
  };
}

type EmailDetailActionCommand = {
  id: number;
  action: string;
};

export function EmailDetail({ emailId, actionCommand = null }: { emailId: number | null; actionCommand?: EmailDetailActionCommand | null }) {
  const [email, setEmail] = useState<EmailData | null>(null);
  const [threadEmails, setThreadEmails] = useState<EmailData[]>([]);
  const [llmData, setLlmData] = useState<LlmData | null>(null);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState<string | null>(null);

  const [draft, setDraft] = useState<string>('');
  const [isDrafting, setIsDrafting] = useState(false);
  const [isSending, setIsSending] = useState(false);
  
  const [draftError, setDraftError] = useState<string | null>(null);
  const [sendStatus, setSendStatus] = useState<{type: 'success' | 'error', message: string} | null>(null);
  const [instruction, setInstruction] = useState('정중하게 답장해줘');

  const [isSyncing, setIsSyncing] = useState(false);
  const [isCreatingTask, setIsCreatingTask] = useState(false);
  const [syncStatus, setSyncStatus] = useState<{type: 'success' | 'error', message: string} | null>(null);
  const [taskStatus, setTaskStatus] = useState<string | null>(null);
  const threadRequestIdRef = useRef(0);
  const handledActionCommandIdRef = useRef<number | null>(null);
  const currentEmailIdRef = useRef<number | null>(emailId);

  useEffect(() => {
    currentEmailIdRef.current = emailId;
  }, [emailId]);

  useEffect(() => {
    handledActionCommandIdRef.current = null;
  }, [emailId]);

  const fetchThread = useCallback(async (currentEmail: EmailData) => {
    const requestId = threadRequestIdRef.current + 1;
    threadRequestIdRef.current = requestId;
    const isLatestThreadRequest = () => requestId === threadRequestIdRef.current;

    setThreadError(null);

    if (!currentEmail.thread_id) {
      if (isLatestThreadRequest()) {
        setThreadLoading(false);
        setThreadEmails([currentEmail]);
      }
      return;
    }

    setThreadLoading(true);
    try {
      const threadJson = await apiClient.get<{ thread: EmailData[] }>(buildThreadUrl('', currentEmail.thread_id));
      if (!isLatestThreadRequest()) return;
      setThreadEmails(threadJson.thread || []);
    } catch (err) {
      if (!isLatestThreadRequest()) return;
      console.error("Error fetching thread:", err);
      setThreadError("대화 흐름을 불러오지 못했습니다.");
      setThreadEmails([currentEmail]);
    } finally {
      if (isLatestThreadRequest()) setThreadLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!emailId) return;
    
    let isMounted = true;

    const fetchData = async () => {
      threadRequestIdRef.current += 1;
      setLoading(true);
      setEmail(null);
      setThreadEmails([]);
      setThreadError(null);
      setDetailError(null);
      setLlmData(null);
      setLlmError(null);
      setDraft('');
      setDraftError(null);
      setSendStatus(null);
      setIsDrafting(false);
      setIsSending(false);
      setIsSyncing(false);
      setIsCreatingTask(false);
      setSyncStatus(null);
      setTaskStatus(null);

      try {
        const emailJson = await apiClient.get<EmailData>(`/api/emails/${emailId}`);
        
        if (!isMounted) return;
        setEmail(emailJson);
        setLoading(false); // Stop loading immediately so the user can read the email

        // Fetch thread in the background
        fetchThread(emailJson).catch((err) => {
          console.error("Unhandled error fetching thread:", err);
        });

        // Fetch LLM summary in the background
        apiClient.post<LlmData>('/api/llm/summarize', { email_body: emailJson.body })
          .then((llmJson) => {
            if (!isMounted) return;
            setLlmData(llmJson);
          })
          .catch((llmErr) => {
            console.error("Error generating LLM summary:", llmErr);
            if (isMounted) setLlmError("맥락 종합을 생성하지 못했습니다.");
          });

      } catch (err) {
        console.error("Error fetching email details:", err);
        if (isMounted) {
          setDetailError("메일 내용을 불러오지 못했습니다.");
          setLoading(false);
        }
      }
    };

    fetchData();

    return () => { isMounted = false; };
  }, [emailId, fetchThread]);

  const handleDraftReply = useCallback(async () => {
    if (!email) return;
    const actionEmailId = email.id;
    const isCurrentEmail = () => currentEmailIdRef.current === actionEmailId;
    setIsDrafting(true);
    setDraftError(null);
    setSendStatus(null);
    try {
      const data = await apiClient.post<{ draft: string }>('/api/llm/draft', { email_body: email.body, instruction });
      if (!isCurrentEmail()) return;
      setDraft(data.draft || '');
    } catch (err) {
      if (!isCurrentEmail()) return;
      console.error("Error drafting reply:", err);
      setDraftError("답장 초안을 생성하지 못했습니다.");
    } finally {
      if (isCurrentEmail()) setIsDrafting(false);
    }
  }, [email, instruction]);

  const handleSendReply = async () => {
    if (!email || !draft) return;
    setIsSending(true);
    setSendStatus(null);
    try {
      const data = await apiClient.post<{ simulated: boolean }>('/api/emails/send', buildReplyPayload(email, draft));
      setSendStatus({
        type: 'success',
        message: data.simulated
          ? '개발 모드에서 답장을 시뮬레이션했습니다. 실제 메일은 전송되지 않았습니다.'
          : '답장을 전송했습니다.',
      });
      setDraft('');
      await fetchThread(email);
    } catch (err) {
      console.error("Error sending email:", err);
      setSendStatus({ type: 'error', message: '답장 전송에 실패했습니다.' });
    } finally {
      setIsSending(false);
    }
  };

  const handleSyncCalendar = useCallback(async () => {
    const actionEmailId = emailId;
    const isCurrentEmail = () => currentEmailIdRef.current === actionEmailId;
    if (!llmData || !llmData.todos.length) {
      setSyncStatus({ type: 'error', message: '캘린더에 반영할 실행 항목이 없습니다.' });
      return;
    }
    setIsSyncing(true);
    setSyncStatus(null);
    try {
      const intents = await Promise.all(
        llmData.todos.map((summary) =>
          apiClient.post<CalendarWritebackIntentResponse>('/api/calendar/writeback-intent', {
            action: 'create',
            summary,
          }),
        ),
      );
      if (!isCurrentEmail()) return;
      setSyncStatus({ type: 'success', message: `${intents.length}개 일정 반영 의도를 선택한 원본 계정에 요청했습니다.` });
    } catch {
      if (!isCurrentEmail()) return;
      setSyncStatus({ type: 'error', message: '일정 반영 의도 요청에 실패했습니다.' });
    } finally {
      if (isCurrentEmail()) setIsSyncing(false);
    }
  }, [emailId, llmData]);

  const handleCreateTask = useCallback(async () => {
    const actionEmail = email;
    const actionEmailId = actionEmail?.id ?? null;
    const isCurrentEmail = () => currentEmailIdRef.current === actionEmailId;
    if (!actionEmail) return;
    if (!llmData || !llmData.todos.length) {
      setTaskStatus('정리할 실행 항목이 없습니다.');
      return;
    }
    setIsCreatingTask(true);
    setTaskStatus(null);
    try {
      const data = await apiClient.post<CreateTasksFromEmailResponse>('/api/tasks/from-email', {
        source_email_id: actionEmail.message_id,
        thread_id: actionEmail.thread_id || actionEmail.message_id,
        items: llmData.todos,
      });
      if (!isCurrentEmail()) return;
      setTaskStatus(`${data.created}개 실행 항목을 티켓형 실행 항목으로 추적합니다.`);
    } catch {
      if (!isCurrentEmail()) return;
      setTaskStatus('티켓형 실행 항목 생성에 실패했습니다.');
    } finally {
      if (isCurrentEmail()) setIsCreatingTask(false);
    }
  }, [email, llmData]);

  useEffect(() => {
    if (!actionCommand) {
      handledActionCommandIdRef.current = null;
      return;
    }
    if (!email || email.id !== emailId) return;
    if (handledActionCommandIdRef.current === actionCommand.id) return;

    if (actionCommand.action === 'reply-draft') {
      handledActionCommandIdRef.current = actionCommand.id;
      queueMicrotask(() => void handleDraftReply());
      return;
    }
    if (!llmData && !llmError) return;
    if (actionCommand.action === 'calendar-sync') {
      handledActionCommandIdRef.current = actionCommand.id;
      queueMicrotask(() => void handleSyncCalendar());
      return;
    }
    if (actionCommand.action === 'create-task') {
      handledActionCommandIdRef.current = actionCommand.id;
      queueMicrotask(() => void handleCreateTask());
    }
  }, [actionCommand, email, emailId, handleCreateTask, handleDraftReply, handleSyncCalendar, llmData, llmError]);

  if (!emailId) {
    return (
      <div className="flex h-full items-center justify-center bg-gradient-to-br from-card via-background to-primary/5 p-8 text-center text-muted-foreground">
        <div className="max-w-md rounded-3xl border border-primary/15 bg-card p-8 shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
          <div className="mx-auto mb-4 grid size-14 place-items-center rounded-2xl bg-primary/10 text-2xl" aria-hidden="true">✦</div>
          <h2 className="text-xl font-black tracking-tight text-foreground">메일을 선택하세요</h2>
          <p className="mt-2 text-sm leading-6">왼쪽 받은편지함에서 메일을 선택하면 Naruon이 맥락 종합, 판단 포인트, 실행 항목을 연결합니다.</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return <div role="status" aria-live="polite" className="flex h-full items-center justify-center bg-card text-muted-foreground">메일 내용을 불러오는 중입니다...</div>;
  }

  if (!email || detailError) {
    return <div role="alert" className="flex h-full items-center justify-center bg-card text-red-500">{detailError || '메일 내용을 불러오지 못했습니다.'}</div>;
  }

  const conversationMessages = getConversationMessages(email, threadEmails);
  const safeEmailSender = toMailDisplayText(email.sender, '보낸 사람');
  const safeEmailSubject = toMailDisplayText(email.subject, '(제목 없음)');
  const safeReplyTo = toMailDisplayText(email.reply_to || email.sender, '답장 주소 없음');
  const confidencePercent = toConfidencePercent(llmData?.confidence);

  return (
    <div className="flex h-full flex-col bg-card">
      <div className="flex items-start bg-gradient-to-br from-card via-card to-primary/5 p-6">
        <div className="flex w-full items-start gap-4 text-sm">
          <Avatar className="h-11 w-11 border border-primary/10 bg-primary/10 text-primary shadow-sm">
            <AvatarFallback>{safeEmailSender ? safeEmailSender.charAt(0).toUpperCase() : 'U'}</AvatarFallback>
          </Avatar>
          <div className="grid min-w-0 flex-1 gap-1">
            <div className="break-words text-lg font-black tracking-tight text-foreground xl:text-xl">{safeEmailSubject}</div>
            <div className="line-clamp-1 text-xs">
              <span className="text-muted-foreground">{safeEmailSender}</span>
            </div>
            <div className="line-clamp-1 text-xs text-muted-foreground">
              답장 주소: {safeReplyTo}
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="hidden whitespace-nowrap rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground shadow-sm 2xl:block">
              {formatEmailDate(email.date)}
            </div>
            {email.requires_reply && (
              <Badge variant="outline" className="border-primary/30 text-primary bg-primary/5 text-[10px]">응답 대기 중</Badge>
            )}
            {email.schedule_conflict && (
              <Badge variant="outline" className="border-emerald-500/30 text-emerald-700 bg-emerald-500/5 text-[10px]">일정 충돌 조율</Badge>
            )}
          </div>
        </div>
      </div>
      <Separator />
      <ScrollArea className="flex-1">
        <div className="flex flex-col gap-6 bg-background/50 p-6 pb-[calc(7rem+env(safe-area-inset-bottom))] lg:pb-6">
          
          <DecisionPointCard
            title="맥락 종합"
            icon={<span aria-hidden="true">✦</span>}
            loading={!llmData && !llmError}
            error={llmError}
            provenance={llmData?.provenance || "AI 생성"}
            confidence={confidencePercent}
          >
            {llmData ? (
              <div className="flex flex-col gap-2">
                <p className="text-sm">{llmData.summary}</p>
                <div className="flex justify-end">
                  <a href={`#msg-${email.id}`} className="text-[10px] text-primary hover:underline flex items-center gap-1 bg-primary/5 px-2 py-1 rounded">
                    근거 원본 보기
                  </a>
                </div>
              </div>
            ) : null}
          </DecisionPointCard>

          <DecisionPointCard
            title="실행 항목"
            icon={<span aria-hidden="true">✓</span>}
            loading={!llmData && !llmError}
            error={llmError ? '실행 항목을 추출하지 못했습니다.' : null}
            empty={Boolean(llmData && llmData.todos.length === 0)}
            emptyMessage="실행 항목이 없습니다."
            provenance={
              confidencePercent !== undefined ? `신뢰도 ${confidencePercent}%` : undefined
            }
            confidence={confidencePercent}
            footerActions={llmData && (llmData.todos.length > 0 || syncStatus || taskStatus) ? (
              <>
                {llmData.todos.length > 0 && (
                  <Button
                    size="sm"
                    onClick={handleSyncCalendar}
                    disabled={isSyncing}
                    aria-busy={isSyncing}
                    className="h-9 rounded-xl bg-emerald-600 px-4 text-white hover:bg-emerald-700"
                  >
                    {isSyncing && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
                    {isSyncing ? "동기화 중" : "일정 반영"}
                  </Button>
                )}
                {llmData.todos.length > 0 && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleCreateTask}
                    disabled={isCreatingTask}
                    aria-busy={isCreatingTask}
                    className="h-9 rounded-xl border-emerald-500/30 px-4 text-emerald-700 hover:bg-emerald-500/10"
                  >
                    {isCreatingTask && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
                    {isCreatingTask ? "추적 중" : "실행 항목 생성"}
                  </Button>
                )}
                {syncStatus && (
                  <span className={`self-center text-xs ${syncStatus.type === 'success' ? 'text-green-600' : 'text-red-500'}`}>
                    {syncStatus.message}
                  </span>
                )}
                {taskStatus && (
                  <span role="status" aria-live="polite" className="self-center text-xs text-emerald-700">
                    {taskStatus}
                  </span>
                )}
              </>
            ) : null}
          >
            {llmData ? (
              llmData.todos.length > 0 ? (
                <ul className="list-none space-y-2 text-sm">
                  {llmData.todos.map((todo, idx) => (
                    <li key={idx} className="flex items-start gap-3 rounded-xl border border-emerald-500/15 bg-emerald-500/5 p-3">
                      <Checkbox id={`todo-${idx}`} className="mt-1" />
                      <label htmlFor={`todo-${idx}`} className="font-semibold leading-5 text-foreground">{todo}</label>
                    </li>
                  ))}
                </ul>
              ) : null
            ) : null}
          </DecisionPointCard>

          <Separator />
          
          <div className="space-y-4 rounded-2xl border border-border bg-card p-4 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold flex items-center gap-2">
                  <MessagesSquare className="w-4 h-4 text-primary" /> 스레드 전체
                </h3>
                <Badge variant="secondary" className="text-[10px] flex items-center gap-1 border border-primary/10 bg-primary/10 text-primary">
                  <MessagesSquare className="w-3 h-3" />
                  {conversationMessages.length}개 메시지
                </Badge>
              </div>
              <Button size="sm" variant="outline" className="h-7 text-xs bg-white text-muted-foreground hover:text-foreground">
                다른 스레드 병합
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">오래된 메시지부터 최신 메시지 순서로 보여줍니다. 답장은 선택된 메시지를 기준으로 작성됩니다.</p>
            {threadLoading && <p role="status" aria-live="polite" className="text-sm text-muted-foreground">대화 흐름을 불러오는 중입니다...</p>}
            {threadError && (
              <div role="alert" className="flex items-center gap-3 text-sm text-red-500">
                <span>{threadError}</span>
                <Button size="sm" variant="outline" onClick={() => fetchThread(email)}>다시 시도</Button>
              </div>
            )}
            <div className="space-y-4">
              {conversationMessages.map((msg) => (
                <div id={`msg-${msg.id}`} key={msg.id} className={`rounded-2xl border p-4 text-card-foreground ${msg.id === email.id ? 'border-primary/60 bg-primary/5 shadow-sm' : 'border-border bg-background/60'}`} aria-current={msg.id === email.id ? "true" : undefined}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-sm">{toMailDisplayText(msg.sender, '보낸 사람')}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-muted-foreground">{formatEmailDate(msg.date)}</span>
                      {msg.id !== conversationMessages[0]?.id && (
                        <Button size="sm" variant="ghost" className="h-6 px-2 text-[10px] text-muted-foreground hover:text-red-600 hover:bg-red-50">
                          스레드 분리
                        </Button>
                      )}
                    </div>
                  </div>
                  {msg.id === email.id && <Badge variant="outline" className="mb-2 border-primary/30 text-[10px] text-primary">선택된 메시지</Badge>}
                  <div className="text-sm leading-6 whitespace-pre-wrap">{toMailBodyText(msg.body)}</div>
                </div>
              ))}
            </div>
          </div>

          <Separator />

          <DecisionPointCard title="답장 초안" provenance="사용자 확인 필요">
            <div className="flex flex-col sm:flex-row sm:items-end gap-2 justify-between">
              <div className="space-y-1.5 flex-1 max-w-sm">
                <label htmlFor="reply-instruction" className="sr-only">AI 답장 지시</label>
                <Input
                  id="reply-instruction"
                  aria-label="AI 답장 지시"
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  placeholder="예: 정중하게 답장해줘"
                  className="h-10 rounded-xl border-purple-500/20 bg-purple-500/5 text-xs"
                />
              </div>
              <Button 
                onClick={handleDraftReply} 
                disabled={isDrafting || !instruction}
                aria-busy={isDrafting}
                variant="outline"
                size="sm"
                className="h-10 rounded-xl border-purple-500/30 px-4 text-purple-700 hover:bg-purple-500/10"
              >
                {isDrafting && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
                {isDrafting ? "초안 작성 중" : "AI 답장 초안"}
              </Button>
            </div>
            
            {draftError && <p role="alert" className="text-sm text-red-500">{draftError}</p>}

            <label htmlFor="reply-draft" className="sr-only">답장 초안</label>
            <Textarea 
              id="reply-draft"
              aria-label="답장 초안"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="답장 초안을 작성하거나 AI 초안을 생성하세요..."
              className="min-h-[150px] rounded-2xl border-purple-500/20 bg-background/70"
            />
            
            <div className="flex items-center justify-between">
              <div>
                {sendStatus && (
                  <p role={sendStatus.type === 'error' ? 'alert' : 'status'} aria-live="polite" className={`text-sm ${sendStatus.type === 'success' ? 'text-green-600' : 'text-red-500'}`}>
                    {sendStatus.message}
                  </p>
                )}
              </div>
              <div className="flex gap-2">
                {draft && (
                  <Button 
                    onClick={() => { setDraft(''); setSendStatus(null); setDraftError(null); }} 
                    variant="ghost"
                    size="sm"
                    className="h-9 rounded-xl"
                  >
                    지우기
                  </Button>
                )}
                <Button 
                  onClick={handleSendReply} 
                  disabled={isSending || !draft}
                  aria-busy={isSending}
                  size="sm"
                  className="h-9 rounded-xl px-4"
                >
                  {isSending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
                  {isSending ? "전송 중" : "답장 보내기"}
                </Button>
              </div>
            </div>
          </DecisionPointCard>
        </div>
      </ScrollArea>
    </div>
  );
}
