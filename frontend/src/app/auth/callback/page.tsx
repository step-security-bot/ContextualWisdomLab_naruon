"use client";

import { completeOidcRedirect } from '@/lib/oidc-session';
import { useEffect, useState } from 'react';

export function toSafeReturnTo(returnTo: string | null | undefined) {
  const candidate = returnTo?.trim() ?? '';
  if (
    !candidate ||
    !candidate.startsWith('/') ||
    candidate.startsWith('//') ||
    candidate.includes('\\') ||
    /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return '/';
  }
  return candidate;
}

export default function AuthCallbackPage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    completeOidcRedirect()
      .then(({ returnTo }) => {
        if (!cancelled) window.location.replace(toSafeReturnTo(returnTo));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'OIDC callback failed');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <section aria-label="OIDC 로그인 콜백" className="w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-sm">
        <h1 className="text-lg font-bold text-foreground">OIDC 로그인 확인</h1>
        {error ? (
          <p role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700">{error}</p>
        ) : (
          <p role="status" className="mt-3 text-sm font-semibold text-muted-foreground">세션을 확인하는 중입니다.</p>
        )}
      </section>
    </main>
  );
}
