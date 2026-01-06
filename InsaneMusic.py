from .. import loader, utils
import asyncio
import time


class InsMusic(loader.Module):
    """Модуль для поиска музыки от @InsModule."""

    strings = {'name': 'InsMusic'}

    def __init__(self):
        self.database = None
        self.search_lock = asyncio.Lock()
        self.spam_protection = {}
        super().__init__()

    async def client_ready(self, client, database):
        self.client = client
        self.database = database
        
        if not self.database.get("InsMusic", "allowed_chats"):
            self.database.set("InsMusic", "allowed_chats", [])
        
        if not self.database.get("InsMusic", "music_bots"):
            default_bots = ["ShillMusic_bot","AudioBoxrobot","Lybot", "vkm4_bot", "MusicDownloaderBot", "DeezerMusicBot", "SpotifyDownloaderBot","shazambot"]
            self.database.set("InsMusic", "music_bots", default_bots)

    @property
    def allowed_chats(self):
        return self.database.get("InsMusic", "allowed_chats", [])

    @allowed_chats.setter
    def allowed_chats(self, value):
        self.database.set("InsMusic", "allowed_chats", value)

    @property
    def music_bots(self):
        return self.database.get("InsMusic", "music_bots", [])

    @music_bots.setter
    def music_bots(self, value):
        self.database.set("InsMusic", "music_bots", value)

    def check_spam(self, user_id):
        """Проверка на спам"""
        current_time = time.time()
        if user_id in self.spam_protection:
            last_time = self.spam_protection[user_id]
            if current_time - last_time < 5:
                return False
        self.spam_protection[user_id] = current_time
        return True

    async def search_in_bot(self, bot_username, query, message):
        try:
            # Используем более быстрый метод получения inline результатов
            results = await asyncio.wait_for(
                message.client.inline_query(bot_username, query),
                timeout=4.0
            )
            if results and len(results) > 0 and hasattr(results[0].result, 'document'):
                return {
                    'bot': bot_username,
                    'document': results[0].result.document,
                    'title': results[0].result.document.attributes[0].title if hasattr(results[0].result.document.attributes[0], 'title') else '',
                    'performer': results[0].result.document.attributes[0].performer if hasattr(results[0].result.document.attributes[0], 'performer') else ''
                }
        except (asyncio.TimeoutError, Exception):
            return None
        return None

    def find_best_match(self, search_results, query):
        """Выбирает самый подходящий результат из всех полученных"""
        if not search_results:
            return None
        
        query_lower = query.lower()
        best_result = None
        best_score = -1
        
        for result in search_results:
            if not result:
                continue
                
            score = 0
            
            # Проверяем совпадение исполнителя
            if result['performer']:
                performer_lower = result['performer'].lower()
                if any(term in performer_lower for term in query_lower.split()):
                    score += 2
                if performer_lower in query_lower or any(word in query_lower for word in performer_lower.split()):
                    score += 3
            
            # Проверяем совпадение названия
            if result['title']:
                title_lower = result['title'].lower()
                if any(term in title_lower for term in query_lower.split()):
                    score += 1
                if title_lower in query_lower or any(word in query_lower for word in title_lower.split()):
                    score += 2
            
            # Если есть и исполнитель и название, увеличиваем шансы
            if result['performer'] and result['title']:
                score += 1
            
            if score > best_score:
                best_score = score
                best_result = result
        
        return best_result['document'] if best_result else None

    async def search_music_all_bots(self, query, message):
        """Ждет результаты от всех ботов и выбирает лучший"""
        search_tasks = []
        
        # Запускаем поиск во всех ботах одновременно
        for bot_username in self.music_bots:
            task = asyncio.create_task(self.search_in_bot(bot_username, query, message))
            search_tasks.append(task)
        
        # Ждем завершения всех задач с таймаутом
        try:
            all_results = await asyncio.wait_for(
                asyncio.gather(*search_tasks, return_exceptions=True),
                timeout=10.0  # Уменьшено с 5 до 3 секунд
            )
        except asyncio.TimeoutError:
            # Получаем результаты от тех ботов, которые успели ответить
            completed_results = []
            for task in search_tasks:
                if task.done():
                    try:
                        result = task.result()
                        if result and not isinstance(result, Exception):
                            completed_results.append(result)
                    except:
                        pass
            all_results = completed_results
        
        # Фильтруем исключения
        valid_results = []
        for result in all_results:
            if result and not isinstance(result, Exception):
                valid_results.append(result)
        
        # Выбираем лучший результат
        return self.find_best_match(valid_results, query)

    async def search_music(self, query, message):
        async with self.search_lock:
            return await self.search_music_all_bots(query, message)

    @loader.command(
        ru_doc="<название> - Ищет музыку по названию (работает с префиксом)",
        en_doc="<title> - Search music by title (works with prefix)"
    )
    async def мcmd(self, message):
        """Поиск музыки по названию"""
        # Проверка на спам
        user_id = message.sender_id
        if not self.check_spam(user_id):
            await message.delete()
            error_message = await message.respond("Слишком много запросов! Подождите 5 секунд.")
            await self.delete_after(error_message, 3)
            return
        
        search_query = utils.get_args_raw(message)
        reply_message = await message.get_reply_message()

        if not search_query:
            await message.delete()
            error_message = await message.respond("Укажите название песни!")
            await self.delete_after(error_message, 3)
            return

        try:
            await message.delete()
            searching_message = await message.respond(f"<emoji document_id=5330324623613533041>⏰</emoji>")

            music_document = await self.search_music(search_query, message)

            if not music_document:
                await searching_message.edit("Музыка не найдена")
                await self.delete_after(searching_message, 3)
                return

            await searching_message.delete()
            # Отправляем реплаем на команду
            await message.client.send_file(
                message.to_id,
                music_document,
                reply_to=message.id  # Всегда отправляем реплаем на команду
            )

        except Exception as error:
            await message.delete()
            error_message = await message.respond(f"Ошибка: {str(error)}")
            await self.delete_after(error_message, 3)

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
            # Проверка на спам
            user_id = message.sender_id
            if not self.check_spam(user_id):
                await message.delete()
                return
            
            search_query = message.text[6:]

            try:
                await message.delete()
                searching_message = await message.respond(f"<emoji document_id=5330324623613533041>⏰</emoji>")

                music_document = await self.search_music(search_query, message)

                if not music_document:
                    await searching_message.edit("Музыка не найдена")
                    await self.delete_after(searching_message, 3)
                    return

                await searching_message.delete()
                # Отправляем реплаем на команду "найти"
                await message.client.send_file(
                    message.to_id,
                    music_document,
                    reply_to=message.id  # Реплаем на команду "найти"
                )

            except Exception as error:
                await message.delete()
                error_message = await message.respond(f"Ошибка: {str(error)}")
                await self.delete_after(error_message, 3)

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
            
        current_allowed_chats = self.allowed_chats.copy()

        if chat_id in current_allowed_chats:
            await message.edit("Этот чат уже в списке разрешенных!")
        else:
            current_allowed_chats.append(chat_id)
            self.allowed_chats = current_allowed_chats
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
            
        current_allowed_chats = self.allowed_chats.copy()

        if chat_id in current_allowed_chats:
            current_allowed_chats.remove(chat_id)
            self.allowed_chats = current_allowed_chats
            await message.edit(f"Чат удален! ID: {chat_id}")
        else:
            await message.edit("Этот чат не найден в списке.")

    @loader.command(
        ru_doc="Показывает список чатов, где команда работает без префикса",
        en_doc="Shows list of chats where command works without prefix"
    )
    async def listmcmd(self, message):
        """Список разрешенных чатов"""
        allowed_chats_list = self.allowed_chats
        if not allowed_chats_list:
            await message.edit("Список разрешенных чатов пуст.")
        else:
            text = "Разрешенные чаты:\n\n"
            for chat_id in allowed_chats_list:
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
            current_bots_list = self.music_bots.copy()
            current_bots_list.append(bot_username)
            self.music_bots = current_bots_list
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
            current_bots_list = self.music_bots.copy()
            current_bots_list.remove(bot_username)
            self.music_bots = current_bots_list
            await message.edit(f"Бот @{bot_username} удален из списка!")
        else:
            await message.edit("Этот бот не найден в списке!")

