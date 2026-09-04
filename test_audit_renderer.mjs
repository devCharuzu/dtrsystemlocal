import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

test('audit history renders user-entered names as text, not markup', () => {
  const context = vm.createContext({ Date });
  vm.runInContext(readFileSync('static/js/audit_renderer.js', 'utf8'), context);

  const html = context.renderAuditRows([{
    admin: '<img src=x onerror=alert(1)>',
    work_date: '2026-07-01',
    changed_at: '2026-07-01T08:00:00',
    slot: 'AM_IN',
    original: '8:00 AM',
    new: '8:01 AM',
  }]);

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});
