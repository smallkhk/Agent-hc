import mysql from 'mysql2/promise';
import { config } from './config.js';

export const pool = mysql.createPool({ uri: config.MYSQL_URL, connectionLimit: 10, timezone: 'Z' });
