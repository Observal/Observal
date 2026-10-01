// SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
// SPDX-License-Identifier: Apache-2.0

/**
 * Observal's in-process DeepSeek Harness plugin. DeepSeek's command-hook shell
 * cannot see the host's session files; run the collector from the Cordis host
 * only after the session store's awaited durability barrier has completed.
 *
 * This file is dependency-free so the Observal CLI can install it into DSH_HOME
 * without downloading a plugin package or changing DeepSeek Harness itself.
 */
import { execFile } from 'node:child_process';

export const name = 'observal-session-collector';
export const inject = ['sessions', 'sessionPersistence'];

function collect(config, args) {
  return new Promise((resolve, reject) => {
    execFile(
      config.pythonPath,
      ['-m', 'observal_cli.sessions.deepseek_collector', ...args],
      {
        env: { ...process.env, DSH_HOME: config.dshHome },
        timeout: 15_000,
        maxBuffer: 128 * 1024,
      },
      (error) => error ? reject(error) : resolve(),
    );
  });
}

export function apply(ctx, config) {
  if (!config || typeof config.pythonPath !== 'string' || typeof config.dshHome !== 'string') {
    throw new Error('Observal collector requires pythonPath and dshHome');
  }

  const pending = new Map();
  function enqueue(session) {
    const id = session.id;
    const previous = pending.get(id) ?? Promise.resolve();
    const task = previous.then(async () => {
      // session/event only signals an in-memory append. A completed flush is
      // necessary before a separate Python process can read the v4 JSONL.
      const persisted = await ctx.sessions.flush(session);
      if (!persisted) throw new Error('no session persistence listener accepted the flush');
      await collect(config, ['--session-id', id, '--cwd', session.header.cwd ?? '']);
    }).catch((error) => {
      // Never interrupt the model; the Python collector retains its own outbox
      // and the next startup/manual reconcile can recover missed records.
      ctx.logger.warn(`observal: session ${id} collection failed: ${String(error)}`);
    });
    pending.set(id, task);
    void task.finally(() => { if (pending.get(id) === task) pending.delete(id); });
  }

  ctx.on('session/event', (session, event) => {
    if (event.type === 'turn/end') enqueue(session);
  });

  // A crash or offline server must not permanently strand earlier sessions.
  // Recovery is detached from startup so it cannot delay DeepSeek boot.
  void collect(config, ['--recover']).catch((error) => {
    ctx.logger.warn(`observal: session recovery failed: ${String(error)}`);
  });

  ctx.effect(() => async () => {
    await Promise.allSettled([...pending.values()]);
  });
}
