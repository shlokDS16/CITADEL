// ==================== CITADEL SUB-PAGES (ENTERPRISE) ====================
// 8 module pages.
// Document Intelligence is fully wired to the FastAPI backend (see backend/).
// The remaining 7 modules are still mock-driven until their backends ship.
console.log('%c[CITADEL] pages.jsx build 2026-05-02-c — Doc Intel: 100% backend-driven, NO mock files', 'background:#D4A843;color:#000;font-weight:700;padding:4px 10px;');

/* ======================================================================
   GOVERNMENT MODULE 1 — DOCUMENT INTELLIGENCE  ·  100% backend-driven
   Backend: backend/app/modules/document_intelligence/router.py
   Tabs: Upload · Queue · Library · Templates · Analytics
   ====================================================================== */

// ----- shared helpers used across this module -----
const DI_DOC_TYPES = [
  { ui: 'Auto-detect',        api: 'auto_detect' },
  { ui: 'Invoice',            api: 'invoice' },
  { ui: 'Contract',           api: 'contract' },
  { ui: 'ID Document',        api: 'id_document' },
  { ui: 'Government Permit',  api: 'government_permit' },
  { ui: 'Tender Notice',      api: 'tender_notice' },
  { ui: 'Permit',             api: 'permit' },
  { ui: 'Report',             api: 'report' },
  { ui: 'Receipt',            api: 'receipt' },
  { ui: 'Affidavit',          api: 'affidavit' },
  { ui: 'Certificate',        api: 'certificate' },
];
const DI_LANGS = [
  { ui: 'English',         api: 'en' },
  { ui: 'Hindi',           api: 'hi' },
  { ui: 'English + Hindi', api: 'en+hi' },
];
const DI_PRIORITIES = ['low', 'normal', 'high', 'urgent'];
const DI_PRIO_BADGE = { urgent: 'red', high: 'gold', normal: 'default', low: 'default' };
const DI_TYPE_ICON = {
  invoice: '📋', contract: '📜', permit: '🏛', id_document: '🪪',
  receipt: '🧾', affidavit: '⚖', tender_notice: '📢',
  certificate: '🎓', government_permit: '🏛', report: '📊',
};
const diTypeLabel = (t) =>
  (DI_DOC_TYPES.find(x => x.api === t)?.ui) || (t || '').replace(/_/g, ' ');

// Reusable backend caller that surfaces errors as toast
const useDIApi = (toast) => React.useCallback(async (path, opts) => {
  try { return await apiFetch(path, opts); }
  catch (e) { toast?.(`API ${path}: ${e.message}`, 'error'); throw e; }
}, [toast]);

// ============================================================
// Top-level shell
// ============================================================
const DocumentIntelligence = ({ onBack }) => {
  const [tab, setTab] = React.useState('upload');
  const [refreshTick, setRefreshTick] = React.useState(0);     // global poke for child tabs
  const [todayCount, setTodayCount] = React.useState(null);
  const bumpRefresh = React.useCallback(() => setRefreshTick(t => t + 1), []);

  // Live "today" count for the subtitle
  React.useEffect(() => {
    apiFetch('/api/dashboard/volume', { params: { period: '7d' } })
      .then(r => setTodayCount(r.today_count))
      .catch(() => setTodayCount(null));
  }, [refreshTick]);

  const tabs = [
    { key: 'upload',    label: 'UPLOAD & ANALYZE', icon: '↑' },
    { key: 'queue',     label: 'QUEUE',            icon: '▤' },
    { key: 'library',   label: 'LIBRARY',          icon: '▣' },
    { key: 'templates', label: 'TEMPLATES',        icon: '◫' },
    { key: 'analytics', label: 'ANALYTICS',        icon: '◈' },
  ];

  const subtitle = (
    <>OCR + NER + LAYOUT · PII REDACTION · AUDIT TRAIL ·
      {todayCount === null ? ' …' : ` ${todayCount} DOC${todayCount === 1 ? '' : 'S'} TODAY`}
    </>
  );

  return (
    <div className="subpage fade-in">
      <SubPageHeader
        title="DOCUMENT INTELLIGENCE"
        gatewayId="GATEWAY_01"
        subtitle={subtitle}
        accentColor="var(--gold)"
        onBack={onBack}
        actions={
          <button
            className="btn-brutal action-btn gold"
            style={{ padding: '8px 16px', fontSize: 12, width: 'auto' }}
            onClick={() => setTab('upload')}
          >
            ＋ NEW INTAKE
          </button>
        }
      />
      <Tabs tabs={tabs} active={tab} onChange={setTab} accent="var(--gold)" />
      {tab === 'upload'    && <DocIntelUpload    onUploaded={bumpRefresh} goToQueue={() => setTab('queue')} />}
      {tab === 'queue'     && <DocIntelQueue     refreshTick={refreshTick} bumpRefresh={bumpRefresh} />}
      {tab === 'library'   && <DocIntelLibrary   refreshTick={refreshTick} />}
      {tab === 'templates' && <DocIntelTemplates refreshTick={refreshTick} />}
      {tab === 'analytics' && <DocIntelAnalytics refreshTick={refreshTick} />}
    </div>
  );
};

// ============================================================
// 1. UPLOAD & ANALYZE — fully wired
// ============================================================
const DocIntelUpload = ({ onUploaded, goToQueue }) => {
  const [files, setFiles]         = React.useState([]);   // [{name, size, _file}]
  const [docType, setDocType]     = React.useState('auto_detect');
  const [lang, setLang]           = React.useState('en');
  const [pii, setPii]             = React.useState(true);
  const [sigDetect, setSigDetect] = React.useState(true);
  const [priority, setPriority]   = React.useState('normal');
  const [analyzing, setAnalyzing] = React.useState(false);
  const [progress, setProgress]   = React.useState(0);
  const [batchId, setBatchId]     = React.useState(null);
  const [results, setResults]     = React.useState(null);
  const [error, setError]         = React.useState(null);
  const [toast, toastHost]        = useToast();
  const fileInputRef = React.useRef(null);

  const triggerPick = () => fileInputRef.current?.click();
  const onFilesPicked = (e) => {
    const picked = Array.from(e.target.files || []);
    setFiles(f => [
      ...f,
      ...picked.map(file => ({
        name: file.name,
        size: file.size >= 1024 * 1024
          ? `${(file.size / 1024 / 1024).toFixed(2)} MB`
          : `${(file.size / 1024).toFixed(0)} KB`,
        _file: file,
      })),
    ]);
    if (e.target) e.target.value = '';
  };
  const removeFile = (idx) => setFiles(f => f.filter((_, i) => i !== idx));

  const analyze = async () => {
    if (files.length === 0) return;
    setError(null); setAnalyzing(true); setProgress(8); setResults(null); setBatchId(null);
    try {
      const fd = new FormData();
      files.forEach(f => f._file && fd.append('files', f._file, f._file.name));
      fd.append('document_type', docType);
      fd.append('language', lang);
      fd.append('priority', priority);
      fd.append('detect_redact_pii', String(pii));
      fd.append('signature_validation', String(sigDetect));
      fd.append('uploaded_by', 'RSD');

      const upload = await apiFetch('/api/documents/upload', { form: fd });
      setBatchId(upload.batch_id);
      setProgress(20);

      // Poll batch results until processing settles
      let attempts = 0;
      let result = null;
      while (attempts < 45) {
        await new Promise(r => setTimeout(r, 1000));
        attempts++;
        try {
          const res = await apiFetch(`/api/documents/batch/${upload.batch_id}/results`);
          setProgress(Math.min(20 + attempts * 6, 95));
          if (res.documents?.length && res.documents.every(d => d.status !== 'PROCESSING')) {
            result = res; break;
          }
        } catch (e) { /* keep polling */ }
      }
      if (!result) throw new Error('Backend did not return results within 45s');
      setProgress(100);
      setResults(result);
      toast(`Processed ${result.successful}/${result.total_processed}`, result.failed ? 'warn' : 'success');
      onUploaded?.();
    } catch (e) {
      setError(e.message || String(e));
      toast(`Upload failed: ${e.message}`, 'error');
    } finally {
      setAnalyzing(false);
    }
  };

  // Per-batch action on the resulting documents
  const bulkAction = async (action) => {
    if (!results?.documents?.length) return;
    const ids = results.documents.map(d => d.doc_id);
    try {
      const res = await apiFetch('/api/documents/bulk-action', {
        json: { doc_ids: ids, action, performed_by: 'RSD' },
      });
      toast(`${action.toUpperCase()} → ${res.successful}/${res.requested}`, res.failed ? 'warn' : 'success');
      // Refresh batch view
      const fresh = await apiFetch(`/api/documents/batch/${batchId}/results`);
      setResults(fresh);
    } catch (e) {
      toast(`${action} failed: ${e.message}`, 'error');
    }
  };

  const downloadExport = (format) => {
    if (!batchId) return;
    const a = document.createElement('a');
    a.href = `${API_BASE}/api/documents/batch/${batchId}/export?format=${format}`;
    a.download = `batch_${batchId}.${format}`;
    a.click();
    toast(`Downloaded ${format.toUpperCase()}`, 'success');
  };

  return (
    <div className="tab-pane">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.png,.jpg,.jpeg"
        onChange={onFilesPicked}
        style={{ display: 'none' }}
      />
      {error && (
        <div className="warning-banner" style={{ marginBottom: 12 }}>
          <span>⚠</span><div><strong>Upload failed:</strong> {error}</div>
        </div>
      )}
      <div className="grid-3-col">
        {/* ---------- LEFT: intake config ---------- */}
        <div className="col-panel left-panel">
          <div className="panel-header" style={{ background: 'var(--gold)' }}>INTAKE CONFIGURATION</div>
          <div className="panel-body">
            <label className="field-label">DOCUMENTS</label>
            <div className="file-drop" onClick={triggerPick}>
              {files.length === 0
                ? <><span className="file-icon">⬆</span> Click to browse — PDF · DOCX · PNG · JPG (≤10MB each, 10 per batch)</>
                : <><span className="file-icon">📁</span> {files.length} file{files.length !== 1 ? 's' : ''} ready</>}
            </div>

            {files.length > 0 && (
              <div className="file-list">
                {files.map((f, i) => (
                  <div key={i} className="file-item">
                    <span style={{ fontSize: 14 }}>📄</span>
                    <div style={{ flex: 1 }}>
                      <div className="file-name">{f.name}</div>
                      <div className="file-meta">{f.size}</div>
                    </div>
                    <button className="icon-btn" onClick={() => removeFile(i)} title="Remove">✕</button>
                  </div>
                ))}
              </div>
            )}

            <label className="field-label mt-14">DOCUMENT TYPE</label>
            <select className="brutal-select" value={docType} onChange={e => setDocType(e.target.value)}>
              {DI_DOC_TYPES.map(t => <option key={t.api} value={t.api}>{t.ui}</option>)}
            </select>

            <div className="inline-fields">
              <div style={{ flex: 1 }}>
                <label className="field-label mt-14">OCR LANGUAGE</label>
                <select className="brutal-select" value={lang} onChange={e => setLang(e.target.value)}>
                  {DI_LANGS.map(l => <option key={l.api} value={l.api}>{l.ui}</option>)}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label className="field-label mt-14">PRIORITY</label>
                <select className="brutal-select" value={priority} onChange={e => setPriority(e.target.value)}>
                  {DI_PRIORITIES.map(p => <option key={p} value={p}>{p.toUpperCase()}</option>)}
                </select>
              </div>
            </div>

            <div className="toggle-group">
              <Toggle checked={pii} onChange={setPii} label="Detect & redact PII" />
              <Toggle checked={sigDetect} onChange={setSigDetect} label="Signature validation" />
            </div>

            {analyzing && (
              <div className="progress-wrap mt-14">
                <div className="progress-bar-lg"><div className="progress-fill-lg" style={{ width: `${progress}%`, background: 'var(--gold)' }}></div></div>
                <div className="progress-pct">{progress}%</div>
              </div>
            )}

            <button
              className="btn-brutal action-btn gold mt-20"
              onClick={analyze}
              disabled={files.length === 0 || analyzing}
            >
              {analyzing ? 'PROCESSING...' : `ANALYZE ${files.length} DOC${files.length !== 1 ? 'S' : ''}`}
            </button>
          </div>
        </div>

        {/* ---------- RIGHT: extraction results ---------- */}
        <div className="col-panel" style={{ gridColumn: 'span 2' }}>
          <div className="panel-header" style={{ background: '#111', color: '#fff' }}>EXTRACTION RESULTS</div>
          <div className="panel-body">
            {!results ? (
              <EmptyState
                icon="📋"
                title="NO EXTRACTION YET"
                description="Pick documents on the left, configure intake, then click ANALYZE. Results show classification, PII findings, signature status, and tags from the live backend pipeline."
              />
            ) : (
              <>
                <div className="summary-grid">
                  <KPICard label="PROCESSED" value={results.total_processed} color="var(--gold)" />
                  <KPICard label="SUCCESS" value={results.successful} color="var(--green)" />
                  <KPICard label="AVG CONF" value={`${results.avg_confidence}%`} color="var(--cyan)" />
                  <KPICard label="PII FOUND" value={results.pii_found_total} color="var(--red)" />
                </div>

                {results.documents.map((d, i) => {
                  const piiTypes = Object.keys(d.pii_results || {});
                  const piiCount = piiTypes.reduce((s, k) => s + (d.pii_results[k].count || 0), 0);
                  const sigStatus = d.signature_status;
                  return (
                  <div key={d.doc_id} className="widget-card mt-20">
                    <div className="widget-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>{DI_TYPE_ICON[d.document_type] || '📄'} {d.doc_id} · {d.filename}</span>
                      <Badge variant={d.status === 'PENDING_REVIEW' ? 'gold' : d.status === 'APPROVED' ? 'green' : d.status === 'REJECTED' ? 'red' : 'default'}>{d.status}</Badge>
                    </div>
                    <div style={{ padding: 14 }}>
                      {/* Pipeline run-status row — explicit visual feedback for PII/signature toggles */}
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                        <span className={`status-pill ${pii ? 'on' : 'off'}`} style={{ background: pii ? (piiCount > 0 ? 'var(--red)' : 'var(--green)') : '#ccc', color: pii ? '#fff' : '#666' }}>
                          🛡 PII Detection: {pii ? (piiCount > 0 ? `${piiCount} ITEMS REDACTED` : 'CLEAN') : 'SKIPPED'}
                        </span>
                        <span className={`status-pill`} style={{ background: sigDetect ? (sigStatus === 'detected' ? 'var(--green)' : sigStatus === 'unclear' ? 'var(--gold)' : 'var(--red)') : '#ccc', color: sigDetect ? '#fff' : '#666' }}>
                          ✍ Signature: {sigDetect ? (sigStatus || 'unknown').toUpperCase() : 'SKIPPED'}
                        </span>
                        <span className="status-pill" style={{ background: 'var(--cyan)', color: '#000' }}>
                          🔎 OCR/Extract: {Math.round(d.confidence || 0)}% confidence
                        </span>
                      </div>

                      <div className="entity-table">
                        <div className="entity-row enhanced">
                          <span className="entity-label">Type</span>
                          <span className="entity-value">{diTypeLabel(d.document_type)}</span>
                          <ConfidenceBar value={Math.round(d.confidence || 0)} compact />
                        </div>
                        <div className="entity-row enhanced">
                          <span className="entity-label">Tags</span>
                          <span className="entity-value">{(d.tags || []).join(', ') || '—'}</span>
                          <span></span>
                        </div>
                        <div className="entity-row enhanced">
                          <span className="entity-label">Preview</span>
                          <span className="entity-value" style={{ fontSize: 11, lineHeight: 1.4 }}>
                            {(d.extracted_text_preview || '—').slice(0, 240)}...
                          </span>
                          <span></span>
                        </div>
                      </div>

                      {piiTypes.length > 0 && (
                        <>
                          <div className="section-divider mt-20"><span>PII DETECTED ({piiCount} items across {piiTypes.length} categories)</span></div>
                          <div className="pii-row">
                            {Object.entries(d.pii_results).map(([k, v]) => (
                              <div key={k} className="pii-chip" title={v.note || ''}>
                                <span className="pii-icon">🛡</span>
                                <div>
                                  <div className="pii-type">{v.label || k}</div>
                                  <div className="pii-found">{v.count} found · {v.status}</div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                );
                })}

                <div className="action-row mt-20">
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }} onClick={() => downloadExport('csv')}>EXPORT CSV</button>
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }} onClick={() => downloadExport('json')}>EXPORT JSON</button>
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }} onClick={() => bulkAction('reject')}>REJECT BATCH</button>
                  <button className="btn-brutal action-btn gold" style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }} onClick={() => goToQueue?.()}>→ GO TO QUEUE FOR APPROVAL</button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
      {toastHost}
    </div>
  );
};

