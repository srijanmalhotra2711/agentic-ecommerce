import { validateEnv, z } from '@agentic-commerce/common';

const env = validateEnv({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  PORT: z.coerce.number().int().positive().default(3002),
  LOG_LEVEL: z.enum(['trace', 'debug', 'info', 'warn', 'error']).default('info'),
  DATABASE_URL: z.string().url(),
  DB_POOL_MAX: z.coerce.number().int().positive().default(10),
  KAFKA_BROKERS: z.string().min(1),
  SERVICE_VERSION: z.string().default('dev'),
});

export default env;
