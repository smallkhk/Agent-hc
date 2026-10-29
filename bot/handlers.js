import { EmbedBuilder, MessageFlags, PermissionFlagsBits } from 'discord.js';
import { config } from '../api/config.js';
import { ConfigError, getGuildConfig, THRESHOLDS, updateGuildConfig } from '../api/lib/guildConfig.js';
import {
  activeSession,
  activeSessionsByMatch,
  createSession,
  endSession,
  reissueCamLink,
  sessionEventCounts,
} from '../api/lib/sessions.js';
import { handleAlertButton } from './alerts.js';
import { camLinkMessage, COLORS, formatDuration, statusEmbed } from './embeds.js';

const LOBBY_MAX = 50;
const ephemeral = { flags: MessageFlags.Ephemeral };
const noPings = { allowedMentions: { parse: [] } };

class UserError extends Error {}

function isAdmin(interaction, cfg) {
  if (interaction.memberPermissions?.has(PermissionFlagsBits.ManageGuild)) return true;
  if (!cfg.adminRoleId) return false;
  const roles = interaction.member?.roles;
  return Array.isArray(roles) ? roles.includes(cfg.adminRoleId) : Boolean(roles?.cache?.has(cfg.adminRoleId));
}

async function requireAdmin(interaction) {
  const cfg = await getGuildConfig(interaction.guildId);
  if (!isAdmin(interaction, cfg)) throw new UserError('Only admins can do that (Manage Server or the hand cam admin role).');
  return cfg;
}

// Creates a session (or a fresh link for one never opened) and DMs the player.
// Returns { state: 'started' | 'reissued' | 'live', dmOk }.
async function startFor(guild, user, matchLabel) {
  const existing = await activeSession(guild.id, user.id);
  if (existing && existing.status !== 'pending') return { state: 'live', dmOk: true };

  let camUrl = existing && (await reissueCamLink(existing.id));
  const state = camUrl ? 'reissued' : 'started';
  if (!camUrl) {
    ({ camUrl } = await createSession({ discordGuildId: guild.id, discordUserId: user.id, matchLabel }));
  }
  const message = camLinkMessage({
    guildName: guild.name,
    matchLabel: existing?.matchLabel ?? matchLabel,
    camUrl,
    ttlMin: config.CAM_LINK_TTL_MIN,
  });
  const dmOk = await user.send(message).then(
    () => true,
    () => false, // DMs closed; the player can still get the link with /handcam join
  );
  return { state, dmOk };
}

async function start(interaction) {
  await requireAdmin(interaction);
  const user = interaction.options.getUser('player', true);
  if (user.bot) throw new UserError('Bots can’t run a hand cam.');
  const { state, dmOk } = await startFor(interaction.guild, user, interaction.options.getString('match'));

  const text = {
    live: `<@${user.id}>’s hand cam is already live. Use \`/handcam status\` to check it.`,
    started: `Hand cam session started for <@${user.id}>.`,
    reissued: `<@${user.id}> hadn’t opened their link yet, so they got a fresh one.`,
  }[state];
  const dmNote =
    state === 'live' ? '' : dmOk ? ' Cam link sent by DM.' : ' ⚠️ Their DMs are closed: ask them to run `/handcam join`.';
  await interaction.reply({ content: text + dmNote, ...ephemeral, ...noPings });
}

async function join(interaction) {
  const existing = await activeSession(interaction.guildId, interaction.user.id);
  if (existing && existing.status !== 'pending') {
    throw new UserError(
      'Your hand cam is already live on another device. To switch devices, ask an admin to `/handcam stop` and start you again.',
    );
  }
  let camUrl = existing && (await reissueCamLink(existing.id));
  if (!camUrl) {
    const cfg = await getGuildConfig(interaction.guildId);
    if (!cfg.selfJoin) throw new UserError('Self-start is off on this server. Ask an admin to start your hand cam.');
    ({ camUrl } = await createSession({ discordGuildId: interaction.guildId, discordUserId: interaction.user.id }));
  }
  await interaction.reply({
    ...camLinkMessage({
      guildName: interaction.guild.name,
      matchLabel: existing?.matchLabel,
      camUrl,
      ttlMin: config.CAM_LINK_TTL_MIN,
    }),
    ...ephemeral,
  });
}

