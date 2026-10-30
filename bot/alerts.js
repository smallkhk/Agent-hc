// Posts worker alerts to the guild's alert channel and handles the admin buttons.
import path from 'node:path';
import { access, stat } from 'node:fs/promises';
import {
  ActionRowBuilder,
  AttachmentBuilder,
  ButtonBuilder,
  ButtonStyle,
  EmbedBuilder,
  MessageFlags,
} from 'discord.js';
import { config } from '../api/config.js';
import {
  alertMessageRef,
  CLIPS_CHANNEL,
  EVENTS_CHANNEL,
  mute,
  rememberAlertMessage,
  subscribe,
} from '../api/lib/bus.js';
import { getEvent, resolveEvent } from '../api/lib/events.js';
import { getGuildConfig } from '../api/lib/guildConfig.js';
import { COLORS } from './embeds.js';

const IGNORE_SEC = 600;
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // Discord's limit for bots in unboosted servers

export const RULE_TEXT = {
  SCREEN_CUT_OFF: 'Screen partly out of frame',
  SCREEN_TOO_SMALL: 'Screen too small (camera too far)',
  SCREEN_NOT_FOUND: 'Screen not visible',
  SCREEN_DARK: 'Screen off or too dark',
  GLARE: 'Glare hides the screen',
  FEED_FROZEN: 'Camera feed frozen',
  STREAM_DROPPED: 'Hand cam disconnected',
  FEED_LOOPED: 'Feed looped / replayed',
  SCENE_CHANGED: 'Camera scene changed',
  mod_menu: 'Mod menu on screen',
  esp_overlay: 'ESP overlay on screen',
  unknown_overlay: 'Unknown overlay on screen',
};

const ACTIONS = {
  confirm: { action: 'confirmed', text: '✅ Confirmed' },
  fp: { action: 'false_positive', text: '👍 False positive' },
  ignore: { action: 'ignored', text: '🔕 Ignored for 10 min' },
};

async function storedFile(rel) {
  if (!rel) return null;
  const root = path.resolve(config.STORAGE_DIR);
  const full = path.resolve(root, rel);
  if (!full.startsWith(root + path.sep)) return null;
  return access(full).then(() => full, () => null);
}

export async function alertMessage(e) {
  const violation = e.severity === 'violation';
  const ts = Math.floor(new Date(e.ts).getTime() / 1000);
  const embed = new EmbedBuilder()
    .setColor(violation ? COLORS.bad : COLORS.warn)
    .setTitle(`${violation ? '❌ Violation' : '⚠️ Warning'}: ${RULE_TEXT[e.type] ?? e.type}`)
    .addFields(
      { name: 'Player', value: `<@${e.discordUserId}>`, inline: true },
      { name: 'Match', value: e.matchLabel || '—', inline: true },
      { name: 'When', value: `<t:${ts}:T> (<t:${ts}:R>)`, inline: true },
    )
    .setFooter({ text: `${e.type} · event ${e.id} · session ${e.sessionId}` });

  const files = [];
  const frame = await storedFile(e.framePath);
  if (frame) {
    files.push(new AttachmentBuilder(frame, { name: 'frame.jpg' }));
    embed.setImage('attachment://frame.jpg');
  }
  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(`hc:confirm:${e.id}`).setLabel('Confirm').setStyle(ButtonStyle.Danger),
    new ButtonBuilder().setCustomId(`hc:fp:${e.id}`).setLabel('False positive').setStyle(ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId(`hc:ignore:${e.id}`).setLabel('Ignore 10m').setStyle(ButtonStyle.Secondary),
  );
  return { embeds: [embed], components: [row], files, allowedMentions: { parse: [] } };
}

async function postAlert(client, eventId) {
  const e = await getEvent(eventId);
  if (!e) return;
  const { alertChannelId } = await getGuildConfig(e.discordGuildId);
  if (!alertChannelId) return;
  const channel = await client.channels.fetch(alertChannelId);
  const message = await channel?.send(await alertMessage(e));
  if (message) await rememberAlertMessage(e.id, channel.id, message.id);
}

// The 20 s clip is cut ~13 s after the alert; it goes in as a reply so the alert isn't held back.
async function postClip(client, eventId) {
  const e = await getEvent(eventId);
  const ref = e && (await alertMessageRef(e.id));
  const clip = ref && (await storedFile(e.clipPath));
  if (!clip) return;
  const channel = await client.channels.fetch(ref.channelId);
  const alert = await channel?.messages.fetch(ref.messageId).catch(() => null);
  if (!alert) return;
  const { size } = await stat(clip);
  if (size > MAX_UPLOAD_BYTES) {
    await alert.reply({ content: `🎬 Clip saved (${(size / 1e6).toFixed(1)} MB, too big for Discord): \`${e.clipPath}\`` });
    return;
  }
  await alert.reply({
    content: '🎬 20 s clip (10 s before, 10 s after)',
    files: [new AttachmentBuilder(clip, { name: `event-${e.id}.mp4` })],
    allowedMentions: { parse: [] },
  });
}

export async function startAlerts(client) {
  const handle = (what, fn) => async ({ eventId }) => {
    try {
      await fn(client, eventId);
    } catch (err) {
      console.error(`${what} for event ${eventId} failed:`, err.message);
    }
  };
  await subscribe(EVENTS_CHANNEL, handle('alert', postAlert));
  await subscribe(CLIPS_CHANNEL, handle('clip', postClip));
}

// customId: hc:<confirm|fp|ignore>:<eventId>. isAdmin is the same check as admin commands.
export async function handleAlertButton(interaction, isAdmin) {
  const [, key, id] = interaction.customId.split(':');
  const choice = ACTIONS[key];
  const eventId = Number(id);
  if (!choice || !Number.isInteger(eventId)) return;
  if (!(await isAdmin(interaction))) {
    return interaction.reply({ content: 'Only admins can resolve alerts.', flags: MessageFlags.Ephemeral });
  }
  const e = await getEvent(eventId);
  if (!e || e.discordGuildId !== interaction.guildId) return;

  if (!(await resolveEvent(eventId, choice.action, interaction.user.id))) {
    const done = await getEvent(eventId);
    return interaction.reply({
      content: `Already resolved (${done.adminAction}) by <@${done.adminId}>.`,
      flags: MessageFlags.Ephemeral,
      allowedMentions: { parse: [] },
    });
  }
  if (choice.action === 'ignored') await mute(e.sessionId, e.type, IGNORE_SEC);

  const embed = EmbedBuilder.from(interaction.message.embeds[0])
    .setColor(choice.action === 'confirmed' ? COLORS.bad : COLORS.idle)
    .addFields({ name: 'Resolved', value: `${choice.text} by <@${interaction.user.id}>` });
  await interaction.update({ embeds: [embed], components: [], allowedMentions: { parse: [] } });
}
