import mysql from 'mysql2/promise';
import { config } from './config.js';

export const pool = mysql.createPool({ uri: config.MYSQL_URL, connectionLimit: 10, timezone: 'Z' });

// Every timestamp is UTC: FROM_UNIXTIME/NOW() follow the session time zone, not the server's.
pool.pool.on('connection', (conn) => conn.query("SET time_zone = '+00:00'"));
