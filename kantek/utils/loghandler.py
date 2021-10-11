"""Module with the Custom Logging Handler for logging to a Telegram Channel."""
import asyncio
import traceback
from datetime import datetime
from logging import Handler, LogRecord, Logger
from typing import Union, Dict

import logzero
from telethon import TelegramClient

logger: Logger = logzero.logger


class TGChannelLogHandler(Handler):
    """Log to a Telegram Channel using a Bot"""

    def __init__(self, api_id: int, api_hash: str, bot_token: str, channel_id: Union[str, int]) -> None:
        self.bot = TelegramClient(None, api_id, api_hash)
        self.bot_token = bot_token
        self.channel_id = channel_id
        # might want to make this a instance variable if its safe to do so
        super().__init__()

    async def connect(self):
        await self.bot.start(bot_token=self.bot_token)
        self.me = await self.bot.get_me()

    def format(self, record: LogRecord) -> str:
        """Format the specified record."""
        time_format = '%Y-%m-%d %H:%M:%S'
        log_time = datetime.fromtimestamp(record.created).strftime(time_format)
        origin = f'`{record.filename}[{record.lineno}]`'
        # only add the function name if the logging call came from one.
        if record.funcName != '<module>':
            origin += f' `❯` `{record.funcName}`'
        formatted_traceback = ''.join(traceback.format_exception(*record.exc_info)) if record.exc_info else ''
        _log_entry = {
            'origin': origin,
            'level': f'{record.levelname.title()}({record.levelno})',
            'time': f'{log_time}',
            'msg': record.getMessage(),
            'traceback': f'```\n{formatted_traceback}```' if formatted_traceback else ''
        }
        log_entry = []
        for k, v in _log_entry.items():
            if v:
                log_entry.append(f'`{k}:` {v}')
        return '\n'.join(log_entry)

    def emit(self, record: LogRecord) -> None:
        """Send the log message to the specified Telegram channel."""
        asyncio.ensure_future(self.bot.send_message(
            self.channel_id,
            self.format(record),
            parse_mode='markdown',
            link_preview=False))
