"""The explorer Worker's data route: version header and pinned candidate selection."""

from __future__ import annotations

import subprocess
from pathlib import Path

WORKER = Path(__file__).resolve().parents[1] / "deploy/cloudflare-explorer/src/worker.js"


def test_worker_version_headers_and_candidate_promotion():
    script = r"""
import fs from 'node:fs';
import assert from 'node:assert/strict';
const source = fs.readFileSync(process.argv[1], 'utf8');
const {default: worker} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const seen = [];
const object = {size: 4, httpEtag: 'etag', writeHttpMetadata() {}};
const prefix = 'candidates/' + 'a'.repeat(64);
const env = {
  CF_VERSION_METADATA: {id: 'test-version'}, DATA_CANDIDATE_PREFIX: prefix,
  BUCKET: {async head(key) {seen.push(key); return object;}, async get(key, opts) {seen.push(key); return {...object, body: 'data', ...(opts.range.has('range') ? {range: {offset: 0, length: 1}} : {})};}}
};
for (const method of ['GET', 'HEAD']) {
  for (const range of [false, true]) {
    const response = await worker.fetch(new Request('https://example.test/data/test.parquet', {method, headers: range ? {range: 'bytes=0-0'} : {}}), env, {});
    assert.equal(response.headers.get('x-atlas-worker-version'), 'test-version');
    assert.equal(response.status, range ? 206 : 200);
    assert.equal(seen.at(-1), prefix + '/test.parquet');
  }
}
await worker.fetch(new Request('https://example.test/data/' + prefix + '/test.parquet'), env, {});
assert.equal(seen.at(-1), prefix + '/test.parquet');
const wrong = 'candidates/' + 'b'.repeat(64);
env.DATA_CANDIDATE_PREFIX = wrong;
await worker.fetch(new Request('https://example.test/data/test.parquet'), env, {});
assert.equal(seen.at(-1), wrong + '/test.parquet');
await worker.fetch(new Request('https://example.test/data/' + prefix + '/test.parquet'), env, {});
assert.equal(seen.at(-1), prefix + '/test.parquet');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(WORKER)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
