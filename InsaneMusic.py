from .. import loader, utils
import asyncio
import time
import re


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
        """Улучшенный поиск в одном боте с получением нескольких результатов"""
        try:
            results = await asyncio.wait_for(
                message.client.inline_query(bot_username, query),
                timeout=3.0
            )
            
            if not results or len(results) == 0:
                return []
            
            music_results = []
            # Собираем до 5 результатов от каждого бота
            for i in range(min(len(results), 5)):
                result = results[i]
                if hasattr(result.result, 'document') and result.result.document:
                    try:
                        doc = result.result.document
                        title = ""
                        performer = ""
                        
                        # Пытаемся извлечь название и исполнителя из атрибутов документа
                        for attr in doc.attributes:
                            if hasattr(attr, 'title'):
                                title = attr.title
                            if hasattr(attr, 'performer'):
                                performer = attr.performer
                        
                        # Если не удалось получить через атрибуты, пробуем из заголовка результата
                        if not title and hasattr(result.result, 'title'):
                            title = result.result.title
                        
                        music_results.append({
                            'bot': bot_username,
                            'document': doc,
                            'title': title,
                            'performer': performer,
                            'raw_title': result.result.title if hasattr(result.result, 'title') else ''
                        })
                    except Exception:
                        continue
            
            return music_results
            
        except (asyncio.TimeoutError, Exception):
            return []
        return []

    def clean_query(self, query):
        """Очищает запрос от лишних символов"""
        # Удаляем лишние пробелы и специальные символы
        query = re.sub(r'[^\w\s-]', ' ', query)
        query = re.sub(r'\s+', ' ', query).strip()
        return query

    def calculate_relevance_score(self, track_info, original_query):
        """Улучшенный расчет релевантности трека"""
        score = 0
        query_lower = original_query.lower()
        query_words = set(query_lower.split())
        
        # Получаем все доступные текстовые поля для анализа
        title_lower = track_info.get('title', '').lower()
        performer_lower = track_info.get('performer', '').lower()
        raw_title_lower = track_info.get('raw_title', '').lower()
        
        # Проверяем точное совпадение запроса с названием или исполнителем
        if query_lower == title_lower or query_lower == performer_lower:
            score += 100
        
        # Проверяем вхождение полного запроса
        if query_lower in title_lower or query_lower in performer_lower:
            score += 50
        if query_lower in raw_title_lower:
            score += 30
        
        # Анализируем отдельные слова из запроса
        matched_words = set()
        for word in query_words:
            if len(word) < 3:  # Пропускаем короткие слова
                continue
                
            # Поиск в названии
            if word in title_lower:
                score += 15
                matched_words.add(word)
            
            # Поиск в исполнителе (более высокий приоритет)
            if word in performer_lower:
                score += 20
                matched_words.add(word)
            
            # Поиск в сыром заголовке
            if word in raw_title_lower:
                score += 10
                matched_words.add(word)
        
        # Бонус за совпадение всех значимых слов
        significant_words = [w for w in query_words if len(w) >= 3]
        if significant_words and len(matched_words) == len(significant_words):
            score += 25
        
        # Бонус за наличие и исполнителя, и названия
        if performer_lower and title_lower:
            score += 10
        
        # Штраф, если в результате есть лишние слова (качество хуже)
        title_parts = set(title_lower.split())
        extra_words = title_parts - query_words
        if extra_words and len(extra_words) > len(title_parts) / 2:
            score -= len(extra_words) * 5
        
        return score

    def extract_track_info_from_document(self, document, raw_title=""):
        """Извлекает информацию о треке из документа"""
        title = ""
        performer = ""
        
        # Пытаемся получить из атрибутов документа
        for attr in document.attributes:
            if hasattr(attr, 'title'):
                title = attr.title
            if hasattr(attr, 'performer'):
                performer = attr.performer
        
        # Если не удалось, пробуем извлечь из имени файла
        if not title and hasattr(document, 'name') and document.name:
            # Пробуем разобрать имя файла
            filename = document.name.lower()
            # Убираем расширение
            filename = re.sub(r'\.(mp3|m4a|ogg|flac|wav)$', '', filename)
            # Если есть дефис, скорее всего это исполнитель - название
            if ' - ' in filename:
                parts = filename.split(' - ', 1)
                performer = parts[0].strip()
                title = parts[1].strip()
            else:
                title = document.name
        
        return {
            'title': title,
            'performer': performer,
            'raw_title': raw_title
        }

    async def search_music_all_bots(self, query, message):
        """Улучшенный поиск по всем ботам с анализом нескольких результатов"""
        cleaned_query = self.clean_query(query)
        search_tasks = []
        
        # Запускаем поиск во всех ботах
        for bot_username in self.music_bots:
            task = asyncio.create_task(self.search_in_bot(bot_username, cleaned_query, message))
            search_tasks.append(task)
        
        # Собираем все результаты
        all_results = []
        try:
            results_lists = await asyncio.wait_for(
                asyncio.gather(*search_tasks, return_exceptions=True),
                timeout=12.0
            )
            
            for results_list in results_lists:
                if isinstance(results_list, list):
                    all_results.extend(results_list)
                    
        except asyncio.TimeoutError:
            # Собираем результаты от завершившихся задач
            for task in search_tasks:
                if task.done() and not task.exception():
                    results = task.result()
                    if isinstance(results, list):
                        all_results.extend(results)
        
        if not all_results:
            return None
        
        # Оцениваем релевантность каждого результата
        scored_results = []
        for result in all_results:
            if not result or not result.get('document'):
                continue
            
            # Извлекаем информацию о треке
            track_info = self.extract_track_info_from_document(
                result['document'], 
                result.get('raw_title', '')
            )
            
            # Объединяем с имеющимися данными
            track_info.update({
                'bot': result.get('bot', ''),
                'document': result['document']
            })
            
            # Рассчитываем релевантность
            score = self.calculate_relevance_score(track_info, cleaned_query)
            
            # Дополнительный бонус за ботов, которые обычно дают хорошие результаты
            preferred_bots = ["ShillMusic_bot", "AudioBoxrobot", "vkm4_bot"]
            if track_info['bot'] in preferred_bots:
                score += 5
            
            scored_results.append((score, track_info))
        
        if not scored_results:
            return None
        
        # Сортируем по релевантности
        scored_results.sort(key=lambda x: x[0], reverse=True)
        
        # Логируем топ-3 результата для отладки
        best_score, best_result = scored_results[0]
        
        # Если лучший результат имеет слишком низкий балл, пробуем взять первый попавшийся
        if best_score < 10 and len(scored_results) > 1:
            # Возвращаем первый результат (часто самый популярный)
            return scored_results[0][1]['document']
        
        return best_result['document']

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

    @loader.command(
        ru_doc="<название> - Позволяет выбрать музыку через инлайн-бота",
        en_doc="<title> - Choose music via inline bot"
    )
    async def миcmd(self, message):
        """Выбор музыки через инлайн"""
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
            
            # Очищаем запрос
            cleaned_query = self.clean_query(search_query)
            
            # Пробуем разные ботов для инлайн-поиска
            bots_to_try = ["lybot", "ShillMusic_bot", "MusicDownloaderBot", "vkm4_bot"]
            inline_results = None
            used_bot = None
            
            for bot in bots_to_try:
                try:
                    inline_results = await message.client.inline_query(bot, cleaned_query)
                    if inline_results and len(inline_results) > 0:
                        used_bot = bot
                        break
                except Exception:
                    continue
            
            if inline_results and len(inline_results) > 0:
                # Создаем список для хранения ID сообщений
                sent_messages = []
                
                # Отправляем первые 5 результатов по одному
                for i in range(min(len(inline_results), 5)):
                    try:
                        # Для первого результата делаем реплай на команду
                        if i == 0:
                            msg = await message.client.send_message(
                                message.to_id,
                                f"🎵 Результат от @{used_bot}:\n{inline_results[i].title if hasattr(inline_results[i], 'title') else ''}",
                                reply_to=message.id
                            )
                            # Пытаемся отправить сам файл
                            if hasattr(inline_results[i].result, 'document'):
                                await message.client.send_file(
                                    message.to_id,
                                    inline_results[i].result.document,
                                    reply_to=msg.id
                                )
                        else:
                            # Остальные результаты просто отправляем
                            msg = await message.client.send_message(
                                message.to_id,
                                f"🎵 Результат {i+1} от @{used_bot}:\n{inline_results[i].title if hasattr(inline_results[i], 'title') else ''}"
                            )
                            if hasattr(inline_results[i].result, 'document'):
                                await message.client.send_file(
                                    message.to_id,
                                    inline_results[i].result.document,
                                    reply_to=msg.id
                                )
                        
                        sent_messages.append(msg)
                        await asyncio.sleep(0.5)  # Небольшая задержка между отправками
                        
                    except Exception as e:
                        continue
                
                if not sent_messages:
                    error_message = await message.respond("Не удалось отправить результаты")
                    await self.delete_after(error_message, 3)
            else:
                error_message = await message.respond("Музыка не найдена")
                await self.delete_after(error_message, 3)
                
        except Exception as error:
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
