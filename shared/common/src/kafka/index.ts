import { Kafka, Producer, Consumer, KafkaConfig, EachMessagePayload } from 'kafkajs';
import { v4 as uuidv4 } from 'uuid';
import type { Logger } from 'pino';
import {
  correlationStore,
  getCorrelationContext,
  runWithCorrelation,
  CorrelationContext,
} from '../correlation';

export interface KafkaClientOptions {
  clientId: string;
  brokers: string;
  logger: Logger;
}

export function createKafkaClient({ clientId, brokers, logger }: KafkaClientOptions): Kafka {
  const config: KafkaConfig = {
    clientId,
    brokers: brokers.split(',').map((b) => b.trim()),
    logCreator: () => ({ namespace, level, log }) => {
      const lvlMap: Record<number, 'error' | 'warn' | 'info' | 'debug'> = {
        1: 'error',
        2: 'warn',
        4: 'info',
        5: 'debug',
      };
      const lvl = lvlMap[level] || 'info';
      logger[lvl]({ kafka_namespace: namespace, ...log }, log.message);
    },
    retry: { initialRetryTime: 300, retries: 8 },
  };
  return new Kafka(config);
}

export interface PublishOptions {
  topic: string;
  key?: string | number | null;
  value: unknown;
  headers?: Record<string, string>;
}

export interface ProducerHandle {
  publish: (opts: PublishOptions) => Promise<string>;
  disconnect: () => Promise<void>;
  raw: Producer;
}

export async function createProducer({
  kafka,
  logger,
}: {
  kafka: Kafka;
  logger: Logger;
}): Promise<ProducerHandle> {
  const producer = kafka.producer({
    allowAutoTopicCreation: true,
    idempotent: true,
  });
  await producer.connect();

  return {
    raw: producer,
    async publish({ topic, key, value, headers = {} }: PublishOptions): Promise<string> {
      const ctx = getCorrelationContext();
      const eventId = uuidv4();

      const enrichedHeaders: Record<string, string> = {
        'event-id': eventId,
        'event-timestamp': new Date().toISOString(),
        ...headers,
      };
      if (ctx?.correlationId) enrichedHeaders['x-correlation-id'] = ctx.correlationId;
      if (ctx?.userId) enrichedHeaders['x-user-id'] = String(ctx.userId);

      await producer.send({
        topic,
        messages: [
          {
            key: key !== null && key !== undefined ? String(key) : null,
            value: JSON.stringify(value),
            headers: enrichedHeaders,
          },
        ],
      });

      logger.info({ topic, event_id: eventId, key }, 'Event published');
      return eventId;
    },
    async disconnect(): Promise<void> {
      await producer.disconnect();
    },
  };
}

export interface ConsumerHandlerArgs {
  topic: string;
  partition: number;
  payload: unknown;
  headers: Record<string, string>;
  eventId: string | undefined;
}

export interface ConsumerOptions {
  kafka: Kafka;
  groupId: string;
  topics: string[];
  handler: (args: ConsumerHandlerArgs) => Promise<void>;
  logger: Logger;
  dlqProducer?: ProducerHandle;
  dlqTopic?: string;
}

export interface ConsumerHandle {
  disconnect: () => Promise<void>;
}

export async function createConsumer({
  kafka,
  groupId,
  topics,
  handler,
  logger,
  dlqProducer,
  dlqTopic,
}: ConsumerOptions): Promise<ConsumerHandle> {
  const consumer: Consumer = kafka.consumer({ groupId });
  await consumer.connect();
  for (const topic of topics) {
    await consumer.subscribe({ topic, fromBeginning: false });
  }

  await consumer.run({
    autoCommit: true,
    eachMessage: async ({ topic, partition, message }: EachMessagePayload) => {
      const headers: Record<string, string> = Object.fromEntries(
        Object.entries(message.headers || {}).map(([k, v]) => [k, v?.toString() || ''])
      );

      const correlationId = headers['x-correlation-id'] || uuidv4();
      const eventId = headers['event-id'];
      const userId = headers['x-user-id'] || null;

      const ctx: CorrelationContext = { correlationId, requestId: uuidv4(), userId };

      await runWithCorrelation(ctx, async () => {
        let payload: unknown;
        try {
          payload = JSON.parse(message.value!.toString());
        } catch (err) {
          logger.error({ err, topic, eventId }, 'Failed to parse message');
          if (dlqProducer && dlqTopic) {
            await dlqProducer.publish({
              topic: dlqTopic,
              key: message.key?.toString(),
              value: { raw: message.value?.toString(), error: (err as Error).message },
              headers: { 'original-topic': topic },
            });
          }
          return;
        }

        try {
          await handler({ topic, partition, payload, headers, eventId });
        } catch (err) {
          logger.error({ err, topic, eventId }, 'Handler failed');
          if (dlqProducer && dlqTopic) {
            await dlqProducer.publish({
              topic: dlqTopic,
              key: message.key?.toString(),
              value: { payload, error: (err as Error).message, stack: (err as Error).stack },
              headers: { 'original-topic': topic, 'original-event-id': eventId || '' },
            });
          }
        }
      });
    },
  });

  return {
    async disconnect(): Promise<void> {
      await consumer.disconnect();
    },
  };
}

// Re-export so consumers can use these without separate imports
export { correlationStore };
