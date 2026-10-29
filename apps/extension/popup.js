import {
  completeTable,
  createProfileWorkbook,
  readProfileWorkbook,
  validateTable,
  downloadWorkbook,
} from './profile-workbook.js';
import {
  requestProfile,
  requestFillPlan,
  readModelStatus,
  MODEL_SERVICE_URL,
} from './local-model-client.js';
import {
  NARRATIVE_KEYS,
  experienceKey,
  experienceGroups,
  readResume,
  validateSource,
} from './resume-profile.js';

const $ = (id) => document.getElementById(id);
const defaults = {
  apiBase: 'http://localhost:8000/api/v1',
  appUrl: 'http://localhost:5173/memory',
};
let auth, profile, plan, target;
let source = { text: '', filename: '手动资料' };
let busy = false;
let dataRevision = 0;

function status(text, error = false) {
  $('status').textContent = text;
  $('status').classList.toggle('error', error);
  $('operation-feedback').textContent = text;
  $('operation-feedback').classList.toggle('error', error);
  $('operation-feedback').hidden = false;
}

function safeUrl(text) {
  const url = new URL(text);
  if (url.username || url.password || url.search || url.hash)
    throw new Error('服务地址不能包含账号、查询参数或片段');
  if (
    url.protocol !== 'https:' &&
    !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))
  )
    throw new Error('请使用 HTTPS 服务地址，本地服务可使用 HTTP');
  return url;
}

function configuration() {
  return {
    apiBase: safeUrl($('api-base').value.trim()).href.replace(/\/$/, ''),
    appUrl: safeUrl($('app-url').value.trim()).href,
  };
}

async function run(action) {
  if (busy) return;
  busy = true;
  for (const button of document.querySelectorAll('button')) button.disabled = true;
  $('resume-file').disabled = true;
  $('workbook-file').disabled = true;
  try {
    await action();
  } catch (error) {
    status(
      error.name === 'TimeoutError' ? '模型请求超时，请重试' : error.message || '操作失败，请重试',
      true,
    );
  } finally {
    busy = false;
    for (const button of document.querySelectorAll('button')) button.disabled = false;
    $('resume-file').disabled = false;
    $('workbook-file').disabled = false;
  }
}

function invalidatePlan() {
  plan = target = undefined;
  $('plan-section').hidden = true;
  $('fill').hidden = true;
  dataRevision += 1;
}

function showAccount() {
  $('login-form').hidden = Boolean(auth);
  $('account').hidden = !auth;
  if (auth) $('user-name').textContent = auth.user.display_name || auth.user.email;
}

function blankProfile() {
  return { filename: '手动资料', fields: [], notes: [] };
}

function persist() {
  return chrome.storage.session.set({ profile, source });
}

function renderProfile() {
  $('profile-fields').replaceChildren();
  for (const field of completeTable(profile.fields)) {
    const key = field.key,
      labelText = field.label;
    const row = document.createElement('div');
    row.className = 'profile-field';
    row.dataset.key = key;
    row.dataset.label = labelText;
    row.dataset.remark = field.remark || '';
    const label = document.createElement('label');
    label.className = 'checkbox-line';
    const include = document.createElement('input');
    include.type = 'checkbox';
    include.checked = Boolean(field?.value) && field?.enabled !== false;
    label.append(include, document.createTextNode(labelText));
    const input = document.createElement(
      NARRATIVE_KEYS.has(key) ||
        ['description', 'responsibilities'].includes(experienceKey(key)?.part) ||
        field.value.length > 100
        ? 'textarea'
        : 'input',
    );
    input.value = field?.value || '';
    input.setAttribute('aria-label', labelText);
    input.dataset.value = '';
    input.maxLength = 1500;
    input.addEventListener('input', () => {
      if (input.value.trim()) include.checked = true;
      updated();
    });
    include.addEventListener('change', updated);
    function updated() {
      invalidatePlan();
      profile.fields = Array.from($('profile-fields').children).map((item) => ({
        key: item.dataset.key,
        label: item.dataset.label,
        remark: item.dataset.remark,
        value: item.querySelector('[data-value]').value,
        enabled: item.querySelector('input[type="checkbox"]').checked,
      }));
      profile.dirty = true;
      updateTableStatus();
      renderExperienceChoice();
      void persist().catch((error) => status(error.message, true));
    }
    row.append(label, input);
    $('profile-fields').append(row);
  }
  updateTableStatus();
  renderExperienceChoice();
  $('source').textContent = source.text
    ? `来源：${source.filename} · ${source.text.length} 字`
    : '可直接在下方填写资料，无需连接启程或模型服务。';
  $('profile-notes').textContent = [
    ...(profile.notes || []),
    ...(profile.omitted_count ? [`${profile.omitted_count} 项未通过原文校验，已省略。`] : []),
  ].join(' ');
}

