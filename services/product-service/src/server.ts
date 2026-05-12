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
import { createProductRouter } from './routes/products';

async function start(): Promise<void> {
  const logger = createLogger({ serviceName: 'product-service', level: env.LOG_LEVEL });
  logger.info({ port: env.PORT, env: env.NODE_ENV }, 'Starting product-service');

  const kafka = createKafkaClient({
    clientId: 'product-service',
    brokers: env.KAFKA_BROKERS,
    logger,
  });
  const producer = await createProducer({ kafka, logger });

  const app = express();
  app.use(express.json({ limit: '100kb' }));
  app.use(correlationMiddleware);

  const health = createHealthRouter({
    readinessChecks: { database: () => db.ping() },
  });
  app.use(health.router);
  app.use('/products', createProductRouter({ logger, producer }));
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
  console.error('Failed to start product-service:', err);
  process.exit(1);
});
