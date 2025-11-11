# 22520876-NguyenNhatMinh

import sys
import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QTextBrowser, QStatusBar, QLabel,
    QDialog, QComboBox, QLineEdit, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt
from PyQt6.QtGui import QFont


API_URL = "http://127.0.0.1:8000"
DARK_STYLESHEET = """
QWidget { background-color: #121212; color: #e6e6e6; }
QTextEdit, QTextBrowser { background-color: #1e1e1e; color: #e6e6e6; border: 1px solid #333; }
QPushButton { background-color: #2b2b2b; color: #e6e6e6; border: 1px solid #444; padding: 6px 12px; }
QPushButton:hover { background-color: #3a3a3a; }
QStatusBar { background-color: #121212; color: #cccccc; }
QComboBox, QLineEdit { background-color: #1e1e1e; color: #e6e6e6; border: 1px solid #333; }
QDialog { background-color: #121212; }
"""


class Worker(QObject):
    """Worker class để chạy tác vụ mạng trong thread riêng"""
    result_ready = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, url, data, timeout: float | None = 120):
        super().__init__()
        self.url = url
        self.data = data
        self.timeout = timeout
    
    def run(self):
        """Chạy request trong thread"""
        try:
            kwargs = {"json": self.data}
            if self.timeout is not None:
                kwargs["timeout"] = self.timeout
            response = requests.post(self.url, **kwargs)
            response.raise_for_status()
            result = response.json()
            self.result_ready.emit(result)
        except requests.exceptions.RequestException as e:
            self.error.emit(f"Lỗi kết nối: {str(e)}")
        except Exception as e:
            self.error.emit(f"Lỗi không xác định: {str(e)}")


