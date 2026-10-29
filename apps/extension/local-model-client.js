import { validateSource } from './resume-profile.js';

export const MODEL_SERVICE_URL = 'http://127.0.0.1:18765';

async function localRequest(path, init = {}) {
  let response;
  try {
    response = await fetch(`${MODEL_SERVICE_URL}${path}`, {
      ...init,
      redirect: 'error',
      cache: 'no-store',
      signal: AbortSignal.timeout(path === '/health' ? 4000 : 130000),
      headers: { 'Content-Type': 'application/json', 'X-Qicheng-Plugin': 'application-assistant' },
    });
  } catch (error) {
    if (error.name === 'TimeoutError') throw new Error('本地模型服务请求超时，请稍后重试');
    throw new Error('无法连接本地模型服务，请先运行 pnpm plugin:serve');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `本地模型服务请求失败（${response.status}）`);
  return data;
}

export function readModelStatus() {
  return localRequest('/health');
}
export function requestProfile(source) {
  return localRequest('/profile', {
    method: 'POST',
    body: JSON.stringify({ source: validateSource(source) }),
  });
}

export function requestFillPlan(fields, controls, overwrite = false) {
  return localRequest('/plan', {
    method: 'POST',
    body: JSON.stringify({ fields, controls, overwrite }),
  });
}
