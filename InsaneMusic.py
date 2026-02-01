from .. import loader, utils
import asyncio
import time
import re
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class InsMusic(loader.Module):
    """Модуль для поиска музыки от @InsModule."""

    strings = {'name': 'InsMusic'}

    def __init__(self):
        self.database = None
        self.search_lock = asyncio.Lock()
        self.spam_protection = {}
        self.cache = {}  # Кэш результатов поиска
        self.channel_cache = {}  # Кэш для канала с результатами
        super().__init__()

    async def client_ready(self, client, database):
        self.client = client
        self.database = database
        
        # Инициализация настроек
        defaults = {
            "allowed_chats": [],
            "music_bots": ["ShillMusic_bot", "AudioBoxrobot", "Lybot", "vkm4_bot", 
                          "MusicDownloaderBot", "DeezerMusicBot", "SpotifyDownloaderBot", "shazambot"],
            "results_channel": None,
            "cache_enabled": True,
            "cache_ttl": 300,  # 5 минут
            "max_workers": 5,
            "preferred_bots": [],
            "quality_priority": True,
            "smart_search": True
        }
        
        for key, value in defaults.items():
            if not self.database.get("InsMusic", key):
                self.database.set("InsMusic", key, value)

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

    @property
    def results_channel(self):
        return self.database.get("InsMusic", "results_channel")

    @results_channel.setter
    def results_channel(self, value):
        self.database.set("InsMusic", "results_channel", value)

    @property
    def cache_enabled(self):
        return self.database.get("InsMusic", "cache_enabled", True)

    @property
    def cache_ttl(self):
        return self.database.get("InsMusic", "cache_ttl", 300)

    @property
    def max_workers(self):
        return self.database.get("InsMusic", "max_workers", 5)

    @property
    def preferred_bots(self):
        return self.database.get("InsMusic", "preferred_bots", [])

    @property
    def quality_priority(self):
        return self.database.get("InsMusic", "quality_priority", True)

    @property
    def smart_search(self):
        return self.database.get("InsMusic", "smart_search", True)

    def check_spam(self, user_id):
        """Проверка на спам с очисткой старых записей"""
        current_time = time.time()
        
        # Очищаем старые записи
        expired = [uid for uid, t in self.spam_protection.items() 
                  if current_time - t > 30]
        for uid in expired:
            del self.spam_protection[uid]
        
        if user_id in self.spam_protection:
            last_time = self.spam_protection[user_id]
            if current_time - last_time < 3:  # 3 секунды между запросами
                return False
        self.spam_protection[user_id] = current_time
        return True

    def normalize_query(self, query: str) -> str:
        """Нормализация поискового запроса"""
        query = query.lower().strip()
        
        # Удаляем лишние слова
        stop_words = {'скачать', 'слушать', 'музыка', 'песня', 'трек', 'mp3', 'music'}
        words = [word for word in query.split() if word not in stop_words]
        
        # Удаляем символы, которые могут мешать поиску
        query = ' '.join(words)
        query = re.sub(r'[^\w\s\-]', '', query)
        
        return query

    def build_cache_key(self, query: str, bot_username: str = None) -> str:
        """Создание ключа для кэша"""
        normalized = self.normalize_query(query)
        if bot_username:
            return f"{bot_username}:{normalized}"
        return f"global:{normalized}"

    def get_from_cache(self, key: str) -> Optional[Dict]:
        """Получение результата из кэша"""
        if not self.cache_enabled:
            return None
            
        if key in self.cache:
            cached_data = self.cache[key]
            if time.time() - cached_data['timestamp'] < self.cache_ttl:
                return cached_data['data']
            else:
                del self.cache[key]
        return None

    def save_to_cache(self, key: str, data: Dict):
        """Сохранение результата в кэш"""
        if self.cache_enabled:
            self.cache[key] = {
                'data': data,
                'timestamp': time.time()
            }

    async def search_in_bot_optimized(self, bot_username: str, query: str, message) -> Optional[Dict]:
        """Оптимизированный поиск в боте"""
        cache_key = self.build_cache_key(query, bot_username)
        cached = self.get_from_cache(cache_key)
        if cached:
            logger.info(f"Cache hit for {bot_username}: {query}")
            return cached

        try:
            # Пробуем разные варианты поискового запроса
            search_variants = []
            
            if self.smart_search:
                # Основной запрос
                search_variants.append(query)
                
                # Без года в скобках
                query_no_year = re.sub(r'\([0-9]{4}\)', '', query).strip()
                if query_no_year and query_no_year != query:
                    search_variants.append(query_no_year)
                
                # Только исполнитель + название (если есть дефис или тире)
                if ' - ' in query:
                    parts = query.split(' - ', 1)
                    search_variants.append(parts[0])  # Только исполнитель
                    search_variants.append(parts[1])  # Только название
            
            else:
                search_variants = [query]

            # Пробуем каждый вариант поиска
            for search_variant in search_variants:
                try:
                    # Используем более быстрый метод с меньшим таймаутом
                    results = await asyncio.wait_for(
                        message.client.inline_query(bot_username, search_variant),
                        timeout=1.5  # Уменьшенный таймаут
                    )
                    
                    if results:
                        # Сортируем результаты по релевантности
                        sorted_results = sorted(
                            results,
                            key=lambda x: self.calculate_relevance(x, query),
                            reverse=True
                        )
                        
                        for result in sorted_results[:3]:  # Проверяем топ-3 результата
                            if hasattr(result, 'result') and hasattr(result.result, 'document'):
                                doc = result.result.document
                                if self.is_valid_audio(doc):
                                    result_data = self.extract_track_info(doc, result)
                                    if result_data and self.is_good_match(result_data, query):
                                        # Сохраняем в кэш перед возвратом
                                        result_data['bot'] = bot_username
                                        result_data['query_variant'] = search_variant
                                        self.save_to_cache(cache_key, result_data)
                                        return result_data
                except (asyncio.TimeoutError, Exception) as e:
                    logger.debug(f"Search variant failed for {bot_username}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error searching in {bot_username}: {e}")
        
        return None

    def is_valid_audio(self, document) -> bool:
        """Проверяет, является ли документ аудиофайлом"""
        if not hasattr(document, 'mime_type'):
            return False
        
        mime_type = document.mime_type.lower()
        return any(audio_type in mime_type for audio_type in 
                  ['audio/', 'ogg', 'flac', 'm4a', 'aac', 'wav'])

    def extract_track_info(self, document, result) -> Dict:
        """Извлекает информацию о треке из документа"""
        info = {
            'document': document,
            'title': '',
            'performer': '',
            'duration': 0,
            'size': document.size if hasattr(document, 'size') else 0,
            'quality': self.estimate_quality(document)
        }
        
        if hasattr(document, 'attributes'):
            for attr in document.attributes:
                if hasattr(attr, 'title'):
                    info['title'] = attr.title
                if hasattr(attr, 'performer'):
                    info['performer'] = attr.performer
                if hasattr(attr, 'duration'):
                    info['duration'] = attr.duration
        
        # Пробуем извлечь из описания инлайн результата
        if hasattr(result, 'description') and result.description:
            desc = result.description
            if ' - ' in desc and not info['performer']:
                parts = desc.split(' - ', 1)
                if not info['performer']:
                    info['performer'] = parts[0]
                if not info['title']:
                    info['title'] = parts[1]
        
        return info

    def estimate_quality(self, document) -> int:
        """Оценивает качество аудиофайла"""
        score = 0
        
        # По размеру файла (примерные оценки)
        if hasattr(document, 'size'):
            size_mb = document.size / (1024 * 1024)
            if size_mb > 8:
                score += 30  # FLAC или высококачественный MP3
            elif size_mb > 3:
                score += 20  # Хороший MP3
            elif size_mb > 1:
                score += 10  # Средний битрейт
        
        # По MIME-типу
        if hasattr(document, 'mime_type'):
            mime = document.mime_type.lower()
            if 'flac' in mime:
                score += 40
            elif 'wav' in mime:
                score += 35
            elif 'm4a' in mime or 'aac' in mime:
                score += 25
            elif 'ogg' in mime:
                score += 15
        
        return score

    def calculate_relevance(self, result, query: str) -> int:
        """Рассчитывает релевантность результата"""
        score = 0
        query_lower = query.lower()
        
        # Проверяем описание и заголовок
        text_to_check = []
        if hasattr(result, 'title'):
            text_to_check.append(result.title.lower())
        if hasattr(result, 'description'):
            text_to_check.append(result.description.lower())
        
        for text in text_to_check:
            # Точное совпадение (исполнитель - название)
            if ' - ' in text:
                parts = text.split(' - ', 1)
                if query_lower in text or text in query_lower:
                    score += 50
                
                # Проверяем каждую часть отдельно
                for part in parts:
                    if any(word in part for word in query_lower.split()):
                        score += 10
                    
                    # Частичное совпадение слов
                    query_words = set(query_lower.split())
                    part_words = set(part.split())
                    common = query_words.intersection(part_words)
                    if common:
                        score += len(common) * 5
            
            # Проверяем отдельные слова
            for word in query_lower.split():
                if len(word) > 2 and word in text:
                    score += 3
        
        return score

    def is_good_match(self, track_info: Dict, query: str) -> bool:
        """Определяет, является ли результат хорошим совпадением"""
        query_lower = query.lower()
        
        # Если нет исполнителя или названия - плохой матч
        if not track_info['title'] and not track_info['performer']:
            return False
        
        # Собираем весь текст для проверки
        text_to_check = []
        if track_info['performer']:
            text_to_check.append(track_info['performer'].lower())
        if track_info['title']:
            text_to_check.append(track_info['title'].lower())
        
        full_text = ' '.join(text_to_check)
        
        # Основные слова запроса должны присутствовать
        important_words = [w for w in query_lower.split() if len(w) > 2]
        if important_words:
            matches = sum(1 for word in important_words if word in full_text)
            if matches < len(important_words) * 0.5:  # Должно совпасть хотя бы 50% важных слов
                return False
        
        return True

    async def search_music_all_bots(self, query: str, message):
        """Параллельный поиск во всех ботах с приоритетами"""
        normalized_query = self.normalize_query(query)
        
        # Проверяем кэш
        cache_key = self.build_cache_key(query)
        cached = self.get_from_cache(cache_key)
        if cached:
            return cached.get('document')
        
        # Сортируем ботов: сначала предпочтительные, потом остальные
        bots_to_search = []
        bots_to_search.extend(self.preferred_bots)
        bots_to_search.extend([b for b in self.music_bots if b not in self.preferred_bots])
        
        # Ограничиваем количество одновременно работающих ботов
        bots_to_search = bots_to_search[:self.max_workers]
        
        # Запускаем поиск во всех ботах одновременно
        tasks = []
        for bot in bots_to_search:
            task = asyncio.create_task(
                self.search_in_bot_optimized(bot, normalized_query, message)
            )
            tasks.append(task)
        
        # Используем asyncio.as_completed для получения первого успешного результата
        completed_tasks = []
        try:
            for task in asyncio.as_completed(tasks, timeout=3.0):
                try:
                    result = await task
                    if result:
                        # Сохраняем успешный результат в кэш
                        self.save_to_cache(cache_key, result)
                        
                        # Сохраняем в канал результатов если настроено
                        await self.save_to_results_channel(result, query)
                        
                        return result['document']
                except (asyncio.TimeoutError, Exception) as e:
                    logger.debug(f"Task failed: {e}")
                    continue
        except asyncio.TimeoutError:
            pass
        
        # Если быстрого результата нет, ждем оставшиеся задачи
        try:
            remaining_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=2.0
            )
            
            # Ищем лучший результат среди всех
            valid_results = []
            for result in remaining_results:
                if isinstance(result, dict) and result:
                    valid_results.append(result)
            
            if valid_results:
                # Выбираем лучший результат по качеству и релевантности
                best_result = self.select_best_result(valid_results, query)
                if best_result:
                    self.save_to_cache(cache_key, best_result)
                    await self.save_to_results_channel(best_result, query)
                    return best_result['document']
                    
        except asyncio.TimeoutError:
            pass
        
        return None

    def select_best_result(self, results: List[Dict], query: str) -> Optional[Dict]:
        """Выбирает лучший результат из нескольких"""
        if not results:
            return None
        
        best_result = None
        best_score = -1
        
        for result in results:
            score = 0
            
            # Приоритет качества (если включен)
            if self.quality_priority:
                score += result.get('quality', 0)
            
            # Релевантность
            relevance = self.calculate_match_score(result, query)
            score += relevance * 10
            
            # Размер файла (предпочитаем большие файлы - лучше качество)
            score += min(result.get('size', 0) // (1024 * 1024), 20)
            
            # Приоритет предпочтительным ботам
            if result.get('bot') in self.preferred_bots:
                score += 15
            
            if score > best_score:
                best_score = score
                best_result = result
        
        return best_result

    def calculate_match_score(self, result: Dict, query: str) -> int:
        """Рассчитывает score совпадения"""
        score = 0
        query_lower = query.lower()
        
        # Проверяем исполнителя
        performer = result.get('performer', '').lower()
        if performer:
            if performer in query_lower:
                score += 30
            elif any(word in query_lower for word in performer.split()):
                score += 20
        
        # Проверяем название
        title = result.get('title', '').lower()
        if title:
            if title in query_lower:
                score += 25
            elif any(word in query_lower for word in title.split()):
                score += 15
        
        # Полное совпадение "исполнитель - название"
        if performer and title:
            full_track = f"{performer} - {title}"
            if full_track in query_lower or query_lower in full_track:
                score += 50
        
        return score

    async def save_to_results_channel(self, track_info: Dict, query: str):
        """Сохраняет найденный трек в канал результатов"""
        if not self.results_channel:
            return
        
        try:
            channel_id = int(self.results_channel)
            
            # Формируем описание
            caption_parts = []
            if track_info.get('performer'):
                caption_parts.append(f"🎤 Исполнитель: {track_info['performer']}")
            if track_info.get('title'):
                caption_parts.append(f"🎵 Название: {track_info['title']}")
            if track_info.get('duration'):
                minutes = track_info['duration'] // 60
                seconds = track_info['duration'] % 60
                caption_parts.append(f"⏱ Длительность: {minutes}:{seconds:02d}")
            if track_info.get('bot'):
                caption_parts.append(f"🤖 Источник: @{track_info['bot']}")
            
            caption_parts.append(f"🔍 Поисковый запрос: {query}")
            
            caption = "\n".join(caption_parts)
            
            # Сохраняем в канал
            await self.client.send_file(
                channel_id,
                track_info['document'],
                caption=caption
            )
            
            # Сохраняем в локальный кэш для быстрого поиска по каналу
            cache_key = f"channel:{track_info.get('performer', '').lower()}:{track_info.get('title', '').lower()}"
            self.channel_cache[cache_key] = {
                'document': track_info['document'],
                'info': track_info,
                'timestamp': time.time()
            }
            
            # Ограничиваем размер кэша
            if len(self.channel_cache) > 1000:
                # Удаляем старые записи
                oldest = sorted(self.channel_cache.items(), key=lambda x: x[1]['timestamp'])[:100]
                for key in [k for k, _ in oldest]:
                    del self.channel_cache[key]
                    
        except Exception as e:
            logger.error(f"Error saving to results channel: {e}")

    async def search_in_results_channel(self, query: str):
        """Ищет трек в сохраненных результатах"""
        if not self.results_channel or not self.channel_cache:
            return None
        
        normalized_query = self.normalize_query(query)
        query_parts = set(normalized_query.split())
        
        best_match = None
        best_score = 0
        
        for cache_key, data in self.channel_cache.items():
            # Проверяем TTL кэша канала
            if time.time() - data['timestamp'] > 86400:  # 24 часа
                continue
            
            info = data['info']
            score = 0
            
            # Проверяем совпадение с исполнителем
            performer = info.get('performer', '').lower()
            if performer:
                performer_words = set(performer.split())
                common_performer = query_parts.intersection(performer_words)
                if common_performer:
                    score += len(common_performer) * 5
            
            # Проверяем совпадение с названием
            title = info.get('title', '').lower()
            if title:
                title_words = set(title.split())
                common_title = query_parts.intersection(title_words)
                if common_title:
                    score += len(common_title) * 3
            
            # Полное совпадение
            if performer and title:
                full_match = f"{performer} {title}"
                if normalized_query in full_match or full_match in normalized_query:
                    score += 20
            
            if score > best_score and score > 2:
                best_score = score
                best_match = data['document']
        
        return best_match

    async def search_music(self, query: str, message):
        """Основная функция поиска музыки"""
        async with self.search_lock:
            # Сначала пробуем найти в сохраненных результатах
            if self.results_channel:
                cached_result = await self.search_in_results_channel(query)
                if cached_result:
                    logger.info("Found in results channel cache")
                    return cached_result
            
            # Затем ищем в ботах
            return await self.search_music_all_bots(query, message)

    @loader.command(
        ru_doc="<id/юзернейм> - Устанавливает канал для сохранения найденной музыки",
        en_doc="<id/username> - Sets channel for saving found music"
    )
    async def setchannelmcmd(self, message):
        """Установить канал для сохранения результатов"""
        args = utils.get_args_raw(message)
        
        if not args:
            await message.edit("Укажите ID канала или его username!")
            return
        
        try:
            # Пробуем получить сущность канала
            try:
                channel = await self.client.get_entity(args)
            except Exception:
                await message.edit("Не удалось найти канал. Проверьте правильность ввода.")
                return
            
            # Сохраняем ID канала
            self.results_channel = channel.id
            await message.edit(f"✅ Канал установлен: {getattr(channel, 'title', 'Unknown')}\nID: {channel.id}")
            
            # Очищаем кэш канала
            self.channel_cache.clear()
            
        except Exception as e:
            await message.edit(f"Ошибка: {str(e)}")

    @loader.command(
        ru_doc="Показывает текущий канал для сохранения результатов",
        en_doc="Shows current results saving channel"
    )
    async def channelmcmd(self, message):
        """Показать текущий канал результатов"""
        if not self.results_channel:
            await message.edit("Канал для сохранения результатов не установлен.")
        else:
            try:
                channel = await self.client.get_entity(int(self.results_channel))
                title = getattr(channel, 'title', 'Unknown')
                await message.edit(f"📁 Текущий канал: {title}\nID: {self.results_channel}")
            except Exception:
                await message.edit(f"Канал не найден. ID: {self.results_channel}")

    @loader.command(
        ru_doc="<true/false> - Включить/выключить кэширование результатов",
        en_doc="<true/false> - Enable/disable result caching"
    )
    async def cachemcmd(self, message):
        """Управление кэшированием"""
        args = utils.get_args_raw(message).lower()
        
        if args == 'true':
            self.database.set("InsMusic", "cache_enabled", True)
            await message.edit("✅ Кэширование включено")
        elif args == 'false':
            self.database.set("InsMusic", "cache_enabled", False)
            self.cache.clear()
            await message.edit("❌ Кэширование выключено")
        else:
            status = "включено" if self.cache_enabled else "выключено"
            await message.edit(f"Текущий статус кэширования: {status}")

    @loader.command(
        ru_doc="<боты через пробел> - Установить предпочтительных ботов для поиска",
        en_doc="<bots separated by space> - Set preferred bots for search"
    )
    async def setpreferredmcmd(self, message):
        """Установить предпочтительных ботов"""
        args = utils.get_args_raw(message)
        
        if not args:
            current = self.preferred_bots
            if current:
                await message.edit(f"Предпочтительные боты:\n" + "\n".join(f"• @{bot}" for bot in current))
            else:
                await message.edit("Предпочтительные боты не установлены.")
            return
        
        bots = [bot.replace('@', '').strip() for bot in args.split()]
        self.database.set("InsMusic", "preferred_bots", bots)
        await message.edit(f"✅ Установлено {len(bots)} предпочтительных ботов")

    @loader.command(
        ru_doc="Очистить кэш поиска",
        en_doc="Clear search cache"
    )
    async def clearcachemcmd(self, message):
        """Очистить кэш"""
        self.cache.clear()
        self.channel_cache.clear()
        await message.edit("✅ Кэш очищен")

    @loader.command(
        ru_doc="Показать статистику кэша",
        en_doc="Show cache statistics"
    )
    async def cachestatsmcmd(self, message):
        """Статистика кэша"""
        main_cache_size = len(self.cache)
        channel_cache_size = len(self.channel_cache)
        
        text = f"📊 Статистика кэша:\n\n"
        text += f"Основной кэш: {main_cache_size} записей\n"
        text += f"Кэш канала: {channel_cache_size} записей\n"
        text += f"Кэширование: {'✅ Включено' if self.cache_enabled else '❌ Выключено'}\n"
        text += f"TTL: {self.cache_ttl} секунд"
        
        await message.edit(text)

    # Остальные команды (мcmd, addmcmd, delmcmd и т.д.) остаются без изменений
    # ...

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
        
        # Расширенный поиск триггеров
        search_triggers = ["найти ", "поиск ", "music ", "song ", "скачать "]
        
        for trigger in search_triggers:
            if text_lower.startswith(trigger):
                # Проверка на спам
                user_id = message.sender_id
                if not self.check_spam(user_id):
                    await message.delete()
                    return
                
                search_query = message.text[len(trigger):].strip()
                
                try:
                    await message.delete()
                    searching_message = await message.respond(
                        f"🔍 Ищу: {search_query[:50]}..."
                    )

                    music_document = await self.search_music(search_query, message)

                    if not music_document:
                        await searching_message.edit("❌ Музыка не найдена")
                        await self.delete_after(searching_message, 3)
                        return

                    await searching_message.delete()
                    
                    # Отправляем результат
                    await message.client.send_file(
                        message.to_id,
                        music_document,
                        reply_to=message.id,
                        caption=f"🎵 Найдено по запросу: {search_query}"
                    )

                except Exception as error:
                    await message.delete()
                    error_message = await message.respond(f"⚠️ Ошибка: {str(error)}")
                    await self.delete_after(error_message, 3)
                break

    async def delete_after(self, message, seconds):
        await asyncio.sleep(seconds)
        try:
            await message.delete()
        except:
            pass
