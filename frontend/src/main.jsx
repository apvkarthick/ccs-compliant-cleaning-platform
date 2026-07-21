import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createClient } from '@supabase/supabase-js';
import { AlertCircle, BookOpen, CheckCircle2, Download, FileSpreadsheet, HelpCircle, Link2, LogOut, Mail, Pause, Play, Send, Upload, X } from 'lucide-react';
import './styles.css';

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL || '',
  import.meta.env.VITE_SUPABASE_ANON_KEY || '',
);

const API_BASE = '/api';

// Module-level token so API helpers don't need prop drilling
let _token = '';
const getAuthHeaders = () => _token ? { Authorization: `Bearer ${_token}` } : {};

// ---------------------------------------------------------------------------
// Auth hook
// ---------------------------------------------------------------------------

function useAuth() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      _token = session?.access_token || '';
      if (_token) localStorage.setItem('ccs_access_token', _token);
      setLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      _token = session?.access_token || '';
      if (_token) localStorage.setItem('ccs_access_token', _token);
      else localStorage.removeItem('ccs_access_token');
    });

    return () => subscription.unsubscribe();
  }, []);

  return { session, loading };
}

// ---------------------------------------------------------------------------
// Login page
// ---------------------------------------------------------------------------

function LoginPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);

  async function sendMagicLink(e) {
    e.preventDefault();
    setSending(true);
    setError('');
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: window.location.origin },
    });
    if (error) setError(error.message);
    else setSent(true);
    setSending(false);
  }

  if (sent) {
    return (
      <div className="login-shell">
        <div className="login-card">
          <p className="eyebrow">Compliant Cleaning Supplies</p>
          <h1>Check your inbox</h1>
          <p style={{ marginTop: '0.75rem', color: '#607080' }}>
            A login link has been sent to <strong>{email}</strong>.<br />Click it to access the platform.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="login-shell">
      <div className="login-card">
        <p className="eyebrow">Compliant Cleaning Supplies</p>
        <h1>CCS Platform</h1>
        <p style={{ marginTop: '0.5rem', marginBottom: '1.25rem', color: '#607080', fontSize: '0.9rem' }}>
          Enter your email to receive a secure login link.
        </p>
        <form onSubmit={sendMagicLink} className="login-form">
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="your@email.com"
            required
          />
          <button type="submit" className="primary" disabled={sending}>
            {sending ? 'Sending…' : 'Send login link'}
          </button>
        </form>
        {error && (
          <div className="notice error" style={{ marginTop: '1rem' }}>
            <AlertCircle size={16} /><span>{error}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

function Root() {
  const { session, loading } = useAuth();

  if (loading) return <div className="login-shell"><div className="login-card"><p>Loading…</p></div></div>;
  return <App session={session} />;
}

function App({ session }) {
  const [activeTab, setActiveTab] = useState(() => {
    if (window.location.pathname === '/email-opens') return 'email-opens';
    if (window.location.pathname === '/pdf-opens') return 'pdf-opens';
    if (window.location.pathname === '/library') return 'library';
    if (window.location.pathname === '/sites') return 'sites';
    if (window.location.pathname === '/data-management') return 'data-management';
    if (window.location.pathname === '/new-products') return 'new-products';
    return 'distribution';
  });

  function switchTab(tab) {
    const paths = {
      'email-opens': '/email-opens',
      'pdf-opens': '/pdf-opens',
      'distribution': '/app',
      'library': '/library',
      'sites': '/sites',
      'data-management': '/data-management',
      'new-products': '/new-products',
    };
    history.pushState(null, '', paths[tab] || '/app');
    setActiveTab(tab);
  }

  async function handleSignOut() {
    await supabase.auth.signOut();
  }

  return (
    <main className="shell">
      <div className="tab-bar">
        <button className={`tab ${activeTab === 'sites' ? 'active' : ''}`} onClick={() => switchTab('sites')}>Sites</button>
        <button className={`tab ${activeTab === 'new-products' ? 'active' : ''}`} onClick={() => switchTab('new-products')}>New Products</button>
        <button className={`tab ${activeTab === 'email-opens' ? 'active' : ''}`} onClick={() => switchTab('email-opens')}>Email Opens</button>
        <button className={`tab ${activeTab === 'library' ? 'active' : ''}`} onClick={() => switchTab('library')}><BookOpen size={13} style={{marginRight:4,verticalAlign:'middle'}}/>Doc Library</button>

        <a className="tab" href="/rebrand">Rebrand SDS</a>
        <button className="tab tab-signout" onClick={handleSignOut} title="Sign out">
          <LogOut size={14} />
        </button>
      </div>
      {activeTab === 'distribution' && <DistributionDesk />}
      {activeTab === 'sites' && <SiteDistribution />}
      {activeTab === 'email-opens' && <EmailOpensDashboard />}
      {activeTab === 'pdf-opens' && <PdfOpensDashboard />}
      {activeTab === 'library' && <DocumentLibrary />}
      {activeTab === 'data-management' && <DataManagement />}
      {activeTab === 'new-products' && <NewProductQueue />}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Distribution desk
// ---------------------------------------------------------------------------

function DistributionDesk() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [contactsText, setContactsText] = useState('Test Contact <test@example.com>');
  const [dryRun, setDryRun] = useState(true);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [sendResult, setSendResult] = useState(null);

  const contacts = useMemo(() => parseContacts(contactsText), [contactsText]);

  useEffect(() => {
    if (!preview?.contacts?.length) return;
    setContactsText(
      preview.contacts
        .map(c => `${c.name || c.company || 'Contact'} <${c.email}>`)
        .join('\n')
    );
  }, [preview]);

  async function uploadRegister(event) {
    event.preventDefault();
    if (!file) { setError('Select a client workbook first.'); return; }
    setLoading(true); setError(''); setSendResult(null);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await fetch(`${API_BASE}/workbook/preview`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Upload failed.');
      setPreview(data);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  async function sendTestDistribution() {
    if (!preview) { setError('Upload and preview a client workbook first.'); return; }
    if (!contacts.length) { setError('Add at least one test contact email.'); return; }
    setSending(true); setError('');
    try {
      const response = await fetch(`${API_BASE}/distribution/test-send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ preview, contacts, dry_run: dryRun }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Distribution failed.');
      setSendResult(data);
    } catch (err) { setError(err.message); }
    finally { setSending(false); }
  }

  return (
    <section className="workbench">
      <div className="topbar">
        <div>
          <p className="eyebrow">Compliant Cleaning Supplies</p>
          <h1>Distribution Desk</h1>
        </div>
        <StatusPill preview={preview} sendResult={sendResult} />
      </div>
      <div className="layout">
        <aside className="side-panel">
          <form onSubmit={uploadRegister} className="upload-box">
            <label htmlFor="register-file">Client workbook</label>
            <input id="register-file" type="file" accept=".xlsx,.xlsm"
              onChange={e => setFile(e.target.files?.[0] || null)} />
            <button type="submit" disabled={loading} className="primary">
              <Upload size={18} />{loading ? 'Uploading' : 'Preview'}
            </button>
          </form>
          <div className="contact-box">
            <label htmlFor="test-contacts">Test contacts</label>
            <textarea id="test-contacts" value={contactsText}
              onChange={e => setContactsText(e.target.value)} rows={6} />
            <div className="toggle-row">
              <input id="dry-run" type="checkbox" checked={dryRun}
                onChange={e => setDryRun(e.target.checked)} />
              <label htmlFor="dry-run">Dry run</label>
            </div>
            <button type="button" onClick={sendTestDistribution}
              disabled={sending || !preview} className="primary">
              <Send size={18} />{sending ? 'Processing' : 'Process Test Email'}
            </button>
          </div>
          {error && <div className="notice error"><AlertCircle size={18} /><span>{error}</span></div>}
        </aside>
        <section className="main-panel">
          {!preview ? <EmptyState /> : <PreviewPanel preview={preview} />}
          {sendResult && <SendResult result={sendResult} />}
        </section>
      </div>
    </section>
  );
}

function StatusPill({ preview, sendResult }) {
  if (sendResult) return <div className="status success"><CheckCircle2 size={18} />{sendResult.dry_run ? 'Dry run prepared' : 'Send requested'}</div>;
  if (preview) return <div className="status success"><CheckCircle2 size={18} />Workbook parsed</div>;
  return <div className="status neutral"><FileSpreadsheet size={18} />Awaiting workbook</div>;
}

function EmptyState() {
  return (
    <div className="empty-state">
      <FileSpreadsheet size={34} />
      <h2>Upload the client workbook</h2>
      <p>The preview will read customer sheets, chemical/product sheets, SDS PDF links, and risk-assessment mappings.</p>
    </div>
  );
}

function PreviewPanel({ preview }) {
  return (
    <div className="preview-grid">
      <div className="section-head">
        <div><p className="eyebrow">Preview</p><h2>{preview.register.title}</h2></div>
        <span className="count">{preview.products.length} products</span>
      </div>
      <div className="info-grid">
        <Info label="Customer" value={preview.customer.company || 'Not found'} />
        <Info label="Contact" value={preview.customer.contact_name || 'Not found'} />
        <Info label="Phone" value={preview.customer.phone || 'Not found'} />
        <Info label="Workbook date" value={preview.register.date || 'Not found'} />
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Code</th><th>Product</th><th>SDS</th><th>Risk</th><th>Expiry</th></tr></thead>
          <tbody>
            {preview.products.map(product => (
              <tr key={`${product.code}-${product.row}`}>
                <td>{product.code}</td>
                <td>{product.name}</td>
                <td><DocCell document={product.sds} /></td>
                <td><DocCell document={product.risk_assessment} /></td>
                <td>{product.sds_expiry || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {preview.missing_documents.length > 0 && (
        <div className="notice warning">
          <AlertCircle size={18} />
          <span>{preview.missing_documents.length} product mappings need source documents.</span>
        </div>
      )}
    </div>
  );
}

function Info({ label, value }) {
  return <div className="info"><span>{label}</span><strong>{value}</strong></div>;
}

function DocCell({ document }) {
  if (!document?.matched) return <span className="missing">Missing</span>;
  return <a className="doc-link" href={document.url} target="_blank" rel="noreferrer"><Link2 size={15} />Open</a>;
}

function SendResult({ result }) {
  return (
    <div className="send-result">
      <div className="section-head">
        <div><p className="eyebrow">Distribution</p><h2>{result.summary.messages} test email payloads</h2></div>
        <span className="count">{result.dry_run ? 'Dry run' : 'Live mode'}</span>
      </div>
      <div className="info-grid">
        <Info label="Contacts" value={String(result.summary.contacts)} />
        <Info label="Products" value={String(result.summary.products)} />
        <Info label="GHL" value={result.ghl?.status || 'prepared'} />
        <Info label="Supabase" value={result.supabase?.status || 'prepared'} />
      </div>
      <div className="message-list">
        {result.messages.map(message => (
          <article key={`${message.to}-${message.subject}`} className="message">
            <strong>{message.to}</strong>
            <span>{message.subject}</span>
          </article>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared batch dropdown hook
// ---------------------------------------------------------------------------

function useBatches() {
  const [batches, setBatches] = useState([]);
  useEffect(() => {
    fetch(`${API_BASE}/distribution/batches`)
      .then(r => r.json())
      .then(d => setBatches(d.batches || []))
      .catch(() => {});
  }, []);
  return batches;
}

function fmtBatchLabel(b) {
  const d = new Date(b.sent_at);
  const date = d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' });
  return `${date} — ${b.contact_count} contact${b.contact_count !== 1 ? 's' : ''}`;
}

function BatchSelect({ batches, value, onChange }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      style={{ padding: '7px 12px', border: '1px solid #d9e1e8', borderRadius: '6px', fontSize: '0.88rem', background: '#fff', cursor: 'pointer' }}
    >
      <option value="">All sends</option>
      {batches.map(b => (
        <option key={b.batch_id} value={b.batch_id}>{fmtBatchLabel(b)}</option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Email Opens dashboard
// ---------------------------------------------------------------------------

function EmailOpensDashboard() {
  const [opens, setOpens] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [batchId, setBatchId] = useState('');
  const batches = useBatches();

  async function loadOpens(bid) {
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ limit: 500 });
      if (bid) params.set('batch_id', bid);
      const response = await fetch(`${API_BASE}/email-opens?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Failed to load');
      setOpens(data.opens || []);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  useEffect(() => { loadOpens(batchId); }, [batchId]);

  function handleBatchChange(bid) {
    setBatchId(bid);
  }

  const byEmail = useMemo(() => {
    const map = {};
    for (const open of opens) {
      const e = open.customer_email;
      if (!map[e]) map[e] = { email: e, contact_id: open.contact_id, first: open.opened_at, last: open.opened_at, count: 0 };
      map[e].count++;
      if (open.opened_at < map[e].first) map[e].first = open.opened_at;
      if (open.opened_at > map[e].last) map[e].last = open.opened_at;
    }
    return Object.values(map).sort((a, b) => (b.last || '').localeCompare(a.last || ''));
  }, [opens]);

  function fmt(ts) {
    if (!ts) return '-';
    return new Date(ts).toLocaleString('en-AU', { dateStyle: 'short', timeStyle: 'short' });
  }

  return (
    <section className="workbench">
      <div className="topbar">
        <div>
          <p className="eyebrow">Compliant Cleaning Supplies</p>
          <h1>Email Opens</h1>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <BatchSelect batches={batches} value={batchId} onChange={handleBatchChange} />
          <button className="tab" onClick={() => loadOpens(batchId)} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>
      {error && <div className="notice error"><AlertCircle size={18} /><span>{error}</span></div>}
      {loading ? (
        <div className="empty-state"><p>Loading…</p></div>
      ) : byEmail.length === 0 ? (
        <div className="empty-state">
          <Mail size={34} />
          <h2>No opens recorded yet</h2>
          <p>Opens appear here once clients open their SDS emails.</p>
        </div>
      ) : (
        <div className="main-panel">
          <div className="section-head">
            <div><p className="eyebrow">Tracking</p><h2>{byEmail.length} unique recipients</h2></div>
            <span className="count">{opens.length} total opens</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Email</th><th>First opened</th><th>Last opened</th><th style={{ textAlign: 'center' }}>Opens</th></tr>
              </thead>
              <tbody>
                {byEmail.map(row => (
                  <tr key={row.email}>
                    <td>{row.email}</td>
                    <td>{fmt(row.first)}</td>
                    <td>{fmt(row.last)}</td>
                    <td style={{ textAlign: 'center' }}>{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// PDF Opens dashboard
// ---------------------------------------------------------------------------

function PdfOpensDashboard() {
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [batchId, setBatchId] = useState('');
  const batches = useBatches();

  async function runSearch(q, bid) {
    const email = (q ?? query).trim();
    const batch = bid ?? batchId;
    if (!email && !batch) { setRows([]); return; }
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ limit: 200 });
      if (email) params.set('email', email);
      if (batch) params.set('batch_id', batch);
      const response = await fetch(`${API_BASE}/document-opens?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Failed to load');
      setRows(data.rows || []);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  function handleSearch(e) {
    e.preventDefault();
    setQuery(search);
    runSearch(search, batchId);
  }

  function handleBatchChange(bid) {
    setBatchId(bid);
    if (query || bid) runSearch(query, bid);
    else setRows([]);
  }

  const filtered = useMemo(() => {
    if (statusFilter === 'opened') return rows.filter(r => r.status === 'downloaded');
    if (statusFilter === 'not-opened') return rows.filter(r => r.status !== 'downloaded');
    return rows;
  }, [rows, statusFilter]);

  const stats = useMemo(() => ({
    total: rows.length,
    opened: rows.filter(r => r.status === 'downloaded').length,
    notOpened: rows.filter(r => r.status !== 'downloaded').length,
  }), [rows]);

  function fmt(ts) {
    if (!ts) return '—';
    return new Date(ts).toLocaleString('en-AU', { dateStyle: 'short', timeStyle: 'short' });
  }

  function chemName(row) {
    return row.chemical_name || row.product_code || row.document_id || '—';
  }

  return (
    <section className="workbench">
      <div className="topbar">
        <div>
          <p className="eyebrow">Compliant Cleaning Supplies</p>
          <h1>PDF Opens</h1>
        </div>
        <BatchSelect batches={batches} value={batchId} onChange={handleBatchChange} />
      </div>

      <form onSubmit={handleSearch} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.25rem' }}>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by contact email…"
          style={{ flex: 1, padding: '8px 12px', border: '1px solid #d9e1e8', borderRadius: '6px', fontSize: '0.95rem' }}
        />
        <button type="submit" className="primary" disabled={loading} style={{ whiteSpace: 'nowrap' }}>
          {loading ? 'Searching…' : 'Search'}
        </button>
      </form>

      {error && <div className="notice error"><AlertCircle size={18} /><span>{error}</span></div>}

      {!loading && rows.length > 0 && (
        <>
          <div className="info-grid" style={{ margin: '0 0 1rem' }}>
            <Info label="Total sent" value={String(stats.total)} />
            <Info label="Opened" value={String(stats.opened)} />
            <Info label="Not opened" value={String(stats.notOpened)} />
            <Info label="Open rate" value={`${Math.round(stats.opened / stats.total * 100)}%`} />
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', margin: '0 0 1rem' }}>
            {[['all', 'All'], ['opened', 'Opened'], ['not-opened', 'Not opened']].map(([val, label]) => (
              <button key={val} className={`tab ${statusFilter === val ? 'active' : ''}`}
                onClick={() => setStatusFilter(val)}
                style={{ fontSize: '0.8rem', padding: '4px 12px' }}>
                {label}
              </button>
            ))}
          </div>
        </>
      )}

      {!query && !batchId ? (
        <div className="empty-state">
          <FileSpreadsheet size={34} />
          <h2>Search a contact</h2>
          <p>Enter an email address, or select a send campaign above to view PDF delivery status.</p>
        </div>
      ) : loading ? (
        <div className="empty-state"><p>Searching…</p></div>
      ) : filtered.length === 0 ? (
        <div className="empty-state"><p>No records found for <strong>{query}</strong>.</p></div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Chemical / Product</th>
                <th>Status</th>
                <th>Opened at</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, i) => (
                <tr key={i}>
                  <td>{row.customer_email}</td>
                  <td>{chemName(row)}</td>
                  <td>
                    <span style={{ color: row.status === 'downloaded' ? '#2C6B33' : '#607080', fontWeight: 600 }}>
                      {row.status === 'downloaded' ? 'Opened' : 'Not opened'}
                    </span>
                  </td>
                  <td>{fmt(row.downloaded_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function parseContacts(value) {
  return value.split(/\r?\n/).map(l => l.trim()).filter(Boolean).map(line => {
    const m = line.match(/^(.*?)<([^>]+)>$/);
    if (m) return { name: m[1].trim(), email: m[2].trim() };
    const parts = line.split(',');
    if (parts.length >= 2) return { name: parts[0].trim(), email: parts[1].trim() };
    return { name: '', email: line };
  }).filter(c => c.email.includes('@'));
}

// ---------------------------------------------------------------------------
// Document Library
// ---------------------------------------------------------------------------

function DocumentLibrary() {
  const [register, setRegister] = useState(null);
  const [pdfs, setPdfs] = useState([]);
  const [customerId, setCustomerId] = useState('');
  const [ingesting, setIngesting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [versions, setVersions] = useState(null);
  const [versionsCode, setVersionsCode] = useState('');
  const [activeSection, setActiveSection] = useState('ingest');

  async function handleIngest(e) {
    e.preventDefault();
    if (!register) return;
    setIngesting(true);
    setError('');
    setResult(null);
    const fd = new FormData();
    fd.append('register_file', register);
    pdfs.forEach(f => fd.append('pdf_files', f));
    if (customerId) fd.append('customer_id', customerId);
    try {
      const res = await fetch(`${API_BASE}/library/ingest?customer_id=${encodeURIComponent(customerId)}`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: fd,
      });
      if (!res.ok) throw new Error(await res.text());
      setResult(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setIngesting(false);
    }
  }

  async function loadStatus() {
    setStatusLoading(true);
    try {
      const res = await fetch(`${API_BASE}/library/status`, { headers: getAuthHeaders() });
      setStatus(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setStatusLoading(false);
    }
  }

  async function loadVersions(code) {
    setVersionsCode(code);
    const res = await fetch(`${API_BASE}/library/versions/${encodeURIComponent(code)}`, { headers: getAuthHeaders() });
    setVersions(await res.json());
  }

  async function handleRollback(code, docType) {
    if (!confirm(`Roll back ${docType.toUpperCase()} for ${code} to previous version?`)) return;
    const res = await fetch(`${API_BASE}/library/rollback`, {
      method: 'POST',
      headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_code: code, document_type: docType }),
    });
    if (res.ok) { alert('Rolled back. Reload status to confirm.'); }
    else { alert(await res.text()); }
  }

  return (
    <div className="desk">
      <div className="tab-bar" style={{ marginBottom: 16 }}>
        <button className={`tab ${activeSection === 'ingest' ? 'active' : ''}`} onClick={() => setActiveSection('ingest')}>Ingest</button>
        <button className={`tab ${activeSection === 'status' ? 'active' : ''}`} onClick={() => { setActiveSection('status'); loadStatus(); }}>Status</button>
        {versions && <button className={`tab ${activeSection === 'versions' ? 'active' : ''}`} onClick={() => setActiveSection('versions')}>Versions: {versionsCode}</button>}
      </div>

      {activeSection === 'ingest' && (
        <>
        <div style={{ background: '#eff6ff', border: '1px solid #93c5fd', borderRadius: 8, padding: '14px 18px', marginBottom: 16, maxWidth: 560, fontSize: 13 }}>
          <strong style={{ display: 'block', marginBottom: 6, color: '#1d4ed8' }}>What is Doc Library?</strong>
          <p style={{ margin: '0 0 8px' }}>Doc Library ingests SDS and Risk Assessment PDFs in bulk — upload the Chemical Register Excel alongside all PDF files, and the system matches each PDF by filename to its product code, then stores it versioned in DO Spaces.</p>
          <p style={{ margin: '0 0 8px' }}>Each product can have multiple SDS/Risk versions over time. The Status tab shows the current live file per product. You can roll back any product to a previous version.</p>
          <p style={{ margin: 0, color: 'var(--muted)' }}><strong>Not the same as Sites → Import.</strong> The Sites tab import uploads the Chemical Register Title Sheet to populate product metadata (name, hazard class, UN number etc.) in Supabase for email distribution. This page is for uploading the actual PDF documents into the file library.</p>
        </div>
        <form onSubmit={handleIngest} className="card" style={{ padding: 24, marginBottom: 16, maxWidth: 560 }}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Upload & Ingest</h2>
          <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 0 }}>
            Upload the Chemical Register Excel + all SDS/Risk Assessment PDFs. Files stored in DO Spaces under <code>ccs/{'{date}/'}</code>.
          </p>
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 13, fontWeight: 600, display: 'block', marginBottom: 4 }}>Customer ID (optional — auto-derived from register if blank)</label>
            <input className="inp" value={customerId} onChange={e => setCustomerId(e.target.value)} placeholder="compliant-cleaning" style={{ width: 280 }} />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 13, fontWeight: 600, display: 'block', marginBottom: 6 }}>Chemical Register (.xlsx / .xlsm) *</label>
            <input type="file" accept=".xlsx,.xlsm" onChange={e => setRegister(e.target.files[0])} required style={{ width: 'auto' }} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 13, fontWeight: 600, display: 'block', marginBottom: 6 }}>SDS + Risk Assessment PDFs (select all, up to 440)</label>
            <input type="file" accept=".pdf" multiple onChange={e => setPdfs(Array.from(e.target.files))} style={{ width: 'auto' }} />
            {pdfs.length > 0 && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{pdfs.length} file{pdfs.length !== 1 ? 's' : ''} selected</div>}
          </div>
          <button className="btn-primary" type="submit" disabled={ingesting || !register}>
            <Upload size={14} style={{ marginRight: 6 }} />{ingesting ? 'Uploading & matching…' : 'Ingest'}
          </button>
          {error && <div className="error-msg" style={{ marginTop: 12 }}>{error}</div>}
          {result && (
            <div style={{ marginTop: 20 }}>
              <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
                <Pill label="Uploaded" value={result.uploaded_count} />
                <Pill label="Matched" value={result.matched_count} ok />
                <Pill label="Unmatched" value={result.unmatched_products?.length} warn={result.unmatched_products?.length > 0} />
                <Pill label="Orphaned PDFs" value={result.orphaned_filenames?.length} warn={result.orphaned_filenames?.length > 0} />
              </div>
              {result.unmatched_products?.length > 0 && (
                <details style={{ marginBottom: 8 }}>
                  <summary style={{ cursor: 'pointer', fontSize: 13, color: 'var(--warn)' }}>Unmatched products ({result.unmatched_products.length})</summary>
                  <table className="mini-table" style={{ marginTop: 8 }}><tbody>
                    {result.unmatched_products.map(p => <tr key={p.code}><td>{p.code}</td><td>{p.name}</td></tr>)}
                  </tbody></table>
                </details>
              )}
              {result.orphaned_filenames?.length > 0 && (
                <details>
                  <summary style={{ cursor: 'pointer', fontSize: 13, color: 'var(--warn)' }}>Orphaned PDFs ({result.orphaned_filenames.length})</summary>
                  <ul style={{ fontSize: 12, marginTop: 8 }}>{result.orphaned_filenames.map(f => <li key={f}>{f}</li>)}</ul>
                </details>
              )}
              {result.upload_errors?.length > 0 && (
                <details>
                  <summary style={{ cursor: 'pointer', fontSize: 13, color: 'var(--warn)' }}>Upload errors ({result.upload_errors.length})</summary>
                  <ul style={{ fontSize: 12, marginTop: 8 }}>{result.upload_errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </details>
              )}
            </div>
          )}
        </form>
        </>
      )}

      {activeSection === 'status' && (
        <div className="card" style={{ padding: 24 }}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Library Status</h2>
          {statusLoading && <p style={{ color: 'var(--muted)' }}>Loading…</p>}
          {status && (
            <>
              <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
                <Pill label="Files in Spaces" value={status.spaces_file_count} />
                <Pill label="Products mapped" value={status.library_product_count} />
                <Pill label="SDS matched" value={status.matched_sds_count} ok />
                <Pill label="Risk matched" value={status.matched_risk_count} ok />
                <Pill label="Unmatched" value={status.unmatched_products?.length} warn={status.unmatched_products?.length > 0} />
              </div>
              {status.library?.length > 0 && (
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Code</th><th>Name</th><th>SDS</th><th>Risk</th><th>Method</th><th>v</th><th></th></tr></thead>
                    <tbody>
                      {status.library.map(r => (
                        <tr key={r.product_code}>
                          <td><code style={{ fontSize: 11 }}>{r.product_code}</code></td>
                          <td style={{ fontSize: 13 }}>{r.product_name}</td>
                          <td>{r.sds_url ? <a href={r.sds_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>PDF</a> : <span style={{ color: 'var(--muted)', fontSize: 12 }}>—</span>}</td>
                          <td>{r.risk_url ? <a href={r.risk_url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>PDF</a> : <span style={{ color: 'var(--muted)', fontSize: 12 }}>—</span>}</td>
                          <td><span style={{ fontSize: 11, color: 'var(--muted)' }}>{r.match_method}</span></td>
                          <td style={{ fontSize: 11 }}>{r.sds_version}</td>
                          <td>
                            <button className="btn-ghost" style={{ fontSize: 11 }} onClick={() => { loadVersions(r.product_code); setActiveSection('versions'); }}>History</button>
                            {r.sds_url_previous && <button className="btn-ghost" style={{ fontSize: 11, marginLeft: 4 }} onClick={() => handleRollback(r.product_code, 'sds')}>↩ SDS</button>}
                            {r.risk_url_previous && <button className="btn-ghost" style={{ fontSize: 11, marginLeft: 4 }} onClick={() => handleRollback(r.product_code, 'risk')}>↩ Risk</button>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {activeSection === 'versions' && versions && (
        <div className="card" style={{ padding: 24 }}>
          <h2 style={{ marginTop: 0, fontSize: 18 }}>Version History — {versionsCode}</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Type</th><th>v</th><th>Batch</th><th>Filename</th><th>URL</th><th>Uploaded</th></tr></thead>
              <tbody>
                {versions.map(v => (
                  <tr key={v.id}>
                    <td><span style={{ fontSize: 11, fontWeight: 600 }}>{v.document_type.toUpperCase()}</span></td>
                    <td style={{ fontSize: 12 }}>{v.version}</td>
                    <td style={{ fontSize: 11, color: 'var(--muted)' }}>{v.ingest_batch}</td>
                    <td style={{ fontSize: 12, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.filename}</td>
                    <td><a href={v.url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>Open</a></td>
                    <td style={{ fontSize: 11, color: 'var(--muted)' }}>{new Date(v.uploaded_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Site Distribution
// ---------------------------------------------------------------------------

function SiteDistribution() {
  const [stats, setStats] = useState(null);
  const [sites, setSites] = useState([]);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [sending, setSending] = useState(false);
  const [taskId, setTaskId] = useState('');
  const [taskStatus, setTaskStatus] = useState(null);
  const [dryRun, setDryRun] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showHelp, setShowHelp] = useState(false);
  const [testAlertResult, setTestAlertResult] = useState('');
  const [testAlertPreviewHtml, setTestAlertPreviewHtml] = useState(null);

  // File inputs
  const [mappingFile, setMappingFile] = useState(null);
  const [sdsFile, setSdsFile] = useState(null);
  const [riskFile, setRiskFile] = useState(null);
  const [groupingFile, setGroupingFile] = useState(null);
  const [registerFile, setRegisterFile] = useState(null);

  // Test contact override — staff enter a test email; used as default in manual send modal
  const [testEmail, setTestEmail] = useState('');

  // Manual send modal
  const [manualSite, setManualSite] = useState(null);
  const [manualEmail, setManualEmail] = useState('');
  const [manualCodes, setManualCodes] = useState(new Set());
  const [manualDryRun, setManualDryRun] = useState(false);
  const [manualSending, setManualSending] = useState(false);
  const [manualResult, setManualResult] = useState('');

  // Email preview
  const [previewData, setPreviewData] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Data management
  const [importStatus, setImportStatus] = useState(null);
  const [clearConfirm, setClearConfirm] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Add product to Chemical Register
  const [showAddProduct, setShowAddProduct] = useState(false);
  const [addProd, setAddProd] = useState({ stock_code: '', product_name: '', hazard_classification: '', un_number: '', maximum_qty: '', risk_assessment_required: false, hazchem: '', chemical_class: '', packing_group: '', primary_use: '', sds_expiry: '', sds_url: '', risk_url: '' });
  const [addProdResult, setAddProdResult] = useState('');
  const [addProdSaving, setAddProdSaving] = useState(false);

  // New customer send
  const [showNewCustomer, setShowNewCustomer] = useState(false);
  const [ncForm, setNcForm] = useState({ customer_name: '', email: '', stockcodes_text: '', dry_run: true });
  const [ncResult, setNcResult] = useState('');
  const [ncSending, setNcSending] = useState(false);
  const [ncPreviewHtml, setNcPreviewHtml] = useState(null);

  // SharePoint pull
  const [spPulling, setSpPulling] = useState(false);
  const [spPullResult, setSpPullResult] = useState(null);
  const [spPullError, setSpPullError] = useState('');

  const PAGE_SIZE = 50;

  async function loadStats() {
    try {
      const r = await fetch(`${API_BASE}/site-distribution/stats`, { headers: getAuthHeaders() });
      if (r.ok) setStats(await r.json());
    } catch { /* ignore */ }
  }

  async function loadSites() {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, page_size: PAGE_SIZE });
      if (search) params.set('search', search);
      const r = await fetch(`${API_BASE}/site-distribution/sites?${params}`, { headers: getAuthHeaders() });
      if (r.ok) setSites((await r.json()).sites || []);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  useEffect(() => { loadStats(); }, []);
  useEffect(() => { loadSites(); }, [page, search]);

  // Poll task progress
  useEffect(() => {
    if (!taskId) return;
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`${API_BASE}/distribution/status/${taskId}`, { headers: getAuthHeaders() });
        if (!r.ok) return;
        const data = await r.json();
        setTaskStatus(data);
        if (data.state === 'SUCCESS' || data.state === 'FAILURE') {
          clearInterval(interval);
          setSending(false);
          loadStats();
        }
      } catch { /* ignore */ }
    }, 2000);
    return () => clearInterval(interval);
  }, [taskId]);

  async function handleImport(e) {
    e.preventDefault();
    if (!mappingFile && !sdsFile && !riskFile && !groupingFile && !registerFile) {
      setError('Select at least one file to import.');
      return;
    }
    setImporting(true); setError(''); setNotice('');
    const form = new FormData();
    if (mappingFile) form.append('mapping', mappingFile);
    if (sdsFile) form.append('sds', sdsFile);
    if (riskFile) form.append('risk', riskFile);
    if (groupingFile) form.append('grouping', groupingFile);
    if (registerFile) form.append('register', registerFile);
    try {
      const r = await fetch(`${API_BASE}/site-distribution/import`, { method: 'POST', headers: getAuthHeaders(), body: form });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Import failed');
      const regNote = data.register ? `, ${data.register} register products` : '';
      setNotice(`Imported: ${data.sites} sites, ${data.links} SDS/Risk links, ${data.groups} product groups${regNote}.`);
      loadStats(); loadSites();
    } catch (err) { setError(err.message); }
    finally { setImporting(false); }
  }

  async function handleSpPull() {
    setSpPulling(true); setSpPullError(''); setSpPullResult(null); setError(''); setNotice('');
    try {
      const r = await fetch(`${API_BASE}/site-distribution/import-from-sharepoint`, { method: 'POST', headers: getAuthHeaders() });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'SharePoint pull failed');
      const regNote = data.register ? `, ${data.register} register products` : '';
      setNotice(`SharePoint import: ${data.sites} sites, ${data.links} SDS/Risk links, ${data.groups} product groups${regNote}.`);
      setSpPullResult(data.pulled_files || {});
      loadStats(); loadSites();
    } catch (err) { setSpPullError(err.message); }
    finally { setSpPulling(false); }
  }

  async function toggleExclude(site) {
    const accno = site.accno;
    const url = `${API_BASE}/site-distribution/exclude/${encodeURIComponent(accno)}`;
    try {
      if (site.excluded) {
        await fetch(url, { method: 'DELETE', headers: getAuthHeaders() });
      } else {
        await fetch(`${url}?name=${encodeURIComponent(site.name)}`, { method: 'POST', headers: getAuthHeaders() });
      }
      setSites(prev => prev.map(s => s.accno === accno ? { ...s, excluded: !s.excluded } : s));
      loadStats();
    } catch (err) { setError(err.message); }
  }

  async function toggleHold(site) {
    const accno = site.accno;
    const url = `${API_BASE}/site-distribution/hold/${encodeURIComponent(accno)}`;
    try {
      if (site.held) {
        await fetch(url, { method: 'DELETE', headers: getAuthHeaders() });
      } else {
        await fetch(`${url}?name=${encodeURIComponent(site.name)}`, { method: 'POST', headers: getAuthHeaders() });
      }
      setSites(prev => prev.map(s => s.accno === accno ? { ...s, held: !s.held } : s));
      loadStats();
    } catch (err) { setError(err.message); }
  }

  function openManualSend(site) {
    setManualSite(site);
    setManualEmail(testEmail || (site.emails || [])[0] || '');
    setManualCodes(new Set(site.stockcodes || []));
    setManualResult('');
    setManualSending(false);
  }

  async function handleManualSend(e) {
    e.preventDefault();
    if (!manualSite) return;
    setManualSending(true);
    setManualResult('');
    try {
      const r = await fetch(`${API_BASE}/site-distribution/send-manual`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          accno: manualSite.accno,
          stockcodes: [...manualCodes],
          email: manualEmail,
          dry_run: manualDryRun,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Send failed');
      setManualResult(`${data.status === 'dry_run' ? 'Dry run OK' : 'Sent'} — ${data.docs} document(s) to ${data.email}`);
    } catch (err) {
      setManualResult(`Error: ${err.message}`);
    } finally {
      setManualSending(false);
    }
  }

  async function handlePreview() {
    if (!manualSite) return;
    setPreviewLoading(true);
    setPreviewData(null);
    try {
      const r = await fetch(`${API_BASE}/site-distribution/preview-email`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          accno: manualSite.accno,
          stockcodes: [...manualCodes],
          email: manualEmail || 'preview@example.com',
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Preview failed');
      setPreviewData(data);
    } catch (err) {
      setManualResult(`Error: ${err.message}`);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function loadImportStatus() {
    try {
      const r = await fetch(`${API_BASE}/site-distribution/import-status`, { headers: getAuthHeaders() });
      if (r.ok) setImportStatus(await r.json());
    } catch { /* ignore */ }
  }

  async function handleClearData() {
    setClearing(true);
    try {
      const r = await fetch(`${API_BASE}/site-distribution/data`, {
        method: 'DELETE',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ tables: ['ccs_site_mapping', 'ccs_sds_links', 'ccs_stock_groups', 'ccs_site_exclusions', 'ccs_site_holds'] }),
      });
      if (r.ok) {
        setClearConfirm(false);
        setImportStatus(null);
        loadStats();
        loadSites();
      }
    } catch { /* ignore */ }
    finally { setClearing(false); }
  }

  async function handleSend() {
    setSending(true); setError(''); setTaskStatus(null);
    try {
      const r = await fetch(`${API_BASE}/site-distribution/send?dry_run=${dryRun}`, { method: 'POST', headers: getAuthHeaders() });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Send failed');
      setTaskId(data.task_id);
      setTaskStatus({ state: 'PENDING', meta: {} });
    } catch (err) { setError(err.message); setSending(false); }
  }

  async function triggerTestAlert(endpoint, label) {
    setTestAlertResult(`Running ${label}…`);
    setTestAlertPreviewHtml(null);
    try {
      const r = await fetch(`${API_BASE}${endpoint}`, { method: 'POST', headers: getAuthHeaders() });
      const text = await r.text();
      let data;
      try { data = JSON.parse(text); } catch { throw new Error(text.slice(0, 200)); }
      if (!r.ok) throw new Error(data.detail || 'Failed');
      if (data.preview_html) {
        setTestAlertPreviewHtml({ title: label, html: data.preview_html });
        const count = data.expiring_count ?? data.held_count ?? '—';
        setTestAlertResult(`${label}: ${count} item(s) — preview ready`);
      } else {
        const ghlStatus = data.ghl?.status || 'no email sent (GHL disabled or nothing to send)';
        const count = data.new_count ?? '—';
        setTestAlertResult(`${label}: count=${count}, GHL=${ghlStatus}`);
      }
    } catch (err) {
      setTestAlertResult(`${label} error: ${err.message}`);
    }
  }

  async function handleAddProduct(e) {
    e.preventDefault();
    if (!addProd.stock_code.trim()) return;
    setAddProdSaving(true);
    setAddProdResult('');
    try {
      const r = await fetch(`${API_BASE}/site-distribution/register/product`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...addProd, stock_code: addProd.stock_code.trim().toUpperCase() }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Failed');
      setAddProdResult(`${data.status === 'created' ? 'Created' : 'Updated'}: ${data.stock_code}`);
      setAddProd({ stock_code: '', product_name: '', hazard_classification: '', un_number: '', maximum_qty: '', risk_assessment_required: false, hazchem: '', chemical_class: '', packing_group: '', primary_use: '', sds_expiry: '', sds_url: '', risk_url: '' });
    } catch (err) {
      setAddProdResult(`Error: ${err.message}`);
    } finally {
      setAddProdSaving(false);
    }
  }

  async function handleNewCustomerSend(e) {
    e.preventDefault();
    if (!ncForm.customer_name || !ncForm.email || !ncForm.stockcodes_text) return;
    const codes = ncForm.stockcodes_text.split(/[\n,]+/).map(s => s.trim().toUpperCase()).filter(Boolean);
    if (!codes.length) return;
    setNcSending(true);
    setNcResult('');
    setNcPreviewHtml(null);
    try {
      const r = await fetch(`${API_BASE}/site-distribution/send-new-customer`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ customer_name: ncForm.customer_name, email: ncForm.email, stockcodes: codes, dry_run: ncForm.dry_run }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Failed');
      if (data.html) setNcPreviewHtml({ title: `New Customer — ${ncForm.customer_name}`, html: data.html });
      setNcResult(`${ncForm.dry_run ? 'Dry run OK' : data.status} — ${data.docs} doc(s) to ${data.email}`);
    } catch (err) {
      setNcResult(`Error: ${err.message}`);
    } finally {
      setNcSending(false);
    }
  }

  const progressMeta = taskStatus?.meta || taskStatus?.result || {};
  const progressPct = progressMeta.total ? Math.round((progressMeta.done || 0) / progressMeta.total * 100) : 0;

  return (
    <section className="workbench">
      <div className="topbar">
        <div>
          <p className="eyebrow">Compliant Cleaning Supplies</p>
          <h1>Site Distribution</h1>
        </div>
        {stats && (
          <div style={{ display: 'flex', gap: 10 }}>
            <Pill label="Total sites" value={stats.total_sites} ok={stats.total_sites > 0} />
            <Pill label="Active" value={stats.active_sites} ok={stats.active_sites > 0} />
            <Pill label="On Hold" value={stats.held_sites} warn={stats.held_sites > 0} />
            <Pill label="Excluded" value={stats.excluded_sites} warn={stats.excluded_sites > 0} />
            <Pill label="SDS links" value={stats.sds_links} ok={stats.sds_links > 0} />
          </div>
        )}
      </div>

      {/* Help panel */}
      <div style={{ maxWidth: 960, margin: '0 auto 12px', padding: '0 0' }}>
        <button
          onClick={() => setShowHelp(h => !h)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#5c7cfa', fontSize: 12, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4, padding: '4px 0' }}
        >
          <HelpCircle size={13} />{showHelp ? 'Hide help' : 'How to use this page'}
        </button>
        {showHelp && (
          <div style={{ background: '#f0f4ff', border: '1px solid #c9d8ff', borderRadius: 8, padding: '16px 20px', marginTop: 6, fontSize: 13, lineHeight: 1.7 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px 32px' }}>
              <div>
                <strong style={{ color: '#2C6B33' }}>Status bar (top right)</strong>
                <ul style={{ margin: '4px 0 0 0', paddingLeft: 16 }}>
                  <li><strong>Total sites</strong> — all imported from mapping file</li>
                  <li><strong>Active</strong> — sites that will receive emails (not held, not excluded)</li>
                  <li><strong>On Hold</strong> — temporarily paused; skipped in sends; monthly internal hold-list email sent to ccshub@</li>
                  <li><strong>Excluded</strong> — permanently removed from all sends</li>
                  <li><strong>SDS links</strong> — total products with at least one SDS URL</li>
                </ul>
              </div>
              <div>
                <strong style={{ color: '#2C6B33' }}>Site row actions</strong>
                <ul style={{ margin: '4px 0 0 0', paddingLeft: 16 }}>
                  <li><strong>Hold / Unhold</strong> — temporarily pause a site. Row dims to 65% opacity. Reversed by clicking Unhold.</li>
                  <li><strong>Active / Excl</strong> — toggle permanent exclusion. Excluded rows dim to 40%.</li>
                  <li><strong>Send (blue)</strong> — open manual send modal for this site</li>
                </ul>
                <strong style={{ color: '#2C6B33', display: 'block', marginTop: 8 }}>Manual send modal</strong>
                <ul style={{ margin: '4px 0 0 0', paddingLeft: 16 }}>
                  <li>All site products pre-checked — uncheck to exclude any from this send</li>
                  <li>Email defaults to the Test Contact (set in sidebar) or site's own email</li>
                  <li><strong>Preview email</strong> — renders the full HTML email + Chemical Register attachment link in a preview overlay. Dry run only — nothing sent.</li>
                  <li><strong>Send</strong> — with Dry run checked, logs result without sending to GHL</li>
                </ul>
              </div>
              <div>
                <strong style={{ color: '#2C6B33' }}>Automated alerts</strong>
                <ul style={{ margin: '4px 0 0 0', paddingLeft: 16 }}>
                  <li><strong>New product detection</strong> — daily 5:00pm AEST. Detects product codes added since last run; review queue at <a href="/new-products" style={{ color: '#5c7cfa' }}>/new-products</a>. First run seeds history silently.</li>
                  <li><strong>SDS expiry alert</strong> — 1st working day of each month, 9:00am AEST. Emails list of products expiring within 60 days.</li>
                  <li><strong>Hold list notification</strong> — 1st working day of each month, 9:15am AEST. Emails current hold list.</li>
                  <li>SDS expiry + hold list send to <strong>ccshub@ccsessentials.com.au</strong>. Use test buttons in sidebar to fire immediately and preview the email.</li>
                </ul>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="layout">
        <aside className="side-panel">
          {/* Import */}
          <form onSubmit={handleImport} className="upload-box">
            <label style={{ fontWeight: 700, fontSize: '0.78rem', letterSpacing: 1, textTransform: 'uppercase', color: '#667789' }}>Import mapping files</label>
            <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <label style={{ fontSize: 12, color: '#445' }}>Customer–Product Code Mapping</label>
              <input type="file" accept=".xlsx" onChange={e => setMappingFile(e.target.files?.[0] || null)} />
              <label style={{ fontSize: 12, color: '#445' }}>SDS links</label>
              <input type="file" accept=".xlsx" onChange={e => setSdsFile(e.target.files?.[0] || null)} />
              <label style={{ fontSize: 12, color: '#445' }}>Risk links</label>
              <input type="file" accept=".xlsx" onChange={e => setRiskFile(e.target.files?.[0] || null)} />
              <label style={{ fontSize: 12, color: '#445' }}>Product grouping (optional)</label>
              <input type="file" accept=".xlsx" onChange={e => setGroupingFile(e.target.files?.[0] || null)} />
              <label style={{ fontSize: 12, color: '#445' }}>Chemical Register — Title Sheet (optional, sets SDS expiry + risk assessment flag)</label>
              <input type="file" accept=".xlsx" onChange={e => setRegisterFile(e.target.files?.[0] || null)} />
            </div>
            <button type="submit" className="primary" disabled={importing} style={{ marginTop: 12 }}>
              <Upload size={16} style={{ marginRight: 6 }} />{importing ? 'Importing…' : 'Import'}
            </button>
          </form>

          {/* SharePoint pull */}
          <div className="upload-box" style={{ marginTop: 8 }}>
            <label style={{ fontWeight: 700, fontSize: '0.78rem', letterSpacing: 1, textTransform: 'uppercase', color: '#667789' }}>Pull from SharePoint</label>
            <p style={{ fontSize: 12, color: '#607080', marginTop: 6, marginBottom: 8 }}>
              Pulls latest file from each folder in <strong>SDS Share Folder</strong> on SharePoint and imports all 5 mapping files in one step. Requires Azure admin consent (Files.Read.All + Sites.Read.All).
            </p>
            <button
              type="button"
              className="primary"
              disabled={spPulling}
              onClick={handleSpPull}
              style={{ width: '100%' }}
            >
              <Upload size={16} style={{ marginRight: 6 }} />{spPulling ? 'Pulling from SharePoint…' : 'Pull from SharePoint'}
            </button>
            {spPullError && (
              <div className="error-msg" style={{ marginTop: 8 }}>{spPullError}</div>
            )}
            {spPullResult && (
              <div style={{ marginTop: 10, fontSize: 12, display: 'grid', gap: 4 }}>
                {Object.entries(spPullResult).map(([key, filename]) => (
                  <div key={key} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ color: filename ? '#167245' : '#9a6500', fontWeight: 700 }}>{filename ? '✓' : '–'}</span>
                    <span style={{ color: '#445', textTransform: 'capitalize' }}>{key.replace(/_/g, ' ')}</span>
                    {filename && <span style={{ color: '#667789', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{filename}</span>}
                    {!filename && <span style={{ color: '#9a6500' }}>no file in folder</span>}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Report download */}
          <div className="contact-box" style={{ marginTop: 16 }}>
            <label style={{ fontWeight: 700, fontSize: '0.78rem', letterSpacing: 1, textTransform: 'uppercase', color: '#667789' }}>Test report</label>
            <p style={{ fontSize: 12, color: '#607080', marginTop: 6, marginBottom: 8 }}>
              Download CSV — every site, what documents they'd receive, and why any are skipped.
            </p>
            <a
              href={`${API_BASE}/site-distribution/report.csv`}
              download
              className="primary"
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', textDecoration: 'none', padding: '8px 14px', borderRadius: 6, fontSize: 13 }}
            >
              <Download size={15} style={{ marginRight: 6 }} />Download report
            </a>
          </div>

          {/* Test contact box */}
          <div className="contact-box" style={{ marginTop: 16 }}>
            <label style={{ fontWeight: 700, fontSize: '0.78rem', letterSpacing: 1, textTransform: 'uppercase', color: '#667789' }}>Test contact</label>
            <p style={{ fontSize: 12, color: '#607080', marginTop: 6, marginBottom: 8 }}>
              Enter a staff email. Clicking Send on any site row will pre-fill this address in the send modal.
            </p>
            <input
              type="email"
              value={testEmail}
              onChange={e => setTestEmail(e.target.value)}
              placeholder="staff@example.com"
              style={{ width: '100%', padding: '7px 10px', border: '1px solid #d8e1e8', borderRadius: 6, fontSize: 13, boxSizing: 'border-box' }}
            />
          </div>

          {/* Test alert triggers */}
          <div className="contact-box" style={{ marginTop: 16 }}>
            <label style={{ fontWeight: 700, fontSize: '0.78rem', letterSpacing: 1, textTransform: 'uppercase', color: '#667789' }}>Test alerts</label>
            <p style={{ fontSize: 12, color: '#607080', marginTop: 6, marginBottom: 8 }}>
              Fire each automated alert immediately. Sends to ccshub@ via GHL (skipped if GHL disabled).
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <button className="btn-ghost" style={{ justifyContent: 'flex-start', fontSize: 12 }}
                onClick={() => triggerTestAlert('/site-distribution/test/detect-new-products', 'New products')}>
                New product detection
              </button>
              <button className="btn-ghost" style={{ justifyContent: 'flex-start', fontSize: 12 }}
                onClick={() => triggerTestAlert('/site-distribution/test/sds-expiry-alerts', 'SDS expiry')}>
                SDS expiry alerts
              </button>
              <button className="btn-ghost" style={{ justifyContent: 'flex-start', fontSize: 12 }}
                onClick={() => triggerTestAlert('/site-distribution/test/hold-list-notification', 'Hold list')}>
                Hold list notification
              </button>
            </div>
            {testAlertResult && (
              <p style={{ fontSize: 11, color: '#445', marginTop: 8, wordBreak: 'break-word' }}>{testAlertResult}</p>
            )}
          </div>

          {/* Add product to Chemical Register */}
          <div className="contact-box" style={{ marginTop: 16 }}>
            <button
              onClick={() => { setShowAddProduct(v => !v); setAddProdResult(''); }}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.78rem', letterSpacing: 1, textTransform: 'uppercase', color: '#667789', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}
            >
              <FileSpreadsheet size={13} />{showAddProduct ? '▲ Hide' : '▼ Add to Chemical Register'}
            </button>
            {showAddProduct && (
              <form onSubmit={handleAddProduct} style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {[
                  ['Product Code *', 'stock_code', 'text', true],
                  ['Product Name', 'product_name', 'text', false],
                  ['Hazard Status', 'hazard_classification', 'text', false],
                  ['UN Number', 'un_number', 'text', false],
                  ['Maximum Qty', 'maximum_qty', 'text', false],
                  ['Hazchem', 'hazchem', 'text', false],
                  ['Class', 'chemical_class', 'text', false],
                  ['Packing Group', 'packing_group', 'text', false],
                  ['Primary Use', 'primary_use', 'text', false],
                  ['SDS Review Date', 'sds_expiry', 'text', false],
                  ['SDS URL', 'sds_url', 'url', false],
                  ['Risk URL', 'risk_url', 'url', false],
                ].map(([label, key, type, req]) => (
                  <div key={key}>
                    <label style={{ fontSize: 11, color: '#445', display: 'block', marginBottom: 2 }}>{label}</label>
                    <input
                      type={type}
                      required={req}
                      value={addProd[key]}
                      onChange={e => setAddProd(p => ({ ...p, [key]: e.target.value }))}
                      style={{ width: '100%', padding: '5px 8px', border: '1px solid #d8e1e8', borderRadius: 5, fontSize: 12, boxSizing: 'border-box' }}
                    />
                  </div>
                ))}
                <label style={{ fontSize: 11, color: '#445', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input type="checkbox" checked={addProd.risk_assessment_required} onChange={e => setAddProd(p => ({ ...p, risk_assessment_required: e.target.checked }))} />
                  Risk Assessment Required
                </label>
                <button type="submit" className="primary" disabled={addProdSaving} style={{ marginTop: 4 }}>
                  {addProdSaving ? 'Saving…' : 'Save to Register'}
                </button>
                {addProdResult && (
                  <p style={{ fontSize: 11, color: addProdResult.startsWith('Error') ? '#c0392b' : '#2C6B33', margin: 0 }}>{addProdResult}</p>
                )}
              </form>
            )}
          </div>

          {/* Send to new customer (no purchase history) */}
          <div className="contact-box" style={{ marginTop: 16 }}>
            <button
              onClick={() => { setShowNewCustomer(v => !v); setNcResult(''); setNcPreviewHtml(null); }}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.78rem', letterSpacing: 1, textTransform: 'uppercase', color: '#667789', display: 'flex', alignItems: 'center', gap: 6, padding: 0 }}
            >
              <Send size={13} />{showNewCustomer ? '▲ Hide' : '▼ New Customer Send'}
            </button>
            {showNewCustomer && (
              <form onSubmit={handleNewCustomerSend} style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <p style={{ fontSize: 11, color: '#607080', margin: 0 }}>Send SDS pack to a customer not yet in the site mapping.</p>
                <div>
                  <label style={{ fontSize: 11, color: '#445', display: 'block', marginBottom: 2 }}>Customer Name *</label>
                  <input required type="text" value={ncForm.customer_name} onChange={e => setNcForm(f => ({ ...f, customer_name: e.target.value }))}
                    style={{ width: '100%', padding: '5px 8px', border: '1px solid #d8e1e8', borderRadius: 5, fontSize: 12, boxSizing: 'border-box' }} />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: '#445', display: 'block', marginBottom: 2 }}>Email *</label>
                  <input required type="email" value={ncForm.email} onChange={e => setNcForm(f => ({ ...f, email: e.target.value }))}
                    style={{ width: '100%', padding: '5px 8px', border: '1px solid #d8e1e8', borderRadius: 5, fontSize: 12, boxSizing: 'border-box' }} />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: '#445', display: 'block', marginBottom: 2 }}>Product Codes (one per line or comma-separated)</label>
                  <textarea required rows={4} value={ncForm.stockcodes_text} onChange={e => setNcForm(f => ({ ...f, stockcodes_text: e.target.value }))}
                    placeholder="AIRDRY5LK&#10;BATHGREEN5L&#10;ALLPURP5L"
                    style={{ width: '100%', padding: '5px 8px', border: '1px solid #d8e1e8', borderRadius: 5, fontSize: 12, boxSizing: 'border-box', resize: 'vertical' }} />
                </div>
                <label style={{ fontSize: 11, color: '#445', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input type="checkbox" checked={ncForm.dry_run} onChange={e => setNcForm(f => ({ ...f, dry_run: e.target.checked }))} />
                  Dry run (preview only, no email sent)
                </label>
                <button type="submit" className="primary" disabled={ncSending}>
                  {ncSending ? 'Sending…' : ncForm.dry_run ? 'Preview' : 'Send'}
                </button>
                {ncResult && (
                  <p style={{ fontSize: 11, color: ncResult.startsWith('Error') ? '#c0392b' : '#2C6B33', margin: 0 }}>{ncResult}</p>
                )}
              </form>
            )}
          </div>

          {/* Bulk send — disabled pending mapping verification */}
          <div className="contact-box" style={{ marginTop: 12, opacity: 0.55, pointerEvents: 'none' }}>
            <label style={{ fontWeight: 700, fontSize: '0.78rem', letterSpacing: 1, textTransform: 'uppercase', color: '#b45309' }}>Bulk send — disabled</label>
            <p style={{ fontSize: 12, color: '#b45309', marginTop: 6 }}>
              Bulk GHL sending is locked until mapping is verified. Use the Send button per site row for individual test sends.
            </p>
            <button className="primary" disabled style={{ marginTop: 8, opacity: 0.4 }}>
              <Send size={16} style={{ marginRight: 6 }} />Send to all sites
            </button>
          </div>
        </aside>

        <div className="main-panel">
          {notice && <div className="notice ok" style={{ marginBottom: 12 }}><CheckCircle2 size={15} /><span>{notice}</span></div>}
          {error && <div className="notice error" style={{ marginBottom: 12 }}><AlertCircle size={15} /><span>{error}</span></div>}

          {/* Search + table */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <input
              type="search"
              placeholder="Search sites…"
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
              style={{ flex: 1, padding: '7px 12px', border: '1px solid #d8e1e8', borderRadius: 6, fontSize: '0.875rem' }}
            />
            <span style={{ fontSize: 12, color: '#607080', whiteSpace: 'nowrap' }}>Page {page}</span>
            <button className="btn-ghost" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>‹</button>
            <button className="btn-ghost" onClick={() => setPage(p => p + 1)} disabled={sites.length < PAGE_SIZE}>›</button>
          </div>

          {loading ? (
            <p style={{ color: '#607080', fontSize: 14 }}>Loading…</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Site</th>
                    <th>Head Office</th>
                    <th>Emails</th>
                    <th style={{ textAlign: 'right' }}>Products</th>
                    <th style={{ textAlign: 'center' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sites.map(site => (
                    <tr key={site.accno} style={{ opacity: site.excluded ? 0.4 : site.held ? 0.65 : 1 }}>
                      <td>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{site.name}</div>
                        <div style={{ fontSize: 11, color: '#607080' }}>#{site.accno}</div>
                      </td>
                      <td style={{ fontSize: 12 }}>{site.ho_name}</td>
                      <td style={{ fontSize: 11, color: '#445', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {(site.emails || []).join('; ')}
                      </td>
                      <td style={{ textAlign: 'right', fontSize: 12 }}>
                        {(site.stockcodes || []).length}
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <div style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
                          <button
                            className="btn-ghost"
                            title={site.held ? 'Remove hold' : 'Put on hold'}
                            style={{
                              fontSize: 10, borderRadius: 4, padding: '2px 6px',
                              color: site.held ? '#e67e22' : '#99aabb',
                              border: `1px solid ${site.held ? '#e67e22' : '#c8d4de'}`,
                            }}
                            onClick={() => toggleHold(site)}
                          >
                            {site.held ? <><Play size={10} style={{ marginRight: 2 }} />Unhold</> : <><Pause size={10} style={{ marginRight: 2 }} />Hold</>}
                          </button>
                          <button
                            className="btn-ghost"
                            style={{
                              fontSize: 10, borderRadius: 4, padding: '2px 6px',
                              color: site.excluded ? '#d35400' : '#2C6B33',
                              border: `1px solid ${site.excluded ? '#d35400' : '#2C6B33'}`,
                            }}
                            onClick={() => toggleExclude(site)}
                          >
                            {site.excluded ? 'Excl' : 'Active'}
                          </button>
                          <button
                            className="btn-ghost"
                            title="Manual send"
                            style={{
                              fontSize: 10, borderRadius: 4, padding: '2px 6px',
                              color: '#5c7cfa', border: '1px solid #5c7cfa',
                            }}
                            onClick={() => openManualSend(site)}
                          >
                            <Mail size={10} style={{ marginRight: 2 }} />Send
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {sites.length === 0 && (
                    <tr><td colSpan={5} style={{ textAlign: 'center', color: '#607080', padding: 24 }}>
                      {stats?.total_sites === 0 ? 'No sites imported yet — upload mapping files.' : 'No results.'}
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Manual send modal */}
      {manualSite && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setManualSite(null)}>
          <div style={{
            background: 'white', borderRadius: 10, padding: 28, width: 480, maxWidth: '95vw',
            maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{manualSite.name}</div>
                <div style={{ fontSize: 11, color: '#607080' }}>#{manualSite.accno} · Manual send</div>
              </div>
              <button className="btn-ghost" onClick={() => setManualSite(null)} style={{ padding: 4 }}>
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleManualSend}>
              <label style={{ fontSize: 12, fontWeight: 600, color: '#445', display: 'block', marginBottom: 4 }}>
                Recipient email
              </label>
              <input
                type="email"
                value={manualEmail}
                onChange={e => setManualEmail(e.target.value)}
                required
                style={{ width: '100%', padding: '7px 10px', border: '1px solid #d8e1e8', borderRadius: 6, fontSize: 13, boxSizing: 'border-box', marginBottom: 14 }}
              />

              <label style={{ fontSize: 12, fontWeight: 600, color: '#445', display: 'block', marginBottom: 6 }}>
                Products to include ({manualCodes.size} selected)
              </label>
              <div style={{ border: '1px solid #e2eaef', borderRadius: 6, maxHeight: 200, overflowY: 'auto', padding: '4px 0', marginBottom: 14 }}>
                {(manualSite.stockcodes || []).map(code => (
                  <label key={code} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px', cursor: 'pointer', fontSize: 12 }}>
                    <input
                      type="checkbox"
                      checked={manualCodes.has(code)}
                      onChange={e => {
                        setManualCodes(prev => {
                          const next = new Set(prev);
                          e.target.checked ? next.add(code) : next.delete(code);
                          return next;
                        });
                      }}
                    />
                    {code}
                  </label>
                ))}
                {(manualSite.stockcodes || []).length === 0 && (
                  <div style={{ padding: '8px 12px', color: '#607080', fontSize: 12 }}>No products on record for this site.</div>
                )}
              </div>

              <div className="toggle-row" style={{ marginBottom: 14 }}>
                <input id="ms-dry-run" type="checkbox" checked={manualDryRun} onChange={e => setManualDryRun(e.target.checked)} />
                <label htmlFor="ms-dry-run" style={{ fontSize: 12 }}>Dry run (no email sent)</label>
              </div>

              {manualResult && (
                <div className={`notice ${manualResult.startsWith('Error') ? 'error' : 'ok'}`} style={{ marginBottom: 12 }}>
                  {manualResult.startsWith('Error') ? <AlertCircle size={14} /> : <CheckCircle2 size={14} />}
                  <span>{manualResult}</span>
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button type="button" className="btn-ghost" onClick={() => setManualSite(null)}>Cancel</button>
                <button
                  type="button"
                  className="btn-ghost"
                  disabled={previewLoading || manualCodes.size === 0}
                  onClick={handlePreview}
                  style={{ border: '1px solid #2C6B33', color: '#2C6B33' }}
                >
                  {previewLoading ? 'Loading…' : 'Preview email'}
                </button>
                <button type="submit" className="primary" disabled={manualSending || manualCodes.size === 0}>
                  <Mail size={14} style={{ marginRight: 6 }} />
                  {manualSending ? 'Sending…' : manualDryRun ? 'Test send' : 'Send now'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Email preview overlay */}
      {previewData && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1100,
          display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
          paddingTop: 40, paddingBottom: 40, overflowY: 'auto',
        }} onClick={() => setPreviewData(null)}>
          <div style={{
            background: '#f3f4f6', borderRadius: 10, width: 700, maxWidth: '96vw',
            boxShadow: '0 12px 40px rgba(0,0,0,0.25)', overflow: 'hidden',
          }} onClick={e => e.stopPropagation()}>
            {/* Email client chrome */}
            <div style={{ background: '#1e2633', padding: '12px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: '#fff', fontWeight: 700, fontSize: 14 }}>Email Preview</span>
              <button onClick={() => setPreviewData(null)} style={{ background: 'none', border: 'none', color: '#aaa', cursor: 'pointer', fontSize: 18, lineHeight: 1 }}>×</button>
            </div>
            {/* Email headers */}
            <div style={{ background: '#fff', borderBottom: '1px solid #e2eaef', padding: '12px 20px', fontSize: 12, color: '#445', lineHeight: 1.8 }}>
              <div><strong>From:</strong> Compliant Cleaning Supplies &lt;ccshub@ccsessentials.com.au&gt;</div>
              <div><strong>To:</strong> {previewData.email}</div>
              <div><strong>Subject:</strong> {previewData.subject}</div>
              {previewData.register_url ? (
                <div style={{ marginTop: 6 }}>
                  <strong>Attachment:</strong>{' '}
                  <a href={previewData.register_url} target="_blank" rel="noreferrer"
                    style={{ color: '#2C6B33', textDecoration: 'underline', fontSize: 12 }}>
                    Chemical Register — {previewData.site_name}.xlsx
                  </a>
                  <span style={{ color: '#607080', marginLeft: 6 }}>(click to download)</span>
                </div>
              ) : (
                <div style={{ marginTop: 6, color: '#b45309', fontSize: 12 }}>
                  <strong>Attachment:</strong> Chemical Register not generated
                  {previewData.register_error && (
                    <span style={{ marginLeft: 6, fontFamily: 'monospace', fontSize: 11 }}>
                      — {previewData.register_error}
                    </span>
                  )}
                </div>
              )}
            </div>
            {/* Email body in iframe */}
            <iframe
              srcDoc={previewData.html}
              title="Email preview"
              style={{ width: '100%', height: 600, border: 'none', background: '#fff', display: 'block' }}
              sandbox="allow-same-origin"
            />
            <div style={{ background: '#f3f4f6', padding: '10px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: '#607080' }}>{previewData.docs} document(s) · {previewData.site_name}</span>
              <button className="btn-ghost" onClick={() => setPreviewData(null)} style={{ fontSize: 12 }}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* Alert email preview overlay */}
      {testAlertPreviewHtml && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1200,
          display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
          padding: '60px 20px', overflowY: 'auto',
        }} onClick={() => setTestAlertPreviewHtml(null)}>
          <div style={{ background: '#fff', borderRadius: 10, width: '100%', maxWidth: 780, boxShadow: '0 8px 40px rgba(0,0,0,0.3)' }}
            onClick={e => e.stopPropagation()}>
            <div style={{ background: '#1a2b3c', color: '#fff', padding: '12px 20px', borderRadius: '10px 10px 0 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>Email preview — {testAlertPreviewHtml.title}</span>
              <button onClick={() => setTestAlertPreviewHtml(null)} style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 20, lineHeight: 1, padding: '0 4px' }}>×</button>
            </div>
            <iframe
              srcDoc={testAlertPreviewHtml.html}
              title="Alert email preview"
              style={{ width: '100%', height: 560, border: 'none', background: '#fff', display: 'block' }}
              sandbox="allow-same-origin"
            />
            <div style={{ background: '#f3f4f6', padding: '10px 20px', display: 'flex', justifyContent: 'flex-end', borderRadius: '0 0 10px 10px' }}>
              <button className="btn-ghost" onClick={() => setTestAlertPreviewHtml(null)} style={{ fontSize: 12 }}>Close</button>
            </div>
          </div>
        </div>
      )}

      {ncPreviewHtml && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1200,
          display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
          padding: '60px 20px', overflowY: 'auto',
        }} onClick={() => setNcPreviewHtml(null)}>
          <div style={{ background: '#fff', borderRadius: 10, width: '100%', maxWidth: 780, boxShadow: '0 8px 40px rgba(0,0,0,0.3)' }}
            onClick={e => e.stopPropagation()}>
            <div style={{ background: '#1a2b3c', color: '#fff', padding: '12px 20px', borderRadius: '10px 10px 0 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>Email preview — {ncPreviewHtml.title}</span>
              <button onClick={() => setNcPreviewHtml(null)} style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 20, lineHeight: 1, padding: '0 4px' }}>×</button>
            </div>
            <iframe
              srcDoc={ncPreviewHtml.html}
              title="New customer email preview"
              style={{ width: '100%', height: 560, border: 'none', background: '#fff', display: 'block' }}
              sandbox="allow-same-origin"
            />
            <div style={{ background: '#f3f4f6', padding: '10px 20px', display: 'flex', justifyContent: 'flex-end', borderRadius: '0 0 10px 10px' }}>
              <button className="btn-ghost" onClick={() => setNcPreviewHtml(null)} style={{ fontSize: 12 }}>Close</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function Pill({ label, value, ok, warn }) {
  const color = ok ? 'var(--ok)' : warn ? 'var(--warn)' : 'var(--muted)';
  return (
    <div style={{ background: 'var(--soft)', border: '1px solid var(--line)', borderRadius: 6, padding: '8px 14px', minWidth: 90 }}>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{value ?? 0}</div>
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data Management page  /data-management
// ---------------------------------------------------------------------------

function DataManagement() {
  const [history, setHistory] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [clearConfirm, setClearConfirm] = useState(false);  // 'all' | table key | false
  const [clearing, setClearing] = useState(false);
  const [clearResult, setClearResult] = useState('');

  async function loadAll() {
    setLoading(true);
    try {
      const [hRes, sRes] = await Promise.all([
        fetch(`${API_BASE}/site-distribution/import-history?limit=10`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/site-distribution/import-status`, { headers: getAuthHeaders() }),
      ]);
      if (hRes.ok) setHistory(await hRes.json());
      if (sRes.ok) setStatus(await sRes.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }

  useEffect(() => { loadAll(); }, []);

  async function handleClear(tables, label) {
    setClearing(true);
    setClearResult('');
    try {
      const r = await fetch(`${API_BASE}/site-distribution/data`, {
        method: 'DELETE',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ tables }),
      });
      if (r.ok) {
        setClearConfirm(false);
        setClearResult(`${label} cleared. Re-upload to repopulate.`);
        loadAll();
      } else {
        setClearResult('Clear failed — check console.');
      }
    } catch (err) { setClearResult(`Error: ${err.message}`); }
    finally { setClearing(false); }
  }

  function fmtTs(ts) {
    if (!ts) return '—';
    return new Date(ts).toLocaleString('en-AU', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: true,
    });
  }

  const th = { fontSize: 11, fontWeight: 700, color: '#667789', textTransform: 'uppercase', letterSpacing: 0.5, padding: '8px 12px', borderBottom: '2px solid #e2eaef', textAlign: 'left', whiteSpace: 'nowrap' };
  const td = { fontSize: 13, padding: '10px 12px', borderBottom: '1px solid #f0f4f8', verticalAlign: 'middle' };

  return (
    <section className="workbench">
      <div className="topbar">
        <div>
          <p className="eyebrow">Compliant Cleaning Supplies</p>
          <h1>Data Management</h1>
        </div>
        <button className="btn-ghost" onClick={loadAll} disabled={loading} style={{ fontSize: 13 }}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      <div style={{ maxWidth: 900, padding: '0 24px 40px' }}>

        {/* Current DB state */}
        <div style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#17202a', marginBottom: 4 }}>Current database state</h2>
          <p style={{ fontSize: 12, color: '#607080', marginBottom: 12 }}>Clear a specific table if you uploaded the wrong file — other tables are unaffected.</p>
          {clearResult && (
            <div style={{ background: '#f0fdf4', border: '1px solid #86efac', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#166534', marginBottom: 12 }}>
              {clearResult}
            </div>
          )}
          {!status && !loading && <p style={{ color: '#607080', fontSize: 13 }}>No data yet — upload mapping files on the Sites page.</p>}
          {status && (() => {
            const TABLES = [
              { key: 'ccs_site_mapping', label: 'Customer–Product Mapping', file: 'Mapping file', also: [] },
              { key: 'ccs_sds_links', label: 'SDS / Risk links + Register metadata', file: 'SDS links, Risk links, Chemical Register', also: [] },
              { key: 'ccs_stock_groups', label: 'Product grouping (size variants)', file: 'Product grouping file', also: [] },
            ];
            return (
              <div style={{ background: '#fff', border: '1px solid #e2eaef', borderRadius: 8, overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead style={{ background: '#f8fafc' }}>
                    <tr>
                      <th style={th}>Table</th>
                      <th style={th}>Populated by</th>
                      <th style={{ ...th, textAlign: 'right' }}>Records</th>
                      <th style={{ ...th, textAlign: 'right' }}>Last import</th>
                      <th style={{ ...th, textAlign: 'center' }}>Clear</th>
                    </tr>
                  </thead>
                  <tbody>
                    {TABLES.map(({ key, label, file }) => {
                      const row = status[key] || {};
                      const isConfirming = clearConfirm === key;
                      return (
                        <tr key={key}>
                          <td style={td}>
                            <div style={{ fontWeight: 600, fontSize: 13 }}>{label}</div>
                            <div style={{ fontSize: 10, color: '#9aabb8', fontFamily: 'monospace' }}>{key}</div>
                          </td>
                          <td style={{ ...td, fontSize: 11, color: '#607080' }}>{file}</td>
                          <td style={{ ...td, textAlign: 'right', fontWeight: 700, color: row.count > 0 ? '#2C6B33' : '#aaa' }}>{row.count ?? 0}</td>
                          <td style={{ ...td, textAlign: 'right', fontSize: 11, color: '#607080' }}>{fmtTs(row.last_import)}</td>
                          <td style={{ ...td, textAlign: 'center' }}>
                            {!isConfirming ? (
                              <button
                                style={{ background: 'none', color: '#c0392b', border: '1px solid #e74c3c', borderRadius: 5, padding: '4px 10px', fontSize: 11, cursor: 'pointer', fontWeight: 600 }}
                                onClick={() => setClearConfirm(key)}
                                disabled={clearing || row.count === 0}
                              >
                                Clear
                              </button>
                            ) : (
                              <div style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
                                <button className="btn-ghost" style={{ fontSize: 11, padding: '3px 8px' }} onClick={() => setClearConfirm(false)}>Cancel</button>
                                <button
                                  style={{ background: '#c0392b', color: '#fff', border: 'none', borderRadius: 5, padding: '3px 10px', fontSize: 11, fontWeight: 700, cursor: 'pointer' }}
                                  disabled={clearing}
                                  onClick={() => handleClear([key], label)}
                                >
                                  {clearing ? '…' : 'Confirm'}
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          })()}
        </div>

        {/* Import history */}
        <div style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#17202a', marginBottom: 4 }}>Import history (last 10)</h2>
          <p style={{ fontSize: 12, color: '#607080', marginBottom: 12 }}>
            Each upload updates matching records by account / stock code. Records not in the new file are kept — the active import is the most recent one.
          </p>
          {loading && <p style={{ color: '#607080', fontSize: 13 }}>Loading…</p>}
          {!loading && (!history || history.length === 0) && (
            <p style={{ color: '#607080', fontSize: 13 }}>No import history yet. Run migration 005 in Supabase then upload files.</p>
          )}
          {history && history.length > 0 && (
            <div style={{ background: '#fff', border: '1px solid #e2eaef', borderRadius: 8, overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead style={{ background: '#f8fafc' }}>
                  <tr>
                    <th style={th}>#</th>
                    <th style={th}>Imported at</th>
                    <th style={{ ...th, textAlign: 'right' }}>Sites</th>
                    <th style={{ ...th, textAlign: 'right' }}>SDS links</th>
                    <th style={{ ...th, textAlign: 'right' }}>Groups</th>
                    <th style={{ ...th, textAlign: 'right' }}>Register</th>
                    <th style={{ ...th, textAlign: 'center' }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((row, i) => (
                    <tr key={row.id} style={{ background: row.status === 'active' ? '#f0fdf4' : '#fff' }}>
                      <td style={{ ...td, color: '#9aabb8', fontSize: 11 }}>{row.id}</td>
                      <td style={{ ...td, fontWeight: row.status === 'active' ? 700 : 400 }}>{fmtTs(row.imported_at)}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{row.sites_count}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{row.sds_links_count}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{row.groups_count}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{row.register_count}</td>
                      <td style={{ ...td, textAlign: 'center' }}>
                        <span style={{
                          display: 'inline-block', padding: '2px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700,
                          background: row.status === 'active' ? '#d1fae5' : '#f3f4f6',
                          color: row.status === 'active' ? '#065f46' : '#6b7280',
                        }}>
                          {row.status === 'active' ? 'Active' : 'Superseded'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Clear all */}
        <div style={{ background: '#fff', border: '1px solid #fca5a5', borderRadius: 8, padding: 20 }}>
          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#991b1b', marginBottom: 6 }}>Clear all imported data</h2>
          <p style={{ fontSize: 12, color: '#607080', marginBottom: 14 }}>
            Deletes all sites, SDS links, stock groups, holds, and exclusions. Import history is preserved.
            Use this before a full re-import to avoid stale records from previous files.
          </p>
          {clearConfirm !== 'all' ? (
            <button
              style={{ background: '#fff', color: '#c0392b', border: '1.5px solid #e74c3c', borderRadius: 6, padding: '8px 18px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
              onClick={() => setClearConfirm('all')}
            >
              Clear all imported data
            </button>
          ) : (
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: '#c0392b', fontWeight: 600 }}>Are you sure? This cannot be undone.</span>
              <button className="btn-ghost" onClick={() => setClearConfirm(false)}>Cancel</button>
              <button
                style={{ background: '#c0392b', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 18px', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}
                disabled={clearing}
                onClick={() => handleClear(['ccs_site_mapping', 'ccs_sds_links', 'ccs_stock_groups', 'ccs_site_exclusions', 'ccs_site_holds'], 'All data')}
              >
                {clearing ? 'Clearing…' : 'Yes, clear all'}
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// New Product Queue  /new-products
// ---------------------------------------------------------------------------

function NewProductQueue() {
  const [queue, setQueue] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testEmail, setTestEmail] = useState('');
  const [selected, setSelected] = useState({});   // {accno: Set<stock_code>}
  const [sending, setSending] = useState('');      // accno currently sending
  const [results, setResults] = useState({});      // {accno: string}

  async function loadQueue() {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/site-distribution/new-products`, { headers: getAuthHeaders() });
      if (r.ok) {
        const data = await r.json();
        setQueue(data);
        const init = {};
        data.forEach(site => {
          init[site.accno] = new Set(site.products.map(p => p.stock_code));
        });
        setSelected(init);
      }
    } finally { setLoading(false); }
  }

  useEffect(() => { loadQueue(); }, []);

  function toggleCode(accno, code) {
    setSelected(prev => {
      const s = new Set(prev[accno] || []);
      if (s.has(code)) s.delete(code); else s.add(code);
      return { ...prev, [accno]: s };
    });
  }

  function toggleAll(accno, codes, checked) {
    setSelected(prev => ({ ...prev, [accno]: checked ? new Set(codes) : new Set() }));
  }

  async function handleSend(site, dryRun) {
    const codes = [...(selected[site.accno] || [])];
    if (!codes.length) return;
    const email = testEmail || (site.emails || [])[0] || '';
    if (!email) { setResults(r => ({ ...r, [site.accno]: 'No email address — set Test Contact above' })); return; }
    setSending(site.accno);
    try {
      const r = await fetch(`${API_BASE}/site-distribution/new-products/send`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ accno: site.accno, stockcodes: codes, email, dry_run: dryRun }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || 'Failed');
      setResults(r => ({ ...r, [site.accno]: `${dryRun ? 'Dry run OK' : 'Sent'} — ${data.docs} doc(s) to ${data.email}` }));
      if (!dryRun) loadQueue();
    } catch (err) {
      setResults(r => ({ ...r, [site.accno]: `Error: ${err.message}` }));
    } finally { setSending(''); }
  }

  return (
    <section className="workbench">
      <div className="topbar">
        <div>
          <p className="eyebrow">Compliant Cleaning Supplies</p>
          <h1>New Product Queue</h1>
        </div>
        <div style={{ fontSize: 13, color: '#607080' }}>
          Sites with product codes added since last send · Detected daily 5pm AEST
        </div>
      </div>

      <div style={{ maxWidth: 860, margin: '0 auto', padding: '0 0 40px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, padding: '12px 16px', background: '#f0f4ff', borderRadius: 8, border: '1px solid #c9d8ff' }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: '#334', whiteSpace: 'nowrap' }}>Test / override email</label>
          <input
            type="email"
            value={testEmail}
            onChange={e => setTestEmail(e.target.value)}
            placeholder="staff@example.com (blank = use site email)"
            style={{ flex: 1, padding: '7px 10px', border: '1px solid #c9d8ff', borderRadius: 6, fontSize: 13 }}
          />
        </div>

        {loading ? (
          <p style={{ color: '#607080', fontSize: 14 }}>Loading…</p>
        ) : queue.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#607080', fontSize: 14 }}>
            No pending new products. Queue is empty — all detected products have been actioned.
          </div>
        ) : (
          queue.map(site => {
            const codes = site.products.map(p => p.stock_code);
            const sel = selected[site.accno] || new Set();
            const allChecked = codes.every(c => sel.has(c));
            return (
              <div key={site.accno} style={{ background: '#fff', border: '1px solid #e0e8f0', borderRadius: 8, marginBottom: 16, overflow: 'hidden' }}>
                <div style={{ padding: '12px 16px', background: '#f8fafc', borderBottom: '1px solid #e0e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span style={{ fontWeight: 700, fontSize: 14 }}>{site.name}</span>
                    <span style={{ fontSize: 11, color: '#607080', marginLeft: 8 }}>#{site.accno}</span>
                    <span style={{ fontSize: 11, color: '#607080', marginLeft: 8 }}>{site.emails?.join('; ')}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{ fontSize: 11, color: '#607080' }}>{sel.size}/{codes.length} selected</span>
                    <button
                      className="btn-ghost"
                      style={{ fontSize: 11, padding: '3px 8px' }}
                      onClick={() => handleSend(site, true)}
                      disabled={sending === site.accno || !sel.size}
                    >Preview dry run</button>
                    <button
                      style={{ background: '#2C6B33', color: '#fff', border: 'none', borderRadius: 5, padding: '5px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
                      onClick={() => handleSend(site, false)}
                      disabled={sending === site.accno || !sel.size}
                    >
                      {sending === site.accno ? 'Sending…' : 'Send'}
                    </button>
                  </div>
                </div>
                {results[site.accno] && (
                  <div style={{ padding: '6px 16px', background: results[site.accno].startsWith('Error') ? '#fff5f5' : '#f0fdf4', fontSize: 12, color: results[site.accno].startsWith('Error') ? '#c0392b' : '#2C6B33', borderBottom: '1px solid #e0e8f0' }}>
                    {results[site.accno]}
                  </div>
                )}
                <div style={{ padding: '10px 16px' }}>
                  <label style={{ fontSize: 11, color: '#607080', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                    <input type="checkbox" checked={allChecked} onChange={e => toggleAll(site.accno, codes, e.target.checked)} />
                    Select all
                  </label>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {site.products.map(p => (
                      <label key={p.stock_code} style={{ fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, padding: '3px 8px', background: sel.has(p.stock_code) ? '#e8f5e9' : '#f5f7fa', border: `1px solid ${sel.has(p.stock_code) ? '#2C6B33' : '#d8e1e8'}`, borderRadius: 4 }}>
                        <input type="checkbox" checked={sel.has(p.stock_code)} onChange={() => toggleCode(site.accno, p.stock_code)} />
                        {p.stock_code}
                        <span style={{ fontSize: 10, color: '#99aabb' }}>{p.first_seen_at?.slice(0,10)}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

createRoot(document.getElementById('root')).render(<Root />);
