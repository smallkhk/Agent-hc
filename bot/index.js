import { Client, Events, GatewayIntentBits } from 'discord.js';
import { botConfig } from './config.js';
import { handleInteraction } from './handlers.js';
import { startAlerts } from './alerts.js';
import { startNotifier } from './notify.js';
import { ensureGuild } from '../api/lib/sessions.js';

const intents = [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates];
if (botConfig.membersIntent) intents.push(GatewayIntentBits.GuildMembers);

const client = new Client({ intents });

client.once(Events.ClientReady, async (c) => {
  console.log(`bot ready as ${c.user.tag} in ${c.guilds.cache.size} server(s)`);
  // Register every server the bot is in, so its admins can log in to the dashboard straight away.
  for (const id of c.guilds.cache.keys()) await ensureGuild(id).catch((err) => console.error('register server', id, err));
  await startNotifier(c);
  await startAlerts(c);
});
client.on(Events.InteractionCreate, handleInteraction);
client.on(Events.GuildCreate, (g) => ensureGuild(g.id).catch((err) => console.error('register server', g.id, err)));

await client.login(botConfig.DISCORD_TOKEN);