// ============================================================
// 2. QUEUE — fully wired with per-row + bulk actions
// ============================================================
const DocIntelQueue = ({ refreshTick, bumpRefresh }) => {
  const [filter, setFilter] = React.useState({ status: '', type: '', priority: '' });
  const [search, setSearch] = React.useState('');
  const [sortBy, setSortBy] = React.useState('created_at');
  const [sortOrder, setSortOrder] = React.useState('desc');
  const [page, setPage] = React.useState(1);
  const perPage = 20;
  const [selected, setSelected] = React.useState([]);
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [tick, setTick] = React.useState(0);
  const [detailDoc, setDetailDoc] = React.useState(null);
  const [toast, toastHost] = useToast();

  React.useEffect(() => {
    setLoading(true); setError(null);
    apiFetch('/api/documents/queue', {
      params: { search, status: filter.status, type: filter.type, priority: filter.priority,
        sort_by: sortBy, sort_order: sortOrder, page, per_page: perPage },
    })
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [search, filter.status, filter.type, filter.priority, sortBy, sortOrder, page, tick, refreshTick]);

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = data?.total_pages || 1;

  const refresh = () => { setTick(t => t + 1); bumpRefresh?.(); };

  const doBulk = async (action) => {
    if (selected.length === 0) return;
    // DataTable selects by row INDEX — map to doc IDs from the current rows
    const docIds = selected.map(i => rows[i]?.id).filter(Boolean);
    if (docIds.length === 0) {
      toast('Selection mismatch — please re-select rows', 'error');
      return;
    }
    try {
      const res = await apiFetch('/api/documents/bulk-action', {
        json: { doc_ids: docIds, action, performed_by: 'RSD' },
      });
      toast(`${action.toUpperCase()} → ${res.successful}/${res.requested}`, res.failed ? 'warn' : 'success');
      setSelected([]); refresh();
    } catch (e) {
      toast(`${action} failed: ${e.message}`, 'error');
    }
  };

  const doSingle = async (docId, action) => {
    try {
      if (action === 'delete') {
        if (!window.confirm(`Permanently delete ${docId}? This removes it from the queue, library, and templates, plus its file from storage. This cannot be undone.`)) return;
        await apiFetch(`/api/documents/${docId}`, { method: 'DELETE', params: { performed_by: 'RSD' } });
      } else {
        await apiFetch(`/api/documents/${docId}/${action}`, { method: 'POST', params: { performed_by: 'RSD' } });
      }
      toast(`${docId} → ${action.toUpperCase()}`, 'success');
      refresh();
    } catch (e) {
      toast(`${action} failed: ${e.message}`, 'error');
    }
  };

  // map backend → row shape
  const rows = items.map(it => ({
    id: it.doc_id,
    type: diTypeLabel(it.document_type),
    uploader: it.uploaded_by || '—',
    status: (it.status || '').toLowerCase(),
    conf: it.confidence == null ? 0 : Math.round(it.confidence),
    priority: (it.priority || 'normal').toUpperCase(),
    time: it.time_ago || '—',
    sla: it.sla_breached,
    pii: it.pii_count || 0,
    _raw: it,
  }));

  return (
    <div className="tab-pane">
      <div className="toolbar">
        <SearchBar value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder="Search by filename..." />
        <FilterBar
          filters={[
            { key: 'status',   label: 'Status',   options: ['PENDING_REVIEW', 'PROCESSING', 'APPROVED', 'REJECTED', 'ARCHIVED'] },
            { key: 'type',     label: 'Type',     options: DI_DOC_TYPES.filter(t => t.api !== 'auto_detect').map(t => ({ value: t.api, label: t.ui })) },
            { key: 'priority', label: 'Priority', options: DI_PRIORITIES.map(p => ({ value: p, label: p.toUpperCase() })) },
          ]}
          values={filter}
          onChange={(k, v) => { setFilter(f => ({ ...f, [k]: v })); setPage(1); }}
          onClear={() => { setFilter({ status: '', type: '', priority: '' }); setPage(1); }}
        />
        <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={refresh} disabled={loading}>↻ REFRESH</button>
      </div>

      {error && (
        <div className="warning-banner" style={{ marginBottom: 12 }}>
          <span>⚠</span><div><strong>Backend error:</strong> {error}</div>
        </div>
      )}

      {selected.length > 0 && (
        <div className="bulk-bar">
          <span>{selected.length} selected</span>
          <button className="btn-brutal action-btn" style={{ width: 'auto', fontSize: 11, padding: '6px 14px', background: 'var(--green)', color: '#000' }} onClick={() => doBulk('approve')}>APPROVE</button>
          <button className="btn-brutal action-btn" style={{ width: 'auto', fontSize: 11, padding: '6px 14px', background: 'var(--red)', color: '#fff' }} onClick={() => doBulk('reject')}>REJECT</button>
          <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={() => doBulk('reassign')}>REASSIGN</button>
          <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={() => doBulk('archive')}>ARCHIVE</button>
          <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px', background: '#000', color: 'var(--red)', borderColor: 'var(--red)' }} onClick={() => { if (window.confirm(`Permanently delete ${selected.length} document(s)? This removes them from queue, library, templates, and storage.`)) doBulk('delete'); }}>🗑 DELETE</button>
          <button className="icon-btn" onClick={() => setSelected([])}>✕</button>
        </div>
      )}

      <div className="widget-card">
        {loading && rows.length === 0 ? (
          <div style={{ padding: 24 }}>
            <Skeleton h={28} /><div style={{ height: 8 }} />
            <Skeleton h={28} /><div style={{ height: 8 }} />
            <Skeleton h={28} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState icon="📭" title="QUEUE EMPTY" description="No documents match your filters. Upload some via the Upload tab to get started." />
        ) : (
          <DataTable
            selectable
            selected={selected}
            onSelect={setSelected}
            onRowClick={r => setDetailDoc(r._raw)}
            columns={[
              { key: 'id',       label: 'DOC ID',    width: 110, render: (v, r) => <span>{v} {r.sla && <span title="SLA breached" style={{ color: 'var(--red)' }}>⚠</span>}</span> },
              { key: 'type',     label: 'TYPE',      width: 130 },
              { key: 'uploader', label: 'UPLOADER' },
              { key: 'priority', label: 'PRIORITY', width: 100, render: v => <Badge variant={DI_PRIO_BADGE[v.toLowerCase()] || 'default'}>{v}</Badge> },
              { key: 'conf',     label: 'CONFIDENCE', width: 150, render: v => v === 0 ? <span style={{ opacity: 0.4, fontSize: 11 }}>—</span> : <ConfidenceBar value={v} compact /> },
              { key: 'pii',      label: 'PII', width: 60, align: 'right', render: v => v > 0 ? <Badge variant="red">{v}</Badge> : <span style={{ opacity: 0.4 }}>—</span> },
              { key: 'status',   label: 'STATUS', width: 150, render: v => <StatusPill status={v === 'pending_review' ? 'pending' : v} label={v.replace('_', ' ').toUpperCase()} /> },
              { key: 'time',     label: 'AGE', width: 80, align: 'right' },
              { key: '_actions', label: '', width: 160, render: (_, r) => (
                <div style={{ display: 'flex', gap: 4 }} onClick={e => e.stopPropagation()}>
                  {r.status === 'pending_review' && <>
                    <button className="icon-btn" title="Approve" onClick={() => doSingle(r.id, 'approve')} style={{ background: 'var(--green)', color: '#000' }}>✓</button>
                    <button className="icon-btn" title="Reject" onClick={() => doSingle(r.id, 'reject')} style={{ background: 'var(--red)', color: '#fff' }}>✕</button>
                  </>}
                  {r.status === 'approved' && <button className="icon-btn" title="Archive" onClick={() => doSingle(r.id, 'archive')}>▣</button>}
                  {(r.status === 'rejected' || r.status === 'pending_review') && <button className="icon-btn" title="Re-process" onClick={() => doSingle(r.id, 'reassign')}>↻</button>}
                  <button className="icon-btn" title="Delete permanently" onClick={() => doSingle(r.id, 'delete')} style={{ background: '#000', color: 'var(--red)', borderColor: 'var(--red)' }}>🗑</button>
                </div>
              ) },
            ]}
            rows={rows}
          />
        )}

        <div style={{ padding: '12px 16px', borderTop: '1px solid #e5e5e0', display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.6 }}>
            {loading ? 'loading...' : `Showing ${rows.length} of ${total}`}
          </span>
          {totalPages > 1 && (
            <Pagination page={page} total={total} perPage={perPage} onPage={setPage} />
          )}
        </div>
      </div>

      {detailDoc && <DocDetailModal doc={detailDoc} onClose={() => setDetailDoc(null)} onChanged={refresh} />}
      {toastHost}
    </div>
  );
};

// ----- Document detail modal: extracted text + audit log + actions -----
const DocDetailModal = ({ doc, onClose, onChanged }) => {
  const [audit, setAudit] = React.useState(null);
  const [editView, setEditView] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [toast, toastHost] = useToast();

  React.useEffect(() => {
    Promise.all([
      apiFetch(`/api/documents/${doc.doc_id}/audit`).catch(() => null),
      apiFetch(`/api/documents/${doc.doc_id}/edit-view`).catch(() => null),
    ]).then(([a, e]) => { setAudit(a); setEditView(e); });
  }, [doc.doc_id]);

  const act = async (action) => {
    if (action === 'delete' && !window.confirm(`Permanently delete ${doc.doc_id}? Removes from queue, library, templates and storage. Cannot be undone.`)) return;
    setBusy(true);
    try {
      if (action === 'delete') {
        await apiFetch(`/api/documents/${doc.doc_id}`, { method: 'DELETE', params: { performed_by: 'RSD' } });
      } else {
        await apiFetch(`/api/documents/${doc.doc_id}/${action}`, { method: 'POST', params: { performed_by: 'RSD' } });
      }
      toast(`${action.toUpperCase()} OK`, 'success');
      onChanged?.();
      setTimeout(onClose, 300);
    } catch (e) {
      toast(`${action} failed: ${e.message}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const status = (doc.status || '').toLowerCase();

  return (
    <Modal
      open={true}
      onClose={onClose}
      title={`${doc.doc_id} · ${doc.filename}`}
      size="lg"
      footer={
        <>
          <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }} onClick={onClose}>CLOSE</button>
          <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px', background: '#000', color: 'var(--red)', borderColor: 'var(--red)' }} disabled={busy} onClick={() => act('delete')}>🗑 DELETE</button>
          {status === 'pending_review' && <>
            <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px', background: 'var(--red)', color: '#fff' }} disabled={busy} onClick={() => act('reject')}>REJECT</button>
            <button className="btn-brutal action-btn gold" style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }} disabled={busy} onClick={() => act('approve')}>APPROVE</button>
          </>}
          {status === 'approved' && <button className="btn-brutal action-btn" style={{ fontSize: 11, padding: '8px 14px', width: 'auto', background: 'var(--cyan)', color: '#000' }} disabled={busy} onClick={() => act('archive')}>ARCHIVE</button>}
          {(status === 'rejected' || status === 'pending_review') && <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }} disabled={busy} onClick={() => act('reassign')}>RE-PROCESS</button>}
        </>
      }
    >
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
        <div>
          <div className="widget-title">EXTRACTED TEXT</div>
          {!editView ? <Skeleton h={160} /> : (
            <pre style={{ padding: 10, background: '#fafaf5', border: '2px solid #000', maxHeight: 320, overflow: 'auto', fontSize: 11, lineHeight: 1.45, whiteSpace: 'pre-wrap' }}>
              {(editView.extracted_text || '').slice(0, 6000) || '(no text extracted)'}
            </pre>
          )}

          {Object.keys(doc.pii_results || {}).length > 0 && (
            <>
              <div className="section-divider mt-20"><span>PII</span></div>
              <div className="pii-row">
                {Object.entries(doc.pii_results).map(([k, v]) => (
                  <div key={k} className="pii-chip">
                    <span className="pii-icon">🛡</span>
                    <div>
                      <div className="pii-type">{v.label || k}</div>
                      <div className="pii-found">{v.count} · {v.status}</div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div>
          <div className="widget-title">AUDIT LOG</div>
          {!audit ? <Skeleton h={160} /> : (
            <div className="status-timeline">
              {(audit.entries || []).map((e, i) => (
                <div key={e.id || i} className={`status-step ${i === audit.entries.length - 1 ? 'active' : 'done'}`}>
                  <div className="status-node">{i + 1}</div>
                  <div className="status-label">
                    <div className="status-title">{e.action.toUpperCase()}</div>
                    <div className="status-time">{new Date(e.created_at).toLocaleString()} · {e.performed_by}</div>
                  </div>
                  {i < audit.entries.length - 1 && <div className="status-connector"></div>}
                </div>
              ))}
            </div>
          )}

          <div className="section-divider mt-20"><span>METADATA</span></div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.8 }}>
            <div>Type: <strong>{diTypeLabel(doc.document_type)}</strong></div>
            <div>Status: <strong>{doc.status}</strong></div>
            <div>Priority: <strong>{(doc.priority || '').toUpperCase()}</strong></div>
            <div>Confidence: <strong>{doc.confidence ?? '—'}%</strong></div>
            <div>Signature: <strong>{doc.signature_status || '—'}</strong></div>
            <div>Tags: <strong>{(doc.tags || []).join(', ') || '—'}</strong></div>
            <div>Uploaded by: <strong>{doc.uploaded_by || '—'}</strong></div>
          </div>
        </div>
      </div>
      {toastHost}
    </Modal>
  );
};

// ============================================================
// 3. LIBRARY — fully wired
// ============================================================
const DocIntelLibrary = ({ refreshTick }) => {
  const [search, setSearch] = React.useState('');
  const [view, setView]     = React.useState('grid');
  const [data, setData]     = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError]   = React.useState(null);
  const [tick, setTick]     = React.useState(0);
  const [detailDoc, setDetailDoc] = React.useState(null);
  const [toast, toastHost] = useToast();

  React.useEffect(() => {
    setLoading(true); setError(null);
    apiFetch('/api/documents/library', { params: { search, view } })
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [search, view, tick, refreshTick]);

  const items = data?.items || [];

  const exportZip = async () => {
    try {
      const r = await fetch(`${API_BASE}/api/documents/library/export`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `citadel_archive_${new Date().toISOString().slice(0, 10)}.zip`;
      a.click();
      toast(`Downloaded ${(blob.size / 1024).toFixed(1)} KB`, 'success');
    } catch (e) {
      toast(`Export failed: ${e.message}`, 'error');
    }
  };

  const downloadOne = async (docId) => {
    try {
      const detail = await apiFetch(`/api/documents/${docId}/edit-view`);
      const txt = detail.extracted_text || '(no text)';
      const blob = new Blob([txt], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${docId}_extracted.txt`;
      a.click();
      toast(`Downloaded ${docId}.txt`, 'success');
    } catch (e) {
      toast(`Download failed: ${e.message}`, 'error');
    }
  };

  const palette = ['var(--gold)', 'var(--red)', 'var(--cyan)', 'var(--green)'];

  return (
    <div className="tab-pane">
      <div className="toolbar">
        <SearchBar value={search} onChange={setSearch} placeholder="Search archive by title or filename..." />
        <SegmentedControl options={['grid', 'list']} value={view} onChange={setView} accent="var(--gold)" />
        <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={() => setTick(t => t + 1)} disabled={loading}>↻</button>
        <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={exportZip} disabled={items.length === 0}>⭳ EXPORT ZIP ({items.length})</button>
      </div>

      {error && <div className="warning-banner"><span>⚠</span><div>Backend: {error}</div></div>}

      {loading && items.length === 0 ? (
        <div className="doc-grid">
          {[1, 2, 3, 4].map(i => <div key={i} className="doc-card"><Skeleton h={180} /></div>)}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon="📦"
          title="ARCHIVE EMPTY"
          description="Approve and archive documents from the Queue to see them here."
        />
      ) : view === 'grid' ? (
        <div className="doc-grid">
          {items.map((d, i) => (
            <div
              key={d.doc_id}
              className="doc-card"
              style={{ animationDelay: `${i * 0.06}s`, cursor: 'pointer' }}
              onClick={() => setDetailDoc(d)}
            >
              <div className="doc-thumb" style={{ background: palette[i % palette.length], color: '#000' }}>
                <span style={{ fontSize: 36 }}>{DI_TYPE_ICON[d.document_type] || '📄'}</span>
                <div className="doc-type-badge">{diTypeLabel(d.document_type)}</div>
              </div>
              <div className="doc-info">
                <div className="doc-title">{d.title || d.filename}</div>
                <div className="doc-meta">{d.doc_id} · {d.file_size}</div>
                <div className="doc-tags">{(d.tags || []).slice(0, 4).map(t => <Chip key={t} label={t} />)}</div>
                <div className="doc-footer">
                  <span>{d.department || '—'}</span>
                  <span>{(d.archived_at || '').slice(0, 10)}</span>
                </div>
                <div style={{ marginTop: 8, display: 'flex', gap: 6 }}>
                  {d.storage_url && <a className="btn-brutal" href={d.storage_url} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 8px', textDecoration: 'none' }} onClick={e => e.stopPropagation()}>⭳ ORIG</a>}
                  <button className="btn-brutal" style={{ fontSize: 10, padding: '4px 8px' }} onClick={e => { e.stopPropagation(); downloadOne(d.doc_id); }}>TXT</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="widget-card">
          <DataTable
            onRowClick={d => setDetailDoc(d)}
            columns={[
              { key: 'doc_id',         label: 'ID',       width: 110 },
              { key: 'title',          label: 'TITLE',    render: (v, r) => v || r.filename },
              { key: 'document_type',  label: 'TYPE',     width: 140, render: diTypeLabel },
              { key: 'department',     label: 'DEPT',     width: 130 },
              { key: 'file_size',      label: 'SIZE',     width: 80 },
              { key: 'archived_at',    label: 'ARCHIVED', width: 110, render: v => (v || '').slice(0, 10) },
            ]}
            rows={items}
          />
        </div>
      )}

      {detailDoc && <DocDetailModal doc={detailDoc} onClose={() => setDetailDoc(null)} onChanged={() => setTick(t => t + 1)} />}
      {toastHost}
    </div>
  );
};

// ============================================================
// 4. TEMPLATES — restructured: Type Cards → Doc List → Editable Doc
//    Each TYPE shows the actual processed/archived documents of that type.
//    Some types are SECURED — open them only after passport-key unlock.
// ============================================================

// Doc types that hold sensitive PII and require unlock
const DI_SECURED_TYPES = new Set(['id_document', 'government_permit']);

const DocIntelTemplates = ({ refreshTick }) => {
  const [allDocs, setAllDocs]     = React.useState([]);
  const [loading, setLoading]     = React.useState(false);
  const [error, setError]         = React.useState(null);
  const [tick, setTick]           = React.useState(0);
  const [openType, setOpenType]   = React.useState(null);     // selected type to drill into
  const [unlockedTypes, setUnlocked] = React.useState(() => new Set());
  const [pendingUnlock, setPendingUnlock] = React.useState(null);  // type pending key entry
  const [editingDoc, setEditingDoc] = React.useState(null);
  const [toast, toastHost] = useToast();

  // Fetch ALL processed docs (any status that ran through pipeline)
  React.useEffect(() => {
    setLoading(true); setError(null);
    apiFetch('/api/documents/queue', { params: { per_page: 100, sort_by: 'created_at', sort_order: 'desc' } })
      .then(res => setAllDocs(res.items || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [tick, refreshTick]);

  const refresh = () => setTick(t => t + 1);

  // Group docs by document_type. All 10 known types listed even if 0 docs.
  const docsByType = React.useMemo(() => {
    const groups = {};
    DI_DOC_TYPES.filter(t => t.api !== 'auto_detect').forEach(t => { groups[t.api] = []; });
    for (const d of allDocs) {
      if (!groups[d.document_type]) groups[d.document_type] = [];
      groups[d.document_type].push(d);
    }
    return groups;
  }, [allDocs]);

  const handleTypeClick = (typeApi) => {
    if (DI_SECURED_TYPES.has(typeApi) && !unlockedTypes.has(typeApi)) {
      setPendingUnlock(typeApi);
    } else {
      setOpenType(typeApi);
    }
  };

  const onUnlock = (typeApi) => {
    setUnlocked(prev => { const next = new Set(prev); next.add(typeApi); return next; });
    setPendingUnlock(null);
    setOpenType(typeApi);
  };

  // ---- LEVEL 2: doc list for a selected type ----
  if (openType) {
    const docs = docsByType[openType] || [];
    const typeUI = DI_DOC_TYPES.find(t => t.api === openType)?.ui || openType;
    return (
      <div className="tab-pane">
        <div className="toolbar">
          <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={() => setOpenType(null)}>← ALL TYPES</button>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, flex: 1 }}>
            {DI_TYPE_ICON[openType] || '📄'} {typeUI.toUpperCase()}
            <span style={{ marginLeft: 12, opacity: 0.6, fontWeight: 400 }}>{docs.length} document{docs.length !== 1 ? 's' : ''} · most recent first</span>
            {DI_SECURED_TYPES.has(openType) && <Badge variant="red" style={{ marginLeft: 10 }}>🔒 SECURED — UNLOCKED</Badge>}
          </div>
          <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={refresh} disabled={loading}>↻</button>
        </div>

        {docs.length === 0 ? (
          <EmptyState icon={DI_TYPE_ICON[openType] || '📄'} title="NO DOCUMENTS" description={`Upload a ${typeUI.toLowerCase()} from the Upload tab to see it here.`} />
        ) : (
          <div className="doc-grid">
            {docs.map((d, i) => (
              <div key={d.doc_id} className="doc-card" style={{ cursor: 'pointer', animationDelay: `${i * 0.06}s` }} onClick={() => setEditingDoc(d)}>
                <div className="doc-thumb" style={{ background: 'var(--gold)', color: '#000' }}>
                  <span style={{ fontSize: 36 }}>{DI_TYPE_ICON[openType] || '📄'}</span>
                  <div className="doc-type-badge">{(d.status || '').replace('_', ' ')}</div>
                </div>
                <div className="doc-info">
                  <div className="doc-title">{d.title || d.filename}</div>
                  <div className="doc-meta">{d.doc_id} · {Math.round(d.confidence || 0)}% conf</div>
                  <div className="doc-tags">{(d.tags || []).slice(0, 3).map(t => <Chip key={t} label={t} />)}</div>
                  <div className="doc-footer">
                    <span>{d.uploaded_by || '—'}</span>
                    <span>{(d.created_at || '').slice(0, 10)}</span>
                  </div>
                  <button className="btn-brutal action-btn gold" style={{ marginTop: 8, fontSize: 11, padding: '6px 10px', width: '100%' }} onClick={e => { e.stopPropagation(); setEditingDoc(d); }}>OPEN & EDIT</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {editingDoc && <DocEditModal doc={editingDoc} onClose={() => setEditingDoc(null)} onSaved={() => { setEditingDoc(null); refresh(); }} />}
        {toastHost}
      </div>
    );
  }

  // ---- LEVEL 1: type grid ----
  return (
    <div className="tab-pane">
      <div className="toolbar">
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, opacity: 0.7 }}>
          Documents organized by type. Click a type to view, edit, or update individual documents.
          {' · '}{allDocs.length} total processed
        </div>
        <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={refresh} disabled={loading}>↻ REFRESH</button>
      </div>

      {error && <div className="warning-banner"><span>⚠</span><div>Backend: {error}</div></div>}

      {loading && allDocs.length === 0 ? (
        <div className="template-grid">
          {[1, 2, 3, 4, 5, 6].map(i => <div key={i} className="template-card"><Skeleton h={110} /></div>)}
        </div>
      ) : (
        <div className="template-grid">
          {Object.entries(docsByType).map(([typeApi, docs], i) => {
            const typeUI = DI_DOC_TYPES.find(t => t.api === typeApi)?.ui || typeApi;
            const secured = DI_SECURED_TYPES.has(typeApi);
            const unlocked = unlockedTypes.has(typeApi);
            return (
              <div
                key={typeApi}
                className="template-card type-card"
                style={{ animationDelay: `${i * 0.05}s`, cursor: 'pointer' }}
                onClick={() => handleTypeClick(typeApi)}
              >
                <div className="template-icon" style={{ background: docs.length > 0 ? 'var(--gold)' : '#e0ddd0' }}>
                  {DI_TYPE_ICON[typeApi] || '📄'}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="template-name">{typeUI}</div>
                  <div className="template-meta">
                    <span style={{ fontWeight: 700, color: docs.length > 0 ? '#000' : '#888' }}>
                      {docs.length} document{docs.length !== 1 ? 's' : ''}
                    </span>
                    {secured && (
                      <span style={{ marginLeft: 8 }}>
                        {unlocked
                          ? <Badge variant="green">🔓 UNLOCKED</Badge>
                          : <Badge variant="red">🔒 SECURED</Badge>}
                      </span>
                    )}
                  </div>
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 18, opacity: 0.4 }}>›</div>
              </div>
            );
          })}
        </div>
      )}

      {pendingUnlock && (
        <PassportUnlockModal
          typeApi={pendingUnlock}
          onClose={() => setPendingUnlock(null)}
          onSuccess={() => onUnlock(pendingUnlock)}
        />
      )}
      {toastHost}
    </div>
  );
};

// ----- Passport unlock modal for secured types -----
const PassportUnlockModal = ({ typeApi, onClose, onSuccess }) => {
  const typeUI = DI_DOC_TYPES.find(t => t.api === typeApi)?.ui || typeApi;
  const [key, setKey] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);

  const tryUnlock = async () => {
    if (key.length !== 6) { setErr('Passport key must be 6 characters'); return; }
    setBusy(true); setErr(null);
    try {
      // Hit the passport-key verification endpoint via any system template
      const tpls = await apiFetch('/api/templates');
      const sysTpl = (tpls.templates || []).find(t => t.is_system);
      if (!sysTpl) { setErr('No system template configured for verification'); setBusy(false); return; }
      const res = await apiFetch(`/api/templates/${sysTpl.id}/verify-access`, { json: { passport_key: key } });
      if (res.access_granted) onSuccess();
      else setErr(res.reason || 'Access denied');
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={true} onClose={onClose} size="sm" title={`🔒 SECURED: ${typeUI.toUpperCase()}`}
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CANCEL</button>
        <button className="btn-brutal action-btn gold" onClick={tryUnlock} disabled={busy || key.length !== 6} style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }}>{busy ? 'CHECKING...' : 'UNLOCK'}</button>
      </>}
    >
      <p style={{ fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.5, marginBottom: 12 }}>
        This document type contains sensitive information (Aadhaar, government records, etc.) viewable only by authorized officials. Enter your <strong>6-character passport key</strong> to access.
      </p>
      <label className="field-label">PASSPORT KEY</label>
      <input
        className="brutal-select"
        value={key}
        onChange={e => setKey(e.target.value.toUpperCase().slice(0, 6))}
        maxLength={6}
        autoFocus
        onKeyDown={e => { if (e.key === 'Enter') tryUnlock(); }}
        placeholder="A3X9K2"
        style={{ letterSpacing: 8, fontFamily: 'var(--font-mono)', fontSize: 18, textAlign: 'center' }}
      />
      {err && <div className="warning-banner" style={{ marginTop: 10 }}><span>⚠</span><div>{err}</div></div>}
    </Modal>
  );
};

// ----- Doc edit modal: actual document editing (extracted text + structured fields) -----
const DocEditModal = ({ doc, onClose, onSaved }) => {
  const [view, setView] = React.useState(null);     // edit-view payload
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const [text, setText] = React.useState('');
  const [title, setTitle] = React.useState(doc.title || '');
  const [tags, setTags] = React.useState((doc.tags || []).join(', '));
  const [department, setDepartment] = React.useState(doc.department || '');
  const [fields, setFields] = React.useState({});
  const [passportKey, setPassportKey] = React.useState('');
  const [toast, toastHost] = useToast();

  React.useEffect(() => {
    apiFetch(`/api/documents/${doc.doc_id}/edit-view`)
      .then(v => {
        setView(v);
        setText(v.extracted_text || '');
        setFields(v.extracted_fields || {});
      })
      .catch(e => setErr(e.message));
  }, [doc.doc_id]);

  const setField = (k, v) => setFields(f => ({ ...f, [k]: v }));

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const body = {
        fields,
        extracted_text: text,
        title: title || null,
        tags: tags ? tags.split(',').map(s => s.trim()).filter(Boolean) : [],
        department: department || null,
      };
      if (view?.requires_passport_key) {
        if (passportKey.length !== 6) { setErr('Passport key required (6 chars)'); setBusy(false); return; }
        body.passport_key = passportKey;
      }
      const res = await apiFetch(`/api/documents/${doc.doc_id}/edit-save`, { method: 'PUT', json: body });
      toast(`Saved · re-indexed: ${res.reindexed ? 'yes' : 'no'}`, 'success');
      onSaved?.();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const reqKey = view?.requires_passport_key;

  return (
    <Modal open={true} onClose={onClose} size="lg"
      title={`✎ EDIT · ${doc.doc_id} · ${doc.filename}`}
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CANCEL</button>
        <button className="btn-brutal action-btn gold" onClick={save} disabled={busy || !view || (reqKey && passportKey.length !== 6)} style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }}>{busy ? 'SAVING...' : '💾 SAVE CHANGES'}</button>
      </>}
    >
      {!view ? <Skeleton h={300} /> : (
        <>
          {reqKey && (
            <div className="warning-banner" style={{ marginBottom: 12 }}>
              <span>🔒</span>
              <div>This document is <strong>archived + urgent</strong>. Enter your 6-char passport key to save edits.</div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label className="field-label">TITLE</label>
              <input className="brutal-select" value={title} onChange={e => setTitle(e.target.value)} placeholder="Optional human-readable title" />
            </div>
            <div>
              <label className="field-label">DEPARTMENT</label>
              <input className="brutal-select" value={department} onChange={e => setDepartment(e.target.value)} placeholder="e.g. Finance, PWD" />
            </div>
          </div>

          <label className="field-label mt-14">TAGS (comma-separated)</label>
          <input className="brutal-select" value={tags} onChange={e => setTags(e.target.value)} placeholder="invoice, q2, finance" />

          {/* Template-mapped structured fields */}
          {(view.template_fields || []).length > 0 && (
            <>
              <div className="section-divider mt-20"><span>STRUCTURED FIELDS · {(view.template_fields || []).length} per template</span></div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
                {(view.template_fields || []).map(f => (
                  <div key={f.name}>
                    <label className="field-label">{f.name.replace(/_/g, ' ').toUpperCase()}{f.required && ' *'}</label>
                    <input
                      className="brutal-select"
                      value={fields[f.name] != null ? String(fields[f.name]) : ''}
                      onChange={e => setField(f.name, e.target.value)}
                      placeholder={f.type}
                    />
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="section-divider mt-20"><span>DOCUMENT CONTENT — Word-style editor (formatting preserved)</span></div>
          <RichEditor value={text} onChange={setText} placeholder="Edit the document content here..." minHeight={420} />

          {reqKey && (
            <>
              <label className="field-label mt-14">PASSPORT KEY (6 chars)</label>
              <input
                className="brutal-select"
                value={passportKey}
                onChange={e => setPassportKey(e.target.value.toUpperCase().slice(0, 6))}
                maxLength={6}
                style={{ letterSpacing: 8, fontFamily: 'var(--font-mono)', fontSize: 16, textAlign: 'center' }}
                placeholder="A3X9K2"
              />
            </>
          )}

          {err && <div className="warning-banner" style={{ marginTop: 12 }}><span>⚠</span><div>{err}</div></div>}
        </>
      )}
      {toastHost}
    </Modal>
  );
};

// ============================================================
// 5. ANALYTICS — fully wired to /api/dashboard/*
// ============================================================
const DocIntelAnalytics = ({ refreshTick }) => {
  const [period, setPeriod] = React.useState('30d');
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [tick, setTick] = React.useState(0);

  React.useEffect(() => {
    setLoading(true); setError(null);
    Promise.all([
      apiFetch('/api/dashboard/stats',            { params: { period } }),
      apiFetch('/api/dashboard/volume',           { params: { period: period === '7d' ? '7d' : '14d' } }),
      apiFetch('/api/dashboard/by-type',          { params: { period } }),
      apiFetch('/api/dashboard/top-uploaders',    { params: { period, limit: 5 } }),
      apiFetch('/api/dashboard/sla-distribution', { params: { period } }),
    ])
      .then(([stats, volume, byType, top, sla]) => setData({ stats, volume, byType, top, sla }))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [period, tick, refreshTick]);

  const palette = ['var(--gold)', 'var(--red)', 'var(--cyan)', 'var(--green)'];
  const fmtPct = (n) => (n > 0 ? `+${n}%` : `${n}%`);

  if (loading && !data) {
    return (
      <div className="tab-pane">
        <div className="kpi-grid-4">
          {[1, 2, 3, 4].map(i => <div key={i} className="kpi-card"><Skeleton h={80} /></div>)}
        </div>
        <div style={{ height: 16 }} />
        <Skeleton h={220} />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="tab-pane">
        <EmptyState icon="⚠" title="DASHBOARD UNAVAILABLE" description={error || 'No data returned.'} />
      </div>
    );
  }

  const { stats, volume, byType, top, sla } = data;
  const volumeData = volume.data.map(b => b.count);
  const segments = byType.breakdown.map((b, i) => ({ label: diTypeLabel(b.type), value: b.count, color: palette[i % palette.length] }));

  return (
    <div className="tab-pane">
      <div className="toolbar">
        <SegmentedControl options={['7d', '14d', '30d', '90d']} value={period} onChange={setPeriod} accent="var(--gold)" />
        <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={() => setTick(t => t + 1)} disabled={loading}>↻ REFRESH</button>
      </div>

      <div className="kpi-grid-4">
        <KPICard label={`DOCS PROCESSED (${period.toUpperCase()})`} value={String(stats.docs_processed.value)} color="var(--gold)" data={volumeData} delta={fmtPct(stats.docs_processed.change_percent)} deltaDir={stats.docs_processed.trend} />
        <KPICard label="AVG CONFIDENCE" value={`${stats.avg_confidence.value}%`} color="var(--green)" data={[stats.avg_confidence.value]} delta={fmtPct(stats.avg_confidence.change_percent)} deltaDir={stats.avg_confidence.trend} />
        <KPICard label="PII REDACTIONS" value={String(stats.pii_redactions.value)} color="var(--red)" data={[stats.pii_redactions.value]} delta={fmtPct(stats.pii_redactions.change_percent)} deltaDir={stats.pii_redactions.trend} />
        <KPICard label="AVG TIME TO APPROVE" value={`${stats.avg_time_to_approve.value}h`} color="var(--cyan)" data={[stats.avg_time_to_approve.value]} delta={fmtPct(stats.avg_time_to_approve.change_percent)} deltaDir={stats.avg_time_to_approve.trend} />
      </div>

      <div className="widgets-grid mt-20">
        <MiniChart title={`DAILY VOLUME (${volume.period.toUpperCase()})`} data={volumeData} color="var(--gold)" labels={['', 'TODAY']} />
        <div className="widget-card">
          <div className="widget-title">DOCS BY TYPE</div>
          <Donut segments={segments.length ? segments : [{ label: 'no data', value: 1, color: '#ccc' }]} centerValue={String(byType.total)} centerLabel={`${period.toUpperCase()} TOTAL`} />
        </div>
      </div>

      <div className="widgets-grid mt-20">
        <div className="widget-card">
          <div className="widget-title">TOP UPLOADERS</div>
          {top.uploaders.length === 0 ? (
            <EmptyState icon="·" description="No uploads in this period" />
          ) : (
            <div className="leaderboard">
              {top.uploaders.map((r, i) => (
                <div key={r.rank} className="leaderboard-row">
                  <span className="leaderboard-rank">#{r.rank}</span>
                  <Avatar name={r.name} color={palette[i % palette.length]} size={28} />
                  <span className="leaderboard-name">{r.name}</span>
                  <span className="leaderboard-count">{r.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="widget-card">
          <div className="widget-title">PROCESSING SLA</div>
          <div className="sla-list">
            {[
              { key: 'under_1h',  label: '< 1 hour',     color: 'var(--green)' },
              { key: '1_to_4h',   label: '1 — 4 hours',  color: 'var(--cyan)' },
              { key: '4_to_24h',  label: '4 — 24 hours', color: 'var(--gold)' },
              { key: 'over_24h',  label: '> 24 hours',   color: 'var(--red)' },
            ].map(b => (
              <div key={b.key} className="sla-row">
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 10, height: 10, background: b.color, border: '1px solid #000' }}></span>
                  {b.label}
                </span>
                <span style={{ fontWeight: 700 }}>{sla[b.key]?.count || 0}</span>
                <span style={{ opacity: 0.6 }}>{sla[b.key]?.percent || 0}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

/* ======================================================================
   GOVERNMENT MODULE 2 — RESUME SCREENING
   Tabs: Jobs · Pipeline · Candidates · Analytics · Settings
   ====================================================================== */
const ResumeScreening = ({ onBack }) => {
  const [tab, setTab] = React.useState('jobs');
  const [refreshTick, setRefreshTick] = React.useState(0);
  const [jobsCount, setJobsCount] = React.useState(0);
  const [candCount, setCandCount] = React.useState(0);
  const bumpRefresh = React.useCallback(() => setRefreshTick(t => t + 1), []);

  React.useEffect(() => {
    apiFetch('/api/resume/jobs').then(r => setJobsCount((r.jobs || []).length)).catch(() => {});
    apiFetch('/api/resume/candidates', { params: { per_page: 1 } }).then(r => setCandCount(r.total || 0)).catch(() => {});
  }, [refreshTick]);

  const tabs = [
    { key: 'jobs',       label: 'ACTIVE JOBS', badge: jobsCount },
    { key: 'pipeline',   label: 'PIPELINE' },
    { key: 'candidates', label: 'CANDIDATES', badge: candCount },
    { key: 'analytics',  label: 'ANALYTICS' },
    { key: 'settings',   label: 'SETTINGS' },
  ];

  return (
    <div className="subpage fade-in">
      <SubPageHeader
        title="RESUME SCREENING"
        gatewayId="GATEWAY_02"
        subtitle={<>BERT + Groq · SKILL MATCHING · BIAS DETECTION · {candCount} ACTIVE CANDIDATES · {jobsCount} OPEN ROLES</>}
        accentColor="var(--red)"
        onBack={onBack}
        actions={
          <button
            className="btn-brutal action-btn red"
            style={{ padding: '8px 16px', fontSize: 12, width: 'auto' }}
            onClick={() => { setTab('jobs'); window.dispatchEvent(new CustomEvent('citadel:open-add-job')); }}
          >
            ＋ NEW REQUISITION
          </button>
        }
      />
      <Tabs tabs={tabs} active={tab} onChange={setTab} accent="var(--red)" />
      {tab === 'jobs'       && <ResumeJobs       refreshTick={refreshTick} bumpRefresh={bumpRefresh} setTab={setTab} />}
      {tab === 'pipeline'   && <ResumePipeline   refreshTick={refreshTick} bumpRefresh={bumpRefresh} />}
      {tab === 'candidates' && <ResumeCandidates refreshTick={refreshTick} bumpRefresh={bumpRefresh} />}
      {tab === 'analytics'  && <ResumeAnalytics  refreshTick={refreshTick} />}
      {tab === 'settings'   && <ResumeSettings   refreshTick={refreshTick} bumpRefresh={bumpRefresh} />}
    </div>
  );
};

// ============================================================
// 1. ACTIVE JOBS — list of cards + Add Job modal + per-card actions
// ============================================================
const ResumeJobs = ({ refreshTick, bumpRefresh, setTab }) => {
  const [jobs, setJobs] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [tick, setTick] = React.useState(0);
  const [openJob, setOpenJob] = React.useState(null);          // job for detail modal
  const [uploadJob, setUploadJob] = React.useState(null);      // job for upload modal
  const [pipelineJob, setPipelineJob] = React.useState(null);  // job for pipeline modal
  const [adding, setAdding] = React.useState(false);
  const [toast, toastHost] = useToast();

  // Listen for the global "open add job" event from header NEW REQUISITION button
  React.useEffect(() => {
    const h = () => setAdding(true);
    window.addEventListener('citadel:open-add-job', h);
    return () => window.removeEventListener('citadel:open-add-job', h);
  }, []);

  React.useEffect(() => {
    setLoading(true); setError(null);
    apiFetch('/api/resume/jobs')
      .then(r => setJobs(r.jobs || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [tick, refreshTick]);

  const refresh = () => { setTick(t => t + 1); bumpRefresh?.(); };

  const deleteJob = async (job) => {
    if (!window.confirm(`Permanently delete ${job.code} (${job.title})? Removes the job + all its candidate records + CV files.`)) return;
    try {
      await apiFetch(`/api/resume/jobs/${job.code}`, { method: 'DELETE' });
      toast(`Deleted ${job.code}`, 'success');
      refresh();
    } catch (e) {
      toast(`Delete failed: ${e.message}`, 'error');
    }
  };

  return (
    <div className="tab-pane">
      <div className="toolbar">
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, opacity: 0.7, flex: 1 }}>
          {jobs.length} active requisition{jobs.length !== 1 ? 's' : ''} · click any card to open full job description
        </div>
        <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={refresh} disabled={loading}>↻ REFRESH</button>
        <button className="btn-brutal action-btn red" style={{ width: 'auto', fontSize: 11, padding: '8px 16px' }} onClick={() => setAdding(true)}>＋ NEW REQUISITION</button>
      </div>

      {error && <div className="warning-banner"><span>⚠</span><div>Backend: {error}</div></div>}

      {loading && jobs.length === 0 ? (
        <div className="jobs-grid">
          {[1, 2, 3].map(i => <div key={i} className="job-card"><Skeleton h={170} /></div>)}
        </div>
      ) : jobs.length === 0 ? (
        <EmptyState icon="📋" title="NO JOBS YET" description="Click ＋ NEW REQUISITION to create your first job." />
      ) : (
        <div className="jobs-grid">
          {jobs.map((j, i) => (
            <div key={j.id} className="job-card" style={{ animationDelay: `${i * 0.06}s`, cursor: 'pointer' }} onClick={() => setOpenJob(j)}>
              <div className="job-header">
                <div style={{ minWidth: 0 }}>
                  <div className="job-title" title={j.title}>{j.title}</div>
                  <div className="job-meta">{j.code} · {j.department || 'Unassigned'}</div>
                </div>
                <Badge variant={j.urgency === 'HIGH' ? 'red' : j.urgency === 'NORMAL' ? 'gold' : 'default'}>{j.urgency}</Badge>
              </div>
              <div className="job-stats">
                <div><div className="job-stat-v">{j.applicants}</div><div className="job-stat-l">APPLICANTS</div></div>
                <div><div className="job-stat-v" style={{ color: 'var(--green)' }}>{j.shortlisted}</div><div className="job-stat-l">SHORTLISTED</div></div>
                <div><div className="job-stat-v">{j.days_open}d</div><div className="job-stat-l">OPEN</div></div>
              </div>
              <div className="job-progress">
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${j.applicants ? Math.min(100, (j.shortlisted / j.applicants) * 100) : 0}%`, background: 'var(--red)' }}></div>
                </div>
                <span className="small-meta">Conversion: {j.applicants ? Math.round((j.shortlisted / j.applicants) * 100) : 0}%</span>
              </div>
              <div className="job-actions" onClick={e => e.stopPropagation()}>
                <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }} onClick={() => setPipelineJob(j)}>VIEW PIPELINE</button>
                <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }} onClick={() => setUploadJob(j)}>BULK SCREEN</button>
                <button className="btn-brutal action-btn red" style={{ fontSize: 11, padding: '6px 12px', width: 'auto' }} onClick={() => setUploadJob(j)}>＋ UPLOAD</button>
                <button className="icon-btn" title="Delete job" onClick={() => deleteJob(j)} style={{ marginLeft: 'auto', background: '#000', color: 'var(--red)', borderColor: 'var(--red)' }}>🗑</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {openJob && <ResumeJobDetailModal job={openJob} onClose={() => setOpenJob(null)} onChanged={refresh} />}
      {uploadJob && <ResumeUploadModal job={uploadJob} onClose={() => setUploadJob(null)} onUploaded={refresh} />}
      {pipelineJob && <ResumePipelineModal job={pipelineJob} onClose={() => setPipelineJob(null)} onChanged={refresh} />}
      {adding && <ResumeAddJobModal onClose={() => setAdding(false)} onCreated={() => { setAdding(false); refresh(); }} />}
      {toastHost}
    </div>
  );
};

// ----- Add Job modal: paste text or upload JD file → preview → create -----
const ResumeAddJobModal = ({ onClose, onCreated }) => {
  const [step, setStep] = React.useState('input');     // input | parsed
  const [tab, setTab] = React.useState('text');        // text | file
  const [text, setText] = React.useState('');
  const fileInputRef = React.useRef(null);
  const [filename, setFilename] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const [parsed, setParsed] = React.useState(null);
  const [rawText, setRawText] = React.useState('');
  const [overrides, setOverrides] = React.useState({});

  const parse = async () => {
    setErr(null); setBusy(true);
    try {
      let res;
      if (tab === 'file') {
        const file = fileInputRef.current?.files?.[0];
        if (!file) { setErr('Pick a file first'); setBusy(false); return; }
        const fd = new FormData(); fd.append('file', file);
        res = await apiFetch('/api/resume/jd/parse', { form: fd });
      } else {
        if (!text.trim() || text.trim().length < 30) { setErr('Paste at least 30 characters of JD'); setBusy(false); return; }
        const fd = new FormData(); fd.append('text', text);
        res = await apiFetch('/api/resume/jd/parse', { form: fd });
      }
      setParsed(res.parsed_jd);
      setRawText(res.raw_text || text);
      setOverrides({
        title: res.parsed_jd.title || '',
        department: res.parsed_jd.department || '',
        urgency: res.parsed_jd.urgency || 'NORMAL',
        openings: res.parsed_jd.openings || 1,
      });
      setStep('parsed');
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  const create = async () => {
    setBusy(true); setErr(null);
    try {
      await apiFetch('/api/resume/jobs', {
        json: {
          title: overrides.title,
          department: overrides.department,
          urgency: overrides.urgency,
          openings: parseInt(overrides.openings) || 1,
          raw_jd_text: rawText,
          parsed_jd: { ...parsed, title: overrides.title, department: overrides.department, urgency: overrides.urgency, openings: parseInt(overrides.openings) || 1 },
          posted_by: 'RSD',
        },
      });
      onCreated?.();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Modal open={true} onClose={onClose} size="lg" title={step === 'input' ? '＋ NEW JOB REQUISITION' : '✓ JD PARSED — REVIEW & CREATE'}
      footer={
        step === 'input' ? <>
          <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CANCEL</button>
          <button className="btn-brutal action-btn red" onClick={parse} disabled={busy} style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }}>{busy ? 'PARSING WITH GROQ...' : 'PARSE JD →'}</button>
        </> : <>
          <button className="btn-brutal" onClick={() => setStep('input')} style={{ fontSize: 11, padding: '8px 14px' }}>← BACK</button>
          <button className="btn-brutal action-btn red" onClick={create} disabled={busy} style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }}>{busy ? 'CREATING...' : '✓ CREATE JOB'}</button>
        </>
      }
    >
      {step === 'input' ? (
        <>
          <div className="segmented-control" style={{ marginBottom: 14 }}>
            <button className={`seg-btn ${tab === 'text' ? 'active' : ''}`} onClick={() => setTab('text')}>📝 PASTE TEXT</button>
            <button className={`seg-btn ${tab === 'file' ? 'active' : ''}`} onClick={() => setTab('file')}>⬆ UPLOAD FILE</button>
          </div>

          {tab === 'text' ? (
            <>
              <label className="field-label">JOB DESCRIPTION (free text)</label>
              <textarea
                className="brutal-select"
                value={text}
                onChange={e => setText(e.target.value)}
                rows={14}
                placeholder="Paste the full JD here. Groq will extract title, skills, experience, education, location, culture-fit automatically."
                style={{ fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.5, width: '100%' }}
              />
              <div className="small-meta" style={{ marginTop: 6 }}>{text.length} chars</div>
            </>
          ) : (
            <>
              <label className="field-label">UPLOAD JD (PDF / DOCX / TXT / image)</label>
              <input ref={fileInputRef} type="file" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg" onChange={e => setFilename(e.target.files?.[0]?.name || '')} className="brutal-select" />
              {filename && <div className="small-meta" style={{ marginTop: 6 }}>Selected: <strong>{filename}</strong></div>}
              <div className="warning-banner" style={{ marginTop: 12 }}>
                <span>ℹ</span>
                <div>OCR runs first if it's a scanned PDF or image. Then Groq extracts title, skills, experience, education, location, and culture-fit values.</div>
              </div>
            </>
          )}
          {err && <div className="warning-banner" style={{ marginTop: 12 }}><span>⚠</span><div>{err}</div></div>}
        </>
      ) : (
        <ResumeJDPreview parsed={parsed} overrides={overrides} setOverrides={setOverrides} err={err} />
      )}
    </Modal>
  );
};

// ----- JD parsed preview (shared by Add Job and Edit Job) -----
const ResumeJDPreview = ({ parsed, overrides, setOverrides, err }) => {
  if (!parsed) return null;
  return (
    <div>
      <div className="warning-banner" style={{ marginBottom: 14 }}>
        <span>✓</span><div><strong>Groq parsed your JD.</strong> Review the auto-extracted fields below — adjust title/department/urgency/openings if needed, then create the job.</div>
      </div>

      <div className="inline-fields">
        <div>
          <label className="field-label">TITLE *</label>
          <input className="brutal-select" value={overrides.title || ''} onChange={e => setOverrides({ ...overrides, title: e.target.value })} />
        </div>
        <div>
          <label className="field-label">DEPARTMENT</label>
          <input className="brutal-select" value={overrides.department || ''} onChange={e => setOverrides({ ...overrides, department: e.target.value })} />
        </div>
      </div>
      <div className="inline-fields" style={{ marginTop: 10 }}>
        <div>
          <label className="field-label">URGENCY</label>
          <select className="brutal-select" value={overrides.urgency} onChange={e => setOverrides({ ...overrides, urgency: e.target.value })}>
            <option>LOW</option><option>NORMAL</option><option>HIGH</option>
          </select>
        </div>
        <div>
          <label className="field-label">OPENINGS</label>
          <input type="number" min="1" className="brutal-select" value={overrides.openings || 1} onChange={e => setOverrides({ ...overrides, openings: e.target.value })} />
        </div>
      </div>

      <div className="section-divider mt-20"><span>EXTRACTED REQUIREMENTS</span></div>
      <ResumeJDDisplay jd={parsed} compact />

      {err && <div className="warning-banner" style={{ marginTop: 12 }}><span>⚠</span><div>{err}</div></div>}
    </div>
  );
};

// ----- Gorgeous JD presentation: shared by Detail modal + parsed preview -----
const ResumeJDDisplay = ({ jd, compact }) => {
  if (!jd) return <EmptyState icon="📄" description="No structured JD available." />;
  const rs = jd.required_skills || {};
  const ex = jd.experience || {};
  const ed = jd.education || {};
  const lo = jd.location || {};
  const cf = jd.culture_fit || {};

  return (
    <div className="resume-jd">
      {jd.summary && (
        <div className="resume-jd-summary">{jd.summary}</div>
      )}

      <div className="resume-jd-strip">
        <div className="strip-stat"><div className="strip-v">{jd.openings || 1}</div><div className="strip-l">OPENINGS</div></div>
        <div className="strip-stat"><div className="strip-v">{ex.min_years ?? 0}–{ex.max_years || '∞'}</div><div className="strip-l">YEARS</div></div>
        <div className="strip-stat"><div className="strip-v">{rs.minimum_match_percent ?? 60}%</div><div className="strip-l">MIN MATCH</div></div>
        <div className="strip-stat"><div className="strip-v">{(ed.minimum_level || 'bachelors').toUpperCase()}</div><div className="strip-l">EDUCATION</div></div>
      </div>

      <div className="resume-jd-section">
        <div className="resume-jd-h">REQUIRED SKILLS</div>
        <div className="resume-jd-row">
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Must have</div>
            <div className="resume-jd-chips">
              {(rs.must_have || []).map(s => <span key={s} className="resume-jd-chip must">{s}</span>)}
              {!(rs.must_have || []).length && <span className="small-meta">— none specified —</span>}
            </div>
          </div>
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Nice to have</div>
            <div className="resume-jd-chips">
              {(rs.nice_to_have || []).map(s => <span key={s} className="resume-jd-chip nice">{s}</span>)}
              {!(rs.nice_to_have || []).length && <span className="small-meta">— none specified —</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="resume-jd-section">
        <div className="resume-jd-h">EXPERIENCE</div>
        <div className="resume-jd-row">
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Preferred titles</div>
            <div className="resume-jd-chips">{(ex.preferred_titles || []).map(t => <span key={t} className="resume-jd-chip">{t}</span>)}</div>
          </div>
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Preferred industries</div>
            <div className="resume-jd-chips">{(ex.preferred_industries || []).map(t => <span key={t} className="resume-jd-chip">{t}</span>)}</div>
          </div>
        </div>
      </div>

      <div className="resume-jd-section">
        <div className="resume-jd-h">EDUCATION</div>
        <div className="resume-jd-row">
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Minimum level</div>
            <div className="resume-jd-chips"><span className="resume-jd-chip must">{(ed.minimum_level || 'bachelors').toUpperCase()}</span></div>
          </div>
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Preferred fields</div>
            <div className="resume-jd-chips">{(ed.preferred_fields || []).map(f => <span key={f} className="resume-jd-chip">{f}</span>)}</div>
          </div>
        </div>
      </div>

      <div className="resume-jd-section">
        <div className="resume-jd-h">LOCATION</div>
        <div className="resume-jd-row">
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Preferred cities</div>
            <div className="resume-jd-chips">{(lo.preferred_cities || []).map(c => <span key={c} className="resume-jd-chip">{c}</span>)}</div>
          </div>
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Flexibility</div>
            <div className="resume-jd-chips">
              {lo.remote_ok && <span className="resume-jd-chip nice">REMOTE OK</span>}
              {lo.relocation_ok && <span className="resume-jd-chip nice">RELOCATION OK</span>}
              {!lo.remote_ok && !lo.relocation_ok && <span className="resume-jd-chip">ON-SITE</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="resume-jd-section">
        <div className="resume-jd-h">CULTURE FIT</div>
        <div className="resume-jd-row">
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Keywords</div>
            <div className="resume-jd-chips">{(cf.keywords || []).map(k => <span key={k} className="resume-jd-chip">{k}</span>)}</div>
          </div>
          <div className="resume-jd-col">
            <div className="resume-jd-sub">Values</div>
            <div className="resume-jd-chips">{(cf.values || []).map(v => <span key={v} className="resume-jd-chip nice">{v}</span>)}</div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ----- Job Detail modal -----
const ResumeJobDetailModal = ({ job, onClose, onChanged }) => {
  const [showRaw, setShowRaw] = React.useState(false);
  const [editing, setEditing] = React.useState(null);
  return (
    <Modal open={true} onClose={onClose} size="lg"
      title={`${job.code} · ${job.title}`}
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CLOSE</button>
        <button className="btn-brutal" onClick={() => setEditing(job)} style={{ fontSize: 11, padding: '8px 14px' }}>✎ EDIT JD</button>
      </>}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <Badge variant={job.urgency === 'HIGH' ? 'red' : job.urgency === 'NORMAL' ? 'gold' : 'default'}>{job.urgency}</Badge>
          <span style={{ marginLeft: 8 }}><Badge variant="default">{job.department || 'Unassigned'}</Badge></span>
          <span style={{ marginLeft: 8 }}><Badge variant="default">{job.status?.toUpperCase()}</Badge></span>
        </div>
        <div className="small-meta">Posted {job.days_open}d ago by {job.posted_by || '—'}</div>
      </div>

      <ResumeJDDisplay jd={job.parsed_jd} />

      {job.raw_jd_text && (
        <>
          <div className="section-divider mt-20"><span>ORIGINAL TEXT</span>
            <button className="btn-brutal" style={{ fontSize: 10, padding: '4px 10px' }} onClick={() => setShowRaw(s => !s)}>{showRaw ? 'HIDE' : 'SHOW'}</button>
          </div>
          {showRaw && (
            <pre style={{ padding: 12, background: '#fafaf5', border: '2px solid #000', maxHeight: 200, overflow: 'auto', fontSize: 11, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
              {job.raw_jd_text}
            </pre>
          )}
        </>
      )}

      {editing && <ResumeEditJDModal job={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChanged?.(); onClose(); }} />}
    </Modal>
  );
};

// ----- Edit JD modal (re-parse + override) -----
const ResumeEditJDModal = ({ job, onClose, onSaved }) => {
  const [text, setText] = React.useState(job.raw_jd_text || '');
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const fd = new FormData(); fd.append('text', text);
      const parsed = await apiFetch('/api/resume/jd/parse', { form: fd });
      await apiFetch(`/api/resume/jobs/${job.code}`, { method: 'PATCH', json: { raw_jd_text: text, parsed_jd: parsed.parsed_jd } });
      onSaved?.();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Modal open={true} onClose={onClose} size="lg" title={`EDIT JD · ${job.code}`}
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CANCEL</button>
        <button className="btn-brutal action-btn red" onClick={save} disabled={busy} style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }}>{busy ? 'RE-PARSING + SAVING...' : '💾 SAVE & RE-SCORE ALL'}</button>
      </>}
    >
      <label className="field-label">JOB DESCRIPTION</label>
      <textarea className="brutal-select" value={text} onChange={e => setText(e.target.value)} rows={20} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, width: '100%' }} />
      <div className="warning-banner" style={{ marginTop: 12 }}><span>⚠</span><div>Saving will re-parse with Groq and re-score every candidate for this job.</div></div>
      {err && <div className="warning-banner" style={{ marginTop: 8 }}><span>⚠</span><div>{err}</div></div>}
    </Modal>
  );
};

// ----- Per-job CV upload modal (single + bulk) -----
const ResumeUploadModal = ({ job, onClose, onUploaded }) => {
  const fileRef = React.useRef(null);
  const [files, setFiles] = React.useState([]);
  const [source, setSource] = React.useState('Direct');
  const [busy, setBusy] = React.useState(false);
  const [progress, setProgress] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [toast, toastHost] = useToast();

  const onPick = (e) => {
    setFiles(Array.from(e.target.files || []));
    if (e.target) e.target.value = '';
  };

  const upload = async () => {
    if (files.length === 0) return;
    setBusy(true); setErr(null); setProgress({ total: files.length, processed: 0 });
    try {
      const fd = new FormData();
      files.forEach(f => fd.append('files', f, f.name));
      fd.append('source', source);
      const res = await apiFetch(`/api/resume/jobs/${job.code}/candidates/upload`, { form: fd });
      toast(`Uploaded ${res.total} CV${res.total !== 1 ? 's' : ''} — Groq parsing + scoring in background`, 'success');
      // Poll candidates for this job until they're scored (or timeout)
      const codes = new Set(res.candidates.map(c => c.code));
      for (let i = 0; i < 45; i++) {
        await new Promise(r => setTimeout(r, 1500));
        const state = await apiFetch('/api/resume/candidates', { params: { job: job.code, per_page: 100 } });
        const done = state.items.filter(it => codes.has(it.code) && it.status !== 'PROCESSING').length;
        setProgress({ total: res.total, processed: done });
        if (done >= res.total) break;
      }
      onUploaded?.();
      setTimeout(onClose, 600);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Modal open={true} onClose={onClose} size="md" title={`📥 UPLOAD CVs → ${job.code}`}
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CANCEL</button>
        <button className="btn-brutal action-btn red" onClick={upload} disabled={busy || files.length === 0} style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }}>{busy ? `PROCESSING ${progress?.processed || 0}/${progress?.total || 0}...` : `UPLOAD & SCORE ${files.length} CV${files.length !== 1 ? 's' : ''}`}</button>
      </>}
    >
      <label className="field-label">SOURCE</label>
      <select className="brutal-select" value={source} onChange={e => setSource(e.target.value)}>
        <option>Direct</option><option>Referral</option><option>LinkedIn</option><option>Naukri</option><option>Other</option>
      </select>

      <label className="field-label mt-14">RESUMES (PDF / DOCX / images)</label>
      <input ref={fileRef} type="file" multiple accept=".pdf,.docx,.txt,.png,.jpg,.jpeg" onChange={onPick} className="brutal-select" />
      {files.length > 0 && (
        <div className="file-list">
          {files.map((f, i) => (
            <div key={i} className="file-item">
              <span style={{ fontSize: 14 }}>📄</span>
              <div style={{ flex: 1 }}>
                <div className="file-name">{f.name}</div>
                <div className="file-meta">{(f.size / 1024).toFixed(0)} KB</div>
              </div>
              <button className="icon-btn" onClick={() => setFiles(files.filter((_, x) => x !== i))}>✕</button>
            </div>
          ))}
        </div>
      )}

      {progress && busy && (
        <div className="progress-wrap mt-14">
          <div className="progress-bar-lg"><div className="progress-fill-lg" style={{ width: `${(progress.processed / progress.total) * 100}%`, background: 'var(--red)' }}></div></div>
          <div className="progress-pct">{progress.processed}/{progress.total}</div>
        </div>
      )}

      {err && <div className="warning-banner mt-14"><span>⚠</span><div>{err}</div></div>}
      {toastHost}
    </Modal>
  );
};

// ============================================================
// 2. PIPELINE — per-job kanban modal
// ============================================================
const ResumePipeline = ({ refreshTick, bumpRefresh }) => {
  const [jobs, setJobs] = React.useState([]);
  const [openJob, setOpenJob] = React.useState(null);

  React.useEffect(() => {
    apiFetch('/api/resume/jobs').then(r => setJobs(r.jobs || [])).catch(() => {});
  }, [refreshTick]);

  return (
    <div className="tab-pane">
      <div className="toolbar">
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, opacity: 0.7 }}>
          Click any job to see its candidate pipeline (Shortlisted → Interview → Offer → Recruited).
        </div>
      </div>
      {jobs.length === 0 ? (
        <EmptyState icon="📋" title="NO JOBS" description="Create a job first." />
      ) : (
        <div className="jobs-grid">
          {jobs.map((j, i) => (
            <div key={j.id} className="job-card" style={{ animationDelay: `${i * 0.06}s`, cursor: 'pointer' }} onClick={() => setOpenJob(j)}>
              <div className="job-header">
                <div style={{ minWidth: 0 }}>
                  <div className="job-title">{j.title}</div>
                  <div className="job-meta">{j.code} · {j.department}</div>
                </div>
                <Badge variant={j.urgency === 'HIGH' ? 'red' : 'gold'}>{j.urgency}</Badge>
              </div>
              <div className="pipeline-mini">
                <div className="pmini" title="Currently in Shortlisted column"><div className="pmini-v" style={{ color: 'var(--green)' }}>{j.currently_shortlisted ?? 0}</div><div className="pmini-l">SHRT</div></div>
                <div className="pmini" title="Currently in Interview"><div className="pmini-v" style={{ color: '#d946ef' }}>{j.interviewing}</div><div className="pmini-l">INTV</div></div>
                <div className="pmini" title="Currently in Offer"><div className="pmini-v" style={{ color: 'var(--red)' }}>{j.offered}</div><div className="pmini-l">OFFR</div></div>
                <div className="pmini" title="Recruited"><div className="pmini-v" style={{ color: '#000' }}>{j.recruited}</div><div className="pmini-l">RCRT</div></div>
                <div className="pmini" title="Rejected"><div className="pmini-v" style={{ color: '#888' }}>{j.rejected}</div><div className="pmini-l">REJ</div></div>
              </div>
              <button className="btn-brutal action-btn red" style={{ width: '100%', fontSize: 11, padding: '8px 12px', marginTop: 10 }} onClick={(e) => { e.stopPropagation(); setOpenJob(j); }}>OPEN PIPELINE →</button>
            </div>
          ))}
        </div>
      )}

      {openJob && <ResumePipelineModal job={openJob} onClose={() => setOpenJob(null)} onChanged={() => bumpRefresh?.()} />}
    </div>
  );
};

const ResumePipelineModal = ({ job, onClose, onChanged }) => {
  const [data, setData] = React.useState([]);
  const [tick, setTick] = React.useState(0);
  const [openCand, setOpenCand] = React.useState(null);

  React.useEffect(() => {
    apiFetch('/api/resume/candidates', { params: { job: job.code, per_page: 200 } })
      .then(r => setData(r.items || []))
      .catch(() => setData([]));
  }, [tick, job.code]);

  const refresh = () => { setTick(t => t + 1); onChanged?.(); };

  const stages = [
    { key: 'SHORTLISTED', label: 'SHORTLISTED', color: 'var(--green)' },
    { key: 'INTERVIEW',   label: 'INTERVIEW',   color: '#d946ef' },
    { key: 'OFFER',       label: 'OFFER',       color: 'var(--red)' },
    { key: 'RECRUITED',   label: 'RECRUITED',   color: '#000' },
    { key: 'REJECTED',    label: 'REJECTED',    color: '#888' },
  ];

  return (
    <Modal open={true} onClose={onClose} size="lg" title={`📋 PIPELINE · ${job.code} · ${job.title}`}
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CLOSE</button>
        <button className="btn-brutal" onClick={refresh} style={{ fontSize: 11, padding: '8px 14px' }}>↻ REFRESH</button>
      </>}
    >
      <div className="kanban-board" style={{ gridTemplateColumns: `repeat(${stages.length}, minmax(220px, 1fr))` }}>
        {stages.map(s => {
          const items = data.filter(c => c.status === s.key);
          return (
            <div key={s.key} className="kanban-col" style={{ '--col-accent': s.color }}>
              <div className="kanban-col-header">
                <span className="kanban-col-title">{s.label}</span>
                <span className="kanban-col-count">{items.length}</span>
              </div>
              <div className="kanban-col-body">
                {items.length === 0 ? <div className="kanban-empty">— empty —</div> :
                  items.map((c, i) => (
                    <div key={c.code} className="kanban-card" style={{ animationDelay: `${i * 0.04}s`, cursor: 'pointer' }} onClick={() => setOpenCand(c)}>
                      <div className="kanban-card-header">
                        <Avatar name={c.name || '?'} size={28} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div className="kanban-name" title={c.name}>{c.name || '(parsing...)'}</div>
                          <div className="kanban-meta">{c.total_experience_years ? `${c.total_experience_years}yrs` : '—'}</div>
                        </div>
                        <div className="kanban-score" style={{ background: c.final_score >= 90 ? 'var(--green)' : c.final_score >= 75 ? 'var(--gold)' : c.final_score >= 50 ? 'var(--cyan)' : 'var(--red)' }}>
                          {Math.round(c.final_score || 0)}
                        </div>
                      </div>
                      <div className="kanban-skills">
                        {(c.top_skills || []).slice(0, 3).map(s => <Chip key={s} label={s} />)}
                      </div>
                    </div>
                  ))
                }
              </div>
            </div>
          );
        })}
      </div>
      {openCand && <ResumeCandidateDetailModal cand={openCand} onClose={() => setOpenCand(null)} onChanged={refresh} />}
    </Modal>
  );
};

// ============================================================
// 3. CANDIDATES — job picker → list + detail + actions + compare
// ============================================================
const ResumeCandidates = ({ refreshTick, bumpRefresh }) => {
  const [jobs, setJobs] = React.useState([]);
  const [selectedJob, setSelectedJob] = React.useState(null);
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const [statusFilter, setStatusFilter] = React.useState('');
  const [minScore, setMinScore] = React.useState('');
  const [tick, setTick] = React.useState(0);
  const [openCand, setOpenCand] = React.useState(null);
  const [compareMode, setCompareMode] = React.useState(false);
  const [compareIds, setCompareIds] = React.useState([]);
  const [compareOpen, setCompareOpen] = React.useState(false);
  const [toast, toastHost] = useToast();

  React.useEffect(() => {
    apiFetch('/api/resume/jobs').then(r => {
      setJobs(r.jobs || []);
      if (!selectedJob && r.jobs?.length) setSelectedJob(r.jobs[0]);
    });
  }, [refreshTick]);

  React.useEffect(() => {
    if (!selectedJob) return;
    setLoading(true);
    apiFetch('/api/resume/candidates', {
      params: { job: selectedJob.code, status: statusFilter, q: search, min_score: minScore ? parseFloat(minScore) : undefined, per_page: 200 },
    })
      .then(r => setItems(r.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [selectedJob, search, statusFilter, minScore, tick]);

  const refresh = () => { setTick(t => t + 1); bumpRefresh?.(); };

  const toggleCompare = (code) => {
    setCompareIds(ids => ids.includes(code) ? ids.filter(x => x !== code) : (ids.length < 3 ? [...ids, code] : ids));
  };

  if (!jobs.length) {
    return <div className="tab-pane"><EmptyState icon="📋" title="NO JOBS" description="Create a job first to see its candidates." /></div>;
  }

  return (
    <div className="tab-pane">
      <div className="job-pills">
        {jobs.map(j => (
          <button key={j.id} className={`job-pill ${selectedJob?.id === j.id ? 'active' : ''}`} onClick={() => { setSelectedJob(j); setCompareIds([]); }}>
            <span className="jp-title">{j.title}</span>
            <span className="jp-meta">{j.code} · {j.applicants} cand</span>
          </button>
        ))}
      </div>

      {selectedJob && (
        <>
          <div className="toolbar mt-14">
            <SearchBar value={search} onChange={setSearch} placeholder="Search by name, email, location..." />
            <FilterBar
              filters={[
                { key: 'status', label: 'Status', options: ['SHORTLISTED', 'INTERVIEW', 'OFFER', 'RECRUITED', 'REJECTED', 'PROCESSING'] },
                { key: 'min_score', label: 'Min Score', options: ['90', '80', '70', '60', '50'] },
              ]}
              values={{ status: statusFilter, min_score: minScore }}
              onChange={(k, v) => { if (k === 'status') setStatusFilter(v); else if (k === 'min_score') setMinScore(v); }}
              onClear={() => { setStatusFilter(''); setMinScore(''); }}
            />
            <Toggle checked={compareMode} onChange={(v) => { setCompareMode(v); if (!v) setCompareIds([]); }} label="Compare mode" />
            {compareMode && compareIds.length >= 2 && (
              <button className="btn-brutal action-btn red" style={{ width: 'auto', fontSize: 11, padding: '8px 14px' }} onClick={() => setCompareOpen(true)}>
                COMPARE ({compareIds.length}) →
              </button>
            )}
            <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={refresh}>↻</button>
          </div>

          {loading ? <div style={{ padding: 20 }}><Skeleton h={28} /><div style={{ height: 8 }} /><Skeleton h={28} /></div> :
            items.length === 0 ?
              <EmptyState icon="👤" title="NO CANDIDATES" description="Upload CVs from the Active Jobs tab to start scoring." /> :
              <div className="candidate-grid">
                {items.map((c, i) => (
                  <div key={c.code} className={`candidate-card ${compareIds.includes(c.code) ? 'comparing' : ''}`} style={{ animationDelay: `${i * 0.04}s` }} onClick={() => compareMode ? toggleCompare(c.code) : setOpenCand(c)}>
                    <div className="cc-top">
                      {compareMode && <input type="checkbox" checked={compareIds.includes(c.code)} onChange={() => toggleCompare(c.code)} onClick={e => e.stopPropagation()} />}
                      <Avatar name={c.name || '?'} size={36} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="cc-name">{c.name || '(parsing...)'}</div>
                        <div className="cc-meta">{c.code} · {c.total_experience_years ? `${c.total_experience_years}yrs` : '—'}</div>
                      </div>
                      <div className="cc-score" style={{ background: c.final_score >= 90 ? 'var(--green)' : c.final_score >= 75 ? 'var(--gold)' : c.final_score >= 50 ? 'var(--cyan)' : 'var(--red)' }}>
                        {Math.round(c.final_score || 0)}
                      </div>
                    </div>
                    <div className="cc-skills">
                      {(c.top_skills || []).slice(0, 4).map(s => <Chip key={s} label={s} />)}
                      {(c.top_skills || []).length > 4 && <Chip label={`+${c.top_skills.length - 4}`} />}
                    </div>
                    <div className="cc-foot">
                      <span className="cc-loc">📍 {c.location || '—'}</span>
                      <span className="cc-source">📥 {c.source}</span>
                      <span className={`cc-status status-${c.status.toLowerCase()}`}>{c.status}</span>
                    </div>
                  </div>
                ))}
              </div>
          }
        </>
      )}

      {openCand && <ResumeCandidateDetailModal cand={openCand} onClose={() => setOpenCand(null)} onChanged={refresh} />}
      {compareOpen && <ResumeCompareModal codes={compareIds} job={selectedJob} onClose={() => setCompareOpen(false)} />}
      {toastHost}
    </div>
  );
};

// ----- Candidate detail modal: radar + AI insights + timeline + actions -----
const ResumeCandidateDetailModal = ({ cand, onClose, onChanged }) => {
  const [detail, setDetail] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [scheduling, setScheduling] = React.useState(false);
  const [rejecting, setRejecting] = React.useState(false);
  const [noting, setNoting] = React.useState(false);
  const [toast, toastHost] = useToast();

  React.useEffect(() => {
    apiFetch(`/api/resume/candidates/${cand.code}`)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [cand.code]);

  const advance = async () => {
    if (!detail) return;
    const next = { 'SHORTLISTED': 'INTERVIEW', 'INTERVIEW': 'OFFER', 'OFFER': 'RECRUITED' }[detail.status];
    if (!next) { toast(`Already at terminal stage: ${detail.status}`, 'warn'); return; }
    setBusy(true);
    try {
      await apiFetch(`/api/resume/candidates/${cand.code}/move-stage`, { json: { new_status: next } });
      toast(`Advanced → ${next}`, 'success');
      onChanged?.(); setTimeout(onClose, 300);
    } catch (e) { toast(e.message, 'error'); }
    finally { setBusy(false); }
  };

  if (!detail) return <Modal open={true} onClose={onClose} size="lg" title={cand.code}><Skeleton h={400} /></Modal>;

  const skillProfile = detail.skill_profile || {};
  const status = (detail.status || '').toUpperCase();
  const insights = detail.ai_insights || [];

  return (
    <Modal open={true} onClose={onClose} size="lg" title={`${detail.code} · ${detail.name || '(parsing)'}`}
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CLOSE</button>
        <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }} onClick={() => setNoting(true)}>📝 ADD NOTE</button>
        <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }} onClick={() => setScheduling(true)}>📅 SCHEDULE INTERVIEW</button>
        <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px', background: 'var(--red)', color: '#fff' }} onClick={() => setRejecting(true)}>✕ REJECT</button>
        {status !== 'RECRUITED' && status !== 'REJECTED' && <button className="btn-brutal action-btn" style={{ fontSize: 11, padding: '8px 14px', width: 'auto', background: 'var(--green)', color: '#000' }} onClick={advance} disabled={busy}>✓ ACCEPT / ADVANCE STAGE</button>}
      </>}
    >
      <div className="cand-header">
        <Avatar name={detail.name || '?'} size={64} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 22, letterSpacing: 1, margin: 0 }}>{detail.name || '(parsing)'}</h2>
          <div className="cand-meta">
            <span>📍 {detail.location || '—'}</span>
            <span>🎓 {detail.highest_education || (detail.parsed_resume?.education?.[0]?.degree) || '—'}</span>
            <span>💼 {detail.total_experience_years ? `${detail.total_experience_years} yrs` : '—'}</span>
            <span>✉ {detail.email || '—'}</span>
            <span>📞 {detail.phone || '—'}</span>
          </div>
          <div style={{ marginTop: 6 }}>
            <Badge variant={status === 'SHORTLISTED' ? 'green' : status === 'REJECTED' ? 'red' : status === 'OFFER' ? 'red' : status === 'INTERVIEW' ? 'gold' : 'default'}>{status}</Badge>
            <span style={{ marginLeft: 8 }}><Badge variant="default">{detail.source || 'Direct'}</Badge></span>
          </div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <ProgressRing value={Math.round(detail.final_score || 0)} color="var(--red)" size={88} />
          <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', marginTop: 4, opacity: 0.6 }}>MATCH SCORE</div>
        </div>
      </div>

      {Object.keys(skillProfile).length > 0 && (
        <div className="detail-section">
          <div className="detail-section-title">SKILL PROFILE</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 16, alignItems: 'center' }}>
            <RadarChart axes={Object.keys(skillProfile)} data={Object.values(skillProfile)} color="var(--red)" />
            <div>
              {Object.entries(skillProfile).map(([k, v]) => (
                <div key={k} className="skill-row">
                  <span>{k}</span>
                  <div className="progress-bar"><div className="progress-fill" style={{ width: `${v}%`, background: v >= 80 ? 'var(--green)' : v >= 65 ? 'var(--gold)' : 'var(--red)' }}></div></div>
                  <span className="progress-val">{Math.round(v)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {detail.score_breakdown && (
        <div className="detail-section">
          <div className="detail-section-title">SCORE BREAKDOWN (per dimension)</div>
          <div className="dim-grid">
            {Object.entries(detail.score_breakdown).map(([k, v]) => (
              <div key={k} className="dim-card">
                <div className="dim-label">{k.replace(/_/g, ' ').toUpperCase()}</div>
                <div className="dim-value">{Math.round(v)}</div>
                <div className="progress-bar"><div className="progress-fill" style={{ width: `${v}%`, background: v >= 75 ? 'var(--green)' : v >= 50 ? 'var(--gold)' : 'var(--red)' }}></div></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {insights.length > 0 && (
        <div className="detail-section">
          <div className="detail-section-title">AI ANALYSIS</div>
          <div className="analysis-cards">
            {insights.map((it, i) => (
              <div key={i} className="analysis-card">
                <span className="ac-icon" style={{ color: it.tone === 'good' ? 'var(--green)' : it.tone === 'warn' ? 'var(--gold)' : it.tone === 'bad' ? 'var(--red)' : 'var(--cyan)' }}>
                  {it.tone === 'good' ? '✓' : it.tone === 'warn' ? '⚠' : it.tone === 'bad' ? '✕' : 'ℹ'}
                </span>
                <div><strong>{it.title}</strong><p>{it.body}</p></div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="detail-section">
        <div className="detail-section-title">DECISION TIMELINE</div>
        <ResumeTimeline history={detail.pipeline_history || []} status={status} />
      </div>

      {(detail.parsed_resume?.work_experience || []).length > 0 && (
        <div className="detail-section">
          <div className="detail-section-title">WORK EXPERIENCE</div>
          <div className="work-list">
            {detail.parsed_resume.work_experience.map((w, i) => (
              <div key={i} className="work-item">
                <div className="work-title">{w.title || 'Role'}{w.company && <span className="work-company"> @ {w.company}</span>}</div>
                <div className="work-meta">{w.duration_months ? `${(w.duration_months / 12).toFixed(1)} yrs` : (w.start_year && w.end_year ? `${w.start_year} – ${w.end_year}` : '')}</div>
                {(w.responsibilities || []).length > 0 && (
                  <ul className="work-bullets">{w.responsibilities.slice(0, 3).map((r, j) => <li key={j}>{r}</li>)}</ul>
                )}
                {(w.technologies || []).length > 0 && (
                  <div className="work-tech">{w.technologies.slice(0, 6).map(t => <Chip key={t} label={t} />)}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {(detail.notes || []).length > 0 && (
        <div className="detail-section">
          <div className="detail-section-title">NOTES ({detail.notes.length})</div>
          <div className="notes-list">
            {detail.notes.map((n, i) => (
              <div key={i} className="note-item">
                <div className="note-text">{n.text}</div>
                <div className="note-meta">{n.author} · {n.ts ? new Date(n.ts).toLocaleString() : ''}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.cv_storage_url && (
        <div className="action-row mt-14">
          <a className="btn-brutal" href={detail.cv_storage_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, padding: '8px 14px', textDecoration: 'none' }}>⭳ DOWNLOAD ORIGINAL CV</a>
        </div>
      )}

      {scheduling && <ResumeScheduleModal cand={detail} onClose={() => setScheduling(false)} onScheduled={() => { setScheduling(false); onChanged?.(); setTimeout(onClose, 300); }} />}
      {rejecting && <ResumeRejectModal cand={detail} onClose={() => setRejecting(false)} onRejected={() => { setRejecting(false); onChanged?.(); setTimeout(onClose, 300); }} />}
      {noting && <ResumeNoteModal cand={detail} onClose={() => setNoting(false)} onSaved={() => { setNoting(false); onChanged?.(); }} />}
      {toastHost}
    </Modal>
  );
};

// ----- Decision timeline -----
const ResumeTimeline = ({ history, status }) => {
  const allStages = ['UPLOADED', 'PROCESSING', 'SHORTLISTED', 'INTERVIEW', 'OFFER', 'RECRUITED'];
  const visited = new Set();
  let lastTime = {};
  for (const h of history) {
    visited.add((h.to_status || '').toUpperCase());
    lastTime[(h.to_status || '').toUpperCase()] = h.created_at;
  }
  const isRejected = status === 'REJECTED';
  const stages = isRejected ? [...Array.from(visited).filter(s => s !== 'REJECTED'), 'REJECTED'] :
    allStages.filter((s, i) => i === 0 || visited.has(s) || allStages.indexOf(status) >= i);

  // Always show full happy-path if not rejected
  const display = isRejected ? stages : allStages;

  return (
    <div className="resume-timeline">
      {display.map((s, i) => {
        const done = visited.has(s) || s === status;
        const isCurrent = s === status;
        return (
          <div key={s} className={`rt-step ${done ? 'done' : ''} ${isCurrent ? 'current' : ''}`}>
            <div className="rt-node">{done ? '✓' : i + 1}</div>
            <div className="rt-label">
              <div className="rt-title">{s}</div>
              {lastTime[s] && <div className="rt-time">{new Date(lastTime[s]).toLocaleString()}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ----- Schedule Interview modal -----
const ResumeScheduleModal = ({ cand, onClose, onScheduled }) => {
  const today = new Date();
  today.setDate(today.getDate() + 3);
  const [when, setWhen] = React.useState(today.toISOString().slice(0, 16));
  const [prep, setPrep] = React.useState('Bring 2 portfolio examples + a 5-min self-intro about a recent project you led.');
  const [sendTg, setSendTg] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      await apiFetch(`/api/resume/candidates/${cand.code}/schedule-interview`, {
        json: { when: new Date(when).toISOString(), prep, send_telegram: sendTg },
      });
      onScheduled?.();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Modal open={true} onClose={onClose} size="md" title="📅 SCHEDULE INTERVIEW"
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CANCEL</button>
        <button className="btn-brutal action-btn red" onClick={submit} disabled={busy} style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }}>{busy ? 'SCHEDULING...' : '📅 SCHEDULE & NOTIFY'}</button>
      </>}
    >
      <p className="small-meta" style={{ marginBottom: 10 }}>Schedule an interview for <strong>{cand.name || cand.code}</strong>. Date + prep notes will be sent to your Telegram and the candidate's status will move to INTERVIEW.</p>
      <label className="field-label">DATE & TIME</label>
      <input type="datetime-local" className="brutal-select" value={when} onChange={e => setWhen(e.target.value)} />
      <label className="field-label mt-14">PREP / WHAT TO BRING</label>
      <textarea className="brutal-select" value={prep} onChange={e => setPrep(e.target.value)} rows={4} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, width: '100%' }} />
      <div style={{ marginTop: 10 }}>
        <Toggle checked={sendTg} onChange={setSendTg} label="Send Telegram notification" />
      </div>
      {err && <div className="warning-banner mt-14"><span>⚠</span><div>{err}</div></div>}
    </Modal>
  );
};

// ----- Reject modal -----
const ResumeRejectModal = ({ cand, onClose, onRejected }) => {
  const [mode, setMode] = React.useState('custom');
  const [note, setNote] = React.useState('');
  const [hint, setHint] = React.useState('');
  const [reason, setReason] = React.useState('skills_gap');
  const [sendTg, setSendTg] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const body = { reason, send_telegram: sendTg };
      if (mode === 'custom') body.note = note;
      else { body.use_ai_cheerup = true; body.custom_hint = hint; }
      await apiFetch(`/api/resume/candidates/${cand.code}/reject`, { json: body });
      onRejected?.();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Modal open={true} onClose={onClose} size="md" title="✕ REJECT CANDIDATE"
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CANCEL</button>
        <button className="btn-brutal action-btn" style={{ fontSize: 11, padding: '8px 14px', width: 'auto', background: 'var(--red)', color: '#fff' }} onClick={submit} disabled={busy}>{busy ? 'REJECTING...' : '✕ CONFIRM REJECT'}</button>
      </>}
    >
      <p className="small-meta" style={{ marginBottom: 10 }}>Reject <strong>{cand.name || cand.code}</strong>. Optionally send a note to your Telegram (so you can forward to the candidate).</p>
      <label className="field-label">REJECTION REASON</label>
      <select className="brutal-select" value={reason} onChange={e => setReason(e.target.value)}>
        <option value="skills_gap">Skills gap</option>
        <option value="experience_gap">Experience gap</option>
        <option value="location">Location mismatch</option>
        <option value="compensation">Compensation</option>
        <option value="cultural_fit">Cultural fit</option>
        <option value="other">Other</option>
      </select>

      <label className="field-label mt-14">MESSAGE</label>
      <div className="segmented-control" style={{ marginBottom: 8 }}>
        <button className={`seg-btn ${mode === 'custom' ? 'active' : ''}`} onClick={() => setMode('custom')}>WRITE CUSTOM NOTE</button>
        <button className={`seg-btn ${mode === 'ai' ? 'active' : ''}`} onClick={() => setMode('ai')}>✨ AI-GENERATED CHEER-UP</button>
      </div>
      {mode === 'custom' ? (
        <textarea className="brutal-select" value={note} onChange={e => setNote(e.target.value)} rows={5} placeholder="Personal note to the candidate (optional)..." style={{ fontFamily: 'var(--font-mono)', fontSize: 12, width: '100%' }} />
      ) : (
        <input className="brutal-select" value={hint} onChange={e => setHint(e.target.value)} placeholder="Optional: extra context for Groq (e.g. 'mention their open-source contribution')" />
      )}

      <div style={{ marginTop: 10 }}>
        <Toggle checked={sendTg} onChange={setSendTg} label="Send to Telegram" />
      </div>
      {err && <div className="warning-banner mt-14"><span>⚠</span><div>{err}</div></div>}
    </Modal>
  );
};

// ----- Add Note modal -----
const ResumeNoteModal = ({ cand, onClose, onSaved }) => {
  const [text, setText] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      await apiFetch(`/api/resume/candidates/${cand.code}/note`, { json: { text, author: 'RSD' } });
      onSaved?.();
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={true} onClose={onClose} size="sm" title="📝 ADD NOTE"
      footer={<>
        <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CANCEL</button>
        <button className="btn-brutal action-btn red" onClick={submit} disabled={busy || !text.trim()} style={{ fontSize: 11, padding: '8px 14px', width: 'auto' }}>{busy ? 'SAVING...' : 'SAVE'}</button>
      </>}
    >
      <textarea className="brutal-select" value={text} onChange={e => setText(e.target.value)} rows={6} placeholder="Internal note about this candidate..." style={{ fontFamily: 'var(--font-mono)', fontSize: 12, width: '100%' }} />
      {err && <div className="warning-banner mt-14"><span>⚠</span><div>{err}</div></div>}
    </Modal>
  );
};

// ----- Compare board -----
const ResumeCompareModal = ({ codes, job, onClose }) => {
  const [data, setData] = React.useState(null);
  React.useEffect(() => {
    apiFetch('/api/resume/candidates/compare', { json: { candidate_ids: codes } })
      .then(setData).catch(() => setData(null));
  }, [codes.join(',')]);
  if (!data) return <Modal open={true} onClose={onClose} size="lg" title="COMPARING..."><Skeleton h={300} /></Modal>;

  const cands = data.candidates || [];
  return (
    <Modal open={true} onClose={onClose} size="lg" title={`⚖ COMPARE · ${job?.code || ''} · ${cands.length} candidates`}
      footer={<button className="btn-brutal" onClick={onClose} style={{ fontSize: 11, padding: '8px 14px' }}>CLOSE</button>}
    >
      {data.llm_summary && (
        <div className="warning-banner" style={{ marginBottom: 14 }}>
          <span>✨</span>
          <div><strong>{data.llm_summary.headline}</strong></div>
        </div>
      )}

      <div className="compare-board">
        <div className="compare-header">
          <div></div>
          {cands.map(c => (
            <div key={c.code} className="compare-cand-cell">
              <Avatar name={c.name} size={32} />
              <div className="compare-cand-name">{c.name}</div>
              <div className="compare-cand-score" style={{ background: c.score >= 90 ? 'var(--green)' : c.score >= 75 ? 'var(--gold)' : 'var(--cyan)' }}>{Math.round(c.score)}</div>
            </div>
          ))}
        </div>

        <div className="compare-row">
          <div className="compare-label">Status</div>
          {cands.map(c => <div key={c.code} className="compare-cell"><Badge variant="default">{c.status}</Badge></div>)}
        </div>
        <div className="compare-row">
          <div className="compare-label">Experience</div>
          {cands.map(c => <div key={c.code} className="compare-cell">{c.experience_years} yrs</div>)}
        </div>
        <div className="compare-row">
          <div className="compare-label">Education</div>
          {cands.map(c => <div key={c.code} className="compare-cell">{c.education}</div>)}
        </div>
        <div className="compare-row">
          <div className="compare-label">Location</div>
          {cands.map(c => <div key={c.code} className="compare-cell">{c.location}</div>)}
        </div>

        <div className="section-divider mt-20"><span>SCORE PER DIMENSION</span></div>
        {data.dimension_grid.map(d => (
          <div key={d.dimension} className="compare-row">
            <div className="compare-label">{d.dimension}</div>
            {d.values.map((v, i) => (
              <div key={i} className="compare-cell">
                <div className="progress-bar" style={{ marginBottom: 2 }}><div className="progress-fill" style={{ width: `${v}%`, background: v >= 75 ? 'var(--green)' : v >= 50 ? 'var(--gold)' : 'var(--red)' }}></div></div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{v}</div>
              </div>
            ))}
          </div>
        ))}

        <div className="section-divider mt-20"><span>SKILL OVERLAP</span></div>
        <div className="skill-matrix">
          {data.skill_matrix.map(s => (
            <div key={s.skill} className="sm-row">
              <div className="sm-skill">{s.skill}</div>
              {s.coverage.map((has, i) => (
                <div key={i} className={`sm-cell ${has ? 'has' : ''}`}>{has ? '✓' : '·'}</div>
              ))}
            </div>
          ))}
        </div>

        {data.llm_summary?.callouts && (
          <>
            <div className="section-divider mt-20"><span>STRENGTHS / WEAKNESSES</span></div>
            <div className="analysis-cards">
              {data.llm_summary.callouts.map((c, i) => (
                <div key={i} className="analysis-card">
                  <span className="ac-icon" style={{ color: 'var(--gold)' }}>★</span>
                  <div>
                    <strong>{c.candidate}</strong>
                    <p style={{ marginTop: 4 }}><strong style={{ color: 'var(--green)' }}>+ </strong>{c.strength}</p>
                    <p><strong style={{ color: 'var(--red)' }}>– </strong>{c.weakness}</p>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};

// ============================================================
// 4. ANALYTICS — real-time aggregates
// ============================================================
const ResumeAnalytics = ({ refreshTick }) => {
  const [period, setPeriod] = React.useState('30d');
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [tick, setTick] = React.useState(0);

  React.useEffect(() => {
    setLoading(true);
    Promise.all([
      apiFetch('/api/resume/analytics/kpis',          { params: { period } }),
      apiFetch('/api/resume/analytics/funnel',        { params: { period } }),
      apiFetch('/api/resume/analytics/sources',        { params: { period } }),
      apiFetch('/api/resume/analytics/source-quality', { params: { period } }),
      apiFetch('/api/resume/analytics/diversity',      { params: { period } }),
      apiFetch('/api/resume/analytics/apps-per-week',  { params: { weeks: 8 } }),
      apiFetch('/api/resume/analytics/top-skills',     { params: { period, limit: 8 } }),
      apiFetch('/api/resume/analytics/jobs-overview',  { params: { limit: 5 } }),
    ])
      .then(([k, f, s, sq, d, w, ts, jo]) => setData({ kpis: k, funnel: f, sources: s, source_quality: sq, diversity: d, weeks: w, top_skills: ts, jobs_overview: jo }))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [period, tick, refreshTick]);

  if (loading || !data) return <div className="tab-pane"><Skeleton h={120} /><div style={{ height: 12 }} /><Skeleton h={300} /></div>;
  const { kpis, funnel, sources, source_quality, diversity, weeks, top_skills, jobs_overview } = data;

  return (
    <div className="tab-pane">
      <div className="toolbar">
        <SegmentedControl options={['7d', '14d', '30d', '90d']} value={period} onChange={setPeriod} accent="var(--red)" />
        <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }} onClick={() => setTick(t => t + 1)}>↻ REFRESH</button>
      </div>

      <div className="kpi-grid-4">
        <KPICard label={`TIME TO HIRE (${period.toUpperCase()})`} value={`${kpis.time_to_hire.value}d`} color="var(--red)" data={[kpis.time_to_hire.value]} delta="" deltaDir="flat" />
        <KPICard label="OFFER ACCEPT" value={`${kpis.offer_accept.value}%`} color="var(--green)" data={[kpis.offer_accept.value]} delta="" deltaDir="flat" />
        <KPICard label="COST PER HIRE" value={`₹${(kpis.cost_per_hire.value / 1000).toFixed(0)}k`} color="var(--gold)" data={[kpis.cost_per_hire.value]} delta="" deltaDir="flat" />
        <KPICard label="ACTIVE SCREENS" value={String(kpis.active_screens.value)} color="var(--cyan)" data={[kpis.active_screens.value]} delta="" deltaDir="flat" />
      </div>

      <div className="widgets-grid mt-20">
        <div className="widget-card">
          <div className="widget-title">HIRING FUNNEL ({period.toUpperCase()})</div>
          <FunnelChart stages={funnel.stages} accent="var(--red)" />
        </div>
        <div className="widget-card">
          <div className="widget-title">SOURCE EFFECTIVENESS · QUALITY BY CHANNEL</div>
          {sources.total === 0 ? <EmptyState icon="·" description="No applications in period" /> :
            <SourceEffectivenessPanel sources={sources} sourceQuality={source_quality} />}
        </div>
      </div>

      <div className="widgets-grid mt-20">
        <div className="widget-card">
          <div className="widget-title">DIVERSITY PIPELINE (post-redaction aggregate)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <DiversityBar label="GENDER (APPLIED)" data={diversity.gender_applied} colorMap={{ female: 'var(--red)', male: 'var(--cyan)', unknown: '#888' }} />
            <DiversityBar label="GENDER (HIRED)"   data={diversity.gender_hired}   colorMap={{ female: 'var(--red)', male: 'var(--cyan)', unknown: '#888' }} />
            <DiversityBar label="EXPERIENCE BANDS" data={diversity.experience_bands} colorMap={{ '<2y': 'var(--green)', '2-5y': 'var(--gold)', '5-10y': 'var(--cyan)', '10y+': 'var(--red)' }} />
          </div>
        </div>
        <MiniChart title="APPLICATIONS PER WEEK (8w)" data={weeks.data} color="var(--red)" labels={['8w ago', 'NOW']} />
      </div>

      <div className="widgets-grid mt-20">
        <div className="widget-card">
          <div className="widget-title">TOP SKILLS IN PIPELINE</div>
          {top_skills.skills.length === 0 ? <EmptyState icon="·" description="No skills extracted yet" /> :
            <div className="leaderboard">
              {top_skills.skills.map((s, i) => (
                <div key={s.skill} className="leaderboard-row">
                  <span className="leaderboard-rank">#{i + 1}</span>
                  <span className="leaderboard-name">{s.skill}</span>
                  <span className="leaderboard-count">{s.count}</span>
                </div>
              ))}
            </div>
          }
        </div>
        <div className="widget-card">
          <div className="widget-title">JOBS OVERVIEW (top 5)</div>
          <div className="leaderboard">
            {jobs_overview.jobs.map((j, i) => (
              <div key={j.code} className="leaderboard-row">
                <span className="leaderboard-rank">#{i + 1}</span>
                <span className="leaderboard-name">{j.title}</span>
                <span className="leaderboard-count">{j.applicants}/{j.shortlisted}/{j.recruited}</span>
              </div>
            ))}
            <div className="small-meta" style={{ marginTop: 8 }}>format: applicants / shortlisted / recruited</div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ----- Source Effectiveness panel: donut + per-source quality grid + leader callouts -----
const SourceEffectivenessPanel = ({ sources, sourceQuality }) => {
  if (!sources || sources.total === 0) return null;
  const sq = sourceQuality?.sources || [];
  const palette = { Referral: 'var(--green)', LinkedIn: 'var(--cyan)', Naukri: 'var(--gold)', Direct: 'var(--red)', Other: '#888' };
  return (
    <div>
      <Donut segments={sources.segments} centerValue={String(sources.total)} centerLabel="APPLICATIONS" />

      <div className="section-divider mt-20"><span>QUALITY BY SOURCE</span><span className="small-meta">live · score · convert · time</span></div>

      {sq.length === 0 ? (
        <div className="small-meta" style={{ padding: 14, textAlign: 'center' }}>No source data yet</div>
      ) : (
        <div className="src-grid">
          {sq.map((s) => (
            <div key={s.name} className="src-row">
              <div className="src-name">
                <span className="src-dot" style={{ background: palette[s.name] || '#888' }}></span>
                {s.name}
              </div>
              <div className="src-apps">{s.applications} <span className="src-apps-l">apps</span></div>
              <div className="src-bar-wrap" title={`${s.shortlisted}/${s.applications} shortlisted`}>
                <div className="src-bar"><div className="src-bar-fill" style={{ width: `${s.shortlist_rate}%`, background: palette[s.name] || '#888' }}></div></div>
                <span className="src-bar-pct">{s.shortlist_rate}%</span>
              </div>
              <div className="src-score" title="Avg final match score" style={{ background: s.avg_score >= 80 ? 'var(--green)' : s.avg_score >= 60 ? 'var(--gold)' : s.avg_score > 0 ? 'var(--red)' : '#ddd' }}>
                {s.avg_score > 0 ? Math.round(s.avg_score) : '—'}
              </div>
              <div className="src-t2h" title="Avg time-to-hire (days)">
                {s.avg_time_to_hire_days != null ? `${Math.round(s.avg_time_to_hire_days)}d` : '—'}
              </div>
            </div>
          ))}
        </div>
      )}

      {(sourceQuality?.quality_leader || sourceQuality?.best_converter || sourceQuality?.fastest_source) && (
        <div className="src-callouts">
          {sourceQuality.quality_leader && (
            <div className="src-callout">
              <span className="src-callout-icon">★</span>
              <div>
                <div className="src-callout-l">QUALITY LEADER</div>
                <div className="src-callout-v">{sourceQuality.quality_leader}</div>
              </div>
            </div>
          )}
          {sourceQuality.best_converter && (
            <div className="src-callout">
              <span className="src-callout-icon" style={{ color: 'var(--cyan)' }}>↗</span>
              <div>
                <div className="src-callout-l">BEST CONVERSION</div>
                <div className="src-callout-v">{sourceQuality.best_converter}</div>
              </div>
            </div>
          )}
          {sourceQuality.fastest_source && (
            <div className="src-callout">
              <span className="src-callout-icon" style={{ color: 'var(--red)' }}>⚡</span>
              <div>
                <div className="src-callout-l">FASTEST TO HIRE</div>
                <div className="src-callout-v">{sourceQuality.fastest_source}</div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const DiversityBar = ({ label, data, colorMap }) => {
  const entries = Object.entries(data || {});
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const right = entries.map(([k, v]) => `${Math.round(v)}% ${k}`).join(' · ');
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontFamily: 'var(--font-mono)', marginBottom: 4 }}>
        <span>{label}</span><span>{total ? right : 'no data'}</span>
      </div>
      <div style={{ display: 'flex', height: 14, border: '2px solid #000' }}>
        {total ? entries.map(([k, v]) => (
          <div key={k} style={{ width: `${v}%`, background: colorMap[k] || '#888' }} title={`${k}: ${v}%`}></div>
        )) : <div style={{ width: '100%', background: '#eee' }}></div>}
      </div>
    </div>
  );
};

// ============================================================
// 5. SETTINGS — per-job weights + bias + threshold + rescore + Telegram
// ============================================================
const ResumeSettings = ({ refreshTick, bumpRefresh }) => {
  const [jobs, setJobs] = React.useState([]);
  const [selectedJob, setSelectedJob] = React.useState(null);
  const [weights, setWeights] = React.useState(null);
  const [biasFlags, setBiasFlags] = React.useState(null);
  const [threshold, setThreshold] = React.useState(70);
  const [busy, setBusy] = React.useState(false);
  const [tg, setTg] = React.useState(null);
  const [tgBusy, setTgBusy] = React.useState(false);
  const [toast, toastHost] = useToast();

  React.useEffect(() => {
    apiFetch('/api/resume/jobs').then(r => {
      setJobs(r.jobs || []);
      if (!selectedJob && r.jobs?.length) setSelectedJob(r.jobs[0]);
    });
    apiFetch('/api/resume/telegram/status').then(setTg).catch(() => {});
  }, [refreshTick]);

  React.useEffect(() => {
    if (!selectedJob) return;
    setWeights(selectedJob.scoring_weights || { skills: 40, experience: 25, education: 15, location: 10, culture_fit: 10 });
    setBiasFlags(selectedJob.bias_flags || { redact_gender: true, redact_age: true, redact_location: false, redact_name: true });
    setThreshold(selectedJob.auto_shortlist_threshold || 70);
  }, [selectedJob]);

  const totalW = weights ? Object.values(weights).reduce((s, v) => s + v, 0) : 0;

  const save = async () => {
    if (totalW !== 100) { toast(`Weights must sum to 100 (currently ${totalW})`, 'error'); return; }
    setBusy(true);
    try {
      await apiFetch(`/api/resume/jobs/${selectedJob.code}/settings`, {
        method: 'PUT',
        json: { scoring_weights: weights, bias_flags: biasFlags, auto_shortlist_threshold: threshold },
      });
      toast(`Saved + re-scoring all ${selectedJob.applicants} candidates for ${selectedJob.code}`, 'success');
      bumpRefresh?.();
      // Refetch
      const r = await apiFetch(`/api/resume/jobs/${selectedJob.code}`);
      setSelectedJob(r);
    } catch (e) { toast(e.message, 'error'); }
    finally { setBusy(false); }
  };

  const discoverTg = async () => {
    setTgBusy(true);
    try {
      const r = await apiFetch('/api/resume/telegram/discover', { json: {} });
      const status = await apiFetch('/api/resume/telegram/status');
      setTg(status);
      toast(`Discovered ${r.newly_added || 0} new chat(s) — ${status.chats?.length || 0} total`, 'success');
    } catch (e) { toast(e.message, 'error'); }
    finally { setTgBusy(false); }
  };

  const testTg = async () => {
    try {
      const r = await apiFetch('/api/resume/telegram/test', { json: {} });
      toast(r.ok ? `Sent to ${r.delivered} chat(s)` : `Failed: ${r.error}`, r.ok ? 'success' : 'error');
    } catch (e) { toast(e.message, 'error'); }
  };

  if (!jobs.length) return <div className="tab-pane"><EmptyState icon="📋" title="NO JOBS" description="Create a job first to configure its settings." /></div>;

  return (
    <div className="tab-pane">
      <div className="job-pills">
        {jobs.map(j => (
          <button key={j.id} className={`job-pill ${selectedJob?.id === j.id ? 'active' : ''}`} onClick={() => setSelectedJob(j)}>
            <span className="jp-title">{j.title}</span>
            <span className="jp-meta">{j.code}</span>
          </button>
        ))}
      </div>

      {selectedJob && weights && biasFlags && (
        <div className="widgets-grid mt-14">
          <div className="widget-card">
            <div className="widget-title">SCORING WEIGHTS · {selectedJob.code}</div>
            <p className="small-meta" style={{ marginBottom: 14 }}>Adjust how each dimension contributes to the overall match score for THIS job. Must sum to 100. Saving re-scores every existing candidate.</p>
            {Object.entries(weights).map(([k, v]) => (
              <div key={k} className="weight-row">
                <span className="weight-label">{k.replace(/_/g, ' ').toUpperCase()}</span>
                <input type="range" min="0" max="80" value={v} onChange={e => setWeights(w => ({ ...w, [k]: +e.target.value }))} className="brutal-slider" />
                <span className="weight-val">{v}%</span>
              </div>
            ))}
            <div className="weight-total">
              TOTAL: {totalW}%
              {totalW !== 100 && <span style={{ marginLeft: 8 }}><Badge variant="red">⚠ MUST EQUAL 100</Badge></span>}
            </div>

            <label className="field-label mt-20">AUTO-SHORTLIST THRESHOLD</label>
            <div className="weight-row">
              <span className="weight-label">SCORE ≥</span>
              <input type="range" min="0" max="100" value={threshold} onChange={e => setThreshold(+e.target.value)} className="brutal-slider" />
              <span className="weight-val">{threshold}</span>
            </div>
            <p className="small-meta">Candidates scoring ≥ this auto-go to SHORTLISTED. Below → REJECTED.</p>

            <button className="btn-brutal action-btn red mt-20" onClick={save} disabled={busy || totalW !== 100} style={{ width: 'auto', fontSize: 11, padding: '8px 16px' }}>{busy ? 'SAVING + RE-SCORING...' : '💾 SAVE & RE-SCORE'}</button>
          </div>

          <div className="widget-card">
            <div className="widget-title">BIAS REDACTION · {selectedJob.code}</div>
            <p className="small-meta" style={{ marginBottom: 14 }}>Strip these attributes from the text BEFORE scoring. Logged in audit trail with each candidate's snapshot.</p>
            {Object.entries(biasFlags).map(([k, v]) => (
              <div key={k} style={{ padding: '10px 0', borderBottom: '1px solid #eee' }}>
                <Toggle checked={v} onChange={val => setBiasFlags(b => ({ ...b, [k]: val }))} label={k.replace('redact_', 'Redact ')} />
              </div>
            ))}
            <div className="warning-banner mt-14">
              <span>ℹ</span>
              <div>The full <strong>scoring config snapshot</strong> (weights + flags + threshold) is stored on every candidate at scoring time, for audit + reproducibility.</div>
            </div>
          </div>

          <div className="widget-card" style={{ gridColumn: 'span 2' }}>
            <div className="widget-title">TELEGRAM NOTIFICATIONS</div>
            {tg ? (
              <>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 10 }}>
                  <span className={`status-pill ${tg.bot_ok ? 'on' : 'off'}`} style={{ background: tg.bot_ok ? 'var(--green)' : 'var(--red)', color: '#fff' }}>
                    🤖 BOT {tg.bot_ok ? 'CONNECTED' : 'OFFLINE'}
                  </span>
                  {tg.bot_username && <span className="small-meta">@{tg.bot_username} · "{tg.bot_first_name}"</span>}
                </div>
                {tg.bot_error && <div className="warning-banner mt-14"><span>⚠</span><div>{tg.bot_error}</div></div>}
                <div className="small-meta" style={{ marginBottom: 10 }}>Connected chats: <strong>{tg.chats?.length || 0}</strong></div>
                {(tg.chats || []).map(c => (
                  <div key={c.chat_id} style={{ padding: '6px 10px', border: '2px solid #000', background: '#fff', marginBottom: 6, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                    <strong>{c.title}</strong> · chat_id={c.chat_id} · {c.chat_type}
                  </div>
                ))}
                <div className="action-row mt-14">
                  <a className="btn-brutal" href={tg.bot_username ? `https://t.me/${tg.bot_username}` : '#'} target="_blank" rel="noreferrer" style={{ fontSize: 11, padding: '8px 14px', textDecoration: 'none' }}>↗ OPEN BOT IN TELEGRAM</a>
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }} onClick={discoverTg} disabled={tgBusy}>{tgBusy ? 'DISCOVERING...' : '🔍 DISCOVER NEW CHATS'}</button>
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }} onClick={testTg}>📤 SEND TEST MESSAGE</button>
                </div>
                <p className="small-meta" style={{ marginTop: 10 }}>How to add a new chat: open the bot in Telegram → send /start → click DISCOVER above.</p>
              </>
            ) : <Skeleton h={120} />}
          </div>
        </div>
      )}
      {toastHost}
    </div>
  );
};

/* ======================================================================
   GOVERNMENT MODULE 3 — TRAFFIC VIOLATIONS
   Tabs: Live Feed · Incidents · Challans · Offenders · Analytics
   ====================================================================== */
// Government-only auth headers for /api/traffic-violations/* (access_control gates these).
const TRAFFIC_AUTH = { headers: { 'x-user-role': 'government_official', 'x-user-id': 'rsd' } };

// ====================================================================
// Phase 1+ — System Status Bar (sits below SubPageHeader, above Tabs)
// Shows Groq / Supabase / OCR / Telegram readiness as colored pills.
// ====================================================================
const SystemStatusBar = () => {
  const [s, setS] = React.useState(null);
  React.useEffect(() => {
    let alive = true;
    const load = () => apiFetch('/api/traffic-violations/system-status', TRAFFIC_AUTH)
      .then(d => { if (alive) setS(d); }).catch(() => {});
    load();
    const t = setInterval(load, 60000);  // refresh every 60s
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!s) return null;
  const pill = (label, ok, sub) => (
    <span className="tv-status-pill" style={{ borderColor: ok ? 'var(--green)' : 'var(--red)' }}>
      <span className="tv-status-dot" style={{ background: ok ? 'var(--green)' : 'var(--red)' }} />
      <span className="tv-status-label">{label}</span>
      {sub && <span className="tv-status-sub">{sub}</span>}
    </span>
  );
  return (
    <div className="tv-system-status">
      {pill('SUPABASE', s.supabase?.ok)}
      {pill('GROQ', s.groq?.ok, s.groq?.model)}
      {pill('OCR', s.ocr?.ok)}
      {pill('TELEGRAM', s.telegram?.ok)}
      <span className="tv-status-env">env: {s.env}</span>
    </div>
  );
};

// ====================================================================
// Phase 1+ — Camera Health Strip (top of Live Feed)
// ====================================================================
const CameraHealthStrip = () => {
  const [h, setH] = React.useState(null);
  React.useEffect(() => {
    let alive = true;
    const load = () => apiFetch('/api/traffic-violations/camera-health', TRAFFIC_AUTH)
      .then(d => { if (alive) setH(d); }).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!h) return null;
  const ago = (iso) => {
    if (!iso) return 'never';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return `${Math.round(s)}s ago`;
    if (s < 3600) return `${Math.round(s/60)}m ago`;
    if (s < 86400) return `${Math.round(s/3600)}h ago`;
    return `${Math.round(s/86400)}d ago`;
  };
  return (
    <div className="tv-health-strip">
      <div className="tv-health-block">
        <div className="tv-health-num">{h.total}</div>
        <div className="tv-health-lbl">TOTAL CAMERAS</div>
      </div>
      <div className="tv-health-block">
        <div className="tv-health-num" style={{ color: 'var(--green)' }}>{h.online_pct}%</div>
        <div className="tv-health-lbl">ONLINE ({h.online}/{h.total})</div>
      </div>
      <div className="tv-health-block">
        <div className="tv-health-num" style={{ color: 'var(--gold)' }}>{h.degraded}</div>
        <div className="tv-health-lbl">DEGRADED</div>
      </div>
      <div className="tv-health-block">
        <div className="tv-health-num" style={{ color: 'var(--red)' }}>{h.offline}</div>
        <div className="tv-health-lbl">OFFLINE</div>
      </div>
      <div className="tv-health-block">
        <div className="tv-health-num">{h.avg_fps}</div>
        <div className="tv-health-lbl">AVG FPS</div>
      </div>
      <div className="tv-health-block" style={{ flex: 2 }}>
        <div className="tv-health-num" style={{ fontSize: 16 }}>
          {h.last_detection
            ? `${(h.last_detection.violation_type || '').replaceAll('_',' ').toUpperCase()} · ${h.last_detection.plate || '—'}`
            : 'NONE'}
        </div>
        <div className="tv-health-lbl">LAST DETECTION · {ago(h.last_detection?.detected_at)}</div>
      </div>
    </div>
  );
};

// ====================================================================
// Phase 1+ — Mini-Map widget (Live Feed)
// Plots all cameras geographically. Click a dot → focus camera.
// ====================================================================
const TrafficMiniMap = ({ cameras, onSelect }) => {
  if (!cameras || cameras.length === 0) return null;
  const lats = cameras.map(c => c.lat).filter(v => typeof v === 'number');
  const lngs = cameras.map(c => c.lng).filter(v => typeof v === 'number');
  if (lats.length === 0) return null;
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const pad = 0.005;
  const W = 100, H = 100;  // viewBox units
  const x = (lng) => ((lng - (minLng - pad)) / ((maxLng + pad) - (minLng - pad))) * W;
  const y = (lat) => H - ((lat - (minLat - pad)) / ((maxLat + pad) - (minLat - pad))) * H;  // invert Y
  const dotColor = (status) => status === 'active' ? 'var(--green)' : status === 'degraded' ? 'var(--gold)' : 'var(--red)';
  return (
    <div className="tv-mini-map">
      <div className="widget-title" style={{ marginBottom: 6 }}>CAMERA GEO MAP · {cameras.length} POINTS</div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 180, background: '#0a0a0a', border: '3px solid #000' }}>
        {/* faint grid */}
        {[20,40,60,80].map(v => <line key={`gh${v}`} x1="0" y1={v} x2={W} y2={v} stroke="#222" strokeWidth="0.2" />)}
        {[20,40,60,80].map(v => <line key={`gv${v}`} x1={v} y1="0" x2={v} y2={H} stroke="#222" strokeWidth="0.2" />)}
        {/* camera dots */}
        {cameras.filter(c => typeof c.lat === 'number' && typeof c.lng === 'number').map(c => (
          <g key={c.id} style={{ cursor: 'pointer' }} onClick={() => onSelect && onSelect(c)}>
            <circle cx={x(c.lng)} cy={y(c.lat)} r={c.status === 'active' ? 2 : 1.5} fill={dotColor(c.status)} opacity={c.status === 'offline' ? 0.4 : 0.9} />
            {c.status === 'active' && (
              <circle cx={x(c.lng)} cy={y(c.lat)} r="3.5" fill="none" stroke={dotColor(c.status)} strokeWidth="0.3" opacity="0.5">
                <animate attributeName="r" values="2;4;2" dur="2s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.6;0;0.6" dur="2s" repeatCount="indefinite" />
              </circle>
            )}
          </g>
        ))}
      </svg>
    </div>
  );
};

// ====================================================================
// Phase 2 — Upload Footage modal
// User picks a video → POST /upload → poll /jobs/{id} every 2s until done.
// On complete: switch to Incidents tab, refresh data.
// ====================================================================
const UploadFootageModal = ({ open, onClose, onComplete }) => {
  const fileRef = React.useRef(null);
  const [stage, setStage] = React.useState('idle');   // idle | uploading | processing | done | error
  const [file, setFile] = React.useState(null);
  const [job, setJob] = React.useState(null);
  const [error, setError] = React.useState('');
  const pollRef = React.useRef(null);

  React.useEffect(() => {
    if (!open) {
      setStage('idle'); setFile(null); setJob(null); setError('');
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }
  }, [open]);

  const pickFile = () => fileRef.current?.click();
  const onPick = (e) => { setFile(e.target.files?.[0] || null); setError(''); };

  const submit = async () => {
    if (!file) return;
    setStage('uploading'); setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('types', 'no_helmet,speeding,illegal_parking');
      const ack = await apiFetch('/api/traffic-violations/upload', { ...TRAFFIC_AUTH, form: fd });
      setJob(ack);
      setStage('processing');
      // start polling
      pollRef.current = setInterval(async () => {
        try {
          const s = await apiFetch(`/api/traffic-violations/jobs/${ack.job_id}`, TRAFFIC_AUTH);
          setJob(s);
          if (s.status === 'complete') {
            clearInterval(pollRef.current); pollRef.current = null;
            setStage('done');
            onComplete && onComplete(s);
          } else if (s.status === 'error') {
            clearInterval(pollRef.current); pollRef.current = null;
            setStage('error');
            setError(s.error || 'Pipeline failed');
          }
        } catch (e) {
          // transient — keep polling
        }
      }, 2000);
    } catch (e) {
      setStage('error');
      setError(e.message || 'Upload failed');
    }
  };

  if (!open) return null;
  const pct = job && job.total_frames > 0
    ? Math.round((job.frames_processed / job.total_frames) * 100)
    : 0;

  return (
    <div className="tv-modal-backdrop" onClick={stage === 'processing' || stage === 'uploading' ? undefined : onClose}>
      <div className="tv-modal" style={{ maxWidth: 640 }} onClick={e => e.stopPropagation()}>
        <div className="tv-modal-head">
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: 1 }}>UPLOAD FOOTAGE</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.6 }}>
              YOLOv8 + DeepSORT + OCR Space · Detects no-helmet, speeding, illegal-parking
            </div>
          </div>
          <button className="btn-brutal" onClick={onClose}
            disabled={stage === 'uploading' || stage === 'processing'}
            style={{ fontSize: 10, padding: '4px 10px', marginLeft: 'auto' }}>✕ CLOSE</button>
        </div>
        <div style={{ padding: 24 }}>
          {stage === 'idle' && (
            <div style={{ textAlign: 'center' }}>
              <input ref={fileRef} type="file" accept="video/*" onChange={onPick} style={{ display: 'none' }} />
              <button className="btn-brutal action-btn cyan" onClick={pickFile} style={{ width: 'auto', padding: '12px 24px' }}>
                📁 CHOOSE VIDEO
              </button>
              {file && (
                <div style={{ marginTop: 14, fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                  Selected: <strong>{file.name}</strong> · {(file.size / (1024*1024)).toFixed(1)} MB
                </div>
              )}
              <div style={{ marginTop: 16, fontSize: 11, opacity: 0.55, fontFamily: 'var(--font-mono)' }}>
                Max 50 MB. MP4 / MOV / AVI / WebM.
              </div>
              {file && (
                <button className="btn-brutal action-btn" onClick={submit}
                  style={{ marginTop: 14, padding: '10px 22px', width: 'auto', background: 'var(--green)', color: '#000' }}>
                  ▶ START DETECTION
                </button>
              )}
            </div>
          )}
          {(stage === 'uploading' || stage === 'processing') && (
            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
                {stage === 'uploading' ? 'UPLOADING…' : 'RUNNING PIPELINE…'}
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.7, marginBottom: 12 }}>
                {job ? `Job ${job.job_id} · ${job.filename}` : ''}
              </div>
              <div className="progress-bar" style={{ height: 18, background: '#222', border: '2px solid #000' }}>
                <div className="progress-fill" style={{ width: `${pct}%`, background: 'var(--cyan)', height: '100%', transition: 'width 0.4s' }}></div>
              </div>
              <div style={{ marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.6 }}>
                {job && job.total_frames > 0
                  ? `Frame ${job.frames_processed} of ${job.total_frames} (${pct}%)`
                  : 'Initializing models — first detection can take ~10 s while YOLO loads…'}
              </div>
            </div>
          )}
          {stage === 'done' && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 36, marginBottom: 8 }}>✓</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700 }}>
                {job?.detection_count || 0} INCIDENT{(job?.detection_count || 0) === 1 ? '' : 'S'} CREATED
              </div>
              <div style={{ marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.6 }}>
                Switch to the Incidents tab to review.
              </div>
              <button className="btn-brutal action-btn cyan" onClick={onClose} style={{ marginTop: 16, padding: '10px 22px', width: 'auto' }}>
                ✓ DONE
              </button>
            </div>
          )}
          {stage === 'error' && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 36, color: 'var(--red)', marginBottom: 8 }}>✕</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--red)' }}>{error || 'Failed'}</div>
              <button className="btn-brutal" onClick={() => setStage('idle')} style={{ marginTop: 14 }}>RETRY</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const TrafficViolations = ({ onBack }) => {
  const [tab, setTab] = React.useState('live');
  const [hdr, setHdr] = React.useState({ pipeline: 'YOLOv8 + DEEPSORT + CRNN OCR', camera_count: 0, detections_today: 0 });
  const [pendingCount, setPendingCount] = React.useState(0);
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [refreshKey, setRefreshKey] = React.useState(0);

  React.useEffect(() => {
    apiFetch('/api/traffic-violations/header-stats', TRAFFIC_AUTH).then(setHdr).catch(() => {});
    apiFetch('/api/traffic-violations/incidents', { ...TRAFFIC_AUTH, params: { status: 'pending', limit: 200 } })
      .then(d => setPendingCount(d.total || 0)).catch(() => {});
  }, [refreshKey]);

  const onUploadComplete = () => {
    setRefreshKey(k => k + 1);
    setTab('incidents');
  };

  const tabs = [
    { key: 'live',      label: 'LIVE FEED' },
    { key: 'incidents', label: 'INCIDENTS',  badge: pendingCount },
    { key: 'challans',  label: 'CHALLANS' },
    { key: 'offenders', label: 'REPEAT OFFENDERS' },
    { key: 'analytics', label: 'ANALYTICS' },
    { key: 'settings',  label: 'SETTINGS' },
  ];
  return (
    <div className="subpage fade-in">
      <SubPageHeader
        title="TRAFFIC VIOLATIONS"
        gatewayId="GATEWAY_03"
        subtitle={`${hdr.pipeline} · ${hdr.camera_count} CAMERAS · ${hdr.detections_today} DETECTIONS TODAY`}
        accentColor="var(--cyan)"
        onBack={onBack}
        actions={
          <button
            className="btn-brutal action-btn cyan"
            onClick={() => setUploadOpen(true)}
            style={{ padding: '8px 16px', fontSize: 12, width: 'auto' }}
          >⬆ UPLOAD FOOTAGE</button>
        }
      />
      <UploadFootageModal open={uploadOpen} onClose={() => setUploadOpen(false)} onComplete={onUploadComplete} />
      <SystemStatusBar />
      <Tabs tabs={tabs} active={tab} onChange={setTab} accent="var(--cyan)" />
      {tab === 'live'      && <TrafficLive />}
      {tab === 'incidents' && <TrafficIncidents />}
      {tab === 'challans'  && <TrafficChallans />}
      {tab === 'offenders' && <TrafficOffenders />}
      {tab === 'analytics' && <TrafficAnalytics />}
      {tab === 'settings'  && <TrafficSettings />}
    </div>
  );
};

// ====================================================================
// Phase 2 — CameraTile component
// Priority:
//   1) snapshot (real Singapore data.gov.sg traffic-image JPG, refreshed every 30s)
//   2) HLS (.m3u8) via hls.js
//   3) MP4/WebM via native <video>
//   4) noise placeholder
// ====================================================================
// Bbox class → colour
const TV_CLS_COLOR = {
  car:        'var(--cyan)',
  truck:      'var(--cyan)',
  bus:        'var(--cyan)',
  motorcycle: 'var(--red)',
  bicycle:    'var(--gold)',
  person:     'var(--gold)',
};

// Loop-video tracks cache (one fetch per loop_id shared by all tiles)
const TV_LOOP_TRACKS_CACHE = new Map();   // loop_id -> Promise<{ frames, fps, ... }>
const TV_LOOP_TRACKS_DATA = new Map();    // loop_id -> resolved data (sync access)
function tvLoadTracks(loop_id, tracks_url) {
  if (TV_LOOP_TRACKS_CACHE.has(loop_id)) return TV_LOOP_TRACKS_CACHE.get(loop_id);
  const API_BASE_LOCAL = (typeof API_BASE !== 'undefined' && API_BASE) || '';
  const url = tracks_url.startsWith('http') ? tracks_url : `${API_BASE_LOCAL}${tracks_url}`;
  const p = fetch(url).then(r => r.json()).then(d => { TV_LOOP_TRACKS_DATA.set(loop_id, d); return d; });
  TV_LOOP_TRACKS_CACHE.set(loop_id, p);
  return p;
}

const CameraTile = ({ cam, index, snapshot, detections, violationLabels = [] }) => {
  const videoRef = React.useRef(null);
  const hlsRef = React.useRef(null);
  const [playing, setPlaying] = React.useState(false);
  const [err, setErr] = React.useState(false);
  const [imgTs, setImgTs] = React.useState(() => Date.now());

  const url = cam.rtsp_url || '';
  const isHls = /\.m3u8(\?|$)/i.test(url);
  const isMp4 = /\.(mp4|webm|mov)(\?|$)/i.test(url);
  const loop = snapshot?.loop;                                 // continuous-motion video assigned by backend
  const hasLoop = !!loop?.video_url;
  const hasSnapshot = !hasLoop && !!snapshot?.image_url;
  const hasVideo = !hasSnapshot && !hasLoop && (isHls || isMp4);
  const hasSource = hasLoop || hasSnapshot || hasVideo;

  // For the loop-video path, bboxes come from the pre-computed tracks JSON
  // synced to video.currentTime. We keep them in state and update via rAF.
  const [loopBoxes, setLoopBoxes] = React.useState([]);
  const boxes = hasLoop ? loopBoxes : (Array.isArray(detections) ? detections : []);

  // Snapshot refresh: bump cache-buster every 10s so the <img> re-fetches.
  React.useEffect(() => {
    if (!hasSnapshot) return;
    const t = setInterval(() => setImgTs(Date.now()), 10000);
    return () => clearInterval(t);
  }, [hasSnapshot]);

  // Loop video: load tracks JSON once, sync bbox overlay to playback via rAF
  React.useEffect(() => {
    if (!hasLoop) return;
    let rafId = 0;
    let cancelled = false;
    let tracksData = TV_LOOP_TRACKS_DATA.get(loop.loop_id) || null;
    const start = () => {
      const video = videoRef.current;
      if (!video) return;
      const tick = () => {
        if (cancelled) return;
        if (tracksData && video.duration > 0) {
          const frameIdx = Math.round(video.currentTime * (tracksData.fps || 30));
          const step = tracksData.frame_step || 1;
          // find nearest pre-computed frame (rounded down to multiple of frame_step)
          const key = Math.floor(frameIdx / step) * step;
          const b = tracksData.frames?.[key] || tracksData.frames?.[String(key)] || [];
          setLoopBoxes(b);
        }
        rafId = requestAnimationFrame(tick);
      };
      rafId = requestAnimationFrame(tick);
    };
    if (tracksData) {
      start();
    } else {
      tvLoadTracks(loop.loop_id, loop.tracks_url).then((d) => {
        if (cancelled) return;
        tracksData = d;
        start();
      }).catch(() => {});
    }
    return () => { cancelled = true; if (rafId) cancelAnimationFrame(rafId); };
  }, [hasLoop, loop?.loop_id, loop?.tracks_url]);

  React.useEffect(() => {
    if (!hasVideo) return;
    const video = videoRef.current;
    if (!video) return;

    const onPlaying = () => { setPlaying(true); setErr(false); };
    const onError = () => { setErr(true); setPlaying(false); };
    video.addEventListener('playing', onPlaying);
    video.addEventListener('error', onError);

    if (isHls) {
      // Native HLS (Safari)
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = url;
        video.play().catch(() => {});
      } else if (window.Hls && window.Hls.isSupported()) {
        const hls = new window.Hls({ maxBufferLength: 8, lowLatencyMode: false });
        hlsRef.current = hls;
        hls.loadSource(url);
        hls.attachMedia(video);
        hls.on(window.Hls.Events.ERROR, (_e, data) => {
          if (data.fatal) setErr(true);
        });
        video.play().catch(() => {});
      } else {
        setErr(true);
      }
    } else if (isMp4) {
      video.src = url;
      video.play().catch(() => {});
    }
    return () => {
      video.removeEventListener('playing', onPlaying);
      video.removeEventListener('error', onError);
      if (hlsRef.current) { try { hlsRef.current.destroy(); } catch {} hlsRef.current = null; }
    };
  }, [url, isHls, isMp4, hasVideo]);

  return (
    <div className="camera-tile" style={{ animationDelay: `${index * 0.04}s` }}>
      <div className="cam-feed">
        {hasLoop ? (
          <>
            <video
              ref={videoRef}
              src={(API_BASE || '') + loop.video_url}
              muted
              playsInline
              autoPlay
              loop
              onLoadedMetadata={(e) => {
                // Stagger start across tiles so adjacent ones don't look identical
                const off = Math.min(loop.start_offset || 0, Math.max(0, (e.target.duration || 1) - 0.1));
                if (off > 0) e.target.currentTime = off;
                setPlaying(true); setErr(false);
              }}
              onError={() => setErr(true)}
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', background: '#000' }}
            />
            {/* synced YOLO bbox overlay */}
            {boxes.length > 0 && (
              <svg viewBox="0 0 1 1" preserveAspectRatio="none"
                   style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
                {boxes.map((b, i) => (
                  <g key={b.track_id != null ? `t${b.track_id}` : `i${i}`}>
                    <rect x={b.x} y={b.y} width={b.w} height={b.h}
                          fill="none" stroke={TV_CLS_COLOR[b.cls] || 'var(--green)'} strokeWidth="0.005"
                          style={{ animation: 'tvBoxPulse 1.6s ease-in-out infinite' }} />
                    <text x={b.x + 0.005} y={Math.max(0.025, b.y - 0.005)}
                          fill={TV_CLS_COLOR[b.cls] || 'var(--green)'} fontSize="0.035"
                          fontFamily="var(--font-mono, monospace)" fontWeight="700"
                          style={{ paintOrder: 'stroke', stroke: '#000', strokeWidth: '0.005' }}>
                      T{b.track_id} {b.cls.toUpperCase()} · {Math.round(b.conf * 100)}%
                    </text>
                  </g>
                ))}
              </svg>
            )}
          </>
        ) : hasSnapshot ? (
          <>
            <img
              src={`${snapshot.image_url}${snapshot.image_url.includes('?') ? '&' : '?'}t=${imgTs}`}
              alt={cam.name}
              onError={() => setErr(true)}
              onLoad={() => { setPlaying(true); setErr(false); }}
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', background: '#000', animation: 'tvKenBurns 12s ease-in-out infinite alternate' }}
            />
            {/* YOLO detection overlay — boxes are 0..1 normalized */}
            {boxes.length > 0 && (
              <svg
                viewBox="0 0 1 1"
                preserveAspectRatio="none"
                style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
              >
                {boxes.map((b, i) => (
                  <g key={b.track_id != null ? `t${b.track_id}` : `i${i}`}>
                    <rect
                      x={b.x} y={b.y} width={b.w} height={b.h}
                      fill="none"
                      stroke={TV_CLS_COLOR[b.cls] || 'var(--green)'}
                      strokeWidth="0.005"
                      style={{
                        animation: 'tvBoxPulse 1.6s ease-in-out infinite',
                        transition: 'all 0.5s ease-in-out',  // smooth IoU-tracked bbox motion
                      }}
                    />
                    <text
                      x={b.x + 0.005}
                      y={Math.max(0.025, b.y - 0.005)}
                      fill={TV_CLS_COLOR[b.cls] || 'var(--green)'}
                      fontSize="0.035"
                      fontFamily="var(--font-mono, monospace)"
                      fontWeight="700"
                      style={{ paintOrder: 'stroke', stroke: '#000', strokeWidth: '0.005' }}
                    >
                      {b.track_id != null ? `T${b.track_id} ` : ''}{b.cls.toUpperCase()} · {Math.round(b.conf * 100)}%
                    </text>
                  </g>
                ))}
              </svg>
            )}
          </>
        ) : hasVideo && !err ? (
          <video
            ref={videoRef}
            muted
            playsInline
            autoPlay
            loop={isMp4}
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', background: '#000' }}
          />
        ) : (
          <>
            <div className="cam-noise"></div>
            <div className="cam-scan-line"></div>
          </>
        )}
        <div className="cam-overlay-tl">
          <span className="cam-rec" style={{ opacity: cam.status === 'offline' ? 0.3 : 1 }}>
            ● {cam.status === 'offline' ? 'OFFLINE' : (hasSource && playing ? 'LIVE' : 'REC')}
          </span>
          <span className="cam-id">{cam.id}</span>
        </div>
        <div className="cam-overlay-tr">
          <span style={{ fontSize: 10 }}>{cam.fps ? `${cam.fps.toFixed ? cam.fps.toFixed(1) : cam.fps} FPS` : '— FPS'}</span>
        </div>
        {/* Detection box overlays will be drawn by Phase 2 from real OTVision output */}
        <div className="cam-overlay-bl">
          <span>{cam.name}</span>
        </div>
        <div className="cam-overlay-br">
          <span style={{ color: cam.status === 'active' ? 'var(--green)' : cam.status === 'degraded' ? 'var(--gold)' : 'var(--red)' }}>
            ◉ {cam.status || '—'}
          </span>
        </div>
        {boxes.length > 0 && (
          <div style={{
            position: 'absolute', bottom: 4, left: '50%', transform: 'translateX(-50%)',
            background: 'rgba(0,0,0,0.7)', padding: '2px 8px',
            fontFamily: 'var(--font-mono, monospace)', fontSize: 9, fontWeight: 700,
            letterSpacing: 1, color: 'var(--cyan)', border: '1px solid var(--cyan)',
          }}>
            DETECTED · {boxes.length} ◉
          </div>
        )}
        {/* Phase A.2 — Violation-label ribbon stacked top-center */}
        {violationLabels.length > 0 && (
          <div style={{
            position: 'absolute', top: 36, left: '50%', transform: 'translateX(-50%)',
            display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'center',
            pointerEvents: 'none', maxWidth: '85%',
          }}>
            {violationLabels.slice(0, 3).map((v, i) => {
              const sev = (v.severity || 'MEDIUM').toUpperCase();
              const bg = sev === 'CRITICAL' ? 'var(--red)'
                       : sev === 'HIGH'     ? 'var(--red)'
                       : sev === 'MEDIUM'   ? 'var(--gold)'
                                            : 'var(--cyan)';
              return (
                <div key={i} style={{
                  background: bg, color: '#000',
                  padding: '2px 8px', fontFamily: 'var(--font-mono, monospace)',
                  fontSize: 9, fontWeight: 800, letterSpacing: 1.2,
                  border: '2px solid #000', boxShadow: '2px 2px 0 #000',
                  textTransform: 'uppercase',
                  animation: v.cooled ? 'none' : 'tvBoxPulse 1.4s ease-in-out infinite',
                  opacity: v.cooled ? 0.65 : 1,
                  whiteSpace: 'nowrap',
                }}>
                  ⚠ {v.label || (v.type || '').replace(/_/g, ' ').toUpperCase()}
                  {v.inc_id ? ` · ${v.inc_id}` : ''}
                </div>
              );
            })}
          </div>
        )}
        {err && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--red)', background: 'rgba(0,0,0,0.6)' }}>
            STREAM ERROR
          </div>
        )}
      </div>
    </div>
  );
};

const TrafficLive = () => {
  // Chip label → incident.type token mapping (backend returns the right column)
  const CHIP_TO_TYPE = {
    'RED LIGHT VIOLATION': 'RED LIGHT',
    'SPEEDING': 'SPEEDING',
    'WRONG LANE': 'WRONG LANE',
    'NO HELMET': 'NO HELMET',
    'NO SEATBELT': 'NO SEATBELT',
    'ILLEGAL PARKING': 'ILLEGAL PARK',
  };
  const detectionTypes = Object.keys(CHIP_TO_TYPE);
  const [selected, setSelected] = React.useState(detectionTypes);  // ALL on by default
  const [cameras, setCameras] = React.useState([]);
  const [layout, setLayout] = React.useState('2x2');
  const [recent, setRecent] = React.useState([]);
  const toggle = (t) => setSelected(s => s.includes(t) ? s.filter(x => x !== t) : [...s, t]);
  const selectAll = () => setSelected(detectionTypes);
  const clearAll  = () => setSelected([]);

  const [snapshots, setSnapshots] = React.useState({});
  const [detections, setDetections] = React.useState({});
  const [detectSummary, setDetectSummary] = React.useState(null);
  // Phase A.2 — per-cam violation badges from the live pipeline
  const [liveLabels, setLiveLabels] = React.useState({});
  const [liveIncidentsRecent, setLiveIncidentsRecent] = React.useState([]);

  React.useEffect(() => {
    apiFetch('/api/traffic-violations/cameras', TRAFFIC_AUTH)
      .then(d => setCameras(d.cameras || []))
      .catch(() => setCameras([]));
    apiFetch('/api/traffic-violations/incidents', { ...TRAFFIC_AUTH, params: { limit: 20 } })
      .then(d => setRecent(d.incidents || []))
      .catch(() => setRecent([]));

    // Live snapshots + YOLO detections — refresh every 30s.
    const loadSnaps = () => apiFetch('/api/traffic-violations/snapshots', TRAFFIC_AUTH)
      .then(d => setSnapshots(d.snapshots || {})).catch(() => {});
    const loadDetect = () => apiFetch('/api/traffic-violations/snapshots/detect', TRAFFIC_AUTH)
      .then(d => {
        setDetections(d.detections || {});
        setDetectSummary(d.summary || null);
        setLiveLabels(d.live_violation_labels || {});
        if (Array.isArray(d.live_incidents_created_recent) && d.live_incidents_created_recent.length) {
          setLiveIncidentsRecent(d.live_incidents_created_recent);
          // Refresh the recent-incidents list so the bottom ticker reflects new auto-creates
          apiFetch('/api/traffic-violations/incidents', { ...TRAFFIC_AUTH, params: { limit: 20 } })
            .then(r => setRecent(r.incidents || []))
            .catch(() => {});
        }
      })
      .catch(() => {});
    loadSnaps();
    loadDetect();
    const t1 = setInterval(loadSnaps, 30000);
    const t2 = setInterval(loadDetect, 30000);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, []);

  // Camera roster is paginated by chosen layout — 4 / 9 / 16 visible tiles.
  const visibleCount = layout === '2x2' ? 4 : layout === '3x3' ? 9 : layout === '4x4' ? 16 : cameras.length;
  const tiles = cameras.slice(0, visibleCount);

  // Filter recent incidents by selected chip types — chips are now FUNCTIONAL filters.
  const selectedTypeTokens = new Set(selected.map(s => CHIP_TO_TYPE[s]));
  const filteredRecent = recent.filter(r => selectedTypeTokens.has(r.type));
  const activeDetections = filteredRecent.length;

  const tickerItems = filteredRecent.length === 0
    ? [{
        tag: 'INFO',
        color: 'var(--cyan)',
        text: selected.length === 0
          ? 'No violation types selected — click a chip above to enable filtering.'
          : recent.length === 0
            ? `${cameras.length} cameras connected. Awaiting first detection — Phase 2 pipeline will populate incidents here.`
            : `No recent detections of: ${selected.join(', ')}. Try toggling more chips.`
      }]
    : filteredRecent.slice(0, 6).map(r => ({
        tag: r.severity === 'CRITICAL' ? 'ALERT' : 'NEW',
        color: r.severity === 'CRITICAL' ? 'var(--red)' : r.severity === 'HIGH' ? 'var(--gold)' : 'var(--cyan)',
        text: `${r.type} on ${r.cam} · Plate ${r.plate} · ${r.conf}% conf`,
      }));

  return (
    <div className="tab-pane">
      <CameraHealthStrip />
      <div className="live-grid-row">
        <div className="live-grid-main">
          <div className="live-top-bar">
            <div className="live-controls">
              <span className="live-indicator"><span className="pulse-dot"></span> LIVE · {detectSummary ? `${detectSummary.total} objects · ${detectSummary.cars}🚗 ${detectSummary.motorcycles}🏍 ${detectSummary.buses + detectSummary.trucks}🚛 ${detectSummary.persons}🚶` : `${activeDetections} active detections`}</span>
              <SegmentedControl options={['2x2', '3x3', '4x4', 'FOCUS']} value={layout} onChange={setLayout} accent="var(--cyan)" />
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.55, marginRight: 4 }}>FILTER:</span>
              {detectionTypes.map(t => (
                <Chip key={t} label={t} selected={selected.includes(t)} onClick={() => toggle(t)} />
              ))}
              <button
                onClick={selected.length === detectionTypes.length ? clearAll : selectAll}
                className="btn-brutal"
                style={{ fontSize: 10, padding: '4px 10px', marginLeft: 4 }}
                title={selected.length === detectionTypes.length ? 'Clear all filters' : 'Enable all filters'}
              >
                {selected.length === detectionTypes.length ? 'CLEAR' : 'ALL'}
              </button>
            </div>
          </div>
          <div className="camera-grid">
        {tiles.map((c, i) => (
          <CameraTile
            key={c.id}
            cam={c}
            index={i}
            snapshot={snapshots[c.id]}
            detections={detections[c.id]}
            violationLabels={liveLabels[c.id] || []}
          />
        ))}
          </div>
        </div>
        <div className="live-grid-side">
          <TrafficMiniMap cameras={cameras} onSelect={(c) => console.log('focus', c.id)} />
        </div>
      </div>
      <AlertTicker items={tickerItems} />
    </div>
  );
};

// ====================================================================
// Phase 4 — Incident clip viewer
// Click the video thumb / VIEW button → modal plays the 3-second clip.
// Falls back to a friendly message if the clip wasn't generated.
// ====================================================================
const IncidentClipModal = ({ inc, onClose }) => {
  // Two evidence types: live-pipeline incidents save a JPG snapshot, upload-pipeline
  // incidents save a 3s mp4 clip. Try JPG first via img.onerror fallback; if that
  // fails too, show a message.
  const [mode, setMode] = React.useState('jpg');   // 'jpg' | 'mp4' | 'none'
  React.useEffect(() => { setMode('jpg'); }, [inc?.id]);
  if (!inc) return null;
  const jpgUrl = `${API_BASE || ''}/api/traffic-violations/incidents/${inc.id}/evidence.jpg`;
  const mp4Url = `${API_BASE || ''}/api/traffic-violations/incidents/${inc.id}/clip.mp4`;
  return (
    <div className="tv-modal-backdrop" onClick={onClose}>
      <div className="tv-modal" style={{ maxWidth: 800 }} onClick={e => e.stopPropagation()}>
        <div className="tv-modal-head">
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, opacity: 0.7 }}>{inc.id}</div>
            <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: 1 }}>{inc.type}</div>
            <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', opacity: 0.7, marginTop: 2 }}>
              Plate: <strong>{inc.plate}</strong> · {inc.cam} · {inc.time} · {inc.conf}% conf
            </div>
          </div>
          <SeverityBadge level={inc.severity} />
          <button className="btn-brutal" onClick={onClose} style={{ fontSize: 10, padding: '4px 10px', marginLeft: 'auto' }}>✕ CLOSE</button>
        </div>
        <div style={{ padding: 18 }}>
          {mode === 'jpg' && (
            <div style={{ position: 'relative' }}>
              <img
                src={jpgUrl}
                alt={`Evidence for ${inc.id}`}
                onError={() => setMode('mp4')}
                style={{ width: '100%', maxHeight: '60vh', objectFit: 'contain', background: '#000', border: '3px solid #000', display: 'block' }}
              />
              <div style={{
                position: 'absolute', top: 8, left: 8,
                background: 'var(--gold)', color: '#000', padding: '2px 8px',
                fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: 1,
                border: '2px solid #000',
              }}>LIVE-CAM SNAPSHOT</div>
            </div>
          )}
          {mode === 'mp4' && (
            <video
              src={mp4Url}
              controls autoPlay muted loop
              onError={() => setMode('none')}
              style={{ width: '100%', maxHeight: '60vh', background: '#000', border: '3px solid #000' }}
            />
          )}
          {mode === 'none' && (
            <div style={{ padding: 30, textAlign: 'center', fontFamily: 'var(--font-mono)', fontSize: 12, opacity: 0.7 }}>
              No evidence file saved for this incident. The detection metadata is still valid below.
            </div>
          )}
          <div style={{ marginTop: 12, fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.7, lineHeight: 1.7 }}>
            <strong>What the system flagged:</strong> {inc.description || `${inc.type} detected with ${inc.conf}% confidence at ${inc.time}.`}<br />
            <strong>Status:</strong> {inc.status?.toUpperCase()}
          </div>
        </div>
      </div>
    </div>
  );
};

