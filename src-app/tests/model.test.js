import test from 'node:test';
import assert from 'node:assert/strict';
import { resultVariant, progressFraction, pathKey } from '../ui/model.js';

test('an intact subset must never present a successful complete backup', () => {
  for (const verifyResult of [
    { result: 'INTACT', run_verdict: 'FAIL' },
    { result: 'INTACT', run_verdict: 'SAFE TO FORMAT', unfinished_copy: true },
    { result: 'INCOMPLETE', run_verdict: 'SAFE TO FORMAT' },
  ]) assert.equal(resultVariant({ verifyResult }), 'incomplete');
});
test('process failures take precedence over earlier success events', () => {
  assert.equal(resultVariant({ report: { verdict: 'SAFE TO FORMAT' }, exitCode: -1 }), 'error');
  assert.equal(resultVariant({ report: { verdict: 'SAFE TO FORMAT' }, cancelled: true }), 'cancelled');
  assert.equal(resultVariant({}), 'error');
});
test('verified copies and damaged copies have distinct outcomes', () => {
  assert.equal(resultVariant({ report: { verdict: 'SAFE TO FORMAT' }, exitCode: 0 }), 'safe');
  assert.equal(resultVariant({ verifyResult: { result: 'INTACT', run_verdict: 'SAFE TO FORMAT' } }), 'intact');
  assert.equal(resultVariant({ verifyResult: { result: 'DAMAGED' } }), 'damaged');
});
test('reading every byte is not the same as finishing verification', () => {
  assert.equal(progressFraction({ bytes_done: 100, files_done: 0 }, { totalBytes: 100, totalFiles: 1 }), 0.8);
  assert.equal(progressFraction({ bytes_done: 100, files_done: 1 }, { totalBytes: 100, totalFiles: 1 }), 1);
  assert.equal(progressFraction({ bytes_done: 0, files_done: 1 }, { totalBytes: 0, totalFiles: 2 }), 0.9);
});
test('destination comparisons ignore Windows case and separators', () => {
  assert.equal(pathKey('E:/Backups/Photos/'), pathKey('e:\\backups\\photos'));
});
