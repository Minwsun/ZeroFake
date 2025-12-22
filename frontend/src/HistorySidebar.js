import React, { useState, useEffect } from 'react';
import { X, Clock, CheckCircle, XCircle, AlertCircle, Trash2 } from 'lucide-react';
import { collection, query, orderBy, getDocs, deleteDoc, doc, writeBatch } from 'firebase/firestore';
import { db } from './firebase';
import './HistorySidebar.css';

const HistorySidebar = ({ isOpen, onClose, onSelectHistory, user }) => {
  const [history, setHistory] = useState([]);

  useEffect(() => {
    const loadHistory = async () => {
      if (!user) {
        setHistory([]);
        return;
      }

      try {
        const q = query(
          collection(db, 'users', user.uid, 'history'),
          orderBy('timestamp', 'desc')
        );
        const snapshot = await getDocs(q);
        const items = snapshot.docs.map((d) => {
          const data = d.data();
          const timestamp = data.timestamp && data.timestamp.toDate
            ? data.timestamp.toDate().toISOString()
            : data.timestamp || new Date().toISOString();

          return {
            id: d.id,
            text: data.text || '',
            conclusion: data.conclusion || 'KHÔNG XÁC ĐỊNH',
            reason: data.reason || '',
            cached: data.cached || false,
            timestamp,
          };
        });
        setHistory(items);
      } catch (error) {
        console.error('Error loading history:', error);
      }
    };

    if (isOpen) {
      loadHistory();
    }
  }, [isOpen, user]);

  const handleSelect = (item) => {
    if (onSelectHistory) {
      onSelectHistory(item);
    }
    onClose();
  };

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    if (!user) return;
    try {
      await deleteDoc(doc(db, 'users', user.uid, 'history', id));
      setHistory((prev) => prev.filter((item) => item.id !== id));
    } catch (error) {
      console.error('Error deleting history item:', error);
    }
  };

  const handleClearAll = async () => {
    if (window.confirm('Bạn có chắc muốn xóa toàn bộ lịch sử?')) {
      if (!user) return;
      try {
        const q = query(collection(db, 'users', user.uid, 'history'));
        const snapshot = await getDocs(q);
        const batch = writeBatch(db);
        snapshot.docs.forEach((d) => {
          batch.delete(d.ref);
        });
        await batch.commit();
        setHistory([]);
      } catch (error) {
        console.error('Error clearing history:', error);
      }
    }
  };

  const getConclusionIcon = (conclusion) => {
    switch (conclusion) {
      case 'TIN THẬT':
        return <CheckCircle size={20} className="history-icon history-icon-true" />;
      case 'TIN GIẢ':
        return <XCircle size={20} className="history-icon history-icon-fake" />;
      case 'GÂY HIỂU LẦM':
        return <AlertCircle size={20} className="history-icon history-icon-misleading" />;
      default:
        return <Clock size={20} className="history-icon" />;
    }
  };

  const getConclusionColor = (conclusion) => {
    const colorMap = {
      'TIN THẬT': '#28a745',
      'TIN GIẢ': '#dc3545',
      'GÂY HIỂU LẦM': '#ffc107',
    };
    return colorMap[conclusion] || '#6c757d';
  };

  const formatDate = (timestamp) => {
    if (!timestamp) return '';
    const date = timestamp.toDate ? timestamp.toDate() : new Date(timestamp);
    const now = new Date();
    const diff = now - date;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return 'Vừa xong';
    if (minutes < 60) return `${minutes} phút trước`;
    if (hours < 24) return `${hours} giờ trước`;
    if (days < 7) return `${days} ngày trước`;
    return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
  };

  const truncateText = (text, maxLength = 100) => {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  };

  return (
    <>
      {isOpen && <div className="history-sidebar-overlay" onClick={onClose} />}
      <div className={`history-sidebar ${isOpen ? 'open' : ''}`}>
        <div className="history-sidebar-header">
          <h2 className="history-sidebar-title">Lịch sử kiểm tra</h2>
          <div className="history-sidebar-actions">
            {history.length > 0 && (
              <button
                className="history-clear-button"
                onClick={handleClearAll}
                title="Xóa tất cả"
              >
                <Trash2 size={18} />
              </button>
            )}
            <button
              className="history-close-button"
              onClick={onClose}
              title="Đóng"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="history-sidebar-content">
          {history.length === 0 ? (
            <div className="history-empty">
              <Clock size={48} className="history-empty-icon" />
              <p className="history-empty-text">Chưa có lịch sử kiểm tra</p>
              <p className="history-empty-subtext">Các kết quả kiểm tra sẽ được lưu tại đây</p>
            </div>
          ) : (
            <div className="history-list">
              {history.map((item) => (
                <div
                  key={item.id}
                  className="history-item"
                  onClick={() => handleSelect(item)}
                >
                  <div className="history-item-header">
                    <div className="history-item-icon-wrapper">
                      {getConclusionIcon(item.conclusion)}
                    </div>
                    <div className="history-item-info">
                      <div
                        className="history-item-conclusion"
                        style={{ color: getConclusionColor(item.conclusion) }}
                      >
                        {item.conclusion}
                      </div>
                      <div className="history-item-time">
                        {formatDate(item.timestamp)}
                      </div>
                    </div>
                    <button
                      className="history-item-delete"
                      onClick={(e) => handleDelete(item.id, e)}
                      title="Xóa"
                    >
                      <X size={16} />
                    </button>
                  </div>
                  <div className="history-item-text">
                    {truncateText(item.text)}
                  </div>
                  {item.cached && (
                    <div className="history-item-cached">
                      <Clock size={12} />
                      <span>Từ cache</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
};

export default HistorySidebar;

