import { Client, Events, GatewayIntentBits } from 'discord.js';
import { botConfig } from './config.js';
import { handleInteraction } from './handlers.js';
import { startAlerts } from './alerts.js';
import { startNotifier } from './notify.js';

const intents = [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates];
if (botConfig.membersIntent) intents.push(GatewayIntentBits.GuildMembers);

const client = new Client({ intents });

client.once(Events.ClientReady, async (c) => {
  console.log(`bot ready as ${c.user.tag} in ${c.guilds.cache.size} server(s)`);
  await startNotifier(c);
  await startAlerts(c);
});
client.on(Events.InteractionCreate, handleInteraction);

await client.login(botConfig.DISCORD_TOKEN);
