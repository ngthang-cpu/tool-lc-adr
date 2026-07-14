#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ứng dụng Android LC79 viết bằng Kivy."""

from __future__ import annotations

import json
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.label import Label
from kivy.core.window import Window

from lc79_core import GAMES, GameUpdate, LC79Engine, prediction_to_text


KV = r"""
#:import dp kivy.metrics.dp

<GameCard>:
    orientation: "vertical"
    size_hint_y: None
    height: self.minimum_height
    padding: dp(14)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: (0.09, 0.12, 0.18, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(18)]
    BoxLayout:
        size_hint_y: None
        height: dp(46)
        spacing: dp(8)
        Label:
            text: root.title
            bold: True
            font_size: "19sp"
            color: (0.95, 0.97, 1, 1)
            halign: "left"
            valign: "middle"
            text_size: self.size
        Button:
            text: "DỪNG" if root.running else "BẬT"
            size_hint_x: None
            width: dp(86)
            background_normal: ""
            background_color: (0.78, 0.20, 0.20, 1) if root.running else (0.12, 0.62, 0.38, 1)
            on_release: root.toggle_game()
    Label:
        text: root.status_text
        size_hint_y: None
        height: max(dp(25), self.texture_size[1] + dp(4))
        text_size: self.width, None
        halign: "left"
        valign: "middle"
        color: (0.55, 0.78, 1, 1)
        font_size: "14sp"
    Label:
        text: root.result_text
        size_hint_y: None
        height: max(dp(82), self.texture_size[1] + dp(10))
        text_size: self.width, None
        halign: "left"
        valign: "top"
        color: (0.92, 0.93, 0.96, 1)
        font_size: "15sp"
    Label:
        text: root.evaluation_text
        size_hint_y: None
        height: max(dp(34), self.texture_size[1] + dp(8))
        text_size: self.width, None
        halign: "left"
        valign: "top"
        color: (0.98, 0.78, 0.35, 1)
        font_size: "14sp"
    Label:
        text: root.prediction_text
        size_hint_y: None
        height: max(dp(95), self.texture_size[1] + dp(10))
        text_size: self.width, None
        halign: "left"
        valign: "top"
        color: (0.72, 0.92, 0.80, 1)
        font_size: "14sp"
    Button:
        text: "LÀM MỚI NGAY"
        size_hint_y: None
        height: dp(42)
        background_normal: ""
        background_color: (0.20, 0.34, 0.58, 1)
        on_release: root.refresh_game()

<HomeScreen>:
    name: "home"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: (0.035, 0.05, 0.08, 1)
            Rectangle:
                pos: self.pos
                size: self.size
        BoxLayout:
            size_hint_y: None
            height: dp(74)
            padding: dp(16), dp(10)
            orientation: "vertical"
            Label:
                text: "LC79 - THEO DÕI THỐNG KÊ"
                bold: True
                font_size: "22sp"
                color: (0.95, 0.97, 1, 1)
                halign: "left"
                valign: "middle"
                text_size: self.size
            Label:
                id: global_status
                text: "Chưa bật game nào"
                font_size: "13sp"
                color: (0.55, 0.78, 1, 1)
                halign: "left"
                valign: "middle"
                text_size: self.size
        ScrollView:
            do_scroll_x: False
            bar_width: dp(5)
            GridLayout:
                id: game_list
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                padding: dp(12)
                spacing: dp(12)
        BoxLayout:
            size_hint_y: None
            height: dp(58)
            padding: dp(8)
            spacing: dp(8)
            Button:
                text: "THỐNG KÊ"
                background_normal: ""
                background_color: (0.18, 0.29, 0.48, 1)
                on_release: app.open_stats()
            Button:
                text: "NHẬT KÝ"
                background_normal: ""
                background_color: (0.18, 0.29, 0.48, 1)
                on_release: app.open_logs()
            Button:
                text: "CÀI ĐẶT"
                background_normal: ""
                background_color: (0.18, 0.29, 0.48, 1)
                on_release: app.open_settings()

<StatsScreen>:
    name: "stats"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: (0.035, 0.05, 0.08, 1)
            Rectangle:
                pos: self.pos
                size: self.size
        BoxLayout:
            size_hint_y: None
            height: dp(58)
            padding: dp(8)
            spacing: dp(8)
            Button:
                text: "< TRỞ LẠI"
                size_hint_x: None
                width: dp(110)
                on_release: app.go_home()
            Label:
                text: "THỐNG KÊ"
                bold: True
                font_size: "21sp"
                color: (0.95, 0.97, 1, 1)
        ScrollView:
            do_scroll_x: False
            Label:
                id: stats_label
                text: ""
                size_hint_y: None
                height: max(self.texture_size[1] + dp(30), self.parent.height)
                text_size: self.width - dp(30), None
                padding: dp(15), dp(15)
                halign: "left"
                valign: "top"
                color: (0.92, 0.93, 0.96, 1)
                font_size: "16sp"
        BoxLayout:
            size_hint_y: None
            height: dp(58)
            padding: dp(8)
            spacing: dp(8)
            Button:
                text: "BACKTEST"
                on_release: app.show_backtest()
            Button:
                text: "XÓA THỐNG KÊ"
                background_normal: ""
                background_color: (0.65, 0.24, 0.20, 1)
                on_release: app.confirm_reset_stats()

<LogsScreen>:
    name: "logs"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: (0.035, 0.05, 0.08, 1)
            Rectangle:
                pos: self.pos
                size: self.size
        BoxLayout:
            size_hint_y: None
            height: dp(58)
            padding: dp(8)
            spacing: dp(8)
            Button:
                text: "< TRỞ LẠI"
                size_hint_x: None
                width: dp(110)
                on_release: app.go_home()
            Label:
                text: "NHẬT KÝ HOẠT ĐỘNG"
                bold: True
                font_size: "20sp"
                color: (0.95, 0.97, 1, 1)
        ScrollView:
            do_scroll_x: False
            Label:
                id: logs_label
                text: ""
                size_hint_y: None
                height: max(self.texture_size[1] + dp(30), self.parent.height)
                text_size: self.width - dp(30), None
                padding: dp(15), dp(15)
                halign: "left"
                valign: "top"
                color: (0.82, 0.88, 0.95, 1)
                font_size: "14sp"
        Button:
            text: "XÓA NHẬT KÝ HIỂN THỊ"
            size_hint_y: None
            height: dp(50)
            on_release: app.clear_logs()

<SettingsScreen>:
    name: "settings"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: (0.035, 0.05, 0.08, 1)
            Rectangle:
                pos: self.pos
                size: self.size
        BoxLayout:
            size_hint_y: None
            height: dp(58)
            padding: dp(8)
            spacing: dp(8)
            Button:
                text: "< TRỞ LẠI"
                size_hint_x: None
                width: dp(110)
                on_release: app.go_home()
            Label:
                text: "CÀI ĐẶT"
                bold: True
                font_size: "21sp"
                color: (0.95, 0.97, 1, 1)
        ScrollView:
            do_scroll_x: False
            GridLayout:
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                padding: dp(18)
                spacing: dp(10)
                Label:
                    text: "Access token API Tele68 (có thể để trống)"
                    size_hint_y: None
                    height: dp(34)
                    color: (0.92, 0.93, 0.96, 1)
                    halign: "left"
                    text_size: self.size
                TextInput:
                    id: access_token
                    multiline: False
                    password: True
                    size_hint_y: None
                    height: dp(52)
                    hint_text: "Dán access token tại đây"
                Label:
                    text: "Chu kỳ kiểm tra (giây, tối thiểu 5)"
                    size_hint_y: None
                    height: dp(34)
                    color: (0.92, 0.93, 0.96, 1)
                    halign: "left"
                    text_size: self.size
                TextInput:
                    id: interval_input
                    multiline: False
                    input_filter: "int"
                    size_hint_y: None
                    height: dp(52)
                    hint_text: "10"
                Button:
                    text: "LƯU CÀI ĐẶT"
                    size_hint_y: None
                    height: dp(52)
                    background_normal: ""
                    background_color: (0.12, 0.62, 0.38, 1)
                    on_release: app.save_settings_from_ui()
                Label:
                    id: settings_status
                    text: ""
                    size_hint_y: None
                    height: max(dp(34), self.texture_size[1] + dp(8))
                    text_size: self.width, None
                    color: (0.55, 0.78, 1, 1)
                    halign: "left"
                Label:
                    text: "Ứng dụng chỉ theo dõi khi đang mở. Dự đoán là thống kê tham khảo, không bảo đảm thắng và ứng dụng không tự đặt cược."
                    size_hint_y: None
                    height: max(dp(80), self.texture_size[1] + dp(12))
                    text_size: self.width, None
                    color: (0.95, 0.72, 0.45, 1)
                    halign: "left"
                    valign: "top"
                Button:
                    text: "XÓA TOÀN BỘ LỊCH SỬ VÀ DỮ LIỆU"
                    size_hint_y: None
                    height: dp(52)
                    background_normal: ""
                    background_color: (0.65, 0.18, 0.18, 1)
                    on_release: app.confirm_clear_all()

ScreenManager:
    HomeScreen:
    StatsScreen:
    LogsScreen:
    SettingsScreen:
"""


