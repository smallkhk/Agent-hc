// Registers /handcam with Discord. Run after changing bot/commands.js: npm run bot:deploy
import { REST, Routes } from 'discord.js';
import { botConfig } from './config.js';
import { handcamCommand } from './commands.js';

const rest = new REST().setToken(botConfig.DISCORD_TOKEN);
const route = botConfig.DISCORD_DEV_GUILD_ID
  ? Routes.applicationGuildCommands(botConfig.DISCORD_CLIENT_ID, botConfig.DISCORD_DEV_GUILD_ID)
  : Routes.applicationCommands(botConfig.DISCORD_CLIENT_ID);

await rest.put(route, { body: [handcamCommand.toJSON()] });
console.log(`registered /handcam ${botConfig.DISCORD_DEV_GUILD_ID ? 'in the dev server' : 'globally'}`);
