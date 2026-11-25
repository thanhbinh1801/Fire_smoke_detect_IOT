// App.js — Ứng dụng di động Giám sát Lửa & Khói IoT (React Native / Expo)
import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  ScrollView,
  SafeAreaView,
  Vibration,
  Platform,
  Image,
  ActivityIndicator,
  Switch,
  Modal,
} from "react-native";
import { StatusBar } from "expo-status-bar";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { WebView } from "react-native-webview";

const STORAGE_KEY_SERVER_URL = "@fire_iot_server_url";
const DEFAULT_SERVER_URL = "http://192.168.5.216:5000";

function normalizeUrl(raw) {
  let clean = (raw || "").trim().replace(/\/+$/, "");
  if (!clean) return DEFAULT_SERVER_URL;
  if (!/^https?:\/\//i.test(clean)) {
    clean = "http://" + clean;
  }
  return clean;
}

export default function App() {
  const [activeTab, setActiveTab] = useState("monitor"); // "monitor" | "history" | "settings"
  const [serverUrl, setServerUrl] = useState(DEFAULT_SERVER_URL);
  const [inputUrl, setInputUrl] = useState(DEFAULT_SERVER_URL);
  const [useSnapshotStream, setUseSnapshotStream] = useState(Platform.OS === "web");
  const [snapshotTick, setSnapshotTick] = useState(Date.now());
  const [fullscreenVideo, setFullscreenVideo] = useState(false);
  const [phoneVibrateEnabled, setPhoneVibrateEnabled] = useState(true);

  const [connected, setConnected] = useState(false);
  const [statusData, setStatusData] = useState(null);
  const [actionMessage, setActionMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [busyKey, setBusyKey] = useState(null);

  const lastFireVibrationRef = useRef(0);

  useEffect(() => {
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(STORAGE_KEY_SERVER_URL);
        if (saved) {
          const norm = normalizeUrl(saved);
          setServerUrl(norm);
          setInputUrl(norm);
        }
      } catch (_err) {
        // Bỏ qua lỗi đọc cache ban đầu
      }
    })();
  }, []);

  const saveServerUrl = async () => {
    const norm = normalizeUrl(inputUrl);
    setServerUrl(norm);
    setInputUrl(norm);
    setErrorMessage("");
    setActionMessage("Đã lưu địa chỉ IP máy chủ mới.");
    try {
      await AsyncStorage.setItem(STORAGE_KEY_SERVER_URL, norm);
    } catch (_err) {
      // Bỏ qua lỗi ghi cache
    }
  };

  const fetchStatus = useCallback(async () => {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 3500);
      const res = await fetch(`${serverUrl}/api/status`, {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStatusData(data);
      setConnected(true);

      if (data.fire_detected && phoneVibrateEnabled) {
        const now = Date.now();
        if (now - lastFireVibrationRef.current > 3000) {
          lastFireVibrationRef.current = now;
          Vibration.vibrate([0, 600, 250, 600]);
        }
      }
    } catch (_err) {
      setConnected(false);
    }
  }, [serverUrl, phoneVibrateEnabled]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 1000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  useEffect(() => {
    if (!useSnapshotStream || !connected) return;
    const timer = setInterval(() => {
      setSnapshotTick(Date.now());
    }, 180);
    return () => clearInterval(timer);
  }, [useSnapshotStream, connected]);

  const sendPost = async (key, path, payload = null) => {
    setBusyKey(key);
    setErrorMessage("");
    setActionMessage("");
    try {
      const options = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      };
      if (payload !== null) {
        options.body = JSON.stringify(payload);
      }
      const res = await fetch(`${serverUrl}${path}`, options);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(data.message || `Lỗi HTTP ${res.status}`);
      }
      if (data.message) setActionMessage(data.message);
      await fetchStatus();
    } catch (err) {
      setErrorMessage(err.message || "Không gửi được lệnh tới thiết bị.");
    } finally {
      setBusyKey(null);
    }
  };

  const detections = Array.isArray(statusData?.detections) ? statusData.detections : [];
  const historyList = Array.isArray(statusData?.history) ? statusData.history : [];
  const aiSettings = statusData?.settings || {};
  const hasFire = Boolean(statusData?.fire_detected);
  const hasSmoke = detections.some((d) => d.label === "smoke");
  const isRunning = connected && statusData?.status === "running";
  const autoArmed = Boolean(statusData?.auto_armed);
  const servoAngle = statusData?.servo?.angle;
  const pump = statusData?.pump || {};
  const isPumpOn = pump.state === "on";

  let bannerStyle = styles.bannerSafe;
  let stateTitle = "ĐANG KẾT NỐI...";
  let stateSub = `Đang chờ phản hồi từ ${serverUrl}`;

  if (connected && statusData) {
    if (hasFire) {
      bannerStyle = styles.bannerFire;
      stateTitle = "🔥 CẢNH BÁO KHẨN: PHÁT HIỆN LỬA!";
      stateSub = "Đang kích hoạt còi, đèn LED & rung điện thoại!";
    } else if (statusData.status === "error") {
      bannerStyle = styles.bannerFire;
      stateTitle = "⚠️ LỖI HỆ THỐNG";
      stateSub = statusData.error || "Kiểm tra camera hoặc model ONNX.";
    } else if (hasSmoke) {
      bannerStyle = styles.bannerSmoke;
      stateTitle = "💨 CẢNH BÁO SỚM: PHÁT HIỆN KHÓI";
      stateSub = "Đang theo dõi đám khói trong khu vực.";
    } else if (statusData.status === "running") {
      bannerStyle = styles.bannerSafe;
      stateTitle = "🟢 HỆ THỐNG AN TOÀN";
      stateSub = "Không phát hiện lửa hoặc khói.";
    }
  } else {
    bannerStyle = styles.bannerOffline;
    stateTitle = "MẤT KẾT NỐI THIẾT BỊ";
    stateSub = `Kiểm tra IP (${serverUrl}) ở tab Cài đặt.`;
  }

  const mjpegHtml = `
    <!DOCTYPE html>
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
        <style>
          html, body {
            margin: 0; padding: 0; width: 100%; height: 100%;
            background: #070b12; display: flex; align-items: center; justify-content: center;
            overflow: hidden;
          }
          img { width: 100%; height: 100%; object-fit: contain; display: block; }
        </style>
      </head>
      <body>
        <img src="${serverUrl}/video_feed" alt="Live Stream" />
      </body>
    </html>
  `;

  const adjustThreshold = (field, currentVal, delta) => {
    const next = Math.max(0.15, Math.min(0.9, Number((currentVal + delta).toFixed(2))));
    sendPost(field, "/api/settings", { [field]: next });
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" backgroundColor="#0a0f18" />

      {/* Header cố định */}
      <View style={styles.header}>
        <View style={styles.brandRow}>
          <View style={styles.brandIcon}>
            <Text style={{ fontSize: 18 }}>🔥</Text>
          </View>
          <View>
            <Text style={styles.brandTitle}>Fire & Smoke IoT App</Text>
            <Text style={styles.ipText}>
              {serverUrl.replace(/^https?:\/\//, "")}
            </Text>
          </View>
        </View>

        <View style={styles.headerRight}>
          <TouchableOpacity
            style={[
              styles.vibrateChip,
              phoneVibrateEnabled ? styles.vibrateOn : styles.vibrateOff,
            ]}
            onPress={() => setPhoneVibrateEnabled(!phoneVibrateEnabled)}
          >
            <Text style={styles.vibrateChipText}>
              {phoneVibrateEnabled ? "📳 Rung: BẬT" : "🔕 Rung: TẮT"}
            </Text>
          </TouchableOpacity>
          <View
            style={[
              styles.connDot,
              { backgroundColor: connected ? "#3ddc97" : "#ff5c5c" },
            ]}
          />
        </View>
      </View>

      {/* Banner cảnh báo luôn hiển thị ở trên cùng mọi tab */}
      <View style={styles.bannerWrap}>
        <View style={[styles.banner, bannerStyle]}>
          <View style={styles.rowBetween}>
            <Text style={styles.bannerTitle}>{stateTitle}</Text>
            {detections.length > 0 && (
              <View style={styles.alertCountPill}>
                <Text style={styles.alertCountText}>
                  {detections.length} mục tiêu
                </Text>
              </View>
            )}
          </View>
          <Text style={styles.bannerSub}>{stateSub}</Text>
        </View>
      </View>

      {/* NỘI DUNG TỪNG TAB */}
      <ScrollView contentContainerStyle={styles.container}>
        {activeTab === "monitor" && (
          <>
            {/* Khung Video Camera Trực Tiếp */}
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <View style={styles.brandRow}>
                  <Text style={styles.cardTitle}>Camera trực tiếp</Text>
                  {isRunning && <Text style={styles.liveTag}>● LIVE</Text>}
                </View>
                <View style={styles.cardHeaderRight}>
                  <TouchableOpacity
                    style={styles.modeSwitchBtn}
                    onPress={() => setUseSnapshotStream(!useSnapshotStream)}
                  >
                    <Text style={styles.modeSwitchText}>
                      {useSnapshotStream ? "Snapshot" : "MJPEG"}
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.modeSwitchBtn}
                    onPress={() => setFullscreenVideo(true)}
                  >
                    <Text style={styles.modeSwitchText}>⛶ Phóng to</Text>
                  </TouchableOpacity>
                </View>
              </View>

              <View style={styles.videoBox}>
                {isRunning ? (
                  useSnapshotStream ? (
                    <Image
                      source={{ uri: `${serverUrl}/api/snapshot?t=${snapshotTick}` }}
                      style={styles.videoStream}
                      resizeMode="contain"
                    />
                  ) : (
                    <WebView
                      originWhitelist={["*"]}
                      source={{ html: mjpegHtml, baseUrl: serverUrl }}
                      style={styles.videoStream}
                      scrollEnabled={false}
                      bounces={false}
                    />
                  )
                ) : (
                  <View style={styles.videoPlaceholder}>
                    <ActivityIndicator size="small" color="#5e9eff" />
                    <Text style={styles.placeholderText}>
                      {connected
                        ? "Đang khởi tạo luồng camera..."
                        : "Chưa kết nối tới máy chủ camera"}
                    </Text>
                  </View>
                )}
              </View>

              <View style={styles.metricsRow}>
                <View style={styles.metricItem}>
                  <Text style={styles.metricLabel}>Camera FPS</Text>
                  <Text style={styles.metricValue}>
                    {statusData ? Number(statusData.camera_fps || 0).toFixed(1) : "--"}
                  </Text>
                </View>
                <View style={styles.metricItem}>
                  <Text style={styles.metricLabel}>AI FPS</Text>
                  <Text style={styles.metricValue}>
                    {statusData ? Number(statusData.ai_fps || 0).toFixed(1) : "--"}
                  </Text>
                </View>
                <View style={styles.metricItem}>
                  <Text style={styles.metricLabel}>Góc Servo</Text>
                  <Text style={styles.metricValue}>
                    {servoAngle == null ? "--°" : `${Math.round(Number(servoAngle))}°`}
                  </Text>
                </View>
              </View>
            </View>

            {/* Điều khiển Góc Servo thông minh (Nút vi chỉnh + Mốc góc nhanh 30°-150°) */}
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle}>Xoay Camera (Servo SG90)</Text>
                <Text style={styles.angleHighlight}>
                  {servoAngle == null ? "--°" : `${Math.round(Number(servoAngle))}°`}
                </Text>
              </View>

              <View style={styles.cardBody}>
                <View style={styles.grid3}>
                  <TouchableOpacity
                    style={styles.btn}
                    disabled={busyKey !== null}
                    onPress={() =>
                      sendPost("servo-left", "/api/servo", { action: "left" })
                    }
                  >
                    <Text style={styles.btnText}>← Quay Trái</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.btn}
                    disabled={busyKey !== null}
                    onPress={() =>
                      sendPost("servo-center", "/api/servo", { action: "center" })
                    }
                  >
                    <Text style={styles.btnText}>Giữa (90°)</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.btn}
                    disabled={busyKey !== null}
                    onPress={() =>
                      sendPost("servo-right", "/api/servo", { action: "right" })
                    }
                  >
                    <Text style={styles.btnText}>Quay Phải →</Text>
                  </TouchableOpacity>
                </View>

                <Text style={[styles.subHint, { marginTop: 12, marginBottom: 6 }]}>
                  Chọn nhanh góc nhìn cố định:
                </Text>
                <View style={styles.presetRow}>
                  {[30, 60, 90, 120, 150].map((deg) => {
                    const isSelected =
                      servoAngle != null && Math.round(Number(servoAngle)) === deg;
                    return (
                      <TouchableOpacity
                        key={deg}
                        style={[
                          styles.presetBtn,
                          isSelected && styles.presetBtnActive,
                        ]}
                        disabled={busyKey !== null}
                        onPress={() =>
                          sendPost(`servo-${deg}`, "/api/servo", {
                            action: "set",
                            angle: deg,
                          })
                        }
                      >
                        <Text
                          style={[
                            styles.presetBtnText,
                            isSelected && { color: "#07101e", fontWeight: "800" },
                          ]}
                        >
                          {deg}°
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>
            </View>

            {/* Điều khiển Bơm Nước Chữa Cháy */}
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle}>Hệ thống Bơm Chữa Cháy</Text>
                <Text
                  style={{
                    color: isPumpOn ? "#ff5c5c" : autoArmed ? "#3ddc97" : "#8c9aad",
                    fontSize: 12,
                    fontWeight: "700",
                  }}
                >
                  {isPumpOn ? "● ĐANG PHUN" : autoArmed ? "● AUTO BẬT" : "● TẮT"}
                </Text>
              </View>

              <View style={styles.cardBody}>
                <TouchableOpacity
                  style={[styles.btnFull, autoArmed && styles.btnActiveGreen]}
                  disabled={busyKey !== null}
                  onPress={() =>
                    sendPost("pump-arm", "/api/pump/arm", { armed: !autoArmed })
                  }
                >
                  <Text
                    style={[
                      styles.btnText,
                      autoArmed && { color: "#07120d", fontWeight: "800" },
                    ]}
                  >
                    {autoArmed
                      ? "✓ Đang BẬT chế độ tự động phun khi có lửa"
                      : "Bật chế độ tự động phun khi có lửa"}
                  </Text>
                </TouchableOpacity>

                <View style={styles.grid2}>
                  <TouchableOpacity
                    style={[styles.btn, styles.btnPrimary]}
                    disabled={busyKey !== null}
                    onPress={() => sendPost("pump-on", "/api/pump", { action: "on" })}
                  >
                    <Text style={styles.btnPrimaryText}>💦 Phun Nước Ngay</Text>
                  </TouchableOpacity>

                  <TouchableOpacity
                    style={[styles.btn, styles.btnDanger]}
                    disabled={busyKey !== null}
                    onPress={() =>
                      sendPost("pump-stop", "/api/pump", { action: "stop" })
                    }
                  >
                    <Text style={styles.btnDangerText}>🛑 DỪNG BƠM</Text>
                  </TouchableOpacity>
                </View>

                <Text style={styles.pumpStatusText}>
                  {isPumpOn
                    ? `Đang phun nước: còn ${Number(pump.seconds_remaining || 0).toFixed(1)}s`
                    : autoArmed
                    ? `Tự động phun đã sẵn sàng (${pump.runs_last_minute || 0}/${pump.max_per_minute || 4} lần/phút)`
                    : "Chế độ tự động đang tắt."}
                </Text>
              </View>
            </View>
          </>
        )}

        {/* TAB 2: NHẬT KÝ CẢNH BÁO */}
        {activeTab === "history" && (
          <View style={styles.card}>
            <View style={styles.cardHeader}>
              <Text style={styles.cardTitle}>
                Nhật ký Phát hiện Lửa & Khói ({historyList.length})
              </Text>
              {historyList.length > 0 && (
                <TouchableOpacity
                  style={styles.modeSwitchBtn}
                  onPress={() => sendPost("clear-history", "/api/history/clear")}
                >
                  <Text style={{ color: "#ff7b7b", fontSize: 11, fontWeight: "700" }}>
                    Xóa lịch sử
                  </Text>
                </TouchableOpacity>
              )}
            </View>

            <View style={styles.cardBody}>
              {historyList.length === 0 ? (
                <View style={{ paddingVertical: 28, alignItems: "center" }}>
                  <Text style={{ fontSize: 28, marginBottom: 8 }}>🛡️</Text>
                  <Text style={{ color: "#c5d0de", fontSize: 14, fontWeight: "600" }}>
                    Chưa có cảnh báo nào được ghi nhận
                  </Text>
                  <Text style={{ color: "#8c9aad", fontSize: 12, marginTop: 4 }}>
                    Mọi sự kiện phát hiện Lửa hoặc Khói sẽ tự động lưu tại đây.
                  </Text>
                </View>
              ) : (
                historyList.map((item) => {
                  const isFireEvt = item.type === "fire";
                  return (
                    <View
                      key={item.id}
                      style={[
                        styles.historyItem,
                        isFireEvt ? styles.historyFire : styles.historySmoke,
                      ]}
                    >
                      <View style={styles.rowBetween}>
                        <Text style={styles.historyTitle}>
                          {isFireEvt ? "🔥 PHÁT HIỆN LỬA" : "💨 PHÁT HIỆN KHÓI"}
                        </Text>
                        <Text style={styles.historyTime}>{item.time_str}</Text>
                      </View>
                      <Text style={styles.historyMeta}>
                        Số vùng: {item.count} · Độ tin cậy cao nhất:{" "}
                        {(Number(item.max_conf || 0) * 100).toFixed(1)}%
                      </Text>
                    </View>
                  );
                })
              )}
            </View>
          </View>
        )}

        {/* TAB 3: CÀI ĐẶT AI & TIỀN XỬ LÝ TRỰC TIẾP */}
        {activeTab === "settings" && (
          <>
            {/* Tinh chỉnh ngưỡng nhạy AI thời gian thực */}
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle}>
                  Tinh chỉnh Ngưỡng AI (Thời gian thực)
                </Text>
              </View>
              <Text style={[styles.settingDesc, { paddingHorizontal: 16, paddingBottom: 12 }]}>
                Thiết lập thử nghiệm chỉ có hiệu lực trong phiên chạy hiện tại và mất khi khởi động lại. Các giới hạn an toàn bơm/servo không bị thay đổi.
              </Text>
              <View style={styles.cardBody}>
                <View style={styles.settingRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.settingTitle}>Ngưỡng nhận diện LỬA</Text>
                    <Text style={styles.settingDesc}>
                      Thấp hơn = nhạy hơn với lửa nhỏ; Cao hơn = chống báo giả
                    </Text>
                  </View>
                  <View style={styles.stepperRow}>
                    <TouchableOpacity
                      style={styles.stepperBtn}
                      onPress={() =>
                        adjustThreshold(
                          "fire_confidence_threshold",
                          Number(aiSettings.fire_confidence_threshold || 0.4),
                          -0.05
                        )
                      }
                    >
                      <Text style={styles.stepperBtnText}>-</Text>
                    </TouchableOpacity>
                    <Text style={styles.stepperValue}>
                      {Math.round(
                        Number(aiSettings.fire_confidence_threshold || 0.4) * 100
                      )}
                      %
                    </Text>
                    <TouchableOpacity
                      style={styles.stepperBtn}
                      onPress={() =>
                        adjustThreshold(
                          "fire_confidence_threshold",
                          Number(aiSettings.fire_confidence_threshold || 0.4),
                          +0.05
                        )
                      }
                    >
                      <Text style={styles.stepperBtnText}>+</Text>
                    </TouchableOpacity>
                  </View>
                </View>

                <View style={styles.divider} />

                <View style={styles.settingRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.settingTitle}>Ngưỡng nhận diện KHÓI</Text>
                    <Text style={styles.settingDesc}>
                      Điều chỉnh độ nhạy phát hiện đám khói sớm
                    </Text>
                  </View>
                  <View style={styles.stepperRow}>
                    <TouchableOpacity
                      style={styles.stepperBtn}
                      onPress={() =>
                        adjustThreshold(
                          "smoke_confidence_threshold",
                          Number(aiSettings.smoke_confidence_threshold || 0.38),
                          -0.05
                        )
                      }
                    >
                      <Text style={styles.stepperBtnText}>-</Text>
                    </TouchableOpacity>
                    <Text style={styles.stepperValue}>
                      {Math.round(
                        Number(aiSettings.smoke_confidence_threshold || 0.38) * 100
                      )}
                      %
                    </Text>
                    <TouchableOpacity
                      style={styles.stepperBtn}
                      onPress={() =>
                        adjustThreshold(
                          "smoke_confidence_threshold",
                          Number(aiSettings.smoke_confidence_threshold || 0.38),
                          +0.05
                        )
                      }
                    >
                      <Text style={styles.stepperBtnText}>+</Text>
                    </TouchableOpacity>
                  </View>
                </View>

                <View style={styles.divider} />

                <View style={styles.settingRow}>
                  <View style={{ flex: 1, paddingRight: 10 }}>
                    <Text style={styles.settingTitle}>
                      ROI Zoom 2 giai đoạn (Lửa ở xa)
                    </Text>
                    <Text style={styles.settingDesc}>
                      Tự động cắt 1:1 vùng nghi ngờ để phát hiện đốm lửa nhỏ
                    </Text>
                  </View>
                  <Switch
                    value={Boolean(aiSettings.roi_zoom_enabled ?? true)}
                    onValueChange={(val) =>
                      sendPost("roi-zoom", "/api/settings", {
                        roi_zoom_enabled: val,
                      })
                    }
                    trackColor={{ false: "#243144", true: "#3ddc97" }}
                  />
                </View>
              </View>
            </View>

            {/* Bộ lọc Tiền xử lý ảnh (Preprocessing Filters) */}
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle}>
                  Bộ lọc Tiền xử lý ảnh (Preprocessing)
                </Text>
              </View>
              <View style={styles.cardBody}>
                <View style={styles.settingRow}>
                  <View style={{ flex: 1, paddingRight: 10 }}>
                    <Text style={styles.settingTitle}>
                      Tăng tương phản CLAHE (LAB)
                    </Text>
                    <Text style={styles.settingDesc}>
                      Làm nổi rõ đám khói mờ hoặc ngược sáng
                    </Text>
                  </View>
                  <Switch
                    value={Boolean(aiSettings.enable_clahe)}
                    onValueChange={(val) =>
                      sendPost("clahe", "/api/settings", { enable_clahe: val })
                    }
                    trackColor={{ false: "#243144", true: "#3ddc97" }}
                  />
                </View>

                <View style={styles.divider} />

                <View style={styles.settingRow}>
                  <View style={{ flex: 1, paddingRight: 10 }}>
                    <Text style={styles.settingTitle}>
                      Cân bằng trắng tự động (Gray-World)
                    </Text>
                    <Text style={styles.settingDesc}>
                      Ổn định màu lửa dưới ánh đèn vàng/huỳnh quang
                    </Text>
                  </View>
                  <Switch
                    value={Boolean(aiSettings.auto_wb)}
                    onValueChange={(val) =>
                      sendPost("auto-wb", "/api/settings", { auto_wb: val })
                    }
                    trackColor={{ false: "#243144", true: "#3ddc97" }}
                  />
                </View>

                <View style={styles.divider} />

                <View style={styles.settingRow}>
                  <View style={{ flex: 1, paddingRight: 10 }}>
                    <Text style={styles.settingTitle}>
                      Làm sắc nét biên (Sharpen)
                    </Text>
                    <Text style={styles.settingDesc}>
                      Tăng độ nét viền ngọn lửa ở khoảng cách xa
                    </Text>
                  </View>
                  <Switch
                    value={Boolean(aiSettings.sharpen)}
                    onValueChange={(val) =>
                      sendPost("sharpen", "/api/settings", { sharpen: val })
                    }
                    trackColor={{ false: "#243144", true: "#3ddc97" }}
                  />
                </View>

                <View style={styles.divider} />

                <Text style={styles.settingTitle}>
                  Hiệu chỉnh sáng Gamma:{" "}
                  <Text style={{ color: "#5e9eff" }}>
                    {Number(aiSettings.gamma || 1.0).toFixed(2)}
                  </Text>
                </Text>
                <Text style={[styles.settingDesc, { marginBottom: 8 }]}>
                  {"< 1.0: Giảm lóa sáng · 1.0: Mặc định · > 1.0: Làm sáng vùng tối"}
                </Text>
                <View style={styles.presetRow}>
                  {[0.7, 0.85, 1.0, 1.2, 1.5].map((g) => {
                    const activeG =
                      Math.abs(Number(aiSettings.gamma || 1.0) - g) < 0.03;
                    return (
                      <TouchableOpacity
                        key={g}
                        style={[
                          styles.presetBtn,
                          activeG && styles.presetBtnActive,
                        ]}
                        onPress={() =>
                          sendPost("gamma", "/api/settings", { gamma: g })
                        }
                      >
                        <Text
                          style={[
                            styles.presetBtnText,
                            activeG && { color: "#07101e", fontWeight: "800" },
                          ]}
                        >
                          {g}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>
            </View>

            {/* Kết nối Máy chủ & Telegram */}
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle}>Kết nối Thiết bị & Telegram</Text>
              </View>
              <View style={styles.cardBody}>
                <Text style={styles.ipLabel}>
                  Địa chỉ IP & Cổng của Raspberry Pi / Laptop:
                </Text>
                <View style={styles.ipInputRow}>
                  <TextInput
                    style={styles.ipInput}
                    value={inputUrl}
                    onChangeText={setInputUrl}
                    placeholder="http://192.168.5.216:5000"
                    placeholderTextColor="#64748b"
                    autoCapitalize="none"
                    autoCorrect={false}
                    keyboardType="url"
                  />
                  <TouchableOpacity
                    style={styles.ipSaveBtn}
                    onPress={saveServerUrl}
                  >
                    <Text style={styles.ipSaveBtnText}>Lưu IP</Text>
                  </TouchableOpacity>
                </View>

                <View style={styles.divider} />

                <TouchableOpacity
                  style={styles.btnFull}
                  disabled={busyKey !== null}
                  onPress={() => sendPost("telegram-test", "/api/telegram/test")}
                >
                  <Text style={styles.btnText}>
                    {busyKey === "telegram-test"
                      ? "Đang gửi tới Telegram..."
                      : "📨 Gửi thử ảnh & cảnh báo về Telegram Bot"}
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
          </>
        )}

        {actionMessage ? (
          <Text style={styles.successMsg}>✓ {actionMessage}</Text>
        ) : null}
        {errorMessage ? (
          <Text style={styles.errorMsg}>⚠ {errorMessage}</Text>
        ) : null}
      </ScrollView>

      {/* Modal Xem Camera Toàn Màn Hình */}
      <Modal
        visible={fullscreenVideo}
        animationType="fade"
        transparent={false}
        onRequestClose={() => setFullscreenVideo(false)}
      >
        <SafeAreaView style={styles.fullscreenModal}>
          <View style={styles.fullscreenHeader}>
            <Text style={styles.cardTitle}>
              Camera Toàn Màn Hình ({servoAngle == null ? "--°" : `${Math.round(Number(servoAngle))}°`})
            </Text>
            <TouchableOpacity
              style={styles.closeFullBtn}
              onPress={() => setFullscreenVideo(false)}
            >
              <Text style={styles.closeFullBtnText}>✕ Đóng</Text>
            </TouchableOpacity>
          </View>
          <View style={{ flex: 1, backgroundColor: "#000" }}>
            {isRunning && (
              <WebView
                originWhitelist={["*"]}
                source={{ html: mjpegHtml, baseUrl: serverUrl }}
                style={{ flex: 1, backgroundColor: "#000" }}
                scrollEnabled={false}
              />
            )}
          </View>
          <View style={styles.fullscreenControls}>
            <TouchableOpacity
              style={styles.btn}
              onPress={() => sendPost("servo-left", "/api/servo", { action: "left" })}
            >
              <Text style={styles.btnText}>← Trái</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.btn}
              onPress={() =>
                sendPost("servo-center", "/api/servo", { action: "center" })
              }
            >
              <Text style={styles.btnText}>Giữa (90°)</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.btn}
              onPress={() =>
                sendPost("servo-right", "/api/servo", { action: "right" })
              }
            >
              <Text style={styles.btnText}>Phải →</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.btn, styles.btnPrimary]}
              onPress={() => sendPost("pump-on", "/api/pump", { action: "on" })}
            >
              <Text style={styles.btnPrimaryText}>💦 Phun</Text>
            </TouchableOpacity>
          </View>
        </SafeAreaView>
      </Modal>

      {/* Thanh Điều Hướng Đa Tab Dưới Cùng (Bottom Navigation Bar) */}
      <View style={styles.tabBar}>
        <TouchableOpacity
          style={[styles.tabItem, activeTab === "monitor" && styles.tabItemActive]}
          onPress={() => setActiveTab("monitor")}
        >
          <Text style={styles.tabIcon}>📹</Text>
          <Text
            style={[
              styles.tabLabel,
              activeTab === "monitor" && styles.tabLabelActive,
            ]}
          >
            Giám sát
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tabItem, activeTab === "history" && styles.tabItemActive]}
          onPress={() => setActiveTab("history")}
        >
          <Text style={styles.tabIcon}>
            🔔{historyList.length > 0 ? ` (${historyList.length})` : ""}
          </Text>
          <Text
            style={[
              styles.tabLabel,
              activeTab === "history" && styles.tabLabelActive,
            ]}
          >
            Nhật ký
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.tabItem, activeTab === "settings" && styles.tabItemActive]}
          onPress={() => setActiveTab("settings")}
        >
          <Text style={styles.tabIcon}>⚙️</Text>
          <Text
            style={[
              styles.tabLabel,
              activeTab === "settings" && styles.tabLabelActive,
            ]}
          >
            Cài đặt AI
          </Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#0a0f18",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 14,
    paddingTop: 10,
    paddingBottom: 10,
    borderBottomWidth: 1,
    borderBottomColor: "#243144",
    backgroundColor: "#0a0f18",
  },
  headerRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  brandIcon: {
    width: 34,
    height: 34,
    borderRadius: 9,
    backgroundColor: "#ff5c5c22",
    borderWidth: 1,
    borderColor: "#ff5c5c55",
    alignItems: "center",
    justifyContent: "center",
  },
  brandTitle: {
    color: "#edf2f8",
    fontSize: 15,
    fontWeight: "700",
  },
  ipText: {
    color: "#8c9aad",
    fontSize: 11,
  },
  vibrateChip: {
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
  },
  vibrateOn: {
    backgroundColor: "#3ddc9718",
    borderColor: "#3ddc9755",
  },
  vibrateOff: {
    backgroundColor: "#ffffff0a",
    borderColor: "#ffffff22",
  },
  vibrateChipText: {
    color: "#edf2f8",
    fontSize: 11,
    fontWeight: "600",
  },
  connDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  bannerWrap: {
    paddingHorizontal: 14,
    paddingTop: 10,
  },
  banner: {
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
  },
  bannerSafe: {
    backgroundColor: "#3ddc9715",
    borderColor: "#3ddc9744",
  },
  bannerSmoke: {
    backgroundColor: "#ffb84d18",
    borderColor: "#ffb84d55",
  },
  bannerFire: {
    backgroundColor: "#ff5c5c28",
    borderColor: "#ff5c5c99",
  },
  bannerOffline: {
    backgroundColor: "#121b28",
    borderColor: "#243144",
  },
  bannerTitle: {
    color: "#ffffff",
    fontSize: 14,
    fontWeight: "800",
  },
  bannerSub: {
    color: "#c5d0de",
    fontSize: 11,
    marginTop: 3,
  },
  alertCountPill: {
    backgroundColor: "#ff5c5c",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
  },
  alertCountText: {
    color: "#fff",
    fontSize: 10,
    fontWeight: "800",
  },
  container: {
    padding: 14,
    paddingBottom: 24,
  },
  card: {
    backgroundColor: "#121b28",
    borderWidth: 1,
    borderColor: "#243144",
    borderRadius: 14,
    overflow: "hidden",
    marginBottom: 14,
  },
  cardHeader: {
    height: 44,
    paddingHorizontal: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#ffffff12",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  cardHeaderRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  cardTitle: {
    color: "#edf2f8",
    fontSize: 13,
    fontWeight: "700",
  },
  liveTag: {
    color: "#ff5c5c",
    fontSize: 11,
    fontWeight: "800",
  },
  modeSwitchBtn: {
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 6,
    backgroundColor: "#ffffff12",
  },
  modeSwitchText: {
    color: "#c5d0de",
    fontSize: 11,
    fontWeight: "600",
  },
  videoBox: {
    width: "100%",
    aspectRatio: 4 / 3,
    backgroundColor: "#070b12",
  },
  videoStream: {
    flex: 1,
    width: "100%",
    height: "100%",
    backgroundColor: "#070b12",
  },
  videoPlaceholder: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
  },
  placeholderText: {
    color: "#8c9aad",
    fontSize: 13,
    marginTop: 10,
    textAlign: "center",
  },
  metricsRow: {
    flexDirection: "row",
    borderTopWidth: 1,
    borderTopColor: "#ffffff10",
  },
  metricItem: {
    flex: 1,
    paddingVertical: 9,
    paddingHorizontal: 12,
    borderRightWidth: 1,
    borderRightColor: "#ffffff0a",
  },
  metricLabel: {
    color: "#8c9aad",
    fontSize: 10,
  },
  metricValue: {
    color: "#edf2f8",
    fontSize: 16,
    fontWeight: "700",
    marginTop: 2,
  },
  cardBody: {
    padding: 14,
  },
  rowBetween: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  angleHighlight: {
    color: "#5e9eff",
    fontSize: 13,
    fontWeight: "800",
  },
  subHint: {
    color: "#8c9aad",
    fontSize: 11,
  },
  presetRow: {
    flexDirection: "row",
    gap: 8,
  },
  presetBtn: {
    flex: 1,
    height: 36,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#ffffff1a",
    backgroundColor: "#ffffff08",
    alignItems: "center",
    justifyContent: "center",
  },
  presetBtnActive: {
    backgroundColor: "#5e9eff",
    borderColor: "#5e9eff",
  },
  presetBtnText: {
    color: "#c5d0de",
    fontSize: 12,
    fontWeight: "600",
  },
  grid3: {
    flexDirection: "row",
    gap: 8,
  },
  grid2: {
    flexDirection: "row",
    gap: 8,
    marginTop: 8,
  },
  btn: {
    flex: 1,
    minHeight: 42,
    borderRadius: 9,
    borderWidth: 1,
    borderColor: "#ffffff1c",
    backgroundColor: "#ffffff0a",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 8,
  },
  btnFull: {
    width: "100%",
    minHeight: 42,
    borderRadius: 9,
    borderWidth: 1,
    borderColor: "#ffffff1c",
    backgroundColor: "#ffffff0a",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 12,
  },
  btnActiveGreen: {
    backgroundColor: "#3ddc97",
    borderColor: "#3ddc97",
  },
  btnPrimary: {
    backgroundColor: "#5e9eff22",
    borderColor: "#5e9eff66",
  },
  btnDanger: {
    backgroundColor: "#ff5c5c22",
    borderColor: "#ff5c5c66",
  },
  btnText: {
    color: "#edf2f8",
    fontSize: 12,
    fontWeight: "600",
  },
  btnPrimaryText: {
    color: "#9ec5ff",
    fontSize: 13,
    fontWeight: "700",
  },
  btnDangerText: {
    color: "#ff9e9e",
    fontSize: 13,
    fontWeight: "800",
  },
  divider: {
    height: 1,
    backgroundColor: "#ffffff12",
    marginVertical: 12,
  },
  pumpStatusText: {
    color: "#8c9aad",
    fontSize: 11,
    marginTop: 10,
  },
  historyItem: {
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    marginBottom: 8,
  },
  historyFire: {
    backgroundColor: "#ff5c5c18",
    borderColor: "#ff5c5c55",
  },
  historySmoke: {
    backgroundColor: "#ffb84d15",
    borderColor: "#ffb84d55",
  },
  historyTitle: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "700",
  },
  historyTime: {
    color: "#c5d0de",
    fontSize: 11,
  },
  historyMeta: {
    color: "#c5d0de",
    fontSize: 12,
    marginTop: 4,
  },
  settingRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  settingTitle: {
    color: "#edf2f8",
    fontSize: 13,
    fontWeight: "600",
  },
  settingDesc: {
    color: "#8c9aad",
    fontSize: 11,
    marginTop: 2,
  },
  stepperRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  stepperBtn: {
    width: 34,
    height: 34,
    borderRadius: 8,
    backgroundColor: "#ffffff14",
    alignItems: "center",
    justifyContent: "center",
  },
  stepperBtnText: {
    color: "#fff",
    fontSize: 18,
    fontWeight: "700",
  },
  stepperValue: {
    color: "#5e9eff",
    fontSize: 14,
    fontWeight: "800",
    minWidth: 42,
    textAlign: "center",
  },
  ipLabel: {
    color: "#c5d0de",
    fontSize: 12,
    marginBottom: 8,
  },
  ipInputRow: {
    flexDirection: "row",
    gap: 8,
  },
  ipInput: {
    flex: 1,
    height: 40,
    backgroundColor: "#0a0f18",
    borderWidth: 1,
    borderColor: "#243144",
    borderRadius: 8,
    paddingHorizontal: 12,
    color: "#edf2f8",
    fontSize: 13,
  },
  ipSaveBtn: {
    backgroundColor: "#5e9eff",
    borderRadius: 8,
    paddingHorizontal: 16,
    justifyContent: "center",
    alignItems: "center",
  },
  ipSaveBtnText: {
    color: "#07101e",
    fontWeight: "700",
    fontSize: 13,
  },
  successMsg: {
    color: "#3ddc97",
    fontSize: 12,
    textAlign: "center",
    marginTop: 4,
  },
  errorMsg: {
    color: "#ff7b7b",
    fontSize: 12,
    textAlign: "center",
    marginTop: 4,
  },
  tabBar: {
    flexDirection: "row",
    height: 58,
    borderTopWidth: 1,
    borderTopColor: "#243144",
    backgroundColor: "#101824",
  },
  tabItem: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  tabItemActive: {
    borderTopWidth: 2,
    borderTopColor: "#5e9eff",
    backgroundColor: "#5e9eff10",
  },
  tabIcon: {
    fontSize: 15,
    color: "#edf2f8",
  },
  tabLabel: {
    fontSize: 11,
    color: "#8c9aad",
    marginTop: 2,
    fontWeight: "600",
  },
  tabLabelActive: {
    color: "#5e9eff",
    fontWeight: "700",
  },
  fullscreenModal: {
    flex: 1,
    backgroundColor: "#000",
  },
  fullscreenHeader: {
    height: 50,
    paddingHorizontal: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: "#0a0f18",
  },
  closeFullBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: "#ff5c5c33",
  },
  closeFullBtnText: {
    color: "#ff9e9e",
    fontWeight: "700",
    fontSize: 12,
  },
  fullscreenControls: {
    flexDirection: "row",
    gap: 8,
    padding: 12,
    backgroundColor: "#0a0f18",
  },
});
