import { ActionRowBuilder, ButtonBuilder, ButtonStyle, EmbedBuilder } from 'discord.js';

export const COLORS = { ok: 0x22c55e, warn: 0xf59e0b, bad: 0xef4444, idle: 0x64748b };

export function formatDuration(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m ${Math.floor(sec % 60)}s`;
}

const formatBytes = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`);

// ✅ / ⚠️ / ❌ badge from session state + unresolved events.
export function badge(session, counts) {
  if (!session) return { emoji: '➖', label: 'No hand cam', color: COLORS.idle };
  if (session.status === 'pending') return { emoji: '⏳', label: 'Waiting for cam', color: COLORS.idle };
  if (counts.openViolations) return { emoji: '❌', label: 'Violation', color: COLORS.bad };
  if (session.status === 'stale') return { emoji: '⚠️', label: 'Not being checked', color: COLORS.warn };
  if (counts.openWarnings) return { emoji: '⚠️', label: 'Warning', color: COLORS.warn };
  return { emoji: '✅', label: 'OK', color: COLORS.ok };
}

export function statusEmbed(userId, session, counts) {
  const b = badge(session, counts);
  const embed = new EmbedBuilder()
    .setColor(b.color)
    .setTitle(`${b.emoji} ${b.label}`)
    .setDescription(`Hand cam for <@${userId}>`);
  if (!session) return embed;

  const elapsed = session.startedAt ? (Date.now() - new Date(session.startedAt).getTime()) / 1000 : 0;
  // Share of the session with frames reaching the vision worker.
  const camUptime = elapsed > 60 ? `${Math.min(100, Math.round((100 * Number(session.uptimeSec)) / elapsed))}%` : '—';
  embed.addFields(
    { name: 'Live for', value: session.startedAt ? formatDuration(elapsed) : '—', inline: true },
    { name: 'Cam uptime', value: camUptime, inline: true },
    { name: 'Match', value: session.matchLabel || '—', inline: true },
    { name: 'Data used', value: formatBytes(Number(session.dataBytes || 0)), inline: true },
    { name: 'Warnings', value: String(counts.warnings), inline: true },
    { name: 'Violations', value: String(counts.violations), inline: true },
  );
  if (session.startedAt) embed.setTimestamp(new Date(session.startedAt)).setFooter({ text: 'Started' });
  return embed;
}

// Cam link message. The link is the button; it is never shown as plain text in a channel.
export function camLinkMessage({ guildName, matchLabel, camUrl, ttlMin }) {
  const embed = new EmbedBuilder()
    .setColor(COLORS.ok)
    .setTitle('📹 Start your hand cam')
    .setDescription(
      [
        `**${guildName}**${matchLabel ? ` · ${matchLabel}` : ''} needs your hand cam.`,
        '',
        '1. Open the link on a **second device** (another phone, tablet or laptop webcam).',
        '2. Point it at the phone or iPad you play on so the **whole screen** fits in the box.',
        '3. Keep that page open and the device plugged in while you play.',
        '',
        `The link works on **one device** and expires in ${ttlMin} min if not opened. Don't share it.`,
      ].join('\n'),
    );
  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setStyle(ButtonStyle.Link).setLabel('Open hand cam').setURL(camUrl),
  );
  return { embeds: [embed], components: [row] };
}
