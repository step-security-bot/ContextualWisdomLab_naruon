import { useState, useCallback } from 'react';
import { apiClient } from '@/lib/api-client';
import { toSafeReactText } from '@/lib/safe-text';

export type TaskItem = {
  id: string;
  title: string;
  status: 'open' | 'in_progress' | 'blocked' | 'done';
  priority: 'low' | 'normal' | 'high' | 'urgent';
  created_at: string;
  updated_at: string;
};

type ReplySlaEscalationResponse = {
  evaluated: number;
  created: number;
  policy: {
    overdue_hours: number;
  };
};

function safeWorkspaceTitle(title: string | null | undefined, fallback = '제목 없는 항목') {
  const displayTitle = toSafeReactText(title?.trim() || null, fallback)
    .replace(/<[^>]*>/g, ' ')
    .replace(/[<>]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return displayTitle || fallback;
}

export function useTasks(initialTasks: TaskItem[], setTasks: React.Dispatch<React.SetStateAction<TaskItem[]>>) {
  const [taskUpdateStatusById, setTaskUpdateStatusById] = useState<Map<string, string>>(() => new Map());
  const [replySlaStatus, setReplySlaStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [replySlaMessage, setReplySlaMessage] = useState<string | null>(null);

  const handleTaskCompletionToggle = useCallback(async (task: TaskItem) => {
    const nextStatus: TaskItem['status'] = task.status === 'done' ? 'open' : 'done';
    const displayTitle = safeWorkspaceTitle(task.title, '제목 없는 작업');

    setTaskUpdateStatusById((currentStatuses) => {
      const nextStatuses = new Map(currentStatuses);
      nextStatuses.delete(task.id);
      return nextStatuses;
    });

    setTasks((currentTasks) =>
      currentTasks.map((currentTask) => (
        currentTask.id === task.id
          ? { ...currentTask, status: nextStatus, updated_at: new Date().toISOString() }
          : currentTask
      )),
    );

    try {
      const updatedTask = await apiClient.patch<TaskItem>(
        `/api/tasks/${encodeURIComponent(task.id)}`,
        { status: nextStatus },
      );
      setTasks((currentTasks) =>
        currentTasks.map((currentTask) => (currentTask.id === updatedTask.id ? updatedTask : currentTask)),
      );
      setTaskUpdateStatusById((currentStatuses) => {
        const nextStatuses = new Map(currentStatuses);
        nextStatuses.set(task.id, `${displayTitle} 작업을 완료 처리했습니다.`);
        return nextStatuses;
      });
    } catch {
      setTasks((currentTasks) =>
        currentTasks.map((currentTask) => (currentTask.id === task.id ? task : currentTask)),
      );
      setTaskUpdateStatusById((currentStatuses) => {
        const nextStatuses = new Map(currentStatuses);
        nextStatuses.set(task.id, `${displayTitle} 작업 상태 변경에 실패했습니다.`);
        return nextStatuses;
      });
    }
  }, [setTasks]);

  const handleReplySlaEscalation = useCallback(async () => {
    setReplySlaStatus('loading');
    setReplySlaMessage(null);
    try {
      const result = await apiClient.post<ReplySlaEscalationResponse>(
        '/api/tasks/reply-sla-escalations',
        { overdue_hours: 48 },
      );
      setReplySlaStatus('ready');
      setReplySlaMessage(`${result.created}개 팔로업 작업 생성, ${result.evaluated}개 답변 대기 확인`);
    } catch {
      setReplySlaStatus('error');
      setReplySlaMessage('미답변 팔로업 작업 생성 실패');
    }
  }, []);

  return {
    taskUpdateStatusById,
    replySlaStatus,
    replySlaMessage,
    handleTaskCompletionToggle,
    handleReplySlaEscalation
  };
}
