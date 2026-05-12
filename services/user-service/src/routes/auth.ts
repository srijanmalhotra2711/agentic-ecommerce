import { Router, Request, Response, NextFunction } from 'express';
import bcrypt from 'bcryptjs';
import jwt from 'jsonwebtoken';
import {
  ValidationError,
  ConflictError,
  UnauthorizedError,
  withCorrelation,
} from '@agentic-commerce/common';
import type { Logger } from 'pino';
import { pool } from '../db';
import env from '../config';
import type { ProducerHandle } from '@agentic-commerce/common';

export function createAuthRouter({ logger, producer }: { logger: Logger; producer: ProducerHandle }) {
  const router = Router();
  const log = withCorrelation(logger);

  router.post('/register', async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { email, password, name } = req.body as { email?: string; password?: string; name?: string };
      if (!email || !password || !name) {
        throw new ValidationError('email, password, and name are required');
      }
      if (password.length < 8) {
        throw new ValidationError('password must be at least 8 characters');
      }

      const existing = await pool.query('SELECT id FROM users WHERE email = $1', [email]);
      if (existing.rows.length > 0) {
        throw new ConflictError('email already registered');
      }

      const hash = await bcrypt.hash(password, 10);
      const result = await pool.query(
        `INSERT INTO users (email, password_hash, name) VALUES ($1, $2, $3)
         RETURNING id, email, name, created_at`,
        [email, hash, name]
      );
      const user = result.rows[0];

      // Fire-and-forget event — for portfolio simplicity we don't use outbox here
      // (the order-service demonstrates the outbox pattern instead)
      producer
        .publish({
          topic: 'UserRegistered',
          key: String(user.id),
          value: { user_id: user.id, email: user.email, name: user.name },
        })
        .catch((err: Error) => log.error({ err }, 'Failed to publish UserRegistered'));

      log.info({ user_id: user.id }, 'User registered');
      res.status(201).json(user);
    } catch (err) {
      next(err);
    }
  });

  router.post('/login', async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { email, password } = req.body as { email?: string; password?: string };
      if (!email || !password) {
        throw new ValidationError('email and password are required');
      }

      const result = await pool.query('SELECT id, email, name, password_hash FROM users WHERE email = $1', [email]);
      if (result.rows.length === 0) {
        throw new UnauthorizedError('invalid credentials');
      }
      const user = result.rows[0];

      const ok = await bcrypt.compare(password, user.password_hash);
      if (!ok) {
        throw new UnauthorizedError('invalid credentials');
      }

      const token = jwt.sign({ user_id: user.id, email: user.email }, env.JWT_SECRET, {
        expiresIn: '24h',
      });

      log.info({ user_id: user.id }, 'User logged in');
      res.json({ token, user: { id: user.id, email: user.email, name: user.name } });
    } catch (err) {
      next(err);
    }
  });

  return router;
}
