# display.py
"""
Module hiển thị hình ảnh trực tiếp lên màn hình (qua OpenCV GUI).
- Vẽ bounding box, nhãn và confidence.
- Đổi màu viền toàn màn hình khi có báo động (Đỏ: Phát hiện lửa, Xanh: An toàn).
- Hiển thị FPS thời gian thực.
- Hỗ trợ phím nóng:
  + 'f': Kích hoạt lấy nét tự động (Autofocus)
  + '[' / ']': Chỉnh tiêu cự lấy nét gần/xa thủ công
  + 'q' hoặc ESC: Thoát
"""

import cv2
import config

def draw_overlay(frame, detections, fps=None, ai_fps=None):
    """
    Vẽ thông tin nhận diện và trạng thái lên frame.
    Trả về frame đã vẽ (định dạng BGR cho OpenCV imshow).
    """
    h, w = frame.shape[:2]

    # Frame từ camera đã ở dạng BGR chuẩn hiển thị cho OpenCV imshow
    render_frame = frame.copy()

    if detections:
        # 1. Viền đỏ cảnh báo toàn khung hình để nhận diện từ xa
        cv2.rectangle(render_frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 6)

        # 2. Thanh banner cảnh báo ở trên cùng
        cv2.rectangle(render_frame, (0, 0), (w, 50), (0, 0, 200), -1)
        cv2.putText(
            render_frame, "!!! CANH BAO: PHAT HIEN LUA !!!", (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA
        )

        # 3. Vẽ bounding box từng đối tượng lửa
        for d in detections:
            x1, y1, x2, y2 = d["box"]
            label = d["label"]
            conf = d["conf"]

            box_color = (0, 0, 255)  # Màu đỏ cho lửa

            # Bounding box
            cv2.rectangle(render_frame, (x1, y1), (x2, y2), box_color, 2)

            # Tag nhãn phía trên box
            tag_text = f"{label} {conf:.2f}"
            (text_w, text_h), baseline = cv2.getTextSize(
                tag_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
            )
            tag_y1 = max(y1 - text_h - 8, 55)
            tag_y2 = tag_y1 + text_h + 6
            cv2.rectangle(render_frame, (x1, tag_y1), (x1 + text_w + 6, tag_y2), box_color, -1)
            cv2.putText(
                render_frame, tag_text, (x1 + 3, tag_y2 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA
            )
    else:
        # Trạng thái an toàn bình thường
        cv2.rectangle(render_frame, (0, 0), (w, 40), (40, 40, 40), -1)
        cv2.putText(
            render_frame, "TRANG THAI: AN TOAN", (15, 28),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 230, 0), 2, cv2.LINE_AA
        )

    # Thanh trạng thái dưới cùng (FPS + Hướng dẫn phím)
    cv2.rectangle(render_frame, (0, h - 30), (w, h), (20, 20, 20), -1)
    if fps is not None and ai_fps is not None and ai_fps > 0:
        fps_str = f"Cam: {fps:.1f} FPS | AI: {ai_fps:.1f} FPS"
    elif fps is not None:
        fps_str = f"FPS: {fps:.1f}"
    else:
        fps_str = "FPS: --"
    cv2.putText(
        render_frame, fps_str, (15, h - 9),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA
    )

    return render_frame

def show(frame):
    """
    Hiện frame lên cửa sổ.
    Trả về hành động phím:
    - 'quit': nếu nhấn 'q' hoặc ESC
    - 'color': nếu nhấn 'c' để đảo màu trực tiếp
    - 'focus': nếu nhấn 'f' để lấy nét lại
    - 'focus_near': nếu nhấn ']' hoặc '+' để tăng tiêu cự
    - 'focus_far': nếu nhấn '[' hoặc '-' để giảm tiêu cự
    - None: không có phím đặc biệt
    """
    cv2.imshow(config.WINDOW_NAME, frame)
    key = cv2.waitKey(1) & 0xFF
    if key in (ord('q'), 27):
        return 'quit'
    elif key == ord('c'):
        return 'color'
    elif key == ord('f'):
        return 'focus'
    elif key in (ord(']'), ord('='), ord('+')):
        return 'focus_near'
    elif key in (ord('['), ord('-')):
        return 'focus_far'
    return None

def close():
    """Đóng tất cả cửa sổ OpenCV"""
    cv2.destroyAllWindows()
