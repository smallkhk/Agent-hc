// PM2 process file. Run from repo root: pm2 start deploy/ecosystem.config.cjs
const path = require('node:path');

const root = path.resolve(__dirname, '..');

// Load .env once here so the Python worker gets the same env as the Node apps.
let env = {};
try {
  process.loadEnvFile(path.join(root, '.env'));
  env = { ...process.env };
} catch {
  // no .env: rely on the shell environment
}

const workers = Number(env.WORKERS ?? process.env.WORKERS ?? 1);

module.exports = {
  apps: [
    {
      name: 'handcam-api',
      cwd: root,
      script: 'api/server.js',
      env,
      max_memory_restart: '512M',
    },
    {
      name: 'handcam-bot',
      cwd: root,
      script: 'bot/index.js',
      env,
      max_memory_restart: '512M',
    },
    // One worker process per WORKERS (default 1); each takes the sessions with id % WORKERS == its index.
    ...Array.from({ length: workers }, (_, i) => ({
      name: workers > 1 ? `handcam-worker-${i}` : 'handcam-worker',
      cwd: root,
      script: '.venv/bin/python',
      args: '-m worker.main',
      interpreter: 'none',
      env: { ...env, WORKER_SHARD: `${i}/${workers}` },
      restart_delay: 2000,
      kill_timeout: 15000, // let FFmpeg close the current chunk cleanly
    })),
  ],
};
