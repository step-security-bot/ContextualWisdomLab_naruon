import React from 'react';
import { RefreshCw } from 'lucide-react';
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

interface EmbeddingTabProps {
  dataSurfaceStatus: DataSurfaceStatus;
  dataQualitySurface: DataQualitySurfaceResponse | null;
}

export function EmbeddingTab({
  dataSurfaceStatus,
  dataQualitySurface,
}: EmbeddingTabProps) {
  return (
<div className="space-y-6">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                  <p className="text-xs font-bold text-muted-foreground mb-1">활성 모델</p>
                  <p className="break-all text-lg font-bold text-primary">
                    {dataQualitySurface?.embedding_collections[0]?.embedding_model ?? '확인 중'}
                  </p>
                </div>
                <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                  <p className="text-xs font-bold text-muted-foreground mb-1">벡터 차원</p>
                  <p className="text-lg font-bold">
                    {dataQualitySurface?.embedding_collections[0]?.vector_dimensions ? formatCount(dataQualitySurface.embedding_collections[0].vector_dimensions) : '-'}
                  </p>
                </div>
                <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                  <p className="text-xs font-bold text-muted-foreground mb-1">벡터 보유 객체</p>
                  <p className="text-lg font-bold">
                    {formatCount(dataQualitySurface?.embedding_collections.reduce((sum, collection) => sum + collection.embedded_count, 0) ?? 0)}
                  </p>
                </div>
                <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
                  <p className="text-xs font-bold text-muted-foreground mb-1">대상 객체</p>
                  <p className="text-lg font-bold">
                    {formatCount(dataQualitySurface?.embedding_collections.reduce((sum, collection) => sum + collection.object_count, 0) ?? 0)}
                  </p>
                </div>
              </div>

              <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
                <h2 className="font-bold text-lg mb-4">임베딩 컬렉션 상태</h2>
                <div className="grid gap-3">
                  {dataSurfaceStatus === 'loading' && (
                    <p className="text-sm font-semibold text-muted-foreground">임베딩 컬렉션을 확인하는 중입니다.</p>
                  )}
                  {dataSurfaceStatus === 'error' && (
                    <p className="text-sm font-bold text-red-700">임베딩 컬렉션을 불러오지 못했습니다.</p>
                  )}
                  {dataQualitySurface?.embedding_collections.map((collection) => (
                    <article key={collection.collection_key} className="rounded-xl border border-border bg-background p-4">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <h3 className="break-all text-sm font-black">{collection.display_name}</h3>
                          <p className="mt-1 text-xs font-semibold text-muted-foreground">원본 근거 연결됨</p>
                        </div>
                        <span className={`w-fit shrink-0 rounded-full px-2 py-1 text-xs font-bold ${getSurfaceStatusClass(collection.status_code)}`}>
                          {getSurfaceStatusLabel(collection.status_code)}
                        </span>
                      </div>
                      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-4">
                        <div>
                          <dt className="font-black text-muted-foreground">대상 객체</dt>
                          <dd className="mt-1 text-sm font-bold">{formatCount(collection.object_count)}</dd>
                        </div>
                        <div>
                          <dt className="font-black text-muted-foreground">벡터 보유</dt>
                          <dd className="mt-1 text-sm font-bold">{formatCount(collection.embedded_count)}</dd>
                        </div>
                        <div>
                          <dt className="font-black text-muted-foreground">모델</dt>
                          <dd className="mt-1 break-all text-sm font-bold">{collection.embedding_model}</dd>
                        </div>
                        <div>
                          <dt className="font-black text-muted-foreground">차원</dt>
                          <dd className="mt-1 text-sm font-bold">{formatCount(collection.vector_dimensions)}</dd>
                        </div>
                      </dl>
                      <div className="mt-4 flex justify-end border-t border-border pt-3">
                        <span className="inline-flex items-center gap-1 rounded bg-primary/10 px-3 py-1.5 text-xs font-bold text-primary">
                          <RefreshCw className="h-3 w-3" />
                          {getWriteBoundaryLabel(collection.provider_write_executed)}
                        </span>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </div>
  );
}
