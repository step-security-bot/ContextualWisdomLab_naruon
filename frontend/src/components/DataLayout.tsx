"use client";

import { useCallback, useState, useEffect, type ChangeEvent } from 'react';
import { Database } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

import { DocumentRepositoryTab } from './data-layout/DocumentRepositoryTab';
import { IngestionPipelineTab } from './data-layout/IngestionPipelineTab';
import { EmbeddingTab } from './data-layout/EmbeddingTab';
import { QualityCheckTab } from './data-layout/QualityCheckTab';
import {
  WebdavWritebackIntentResponse,
  WritebackStatus,
  WebdavAccountStatus,
  WebdavAccount,
  UniqueThreadIntentResponse,
  UniqueThreadStatus,
  EmailImportStatus,
  DocumentActionStatus,
  DataSurfaceStatus,
  DataQualitySurfaceResponse,
  EmailFileImportResponse,
  DataDocumentActionResponse,
  duplicateImportCandidates
} from './data-layout/types';
import {
  getApiErrorStatus,
  getSafeErrorSummary,
  getDocumentTypeForFile,
  isTextDocumentUploadType,
} from './data-layout/utils';


export function DataLayout() {
  const [activeTab, setActiveTab] = useState<'문서 저장소' | '수집 파이프라인' | '임베딩' | '품질 점검'>('문서 저장소');
  
  interface ProjectFolder {
    folder_uid: string;
    project_name: string;
    webdav_path: string;
  }
  
  const [webdavAccounts, setWebdavAccounts] = useState<WebdavAccount[]>([]);
  const [webdavAccountStatus, setWebdavAccountStatus] = useState<WebdavAccountStatus>('loading');
  const [selectedWebdavSourceId, setSelectedWebdavSourceId] = useState<string | null>(null);
  const [projectFolders, setProjectFolders] = useState<ProjectFolder[]>([]);
  const [writebackStatus, setWritebackStatus] = useState<WritebackStatus>('idle');
  const [writebackResult, setWritebackResult] = useState<WebdavWritebackIntentResponse | null>(null);
  const [uniqueThreadStatus, setUniqueThreadStatus] = useState<UniqueThreadStatus>('idle');
  const [uniqueThreadResult, setUniqueThreadResult] = useState<UniqueThreadIntentResponse | null>(null);
  const [emailImportStatus, setEmailImportStatus] = useState<EmailImportStatus>('idle');
  const [emailImportResult, setEmailImportResult] = useState<EmailFileImportResponse | null>(null);
  const [emailImportFiles, setEmailImportFiles] = useState<File[]>([]);
  const [documentActionStatus, setDocumentActionStatus] = useState<DocumentActionStatus>('idle');
  const [documentActionResult, setDocumentActionResult] = useState<DataDocumentActionResponse | null>(null);
  const [documentUploadFiles, setDocumentUploadFiles] = useState<File[]>([]);
  const [dataSurfaceStatus, setDataSurfaceStatus] = useState<DataSurfaceStatus>('loading');
  const [dataQualitySurface, setDataQualitySurface] = useState<DataQualitySurfaceResponse | null>(null);
  const [selectedRepositoryAssetKey, setSelectedRepositoryAssetKey] = useState<string | null>(null);

  const loadDataQualitySurface = useCallback(async (options?: { markLoading?: boolean }) => {
    if (options?.markLoading) {
      setDataSurfaceStatus('loading');
    }
    try {
      const data = await apiClient.get<DataQualitySurfaceResponse>('/api/data/quality-surface');
      if (!Array.isArray(data.repositories) || !Array.isArray(data.pipeline_stages)) {
        throw new Error('Invalid data quality surface response');
      }
      setDataQualitySurface(data);
      setDataSurfaceStatus('ready');
    } catch (error: unknown) {
      console.error('Data quality surface fetch error', getSafeErrorSummary(error));
      setDataQualitySurface(null);
      setDataSurfaceStatus('error');
    }
  }, []);

  useEffect(() => {
    apiClient.get<DataQualitySurfaceResponse>('/api/data/quality-surface')
      .then((data) => {
        if (!Array.isArray(data.repositories) || !Array.isArray(data.pipeline_stages)) {
          throw new Error('Invalid data quality surface response');
        }
        setDataQualitySurface(data);
        setDataSurfaceStatus('ready');
      })
      .catch((error: unknown) => {
        console.error('Data quality surface fetch error', getSafeErrorSummary(error));
        setDataQualitySurface(null);
        setDataSurfaceStatus('error');
      });

    apiClient.get<WebdavAccount[]>('/api/webdav/accounts')
      .then((data) => {
        if (!Array.isArray(data)) throw new Error('Invalid WebDAV accounts response');
        setWebdavAccounts(data);
        setSelectedWebdavSourceId(data.find((account) => account.writeback_enabled)?.source_id ?? null);
        setWebdavAccountStatus('ready');
      })
      .catch((error: unknown) => {
        console.error('WebDAV accounts fetch error', getSafeErrorSummary(error));
        setWebdavAccounts([]);
        setWebdavAccountStatus('error');
        setSelectedWebdavSourceId(null);
      });

    apiClient.get<ProjectFolder[]>('/api/webdav/folders')
      .then(data => Array.isArray(data) && setProjectFolders(data))
      .catch((error: unknown) => console.error('WebDAV folders fetch error', getSafeErrorSummary(error)));
  }, []);

  const requestWebdavWritebackIntent = useCallback(async () => {
    setWritebackStatus('loading');
    setWritebackResult(null);
    try {
      if (webdavAccountStatus !== 'ready') {
        setWritebackStatus('fetch_error');
        return;
      }
      const targetSourceId = webdavAccounts.find((account) => (
        account.source_id === selectedWebdavSourceId && account.writeback_enabled
      ))?.source_id ?? webdavAccounts.find((account) => account.writeback_enabled)?.source_id;
      if (!targetSourceId) {
        setWritebackStatus('no_source');
        return;
      }
      const result = await apiClient.post<WebdavWritebackIntentResponse>(
        '/api/webdav/writeback-intent',
        { target_source_id: targetSourceId },
      );
      setWritebackResult(result);
      setWritebackStatus('success');
    } catch (error: unknown) {
      const status = getApiErrorStatus(error);
      if (status === 422) {
        setWritebackStatus('no_source');
      } else if (status === 409) {
        setWritebackStatus('conflict');
      } else if (status === 401 || status === 403) {
        setWritebackStatus('auth');
      } else {
        setWritebackStatus('error');
      }
    }
  }, [selectedWebdavSourceId, webdavAccounts, webdavAccountStatus]);

  const requestUniqueThreadIntent = useCallback(async () => {
    setUniqueThreadStatus('loading');
    setUniqueThreadResult(null);
    try {
      const result = await apiClient.post<UniqueThreadIntentResponse>(
        '/api/emails/unique-thread-intent',
        { candidates: duplicateImportCandidates },
      );
      setUniqueThreadResult(result);
      setUniqueThreadStatus('success');
    } catch (error: unknown) {
      const status = getApiErrorStatus(error);
      setUniqueThreadStatus(status === 401 || status === 403 ? 'auth' : 'error');
    }
  }, []);

  const handleEmailImportFileChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    setEmailImportFiles(Array.from(event.target.files ?? []));
    setEmailImportResult(null);
    setEmailImportStatus('idle');
  }, []);

  const requestEmailFileImport = useCallback(async () => {
    if (emailImportFiles.length === 0) {
      setEmailImportStatus('error');
      return;
    }

    setEmailImportStatus('loading');
    setEmailImportResult(null);
    try {
      const formData = new FormData();
      emailImportFiles.forEach((file) => formData.append('files', file));
      const result = await apiClient.postForm<EmailFileImportResponse>('/api/emails/import-files', formData);
      setEmailImportResult(result);
      setEmailImportStatus('success');
    } catch (error: unknown) {
      const status = getApiErrorStatus(error);
      setEmailImportStatus(status === 401 || status === 403 ? 'auth' : 'error');
    }
  }, [emailImportFiles]);

  const handleDocumentFileChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    setDocumentUploadFiles(Array.from(event.target.files ?? []));
    setDocumentActionResult(null);
    setDocumentActionStatus('idle');
  }, []);

  const requestDocumentUpload = useCallback(async () => {
    const [file] = documentUploadFiles;
    if (!file) {
      setDocumentActionStatus('error');
      return;
    }

    setDocumentActionStatus('loading');
    setDocumentActionResult(null);
    try {
      const documentType = getDocumentTypeForFile(file);
      if (!isTextDocumentUploadType(documentType)) {
        setDocumentActionStatus('error');
        return;
      }
      const documentContent = await file.text();
      const result = await apiClient.post<DataDocumentActionResponse>(
        '/api/data/documents',
        {
          document_name: file.name,
          document_type: documentType,
          document_content: documentContent,
        },
      );
      setDocumentActionResult(result);
      setDocumentActionStatus('success');
      await loadDataQualitySurface({ markLoading: true });
    } catch (error: unknown) {
      const status = getApiErrorStatus(error);
      setDocumentActionStatus(status === 401 || status === 403 ? 'auth' : 'error');
    }
  }, [documentUploadFiles, loadDataQualitySurface]);

  const requestDocumentAction = useCallback(async (
    action: 'reparse' | 'embedding-regeneration-intent' | 'hwp-conversion-intent' | 'webdav-materialization-intent',
  ) => {
    const asset = dataQualitySurface?.repository_assets.find((candidate) => (
      candidate.asset_key === selectedRepositoryAssetKey
    )) ?? dataQualitySurface?.repository_assets[0] ?? null;
    if (!asset || asset.asset_type !== 'workspace_document') {
      setDocumentActionStatus('error');
      return;
    }
    const targetSourceId = webdavAccounts.find((account) => (
      account.source_id === selectedWebdavSourceId && account.writeback_enabled
    ))?.source_id ?? webdavAccounts.find((account) => account.writeback_enabled)?.source_id;
    if (action === 'webdav-materialization-intent' && (webdavAccountStatus !== 'ready' || !targetSourceId)) {
      setDocumentActionStatus('error');
      return;
    }

    setDocumentActionStatus('loading');
    setDocumentActionResult(null);
    try {
      const result = await apiClient.post<DataDocumentActionResponse>(
        `/api/data/documents/${encodeURIComponent(asset.asset_key)}/${action}`,
        action === 'webdav-materialization-intent'
          ? { target_source_id: targetSourceId, execute_provider: true }
          : {},
      );
      setDocumentActionResult(result);
      setDocumentActionStatus('success');
      await loadDataQualitySurface({ markLoading: true });
    } catch (error: unknown) {
      const status = getApiErrorStatus(error);
      setDocumentActionStatus(status === 401 || status === 403 ? 'auth' : 'error');
    }
  }, [
    dataQualitySurface,
    loadDataQualitySurface,
    selectedRepositoryAssetKey,
    selectedWebdavSourceId,
    webdavAccounts,
    webdavAccountStatus,
  ]);

  const isWritebackLoading = writebackStatus === 'loading';
  const isWebdavSourceLoading = webdavAccountStatus === 'loading';
  const canRequestWebdavWriteback = webdavAccountStatus === 'ready';
  const isUniqueThreadLoading = uniqueThreadStatus === 'loading';
  const isEmailImportLoading = emailImportStatus === 'loading';
  const isDocumentActionLoading = documentActionStatus === 'loading';
  const selectedWebdavAccount = webdavAccounts.find((account) => (
    account.source_id === selectedWebdavSourceId && account.writeback_enabled
  )) ?? webdavAccounts.find((account) => account.writeback_enabled) ?? null;
  const repositories = dataQualitySurface?.repositories ?? [];
  const emailRepository = repositories.find((repository) => repository.repository_type === 'email_repository');
  const attachmentRepository = repositories.find((repository) => repository.repository_type === 'attachment_repository');
  const embeddingStage = dataQualitySurface?.pipeline_stages.find((stage) => stage.stage_key === 'embedding_inventory');
  const connectorEvents = dataQualitySurface?.connector_events ?? [];
  const repositoryAssets = dataQualitySurface?.repository_assets ?? [];
  const selectedRepositoryAsset = repositoryAssets.find((asset) => asset.asset_key === selectedRepositoryAssetKey)
    ?? repositoryAssets[0]
    ?? null;
  const selectedWorkspaceDocument = selectedRepositoryAsset?.asset_type === 'workspace_document'
    ? selectedRepositoryAsset
    : null;

  return (
    <div className="flex h-full min-w-0 min-h-0 bg-background text-foreground flex-col overflow-x-hidden">
      <header className="flex h-20 shrink-0 items-center border-b border-border bg-card px-4 md:px-8 overflow-hidden">
        <h1 className="text-xl md:text-2xl font-bold flex shrink-0 items-center gap-3">
          <Database className="size-6 text-primary" /> <span className="sr-only sm:not-sr-only sm:inline">데이터와 파일</span>
        </h1>
        <p className="sr-only">중복 반입과 스레드 정리</p>
        <div className="ml-4 md:ml-8 flex flex-1 min-w-0 gap-2 overflow-x-auto pb-1 scrollbar-hide">
          {['문서 저장소', '수집 파이프라인', '임베딩', '품질 점검'].map((tab) => (
            <button type="button"
              key={tab}
              onClick={() => setActiveTab(tab as '문서 저장소' | '수집 파이프라인' | '임베딩' | '품질 점검')}
              className={`whitespace-nowrap px-3 md:px-4 py-2 text-sm font-bold rounded-lg transition-colors shrink-0 ${activeTab === tab ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-secondary'}`}
            >
              {tab}
            </button>
          ))}
        </div>
      </header>

      <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden p-4 pb-[calc(7rem+env(safe-area-inset-bottom))] md:p-8 bg-background">
        <div className="max-w-5xl mx-auto space-y-8">
          
          {activeTab === '문서 저장소' && (
            <DocumentRepositoryTab
              dataSurfaceStatus={dataSurfaceStatus}
              dataQualitySurface={dataQualitySurface}
              embeddingStage={embeddingStage}
              emailRepository={emailRepository}
              attachmentRepository={attachmentRepository}
              handleEmailImportFileChange={handleEmailImportFileChange}
              requestEmailFileImport={requestEmailFileImport}
              isEmailImportLoading={isEmailImportLoading}
              emailImportFiles={emailImportFiles}
              emailImportStatus={emailImportStatus}
              emailImportResult={emailImportResult}
              handleDocumentFileChange={handleDocumentFileChange}
              requestDocumentUpload={requestDocumentUpload}
              isDocumentActionLoading={isDocumentActionLoading}
              documentUploadFiles={documentUploadFiles}
              documentActionStatus={documentActionStatus}
              documentActionResult={documentActionResult}
              webdavAccountStatus={webdavAccountStatus}
              webdavAccounts={webdavAccounts}
              projectFolders={projectFolders}
              selectedRepositoryAssetKey={selectedRepositoryAssetKey}
              setSelectedRepositoryAssetKey={setSelectedRepositoryAssetKey}
              repositoryAssets={repositoryAssets}
              selectedWorkspaceDocument={selectedWorkspaceDocument}
              requestDocumentAction={requestDocumentAction}
              connectorEvents={connectorEvents}
              writebackStatus={writebackStatus}
              writebackResult={writebackResult}
              requestWebdavWritebackIntent={requestWebdavWritebackIntent}
              isWritebackLoading={isWritebackLoading}
              canRequestWebdavWriteback={canRequestWebdavWriteback}
              selectedWebdavAccount={selectedWebdavAccount}
              isWebdavSourceLoading={isWebdavSourceLoading}
              setSelectedWebdavSourceId={setSelectedWebdavSourceId}
              uniqueThreadStatus={uniqueThreadStatus}
              uniqueThreadResult={uniqueThreadResult}
              requestUniqueThreadIntent={requestUniqueThreadIntent}
              isUniqueThreadLoading={isUniqueThreadLoading}
            />
          )}

          {activeTab === '수집 파이프라인' && (
            <IngestionPipelineTab
              dataSurfaceStatus={dataSurfaceStatus}
              dataQualitySurface={dataQualitySurface}
            />
          )}

          {activeTab === '임베딩' && (
            <EmbeddingTab
              dataSurfaceStatus={dataSurfaceStatus}
              dataQualitySurface={dataQualitySurface}
            />
          )}

          {activeTab === '품질 점검' && (
            <QualityCheckTab
              dataSurfaceStatus={dataSurfaceStatus}
              dataQualitySurface={dataQualitySurface}
            />
          )}
        </div>
      </main>
    </div>
  );
}
