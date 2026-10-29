import { Router } from 'express';
import { z } from 'zod';
import { config } from '../config.js';
import { playerToken } from '../lib/livekit.js';
import { addDataUsed, authDevice, CamLinkError, redeemCamLink } from '../lib/sessions.js';

export const camRouter = Router();

const token = z.string().regex(/^[A-Za-z0-9_-]{43}$/);
const redeemBody = z.object({ token });
const statsBody = z.object({
  token,
  // delta since the last report; capped so a client can't inflate the counter
  bytesSent: z.number().int().nonnegative().max(200_000_000),
});

const cookieName = (sessionId) => `hc_dev_${sessionId}`;
// A browser may hold cookies from several sessions; each is tried against the link.
const deviceSecrets = (req) =>
  Object.entries(req.cookies)
    .filter(([k]) => k.startsWith('hc_dev_'))
    .map(([, v]) => v);

const linkErrors = {
  invalid: [404, 'This cam link is not valid.'],
  expired: [410, 'This cam link has expired. Ask an admin for a new one.'],
  used: [409, 'This cam link was already opened on another device.'],
  ended: [410, 'This hand cam session has ended.'],
};

// POST /api/cam/redeem — cam link token → LiveKit publish token
camRouter.post('/redeem', async (req, res, next) => {
  const body = redeemBody.safeParse(req.body);
  if (!body.success) return res.status(400).json({ error: 'Bad request.' });

  try {
    const secrets = deviceSecrets(req);
    let result;
    for (const secret of secrets.length ? secrets : [undefined]) {
      try {
        result = await redeemCamLink(body.data.token, secret);
        break;
      } catch (err) {
        if (!(err instanceof CamLinkError) || err.code !== 'used') throw err;
      }
    }
    if (!result) throw new CamLinkError('used');

    if (result.newDeviceSecret) {
      res.cookie(cookieName(result.sessionId), result.newDeviceSecret, {
        httpOnly: true,
        secure: config.secureCookies,
        sameSite: 'strict',
        path: '/api/cam',
        maxAge: 24 * 60 * 60 * 1000,
      });
    }
    res.json({
      sessionId: result.sessionId,
      matchLabel: result.matchLabel,
      livekitUrl: config.LIVEKIT_URL,
      livekitToken: await playerToken(result.sessionId),
      defaultRes: config.DEFAULT_CAM_RES,
    });
  } catch (err) {
    if (err instanceof CamLinkError) {
      const [status, message] = linkErrors[err.code];
      return res.status(status).json({ error: message, code: err.code });
    }
    next(err);
  }
});

// POST /api/cam/stats — data used by the cam device
camRouter.post('/stats', async (req, res, next) => {
  const body = statsBody.safeParse(req.body);
  if (!body.success) return res.status(400).json({ error: 'Bad request.' });
  try {
    let sessionId = null;
    for (const secret of deviceSecrets(req)) {
      if ((sessionId = await authDevice(body.data.token, secret))) break;
    }
    if (!sessionId) return res.status(403).json({ error: 'Forbidden.' });
    await addDataUsed(sessionId, body.data.bytesSent);
    res.status(204).end();
  } catch (err) {
    next(err);
  }
});
