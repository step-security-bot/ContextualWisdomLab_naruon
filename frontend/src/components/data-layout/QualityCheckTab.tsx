import React from 'react';
import {
  DataQualitySurfaceResponse,
  DataSurfaceStatus
} from './types';
import {
  formatCount,
  getSurfaceStatusLabel,
  getSurfaceStatusClass,
  getWriteBoundaryLabel
} from './utils';

interface QualityCheckTabProps {
  dataSurfaceStatus: DataSurfaceStatus;
  dataQualitySurface: DataQualitySurfaceResponse | null;
}

export function QualityCheckTab({
  dataSurfaceStatus,
  dataQualitySurface,
}: QualityCheckTabProps) {
  return (
<div className="space-y-6">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                {(dataQualitySurface?.quality_checks.slice(0, 3) ?? []).map((check) => (
                  <div key={check.check_key} className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                    <p className="text-xs font-bold text-muted-foreground mb-1">{check.display_name}</p>
                    <p className={`text-xl font-bold ${check.issue_count > 0 ? 'text-amber-600' : 'text-emerald-600'}`}>
                      {formatCount(check.issue_count)} / {formatCount(check.total_count)}
                    </p>
                    <span className={`mt-3 inline-flex rounded-full px-2 py-1 text-xs font-bold ${getSurfaceStatusClass(check.status_code)}`}>
                      {getSurfaceStatusLabel(check.status_code)}
                    </span>
                    <div className="mt-4 flex gap-2 justify-end border-t border-border pt-3">
                      <button type="button" className="rounded bg-secondary px-3 py-1.5 text-xs font-bold text-secondary-foreground hover:bg-secondary/80">
                        품질 점검
                      </button>
                      <button type="button" className="rounded bg-red-50 px-3 py-1.5 text-xs font-bold text-red-600 hover:bg-red-100 border border-red-200">
                        격리
                      </button>
                    </div>
                  </div>
                ))}
                {dataSurfaceStatus === 'loading' && (
                  <div className="rounded-2xl border border-border bg-card p-5 text-sm font-semibold text-muted-foreground shadow-sm md:col-span-3">
                    품질 점검 근거를 확인하는 중입니다.
                  </div>
                )}
                {dataSurfaceStatus === 'error' && (
                  <div className="rounded-2xl border border-border bg-card p-5 text-sm font-bold text-red-700 shadow-sm md:col-span-3">
                    품질 점검 근거를 불러오지 못했습니다.
                  </div>
                )}
              </div>
              <div className="rounded-2xl border border-border bg-card shadow-sm overflow-hidden">
                <div className="p-5 border-b border-border bg-secondary/30">
                  <h2 className="font-bold text-lg">품질 문제 항목</h2>
                </div>
                <div className="grid gap-3 p-5">
                  {dataQualitySurface?.quality_checks.map((check) => (
                    <article key={check.check_key} className="rounded-xl border border-border bg-background p-4">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <h3 className="text-sm font-black">{check.display_name}</h3>
                          <p className="mt-1 text-sm leading-6 text-muted-foreground">{check.detail_text}</p>
                          <p className="mt-1 text-xs font-semibold text-muted-foreground">원본 근거 연결됨</p>
                        </div>
                        <span className={`w-fit shrink-0 rounded-full px-2 py-1 text-xs font-bold ${getSurfaceStatusClass(check.status_code)}`}>
                          {getSurfaceStatusLabel(check.status_code)}
                        </span>
                      </div>
                      <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-3">
                        <div>
                          <dt className="font-black text-muted-foreground">이슈</dt>
                          <dd className="mt-1 text-sm font-bold">{formatCount(check.issue_count)}</dd>
                        </div>
                        <div>
                          <dt className="font-black text-muted-foreground">대상</dt>
                          <dd className="mt-1 text-sm font-bold">{formatCount(check.total_count)}</dd>
                        </div>
                        <div>
                          <dt className="font-black text-muted-foreground">쓰기 경계</dt>
                          <dd className="mt-1 text-sm font-bold">{getWriteBoundaryLabel(check.provider_write_executed)}</dd>
                        </div>
                      </dl>
                    </article>
                  ))}
                </div>
              </div>
            </div>
  );
}