function chosenFields() {
  return Array.from($('profile-fields').children)
    .filter((row) => row.querySelector('input[type="checkbox"]').checked)
    .map((row) => ({
      key: row.dataset.key,
      label: row.dataset.label,
      remark: row.dataset.remark,
      value: row.querySelector('[data-value]').value.trim(),
      enabled: true,
    }))
    .filter((field) => field.value);
}

function renderExperienceChoice() {
  const select = $('experience-record');
  const previous = select.options.length > 1 ? select.value : undefined;
  const groups = experienceGroups(profile.fields);
  select.replaceChildren();
  for (const group of [{ id: '', label: '仅填写基本资料' }, ...groups]) {
    const option = document.createElement('option');
    option.value = group.id;
    option.textContent = group.label;
    select.append(option);
  }
  select.value =
    previous !== undefined && [...select.options].some((option) => option.value === previous)
      ? previous
      : groups[0]?.id || '';
  $('experience-choice').hidden = !groups.length;
  $('experience-hint').textContent = groups.length
    ? '实践/实习/项目逐条填写：选择经历 → 匹配并填入 → 在企业页面保存或新增下一条。'
    : '有整段经历但没有明细？可先点击“将表格中的整段经历拆成明细”。';
}

function fieldsForPage() {
  const selected = $('experience-record').value;
  return chosenFields().filter((field) => {
    const record = experienceKey(field.key);
    if (record) return record.group === selected;
    // Never fall back to another record embedded in the legacy aggregate text.
    return !['work_experience', 'project_experience'].includes(field.key);
  });
}

$('experience-record').addEventListener('change', invalidatePlan);
$('split-experiences').addEventListener('click', () =>
  run(async () => {
    const current = chosenFields();
    if (experienceGroups(current).length)
      throw new Error('已有经历明细，请在底部选择本次经历；修改内容可编辑 Excel 后重新导入。');
    const narratives = current.filter((field) => /经历|实践|项目|竞赛|荣誉|任职/.test(field.label));
    if (!narratives.length)
      throw new Error('当前表格没有经历内容，请先导入包含经历的 Excel 或解析简历。');
    const revision = dataRevision;
    status('正在将当前表格中的经历按条拆分，不会读取旧简历或改动薪资等资料…');
    const result = await requestProfile(
      narratives.map(({ label, value }) => `${label}\n${value}`).join('\n\n'),
    );
    const records = result.fields.filter((field) => experienceKey(field.key));
    if (!records.length)
      throw new Error(
        '未识别到有依据的经历明细，请在 Excel 中补充经历名称、起止日期和描述后重试。',
      );
    if (revision !== dataRevision) throw new Error('资料已修改，请重新拆分经历');
    const fields = validateTable([
      ...profile.fields.filter((field) => !experienceKey(field.key)),
      ...records,
    ]);
    const bytes = await createProfileWorkbook(fields, profile.filename || source.filename);
    profile.fields = fields;
    profile.tableName ||= excelFilename(profile.filename || source.filename);
    profile.dirty = false;
    invalidatePlan();
    await persist();
    renderProfile();
    downloadWorkbook(bytes, profile.tableName);
    status(
      `已拆分 ${experienceGroups(records).length} 条经历并导出 Excel。请在底部选择本次经历后匹配页面。`,
    );
  }),
);

