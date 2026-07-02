import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertCircle, CheckCircle2, FileSpreadsheet, Link2, Send, Upload } from 'lucide-react';
import './styles.css';

const API_BASE = '/api';

function App() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [contactsText, setContactsText] = useState('Test Contact <test@example.com>');
  const [dryRun, setDryRun] = useState(true);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [sendResult, setSendResult] = useState(null);

  const contacts = useMemo(() => parseContacts(contactsText), [contactsText]);

  async function uploadRegister(event) {
    event.preventDefault();
    if (!file) {
      setError('Select an Excel register first.');
      return;
    }
    setLoading(true);
    setError('');
    setSendResult(null);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${API_BASE}/register/preview`, {
        method: 'POST',
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Upload failed.');
      setPreview(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function sendTestDistribution() {
    if (!preview) {
      setError('Upload and preview a register first.');
      return;
    }
    if (contacts.length === 0) {
      setError('Add at least one test contact email.');
      return;
    }
    setSending(true);
    setError('');

    try {
      const response = await fetch(`${API_BASE}/distribution/test-send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preview, contacts, dry_run: dryRun }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Distribution failed.');
      setSendResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="shell">
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
              <label htmlFor="register-file">Chemical register</label>
              <input
                id="register-file"
                type="file"
                accept=".xlsx,.xlsm"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
              <button type="submit" disabled={loading} className="primary">
                <Upload size={18} />
                {loading ? 'Uploading' : 'Preview'}
              </button>
            </form>

            <div className="contact-box">
              <label htmlFor="test-contacts">Test contacts</label>
              <textarea
                id="test-contacts"
                value={contactsText}
                onChange={(event) => setContactsText(event.target.value)}
                rows={6}
              />
              <div className="toggle-row">
                <input
                  id="dry-run"
                  type="checkbox"
                  checked={dryRun}
                  onChange={(event) => setDryRun(event.target.checked)}
                />
                <label htmlFor="dry-run">Dry run</label>
              </div>
              <button type="button" onClick={sendTestDistribution} disabled={sending || !preview} className="primary">
                <Send size={18} />
                {sending ? 'Processing' : 'Process Test Email'}
              </button>
            </div>

            {error && (
              <div className="notice error">
                <AlertCircle size={18} />
                <span>{error}</span>
              </div>
            )}
          </aside>

          <section className="main-panel">
            {!preview ? <EmptyState /> : <PreviewPanel preview={preview} />}
            {sendResult && <SendResult result={sendResult} />}
          </section>
        </div>
      </section>
    </main>
  );
}

function StatusPill({ preview, sendResult }) {
  if (sendResult) {
    return (
      <div className="status success">
        <CheckCircle2 size={18} />
        {sendResult.dry_run ? 'Dry run prepared' : 'Send requested'}
      </div>
    );
  }
  if (preview) {
    return (
      <div className="status success">
        <CheckCircle2 size={18} />
        Register parsed
      </div>
    );
  }
  return (
    <div className="status neutral">
      <FileSpreadsheet size={18} />
      Awaiting register
    </div>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <FileSpreadsheet size={34} />
      <h2>Upload a CCS chemical register</h2>
      <p>The preview will show customer details, selected products, SDS links, and risk-assessment matches.</p>
    </div>
  );
}

function PreviewPanel({ preview }) {
  return (
    <div className="preview-grid">
      <div className="section-head">
        <div>
          <p className="eyebrow">Preview</p>
          <h2>{preview.register.title}</h2>
        </div>
        <span className="count">{preview.products.length} products</span>
      </div>

      <div className="info-grid">
        <Info label="Customer" value={preview.customer.company || 'Not found'} />
        <Info label="Contact" value={preview.customer.contact_name || 'Not found'} />
        <Info label="Phone" value={preview.customer.phone || 'Not found'} />
        <Info label="Register date" value={preview.register.date || 'Not found'} />
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Code</th>
              <th>Product</th>
              <th>SDS</th>
              <th>Risk</th>
              <th>Expiry</th>
            </tr>
          </thead>
          <tbody>
            {preview.products.map((product) => (
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
  return (
    <div className="info">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DocCell({ document }) {
  if (!document?.matched) return <span className="missing">Missing</span>;
  return (
    <a className="doc-link" href={document.url} target="_blank" rel="noreferrer">
      <Link2 size={15} />
      Open
    </a>
  );
}

function SendResult({ result }) {
  return (
    <div className="send-result">
      <div className="section-head">
        <div>
          <p className="eyebrow">Distribution</p>
          <h2>{result.summary.messages} test email payloads</h2>
        </div>
        <span className="count">{result.dry_run ? 'Dry run' : 'Live mode'}</span>
      </div>

      <div className="info-grid">
        <Info label="Contacts" value={String(result.summary.contacts)} />
        <Info label="Products" value={String(result.summary.products)} />
        <Info label="GHL" value={result.ghl?.status || 'prepared'} />
        <Info label="Supabase" value={result.supabase?.status || 'prepared'} />
      </div>

      <div className="message-list">
        {result.messages.map((message) => (
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
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const bracketMatch = line.match(/^(.*?)<([^>]+)>$/);
      if (bracketMatch) {
        return { name: bracketMatch[1].trim(), email: bracketMatch[2].trim() };
      }
      const parts = line.split(',');
      if (parts.length >= 2) {
        return { name: parts[0].trim(), email: parts[1].trim() };
      }
      return { name: '', email: line };
    })
    .filter((contact) => contact.email.includes('@'));
}

createRoot(document.getElementById('root')).render(<App />);
