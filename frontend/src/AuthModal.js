import React, { useState } from 'react';
import { X } from 'lucide-react';
import { auth } from './firebase';
import {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
} from 'firebase/auth';
import './App.css';

const AuthModal = ({ isOpen, onClose, onAuthSuccess }) => {
  const [mode, setMode] = useState('login'); // 'login' | 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const resetForm = () => {
    setEmail('');
    setPassword('');
    setError('');
  };

  const handleClose = () => {
    if (loading) return;
    resetForm();
    onClose && onClose();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!email || !password) {
      setError('Vui lòng nhập email và mật khẩu.');
      return;
    }

    setLoading(true);
    try {
      let userCredential;
      if (mode === 'login') {
        userCredential = await signInWithEmailAndPassword(auth, email, password);
      } else {
        userCredential = await createUserWithEmailAndPassword(auth, email, password);
      }

      onAuthSuccess && onAuthSuccess(userCredential.user);
      resetForm();
      onClose && onClose();
    } catch (err) {
      let message = 'Đăng nhập/đăng ký thất bại. Vui lòng thử lại.';
      if (err.code === 'auth/email-already-in-use') {
        message = 'Email này đã được sử dụng.';
      } else if (err.code === 'auth/invalid-email') {
        message = 'Email không hợp lệ.';
      } else if (err.code === 'auth/weak-password') {
        message = 'Mật khẩu quá yếu (ít nhất 6 ký tự).';
      } else if (err.code === 'auth/user-not-found') {
        message = 'Không tìm thấy tài khoản. Vui lòng đăng ký.';
      } else if (err.code === 'auth/wrong-password') {
        message = 'Mật khẩu không chính xác.';
      }
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-modal-overlay" onClick={handleClose}>
      <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
        <button className="auth-modal-close" onClick={handleClose}>
          <X size={18} />
        </button>
        <h2 className="auth-modal-title">
          {mode === 'login' ? 'Đăng nhập' : 'Đăng ký tài khoản'}
        </h2>
        <p className="auth-modal-subtitle">
          {mode === 'login'
            ? 'Đăng nhập để xem và đồng bộ lịch sử tra cứu của bạn.'
            : 'Tạo tài khoản để lưu lịch sử tra cứu theo từng người dùng.'}
        </p>

        <form className="auth-modal-form" onSubmit={handleSubmit}>
          <label className="auth-modal-label">
            Email
            <input
              type="email"
              className="auth-modal-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </label>
          <label className="auth-modal-label">
            Mật khẩu
            <input
              type="password"
              className="auth-modal-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Ít nhất 6 ký tự"
            />
          </label>

          {error && <div className="auth-modal-error">{error}</div>}

          <button
            type="submit"
            className="auth-modal-submit"
            disabled={loading}
          >
            {loading
              ? 'Đang xử lý...'
              : mode === 'login'
                ? 'Đăng nhập'
                : 'Đăng ký'}
          </button>
        </form>

        <div className="auth-modal-footer">
          {mode === 'login' ? (
            <span>
              Chưa có tài khoản?{' '}
              <button
                type="button"
                className="auth-modal-link"
                onClick={() => {
                  setMode('signup');
                  setError('');
                }}
              >
                Đăng ký ngay
              </button>
            </span>
          ) : (
            <span>
              Đã có tài khoản?{' '}
              <button
                type="button"
                className="auth-modal-link"
                onClick={() => {
                  setMode('login');
                  setError('');
                }}
              >
                Đăng nhập
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export default AuthModal;


