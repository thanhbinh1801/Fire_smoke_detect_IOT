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
} from "react-native";
import { StatusBar } from "expo-status-bar";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { WebView } from "react-native-webview";

const STORAGE_KEY_SERVER_URL = "@fire_iot_server_url";
const DEFAULT_SERVER_URL = "http://192.168.1.100:5000";

function normalizeUrl(raw) {
  let clean = (raw || "").trim().replace(/\/+$/, "");
  if (!clean) return DEFAULT_SERVER_URL;
  if (!/^https?:\/\//i.test(clean)) {
    clean = "http://" + clean;
  }
  return clean;
}

export default function App() {
  const [serverUrl, setServerUrl] = useState(DEFAULT_SERVER_URL);
  const [inputUrl, setInputUrl] = useState(DEFAULT_SERVER_URL);
  const [editingIp, setEditingIp] = useState(false);
  const [useSnapshotStream, setUseSnapshotStream] = useState(Platform.OS === "web");
  const [snapshotTick, setSnapshotTick] = useState(Date.now());

  const [connected, setConnected] = useState(false);
  const [statusData, setStatusData] = useState(null);
  const [actionMessage, setActionMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [busyKey, setBusyKey] = useState(null);

  const lastFireVibrationRef = useRef(0);

  // Nạp IP đã lưu trong máy khi mở App
  useEffect(() => {
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(STORAGE_KEY_SERVER_URL);
        if (saved) {
          const norm = normalizeUrl(saved);
          setServerUrl(norm);
          setInputUrl(norm);
        }
      } catch {}
    })();
  }, []);

  const saveServerUrl = async () => {
    const norm = normalizeUrl(inputUrl);
    setServerUrl(norm);
    setInputUrl(norm);
    setEditingIp(false);
    setErrorMessage("");
    try {
      await AsyncStorage.setItem(STORAGE_KEY_SERVER_URL, norm);
    } catch {}
  };

  // Poll trạng thái hệ thống từ Raspberry Pi mỗi 1 giây
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

      // Rung điện thoại cảnh báo khi phát hiện LỬA
      if (data.fire_detected) {
        const now = Date.now();
        if (now - lastFireVibrationRef.current > 3500) {
          lastFireVibrationRef.current = now;
          Vibration.vibrate([0, 500, 250, 500]);
        }
      }
    } catch {
      setConnected(false);
    }
  }, [serverUrl]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 1000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // Nếu dùng chế độ ảnh Snapshot liên tục, cập nhật 6 FPS
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
      stateTitle = "🔥 CẢNH BÁO: PHÁT HIỆN LỬA!";
      stateSub = "Đã kích hoạt còi, đèn LED và cảnh báo khẩn cấp!";
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
      stateTitle = "🟢 AN TOÀN";
      stateSub = "Không phát hiện lửa hoặc khói.";
    }
  } else {
    bannerStyle = styles.bannerOffline;
    stateTitle = "MẤT KẾT NỐI THIẾT BỊ";
    stateSub = `Kiểm tra IP (${serverUrl}) và cùng mạng Wi-Fi với Raspberry Pi.`;
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

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" backgroundColor="#0a0f18" />
      <ScrollView contentContainerStyle={styles.container}>
        {/* Thanh Tiêu đề & Kết nối IP */}
        <View style={styles.header}>
          <View style={styles.brandRow}>
            <View style={styles.brandIcon}>
              <Text style={{ fontSize: 18 }}>🔥</Text>
            </View>
            <View>
              <Text style={styles.brandTitle}>Giám sát Lửa & Khói IoT</Text>
              <TouchableOpacity onPress={() => setEditingIp(!editingIp)}>
                <Text style={styles.ipText}>
                  IP: {serverUrl.replace(/^https?:\/\//, "")} ✎
                </Text>
              </TouchableOpacity>
            </View>
          </View>

          <View
            style={[
              styles.connBadge,
              connected ? styles.connOnline : styles.connOffline,
            ]}
          >
            <View
              style={[
                styles.connDot,
                { backgroundColor: connected ? "#3ddc97" : "#ff5c5c" },
              ]}
            />
            <Text style={styles.connText}>
              {connected ? "Trực tuyến" : "Mất kết nối"}
            </Text>
          </View>
        </View>

        {/* Hộp nhập đổi địa chỉ IP Raspberry Pi */}
        {editingIp && (
          <View style={styles.ipCard}>
            <Text style={styles.ipLabel}>
              Địa chỉ IP & Cổng của Raspberry Pi / Máy chủ:
            </Text>
            <View style={styles.ipInputRow}>
              <TextInput
                style={styles.ipInput}
                value={inputUrl}
                onChangeText={setInputUrl}
                placeholder="http://192.168.1.100:5000"
                placeholderTextColor="#64748b"
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
              />
              <TouchableOpacity style={styles.ipSaveBtn} onPress={saveServerUrl}>
                <Text style={styles.ipSaveBtnText}>Kết nối</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* 1. Bảng Trạng thái Cảnh báo */}
        <View style={[styles.banner, bannerStyle]}>
          <Text style={styles.bannerTitle}>{stateTitle}</Text>
          <Text style={styles.bannerSub}>{stateSub}</Text>
        </View>

        {/* 2. Khung Video Camera Trực Tiếp */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <Text style={styles.cardTitle}>Camera trực tiếp</Text>
            <View style={styles.cardHeaderRight}>
              {isRunning && <Text style={styles.liveTag}>● LIVE</Text>}
              <TouchableOpacity
                style={styles.modeSwitchBtn}
                onPress={() => setUseSnapshotStream(!useSnapshotStream)}
              >
                <Text style={styles.modeSwitchText}>
                  {useSnapshotStream ? "Chế độ: Snapshot" : "Chế độ: MJPEG"}
                </Text>
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
                <TouchableOpacity
                  style={styles.changeIpHintBtn}
                  onPress={() => setEditingIp(true)}
                >
                  <Text style={styles.changeIpHintText}>Đổi địa chỉ IP</Text>
                </TouchableOpacity>
              </View>
            )}
          </View>

          {/* Chỉ số tốc độ FPS */}
          <View style={styles.metricsRow}>
            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>Tốc độ Camera</Text>
              <Text style={styles.metricValue}>
                {statusData ? Number(statusData.camera_fps || 0).toFixed(1) : "--"}{" "}
                <Text style={styles.metricUnit}>FPS</Text>
              </Text>
            </View>
            <View style={styles.metricItem}>
              <Text style={styles.metricLabel}>Tốc độ AI</Text>
              <Text style={styles.metricValue}>
                {statusData ? Number(statusData.ai_fps || 0).toFixed(1) : "--"}{" "}
                <Text style={styles.metricUnit}>FPS</Text>
              </Text>
            </View>
          </View>
        </View>

        {/* 3. Điều khiển Servo & Bơm chữa cháy */}
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <Text style={styles.cardTitle}>Điều khiển Servo & Bơm nước</Text>
          </View>

          <View style={styles.cardBody}>
            {/* Điều khiển Servo */}
            <View style={styles.rowBetween}>
              <Text style={styles.sectionLabel}>Góc quay Camera (Servo)</Text>
              <View style={styles.angleBadge}>
                <Text style={styles.angleBadgeText}>
                  {servoAngle == null ? "--°" : `${Math.round(Number(servoAngle))}°`}
                </Text>
              </View>
            </View>

            <View style={styles.grid3}>
              <TouchableOpacity
                style={styles.btn}
                disabled={busyKey !== null}
                onPress={() => sendPost("servo-left", "/api/servo", { action: "left" })}
              >
                <Text style={styles.btnText}>← Trái</Text>
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
                <Text style={styles.btnText}>Phải →</Text>
              </TouchableOpacity>
            </View>

            <View style={styles.divider} />

            {/* Điều khiển Bơm nước */}
            <Text style={[styles.sectionLabel, { marginBottom: 8 }]}>
              Bơm nước chữa cháy
            </Text>

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
                  ? "✓ Đang bật phun tự động khi có lửa"
                  : "Bật phun tự động khi có lửa"}
              </Text>
            </TouchableOpacity>

            <View style={styles.grid2}>
              <TouchableOpacity
                style={[styles.btn, styles.btnPrimary]}
                disabled={busyKey !== null}
                onPress={() => sendPost("pump-on", "/api/pump", { action: "on" })}
              >
                <Text style={styles.btnPrimaryText}>💦 Phun nước</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[styles.btn, styles.btnDanger]}
                disabled={busyKey !== null}
                onPress={() => sendPost("pump-stop", "/api/pump", { action: "stop" })}
              >
                <Text style={styles.btnDangerText}>🛑 DỪNG BƠM</Text>
              </TouchableOpacity>
            </View>

            <Text
              style={[
                styles.pumpStatusText,
                isPumpOn && { color: "#ff5c5c", fontWeight: "700" },
              ]}
            >
              {isPumpOn
                ? `Bơm: ĐANG PHUN (${Number(pump.seconds_remaining || 0).toFixed(1)}s)`
                : autoArmed
                ? `Bơm: Chế độ tự động đang bật${
                    Number(pump.cooldown_remaining || 0) > 0
                      ? ` · chờ ${Math.ceil(Number(pump.cooldown_remaining))}s`
                      : ""
                  }`
                : "Bơm: đang tắt."}
            </Text>

            <View style={styles.divider} />

            {/* Kiểm tra Telegram */}
            <TouchableOpacity
              style={styles.btnFull}
              disabled={busyKey !== null}
              onPress={() => sendPost("telegram-test", "/api/telegram/test")}
            >
              <Text style={styles.btnText}>
                {busyKey === "telegram-test"
                  ? "Đang gửi tới Telegram..."
                  : "📨 Gửi thử cảnh báo Telegram"}
              </Text>
            </TouchableOpacity>

            {actionMessage ? (
              <Text style={styles.successMsg}>{actionMessage}</Text>
            ) : null}
            {errorMessage ? (
              <Text style={styles.errorMsg}>{errorMessage}</Text>
            ) : null}
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#0a0f18",
  },
  container: {
    padding: 14,
    paddingBottom: 32,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 12,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: "#243144",
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  brandIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: "#ff5c5c22",
    borderWidth: 1,
    borderColor: "#ff5c5c55",
    alignItems: "center",
    justifyContent: "center",
  },
  brandTitle: {
    color: "#edf2f8",
    fontSize: 16,
    fontWeight: "700",
  },
  ipText: {
    color: "#5e9eff",
    fontSize: 12,
    marginTop: 2,
  },
  connBadge: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    gap: 6,
  },
  connOnline: {
    backgroundColor: "#121b28",
    borderColor: "#3ddc9755",
  },
  connOffline: {
    backgroundColor: "#121b28",
    borderColor: "#ff5c5c55",
  },
  connDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  connText: {
    color: "#c5d0de",
    fontSize: 12,
    fontWeight: "600",
  },
  ipCard: {
    backgroundColor: "#121b28",
    borderWidth: 1,
    borderColor: "#5e9eff55",
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
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
  banner: {
    borderRadius: 12,
    padding: 14,
    borderWidth: 1,
    marginBottom: 14,
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
    backgroundColor: "#ff5c5c24",
    borderColor: "#ff5c5c88",
  },
  bannerOffline: {
    backgroundColor: "#121b28",
    borderColor: "#243144",
  },
  bannerTitle: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "800",
  },
  bannerSub: {
    color: "#c5d0de",
    fontSize: 12,
    marginTop: 4,
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
    gap: 10,
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
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    backgroundColor: "#ffffff10",
  },
  modeSwitchText: {
    color: "#8c9aad",
    fontSize: 11,
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
  changeIpHintBtn: {
    marginTop: 12,
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#5e9eff55",
    backgroundColor: "#5e9eff18",
  },
  changeIpHintText: {
    color: "#8ab8ff",
    fontSize: 12,
    fontWeight: "600",
  },
  metricsRow: {
    flexDirection: "row",
    borderTopWidth: 1,
    borderTopColor: "#ffffff10",
  },
  metricItem: {
    flex: 1,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRightWidth: 1,
    borderRightColor: "#ffffff0a",
  },
  metricLabel: {
    color: "#8c9aad",
    fontSize: 11,
  },
  metricValue: {
    color: "#edf2f8",
    fontSize: 18,
    fontWeight: "700",
    marginTop: 2,
  },
  metricUnit: {
    color: "#8c9aad",
    fontSize: 11,
    fontWeight: "500",
  },
  cardBody: {
    padding: 14,
  },
  rowBetween: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  sectionLabel: {
    color: "#c5d0de",
    fontSize: 12,
    fontWeight: "600",
  },
  angleBadge: {
    backgroundColor: "#ffffff12",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  angleBadgeText: {
    color: "#edf2f8",
    fontSize: 12,
    fontWeight: "700",
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
    paddingHorizontal: 10,
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
    fontSize: 13,
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
    marginVertical: 14,
  },
  pumpStatusText: {
    color: "#8c9aad",
    fontSize: 12,
    marginTop: 10,
  },
  successMsg: {
    color: "#3ddc97",
    fontSize: 12,
    marginTop: 10,
  },
  errorMsg: {
    color: "#ff7b7b",
    fontSize: 12,
    marginTop: 10,
  },
});
