import ExcelJS from 'exceljs';
import { createModelService, extensionOrigin, SERVICE_PORT } from '../service.mjs';
import { chromium } from 'playwright-core';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { zipSync, strToU8 } from 'fflate';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temporary = await mkdtemp(path.join(tmpdir(), 'qicheng-plugin-browser-'));
const mime = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.mjs': 'application/javascript',
  '.css': 'text/css',
};
const server = createServer(async (request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
  const file = path.resolve(root, `.${pathname}`);
  if (!file.startsWith(root + path.sep)) {
    response.writeHead(403).end();
    return;
  }
  try {
    response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
    response.end(await readFile(file));
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let context;
let modelService;
let modelRequests = [];
let planRequests = [];
let checks = 0;
function pass(name) {
  checks += 1;
  console.log(`PASS ${name}`);
}

function pdfBytes(text) {
  const stream = `BT /F1 12 Tf 50 750 Td (${text}) Tj ET`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`)
    .join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(pdf);
}

try {
  const manifest = JSON.parse(await readFile(path.join(root, 'dist/manifest.json'), 'utf8'));
  modelService = createModelService(
    {
      modelBase: 'https://fixture.invalid',
      model: 'fixture-model',
      apiKey: 'server-only-test-key',
    },
    extensionOrigin(manifest.key),
    async (source) => {
      modelRequests.push(source);
      if (source.includes('旧表经历验证'))
        return {
          fields: [
            { key: 'experience.work.1.name', label: '工作与实习1 · 名称', value: '海川数据公司' },
            { key: 'experience.work.1.start', label: '工作与实习1 · 开始时间', value: '2025-03' },
            {
              key: 'experience.work.1.description',
              label: '工作与实习1 · 详细描述',
              value: '负责数据看板开发',
            },
          ],
          omitted_count: 0,
        };
      return {
        fields: [
          { key: 'full_name', label: '姓名', value: '李青' },
          { key: 'school', label: '学校', value: '海川大学' },
        ],
        omitted_count: 0,
      };
    },
    async (payload) => {
      planRequests.push(payload);
      const bindings = payload.controls.flatMap((control) => {
        const key = /月收入/.test(control.label)
          ? 'expected_monthly_salary'
          : /发放/.test(control.label)
            ? 'salary_months'
            : /院校/.test(control.label)
              ? 'school'
              : '';
        return key ? [{ controlId: control.controlId, fieldKey: key }] : [];
      });
      return { bindings, rejected_count: 0 };
    },
  );
  await new Promise((resolve, reject) => {
    modelService.once('error', reject);
    modelService.listen(SERVICE_PORT, '127.0.0.1', resolve);
  });
  context = await chromium.launchPersistentContext(path.join(temporary, 'profile'), {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || chromium.executablePath(),
    headless: true,
    args: [
      `--disable-extensions-except=${path.join(root, 'dist')}`,
      `--load-extension=${path.join(root, 'dist')}`,
    ],
  });
  const page = await context.newPage();
  await page.goto(`${origin}/tests/form-fixture.html`);
  const result = await page.evaluate(() => {
    const fields = [
      { key: 'full_name', value: '李青' },
      { key: 'phone', value: '13900001234' },
      { key: 'email', value: 'new@example.com' },
      { key: 'school', value: '海川大学' },
      { key: 'major', value: '会计学' },
      { key: 'degree', value: '学士' },
      { key: 'graduation_date', value: '2027-06' },
      { key: 'self_introduction', value: '财务分析与数据管理' },
    ];
    let events = 0;
    document.addEventListener('input', () => (events += 1));
    const plan = QichengAutofill.scan(fields);
    const before = document.querySelector('#name').value;
    const applied = QichengAutofill.fill(
      plan.scanId,
      plan.items.filter((item) => item.status === 'ready').map((item) => item.id),
    );
    return {
      before,
      plan,
      applied,
      events,
      values: Object.fromEntries(
        [
          'name',
          'phone',
          'email',
          'school',
          'major',
          'degree',
          'graduation',
          'intro',
          'secret',
          'emergency',
          'code',
        ].map((id) => [id, document.getElementById(id).value]),
      ),
      submitted: Boolean(window.submitted),
    };
  });
  assert.equal(result.before, '');
  assert.equal(result.applied.filter((item) => item.status === 'filled').length, 7);
  assert.equal(result.values.name, '李青');
  assert.equal(result.values.phone, '13900001234');
  assert.equal(result.values.email, 'keep@example.com');
  assert.equal(result.values.degree, 'bachelor');
  assert.equal(result.values.graduation, '2027-06');
  assert.equal(result.values.secret + result.values.emergency + result.values.code, '');
  assert.equal(result.events, 7);
  assert.equal(result.submitted, false);
  pass('native inputs, select, date, input events, preserving existing fields, no submission');

  const changed = await page.evaluate(() => {
    document.getElementById('name').value = '';
    const plan = QichengAutofill.scan([{ key: 'full_name', value: '李青' }]);
    document.getElementById('name').value = '用户新输入';
    return QichengAutofill.fill(
      plan.scanId,
      plan.items.map((item) => item.id),
    );
  });
  assert.equal(changed[0].status, 'skipped');
  pass('user edits made after scan are preserved');
  const stale = await page.evaluate(() => {
    const old = QichengAutofill.scan([{ key: 'full_name', value: '李青' }]);
    QichengAutofill.scan([]);
    try {
      QichengAutofill.fill(old.scanId, []);
      return false;
    } catch {
      return true;
    }
  });
  assert.equal(stale, true);
  pass('stale scans rejected');

  await page.setContent(
    '<label>学校<input></label><label>学校<input></label><div role="combobox" aria-label="学历">请选择</div><label>毕业时间<input type="date"></label>',
  );
  const ambiguous = await page.evaluate(() =>
    QichengAutofill.scan([
      { key: 'school', value: '海川大学' },
      { key: 'degree', value: '本科' },
      { key: 'graduation_date', value: '2027-06' },
    ]),
  );
  assert.equal(ambiguous.items.filter((item) => item.status === 'ambiguous').length, 2);
  assert.equal(ambiguous.items.filter((item) => item.status === 'unsupported').length, 2);
  pass('repeated records, custom dropdowns and incomplete dates skipped');

  await page.setContent(
    '<div id="shadow"></div><iframe id="frame" srcdoc="<label>学校<input></label>"></iframe>',
  );
  await page.locator('#frame').contentFrame().locator('input').waitFor();
  const nested = await page.evaluate(() => {
    document.getElementById('shadow').attachShadow({ mode: 'open' }).innerHTML =
      '<label>手机号<input type="tel"></label>';
    const plan = QichengAutofill.scan([
      { key: 'phone', value: '13900001234' },
      { key: 'school', value: '海川大学' },
    ]);
    QichengAutofill.fill(
      plan.scanId,
      plan.items.map((item) => item.id),
    );
    return [
      document.getElementById('shadow').shadowRoot.querySelector('input').value,
      document.getElementById('frame').contentDocument.querySelector('input').value,
    ];
  });
  assert.deepEqual(nested, ['13900001234', '海川大学']);
  pass('open Shadow DOM and same-origin iframe');

  // Exercise bundled parsers, including the local worker, in a real browser.
  await page.goto(`${origin}/tests/form-fixture.html`);
  const pdfPath = path.join(temporary, 'resume.pdf');
  const docxPath = path.join(temporary, 'resume.docx');
  await writeFile(pdfPath, pdfBytes('Alex Chen Financial Analyst'));
  await writeFile(
    docxPath,
    zipSync({
      '[Content_Types].xml': strToU8(
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
      ),
      '_rels/.rels': strToU8(
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
      ),
      'word/document.xml': strToU8(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>李青 海川大学 会计学</w:t></w:r></w:p></w:body></w:document>',
      ),
    }),
  );
  const parsed = await page.evaluate(
    async ({ pdf, docx }) => {
      const module = await import('/dist/resume-profile.js');
      const one = await module.readResume(new File([new Uint8Array(pdf)], 'resume.pdf'));
      const two = await module.readResume(new File([new Uint8Array(docx)], 'resume.docx'));
      return [one, two];
    },
    { pdf: [...(await readFile(pdfPath))], docx: [...(await readFile(docxPath))] },
  );
  assert.match(parsed[0], /Alex Chen Financial Analyst/);
  assert.match(parsed[1], /李青 海川大学 会计学/);
  pass('bundled PDF worker and DOCX local extraction');

  const manager = await context.newPage();
  await manager.goto('chrome://extensions');
  const item = manager.locator('extensions-item').filter({ hasText: '启程' });
  await item.waitFor();
  const extensionId = await item.getAttribute('id');
  assert.match(extensionId, /^[a-p]{32}$/);
  assert.equal(`chrome-extension://${extensionId}`, extensionOrigin(manifest.key));
  const popup = await context.newPage();
  const popupErrors = [];
  popup.on('pageerror', (error) => popupErrors.push(error.message));
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  await popup.getByRole('status').filter({ hasText: '插件可独立使用' }).waitFor();
  await popup.getByText('查看和编辑表格资料', { exact: true }).click();
  await popup.evaluate(() =>
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === 'session' && changes.profile) window.profileSnapshot = changes.profile.newValue;
    }),
  );
  await popup.getByRole('textbox', { name: '姓名', exact: true }).fill('李青');
  await popup.waitForFunction(() =>
    window.profileSnapshot?.fields?.some(
      (field) => field.key === 'full_name' && field.value === '李青',
    ),
  );
  await popup.reload();
  await popup.getByText('查看和编辑表格资料', { exact: true }).click();
  await popup.waitForFunction(
    () => document.querySelector('[data-key="full_name"] [data-value]')?.value === '李青',
  );
  assert.equal(
    await popup.getByRole('textbox', { name: '姓名', exact: true }).inputValue(),
    '李青',
  );
  pass('real unpacked extension loaded; manual profile works without the host or a model');
  await popup.locator('#resume-file').setInputFiles(pdfPath);
  await popup.waitForFunction(() =>
    document.querySelector('#resume-text').value.includes('Alex Chen'),
  );
  await popup.locator('#resume-file').setInputFiles(docxPath);
  await popup.waitForFunction(() =>
    document.querySelector('#resume-text').value.includes('海川大学'),
  );
  assert.equal(await popup.locator('#model-key').count(), 0);
  await popup.getByRole('button', { name: '检查连接', exact: true }).click();
  await popup.getByRole('status').filter({ hasText: '本地 .env 模型配置已就绪' }).waitFor();
  assert.equal(modelRequests.length, 0);
  const excelDownload = popup.waitForEvent('download');
  await popup.getByRole('button', { name: '解析简历并导出 Excel', exact: true }).click();
  await popup.getByRole('status').filter({ hasText: '已生成 2 项资料' }).waitFor();
  assert.equal(modelRequests.length, 1);
  assert.match(modelRequests[0], /海川大学/);
  assert.equal((await popup.locator('body').innerText()).includes('server-only-test-key'), false);
  assert.equal(
    await popup.evaluate(async () => (await chrome.storage.session.get('modelKey')).modelKey),
    undefined,
  );
  pass('browser-to-local-service bridge without browser-side model credentials');
  const savedExcel = path.join(temporary, 'editable-profile.xlsx');
  await (await excelDownload).saveAs(savedExcel);
  const edited = new ExcelJS.Workbook();
  await edited.xlsx.readFile(savedExcel);
  const sheet = edited.getWorksheet('填写资料');
  const practiceDescription =
    '参与数据看板与动态表单开发，负责字段映射、接口联调和数据回显。' +
    '维护组件并修复数据校验问题。'.repeat(18);
  const practiceValues = {
    'experience.work.1.name': '海川数据公司',
    'experience.work.1.start': '2025-03-01',
    'experience.work.1.end': '2025-07-01',
    'experience.work.1.description': practiceDescription,
  };
  sheet.eachRow((row) => {
    const key = row.getCell(4).value;
    if (key === 'expected_monthly_salary') row.getCell(3).value = '18000';
    if (key === 'salary_months') row.getCell(3).value = '15';
    if (key === 'school') row.getCell(3).value = '用户修改的学校';
    if (practiceValues[key]) row.getCell(3).value = practiceValues[key];
  });
  sheet.addRow(['是', '实习2 · 名称', '另一家公司', 'experience.work.2.name', '']);
  sheet.addRow([
    '是',
    '实习2 · 详细描述',
    '这条经历不能混入第一条',
    'experience.work.2.description',
    '',
  ]);
  await edited.xlsx.writeFile(savedExcel);
  await popup.locator('#workbook-file').setInputFiles(savedExcel);
  await popup.getByRole('status').filter({ hasText: 'Excel 已导入' }).waitFor();
  assert.equal(
    await popup.getByRole('textbox', { name: '期望月薪', exact: true }).inputValue(),
    '18000',
  );
  assert.equal(
    await popup.getByRole('textbox', { name: '学校', exact: true }).inputValue(),
    '用户修改的学校',
  );
  pass('generated Excel download and user-edited salary/months/school re-import');

  await page.setContent(
    '<label>税前预期月收入(元)<input id="salary" type="number"></label><label>一年发放几个月<input id="months" type="number"></label><label>毕业院校<input id="college"></label>',
  );
  const snapshot = await page.evaluate(() => QichengAutofill.inspect());
  const table = await popup.evaluate(async () =>
    (await chrome.storage.session.get('profile')).profile.fields.filter(
      (field) => field.enabled && field.value,
    ),
  );
  const matched = await popup.evaluate(
    async ({ fields, controls }) => {
      const response = await fetch('http://127.0.0.1:18765/plan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Qicheng-Plugin': 'application-assistant',
        },
        body: JSON.stringify({ fields, controls, overwrite: false }),
      });
      return { status: response.status, data: await response.json() };
    },
    { fields: table, controls: snapshot.items },
  );
  assert.equal(matched.status, 200);
  assert.equal(planRequests.length, 1);
  assert.equal(
    planRequests[0].fields.find((field) => field.key === 'expected_monthly_salary').value,
    '18000',
  );
  assert.equal(planRequests[0].source, undefined);
  const filledFromTable = await page.evaluate(
    ({ scan, bindings, fields }) => {
      const prepared = QichengAutofill.prepare(scan, bindings, fields, false);
      QichengAutofill.fill(
        scan,
        prepared.items.filter((item) => item.status === 'ready').map((item) => item.id),
      );
      return ['salary', 'months', 'college'].map((id) => document.getElementById(id).value);
    },
    { scan: snapshot.scanId, bindings: matched.data.bindings, fields: table },
  );
  assert.deepEqual(filledFromTable, ['18000', '15', '用户修改的学校']);
  pass('AI plan and actual page writes use edited table values, not resume source');

  await page.setContent('<label>期望月薪(K)<input id="salary-k" type="number"></label>');
  const salaryConverted = await page.evaluate(() => {
    const snapshot = QichengAutofill.inspect();
    const prepared = QichengAutofill.prepare(
      snapshot.scanId,
      [{ controlId: snapshot.items[0].controlId, fieldKey: 'expected_monthly_salary' }],
      [{ key: 'expected_monthly_salary', label: '期望月薪', value: '18000', remark: '元/月' }],
    );
    QichengAutofill.fill(
      snapshot.scanId,
      prepared.items.map((item) => item.id),
    );
    return document.getElementById('salary-k').value;
  });
  assert.equal(salaryConverted, '18');
  pass('salary conversion from explicit yuan/month table units to K page units');
  await popup.locator('#experience-choice').waitFor({ state: 'visible' });
  assert.equal(await popup.locator('#experience-record').inputValue(), 'experience.work.1');
  assert.match(await popup.locator('#experience-record').innerText(), /海川数据公司/);
  assert.match(await popup.locator('#experience-record').innerText(), /另一家公司/);
  await popup.locator('#experience-record').selectOption('experience.work.2');
  assert.equal(await popup.locator('#plan-section').isVisible(), false);
  await popup.locator('#experience-record').selectOption('experience.work.1');
  pass('Excel experience records appear separately and selection invalidates stale plans');

  await page.setContent(`<section><h2>实践活动（包含校内实践或校外实习经历）</h2>
    <label>时间：<input id="practice-start" placeholder="请选择开始时间"></label>
    <input id="practice-end" placeholder="请选择结束或预计结束时间">
    <label>实践活动/公司名称：<input id="practice-name"></label>
    <label>详细描述：<textarea id="practice-description" maxlength="200"></textarea></label>
    <button id="save-practice" onclick="window.saved=true">保存</button></section>`);
  const practiceResult = await page.evaluate(
    ({ table, excerpt }) => {
      const selected = table.filter(
        (field) => field.key.startsWith('experience.work.1.') && field.value,
      );
      const snapshot = QichengAutofill.inspect();
      const bindings = snapshot.items.map((control) => ({
        controlId: control.controlId,
        fieldKey: `experience.work.1.${/开始/.test(control.label) ? 'start' : /结束/.test(control.label) ? 'end' : /名称/.test(control.label) ? 'name' : 'description'}`,
        ...(/详细描述/.test(control.label) ? { excerpts: [excerpt] } : {}),
      }));
      const prepared = QichengAutofill.prepare(snapshot.scanId, bindings, selected);
      QichengAutofill.fill(
        snapshot.scanId,
        prepared.items.filter((item) => item.status === 'ready').map((item) => item.id),
      );
      return {
        snapshot,
        prepared,
        values: ['practice-start', 'practice-end', 'practice-name', 'practice-description'].map(
          (id) => document.getElementById(id).value,
        ),
        saved: Boolean(window.saved),
      };
    },
    { table, excerpt: practiceDescription.split('。')[0] + '。' },
  );
  assert.deepEqual(practiceResult.values, [
    '2025-03-01',
    '2025-07-01',
    '海川数据公司',
    practiceDescription.split('。')[0] + '。',
  ]);
  assert.equal(practiceResult.saved, false);
  assert.equal(
    practiceResult.snapshot.items.find((item) => item.tag === 'TEXTAREA').maxLength,
    200,
  );
  assert.match(
    practiceResult.snapshot.items.find((item) => item.tag === 'TEXTAREA').context,
    /实践活动/,
  );
  assert.match(
    practiceResult.prepared.items.find((item) => item.key.endsWith('.description')).reason,
    /摘选原文/,
  );
  pass(
    'practice name, start/end and 200-character description fill from one Excel record without saving',
  );

  const forgedExcerpt = await page.evaluate(() => {
    const snapshot = QichengAutofill.inspect();
    const control = snapshot.items.find((item) => item.tag === 'TEXTAREA');
    return QichengAutofill.prepare(
      snapshot.scanId,
      [
        {
          controlId: control.controlId,
          fieldKey: 'experience.work.1.description',
          excerpts: ['虚构的实习业绩'],
        },
      ],
      [{ key: 'experience.work.1.description', value: '只有原文描述', label: '实习描述' }],
      true,
    ).items.filter((item) => item.status === 'ready').length;
  });
  assert.equal(forgedExcerpt, 0);
  pass('browser independently rejects fabricated experience descriptions');
  await popup.evaluate(() =>
    chrome.storage.session.set({
      profile: {
        filename: '旧版资料.xlsx',
        fields: [
          { key: 'full_name', label: '姓名', value: '李青' },
          { key: 'expected_monthly_salary', label: '期望月薪', value: '18000' },
          {
            key: 'work_experience',
            label: '工作与实习经历',
            value: '旧表经历验证：2025.03 海川数据公司，负责数据看板开发',
          },
        ],
      },
      source: { filename: '旧版资料.xlsx', text: '不得使用这份旧简历原文' },
    }),
  );
  await popup.reload();
  await popup.getByRole('status').filter({ hasText: '已恢复表格资料' }).waitFor();
  const splitDownload = popup.waitForEvent('download');
  await popup.locator('#split-experiences').click();
  await popup.getByRole('status').filter({ hasText: '已拆分 1 条经历' }).waitFor();
  assert.match((await splitDownload).suggestedFilename(), /投递资料\.xlsx$/);
  assert.equal(modelRequests.at(-1).includes('不得使用这份旧简历原文'), false);
  const afterSplit = await popup.evaluate(
    async () => (await chrome.storage.session.get('profile')).profile.fields,
  );
  assert.equal(afterSplit.find((field) => field.key === 'expected_monthly_salary').value, '18000');
  assert.equal(
    afterSplit.find((field) => field.key === 'experience.work.1.name').value,
    '海川数据公司',
  );
  pass(
    'legacy Excel experience splitting preserves edited salary and exports without old resume fallback',
  );
  assert.match(await popup.locator('#operation-feedback').innerText(), /已拆分 1 条经历/);
  pass('operation result remains visible in bottom action area');

  async function workForm(style = 'element') {
    await page.setContent(`<section><h2>工作经历</h2>
      <div class="form-item"><label>工作地点</label>${
        style === 'element' || style === 'unlinked'
          ? '<div class="el-select"><input id="workplace" readonly aria-controls="work-cities" placeholder="请选择"></div>'
          : style === 'ant'
            ? '<div class="ant-select"><div class="ant-select-selector"><input id="workplace" type="search" role="combobox" aria-controls="work-cities"><span class="ant-select-selection-item"></span></div></div>'
            : '<div id="workplace" role="combobox" aria-label="工作地点" aria-controls="work-cities" tabindex="0">请选择</div>'
      }</div>
      <label>部门<input id="work-department"></label>
      <label>工作职责<textarea id="work-duties" maxlength="2000"></textarea></label>
      <button onclick="window.workSaved=true">保存</button></section>
      <ul id="work-cities" role="listbox" hidden><li role="option">杭州市</li><li role="option">上海市</li><li role="option" aria-disabled="true">深圳市</li></ul>`);
    await page.evaluate((style) => {
      const trigger = document.getElementById('workplace');
      if (style === 'unlinked') trigger.removeAttribute('aria-controls');
      const panel = document.getElementById('work-cities');
      trigger.addEventListener(style === 'ant' ? 'mousedown' : 'click', () =>
        setTimeout(() => {
          panel.hidden = false;
        }, 70),
      );
      trigger.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') panel.hidden = true;
      });
      panel.addEventListener('click', (event) => {
        const option = event.target.closest('[role="option"]');
        if (!option || option.getAttribute('aria-disabled') === 'true') return;
        const value = option.textContent.trim();
        window.workModel = { city: value };
        if (style === 'ant')
          document.querySelector('.ant-select-selection-item').textContent = value;
        else if (trigger.tagName === 'INPUT') trigger.value = value;
        else {
          trigger.textContent = value;
          trigger.setAttribute('aria-valuetext', value);
        }
        panel.hidden = true;
      });
    }, style);
  }
  const workTable = [
    { key: 'experience.work.1.location', label: '工作地点', value: '杭州' },
    { key: 'experience.work.1.department', label: '部门', value: '国际业务组' },
    {
      key: 'experience.work.1.responsibilities',
      label: '工作职责',
      value: '参与人员管理模块定制开发，负责接口联调和数据回显。',
    },
  ];
  for (const style of ['element', 'aria', 'ant', 'unlinked']) {
    await workForm(style);
    const workFilled = await page.evaluate(
      async ({ fields }) => {
        const snapshot = await QichengAutofill.inspectAsync();
        const bindings = snapshot.items.map((control) => ({
          controlId: control.controlId,
          fieldKey: `experience.work.1.${/工作地点/.test(control.label) ? 'location' : /部门/.test(control.label) ? 'department' : 'responsibilities'}`,
          ...(control.customSelect ? { optionValue: '杭州市' } : {}),
        }));
        const prepared = QichengAutofill.prepare(snapshot.scanId, bindings, fields);
        const results = await QichengAutofill.fillAsync(
          snapshot.scanId,
          prepared.items.filter((item) => item.status === 'ready').map((item) => item.id),
        );
        return {
          snapshot,
          results,
          city: window.workModel?.city,
          department: document.getElementById('work-department').value,
          duties: document.getElementById('work-duties').value,
          saved: Boolean(window.workSaved),
          feedback: document.querySelector('[data-qicheng-feedback]')?.shadowRoot.textContent,
        };
      },
      { fields: workTable },
    );
    assert.equal(workFilled.city, '杭州市');
    assert.equal(workFilled.department, '国际业务组');
    assert.equal(workFilled.duties, workTable[2].value);
    assert.equal(workFilled.results.filter((item) => item.status === 'filled').length, 3);
    assert.equal(workFilled.saved, false);
    assert.match(workFilled.feedback, /已填 3 项/);
    assert.equal(
      workFilled.snapshot.items
        .find((item) => item.customSelect)
        .options.some((option) => option.label === '深圳市'),
      false,
    );
    pass(`${style} custom workplace dropdown, department, duties and page completion feedback`);
  }
  await workForm();
  const missingLocation = await page.evaluate(async () => {
    const snapshot = await QichengAutofill.inspectAsync();
    const prepared = QichengAutofill.prepare(
      snapshot.scanId,
      [],
      [{ key: 'current_city', label: '现居城市', value: '杭州' }],
    );
    return prepared.items.find((item) => /工作地点/.test(item.label)).reason;
  });
  assert.match(missingLocation, /所选经历未填写工作地点/);
  pass('missing workplace shows actionable reason instead of borrowing current city');
  const staleOption = await page.evaluate(async (fields) => {
    const snapshot = await QichengAutofill.inspectAsync();
    const location = snapshot.items.find((item) => item.customSelect);
    const prepared = QichengAutofill.prepare(
      snapshot.scanId,
      [{ controlId: location.controlId, fieldKey: fields[0].key, optionValue: '杭州市' }],
      fields,
    );
    document.querySelector('#work-cities [role="option"]').textContent = '北京市';
    return QichengAutofill.fillAsync(
      snapshot.scanId,
      prepared.items.filter((item) => item.status === 'ready').map((item) => item.id),
    );
  }, workTable);
  assert.equal(staleOption[0].status, 'skipped');
  pass('changed dropdown options are skipped instead of clicking a different city');
  await workForm();
  const unrelated = await page.evaluate(async (fields) => {
    const old = document.getElementById('workplace');
    const trigger = old.cloneNode(true);
    trigger.removeAttribute('aria-controls');
    old.replaceWith(trigger);
    const list = document.createElement('ul');
    list.setAttribute('role', 'listbox');
    list.innerHTML = '<li role="option">杭州市</li>';
    list.addEventListener('click', () => {
      window.unrelatedClicked = true;
    });
    document.body.append(list);
    const snapshot = await QichengAutofill.inspectAsync();
    const control = snapshot.items.find((item) => item.customSelect);
    const plan = QichengAutofill.prepare(
      snapshot.scanId,
      [{ controlId: control.controlId, fieldKey: fields[0].key, optionValue: '杭州市' }],
      fields,
    );
    await QichengAutofill.fillAsync(
      snapshot.scanId,
      plan.items.filter((item) => item.status === 'ready').map((item) => item.id),
    );
    return {
      supported: control.supported,
      clicked: Boolean(window.unrelatedClicked),
      value: trigger.value,
    };
  }, workTable);
  assert.equal(unrelated.supported, false);
  assert.equal(unrelated.clicked, false);
  assert.equal(unrelated.value, '');
  pass('unrelated open dropdown is never treated as workplace options');

  await page.setContent(`<div class="form-item"><label>工作地点</label><div id="phoenix-workplace" class="phoenix-select">请选择</div></div>
    <div class="area-selector-container" hidden><div class="area-search-input"><input placeholder="搜索"></div>
    <span class="select-data-num-limit">/1</span><span class="select-data-num-text">0</span><div class="area-data-container"></div>
    <div class="area-footer-button"><button>取消</button><button>确定</button></div></div>
    <button id="save-full-resume" onclick="window.savedResume=true">保存简历</button>`);
  await page.evaluate(() => {
    const trigger = document.getElementById('phoenix-workplace');
    const area = document.querySelector('.area-selector-container');
    trigger.addEventListener('click', () => {
      area.hidden = false;
    });
    area.querySelector('input').addEventListener('input', (event) =>
      setTimeout(() => {
        area.querySelector('.area-data-container').innerHTML =
          '<div class="search-result">搜索结果</div><div class="area-item-container"><div class="area-item-name"><span class="icon-container visible"><svg class="area-icon-RadioUnchecked"></svg></span><span class="area-text-label">杭州市</span></div><div class="area-item-path">中国/浙江省/杭州市</div></div>';
        area.querySelector('svg').addEventListener('click', () => {
          area.querySelector('.select-data-num-text').textContent = '1';
          window.pendingPhoenixCity = '杭州市';
        });
      }, 220),
    );
    area.querySelectorAll('button')[0].addEventListener('click', () => {
      area.hidden = true;
      window.pendingPhoenixCity = undefined;
    });
    area.querySelectorAll('button')[1].addEventListener('click', () => {
      if (window.pendingPhoenixCity) {
        trigger.textContent = window.pendingPhoenixCity;
        window.committedPhoenixCity = window.pendingPhoenixCity;
        area.hidden = true;
      }
    });
  });
  const phoenix = await page.evaluate(async (fields) => {
    const snapshot = await QichengAutofill.inspectAsync(fields);
    const control = snapshot.items.find((item) => item.customSelect);
    const before = document.getElementById('phoenix-workplace').textContent;
    const prepared = QichengAutofill.prepare(
      snapshot.scanId,
      [
        {
          controlId: control.controlId,
          fieldKey: fields[0].key,
          optionValue: control.options[0]?.value,
        },
      ],
      fields,
    );
    const results = await QichengAutofill.fillAsync(
      snapshot.scanId,
      prepared.items.filter((item) => item.status === 'ready').map((item) => item.id),
    );
    return {
      before,
      results,
      city: window.committedPhoenixCity,
      saved: Boolean(window.savedResume),
      option: control.options[0]?.value,
    };
  }, workTable);
  assert.equal(phoenix.before, '请选择');
  assert.equal(phoenix.city, '杭州市');
  assert.equal(phoenix.results[0].status, 'filled');
  assert.equal(phoenix.saved, false);
  assert.match(phoenix.option, /中国\/浙江省\/杭州市/);
  pass('Beisen Phoenix area search, radio and scoped confirmation fill city without saving resume');

  await popup.route('http://localhost:8000/api/v1/resume', (route) =>
    route.fulfill({
      status: 200,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,OPTIONS',
        'Access-Control-Allow-Headers': '*',
      },
      contentType: 'application/json',
      body: JSON.stringify({ filename: '启程导入简历.txt', content: '李青 海川大学 会计学' }),
    }),
  );
  await popup.evaluate(() =>
    chrome.storage.session.set({
      auth: {
        token: 'local-test-token',
        user: { display_name: '导入验证', email: 'test@example.com' },
        apiBase: 'http://localhost:8000/api/v1',
      },
    }),
  );
  await popup.reload();
  await popup.waitForFunction(() => document.getElementById('account').hidden === false);
  await popup.locator('#settings').evaluate((element) => {
    element.open = true;
  });
  const fromHost = popup.waitForEvent('download');
  await popup.getByRole('button', { name: '从启程简历一键生成 Excel', exact: true }).click();
  assert.match((await fromHost).suggestedFilename(), /投递资料\.xlsx$/);
  assert.equal(modelRequests.at(-1), '李青 海川大学 会计学');
  pass('optional host resume import directly generates the same editable Excel table');

  assert.deepEqual(popupErrors, []);
  await popup.getByRole('button', { name: '清除资料', exact: true }).click();
  await popup.waitForFunction(() => document.querySelector('#resume-text').value === '');
  pass('extension CSP, original file import, clear-data workflow');

  if (process.env.TEST_APP_URL) {
    const market = await context.newPage();
    await market.route('**/api/v1/**', (route) =>
      route.fulfill({
        status: 200,
        headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*' },
        contentType: 'application/json',
        body: route.request().url().endsWith('/resume') ? 'null' : '[]',
      }),
    );
    await market.addInitScript(() =>
      localStorage.setItem(
        'workplace-agent-session',
        JSON.stringify({
          accessToken: 'local-ui-test',
          user: { id: 'local-test', displayName: '插件入口验证', email: 'local-test@example.com' },
        }),
      ),
    );
    await market.goto(`${process.env.TEST_APP_URL}/memory`);
    await market.getByRole('button', { name: '应用市场', exact: true }).click();
    await market.getByRole('dialog', { name: '应用市场' }).waitFor();
    const download = market.waitForEvent('download');
    await market.getByRole('link', { name: '下载安装包' }).click();
    assert.match((await download).suggestedFilename(), /\.zip$/);
    pass('host catalogue entry and downloadable extension archive');
  }
  console.log(`${checks} real-browser checks passed`);
} finally {
  await context?.close();
  if (modelService?.listening) await new Promise((resolve) => modelService.close(resolve));
  await new Promise((resolve) => server.close(resolve));
  const resolved = path.resolve(temporary);
  if (
    path.dirname(resolved) !== path.resolve(tmpdir()) ||
    !path.basename(resolved).startsWith('qicheng-plugin-browser-')
  )
    throw new Error('Unsafe temporary cleanup path');
  await rm(resolved, { recursive: true, force: true });
}
