#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lõi dữ liệu và thống kê cho ứng dụng LC79 Android.

Được viết lại từ hai file bot Telegram/Windows do người dùng cung cấp.
Không đăng nhập tài khoản, không đặt cược và không bảo đảm dự đoán đúng.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


REQUEST_TIMEOUT = 15
MIN_PREDICTION_HISTORY = 6
DEFAULT_HISTORY_LIMIT = 400

GAMES: dict[str, dict[str, Any]] = {
    "txmd5": {
        "name": "Tài Xỉu MD5",
        "type": "session",
        "url": "https://wtxmd52.tele68.com/v1/txmd5/lite-sessions",
        "params": {"cp": "R", "cl": "R", "pf": "web"},
        "choices": ("TÀI", "XỈU"),
    },
    "xocdia": {
        "name": "Xóc Đĩa",
        "type": "session",
        "url": "https://wcl.tele68.com/v1/chanlefull/lite-sessions",
        "params": {"cp": "R", "cl": "R", "pf": "web"},
        "choices": ("CHẴN", "LẺ"),
    },
    "nohu": {
        "name": "Nổ Hũ / Jackpot",
        "type": "jackpot",
        "url": "https://gameapi.tele68.com/v1/top-jack-pot/data-update",
        "params": {"cp": "R", "cl": "R", "pf": "web"},
        "choices": ("TĂNG", "GIẢM"),
    },
}

ALGORITHM_LABELS = {
    "weighted_frequency": "Tần suất trọng số",
    "markov_1": "Markov bậc 1",
    "markov_2": "Markov bậc 2",
    "pattern_match": "Khớp mẫu chuỗi",
    "run_length": "Độ dài chuỗi",
}

BASE_ALGORITHM_WEIGHTS = {
    "weighted_frequency": 1.00,
    "markov_1": 1.20,
    "markov_2": 1.35,
    "pattern_match": 1.50,
    "run_length": 1.05,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13) "
        "AppleWebKit/537.36 Chrome/150 Mobile Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


@dataclass
class AlgorithmOutput:
    probabilities: dict[str, float]
    explanation: str


@dataclass
class PredictionOutput:
    prediction: str
    confidence: int
    probabilities: dict[str, float]
    votes: dict[str, str]
    details: dict[str, str]
    reason: str


@dataclass
class GameUpdate:
    game_key: str
    game_name: str
    is_new: bool
    data_id: str
    actual_result: str
    result_summary: str
    evaluation: str
    prediction: Optional[PredictionOutput]
    updated_at: int

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


class LC79Error(RuntimeError):
    """Lỗi thân thiện để giao diện hiển thị."""


