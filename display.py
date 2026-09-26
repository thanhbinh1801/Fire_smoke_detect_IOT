# display.py
"""
Module hiển thị hình ảnh trực tiếp lên màn hình (qua OpenCV GUI).
- Vẽ bounding box, nhãn và confidence.
- Đổi màu viền toàn màn hình khi có báo động (Đỏ: Cháy/Khói, Xanh: An toàn).
- Hiển thị FPS thời gian thực.
"""

import cv2
import config

def draw_overlay(frame, detections, fps=None):
    """
    Vẽ thông tin nhận diện và trạng thái lên frame.
    Trả về frame đã vẽ.
    """
    h, w = frame.shape[:2]

    if detections:
        # 1. Viền đỏ cảnh báo toàn khung hình để nhận diện từ xa
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 6)

        # 2. Thanh banner cảnh báo ở trên cùng
        cv2.rectangle(frame, (0, 0), (w, 50), (0, 0, 200), -1)
        cv2.putText(
            frame, "!!! CANH BAO CHAY / KHOI !!!", (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA
        )

        # 3. Vẽ bounding box từng đối tượng
        for d in detections:
            x1, y1, x2, y2 = d["box"]
            label = d["label"]
            conf = d["conf"]

            # Phân màu: Lửa dùng màu Đỏ Cam, Khói dùng màu Vàng Cam / Xám
            is_fire = "fire" in label.lower()
            box_color = (0, 0, 255) if is_fire else (0, 165, 255)

            # Bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)

            # Tag nhãn phía trên box
            tag_text = f"{label} {conf:.2f}"
            (text_w, text_h), baseline = cv2.getTextSize(
                tag_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
            )
            tag_y1 = max(y1 - text_h - 8, 55)
            tag_y2 = tag_y1 + text_h + 6
            cv2.rectangle(frame, (x1, tag_y1), (x1 + text_w + 6, tag_y2), box_color, -1)
            cv2.putText(
                frame, tag_text, (x1 + 3, tag_y2 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA
            )
    else:
        # Trạng thái an toàn bình thường
        cv2.rectangle(frame, (0, 0), (w, 40), (40, 40, 40), -1)
        cv2.putText(
            frame, "TRANG THAI: AN TOAN", (15, 28),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 230, 0), 2, cv2.LINE_AA
        )

    # Hiển thị FPS góc dưới bên trái
    if fps is not None:
        cv2.putText(
            frame, f"FPS: {fps:.1f}", (15, h - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2, cv2.LINE_AA
        )

    return frame

def show(frame):
    """
    Hiện frame lên cửa sổ.
    Trả về False nếu người dùng nhấn phím 'q' hoặc 'ESC' để thoát.
    """
    cv2.imshow(config.WINDOW_NAME, frame)
    key = cv2.waitKey(1) & 0xFF
    return key not in (ord('q'), 27)

def close():
    """Đóng tất cả cửa sổ OpenCV"""
    cv2.destroyAllWindows()
