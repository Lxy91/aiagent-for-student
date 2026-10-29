const badge = 'padding:2px 6px;border-radius:3px;font-weight:bold;background:#fff2df;color:#ad6800';
const roleLabels: Record<string, string> = {
  user: '用户',
  system: '上下文',
  assistant: '助手',
  tool: '工具',
};

function preview(value: unknown, limit = 180): string {
  const text = typeof value === 'string' ? value : (JSON.stringify(value) ?? '');
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

/** Each send owns a logger so interleaved conversations retain their trace and order. */
export function createExecutionLogger(conversationId: string) {
  let index = 0;
  let traceId = '';
  return (kind: string, data: Record<string, unknown>) => {
    if (data.trace_id) traceId = String(data.trace_id);
    const prefix = `[执行 ${conversationId.slice(0, 8)} #${++index}]`;
    const identity = { conversationId, traceId, ...data };
    if (kind === 'model.request' || kind === 'context') {
      console.groupCollapsed(
        `${prefix} %c上下文%c ${data.phase ?? '初始上下文'} 第 ${data.iteration ?? 0} 轮`,
        badge,
        '',
      );
      if (Array.isArray(data.messages)) {
        console.table(
          data.messages.map((message: Record<string, unknown>, position: number) => ({
            序号: position + 1,
            角色: roleLabels[String(message.role)] ?? message.role,
            内容: preview(message.content ?? message.tool_calls),
            工具调用: message.tool_call_id ?? '',
          })),
        );
      }
      console.info('完整请求与关联信息', identity);
      console.groupEnd();
    } else if (
      kind === 'tool.failed' ||
      kind === 'error' ||
      kind === 'http.error' ||
      kind === 'connection.error'
    ) {
      console.error(
        `${prefix} [${data.tool ? `工具失败 ${data.tool}` : '请求失败'}] ${data.code ?? ''} ${data.message ?? ''}`,
        identity,
      );
    } else if (kind === 'retry') {
      console.warn(`${prefix} [自动重试 ${data.attempt}/2] ${data.code} ${data.message}`, identity);
    } else if (kind === 'context.compacted') {
      console.info(
        `${prefix} [自动整理上下文] ${data.before_tokens} → ${data.estimated_tokens} Token，继续执行`,
        identity,
      );
    } else if (kind === 'tool.started') {
      console.info(
        `${prefix} %c工具%c ${data.tool} ${preview(data.arguments)} → 开始`,
        badge,
        '',
        identity,
      );
    } else if (kind === 'tool.completed') {
      console.info(
        `${prefix} %c工具%c ${data.tool} → 完成 (${data.elapsed_ms ?? '?'}ms)`,
        badge,
        '',
        identity,
      );
    } else if (kind === 'model.response') {
      console.info(
        `${prefix} %c助手%c ${preview(data.content ?? data.tool_calls)}`,
        badge,
        '',
        identity,
      );
    } else if (kind === 'reasoning.step') {
      if (data.kind !== 'tool') console.info(`${prefix} [助手·执行摘要] ${data.detail}`, identity);
    } else {
      console.info(
        `${prefix} [${kind === 'user' ? '用户' : kind}] ${preview(data.content ?? data.explanation ?? '')}`,
        identity,
      );
    }
  };
}
