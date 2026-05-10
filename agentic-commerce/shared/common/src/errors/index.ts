import { Request, Response, NextFunction } from 'express';
import type { Logger } from 'pino';

export class AppError extends Error {
  public readonly statusCode: number;
  public readonly code: string;
  public readonly details?: unknown;

  constructor(
    message: string,
    opts: { statusCode?: number; code?: string; details?: unknown } = {}
  ) {
    super(message);
    this.name = this.constructor.name;
    this.statusCode = opts.statusCode ?? 500;
    this.code = opts.code ?? 'INTERNAL_ERROR';
    this.details = opts.details;
    Error.captureStackTrace(this, this.constructor);
  }
}

export class ValidationError extends AppError {
  constructor(message: string, details?: unknown) {
    super(message, { statusCode: 400, code: 'VALIDATION_ERROR', details });
  }
}

export class UnauthorizedError extends AppError {
  constructor(message = 'Unauthorized') {
    super(message, { statusCode: 401, code: 'UNAUTHORIZED' });
  }
}

export class ForbiddenError extends AppError {
  constructor(message = 'Forbidden') {
    super(message, { statusCode: 403, code: 'FORBIDDEN' });
  }
}

export class NotFoundError extends AppError {
  constructor(resource: string) {
    super(`${resource} not found`, { statusCode: 404, code: 'NOT_FOUND' });
  }
}

export class ConflictError extends AppError {
  constructor(message: string) {
    super(message, { statusCode: 409, code: 'CONFLICT' });
  }
}

export function errorHandler(logger: Logger) {
  return (err: Error, req: Request, res: Response, _next: NextFunction): void => {
    const isAppError = err instanceof AppError;
    const statusCode = isAppError ? err.statusCode : 500;
    const code = isAppError ? err.code : 'INTERNAL_ERROR';

    const logMethod = statusCode >= 500 ? 'error' : 'warn';
    logger[logMethod](
      { err, path: req.path, method: req.method, statusCode, code },
      err.message
    );

    const isDev = process.env.NODE_ENV !== 'production';
    const body: Record<string, unknown> = {
      code,
      message: isAppError || isDev ? err.message : 'Internal server error',
    };
    if (isAppError && err.details) body.details = err.details;
    if (isDev && !isAppError) body.stack = err.stack;

    res.status(statusCode).json({ error: body });
  };
}
