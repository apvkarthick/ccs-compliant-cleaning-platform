import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertCircle, CheckCircle2, Download, FileSpreadsheet, Link2, Send, Upload } from 'lucide-react';
import './styles.css';

const API_BASE = '/api';

function App() {
  return (
    <main className="shell">
      <div className="tab-bar">
        <button className="tab active">Distribution</button>
        <a className="tab" href="/rebrand">Rebrand SDS</a>
      </div>
      <DistributionDesk />
    </main>
  );
}

// ---------------------------------------------------------------------------
// Rebrand tab
// ---------------------------------------------------------------------------

function RebrandDesk() {
  const [files, setFiles] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [running, setRunning] = useState(false);
  const inputRef = useRef(null);

  function onFilePick(e) {
    const picked = Array.from(e.target.files || []).filter(f => f.name.toLowerCase().endsWith('.docx'));
    setFiles(picked);
    setJobs(picked.map(f => ({ name: f.name, status: 'pending', url: null, error: null })));
  }

  async function runRebrand() {
    if (!files.length) return;
    setRunning(true);
    const updated = jobs.map(j => ({ ...j, status: 'pending', url: null, error: null }));
    setJobs([...updated]);

    for (let i = 0; i < files.length; i++) {
      setJobs(prev => prev.map((j, idx) => idx === i ? { ...j, status: 'processing' } : j));
      try {
        const fd = new FormData();
        fd.append('file', files[i]);
        const res = await fetch(`${API_BASE}/rebrand/sds`, { method: 'POST', body: fd });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail || 'Server error');
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const oldSupplier = res.headers.get('X-CCS-Old-Supplier') || '';
        const changes = res.headers.get('X-CCS-Changes') || '0';
        setJobs(prev => prev.map((j, idx) => idx === i
          ? { ...j, status: 'done', url, changes: parseInt(changes), oldSupplier }
          : j));
      } catch (err) {
        setJobs(prev => prev.map((j, idx) => idx === i ? { ...j, status: 'error', error: err.message } : j));
      }
    }
    setRunning(false);
  }

  function downloadAll() {
    jobs.filter(j => j.url).forEach(j => {
      const a = document.createElement('a');
      a.href = j.url;
      a.download = j.name.replace('.docx', '_ccs_branded.docx');
      a.click();
    });
  }

  const doneCount = jobs.filter(j => j.status === 'done').length;

  return (
    <section className="workbench">
      <div className="topbar">
        <div>
          <p className="eyebrow">Compliant Cleaning Supplies</p>
          <h1>Rebrand SDS</h1>
        </div>
        {doneCount > 0 && (
          <div className="status success"><CheckCircle2 size={18} />{doneCount} branded</div>
        )}
      </div>

      <div className="layout">
        <aside className="side-panel">
          <div className="upload-box">
            <label>Select DOCX files</label>
            <input ref={inputRef} type="file" accept=".docx" multiple onChange={onFilePick} />
            <button className="primary" onClick={runRebrand} disabled={running || !files.length}>
              <Upload size={18} />{running ? 'Processing…' : `Rebrand ${files.length || ''} file${files.length !== 1 ? 's' : ''}`}
            </button>
            {doneCount > 1 && (
              <button className="secondary" onClick={downloadAll}>
                <Download size={18} />Download all
              </button>
            )}
          </div>
          <div className="notice info" style={{marginTop:'1rem', fontSize:'0.82rem', color:'#64748b'}}>
            <span>Each file is rebranded locally on the server. Logo, supplier block, SDS date, and all body references are replaced with CCS details.</span>
          </div>
        </aside>

        <section className="main-panel">
          {jobs.length === 0
            ? <div className="empty-state"><Upload size={34}/><h2>Select .docx SDS files</h2><p>Upload one or multiple supplier SDS documents to rebrand them with CCS identity.</p></div>
            : <RebrandJobList jobs={jobs} />}
        </section>
      </div>
    </section>
  );
}

function RebrandJobList({ jobs }) {
  return (
    <div className="preview-grid">
      <div className="section-head"><div><p className="eyebrow">Files</p><h2>{jobs.length} document{jobs.length !== 1 ? 's' : ''}</h2></div></div>
      <div className="message-list">
        {jobs.map((job, i) => (
          <article key={`${job.name}-${i}`} className="message" style={{alignItems:'center', gap:'0.6rem'}}>
            <div style={{flex:1}}>
              <strong style={{fontSize:'0.9rem'}}>{job.name}</strong>
              {job.oldSupplier && <div style={{fontSize:'0.78rem',color:'#94a3b8',marginTop:'2px'}}>Replaced: {job.oldSupplier} → CCS</div>}
              {job.error && <div style={{fontSize:'0.78rem',color:'#f87171',marginTop:'2px'}}>{job.error}</div>}
            </div>
            <JobBadge status={job.status} changes={job.changes} />
            {job.url && (
              <a href={job.url} download={job.name.replace('.docx','_ccs_branded.docx')} className="doc-link" style={{whiteSpace:'nowrap'}}>
                <Download size={15}/>Download
              </a>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}

function JobBadge({ status, changes }) {
  const map = { pending: ['#475569','Pending'], processing: ['#38bdf8','Processing…'], done: ['#34d399',`Done · ${changes} changes`], error: ['#f87171','Error'] };
  const [color, label] = map[status] || ['#475569', status];
  return <span style={{fontSize:'0.75rem',fontWeight:700,color,whiteSpace:'nowrap'}}>{label}</span>;
}

// ---------------------------------------------------------------------------
// Distribution tab (original App content)
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
        .map((contact) => `${contact.name || contact.company || 'Contact'} <${contact.email}>`)
        .join('\n')
    );
  }, [preview]);

  async function uploadRegister(event) {
    event.preventDefault();
    if (!file) {
      setError('Select a client workbook first.');
      return;
    }
    setLoading(true);
    setError('');
    setSendResult(null);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${API_BASE}/workbook/preview`, {
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
      setError('Upload and preview a client workbook first.');
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
        Workbook parsed
      </div>
    );
  }
  return (
    <div className="status neutral">
      <FileSpreadsheet size={18} />
      Awaiting workbook
    </div>
  );
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
        <Info label="Workbook date" value={preview.register.date || 'Not found'} />
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