class FeedbackDialog(QDialog):
    """Dialog để nhập phản hồi khi người dùng báo sai"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Phản hồi - Kết quả không chính xác")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        
        # Label
        label = QLabel("Vui lòng chọn kết quả đúng và ghi chú:")
        layout.addWidget(label)
        
        # ComboBox cho kết quả đúng
        self.correction_combo = QComboBox()
        self.correction_combo.addItems([
            "TIN THẬT",
            "TIN GIẢ",
            "GÂY HIỂU LẦM",
            "TIN CHƯA XÁC THỰC"
        ])
        layout.addWidget(QLabel("Kết quả đúng:"))
        layout.addWidget(self.correction_combo)
        
        # LineEdit cho ghi chú
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Nhập ghi chú (tùy chọn)...")
        layout.addWidget(QLabel("Ghi chú:"))
        layout.addWidget(self.notes_edit)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def get_correction(self):
        """Lấy kết quả đúng"""
        return self.correction_combo.currentText()
    
    def get_notes(self):
        """Lấy ghi chú"""
        return self.notes_edit.text()


class MainWindow(QMainWindow):
    """Main window của ứng dụng"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ZeroFake V1.0")
        self.setGeometry(100, 100, 1000, 700)
        
        # Lưu trữ kết quả hiện tại
        self.current_result = None
        self.current_text_input = None
        self.flash_mode = False
        
        # Tạo UI
        self.init_ui()
    
    def init_ui(self):
        """Khởi tạo giao diện"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        
        # Title
        title = QLabel("ZeroFake")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Input area
        input_label = QLabel("Nhập tin tức cần kiểm tra:")
        layout.addWidget(input_label)
        
        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("Dán hoặc nhập tin tức cần kiểm tra vào đây...")
        self.input_text.setMaximumHeight(150)
        layout.addWidget(self.input_text)
        
        # Button area
        button_layout = QHBoxLayout()
        
        self.check_button = QPushButton("Kiểm tra")
        self.check_button.setMinimumHeight(40)
        self.check_button.clicked.connect(self.check_news)
        button_layout.addWidget(self.check_button)

        self.flash_button = QPushButton("Flash: OFF")
        self.flash_button.setCheckable(True)
        self.flash_button.setMinimumHeight(40)
        self.flash_button.setToolTip("Bật để sử dụng chế độ flash (gemini-2.5-flash cho cả 2 agents, không timeout)")
        self.flash_button.toggled.connect(self.toggle_flash_mode)
        button_layout.addWidget(self.flash_button)
        
        # Feedback buttons (ẩn ban đầu)
        self.feedback_correct_button = QPushButton("Đúng")
        self.feedback_correct_button.setVisible(False)
        self.feedback_correct_button.clicked.connect(self.handle_feedback_correct)
        button_layout.addWidget(self.feedback_correct_button)
        
        self.feedback_wrong_button = QPushButton("Sai")
        self.feedback_wrong_button.setVisible(False)
        self.feedback_wrong_button.clicked.connect(self.handle_feedback_wrong)
        button_layout.addWidget(self.feedback_wrong_button)
        
        layout.addLayout(button_layout)
        
        # Result area
        result_label = QLabel("Kết quả:")
        layout.addWidget(result_label)
        
        self.result_browser = QTextBrowser()
        self.result_browser.setPlaceholderText("Kết quả sẽ hiển thị ở đây...")
        layout.addWidget(self.result_browser)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Sẵn sàng")
    
    def check_news(self):
        """Xử lý khi nhấn nút Kiểm tra"""
        text_input = self.input_text.toPlainText().strip()
        
        if not text_input:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng nhập tin tức cần kiểm tra!")
            return
        
        # Vô hiệu hóa nút
        self.check_button.setEnabled(False)
        self.status_bar.showMessage("Đang tra cứu...")
        self.result_browser.clear()
        
        # Ẩn feedback buttons
        self.feedback_correct_button.setVisible(False)
        self.feedback_wrong_button.setVisible(False)
        
        # Tạo thread và worker
        self.thread = QThread()
        payload = {"text": text_input, "flash_mode": self.flash_mode}
        timeout = None if self.flash_mode else 120
        self.worker = Worker(f"{API_URL}/check_news", payload, timeout=timeout)
        self.worker.moveToThread(self.thread)
        
        # Kết nối signals
        self.thread.started.connect(self.worker.run)
        self.worker.result_ready.connect(self.update_ui)
        self.worker.error.connect(self.handle_error)
        self.worker.result_ready.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        
        # Lưu text input
        self.current_text_input = text_input
        
        # Start thread
        self.thread.start()

    def toggle_flash_mode(self, checked: bool):
        self.flash_mode = checked
        if checked:
            self.flash_button.setText("Flash: ON")
            self.status_bar.showMessage("Chế độ Flash (gemini-2.5-flash) đã bật - chờ vô hạn")
        else:
            self.flash_button.setText("Flash: OFF")
            self.status_bar.showMessage("Chế độ Flash đã tắt")
    
    def update_ui(self, result: dict):
        """Cập nhật UI với kết quả"""
        self.current_result = result
        
        # Format HTML để hiển thị
        conclusion = result.get("conclusion", "N/A")
        reason = result.get("reason", "N/A")
        style_analysis = result.get("style_analysis", "N/A")
        key_evidence_snippet = result.get("key_evidence_snippet", "N/A")
        key_evidence_source = result.get("key_evidence_source", "N/A")
        cached = result.get("cached", False)
        
        # Màu sắc cho conclusion
        color_map = {
            "TIN THẬT": "#28a745",
            "TIN GIẢ": "#dc3545",
            "GÂY HIỂU LẦM": "#ffc107",
            "TIN CHƯA XÁC THỰC": "#17a2b8"
        }
        color = color_map.get(conclusion, "#6c757d")
        
        html = f"""
        <div style="font-family: Arial, sans-serif; color: #e6e6e6;">
            <h2 style="color: {color};">
                Kết luận: <strong>{conclusion}</strong>
                {'<span style="font-size: 12px; color: #6c757d;">(Từ Cache)</span>' if cached else ''}
            </h2>
            
            <h3>Lý do:</h3>
            <p style="background-color: #1f1f1f; color: #e6e6e6; padding: 10px; border-radius: 5px;">
                {reason}
            </p>
            
            <h3>Phân tích văn phong:</h3>
            <p style="background-color: #1f1f1f; color: #e6e6e6; padding: 10px; border-radius: 5px;">
                {style_analysis}
            </p>
            
            <h3>Bằng chứng quan trọng:</h3>
            <p style="background-color: #242424; color: #e6e6e6; padding: 10px; border-radius: 5px; font-style: italic;">
                "{key_evidence_snippet}"
            </p>
            
            <p style="color: #6c757d; font-size: 12px;">
                Nguồn: {key_evidence_source}
            </p>
        </div>
        """
        
        self.result_browser.setHtml(html)
        
        # Cập nhật status bar
        self.status_bar.showMessage("Hoàn thành.")
        
        # Kích hoạt lại nút
        self.check_button.setEnabled(True)
        
        # Hiển thị feedback buttons
        self.feedback_correct_button.setVisible(True)
        self.feedback_wrong_button.setVisible(True)
    
    def handle_error(self, error_msg: str):
        """Xử lý lỗi"""
        self.result_browser.setPlainText(f"Lỗi: {error_msg}\n\nVui lòng kiểm tra:\n1. Server đã chạy chưa?\n2. Kết nối internet có ổn không?")
        self.status_bar.showMessage("Lỗi xảy ra.")
        self.check_button.setEnabled(True)
    
    def handle_feedback_correct(self):
        """Xử lý khi người dùng báo đúng"""
        QMessageBox.information(self, "Cảm ơn", "Cảm ơn bạn đã phản hồi!")
        self.feedback_correct_button.setVisible(False)
        self.feedback_wrong_button.setVisible(False)
    
    def handle_feedback_wrong(self):
        """Xử lý khi người dùng báo sai"""
        if not self.current_result or not self.current_text_input:
            QMessageBox.warning(self, "Cảnh báo", "Không có kết quả để phản hồi!")
            return
        
        # Hiển thị dialog
        dialog = FeedbackDialog(self)
        if dialog.exec():
            human_correction = dialog.get_correction()
            notes = dialog.get_notes()
            
            # Gửi feedback
            try:
                feedback_data = {
                    "original_text": self.current_text_input,
                    "gemini_conclusion": self.current_result.get("conclusion", ""),
                    "gemini_reason": self.current_result.get("reason", ""),
                    "human_correction": human_correction,
                    "notes": notes
                }
                
                response = requests.post(f"{API_URL}/feedback", json=feedback_data, timeout=10)
                response.raise_for_status()
                
                QMessageBox.information(self, "Thành công", "Đã ghi nhận phản hồi. Cảm ơn bạn!")
                self.status_bar.showMessage("Đã ghi nhận phản hồi.")
                
                # Ẩn feedback buttons
                self.feedback_correct_button.setVisible(False)
                self.feedback_wrong_button.setVisible(False)
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể gửi phản hồi: {str(e)}")


def main():
    """Hàm main để chạy ứng dụng"""
    app = QApplication(sys.argv)
    try:
        app.setStyleSheet(DARK_STYLESHEET)
    except Exception:
        pass
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

