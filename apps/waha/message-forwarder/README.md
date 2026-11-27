# WhatsApp messages on Apple Watch

WAHA sends signed `message` events to the in-cluster `waha-forwarder` service. The forwarder filters one WhatsApp session and posts approved messages to your configured webhook. The included [n8n workflow](../../n8n/workflows/waha-watch-forwarder.json) sends them to a private Telegram bot chat that you can read in [Pigeon](https://apps.apple.com/us/app/pigeon-for-telegram/id1671939892).

## Verify the Watch first

1. Create a dedicated bot with [@BotFather](https://core.telegram.org/bots/features#botfather). Open a private chat with the bot in Telegram and press **Start**. Log in to Pigeon with the same Telegram account, enable notifications, and leave the bot chat unmuted.
2. Use [`getUpdates`](https://core.telegram.org/bots/api#getupdates) to find your chat ID: use `message.chat.id` from your `/start` update and verify `message.chat.type` is `private`. Keep the bot token in n8n's **Telegram API** credential. Pigeon Free shows the latest [50 messages per chat](https://support.pigeonwatch.app/notes/pn002).
3. With the Watch worn, unlocked and connected to known Wi-Fi, fully power off the paired iPhone. Close Pigeon and send 12 test messages into the bot chat, including repeated text and one message after the Watch has been idle. Check that new arrivals give readable previews without opening Pigeon and that you can then reopen the chat to browse and read them. A bot send tests Watch delivery independently of WAHA and n8n.

## Configure n8n and Doppler

1. Import `waha-watch-forwarder.json` into n8n. In **Forwarded WhatsApp message**, set a **Header Auth** credential with name `X-WhatsApp-Forwarder-Token` and a random value. In **Send to private Telegram chat**, set the Telegram credential and the private chat ID. Publish the workflow.
2. Use the WAHA dashboard's **Event Monitor** to inspect new `message` events from consenting test chats. Use `payload.from` for each allowlist entry. Private IDs can be `@c.us` or `@lid`; use `@g.us` for group IDs. The forwarder also checks NOWEB's alternate user ID when available. A group entry admits messages from any member, independently of the private allowlist.
3. In the Doppler config behind `doppler-auth-api`, set `WAHA_FORWARDER_HMAC_KEY` to a random secret of at least 32 characters, and set `WAHA_FORWARDER_CONFIG` to JSON. For example, replacing all sample values:

   ```json
   {
     "session": "default",
     "webhookUrl": "http://n8n.n8n.svc.cluster.local:5678/webhook/waha-watch-forwarder",
     "webhookToken": "<same value as the n8n Header Auth credential>",
     "privateChats": {
       "15555550100@c.us": "Maya",
       "15555550101@lid": ""
     },
     "groupChats": {
       "120363000000000000@g.us": "Family"
     }
   }
   ```

   An empty label uses the sender's WhatsApp display name or ID for a DM, and the group ID for a group. Add group labels for readable group names on the Watch. `webhookToken` can be omitted for a different destination that doesn't need this header. Use HTTPS for destinations outside the cluster.

   To forward all new DMs and standalone groups, set `"forwardAllPrivateChats": true` and `"forwardAllStandaloneGroups": true`. Both default to `false`, so existing configurations keep their allowlist behavior. In standalone-group mode, `groupChats` provides optional display labels; it cannot override Community exclusions. WAHA supplies group names and Community membership. The forwarder refreshes that information on demand after 30 seconds, skips unclassified groups and groups with a known disappearing-message timer, and asks WAHA to retry group events if the lookup fails.

4. Deploy the manifests via Flux. Wait for `externalsecret/waha-forwarder-secrets` in `waha` to be Ready. The WAHA hook stays disabled until its secret exists and WAHA starts with it; if the pods started before the secret synced, restart `deployment/waha-forwarder` and then `deployment/waha` after the sync. Restart the forwarder after Doppler config changes; restart WAHA too when changing the signing key. If changing destinations, let the old queue drain first so multipart forwards aren't split between destinations.

   If the n8n ingress is unavailable, use `kubectl -n n8n port-forward svc/n8n 5678:5678` and open `http://localhost:5678` to import the workflow.

## Verify after rollout

- From an allowed DM and an allowed group, send text and a photo with a caption. Confirm the wrist alert shows the sender and text and the bot chat has the full text. Try an unlisted chat, one of your own messages, a view-once photo, and a disappearing message. Verify the existing poll vote callback separately.
- Pause the test workflow, send an allowed message, then restart the forwarder pod. Publish the workflow again and confirm the queued message arrives. Test long text with emoji and markup characters; the workflow should deliver numbered parts in order, requesting a sound only for the first part.
- Check `kubectl -n waha logs deploy/waha-forwarder` for destination failures and expired deliveries. The forwarder retries for up to 24 hours after accepting a message and clears the stored body on success or expiry. It keeps hashed delivery IDs for seven days for deduplication. If Telegram accepts a part but the acknowledgment is lost, that part may appear twice.

The forwarder does not fetch history and ignores events for messages more than five minutes older than the WAHA event. It skips view-once and disappearing messages identified in NOWEB's payload and never relays quoted text or attachment files. NOWEB does not report a reliable disappearing-message flag on every event; leave chats with disappearing messages off the allowlist if an independent copy is unacceptable. Forwarded copies are stored in Telegram.

The workflow disables saving successful, failed and manual executions in n8n's history. n8n still writes data during execution, then marks it deleted and physically removes it during its [execution pruning](https://docs.n8n.io/hosting/scaling/execution-data/#enable-execution-pruning) cycle.

## Webhook contract

The bridge sends JSON of the form:

```json
{
  "id": "<stable SHA-256 delivery ID>",
  "timestamp": 1780000000,
  "sender": "Maya",
  "group": "Family",
  "text": "Running 10 minutes late",
  "attachment": null
}
```

`group` is null for a DM. `attachment` is a display type (for example, `"Voice message"`) or null; `text` is the original text or caption and can be empty for an attachment. `Idempotency-Key` matches `id`. The bridge treats a `2xx` as success and retries other responses and connection failures. For the n8n workflow, `X-WhatsApp-Forwarder-Part` starts at `1`, and `X-WhatsApp-Forwarder-Next-Part` acknowledges the current part with either the next part number or `0` for done. Other webhooks can ignore the part header and return an ordinary `2xx`.
