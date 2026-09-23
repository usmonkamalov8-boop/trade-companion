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
      // Only the two "you do have a real lock, you just can't get past it yet" cases stay locked - those
      // are genuinely worth showing and retrying. Everything else (including uiUnavailable, and anything
      // this list doesn't name) fails OPEN: this lock is a client-side convenience, not the real security
      // boundary (that's the API token), so a platform/device quirk we didn't anticipate must never be able
      // to brick access to someone's own account. See also the manual "Turn off app lock" escape below,
      // which works even if authenticate() never returns a recognizable result at all.
      switch (e.code) {
        case LocalAuthExceptionCode.temporaryLockout:
          err = 'Too many attempts. Try again shortly, or use your device PIN.';
          break;
        case LocalAuthExceptionCode.biometricLockout:
          err = 'Locked out. Use your device PIN/pattern to unlock the phone first.';
          break;
        default:
          ok = true;
      }
    } catch (e) {
      ok = true; // an error type we didn't even expect: same reasoning, fail open rather than lock hard
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
                // Always enabled, even mid-check: this is the guaranteed way out, so it must not depend on
                // authenticate() ever actually returning.
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
