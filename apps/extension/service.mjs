import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { parseEnv } from 'node:util';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { generateProfile, ModelResponseError } from './model-provider.mjs';
import { generateFillPlan, validatePlanRequest } from './model-planner.mjs';
import { validateSource } from './resume-profile.js';

const directory = path.dirname(fileURLToPath(import.meta.url));
export const SERVICE_PORT = 18765;

export function extensionOrigin(key) {
  if (!key) throw new Error('插件 manifest 缺少固定标识');
  const digest = createHash('sha256').update(Buffer.from(key, 'base64')).digest('hex').slice(0, 32);
  return `chrome-extension://${[...digest].map((char) => String.fromCharCode(97 + parseInt(char, 16))).join('')}`;
}

export async function readConfiguration(
  envFile = path.join(directory, '.env'),
  environment = process.env,
) {
  let values = {};
  try {
    values = parseEnv(await readFile(envFile, 'utf8'));
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  const settings = { ...values, ...environment };
  const modelBase = (settings.MODEL_API_BASE || 'https://api.deepseek.com').replace(/\/$/, '');
  const url = new URL(modelBase);
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.protocol !== 'https:' &&
      !(url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)))
  ) {
    throw new Error('MODEL_API_BASE 必须使用 HTTPS，或本机 HTTP 地址');
  }
  return { modelBase, model: settings.MODEL_NAME || '', apiKey: settings.MODEL_API_KEY || '' };
}

export function createModelService(
  config,
  allowedOrigin,
  generate = generateProfile,
  plan = generateFillPlan,
) {
  let pending = 0;
  const server = createServer(async (request, response) => {
    const port = server.address()?.port;
    if (![`127.0.0.1:${port}`, `localhost:${port}`].includes(request.headers.host)) {
      response.writeHead(403).end();
      return;
    }
    const origin = request.headers.origin;
    const path = request.url;
    const publicHealth = !origin && path === '/health' && request.method === 'GET';
    if (origin !== allowedOrigin && !publicHealth) {
      response.writeHead(403).end();
      return;
    }
    if (origin) response.setHeader('Access-Control-Allow-Origin', allowedOrigin);
    response.setHeader('Vary', 'Origin');
    response.setHeader('Cache-Control', 'no-store');
    response.setHeader('Content-Type', 'application/json; charset=utf-8');
    response.setHeader('X-Content-Type-Options', 'nosniff');
    const send = (code, value) => {
      response.writeHead(code);
      response.end(JSON.stringify(value));
    };
    if (request.method === 'OPTIONS') {
      response.setHeader('Access-Control-Allow-Methods', 'POST, GET, OPTIONS');
      response.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Qicheng-Plugin');
      response.writeHead(204).end();
      return;
    }
    if (path === '/health' && request.method === 'GET') {
      send(200, {
        configured: Boolean(config.model && config.apiKey),
        model: config.model,
        provider: new URL(config.modelBase).host,
      });
      return;
    }
    if (!['/profile', '/plan'].includes(path) || request.method !== 'POST') {
      send(404, { error: '接口不存在' });
      return;
    }
    if (
      request.headers['x-qicheng-plugin'] !== 'application-assistant' ||
      !request.headers['content-type']?.startsWith('application/json')
    ) {
      send(403, { error: '请求来源校验失败，请更新并重新加载扩展' });
      return;
    }
    if (!config.model || !config.apiKey) {
      send(503, { error: '请在插件 .env 中配置 MODEL_NAME 和 MODEL_API_KEY，然后重启本地服务' });
      return;
    }
    if (pending >= 2) {
      send(429, { error: '正在生成其他资料，请稍后重试' });
      return;
    }
    let source, planData;
    try {
      const chunks = [];
      const bodyLimit = path === '/plan' ? 512 * 1024 : 128 * 1024;
      let size = 0;
      await new Promise((resolve, reject) => {
        request.on('data', (chunk) => {
          size += chunk.length;
          if (size <= bodyLimit) chunks.push(chunk);
        });
        request.on('end', resolve);
        request.on('error', reject);
      });
      if (size > bodyLimit) {
        send(413, { error: '请求内容过大' });
        return;
      }
      const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      if (path === '/profile') source = validateSource(payload.source);
      else planData = validatePlanRequest(payload);
    } catch {
      send(400, {
        error:
          path === '/profile'
            ? '请提供不超过 30000 字的有效简历文字'
            : '表格资料或页面字段无效，请检查内容和数量后重试',
      });
      return;
    }
    pending += 1;
    try {
      const result =
        path === '/profile'
          ? await generate(
              source,
              { modelBase: config.modelBase, model: config.model },
              config.apiKey,
            )
          : await plan(
              planData,
              { modelBase: config.modelBase, model: config.model },
              config.apiKey,
            );
      send(200, result);
    } catch (error) {
      if (error instanceof ModelResponseError) {
        console.warn(
          'Model response failed',
          JSON.stringify({ code: error.code, ...error.diagnostics }),
        );
        send(502, { error: error.message, code: error.code, diagnostics: error.diagnostics });
        return;
      }
      // Only known, key-free messages; never log source text or upstream request headers.
      const message = /^(模型请求失败|模型结果格式无效|没有提取到)/.test(error.message || '')
        ? error.message
        : '无法完成模型请求，请检查 .env 中的模型配置与网络';
      send(502, { error: message });
    } finally {
      pending -= 1;
    }
  });
  server.requestTimeout = 15000;
  server.headersTimeout = 10000;
  return server;
}

export async function startService() {
  const config = await readConfiguration();
  const manifest = JSON.parse(await readFile(path.join(directory, 'manifest.json'), 'utf8'));
  const server = createModelService(config, extensionOrigin(manifest.key));
  server.on('error', (error) => {
    console.error(
      error.code === 'EADDRINUSE' ? `本地端口 ${SERVICE_PORT} 已被占用` : '本地模型服务启动失败',
    );
    process.exitCode = 1;
  });
  server.listen(SERVICE_PORT, '127.0.0.1', () => {
    console.log(`投递助手模型服务：http://127.0.0.1:${SERVICE_PORT}（仅本机）`);
    console.log(
      config.model && config.apiKey ? '已读取插件 .env 模型配置' : '请配置插件 .env 后重启服务',
    );
  });
  return server;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  startService().catch(() => {
    console.error('读取插件 .env 失败，请检查配置文件');
    process.exitCode = 1;
  });
}
