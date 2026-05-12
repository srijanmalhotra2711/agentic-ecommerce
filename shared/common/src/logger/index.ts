import pino, { Logger, LoggerOptions } from 'pino';

export interface CreateLoggerOptions {
  serviceName: string;
  level?: string;
}

export function createLogger({ serviceName, level }: CreateLoggerOptions): Logger {
  if (!serviceName) {
    throw new Error('createLogger requires a serviceName');
  }

  const isDev = process.env.NODE_ENV !== 'production';
  const logLevel = level || process.env.LOG_LEVEL || (isDev ? 'debug' : 'info');

  const opts: LoggerOptions = {
    level: logLevel,
    base: {
      service: serviceName,
      env: process.env.NODE_ENV || 'development',
      version: process.env.SERVICE_VERSION || 'dev',
    },
    timestamp: pino.stdTimeFunctions.isoTime,
    redact: {
      paths: [
        'req.headers.authorization',
        'req.headers.cookie',
        '*.password',
        '*.token',
        '*.secret',
        '*.apiKey',
      ],
      censor: '[REDACTED]',
    },
  };

  if (isDev) {
    opts.transport = {
      target: 'pino-pretty',
      options: {
        colorize: true,
        translateTime: 'HH:MM:ss.l',
        ignore: 'pid,hostname',
      },
    };
  }

  return pino(opts);
}
