export const FIELD_LABELS = {
  full_name: '姓名',
  phone: '手机号',
  email: '邮箱',
  current_city: '现居城市',
  school: '学校',
  major: '专业',
  degree: '学历',
  education_start: '入学时间',
  graduation_date: '毕业时间',
  github: 'GitHub',
  linkedin: 'LinkedIn',
  portfolio: '个人网站',
  skills: '专业技能',
  self_introduction: '个人介绍',
  work_experience: '工作与实习经历',
  project_experience: '项目经历',
  full_name_pinyin: '姓名拼音',
  expected_monthly_salary: '期望月薪',
  salary_months: '薪资月数',
  expected_annual_salary: '期望年薪',
  salary_currency: '薪资币种',
  expected_position: '意向岗位',
  preferred_city: '意向城市',
  available_date: '可到岗日期',
  certificates: '资格证书',
  english_level: '英语等级',
  english_score: '英语成绩',
  work_location_preference: '意向工作地',
  overseas_preference: '是否接受海外工作',
};
export const NARRATIVE_KEYS = new Set([
  'skills',
  'self_introduction',
  'work_experience',
  'project_experience',
]);
export const EXPERIENCE_KINDS = {
  work: '工作与实习',
  project: '项目',
  practice: '实践活动',
  campus: '在校任职',
  award: '奖励荣誉',
  competition: '竞赛',
};
export const EXPERIENCE_PARTS = {
  name: '名称',
  organization: '单位/组织',
  role: '职位/职务',
  department: '部门',
  location: '工作地点',
  responsibilities: '工作职责',
  start: '开始时间',
  end: '结束时间',
  description: '详细描述',
};
export function experienceKey(key) {
  const match =
    /^experience\.(work|project|practice|campus|award|competition)\.([1-9]|1\d|20)\.(name|organization|role|department|location|responsibilities|start|end|description)$/.exec(
      key,
    );
  return match
    ? {
        kind: match[1],
        index: Number(match[2]),
        part: match[3],
        group: key.slice(0, key.lastIndexOf('.')),
      }
    : null;
}
export function experienceGroups(fields) {
  const groups = new Map();
  for (const field of fields) {
    const record = experienceKey(field.key);
    if (!record || field.enabled === false || !field.value) continue;
    if (!groups.has(record.group))
      groups.set(record.group, {
        id: record.group,
        kind: record.kind,
        index: record.index,
        fields: {},
      });
    groups.get(record.group).fields[record.part] = field.value;
  }
  return [...groups.values()].map((group) => ({
    ...group,
    label: `${EXPERIENCE_KINDS[group.kind]} ${group.index} · ${group.fields.name || group.fields.organization || group.fields.role || '未命名'}`,
  }));
}
const normalize = (text) =>
  String(text || '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[–—−]/g, '-')
    .replace(/\s+/g, '');

export function validateFields(raw, source) {
  if (!raw || !Array.isArray(raw.fields)) throw new Error('模型返回的资料格式无效，请重试');
  const fields = [],
    seen = new Set();
  let omitted = 0;
  for (const fact of raw.fields) {
    const record = experienceKey(fact?.key || '');
    const validShape =
      fact &&
      (Object.hasOwn(FIELD_LABELS, fact.key) || record) &&
      typeof fact.value === 'string' &&
      fact.value.trim() &&
      fact.value.length <= 1500 &&
      !seen.has(fact.key) &&
      Array.isArray(fact.evidence) &&
      fact.evidence.length > 0 &&
      fact.evidence.length <= 6;
    if (
      !validShape ||
      !fact.evidence.every(
        (quote) =>
          typeof quote === 'string' &&
          normalize(quote) &&
          normalize(source).includes(normalize(quote)),
      )
    ) {
      omitted += 1;
      continue;
    }
    const proof = fact.evidence.join(' ');
    let supported = true;
    if (!NARRATIVE_KEYS.has(fact.key)) {
      if (
        ['phone', 'education_start', 'graduation_date'].includes(fact.key) ||
        (record && ['start', 'end'].includes(record.part) && /^\d/.test(fact.value))
      ) {
        const digits = fact.value.replace(/\D/g, '');
        supported = digits.length > 0 && proof.replace(/\D/g, '').includes(digits);
      } else supported = normalize(proof).includes(normalize(fact.value));
    }
    if (fact.key === 'education_start' || fact.key === 'graduation_date') {
      supported &&= /^\d{4}(?:-(?:0[1-9]|1[0-2]))?(?:-(?:0[1-9]|[12]\d|3[01]))?$/.test(fact.value);
    }
    if (record && ['start', 'end'].includes(record.part)) {
      supported &&=
        /^(?:\d{4}(?:-(?:0[1-9]|1[0-2]))?(?:-(?:0[1-9]|[12]\d|3[01]))?|至今|present)$/i.test(
          fact.value,
        );
    }
    if (fact.key === 'phone') supported &&= /^\+?[\d\s()-]{6,24}$/.test(fact.value);
    if (fact.key === 'email') supported &&= /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(fact.value);
    if (!supported) {
      omitted += 1;
      continue;
    }
    fields.push({
      key: fact.key,
      label: record
        ? `${EXPERIENCE_KINDS[record.kind]}${record.index} · ${EXPERIENCE_PARTS[record.part]}`
        : FIELD_LABELS[fact.key],
      value: fact.value.trim(),
    });
    seen.add(fact.key);
  }
  return { fields, omitted_count: omitted };
}

export async function readResume(file) {
  if (file.size > 20 * 1024 * 1024) throw new Error('简历文件不能超过 20 MB');
  const extension = file.name.split('.').pop().toLowerCase();
  const buffer = await file.arrayBuffer();
  let text;
  if (extension === 'pdf') {
    const pdfjs = await import('pdfjs-dist/build/pdf.mjs');
    const base = new URL('.', import.meta.url);
    pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdf.worker.min.mjs', base).href;
    const task = pdfjs.getDocument({
      data: buffer,
      isEvalSupported: false,
      useWasm: false,
      cMapUrl: new URL('cmaps/', base).href,
      cMapPacked: true,
      standardFontDataUrl: new URL('standard_fonts/', base).href,
    });
    let pdf;
    try {
      pdf = await task.promise;
      if (pdf.numPages > 50) throw new Error('简历不能超过 50 页，请精简后导入');
      const pages = [];
      for (let index = 1; index <= pdf.numPages; index += 1) {
        const page = await pdf.getPage(index);
        const content = await page.getTextContent();
        pages.push(
          content.items
            .map((item) => ('str' in item ? item.str + (item.hasEOL ? '\n' : ' ') : ''))
            .join(''),
        );
      }
      text = pages.join('\n\n');
    } catch (error) {
      if (error.name === 'PasswordException') throw new Error('PDF 已加密，请导入未加密版本');
      throw error;
    } finally {
      if (pdf) await pdf.destroy();
      else await task.destroy();
    }
  } else if (extension === 'docx') {
    const module = await import('mammoth/mammoth.browser.js');
    text = (await (module.default || module).extractRawText({ arrayBuffer: buffer })).value;
  } else if (extension === 'txt' || extension === 'md') {
    text = new TextDecoder('utf-8').decode(buffer);
    if (text.includes('\uFFFD')) text = new TextDecoder('gb18030').decode(buffer);
  } else throw new Error('支持 PDF、DOCX、TXT 和 Markdown 简历');
  return validateSource(text);
}

export function validateSource(source) {
  const text = String(source || '').trim();
  if (!text) throw new Error('未读取到文字。扫描版 PDF 请先转为可复制文字的版本，或粘贴简历文字。');
  if (text.length > 30000) throw new Error('简历文字超过 30000 字，请精简后导入');
  return text;
}
