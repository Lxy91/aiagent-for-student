import test from 'node:test';
import assert from 'node:assert/strict';
import ExcelJS from 'exceljs';
import {
  createProfileWorkbook,
  readProfileWorkbook,
  SHEET_NAME,
  completeTable,
} from '../profile-workbook.js';

test('generated Excel includes editable extras and preserves phone/text formats', async () => {
  const bytes = await createProfileWorkbook(
    [
      { key: 'full_name', label: '姓名', value: '李青' },
      { key: 'phone', label: '手机号', value: '013900001234' },
    ],
    'resume.pdf',
  );
  const book = new ExcelJS.Workbook();
  await book.xlsx.load(bytes);
  const sheet = book.getWorksheet(SHEET_NAME);
  assert.deepEqual(sheet.getRow(1).values.slice(1), [
    '启用',
    '字段名称',
    '字段值',
    '字段标识',
    '备注',
  ]);
  let salary, phone;
  sheet.eachRow((row) => {
    if (row.getCell(4).value === 'expected_monthly_salary') salary = row;
    if (row.getCell(4).value === 'phone') phone = row;
  });
  assert.equal(salary.getCell(3).value, '');
  assert.equal(phone.getCell(3).value, '013900001234');
  assert.equal(phone.getCell(3).numFmt, '@');
  salary.getCell(3).value = '18000';
  const months = sheet.findRow(
    completeTable().findIndex((field) => field.key === 'salary_months') + 2,
  );
  months.getCell(3).value = 15;
  sheet.addRow(['是', '可接受出差频率', '每月一次', '', '用户补充']);
  const imported = await readProfileWorkbook(new Uint8Array(await book.xlsx.writeBuffer()));
  assert.equal(imported.find((field) => field.key === 'expected_monthly_salary').value, '18000');
  assert.equal(imported.find((field) => field.key === 'salary_months').value, '15');
  assert.equal(imported.find((field) => field.label === '可接受出差频率').value, '每月一次');
});

test('older multi-record tables receive editable location, department and duties for each record', () => {
  const fields = completeTable([
    { key: 'experience.work.2.description', label: '第二段实习', value: '负责数据回显' },
  ]);
  for (const part of ['location', 'department', 'responsibilities']) {
    const field = fields.find((field) => field.key === `experience.work.2.${part}`);
    assert.ok(field);
    assert.equal(field.value, '');
  }
  assert.equal(
    fields.find((field) => field.key === 'experience.work.2.description').value,
    '负责数据回显',
  );
});

test('Excel edits override parsed values; disabled and hidden fields stay out of usable rows', async () => {
  const book = new ExcelJS.Workbook();
  await book.xlsx.load(
    await createProfileWorkbook([{ key: 'full_name', label: '姓名', value: '原姓名' }]),
  );
  const sheet = book.getWorksheet(SHEET_NAME);
  sheet.getRow(2).getCell(3).value = '已修改姓名';
  sheet.addRow(['否', '自定义内部备注', '不要提供给企业', 'private_note', '']);
  sheet.addRow(['是', '隐藏行', '不使用此值', 'hidden_data', '']).hidden = true;
  const rows = await readProfileWorkbook(new Uint8Array(await book.xlsx.writeBuffer()));
  assert.equal(rows.find((field) => field.key === 'full_name').value, '已修改姓名');
  assert.equal(rows.find((field) => field.key === 'private_note').enabled, false);
  assert.equal(
    rows.some((field) => field.key === 'hidden_data'),
    false,
  );
});

test('cached formula results are used; unevaluated formulas fail clearly', async () => {
  const book = new ExcelJS.Workbook();
  await book.xlsx.load(
    await createProfileWorkbook([{ key: 'full_name', label: '姓名', value: '李青' }]),
  );
  const sheet = book.getWorksheet(SHEET_NAME);
  sheet.addRow([
    '是',
    '期望年薪',
    { formula: '18000*15', result: 270000 },
    'annual_custom',
    '元/年',
  ]);
  let bytes = new Uint8Array(await book.xlsx.writeBuffer());
  assert.equal(
    (await readProfileWorkbook(bytes)).find((field) => field.key === 'annual_custom').value,
    '270000',
  );
  sheet.getRow(sheet.rowCount).getCell(3).value = { formula: '18000*15' };
  bytes = new Uint8Array(await book.xlsx.writeBuffer());
  await assert.rejects(readProfileWorkbook(bytes), /公式未保存计算结果/);
});

test('formula-like user text is exported as text and duplicate keys are rejected', async () => {
  const value = '=HYPERLINK("https://example.invalid","text")';
  const bytes = await createProfileWorkbook([{ key: 'full_name', label: '姓名', value }]);
  const book = new ExcelJS.Workbook();
  await book.xlsx.load(bytes);
  const cell = book.getWorksheet(SHEET_NAME).getRow(2).getCell(3);
  assert.equal(typeof cell.value, 'string');
  assert.equal(cell.value, value);
  book.getWorksheet(SHEET_NAME).addRow(['是', '重复姓名', '李青', 'full_name', '']);
  await assert.rejects(readProfileWorkbook(new Uint8Array(await book.xlsx.writeBuffer())), /重复/);
});