class GameCard(BoxLayout):
    game_key = StringProperty("")
    title = StringProperty("")
    running = BooleanProperty(False)
    status_text = StringProperty("Đang chờ bật theo dõi")
    result_text = StringProperty("Chưa có dữ liệu")
    evaluation_text = StringProperty("")
    prediction_text = StringProperty("Chưa đủ dữ liệu để dự đoán")

    def toggle_game(self) -> None:
        app = App.get_running_app()
        app.toggle_game(self.game_key)

    def refresh_game(self) -> None:
        app = App.get_running_app()
        app.refresh_game(self.game_key, manual=True)


class HomeScreen(Screen):
    pass


class StatsScreen(Screen):
    pass


class LogsScreen(Screen):
    pass


class SettingsScreen(Screen):
    pass


class LC79App(App):
    title = "LC79 Thống Kê"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.engine: LC79Engine | None = None
        self.cards: dict[str, GameCard] = {}
        self.active_games: set[str] = set()
        self.in_flight: set[str] = set()
        self.next_due: dict[str, float] = {}
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="lc79")
        self.logs: deque[str] = deque(maxlen=120)
        self.interval = 10
        self.config_file: Path | None = None

    def build(self):
        Window.clearcolor = (0.035, 0.05, 0.08, 1)
        self.config_file = Path(self.user_data_dir) / "lc79_app_config.json"
        config = self._load_app_config()
        self.interval = max(5, int(config.get("interval", 10)))
        access_token = str(config.get("access_token", ""))
        self.engine = LC79Engine(self.user_data_dir, access_token=access_token)

        root = Builder.load_string(KV)
        home = root.get_screen("home")
        for game_key, game in GAMES.items():
            card = GameCard(game_key=game_key, title=game["name"])
            self.cards[game_key] = card
            home.ids.game_list.add_widget(card)
            self._restore_card(game_key)

        settings = root.get_screen("settings")
        settings.ids.access_token.text = access_token
        settings.ids.interval_input.text = str(self.interval)

        Window.bind(on_keyboard=self._on_keyboard)
        Clock.schedule_interval(self._poll, 1.0)
        Clock.schedule_once(lambda _dt: self._enable_keep_screen_on(), 0.5)
        self._append_log("Ứng dụng đã khởi động.")
        self._update_global_status()
        return root

    def _load_app_config(self) -> dict[str, Any]:
        if self.config_file is None or not self.config_file.exists():
            return {}
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_app_config(self) -> None:
        if self.config_file is None or self.engine is None:
            return
        data = {
            "access_token": self.engine.access_token,
            "interval": self.interval,
        }
        temp = self.config_file.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.config_file)

    def _enable_keep_screen_on(self) -> None:
        try:
            from jnius import autoclass

            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            layout_params = autoclass("android.view.WindowManager$LayoutParams")
            activity.getWindow().addFlags(layout_params.FLAG_KEEP_SCREEN_ON)
        except Exception:
            # Chạy trên Windows/Linux hoặc thiết bị không hỗ trợ thì bỏ qua.
            pass

    def _restore_card(self, game_key: str) -> None:
        if self.engine is None:
            return
        saved = self.engine.get_last_update(game_key)
        if not saved:
            return
        card = self.cards[game_key]
        card.result_text = str(saved.get("result_summary", "Chưa có dữ liệu"))
        card.evaluation_text = str(saved.get("evaluation", ""))
        prediction = saved.get("prediction")
        if isinstance(prediction, dict):
            # Dựng lại nội dung ngắn từ dict đã lưu.
            probs = prediction.get("probabilities", {})
            prob_text = " | ".join(
                f"{key} {float(value) * 100:.1f}%"
                for key, value in probs.items()
            )
            card.prediction_text = (
                f"Dự đoán phiên tiếp: {prediction.get('prediction', '?')}\n"
                f"Độ nghiêng thống kê: {prediction.get('confidence', 50)}%\n"
                f"Xác suất mô hình: {prob_text}"
            )
        timestamp = int(saved.get("updated_at", 0))
        if timestamp:
            card.status_text = "Dữ liệu đã lưu: " + datetime.fromtimestamp(timestamp).strftime(
                "%d/%m %H:%M:%S"
            )

    def toggle_game(self, game_key: str) -> None:
        if game_key not in GAMES:
            return
        card = self.cards[game_key]
        if game_key in self.active_games:
            self.active_games.discard(game_key)
            self.next_due.pop(game_key, None)
            card.running = False
            card.status_text = "Đã dừng theo dõi"
            self._append_log(f"Đã dừng {GAMES[game_key]['name']}.")
        else:
            self.active_games.add(game_key)
            self.next_due[game_key] = 0.0
            card.running = True
            card.status_text = "Đã bật, đang chuẩn bị lấy dữ liệu..."
            self._append_log(f"Đã bật {GAMES[game_key]['name']}.")
        self._update_global_status()

    def refresh_game(self, game_key: str, manual: bool = False) -> None:
        if game_key not in GAMES or self.engine is None:
            return
        if game_key in self.in_flight:
            if manual:
                self.cards[game_key].status_text = "Đang lấy dữ liệu, vui lòng chờ..."
            return

        self.in_flight.add(game_key)
        self.cards[game_key].status_text = "Đang kết nối API..."
        future = self.executor.submit(self.engine.fetch_and_process, game_key)
        future.add_done_callback(
            lambda done, key=game_key: Clock.schedule_once(
                lambda _dt: self._finish_fetch(key, done), 0
            )
        )

    def _finish_fetch(self, game_key: str, future: Future) -> None:
        self.in_flight.discard(game_key)
        card = self.cards[game_key]
        self.next_due[game_key] = time.monotonic() + self.interval

        try:
            update: GameUpdate = future.result()
        except Exception as error:
            card.status_text = f"Lỗi: {error}"
            self._append_log(f"{GAMES[game_key]['name']}: {error}")
            return

        card.result_text = update.result_summary
        card.evaluation_text = update.evaluation
        card.prediction_text = prediction_to_text(update.prediction)
        now_text = datetime.fromtimestamp(update.updated_at).strftime("%H:%M:%S")
        if update.is_new:
            card.status_text = f"Có dữ liệu mới lúc {now_text}"
            self._append_log(
                f"{GAMES[game_key]['name']}: {update.actual_result} - {update.evaluation.splitlines()[0]}"
            )
        else:
            card.status_text = f"Chưa có dữ liệu mới - kiểm tra {now_text}"

    def _poll(self, _dt: float) -> None:
        now = time.monotonic()
        for game_key in list(self.active_games):
            if game_key in self.in_flight:
                continue
            if now >= self.next_due.get(game_key, 0.0):
                self.refresh_game(game_key)

    def _update_global_status(self) -> None:
        if not self.root:
            return
        home = self.root.get_screen("home")
        if not self.active_games:
            home.ids.global_status.text = "Chưa bật game nào"
            return
        names = ", ".join(GAMES[key]["name"] for key in sorted(self.active_games))
        home.ids.global_status.text = (
            f"Đang theo dõi mỗi {self.interval} giây: {names}"
        )

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%d/%m %H:%M:%S")
        self.logs.appendleft(f"[{timestamp}] {message}")
        if self.root:
            self.root.get_screen("logs").ids.logs_label.text = "\n\n".join(self.logs)

    def clear_logs(self) -> None:
        self.logs.clear()
        self.root.get_screen("logs").ids.logs_label.text = ""

    def go_home(self) -> None:
        self.root.current = "home"

    def open_stats(self) -> None:
        if self.engine is None:
            return
        self.root.get_screen("stats").ids.stats_label.text = self.engine.stats_text()
        self.root.current = "stats"

    def show_backtest(self) -> None:
        if self.engine is None:
            return
        self.root.get_screen("stats").ids.stats_label.text = self.engine.backtest_text()

    def open_logs(self) -> None:
        self.root.get_screen("logs").ids.logs_label.text = "\n\n".join(self.logs)
        self.root.current = "logs"

    def open_settings(self) -> None:
        if self.engine is None:
            return
        screen = self.root.get_screen("settings")
        screen.ids.access_token.text = self.engine.access_token
        screen.ids.interval_input.text = str(self.interval)
        screen.ids.settings_status.text = ""
        self.root.current = "settings"

    def save_settings_from_ui(self) -> None:
        if self.engine is None:
            return
        screen = self.root.get_screen("settings")
        token = screen.ids.access_token.text.strip()
        try:
            interval = max(5, int(screen.ids.interval_input.text.strip() or "10"))
        except ValueError:
            screen.ids.settings_status.text = "Chu kỳ phải là số nguyên."
            return

        self.interval = interval
        self.engine.set_access_token(token)
        self._save_app_config()
        screen.ids.interval_input.text = str(interval)
        screen.ids.settings_status.text = "Đã lưu cài đặt."
        self._append_log(f"Đã lưu cài đặt, chu kỳ {interval} giây.")
        self._update_global_status()

    def confirm_reset_stats(self) -> None:
        self._confirm_popup(
            title="Xóa thống kê?",
            message="Xóa số lần đúng/sai và dự đoán đang chờ. Lịch sử kết quả vẫn được giữ.",
            action=self._reset_stats,
        )

    def _reset_stats(self) -> None:
        if self.engine is None:
            return
        self.engine.reset_stats()
        self.root.get_screen("stats").ids.stats_label.text = self.engine.stats_text()
        self._append_log("Đã xóa thống kê đúng/sai.")

    def confirm_clear_all(self) -> None:
        self._confirm_popup(
            title="Xóa toàn bộ dữ liệu?",
            message="Thao tác này xóa lịch sử, thống kê, dự đoán chờ và dữ liệu phiên đã lưu.",
            action=self._clear_all,
        )

    def _clear_all(self) -> None:
        if self.engine is None:
            return
        self.engine.clear_all_data()
        for card in self.cards.values():
            card.result_text = "Chưa có dữ liệu"
            card.evaluation_text = ""
            card.prediction_text = "Chưa đủ dữ liệu để dự đoán"
            card.status_text = "Dữ liệu đã được xóa"
        self.root.get_screen("settings").ids.settings_status.text = "Đã xóa toàn bộ dữ liệu."
        self._append_log("Đã xóa toàn bộ lịch sử và dữ liệu.")

    def _confirm_popup(self, title: str, message: str, action) -> None:
        content = BoxLayout(orientation="vertical", padding=14, spacing=10)
        content.add_widget(Label(text=message, text_size=(320, None), halign="center"))
        buttons = BoxLayout(size_hint_y=None, height=50, spacing=8)
        from kivy.uix.button import Button

        cancel = Button(text="HỦY")
        confirm = Button(text="XÁC NHẬN")
        buttons.add_widget(cancel)
        buttons.add_widget(confirm)
        content.add_widget(buttons)
        popup = Popup(
            title=title,
            content=content,
            size_hint=(0.88, 0.38),
            auto_dismiss=False,
        )
        cancel.bind(on_release=popup.dismiss)

        def run_action(*_args):
            popup.dismiss()
            action()

        confirm.bind(on_release=run_action)
        popup.open()

    def _on_keyboard(self, _window, key, *_args) -> bool:
        if key == 27 and self.root and self.root.current != "home":
            self.go_home()
            return True
        return False

    def on_pause(self) -> bool:
        try:
            self._save_app_config()
            if self.engine is not None:
                self.engine.save_state()
        except Exception:
            pass
        return True

    def on_stop(self) -> None:
        try:
            self._save_app_config()
            if self.engine is not None:
                self.engine.save_state()
        finally:
            self.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    LC79App().run()
