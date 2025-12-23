import React, { useState } from 'react';
import { X } from 'lucide-react';
import { auth } from './firebase';
import {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  updateProfile,
} from 'firebase/auth';
import './App.css';

const AuthModal = ({ isOpen, onClose, onAuthSuccess }) => {
  const [mode, setMode] = useState('login'); // 'login' | 'signup'
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const resetForm = () => {
    setEmail('');
    setUsername('');
    setPassword('');
    setConfirmPassword('');
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

    const normalizedEmail = email.trim();
    const normalizedUsername = username.trim();

    if (!normalizedEmail || !password) {
      setError('Please enter email and password.');
      return;
    }

    if (mode === 'signup' && !normalizedUsername) {
      setError('Please enter a username.');
      return;
    }

    if (mode === 'signup' && !confirmPassword) {
      setError('Please confirm your password.');
      return;
    }

    if (mode === 'signup' && password !== confirmPassword) {
      setError('Password confirmation does not match.');
      return;
    }

    setLoading(true);
    try {
      let userCredential;
      if (mode === 'login') {
        userCredential = await signInWithEmailAndPassword(auth, normalizedEmail, password);
      } else {
        userCredential = await createUserWithEmailAndPassword(auth, normalizedEmail, password);

        // Lưu username vào displayName để hiển thị trên nút tài khoản
        if (normalizedUsername) {
          try {
            await updateProfile(userCredential.user, { displayName: normalizedUsername });
          } catch (profileErr) {
            console.error('Failed to update profile:', profileErr);
          }
        }
      }

      onAuthSuccess && onAuthSuccess(userCredential.user);
      resetForm();
      onClose && onClose();
    } catch (err) {
      let message = 'Sign in/sign up failed. Please try again.';
      if (err.code === 'auth/email-already-in-use') {
        message = 'This email is already in use.';
      } else if (err.code === 'auth/invalid-email') {
        message = 'Invalid email.';
      } else if (err.code === 'auth/weak-password') {
        message = 'Weak password (minimum 6 characters).';
      } else if (err.code === 'auth/user-not-found') {
        message = 'Account not found. Please sign up.';
      } else if (err.code === 'auth/wrong-password') {
        message = 'Incorrect password.';
      }
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-modal-overlay">
      <div className="auth-modal">
        <button className="auth-modal-close" onClick={handleClose}>
          <X size={18} />
        </button>
        <h2 className="auth-modal-title">
          {mode === 'login' ? 'Sign in' : 'Create account'}
        </h2>
        <p className="auth-modal-subtitle">
          {mode === 'login'
            ? 'Sign in to view and sync your search history.'
            : 'Create an account to save search history per user.'}
        </p>

        <form className="auth-modal-form" onSubmit={handleSubmit}>
          <label className="auth-modal-label">
            Email
            <input
              type="email"
              className="auth-modal-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="your@email.com"
              autoComplete="email"
            />
          </label>

          {mode === 'signup' && (
            <label className="auth-modal-label">
              Username
              <input
                type="text"
                className="auth-modal-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Display name"
                autoComplete="username"
              />
            </label>
          )}

          <label className="auth-modal-label">
            Password
            <input
              type="password"
              className="auth-modal-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </label>

          {mode === 'signup' && (
            <label className="auth-modal-label">
              Confirm password
              <input
                type="password"
                className="auth-modal-input"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter password"
                autoComplete="new-password"
              />
            </label>
          )}

          {error && <div className="auth-modal-error">{error}</div>}

          <button
            type="submit"
            className="auth-modal-submit"
            disabled={loading}
          >
            {loading
              ? 'Processing...'
              : mode === 'login'
                ? 'Sign in'
                : 'Sign up'}
          </button>
        </form>

        <div className="auth-modal-footer">
          {mode === 'login' ? (
            <span>
              No account yet?{' '}
              <button
                type="button"
                className="auth-modal-link"
                onClick={() => {
                  setMode('signup');
                  setConfirmPassword('');
                  setPassword('');
                  setError('');
                }}
              >
                Sign up
              </button>
            </span>
          ) : (
            <span>
              Already have an account?{' '}
              <button
                type="button"
                className="auth-modal-link"
                onClick={() => {
                  setMode('login');
                  setConfirmPassword('');
                  setPassword('');
                  setError('');
                }}
              >
                Sign in
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export default AuthModal;


