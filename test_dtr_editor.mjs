import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function classList() {
  const values = new Set();
  return {
    add: (...names) => names.forEach(name => values.add(name)),
    remove: (...names) => names.forEach(name => values.delete(name)),
    contains: name => values.has(name),
  };
}

test('a failed save restores the value that is actually stored', async () => {
  const editor = {
    style: {}, value: '', addEventListener() {}, focus() {}, select() {},
  };
  const display = { textContent: '8:00 AM' };
  const td = {
    classList: classList(),
    dataset: {
      original: '8:00', slot: 'AM_IN', employee: '1', date: '2026-07-01',
    },
    contains: () => false,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 80 }),
    querySelector: () => display,
  };
  const document = {
    addEventListener() {},
    body: { appendChild() {} },
    createElement: () => ({ innerHTML: '', remove() {} }),
    getElementById: id => id === 'cell-editor' ? editor : { value: 'HR Admin' },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  const context = vm.createContext({
    console: { error() {} },
    document,
    fetch: async () => ({ ok: false, text: async () => 'failed' }),
    parseInt,
    setTimeout: callback => callback(),
    window: { scrollX: 0, scrollY: 0 },
  });
  const source = readFileSync('static/js/dtr_editor.js', 'utf8');
  vm.runInContext(source, context);

  context.startEdit(td);
  editor.value = '9:00';
  context.commitEdit(td);
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(td.dataset.original, '8:00');
  assert.equal(display.textContent, '8:00 AM');
});