async function status(interaction) {
  const user = interaction.options.getUser('player') ?? interaction.user;
  const session = await activeSession(interaction.guildId, user.id);
  const counts = session ? await sessionEventCounts(session.id) : null;
  await interaction.reply({ embeds: [statusEmbed(user.id, session, counts)], ...noPings });
}

async function stop(interaction) {
  await requireAdmin(interaction);
  const user = interaction.options.getUser('player', true);
  const session = await activeSession(interaction.guildId, user.id);
  if (!session || !(await endSession(session))) throw new UserError(`<@${user.id}> has no active hand cam.`);
  const uptime = session.startedAt ? ` after ${formatDuration((Date.now() - new Date(session.startedAt)) / 1000)}` : '';
  await interaction.reply({ content: `Ended <@${user.id}>’s hand cam${uptime}.`, ...ephemeral, ...noPings });
}

// Members of the lobby: a voice channel (option, or the admin's current one) or a role.
async function lobbyMembers(interaction, { required }) {
  const role = interaction.options.getRole('role');
  if (role) {
    try {
      await interaction.guild.members.fetch();
    } catch {
      throw new UserError('Role lobbies need the **Server Members Intent** (Developer Portal → Bot), then set `DISCORD_MEMBERS_INTENT=true`.');
    }
    const fresh = interaction.guild.roles.cache.get(role.id);
    return { label: role.name, members: [...(fresh?.members.values() ?? [])] };
  }
  const channel =
    interaction.options.getChannel('channel') ?? interaction.guild.members.cache.get(interaction.user.id)?.voice.channel;
  if (!channel) {
    if (!required) return { label: null, members: [] };
    throw new UserError('Pick a voice `channel` or `role`, or join the lobby voice channel first.');
  }
  const voice = interaction.guild.channels.cache.get(channel.id) ?? channel;
  return { label: voice.name, members: [...(voice.members?.values() ?? [])] };
}

const mentionList = (ids) => ids.map((id) => `<@${id}>`).join(', ');

async function lobbyStart(interaction) {
  await requireAdmin(interaction);
  await interaction.deferReply(ephemeral); // member fetch + one DM per player can exceed 3s
  const { label, members } = await lobbyMembers(interaction, { required: true });
  const players = members.filter((m) => !m.user.bot);
  if (!players.length) throw new UserError('Nobody is in that lobby.');
  if (players.length > LOBBY_MAX) throw new UserError(`That lobby has ${players.length} members; the limit is ${LOBBY_MAX}.`);

  const match = interaction.options.getString('match') ?? label;
  const out = { started: [], reissued: [], live: [], noDm: [] };
  for (const m of players) {
    const { state, dmOk } = await startFor(interaction.guild, m.user, match);
    out[state].push(m.id);
    if (!dmOk) out.noDm.push(m.id);
  }
  const lines = [
    `**${match}**: ${players.length} players`,
    out.started.length && `▶️ Started: ${mentionList(out.started)}`,
    out.reissued.length && `🔁 New link (hadn’t opened theirs): ${mentionList(out.reissued)}`,
    out.live.length && `✅ Already live: ${mentionList(out.live)}`,
    out.noDm.length && `⚠️ DMs closed, ask them to run \`/handcam join\`: ${mentionList(out.noDm)}`,
  ].filter(Boolean);
  await interaction.editReply({ content: lines.join('\n'), ...noPings });
}

