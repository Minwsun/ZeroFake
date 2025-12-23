import React, { useState, useEffect, useRef } from 'react';
import { IconCheck } from '@tabler/icons-react';
import { CheckCircle, XCircle, AlertCircle, FileText, TrendingUp, Shield, X, Clock, User } from 'lucide-react';
import { onAuthStateChanged, signOut } from 'firebase/auth';
import { collection, addDoc, serverTimestamp } from 'firebase/firestore';
import HistorySidebar from './HistorySidebar';
import AuthModal from './AuthModal';
import { auth, db } from './firebase';
import './App.css';

/* URL API backend */
const API_URL = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';

const PROGRESS_STEPS = [
  { label: 'Checking cache and planning', duration: 2000 },
  { label: 'Gathering evidence', duration: 4000 },
  { label: 'Analyzing and summarizing', duration: 3000 },
];

function App() {
  /* State quản lý nội dung tin tức và cấu hình */
  const [text, setText] = useState('');
  // Fallback model
  const [agent1Model] = useState('models/gemma-3-4b-it');
  const [agent2Model] = useState('models/gemini-2.5-flash');

  /* State quản lý người dùng (auth) */
  const [user, setUser] = useState(null);
  const [showAuthModal, setShowAuthModal] = useState(false);

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
  const [showAccountMenu, setShowAccountMenu] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  /* State quản lý popup feedback */
  const [showFeedbackPopup, setShowFeedbackPopup] = useState(false);
  const [feedbackPopupType, setFeedbackPopupType] = useState(null); // 'success', 'error', 'correction'
  const [feedbackPopupMessage, setFeedbackPopupMessage] = useState('');
  const [showCorrectionDialog, setShowCorrectionDialog] = useState(false);
  const [selectedCorrection, setSelectedCorrection] = useState('');
  const [correctionNotes, setCorrectionNotes] = useState('');
  const accountMenuRef = useRef(null);

  /* Lắng nghe trạng thái đăng nhập Firebase */
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
      setUser(firebaseUser);
      setShowAccountMenu(false);
      setShowLogoutConfirm(false);
    });

    return () => unsubscribe();
  }, []);

  /* Loading */
  useEffect(() => {
    if (!loading) {
      setCurrentStep(0);
      document.body.style.overflow = '';
      return;
    }

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

  /* Đăng xuất */
  const handleLogout = async () => {
    try {
      await signOut(auth);
      setShowAccountMenu(false);
      setShowLogoutConfirm(false);
    } catch (err) {
      console.error('Logout error:', err);
    }
  };

  const handleConfirmLogout = () => {
    setShowLogoutConfirm(true);
    setShowAccountMenu(false);
  };

  const handleCloseLogoutConfirm = () => {
    setShowLogoutConfirm(false);
  };

  const getDisplayName = (firebaseUser) => {
    if (!firebaseUser) return 'Tài khoản';
    if (firebaseUser.displayName) return firebaseUser.displayName;
    if (firebaseUser.email) return firebaseUser.email.split('@')[0];
    return 'Tài khoản';
  };

  const handleToggleAccountMenu = () => {
    setShowAccountMenu((prev) => !prev);
  };

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (accountMenuRef.current && !accountMenuRef.current.contains(event.target)) {
        setShowAccountMenu(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const handleOpenAuth = () => {
    setShowAuthModal(true);
  };

  /* Xử lý kiểm tra tin tức */
  const handleCheck = async () => {
    if (!text.trim()) {
      setError('Please enter news to verify!');
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    setShowFeedback(false);

    try {
      /* Kiểm tra xem có sử dụng flash mode không */
      const flashMode = agent1Model.includes('flash') && agent2Model.includes('flash');
      const response = await fetch(`${API_URL}/check_news`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          text: text.trim(),
          agent1_model: agent1Model,
          agent2_model: agent2Model,
          flash_mode: flashMode,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Connection error' }));
        throw new Error(errorData.detail || `Lỗi ${response.status}`);
      }

      const data = await response.json();
      setResult(data);
      setShowFeedback(true);
      setActiveTab('reason');
      setCurrentStep(PROGRESS_STEPS.length);
      setLoading(false);
      setShowResultModal(true);

      /* Lưu vào lịch sử cho user hiện tại (Firestore) - không chặn UI */
      saveToHistory(user, text.trim(), data);
    } catch (err) {
      setError(err.message || 'Something went wrong. Please check your connection and try again.');
      setLoading(false);
    }
  };

  /* Xử lý phản hồi từ người dùng về độ chính xác của kết quả */
  const handleFeedback = async (isCorrect) => {
    if (!result) return;

    if (isCorrect) {
      /* Gửi phản hồi khi kết quả chính xác */
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
            human_correction: result.conclusion,
            notes: 'Đúng',
          }),
        });
        setFeedbackPopupType('success');
        setFeedbackPopupMessage('Thank you for your feedback!');
        setShowFeedbackPopup(true);
      } catch (err) {
        setFeedbackPopupType('error');
        setFeedbackPopupMessage('Unable to send feedback. Please try again.');
        setShowFeedbackPopup(true);
      }
      setShowFeedback(false);
      setShowResultModal(false);
      return;
    }

    /* Xử lý khi kết quả không chính xác - hiển thị dialog chọn kết quả đúng */
    setShowCorrectionDialog(true);
  };

  /* Xử lý khi người dùng chọn kết quả đúng và gửi phản hồi */
  const handleSubmitCorrection = async () => {
    if (!selectedCorrection) {
      setFeedbackPopupType('error');
      setFeedbackPopupMessage('Please select the correct result!');
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
      setFeedbackPopupMessage('Thank you for your feedback!');
      setShowFeedbackPopup(true);
    } catch (err) {
      setFeedbackPopupType('error');
      setFeedbackPopupMessage('Unable to send feedback. Please try again.');
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

  /* Lưu kết quả kiểm tra vào lịch sử Firestore theo từng người dùng */
  const saveToHistory = async (currentUser, newsText, resultData) => {
    if (!currentUser) {
      // Nếu chưa đăng nhập thì không lưu lịch sử
      return;
    }

    try {
      await addDoc(
        collection(db, 'users', currentUser.uid, 'history'),
        {
          text: newsText,
          conclusion: resultData.conclusion || 'KHÔNG XÁC ĐỊNH',
          reason: resultData.reason || '',
          cached: resultData.cached || false,
          timestamp: serverTimestamp(),
        }
      );
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

  return (
    <div className="App">
      {/* Các điểm màu phát sáng làm nền */}
      <div className="glow-orb orb-1"></div>
      <div className="glow-orb orb-2"></div>
      <div className="glow-orb orb-3"></div>
      <div className="glow-orb orb-4"></div>

      <div className="container">
        <header className="header">
          <div className="header-left">
            <h1 className="fancy">ZeroFake</h1>
            <p className="subtitle">Fast fact-checking for news</p>
          </div>
          <div className="header-right">
            {user && (
              <button
                className="history-button"
                onClick={() => setShowHistorySidebar(true)}
                title="View history"
              >
                <Clock size={20} />
                <span className="history-button-label">History</span>
              </button>
            )}
            {user ? (
              <div className="account-menu-wrapper" ref={accountMenuRef}>
                <button
                  className="account-button"
                  onClick={handleToggleAccountMenu}
                  title={getDisplayName(user)}
                >
                  <User className="account-icon" size={18} />
                  <span className="account-email">
                    {getDisplayName(user)}
                  </span>
                </button>
                {showAccountMenu && (
                  <div className="account-dropdown">
                    <button
                      className="account-dropdown-item danger"
                      onClick={handleConfirmLogout}
                    >
                      Log out
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <button
                className="auth-button"
                onClick={handleOpenAuth}
              >
                Sign in
              </button>
            )}
          </div>
          <button
            className="more-button"
            onClick={() => setShowHistorySidebar(true)}
            aria-label="More options"
          >
            <span className="more-icon"></span>
          </button>
        </header>

        <div className="main-content">
          <div className="input-section">
            <label htmlFor="news-input">Enter the news to verify:</label>
            <textarea
              id="news-input"
              className="text-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste or type the news here..."
              rows="6"
            />
          </div>

          <div className="button-group">
            <button
              className="check-button"
              onClick={handleCheck}
              disabled={loading}
            >
              {loading ? 'Checking...' : 'Verify'}
            </button>

            {showFeedback && result && (
              <>
                <button
                  className="feedback-button feedback-correct"
                  onClick={() => handleFeedback(true)}
                >
                  Accurate
                </button>
                <button
                  className="feedback-button feedback-incorrect"
                  onClick={() => handleFeedback(false)}
                >
                  Inaccurate
                </button>
              </>
            )}
          </div>

          {error && (
            <div className="error-message">
              <strong>Lỗi:</strong> {error}
            </div>
          )}
        </div>
      </div>

      {/* Overlay hiển thị khi đang kiểm tra */}
      {loading && (
        <div className="loading-overlay">
          <div className="loading-content">
            <div className="loader-wrapper">
              <div className="loader"></div>
            </div>
            <h2 className="loading-title">Analyzing the news...</h2>
            <p className="loading-subtitle">Please wait a moment</p>

            <div className="progress-steps">
              {PROGRESS_STEPS.map((step, index) => (
                <div
                  key={index}
                  className={`progress-step ${index < currentStep ? 'completed' : ''} ${index === currentStep ? 'current' : ''} ${index < currentStep || index === currentStep ? 'active' : ''}`}
                >
                  <div className="progress-step-indicator">
                    {index < currentStep ? (
                      <IconCheck size={14} stroke={2.5} />
                    ) : (
                      <div className="progress-step-number">{index + 1}</div>
                    )}
                  </div>
                  <div className="progress-step-label">{step.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Modal hiển thị kết quả kiểm tra */}
      {showResultModal && result && (
        <div className="modal-overlay">
          <div className="modal-content-dark">
            <button className="modal-close-dark" onClick={closeModal}>
              <X size={20} />
            </button>

            {/* Header modal với màu sắc theo kết luận */}
            <div
              className="modal-header-dark"
              style={{
                background: result.conclusion === 'TIN THẬT'
                  ? 'linear-gradient(135deg, #10b981 0%, #059669 100%)'
                  : result.conclusion === 'TIN GIẢ'
                    ? 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)'
                    : 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)'
              }}
            >
              <div className="modal-header-content">
                {result.conclusion === 'TIN THẬT' && <CheckCircle className="modal-header-icon" size={48} />}
                {result.conclusion === 'TIN GIẢ' && <XCircle className="modal-header-icon" size={48} />}
                {result.conclusion === 'GÂY HIỂU LẦM' && <AlertCircle className="modal-header-icon" size={48} />}
                <div>
                  <h2 className="modal-title-dark">{result.conclusion}</h2>
                  <p className="modal-subtitle-dark">
                    {result.cached ? 'Verified (from cache)' : 'Verified'}
                  </p>
                </div>
              </div>
            </div>

            {/* Các tab chuyển đổi giữa các phần thông tin */}
            <div className="modal-tabs-dark">
              <button
                onClick={() => setActiveTab('reason')}
                className={`modal-tab-dark ${activeTab === 'reason' ? 'active' : ''}`}
              >
                <FileText size={18} />
                Reason
              </button>
              <button
                onClick={() => setActiveTab('style')}
                className={`modal-tab-dark ${activeTab === 'style' ? 'active' : ''}`}
              >
                <TrendingUp size={18} />
                Style analysis
              </button>
              <button
                onClick={() => setActiveTab('evidence')}
                className={`modal-tab-dark ${activeTab === 'evidence' ? 'active' : ''}`}
              >
                <Shield size={18} />
                Key evidence
              </button>
            </div>

            {/* Nội dung của các tab */}
            <div className="modal-body-dark">
              {activeTab === 'reason' && (
                <div className="tab-content-dark">
                  <h3 className="tab-title-dark">Verification reasons</h3>
                  <div className="verification-box-dark">
                    <p className="verification-text-dark">
                      {result.reason || 'Content confirmed from trusted sources including mainstream media and official agencies. Information cross-checked across at least 3 independent sources.'}
                    </p>
                  </div>
                  <ul className="verification-list-dark">
                    <li className="verification-item-dark">
                      <CheckCircle className="verification-check-icon" size={20} />
                      <span>Clear origin from reputable organizations</span>
                    </li>
                    <li className="verification-item-dark">
                      <CheckCircle className="verification-check-icon" size={20} />
                      <span>Consistent information across sources</span>
                    </li>
                    <li className="verification-item-dark">
                      <CheckCircle className="verification-check-icon" size={20} />
                      <span>Supporting visual or video evidence</span>
                    </li>
                  </ul>
                </div>
              )}

              {activeTab === 'style' && (
                <div className="tab-content-dark">
                  <h3 className="tab-title-dark">Style analysis</h3>
                  <div className="style-analysis-dark">
                    <div className="style-card-dark">
                      <p className="style-card-title-dark">AI analysis</p>
                      <div className="style-analysis-content-dark">
                        {result.style_analysis ? (
                          <p className="style-card-text-dark" style={{ whiteSpace: 'pre-wrap', lineHeight: '1.8' }}>
                            {result.style_analysis}
                          </p>
                        ) : (
                          <p className="style-card-text-dark">
                            No style analysis available yet. Please try again.
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'evidence' && (
                <div className="tab-content-dark">
                  <h3 className="tab-title-dark">Key evidence</h3>
                  <div className="evidence-list-dark">
                    {result.key_evidence_source ? (
                      <div className="evidence-card-dark">
                        <p className="evidence-source-title-dark">Primary source</p>
                        <p className="evidence-source-date-dark">Verified</p>
                        <blockquote className="evidence-quote-dark">
                          "{result.key_evidence_snippet || 'Evidence from a trusted source'}"
                        </blockquote>
                        <a href={result.key_evidence_source} target="_blank" rel="noopener noreferrer" className="evidence-link-dark">
                          {result.key_evidence_source}
                        </a>
                      </div>
                    ) : (
                      <div className="evidence-card-dark">
                        <p className="evidence-source-title-dark">No specific evidence yet</p>
                        <p className="evidence-source-date-dark">Updating</p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Các nút phản hồi */}
            {showFeedback && (
              <div className="modal-actions-dark">
                <button
                  className="action-button-dark action-button-correct"
                  onClick={() => handleFeedback(true)}
                >
                  Accurate
                </button>
                <button
                  className="action-button-dark action-button-incorrect"
                  onClick={() => handleFeedback(false)}
                >
                  Inaccurate
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Sidebar hiển thị lịch sử kiểm tra */}
      <HistorySidebar
        user={user}
        isOpen={showHistorySidebar}
        onClose={() => setShowHistorySidebar(false)}
        onSelectHistory={handleSelectHistory}
        onOpenAuth={handleOpenAuth}
        onLogout={handleConfirmLogout}
      />

      {/* Popup thông báo feedback */}
      {showFeedbackPopup && (
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
              Close
            </button>
          </div>
        </div>
      )}

      {/* Popup xác nhận đăng xuất */}
      {showLogoutConfirm && (
        <div className="logout-confirm-overlay" onClick={handleCloseLogoutConfirm}>
          <div className="logout-confirm-dialog" onClick={(e) => e.stopPropagation()}>
            <h3 className="logout-confirm-title">Are you sure you want to log out?</h3>
            <p className="logout-confirm-text">Your session will end and you will need to sign back in to access history.</p>
            <div className="logout-confirm-actions">
              <button
                className="logout-confirm-button secondary"
                onClick={handleCloseLogoutConfirm}
              >
                Cancel
              </button>
              <button
                className="logout-confirm-button"
                onClick={handleLogout}
              >
                Log out
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Dialog chọn kết quả đúng khi feedback không chính xác */}
      {showCorrectionDialog && (
        <div className="correction-dialog-overlay" onClick={() => setShowCorrectionDialog(false)}>
          <div className="correction-dialog" onClick={(e) => e.stopPropagation()}>
            <button
              className="correction-dialog-close"
              onClick={() => {
                setShowCorrectionDialog(false);
                setSelectedCorrection('');
                setCorrectionNotes('');
              }}
            >
              <X size={20} />
            </button>
            <h3 className="correction-dialog-title">Please choose the correct result</h3>
            <div className="correction-options">
              <button
                className={`correction-option ${selectedCorrection === 'TIN THẬT' ? 'selected' : ''}`}
                onClick={() => setSelectedCorrection('TIN THẬT')}
              >
                <CheckCircle size={20} />
                <span>REAL</span>
              </button>
              <button
                className={`correction-option ${selectedCorrection === 'TIN GIẢ' ? 'selected' : ''}`}
                onClick={() => setSelectedCorrection('TIN GIẢ')}
              >
                <XCircle size={20} />
                <span>FAKE</span>
              </button>
              <button
                className={`correction-option ${selectedCorrection === 'GÂY HIỂU LẦM' ? 'selected' : ''}`}
                onClick={() => setSelectedCorrection('GÂY HIỂU LẦM')}
              >
                <AlertCircle size={20} />
                <span>MISLEADING</span>
              </button>
            </div>
            <div className="correction-notes-section">
              <label htmlFor="correction-notes">Notes (optional):</label>
              <textarea
                id="correction-notes"
                className="correction-notes-input"
                value={correctionNotes}
                onChange={(e) => setCorrectionNotes(e.target.value)}
                placeholder="Enter your notes..."
                rows="3"
              />
            </div>
            <div className="correction-dialog-actions">
              <button
                className="correction-dialog-cancel"
                onClick={() => {
                  setShowCorrectionDialog(false);
                  setSelectedCorrection('');
                  setCorrectionNotes('');
                }}
              >
                Cancel
              </button>
              <button
                className="correction-dialog-submit"
                onClick={handleSubmitCorrection}
              >
                Submit feedback
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal đăng nhập / đăng ký */}
      <AuthModal
        isOpen={showAuthModal}
        onClose={() => setShowAuthModal(false)}
        onAuthSuccess={(firebaseUser) => setUser(firebaseUser)}
      />
    </div>
  );
}

export default App;
