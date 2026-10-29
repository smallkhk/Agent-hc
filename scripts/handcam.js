// Dev/admin CLI until the Discord bot lands (Phase 3).
//   npm run cli -- new --guild <discord guild id> --user <discord user id> [--match "Lobby 1"]
//   npm run cli -- watch --session <id>
import { parseArgs } from 'node:util';
import { config } from '../api/config.js';
import { pool } from '../api/db.js';
import { watchToken } from '../api/lib/livekit.js';
import { createSession } from '../api/lib/sessions.js';

const { positionals, values } = parseArgs({
  allowPositionals: true,
  options: {
    guild: { type: 'string' },
    user: { type: 'string' },
    match: { type: 'string' },
    session: { type: 'string' },
  },
});

try {
  switch (positionals[0]) {
    case 'new': {
      if (!values.guild || !values.user) throw new Error('new needs --guild and --user');
      const s = await createSession({
        discordGuildId: values.guild,
        discordUserId: values.user,
        matchLabel: values.match,
      });
      console.log(`session ${s.sessionId}`);
      console.log(`cam link (send to the player, valid ${config.CAM_LINK_TTL_MIN} min, one device): ${s.camUrl}`);
      console.log(`watch: npm run cli -- watch --session ${s.sessionId}`);
      break;
    }
    case 'watch': {
      const id = Number(values.session);
      if (!Number.isInteger(id)) throw new Error('watch needs --session <id>');
      const jwt = await watchToken(id);
      const fragment = new URLSearchParams({ url: config.LIVEKIT_URL, t: jwt });
      console.log(`watch link (1 h): ${config.PUBLIC_URL}/watch.html#${fragment}`);
      break;
    }
    default:
      throw new Error('usage: handcam.js new|watch ...');
  }
} catch (err) {
  console.error(err.message);
  process.exitCode = 1;
} finally {
  await pool.end();
}
