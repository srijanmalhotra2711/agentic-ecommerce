import { Router, Request, Response, NextFunction } from 'express';
import {
  ValidationError,
  NotFoundError,
  withCorrelation,
} from '@agentic-commerce/common';
import type { Logger } from 'pino';
import type { ProducerHandle } from '@agentic-commerce/common';
import { pool } from '../db';

export function createProductRouter({ logger, producer }: { logger: Logger; producer: ProducerHandle }) {
  const router = Router();
  const log = withCorrelation(logger);

  // List products
  router.get('/', async (_req: Request, res: Response, next: NextFunction) => {
    try {
      const result = await pool.query(
        `SELECT id, name, description, price, stock, category, created_at
         FROM products ORDER BY id LIMIT 100`
      );
      res.json(result.rows);
    } catch (err) {
      next(err);
    }
  });

  // Get one
  router.get('/:id', async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { id } = req.params;
      const result = await pool.query(
        `SELECT id, name, description, price, stock, category, created_at
         FROM products WHERE id = $1`,
        [id]
      );
      if (result.rows.length === 0) throw new NotFoundError('Product');
      res.json(result.rows[0]);
    } catch (err) {
      next(err);
    }
  });

  // Create — publishes ProductCreated event for AI service to consume
  router.post('/', async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { name, description, price, stock, category } = req.body as {
        name?: string;
        description?: string;
        price?: number;
        stock?: number;
        category?: string;
      };

      if (!name || price === undefined) {
        throw new ValidationError('name and price are required');
      }
      if (price < 0) throw new ValidationError('price must be non-negative');

      const result = await pool.query(
        `INSERT INTO products (name, description, price, stock, category)
         VALUES ($1, $2, $3, $4, $5)
         RETURNING id, name, description, price, stock, category, created_at`,
        [name, description || '', price, stock || 0, category || 'general']
      );
      const product = result.rows[0];

      // Publish event so AI service can generate an embedding
      producer
        .publish({
          topic: 'ProductCreated',
          key: String(product.id),
          value: {
            product_id: product.id,
            name: product.name,
            description: product.description,
            price: Number(product.price),
            category: product.category,
          },
        })
        .catch((err: Error) => log.error({ err }, 'Failed to publish ProductCreated'));

      log.info({ product_id: product.id }, 'Product created');
      res.status(201).json(product);
    } catch (err) {
      next(err);
    }
  });

  return router;
}
