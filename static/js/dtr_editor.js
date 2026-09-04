/**
 * DTR Inline Cell Editor
 * Double-click to edit any non-weekend, non-readonly cell.
 * Auto-saves to backend on blur or Enter. Logs audit trail.
 */

let activeCell = null;
const editor = document.getElementById('cell-editor');

function startEdit(td) {
  if (td.classList.contains('cell-readonly')) return;

  // If another cell was being edited, save it first
  if (activeCell && activeCell !== td) commitEdit(activeCell);

  activeCell = td;
  td.classList.add('cell-editing');

  // Position the floating input over the cell
  const rect = td.getBoundingClientRect();
  editor.style.left = (rect.left + window.scrollX) + 'px';
  editor.style.top = (rect.top + window.scrollY) + 'px';
  editor.style.width = rect.width + 'px';
  editor.style.display = 'block';
  editor.value = td.dataset.original || '';
  editor.focus();
  editor.select();
}

// Append AM/PM based on the slot and hour, mirroring the server-side logic.
function slotPeriod(slot, val) {
  if (!val || !val.includes(':')) return '';
  const hour = parseInt(val.split(':')[0], 10);
  if (slot === 'PM_IN' || slot === 'PM_OUT') return 'PM';
  if (hour === 12) return 'PM';
  return 'AM';
}

function withPeriod(slot, val) {
  if (!val) return '';
  const p = slotPeriod(slot, val);
  return p ? `${val} ${p}` : val;
}

function commitEdit(td) {
  if (!td) return;
  const rawVal = editor.value.trim();
  const newVal = validateTime(rawVal);

  const display = td.querySelector('.cell-display');
  const originalVal = td.dataset.original;
  const originalFlagged = td.classList.contains('cell-flagged');

  display.textContent = withPeriod(td.dataset.slot, newVal);
  td.classList.remove('cell-editing', 'cell-flagged');

  // Only save if changed
  if (newVal !== originalVal) {
    saveCell(td, originalVal, newVal, originalFlagged);
    td.dataset.original = newVal;
  }

  editor.style.display = 'none';
  activeCell = null;
}

function validateTime(val) {
  if (!val) return '';
  // Accept regular 12-hour time like 7:58, 12:03, or 531.
  val = val.replace(/[^0-9:]/g, '');
  if (!val.includes(':')) {
    if (val.length === 3) val = val.slice(0, 1) + ':' + val.slice(1);
    if (val.length === 4) val = val.slice(0, 2) + ':' + val.slice(2);
  }
  const match = val.match(/^(\d{1,2}):([0-5]\d)$/);
  if (!match) return '';
  const hour = parseInt(match[1], 10);
  if (hour < 1 || hour > 12) return '';
  return `${hour}:${match[2]}`;
}

function restoreCellAfterFailedSave(td, originalVal, attemptedVal, originalFlagged) {
  // Do not overwrite a newer edit if another save started while this one waited.
  if (td.dataset.original !== attemptedVal) return;
  td.dataset.original = originalVal;
  td.querySelector('.cell-display').textContent = withPeriod(td.dataset.slot, originalVal);
  if (originalFlagged) td.classList.add('cell-flagged');
}

async function saveCell(td, originalVal, newVal, originalFlagged) {
  const adminUser = document.getElementById('admin-user')?.value || 'HR Admin';
  try {
    const res = await fetch('/dtr/cell/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        employee_id: parseInt(td.dataset.employee),
        work_date: td.dataset.date,
        slot: td.dataset.slot,
        new_value: newVal,
        admin_user: adminUser,
      }),
    });
    if (!res.ok) {
      console.error('Save failed', await res.text());
      restoreCellAfterFailedSave(td, originalVal, newVal, originalFlagged);
      showToast('Save failed — check console.', 'danger');
      return false;
    } else {
      const data = await res.json();
      updateUndertimeCell(td.dataset.date, data.undertime);
      showToast(`Saved ${td.dataset.slot} on ${td.dataset.date}`, 'success');
      return true;
    }
  } catch (e) {
    restoreCellAfterFailedSave(td, originalVal, newVal, originalFlagged);
    showToast('Network error saving cell.', 'danger');
    return false;
  }
}

// Editor event bindings
editor.addEventListener('keydown', e => {
  if (e.key === 'Enter') { commitEdit(activeCell); }
  if (e.key === 'Escape') {
    editor.style.display = 'none';
    if (activeCell) activeCell.classList.remove('cell-editing');
    activeCell = null;
  }
  // Tab to next cell
  if (e.key === 'Tab') {
    e.preventDefault();
    const current = activeCell;
    commitEdit(current);
    const allCells = Array.from(document.querySelectorAll('.dtr-cell:not(.cell-readonly)'));
    const idx = allCells.indexOf(current);
    const next = allCells[idx + (e.shiftKey ? -1 : 1)];
    if (next) startEdit(next);
  }
});

editor.addEventListener('blur', () => {
  setTimeout(() => { if (activeCell) commitEdit(activeCell); }, 100);
});

// Click outside = commit
document.addEventListener('click', e => {
  if (activeCell && e.target !== editor && !activeCell.contains(e.target)) {
    commitEdit(activeCell);
  }
});

// Refresh the row's Undertime cell after an edit recomputes it server-side.
function updateUndertimeCell(dateStr, ut) {
  if (!ut) return;
  const td = document.querySelector(`.ut-cell[data-ut-date="${dateStr}"]`);
  if (!td) return;
  if (ut.total > 0) {
    td.textContent = (ut.hours ? ut.hours + 'h ' : '') + ut.minutes + 'm';
    td.classList.add('text-danger', 'fw-semibold');
    td.classList.remove('text-muted');
  } else {
    td.textContent = '—';
    td.classList.remove('text-danger', 'fw-semibold');
    td.classList.add('text-muted');
  }
}

// Toast notification
function showToast(msg, type = 'success') {
  const id = 'toast-' + Date.now();
  const div = document.createElement('div');
  div.innerHTML = `
    <div id="${id}" class="toast align-items-center text-bg-${type} border-0 show" role="alert" style="position:fixed;bottom:1rem;right:1rem;z-index:9999">
      <div class="d-flex">
        <div class="toast-body">${msg}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" onclick="this.closest('.toast').remove()"></button>
      </div>
    </div>`;
  document.body.appendChild(div);
  setTimeout(() => div.remove(), 3000);
}
