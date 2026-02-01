from .. import loader, utils
import asyncio
import time
from typing import Optional, Dict, List


class InsMusic(loader.Module):
    """Модуль для поиска музыки от @InsModule."""

    strings = {'name': 'InsMusic'}

    def __init__(self):
        self.database = None
        self.search_lock = asyncio.Lock()
        self.spam_protection = {}
        self.cache = {}  # Кэш для результатов поиска
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

    async def search_in_bot(self, bot_username: str, query: str, message) -> Optional[Dict]:
        """Поиск музыки в конкретном боте с улучшенной логикой"""
        try:
            # Ключ для кэша
            cache_key = f"{bot_username}:{query.lower()}"
            
            # Проверяем кэш
            if cache_key in self.cache:
                cached_result = self.cache[cache_key]
                # Проверяем актуальность кэша (5 минут)
                if time.time() - cached_result.get('timestamp', 0) < 300:
                    return cached_result.get('result')
            
            # Получаем инлайн результаты
            results = await asyncio.wait_for(
                message.client.inline_query(bot_username, query),
                timeout=5  # Увеличено для медленных ботов
            )
            
            if not results:
                return None
            
            # Ищем лучший результат среди всех предложенных
            best_result = None
            best_score = 0
            
            for result in results[:10]:  # Проверяем первые 10 результатов
                if not hasattr(result, 'result') or not hasattr(result.result, 'document'):
                    continue
                
                document = result.result.document
                
                # Пропускаем не аудио файлы
                if not document.mime_type.startswith('audio/'):
                    continue
                
                # Извлекаем метаданные
                title = ""
                performer = ""
                duration = 0
                
                if hasattr(document, 'attributes') and document.attributes:
                    for attr in document.attributes:
                        if hasattr(attr, 'title'):
                            title = getattr(attr, 'title', '').lower()
                        if hasattr(attr, 'performer'):
                            performer = getattr(attr, 'performer', '').lower()
                        if hasattr(attr, 'duration'):
                            duration = getattr(attr, 'duration', 0)
                
                # Пропускаем слишком короткие или слишком длинные треки
                if duration < 30 or duration > 600:  # от 30 секунд до 10 минут
                    continue
                
                # Считаем релевантность
                score = self.calculate_relevance(query.lower(), title, performer)
                
                if score > best_score:
                    best_score = score
                    best_result = {
                        'bot': bot_username,
                        'document': document,
                        'title': title.capitalize() if title else '',
                        'performer': performer.capitalize() if performer else '',
                        'duration': duration,
                        'score': score
                    }
            
            if best_result:
                # Сохраняем в кэш
                self.cache[cache_key] = {
                    'result': best_result,
                    'timestamp': time.time()
                }
                return best_result
            
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            # Логируем ошибку, но не прерываем выполнение
            print(f"Error in bot {bot_username}: {e}")
            return None
        
        return None

    def calculate_relevance(self, query: str, title: str, performer: str) -> int:
        """Вычисляет релевантность результата запросу"""
        score = 0
        
        # Разбиваем запрос на слова
        query_words = set(query.split())
        
        if title:
            title_words = set(title.split())
            # Количество совпадающих слов
            common_words = query_words.intersection(title_words)
            score += len(common_words) * 3
            
            # Полное совпадение названия
            if query in title:
                score += 10
            # Частичное совпадение
            elif any(word in title for word in query_words):
                score += 5
        
        if performer:
            performer_words = set(performer.split())
            # Совпадение исполнителя
            common_words = query_words.intersection(performer_words)
            score += len(common_words) * 4
            
            # Запрос содержит исполнителя
            if any(word in performer for word in query_words):
                score += 7
        
        # Бонус за наличие и названия и исполнителя
        if title and performer:
            score += 3
        
        # Штраф за пустые поля
        if not title and not performer:
            score -= 10
        
        return score

    async def search_music_all_bots(self, query: str, message):
        """Ждет результаты от всех ботов и выбирает лучший"""
        search_tasks = []
        
        # Запускаем поиск во всех ботах одновременно
        for bot_username in self.music_bots:
            task = asyncio.create_task(self.search_in_bot(bot_username, query, message))
            search_tasks.append(task)
        
        # Ждем первые успешные результаты
        timeout = 8.0  # Увеличено для стабильности
        start_time = time.time()
        
        all_results = []
        pending_tasks = set(search_tasks)
        
        while pending_tasks and time.time() - start_time < timeout:
            # Ждем завершения хотя бы одной задачи
            done, pending_tasks = await asyncio.wait(
                pending_tasks,
                timeout=timeout - (time.time() - start_time),
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in done:
                try:
                    result = task.result()
                    if result:
                        all_results.append(result)
                        # Если нашли очень релевантный результат, возвращаем сразу
                        if result.get('score', 0) >= 15:
                            # Отменяем оставшиеся задачи
                            for t in pending_tasks:
                                t.cancel()
                            return result.get('document')
                except Exception:
                    continue
        
        # Выбираем лучший результат среди найденных
        if not all_results:
            return None
        
        # Сортируем по релевантности
        all_results.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        # Возвращаем документ лучшего результата
        return all_results[0].get('document')

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

        if not search_query:
            await message.delete()
            error_message = await message.respond("Укажите название песни!")
            await self.delete_after(error_message, 3)
            return

        try:
            await message.delete()
            searching_message = await message.respond(f"<emoji document_id=5330324623613533041>⏰</emoji> Поиск: {search_query[:50]}...")

            music_document = await self.search_music(search_query, message)

            if not music_document:
                await searching_message.edit("❌ Музыка не найдена")
                await self.delete_after(searching_message, 3)
                return

            await searching_message.delete()
            # Отправляем реплаем на команду
            await message.client.send_file(
                message.to_id,
                music_document,
                reply_to=message.id,
                caption=f"🎵 Найдено по запросу: {search_query}"
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
            
            search_query = message.text[6:].strip()
            
            if not search_query or len(search_query) < 2:
                return

            try:
                await message.delete()
                searching_message = await message.respond(f"<emoji document_id=5330324623613533041>⏰</emoji> Поиск: {search_query[:50]}...")

                music_document = await self.search_music(search_query, message)

                if not music_document:
                    await searching_message.edit("❌ Музыка не найдена")
                    await self.delete_after(searching_message, 3)
                    return

                await searching_message.delete()
                # Отправляем реплаем на команду "найти"
                await message.client.send_file(
                    message.to_id,
                    music_document,
                    reply_to=message.id,
                    caption=f"🎵 Найдено по запросу: {search_query}"
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
            text += f"{i}. @{bot}\n"
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

    @loader.command(
        ru_doc="Очищает кэш поиска",
        en_doc="Clears search cache"
    )
    async def clearmcache(self, message):
        """Очистить кэш поиска"""
        self.cache.clear()
        await message.edit("✅ Кэш поиска очищен!")
