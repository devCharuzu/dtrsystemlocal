/** Render audit rows while treating every server-provided value as text. */
function escapeHtml(value) {
  return String(value ?? '').replace(
    /[&<>"']/g,
    char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char],
  );
}

function renderAuditRows(logs) {
  if (!logs.length) {
    return '<tr><td colspan="6" class="text-center text-muted">No edits recorded.</td></tr>';
  }
  const slotLabel = {
    AM_IN: 'AM Arrival', AM_OUT: 'AM Departure',
    PM_IN: 'PM Arrival', PM_OUT: 'PM Departure',
  };
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  return logs.map(log => {
    const workDate = new Date(`${log.work_date}T00:00:00`);
    const day = days[workDate.getDay()];
    const date = workDate.toLocaleDateString('en-PH', {
      month: 'short', day: 'numeric', year: 'numeric',
    });
    const changedAt = new Date(log.changed_at);
    const changed = changedAt.toLocaleDateString('en-PH', {
      month: 'short', day: 'numeric', year: 'numeric',
    }) + ' ' + changedAt.toLocaleTimeString('en-PH', {
      hour: 'numeric', minute: '2-digit', hour12: true,
    });
    return `<tr>
      <td class="fw-semibold">${escapeHtml(log.admin)}</td>
      <td class="small"><span class="fw-semibold">${escapeHtml(day)}</span>, ${escapeHtml(date)}</td>
      <td class="audit-col-slot"><span class="badge bg-light text-dark border">${escapeHtml(slotLabel[log.slot] || log.slot)}</span></td>
      <td class="audit-col-original"><span class="badge bg-secondary">${escapeHtml(log.original || '—')}</span></td>
      <td class="audit-col-new"><span class="badge bg-primary">${escapeHtml(log.new || '—')}</span></td>
      <td class="text-end small text-muted audit-col-date-changed">${escapeHtml(changed)}</td>
    </tr>`;
  }).join('');
}
