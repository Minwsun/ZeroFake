# 22520876-NguyenNhatMinh

import sys
import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QTextBrowser, QStatusBar, QLabel,
    QDialog, QComboBox, QLineEdit, QDialogButtonBox, QMessageBox, QCheckBox
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
    """Worker class to run network tasks in separate thread"""
    result_ready = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, url, data, timeout: float | None = 120):
        super().__init__()
        self.url = url
        self.data = data
        self.timeout = timeout
    
    def run(self):
        """Run request in thread"""
        try:
            kwargs = {"json": self.data}
            if self.timeout is not None:
                kwargs["timeout"] = self.timeout
            response = requests.post(self.url, **kwargs)
            response.raise_for_status()
            result = response.json()
            self.result_ready.emit(result)
        except requests.exceptions.RequestException as e:
            self.error.emit(f"Connection error: {str(e)}")
        except Exception as e:
            self.error.emit(f"Unknown error: {str(e)}")


class FeedbackDialog(QDialog):
    """Dialog to enter feedback when user reports incorrect result"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Feedback - Incorrect Result")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        
        # Label
        label = QLabel("Please select the correct result and add notes:")
        layout.addWidget(label)
        
        # ComboBox for correct result
        self.correction_combo = QComboBox()
        self.correction_combo.addItems([
            "TIN THẬT",
            "TIN GIẢ",
            "GÂY HIỂU LẦM"
        ])
        layout.addWidget(QLabel("Correct result:"))
        layout.addWidget(self.correction_combo)
        
        # LineEdit for notes
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Enter notes (optional)...")
        layout.addWidget(QLabel("Notes:"))
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
        """Get correct result"""
        return self.correction_combo.currentText()
    
    def get_notes(self):
        """Get notes"""
        return self.notes_edit.text()


class MainWindow(QMainWindow):
    """Main window of the application"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ZeroFake v1.1")
        self.setGeometry(100, 100, 1000, 700)
        
        # Store current result
        self.current_result = None
        self.current_text_input = None

        # Create UI
        self.init_ui()
    
    def init_ui(self):
        """Initialize interface"""
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
        input_label = QLabel("Enter news to check:")
        layout.addWidget(input_label)
        
        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("Paste or enter news to check here...")
        self.input_text.setMaximumHeight(150)
        layout.addWidget(self.input_text)
        
        # Model selection removed - system auto-fallbacks to best available model
        # Fallback chain: Gemini Flash -> Gemma 4B -> Gemma 1B (Agent 1)
        # Fallback chain: Gemini Pro -> Gemini Flash -> Gemma 27B -> Gemma 12B (Agent 2)
        
        # Button area
        button_layout = QHBoxLayout()
        
        self.check_button = QPushButton("Check")
        self.check_button.setMinimumHeight(40)
        self.check_button.clicked.connect(self.check_news)
        button_layout.addWidget(self.check_button)
        
        # Feedback buttons (hidden initially)
        self.feedback_correct_button = QPushButton("Correct")
        self.feedback_correct_button.setVisible(False)
        self.feedback_correct_button.clicked.connect(self.handle_feedback_correct)
        button_layout.addWidget(self.feedback_correct_button)
        
        self.feedback_wrong_button = QPushButton("Incorrect")
        self.feedback_wrong_button.setVisible(False)
        self.feedback_wrong_button.clicked.connect(self.handle_feedback_wrong)
        button_layout.addWidget(self.feedback_wrong_button)
        
        layout.addLayout(button_layout)
        
        # Result area
        result_label = QLabel("Result:")
        layout.addWidget(result_label)
        
        self.result_browser = QTextBrowser()
        self.result_browser.setPlaceholderText("Results will be displayed here...")
        layout.addWidget(self.result_browser)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def check_news(self):
        """Handle when Check button is clicked"""
        text_input = self.input_text.toPlainText().strip()
        
        if not text_input:
            QMessageBox.warning(self, "Warning", "Please enter news to check!")
            return
        
        # Disable button
        self.check_button.setEnabled(False)
        self.status_bar.showMessage("Đang kiểm tra với Adversarial Dialectic...")
        self.result_browser.clear()
        
        # Hide feedback buttons
        self.feedback_correct_button.setVisible(False)
        self.feedback_wrong_button.setVisible(False)
        
        # Tạo thread và worker
        self.thread = QThread()
        
        # Auto-fallback mode: backend will choose best model with fallback chain
        payload = {
            "text": text_input,
            # Models are auto-selected by backend with fallback chain
            # Agent 1: Gemini Flash -> Gemma 4B -> Gemma 1B
            # Agent 2: Gemini Pro -> Gemini Flash -> Gemma 27B -> Gemma 12B
        }
        endpoint = f"{API_URL}/check_news"
        timeout = 180  # Longer timeout for auto-fallback
        
        self.worker = Worker(endpoint, payload, timeout=timeout)
        self.worker.moveToThread(self.thread)
        
        # Kết nối signals
        self.thread.started.connect(self.worker.run)
        self.worker.result_ready.connect(self.update_ui)
        self.worker.error.connect(self.handle_error)
        self.worker.result_ready.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        
        # Save text input
        self.current_text_input = text_input
        
        # Start thread
        self.thread.start()

    
    def update_ui(self, result: dict):
        """Update UI with result"""
        self.current_result = result
        
        # Format HTML for display
        conclusion = result.get("conclusion", "N/A")
        reason = result.get("reason", "N/A")
        style_analysis = result.get("style_analysis", "N/A")
        key_evidence_snippet = result.get("key_evidence_snippet", "N/A")
        key_evidence_source = result.get("key_evidence_source", "N/A")
        cached = result.get("cached", False)
        confidence_score = result.get("confidence_score", "N/A")
        
        # Get debate_log for Adversarial Dialectic display
        debate_log = result.get("debate_log", {})
        red_team = debate_log.get("red_team_argument", "")
        blue_team = debate_log.get("blue_team_argument", "")
        judge_reasoning = debate_log.get("judge_reasoning", "")
        
        # Colors for conclusion
        color_map = {
            "TIN THẬT": "#28a745",
            "TIN GIẢ": "#dc3545",
            "GÂY HIỂU LẦM": "#ffc107",
            "CHƯA KIỂM CHỨNG": "#6c757d"
        }
        color = color_map.get(conclusion, "#6c757d")
        
        # Build debate HTML if available
        debate_html = ""
        if red_team or blue_team or judge_reasoning:
            debate_html = f"""
            <h3>⚔️ Tranh Biện Đối Kháng (Adversarial Dialectic):</h3>
            
            <div style="background-color: #2a1515; padding: 10px; border-left: 4px solid #dc3545; margin-bottom: 10px;">
                <strong style="color: #dc3545;">🔴 RED TEAM (Phe Công Tố):</strong>
                <p style="color: #e6e6e6; margin: 5px 0;">{red_team}</p>
            </div>
            
            <div style="background-color: #151f2a; padding: 10px; border-left: 4px solid #007bff; margin-bottom: 10px;">
                <strong style="color: #007bff;">🔵 BLUE TEAM (Phe Biện Hộ):</strong>
                <p style="color: #e6e6e6; margin: 5px 0;">{blue_team}</p>
            </div>
            
            <div style="background-color: #2a2515; padding: 10px; border-left: 4px solid #ffc107; margin-bottom: 10px;">
                <strong style="color: #ffc107;">⚖️ JUDGE (Thẩm Phán):</strong>
                <p style="color: #e6e6e6; margin: 5px 0;">{judge_reasoning}</p>
            </div>
            """
        
        html = f"""
        <div style="font-family: Arial, sans-serif; color: #e6e6e6;">
            <h2 style="color: {color};">
                Kết Luận: <strong>{conclusion}</strong>
                {f'<span style="font-size: 12px; color: #6c757d;">(Độ tin cậy: {confidence_score}%)</span>' if confidence_score != "N/A" else ''}
                {'<span style="font-size: 12px; color: #6c757d;">(From Cache)</span>' if cached else ''}
            </h2>
            
            {debate_html}
            
            <h3>📝 Lý Do:</h3>
            <p style="background-color: #1f1f1f; color: #e6e6e6; padding: 10px; border-radius: 5px;">
                {reason}
            </p>
            
            <h3>🔍 Bằng Chứng Quan Trọng:</h3>
            <p style="background-color: #242424; color: #e6e6e6; padding: 10px; border-radius: 5px; font-style: italic;">
                "{key_evidence_snippet}"
            </p>
            
            <p style="color: #6c757d; font-size: 12px;">
                📎 Nguồn: <a href="{key_evidence_source}" style="color: #007bff;">{key_evidence_source}</a>
            </p>
            
            {f'<h3>✍️ Phân Tích Văn Phong:</h3><p style="background-color: #1f1f1f; padding: 10px; border-radius: 5px;">{style_analysis}</p>' if style_analysis and style_analysis != "N/A" else ''}
        </div>
        """
        
        self.result_browser.setHtml(html)
        
        # Update status bar
        self.status_bar.showMessage("Completed.")
        
        # Re-enable button
        self.check_button.setEnabled(True)
        
        # Show feedback buttons
        self.feedback_correct_button.setVisible(True)
        self.feedback_wrong_button.setVisible(True)
    
    def handle_error(self, error_msg: str):
        """Handle error"""
        self.result_browser.setPlainText(f"Error: {error_msg}\n\nPlease check:\n1. Is the server running?\n2. Is the internet connection stable?")
        self.status_bar.showMessage("Error occurred.")
        self.check_button.setEnabled(True)
    
    def handle_feedback_correct(self):
        """Handle when user reports correct"""
        QMessageBox.information(self, "Thank You", "Thank you for your feedback!")
        self.feedback_correct_button.setVisible(False)
        self.feedback_wrong_button.setVisible(False)
    
    def handle_feedback_wrong(self):
        """Handle when user reports incorrect"""
        if not self.current_result or not self.current_text_input:
            QMessageBox.warning(self, "Warning", "No result to provide feedback on!")
            return
        
        # Show dialog
        dialog = FeedbackDialog(self)
        if dialog.exec():
            human_correction = dialog.get_correction()
            notes = dialog.get_notes()
            
            # Send feedback
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
                
                QMessageBox.information(self, "Success", "Feedback recorded. Thank you!")
                self.status_bar.showMessage("Feedback recorded.")
                
                # Hide feedback buttons
                self.feedback_correct_button.setVisible(False)
                self.feedback_wrong_button.setVisible(False)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not send feedback: {str(e)}")


def main():
    """Main function to run the application"""
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

