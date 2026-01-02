from .. import loader, utils
import asyncio


class InsMusic(loader.Module):
    """Модуль для поиска музыки от @InsModule."""

    strings = {'name': 'InsMusic'}

    def __init__(self):
        self.db = None
        self._search_lock = asyncio.Lock()
        super().__init__()

    async def client_ready(self, client, db):
        self.client = client
        self.db = db
        
        if not self.db.get("InsMusic", "allowed_chats"):
            self.db.set("InsMusic", "allowed_chats", [])
        
        if not self.db.get("InsMusic", "music_bots"):
            default_bots = ["ShillMusic_bot", "losslessrobot","AudioBoxrobot", "shazambot", "Lybot", "vkm4_bot", "MusicDownloaderBot", "DeezerMusicBot", "SpotifyDownloaderBot"]
            self.db.set("InsMusic", "music_bots", default_bots)

    @property
    def allowed_chats(self):
        return self.db.get("InsMusic", "allowed_chats", [])

    @allowed_chats.setter
    def allowed_chats(self, value):
        self.db.set("InsMusic", "allowed_chats", value)

    @property
    def music_bots(self):
        return self.db.get("InsMusic", "music_bots", [])

    @music_bots.setter
    def music_bots(self, value):
        self.db.set("InsMusic", "music_bots", value)

    async def search_in_bot(self, bot_username, query, message):
        try:
            music = await message.client.inline_query(bot_username, query)
            if music and len(music) > 0 and hasattr(music[0].result, 'document'):
                return music[0].result.document
        except Exception:
            return None
        return None

    async def search_music_fast(self, query, message):
        tasks = []
        for bot_username in self.music_bots:
            task = asyncio.create_task(self.search_in_bot(bot_username, query, message))
            tasks.append((bot_username, task))
        
        for bot_username, task in tasks:
            try:
                result = await asyncio.wait_for(task, timeout=3.0)
                if result:
                    for other_bot, other_task in tasks:
                        if other_bot != bot_username and not other_task.done():
                            other_task.cancel()
                    return result
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue
        
        return None

    async def search_music(self, query, message):
        async with self._search_lock:
            return await self.search_music_fast(query, message)

    @loader.command(
        ru_doc="<название> - Ищет музыку по названию (работает с префиксом)",
        en_doc="<title> - Search music by title (works with prefix)"
    )
    async def мcmd(self, message):
        """Поиск музыки по названию"""
        args = utils.get_args_raw(message)
        reply = await message.get_reply_message()

        if not args:
            await message.delete()
            error_msg = await message.respond("Укажите название песни!")
            await self.delete_after(error_msg, 3)
            return

        try:
            await message.delete()
            search_msg = await message.respond(f"<emoji document_id=5330324623613533041>⏰</emoji>")

            music_doc = await self.search_music(args, message)

            if not music_doc:
                await search_msg.edit("Музыка не найдена")
                await self.delete_after(search_msg, 3)
                return

            await search_msg.delete()
            await message.client.send_file(
                message.to_id,
                music_doc,
                reply_to=reply.id if reply else None
            )

        except Exception as e:
            await message.delete()
            error_msg = await message.respond(f"Ошибка: {str(e)}")
            await self.delete_after(error_msg, 3)

    async def watcher(self, message):
        if not message.text:
            return

        try:
            chat_id = str(message.chat_id if hasattr(message, 'chat_id') else message.to_id)
        except Exception:
            chat_id = str(message.peer_id)
        
        if chat_id.startswith('-100'):
            chat_id = chat_id[4:]
        
        if chat_id not in self.allowed_chats:
            original_chat_id = str(message.chat_id if hasattr(message, 'chat_id') else message.to_id)
            if original_chat_id not in self.allowed_chats:
                return

        text_lower = message.text.lower()
        if text_lower.startswith("найти "):
            args = message.text[6:]

            try:
                await message.delete()
                search_msg = await message.respond(f"<emoji document_id=5330324623613533041>⏰</emoji>")

                music_doc = await self.search_music(args, message)

                if not music_doc:
                    await search_msg.edit("Музыка не найдена")
                    await self.delete_after(search_msg, 3)
                    return

                await search_msg.delete()
                await message.client.send_file(
                    message.to_id,
                    music_doc
                )

            except Exception as e:
                await message.delete()
                error_msg = await message.respond(f"Ошибка: {str(e)}")
                await self.delete_after(error_msg, 3)

    async def delete_after(self, message, seconds):
        await asyncio.sleep(seconds)
        await message.delete()

    @loader.command(
        ru_doc="Добавляет текущий чат в список разрешенных для команды без префикса",
        en_doc="Adds current chat to the list of allowed chats for prefix-less command"
    )
    async def addmcmd(self, message):
        """Добавить чат для работы без префикса"""
        try:
            chat_id = str(message.chat_id if hasattr(message, 'chat_id') else message.to_id)
        except Exception:
            chat_id = str(message.peer_id)
            
        if chat_id.startswith('-100'):
            chat_id = chat_id[4:]
            
        current_chats = self.allowed_chats.copy()

        if chat_id in current_chats:
            await message.edit("Этот чат уже в списке разрешенных!")
        else:
            current_chats.append(chat_id)
            self.allowed_chats = current_chats
            await message.edit(f"Чат добавлен! ID: {chat_id}")

    @loader.command(
        ru_doc="[id чата] - Удаляет текущий/указанный чат из списка разрешенных",
        en_doc="[chat id] - Removes current/specified chat from allowed list"
    )
    async def delmcmd(self, message):
        """Удалить чат из разрешенных"""
        args = utils.get_args_raw(message)
        
        if args:
            chat_id = args
        else:
            try:
                chat_id = str(message.chat_id if hasattr(message, 'chat_id') else message.to_id)
            except Exception:
                chat_id = str(message.peer_id)
            
            if chat_id.startswith('-100'):
                chat_id = chat_id[4:]
            
        current_chats = self.allowed_chats.copy()

        if chat_id in current_chats:
            current_chats.remove(chat_id)
            self.allowed_chats = current_chats
            await message.edit(f"Чат удален! ID: {chat_id}")
        else:
            await message.edit("Этот чат не найден в списке.")

    @loader.command(
        ru_doc="Показывает список чатов, где команда работает без префикса",
        en_doc="Shows list of chats where command works without prefix"
    )
    async def listmcmd(self, message):
        """Список разрешенных чатов"""
        chats = self.allowed_chats
        if not chats:
            await message.edit("Список разрешенных чатов пуст.")
        else:
            text = "Разрешенные чаты:\n\n"
            for chat_id in chats:
                try:
                    if chat_id.isdigit():
                        chat = await self.client.get_entity(int(chat_id))
                        title = getattr(chat, 'title', 'Личные сообщения')
                        text += f"• {title} ({chat_id})\n"
                    else:
                        text += f"• Неизвестный чат ({chat_id})\n"
                except Exception:
                    text += f"• Неизвестный чат ({chat_id})\n"
            await message.edit(text)

    @loader.command(
        ru_doc="Показывает список ботов для поиска музыки",
        en_doc="Shows list of music search bots"
    )
    async def botsmcmd(self, message):
        """Список ботов для поиска"""
        text = "Боты для поиска музыки:\n\n"
        for i, bot in enumerate(self.music_bots, 1):
            text += f"{i}. {bot}\n"
        await message.edit(text)

    @loader.command(
        ru_doc="<юзернейм> - Добавляет бота в список для поиска музыки",
        en_doc="<username> - Adds bot to music search list"
    )
    async def addbotmcmd(self, message):
        """Добавить бота для поиска"""
        args = utils.get_args_raw(message)
        if not args:
            await message.edit("Укажите username бота!")
            return
        
        bot_username = args.replace('@', '')
        if bot_username in self.music_bots:
            await message.edit("Этот бот уже есть в списке!")
        else:
            current_bots = self.music_bots.copy()
            current_bots.append(bot_username)
            self.music_bots = current_bots
            await message.edit(f"Бот @{bot_username} добавлен в список!")

    @loader.command(
        ru_doc="<юзернейм> - Удаляет бота из списка для поиска музыки",
        en_doc="<username> - Removes bot from music search list"
    )
    async def delbotmcmd(self, message):
        """Удалить бота из поиска"""
        args = utils.get_args_raw(message)
        if not args:
            await message.edit("Укажите username бота!")
            return
        
        bot_username = args.replace('@', '')
        if bot_username in self.music_bots:
            current_bots = self.music_bots.copy()
            current_bots.remove(bot_username)
            self.music_bots = current_bots
            await message.edit(f"Бот @{bot_username} удален из списка!")
        else:
            await message.edit("Этот бот не найден в списке!")
