/* Runs in the extension's isolated world, only after the toolbar is invoked. */
(() => {
  const version = '0.5.0';
  if (globalThis.QichengAutofill?.version === version) return;
  const aliases = {
    full_name: [
      '姓名',
      '中文姓名',
      '真实姓名',
      '个人姓名',
      'fullname',
      'candidatename',
      'applicantname',
      'name',
    ],
    phone: [
      '手机号',
      '手机号码',
      '联系电话',
      '联系电话号码',
      '手机',
      'mobilephone',
      'mobile',
      'phonenumber',
      'phone',
      'telephone',
    ],
    email: ['邮箱', '电子邮箱', '电子邮件', '联系邮箱', 'emailaddress', 'email'],
    current_city: ['现居城市', '当前城市', '居住城市', 'currentcity', 'cityofresidence'],
    school: [
      '毕业院校',
      '毕业学校',
      '学校',
      '学校名称',
      '院校名称',
      '就读院校',
      'universityname',
      'university',
      'collegename',
      'college',
      'schoolname',
      'school',
    ],
    major: ['所学专业', '专业名称', '专业', 'major', 'fieldofstudy', 'specialization'],
    degree: ['最高学历', '学历', '学位', '教育程度', 'degree', 'educationlevel', 'qualification'],
    education_start: [
      '入学时间',
      '入学日期',
      '入学年月',
      '入学年份',
      '入学月份',
      'enrollmentdate',
      'enrollmentyear',
      'educationstart',
    ],
    graduation_date: [
      '毕业时间',
      '毕业日期',
      '毕业年月',
      '毕业年份',
      '毕业月份',
      '预计毕业时间',
      'graduationdate',
      'graduationyear',
      'graduationmonth',
    ],
    github: ['github', 'githuburl', 'github地址'],
    linkedin: ['linkedin', 'linkedinurl', '领英地址'],
    portfolio: [
      '个人网站',
      '个人主页',
      '作品集链接',
      '个人博客',
      'portfolio',
      'personalwebsite',
      'websiteurl',
    ],
    skills: ['专业技能', '专业能力', '技能特长', '技术技能', 'skills', 'professionalskills'],
    self_introduction: [
      '自我介绍',
      '个人介绍',
      '自我评价',
      '个人简介',
      'selfintroduction',
      'personalsummary',
      'aboutme',
    ],
    work_experience: [
      '工作经历',
      '实习经历',
      '工作与实习经历',
      'workexperience',
      'employmenthistory',
    ],
    project_experience: ['项目经历', '项目经验', 'projectexperience', 'projects'],
  };
  const narrative = new Set([
    'skills',
    'self_introduction',
    'work_experience',
    'project_experience',
  ]);
  const clean = (value) =>
    String(value || '')
      .normalize('NFKC')
      .toLowerCase()
      .replace(/请输入|请填写|请选择|必填|required|please enter|please select/gi, '')
      .replace(/[\s\p{P}\p{S}]/gu, '');
  let records = new Map();
  let scanId = '';
  let plannedItems = [];
  const linkedPopups = new WeakMap();
  let activeCombo;

  function labelText(element) {
    if (!element) return '';
    const copy = element.cloneNode(true);
    for (const control of copy.querySelectorAll('input,textarea,select,button,[role="combobox"]'))
      control.remove();
    return copy.textContent;
  }

  function labels(element) {
    const doc = element.ownerDocument;
    const human = [element.getAttribute('aria-label')];
    for (const id of (element.getAttribute('aria-labelledby') || '').split(/\s+/)) {
      if (id) human.push(doc.getElementById(id)?.textContent);
    }
    human.push(...Array.from(element.labels || [], (label) => labelText(label)));
    const row = element.closest('.ant-form-item,.el-form-item,.form-group,.form-item,[data-field]');
    if (row)
      human.push(labelText(row.querySelector('label,.ant-form-item-label,.el-form-item__label')));
    if (!human.some((value) => value && clean(value))) {
      for (
        let parent = element.parentElement, depth = 0;
        parent && depth < 5;
        parent = parent.parentElement, depth += 1
      ) {
        if (parent.querySelectorAll('input:not([type="hidden"]),textarea,select').length > 1) break;
        const label = parent.querySelector('label,[class*="label"]');
        const text = label && !label.contains(element) ? labelText(label).trim() : '';
        if (text && text.length < 60 && clean(text)) {
          human.push(text);
          break;
        }
      }
    }
    const previous = element.previousElementSibling;
    if (
      !human.some((value) => value && clean(value)) &&
      previous?.matches('label,span,strong') &&
      previous.textContent.length < 60 &&
      (!previous.control || previous.control === element)
    )
      human.push(previous.textContent);
    const meaningful = human.filter((value) => value && clean(value));
    return {
      human: meaningful,
      candidates: meaningful.length
        ? [...meaningful, element.getAttribute('placeholder')].filter(Boolean)
        : [element.getAttribute('placeholder'), element.name, element.id],
    };
  }

  function classify(element) {
    const texts = labels(element);
    const all = texts.candidates.join(' ');
    if (
      /紧急|联系人|推荐人|父亲|母亲|配偶|家庭成员|emergency|reference|recommender|search|搜索|筛选|验证码/i.test(
        all,
      )
    )
      return null;
    const matches = new Set();
    for (const candidate of texts.candidates) {
      const value = clean(candidate);
      if (!value) continue;
      for (const [key, names] of Object.entries(aliases)) {
        if (
          names.some(
            (alias) =>
              value === alias ||
              (alias.length >= 4 && value.startsWith(alias) && value.length < 35),
          )
        )
          matches.add(key);
      }
    }
    if (matches.size !== 1) return null;
    return {
      key: [...matches][0],
      label: (texts.human[0] || element.placeholder || element.name || element.id || '')
        .trim()
        .slice(0, 80),
    };
  }

  function visible(element) {
    if (
      !element.isConnected ||
      element.disabled ||
      element.matches(':disabled') ||
      (element.readOnly && !combo(element)) ||
      element.closest('[hidden],[aria-hidden="true"],[inert]')
    )
      return false;
    const style = element.ownerDocument.defaultView.getComputedStyle(element);
    return (
      style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      element.getClientRects().length > 0
    );
  }

  function combo(element) {
    if (element.tagName === 'SELECT') return null;
    if (element.closest('.el-cascader,.ant-cascader,.ant-tree-select,[aria-haspopup="tree"]'))
      return null;
    const root =
      element.closest('.el-select,.ant-select,.phoenix-select') ||
      element.closest('[role="combobox"]') ||
      (element.tagName === 'INPUT' &&
      element.readOnly &&
      /工作地点|工作城市|work\s*location/i.test(labels(element).candidates.join(' '))
        ? element.parentElement
        : null);
    if (
      !root ||
      root.querySelector('select') ||
      root.matches(
        '[aria-disabled="true"],.is-disabled,.ant-select-disabled,.phoenix-select--disabled',
      ) ||
      root.matches('[aria-multiselectable="true"],.is-multiple,.ant-select-multiple') ||
      root.querySelector('.el-tag,.ant-select-selection-overflow')
    )
      return null;
    const trigger = root.querySelector('input:not([type="hidden"])') || root;
    return { root, trigger };
  }

  function comboValue(element) {
    const adapter = combo(element);
    if (!adapter) return element.value?.trim() || '';
    const selected = adapter.root.querySelector(
      '.ant-select-selection-item,.el-select__selected-item:not(.is-transparent)',
    );
    const display = adapter.root.cloneNode(true);
    for (const child of display.querySelectorAll(
      'input,button,[role="listbox"],[role="option"],[aria-hidden="true"]',
    ))
      child.remove();
    const value = (
      selected?.textContent ||
      adapter.trigger.value ||
      adapter.root.getAttribute('aria-valuetext') ||
      display.textContent ||
      ''
    ).trim();
    return /^(请选择.*|please\s*select.*|select\s*one)$/i.test(value) ? '' : value;
  }

  function popupOptions(element) {
    const { root, trigger } = combo(element) || {};
    if (!root) return [];
    const doc = element.ownerDocument;
    const ids = [
      trigger.getAttribute('aria-controls'),
      trigger.getAttribute('aria-owns'),
      root.getAttribute('aria-controls'),
      root.getAttribute('aria-owns'),
    ]
      .filter(Boolean)
      .join(' ')
      .split(/\s+/);
    let panels = ids
      .map((id) => doc.getElementById(id))
      .filter(Boolean)
      .map((panel) => panel.closest('.ant-select-dropdown,.el-select-dropdown') || panel);
    if (!panels.length) {
      panels = [
        ...root.querySelectorAll(
          '[role="listbox"],.el-select-dropdown,.ant-select-dropdown,.phoenix-single-select-list,.single-select-list,.area-selector-container',
        ),
      ];
      if (!panels.length && activeCombo === element && linkedPopups.get(element)?.isConnected)
        panels = [linkedPopups.get(element)];
      if (!panels.length) return [];
    }
    const options = [
      ...new Set(
        panels.flatMap((panel) => [
          ...panel.querySelectorAll(
            '[role="option"],.el-select-dropdown__item,.ant-select-item-option,li[class*="single-select-list__item"],.area-item-container',
          ),
        ]),
      ),
    ];
    return options.filter(
      (option) =>
        visible(option) &&
        !option.matches(
          '[aria-disabled="true"],.is-disabled,.disabled,.ant-select-item-option-disabled',
        ) &&
        !option.querySelector('[role="option"]') &&
        (!option.matches('.area-item-container') ||
          Boolean(
            option.querySelector(
              '.icon-container.visible [class*="area-icon-Radio"]:not([class*="disabled"])',
            ),
          )) &&
        !option.matches('[class*="--disabled"]'),
    );
  }

  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  function optionText(option) {
    const name = option.querySelector('.area-text-label');
    const path = option.querySelector('.area-item-path')?.textContent.trim();
    return name ? name.textContent.trim() + (path ? `（${path}）` : '') : option.textContent.trim();
  }
  function areaFor(element) {
    const root = combo(element)?.root;
    const linked = activeCombo === element ? linkedPopups.get(element) : null;
    const candidates = [root, linked];
    for (const id of (
      element.getAttribute('aria-controls') ||
      element.getAttribute('aria-owns') ||
      ''
    ).split(/\s+/))
      if (id) candidates.push(element.ownerDocument.getElementById(id));
    return candidates
      .filter(Boolean)
      .map((panel) =>
        panel.matches('.area-selector-container')
          ? panel
          : panel.querySelector('.area-selector-container'),
      )
      .find((panel) => panel && visible(panel));
  }
  async function readCombo(element, query = '') {
    let options = await openCombo(element);
    const area = areaFor(element);
    if (!area) return options;
    if (
      area.querySelector('.select-data-num-limit')?.textContent.trim() !== '/1' ||
      !query ||
      query.length > 80
    )
      return [];
    const search = area.querySelector('.area-search-input input');
    if (!search || !visible(search)) return [];
    const view = search.ownerDocument.defaultView;
    Object.getOwnPropertyDescriptor(view.HTMLInputElement.prototype, 'value').set.call(
      search,
      query,
    );
    search.dispatchEvent(new view.Event('input', { bubbles: true }));
    search.dispatchEvent(new view.Event('change', { bubbles: true }));
    for (let index = 0; index < 18; index += 1) {
      await delay(100);
      options = popupOptions(element);
      if (area.querySelector('.search-result') && options.length) return options;
    }
    return [];
  }

  function activate(element) {
    const view = element.ownerDocument.defaultView;
    element.dispatchEvent(
      new view.PointerEvent('pointerdown', {
        bubbles: true,
        pointerType: 'mouse',
        pointerId: 1,
        button: 0,
        buttons: 1,
      }),
    );
    element.dispatchEvent(
      new view.MouseEvent('mousedown', { bubbles: true, button: 0, buttons: 1 }),
    );
    element.focus?.({ preventScroll: true });
    element.dispatchEvent(
      new view.PointerEvent('pointerup', {
        bubbles: true,
        pointerType: 'mouse',
        pointerId: 1,
        button: 0,
      }),
    );
    element.dispatchEvent(new view.MouseEvent('mouseup', { bubbles: true, button: 0 }));
    if (typeof element.click === 'function') element.click();
    else element.dispatchEvent(new view.MouseEvent('click', { bubbles: true, button: 0 }));
  }

  async function openCombo(element) {
    const adapter = combo(element);
    if (!adapter || !visible(element)) return [];
    let options = popupOptions(element);
    if (options.length) return options;
    const doc = element.ownerDocument;
    const before = new Set(
      [
        ...doc.querySelectorAll(
          '[role="listbox"],.el-select-dropdown,.ant-select-dropdown,.phoenix-single-select-list,.single-select-list,.area-selector-container',
        ),
      ].filter(visible),
    );
    activate(adapter.trigger);
    for (let index = 0; index < 15; index += 1) {
      await delay(40);
      if (!element.isConnected) return [];
      options = popupOptions(element);
      if (!options.length) {
        const appeared = [
          ...doc.querySelectorAll(
            '[role="listbox"],.el-select-dropdown,.ant-select-dropdown,.phoenix-single-select-list,.single-select-list,.area-selector-container',
          ),
        ].filter((panel) => visible(panel) && !before.has(panel));
        const roots = appeared.filter(
          (panel) => !appeared.some((other) => other !== panel && other.contains(panel)),
        );
        if (roots.length === 1) {
          linkedPopups.set(element, roots[0]);
          activeCombo = element;
          options = popupOptions(element);
        }
      }
      if (options.length) return options;
    }
    return [];
  }

  function closeCombo(element) {
    const adapter = combo(element);
    if (!adapter) return;
    const area = areaFor(element);
    const cancel =
      area &&
      [...area.querySelectorAll('.area-footer-button button')].find((button) =>
        /^(取消|cancel)$/i.test(button.textContent.trim()),
      );
    if (cancel) activate(cancel);
    const view = element.ownerDocument.defaultView;
    adapter.trigger.dispatchEvent(
      new view.KeyboardEvent('keydown', {
        key: 'Escape',
        code: 'Escape',
        keyCode: 27,
        which: 27,
        bubbles: true,
      }),
    );
    if (popupOptions(element).length) activate(element.ownerDocument.body);
    if (activeCombo === element) activeCombo = undefined;
  }

  function controls(root, result = []) {
    for (const element of root.querySelectorAll('*')) {
      if (element.matches('input,textarea,select,[role="combobox"],.phoenix-select'))
        result.push(element);
      if (element.shadowRoot) controls(element.shadowRoot, result);
      if (element.tagName === 'IFRAME') {
        try {
          if (element.contentDocument) controls(element.contentDocument, result);
        } catch {
          /* cross-origin frame */
        }
      }
    }
    return result;
  }

  function datePart(element, key) {
    if (key !== 'education_start' && key !== 'graduation_date') return '';
    const text = labels(element).candidates.join(' ');
    return /年份|year/i.test(text)
      ? 'year'
      : /月份|month/i.test(text) && !/年月/.test(text)
        ? 'month'
        : '';
  }

  function adaptedValue(element, key, value) {
    const type = (element.type || '').toLowerCase();
    let result = value;
    if (
      key === 'education_start' ||
      key === 'graduation_date' ||
      type === 'date' ||
      type === 'month'
    ) {
      const date = value.match(/^(\d{4})(?:[./年-](\d{1,2}))?(?:[./月-](\d{1,2}))?/);
      if (!date) return null;
      const part = datePart(element, key);
      if (part === 'year') result = date[1];
      else if (part === 'month') result = date[2] ? String(Number(date[2])) : null;
      else if (type === 'month') result = date[2] ? `${date[1]}-${date[2].padStart(2, '0')}` : null;
      else if (type === 'date')
        result =
          date[2] && date[3]
            ? `${date[1]}-${date[2].padStart(2, '0')}-${date[3].padStart(2, '0')}`
            : null;
    }
    if (result === null) return null;
    if (element.tagName === 'SELECT') {
      const degreeGroups = [
        ['本科', '学士', 'bachelor', 'bachelorsdegree'],
        ['硕士', 'master', 'mastersdegree'],
        ['博士', 'phd', 'doctorate'],
        ['专科', '大专', 'associate'],
      ];
      let values = [clean(result)];
      if (key === 'degree')
        values = degreeGroups.find((group) => group.includes(clean(result))) || values;
      const options = Array.from(element.options).filter(
        (option) =>
          !option.disabled &&
          option.value &&
          (values.includes(clean(option.textContent)) || values.includes(clean(option.value))),
      );
      return options.length === 1 ? options[0].value : null;
    }
    if (type === 'number' && !/^\d+(\.\d+)?$/.test(result)) return null;
    if (element.maxLength > 0 && result.length > element.maxLength) return null;
    if (narrative.has(key) && element.tagName !== 'TEXTAREA') return null;
    return result;
  }

  function existing(element) {
    if (combo(element)) return Boolean(comboValue(element));
    if (element.tagName === 'SELECT') {
      const option = element.selectedOptions[0];
      return Boolean(
        element.value &&
        !/^(请选择.*|please\s*select.*|select\s*one)$/i.test(option?.textContent.trim() || ''),
      );
    }
    return Boolean(element.value?.trim());
  }

  function scan(fields, overwrite = false) {
    records = new Map();
    scanId = crypto.randomUUID();
    const supplied = new Map(
      fields
        .filter((field) => typeof field.value === 'string' && field.value.trim())
        .map((field) => [field.key, field.value]),
    );
    const result = [];
    for (const element of controls(document)) {
      if (!visible(element)) continue;
      const type = (element.type || '').toLowerCase();
      if (
        [
          'password',
          'search',
          'hidden',
          'file',
          'checkbox',
          'radio',
          'submit',
          'button',
          'reset',
        ].includes(type)
      )
        continue;
      const match = classify(element);
      if (!match || !supplied.has(match.key)) continue;
      const native =
        ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName) &&
        !combo(element) &&
        element.getAttribute('role') !== 'combobox';
      const value = native ? adaptedValue(element, match.key, supplied.get(match.key)) : null;
      const status =
        !native || value === null
          ? 'unsupported'
          : existing(element) && !overwrite
            ? 'existing'
            : 'ready';
      const item = {
        id: `${scanId}:${result.length}`,
        key: match.key,
        label: match.label,
        value: supplied.get(match.key),
        status,
        reason:
          status === 'unsupported'
            ? '自定义控件、选项不匹配或日期不完整，请手填'
            : status === 'existing'
              ? '已有内容，已保留'
              : '待确认填入',
      };
      result.push(item);
      records.set(item.id, {
        element,
        key: match.key,
        value,
        status,
        part: datePart(element, match.key),
      });
    }
    const counts = new Map();
    for (const item of result) {
      const record = records.get(item.id);
      const key = `${item.key}:${record.part}`;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    for (const item of result) {
      const record = records.get(item.id);
      if (counts.get(`${item.key}:${record.part}`) > 1 && item.status === 'ready') {
        item.status = record.status = 'ambiguous';
        item.reason = '有多个同类字段，需手动选择对应经历';
      }
    }
    return { scanId, items: result, url: location.href };
  }

  function signature(element) {
    return JSON.stringify([
      labels(element).candidates,
      element.name,
      element.type,
      element.maxLength,
      element.tagName === 'SELECT'
        ? Array.from(element.options, (option) => [option.value, option.textContent])
        : null,
    ]);
  }

  function sectionContext(element) {
    // Section headings distinguish identical labels such as “详细描述” without sending saved records.
    const headings = [];
    let parent = element.parentElement;
    for (let depth = 0; parent && depth < 7; depth += 1, parent = parent.parentElement) {
      const heading = parent.querySelector(
        'h1,h2,h3,h4,legend,[role="heading"],.panel-heading,.panel-title,.section-title',
      );
      if (heading && !heading.contains(element)) {
        const text = labelText(heading).trim().slice(0, 100);
        if (text && !headings.includes(text)) headings.push(text);
      }
      if (headings.length === 2) break;
    }
    return headings.join(' / ');
  }

  function inspect() {
    records = new Map();
    plannedItems = [];
    scanId = crypto.randomUUID();
    const items = [];
    for (const element of controls(document)) {
      if (!visible(element)) continue;
      const adapter = combo(element);
      if (element.closest('.area-selector-container,.phoenix-single-select-list')) continue;
      if (adapter && adapter.trigger !== element) continue;
      const type = (element.type || '').toLowerCase();
      if (
        (!adapter && type === 'search') ||
        ['password', 'hidden', 'file', 'checkbox', 'radio', 'submit', 'button', 'reset'].includes(
          type,
        )
      )
        continue;
      const text = labels(element).candidates.filter(Boolean).join(' ').slice(0, 160);
      if (
        !text ||
        /密码|验证码|证件号码|身份证|银行卡|银行账号|password|captcha|\bssn\b/i.test(text)
      )
        continue;
      const native =
        ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName) &&
        !adapter &&
        element.getAttribute('role') !== 'combobox';
      const item = {
        controlId: `${scanId}:${items.length}`,
        label: text,
        name: (element.name || element.id || '').slice(0, 80),
        tag: element.tagName,
        type,
        hasValue: existing(element),
        supported: native,
        customSelect: Boolean(adapter),
        maxLength: element.maxLength > 0 ? element.maxLength : 0,
        context: (
          sectionContext(element) +
          ' ' +
          labelText(element.closest('tr,.ant-form-item,.el-form-item,.form-group,.form-item'))
        ).slice(0, 160),
        options:
          element.tagName === 'SELECT'
            ? Array.from(element.options)
                .filter((option) => !option.disabled && option.value)
                .slice(0, 100)
                .map((option) => ({
                  value: option.value.slice(0, 120),
                  label: option.textContent.trim().slice(0, 120),
                }))
            : [],
      };
      items.push(item);
      records.set(item.controlId, {
        element,
        ai: true,
        signature: signature(element),
        descriptor: item,
        status: 'pending',
        custom: Boolean(adapter),
      });
      if (items.length >= 180) break;
    }
    return { scanId, items, url: location.href };
  }

  async function inspectAsync(fields = []) {
    const snapshot = inspect();
    let opened = 0;
    for (const item of snapshot.items) {
      const record = records.get(item.controlId);
      if (!record.custom || opened++ >= 20) continue;
      record.searchQuery = /工作地点|工作城市|work\s*location/i.test(item.label)
        ? fields.find(
            (field) =>
              /^experience\.[^.]+\.\d+\.location$/.test(field.key) && field.enabled !== false,
          )?.value || ''
        : '';
      const options = await readCombo(record.element, record.searchQuery);
      const labels = [
        ...new Set(options.map(optionText).filter((text) => text && text.length <= 120)),
      ].slice(0, 100);
      item.options = labels.map((label) => ({ value: label, label }));
      item.supported = labels.length > 0;
      closeCombo(record.element);
      record.signature = signature(record.element);
    }
    return snapshot;
  }

  function tableValue(element, field) {
    const target = labels(element).candidates.join(' ');
    let value = field.value;
    if (/薪|salary/i.test(field.label || '')) {
      const period = (text) =>
        /年薪|年收入|年包|annual|per year|\/年/i.test(text)
          ? 'annual'
          : /月薪|月收入|monthly|per month|\/月/i.test(text)
            ? 'monthly'
            : '';
      const sourcePeriod = period(`${field.label} ${field.remark || ''}`),
        targetPeriod = period(target);
      if (sourcePeriod && targetPeriod && sourcePeriod !== targetPeriod) return null;
      if (
        field.key === 'salary_months' &&
        !/月数|几个月|多少个月|几薪|发放|salarymonths|payperiods/i.test(target)
      )
        return null;

      const sourceK =
        /(?:\bk\b|千元)/i.test(`${value} ${field.remark || ''}`) || /\d\s*k$/i.test(value);
      const sourceYuan = !sourceK && /元/.test(field.remark || '');
      const targetK = /千元|\bk\b|k[\/月年)）]/i.test(target);
      const targetYuan = !targetK && /元/.test(target);
      if (targetK && !sourceK && !sourceYuan) return null;
      const number = value.replace(/[,，]/g, '').match(/^([0-9]+(?:\.[0-9]+)?)\s*(?:k|千元)?$/i);
      if ((targetK && sourceYuan) || (targetYuan && sourceK)) {
        if (!number) return null;
        value = String(Number(number[1]) * (targetK ? 0.001 : 1000));
      } else if (sourceK && targetK && number) value = number[1];
    }
    return adaptedValue(element, field.key, value);
  }

  function prepare(id, bindings, fields, overwrite = false) {
    if (id !== scanId) throw new Error('页面扫描已过期，请重新识别');
    const supplied = new Map(
      fields
        .filter((field) => field.enabled !== false && field.value)
        .map((field) => [field.key, field]),
    );
    const counts = new Map();
    const experienceCounts = new Map();
    for (const binding of bindings)
      counts.set(binding.controlId, (counts.get(binding.controlId) || 0) + 1);
    for (const binding of bindings)
      if (/^experience\./.test(binding.fieldKey))
        experienceCounts.set(binding.fieldKey, (experienceCounts.get(binding.fieldKey) || 0) + 1);
    const items = [];
    for (const binding of bindings) {
      const record = records.get(binding.controlId),
        field = supplied.get(binding.fieldKey);
      if (
        !record?.ai ||
        !field ||
        counts.get(binding.controlId) !== 1 ||
        experienceCounts.get(binding.fieldKey) > 1
      )
        continue;
      const { element, descriptor } = record;
      if (!visible(element) || signature(element) !== record.signature) continue;
      if (
        (/工作地点|工作城市|办公地点|work\s*location/i.test(descriptor.label) &&
          ['current_city', 'preferred_city', 'work_location_preference'].includes(field.key)) ||
        (/职责|工作内容|实习内容|responsibilities|duties/i.test(descriptor.label) &&
          /^experience\.[^.]+\.\d+\.role$/.test(field.key))
      )
        continue;
      let inputField = field;
      if (binding.excerpts !== undefined) {
        const narrativeField =
          narrative.has(field.key) ||
          /^experience\.[a-z]+\.\d+\.(description|responsibilities)$/.test(field.key);
        if (
          !narrativeField ||
          element.tagName !== 'TEXTAREA' ||
          element.maxLength <= 0 ||
          !Array.isArray(binding.excerpts) ||
          !binding.excerpts.length ||
          binding.excerpts.length > 8 ||
          !binding.excerpts.every(
            (text) => typeof text === 'string' && text.trim() && field.value.includes(text),
          ) ||
          binding.excerpts.join('\n').length > element.maxLength
        )
          continue;
        inputField = { ...field, value: binding.excerpts.join('\n') };
      }
      let value = descriptor.supported ? tableValue(element, inputField) : null;
      if (record.custom) {
        const option = descriptor.options.filter((option) =>
          binding.optionValue != null
            ? option.value === binding.optionValue
            : clean(option.label) === clean(field.value),
        );
        value = descriptor.supported && option.length === 1 ? option[0].label : null;
      }
      if (element.tagName === 'SELECT' && binding.optionValue !== undefined) {
        value = Array.from(element.options).some(
          (option) => !option.disabled && option.value === binding.optionValue,
        )
          ? binding.optionValue
          : null;
      }
      const status =
        value === null ? 'unsupported' : existing(element) && !overwrite ? 'existing' : 'ready';
      record.key = field.key;
      record.value = value;
      record.status = status;
      items.push({
        id: binding.controlId,
        key: field.key,
        label: descriptor.label,
        value:
          element.tagName === 'SELECT' && value !== null
            ? Array.from(element.options).find((option) => option.value === value)?.textContent ||
              field.value
            : (value ?? field.value),
        sourceLabel: field.label,
        sourceValue: field.value,
        status,
        reason:
          status === 'unsupported'
            ? '控件、日期或单位不能可靠转换，请手填'
            : status === 'existing'
              ? '已有内容，已保留'
              : `AI 匹配表格字段：${field.label}${binding.excerpts ? '（按页面字数限制摘选原文，请核对）' : ''}`,
      });
    }
    const included = new Set(items.map((item) => item.id));
    for (const [controlId, record] of records) {
      if (!record.ai || included.has(controlId) || (existing(record.element) && !overwrite))
        continue;
      const label = record.descriptor.label;
      const part = /工作地点|工作城市|办公地点/i.test(label)
        ? 'location'
        : /职责|工作内容|实习内容/i.test(label)
          ? 'responsibilities'
          : /部门/i.test(label)
            ? 'department'
            : '';
      const available = [...supplied.values()];
      const missing =
        part &&
        !available.some(
          (field) =>
            field.key.endsWith(`.${part}`) ||
            (part === 'responsibilities' && field.key.endsWith('.description')),
        );
      items.push({
        id: controlId,
        label,
        value: '',
        status: 'unmatched',
        reason: missing
          ? `所选经历未填写${part === 'location' ? '工作地点' : part === 'department' ? '部门' : '工作职责'}，请在 Excel 或表格资料中补充`
          : !record.descriptor.supported
            ? '暂未读取到可操作的控件或选项，请展开下拉后重新识别；级联和多选需手动处理'
            : '未找到可靠的表格对应项，请补充资料或手动选择',
      });
    }
    plannedItems = items;
    return { scanId, items, url: location.href };
  }

  function fill(id, selectedIds, overwrite = false) {
    if (id !== scanId) throw new Error('页面扫描已过期，请重新识别');
    const result = [];
    for (const fieldId of new Set(selectedIds)) {
      const record = records.get(fieldId);
      if (!record || record.status !== 'ready' || record.custom) continue;
      const { element } = record;
      if (
        !visible(element) ||
        (record.ai
          ? signature(element) !== record.signature
          : classify(element)?.key !== record.key) ||
        (existing(element) && !overwrite)
      ) {
        result.push({ id: fieldId, status: 'skipped', reason: '字段已变化或已有内容' });
        continue;
      }
      const view = element.ownerDocument.defaultView;
      const prototype =
        element.tagName === 'SELECT'
          ? view.HTMLSelectElement.prototype
          : element.tagName === 'TEXTAREA'
            ? view.HTMLTextAreaElement.prototype
            : view.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, record.value);
      element.dispatchEvent(new view.Event('input', { bubbles: true, composed: true }));
      element.dispatchEvent(new view.Event('change', { bubbles: true, composed: true }));
      result.push({
        id: fieldId,
        status: element.value === record.value ? 'filled' : 'skipped',
        reason: element.value === record.value ? '已填入，请核对' : '页面未接受该值，请手填',
      });
      record.status = 'filled';
    }
    return result;
  }

  function notifyPage(results) {
    const doc = document;
    doc.querySelector('[data-qicheng-feedback]')?.remove();
    const host = doc.createElement('div');
    host.setAttribute('data-qicheng-feedback', '');
    host.style.cssText = 'position:fixed;top:20px;right:20px;z-index:2147483647;max-width:360px';
    const shadow = host.attachShadow({ mode: 'open' });
    const box = doc.createElement('div');
    box.setAttribute('role', 'status');
    box.style.cssText =
      'font:14px/1.6 system-ui,sans-serif;color:#20362f;background:#eef8f1;border:1px solid #91c3a5;border-radius:10px;padding:14px 18px;box-shadow:0 4px 20px #0002';
    const count = results.filter((item) => item.status === 'filled').length;
    box.textContent = `启程填表完成：已填 ${count} 项，${Math.max(0, plannedItems.length - count)} 项未填。请核对页面后自行保存；未填原因见插件面板。`;
    shadow.append(box);
    doc.documentElement.append(host);
    setTimeout(() => host.remove(), 10000);
  }

  async function fillAsync(id, selectedIds, overwrite = false) {
    if (id !== scanId) throw new Error('页面扫描已过期，请重新识别');
    const results = [];
    for (const fieldId of new Set(selectedIds)) {
      const record = records.get(fieldId);
      if (!record?.custom) {
        results.push(...fill(id, [fieldId], overwrite));
        continue;
      }
      const { element } = record;
      if (
        record.status !== 'ready' ||
        !visible(element) ||
        signature(element) !== record.signature ||
        (existing(element) && !overwrite)
      ) {
        results.push({ id: fieldId, status: 'skipped', reason: '字段已变化或已有内容' });
        continue;
      }
      const previous = comboValue(element);
      const options = await readCombo(element, record.searchQuery);
      const candidates = options.filter((option) => optionText(option) === record.value);
      if (
        id !== scanId ||
        !visible(element) ||
        signature(element) !== record.signature ||
        comboValue(element) !== previous ||
        candidates.length !== 1
      ) {
        closeCombo(element);
        results.push({
          id: fieldId,
          status: 'skipped',
          reason: '下拉选项已变化或存在歧义，请重新识别',
        });
        continue;
      }
      const area = areaFor(element);
      const expectedName = candidates[0].querySelector('.area-text-label')?.textContent.trim();
      const radio = candidates[0].querySelector(
        '.icon-container.visible [class*="area-icon-Radio"]',
      );
      activate(area && radio ? radio : candidates[0]);
      if (area) {
        await delay(80);
        const confirm = [...area.querySelectorAll('.area-footer-button button')].find(
          (button) =>
            /^(确定|確定|ok|confirm)$/i.test(button.textContent.trim()) && !button.disabled,
        );
        if (area.querySelector('.select-data-num-text')?.textContent.trim() === '1' && confirm)
          activate(confirm);
      }
      await delay(120);
      const displayed = comboValue(element);
      const accepted =
        area && expectedName ? displayed.includes(expectedName) : displayed === record.value;
      closeCombo(element);
      record.status = accepted ? 'filled' : 'skipped';
      results.push({
        id: fieldId,
        status: record.status,
        reason: accepted ? '已选择，请核对' : '页面未确认选择结果，请手动核对',
      });
    }
    notifyPage(results);
    return results;
  }
  globalThis.QichengAutofill = { version, scan, inspect, inspectAsync, prepare, fill, fillAsync };
})();
