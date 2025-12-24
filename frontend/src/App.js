import React, { useState, useEffect } from 'react';
import { IconCheck } from '@tabler/icons-react';
import { CheckCircle, XCircle, AlertCircle, FileText, TrendingUp, Shield, X, Clock, Moon, Sun } from 'lucide-react';
import HistorySidebar from './HistorySidebar';
import './App.css';

/* URL API backend */
const API_URL = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';

/* Các bước tiến trình khi kiểm tra tin tức */
const PROGRESS_STEPS = [
  { label: 'Đang kiểm tra cache và tạo kế hoạch', duration: 2000 },
  { label: 'Đang thu thập bằng chứng', duration: 4000 },
  { label: 'Đang phân tích và tổng hợp', duration: 3000 },
];

function App() {
  /* State quản lý nội dung tin tức */
  const [text, setText] = useState('');

  /* State quản lý trạng thái loading và tiến trình */
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);

  /* State quản lý kết quả và lỗi */
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  /* State quản lý UI */
  const [showFeedback, setShowFeedback] = useState(false);
  const [showResultModal, setShowResultModal] = useState(false);
  const [activeTab, setActiveTab] = useState('reason');
  const [showHistorySidebar, setShowHistorySidebar] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(() => {
    // Load theme from localStorage, default to dark mode
    const savedTheme = localStorage.getItem('zerofake_theme');
    return savedTheme !== 'light';
  });

  /* State quản lý popup feedback */
  const [showFeedbackPopup, setShowFeedbackPopup] = useState(false);
  const [feedbackPopupType, setFeedbackPopupType] = useState(null); // 'success', 'error', 'correction'
  const [feedbackPopupMessage, setFeedbackPopupMessage] = useState('');
  const [showCorrectionDialog, setShowCorrectionDialog] = useState(false);
  const [selectedCorrection, setSelectedCorrection] = useState('');
  const [correctionNotes, setCorrectionNotes] = useState('');

  /* Auto-hide feedback toast after 2 seconds */
  useEffect(() => {
    if (showFeedbackPopup) {
      const timer = setTimeout(() => setShowFeedbackPopup(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [showFeedbackPopup]);

  /* Quản lý hiển thị tiến trình loading và vô hiệu hóa scroll */
  useEffect(() => {
    if (!loading) {
      setCurrentStep(0);
      document.body.style.overflow = '';
      return;
    }

    /* Vô hiệu hóa scroll khi đang loading */
    document.body.style.overflow = 'hidden';

    const stepTimers = [];

    /* Hàm đệ quy để chạy từng bước tiến trình */
    const runStep = (index) => {
      if (index >= PROGRESS_STEPS.length || !loading) {
        return;
      }

      setCurrentStep(index);
      const timer = setTimeout(() => {
        if (index < PROGRESS_STEPS.length - 1) {
          runStep(index + 1);
        }
      }, PROGRESS_STEPS[index].duration);

      stepTimers.push(timer);
    };

    runStep(0);

    /* Cleanup: dọn dẹp timers và khôi phục scroll */
    return () => {
      stepTimers.forEach(timer => clearTimeout(timer));
      document.body.style.overflow = '';
    };
  }, [loading]);

  /* Xử lý kiểm tra tin tức */
  const handleCheck = async () => {
    if (!text.trim()) {
      setError('Vui lòng nhập tin tức cần kiểm tra!');
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    setShowFeedback(false);

    try {
      const response = await fetch(`${API_URL}/check_news`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          text: text.trim(),
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Lỗi kết nối' }));
        throw new Error(errorData.detail || `Lỗi ${response.status}`);
      }

      const data = await response.json();
      setResult(data);
      setShowFeedback(true);
      setActiveTab('reason');
      setCurrentStep(PROGRESS_STEPS.length);
      setLoading(false);

      /* Lưu vào lịch sử */
      saveToHistory(text.trim(), data);

      /* Hiển thị modal kết quả sau khi loading xong */
      setTimeout(() => {
        setShowResultModal(true);
      }, 300);
    } catch (err) {
      setError(err.message || 'Đã xảy ra lỗi. Vui lòng kiểm tra kết nối và thử lại.');
      setLoading(false);
    }
  };

  /* Xử lý phản hồi từ người dùng về độ chính xác của kết quả */
  const handleFeedback = (isCorrect) => {
    if (!result) return;

    const conclusion = isCorrect ? result.conclusion : (result.conclusion === 'TIN THẬT' ? 'TIN GIẢ' : 'TIN THẬT');
    const notes = isCorrect ? 'Đúng - xác nhận kết quả' : 'Sai - đã sửa kết quả';

    // Fire-and-forget: Send feedback async without blocking UI
    fetch(`${API_URL}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        original_text: text,
        gemini_conclusion: result.conclusion,
        gemini_reason: result.reason,
        human_correction: conclusion,
        notes: notes,
      }),
    }).catch(err => console.log('Feedback error:', err));

    // Save to localStorage immediately
    try {
      const historyItem = {
        id: Date.now().toString(),
        text: text,
        conclusion: conclusion,
        reason: result.reason,
        timestamp: new Date().toISOString(),
        feedbackGiven: true,
      };
      const stored = localStorage.getItem('zerofake_history');
      const history = stored ? JSON.parse(stored) : [];
      const existingIndex = history.findIndex(h => h.text === text);
      if (existingIndex >= 0) {
        history[existingIndex] = historyItem;
      } else {
        history.unshift(historyItem);
      }
      localStorage.setItem('zerofake_history', JSON.stringify(history.slice(0, 100)));
    } catch (e) { }

    // Immediate UI update - show thank you toast
    setFeedbackPopupType('success');
    setFeedbackPopupMessage('Cảm ơn đóng góp của bạn!');
    setShowFeedbackPopup(true);
    setShowFeedback(false);
    setShowResultModal(false);
  };

  /* Xử lý khi người dùng chọn kết quả đúng và gửi phản hồi */
  const handleSubmitCorrection = async () => {
    if (!selectedCorrection) {
      setFeedbackPopupType('error');
      setFeedbackPopupMessage('Vui lòng chọn kết quả đúng!');
      setShowFeedbackPopup(true);
      return;
    }

    const correctionMap = {
      'TIN THẬT': 'TIN THẬT',
      'TIN GIẢ': 'TIN GIẢ',
      'GÂY HIỂU LẦM': 'GÂY HIỂU LẦM',
    };

    const humanCorrection = correctionMap[selectedCorrection] || selectedCorrection;

    try {
      await fetch(`${API_URL}/feedback`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          original_text: text,
          gemini_conclusion: result.conclusion,
          gemini_reason: result.reason,
          human_correction: humanCorrection,
          notes: correctionNotes || '',
        }),
      });
      setShowCorrectionDialog(false);
      setSelectedCorrection('');
      setCorrectionNotes('');
      setFeedbackPopupType('success');
      setFeedbackPopupMessage('Cảm ơn bạn đã phản hồi!');
      setShowFeedbackPopup(true);
    } catch (err) {
      setFeedbackPopupType('error');
      setFeedbackPopupMessage('Không thể gửi phản hồi. Vui lòng thử lại.');
      setShowFeedbackPopup(true);
    }
    setShowFeedback(false);
    setShowResultModal(false);
  };

  /* Đóng modal kết quả */
  const closeModal = () => {
    setShowResultModal(false);
    setActiveTab('reason');
  };

  /* Lấy màu sắc tương ứng với kết luận */
  const getConclusionColor = (conclusion) => {
    const colorMap = {
      'TIN THẬT': '#28a745',
      'TIN GIẢ': '#dc3545',
      'GÂY HIỂU LẦM': '#ffc107',
    };
    return colorMap[conclusion] || '#6c757d';
  };

  /* Lưu kết quả kiểm tra vào lịch sử localStorage */
  const saveToHistory = (newsText, resultData) => {
    try {
      const historyItem = {
        id: Date.now().toString(),
        text: newsText,
        conclusion: resultData.conclusion || 'KHÔNG XÁC ĐỊNH',
        reason: resultData.reason || '',
        cached: resultData.cached || false,
        timestamp: new Date().toISOString(),
      };

      const existing = localStorage.getItem('zerofake_history');
      const history = existing ? JSON.parse(existing) : [];
      history.push(historyItem);

      /* Chỉ giữ lại 100 mục gần nhất */
      const limitedHistory = history.slice(-100);
      localStorage.setItem('zerofake_history', JSON.stringify(limitedHistory));
    } catch (error) {
      console.error('Error saving to history:', error);
    }
  };

  /* Xử lý khi người dùng chọn một mục từ lịch sử */
  const handleSelectHistory = (historyItem) => {
    setText(historyItem.text);
    setResult({
      conclusion: historyItem.conclusion,
      reason: historyItem.reason,
      cached: historyItem.cached,
    });
    setShowFeedback(true);
    setActiveTab('reason');
    setTimeout(() => {
      setShowResultModal(true);
    }, 300);
  };

  /* Xử lý chuyển đổi chế độ sáng/tối */
  const toggleTheme = () => {
    const newTheme = !isDarkMode;
    setIsDarkMode(newTheme);
    // Save to localStorage
    localStorage.setItem('zerofake_theme', newTheme ? 'dark' : 'light');
  };

  /* Áp dụng theme cho document */
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.setAttribute('data-theme', 'light');
    }
  }, [isDarkMode]);

  return (
    <div className="App">
      {/* Feedback Toast Popup */}
      {showFeedbackPopup && (
        <div className="feedback-toast" onClick={() => setShowFeedbackPopup(false)}>
          <span>{feedbackPopupMessage}</span>
        </div>
      )}

      {/* Plain dark background */}

      <div className="container">
        <header className="header">
          <div className="header-left">
            <h1 className="fancy">ZeroFake</h1>
            <p className="subtitle">Kiểm tra tin tức thật giả</p>
          </div>
          <div className="header-buttons">
            <button
              className="theme-toggle-button"
              onClick={toggleTheme}
              title={isDarkMode ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối'}
            >
              {isDarkMode ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button
              className="history-button"
              onClick={() => setShowHistorySidebar(true)}
              title="Xem lịch sử kiểm tra"
            >
              <Clock size={18} />
            </button>
          </div>
        </header>

        <div className="main-content">
          {/* Modern Form Input */}
          <form className="particle-form" onSubmit={(e) => { e.preventDefault(); handleCheck(); }}>
            <div className="field">
              <label className="field-label" htmlFor="news-input">
                Nhập tin tức cần kiểm tra
              </label>
              <div className="input-wrapper">
                <textarea
                  id="news-input"
                  className="particle-input"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onInput={(e) => {
                    e.target.style.height = 'auto';
                    e.target.style.height = e.target.scrollHeight + 'px';
                  }}
                  placeholder="Nhập hoặc dán tin tức cần kiểm tra..."
                  disabled={loading}
                  rows={1}
                />
              </div>
            </div>
            <button
              className="particle-submit"
              type="submit"
              disabled={loading || !text.trim()}
            >
              <span className="circle"></span>
              <span className="text">{loading ? 'Đang kiểm tra...' : 'Kiểm tra'}</span>
            </button>
          </form>

          {error && (
            <div className="error-message">
              <strong>Lỗi:</strong> {error}
            </div>
          )}
        </div>
      </div>

      {/* Overlay hiển thị khi đang kiểm tra */}
      {
        loading && (
          <div className="loading-overlay">
            <div className="loading-content">
              <div className="loader-wrapper">
                <div className="loader"></div>
                <span className="loader-letter">T</span>
                <span className="loader-letter">h</span>
                <span className="loader-letter">i</span>
                <span className="loader-letter">n</span>
                <span className="loader-letter">k</span>
                <span className="loader-letter">i</span>
                <span className="loader-letter">n</span>
                <span className="loader-letter">g</span>
                <span className="loader-letter">.</span>
                <span className="loader-letter">.</span>
                <span className="loader-letter">.</span>
              </div>
            </div>
          </div>
        )
      }

      {/* Modal hiển thị kết quả kiểm tra */}
      {
        showResultModal && result && (
          <div className="modal-overlay">
            <div className="modal-content-dark">
              <button className="modal-close-dark" onClick={closeModal}>
                <X size={18} />
              </button>

              {/* Simple Result Card */}
              <div className="result-header">
                {result.conclusion === 'TIN THẬT' ? (
                  <CheckCircle size={24} />
                ) : (
                  <XCircle size={24} />
                )}
                <span className="result-conclusion">{result.conclusion}</span>
              </div>

              <div className="result-reason">
                <p>{result.reason || 'Không có lý do cụ thể từ AI.'}</p>
              </div>

              {/* Evidence Links Section - Only web sources (filter out fact check) */}
              {result.evidence_links && result.evidence_links.length > 0 && (() => {
                // Filter out fact check sources - only show web sources
                const factCheckPatterns = [
                  'factcheck', 'fact-check', 'snopes', 'politifact',
                  'fullfact', 'factcheckvn', 'factcheck.org', 'factchecker',
                  'kiểm chứng', 'kiem chung', 'xác minh', 'xac minh'
                ];

                const webSources = result.evidence_links.filter(link => {
                  const urlLower = (link.url || '').toLowerCase();
                  const sourceLower = (link.source || '').toLowerCase();
                  // Exclude if matches any fact check pattern
                  return !factCheckPatterns.some(pattern =>
                    urlLower.includes(pattern) || sourceLower.includes(pattern)
                  );
                }).slice(0, 5); // Max 5 web sources

                return webSources.length > 0 ? (
                  <div className="evidence-links-section">
                    <h4 className="evidence-links-title">Các nguồn:</h4>
                    <div className="evidence-sources-list">
                      {webSources.map((link, index) => (
                        <div key={index} className="evidence-source-item">
                          <a
                            href={link.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="evidence-source-name"
                          >
                            {link.source || `Nguồn ${index + 1}`}
                          </a>
                          {link.snippet && (
                            <p className="evidence-source-quote">{link.snippet}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null;
              })()}

              {/* Feedback Buttons - Đúng/Sai */}
              {showFeedback && (
                <div className="feedback-buttons-row">
                  <button
                    className="feedback-btn feedback-btn-correct"
                    onClick={() => handleFeedback(true)}
                  >
                    <i className="fi fi-rs-check"></i>
                    Đúng
                  </button>
                  <button
                    className="feedback-btn feedback-btn-incorrect"
                    onClick={() => handleFeedback(false)}
                  >
                    <i className="fi fi-rr-cross-small"></i>
                    Sai
                  </button>
                </div>
              )}
            </div>
          </div>
        )
      }

      {/* Sidebar hiển thị lịch sử kiểm tra */}
      <HistorySidebar
        isOpen={showHistorySidebar}
        onClose={() => setShowHistorySidebar(false)}
        onSelectHistory={handleSelectHistory}
      />

      {/* Popup thông báo feedback */}
      {
        showFeedbackPopup && (
          <div className="feedback-popup-overlay" onClick={() => setShowFeedbackPopup(false)}>
            <div className="feedback-popup" onClick={(e) => e.stopPropagation()}>
              <div className={`feedback-popup-icon ${feedbackPopupType}`}>
                {feedbackPopupType === 'success' && <CheckCircle size={48} />}
                {feedbackPopupType === 'error' && <XCircle size={48} />}
              </div>
              <p className="feedback-popup-message">{feedbackPopupMessage}</p>
              <button
                className="feedback-popup-button"
                onClick={() => setShowFeedbackPopup(false)}
              >
                Đóng
              </button>
            </div>
          </div>
        )
      }
    </div >
  );
}

export default App;
