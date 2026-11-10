# notifier.py
"""
Module gửi thông báo cảnh báo Lửa & Khói qua Telegram Bot.
- Gửi kèm ảnh chụp thực tế đã vẽ bounding box và thông tin độ tin cậy, thời gian.
- Có cơ chế giãn cách (cooldown) riêng cho Lửa và Khói để tránh spam tin nhắn.
- Chạy hoàn toàn bất đồng bộ trên luồng nền (non-blocking thread) để không làm giảm FPS camera/AI.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid

import cv2

import config
import display

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, start_listener: bool = True):
        self.enabled = bool(getattr(config, "TELEGRAM_ENABLED", True))
        self.bot_token = (
            os.environ.get("TELEGRAM_BOT_TOKEN")
            or getattr(config, "TELEGRAM_BOT_TOKEN", "")
        ).strip()
        self.chat_id = str(
            os.environ.get("TELEGRAM_CHAT_ID")
            or getattr(config, "TELEGRAM_CHAT_ID", "")
        ).strip()
        self.fire_cooldown = max(
            0.0, float(getattr(config, "TELEGRAM_FIRE_COOLDOWN", 30.0))
        )
        self.smoke_cooldown = max(
            0.0, float(getattr(config, "TELEGRAM_SMOKE_COOLDOWN", 60.0))
        )
        self.timeout = max(
            3.0, float(getattr(config, "TELEGRAM_TIMEOUT", 10.0))
        )

        self._lock = threading.Lock()
        self._last_sent = {"fire": 0.0, "smoke": 0.0}
        self._sending = {"fire": False, "smoke": False}
        self.last_error = None
        self.last_notified_at = None
        self._last_update_id = 0
        self._latest_context = {
            "frame": None,
            "detections": [],
            "fps": 0.0,
            "ai_fps": 0.0,
            "confirmed_fire": False,
            "updated_at": 0.0,
        }

        if self.enabled and self.bot_token and not self.chat_id:
            detected_id = self.auto_detect_chat_id()
            if detected_id:
                self.chat_id = detected_id
                self._save_chat_id_to_config(detected_id)
                print(
                    f"[Telegram] Đã tự động nhận diện và lưu TELEGRAM_CHAT_ID = {self.chat_id} từ tin nhắn /start!"
                )

        if self.is_configured:
            print(
                f"[Telegram] Đã bật thông báo Telegram (Chat ID: {self.chat_id} | "
                f"Cooldown Lửa: {self.fire_cooldown:.0f}s, Khói: {self.smoke_cooldown:.0f}s)."
            )
        elif self.enabled:
            print(
                "[Telegram] Chưa có TELEGRAM_CHAT_ID. Hãy nhắn '/start' vào bot trên Telegram "
                "hoặc điền TELEGRAM_CHAT_ID trong config.py."
            )

        if self.enabled and self.bot_token and start_listener:
            self._listener_thread = threading.Thread(
                target=self._bot_command_listener,
                daemon=True,
                name="TelegramBotListener",
            )
            self._listener_thread.start()

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.bot_token and self.chat_id)

    def _save_chat_id_to_config(self, chat_id: str):
        """Tự động điền TELEGRAM_CHAT_ID vào config.py nếu đang để trống."""
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
        try:
            if not os.path.exists(config_path):
                return
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            new_content, count = re.subn(
                r'^(TELEGRAM_CHAT_ID\s*=\s*)""',
                f'\\1"{chat_id}"',
                content,
                count=1,
                flags=re.MULTILINE,
            )
            if count > 0:
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                config.TELEGRAM_CHAT_ID = chat_id
        except Exception as error:
            logger.debug("Không tự lưu được TELEGRAM_CHAT_ID vào config.py: %s", error)

    def _bot_command_listener(self):
        """Lắng nghe lệnh /start hoặc /id trên Telegram để tự động trả lời Chat ID cho người dùng."""
        while self.enabled and self.bot_token:
            try:
                offset_param = (
                    f"&offset={self._last_update_id + 1}"
                    if self._last_update_id > 0
                    else ""
                )
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?timeout=10{offset_param}"
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "EmberFireSmokeIoT/1.0"},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                for item in data.get("result") or []:
                    update_id = item.get("update_id", 0)
                    if update_id > self._last_update_id:
                        self._last_update_id = update_id
                    msg = item.get("message") or {}
                    text = str(msg.get("text") or "").strip().lower()
                    chat = msg.get("chat") or {}
                    incoming_id = chat.get("id")
                    if incoming_id is None:
                        continue
                    incoming_id_str = str(incoming_id)
                    if not self.chat_id:
                        self.chat_id = incoming_id_str
                        self._save_chat_id_to_config(incoming_id_str)
                        print(
                            f"[Telegram] Đã tự động nhận diện và lưu TELEGRAM_CHAT_ID = {self.chat_id}"
                        )
                    if text.startswith("/start") or text.startswith("/id"):
                        reply = (
                            "👋 Xin chào! Bot giám sát Lửa & Khói IoT đã kết nối.\n"
                            f"🆔 Chat ID của bạn là: {incoming_id_str}\n"
                            "✅ Hệ thống sẽ tự động gửi ảnh cảnh báo khi phát hiện Lửa hoặc Khói.\n\n"
                            "📌 Các lệnh điều khiển từ xa:\n"
                            "• /status — Xem trạng thái hệ thống & FPS hiện tại\n"
                            "• /photo — Chụp và gửi ảnh camera ngay lập tức"
                        )
                        self._send_text_message(reply, target_chat_id=incoming_id_str)
                    elif text.startswith("/status"):
                        self._handle_status_command(incoming_id_str)
                    elif text.startswith("/photo") or text.startswith("/snap") or text.startswith("/anh"):
                        self._handle_photo_command(incoming_id_str)
            except Exception:
                time.sleep(5.0)

    def update_runtime_context(
        self,
        frame,
        detections: list,
        fps: float = 0.0,
        ai_fps: float = 0.0,
        confirmed_fire: bool = False,
    ):
        """Cập nhật frame và trạng thái mới nhất để phục vụ lệnh /status và /photo từ Telegram."""
        with self._lock:
            self._latest_context = {
                "frame": frame,
                "detections": list(detections or []),
                "fps": float(fps or 0.0),
                "ai_fps": float(ai_fps or 0.0),
                "confirmed_fire": bool(confirmed_fire),
                "updated_at": time.time(),
            }

    def _handle_status_command(self, target_chat_id: str):
        with self._lock:
            ctx = dict(self._latest_context)
        if not ctx["updated_at"]:
            self._send_text_message(
                "⏳ Hệ thống đang khởi động hoặc camera chưa sẵn sàng.",
                target_chat_id=target_chat_id,
            )
            return
        dets = ctx["detections"]
        has_smoke = any(d.get("label") == "smoke" for d in dets)
        if ctx["confirmed_fire"]:
            state_str = "🔥 CẢNH BÁO: ĐANG PHÁT HIỆN LỬA!"
        elif has_smoke:
            state_str = "💨 CẢNH BÁO SỚM: ĐANG PHÁT HIỆN KHÓI"
        else:
            state_str = "🟢 AN TOÀN (Không phát hiện lửa/khói)"
        msg = (
            f"📊 TRẠNG THÁI HỆ THỐNG\n"
            f"• Trạng thái: {state_str}\n"
            f"• Thiết bị: {str(getattr(config, 'PLATFORM', 'unknown')).upper()}\n"
            f"• Tốc độ Camera: {ctx['fps']:.1f} FPS\n"
            f"• Tốc độ AI: {ctx['ai_fps']:.1f} FPS\n"
            f"• Cập nhật lúc: {time.strftime('%H:%M:%S - %d/%m/%Y', time.localtime(ctx['updated_at']))}"
        )
        self._send_text_message(msg, target_chat_id=target_chat_id)

    def _handle_photo_command(self, target_chat_id: str):
        with self._lock:
            ctx = dict(self._latest_context)
        frame = ctx.get("frame")
        if frame is None:
            self._send_text_message(
                "⚠️ Hiện chưa có hình ảnh từ camera.",
                target_chat_id=target_chat_id,
            )
            return
        annotated = display.draw_overlay(
            frame.copy(),
            ctx["detections"],
            fps=ctx["fps"],
            ai_fps=ctx["ai_fps"],
        )
        ok, encoded = cv2.imencode(
            ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        )
        caption = (
            f"📷 Ảnh chụp trực tiếp từ camera\n"
            f"🕒 Thời gian: {time.strftime('%H:%M:%S - %d/%m/%Y')}\n"
            f"⚡ Cam: {ctx['fps']:.1f} FPS | AI: {ctx['ai_fps']:.1f} FPS"
        )
        if ok:
            self._send_photo_bytes(
                encoded.tobytes(), caption, target_chat_id=target_chat_id
            )
        else:
            self._send_text_message(caption, target_chat_id=target_chat_id)

    def get_bot_info(self) -> dict:
        """Kiểm tra token và lấy thông tin @username của bot."""
        if not self.bot_token:
            return {}
        url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "EmberFireSmokeIoT/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return data.get("result") or {}

    def auto_detect_chat_id(self, poll_timeout: int = 2) -> str:
        """Tự động lấy chat_id mới nhất từ API getUpdates khi người dùng đã nhắn /start cho bot."""
        if not self.bot_token:
            return ""
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?timeout={int(poll_timeout)}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "EmberFireSmokeIoT/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                req, timeout=max(self.timeout, poll_timeout + 5)
            ) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            results = data.get("result") or []
            for item in reversed(results):
                for key in (
                    "message",
                    "edited_message",
                    "channel_post",
                    "my_chat_member",
                    "chat_member",
                ):
                    obj = item.get(key)
                    if isinstance(obj, dict):
                        chat = obj.get("chat") or obj.get("from") or {}
                        chat_id = chat.get("id")
                        if chat_id is not None:
                            return str(chat_id)
        except Exception as error:
            print(f"[Telegram] Lỗi khi gọi getUpdates: {error}")
        return ""

    def get_status(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled,
                "configured": self.is_configured,
                "last_notified_at": self.last_notified_at,
                "last_error": self.last_error,
            }

    def notify(
        self,
        event_type: str,
        frame,
        detections: list,
        fps: float = None,
        ai_fps: float = None,
    ) -> bool:
        """
        Kiểm tra cooldown và đẩy tác vụ gửi ảnh + cảnh báo sang luồng nền.
        event_type: "fire" hoặc "smoke"
        Trả về True nếu bắt đầu gửi, False nếu bị bỏ qua do cooldown hoặc chưa cấu hình.
        """
        if self.enabled and self.bot_token and not self.chat_id:
            detected_id = self.auto_detect_chat_id()
            if detected_id:
                self.chat_id = detected_id
                print(
                    f"[Telegram] Đã tự động nhận diện TELEGRAM_CHAT_ID = {self.chat_id}!"
                )
        if not self.is_configured or frame is None:
            return False

        event_key = "fire" if event_type == "fire" else "smoke"
        cooldown = self.fire_cooldown if event_key == "fire" else self.smoke_cooldown
        now = time.monotonic()

        with self._lock:
            if self._sending.get(event_key, False):
                return False
            if (
                self._last_sent.get(event_key, 0.0) > 0.0
                and (now - self._last_sent[event_key]) < cooldown
            ):
                return False
            self._sending[event_key] = True
            self._last_sent[event_key] = now

        frame_copy = frame.copy()
        detections_copy = [dict(d) for d in (detections or [])]

        worker = threading.Thread(
            target=self._send_alert_worker,
            args=(event_key, frame_copy, detections_copy, fps, ai_fps),
            daemon=True,
            name=f"TelegramAlert-{event_key}",
        )
        worker.start()
        return True

    def _build_caption(self, event_key: str, detections: list) -> str:
        timestamp_str = time.strftime("%H:%M:%S - %d/%m/%Y")
        platform_str = str(getattr(config, "PLATFORM", "unknown")).upper()

        fire_confs = [
            float(d.get("conf", 0.0))
            for d in detections
            if d.get("label") == "fire"
        ]
        smoke_confs = [
            float(d.get("conf", 0.0))
            for d in detections
            if d.get("label") == "smoke"
        ]

        if event_key == "fire":
            header = "🔥 CẢNH BÁO KHẨN CẤP: PHÁT HIỆN LỬA!"
        else:
            header = "💨 CẢNH BÁO SỚM: PHÁT HIỆN KHÓI!"

        details = []
        if fire_confs:
            details.append(
                f"• Lửa: {len(fire_confs)} vị trí (độ tin cậy cao nhất: {max(fire_confs) * 100:.1f}%)"
            )
        if smoke_confs:
            details.append(
                f"• Khói: {len(smoke_confs)} vị trí (độ tin cậy cao nhất: {max(smoke_confs) * 100:.1f}%)"
            )
        if not details:
            details.append("• Đối tượng: Đã xác nhận qua AI")

        lines = [
            header,
            f"🕒 Thời gian: {timestamp_str}",
            f"📍 Thiết bị: {platform_str}",
            "📊 Chi tiết nhận diện:",
            *details,
        ]
        return "\n".join(lines)

    def _send_alert_worker(
        self,
        event_key: str,
        frame,
        detections: list,
        fps: float,
        ai_fps: float,
    ):
        try:
            annotated = display.draw_overlay(
                frame, detections, fps=fps, ai_fps=ai_fps
            )
            ok, encoded = cv2.imencode(
                ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
            )
            caption = self._build_caption(event_key, detections)

            if ok:
                self._send_photo_bytes(encoded.tobytes(), caption)
            else:
                self._send_text_message(caption)

            with self._lock:
                self.last_notified_at = time.time()
                self.last_error = None
            print(
                f"[Telegram] >>> Đã gửi thông báo cảnh báo ({event_key.upper()}) kèm ảnh thành công! <<<"
            )
        except Exception as error:
            with self._lock:
                self.last_error = str(error)
                # Cho phép thử gửi lại sớm hơn nếu lần gửi trước gặp lỗi mạng
                self._last_sent[event_key] = 0.0
            logger.error("Lỗi khi gửi thông báo Telegram (%s): %s", event_key, error)
            print(f"[Telegram] Lỗi gửi thông báo ({event_key}): {error}")
        finally:
            with self._lock:
                self._sending[event_key] = False

    def _send_photo_bytes(
        self, jpeg_bytes: bytes, caption: str, target_chat_id: str = None
    ):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        boundary = f"----EmberIoTBoundary{uuid.uuid4().hex}"
        body = bytearray()

        def add_field(name: str, value: str):
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
            )
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        add_field("chat_id", target_chat_id or self.chat_id)
        add_field("caption", caption)

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            b'Content-Disposition: form-data; name="photo"; filename="alert.jpg"\r\n'
        )
        body.extend(b"Content-Type: image/jpeg\r\n\r\n")
        body.extend(jpeg_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "EmberFireSmokeIoT/1.0",
            },
            method="POST",
        )
        self._execute_request(req)

    def _send_text_message(self, text: str, target_chat_id: str = None):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = json.dumps(
            {"chat_id": target_chat_id or self.chat_id, "text": text}
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "EmberFireSmokeIoT/1.0",
            },
            method="POST",
        )
        self._execute_request(req)

    def _execute_request(self, req: urllib.request.Request):
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                data = json.loads(raw)
                if not data.get("ok"):
                    raise RuntimeError(data.get("description", "Telegram API trả về lỗi"))
        except urllib.error.HTTPError as http_err:
            err_body = http_err.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                desc = err_json.get("description", err_body)
            except Exception:
                desc = err_body
            raise RuntimeError(f"HTTP {http_err.code}: {desc}") from http_err
        except urllib.error.URLError as url_err:
            raise RuntimeError(f"Lỗi kết nối mạng: {url_err.reason}") from url_err

    def send_test(self, frame=None, detections=None, fps=None, ai_fps=None):
        """Gửi tin nhắn/ảnh kiểm tra kết nối Telegram ngay lập tức."""
        if self.bot_token and not self.chat_id:
            detected_id = self.auto_detect_chat_id()
            if detected_id:
                self.chat_id = detected_id
        if not self.bot_token or not self.chat_id:
            return (
                False,
                "Chưa có TELEGRAM_CHAT_ID. Hãy nhắn '/start' cho bot trên Telegram rồi bấm lại!",
            )
        try:
            timestamp_str = time.strftime("%H:%M:%S - %d/%m/%Y")
            caption = (
                "✅ KIỂM TRA KẾT NỐI TELEGRAM THÀNH CÔNG!\n"
                f"🆔 Chat ID của bạn: {self.chat_id}\n"
                f"🕒 Thời gian: {timestamp_str}\n"
                f"📍 Thiết bị: {str(getattr(config, 'PLATFORM', 'unknown')).upper()}\n"
                "Hệ thống giám sát Lửa & Khói IoT đã sẵn sàng gửi cảnh báo."
            )
            if frame is not None:
                annotated = display.draw_overlay(
                    frame, detections or [], fps=fps, ai_fps=ai_fps
                )
                ok, encoded = cv2.imencode(
                    ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                )
                if ok:
                    self._send_photo_bytes(encoded.tobytes(), caption)
                else:
                    self._send_text_message(caption)
            else:
                self._send_text_message(caption)

            with self._lock:
                self.last_notified_at = time.time()
                self.last_error = None
            return True, "Đã gửi thông báo thử nghiệm về Telegram!"
        except Exception as error:
            with self._lock:
                self.last_error = str(error)
            return False, f"Không gửi được Telegram: {error}"


if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    notifier = TelegramNotifier(start_listener=False)
    try:
        bot_info = notifier.get_bot_info()
        bot_username = bot_info.get("username", "unknown_bot")
        print(f"[Telegram] Kết nối thành công tới Bot: @{bot_username} (Tên: {bot_info.get('first_name', '')})")
    except Exception as err:
        print(f"[LỖI TOKEN] Không kết nối được tới Telegram Bot ({err}). Hãy kiểm tra lại TELEGRAM_BOT_TOKEN trong config.py!")
        sys.exit(1)

    if not notifier.chat_id:
        print(
            f"\n>>> HÃY MỞ TELEGRAM VÀ NHẮN 1 TIN BẤT KỲ (ví dụ: 'hi' hoặc '/start') VÀO BOT @{bot_username} <<<"
        )
        print("Đang chờ tin nhắn của bạn trên Telegram (tối đa 60 giây)...")
        for _ in range(4):
            detected = notifier.auto_detect_chat_id(poll_timeout=15)
            if detected:
                notifier.chat_id = detected
                notifier._save_chat_id_to_config(detected)
                print(f"[THÀNH CÔNG] Đã nhận được Chat ID: {detected} (đã tự động lưu vào config.py!)")
                break

    ok, msg = notifier.send_test()
    print(f"[{'OK' if ok else 'LỖI'}] {msg}")