async function api(path) {
  if (!auth) throw new Error('请先连接启程账号');
  if (configuration().apiBase !== auth.apiBase) throw new Error('服务地址已变更，请重新连接');
  const response = await fetch(`${auth.apiBase}${path}`, {
    redirect: 'error',
    cache: 'no-store',
    headers: { Authorization: `Bearer ${auth.token}` },
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    auth = undefined;
    await chrome.storage.session.remove('auth');
    showAccount();
    throw new Error('启程登录已过期，请重新连接');
  }
  if (!response.ok) throw new Error(data.error?.message || `请求失败（${response.status}）`);
  return data;
}

function updateTableStatus() {
  updateFileLabels();
  const count = profile.fields.filter(
    (field) => field.enabled !== false && field.value?.trim(),
  ).length;
  $('table-status').textContent = profile.tableName
    ? `当前资料表：${profile.tableName} · ${count} 项可用${profile.dirty ? ' · 已修改，导出可保存为新 Excel' : ''}`
    : `当前 ${count} 项资料；可导出空白模板，补充后重新导入。`;
}

function updateFileLabels() {
  // File inputs reset for same-file re-import; the loaded content has its own persistent name.
  $('resume-filename').textContent = source.text?.trim()
    ? `已读入：${source.filename}`
    : '未选择文件';
  $('workbook-filename').textContent = profile.tableName
    ? `当前资料表：${profile.tableName}`
    : '未导入资料表';
}

for (const [buttonId, inputId] of [
  ['choose-resume', 'resume-file'],
  ['choose-workbook', 'workbook-file'],
]) {
  $(buttonId).addEventListener('click', () => {
    $(inputId).value = '';
    $(inputId).click();
  });
}

function excelFilename(name = '个人') {
  return (
    name
      .replace(/\.[^.]+$/, '')
      .replace(/[\\/:*?"<>|]/g, '_')
      .slice(0, 60) + '_投递资料.xlsx'
  );
}

async function generateTable(text, filename) {
  const revision = dataRevision;
  const result = await requestProfile(text);
  const bytes = await createProfileWorkbook(result.fields, filename);
  const fields = await readProfileWorkbook(bytes);
  const tableName = excelFilename(filename);
  if (revision !== dataRevision)
    throw new Error('资料已修改，本次生成结果未覆盖当前表格，请重新生成');
  profile = {
    fields,
    filename,
    tableName,
    omitted_count: result.omitted_count,
    notes: ['请在 Excel 补充薪资等内容，保存后重新导入；AI 仅使用当前资料表。'],
  };
  invalidatePlan();
  await persist();
  renderProfile();
  downloadWorkbook(bytes, tableName);
  status(
    `已生成 ${fields.filter((field) => field.value).length} 项资料并导出 Excel；补充后可导入重用。`,
  );
}

$('workbook-file').addEventListener('change', () =>
  run(async () => {
    const file = $('workbook-file').files[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.xlsx'))
      throw new Error('请导入 .xlsx 文件；旧版 .xls 请另存为 .xlsx');
    const fields = await readProfileWorkbook(await file.arrayBuffer());
    $('workbook-file').value = '';
    profile = {
      fields,
      filename: file.name,
      tableName: file.name,
      notes: ['已读取你编辑后的 Excel；填写以此表为准。'],
    };
    source = { filename: file.name, text: '' };
    $('resume-text').value = '';
    invalidatePlan();
    await persist();
    renderProfile();
    status(
      `Excel 已导入，${fields.filter((field) => field.enabled && field.value).length} 项可用。点击下方 AI 匹配页面。`,
    );
  }),
);

$('export-workbook').addEventListener('click', () =>
  run(async () => {
    const bytes = await createProfileWorkbook(profile.fields, profile.filename || source.filename);
    const filename = profile.tableName || excelFilename(profile.filename || source.filename);
    profile.tableName = filename;
    profile.dirty = false;
    await persist();
    updateTableStatus();
    renderExperienceChoice();
    downloadWorkbook(bytes, filename);
    status('Excel 已导出。补充字段值并保存后，重新导入即可用于下次填表。');
  }),
);

function renderPlan() {
  $('plan-fields').replaceChildren();
  $('target-site').textContent = `本次填入：${new URL(plan.url).host}`;
  for (const item of plan.items) {
    const row = document.createElement('div');
    row.className = 'plan-field';
    const label = document.createElement('label');
    label.className = 'checkbox-line';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = item.id;
    checkbox.checked = item.status === 'ready';
    checkbox.disabled = item.status !== 'ready';
    label.append(checkbox, document.createTextNode(item.label));
    const value = document.createElement('p');
    value.textContent = item.value;
    const reason = document.createElement('small');
    reason.textContent = item.reason;
    row.append(label, value, reason);
    $('plan-fields').append(row);
  }
  $('plan-section').hidden = false;
  $('fill').hidden = !plan.items.some((item) => item.status === 'ready');
  $('plan-section').scrollIntoView({ block: 'start' });
  if (!plan.items.length)
    status('本页未发现可匹配字段。展开投递表单后再识别；跨域嵌入页面可在独立标签页打开。');
  else
    status(
      `识别到 ${plan.items.length} 项，其中 ${plan.items.filter((item) => item.status === 'ready').length} 项可填。请核对后确认。`,
    );
}

$('resume-file').addEventListener('change', () =>
  run(async () => {
    const file = $('resume-file').files[0];
    if (!file) return;
    status('正在本地读取简历文字…');
    const text = await readResume(file);
    $('resume-file').value = '';
    source = { filename: file.name, text };
    profile = blankProfile();
    $('resume-text').value = text;
    invalidatePlan();
    await persist();
    renderProfile();
    status(`简历文字已导入：${file.name}（${text.length} 字）。可生成资料，也可直接编辑填表资料。`);
  }),
);
$('resume-text').addEventListener('input', () => {
  source.text = $('resume-text').value;
  if (profile.fields.length) {
    profile = blankProfile();
    renderProfile();
  }
  if (!source.filename || source.filename === '手动资料') source.filename = '粘贴的简历文字';
  updateFileLabels();
  invalidatePlan();
  void persist().catch((error) => status(error.message, true));
});
$('check-model').addEventListener('click', () =>
  run(async () => {
    const granted = await chrome.permissions.request({ origins: [`${MODEL_SERVICE_URL}/*`] });
    if (!granted) throw new Error('未获得本地模型服务访问权限');
    const info = await readModelStatus();
    $('model-status').textContent = info.configured
      ? `已连接：${info.model}`
      : '本地服务已启动，请在 .env 中补齐模型配置并重启服务';
    status(
      info.configured ? '本地 .env 模型配置已就绪' : '本地 .env 模型配置尚未完成',
      !info.configured,
    );
  }),
);
$('generate').addEventListener('click', () =>
  run(async () => {
    const text = validateSource($('resume-text').value);
    const granted = await chrome.permissions.request({ origins: [`${MODEL_SERVICE_URL}/*`] });
    if (!granted) throw new Error('未获得本地模型服务访问权限');
    status('正在通过本地 .env 配置生成资料，请保持面板打开…');
    await generateTable(text, source.filename);
  }),
);
$('clear-data').addEventListener('click', () =>
  run(async () => {
    profile = blankProfile();
    source = { text: '', filename: '手动资料' };
    $('resume-text').value = '';
    $('resume-file').value = '';
    invalidatePlan();
    await persist();
    renderProfile();
    status('会话中的简历文字和填表资料已清除');
  }),
);
$('login-form').addEventListener('submit', (event) => {
  event.preventDefault();
  void run(async () => {
    const config = configuration();
    const granted = await chrome.permissions.request({
      origins: [`${new URL(config.apiBase).origin}/*`],
    });
    if (!granted) throw new Error('未获得启程服务访问权限');
    status('正在连接启程账号…');
    const credentials = { email: $('email').value.trim(), password: $('password').value };
    $('password').value = '';
    const response = await fetch(`${config.apiBase}/auth/login`, {
      method: 'POST',
      redirect: 'error',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(credentials),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || '登录失败');
    auth = { token: data.access_token, user: data.user, apiBase: config.apiBase };
    await chrome.storage.session.set({ auth });
    await chrome.storage.local.set({ config });
    $('open-app').href = config.appUrl;
    showAccount();
    status('已连接，可按需导入简历文字');
  });
});
$('logout').addEventListener('click', () =>
  run(async () => {
    auth = undefined;
    await chrome.storage.session.remove('auth');
    showAccount();
    status('已断开启程连接，插件内资料保持独立');
  }),
);
$('sync').addEventListener('click', () =>
  run(async () => {
    const resume = await api('/resume');
    if (!resume) throw new Error('记忆中心尚未上传简历');
    source = { text: validateSource(resume.content), filename: resume.filename };
    profile = blankProfile();
    $('resume-text').value = source.text;
    invalidatePlan();
    await persist();
    renderProfile();
    status('已导入启程简历，正在生成统一 Excel 资料表…');
    await generateTable(source.text, source.filename);
  }),
);

$('overwrite').addEventListener('change', invalidatePlan);
$('scan').addEventListener('click', () =>
  run(async () => {
    const fields = validateTable(fieldsForPage());
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !/^https?:/.test(tab.url || ''))
      throw new Error('请先打开企业投递表单，再点击插件');
    const currentTarget = { tabId: tab.id, url: tab.url, overwrite: $('overwrite').checked };
    target = currentTarget;
    const revision = dataRevision;
    status('正在读取页面字段和下拉选项，请稍候…');
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['form-filler.js'] });
    const [snapshot] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (fields) => globalThis.QichengAutofill.inspectAsync(fields),
      args: [fields],
    });
    const page = snapshot.result;
    if (!page.items.length) throw new Error('本页未找到可读取的投递字段，请展开表单后重试');
    if (!currentTarget.overwrite && page.items.every((item) => item.hasValue || !item.supported))
      throw new Error('页面已有内容默认保留。需要替换时请勾选“允许覆盖页面已有内容”后重新识别');
    status('正在用当前 Excel 表格资料与页面字段进行 AI 匹配…');
    const result = await requestFillPlan(fields, page.items, currentTarget.overwrite);
    if (revision !== dataRevision) throw new Error('表格资料已变化，请重新识别页面');
    const [current] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (current?.id !== currentTarget.tabId || current.url !== currentTarget.url)
      throw new Error('页面已变化，请重新识别');
    const [prepared] = await chrome.scripting.executeScript({
      target: { tabId: currentTarget.tabId },
      func: (id, bindings, data, overwrite) =>
        globalThis.QichengAutofill.prepare(id, bindings, data, overwrite),
      args: [page.scanId, result.bindings, fields, currentTarget.overwrite],
    });
    plan = prepared.result;
    renderPlan();
  }),
);

