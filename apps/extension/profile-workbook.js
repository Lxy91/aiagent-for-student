import {
  FIELD_LABELS,
  EXPERIENCE_KINDS,
  EXPERIENCE_PARTS,
  experienceKey,
} from './resume-profile.js';

export const SHEET_NAME = '填写资料';
export const HEADERS = ['启用', '字段名称', '字段值', '字段标识', '备注'];
export const DEFAULT_NOTES = {
  phone: '按文本填写，保留前导零和国家区号',
  education_start: 'YYYY-MM 或完整日期；不要补造日期',
  graduation_date: 'YYYY-MM 或完整日期；不要补造日期',
  expected_monthly_salary: '元/月；例如 12000，只填写本人期望',
  salary_months: '月/年；例如 13、15',
  expected_annual_salary: '元/年；请自行填写或在 Excel 中计算并重算保存',
  salary_currency: '例如 CNY、USD',
  preferred_city: '可填写多个城市，注明优先顺序',
  available_date: '填写明确日期或本人可接受的到岗时间',
};

async function excel() {
  const module = await import('exceljs');
  return module.default || module;
}

export function completeTable(fields = []) {
  const existing = new Map(fields.map((field) => [field.key, field]));
  const standard = Object.entries(FIELD_LABELS).map(([key, label]) => ({
    key,
    label,
    value: '',
    enabled: true,
    remark: DEFAULT_NOTES[key] || '',
    ...existing.get(key),
  }));
  const groups = new Map(
    Object.keys(EXPERIENCE_KINDS).map((kind) => [`experience.${kind}.1`, { kind, index: 1 }]),
  );
  for (const field of fields) {
    const record = experienceKey(field.key);
    if (record) groups.set(record.group, record);
  }
  const records = [...groups.values()].flatMap(({ kind, index }) =>
    Object.entries(EXPERIENCE_PARTS).map(([part, label]) => {
      const key = `experience.${kind}.${index}.${part}`;
      return {
        key,
        label: `${EXPERIENCE_KINDS[kind]}${index} · ${label}`,
        value: '',
        enabled: true,
        remark: ['start', 'end'].includes(part)
          ? '保留真实日期精度；YYYY-MM 或 YYYY-MM-DD，至今填“至今”'
          : part === 'location'
            ? '该段经历的实际工作城市/地点，简历未写请本人补充；不要用现居或意向城市代替'
            : part === 'responsibilities'
              ? '填写做了什么、负责事项；职位/职务仅填写岗位名称'
              : '同一条经历共用相同类别和序号；复制这些行并修改序号可新增一条',
        ...existing.get(key),
      };
    }),
  );
  const provided = new Set([...standard, ...records].map((field) => field.key));
  return [...standard, ...records, ...fields.filter((field) => !provided.has(field.key))];
}

export function validateTable(fields, { allowEmpty = false } = {}) {
  if (!Array.isArray(fields) || fields.length > 500) throw new Error('资料表最多支持 500 行');
  const keys = new Set();
  let characters = 0;
  const result = fields.map((field, index) => {
    const key = String(field.key || `custom_${index + 1}`).trim();
    const label = String(field.label || '').trim();
    const value = String(field.value ?? '').trim();
    if (!/^[a-zA-Z][a-zA-Z0-9_.-]{0,79}$/.test(key) || keys.has(key))
      throw new Error(`第 ${index + 2} 行字段标识无效或重复`);
    if (!label || label.length > 100 || value.length > 1500)
      throw new Error(`第 ${index + 2} 行字段名或内容过长/缺失`);
    keys.add(key);
    characters += value.length;
    return {
      key,
      label,
      value,
      enabled: field.enabled !== false,
      remark: String(field.remark || '').slice(0, 300),
    };
  });
  if (characters > 30000) throw new Error('资料表内容总计不能超过 30000 字');
  if (!allowEmpty && !result.some((field) => field.enabled && field.value))
    throw new Error('表格没有已启用且非空的资料，请先填写字段值');
  return result;
}

