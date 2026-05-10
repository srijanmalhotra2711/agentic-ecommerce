import express from 'express';
import {
  createLogger,
  correlationMiddleware,
  createHealthRouter,
  setupGracefulShutdown,
  errorHandler,
  createKafkaClient,
  createProducer,
} from '@agentic-commerce/common';
import env from './config';
import * as db from './db';
import { createAuthRouter } from './routes/auth';

async function start(): Promise<void> {
  const logger = createLogger({ serviceName: 'user-service', level: env.LOG_LEVEL });
  logger.info({ port: env.PORT, env: env.NODE_ENV }, 'Starting user-service');

  const kafka = createKafkaClient({
    clientId: 'user-service',
    brokers: env.KAFKA_BROKERS,
    logger,
  });
  const producer = await createProducer({ kafka, logger });

  const app = express();
  app.use(express.json({ limit: '100kb' }));
  app.use(correlationMiddleware);

  const health = createHealthRouter({
    readinessChecks: {
      database: () => db.ping(),
    },
  });
  app.use(health.router);

  app.use('/auth', createAuthRouter({ logger, producer }));

  app.use(errorHandler(logger));

  const server = app.listen(env.PORT, () => {
    logger.info({ port: env.PORT }, 'HTTP server listening');
  });

  setupGracefulShutdown({
    server,
    logger,
    healthHandle: health,
    cleanupFns: [() => producer.disconnect(), () => db.close()],
  });
}

start().catch((err) => {
  // eslint-disable-next-line no-console
  console.error('Failed to start user-service:', err);
  process.exit(1);
});