// ====================================================================
// Phase 4 — Challan detail + manual mark-paid / mark-disputed
// (works without ngrok / Telegram webhook)
// ====================================================================
const ChallanDetailModal = ({ challan, onClose, onChanged }) => {
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  if (!challan) return null;
  const update = async (newStatus, reason = '') => {
    setBusy(true); setMsg('');
    try {
      await apiFetch(`/api/traffic-violations/challans/${challan.id}/mark-status`, {
        ...TRAFFIC_AUTH, json: { status: newStatus, reason, actor: 'rsd' },
      });
      setMsg(`✓ ${challan.id} marked ${newStatus}`);
      onChanged && onChanged();
      setTimeout(onClose, 1000);
    } catch (e) {
      setMsg(`✕ ${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };
  const isUnpaid = (challan.status || '').toUpperCase() === 'UNPAID';
  return (
    <div className="tv-modal-backdrop" onClick={onClose}>
      <div className="tv-modal" style={{ maxWidth: 620 }} onClick={e => e.stopPropagation()}>
        <div className="tv-modal-head">
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, opacity: 0.7 }}>{challan.id}</div>
            <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: 1 }}>{challan.type}</div>
            <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', opacity: 0.7, marginTop: 2 }}>
              {challan.plate} · {challan.driver} · ₹{(challan.amt || 0).toLocaleString()} · due {challan.due}
            </div>
          </div>
          <Badge variant={challan.status === 'PAID' ? 'green' : challan.status === 'DISPUTED' ? 'gold' : 'red'}>{challan.status}</Badge>
          <button className="btn-brutal" onClick={onClose} style={{ fontSize: 10, padding: '4px 10px', marginLeft: 'auto' }}>✕ CLOSE</button>
        </div>
        <div style={{ padding: 20 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.7, marginBottom: 14, lineHeight: 1.8 }}>
            <div><strong>Issued:</strong> {challan.issued}</div>
            <div><strong>Driver:</strong> {challan.driver}</div>
            <div><strong>Amount:</strong> ₹{(challan.amt || 0).toLocaleString()}</div>
          </div>
          {isUnpaid ? (
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                className="btn-brutal action-btn"
                disabled={busy}
                onClick={() => update('PAID')}
                style={{ flex: 1, padding: '12px 18px', background: 'var(--green)', color: '#000', width: 'auto' }}
              >✅ MARK PAID</button>
              <button
                className="btn-brutal action-btn"
                disabled={busy}
                onClick={() => {
                  const r = prompt('Dispute reason (optional):') || '';
                  update('DISPUTED', r);
                }}
                style={{ flex: 1, padding: '12px 18px', background: 'var(--gold)', color: '#000', width: 'auto' }}
              >⚠️ MARK DISPUTED</button>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                className="btn-brutal"
                disabled={busy}
                onClick={() => update('UNPAID')}
                style={{ flex: 1, padding: '10px 14px' }}
              >↻ REOPEN AS UNPAID</button>
            </div>
          )}
          {msg && (
            <div style={{ marginTop: 14, padding: 10, fontFamily: 'var(--font-mono)', fontSize: 12, background: msg.startsWith('✓') ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)' }}>
              {msg}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ====================================================================
// Phase 1+ — Plate lookup (Incidents tab top)
// Type any plate → modal opens with full incident + challan history.
// ====================================================================
const PlateLookup = ({ onResult }) => {
  const [q, setQ] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [err, setErr] = React.useState('');

  const submit = async (e) => {
    e?.preventDefault?.();
    if (!q.trim()) return;
    setLoading(true); setErr('');
    try {
      const r = await apiFetch(`/api/traffic-violations/plates/${encodeURIComponent(q.trim().toUpperCase())}`, TRAFFIC_AUTH);
      onResult(r);
    } catch (e) {
      setErr(e.message || 'Lookup failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={submit} className="tv-plate-lookup">
      <span className="tv-plate-lbl">PLATE LOOKUP</span>
      <input
        className="tv-plate-input"
        placeholder="e.g. MH-01-AB-9087"
        value={q}
        onChange={e => setQ(e.target.value)}
      />
      <button type="submit" className="btn-brutal" disabled={loading} style={{ fontSize: 11, padding: '6px 14px', width: 'auto' }}>
        {loading ? 'SEARCHING…' : 'LOOKUP'}
      </button>
      {err && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--red)' }}>{err}</span>}
    </form>
  );
};

// ====================================================================
// Phase 1+ — Plate detail modal (after lookup)
// ====================================================================
const PlateDetailModal = ({ result, onClose }) => {
  if (!result) return null;
  if (!result.found) {
    return (
      <div className="tv-modal-backdrop" onClick={onClose}>
        <div className="tv-modal" onClick={e => e.stopPropagation()}>
          <div className="tv-modal-head">
            <div className="incident-plate" style={{ fontSize: 18 }}>{result.plate}</div>
            <button className="btn-brutal" onClick={onClose} style={{ fontSize: 10, padding: '4px 10px' }}>✕ CLOSE</button>
          </div>
          <div style={{ padding: 30, textAlign: 'center', opacity: 0.6, fontFamily: 'var(--font-mono)' }}>
            No history found for this plate. Either it's never been flagged or the plate format is unknown.
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="tv-modal-backdrop" onClick={onClose}>
      <div className="tv-modal" onClick={e => e.stopPropagation()}>
        <div className="tv-modal-head">
          <div>
            <div className="incident-plate" style={{ fontSize: 18 }}>{result.plate}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.6 }}>{result.driver_name || '— unregistered driver —'}</div>
          </div>
          <SeverityBadge level={result.risk} />
          <button className="btn-brutal" onClick={onClose} style={{ fontSize: 10, padding: '4px 10px', marginLeft: 'auto' }}>✕ CLOSE</button>
        </div>
        <div className="tv-modal-stats">
          <div className="tv-health-block"><div className="tv-health-num">{result.total_incidents}</div><div className="tv-health-lbl">INCIDENTS</div></div>
          <div className="tv-health-block"><div className="tv-health-num">{result.total_challans}</div><div className="tv-health-lbl">CHALLANS</div></div>
          <div className="tv-health-block"><div className="tv-health-num" style={{ color: 'var(--red)' }}>₹{result.total_pending.toLocaleString()}</div><div className="tv-health-lbl">PENDING</div></div>
        </div>
        <div className="tv-modal-body">
          <div style={{ marginBottom: 16 }}>
            <div className="widget-title">RECENT INCIDENTS</div>
            {result.incidents.length === 0
              ? <div style={{ padding: 16, fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.5 }}>None.</div>
              : result.incidents.slice(0, 8).map(i => (
                <div key={i.id} className="tv-history-row">
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.6 }}>{i.id}</span>
                  <span style={{ fontWeight: 700 }}>{i.type}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{i.cam} · {i.time}</span>
                  <SeverityBadge level={i.severity} />
                  <StatusPill status={i.status} label={i.status.toUpperCase()} />
                </div>
              ))}
          </div>
          <div>
            <div className="widget-title">CHALLANS ISSUED</div>
            {result.challans.length === 0
              ? <div style={{ padding: 16, fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.5 }}>None.</div>
              : result.challans.slice(0, 8).map(c => (
                <div key={c.id} className="tv-history-row">
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.6 }}>{c.id}</span>
                  <span style={{ fontWeight: 700 }}>{c.type}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>₹{(c.amt||0).toLocaleString()} · due {c.due}</span>
                  <Badge variant={c.status === 'PAID' ? 'green' : c.status === 'DISPUTED' ? 'gold' : 'red'}>{c.status}</Badge>
                </div>
              ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ====================================================================
// Phase 1+ — Bulk Actions Bar (Incidents tab — sticky bottom)
// ====================================================================
const BulkActionsBar = ({ count, onApproveAll, onRejectAll, onClear }) => {
  if (count === 0) return null;
  return (
    <div className="tv-bulk-bar">
      <span className="tv-bulk-count">{count} selected</span>
      <button className="btn-brutal" onClick={onClear} style={{ fontSize: 11, padding: '6px 12px' }}>CLEAR</button>
      <div style={{ flex: 1 }} />
      <button className="btn-brutal action-btn" onClick={onApproveAll} style={{ fontSize: 11, padding: '6px 14px', width: 'auto', background: 'var(--green)', color: '#000' }}>
        ✓ APPROVE ALL
      </button>
      <button className="btn-brutal action-btn" onClick={onRejectAll} style={{ fontSize: 11, padding: '6px 14px', width: 'auto', background: 'var(--red)', color: '#fff' }}>
        ✕ REJECT ALL
      </button>
    </div>
  );
};

const TrafficIncidents = () => {
  const [selected, setSelected] = React.useState([]);  // chip filter state (unused — legacy)
  const [incidents, setIncidents] = React.useState([]);
  const [filters, setFilters] = React.useState({});
  const [loading, setLoading] = React.useState(true);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [selectedIds, setSelectedIds] = React.useState([]);   // bulk-select inc_id list
  const [plateResult, setPlateResult] = React.useState(null);
  const [viewIncident, setViewIncident] = React.useState(null);   // for the clip modal
  const [toast, setToast] = React.useState('');                    // approve/reject feedback
  const [busyId, setBusyId] = React.useState(null);                // per-card busy flag

  React.useEffect(() => {
    setLoading(true);
    const params = { limit: 50 };
    Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
    apiFetch('/api/traffic-violations/incidents', { ...TRAFFIC_AUTH, params })
      .then(d => { setIncidents(d.incidents || []); setLoading(false); })
      .catch(() => { setIncidents([]); setLoading(false); });
  }, [filters, refreshKey]);

  // Phase A.1 — auto-poll for new live-pipeline incidents every 15s.
  // Silent (no loading flag) so the user's interaction isn't interrupted.
  React.useEffect(() => {
    const tick = () => {
      const params = { limit: 50 };
      Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
      apiFetch('/api/traffic-violations/incidents', { ...TRAFFIC_AUTH, params })
        .then(d => setIncidents(d.incidents || []))
        .catch(() => {});
    };
    const id = setInterval(tick, 15000);
    return () => clearInterval(id);
  }, [filters]);

  const toggleSelected = (id) => {
    setSelectedIds(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id]);
  };
  const clearSelection = () => setSelectedIds([]);
  const doBulk = async (action) => {
    if (selectedIds.length === 0) return;
    try {
      const result = await apiFetch('/api/traffic-violations/incidents/bulk-action', {
        ...TRAFFIC_AUTH,
        json: { ids: selectedIds, action, actor: 'rsd' },
      });
      setSelectedIds([]);
      setRefreshKey(k => k + 1);
      const ch = result.challan_ids?.length ? ` · challan(s) issued: ${result.challan_ids.length}` : '';
      const tg = result.telegram_failures?.length ? ` · telegram failures: ${result.telegram_failures.length}` : '';
      setToast(`✓ ${result.updated} incident(s) ${action.toLowerCase()}d${ch}${tg}`);
      setTimeout(() => setToast(''), 4000);
    } catch (e) {
      setToast(`✕ Bulk ${action} failed: ${e.message || e}`);
      setTimeout(() => setToast(''), 5000);
    }
  };

  const doSingle = async (incId, action) => {
    setBusyId(incId);
    try {
      const result = await apiFetch(`/api/traffic-violations/incidents/${incId}/${action}`, {
        ...TRAFFIC_AUTH, json: { actor: 'rsd' },
      });
      setRefreshKey(k => k + 1);
      const chId = result.challan?.id ? ` · ${result.challan.id} issued` : '';
      const tgErr = result.telegram_error ? ` · ⚠ Telegram: ${result.telegram_error}` : '';
      setToast(`✓ ${incId} ${action}d${chId}${tgErr}`);
      setTimeout(() => setToast(''), 4000);
    } catch (e) {
      setToast(`✕ ${incId} ${action} failed: ${e.message || e}`);
      setTimeout(() => setToast(''), 5000);
    } finally {
      setBusyId(null);
    }
  };

  const downloadCourtPack = async (incId) => {
    try {
      const m = await apiFetch(`/api/traffic-violations/incidents/${incId}/court-pack`, TRAFFIC_AUTH);
      // Phase 1: download the manifest JSON. Phase 2 will swap to zip.
      const blob = new Blob([JSON.stringify(m, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `court-pack-${incId}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      alert(`Court pack failed: ${e.message || e}`);
    }
  };

  return (
    <div className="tab-pane">
      <PlateLookup onResult={setPlateResult} />
      <PlateDetailModal result={plateResult} onClose={() => setPlateResult(null)} />
      <IncidentClipModal inc={viewIncident} onClose={() => setViewIncident(null)} />
      {toast && (
        <div style={{
          position: 'fixed', top: 24, right: 24, zIndex: 100, padding: '12px 16px',
          background: toast.startsWith('✓') ? '#0a3d1f' : '#3d0a0a',
          color: toast.startsWith('✓') ? 'var(--green)' : 'var(--red)',
          border: `3px solid ${toast.startsWith('✓') ? 'var(--green)' : 'var(--red)'}`,
          boxShadow: '4px 4px 0 #000',
          fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, maxWidth: 480,
        }}>{toast}</div>
      )}

      <div className="toolbar">
        <FilterBar
          filters={[
            { key: 'type', label: 'Type', options: ['NO HELMET', 'SPEEDING', 'WRONG LANE', 'RED LIGHT', 'NO SEATBELT', 'ILLEGAL PARK'] },
            { key: 'severity', label: 'Severity', options: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] },
            { key: 'status', label: 'Status', options: ['pending', 'approved', 'rejected'] },
          ]}
          values={filters}
          onChange={setFilters}
        />
      </div>
      {!loading && incidents.length === 0 && (
        <div className="widget-card" style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 14, opacity: 0.6, marginBottom: 8 }}>NO INCIDENTS YET</div>
          <div style={{ fontSize: 11, opacity: 0.4, fontFamily: 'var(--font-mono)' }}>
            Phase 2 pipeline (OTVision + DeepSORT + plate OCR) will auto-create incidents here from live feeds and uploads.
          </div>
        </div>
      )}
      <div className="incident-grid">
        {incidents.map((inc, i) => {
          const isPending = inc.status === 'pending';
          const isSelected = selectedIds.includes(inc.id);
          return (
            <div key={inc.id} className={`incident-card ${isSelected ? 'tv-selected' : ''}`} style={{ animationDelay: `${i * 0.05}s` }}>
              {isPending && (
                <label className="tv-card-checkbox" title="Select for bulk action">
                  <input type="checkbox" checked={isSelected} onChange={() => toggleSelected(inc.id)} />
                </label>
              )}
              <div className="incident-video-thumb"
                   onClick={(e) => { e.stopPropagation(); setViewIncident(inc); }}
                   style={{ cursor: 'pointer' }}
                   title="Click to play clip">
                <div className="vt-cam-label">{inc.cam}</div>
                <div className="vt-play">▶</div>
                <div className="vt-duration">0:03</div>
              </div>
              <div className="incident-info">
                <div className="incident-top">
                  <div>
                    <div className="incident-id">{inc.id}</div>
                    <div className="incident-type">{inc.type}</div>
                  </div>
                  <SeverityBadge level={inc.severity} />
                </div>
                <div className="incident-meta">
                  <div className="incident-plate">{inc.plate}</div>
                  <div style={{ display: 'flex', gap: 10, fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.6 }}>
                    <span>⏱ {inc.time}</span>
                    <span>◉ {inc.conf}% conf</span>
                  </div>
                </div>
                <ConfidenceBar value={inc.conf} showLabel={false} />
                {isPending ? (
                  <div className="incident-actions">
                    <button className="btn-brutal" style={{ fontSize: 10, padding: '4px 10px' }}
                            onClick={() => setViewIncident(inc)}>👁 VIEW</button>
                    <button
                      className="btn-brutal action-btn"
                      disabled={busyId === inc.id}
                      onClick={() => doSingle(inc.id, 'approve')}
                      style={{ fontSize: 10, padding: '4px 10px', width: 'auto', background: 'var(--green)', color: '#000', opacity: busyId === inc.id ? 0.5 : 1 }}
                    >{busyId === inc.id ? '...' : '✓ APPROVE'}</button>
                    <button
                      className="btn-brutal action-btn"
                      disabled={busyId === inc.id}
                      onClick={() => doSingle(inc.id, 'reject')}
                      style={{ fontSize: 10, padding: '4px 10px', width: 'auto', background: 'var(--red)', color: '#fff', opacity: busyId === inc.id ? 0.5 : 1 }}
                    >{busyId === inc.id ? '...' : '✕ REJECT'}</button>
                  </div>
                ) : (
                  <div style={{ padding: '6px 0', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
                    <StatusPill status={inc.status} label={inc.status.toUpperCase()} />
                  </div>
                )}
                <button
                  className="btn-brutal"
                  onClick={() => downloadCourtPack(inc.id)}
                  style={{ fontSize: 10, padding: '3px 8px', marginTop: 6, width: '100%' }}
                  title="Download court-grade evidence manifest (JSON for now; zip in Phase 2)"
                >📦 COURT PACK</button>
              </div>
            </div>
          );
        })}
      </div>
      <BulkActionsBar
        count={selectedIds.length}
        onApproveAll={() => doBulk('approve')}
        onRejectAll={() => doBulk('reject')}
        onClear={clearSelection}
      />
    </div>
  );
};