export async function createProfileWorkbook(fields, sourceName = '') {
  const Excel = await excel();
  const workbook = new Excel.Workbook();
  workbook.creator = '启程投递填表助手';
  const sheet = workbook.addWorksheet(SHEET_NAME, { views: [{ state: 'frozen', ySplit: 1 }] });
  sheet.columns = [
    { header: HEADERS[0], width: 9 },
    { header: HEADERS[1], width: 22 },
    { header: HEADERS[2], width: 65 },
    { header: HEADERS[3], width: 30 },
    { header: HEADERS[4], width: 62 },
  ];
  const table = validateTable(completeTable(fields), { allowEmpty: true });
  for (const field of table) {
    const row = sheet.addRow([
      field.enabled ? '是' : '否',
      field.label,
      field.value,
      field.key,
      field.remark,
    ]);
    const widths = [9, 22, 65, 30, 62];
    const lines = [
      field.enabled ? '是' : '否',
      field.label,
      field.value,
      field.key,
      field.remark,
    ].map((value, index) =>
      String(value)
        .split('\n')
        .reduce(
          (count, line) =>
            count +
            Math.max(1, Math.ceil(line.replace(/[^\x00-\xff]/g, 'xx').length / widths[index])),
          0,
        ),
    );
    row.height = Math.min(360, Math.max(28, 16 * Math.max(...lines) + 8));
    for (let col = 1; col <= 5; col += 1) {
      row.getCell(col).numFmt = '@';
      row.getCell(col).alignment = { vertical: 'top', wrapText: true };
    }
    row.getCell(1).dataValidation = { type: 'list', allowBlank: false, formulae: ['"是,否"'] };
    row.getCell(3).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF0F7F2' } };
  }
  sheet.getRow(1).height = 30;
  sheet.getRow(1).font = { bold: true, color: { argb: 'FFFFFFFF' } };
  sheet.getRow(1).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF256C60' } };
  sheet.autoFilter = `A1:E${sheet.rowCount}`;
  const help = workbook.addWorksheet('填写说明');
  help.columns = [
    { header: '项目', width: 24 },
    { header: '说明', width: 100 },
  ];
  help.addRows([
    ['资料来源', sourceName],
    [
      '修改方式',
      '主要修改“字段值”和“启用”。可新增行，填写字段名称和值；字段标识留空时会自动生成。',
    ],
    ['期望薪资', '月薪、薪资月数、年薪各自独立填写，保留单位。空白不会由 AI 推算或补造。'],
    ['填写前', '在 Excel/WPS 保存后，重新导入本表。插件不会自动监视或覆盖电脑上的原文件。'],
    ['日期与手机号', '建议保留文本格式，以免丢失前导零、国家区号或改变日期。'],
    ['公式', '可以使用 Excel 公式，需在 Excel/WPS 中完成重算并保存，插件读取已保存的结果。'],
    ['授权范围', '“启用=否”、隐藏行、空值不会发给填表模型。不要填写不希望提供给招聘页面的信息。'],
    ['填表依据', 'AI 根据本表资料与页面字段匹配，只能引用表中已有值；提交投递由本人完成。'],
    [
      '多段经历',
      'experience.work.1.name/start/end/description 等字段属于同一条经历。新增经历请复制对应行并将序号改成2、3等（每类最多20条）。在插件底部选择本次填写的一条，在企业页面保存后再填写下一条。',
    ],
    [
      '限字描述',
      '页面有描述字数限制时，AI 可从该条描述逐字摘选原文片段；会在核对区提示，不会新增事实。',
    ],
  ]);
  help.getColumn(2).alignment = { wrapText: true, vertical: 'top' };
  help.getRow(1).font = { bold: true };
  help.eachRow((row) => {
    row.height = Math.max(
      28,
      16 *
        Math.ceil(String(row.getCell(2).value || '').replace(/[^\x00-\xff]/g, 'xx').length / 100) +
        8,
    );
  });
  return new Uint8Array(await workbook.xlsx.writeBuffer());
}

function cellText(cell, row) {
  let value = cell.value;
  if (value === null || value === undefined) return '';
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  if (typeof value === 'object') {
    if ('error' in value) throw new Error(`第 ${row} 行存在 Excel 错误，请修正后保存`);
    if ('formula' in value || 'sharedFormula' in value) {
      if (value.result === undefined || value.result === null)
        throw new Error(`第 ${row} 行公式未保存计算结果，请在 Excel/WPS 重算并保存`);
      value = value.result;
      if (value && typeof value === 'object' && 'error' in value)
        throw new Error(`第 ${row} 行公式计算错误`);
    } else if (value.richText) value = value.richText.map((item) => item.text).join('');
    else if (typeof value.text === 'string') value = value.text;
    else throw new Error(`第 ${row} 行单元格类型不支持`);
  }
  return String(value);
}

export async function readProfileWorkbook(data) {
  const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : data;
  if (bytes.byteLength > 20 * 1024 * 1024) throw new Error('Excel 文件不能超过 20 MB');
  const Excel = await excel();
  const book = new Excel.Workbook();
  try {
    await book.xlsx.load(bytes);
  } catch {
    throw new Error('无法读取 Excel，请使用未加密的 .xlsx 文件');
  }
  const sheet =
    book.getWorksheet(SHEET_NAME) || book.worksheets.find((item) => item.state === 'visible');
  if (!sheet || sheet.state !== 'visible') throw new Error('未找到可见的填写资料工作表');
  const columns = new Map();
  sheet.getRow(1).eachCell((cell, col) => columns.set(cellText(cell, 1).trim(), col));
  if (!columns.has('字段名称') || !columns.has('字段值'))
    throw new Error('表格首行需包含“字段名称”和“字段值”，建议先导出模板');
  if (sheet.rowCount > 501) throw new Error('资料表最多支持 500 行');
  const records = [];
  for (let rowNumber = 2; rowNumber <= sheet.rowCount; rowNumber += 1) {
    const row = sheet.getRow(rowNumber);
    if (row.hidden) continue;
    const read = (name) =>
      columns.has(name) ? cellText(row.getCell(columns.get(name)), rowNumber).trim() : '';
    const label = read('字段名称'),
      value = read('字段值');
    if (!label && !value) continue;
    if (!label) throw new Error(`第 ${rowNumber} 行缺少字段名称`);
    records.push({
      key: read('字段标识') || `custom_${rowNumber}`,
      label,
      value,
      enabled: !['否', 'no', 'false', '0'].includes(read('启用').toLowerCase()),
      remark: read('备注'),
    });
  }
  return validateTable(records);
}

export function downloadWorkbook(bytes, filename) {
  const blob = new Blob([bytes], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = URL.createObjectURL(blob),
    anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