async function lobbyStop(interaction) {
  await requireAdmin(interaction);
  await interaction.deferReply(ephemeral);
  const match = interaction.options.getString('match');
  const { members } = await lobbyMembers(interaction, { required: !match });

  const sessions = new Map();
  if (match) for (const s of await activeSessionsByMatch(interaction.guildId, match)) sessions.set(s.id, s);
  for (const m of members) {
    const s = await activeSession(interaction.guildId, m.id);
    if (s) sessions.set(s.id, s);
  }
  if (!sessions.size) throw new UserError('No active hand cams in that lobby.');

  const ended = [];
  for (const s of sessions.values()) if (await endSession(s)) ended.push(s.discordUserId);
  await interaction.editReply({ content: `⏹️ Ended ${ended.length} hand cam(s): ${mentionList(ended)}`, ...noPings });
}

const CONFIG_OPTIONS = {
  grace_sec: 'graceSec',
  violation_sec: 'violationSec',
  freeze_sec: 'freezeSec',
  drop_sec: 'dropSec',
  menu_threshold: 'menuThreshold',
};

function configEmbed(cfg) {
  const t = (k) => `${cfg[k]}${THRESHOLDS[k].int ? 's' : ''}`;
  return new EmbedBuilder()
    .setColor(COLORS.idle)
    .setTitle('Hand cam settings')
    .addFields(
      { name: 'Alert channel', value: cfg.alertChannelId ? `<#${cfg.alertChannelId}>` : 'not set', inline: true },
      { name: 'Admin role', value: cfg.adminRoleId ? `<@&${cfg.adminRoleId}>` : 'Manage Server only', inline: true },
      { name: 'Self join', value: cfg.selfJoin ? 'on' : 'off', inline: true },
      { name: 'Screen warning / violation', value: `${t('graceSec')} / ${t('violationSec')}`, inline: true },
      { name: 'Freeze / drop', value: `${t('freezeSec')} / ${t('dropSec')}`, inline: true },
      { name: 'Menu threshold', value: String(cfg.menuThreshold), inline: true },
    );
}

async function configure(interaction) {
  await requireAdmin(interaction);
  const o = interaction.options;
  const patch = {
    alertChannelId: o.getChannel('alert_channel')?.id,
    adminRoleId: o.getRole('admin_role')?.id,
    selfJoin: o.getBoolean('self_join') ?? undefined,
    ...Object.fromEntries(Object.entries(CONFIG_OPTIONS).map(([opt, key]) => [key, o.get(opt)?.value])),
  };
  const changed = Object.values(patch).some((v) => v !== undefined);
  let cfg;
  try {
    cfg = changed ? await updateGuildConfig(interaction.guildId, patch) : await getGuildConfig(interaction.guildId);
  } catch (err) {
    if (err instanceof ConfigError) throw new UserError(err.message);
    throw err;
  }
  await interaction.reply({ content: changed ? 'Saved.' : undefined, embeds: [configEmbed(cfg)], ...ephemeral });
}

const routes = {
  start,
  join,
  status,
  stop,
  config: configure,
  'lobby start': lobbyStart,
  'lobby stop': lobbyStop,
};

const isGuildAdmin = async (interaction) => isAdmin(interaction, await getGuildConfig(interaction.guildId));

export async function handleInteraction(interaction) {
  if (interaction.isButton() && interaction.customId.startsWith('hc:')) {
    return handleAlertButton(interaction, isGuildAdmin).catch((err) => {
      console.error(`alert button ${interaction.customId} failed:`, err.stack);
      return interaction.reply({ content: 'Something went wrong.', ...ephemeral }).catch(() => {});
    });
  }
  if (!interaction.isChatInputCommand() || interaction.commandName !== 'handcam') return;
  const group = interaction.options.getSubcommandGroup(false);
  const sub = interaction.options.getSubcommand();
  const handler = routes[group ? `${group} ${sub}` : sub];
  try {
    await handler(interaction);
  } catch (err) {
    const content = err instanceof UserError ? err.message : 'Something went wrong. Try again in a moment.';
    if (!(err instanceof UserError)) console.error(`/handcam ${group ?? ''} ${sub} failed:`, err.stack);
    const reply = { content, ...ephemeral, ...noPings };
    await (interaction.deferred || interaction.replied ? interaction.editReply(reply) : interaction.reply(reply)).catch(
      () => {},
    );
  }
}
