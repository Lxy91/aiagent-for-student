import { generateProfile } from '../model-provider.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import { validateFields, validateSource, readResume } from '../resume-profile.js';

test('copied identity and dates require original evidence', () => {
  const source = '姓名：李青\n学校：海川大学\n入学：2022.09\n邮箱：qing@example.com';
  const result = validateFields(
    {
      fields: [
        { key: 'full_name', value: '李青', evidence: ['姓名：李青'] },
        { key: 'education_start', value: '2022-09', evidence: ['入学：2022.09'] },
        { key: 'school', value: '虚构大学', evidence: ['学校：海川大学'] },
        { key: 'email', value: 'qing@example.com', evidence: ['邮箱：qing@example.com'] },
        { key: 'bank_account', value: '123456', evidence: ['姓名：李青'] },
      ],
    },
    source,
  );
  assert.deepEqual(
    result.fields.map((field) => field.key),
    ['full_name', 'education_start', 'email'],
  );
  assert.equal(result.omitted_count, 2);
});

test('duplicate keys and nonexistent evidence are omitted independently', () => {
  const result = validateFields(
    {
      fields: [
        { key: 'school', value: '海川大学', evidence: ['海川大学'] },
        { key: 'school', value: '海川大学', evidence: ['海川大学'] },
        { key: 'skills', value: '财务分析', evidence: ['不存在的资料'] },
      ],
    },
    '海川大学',
  );
  assert.equal(result.fields.length, 1);
  assert.equal(result.omitted_count, 2);
});

test('text files are read locally without any network call', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = () => {
    throw new Error('Unexpected network');
  };
  try {
    assert.equal(await readResume(new File(['李青\n海川大学'], 'resume.txt')), '李青\n海川大学');
    await assert.rejects(readResume(new File([''], 'empty.txt')), /未读取到文字/);
    await assert.rejects(readResume(new File(['text'], 'resume.exe')), /支持 PDF/);
  } finally {
    globalThis.fetch = original;
  }
});

test('source bounds are explicit rather than silently truncating', () => {
  assert.throws(() => validateSource('a'.repeat(30001)), /30000/);
  assert.throws(() => validateSource('  '), /未读取到文字/);
});

test('invalid date strings cannot pass merely by sharing digits with evidence', () => {
  const result = validateFields(
    {
      fields: [
        { key: 'graduation_date', value: 'wrong-2027-06', evidence: ['2027-06'] },
        { key: 'education_start', value: '2022-99', evidence: ['2022-99'] },
      ],
    },
    '2027-06 2022-99',
  );
  assert.equal(result.fields.length, 0);
  assert.equal(result.omitted_count, 2);
});

test('model extraction only posts to the configured provider and validates fields', async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      json: async () => ({
        choices: [
          {
            message: {
              content: JSON.stringify({
                fields: [{ key: 'full_name', value: '李青', evidence: ['李青'] }],
              }),
            },
          },
        ],
      }),
    };
  };
  try {
    const result = await generateProfile(
      '李青',
      { modelBase: 'https://model.example/v1', model: 'test-model' },
      'test-key',
    );
    assert.equal(result.fields[0].value, '李青');
    assert.equal(requests[0].url, 'https://model.example/v1/chat/completions');
    assert.equal(requests[0].options.redirect, 'error');
    assert.equal(JSON.parse(requests[0].options.body).model, 'test-model');
    await assert.rejects(
      generateProfile('李青', { modelBase: 'https://model.example', model: 'test' }, ''),
      /MODEL_API_KEY/,
    );
  } finally {
    globalThis.fetch = original;
  }
});
