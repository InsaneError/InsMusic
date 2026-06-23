from .. import loader, utils
import asyncio
import time
import re
import logging
from telethon.tl.types import Message

logger = logging.getLogger(__name__)


class InsMusic(loader.Module):
    """Модуль для поиска музыки от @InsModule."""

    strings = {'name': 'InsMusic'}

    def __init__(self):
        try:
            self.database = None
            self.client = None
            self.search_lock = asyncio.Lock()
            self.spam_protection = {}
            self.cache = {}
            self.sent_tracks = {}
            self.failed_bots = {}
            super().__init__()
        except Exception as e:
            logger.error(f"Ошибка инициализации InsMusic: {e}")

    async def on_dlmod(self):
        """Вызывается при загрузке модуля"""
        pass

    async def on_unload(self):
        """Вызывается при выгрузке модуля"""
        self.sent_tracks.clear()
        self.cache.clear()
        self.spam_protection.clear()
        self.failed_bots.clear()

    async def client_ready(self, client, database):
        self.client = client
        self.database = database
        
        if not self.database.get("InsMusic", "allowed_chats"):
            self.database.set("InsMusic", "allowed_chats", [])
        
        if not self.database.get("InsMusic", "music_bots"):
            default_bots = ["ShillMusic_bot","AudioBoxrobot","Lybot", "vkm4_bot", "MusicDownloaderBot"]
            self.database.set("InsMusic", "music_bots", default_bots)

        if not self.database.get("InsMusic", "emojis_enabled"):
            self.database.set("InsMusic", "emojis_enabled", True)

    async def _safe_respond(self, message, text):
        """Безопасная отправка ответа с обработкой TOPIC_CLOSED"""
        try:
            return await message.respond(text)
        except Exception as e:
            if "TOPIC_CLOSED" in str(e) or "TOPIC_DELETED" in str(e):
                try:
                    return await self.client.send_message(message.to_id, text)
                except Exception:
                    pass
            raise e

    async def _safe_edit(self, message, text):
        """Безопасное редактирование с обработкой TOPIC_CLOSED"""
        try:
            return await message.edit(text)
        except Exception as e:
            if "TOPIC_CLOSED" in str(e) or "TOPIC_DELETED" in str(e):
                try:
                    await message.delete()
                    return await self.client.send_message(message.to_id, text)
                except Exception:
                    pass
            raise e

    async def _safe_delete(self, message):
        """Безопасное удаление сообщения"""
        try:
            await message.delete()
        except Exception:
            pass

    async def _safe_send_file(self, to_id, file, reply_to=None):
        """Безопасная отправка файла с обработкой TOPIC_CLOSED"""
        try:
            if reply_to:
                try:
                    return await self.client.send_file(to_id, file, reply_to=reply_to)
                except Exception as e:
                    if "TOPIC_CLOSED" in str(e) or "TOPIC_DELETED" in str(e):
                        return await self.client.send_file(to_id, file)
                    raise e
            else:
                return await self.client.send_file(to_id, file)
        except Exception as e:
            if "TOPIC_CLOSED" not in str(e) and "TOPIC_DELETED" not in str(e):
                raise e
            return None

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
    def emojis_enabled(self):
        return self.database.get("InsMusic", "emojis_enabled", True)

    @emojis_enabled.setter
    def emojis_enabled(self, value):
        self.database.set("InsMusic", "emojis_enabled", value)

    def clock_emoji(self):
        """Возвращает эмодзи часов или текст в зависимости от настройки"""
        if self.emojis_enabled:
            return "<emoji document_id=5330324623613533041>⏰</emoji>"
        return ""

    def check_spam(self, user_id):
        """Проверка на спам"""
        if not user_id:
            return True
        current_time = time.time()
        if user_id in self.spam_protection:
            last_time = self.spam_protection[user_id]
            if current_time - last_time < 5:
                return False
        self.spam_protection[user_id] = current_time
        return True

    def _get_chat_id(self, message):
        """Безопасное получение chat_id"""
        try:
            chat_id = str(message.chat_id)
            if chat_id.startswith('-100'):
                chat_id = chat_id[4:]
            elif chat_id.startswith('-'):
                chat_id = chat_id[1:]
            return chat_id
        except Exception:
            try:
                chat_id = str(message.peer_id)
                if chat_id.startswith('-100'):
                    chat_id = chat_id[4:]
                elif chat_id.startswith('-'):
                    chat_id = chat_id[1:]
                return chat_id
            except Exception:
                return str(message.to_id)

    def _get_track_id(self, document):
        """Генерирует уникальный ID для трека на основе его атрибутов"""
        if not document:
            return str(time.time())
        try:
            if hasattr(document, 'id'):
                return str(document.id)
            
            title = ""
            performer = ""
            for attr in document.attributes:
                if hasattr(attr, 'title'):
                    title = attr.title
                if hasattr(attr, 'performer'):
                    performer = attr.performer
            
            if title and performer:
                return f"{performer}-{title}".lower()
            elif title:
                return title.lower()
            elif hasattr(document, 'name') and document.name:
                return document.name.lower()
            
            return str(hash(str(document)))
        except Exception:
            return str(hash(str(document)))

    async def _send_with_reply(self, to_id, file, reply_to_msg):
        """Отправляет файл с учетом темы"""
        try:
            if hasattr(reply_to_msg, 'reply_to') and reply_to_msg.reply_to:
                if hasattr(reply_to_msg.reply_to, 'forum_topic') and reply_to_msg.reply_to.forum_topic:
                    return await self.client.send_file(
                        to_id,
                        file,
                        reply_to=reply_to_msg.id,
                        topic=reply_to_msg.reply_to.reply_to_msg_id
                    )
            
            return await self._safe_send_file(to_id, file, reply_to_msg.id)
        except Exception as e:
            if "TOPIC_CLOSED" in str(e) or "TOPIC_DELETED" in str(e):
                return await self._safe_send_file(to_id, file)
            raise e

    def is_bot_failed(self, bot_username):
        """Проверяет, не заблокирован ли бот для инлайн-режима"""
        if bot_username in self.failed_bots:
            fail_time = self.failed_bots[bot_username]
            if time.time() - fail_time < 3600:
                return True
            else:
                del self.failed_bots[bot_username]
        return False

    def mark_bot_failed(self, bot_username):
        """Помечает бота как недоступного для инлайн-режима на час"""
        self.failed_bots[bot_username] = time.time()

    async def search_in_bot(self, bot_username, query, message):
        """Улучшенный поиск в одном боте с получением нескольких результатов"""
        if self.is_bot_failed(bot_username):
            return []
            
        try:
            results = await asyncio.wait_for(
                message.client.inline_query(bot_username, query),
                timeout=3.0
            )
            
            if not results or not hasattr(results, '__iter__'):
                return []
            
            music_results = []
            
            for i in range(min(len(results), 10)):
                result = results[i]
                if hasattr(result.result, 'document') and result.result.document:
                    try:
                        doc = result.result.document
                        title = ""
                        performer = ""
                        
                        if hasattr(doc, 'attributes'):
                            for attr in doc.attributes:
                                if hasattr(attr, 'title'):
                                    title = attr.title
                                if hasattr(attr, 'performer'):
                                    performer = attr.performer
                        
                        if not title and hasattr(result.result, 'title'):
                            title = result.result.title
                        
                        music_results.append({
                            'bot': bot_username,
                            'document': doc,
                            'title': title,
                            'performer': performer,
                            'raw_title': result.result.title if hasattr(result.result, 'title') else '',
                            'result_id': i,  
                            'original_result': result  
                        })
                    except Exception as e:
                        logger.error(f"Ошибка обработки результата от {bot_username}: {e}")
                        continue
            
            return music_results
            
        except asyncio.TimeoutError:
            return []
        except Exception as e:
            error_str = str(e)
            if "can't be used in inline mode" in error_str or "bot can't be used" in error_str.lower():
                logger.warning(f"Бот {bot_username} не поддерживает инлайн-режим, временно исключен")
                self.mark_bot_failed(bot_username)
            elif "wait" in error_str.lower() and "second" in error_str.lower():
                logger.debug(f"Бот {bot_username} требует ожидания")
            else:
                logger.error(f"Ошибка поиска в боте {bot_username}: {e}")
            return []

    def clean_query(self, query):
        """Очищает запрос от лишних символов"""
        if not query:
            return ""
        query = re.sub(r'[^\w\s-]', ' ', query)
        query = re.sub(r'\s+', ' ', query).strip()
        return query

    def calculate_relevance_score(self, track_info, original_query):
        """Улучшенный расчет релевантности трека с приоритетом на название"""
        if not original_query or not track_info:
            return 0
            
        score = 0
        query_lower = original_query.lower()
        query_words = set(query_lower.split())
        
        title_lower = track_info.get('title', '').lower()
        performer_lower = track_info.get('performer', '').lower()
        raw_title_lower = track_info.get('raw_title', '').lower()
        
        if query_lower == title_lower:
            score += 150
        if query_lower == performer_lower:
            score += 100
        
        if query_lower in title_lower:
            score += 60
        if query_lower in performer_lower:
            score += 40
        
        if query_lower in raw_title_lower:
            score += 30
        
        matched_title_words = 0
        matched_performer_words = 0
        total_words = len(query_words)
        
        for word in query_words:
            if len(word) < 2:
                continue
            
            if word in title_lower:
                matched_title_words += 1
                if len(word) <= 3:
                    score += 15
                else:
                    score += 10
            
            if word in performer_lower:
                matched_performer_words += 1
                score += 8
            
            if word in raw_title_lower:
                score += 5
        
        if total_words > 0 and matched_title_words == total_words:
            score += 30
        
        if total_words > 0 and matched_performer_words == total_words:
            score += 20
        
        if len(query_words) >= 2:
            title_parts = set(title_lower.split())
            performer_parts = set(performer_lower.split())
            
            for part in title_parts:
                if len(part) >= 3 and part in query_lower:
                    score += 8
            
            for part in performer_parts:
                if len(part) >= 3 and part in query_lower:
                    score += 5
        
        if performer_lower and title_lower:
            score += 5
        
        return score

    def extract_track_info_from_document(self, document, raw_title=""):
        """Извлекает информацию о треке из документа"""
        if not document:
            return {'title': '', 'performer': '', 'raw_title': raw_title}
            
        title = ""
        performer = ""
        
        if hasattr(document, 'attributes'):
            for attr in document.attributes:
                if hasattr(attr, 'title'):
                    title = attr.title
                if hasattr(attr, 'performer'):
                    performer = attr.performer
        
        if not title and hasattr(document, 'name') and document.name:
            filename = document.name.lower()
            filename = re.sub(r'\.(mp3|m4a|ogg|flac|wav)$', '', filename)
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
        """Улучшенный поиск по всем ботам с приоритетом названия"""
        if not query:
            return None
            
        cleaned_query = self.clean_query(query)
        
        search_variations = [
            cleaned_query,
            cleaned_query.lower(),
        ]
        
        if len(cleaned_query.split()) > 2:
            words = cleaned_query.split()
            search_variations.append(' '.join(words[:-1]))
        
        inline_bots = [bot for bot in self.music_bots if not self.is_bot_failed(bot)]
        all_results = []
        
        for search_query in search_variations:
            if not search_query:
                continue
                
            search_tasks = []
            for bot_username in inline_bots:
                task = asyncio.create_task(self.search_in_bot(bot_username, search_query, message))
                search_tasks.append(task)
            
            start_time = time.time()
            timeout = 8.0
            
            while time.time() - start_time < timeout and search_tasks:
                completed = [t for t in search_tasks if t.done()]
                
                for task in completed:
                    search_tasks.remove(task)
                        
                    try:
                        results = task.result()
                        if isinstance(results, list) and results:
                            all_results.extend(results)
                            
                            scored_results = []
                            for result in results:
                                if not result or not result.get('document'):
                                    continue
                                
                                track_info = self.extract_track_info_from_document(
                                    result['document'], 
                                    result.get('raw_title', '')
                                )
                                
                                track_info.update({
                                    'bot': result.get('bot', ''),
                                    'document': result['document'],
                                    'result_id': result.get('result_id', 0),
                                    'original_result': result.get('original_result')
                                })
                                
                                score = self.calculate_relevance_score(track_info, cleaned_query)
                                scored_results.append((score, track_info))
                            
                            if scored_results:
                                scored_results.sort(key=lambda x: x[0], reverse=True)
                                best_score, best_result = scored_results[0]
                                
                                if best_score >= 20:
                                    return best_result['document']
                        
                    except Exception as e:
                        logger.error(f"Ошибка обработки результатов: {e}")
                
                if search_tasks:
                    await asyncio.sleep(0.2)
        
        if all_results:
            all_scored_results = []
            for result in all_results:
                if not result or not result.get('document'):
                    continue
                
                track_info = self.extract_track_info_from_document(
                    result['document'], 
                    result.get('raw_title', '')
                )
                
                track_info.update({
                    'bot': result.get('bot', ''),
                    'document': result['document'],
                    'result_id': result.get('result_id', 0),
                    'original_result': result.get('original_result')
                })
                
                score = self.calculate_relevance_score(track_info, cleaned_query)
                
                preferred_bots = ["ShillMusic_bot", "AudioBoxrobot", "vkm4_bot"]
                if track_info['bot'] in preferred_bots:
                    score += 5
                
                all_scored_results.append((score, track_info))
            
            if all_scored_results:
                all_scored_results.sort(key=lambda x: x[0], reverse=True)
                best_score, best_result = all_scored_results[0]
                if best_score >= 10:
                    return best_result['document']
        
        return None

    async def search_music(self, query, message, status_msg=None):
        """Основной метод поиска"""
        if not query:
            return None
        async with self.search_lock:
            result = await self.search_music_all_bots(query, message)
            return result

    async def search_music_inline(self, query, message, offset=0):
        """Поиск музыки для инлайн-режима с возвратом нескольких результатов"""
        if not query:
            return []
            
        cleaned_query = self.clean_query(query)
        
        inline_bots = [bot for bot in self.music_bots if not self.is_bot_failed(bot)]
        all_scored_results = []
        
        for bot_username in inline_bots:
            try:
                results = await self.search_in_bot(bot_username, cleaned_query, message)
                
                if not results:
                    continue
                
                for result in results:
                    if not result or not result.get('document'):
                        continue
                    
                    track_info = self.extract_track_info_from_document(
                        result['document'], 
                        result.get('raw_title', '')
                    )
                    
                    track_info.update({
                        'bot': bot_username,
                        'document': result['document'],
                        'result_id': result.get('result_id', 0),
                        'original_result': result.get('original_result')
                    })
                    
                    score = self.calculate_relevance_score(track_info, cleaned_query)
                    
                    preferred_bots = ["ShillMusic_bot", "AudioBoxrobot", "vkm4_bot", "Lybot"]
                    if bot_username in preferred_bots:
                        score += 10
                    
                    all_scored_results.append((score, track_info))
                    
            except Exception as e:
                logger.error(f"Ошибка при поиске в {bot_username}: {e}")
                continue
        
        if not all_scored_results:
            return []
        
        all_scored_results.sort(key=lambda x: x[0], reverse=True)
        
        unique_results = []
        seen_documents = set()
        
        for score, track_info in all_scored_results:
            doc_id = id(track_info['document'])
            
            if doc_id not in seen_documents:
                seen_documents.add(doc_id)
                unique_results.append(track_info)
            
            if len(unique_results) >= 10:
                break
        
        return unique_results

    async def _execute_search_and_send(self, message, search_query):
        """Общая логика поиска и отправки музыки"""
        if not search_query:
            return
            
        searching_message = None
        try:
            await self._safe_delete(message)
            
            if self.emojis_enabled:
                searching_message = await self._safe_respond(message, self.clock_emoji())

            music_document = await self.search_music(search_query, message, searching_message)

            if searching_message:
                await self._safe_delete(searching_message)

            if not music_document:
                error_message = await self._safe_respond(message, "Музыка не найдена")
                await self.delete_after(error_message, 3)
                return

            await self._send_with_reply(
                message.to_id,
                music_document,
                message
            )

        except Exception as error:
            logger.error(f"Ошибка в _execute_search_and_send: {error}")
            await self._safe_delete(message)
            if searching_message:
                await self._safe_delete(searching_message)
            error_message = await self._safe_respond(message, f"Ошибка: {str(error)}")
            await self.delete_after(error_message, 3)

    @loader.command(
        ru_doc="<название> - Ищет музыку по названию (работает с префиксом)",
        en_doc="<title> - Search music by title (works with prefix)"
    )
    async def мcmd(self, message):
        """Поиск музыки по названию"""
        
        user_id = message.sender_id
        if not self.check_spam(user_id):
            await self._safe_delete(message)
            error_message = await self._safe_respond(message, "Слишком много запросов! Подождите 5 секунд.")
            await self.delete_after(error_message, 3)
            return
        
        search_query = utils.get_args_raw(message)

        if not search_query:
            await self._safe_delete(message)
            error_message = await self._safe_respond(message, "Укажите название песни!")
            await self.delete_after(error_message, 3)
            return

        await self._execute_search_and_send(message, search_query)

    @loader.command(
        ru_doc="<название> - Инлайн-поиск музыки (работает через инлайн)",
        en_doc="<title> - Inline music search (works via inline)"
    )
    async def миcmd(self, message: Message):
        """Инлайн-поиск музыки"""
        args = utils.get_args_raw(message)
        
        if not args:
            await utils.answer(message, "Укажите название песни для поиска!")
            return
        
        await self._safe_delete(message)
        
        emoji_message = None
        if self.emojis_enabled:
            emoji_message = await self._safe_respond(message, self.clock_emoji())
        
        try:
            buttons = await self._build_music_buttons(args, message)
            if buttons:
                await self.inline.form(
                    text="Выберите трек:",
                    message=message,
                    reply_markup=buttons,
                    silent=True
                )
            else:
                error_message = await self._safe_respond(message, "Ничего не найдено")
                await self.delete_after(error_message, 3)
        except Exception as e:
            logger.error(f"Ошибка в миcmd: {e}")
            error_message = await self._safe_respond(message, f"Ошибка: {str(e)}")
            await self.delete_after(error_message, 3)
        finally:
            if emoji_message:
                await self._safe_delete(emoji_message)

    async def _build_music_buttons(self, query: str, message: Message):
        """Создает кнопки с результатами поиска"""
        if not query:
            return [[{"text": "Пустой запрос", "action": "close"}]]
        
        results = await self.search_music_inline(query, message)
        
        if not results:
            return None
        
        buttons = []
        for i, result in enumerate(results[:10], 1):
            
            title = result.get('title', 'Неизвестный трек')
            performer = result.get('performer', '')
            
            if performer:
                display_name = f"{i}. {performer} - {title}"
            else:
                display_name = f"{i}. {title}"
            
            if len(display_name) > 40:
                display_name = display_name[:37] + "..."
            
            buttons.append([{
                "text": f"{display_name}",
                "callback": self._send_music_callback,
                "args": (result['document'], message)
            }])
        
        buttons.append([{"text": "Закрыть", "action": "close"}])
        
        return buttons

    async def _send_music_callback(self, call, document, original_message):
        """Callback для отправки выбранной музыки"""
        try:
            if self.emojis_enabled:
                await call.answer(self.clock_emoji())
            else:
                await call.answer()
            
            await self._safe_delete(call)
            
            await self._send_with_reply(
                original_message.to_id,
                document,
                original_message
            )
            
        except Exception as e:
            logger.error(f"Ошибка в _send_music_callback: {e}")
            await call.answer(f"Ошибка: {str(e)}", show_alert=True)

    async def watcher(self, message):
        """Наблюдатель за сообщениями"""
        if not message or not message.text or len(message.text) < 6:
            return
        
        if not hasattr(message, 'sender_id') or not message.sender_id:
            return

        chat_id = self._get_chat_id(message)
        
        if chat_id not in self.allowed_chats:
            return

        text_lower = message.text.lower()
        
        if text_lower.startswith("найти "):
            user_id = message.sender_id
            if not self.check_spam(user_id):
                await self._safe_delete(message)
                return
            
            search_query = message.text[6:]
            if search_query:
                await self._execute_search_and_send(message, search_query)
        
        elif text_lower.startswith("найтими "):
            user_id = message.sender_id
            if not self.check_spam(user_id):
                await self._safe_delete(message)
                return
            
            search_query = message.text[8:]
            if not search_query:
                return
            
            emoji_message = None
            try:
                await self._safe_delete(message)
                
                if self.emojis_enabled:
                    emoji_message = await self._safe_respond(message, self.clock_emoji())
                
                buttons = await self._build_music_buttons(search_query, message)
                if buttons:
                    await self.inline.form(
                        text="Выберите трек:",
                        message=message,
                        reply_markup=buttons,
                        silent=True
                    )
                else:
                    error_message = await self._safe_respond(message, "Ничего не найдено")
                    await self.delete_after(error_message, 3)
            except Exception as e:
                logger.error(f"Ошибка в watcher найтими: {e}")
                error_message = await self._safe_respond(message, f"Ошибка: {str(e)}")
                await self.delete_after(error_message, 3)
            finally:
                if emoji_message:
                    await self._safe_delete(emoji_message)

    async def delete_after(self, message, seconds):
        """Удаляет сообщение через указанное количество секунд"""
        try:
            await asyncio.sleep(seconds)
            await self._safe_delete(message)
        except Exception:
            pass

    @loader.command(
        ru_doc="Включает/выключает эмодзи в сообщениях модуля",
        en_doc="Toggles emojis in module messages on/off"
    )
    async def котмcmd(self, message):
        """Вкл/Выкл эмодзи"""
        current = self.emojis_enabled
        self.emojis_enabled = not current
        
        if self.emojis_enabled:
            await self._safe_edit(message, f"{self.clock_emoji()} Эмодзи включены")
        else:
            await self._safe_edit(message, "Эмодзи выключены")

    @loader.command(
        ru_doc="Добавляет текущий чат в список разрешенных для команды без префикса",
        en_doc="Adds current chat to the list of allowed chats for prefix-less command"
    )
    async def addmcmd(self, message):
        """Добавить чат для работы без префикса"""
        chat_id = self._get_chat_id(message)
            
        current_allowed_chats = self.allowed_chats.copy()

        if chat_id in current_allowed_chats:
            await self._safe_edit(message, "Этот чат уже в списке разрешенных!")
        else:
            current_allowed_chats.append(chat_id)
            self.allowed_chats = current_allowed_chats
            await self._safe_edit(message, f"Чат добавлен! ID: {chat_id}")

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
            chat_id = self._get_chat_id(message)
            
        current_allowed_chats = self.allowed_chats.copy()

        if chat_id in current_allowed_chats:
            current_allowed_chats.remove(chat_id)
            self.allowed_chats = current_allowed_chats
            await self._safe_edit(message, f"Чат удален! ID: {chat_id}")
        else:
            await self._safe_edit(message, "Этот чат не найден в списке.")

    @loader.command(
        ru_doc="Показывает список чатов, где команда работает без префикса",
        en_doc="Shows list of chats where command works without prefix"
    )
    async def listmcmd(self, message):
        """Список разрешенных чатов"""
        allowed_chats_list = self.allowed_chats
        if not allowed_chats_list:
            await self._safe_edit(message, "Список разрешенных чатов пуст.")
        else:
            text = "Разрешенные чаты:\n\n"
            for chat_id in allowed_chats_list:
                try:
                    if chat_id.lstrip('-').isdigit():
                        chat = await self.client.get_entity(int(chat_id))
                        title = getattr(chat, 'title', 'Личные сообщения')
                        text += f"• {title} ({chat_id})\n"
                    else:
                        text += f"• Неизвестный чат ({chat_id})\n"
                except Exception:
                    text += f"• Неизвестный чат ({chat_id})\n"
            await self._safe_edit(message, text)

    @loader.command(
        ru_doc="Показывает список ботов для поиска музыки",
        en_doc="Shows list of music search bots"
    )
    async def botsmcmd(self, message):
        """Список ботов для поиска"""
        bots = self.music_bots
        if not bots:
            await self._safe_edit(message, "Список ботов пуст!")
            return
            
        text = "Боты для поиска музыки:\n\n"
        for i, bot in enumerate(bots, 1):
            status = " (недоступен)" if self.is_bot_failed(bot) else ""
            text += f"{i}. @{bot}{status}\n"
        await self._safe_edit(message, text)

    @loader.command(
        ru_doc="<юзернейм> - Добавляет бота в список для поиска музыки",
        en_doc="<username> - Adds bot to music search list"
    )
    async def addbotmcmd(self, message):
        """Добавить бота для поиска"""
        args = utils.get_args_raw(message)
        if not args:
            await self._safe_edit(message, "Укажите username бота!")
            return
        
        bot_username = args.replace('@', '').strip()
        if not bot_username:
            await self._safe_edit(message, "Некорректный username бота!")
            return
            
        if bot_username in self.music_bots:
            await self._safe_edit(message, "Этот бот уже есть в списке!")
        else:
            current_bots_list = self.music_bots.copy()
            current_bots_list.append(bot_username)
            self.music_bots = current_bots_list
            await self._safe_edit(message, f"Бот @{bot_username} добавлен в список!")

    @loader.command(
        ru_doc="<юзернейм> - Удаляет бота из списка для поиска музыки",
        en_doc="<username> - Removes bot from music search list"
    )
    async def delbotmcmd(self, message):
        """Удалить бота из поиска"""
        args = utils.get_args_raw(message)
        if not args:
            await self._safe_edit(message, "Укажите username бота!")
            return
        
        bot_username = args.replace('@', '').strip()
        if bot_username in self.music_bots:
            current_bots_list = self.music_bots.copy()
            current_bots_list.remove(bot_username)
            self.music_bots = current_bots_list
            if bot_username in self.failed_bots:
                del self.failed_bots[bot_username]
            await self._safe_edit(message, f"Бот @{bot_username} удален из списка!")
        else:
            await self._safe_edit(message, "Этот бот не найден в списке!")