$('fill').addEventListener('click', () =>
  run(async () => {
    if (!plan || !target) throw new Error('请重新识别页面');
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id !== target.tabId || tab.url !== target.url)
      throw new Error('页面已变化，请重新识别');
    const selected = Array.from($('plan-fields').querySelectorAll('input:checked')).map(
      (input) => input.value,
    );
    if (!selected.length) throw new Error('请勾选要填入的字段');
    const [response] = await chrome.scripting.executeScript({
      target: { tabId: target.tabId },
      func: (id, fields, overwrite) => globalThis.QichengAutofill.fillAsync(id, fields, overwrite),
      args: [plan.scanId, selected, target.overwrite],
    });
    const results = response.result;
    const filled = results.filter((item) => item.status === 'filled').length;
    const pending = plan.items.length - filled;
    const detail = plan.items
      .filter(
        (item) => !results.some((result) => result.id === item.id && result.status === 'filled'),
      )
      .slice(0, 4)
      .map(
        (item) =>
          `${item.label}：${results.find((result) => result.id === item.id)?.reason || item.reason}`,
      );
    invalidatePlan();
    status(
      `填写完成：已填入 ${filled} 项，${pending} 项未填。请核对页面后保存。${detail.length ? '未填原因：' + detail.join('；') : ''}`,
    );
  }),
);

async function initialize() {
  const { config: stored = {} } = await chrome.storage.local.get('config');
  const config = { ...defaults, ...stored };
  $('api-base').value = config.apiBase;
  $('app-url').value = config.appUrl;
  $('open-app').href = safeUrl(config.appUrl).href;
  const saved = await chrome.storage.session.get(['auth', 'profile', 'source']);
  auth = saved.auth;
  profile = saved.profile || blankProfile();
  source = saved.source || source;
  $('resume-text').value = source.text;
  await chrome.storage.session.remove('modelKey');
  await chrome.storage.local.set({ config: { apiBase: config.apiBase, appUrl: config.appUrl } });
  showAccount();
  renderProfile();
  status(
    profile.fields.length
      ? '已恢复表格资料。可重新导入编辑后的 Excel，再进行 AI 匹配填表。'
      : '插件可独立使用。导入简历，或直接维护填表资料。',
  );
}
void initialize().catch((error) => status(error.message, true));
