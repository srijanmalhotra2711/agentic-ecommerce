import type { Logger } from 'pino';
import type { ProducerHandle } from '@agentic-commerce/common';
import { pool } from '../db';

export interface PollerHandle {
  stop: () => Promise<void>;
}

export function startOutboxPoller({
  producer,
  logger,
  intervalMs = 1000,
}: {
  producer: ProducerHandle;
  logger: Logger;
  intervalMs?: number;
}): PollerHandle {
  let stopped = false;
  let timer: NodeJS.Timeout | null = null;

  async function pollOnce(): Promise<void> {
    if (stopped) return;
    try {
      const client = await pool.connect();
      try {
        await client.query('BEGIN');

        const { rows } = await client.query(
          `SELECT id, aggregate_id, event_type, payload, correlation_id
           FROM event_outbox
           WHERE published_at IS NULL AND attempts < 5
           ORDER BY created_at ASC
           LIMIT 50
           FOR UPDATE SKIP LOCKED`
        );

        for (const event of rows) {
          try {
            await producer.publish({
              topic: event.event_type,
              key: String(event.aggregate_id),
              value: event.payload,
              headers: event.correlation_id ? { 'x-correlation-id': event.correlation_id } : {},
            });
            await client.query(
              'UPDATE event_outbox SET published_at = NOW() WHERE id = $1',
              [event.id]
            );
          } catch (err) {
            await client.query(
              'UPDATE event_outbox SET attempts = attempts + 1, last_error = $2 WHERE id = $1',
              [event.id, (err as Error).message]
            );
            logger.error({ err, outbox_id: event.id }, 'Outbox publish failed');
          }
        }

        await client.query('COMMIT');
      } catch (err) {
        await client.query('ROLLBACK').catch(() => undefined);
        // CRITICAL: catch and log — never let the poller crash the process
        logger.error({ err }, 'Outbox poll failed');
      } finally {
        client.release();
      }
    } catch (err) {
      // Even if we can't get a client, don't crash — just log and try again later
      logger.error({ err }, 'Outbox poll could not acquire DB connection');
    } finally {
      if (!stopped) timer = setTimeout(() => void pollOnce(), intervalMs);
    }
  }

  timer = setTimeout(() => void pollOnce(), intervalMs);

  return {
    async stop(): Promise<void> {
      stopped = true;
      if (timer) clearTimeout(timer);
    },
  };
}
