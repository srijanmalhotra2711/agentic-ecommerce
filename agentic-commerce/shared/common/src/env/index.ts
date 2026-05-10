import { z, ZodRawShape, ZodObject } from 'zod';

export { z };

export function validateEnv<T extends ZodRawShape>(shape: T): z.infer<ZodObject<T>> {
  const schema = z.object(shape);
  const result = schema.safeParse(process.env);

  if (!result.success) {
    const errors = result.error.errors.map(
      (e) => `  - ${e.path.join('.')}: ${e.message}`
    );
    // eslint-disable-next-line no-console
    console.error(
      `\n❌ Invalid environment configuration:\n${errors.join('\n')}\n`
    );
    process.exit(1);
  }

  return result.data;
}
