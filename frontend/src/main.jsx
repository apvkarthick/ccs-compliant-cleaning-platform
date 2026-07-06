import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createClient } from '@supabase/supabase-js';
import { AlertCircle, CheckCircle2, Download, FileSpreadsheet, Link2, LogOut, Send, Upload } from 'lucide-react';
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
  async function handleSignOut() {
    await supabase.auth.signOut();
  }

  return (
    <main className="shell">
      <div className="tab-bar">
        <button className="tab active">Distribution</button>
        <a className="tab" href="/rebrand">Rebrand SDS</a>
        <button className="tab tab-signout" onClick={handleSignOut} title="Sign out">
          <LogOut size={14} />
        </button>
      </div>
      <DistributionDesk />
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

function parseContacts(value) {
  return value.split(/\r?\n/).map(l => l.trim()).filter(Boolean).map(line => {
    const m = line.match(/^(.*?)<([^>]+)>$/);
    if (m) return { name: m[1].trim(), email: m[2].trim() };
    const parts = line.split(',');
    if (parts.length >= 2) return { name: parts[0].trim(), email: parts[1].trim() };
    return { name: '', email: line };
  }).filter(c => c.email.includes('@'));
}

createRoot(document.getElementById('root')).render(<Root />);
