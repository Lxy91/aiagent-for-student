import test from 'node:test';
import assert from 'node:assert/strict';
import { validateFields, experienceGroups } from '../resume-profile.js';
import { createProfileWorkbook, readProfileWorkbook } from '../profile-workbook.js';
import { validateBindings, generateFillPlan } from '../model-planner.mjs';

const records = [
  { key: 'experience.work.1.name', label: '实习1 · 名称', value: '星海公司' },
  { key: 'experience.work.1.start', label: '实习1 · 开始时间', value: '2025-07' },
  {
    key: 'experience.work.1.description',
    label: '实习1 · 描述',
    value: '参与报表编制，核对财务数据。完成资料归档。',
  },
  { key: 'experience.work.2.name', label: '实习2 · 名称', value: '远山事务所' },
];

test('work duties, department and workplace are grounded independent experience fields', () => {
  const source =
    '新中大科技股份有限公司，杭州，国际业务组，Java 后端开发实习生；负责接口联调和数据回显。';
  const facts = [
    ['role', 'Java 后端开发实习生'],
    ['department', '国际业务组'],
    ['location', '杭州'],
    ['responsibilities', '负责接口联调和数据回显。'],
  ].map(([part, value]) => ({ key: `experience.work.1.${part}`, value, evidence: [value] }));
  const result = validateFields({ fields: facts }, source);
  assert.equal(result.fields.length, 4);
  assert.equal(experienceGroups(result.fields)[0].fields.location, '杭州');
  assert.equal(
    validateFields(
      {
        fields: [
          {
            key: 'experience.work.1.location',
            value: '上海',
            evidence: ['新中大科技股份有限公司'],
          },
        ],
      },
      source,
    ).fields.length,
    0,
  );
});

test('custom select binding uses actual options; current city and job title cannot replace workplace and duties', () => {
  const table = [
    { key: 'experience.work.1.location', label: '工作地点', value: '杭州' },
    { key: 'current_city', label: '现居城市', value: '杭州' },
    { key: 'experience.work.1.role', label: '职位', value: 'Java开发实习生' },
  ];
  const control = {
    controlId: 'workplace',
    label: '工作地点',
    tag: 'INPUT',
    customSelect: true,
    options: [{ value: '杭州市', label: '杭州市' }],
  };
  assert.equal(
    validateBindings(
      { bindings: [{ controlId: 'workplace', fieldKey: table[0].key, optionValue: '杭州市' }] },
      table,
      [control],
    ).bindings.length,
    1,
  );
  assert.equal(
    validateBindings(
      { bindings: [{ controlId: 'workplace', fieldKey: table[0].key, optionValue: '不存在城市' }] },
      table,
      [control],
    ).bindings.length,
    0,
  );
  assert.equal(
    validateBindings(
      { bindings: [{ controlId: 'workplace', fieldKey: 'current_city', optionValue: '杭州市' }] },
      table,
      [control],
    ).bindings.length,
    0,
  );
  assert.equal(
    validateBindings({ bindings: [{ controlId: 'duties', fieldKey: table[2].key }] }, table, [
      { controlId: 'duties', label: '工作职责', tag: 'TEXTAREA' },
    ]).bindings.length,
    0,
  );
});

test('experience extraction keeps separate records with grounded names, dates and descriptions', () => {
  const source = '星海公司 2025.07-2025.09 参与报表编制，核对财务数据。完成资料归档。\n远山事务所';
  const raw = records.map((field) => ({
    ...field,
    evidence: [field.key.endsWith('.start') ? '2025.07' : field.value],
  }));
  raw.push({ key: 'experience.work.1.end', value: '2025-09-01', evidence: ['2025.09'] });
  raw.push({ key: 'experience.work.1.organization', value: '不存在公司', evidence: ['星海公司'] });
  raw.push({ key: 'experience.work.21.name', value: '星海公司', evidence: ['星海公司'] });
  const result = validateFields({ fields: raw }, source);
  assert.equal(result.fields.length, 4);
  assert.equal(result.omitted_count, 3);
  assert.equal(experienceGroups(result.fields).length, 2);
  assert.equal(experienceGroups(result.fields)[0].fields.start, '2025-07');
});

test('experience records survive Excel roundtrip and user edits without merging', async () => {
  const fields = await readProfileWorkbook(await createProfileWorkbook(records));
  const first = fields.find((field) => field.key === 'experience.work.1.name');
  first.value = '用户修改的公司';
  const again = await readProfileWorkbook(await createProfileWorkbook(fields));
  const groups = experienceGroups(again);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].fields.name, '用户修改的公司');
  assert.equal(groups[1].fields.name, '远山事务所');
});

test('limited descriptions accept only exact table excerpts, never invented facts or scalar edits', () => {
  const control = { controlId: 'details', tag: 'TEXTAREA', maxLength: 18 };
  const binding = { controlId: 'details', fieldKey: records[2].key, excerpts: ['完成资料归档。'] };
  assert.equal(validateBindings({ bindings: [binding] }, records, [control]).bindings.length, 1);
  for (const invalid of [
    { ...binding, excerpts: ['获得优秀实习生。'] },
    { ...binding, excerpts: [records[2].value] },
    { ...binding, fieldKey: records[0].key, excerpts: ['星海'] },
  ])
    assert.equal(validateBindings({ bindings: [invalid] }, records, [control]).bindings.length, 0);
});

test('optional nulls are absent values, while duplicated experience assignments are rejected', () => {
  const control = { controlId: 'name', tag: 'INPUT' };
  const binding = {
    controlId: 'name',
    fieldKey: records[0].key,
    excerpts: null,
    optionValue: null,
    value: null,
  };
  assert.deepEqual(validateBindings({ bindings: [binding] }, records, [control]).bindings, [
    { controlId: 'name', fieldKey: records[0].key },
  ]);
  assert.equal(
    validateBindings(
      { bindings: [binding, { controlId: 'second-name', fieldKey: records[0].key }] },
      records,
      [control, { controlId: 'second-name', tag: 'INPUT' }],
    ).bindings.length,
    0,
  );
});

test('AI receives section context, date placeholders and textarea limit for selected experience', async () => {
  const original = globalThis.fetch;
  let sent;
  globalThis.fetch = async (_url, init) => {
    sent = JSON.parse(JSON.parse(init.body).messages[1].content);
    return {
      ok: true,
      json: async () => ({
        choices: [
          {
            finish_reason: 'stop',
            message: {
              content: JSON.stringify({
                bindings: [
                  { controlId: 'details', fieldKey: records[2].key, excerpts: ['完成资料归档。'] },
                ],
              }),
            },
          },
        ],
      }),
    };
  };
  try {
    const result = await generateFillPlan(
      {
        fields: records.slice(0, 3),
        controls: [
          {
            controlId: 'details',
            tag: 'TEXTAREA',
            type: 'textarea',
            label: '详细描述',
            context: '实践活动（包含校内实践或校外实习经历）',
            maxLength: 18,
          },
        ],
      },
      { modelBase: 'https://fixture.invalid', model: 'test' },
      'test-key',
    );
    assert.equal(sent.page_controls[0].maxLength, 18);
    assert.match(sent.page_controls[0].context, /实践活动/);
    assert.equal(
      sent.table.some((field) => field.key.includes('work.2')),
      false,
    );
    assert.deepEqual(result.bindings[0].excerpts, ['完成资料归档。']);
  } finally {
    globalThis.fetch = original;
  }
});