class LC79Engine:
    def __init__(
        self,
        storage_dir: str | Path,
        access_token: str = "",
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.storage_dir / "lc79_app_state.json"
        self.access_token = access_token.strip()
        self.history_limit = max(100, int(history_limit))
        self.lock = threading.RLock()

        self.history: dict[str, deque[str]] = {
            key: deque(maxlen=self.history_limit) for key in GAMES
        }
        self.pending_predictions: dict[str, dict[str, Any]] = {}
        self.stats: dict[str, dict[str, Any]] = {
            key: self._empty_game_stats() for key in GAMES
        }
        self.last_seen_ids: dict[str, str] = {}
        self.last_jackpot_totals: dict[str, float] = {}
        self.last_updates: dict[str, dict[str, Any]] = {}

        self.http_session = self._create_http_session()
        self.load_state()

    @staticmethod
    def _create_http_session() -> requests.Session:
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.7,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=10,
            pool_maxsize=10,
        )
        session = requests.Session()
        session.headers.update(HEADERS)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    @staticmethod
    def _empty_game_stats() -> dict[str, Any]:
        return {
            "correct": 0,
            "wrong": 0,
            "algorithms": {
                name: {"correct": 0, "wrong": 0}
                for name in ALGORITHM_LABELS
            },
        }

    def set_access_token(self, access_token: str) -> None:
        self.access_token = access_token.strip()

    def load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            with self.lock:
                for game_key, items in raw.get("history", {}).items():
                    if game_key not in self.history or not isinstance(items, list):
                        continue
                    choices = set(GAMES[game_key]["choices"])
                    self.history[game_key].extend(
                        str(item).upper()
                        for item in items[-self.history_limit :]
                        if str(item).upper() in choices
                    )

                for game_key, value in raw.get("stats", {}).items():
                    if game_key not in GAMES or not isinstance(value, dict):
                        continue
                    target = self._empty_game_stats()
                    target["correct"] = int(value.get("correct", 0))
                    target["wrong"] = int(value.get("wrong", 0))
                    raw_algorithms = value.get("algorithms", {})
                    if isinstance(raw_algorithms, dict):
                        for name in ALGORITHM_LABELS:
                            item = raw_algorithms.get(name, {})
                            if isinstance(item, dict):
                                target["algorithms"][name] = {
                                    "correct": int(item.get("correct", 0)),
                                    "wrong": int(item.get("wrong", 0)),
                                }
                    self.stats[game_key] = target

                pending = raw.get("pending_predictions", {})
                if isinstance(pending, dict):
                    self.pending_predictions = {
                        key: value
                        for key, value in pending.items()
                        if key in GAMES and isinstance(value, dict)
                    }

                ids = raw.get("last_seen_ids", {})
                if isinstance(ids, dict):
                    self.last_seen_ids = {
                        key: str(value)
                        for key, value in ids.items()
                        if key in GAMES
                    }

                totals = raw.get("last_jackpot_totals", {})
                if isinstance(totals, dict):
                    for key, value in totals.items():
                        if key in GAMES:
                            try:
                                self.last_jackpot_totals[key] = float(value)
                            except (TypeError, ValueError):
                                pass

                updates = raw.get("last_updates", {})
                if isinstance(updates, dict):
                    self.last_updates = {
                        key: value
                        for key, value in updates.items()
                        if key in GAMES and isinstance(value, dict)
                    }
        except Exception:
            # Không làm ứng dụng chết nếu file trạng thái cũ bị hỏng.
            return

    def save_state(self) -> None:
        with self.lock:
            data = {
                "version": 3,
                "saved_at": int(time.time()),
                "history": {
                    game_key: list(items)
                    for game_key, items in self.history.items()
                },
                "stats": self.stats,
                "pending_predictions": self.pending_predictions,
                "last_seen_ids": self.last_seen_ids,
                "last_jackpot_totals": self.last_jackpot_totals,
                "last_updates": self.last_updates,
            }
        temp_file = self.state_file.with_suffix(".json.tmp")
        try:
            temp_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_file.replace(self.state_file)
        except OSError as error:
            raise LC79Error(f"Không lưu được dữ liệu ứng dụng: {error}") from error

    def get_game_data(self, game_key: str) -> dict[str, Any]:
        game = GAMES.get(game_key)
        if game is None:
            raise LC79Error("Game không tồn tại.")

        params = dict(game.get("params", {}))
        if self.access_token:
            params["at"] = self.access_token

        try:
            response = self.http_session.get(
                game["url"],
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.Timeout as error:
            raise LC79Error("API phản hồi quá chậm. Hãy kiểm tra mạng.") from error
        except requests.ConnectionError as error:
            raise LC79Error("Không kết nối được API. Hãy kiểm tra mạng hoặc tên miền.") from error
        except requests.HTTPError as error:
            status = getattr(error.response, "status_code", "?")
            raise LC79Error(
                f"API trả lỗi HTTP {status}. Access token hoặc endpoint có thể đã đổi."
            ) from error
        except requests.RequestException as error:
            raise LC79Error(f"Lỗi mạng: {error}") from error

        try:
            data = response.json()
        except ValueError as error:
            preview = response.text[:160].replace("\n", " ")
            raise LC79Error(f"API không trả JSON: {preview}") from error

        if not isinstance(data, dict):
            raise LC79Error("API không trả dữ liệu JSON dạng object.")
        return data

    def fetch_and_process(self, game_key: str) -> GameUpdate:
        data = self.get_game_data(game_key)
        return self.process_payload(game_key, data)

    def process_payload(self, game_key: str, data: dict[str, Any]) -> GameUpdate:
        if game_key not in GAMES:
            raise LC79Error("Game không tồn tại.")
        if GAMES[game_key]["type"] == "jackpot":
            return self._process_jackpot(game_key, data)
        return self._process_session(game_key, data)

    def _process_session(self, game_key: str, data: dict[str, Any]) -> GameUpdate:
        parsed = parse_session_game(game_key, data)
        data_id = parsed["id"]
        actual = parsed["result"]
        summary = (
            f"Phiên {data_id}\n"
            f"Kết quả: {actual}\n"
            f"Điểm/Tổng: {parsed['point']}\n"
            f"Chi tiết: {parsed['detail']}"
        )

        with self.lock:
            if self.last_seen_ids.get(game_key) == data_id:
                prediction = self._current_prediction(game_key)
                return GameUpdate(
                    game_key=game_key,
                    game_name=GAMES[game_key]["name"],
                    is_new=False,
                    data_id=data_id,
                    actual_result=actual,
                    result_summary=summary,
                    evaluation="Chưa có phiên mới.",
                    prediction=prediction,
                    updated_at=int(time.time()),
                )

            evaluation = self._evaluate_prediction(game_key, actual, data_id)
            if actual in set(GAMES[game_key]["choices"]):
                self.history[game_key].append(actual)
            self.last_seen_ids[game_key] = data_id
            prediction = self._save_next_prediction(game_key, data_id)

            update = GameUpdate(
                game_key=game_key,
                game_name=GAMES[game_key]["name"],
                is_new=True,
                data_id=data_id,
                actual_result=actual,
                result_summary=summary,
                evaluation=evaluation,
                prediction=prediction,
                updated_at=int(time.time()),
            )
            self.last_updates[game_key] = update.to_dict()
            self.save_state()
            return update

    def _process_jackpot(self, game_key: str, data: dict[str, Any]) -> GameUpdate:
        parsed = parse_jackpot_game(data)
        data_id = parsed["id"]
        total = float(parsed["total"])
        summary = f"{parsed['text']}\nTổng số đọc được: {total:,.2f}"

        with self.lock:
            previous_total = self.last_jackpot_totals.get(game_key)
            if self.last_seen_ids.get(game_key) == data_id:
                return GameUpdate(
                    game_key=game_key,
                    game_name=GAMES[game_key]["name"],
                    is_new=False,
                    data_id=data_id,
                    actual_result="CHƯA ĐỔI",
                    result_summary=summary,
                    evaluation="Chưa có biến động jackpot mới.",
                    prediction=self._current_prediction(game_key),
                    updated_at=int(time.time()),
                )

            actual = ""
            if previous_total is not None:
                if total > previous_total:
                    actual = "TĂNG"
                elif total < previous_total:
                    actual = "GIẢM"

            evaluation = (
                self._evaluate_prediction(game_key, actual, data_id)
                if actual
                else "Đã ghi mốc jackpot đầu tiên."
            )
            if actual in set(GAMES[game_key]["choices"]):
                self.history[game_key].append(actual)

            self.last_seen_ids[game_key] = data_id
            self.last_jackpot_totals[game_key] = total
            prediction = self._save_next_prediction(game_key, data_id)

            update = GameUpdate(
                game_key=game_key,
                game_name=GAMES[game_key]["name"],
                is_new=True,
                data_id=data_id,
                actual_result=actual or "MỐC ĐẦU",
                result_summary=summary,
                evaluation=evaluation,
                prediction=prediction,
                updated_at=int(time.time()),
            )
            self.last_updates[game_key] = update.to_dict()
            self.save_state()
            return update

    def _current_prediction(self, game_key: str) -> Optional[PredictionOutput]:
        pending = self.pending_predictions.get(game_key)
        if not pending:
            return None
        try:
            return PredictionOutput(
                prediction=str(pending["prediction"]),
                confidence=int(pending.get("confidence", 50)),
                probabilities={
                    str(key): float(value)
                    for key, value in pending.get("probabilities", {}).items()
                },
                votes={
                    str(key): str(value)
                    for key, value in pending.get("votes", {}).items()
                },
                details={},
                reason=str(pending.get("reason", "Dự đoán đang chờ chấm.")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _save_next_prediction(
        self,
        game_key: str,
        current_id: str,
    ) -> Optional[PredictionOutput]:
        output = self.predict_from_sequence(game_key, list(self.history[game_key]))
        if output is None:
            self.pending_predictions.pop(game_key, None)
            return None
        self.pending_predictions[game_key] = {
            "source_id": current_id,
            "prediction": output.prediction,
            "confidence": output.confidence,
            "probabilities": output.probabilities,
            "votes": output.votes,
            "reason": output.reason,
            "created_at": int(time.time()),
        }
        return output

    def _evaluate_prediction(
        self,
        game_key: str,
        actual_result: str,
        current_id: str,
    ) -> str:
        pending = self.pending_predictions.get(game_key)
        if not pending:
            return "Chưa có dự đoán trước để chấm."
        if str(pending.get("source_id")) == str(current_id):
            return "Đang chờ phiên tiếp theo để chấm."

        choices = set(GAMES[game_key]["choices"])
        actual = normalize_text(actual_result)
        prediction = normalize_text(pending.get("prediction", ""))
        if actual not in choices or prediction not in choices:
            return "Không chấm được vì kết quả API không hợp lệ."

        game_stats = self.stats.setdefault(game_key, self._empty_game_stats())
        correct = prediction == actual
        if correct:
            game_stats["correct"] += 1
            headline = "ĐÚNG"
        else:
            game_stats["wrong"] += 1
            headline = "SAI"

        lines = [
            f"Dự đoán trước: {prediction}",
            f"Kết quả thật: {actual}",
            f"Đánh giá: {headline}",
        ]

        votes = pending.get("votes", {})
        if isinstance(votes, dict):
            model_lines = []
            for name, vote in votes.items():
                if name not in ALGORITHM_LABELS or vote not in choices:
                    continue
                target = game_stats["algorithms"].setdefault(
                    name, {"correct": 0, "wrong": 0}
                )
                if vote == actual:
                    target["correct"] += 1
                    mark = "đúng"
                else:
                    target["wrong"] += 1
                    mark = "sai"
                model_lines.append(f"{ALGORITHM_LABELS[name]}: {vote} ({mark})")
            if model_lines:
                lines.append("Mô hình: " + "; ".join(model_lines))

        self.pending_predictions.pop(game_key, None)
        return "\n".join(lines)

    def predict_from_sequence(
        self,
        game_key: str,
        sequence: list[str],
    ) -> Optional[PredictionOutput]:
        choices = tuple(GAMES[game_key]["choices"])
        valid = [value for value in sequence if value in choices]
        if len(valid) < MIN_PREDICTION_HISTORY:
            return None

        outputs = collect_algorithm_outputs(valid, choices)
        if not outputs:
            return None

        ensemble_scores = {choice: 0.0 for choice in choices}
        total_weight = 0.0
        votes: dict[str, str] = {}
        details: dict[str, str] = {}

        for name, output in outputs.items():
            weight = BASE_ALGORITHM_WEIGHTS[name] * self._performance_multiplier(
                game_key, name
            )
            for choice in choices:
                ensemble_scores[choice] += output.probabilities[choice] * weight
            votes[name] = max(choices, key=lambda c: output.probabilities[c])
            details[name] = output.explanation
            total_weight += weight

        probabilities = {
            choice: ensemble_scores[choice] / total_weight
            for choice in choices
        }
        first, second = choices
        if math.isclose(probabilities[first], probabilities[second], abs_tol=1e-9):
            prediction = votes.get("weighted_frequency", first)
        else:
            prediction = max(choices, key=lambda c: probabilities[c])

        sorted_probs = sorted(probabilities.values(), reverse=True)
        margin = sorted_probs[0] - sorted_probs[1]
        data_factor = min(len(valid) / 80.0, 1.0)
        model_factor = min(len(outputs) / len(ALGORITHM_LABELS), 1.0)
        confidence = round(50 + margin * 32 + data_factor * 4 + model_factor * 3)
        confidence = max(50, min(confidence, 78))

        recent = Counter(valid[-20:])
        vote_counter = Counter(votes.values())
        reason = (
            f"{len(outputs)} mô hình; phiếu {dict(vote_counter)}; "
            f"20 phiên {dict(recent)}"
        )
        return PredictionOutput(
            prediction=prediction,
            confidence=confidence,
            probabilities=probabilities,
            votes=votes,
            details=details,
            reason=reason,
        )

    def _performance_multiplier(self, game_key: str, algorithm: str) -> float:
        value = self.stats.setdefault(game_key, self._empty_game_stats())[
            "algorithms"
        ].setdefault(algorithm, {"correct": 0, "wrong": 0})
        correct = int(value.get("correct", 0))
        wrong = int(value.get("wrong", 0))
        total = correct + wrong
        accuracy = (correct + 2) / (total + 4)
        sample_factor = min(total / 30.0, 1.0)
        return 1.0 + (accuracy - 0.5) * 1.2 * sample_factor

    def walk_forward_backtest(
        self,
        game_key: str,
        max_tests: int = 100,
    ) -> dict[str, Any]:
        with self.lock:
            sequence = list(self.history[game_key])
        choices = set(GAMES[game_key]["choices"])
        sequence = [value for value in sequence if value in choices]
        if len(sequence) < 18:
            return {"tested": 0, "correct": 0, "wrong": 0, "rate": 0.0}

        start = max(MIN_PREDICTION_HISTORY, len(sequence) - max_tests)
        correct = 0
        wrong = 0
        for index in range(start, len(sequence)):
            prediction = self.predict_from_sequence(game_key, sequence[:index])
            if prediction is None:
                continue
            if prediction.prediction == sequence[index]:
                correct += 1
            else:
                wrong += 1
        tested = correct + wrong
        return {
            "tested": tested,
            "correct": correct,
            "wrong": wrong,
            "rate": correct / tested * 100 if tested else 0.0,
        }

    def stats_text(self) -> str:
        sections = ["THỐNG KÊ DỰ ĐOÁN"]
        for game_key in GAMES:
            sections.append(self.game_stats_text(game_key))
        sections.append("Tỷ lệ quá khứ không bảo đảm kết quả tương lai.")
        return "\n\n".join(sections)

    def game_stats_text(self, game_key: str) -> str:
        with self.lock:
            value = self.stats.setdefault(game_key, self._empty_game_stats())
            correct = int(value["correct"])
            wrong = int(value["wrong"])
            history_count = len(self.history[game_key])
            algorithms = json.loads(json.dumps(value["algorithms"]))

        total = correct + wrong
        rate = correct / total * 100 if total else 0.0
        rows: list[tuple[str, float, int]] = []
        for name, item in algorithms.items():
            c = int(item.get("correct", 0))
            w = int(item.get("wrong", 0))
            count = c + w
            rows.append((name, c / count * 100 if count else 0.0, count))
        rows.sort(key=lambda item: (item[2] > 0, item[1], item[2]), reverse=True)

        lines = [
            GAMES[game_key]["name"],
            f"Đúng: {correct}",
            f"Sai: {wrong}",
            f"Tỷ lệ: {rate:.1f}%",
            f"Lịch sử: {history_count} kết quả",
        ]
        for name, algo_rate, count in rows[:3]:
            if count:
                lines.append(
                    f"- {ALGORITHM_LABELS[name]}: {algo_rate:.1f}% ({count} lần)"
                )
        return "\n".join(lines)

    def backtest_text(self) -> str:
        sections = ["BACKTEST TUẦN TỰ"]
        for game_key in GAMES:
            result = self.walk_forward_backtest(game_key)
            if not result["tested"]:
                text = f"{GAMES[game_key]['name']}: chưa đủ lịch sử (cần khoảng 18 phiên)."
            else:
                text = (
                    f"{GAMES[game_key]['name']}\n"
                    f"Kiểm tra: {result['tested']}\n"
                    f"Đúng: {result['correct']} | Sai: {result['wrong']}\n"
                    f"Tỷ lệ khớp lịch sử: {result['rate']:.1f}%"
                )
            sections.append(text)
        sections.append("Backtest không chứng minh hiệu quả ở phiên tương lai.")
        return "\n\n".join(sections)

    def reset_stats(self) -> None:
        with self.lock:
            self.stats = {key: self._empty_game_stats() for key in GAMES}
            self.pending_predictions.clear()
            self.save_state()

    def clear_all_data(self) -> None:
        with self.lock:
            self.history = {
                key: deque(maxlen=self.history_limit) for key in GAMES
            }
            self.pending_predictions.clear()
            self.stats = {key: self._empty_game_stats() for key in GAMES}
            self.last_seen_ids.clear()
            self.last_jackpot_totals.clear()
            self.last_updates.clear()
            self.save_state()

    def get_last_update(self, game_key: str) -> Optional[dict[str, Any]]:
        with self.lock:
            value = self.last_updates.get(game_key)
            return json.loads(json.dumps(value)) if value else None


def normalize_text(value: Any) -> str:
    return str(value).strip().upper()


def normalize_session_result(game_key: str, raw_result: Any, point: Any) -> str:
    text = normalize_text(raw_result)
    if game_key == "txmd5":
        if "TÀI" in text or text == "TAI":
            return "TÀI"
        if "XỈU" in text or text == "XIU":
            return "XỈU"
        try:
            total = int(float(point))
            return "TÀI" if total >= 11 else "XỈU"
        except (TypeError, ValueError):
            return text

    if game_key == "xocdia":
        if "CHẴN" in text or text == "CHAN":
            return "CHẴN"
        if "LẺ" in text or text == "LE":
            return "LẺ"
        try:
            total = int(float(point))
            return "CHẴN" if total % 2 == 0 else "LẺ"
        except (TypeError, ValueError):
            return text
    return text


def find_session_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    direct_keys = ("list", "sessions", "items", "results")
    for key in direct_keys:
        value = data.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value

    nested = data.get("data")
    if isinstance(nested, list) and nested and isinstance(nested[0], dict):
        return nested
    if isinstance(nested, dict):
        for key in direct_keys:
            value = nested.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
    raise LC79Error("Không tìm thấy danh sách phiên trong JSON API.")


def numeric_session_id(item: dict[str, Any]) -> Optional[int]:
    for key in ("id", "sessionId", "sid", "_id", "session"):
        try:
            return int(str(item.get(key)))
        except (TypeError, ValueError):
            continue
    return None


def select_latest_session(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    numeric = [(numeric_session_id(item), item) for item in sessions]
    numeric = [(sid, item) for sid, item in numeric if sid is not None]
    if numeric:
        return max(numeric, key=lambda pair: pair[0])[1]
    return sessions[0]


def first_non_empty(
    item: dict[str, Any],
    keys: tuple[str, ...],
    default: Any,
) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return default


def parse_session_game(game_key: str, data: dict[str, Any]) -> dict[str, Any]:
    current = select_latest_session(find_session_list(data))
    session_id = first_non_empty(
        current, ("id", "sessionId", "sid", "_id", "session"), "Không rõ"
    )
    raw_result = first_non_empty(
        current,
        ("resultTruyenThong", "result", "ketQua", "type", "winType"),
        "Không rõ",
    )
    point = first_non_empty(current, ("point", "total", "score", "sum"), "Không rõ")
    dices = first_non_empty(
        current, ("dices", "dice", "plates", "coins", "values"), []
    )
    detail = " - ".join(str(value) for value in dices) if isinstance(dices, list) else str(dices)
    return {
        "id": str(session_id),
        "result": normalize_session_result(game_key, raw_result, point),
        "point": point,
        "detail": detail or "Không rõ",
    }


def parse_jackpot_game(data: dict[str, Any]) -> dict[str, Any]:
    values: list[str] = []
    numeric_total = 0.0
    source = data.get("data") if isinstance(data.get("data"), dict) else data
    for game_name, jackpots in source.items():
        if not isinstance(jackpots, list):
            continue
        display_values: list[str] = []
        for value in jackpots[:3]:
            if isinstance(value, (int, float)):
                numeric_total += float(value)
                display_values.append(f"{value:,}")
            elif value is None:
                display_values.append("-")
            else:
                display_values.append(str(value))
        status = "ON" if len(jackpots) > 3 and jackpots[3] == 1 else "OFF"
        values.append(f"{game_name}: {' | '.join(display_values)} | {status}")
    if not values:
        raise LC79Error("API Jackpot không có dữ liệu danh sách hợp lệ.")
    canonical = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return {
        "id": digest,
        "text": "\n".join(values[:20]),
        "total": round(numeric_total, 2),
    }


def normalize_probabilities(
    scores: dict[str, float],
    choices: tuple[str, str],
) -> dict[str, float]:
    cleaned = {choice: max(0.0, float(scores.get(choice, 0.0))) for choice in choices}
    total = sum(cleaned.values())
    if total <= 0:
        return {choice: 0.5 for choice in choices}
    return {choice: cleaned[choice] / total for choice in choices}


def weighted_frequency(sequence: list[str], choices: tuple[str, str]) -> AlgorithmOutput:
    recent = sequence[-40:]
    scores = {choice: 0.0 for choice in choices}
    decay = 0.90
    for age, value in enumerate(reversed(recent)):
        if value in scores:
            scores[value] += decay**age
    return AlgorithmOutput(
        normalize_probabilities(scores, choices),
        f"Tần suất trọng số trên {len(recent)} phiên gần nhất",
    )


def markov_order_1(
    sequence: list[str], choices: tuple[str, str]
) -> Optional[AlgorithmOutput]:
    if len(sequence) < 4:
        return None
    last = sequence[-1]
    counts = Counter()
    for current, next_value in zip(sequence[:-1], sequence[1:]):
        if current == last and next_value in choices:
            counts[next_value] += 1
    if sum(counts.values()) < 2:
        return None
    scores = {choice: counts[choice] + 1 for choice in choices}
    return AlgorithmOutput(normalize_probabilities(scores, choices), f"Sau {last}: {dict(counts)}")


def markov_order_2(
    sequence: list[str], choices: tuple[str, str]
) -> Optional[AlgorithmOutput]:
    if len(sequence) < 7:
        return None
    context = tuple(sequence[-2:])
    counts = Counter()
    for index in range(len(sequence) - 2):
        if tuple(sequence[index : index + 2]) == context:
            next_value = sequence[index + 2]
            if next_value in choices:
                counts[next_value] += 1
    if sum(counts.values()) < 2:
        return None
    scores = {choice: counts[choice] + 1 for choice in choices}
    return AlgorithmOutput(
        normalize_probabilities(scores, choices),
        f"Sau mẫu {'-'.join(context)}: {dict(counts)}",
    )


def pattern_match(
    sequence: list[str], choices: tuple[str, str]
) -> Optional[AlgorithmOutput]:
    if len(sequence) < 8:
        return None
    scores = {choice: 0.0 for choice in choices}
    matches = 0
    for length in range(2, min(5, len(sequence) - 2) + 1):
        suffix = sequence[-length:]
        for index in range(0, len(sequence) - length):
            if sequence[index : index + length] == suffix:
                next_index = index + length
                if next_index < len(sequence):
                    next_value = sequence[next_index]
                    if next_value in choices:
                        scores[next_value] += float(length * length)
                        matches += 1
    if matches < 2 or sum(scores.values()) <= 0:
        return None
    return AlgorithmOutput(
        normalize_probabilities(scores, choices),
        f"Tìm thấy {matches} lần khớp mẫu dài 2-5",
    )


def current_run(sequence: list[str]) -> tuple[str, int]:
    last = sequence[-1]
    run = 1
    for value in reversed(sequence[:-1]):
        if value != last:
            break
        run += 1
    return last, run


def run_length_model(
    sequence: list[str], choices: tuple[str, str]
) -> Optional[AlgorithmOutput]:
    if len(sequence) < 10:
        return None
    current_value, current_length = current_run(sequence)
    counts: Counter[str] = Counter()
    index = 0
    while index < len(sequence):
        value = sequence[index]
        end = index + 1
        while end < len(sequence) and sequence[end] == value:
            end += 1
        run_length = end - index
        if value == current_value and run_length >= current_length and end < len(sequence):
            next_value = sequence[end]
            if next_value in choices:
                distance = abs(run_length - current_length)
                counts[next_value] += 1.0 / (1.0 + distance)
        index = end
    if sum(counts.values()) <= 0:
        return None
    scores = {choice: float(counts[choice]) + 0.5 for choice in choices}
    return AlgorithmOutput(
        normalize_probabilities(scores, choices),
        f"Chuỗi hiện tại {current_value} x{current_length}",
    )


def collect_algorithm_outputs(
    sequence: list[str],
    choices: tuple[str, str],
) -> dict[str, AlgorithmOutput]:
    outputs = {"weighted_frequency": weighted_frequency(sequence, choices)}
    candidates = {
        "markov_1": markov_order_1(sequence, choices),
        "markov_2": markov_order_2(sequence, choices),
        "pattern_match": pattern_match(sequence, choices),
        "run_length": run_length_model(sequence, choices),
    }
    for name, output in candidates.items():
        if output is not None:
            outputs[name] = output
    return outputs


def prediction_to_text(output: Optional[PredictionOutput]) -> str:
    if output is None:
        return (
            "Chưa đủ dữ liệu để dự đoán. "
            f"Cần ít nhất {MIN_PREDICTION_HISTORY} kết quả hợp lệ."
        )
    probs = " | ".join(
        f"{choice} {probability * 100:.1f}%"
        for choice, probability in output.probabilities.items()
    )
    votes = ", ".join(
        f"{ALGORITHM_LABELS.get(name, name)}={vote}"
        for name, vote in output.votes.items()
    )
    return (
        f"Dự đoán phiên tiếp: {output.prediction}\n"
        f"Độ nghiêng thống kê: {output.confidence}%\n"
        f"Xác suất mô hình: {probs}\n"
        f"Phiếu: {votes}\n"
        f"Dữ liệu: {output.reason}"
    )
