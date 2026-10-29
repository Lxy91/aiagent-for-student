import test from 'node:test';
import assert from 'node:assert/strict';
import { generateProfile, parseModelResult, ModelResponseError } from '../model-provider.mjs';

const result = { fields: [{ key: 'full_name', value: '李青', evidence: ['李青'] }] };
const config = { modelBase: 'https://api.deepseek.com', model: 'deepseek-v4-flash' };
function response(content, finish = 'stop') {
  return {
    ok: true,
    json: async () => ({ choices: [{ finish_reason: finish, message: { content } }] }),
  };
}

test('structured extraction explicitly disables DeepSeek thinking', async () => {
  const original = globalThis.fetch;
  let payload;
  globalThis.fetch = async (url, options) => {
    payload = JSON.parse(options.body);
    return response(JSON.stringify(result));
  };
  try {
    assert.equal((await generateProfile('李青', config, 'private-test-key')).fields.length, 1);
    assert.deepEqual(payload.thinking, { type: 'disabled' });
    assert.equal(payload.max_tokens, 6000);
  } finally {
    globalThis.fetch = original;
  }
});

test('truncation increases budget and retries without parsing partial JSON', async () => {
  const original = globalThis.fetch,
    payloads = [];
  globalThis.fetch = async (url, options) => {
    payloads.push(JSON.parse(options.body));
    return payloads.length === 1
      ? response('{"fields":[{"key":"full_name"', 'length')
      : response(JSON.stringify(result));
  };
  try {
    assert.equal(
      (await generateProfile('李青', config, 'private-test-key')).fields[0].value,
      '李青',
    );
    assert.deepEqual(
      payloads.map((item) => item.max_tokens),
      [6000, 12000],
    );
    assert.match(payloads[1].messages.at(-1).content, /MODEL_OUTPUT_TRUNCATED/);
  } finally {
    globalThis.fetch = original;
  }
});

test('persistent truncation has a specific code and safe diagnostic metadata', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => response('sensitive-incomplete-answer', 'length');
  try {
    await assert.rejects(generateProfile('李青', config, 'private-test-key'), (error) => {
      assert(error instanceof ModelResponseError);
      assert.equal(error.code, 'MODEL_OUTPUT_TRUNCATED');
      assert.equal(error.diagnostics.attempts, 2);
      assert.equal(error.diagnostics.finishReason, 'length');
      assert.equal(JSON.stringify(error.diagnostics).includes('sensitive'), false);
      return true;
    });
  } finally {
    globalThis.fetch = original;
  }
});

test('empty final content retries instead of treating reasoning as the answer', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () =>
    ++calls === 1 ? response(null) : response(JSON.stringify(result));
  try {
    assert.equal((await generateProfile('李青', config, 'private-test-key')).fields.length, 1);
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = original;
  }
});

test('fences, prose wrappers, content parts and equivalent dictionaries are accepted', () => {
  assert.deepEqual(
    parseModelResult(`结果如下：\n\`\`\`json\n${JSON.stringify(result)}\n\`\`\``),
    result,
  );
  const json = JSON.stringify(result);
  assert.deepEqual(
    parseModelResult([
      { type: 'text', text: json.slice(0, 25) },
      { type: 'text', text: json.slice(25) },
    ]),
    result,
  );
  assert.deepEqual(
    parseModelResult(
      JSON.stringify({ fields: { full_name: { value: '李青', evidence: ['李青'] } } }),
    ),
    result,
  );
  assert.throws(
    () => parseModelResult('{"fields":[{"key":"school"'),
    (error) => error.code === 'MODEL_JSON_INVALID',
  );
});

test('other compatible providers do not receive a vendor-only thinking parameter', async () => {
  const original = globalThis.fetch;
  let payload;
  globalThis.fetch = async (url, options) => {
    payload = JSON.parse(options.body);
    return response(JSON.stringify(result));
  };
  try {
    await generateProfile(
      '李青',
      { modelBase: 'https://model.example/v1', model: 'other' },
      'private-test-key',
    );
    assert.equal(Object.hasOwn(payload, 'thinking'), false);
  } finally {
    globalThis.fetch = original;
  }
});
