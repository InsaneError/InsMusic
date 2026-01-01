from .. import loader, utils
import asyncio


class InsMusic(loader.Module):
    """Модуль для поиска музыки от @InsModule."""

    strings = {'name': 'InsMusic'}

    def __init__(self):
        self.config = loader.ModuleConfig(
            "allowed_chats", [], "ID чатов, где команда работает без префикса"
        )
        # Список ботов для поиска музыки
        self.music_bots = ["Lybot", "vkm4_bot", "MusicDownloaderBot", "DeezerMusicBot", "SpotifyDownloaderBot"]
        self._search_lock = asyncio.Lock()
        super().__init__()

    async def client_ready(self, client, db):
        self.client = client
        self.db = db

    async def search_in_bot(self, bot_username, query, message):
        try:
            music = await message.client.inline_query(bot_username, query)
            if music and len(music) > 0 and hasattr(music[0].result, 'document'):
                return music[0].result.document
        except Exception as e:
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

    @loader.command()
    async def мcmd(self, message):
        args = utils.get_args_raw(message)
        reply = await message.get_reply_message()

        if not args:
            await message.delete()
            error_msg = await message.respond("Укажите название песни!")
            await self.delete_after(error_msg, 3)
            return

        try:
            await message.delete()
            search_msg = await message.respond(f"Поиск: {args}")

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

        chat_id = str(message.chat_id)
        if chat_id not in self.config["allowed_chats"]:
            return

        text_lower = message.text.lower()
        if text_lower.startswith("найти "):
            args = message.text[6:]

            try:
                await message.delete()
                search_msg = await message.respond(f"Поиск: {args}")

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

    @loader.command()
    async def addmcmd(self, message):
        chat_id = str(message.chat_id)
        current_chats = self.config["allowed_chats"].copy()

        if chat_id in current_chats:
            await message.edit("Этот чат уже в списке разрешенных!")
        else:
            current_chats.append(chat_id)
            self.config["allowed_chats"] = current_chats
            await message.edit(f"Чат добавлен! ID: {chat_id}")

    @loader.command()
    async def delmcmd(self, message):
        args = utils.get_args_raw(message)
        chat_id = args if args else str(message.chat_id)
        current_chats = self.config["allowed_chats"].copy()

        if chat_id in current_chats:
            current_chats.remove(chat_id)
            self.config["allowed_chats"] = current_chats
            await message.edit(f"Чат удален! ID: {chat_id}")
        else:
            await message.edit("Этот чат не найден в списке.")

    @loader.command()
    async def listmcmd(self, message):
        chats = self.config["allowed_chats"]
        if not chats:
            await message.edit("Список разрешенных чатов пуст.")
        else:
            text = "Разрешенные чаты:\n\n"
            for chat_id in chats:
                try:
                    chat = await self.client.get_entity(int(chat_id))
                    title = getattr(chat, 'title', 'Личные сообщения')
                    text += f"• {title} ({chat_id})\n"
                except:
                    text += f"• Неизвестный чат ({chat_id})\n"
            await message.edit(text)

    @loader.command()
    async def botsmcmd(self, message):
        text = "Боты для поиска музыки:\n\n"
        for i, bot in enumerate(self.music_bots, 1):
            text += f"{i}. {bot}\n"
        await message.edit(text)

    @loader.command()
    async def addbotmcmd(self, message):
        args = utils.get_args_raw(message)
        if not args:
            await message.edit("Укажите username бота!")
            return

        bot_username = args.replace('@', '')
        if bot_username in self.music_bots:
            await message.edit("Этот бот уже есть в списке!")
        else:
            self.music_bots.append(bot_username)
            await message.edit(f"Бот @{bot_username} добавлен в список!")

    @loader.command()
    async def delbotmcmd(self, message):
        args = utils.get_args_raw(message)
        if not args:
            await message.edit("Укажите username бота!")
            return

        bot_username = args.replace('@', '')
        if bot_username in self.music_bots:
            self.music_bots.remove(bot_username)
            await message.edit(f"Бот @{bot_username} удален из списка!")
        else:
            await message.edit("Этот бот не найден в списке!")