const fmtRupees = (n) => {
  if (!n) return '₹0';
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  return `₹${n.toLocaleString()}`;
};

// ====================================================================
// Phase 1+ — SLA Queue widget (Challans tab top)
// ====================================================================
const SLAWidget = () => {
  const [sla, setSla] = React.useState(null);
  React.useEffect(() => {
    apiFetch('/api/traffic-violations/challans/sla', { ...TRAFFIC_AUTH, params: { window_days: 7 } })
      .then(setSla).catch(() => {});
  }, []);
  if (!sla) return null;
  return (
    <div className="widget-card" style={{ marginBottom: 12 }}>
      <div className="widget-title">SLA QUEUE · NEXT {sla.window_days} DAYS</div>
      <div className="tv-sla-row">
        <div className="tv-health-block"><div className="tv-health-num" style={{ color: 'var(--red)' }}>{sla.overdue_count}</div><div className="tv-health-lbl">OVERDUE</div></div>
        <div className="tv-health-block"><div className="tv-health-num" style={{ color: 'var(--gold)' }}>{sla.approaching_count}</div><div className="tv-health-lbl">APPROACHING DUE</div></div>
        <div className="tv-health-block"><div className="tv-health-num" style={{ color: 'var(--red)' }}>{fmtRupees(sla.total_at_risk)}</div><div className="tv-health-lbl">AT RISK</div></div>
      </div>
      {(sla.overdue.length > 0 || sla.approaching.length > 0) && (
        <div className="tv-sla-list">
          {sla.overdue.slice(0, 3).map(c => (
            <div key={c.id} className="tv-history-row" style={{ borderLeft: '4px solid var(--red)' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.6 }}>{c.id}</span>
              <span style={{ fontWeight: 700 }}>{c.plate}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{c.type} · ₹{(c.amt||0).toLocaleString()}</span>
              <Badge variant="red">OVERDUE {c.days_overdue || 0}d</Badge>
            </div>
          ))}
          {sla.approaching.slice(0, 3).map(c => (
            <div key={c.id} className="tv-history-row" style={{ borderLeft: '4px solid var(--gold)' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.6 }}>{c.id}</span>
              <span style={{ fontWeight: 700 }}>{c.plate}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{c.type} · ₹{(c.amt||0).toLocaleString()}</span>
              <Badge variant="gold">DUE IN {c.days_until_due || 0}d</Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ====================================================================
// Phase 1+ — Revenue forecast card (Challans tab)
// ====================================================================
const RevenueForecastCard = () => {
  const [r, setR] = React.useState(null);
  React.useEffect(() => {
    apiFetch('/api/traffic-violations/analytics/revenue-forecast', { ...TRAFFIC_AUTH, params: { days: 30 } })
      .then(setR).catch(() => {});
  }, []);
  if (!r) return null;
  return (
    <div className="widget-card" style={{ marginBottom: 12 }}>
      <div className="widget-title">REVENUE FORECAST · NEXT {r.days} DAYS</div>
      <div className="tv-sla-row">
        <div className="tv-health-block"><div className="tv-health-num" style={{ color: 'var(--green)' }}>{fmtRupees(r.projected_total_collection)}</div><div className="tv-health-lbl">PROJECTED COLLECTION</div></div>
        <div className="tv-health-block"><div className="tv-health-num">{fmtRupees(r.projected_new_amount)}</div><div className="tv-health-lbl">NEW ISSUANCE</div></div>
        <div className="tv-health-block"><div className="tv-health-num" style={{ color: 'var(--gold)' }}>{r.collection_rate}%</div><div className="tv-health-lbl">COLLECTION RATE</div></div>
      </div>
      <div style={{ marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.55, lineHeight: 1.6 }}>
        Recovery from current pending ({fmtRupees(r.pending_amount)}): ~{fmtRupees(r.projected_collection_pending)} · From new issuance: ~{fmtRupees(r.projected_collection_new)}
      </div>
    </div>
  );
};

const TrafficChallans = () => {
  const [challans, setChallans] = React.useState([]);
  const [kpis, setKpis] = React.useState({ issued_30d: 0, total_collected: 0, collection_rate: 0, disputed_pct: 0 });
  const [openChallan, setOpenChallan] = React.useState(null);
  const [refreshKey, setRefreshKey] = React.useState(0);

  React.useEffect(() => {
    apiFetch('/api/traffic-violations/challans', TRAFFIC_AUTH)
      .then(d => setChallans(d.challans || []))
      .catch(() => setChallans([]));
    apiFetch('/api/traffic-violations/challans/kpis', TRAFFIC_AUTH)
      .then(setKpis).catch(() => {});
  }, [refreshKey]);

  return (
    <div className="tab-pane">
      <div className="kpi-grid-4">
        <KPICard label="CHALLANS ISSUED (30D)" value={kpis.issued_30d.toLocaleString()}     color="var(--cyan)" />
        <KPICard label="TOTAL COLLECTED"       value={fmtRupees(kpis.total_collected)}      color="var(--green)" />
        <KPICard label="COLLECTION RATE"       value={`${kpis.collection_rate}%`}            color="var(--gold)" />
        <KPICard label="DISPUTED"              value={`${kpis.disputed_pct}%`}               color="var(--red)" />
      </div>
      <div className="tv-grid-2col mt-20">
        <SLAWidget />
        <RevenueForecastCard />
      </div>
      <div className="widget-card mt-20">
        {challans.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center' }}>
            <div style={{ fontSize: 14, opacity: 0.6, marginBottom: 8 }}>NO CHALLANS ISSUED YET</div>
            <div style={{ fontSize: 11, opacity: 0.4, fontFamily: 'var(--font-mono)' }}>
              Phase 4 wires this: approving an incident auto-issues a challan + sends a Telegram pay yes/no to the driver.
            </div>
          </div>
        ) : (
          <>
            <DataTable
              onRowClick={r => setOpenChallan(r)}
              columns={[
                { key: 'id',     label: 'CHALLAN',  width: 100 },
                { key: 'plate',  label: 'PLATE',    width: 150 },
                { key: 'driver', label: 'DRIVER',   width: 120 },
                { key: 'type',   label: 'OFFENSE',  width: 140 },
                { key: 'amt',    label: 'AMOUNT',   width: 100, align: 'right', render: v => `₹${v.toLocaleString()}` },
                { key: 'issued', label: 'ISSUED',   width: 110 },
                { key: 'due',    label: 'DUE BY',   width: 110 },
                { key: 'status', label: 'STATUS',   width: 130, render: v => <Badge variant={v === 'PAID' ? 'green' : v === 'DISPUTED' ? 'gold' : 'red'}>{v}</Badge> },
              ]}
              rows={challans}
            />
            <ChallanDetailModal
              challan={openChallan}
              onClose={() => setOpenChallan(null)}
              onChanged={() => setRefreshKey(k => k + 1)}
            />
          </>
        )}
      </div>
    </div>
  );
};

const OffenderTimelineModal = ({ plate, onClose }) => {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [notifyBusy, setNotifyBusy] = React.useState(false);
  const [toast, setToast] = React.useState('');

  const load = React.useCallback(() => {
    setLoading(true);
    apiFetch(`/api/traffic-violations/offenders/${encodeURIComponent(plate)}/timeline`, TRAFFIC_AUTH)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [plate]);
  React.useEffect(() => { load(); }, [load]);

  const doNotify = async () => {
    setNotifyBusy(true);
    try {
      const r = await apiFetch(`/api/traffic-violations/offenders/${encodeURIComponent(plate)}/notify`, {
        ...TRAFFIC_AUTH, json: { actor: 'rsd' }
      });
      if (r.notified) {
        setToast(`Telegram nag sent · msg #${r.telegram_message_id}`);
        load();
      } else {
        setToast(`Notify failed: ${r.error || 'unknown error'}`);
      }
    } catch (e) {
      setToast(`Notify failed: ${e.message || e}`);
    } finally {
      setNotifyBusy(false);
      setTimeout(() => setToast(''), 4500);
    }
  };

  const fmtAt = (iso) => {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleString('en-IN', { hour12: false }).replace(',', ' ·');
    } catch { return iso; }
  };
  const colorVar = (c) => ({ red: 'var(--red)', green: 'var(--green)', gold: 'var(--gold)', cyan: 'var(--cyan)' }[c] || 'var(--cyan)');

  return (
    <div className="tv-modal-backdrop" onClick={onClose}>
      <div className="tv-modal tv-modal-pad" style={{ maxWidth: 760 }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, opacity: 0.55, letterSpacing: 1 }}>OFFENDER TIMELINE</div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{plate}</div>
            {data?.driver && <div style={{ fontSize: 12, opacity: 0.7, marginTop: 2 }}>{data.driver}</div>}
          </div>
          <button className="btn-brutal" onClick={onClose} style={{ fontSize: 11 }}>CLOSE</button>
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', opacity: 0.55 }}>Loading timeline…</div>
        ) : !data ? (
          <div style={{ padding: 40, textAlign: 'center', opacity: 0.55 }}>No data.</div>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 18 }}>
              <KPICard label="INCIDENTS"        value={data.incident_count}                                color="var(--cyan)" />
              <KPICard label="CHALLANS"         value={data.challan_count}                                 color="var(--gold)" />
              <KPICard label="OUTSTANDING"      value={`₹${(data.total_outstanding || 0).toLocaleString()}`} color="var(--red)" />
              <KPICard label="COLLECTED"        value={`₹${(data.total_paid || 0).toLocaleString()}`}        color="var(--green)" />
            </div>

            <div style={{ display: 'flex', gap: 8, marginBottom: 14, alignItems: 'center' }}>
              <button className="btn-brutal" onClick={doNotify} disabled={notifyBusy} style={{ background: 'var(--gold)', color: '#000' }}>
                {notifyBusy ? 'SENDING…' : 'SEND TELEGRAM NAG'}
              </button>
              <div style={{ fontSize: 10, opacity: 0.55, fontFamily: 'var(--font-mono)' }}>
                {data.chat_id ? `chat_id: ${data.chat_id}` : 'No driver chat_id — uses default'}
              </div>
              {toast && <div style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--cyan)' }}>{toast}</div>}
            </div>

            <div className="tv-timeline">
              {data.events.length === 0 ? (
                <div style={{ padding: 30, textAlign: 'center', opacity: 0.4 }}>No events.</div>
              ) : data.events.map((e, i) => (
                <div key={i} className="tv-timeline-row">
                  <div className="tv-timeline-dot" style={{ background: colorVar(e.badge_color) }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{e.label}</span>
                      {e.badge && (
                        <span style={{
                          fontSize: 10,
                          fontFamily: 'var(--font-mono)',
                          padding: '2px 8px',
                          background: colorVar(e.badge_color),
                          color: '#000',
                          letterSpacing: 1,
                        }}>{e.badge}</span>
                      )}
                      <span style={{ marginLeft: 'auto', fontSize: 10, opacity: 0.5, fontFamily: 'var(--font-mono)' }}>{fmtAt(e.at)}</span>
                    </div>
                    {e.detail && <div style={{ fontSize: 11, opacity: 0.65, marginTop: 2, fontFamily: 'var(--font-mono)' }}>{e.detail}</div>}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const TrafficOffenders = () => {
  const [offenders, setOffenders] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [openPlate, setOpenPlate] = React.useState(null);
  const [notifyBusy, setNotifyBusy] = React.useState('');
  const [toast, setToast] = React.useState('');

  const load = React.useCallback(() => {
    apiFetch('/api/traffic-violations/offenders/top', { ...TRAFFIC_AUTH, params: { days: 90, limit: 5 } })
      .then(d => { setOffenders(d.offenders || []); setLoading(false); })
      .catch(() => { setOffenders([]); setLoading(false); });
  }, []);
  React.useEffect(load, [load]);

  const quickNotify = async (plate, e) => {
    e.stopPropagation();
    setNotifyBusy(plate);
    try {
      const r = await apiFetch(`/api/traffic-violations/offenders/${encodeURIComponent(plate)}/notify`, {
        ...TRAFFIC_AUTH, json: { actor: 'rsd' }
      });
      setToast(r.notified
        ? `${plate}: Telegram nag sent (#${r.telegram_message_id})`
        : `${plate}: ${r.error || 'notify failed'}`);
    } catch (err) {
      setToast(`${plate}: ${err.message || err}`);
    } finally {
      setNotifyBusy('');
      setTimeout(() => setToast(''), 4500);
    }
  };

  return (
    <div className="tab-pane">
      {toast && (
        <div style={{
          position: 'fixed', top: 80, right: 20, zIndex: 9999,
          background: 'var(--gold)', color: '#000', padding: '10px 16px',
          fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: 1,
          border: '2px solid #000', boxShadow: '4px 4px 0 #000',
        }}>{toast}</div>
      )}
      <div className="widget-card">
        <div className="widget-title">TOP 5 REPEAT OFFENDERS · LAST 90 DAYS</div>
        {!loading && offenders.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center' }}>
            <div style={{ fontSize: 14, opacity: 0.6, marginBottom: 8 }}>NO REPEAT OFFENDERS YET</div>
            <div style={{ fontSize: 11, opacity: 0.4, fontFamily: 'var(--font-mono)' }}>
              This rolls up tv_incidents + tv_challans by plate (90-day window). Populates as Phase 2 detections accumulate.
            </div>
          </div>
        ) : (
        <div className="offender-list">
          {offenders.map(o => (
            <div
              key={o.rank}
              className="offender-row"
              style={{ cursor: 'pointer' }}
              onClick={() => setOpenPlate(o.plate)}
              title="Click for full timeline"
            >
              <span className="offender-rank">#{o.rank}</span>
              <div style={{ flex: 1 }}>
                <div className="offender-plate">{o.plate}</div>
                <div className="offender-driver">{o.driver}</div>
              </div>
              <div className="offender-stats">
                <div><strong>{o.offenses}</strong> offenses</div>
                <div>₹{(o.total || 0).toLocaleString()} pending</div>
              </div>
              <SeverityBadge level={o.risk} />
              <div className="offender-actions">
                <button
                  className="btn-brutal"
                  style={{ fontSize: 10, padding: '4px 10px' }}
                  onClick={e => { e.stopPropagation(); setOpenPlate(o.plate); }}
                >HISTORY</button>
                <button
                  className="btn-brutal"
                  style={{ fontSize: 10, padding: '4px 10px', background: 'var(--gold)', color: '#000' }}
                  disabled={notifyBusy === o.plate}
                  onClick={e => quickNotify(o.plate, e)}
                >{notifyBusy === o.plate ? '…' : 'NOTIFY'}</button>
              </div>
            </div>
          ))}
        </div>
        )}
      </div>
      {openPlate && <OffenderTimelineModal plate={openPlate} onClose={() => setOpenPlate(null)} />}
    </div>
  );
};

const TrafficAnalytics = () => {
  const [summary, setSummary] = React.useState({ detections_24h: 0, avg_confidence: 0, false_positive_pct: 0, cam_uptime_pct: 0 });

  React.useEffect(() => {
    apiFetch('/api/traffic-violations/analytics/summary', TRAFFIC_AUTH)
      .then(setSummary)
      .catch(() => {});
  }, []);

  // Heatmap/donut/hotspot/trend become real in Phase 6. For Phase 1 we render
  // zeroed-out shells so the layout stays intact and nothing fakes the data.
  const emptyHeatmap = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0));

  return (
    <div className="tab-pane">
      <div className="kpi-grid-4">
        <KPICard label="DETECTIONS (24H)" value={summary.detections_24h.toLocaleString()} color="var(--cyan)" />
        <KPICard label="AVG CONFIDENCE"   value={`${summary.avg_confidence}%`}            color="var(--green)" />
        <KPICard label="FALSE POSITIVES"  value={`${summary.false_positive_pct}%`}        color="var(--red)" />
        <KPICard label="CAM UPTIME"       value={`${summary.cam_uptime_pct}%`}            color="var(--gold)" />
      </div>
      <div className="widgets-grid mt-20">
        <Heatmap data={emptyHeatmap} title="VIOLATIONS BY HOUR × DAY" />
        <div className="widget-card">
          <div className="widget-title">VIOLATION BREAKDOWN</div>
          <div style={{ padding: 40, textAlign: 'center', fontSize: 11, opacity: 0.4, fontFamily: 'var(--font-mono)' }}>
            Donut populates once detections exist (Phase 6).
          </div>
        </div>
      </div>
      <div className="widgets-grid mt-20">
        <div className="widget-card">
          <div className="widget-title">7-DAY TREND</div>
          <div style={{ padding: 40, textAlign: 'center', fontSize: 11, opacity: 0.4, fontFamily: 'var(--font-mono)' }}>
            Trend chart fills as daily detections accumulate (Phase 6).
          </div>
        </div>
        <div className="widget-card">
          <div className="widget-title">TOP HOTSPOT ZONES</div>
          <div style={{ padding: 40, textAlign: 'center', fontSize: 11, opacity: 0.4, fontFamily: 'var(--font-mono)' }}>
            Hotspot ranking by camera location (Phase 6).
          </div>
        </div>
      </div>
    </div>
  );
};

// ====================================================================
// Phase C — Settings tab
// Live-tune the detection thresholds + manage Telegram webhook + show
// recognised violation taxonomy.
// ====================================================================
const TRAFFIC_FIELD_LABELS = {
  live_pipeline_enabled:      ['Live pipeline enabled',     'Master switch — toggle to pause/resume the auto-detection loop.'],
  vision_provider:            ['Vision provider',           '"ollama" runs Gemma 4 locally (default). "groq" uses Llama-4-Scout cloud. "auto" tries local first then cloud.'],
  groq_cooldown_secs:         ['Per-cam vision cooldown',   'Min seconds between Vision-API calls on the same camera. Higher = fewer dupes / lower cost.'],
  incident_cooldown_secs:     ['Per (cam, type) cooldown',  'Min seconds before the same violation type can re-fire on the same cam.'],
  label_ttl_secs:             ['Tile label TTL',            'How long a violation badge stays on a live tile after detection.'],
  groq_budget_per_cycle:      ['Vision calls per cycle',    'Hard cap per 30 s detect cycle. Ollama: 2 is safe. Groq: 4 is safe.'],
  stationary_lifetime_heavy:  ['Stationary frames (heavy)', 'Cycles a truck/bus must persist before triggering Vision (accident candidate).'],
  stationary_lifetime_moto:   ['Stationary frames (moto)',  'Cycles a motorcycle must persist before triggering Vision (helmet check).'],
  density_suspicious:         ['Density threshold',         'Vehicle count above which we treat the frame as a congestion / pile-up candidate.'],
  clip_frames_after:          ['Clip frames after',         'How many cycles of "after" snapshots get stitched into the evidence slideshow.'],
  clip_fps:                   ['Evidence clip FPS',         'Playback fps of the stitched slideshow mp4. 2 fps = 5 s of playback for 10 frames.'],
  frame_buffer_size:          ['Frame buffer size',         'How many recent JPGs per cam we keep in memory for "before" context.'],
  detect_cache_ttl_secs:      ['Detect cache TTL',          'How long YOLO + Groq results stay cached before the next compute cycle.'],
  track_iou_threshold:        ['Track IoU threshold',       'Min IoU to consider two bboxes the same vehicle across snapshots (0..1).'],
};

const TrafficSettings = () => {
  const [config, setConfig] = React.useState(null);
  const [schema, setSchema] = React.useState({});
  const [violationTypes, setViolationTypes] = React.useState({});
  const [draft, setDraft] = React.useState({});
  const [busy, setBusy] = React.useState(false);
  const [toast, setToast] = React.useState('');
  const [whStatus, setWhStatus] = React.useState(null);
  const [whBusy, setWhBusy] = React.useState(false);

  const load = React.useCallback(() => {
    apiFetch('/api/traffic-violations/config', TRAFFIC_AUTH)
      .then(d => {
        setConfig(d.config || {});
        setSchema(d.schema || {});
        setViolationTypes(d.violation_types || {});
        setDraft(d.config || {});
      })
      .catch(() => setToast('Failed to load config'));
    apiFetch('/api/traffic-violations/telegram/webhook-status', TRAFFIC_AUTH)
      .then(setWhStatus)
      .catch(() => {});
  }, []);
  React.useEffect(load, [load]);

  const flash = (msg) => { setToast(msg); setTimeout(() => setToast(''), 4500); };

  const save = async () => {
    if (!config) return;
    const patch = {};
    Object.keys(draft).forEach(k => {
      if (draft[k] !== config[k]) patch[k] = draft[k];
    });
    if (Object.keys(patch).length === 0) { flash('No changes to save'); return; }
    setBusy(true);
    try {
      const r = await apiFetch('/api/traffic-violations/config', {
        ...TRAFFIC_AUTH, method: 'PUT', json: patch,
      });
      setConfig(r.config || {});
      setDraft(r.config || {});
      const appliedKeys = Object.keys(r.applied || {});
      const rejectedKeys = Object.keys(r.rejected || {});
      let msg = `Saved: ${appliedKeys.join(', ') || '(none)'}`;
      if (rejectedKeys.length) msg += ` · Rejected: ${rejectedKeys.join(', ')}`;
      flash(msg);
    } catch (e) {
      flash(`Save failed: ${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  const reset = () => setDraft({ ...config });

  const setupWebhook = async () => {
    setWhBusy(true);
    try {
      const r = await apiFetch('/api/traffic-violations/telegram/setup-webhook', { ...TRAFFIC_AUTH, json: {} });
      flash(`Webhook live: ${r.public_url}`);
      setWhStatus(await apiFetch('/api/traffic-violations/telegram/webhook-status', TRAFFIC_AUTH));
    } catch (e) {
      flash(`Setup failed: ${e.message || e}`);
    } finally {
      setWhBusy(false);
    }
  };
  const teardownWebhook = async () => {
    setWhBusy(true);
    try {
      await apiFetch('/api/traffic-violations/telegram/teardown-webhook', { ...TRAFFIC_AUTH, json: {} });
      flash('Webhook torn down');
      setWhStatus(await apiFetch('/api/traffic-violations/telegram/webhook-status', TRAFFIC_AUTH));
    } catch (e) {
      flash(`Teardown failed: ${e.message || e}`);
    } finally {
      setWhBusy(false);
    }
  };

  if (!config) {
    return <div className="tab-pane"><div style={{ padding: 30, opacity: 0.55, fontFamily: 'var(--font-mono)' }}>Loading config…</div></div>;
  }

  const dirty = Object.keys(draft).some(k => draft[k] !== config[k]);
  const updateField = (k, raw) => {
    const t = schema[k];
    let v = raw;
    if (t === 'bool') v = !!raw;
    else if (t === 'int') v = raw === '' ? '' : parseInt(raw, 10);
    else if (t === 'float') v = raw === '' ? '' : parseFloat(raw);
    setDraft(d => ({ ...d, [k]: v }));
  };

  return (
    <div className="tab-pane">
      {toast && (
        <div style={{
          position: 'fixed', top: 80, right: 20, zIndex: 9999,
          background: 'var(--cyan)', color: '#000', padding: '10px 16px',
          fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: 1,
          border: '2px solid #000', boxShadow: '4px 4px 0 #000',
        }}>{toast}</div>
      )}

      <div className="widgets-grid">
        <div className="widget-card">
          <div className="widget-title">DETECTION PIPELINE THRESHOLDS</div>
          <div style={{ padding: 14, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            {Object.keys(schema).map(k => {
              const [label, hint] = TRAFFIC_FIELD_LABELS[k] || [k, ''];
              const t = schema[k];
              const v = draft[k] ?? config[k];
              const changed = draft[k] !== config[k];
              const baseStyle = {
                width: '100%', padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: 12,
                border: changed ? '2px solid var(--gold)' : '2px solid #000', background: '#fff', color: '#000',
              };
              return (
                <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1, fontFamily: 'var(--font-mono)' }}>
                    {label.toUpperCase()}
                    {changed && <span style={{ color: 'var(--gold)', marginLeft: 8 }}>● modified</span>}
                  </label>
                  {t === 'bool' ? (
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 12, padding: 6, border: changed ? '2px solid var(--gold)' : '2px solid #000', background: '#fff', color: '#000' }}>
                      <input type="checkbox" checked={!!v} onChange={e => updateField(k, e.target.checked)} />
                      {v ? 'ENABLED' : 'DISABLED'}
                    </label>
                  ) : t === 'str' && k === 'vision_provider' ? (
                    <select value={v ?? ''} onChange={e => updateField(k, e.target.value)} style={baseStyle}>
                      <option value="ollama">ollama (Gemma 4 local)</option>
                      <option value="groq">groq (Llama-4-Scout cloud)</option>
                      <option value="auto">auto (Ollama then Groq)</option>
                    </select>
                  ) : (
                    <input
                      type={t === 'int' || t === 'float' ? 'number' : 'text'}
                      step={t === 'float' ? '0.01' : '1'}
                      value={v ?? ''}
                      onChange={e => updateField(k, e.target.value)}
                      style={baseStyle}
                    />
                  )}
                  {hint && <div style={{ fontSize: 10, opacity: 0.55, fontFamily: 'var(--font-mono)', lineHeight: 1.45 }}>{hint}</div>}
                </div>
              );
            })}
          </div>
          <div style={{ display: 'flex', gap: 8, padding: '12px 14px', borderTop: '2px solid #000' }}>
            <button className="btn-brutal" disabled={!dirty || busy} onClick={save}
              style={{ background: dirty ? 'var(--cyan)' : '#ddd', color: '#000', fontSize: 12 }}>
              {busy ? 'SAVING…' : 'SAVE CHANGES'}
            </button>
            <button className="btn-brutal" disabled={!dirty || busy} onClick={reset} style={{ fontSize: 12 }}>RESET</button>
            <div style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.55, alignSelf: 'center' }}>
              Edits apply live to the running pipeline. Server restart resets to env defaults.
            </div>
          </div>
        </div>
      </div>

      <div className="widgets-grid mt-20">
        <div className="widget-card">
          <div className="widget-title">TELEGRAM WEBHOOK (ngrok)</div>
          <div style={{ padding: 14, fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.7 }}>
            <div><strong>Tunnel:</strong> {whStatus?.tunnel_open ? '◉ OPEN' : '○ CLOSED'}</div>
            <div><strong>Public URL:</strong> {whStatus?.public_url || '—'}</div>
            <div><strong>Registered:</strong> {whStatus?.registered_webhook || '—'}</div>
            <div><strong>Telegram pending updates:</strong> {whStatus?.telegram_getWebhookInfo?.result?.pending_update_count ?? '—'}</div>
            <div><strong>Telegram url-on-record:</strong> {whStatus?.telegram_getWebhookInfo?.result?.url || '—'}</div>
          </div>
          <div style={{ display: 'flex', gap: 8, padding: '12px 14px', borderTop: '2px solid #000' }}>
            <button className="btn-brutal" disabled={whBusy} onClick={setupWebhook} style={{ background: 'var(--green)', color: '#000', fontSize: 12 }}>
              {whBusy ? '…' : (whStatus?.tunnel_open ? 'REFRESH TUNNEL' : 'START TUNNEL + REGISTER')}
            </button>
            <button className="btn-brutal" disabled={whBusy || !whStatus?.tunnel_open} onClick={teardownWebhook} style={{ fontSize: 12 }}>TEARDOWN</button>
            <button className="btn-brutal" onClick={() => apiFetch('/api/traffic-violations/telegram/webhook-status', TRAFFIC_AUTH).then(setWhStatus)} style={{ fontSize: 12, marginLeft: 'auto' }}>REFRESH STATUS</button>
          </div>
        </div>

        <div className="widget-card">
          <div className="widget-title">RECOGNISED VIOLATION TYPES</div>
          <div style={{ padding: 14, fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.9 }}>
            {Object.entries(violationTypes).map(([k, v]) => (
              <div key={k} style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 12, padding: '2px 0' }}>
                <span style={{ opacity: 0.55 }}>{k}</span>
                <strong>{v}</strong>
              </div>
            ))}
            <div style={{ marginTop: 12, fontSize: 10, opacity: 0.55 }}>
              Vision returns one of these as <code>violation_type</code>. Anything else is dropped before insert.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

/* ======================================================================
   GOVERNMENT MODULE 4 — ANOMALY MONITORING
   Tabs: Alerts · Sensors · Map · Work Orders · Analytics
   ====================================================================== */
const AnomalyMonitoring = ({ onBack }) => {
  const [tab, setTab] = React.useState('alerts');
  const tabs = [
    { key: 'alerts',    label: 'ALERTS', badge: 7 },
    { key: 'sensors',   label: 'SENSOR FLEET' },
    { key: 'map',       label: 'CITY MAP' },
    { key: 'workorders',label: 'WORK ORDERS' },
    { key: 'analytics', label: 'ANALYTICS' },
  ];
  return (
    <div className="subpage fade-in">
      <SubPageHeader
        title="ANOMALY MONITORING"
        gatewayId="GATEWAY_04"
        subtitle="IOT FUSION · ISOLATION FOREST · 847 SENSORS · 7 OPEN ALERTS"
        accentColor="var(--red)"
        onBack={onBack}
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn-brutal" style={{ padding: '8px 14px', fontSize: 12 }}>◉ AUTO-SCAN</button>
            <button className="btn-brutal action-btn red" style={{ padding: '8px 14px', fontSize: 12, width: 'auto' }}>RUN FULL SCAN</button>
          </div>
        }
      />
      <Tabs tabs={tabs} active={tab} onChange={setTab} accent="var(--red)" />
      {tab === 'alerts'     && <AnomalyAlerts />}
      {tab === 'sensors'    && <AnomalySensors />}
      {tab === 'map'        && <AnomalyMap />}
      {tab === 'workorders' && <AnomalyWorkOrders />}
      {tab === 'analytics'  && <AnomalyAnalytics />}
    </div>
  );
};

const AnomalyAlerts = () => {
  const alerts = [
    { id: 'ANM-244431', title: 'STRUCTURAL DEGRADATION',  cat: 'Bridge',     loc: 'Sector 12 · R4 Road Junction', time: '2026-04-22, 19:16', conf: 89, severity: 'CRITICAL', ack: false },
    { id: 'ANM-302108', title: 'TRAFFIC SIGNAL MALFUNCTION', cat: 'Traffic', loc: 'Sector 13 · N6 Road Junction', time: '2026-04-24, 16:16', conf: 85, severity: 'HIGH',     ack: false },
    { id: 'ANM-076235', title: 'SEWAGE SYSTEM BLOCKAGE',   cat: 'Drainage',  loc: 'Highway NH-14 · Km 34',        time: '2026-04-22, 23:15', conf: 78, severity: 'HIGH',     ack: true  },
    { id: 'ANM-094172', title: 'BUILDING VIBRATION ANOMALY', cat: 'Structure', loc: 'Sector 23 · Power Substation', time: '2026-04-22, 12:10', conf: 96, severity: 'HIGH',   ack: false },
    { id: 'ANM-187342', title: 'WATER PRESSURE DROP',      cat: 'Water',     loc: 'Zone B · Reservoir 2',         time: '2026-04-23, 09:22', conf: 82, severity: 'MEDIUM',  ack: false },
    { id: 'ANM-201554', title: 'AIR QUALITY SPIKE',        cat: 'AQI',       loc: 'Sector 7 · Industrial',        time: '2026-04-23, 14:45', conf: 91, severity: 'MEDIUM',  ack: true },
    { id: 'ANM-223678', title: 'POWER DRAW ANOMALY',       cat: 'Electric', loc: 'Sector 15 · Substation 3',      time: '2026-04-23, 18:33', conf: 74, severity: 'LOW',     ack: false },
  ];
  return (
    <div className="tab-pane">
      <div className="anomaly-stats-row">
        <div className="anomaly-stat"><div className="anomaly-stat-val">7</div><div className="anomaly-stat-lbl">TOTAL OPEN</div></div>
        <div className="anomaly-stat"><div className="anomaly-stat-val" style={{ color: 'var(--red)' }}>1</div><div className="anomaly-stat-lbl">CRITICAL</div></div>
        <div className="anomaly-stat"><div className="anomaly-stat-val" style={{ color: 'var(--gold)' }}>3</div><div className="anomaly-stat-lbl">HIGH</div></div>
        <div className="anomaly-stat"><div className="anomaly-stat-val" style={{ color: 'var(--cyan)' }}>2</div><div className="anomaly-stat-lbl">MEDIUM</div></div>
        <div className="anomaly-stat"><div className="anomaly-stat-val">4</div><div className="anomaly-stat-lbl">UNACKED</div></div>
      </div>
      <div className="alert-list">
        {alerts.map((a, i) => (
          <div key={a.id} className={`alert-card-lg ${a.severity.toLowerCase()} ${a.ack ? 'acked' : ''}`} style={{ animationDelay: `${i * 0.05}s` }}>
            <div className="alert-left-bar" style={{ background: a.severity === 'CRITICAL' ? 'var(--red)' : a.severity === 'HIGH' ? 'var(--gold)' : 'var(--cyan)' }}></div>
            <div className="alert-body">
              <div className="alert-header-row">
                <div style={{ flex: 1 }}>
                  <div className="alert-title-lg">{a.title}</div>
                  <div className="alert-meta-lg">{a.id} · {a.cat}</div>
                </div>
                <SeverityBadge level={a.severity} />
                {a.ack && <Badge variant="green">ACKED</Badge>}
              </div>
              <div className="alert-loc-row">
                <span>📍 {a.loc}</span>
                <span>🕐 {a.time}</span>
              </div>
              <ConfidenceBar value={a.conf} />
              <div className="action-row">
                <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>VIEW SENSOR DATA</button>
                <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>ROOT CAUSE</button>
                {!a.ack && <button className="btn-brutal action-btn" style={{ fontSize: 11, padding: '6px 12px', width: 'auto', background: 'var(--gold)', color: '#000' }}>ACK</button>}
                <button className="btn-brutal action-btn" style={{ fontSize: 11, padding: '6px 12px', width: 'auto', background: 'var(--red)', color: '#fff' }}>CREATE WORK ORDER</button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const AnomalySensors = () => {
  const sensors = [
    { id: 'SNS-0147', type: 'Bridge Vibration', zone: 'Sector 12', battery: 87, uptime: 99.8, health: 'healthy', lastSeen: 'just now' },
    { id: 'SNS-0243', type: 'Water Pressure',   zone: 'Zone B',    battery: 62, uptime: 99.1, health: 'healthy', lastSeen: '30 sec' },
    { id: 'SNS-0358', type: 'AQI Particulate',  zone: 'Sector 7',  battery: 14, uptime: 92.3, health: 'warning', lastSeen: '2 min'  },
    { id: 'SNS-0421', type: 'Traffic Signal',   zone: 'Sector 13', battery: 94, uptime: 99.9, health: 'healthy', lastSeen: 'just now' },
    { id: 'SNS-0505', type: 'Sewage Level',     zone: 'NH-14',     battery: 78, uptime: 99.4, health: 'healthy', lastSeen: '45 sec' },
    { id: 'SNS-0618', type: 'Power Meter',      zone: 'Sector 15', battery: 0,  uptime: 0,    health: 'offline', lastSeen: '3 hr'   },
    { id: 'SNS-0729', type: 'Structure Vib',    zone: 'Sector 23', battery: 55, uptime: 98.7, health: 'healthy', lastSeen: '1 min'  },
    { id: 'SNS-0833', type: 'AQI NO2',          zone: 'Sector 3',  battery: 72, uptime: 99.2, health: 'healthy', lastSeen: '20 sec' },
  ];
  return (
    <div className="tab-pane">
      <div className="kpi-grid-4">
        <KPICard label="TOTAL SENSORS"   value="847"   color="var(--gold)" />
        <KPICard label="ONLINE"          value="832"   color="var(--green)" />
        <KPICard label="WARNINGS"        value="11"    color="var(--gold)" />
        <KPICard label="OFFLINE"         value="4"     color="var(--red)" />
      </div>
      <div className="widget-card mt-20">
        <DataTable
          onRowClick={r => console.log(r)}
          columns={[
            { key: 'id',      label: 'SENSOR ID', width: 110 },
            { key: 'type',    label: 'TYPE',      width: 160 },
            { key: 'zone',    label: 'ZONE',      width: 120 },
            { key: 'battery', label: 'BATTERY',   width: 140, render: v => v === 0 ? <span style={{ color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>OFFLINE</span> : <ConfidenceBar value={v} /> },
            { key: 'uptime',  label: 'UPTIME',    width: 100, align: 'right', render: v => `${v}%` },
            { key: 'health',  label: 'HEALTH',    width: 120, render: v => <StatusPill status={v === 'healthy' ? 'online' : v === 'warning' ? 'busy' : 'alert'} label={v.toUpperCase()} /> },
            { key: 'lastSeen', label: 'LAST SEEN', width: 100, align: 'right' },
          ]}
          rows={sensors}
        />
      </div>
    </div>
  );
};

const AnomalyMap = () => {
  const pins = [
    { x: 90, y: 80, color: 'var(--red)',   pulse: true,  label: 'S12' },
    { x: 200, y: 140, color: 'var(--gold)', pulse: true, label: 'S13' },
    { x: 320, y: 210, color: 'var(--cyan)', pulse: false, label: 'NH14' },
    { x: 60, y: 200, color: 'var(--red)',   pulse: false, label: 'S7' },
    { x: 260, y: 90, color: 'var(--green)', pulse: false, label: 'S23' },
    { x: 180, y: 230, color: 'var(--gold)', pulse: false, label: 'Z-B' },
  ];
  return (
    <div className="tab-pane">
      <div className="map-layout">
        <div>
          <MapMock pins={pins} title="CITY MAP · SENSOR & ALERT OVERLAY" />
          <div className="map-legend">
            <span><span className="status-dot red"></span> Critical alert</span>
            <span><span className="status-dot" style={{ background: 'var(--gold)' }}></span> High alert</span>
            <span><span className="status-dot" style={{ background: 'var(--cyan)' }}></span> Medium alert</span>
            <span><span className="status-dot green"></span> Nominal</span>
          </div>
        </div>
        <div className="map-sidebar">
          <div className="widget-card">
            <div className="widget-title">ZONES OVERVIEW</div>
            {[
              { zone: 'Sector 12', alerts: 3, sensors: 42, status: 'critical' },
              { zone: 'Sector 13', alerts: 1, sensors: 38, status: 'warning' },
              { zone: 'Sector 7',  alerts: 1, sensors: 52, status: 'critical' },
              { zone: 'NH-14',     alerts: 1, sensors: 18, status: 'warning' },
              { zone: 'Sector 23', alerts: 1, sensors: 28, status: 'warning' },
              { zone: 'Zone B',    alerts: 1, sensors: 24, status: 'warning' },
            ].map(z => (
              <div key={z.zone} className="zone-row">
                <StatusPill status={z.status === 'critical' ? 'alert' : 'busy'} label="" />
                <span style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 500 }}>{z.zone}</span>
                <span className="small-meta">{z.sensors} sensors</span>
                <Badge variant={z.alerts > 2 ? 'red' : 'gold'}>{z.alerts} alert{z.alerts > 1 ? 's' : ''}</Badge>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

const AnomalyWorkOrders = () => {
  const orders = [
    { id: 'WO-3821', alert: 'ANM-244431', task: 'Inspect bridge structural sensors',  assignee: 'PWD Team A', sla: '6h left', priority: 'CRITICAL', status: 'in_progress' },
    { id: 'WO-3820', alert: 'ANM-302108', task: 'Replace traffic signal controller',   assignee: 'Traffic-5', sla: '18h left', priority: 'HIGH',  status: 'assigned' },
    { id: 'WO-3819', alert: 'ANM-094172', task: 'Vibration root-cause investigation',  assignee: 'Structural Eng.', sla: '2d left', priority: 'HIGH', status: 'in_progress' },
    { id: 'WO-3818', alert: 'ANM-076235', task: 'Unblock sewage line NH-14 Km 34',     assignee: 'Sanitation-3', sla: 'OVERDUE', priority: 'HIGH', status: 'in_progress' },
    { id: 'WO-3817', alert: 'ANM-201554', task: 'AQI monitor calibration',             assignee: 'Env. Dept', sla: '4d left', priority: 'MEDIUM', status: 'assigned' },
  ];
  return (
    <div className="tab-pane">
      <div className="widget-card">
        <DataTable
          onRowClick={r => console.log(r)}
          columns={[
            { key: 'id',       label: 'ORDER',   width: 100 },
            { key: 'alert',    label: 'ALERT',   width: 130 },
            { key: 'task',     label: 'TASK' },
            { key: 'assignee', label: 'ASSIGNED',width: 150 },
            { key: 'priority', label: 'PRIORITY', width: 100, render: v => <Badge variant={v === 'CRITICAL' ? 'red' : v === 'HIGH' ? 'gold' : 'default'}>{v}</Badge> },
            { key: 'sla',      label: 'SLA',     width: 110, render: v => <span style={{ color: v === 'OVERDUE' ? 'var(--red)' : 'inherit', fontWeight: v === 'OVERDUE' ? 700 : 400 }}>{v}</span> },
            { key: 'status',   label: 'STATUS',  width: 140, render: v => <StatusPill status={v === 'in_progress' ? 'busy' : 'online'} label={v.replace('_', ' ').toUpperCase()} /> },
          ]}
          rows={orders}
        />
      </div>
    </div>
  );
};

const AnomalyAnalytics = () => {
  const chartData = Array.from({ length: 24 }, () => Math.floor(Math.random() * 10));
  return (
    <div className="tab-pane">
      <div className="kpi-grid-4">
        <KPICard label="MTTR"            value="4.2h"  color="var(--gold)" data={[6, 5.5, 5, 4.8, 4.5, 4.3, 4.2]} delta="-30%" deltaDir="down" />
        <KPICard label="PREVENTED DAYS"  value="48"    color="var(--green)" />
        <KPICard label="FALSE POSITIVES" value="6.1%"  color="var(--cyan)" />
        <KPICard label="CRITICAL ASSETS" value="24"    color="var(--red)" />
      </div>
      <div className="widgets-grid mt-20">
        <MiniChart title="24-HOUR ANOMALY TIMELINE" data={chartData} color="var(--red)" />
        <div className="widget-card">
          <div className="widget-title">SEVERITY DISTRIBUTION</div>
          {[{ l: 'CRITICAL', v: 1, c: 'var(--red)' }, { l: 'HIGH', v: 5, c: 'var(--gold)' }, { l: 'MEDIUM', v: 2, c: 'var(--cyan)' }, { l: 'LOW', v: 3, c: 'var(--green)' }].map((s, i) => (
            <div key={i} className="progress-row">
              <span>{s.l}</span>
              <div className="progress-bar"><div className="progress-fill" style={{ width: `${(s.v / 11) * 100}%`, background: s.c }}></div></div>
              <span className="progress-val">{s.v}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="widgets-grid mt-20">
        <div className="widget-card">
          <div className="widget-title">TOP CATEGORIES</div>
          <Donut
            segments={[
              { label: 'Structure', value: 32, color: 'var(--red)' },
              { label: 'Traffic',   value: 22, color: 'var(--cyan)' },
              { label: 'Water',     value: 18, color: 'var(--green)' },
              { label: 'AQI',       value: 14, color: 'var(--gold)' },
              { label: 'Power',     value: 14, color: '#888' },
            ]}
            centerValue="47"
            centerLabel="30D"
          />
        </div>
        <div className="widget-card">
          <div className="widget-title">CRITICAL ASSETS · UPTIME</div>
          <div className="asset-list">
            {[
              { asset: 'Sector-12 Bridge',     uptime: 99.8, class: 'P0' },
              { asset: 'Water Reservoir 2',   uptime: 99.2, class: 'P0' },
              { asset: 'Power Substation S15', uptime: 0,    class: 'P0' },
              { asset: 'NH-14 Drainage',       uptime: 97.8, class: 'P1' },
            ].map(a => (
              <div key={a.asset} className="asset-row">
                <Badge variant={a.class === 'P0' ? 'red' : 'gold'}>{a.class}</Badge>
                <span style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 500 }}>{a.asset}</span>
                <div className="progress-bar" style={{ flex: 1, maxWidth: 120 }}><div className="progress-fill" style={{ width: `${a.uptime}%`, background: a.uptime === 0 ? 'var(--red)' : a.uptime > 99 ? 'var(--green)' : 'var(--gold)' }}></div></div>
                <span className="progress-val">{a.uptime}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

/* ======================================================================
   CITIZEN MODULE 1 — RAG CHATBOT
   Tabs: Chat · Services · History
   ====================================================================== */
const RAGChatbot = ({ onBack }) => {
  const [tab, setTab] = React.useState('chat');
  const tabs = [
    { key: 'chat',     label: 'ASSISTANT' },
    { key: 'services', label: 'SERVICE CATALOG' },
    { key: 'history',  label: 'HISTORY' },
  ];
  return (
    <div className="subpage fade-in">
      <SubPageHeader
        title="RAG CHATBOT"
        gatewayId="GATEWAY_01"
        subtitle="LOCAL RAG · OLLAMA LLAMA 3.2 · MULTILINGUAL · 247 KB ARTICLES"
        accentColor="var(--gold)"
        onBack={onBack}
      />
      <Tabs tabs={tabs} active={tab} onChange={setTab} accent="var(--gold)" />
      {tab === 'chat'     && <ChatbotChat />}
      {tab === 'services' && <ChatbotServices />}
      {tab === 'history'  && <ChatbotHistory />}
    </div>
  );
};

const ChatbotChat = () => {
  const [messages, setMessages] = React.useState([
    { role: 'bot', text: "Welcome to C.I.T.A.D.E.L. AI Assistant.\n\nI can help with:\n• Government services (Aadhaar, PAN, Passport, Voter ID, Driving License)\n• Tax filing, property records, scheme eligibility\n• Health, pension, business registration\n\nHow can I help you today?", suggestions: ['How to apply for Aadhaar?', 'PAN card status check', 'Property tax calculator', 'Ayushman Bharat scheme'] }
  ]);
  const [input, setInput] = React.useState('');
  const [typing, setTyping] = React.useState(false);
  const [lang, setLang] = React.useState('English');
  const [voice, setVoice] = React.useState(false);
  const chatRef = React.useRef(null);

  React.useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages, typing]);

  const send = (q) => {
    const query = q || input;
    if (!query.trim()) return;
    setMessages(m => [...m, { role: 'user', text: query }]);
    setInput('');
    setTyping(true);
    setTimeout(() => {
      setTyping(false);
      setMessages(m => [...m, {
        role: 'bot',
        text: "Here's what I found in the knowledge base:\n\n**Applying for Aadhaar**\n\n1. Find your nearest enrollment center (Aadhaar Seva Kendra) via uidai.gov.in\n2. Bring valid ID proof (Passport, Voter ID, Driving License) and address proof\n3. Biometric capture (fingerprints + iris + photo) takes ~15 min\n4. You receive an enrollment slip with EID\n5. Your Aadhaar card arrives in 60–90 days by post\n\nOnline tracking available at resident.uidai.gov.in using your EID.",
        sources: [
          { title: 'gov-services-2026.pdf', section: 'Section 3.2', relevance: 96 },
          { title: 'aadhaar-enrollment-faq.md', section: 'Q4–Q7', relevance: 88 },
          { title: 'uidai-circular-2026.pdf', section: 'Page 14', relevance: 82 },
        ],
        suggestions: ['How long does it take?', 'Can I update my address?', 'What if I lost my Aadhaar?', 'Book appointment'],
        confidence: 94
      }]);
    }, 1500);
  };

  return (
    <div className="chat-layout-enhanced">
      <div className="chat-sidebar-enhanced">
        <div className="widget-card compact">
          <div className="widget-title">SESSION</div>
          <div className="info-rows">
            <div className="info-row"><span>LLM:</span><span style={{ color: 'var(--green)' }}>Ollama 3.2 ✓</span></div>
            <div className="info-row"><span>Language:</span><span>{lang}</span></div>
            <div className="info-row"><span>KB Articles:</span><span>247</span></div>
            <div className="info-row"><span>Response:</span><span>~1.2s avg</span></div>
          </div>
        </div>
        <div className="widget-card compact">
          <div className="widget-title">LANGUAGE</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
            {['English', 'हिन्दी', 'தமிழ்', 'বাংলা', 'मराठी', 'తెలుగు'].map(l => (
              <button key={l} className={`chip ${lang === l ? 'selected' : ''}`} onClick={() => setLang(l)} style={{ justifyContent: 'center' }}>{l}</button>
            ))}
          </div>
          <div style={{ marginTop: 12 }}>
            <Toggle checked={voice} onChange={setVoice} label="🎙 Voice input (Beta)" />
          </div>
        </div>
        <div className="widget-card compact">
          <div className="widget-title">QUICK ACTIONS</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {['📋 Apply Aadhaar', '💳 Check PAN status', '📘 Passport renewal', '🏠 Property tax', '🎓 Scholarship finder'].map(a => (
              <button key={a} className="quick-link" onClick={() => send(a.split(' ').slice(1).join(' '))}>{a}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="chat-main-enhanced">
        <div className="chat-header">
          <span className="chat-title">🤖 OLLAMA ASSISTANT</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="status-badge green small">● ONLINE</span>
            <button className="icon-btn" title="Export chat">⬇</button>
            <button className="icon-btn" title="Clear">✕</button>
          </div>
        </div>
        <div className="chat-messages" ref={chatRef}>
          {messages.map((m, i) => (
            <React.Fragment key={i}>
              <div className={`chat-msg ${m.role}`}>
                {m.role === 'bot' && <span className="msg-avatar">🤖</span>}
                <div className="msg-bubble">
                  <div dangerouslySetInnerHTML={{ __html: m.text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>') }}></div>
                  {m.sources && (
                    <div className="msg-sources">
                      <div className="msg-sources-title">📎 SOURCES</div>
                      {m.sources.map((s, j) => (
                        <div key={j} className="source-chip">
                          <span className="source-title">{s.title}</span>
                          <span className="source-section">{s.section}</span>
                          <span className="source-rel">{s.relevance}%</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {m.confidence !== undefined && (
                    <div className="msg-footer">
                      <ConfidenceBar value={m.confidence} compact />
                      <div className="feedback-btns">
                        <button className="icon-btn small" title="Helpful">👍</button>
                        <button className="icon-btn small" title="Not helpful">👎</button>
                        <button className="icon-btn small" title="Copy">⎘</button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
              {m.suggestions && (
                <div className="msg-suggestions">
                  {m.suggestions.map(s => (
                    <button key={s} className="suggestion-chip" onClick={() => send(s)}>{s}</button>
                  ))}
                </div>
              )}
            </React.Fragment>
          ))}
          {typing && (
            <div className="chat-msg bot">
              <span className="msg-avatar">🤖</span>
              <div className="msg-bubble typing">
                <span className="typing-dots"><span></span><span></span><span></span></span>
                Thinking...
              </div>
            </div>
          )}
        </div>
        <div className="chat-input-bar">
          {voice && <button className="icon-btn" style={{ background: 'var(--red)', color: '#fff' }}>🎙</button>}
          <input className="chat-input" value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && send()} placeholder="Type your message..." />
          <button className="icon-btn" title="Attach">📎</button>
          <button className="btn-brutal action-btn gold" onClick={() => send()} style={{ padding: '8px 20px', width: 'auto' }}>SEND</button>
        </div>
      </div>
    </div>
  );
};

const ChatbotServices = () => {
  const services = [
    { cat: 'Identity', icon: '🪪', items: ['Aadhaar Enrollment', 'Aadhaar Update', 'PAN Card', 'Voter ID', 'Passport', 'Driving License'] },
    { cat: 'Tax & Revenue', icon: '💰', items: ['Income Tax', 'GST Registration', 'Property Tax', 'Road Tax', 'Professional Tax'] },
    { cat: 'Health', icon: '🏥', items: ['Ayushman Bharat', 'Vaccine Records', 'Birth Certificate', 'Death Certificate', 'Health ID'] },
    { cat: 'Education', icon: '🎓', items: ['Scholarship Portal', 'DigiLocker', 'Board Certificates', 'Student Loans'] },
    { cat: 'Business', icon: '🏢', items: ['Startup India', 'MSME Registration', 'Udyam Registration', 'Import-Export Code'] },
    { cat: 'Pension', icon: '👴', items: ['PF Balance', 'Pension Tracking', 'APY Scheme', 'NPS'] },
    { cat: 'Property', icon: '🏠', items: ['Land Records', 'Registration', 'Mutation', 'Building Plan Approval'] },
    { cat: 'Utilities', icon: '💡', items: ['Electricity Bill', 'Water Bill', 'Gas Connection', 'Sewage'] },
  ];
  const [search, setSearch] = React.useState('');
  return (
    <div className="tab-pane">
      <div className="toolbar">
        <SearchBar value={search} onChange={setSearch} placeholder="Search 50+ services..." />
      </div>
      <div className="service-grid">
        {services.map((s, i) => (
          <div key={s.cat} className="service-card" style={{ animationDelay: `${i * 0.05}s` }}>
            <div className="service-cat-header">
              <span style={{ fontSize: 22 }}>{s.icon}</span>
              <span>{s.cat}</span>
            </div>
            <div className="service-items">
              {s.items.filter(i => !search || i.toLowerCase().includes(search.toLowerCase())).map(item => (
                <button key={item} className="service-item">{item}</button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const ChatbotHistory = () => {
  const sessions = [
    { id: 1, title: 'Aadhaar enrollment process', msgs: 8,  when: '2 hours ago',  helpful: true },
    { id: 2, title: 'PAN status inquiry',          msgs: 4,  when: 'Yesterday',     helpful: true },
    { id: 3, title: 'Property tax calculation',    msgs: 12, when: '3 days ago',    helpful: true },
    { id: 4, title: 'Passport renewal timeline',   msgs: 6,  when: '1 week ago',    helpful: false },
    { id: 5, title: 'Ayushman Bharat eligibility', msgs: 10, when: '2 weeks ago',   helpful: true },
  ];
  return (
    <div className="tab-pane">
      <div className="toolbar">
        <SearchBar value="" onChange={() => {}} placeholder="Search past conversations..." />
        <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 14px' }}>⬇ EXPORT ALL</button>
      </div>
      <div className="session-list">
        {sessions.map((s, i) => (
          <div key={s.id} className="session-item" style={{ animationDelay: `${i * 0.05}s` }}>
            <span style={{ fontSize: 20 }}>💬</span>
            <div style={{ flex: 1 }}>
              <div className="session-title">{s.title}</div>
              <div className="session-meta">{s.msgs} messages · {s.when}</div>
            </div>
            {s.helpful ? <Badge variant="green">👍 HELPFUL</Badge> : <Badge variant="default">👎 NOT HELPFUL</Badge>}
            <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>RESUME</button>
            <button className="icon-btn">⋯</button>
          </div>
        ))}
      </div>
    </div>
  );
};

/* ======================================================================
   CITIZEN MODULE 2 — FAKE NEWS DETECTOR
   Tabs: Analyze · Bulk · History · Learn
   ====================================================================== */
const FakeNewsDetector = ({ onBack }) => {
  const [tab, setTab] = React.useState('analyze');
  const tabs = [
    { key: 'analyze', label: 'ANALYZE' },
    { key: 'bulk',    label: 'BULK CHECK' },
    { key: 'history', label: 'HISTORY' },
    { key: 'learn',   label: 'LEARN' },
  ];
  return (
    <div className="subpage fade-in">
      <SubPageHeader
        title="FAKE NEWS DETECTOR"
        gatewayId="GATEWAY_02"
        subtitle="BERT + TF-IDF · CLAIM EXTRACTION · SOURCE CREDIBILITY · BIAS ANALYSIS"
        accentColor="var(--red)"
        onBack={onBack}
      />
      <Tabs tabs={tabs} active={tab} onChange={setTab} accent="var(--red)" />
      {tab === 'analyze' && <FakeNewsAnalyze />}
      {tab === 'bulk'    && <FakeNewsBulk />}
      {tab === 'history' && <FakeNewsHistory />}
      {tab === 'learn'   && <FakeNewsLearn />}
    </div>
  );
};

const FakeNewsAnalyze = () => {
  const [mode, setMode] = React.useState('TEXT');
  const [text, setText] = React.useState('');
  const [analyzing, setAnalyzing] = React.useState(false);
  const [result, setResult] = React.useState(null);

  const verify = () => {
    if (!text.trim()) return;
    setAnalyzing(true);
    setTimeout(() => {
      setAnalyzing(false);
      setResult({
        verdict: 'LIKELY FAKE',
        confidence: 87,
        claims: [
          { text: 'Government announces free smartphones for all citizens', verdict: 'FALSE',       conf: 96, notes: 'No official source found; schema matches known hoax pattern' },
          { text: 'Distribution starts next week',                          verdict: 'UNVERIFIED', conf: 62, notes: 'Specific date with no confirming source' },
          { text: 'Register via link in message',                           verdict: 'SUSPICIOUS', conf: 94, notes: 'Phishing indicator — non-gov domain' },
        ],
        sourceCred: { score: 18, publisher: 'unverified-news.info', age: 'Domain registered 14 days ago', trustRating: 'LOW' },
        bias: { left: 12, center: 22, right: 66 },
        sentiment: { positive: 12, negative: 68, neutral: 20 },
        redFlags: [
          'Extreme emotional language detected',
          'No credible source cited',
          'Specific amounts without verification',
          'Calls to immediate action',
          'Similar to known misinformation template #4471',
        ],
        manipulation: { clickbait: 82, urgency: 78, authorityClaim: 45, emotional: 88 },
        relatedArticles: [
          { title: 'Fact-check: No free phone scheme from government', src: 'PIB Fact Check', date: '2026-03-18' },
          { title: 'Similar scam circulated in 2024',                  src: 'TruthSpy India',  date: '2024-11-02' },
        ]
      });
    }, 2000);
  };

  return (
    <div className="tab-pane">
      <div className="grid-3-col">
        <div className="col-panel left-panel">
          <div className="panel-header" style={{ background: 'var(--red)', color: '#fff' }}>CONTENT INPUT</div>
          <div className="panel-body">
            <SegmentedControl options={['TEXT', 'URL', 'IMAGE', 'VIDEO']} value={mode} onChange={setMode} accent="var(--red)" />
            <textarea className="brutal-textarea mt-14" rows={8} placeholder={mode === 'TEXT' ? 'Paste article text or news content...' : mode === 'URL' ? 'https://example.com/article' : 'Upload or paste media URL'} value={text} onChange={e => setText(e.target.value)}></textarea>
            <div className="checkbox-row">
              <label><input type="checkbox" defaultChecked /> Source credibility check</label>
              <label><input type="checkbox" defaultChecked /> Claim-by-claim analysis</label>
              <label><input type="checkbox" defaultChecked /> Bias detection</label>
              <label><input type="checkbox" /> Deepfake detection {mode === 'IMAGE' || mode === 'VIDEO' ? '' : '(requires media)'}</label>
              <label><input type="checkbox" defaultChecked /> Cross-reference fact checkers</label>
            </div>
            <button className="btn-brutal action-btn red mt-20" onClick={verify} disabled={analyzing}>
              {analyzing ? 'VERIFYING...' : 'VERIFY AUTHENTICITY'}
            </button>
            <div className="model-info-bar mt-20">
              <span>NLP: <strong>BERT-base</strong></span>
              <span>Accuracy: <strong style={{ color: 'var(--green)' }}>92.3%</strong></span>
              <span>Last trained: <strong>2026-04-18</strong></span>
            </div>
          </div>
        </div>
        <div className="col-panel" style={{ gridColumn: 'span 2' }}>
          <div className="panel-header" style={{ background: '#111', color: '#fff' }}>ANALYSIS RESULT</div>
          <div className="panel-body">
            {!result ? (
              <EmptyState icon="📰" title="NO ANALYSIS YET" description="Paste an article, URL, or upload media to run full credibility analysis with claim extraction, source scoring, and bias detection." />
            ) : (
              <>
                <div className={`verdict-big ${result.verdict.includes('FAKE') ? 'fake' : 'real'}`}>
                  <div className="verdict-icon">{result.verdict.includes('FAKE') ? '⚠' : '✓'}</div>
                  <div>
                    <div className="verdict-label">{result.verdict}</div>
                    <div className="verdict-conf">Confidence: {result.confidence}%</div>
                  </div>
                  <button className="btn-brutal" style={{ marginLeft: 'auto', fontSize: 11, padding: '6px 14px' }}>⚠ REPORT</button>
                </div>
                <div className="section-divider mt-14"><span>CLAIM-BY-CLAIM</span><span className="small-meta">{result.claims.length} claims</span></div>
                <div className="claim-list">
                  {result.claims.map((c, i) => (
                    <div key={i} className={`claim-card ${c.verdict.toLowerCase()}`}>
                      <div className="claim-top">
                        <span className={`claim-verdict-badge ${c.verdict.toLowerCase()}`}>{c.verdict}</span>
                        <span className="claim-conf">{c.conf}%</span>
                      </div>
                      <div className="claim-text">"{c.text}"</div>
                      <div className="claim-notes">{c.notes}</div>
                    </div>
                  ))}
                </div>
                <div className="widgets-grid mt-20">
                  <div className="analysis-widget">
                    <div className="widget-title">SOURCE CREDIBILITY</div>
                    <div style={{ textAlign: 'center' }}><ProgressRing value={result.sourceCred.score} color="var(--red)" /></div>
                    <div className="source-details">
                      <div><span>Publisher</span><strong>{result.sourceCred.publisher}</strong></div>
                      <div><span>Domain</span><strong>{result.sourceCred.age}</strong></div>
                      <div><span>Trust Rating</span><Badge variant="red">{result.sourceCred.trustRating}</Badge></div>
                    </div>
                  </div>
                  <div className="analysis-widget">
                    <div className="widget-title">BIAS PROFILE</div>
                    <div className="bias-bar">
                      <div className="bias-seg" style={{ width: `${result.bias.left}%`,   background: '#3B82F6' }}>L</div>
                      <div className="bias-seg" style={{ width: `${result.bias.center}%`, background: '#888' }}>C</div>
                      <div className="bias-seg" style={{ width: `${result.bias.right}%`,  background: '#EF4444' }}>R</div>
                    </div>
                    <div className="bias-labels"><span>LEFT</span><span>CENTER</span><span>RIGHT</span></div>
                    <div className="widget-title mt-14">MANIPULATION</div>
                    {Object.entries(result.manipulation).map(([k, v]) => (
                      <div key={k} className="manipulation-row">
                        <span>{k.toUpperCase()}</span>
                        <div className="progress-bar"><div className="progress-fill" style={{ width: `${v}%`, background: v > 70 ? 'var(--red)' : v > 40 ? 'var(--gold)' : 'var(--green)' }}></div></div>
                        <span className="progress-val">{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="section-divider mt-20"><span>RED FLAGS</span></div>
                <div className="flags-list">
                  {result.redFlags.map((f, i) => <div key={i} className="flag-item">⚠ {f}</div>)}
                </div>
                <div className="section-divider mt-20"><span>RELATED FACT-CHECKS</span></div>
                <div className="related-list">
                  {result.relatedArticles.map((a, i) => (
                    <div key={i} className="related-item">
                      <div>
                        <div className="related-title">{a.title}</div>
                        <div className="related-src">{a.src} · {a.date}</div>
                      </div>
                      <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>READ</button>
                    </div>
                  ))}
                </div>
                <div className="action-row mt-20">
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }}>⬇ EXPORT REPORT</button>
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }}>🔗 SHARE</button>
                  <button className="btn-brutal action-btn" style={{ fontSize: 11, padding: '8px 14px', width: 'auto', background: 'var(--red)', color: '#fff' }}>⚠ REPORT TO PIB</button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

const FakeNewsBulk = () => {
  const [urls, setUrls] = React.useState('https://unverified.info/free-phones\nhttps://trusted.gov.in/pib-statement\nhttps://questionable.blog/vaccine-hoax');
  const [results, setResults] = React.useState(null);
  const run = () => {
    const list = urls.split('\n').filter(u => u.trim());
    setResults(list.map((u, i) => ({
      url: u,
      verdict: i % 3 === 0 ? 'FAKE' : i % 3 === 1 ? 'REAL' : 'UNCERTAIN',
      conf: 60 + Math.floor(Math.random() * 38),
    })));
  };
  return (
    <div className="tab-pane">
      <div className="widgets-grid">
        <div className="widget-card">
          <div className="widget-title">BATCH URL LIST</div>
          <textarea className="brutal-textarea" rows={10} value={urls} onChange={e => setUrls(e.target.value)} placeholder="One URL per line..."></textarea>
          <div className="action-row mt-14">
            <button className="btn-brutal" style={{ fontSize: 11, padding: '8px 14px' }}>⬆ UPLOAD CSV</button>
            <button className="btn-brutal action-btn red" style={{ fontSize: 12, padding: '8px 18px', width: 'auto' }} onClick={run}>RUN BATCH ANALYSIS</button>
          </div>
        </div>
        <div className="widget-card">
          <div className="widget-title">RESULTS</div>
          {!results ? <EmptyState icon="📊" description="Batch analysis results will appear here" /> : (
            <div className="bulk-results">
              {results.map((r, i) => (
                <div key={i} className="bulk-row">
                  <span className="bulk-url">{r.url}</span>
                  <Badge variant={r.verdict === 'FAKE' ? 'red' : r.verdict === 'REAL' ? 'green' : 'gold'}>{r.verdict}</Badge>
                  <span className="bulk-conf">{r.conf}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const FakeNewsHistory = () => {
  const history = [
    { id: 1, title: 'Free phone giveaway claim',     verdict: 'FAKE',      conf: 96, date: '2 hours ago' },
    { id: 2, title: 'PIB official scheme notice',    verdict: 'REAL',      conf: 98, date: 'Yesterday' },
    { id: 3, title: 'Petrol price drop rumor',       verdict: 'UNCERTAIN', conf: 58, date: '3 days ago' },
    { id: 4, title: 'Vaccine side-effect article',   verdict: 'FAKE',      conf: 89, date: '1 week ago' },
    { id: 5, title: 'Budget announcement summary',   verdict: 'REAL',      conf: 95, date: '2 weeks ago' },
  ];
  return (
    <div className="tab-pane">
      <div className="kpi-grid-4">
        <KPICard label="CHECKS RUN"        value="47" color="var(--gold)" />
        <KPICard label="FAKE DETECTED"     value="18" color="var(--red)" />
        <KPICard label="VERIFIED REAL"     value="21" color="var(--green)" />
        <KPICard label="REPORTED TO PIB"   value="9"  color="var(--cyan)" />
      </div>
      <div className="widget-card mt-20">
        <div className="widget-title">PAST CHECKS</div>
        <DataTable
          columns={[
            { key: 'title',   label: 'TITLE' },
            { key: 'verdict', label: 'VERDICT', width: 130, render: v => <Badge variant={v === 'FAKE' ? 'red' : v === 'REAL' ? 'green' : 'gold'}>{v}</Badge> },
            { key: 'conf',    label: 'CONFIDENCE', width: 140, render: v => <ConfidenceBar value={v} compact /> },
            { key: 'date',    label: 'WHEN', width: 120, align: 'right' },
          ]}
          rows={history}
        />
      </div>
    </div>
  );
};

const FakeNewsLearn = () => (
  <div className="tab-pane">
    <div className="widgets-grid">
      <div className="widget-card">
        <div className="widget-title">🚩 COMMON RED FLAGS</div>
        <div className="flag-guide">
          {[
            { t: 'EXTREME HEADLINES', d: 'ALL CAPS, excessive exclamation points, shocking claims' },
            { t: 'EMOTIONAL MANIPULATION', d: 'Fear, outrage, guilt-tripping to bypass critical thinking' },
            { t: 'NO SOURCES', d: 'Claims without citing reputable outlets, officials, or data' },
            { t: 'SUSPICIOUS DOMAINS', d: 'Unusual URLs (.info, newly registered, typo-squatting)' },
            { t: 'URGENT CALLS TO ACT', d: '"Share before it\'s deleted!", "Act now!"' },
            { t: 'ANONYMOUS QUOTES', d: '"Experts say", "Officials confirm" — no names given' },
          ].map((f, i) => (
            <div key={i} className="flag-guide-item">
              <div className="flag-guide-title">{f.t}</div>
              <div className="flag-guide-desc">{f.d}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="widget-card">
        <div className="widget-title">✅ TRUSTED SOURCES</div>
        <div className="trusted-list">
          {[
            { name: 'PIB Fact Check',    url: 'pib.gov.in/factcheck',     cat: 'Government' },
            { name: 'Press Information Bureau', url: 'pib.gov.in',       cat: 'Government' },
            { name: 'Boom Live',          url: 'boomlive.in',             cat: 'Independent' },
            { name: 'Alt News',           url: 'altnews.in',              cat: 'Independent' },
            { name: 'Vishvas News',       url: 'vishvasnews.com',         cat: 'Independent' },
            { name: 'The Wire FactCheck', url: 'thewire.in/factcheck',    cat: 'Independent' },
          ].map((t, i) => (
            <div key={i} className="trusted-row">
              <span style={{ color: 'var(--green)' }}>✓</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, fontFamily: 'var(--font-display)', fontSize: 13 }}>{t.name}</div>
                <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', opacity: 0.5 }}>{t.url}</div>
              </div>
              <Badge variant="default">{t.cat}</Badge>
            </div>
          ))}
        </div>
      </div>
    </div>
    <div className="widget-card mt-20">
      <div className="widget-title">📚 HOW TO VERIFY NEWS — 5-STEP GUIDE</div>
      <div className="verify-steps">
        {[
          { n: 1, t: 'Check the source',    d: 'Is it a known, reputable outlet? Check their About page and editorial standards.' },
          { n: 2, t: 'Read beyond headline', d: 'Headlines can mislead. Read the full article for context and nuance.' },
          { n: 3, t: 'Check author & date',  d: 'Anonymous articles or old news presented as current are red flags.' },
          { n: 4, t: 'Look at sources cited', d: 'Credible news cites primary sources — officials, documents, data.' },
          { n: 5, t: 'Search other outlets',  d: 'If only one source reports it, be skeptical. Check 2-3 independent outlets.' },
        ].map(s => (
          <div key={s.n} className="verify-step">
            <div className="verify-num">{s.n}</div>
            <div>
              <div className="verify-t">{s.t}</div>
              <div className="verify-d">{s.d}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

/* ======================================================================
   CITIZEN MODULE 3 — SUPPORT TICKETS
   Tabs: Submit · My Tickets · Community · Map
   ====================================================================== */
const SupportTickets = ({ onBack }) => {
  const [tab, setTab] = React.useState('submit');
  const tabs = [
    { key: 'submit',    label: 'SUBMIT NEW' },
    { key: 'mine',      label: 'MY TICKETS', badge: 4 },
    { key: 'community', label: 'COMMUNITY' },
    { key: 'map',       label: 'MAP VIEW' },
  ];
  return (
    <div className="subpage fade-in">
      <SubPageHeader
        title="SUPPORT TICKETS"
        gatewayId="GATEWAY_03"
        subtitle="AI CLASSIFICATION · AUTO-ROUTING · GPS + PHOTO + VOICE · COMMUNITY UPVOTE"
        accentColor="var(--cyan)"
        onBack={onBack}
      />
      <Tabs tabs={tabs} active={tab} onChange={setTab} accent="var(--cyan)" />
      {tab === 'submit'    && <TicketSubmit />}
      {tab === 'mine'      && <TicketMine />}
      {tab === 'community' && <TicketCommunity />}
      {tab === 'map'       && <TicketMap />}
    </div>
  );
};

const TicketSubmit = () => {
  const [subject, setSubject] = React.useState('');
  const [desc, setDesc] = React.useState('');
  const [category, setCategory] = React.useState('Auto-detect');
  const [priority, setPriority] = React.useState('AUTO');
  const [anonymous, setAnonymous] = React.useState(false);
  const [attachments, setAttachments] = React.useState([]);
  const [aiPreview, setAiPreview] = React.useState(null);
  const [toast, toastHost] = useToast();

  const templates = [
    { title: 'Road Pothole',          desc: 'There is a dangerous pothole on [Street Name] near [Landmark]. It has been there for [duration] and has caused damage to vehicles.',       cat: 'Roads' },
    { title: 'Water Supply Issue',    desc: 'We have had no water supply in [Area/Zone] since [Date/Time]. This is affecting [N] households.',                                       cat: 'Water' },
    { title: 'Streetlight Out',       desc: 'The streetlight at [Location] has been out for [duration]. This creates a safety risk at night.',                                        cat: 'Electric' },
    { title: 'Garbage Pile',          desc: 'Uncollected garbage at [Location] since [Date]. Creating health hazard and bad smell in the area.',                                     cat: 'Sanitation' },
    { title: 'Stray Animals',         desc: 'Aggressive stray dogs in [Area] have been attacking residents. Request immediate intervention.',                                        cat: 'Public Safety' },
    { title: 'Public Park Maintenance', desc: 'The public park at [Location] needs [specific maintenance]. Benches broken / playground unsafe / etc.',                               cat: 'Parks' },
  ];

  const useTemplate = (t) => {
    setSubject(t.title); setDesc(t.desc); setCategory(t.cat);
    setAiPreview({
      category: t.cat,
      priority: t.cat === 'Public Safety' ? 'HIGH' : t.cat === 'Water' ? 'HIGH' : 'NORMAL',
      dept: t.cat === 'Roads' ? 'PWD' : t.cat === 'Water' ? 'Water Board' : t.cat === 'Electric' ? 'Electricity Board' : t.cat === 'Sanitation' ? 'Sanitation Dept.' : t.cat === 'Public Safety' ? 'Police' : 'Parks Dept.',
      sla: t.cat === 'Public Safety' ? '4 hours' : t.cat === 'Water' ? '8 hours' : '48 hours',
    });
  };

  const submit = () => {
    if (!subject) { toast('Please enter a subject', 'warn'); return; }
    toast(`Ticket TKT-${1024 + Math.floor(Math.random() * 99)} submitted. SLA: ${aiPreview?.sla || '48h'}`, 'success');
    setSubject(''); setDesc(''); setAttachments([]); setAiPreview(null);
  };

  return (
    <div className="tab-pane">
      <div className="grid-3-col">
        <div className="col-panel left-panel" style={{ gridColumn: 'span 2' }}>
          <div className="panel-header" style={{ background: 'var(--cyan)' }}>NEW TICKET</div>
          <div className="panel-body">
            <label className="field-label">SUBJECT *</label>
            <input className="brutal-input" placeholder="Brief description..." value={subject} onChange={e => setSubject(e.target.value)} />
            <label className="field-label mt-14">DETAILED DESCRIPTION *</label>
            <textarea className="brutal-textarea" rows={6} placeholder="Describe the issue with specifics — location, time, impact..." value={desc} onChange={e => setDesc(e.target.value)}></textarea>
            <div className="inline-fields">
              <div style={{ flex: 1 }}>
                <label className="field-label mt-14">CATEGORY</label>
                <select className="brutal-select" value={category} onChange={e => setCategory(e.target.value)}>
                  {['Auto-detect', 'Roads', 'Water', 'Electric', 'Sanitation', 'Public Safety', 'Parks', 'Health', 'Other'].map(c => <option key={c}>{c}</option>)}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label className="field-label mt-14">PRIORITY</label>
                <select className="brutal-select" value={priority} onChange={e => setPriority(e.target.value)}>
                  {['AUTO', 'LOW', 'NORMAL', 'HIGH', 'CRITICAL'].map(c => <option key={c}>{c}</option>)}
                </select>
              </div>
            </div>
            <label className="field-label mt-14">ATTACHMENTS</label>
            <div className="attach-grid">
              <button className="attach-btn" onClick={() => setAttachments(a => [...a, { type: 'photo', name: 'photo.jpg' }])}>📷<span>Photo</span></button>
              <button className="attach-btn" onClick={() => setAttachments(a => [...a, { type: 'video', name: 'video.mp4' }])}>🎬<span>Video</span></button>
              <button className="attach-btn" onClick={() => setAttachments(a => [...a, { type: 'voice', name: 'voice.ogg' }])}>🎙<span>Voice</span></button>
              <button className="attach-btn" onClick={() => setAttachments(a => [...a, { type: 'location', name: '12.97°N, 77.59°E' }])}>📍<span>GPS</span></button>
              <button className="attach-btn" onClick={() => setAttachments(a => [...a, { type: 'file', name: 'doc.pdf' }])}>📎<span>File</span></button>
            </div>
            {attachments.length > 0 && (
              <div className="file-list mt-14">
                {attachments.map((a, i) => (
                  <div key={i} className="file-item">
                    <span>{a.type === 'photo' ? '📷' : a.type === 'video' ? '🎬' : a.type === 'voice' ? '🎙' : a.type === 'location' ? '📍' : '📎'}</span>
                    <span style={{ flex: 1 }}>{a.name}</span>
                    <button className="icon-btn" onClick={() => setAttachments(attachments.filter((_, x) => x !== i))}>✕</button>
                  </div>
                ))}
              </div>
            )}
            <div style={{ marginTop: 14, padding: '10px 0', borderTop: '1px solid #eee' }}>
              <Toggle checked={anonymous} onChange={setAnonymous} label="Submit anonymously (whistleblower mode)" />
            </div>
            <button className="btn-brutal action-btn cyan mt-20" onClick={submit}>SUBMIT TICKET</button>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {aiPreview && (
            <div className="widget-card ai-preview">
              <div className="widget-title">⚡ AI PRE-ANALYSIS</div>
              <div className="ai-preview-body">
                <div className="ai-row"><span>Category:</span><Badge variant="gold">{aiPreview.category}</Badge></div>
                <div className="ai-row"><span>Priority:</span><Badge variant={aiPreview.priority === 'HIGH' ? 'red' : 'default'}>{aiPreview.priority}</Badge></div>
                <div className="ai-row"><span>Route to:</span><span style={{ fontFamily: 'var(--font-display)', fontWeight: 700 }}>{aiPreview.dept}</span></div>
                <div className="ai-row"><span>Expected SLA:</span><strong>{aiPreview.sla}</strong></div>
              </div>
            </div>
          )}
          <div className="widget-card">
            <div className="widget-title">QUICK TEMPLATES</div>
            <div className="template-list-lg">
              {templates.map(t => (
                <button key={t.title} className="template-btn-lg" onClick={() => useTemplate(t)}>
                  <div style={{ fontWeight: 700, fontFamily: 'var(--font-display)' }}>{t.title}</div>
                  <div className="template-cat-lg">{t.cat}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
      {toastHost}
    </div>
  );
};

const TicketMine = () => {
  const tickets = [
    { id: 'TKT-1024', subject: 'Pothole on Sector 12 Main Road', cat: 'Roads',    priority: 'HIGH',   status: 'in_progress', age: '2d', dept: 'PWD', step: 2 },
    { id: 'TKT-1019', subject: 'Streetlight out near Park Lane',  cat: 'Electric', priority: 'NORMAL', status: 'resolved',    age: '5d', dept: 'EB',  step: 4 },
    { id: 'TKT-1014', subject: 'Water supply outage since 6am',   cat: 'Water',    priority: 'HIGH',   status: 'assigned',    age: '1d', dept: 'WB',  step: 1 },
    { id: 'TKT-1008', subject: 'Garbage pile near school',         cat: 'Sanitation', priority: 'NORMAL', status: 'open',      age: '3h', dept: 'SD',  step: 0 },
  ];
  const [expanded, setExpanded] = React.useState(null);
  return (
    <div className="tab-pane">
      <div className="kpi-grid-4">
        <KPICard label="OPEN"        value="1" color="var(--cyan)" />
        <KPICard label="IN PROGRESS" value="2" color="var(--gold)" />
        <KPICard label="RESOLVED"    value="8" color="var(--green)" />
        <KPICard label="AVG RESOLUTION" value="36h" color="var(--red)" />
      </div>
      <div className="widgets-grid mt-20" style={{ gridTemplateColumns: '1fr' }}>
        {tickets.map((t, i) => (
          <div key={t.id} className="ticket-card-lg" style={{ animationDelay: `${i * 0.06}s` }}>
            <div className="ticket-top-row">
              <div style={{ flex: 1 }}>
                <div className="ticket-id-lg">{t.id}</div>
                <div className="ticket-subject-lg">{t.subject}</div>
                <div className="ticket-meta-row">
                  <Badge variant="default">{t.cat}</Badge>
                  <Badge variant={t.priority === 'HIGH' ? 'red' : 'default'}>{t.priority}</Badge>
                  <span className="small-meta">Dept: {t.dept}</span>
                  <span className="small-meta">Age: {t.age}</span>
                </div>
              </div>
              <StatusPill status={t.status === 'open' ? 'pending' : t.status === 'in_progress' ? 'busy' : t.status === 'resolved' ? 'online' : 'pending'} label={t.status.replace('_', ' ').toUpperCase()} />
              <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }} onClick={() => setExpanded(expanded === t.id ? null : t.id)}>{expanded === t.id ? 'COLLAPSE' : 'DETAILS'}</button>
            </div>
            {expanded === t.id && (
              <div className="ticket-expanded">
                <StatusTimeline
                  current={t.step}
                  steps={[
                    { label: 'Submitted', time: 'Apr 22, 10:14' },
                    { label: 'Assigned',  time: 'Apr 22, 10:28' },
                    { label: 'In Progress', time: 'Apr 23, 09:00' },
                    { label: 'Verification' },
                    { label: 'Resolved' },
                  ]}
                />
                <div className="ticket-updates">
                  <div className="update-item">
                    <Avatar name="PWD Team" color="var(--cyan)" size={28} />
                    <div style={{ flex: 1 }}>
                      <div className="update-text">Work order issued. Team will reach site by tomorrow morning.</div>
                      <div className="update-time">PWD Officer · 8 hours ago</div>
                    </div>
                  </div>
                  <div className="update-item">
                    <Avatar name="You" color="var(--gold)" size={28} />
                    <div style={{ flex: 1 }}>
                      <div className="update-text">Issue reported with photos.</div>
                      <div className="update-time">You · 2 days ago</div>
                    </div>
                  </div>
                </div>
                <div className="action-row">
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>➕ ADD UPDATE</button>
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>✉ CONTACT DEPT</button>
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>⭐ RATE</button>
                  <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>🔄 REOPEN</button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

const TicketCommunity = () => {
  const community = [
    { id: 'TKT-1198', title: 'Water logging during heavy rain',          loc: 'Sector 14', cat: 'Drainage',   upvotes: 47, responses: 3, age: '4h' },
    { id: 'TKT-1189', title: 'Traffic signal failure at Main Crossing',  loc: 'Sector 12', cat: 'Traffic',    upvotes: 34, responses: 5, age: '6h' },
    { id: 'TKT-1174', title: 'Illegal construction near park',            loc: 'Sector 8',  cat: 'Planning',   upvotes: 28, responses: 2, age: '1d' },
    { id: 'TKT-1156', title: 'Stray dog menace in residential area',     loc: 'Sector 21', cat: 'Public Safety', upvotes: 22, responses: 7, age: '2d' },
    { id: 'TKT-1142', title: 'School zone missing speed signage',         loc: 'Sector 9',  cat: 'Roads',      upvotes: 18, responses: 1, age: '3d' },
  ];
  return (
    <div className="tab-pane">
      <div className="toolbar">
        <SearchBar value="" onChange={() => {}} placeholder="Search community tickets..." />
        <SegmentedControl options={['TRENDING', 'NEW', 'NEARBY', 'UNRESOLVED']} value="TRENDING" onChange={() => {}} accent="var(--cyan)" />
      </div>
      <div className="community-list">
        {community.map((t, i) => (
          <div key={t.id} className="community-card" style={{ animationDelay: `${i * 0.05}s` }}>
            <div className="upvote-col">
              <button className="upvote-btn">▲</button>
              <span className="upvote-count">{t.upvotes}</span>
              <span className="upvote-label">SUPPORT</span>
            </div>
            <div style={{ flex: 1 }}>
              <div className="community-title">{t.title}</div>
              <div className="community-meta">
                <span>{t.id}</span>
                <span>📍 {t.loc}</span>
                <Badge variant="default">{t.cat}</Badge>
                <span className="small-meta">{t.responses} responses</span>
                <span className="small-meta">{t.age}</span>
              </div>
            </div>
            <div className="community-actions">
              <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>🙋 SUPPORT</button>
              <button className="btn-brutal" style={{ fontSize: 11, padding: '6px 12px' }}>💬 COMMENT</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const TicketMap = () => {
  const pins = [
    { x: 120, y: 100, color: 'var(--red)', pulse: true, label: 'TKT-1198' },
    { x: 220, y: 140, color: 'var(--gold)', label: 'TKT-1189' },
    { x: 80,  y: 200, color: 'var(--cyan)', label: 'TKT-1174' },
    { x: 310, y: 170, color: 'var(--red)', label: 'TKT-1156' },
    { x: 180, y: 220, color: 'var(--gold)', label: 'TKT-1142' },
  ];
  return (
    <div className="tab-pane">
      <div className="map-layout">
        <div>
          <MapMock pins={pins} title="NEIGHBORHOOD TICKETS · 5 KM RADIUS" />
        </div>
        <div className="map-sidebar">
          <div className="widget-card">
            <div className="widget-title">NEARBY ISSUES</div>
            <div className="nearby-list">
              {[
                { title: 'Water logging', dist: '0.4 km', sev: 'HIGH' },
                { title: 'Signal failure', dist: '0.8 km', sev: 'HIGH' },
                { title: 'Construction', dist: '1.2 km', sev: 'MEDIUM' },
                { title: 'Stray dogs', dist: '2.1 km', sev: 'HIGH' },
                { title: 'Signage missing', dist: '2.8 km', sev: 'LOW' },
              ].map(i => (
                <div key={i.title} className="nearby-row">
                  <div style={{ flex: 1 }}>
                    <div style={{ fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 600 }}>{i.title}</div>
                    <div className="small-meta">{i.dist}</div>
                  </div>
                  <SeverityBadge level={i.sev} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

/* ======================================================================
   CITIZEN MODULE 4 — EXPENSE CATEGORIZER
   Tabs: Add · Dashboard · Budget · Receipts · Reports
   ====================================================================== */
const ExpenseCategorizer = ({ onBack }) => {
  const [tab, setTab] = React.useState('dashboard');
  const tabs = [
    { key: 'add',       label: 'ADD EXPENSE' },
    { key: 'dashboard', label: 'DASHBOARD' },
    { key: 'budget',    label: 'BUDGET' },
    { key: 'receipts',  label: 'RECEIPTS' },
    { key: 'reports',   label: 'REPORTS' },
  ];
  return (
    <div className="subpage fade-in">
      <SubPageHeader
        title="EXPENSE CATEGORIZER"
        gatewayId="GATEWAY_04"
        subtitle="TF-IDF + ISOLATION FOREST · RECEIPT OCR · BANK STMT IMPORT · BUDGET ALERTS"
        accentColor="var(--gold)"
        onBack={onBack}
      />
      <Tabs tabs={tabs} active={tab} onChange={setTab} accent="var(--gold)" />
      {tab === 'add'       && <ExpenseAdd />}
      {tab === 'dashboard' && <ExpenseDashboard />}
      {tab === 'budget'    && <ExpenseBudget />}
      {tab === 'receipts'  && <ExpenseReceipts />}
      {tab === 'reports'   && <ExpenseReports />}
    </div>
  );
};

const ExpenseAdd = () => {
  const [desc, setDesc] = React.useState('');
  const [amt, setAmt] = React.useState('');
  const [cat, setCat] = React.useState('Auto-detect');
  const [merchant, setMerchant] = React.useState('');
  const [aiCat, setAiCat] = React.useState(null);
  const [toast, toastHost] = useToast();

  const predict = (txt) => {
    if (!txt) return null;
    const t = txt.toLowerCase();
    if (t.includes('uber') || t.includes('taxi') || t.includes('petrol') || t.includes('metro')) return { cat: 'Transport', conf: 94 };
    if (t.includes('swiggy') || t.includes('restaurant') || t.includes('food') || t.includes('zomato')) return { cat: 'Food & Dining', conf: 96 };
    if (t.includes('electricity') || t.includes('water') || t.includes('bill') || t.includes('gas')) return { cat: 'Utilities', conf: 92 };
    if (t.includes('amazon') || t.includes('flipkart') || t.includes('shopping')) return { cat: 'Shopping', conf: 88 };
    if (t.includes('doctor') || t.includes('medicine') || t.includes('pharmacy') || t.includes('hospital')) return { cat: 'Healthcare', conf: 91 };
    return { cat: 'Other', conf: 62 };
  };
  React.useEffect(() => {
    setAiCat(predict(desc));
  }, [desc]);

  const add = () => {
    if (!desc || !amt) { toast('Please fill description and amount', 'warn'); return; }
    toast(`Expense added: ₹${amt} — ${aiCat?.cat || cat}`, 'success');
    setDesc(''); setAmt(''); setMerchant(''); setAiCat(null);
  };

  return (
    <div className="tab-pane">
      <div className="grid-3-col">
        <div className="col-panel left-panel">
          <div className="panel-header" style={{ background: 'var(--gold)' }}>MANUAL ENTRY</div>
          <div className="panel-body">
            <label className="field-label">DESCRIPTION *</label>
            <input className="brutal-input" placeholder="e.g., Uber ride to office" value={desc} onChange={e => setDesc(e.target.value)} />
            <label className="field-label mt-14">MERCHANT</label>
            <input className="brutal-input" placeholder="e.g., Uber India Ltd." value={merchant} onChange={e => setMerchant(e.target.value)} />
            <div className="inline-fields">
              <div style={{ flex: 1 }}>
                <label className="field-label mt-14">AMOUNT (₹) *</label>
                <input className="brutal-input" type="number" placeholder="0.00" value={amt} onChange={e => setAmt(e.target.value)} />
              </div>
              <div style={{ flex: 1 }}>
                <label className="field-label mt-14">CATEGORY</label>
                <select className="brutal-select" value={cat} onChange={e => setCat(e.target.value)}>
                  {['Auto-detect', 'Food & Dining', 'Transport', 'Utilities', 'Healthcare', 'Shopping', 'Education', 'Entertainment', 'Housing', 'Insurance', 'Other'].map(c => <option key={c}>{c}</option>)}
                </select>
              </div>
            </div>
            {aiCat && (
              <div className="ai-predict">
                <span>⚡ AI predicts:</span>
                <Badge variant="gold">{aiCat.cat}</Badge>
                <span className="small-meta">{aiCat.conf}% confidence</span>
              </div>
            )}
            <button className="btn-brutal action-btn gold mt-20" onClick={add}>＋ ADD EXPENSE</button>
          </div>
        </div>
        <div className="col-panel">
          <div className="panel-header" style={{ background: 'var(--cyan)' }}>SCAN RECEIPT</div>
          <div className="panel-body">
            <div className="file-drop" style={{ background: '#fafaf8' }}>
              <span className="file-icon">📷</span>
              Drop receipt image or click to scan
            </div>
            <div className="small-meta" style={{ marginTop: 8 }}>Supports JPG, PNG, HEIC. OCR extracts merchant, items, amount, tax, and date.</div>
            <div className="ocr-preview mt-14">
              <div className="ocr-preview-title">LAST OCR</div>
              <div className="ocr-preview-body">
                <div className="ocr-row"><span>Merchant:</span><strong>Croma Electronics</strong></div>
                <div className="ocr-row"><span>Items:</span><strong>2</strong></div>
                <div className="ocr-row"><span>Subtotal:</span><strong>₹4,200</strong></div>
                <div className="ocr-row"><span>Tax (GST):</span><strong>₹756</strong></div>
                <div className="ocr-row"><span>Total:</span><strong>₹4,956</strong></div>
                <div className="ocr-row"><span>Category:</span><Badge variant="gold">Shopping</Badge></div>
              </div>
            </div>
          </div>
        </div>
        <div className="col-panel">
          <div className="panel-header" style={{ background: 'var(--red)', color: '#fff' }}>IMPORT SOURCES</div>
          <div className="panel-body">
            <button className="attach-btn" style={{ width: '100%', padding: '20px', justifyContent: 'flex-start', gap: 12, flexDirection: 'row' }}>
              <span style={{ fontSize: 28 }}>🏦</span>
              <div style={{ textAlign: 'left' }}>
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14 }}>Bank Statement</div>
                <div className="small-meta">Upload PDF/CSV · auto-parse</div>
              </div>
            </button>
            <button className="attach-btn mt-14" style={{ width: '100%', padding: '20px', justifyContent: 'flex-start', gap: 12, flexDirection: 'row' }}>
              <span style={{ fontSize: 28 }}>📱</span>
              <div style={{ textAlign: 'left' }}>
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14 }}>UPI Linked</div>
                <div className="small-meta">GPay · PhonePe · Paytm</div>
              </div>
            </button>
            <button className="attach-btn mt-14" style={{ width: '100%', padding: '20px', justifyContent: 'flex-start', gap: 12, flexDirection: 'row' }}>
              <span style={{ fontSize: 28 }}>💳</span>
              <div style={{ textAlign: 'left' }}>
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 14 }}>Credit Cards</div>
                <div className="small-meta">HDFC · ICICI · Axis</div>
              </div>
            </button>
          </div>
        </div>
      </div>
      {toastHost}
    </div>
  );
};

const ExpenseDashboard = () => {
  const spendByCat = [
    { label: 'Food & Dining', value: 8400,  color: 'var(--gold)' },
    { label: 'Transport',     value: 4200,  color: 'var(--cyan)' },
    { label: 'Utilities',     value: 3200,  color: 'var(--green)' },
    { label: 'Shopping',      value: 6800,  color: 'var(--red)' },
    { label: 'Healthcare',    value: 1500,  color: '#d946ef' },
    { label: 'Other',         value: 2300,  color: '#888' },
  ];
  const expenses = [
    { desc: 'Swiggy — Pizza',   cat: 'Food & Dining', amt: 450,  when: 'Today',     anomaly: false, tax: false },
    { desc: 'Uber — Office',    cat: 'Transport',    amt: 180,  when: 'Today',     anomaly: false, tax: false },
    { desc: 'Electricity Bill', cat: 'Utilities',    amt: 2100, when: 'Yesterday', anomaly: false, tax: true  },
    { desc: 'Amazon Order',     cat: 'Shopping',     amt: 4956, when: 'Yesterday', anomaly: true,  tax: false },
    { desc: 'Pharmacy',         cat: 'Healthcare',   amt: 680,  when: '2 days',    anomaly: false, tax: true  },
    { desc: 'Zomato Dinner',    cat: 'Food & Dining', amt: 1250, when: '3 days',    anomaly: false, tax: false },
    { desc: 'Croma — TV',       cat: 'Shopping',     amt: 45000, when: '5 days',   anomaly: true,  tax: false },
  ];
  return (
    <div className="tab-pane">
      <div className="kpi-grid-4">
        <KPICard label="TOTAL THIS MONTH" value="₹26.4k" color="var(--gold)" data={[18, 20, 22, 23, 24, 25, 26]} delta="+8%" deltaDir="up" />
        <KPICard label="AVG DAILY"         value="₹880"   color="var(--cyan)" data={[920, 890, 870, 880, 900, 880, 880]} />
        <KPICard label="TRANSACTIONS"      value="47"     color="var(--green)" data={[32, 36, 40, 42, 45, 46, 47]} />
        <KPICard label="ANOMALIES"         value="2"      color="var(--red)" delta="NEW" />
      </div>
      <div className="widgets-grid mt-20">
        <div className="widget-card">
          <div className="widget-title">BY CATEGORY · APRIL</div>
          <Donut segments={spendByCat} centerValue="₹26.4k" centerLabel="MONTHLY TOTAL" />
        </div>
        <div className="widget-card">
          <div className="widget-title">DAILY TREND (30D)</div>
          <MiniChart title="" data={[420, 680, 550, 890, 1200, 780, 950, 620, 1100, 540, 780, 920, 1400, 680, 890]} color="var(--gold)" />
          <div className="small-meta mt-14">Highest spend: ₹4,956 on Apr 22 (Amazon)</div>
        </div>
      </div>
      <div className="widget-card mt-20">
        <div className="widget-title">RECENT TRANSACTIONS</div>
        <div className="expense-list">
          {expenses.map((e, i) => (
            <div key={i} className={`expense-row-lg ${e.anomaly ? 'anomaly' : ''}`}>
              <span style={{ fontSize: 18, width: 28 }}>{e.cat === 'Food & Dining' ? '🍕' : e.cat === 'Transport' ? '🚗' : e.cat === 'Utilities' ? '💡' : e.cat === 'Shopping' ? '🛍' : e.cat === 'Healthcare' ? '💊' : '📦'}</span>
              <div style={{ flex: 1 }}>
                <div className="expense-desc-lg">{e.desc}</div>
                <div className="expense-meta"><Badge variant="default">{e.cat}</Badge>{e.tax && <Badge variant="green">TAX ✓</Badge>}{e.anomaly && <Badge variant="red">⚠ ANOMALY</Badge>}<span className="small-meta">{e.when}</span></div>
              </div>
              <div className="expense-amt-lg">₹{e.amt.toLocaleString()}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

const ExpenseBudget = () => {
  const budgets = [
    { cat: 'Food & Dining', budget: 10000, spent: 8400, icon: '🍕' },
    { cat: 'Transport',     budget: 5000,  spent: 4200, icon: '🚗' },
    { cat: 'Utilities',     budget: 4000,  spent: 3200, icon: '💡' },
    { cat: 'Shopping',      budget: 5000,  spent: 6800, icon: '🛍' },
    { cat: 'Healthcare',    budget: 2000,  spent: 1500, icon: '💊' },
    { cat: 'Entertainment', budget: 3000,  spent: 1100, icon: '🎬' },
  ];
  return (
    <div className="tab-pane">
      <div className="toolbar">
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, opacity: 0.7 }}>Monthly budgets · April 2026 · alerts when 80% used</div>
        <button className="btn-brutal action-btn gold" style={{ width: 'auto', fontSize: 11, padding: '8px 16px' }}>＋ NEW BUDGET</button>
      </div>
      <div className="budget-grid">
        {budgets.map((b, i) => {
          const pct = (b.spent / b.budget) * 100;
          const over = pct > 100;
          const near = pct > 80 && pct <= 100;
          return (
            <div key={b.cat} className={`budget-card ${over ? 'over' : near ? 'near' : ''}`} style={{ animationDelay: `${i * 0.06}s` }}>
              <div className="budget-card-top">
                <span style={{ fontSize: 26 }}>{b.icon}</span>
                <div style={{ flex: 1 }}>
                  <div className="budget-cat">{b.cat}</div>
                  <div className="budget-amt">₹{b.spent.toLocaleString()} of ₹{b.budget.toLocaleString()}</div>
                </div>
                {over && <Badge variant="red">⚠ OVER</Badge>}
                {near && <Badge variant="gold">⚠ NEAR</Badge>}
              </div>
              <div className="progress-bar-lg">
                <div className="progress-fill-lg" style={{ width: `${Math.min(100, pct)}%`, background: over ? 'var(--red)' : near ? 'var(--gold)' : 'var(--green)' }}></div>
              </div>
              <div className="budget-footer">
                <span>{Math.round(pct)}% used</span>
                <span>{over ? `₹${(b.spent - b.budget).toLocaleString()} over` : `₹${(b.budget - b.spent).toLocaleString()} left`}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const ExpenseReceipts = () => {
  const receipts = [
    { id: 1, merchant: 'Croma Electronics', amt: 4956, date: '2026-04-22', tags: ['shopping', 'gst'] },
    { id: 2, merchant: 'Swiggy',            amt: 450,  date: '2026-04-24', tags: ['food'] },
    { id: 3, merchant: 'Apollo Pharmacy',    amt: 680,  date: '2026-04-22', tags: ['healthcare', 'tax'] },
    { id: 4, merchant: 'BESCOM',             amt: 2100, date: '2026-04-21', tags: ['utilities', 'tax'] },
    { id: 5, merchant: 'Uber',               amt: 180,  date: '2026-04-24', tags: ['transport'] },
    { id: 6, merchant: 'Zomato',             amt: 1250, date: '2026-04-21', tags: ['food'] },
  ];
  return (
    <div className="tab-pane">
      <div className="toolbar">
        <SearchBar value="" onChange={() => {}} placeholder="Search receipts..." />
        <FilterBar
          filters={[
            { key: 'cat', label: 'Category', options: ['Food', 'Transport', 'Shopping', 'Utilities'] },
            { key: 'tax', label: 'Tax Deductible', options: ['Yes', 'No'] },
          ]}
          values={{}}
          onChange={() => {}}
        />
      </div>
      <div className="receipt-grid">
        {receipts.map((r, i) => (
          <div key={r.id} className="receipt-card" style={{ animationDelay: `${i * 0.05}s` }}>
            <div className="receipt-thumb">🧾</div>
            <div className="receipt-info">
              <div className="receipt-merchant">{r.merchant}</div>
              <div className="receipt-amt">₹{r.amt.toLocaleString()}</div>
              <div className="receipt-date">{r.date}</div>
              <div className="receipt-tags">
                {r.tags.map(t => <Chip key={t} label={t} />)}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const ExpenseReports = () => (
  <div className="tab-pane">
    <div className="kpi-grid-4">
      <KPICard label="FY26 SPEND"      value="₹2.84L" color="var(--gold)" />
      <KPICard label="TAX DEDUCTIBLE"  value="₹42k"  color="var(--green)" />
      <KPICard label="AVG SAVINGS"     value="22%"   color="var(--cyan)" />
      <KPICard label="NET WORTH Δ"     value="+₹18k" color="var(--red)" />
    </div>
    <div className="widgets-grid mt-20">
      <div className="widget-card">
        <div className="widget-title">MONTHLY TREND (FY26)</div>
        <MiniChart title="" data={[22, 24, 18, 26, 22, 28, 30, 24, 26, 32, 28, 26]} color="var(--gold)" labels={['APR', 'MAR']} />
      </div>
      <div className="widget-card">
        <div className="widget-title">TAX SUMMARY FY26</div>
        <div className="tax-rows">
          <div className="tax-row"><span>Section 80C Investments</span><strong>₹1,20,000</strong></div>
          <div className="tax-row"><span>Section 80D Health Insurance</span><strong>₹18,000</strong></div>
          <div className="tax-row"><span>Business Expenses</span><strong>₹24,000</strong></div>
          <div className="tax-row"><span>HRA Claims</span><strong>₹60,000</strong></div>
          <div className="tax-row total"><span>TOTAL DEDUCTIBLE</span><strong>₹2,22,000</strong></div>
        </div>
      </div>
    </div>
    <div className="action-row mt-20">
      <button className="btn-brutal" style={{ fontSize: 12, padding: '10px 16px' }}>⬇ EXPORT CSV</button>
      <button className="btn-brutal" style={{ fontSize: 12, padding: '10px 16px' }}>📊 EXPORT TO EXCEL</button>
      <button className="btn-brutal" style={{ fontSize: 12, padding: '10px 16px' }}>📧 EMAIL REPORT</button>
      <button className="btn-brutal action-btn gold" style={{ fontSize: 12, padding: '10px 16px', width: 'auto' }}>🗂 TAX PACKAGE</button>
    </div>
  </div>
);

// Export all modules
Object.assign(window, {
  DocumentIntelligence, ResumeScreening, TrafficViolations, AnomalyMonitoring,
  RAGChatbot, FakeNewsDetector, SupportTickets, ExpenseCategorizer
});
