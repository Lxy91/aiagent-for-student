import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { once } from 'node:events';
import { readConfiguration, createModelService, extensionOrigin } from '../service.mjs';
import { requestProfile } from '../local-model-client.js';

const origin = `chrome-extension://${'a'.repeat(32)}`;
async function withService(config, generate, run) {
  const server = createModelService(config, origin, generate);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    await run(`http://127.0.0.1:${server.address().port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}
const config = {
  modelBase: 'https://model.example/v1',
  model: 'test-model',
  apiKey: 'server-only-secret',
};

test('independent .env is parsed at runtime and environment overrides it', async () => {
  const folder = await mkdtemp(path.join(tmpdir(), 'qicheng-env-test-'));
  try {
    const file = path.join(folder, '.env');
    await writeFile(
      file,
      'MODEL_API_BASE=https://model.example/v1\nMODEL_NAME="from-file"\nMODEL_API_KEY="private-key"\n',
    );
    const loaded = await readConfiguration(file, { MODEL_NAME: 'from-environment' });
    assert.equal(loaded.model, 'from-environment');
    assert.equal(loaded.apiKey, 'private-key');
    assert.equal(loaded.modelBase, 'https://model.example/v1');
  } finally {
    if (
      path.dirname(path.resolve(folder)) !== path.resolve(tmpdir()) ||
      !path.basename(folder).startsWith('qicheng-env-test-')
    )
      throw new Error('Invalid cleanup path');
    await rm(folder, { recursive: true, force: true });
  }
});

test('only the fixed extension may generate and provider settings stay server-side', async () => {
  const calls = [];
  await withService(
    config,
    async (...args) => {
      calls.push(args);
      return { fields: [{ key: 'full_name', value: '李青' }], omitted_count: 0 };
    },
    async (base) => {
      const health = await (await fetch(`${base}/health`)).text();
      assert.equal(health.includes(config.apiKey), false);
      assert.equal(JSON.parse(health).configured, true);
      for (const denied of ['https://evil.example', `chrome-extension://${'b'.repeat(32)}`]) {
        const blocked = await fetch(`${base}/profile`, {
          method: 'POST',
          headers: { Origin: denied, 'Content-Type': 'application/json' },
          body: '{"source":"李青"}',
        });
        assert.equal(blocked.status, 403);
      }
      const response = await fetch(`${base}/profile`, {
        method: 'POST',
        headers: {
          Origin: origin,
          'Content-Type': 'application/json',
          'X-Qicheng-Plugin': 'application-assistant',
        },
        body: JSON.stringify({
          source: '李青',
          modelBase: 'https://evil.example',
          apiKey: 'attacker',
        }),
      });
      assert.equal(response.status, 200);
      assert.equal(response.headers.get('access-control-allow-origin'), origin);
      const text = await response.text();
      assert.equal(text.includes(config.apiKey), false);
      assert.equal(calls.length, 1);
      assert.deepEqual(calls[0], [
        '李青',
        { modelBase: config.modelBase, model: config.model },
        config.apiKey,
      ]);
    },
  );
});

test('missing configuration and invalid source fail without exposing secrets', async () => {
  await withService(
    { ...config, apiKey: '' },
    () => {
      throw new Error('Unexpected model call');
    },
    async (base) => {
      const response = await fetch(`${base}/profile`, {
        method: 'POST',
        headers: {
          Origin: origin,
          'Content-Type': 'application/json',
          'X-Qicheng-Plugin': 'application-assistant',
        },
        body: '{"source":"李青"}',
      });
      assert.equal(response.status, 503);
      assert.match(await response.text(), /\.env/);
    },
  );
});

test('browser client posts only source to the local service, never a key', async () => {
  const original = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ fields: [] }) };
  };
  try {
    await requestProfile('李青');
    assert.equal(request.url, 'http://127.0.0.1:18765/profile');
    assert.deepEqual(JSON.parse(request.options.body), { source: '李青' });
    assert.equal(Object.hasOwn(request.options.headers, 'Authorization'), false);
  } finally {
    globalThis.fetch = original;
  }
});

test('manifest has a stable, valid extension origin', async () => {
  const manifest = JSON.parse(await readFile(new URL('../manifest.json', import.meta.url)));
  assert.match(extensionOrigin(manifest.key), /^chrome-extension:\/\/[a-p]{32}$/);
});
