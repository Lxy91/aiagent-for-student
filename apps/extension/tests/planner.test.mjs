import test from 'node:test';
import assert from 'node:assert/strict';
import { generateFillPlan, validateBindings, validatePlanRequest } from '../model-planner.mjs';
const fields = [
  {
    key: 'expected_monthly_salary',
    label: '期望月薪',
    value: '18000',
    enabled: true,
    remark: '元/月',
  },
];
const controls = [
  {
    controlId: 'salary-control',
    label: '税前期望月收入',
    tag: 'INPUT',
    type: 'number',
    supported: true,
    hasValue: false,
  },
];

test('AI receives only current table data and control descriptions, not resume text', async () => {
  const original = globalThis.fetch;
  let payload;
  globalThis.fetch = async (url, options) => {
    payload = JSON.parse(options.body);
    return {
      ok: true,
      json: async () => ({
        choices: [
          {
            finish_reason: 'stop',
            message: {
              content: JSON.stringify({
                bindings: [{ controlId: 'salary-control', fieldKey: 'expected_monthly_salary' }],
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
        fields: [
          ...fields,
          { key: 'disabled', label: '内部备注', value: '不许发送', enabled: false },
        ],
        controls,
        source: '原始简历不得回退使用',
      },
      { modelBase: 'https://api.deepseek.com', model: 'test' },
      'private-test-key',
    );
    assert.equal(result.bindings.length, 1);
    const sent = JSON.parse(payload.messages[1].content);
    assert.deepEqual(sent.table, fields);
    assert.equal(JSON.stringify(sent).includes('原始简历'), false);
    assert.equal(JSON.stringify(sent).includes('不许发送'), false);
    assert.equal(payload.thinking.type, 'disabled');
  } finally {
    globalThis.fetch = original;
  }
});

test('unknown identifiers, invented values, duplicate mappings and fake options are rejected', () => {
  const result = validateBindings(
    {
      bindings: [
        { controlId: 'salary-control', fieldKey: 'expected_monthly_salary', value: '99999' },
        { controlId: 'not-on-page', fieldKey: 'expected_monthly_salary' },
        { controlId: 'salary-control', fieldKey: 'nonexistent' },
      ],
    },
    fields,
    controls,
  );
  assert.deepEqual(result.bindings, []);
  assert.equal(result.rejected_count, 3);
  const option = validateBindings(
    {
      bindings: [
        { controlId: 'select', fieldKey: 'expected_monthly_salary', optionValue: 'invented' },
      ],
    },
    fields,
    [
      {
        ...controls[0],
        controlId: 'select',
        tag: 'SELECT',
        options: [{ value: 'real', label: '实际选项' }],
      },
    ],
  );
  assert.deepEqual(option.bindings, []);
});

test('invalid table data and password controls are rejected before model access', () => {
  assert.throws(() => validatePlanRequest({ fields: [], controls }), /没有/);
  assert.throws(
    () => validatePlanRequest({ fields, controls: [{ ...controls[0], type: 'password' }] }),
    /不支持/,
  );
});
