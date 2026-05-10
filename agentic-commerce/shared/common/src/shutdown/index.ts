import { Server } from 'http';
import type { Logger } from 'pino';
import type { HealthHandle } from '../health';

export interface ShutdownOptions {
  server?: Server;
  logger: Logger;
  healthHandle?: HealthHandle;
  cleanupFns?: Array<() => Promise<void> | void>;
  timeoutMs?: number;
}

export function setupGracefulShutdown({
  server,
  logger,
  healthHandle,
  cleanupFns = [],
  timeoutMs = 25000,
}: ShutdownOptions): void {
  let shuttingDown = false;

  const shutdown = async (signal: string): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;

    logger.info({ signal }, 'Graceful shutdown initiated');

    const forceExitTimer = setTimeout(() => {
      logger.error('Graceful shutdown timed out, forcing exit');
      process.exit(1);
    }, timeoutMs);

    try {
      if (healthHandle) healthHandle.markShuttingDown();
      await new Promise((r) => setTimeout(r, 2000));

      if (server) {
        await new Promise<void>((resolve, reject) => {
          server.close((err) => (err ? reject(err) : resolve()));
        });
        logger.info('HTTP server closed');
      }

      for (const fn of cleanupFns) {
        try {
          await fn();
        } catch (err) {
          logger.error({ err }, 'Cleanup function failed');
        }
      }

      logger.info('Graceful shutdown complete');
      clearTimeout(forceExitTimer);
      process.exit(0);
    } catch (err) {
      logger.error({ err }, 'Error during graceful shutdown');
      clearTimeout(forceExitTimer);
      process.exit(1);
    }
  };

  process.on('SIGTERM', () => void shutdown('SIGTERM'));
  process.on('SIGINT', () => void shutdown('SIGINT'));
  process.on('uncaughtException', (err) => {
    logger.fatal({ err }, 'Uncaught exception');
    void shutdown('uncaughtException');
  });
  process.on('unhandledRejection', (reason) => {
    logger.fatal({ reason }, 'Unhandled promise rejection');
    void shutdown('unhandledRejection');
  });
}
