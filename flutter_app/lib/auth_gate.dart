// Biometric (or device PIN/pattern) lock: required on launch and whenever the app returns from the
// background, when enabled in Settings. There is deliberately no separate "can this device even do this"
// pre-check anymore - an earlier version had one (canCheckBiometrics / isDeviceSupported), and it silently
// unlocked the app before a real authentication attempt was ever made on some devices, defeating the whole
// feature. The actual authenticate() call is now the only source of truth: if it reports the device genuinely
// has nothing configured, this unlocks; for anything else, it stays locked and the person can always tap
// "Turn off app lock" below - that never depends on authenticate() succeeding or even returning at all.
import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';
import 'prefs.dart';
import 'theme.dart';

class AuthGate extends StatefulWidget {
  final Widget child;
  const AuthGate({super.key, required this.child});
  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> with WidgetsBindingObserver {
  final _auth = LocalAuthentication();
  // Starts locked synchronously (no first-frame flash of real content) whenever the setting is on.
  late bool _locked = LocalPrefs.I.biometricLock;
  bool _checking = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Wait for the first frame before showing a native biometric prompt: asking too early, before the
    // Activity/window is fully attached, is a real, documented cause of a "UI unavailable" failure on
    // Android - this is what most likely caused the uiUnavailable error seen previously.
    WidgetsBinding.instance.addPostFrameCallback((_) => _onForeground());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused && LocalPrefs.I.biometricLock) {
      setState(() {
        _locked = true; // the next time the app is foregrounded, it must be unlocked again
        _error = null;
      });
    } else if (state == AppLifecycleState.resumed) {
      _onForeground();
    }
  }

  Future<void> _onForeground() async {
    if (!LocalPrefs.I.biometricLock) {
      if (_locked) setState(() => _locked = false);
      return;
    }
    if (!_locked && mounted) setState(() => _locked = true);
    await _tryAuth();
  }

  Future<void> _tryAuth() async {
    if (_checking) return;
    setState(() {
      _checking = true;
      _error = null;
    });
    var ok = false;
    String? err;
    try {
      ok = await _auth.authenticate(
        localizedReason: 'Unlock Trade Companion',
        biometricOnly: false, // allow device PIN/pattern as a fallback
        persistAcrossBackgrounding: true,
      );
    } on LocalAuthException catch (e) {
      switch (e.code) {
        case LocalAuthExceptionCode.noBiometricHardware:
        case LocalAuthExceptionCode.noBiometricsEnrolled:
          // The device genuinely has nothing set up (no fingerprint/Face ID/PIN at all) - the only case
          // that unlocks automatically, matching what Settings already tells you about this toggle.
          ok = true;
          break;
        case LocalAuthExceptionCode.temporaryLockout:
          err = 'Too many attempts. Try again shortly, or use your device PIN.';
          break;
        case LocalAuthExceptionCode.biometricLockout:
          err = 'Locked out. Use your device PIN/pattern to unlock the phone first.';
          break;
        default:
          // Anything else, including uiUnavailable: stay locked and show why, rather than silently letting
          // anyone in - the "Turn off app lock" button is the deliberate, visible way out, not this.
          err = 'Could not authenticate (${e.code}). Try again, or turn off app lock below.';
      }
    } catch (e) {
      err = 'Could not authenticate: $e';
    }
    if (!mounted) return;
    setState(() {
      _checking = false;
      _error = err;
      if (ok) _locked = false;
    });
  }

  Future<void> _disableLock() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Turn off app lock?'),
        content: const Text('The app will open without authentication from now on, until you turn this back '
            'on in Settings > Security.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Turn off')),
        ],
      ),
    );
    if (ok == true) {
      await LocalPrefs.I.setBiometricLock(false);
      if (mounted) setState(() => _locked = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_locked) return widget.child;
    final p = context.pal;
    return Scaffold(
      backgroundColor: p.bg,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.lock_outline, size: 56, color: p.muted),
              const SizedBox(height: 16),
              const Text('Trade Companion is locked', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Text('Authenticate to view your trades and balances.', textAlign: TextAlign.center, style: TextStyle(color: p.muted)),
              if (_error != null)
                Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, textAlign: TextAlign.center, style: TextStyle(color: p.loss, fontSize: 12.5))),
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: _checking ? null : _tryAuth,
                icon: _checking
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.fingerprint),
                label: Text(_checking ? 'Checking...' : 'Unlock'),
              ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: _disableLock,
                child: Text('Trouble unlocking? Turn off app lock', style: TextStyle(color: p.muted, fontSize: 12.5)),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
