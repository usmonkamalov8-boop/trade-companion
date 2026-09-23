// Biometric (or device PIN/pattern) lock: required on launch and whenever the app returns from the
// background, when enabled in Settings. If the device has no usable authentication at all, the gate
// gets out of the way entirely rather than locking the person out of their own app.
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
  // Starts locked synchronously (no first-frame flash of real content) whenever the setting is on - the async
  // capability check below can only ever relax this to unlocked, never the other way round.
  late bool _locked = LocalPrefs.I.biometricLock;
  bool _checking = false;
  bool _bootChecked = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _onForeground();
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
    if (!_bootChecked) {
      // Cold start: drop the lock only if the device turns out to have no usable authentication at all -
      // an app with no usable lock screen should never become permanently unreachable. _locked is already
      // true from the field initializer above, so there is nothing to flash before this check finishes.
      _bootChecked = true;
      var can = false;
      try {
        can = await _auth.canCheckBiometrics || await _auth.isDeviceSupported();
      } catch (_) {}
      if (!can) {
        if (mounted) setState(() => _locked = false);
        return;
      }
    }
    if (_locked) await _tryAuth();
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
        biometricOnly: false, // allow device PIN/pattern as a fallback - never a hard biometric-only lockout
        persistAcrossBackgrounding: true,
      );
    } on LocalAuthException catch (e) {
      err = switch (e.code) {
        LocalAuthExceptionCode.noBiometricHardware => null, // no hardware: just let them in
        LocalAuthExceptionCode.notEnrolled => null, // nothing enrolled: just let them in
        LocalAuthExceptionCode.temporaryLockout => 'Too many attempts. Try again shortly, or use your device PIN.',
        LocalAuthExceptionCode.biometricLockout => 'Locked out. Use your device PIN/pattern to unlock the phone first.',
        _ => 'Could not authenticate: ${e.code}',
      };
      ok = ok || err == null; // no hardware / nothing enrolled -> treat as an unsupported device, not a failure
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
            ]),
          ),
        ),
      ),
    );
  }
}
