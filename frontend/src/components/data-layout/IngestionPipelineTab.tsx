import React from 'react';
import { RefreshCw } from 'lucide-react';
import {
  DataQualitySurfaceResponse,
  DataSurfaceStatus
} from './types';
import {
  getSurfaceStatusLabel,
  getSurfaceStatusClass,
  getWriteBoundaryLabel
} from './utils';

interface IngestionPipelineTabProps {
  dataSurfaceStatus: DataSurfaceStatus;
  dataQualitySurface: DataQualitySurfaceResponse | null;
}

export function IngestionPipelineTab({
  dataSurfaceStatus,
  dataQualitySurface,
}: IngestionPipelineTabProps) {
  return (
<div className="space-y-6">
              <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
                <h2 className="font-bold text-lg mb-6">현재 파이프라인 진행률</h2>
                <div className="space-y-6">
                  {dataSurfaceStatus === 'loading' && (
                    <p className="text-sm font-semibold text-muted-foreground">파이프라인 근거를 확인하는 중입니다.</p>
                  )}
                  {dataSurfaceStatus === 'error' && (
                    <p className="text-sm font-bold text-red-700">파이프라인 근거를 불러오지 못했습니다.</p>
                  )}
                  {dataQualitySurface?.pipeline_stages.map((stage, index) => (
                    <div key={stage.stage_key}>
                      <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <span className="text-sm font-bold">{index + 1}. {stage.display_name}</span>
                          <p className="mt-1 text-xs text-muted-foreground">{stage.detail_text}</p>
                          <p className="mt-1 text-xs font-semibold text-muted-foreground">원본 근거 연결됨</p>
                        </div>
                        <span className={`w-fit shrink-0 rounded-full px-2 py-1 text-xs font-bold ${getSurfaceStatusClass(stage.status_code)}`}>
                          {getSurfaceStatusLabel(stage.status_code)} · {stage.progress_percent}%
                        </span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-secondary overflow-hidden">
                        <div
                          className="h-full bg-primary transition-all"
                          style={{ width: `${stage.progress_percent}%` }}
                        ></div>
                      </div>
                      <div className="mt-3 flex justify-end">
                        <span className="inline-flex items-center gap-1 rounded bg-secondary px-2 py-1 text-xs font-bold text-secondary-foreground">
                          <RefreshCw className="h-3 w-3" />
                          {getWriteBoundaryLabel(stage.provider_write_executed)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
  );
}
