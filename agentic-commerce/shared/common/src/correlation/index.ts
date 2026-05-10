import { AsyncLocalStorage } from 'async_hooks';
import { Request, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';
import type { Logger } from 'pino';

export interface CorrelationContext {
  correlationId: string;
  requestId: string;
  userId: string | null;
}

export const correlationStore = new AsyncLocalStorage<CorrelationContext>();

export const CORRELATION_HEADER = 'x-correlation-id';
export const REQUEST_HEADER = 'x-request-id';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      correlationId: string;
      requestId: string;
    }
  }
}

export function correlationMiddleware(req: Request, res: Response, next: NextFunction): void {
  const correlationId = (req.headers[CORRELATION_HEADER] as string) || uuidv4();
  const requestId = uuidv4();

  req.correlationId = correlationId;
  req.requestId = requestId;
  res.setHeader(CORRELATION_HEADER, correlationId);
  res.setHeader(REQUEST_HEADER, requestId);

  correlationStore.run(
    { correlationId, requestId, userId: null },
    () => next()
  );
}

export function getCorrelationContext(): CorrelationContext | undefined {
  return correlationStore.getStore();
}

export function setUserId(userId: string | number): void {
  const ctx = correlationStore.getStore();
  if (ctx) ctx.userId = String(userId);
}

/**
 * Run a function inside a fresh correlation context. Used by Kafka consumers
 * to restore context for incoming events so that any downstream logging or
 * outbound calls inherit the same correlation_id.
 */
export function runWithCorrelation<T>(ctx: CorrelationContext, fn: () => Promise<T>): Promise<T> {
  return correlationStore.run(ctx, fn);
}

/**
 * Wrap a logger so all log calls automatically include the current
 * correlation context (correlation_id, request_id, user_id).
 */
export function withCorrelation(logger: Logger): Logger {
  const handler: ProxyHandler<Logger> = {
    get(target, prop) {
      const original = (target as unknown as Record<string | symbol, unknown>)[prop];
      if (typeof original !== 'function') return original;
      const logMethods = ['trace', 'debug', 'info', 'warn', 'error', 'fatal'];
      if (!logMethods.includes(prop as string)) {
        return (original as Function).bind(target);
      }
      return function (...args: unknown[]) {
        const ctx = correlationStore.getStore();
        if (!ctx) return (original as Function).apply(target, args);

        const enrichment: Record<string, unknown> = {
          correlation_id: ctx.correlationId,
          request_id: ctx.requestId,
        };
        if (ctx.userId) enrichment.user_id = ctx.userId;

        if (typeof args[0] === 'object' && args[0] !== null) {
          args[0] = { ...enrichment, ...(args[0] as object) };
        } else {
          args.unshift(enrichment);
        }
        return (original as Function).apply(target, args);
      };
    },
  };
  return new Proxy(logger, handler);
}
