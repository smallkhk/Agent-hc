// Applies db/schema.sql (idempotent), then any db/migrations/*.sql not yet applied.
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import mysql from 'mysql2/promise';

const dir = path.dirname(new URL(import.meta.url).pathname);
const conn = await mysql.createConnection({ uri: process.env.MYSQL_URL, multipleStatements: true });

try {
  await conn.query(await readFile(path.join(dir, 'schema.sql'), 'utf8'));
  await conn.query(`CREATE TABLE IF NOT EXISTS schema_migrations (
    name VARCHAR(255) PRIMARY KEY,
    applied_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
  ) ENGINE=InnoDB`);

  const [rows] = await conn.query('SELECT name FROM schema_migrations');
  const applied = new Set(rows.map((r) => r.name));
  const files = (await readdir(path.join(dir, 'migrations'))).filter((f) => f.endsWith('.sql')).sort();

  for (const file of files) {
    if (applied.has(file)) continue;
    await conn.query(await readFile(path.join(dir, 'migrations', file), 'utf8'));
    await conn.query('INSERT INTO schema_migrations (name) VALUES (?)', [file]);
    console.log(`applied ${file}`);
  }
  console.log('schema up to date');
} finally {
  await conn.end();
}
