import { Router, Request, Response, NextFunction } from 'express';
import {
  ValidationError,
  NotFoundError,
  AppError,
  withCorrelation,
  setUserId,
} from '@agentic-commerce/common';
import type { Logger } from 'pino';
import { pool } from '../db';
import env from '../config';

interface ProductResponse {
  id: number;
  name: string;
  price: number;
  stock: number;
}

async function fetchProduct(productId: number, correlationId: string): Promise<ProductResponse> {
  const url = `${env.PRODUCT_SERVICE_URL}/products/${productId}`;
  const res = await fetch(url, {
    headers: { 'x-correlation-id': correlationId, Accept: 'application/json' },
  });
  if (res.status === 404) throw new NotFoundError(`Product ${productId}`);
  if (!res.ok) {
    throw new AppError(`Product service returned ${res.status}`, {
      statusCode: 502,
      code: 'UPSTREAM_ERROR',
    });
  }
  return (await res.json()) as ProductResponse;
}

interface OrderItemInput {
  product_id: number;
  quantity: number;
}

export function createOrderRouter({ logger }: { logger: Logger }) {
  const router = Router();
  const log = withCorrelation(logger);

  router.post('/', async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { user_id, items } = req.body as { user_id?: number; items?: OrderItemInput[] };

      if (!user_id || !Array.isArray(items) || items.length === 0) {
        throw new ValidationError('user_id and items required');
      }
      if (items.some((i) => !i.product_id || !i.quantity || i.quantity < 1)) {
        throw new ValidationError('each item needs product_id and quantity ≥ 1');
      }

      setUserId(user_id);

      // Fetch product details in parallel — snapshot pricing at order time
      const products = await Promise.all(
        items.map((i) => fetchProduct(i.product_id, req.correlationId))
      );

      const enriched = items.map((item, idx) => ({
        product_id: item.product_id,
        product_name: products[idx].name,
        quantity: item.quantity,
        unit_price: Number(products[idx].price),
      }));

      const totalAmount = enriched.reduce((sum, i) => sum + i.unit_price * i.quantity, 0);

      const client = await pool.connect();
      try {
        await client.query('BEGIN');

        const orderResult = await client.query(
          `INSERT INTO orders (user_id, total_amount, status)
           VALUES ($1, $2, 'pending')
           RETURNING id, total_amount, status, created_at`,
          [user_id, totalAmount]
        );
        const order = orderResult.rows[0];

        for (const item of enriched) {
          await client.query(
            `INSERT INTO order_items (order_id, product_id, product_name, quantity, unit_price)
             VALUES ($1, $2, $3, $4, $5)`,
            [order.id, item.product_id, item.product_name, item.quantity, item.unit_price]
          );
        }

        // Transactional outbox — guaranteed at-least-once event publication
        await client.query(
          `INSERT INTO event_outbox (aggregate_id, event_type, payload, correlation_id)
           VALUES ($1, $2, $3, $4)`,
          [
            order.id,
            'OrderCreated',
            JSON.stringify({
              order_id: order.id,
              user_id,
              total_amount: Number(order.total_amount),
              items: enriched,
            }),
            req.correlationId,
          ]
        );

        await client.query('COMMIT');
        log.info(
          { order_id: order.id, total_amount: Number(order.total_amount), item_count: enriched.length },
          'Order created'
        );
        res.status(201).json({
          order_id: order.id,
          status: order.status,
          total_amount: Number(order.total_amount),
          created_at: order.created_at,
        });
      } catch (err) {
        await client.query('ROLLBACK');
        throw err;
      } finally {
        client.release();
      }
    } catch (err) {
      next(err);
    }
  });

  router.get('/:id', async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { id } = req.params;
      const result = await pool.query(
        `SELECT o.id, o.user_id, o.total_amount, o.status, o.created_at,
                COALESCE(json_agg(json_build_object(
                  'product_id', oi.product_id,
                  'product_name', oi.product_name,
                  'quantity', oi.quantity,
                  'unit_price', oi.unit_price
                )) FILTER (WHERE oi.product_id IS NOT NULL), '[]') AS items
         FROM orders o
         LEFT JOIN order_items oi ON oi.order_id = o.id
         WHERE o.id = $1
         GROUP BY o.id`,
        [id]
      );
      if (result.rows.length === 0) throw new NotFoundError('Order');
      res.json(result.rows[0]);
    } catch (err) {
      next(err);
    }
  });

  return router;
}
