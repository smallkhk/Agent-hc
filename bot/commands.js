import { ChannelType, InteractionContextType, SlashCommandBuilder } from 'discord.js';
import { THRESHOLDS } from '../api/lib/thresholds.js';

const lobbyTargets = (sub) =>
  sub
    .addChannelOption((o) =>
      o
        .setName('channel')
        .setDescription('Voice channel of the lobby (default: the one you are in)')
        .addChannelTypes(ChannelType.GuildVoice, ChannelType.GuildStageVoice),
    )
    .addRoleOption((o) => o.setName('role').setDescription('Everyone with this role instead of a voice channel'));

export const handcamCommand = new SlashCommandBuilder()
  .setName('handcam')
  .setDescription('Hand cam monitoring')
  .setContexts(InteractionContextType.Guild)
  .addSubcommand((s) =>
    s
      .setName('start')
      .setDescription('Admin: start a hand cam session and DM the player a cam link')
      .addUserOption((o) => o.setName('player').setDescription('Player').setRequired(true))
      .addStringOption((o) => o.setName('match').setDescription('Match / lobby label').setMaxLength(100)),
  )
  .addSubcommand((s) => s.setName('join').setDescription('Get your cam link (start your own hand cam)'))
  .addSubcommand((s) =>
    s
      .setName('status')
      .setDescription('Hand cam status of a player')
      .addUserOption((o) => o.setName('player').setDescription('Player (default: you)')),
  )
  .addSubcommand((s) =>
    s
      .setName('stop')
      .setDescription('Admin: end a player’s hand cam session')
      .addUserOption((o) => o.setName('player').setDescription('Player').setRequired(true)),
  )
  .addSubcommandGroup((g) =>
    g
      .setName('lobby')
      .setDescription('Admin: hand cams for a whole lobby')
      .addSubcommand((s) =>
        lobbyTargets(s.setName('start').setDescription('Start sessions for everyone in a lobby')).addStringOption(
          (o) => o.setName('match').setDescription('Match label (default: channel or role name)').setMaxLength(100),
        ),
      )
      .addSubcommand((s) =>
        lobbyTargets(s.setName('stop').setDescription('End sessions for a lobby')).addStringOption((o) =>
          o.setName('match').setDescription('End every session with this match label'),
        ),
      ),
  )
  .addSubcommand((s) => {
    s.setName('config')
      .setDescription('Admin: alert channel and thresholds (no options = show current)')
      .addChannelOption((o) =>
        o
          .setName('alert_channel')
          .setDescription('Channel for alerts')
          .addChannelTypes(ChannelType.GuildText, ChannelType.GuildAnnouncement),
      )
      .addRoleOption((o) => o.setName('admin_role').setDescription('Role allowed to run admin commands'))
      .addBooleanOption((o) => o.setName('self_join').setDescription('Let players start their own hand cam with /handcam join'));
    const intOpt = (name, key, desc) =>
      s.addIntegerOption((o) =>
        o.setName(name).setDescription(desc).setMinValue(THRESHOLDS[key].min).setMaxValue(THRESHOLDS[key].max),
      );
    intOpt('grace_sec', 'graceSec', 'Seconds of screen problems before a warning');
    intOpt('violation_sec', 'violationSec', 'Seconds of screen problems before a violation');
    intOpt('freeze_sec', 'freezeSec', 'Seconds of frozen feed before FEED_FROZEN');
    intOpt('drop_sec', 'dropSec', 'Seconds disconnected before STREAM_DROPPED');
    s.addNumberOption((o) =>
      o
        .setName('menu_threshold')
        .setDescription('Hack-menu classifier confidence needed to flag (0.5–0.99)')
        .setMinValue(THRESHOLDS.menuThreshold.min)
        .setMaxValue(THRESHOLDS.menuThreshold.max),
    );
    return s;
  });
