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

    def generate_search_variants(self, query):
        """Генерирует варианты поискового запроса для лучшего нахождения"""
        words = query.split()
        variants = []
        
        # Оригинальный запрос
        variants.append(query)
        
        # Удаляем лишние слова вроде "скачать", "музыка", "песня"
        stop_words = ['скачать', 'музыка', 'песня', 'слушать', 'mp3', 'music', 'download']
        filtered_words = [w for w in words if w.lower() not in stop_words]
        if filtered_words and len(filtered_words) != len(words):
            variants.append(' '.join(filtered_words))
        
        # Разные комбинации для артиста и названия
        if len(words) >= 2:
            # Меняем местами слова (артист - название)
            variants.append(f"{words[1]} {words[0]}")
            
            # Добавляем только первое слово (часто это артист)
            variants.append(words[0])
            
            # Добавляем только последнее слово (часто это название)
            variants.append(words[-1])
            
            # Комбинация всех слов кроме первого
            if len(words) > 2:
                variants.append(' '.join(words[1:]))
        
        # Убираем дубликаты
        unique_variants = []
        seen = set()
        for variant in variants:
            if variant and variant not in seen:
                seen.add(variant)
                unique_variants.append(variant)
        
        return unique_variants[:6]  # Ограничиваем количество вариантов

    async def search_in_bot(self, bot_username, query, message):
        """Ищет музыку в конкретном боте с разными вариантами запроса"""
        variants = self.generate_search_variants(query)
        
        for search_variant in variants:
            try:
                # Пытаемся получить результаты с более агрессивным таймаутом
                results = await asyncio.wait_for(
                    message.client.inline_query(bot_username, search_variant),
                    timeout=1.5  # Уменьшенный таймаут для быстрого переключения
                )
                
                if results and len(results) > 0:
                    for result in results[:3]:  # Проверяем первые 3 результата
                        if hasattr(result.result, 'document'):
                            # Проверяем качество совпадения
                            title_match = False
                            performer_match = False
                            
                            if hasattr(result.result.document.attributes[0], 'title'):
                                doc_title = result.result.document.attributes[0].title.lower()
                                # Проверяем ключевые слова в названии
                                for word in query.lower().split():
                                    if len(word) > 3 and word in doc_title:
                                        title_match = True
                                        break
                            
                            if hasattr(result.result.document.attributes[0], 'performer'):
                                doc_performer = result.result.document.attributes[0].performer.lower()
                                # Проверяем ключевые слова в имени исполнителя
                                for word in query.lower().split():
                                    if len(word) > 3 and word in doc_performer:
                                        performer_match = True
                                        break
                            
                            # Если есть совпадение либо в названии, либо в исполнителе
                            if title_match or performer_match:
                                return {
                                    'bot': bot_username,
                                    'document': result.result.document,
                                    'title': result.result.document.attributes[0].title if hasattr(result.result.document.attributes[0], 'title') else '',
                                    'performer': result.result.document.attributes[0].performer if hasattr(result.result.document.attributes[0], 'performer') else '',
                                    'score': (2 if title_match else 0) + (2 if performer_match else 0)
                                }
                    
                    # Если не нашли точного совпадения, берем первый результат
                    return {
                        'bot': bot_username,
                        'document': results[0].result.document,
                        'title': results[0].result.document.attributes[0].title if hasattr(results[0].result.document.attributes[0], 'title') else '',
                        'performer': results[0].result.document.attributes[0].performer if hasattr(results[0].result.document.attributes[0], 'performer') else '',
                        'score': 1
                    }
                    
            except (asyncio.TimeoutError, Exception):
                continue  # Пробуем следующий вариант или следующего бота
        
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
                
            # Используем предварительно вычисленный score
            score = result.get('score', 0)
            
            # Дополнительные проверки для улучшения точности
            if result['title']:
                title_lower = result['title'].lower()
                # Проверяем полное совпадение слов
                query_words = set(query_lower.split())
                title_words = set(title_lower.split())
                common_words = query_words.intersection(title_words)
                if common_words:
                    score += len(common_words) * 2
            
            if result['performer']:
                performer_lower = result['performer'].lower()
                query_words = set(query_lower.split())
                performer_words = set(performer_lower.split())
                common_words = query_words.intersection(performer_words)
                if common_words:
                    score += len(common_words) * 3
            
            # Бонус за наличие обоих полей
            if result['performer'] and result['title']:
                score += 2
            
            if score > best_score:
                best_score = score
                best_result = result
        
        return best_result['document'] if best_result else None

    async def search_music_all_bots(self, query, message):
        """Ждет результаты от всех ботов одновременно и выбирает лучший"""
        search_tasks = []
        
        # Запускаем поиск во всех ботах параллельно
        for bot_username in self.music_bots:
            task = asyncio.create_task(self.search_in_bot(bot_username, query, message))
            search_tasks.append(task)
        
        # Используем as_completed для получения первого успешного результата
        completed_results = []
        done, pending = await asyncio.wait(search_tasks, timeout=3.0, return_when=asyncio.FIRST_COMPLETED)
        
        # Собираем завершенные задачи
        for task in done:
            try:
                result = task.result()
                if result:
                    completed_results.append(result)
                    # Если нашли хороший результат (score >= 3), можем остановиться
                    if result.get('score', 0) >= 3:
                        # Отменяем оставшиеся задачи
                        for p in pending:
                            p.cancel()
                        return self.find_best_match([result], query)
            except Exception:
                pass
        
        # Если есть еще время, ждем другие результаты
        if pending and completed_results:
            try:
                additional_done, _ = await asyncio.wait(pending, timeout=1.0)
                for task in additional_done:
                    try:
                        result = task.result()
                        if result:
                            completed_results.append(result)
                    except Exception:
                        pass
            except asyncio.TimeoutError:
                pass
        
        # Отменяем все оставшиеся задачи
        for task in pending:
            task.cancel()
        
        # Выбираем лучший результат из найденных
        return self.find_best_match(completed_results, query)

    async def search_music(self, query, message):
        async with self.search_lock:
            return await self.search_music_all_bots(query, message)

    # Остальные методы остаются без изменений...
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
