import { Router, Request, Response } from 'express';

export type ReadinessCheck = () => Promise<void>;

export interface HealthRouterOptions {
  readinessChecks?: Record<string, ReadinessCheck>;
}

export interface HealthHandle {
  router: Router;
  markShuttingDown: () => void;
}

export function createHealthRouter({ readinessChecks = {} }: HealthRouterOptions = {}): HealthHandle {
  const router = Router();
  let isShuttingDown = false;

  router.get('/healthz', (_req: Request, res: Response) => {
    if (isShuttingDown) {
      res.status(503).json({ status: 'shutting_down' });
      return;
    }
    res.json({ status: 'ok' });
  });

  router.get('/readyz', async (_req: Request, res: Response) => {
    if (isShuttingDown) {
      res.status(503).json({ status: 'shutting_down' });
      return;
    }

    const results: Record<string, { status: string; error?: string }> = {};
    let allPassed = true;

    await Promise.all(
      Object.entries(readinessChecks).map(async ([name, check]) => {
        try {
          await Promise.race([
            check(),
            new Promise<void>((_, reject) =>
              setTimeout(() => reject(new Error('timeout')), 2000)
            ),
          ]);
          results[name] = { status: 'ok' };
        } catch (err) {
          results[name] = { status: 'fail', error: (err as Error).message };
          allPassed = false;
        }
      })
    );

    res.status(allPassed ? 200 : 503).json({
      status: allPassed ? 'ready' : 'not_ready',
      checks: results,
    });
  });

  return {
    router,
    markShuttingDown: () => {
      isShuttingDown = true;
    },
  };
}
