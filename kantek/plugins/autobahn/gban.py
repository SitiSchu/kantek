import asyncio
import datetime
import logging
from typing import Dict, Optional, List

from telethon.errors import UserNotParticipantError
from telethon.tl.custom import Message
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.messages import ReportRequest
from telethon.tl.types import (Channel, InputReportReasonSpam, InputPeerChannel, ChannelParticipantCreator,
                               InputMessagesFilterPhotos, PeerUser, )

from kantek import Database
from kantek.utils import helpers, parsers
from kantek import Client
from kantex.md import *
from kantek import k, Command
from kantek.utils.tags import Tags

tlog = logging.getLogger('kantek-channel-log')

DEFAULT_REASON = 'spam[gban]'
CHUNK_SIZE = 10


@k.command('gban', delete=True)
async def gban(client: Client, db: Database, tags: Tags, chat: Channel, msg: Message,
               args: List, kwargs: Dict, event: Command) -> Optional[KanTeXDocument]:
    """Globally ban a user.

    This will not actively ban them from any chats except the one command was issued in as reply. GBanned users will be automatically banned on join or when writing a message by the Grenzschutz module.
    When banning by reply the message content will be automatically sent to the SpamWatch API if enabled.

    Arguments:
        `ids`: List of user ids to be gbanned
        `reason`: Ban reason, defaults to `spam[gban]`
        `msg`: String of the message the user sent. Only useful with the SpamWatch API
        `link`: Link to the users message. Only useful with the SpamWatch API
        `sa`: Key for a Strafanzeige entry, simply copy paste this from {prefix}user

    Tags:
        gban:
            verbose: Send a message when a user was banned by id
        gbancmd:
            *: Send `{{bancmd}} {{ban_reason}}` in reply to the message

    Examples:
        {cmd} 777000
        {cmd} 777000 "some reason here"
        {cmd} 777000 msg: "the message for the api"
        {cmd} 777000 link: https://t.me/c/1129887931/26708
        {cmd} sa: xcQq9aMm77U2aA
        {cmd}
    """
    _gban = tags.get('gban')
    if event.is_private:
        admin = False
    else:
        admin = bool(chat.creator or chat.admin_rights)
    only_joinspam = kwargs.get('only_joinspam', False) or kwargs.get('oj', False)
    sa_key = kwargs.get('sa')
    anzeige = None
    if sa_key:
        anzeige = await db.strafanzeigen.get(sa_key)

    if anzeige:
        _kw, _args = parsers.arguments(anzeige)
        kwargs.update(_kw)
        args.extend(_args)

    verbose = False
    if _gban == 'verbose' or event.is_private:
        verbose = True

    if msg.is_reply:
        bancmd = tags.get('gbancmd')
        reply_msg: Message = await msg.get_reply_message()

        peer = reply_msg.from_id

        if not isinstance(peer, PeerUser):
            return
        else:
            uid = peer.user_id
        if args:
            ban_reason = ' '.join(args)
        else:
            ban_reason = DEFAULT_REASON
            try:
                participant = await client(GetParticipantRequest(event.chat_id, uid))
                if not isinstance(participant.participant, ChannelParticipantCreator):
                    join_date = participant.participant.date

                    if (reply_msg.date - datetime.timedelta(hours=1)) < join_date:
                        ban_reason = 'joinspam'
                    elif only_joinspam:
                        return
            except UserNotParticipantError:
                pass

        message = await helpers.textify_message(reply_msg)
        await client.gban(uid, ban_reason, message)
        peer_channel: InputPeerChannel = await event.get_input_chat()
        if not client.config.debug_mode:
            await client(ReportRequest(peer_channel, [reply_msg.id], InputReportReasonSpam()))
        if bancmd == 'manual' or bancmd is None:
            if admin:
                await client.ban(chat, uid)

        elif bancmd is not None:
            await reply_msg.reply(f'{bancmd} {ban_reason if admin else ""}')
            await asyncio.sleep(0.5)

        if not client.config.debug_mode and admin:
            if reply_msg.grouped_id is not None:
                m: Message
                async for m in client.iter_messages(chat, limit=12, filter=InputMessagesFilterPhotos, offset_id=msg.id):
                    if m.grouped_id == reply_msg.grouped_id:
                        await m.delete()
            await reply_msg.delete()
    else:
        uids = []
        ban_reason = []
        for arg in args:
            if isinstance(arg, int):
                uids.append(arg)
            else:
                ban_reason.append(arg)
        if ban_reason:
            ban_reason = ' '.join(ban_reason)
        else:
            ban_reason = kwargs.get('reason', DEFAULT_REASON)

        message = kwargs.get('msg')
        if not message:
            link = kwargs.get('link')
            if link:
                try:
                    linked_msg: Message = await helpers.get_linked_message(client, link)
                    message = await helpers.textify_message(linked_msg)
                except Exception:  # pylint: disable = W0703
                    message = link

        skipped_uids = {}
        banned_uids = {}
        progress_message: Optional[Message]
        if verbose and len(uids) > 10:
            progress_message: Message = await client.send_message(chat, f"Processing {len(uids)} User IDs")
        else:
            progress_message = None
        while uids:
            uid_batch = uids[:CHUNK_SIZE]
            for uid in uid_batch:
                banned, reason = await client.gban(uid, ban_reason, message)
                if not banned:
                    skipped_uids[reason] = skipped_uids.get(reason, []) + [str(uid)]
                # sleep to avoid flooding the bots too much
                else:
                    banned_uids[reason] = banned_uids.get(reason, []) + [str(uid)]
                await asyncio.sleep(0.5)
            uids = uids[CHUNK_SIZE:]
            if uids:
                if progress_message:
                    await progress_message.edit(
                        f"Sleeping for 10 seconds after banning {len(uid_batch)} Users. {len(uids)} Users left.")
                await asyncio.sleep(10)

        if progress_message:
            await progress_message.delete()

        if verbose:
            sections = []
            if banned_uids:
                bans = _build_message(banned_uids, message)
                sections.append(Section(f'GBanned User{"s" if len(banned_uids) > 1 else ""}', *bans))
            if skipped_uids:
                bans = _build_message(skipped_uids)
                sections.append(Section('Skipped GBan', *bans))

            return KanTeXDocument(*sections)


def _build_message(bans: Dict[str, List[str]], message: Optional[str] = None) -> List[KeyValueItem]:
    sections = []
    for reason, uids in bans.items():
        sections.append(KeyValueItem(Bold('Reason'), reason))
        sections.append(KeyValueItem(Bold('IDs'), Code(', '.join(uids))))
        if message:
            sections.append(KeyValueItem(Bold('Message'), 'Attached'))
    return sections
