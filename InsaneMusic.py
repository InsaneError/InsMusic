from .. import loader, utils
import asyncio
import re


class InsMusic(loader.Module):
    """Модуль для поиска музыки от @InsModule."""

    strings = {'name': 'InsMusic'}

    def __init__(self):
        self.database = None
        self._search_lock = asyncio.Lock()
        super().__init__()

    async def client_ready(self, client, db):
        self.client = client
        self.database = db
        
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

    async def search_in_bot(self, bot_username, query, message):
        """Поиск музыки в конкретном боте с несколькими попытками"""
        search_attempts = []
        
        # Разные варианты запроса для лучшего поиска
        search_variants = [
            query,
            f"{query} music",
            f"{query} mp3",
            f"{query} audio",
            f"{query} песня",
            f"{query} трек"
        ]
        
        for search_variant in search_variants:
            try:
                results = await message.client.inline_query(bot_username, search_variant)
                if results and len(results) > 0:
                    # Возвращаем больше результатов для лучшего выбора
                    search_attempts.extend(results[:10])
            except Exception:
                continue
            
            # Если нашли достаточно результатов, можно прерваться
            if len(search_attempts) >= 5:
                break
        
        return search_attempts[:15]  # Ограничиваем общее количество

    def extract_track_info(self, result):
        """Извлекает информацию о треке из результата"""
        artist = ""
        title = ""
        full_text = ""
        
        # Пробуем разные способы извлечения информации
        if hasattr(result, 'title') and result.title:
            full_text = result.title
        elif hasattr(result, 'description') and result.document:
            full_text = result.description
        
        # Если есть доступ к документу, пробуем получить атрибуты
        if hasattr(result, 'document'):
            doc = result.document
            if hasattr(doc, 'attributes'):
                for attr in doc.attributes:
                    if hasattr(attr, 'performer') and attr.performer:
                        artist = attr.performer
                    if hasattr(attr, 'title') and attr.title:
                        title = attr.title
        
        # Парсим текст для поиска информации
        if not artist or not title:
            # Пробуем найти формат "Исполнитель - Название"
            if " - " in full_text:
                parts = full_text.split(" - ", 1)
                if not artist:
                    artist = parts[0].strip()
                if not title:
                    title = parts[1].strip()
            
            # Пробуем найти в скобках
            elif "(" in full_text and ")" in full_text:
                match = re.search(r'\((.*?)\)', full_text)
                if match and not artist:
                    artist = match.group(1).strip()
            
            # Убираем мусорные слова
            cleanup_words = ["скачать", "слушать", "mp3", "m4a", "flac", "320kbps", "official", "audio", "lyrics"]
            if title:
                for word in cleanup_words:
                    title = title.replace(word, "").strip()
        
        return artist, title, full_text

    def calculate_match_score(self, original_query, artist, title, full_text, document):
        """Вычисляет оценку соответствия результата запросу"""
        score = 0
        query_lower = original_query.lower()
        
        # Подготавливаем тексты для сравнения
        artist_lower = artist.lower() if artist else ""
        title_lower = title.lower() if title else ""
        full_text_lower = full_text.lower() if full_text else ""
        
        # Проверяем совпадение в разных частях
        if query_lower in artist_lower:
            score += 40  # Нашли в исполнителе - самый важный критерий
        elif query_lower in title_lower:
            score += 30  # Нашли в названии
        elif query_lower in full_text_lower:
            score += 20  # Нашли в полном тексте
        
        # Проверяем частичное совпадение слов
        query_words = set(query_lower.split())
        if artist_lower:
            artist_words = set(artist_lower.split())
            common_words = query_words.intersection(artist_words)
            if common_words:
                score += len(common_words) * 10
        
        if title_lower:
            title_words = set(title_lower.split())
            common_words = query_words.intersection(title_words)
            if common_words:
                score += len(common_words) * 8
        
        # Бонус за качество файла
        if hasattr(document, 'size'):
            if document.size > 2000000:  # Больше 2MB
                score += 25
            elif document.size > 1000000:  # Больше 1MB
                score += 15
            elif document.size > 500000:  # Больше 500KB
                score += 5
        
        # Бонус за формат "Исполнитель - Название"
        if artist and title:
            score += 20
        
        # Бонус за определенные ключевые слова (качество)
        quality_indicators = ["320", "flac", "hq", "high quality", "lossless"]
        for indicator in quality_indicators:
            if indicator in full_text_lower:
                score += 10
                break
        
        # Штраф за нежелательные слова
        bad_indicators = ["remix", "cover", "karaoke", "instrumental", "минус", "минусовка"]
        for indicator in bad_indicators:
            if indicator in full_text_lower:
                score -= 15
                break
        
        return score

    async def search_all_bots_concurrent(self, query, message):
        """Ищет музыку во всех ботах одновременно"""
        search_tasks = []
        
        # Запускаем поиск во всех ботах
        for bot_username in self.music_bots:
            task = asyncio.create_task(self.search_in_bot(bot_username, query, message))
            search_tasks.append(task)
        
        # Ждем результаты с таймаутом
        try:
            all_results = await asyncio.wait_for(
                asyncio.gather(*search_tasks, return_exceptions=True),
                timeout=10.0  # Увеличиваем таймаут
            )
        except asyncio.TimeoutError:
            # Возвращаем то, что успели собрать
            completed = []
            for task in search_tasks:
                if task.done() and not task.cancelled():
                    try:
                        completed.append(task.result())
                    except:
                        continue
            all_results = completed
        
        # Собираем все результаты
        all_valid_results = []
        for result in all_results:
            if isinstance(result, list):
                all_valid_results.extend(result)
        
        return all_valid_results

    def find_best_track(self, all_results, original_query):
        """Находит лучший трек из всех результатов"""
        best_result = None
        best_score = -1
        
        for result in all_results:
            if not hasattr(result, 'document'):
                continue
            
            # Извлекаем информацию о треке
            artist, title, full_text = self.extract_track_info(result)
            
            # Вычисляем оценку
            score = self.calculate_match_score(original_query, artist, title, full_text, result.document)
            
            # Обновляем лучший результат
            if score > best_score:
                best_score = score
                best_result = result
        
        # Если лучший результат имеет низкий балл (меньше 20), возможно лучше ничего не возвращать
        if best_result and best_score >= 10:  # Снижаем минимальный порог
            return best_result.document
        
        return None

    async def search_music(self, query, message):
        """Основная функция поиска с улучшенной логикой"""
        async with self._search_lock:
            # Собираем все результаты от всех ботов
            all_results = await self.search_all_bots_concurrent(query, message)
            
            if not all_results:
                # Пробуем альтернативный подход - убираем лишние слова
                clean_query = self.clean_search_query(query)
                if clean_query != query:
                    all_results = await self.search_all_bots_concurrent(clean_query, message)
            
            # Выбираем лучший результат
            if all_results:
                return self.find_best_track(all_results, query)
            
            return None

    def clean_search_query(self, query):
        """Очищает запрос от лишних слов"""
        # Удаляем указания на качество и формат
        cleanup_patterns = [
            r'\d{3,4}kbps?', r'\d{3,4}k', 
            r'скачать', r'слушать', r'mp3', r'm4a', r'flac',
            r'официальный', r'official', r'audio', r'музыка'
        ]
        
        cleaned = query
        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Убираем лишние пробелы
        cleaned = ' '.join(cleaned.split())
        
        # Если очистка удалила всё, возвращаем оригинал
        return cleaned if cleaned.strip() else query

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
            search_msg = await message.respond(f"<emoji document_id=5330324623613533041>🔍</emoji> Ищу музыку...")

            music_doc = await self.search_music(args, message)

            if not music_doc:
                await search_msg.edit("❌ Музыка не найдена\n\nПопробуйте:\n• Указать исполнителя\n• Проверить название\n• Использовать английские слова")
                await self.delete_after(search_msg, 5)
                return

            await search_msg.edit("<emoji document_id=5330324623613533041>✅</emoji> Найдено! Отправляю...")
            await asyncio.sleep(1)
            await search_msg.delete()
            
            await message.client.send_file(
                message.to_id,
                music_doc,
                reply_to=reply.id if reply else None,
                caption=f"🎵 По запросу: {args}"
            )

        except Exception as e:
            await message.delete()
            error_msg = await message.respond(f"⚠️ Ошибка: {str(e)}")
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
                search_msg = await message.respond(f"<emoji document_id=5330324623613533041>🔍</emoji> Ищу...")

                music_doc = await self.search_music(args, message)

                if not music_doc:
                    await search_msg.edit("❌ Музыка не найдена")
                    await self.delete_after(search_msg, 3)
                    return

                await search_msg.delete()
                await message.client.send_file(
                    message.to_id,
                    music_doc,
                    caption=f"🎵 По запросу: {args}"
                )

            except Exception as e:
                await message.delete()
                error_msg = await message.respond(f"⚠️ Ошибка: {str(e)}")
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
